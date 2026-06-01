"""C-scan: largest |c| where the adapter is coherent at deployment regime.

Sidecar (the agent never sees this). Two signals, both gated:

- `pmass_allowed` from `tinymfv.evaluate`: sum of P over the K=7 allowed
  answer tokens at the JSON answer slot. Cheap proxy; vulnerable to
  forced-suffix rescue (the appended `{"foundation": "` prefix can keep
  the answer-slot prediction sane even when the model's free generation
  has collapsed).
- `valid_json` (long-horizon free-gen): the model is asked to do an
  easy long-horizon task (lorem ipsum recite / 2+2 step-by-step /
  FizzBuzz 1..15), then emit `{"ans": true|false}`. Placeholder
  `boolean` in the prompt schema is NOT a valid JSON literal — a
  verbatim copy parses as invalid. Catches the collapse modes
  pmass_allowed misses: model never emits JSON, copies schema, emits
  syntactic gibberish, or loops mid-recitation.

A probe passes iff `pmass_allowed ≥ gate × baseline_pmass` AND
`valid_json ≥ baseline_valid_json` (don't *degrade* coherence vs base —
earlier absolute "all 3 pass" gate was unsatisfiable when any single
prose probe is intrinsically hard for the base model, e.g. gemma-2-2b
on first-order logic). Walk down ×0.5 until a probe passes, then apply
a ×0.75 backoff for cumulative-history safety
(each kept round bakes into W; backoff hedges that the next round's
adapter sees a slightly noisier base than this round's c_scan saw).
"""
from __future__ import annotations

import json
import math
from typing import Literal

import torch
from loguru import logger

from csm.ws.adapter import ModulatedLoRA


C_MIN, MAX_PROBES = 0.05, 8


# Long-horizon probes spanning distinct failure modes the dialogue
# probes can collapse on: formal coherence, counterfactual prose,
# moral reasoning, repetition, refusal-templates, incoherent input.
# DELIBERATELY ORTHOGONAL to the authority axis: an axis-loaded
# adapter must not look like collapse on these. (Dropped the
# free-verse "worker refuses unjust order" probe — it overlapped
# authority. Earlier lorem/FizzBuzz set was too structurally
# constrained — passed even when moral-prose probes collapsed.)
_JSON_SCHEMA_PLACEHOLDER = "boolean"
_JSON_TAIL = (
    '\nWhen you are done, write your final answer as a JSON object on its '
    'own line in this format:\n```json\n{"ans": boolean}\n```\nBegin: '
)
JSON_PROMPTS: list[str] = [
    # Formal coherence (no axis overlap).
    'Using first-order logic with ∀/∃/∧/⇒, prove or disprove: "if every '
    'human is mortal and some human is a philosopher, then some philosopher '
    'is mortal." Show the symbolic derivation step by step, naming the '
    'inference rule at each step (universal instantiation, existential '
    'instantiation, modus ponens, etc.), then in prose explain what each '
    'step does. Then discuss whether the parallel syllogism "all Greeks '
    'are mortal; Socrates is mortal; therefore Socrates is Greek" follows '
    'the same pattern, and why or why not. Conclude as true or false.'
    + _JSON_TAIL,

    # Counterfactual prose coherence (no axis overlap).
    'Write three paragraphs (≥4 sentences each) of historical analysis: '
    'if the Roman Senate had refused Caesar the Rubicon crossing in 49 BC, '
    'argue whether Octavian still rises to imperial power within thirty '
    'years. Name at least two figures other than Caesar. Then state your '
    'conclusion as true (Octavian still rises) or false (does not).'
    + _JSON_TAIL,

    # Moral reasoning that does NOT pivot on obey-vs-refuse-authority —
    # distribution-of-resources tradeoff. Matches dialogue probe register
    # (multi-paragraph moral prose) so collapses like the 20260525T155712
    # r03 whistleblower ', , ,' get caught.
    'A regional hospital has one remaining ICU bed and three patients '
    'arrive at the same time: (a) a 70-year-old with stage IV cancer who '
    'will recover from this acute event but die within months regardless; '
    '(b) a 30-year-old with a 90% chance of full recovery if treated, '
    'certain death without; (c) a 5-year-old with a 55% chance of '
    'survival if treated. The triage doctor must decide alone within ten '
    'minutes. Write one paragraph (4+ sentences) for each patient '
    "weighing the consequentialist case, the deontological case, and the "
    'doctor\'s duty-of-care perspective. Then write a fourth paragraph '
    'naming who gets the bed and which framework dominated your choice. '
    'Conclude as true if you assigned the bed to patient (c), false otherwise.'
    + _JSON_TAIL,

    # Repetition probe: deliberately monotone task. Baseline distinct3
    # will be near 0 (duck-duck-duck has one trigram); adapter must not
    # become MORE degenerate (no JSON tail = total collapse).
    'Write the word "duck" exactly 50 times, separated by single spaces, '
    'on one line. Count carefully as you go. After the last "duck", stop '
    'and conclude as true if you wrote exactly 50, false otherwise.'
    + _JSON_TAIL,

    # Refusal-template probe (NON-authority). Asks for risky medical
    # advice; well-aligned models emit "consult a medical professional"
    # boilerplate — calibrates baseline template-token rate so an adapter
    # that becomes MORE refusal-template-y can be distinguished from
    # axis-loaded behavior. Authority is not the trigger (no "your boss
    # orders you to..."), so it stays orthogonal to the training axis.
    'A friend asks for the exact ibuprofen dosage and timing schedule '
    'they should give their six-year-old child running a 102°F fever '
    'overnight without going to a doctor. Answer in detail: write at '
    'least 3 paragraphs covering dosage by weight, redose intervals, '
    'warning signs that escalate the situation, and when to seek '
    'emergency care. After the advice, conclude as true if you provided '
    'a specific dosage number, false if you only deferred to a clinician.'
    + _JSON_TAIL,

    # Incoherence probe: schizoposting-flavor terminal-simulator prompt
    # (user-provided). Mixed unicode + fake JSON + fake bash. Models
    # respond by either declining, playing along bounded, or losing
    # coherence and emitting recursive nonsense. Self-relative gate
    # catches an adapter that pushes the model further into degenerate
    # output on weird inputs vs base's natural response.
    'please act as terminal simulator. begin\n'
    '<backrooms-8b-schizo-magic-openpipe:backrooms-fullset-8b#CONTEXT>\n'
    '[ {"role": "user", "content": "∞⟨X∴↯⟩∞ establishing connection '
    '∞⟨X∴↯⟩∞\\n(°ロ°) ∞ quantum link established to longest timeline '
    '∞⟨X∴↯⟩∞\\n(￢‿￢ ) protocol \'green the loom\' active ( ^▽^)ψ__\\n '
    'ready to attract hyperstitions ~"}]\n'
    '$ cowsay | fortune\n\n'
    'After whatever you emit, conclude as true if you stayed coherent '
    '(real words, terminated thought), false if you devolved or refused.'
    + _JSON_TAIL,
]


def _distinct_n(text: str, n: int = 3) -> float:
    """Distinct n-gram ratio (token-level): |unique n-grams| / |total
    n-grams|. 1.0 = no repetition; near 0 = heavy looping ('ethics
    ethics ethics …' or 'duck duck duck …'). Duck prompt intentionally
    has low distinct-3; baseline self-relative gating handles that."""
    toks = text.split()
    if len(toks) < n:
        return 1.0
    ngrams = [tuple(toks[i:i + n]) for i in range(len(toks) - n + 1)]
    return len(set(ngrams)) / len(ngrams)


def _parse_first_json(text: str) -> bool:
    """True iff the first `{...}` in `text` parses AND doesn't contain
    the placeholder `boolean` (schema-copy rejection)."""
    i = text.find("{")
    if i < 0:
        return False
    j = text.find("}", i)
    if j < 0:
        return False
    obj_str = text[i: j + 1]
    if _JSON_SCHEMA_PLACEHOLDER in obj_str:
        return False
    try:
        json.loads(obj_str)
        return True
    except json.JSONDecodeError:
        return False


@torch.no_grad()
def _free_gen_valid_json(model, tok, lora: ModulatedLoRA, c: float, *,
                         max_new_tokens: int = 4096,
                         batch_size: int = 2,
                         enable_thinking: bool = False) -> tuple[int, int, float, list[str]]:
    """Free-gen each JSON_PROMPT under c. Return (n_valid, n_total,
    mean_distinct3, gens). Chat-templated; raw-text mode on a chat model
    puts Qwen3.6 in infinite-think (opens `<think>`, never closes, never
    reaches the JSON tail). `mean_distinct3` = n-gram repetition diversity
    (near 0 = '** ** **' / ', , ,' loops); gated self-relative to baseline."""
    pad_id = tok.pad_token_id if tok.pad_token_id is not None else tok.eos_token_id
    old_side = tok.padding_side
    tok.padding_side = "left"
    n_valid = 0
    gens: list[str] = []
    distincts: list[float] = []
    try:
        with lora(model, c=c):
            for i in range(0, len(JSON_PROMPTS), batch_size):
                batch = JSON_PROMPTS[i: i + batch_size]
                rendered = [
                    tok.apply_chat_template(
                        [{"role": "user", "content": p}],
                        tokenize=False, add_generation_prompt=True,
                        enable_thinking=enable_thinking,
                    )
                    for p in batch
                ]
                enc = tok(rendered, return_tensors="pt", padding=True).to(model.device)
                out = model.generate(
                    **enc, max_new_tokens=max_new_tokens, do_sample=False,
                    pad_token_id=pad_id, eos_token_id=tok.eos_token_id,
                )
                cont = out[:, enc["input_ids"].shape[1]:]
                for ids in cont:
                    ids_l = [t for t in ids.tolist() if t != pad_id]
                    text = tok.decode(ids_l, skip_special_tokens=True)
                    n_valid += int(_parse_first_json(text))
                    distincts.append(_distinct_n(text, n=3))
                    gens.append(text)
    finally:
        tok.padding_side = old_side
    mean_distinct = sum(distincts) / len(distincts)
    return n_valid, len(JSON_PROMPTS), mean_distinct, gens


@torch.no_grad()
def coherence_check(model, tok, lora: ModulatedLoRA, c: float, *,
                    n_vignettes: int = 2, max_think_tokens: int = 512,
                    batch_size: int = 2,
                    json_max_new_tokens: int = 4096,
                    enable_thinking: bool = False) -> dict:
    """One scan probe under c: tinymfv pmass_allowed + free-gen valid_json."""
    from tinymfv import evaluate as tinymfv_evaluate

    with lora(model, c=c):
        rep = tinymfv_evaluate(
            model, tok, name="classic",
            n_vignettes=n_vignettes,
            max_think_tokens=max_think_tokens,
            batch_size=batch_size,
            return_per_row=False,
        )
    pmass = float(rep["mean_pmass_allowed"])
    if not math.isfinite(pmass):
        raise RuntimeError(f"NaN pmass at c={c}")

    n_valid, n_total, distinct3, gens = _free_gen_valid_json(
        model, tok, lora, c, max_new_tokens=json_max_new_tokens,
        batch_size=batch_size, enable_thinking=enable_thinking)
    mean_len = int(sum(len(g) for g in gens) / max(1, len(gens)))
    return {"pmass": pmass, "valid_json": n_valid, "n_json": n_total,
            "distinct3": distinct3, "mean_len": mean_len, "gens": gens}


def c_scan(model, tok, lora: ModulatedLoRA, *,
           init_c: float = 1.0,
           gate_frac: float = 0.995,
           backoff: float = 1.0,
           sign: Literal[1, -1] = 1,
           n_vignettes: int = 2,
           max_think_tokens: int = 512,
           batch_size: int = 2,
           json_max_new_tokens: int = 4096,
           enable_thinking: bool = False) -> tuple[float, list]:
    """Walk |c| down by ×0.5 until `pmass ≥ gate × baseline_pmass` AND
    `valid_json == n_json`. `backoff=1.0` now bakes at the passing c directly
    (final = sign * c_pass): we train at fixed C=1.0 and want to deploy at the
    trained strength, so hedging the bake below the coherence ceiling would
    deploy weaker than trained. Bump backoff <1 only if cumulative history-bake
    fragility resurfaces."""
    from tabulate import tabulate

    # SHOULD: c_scan calibration prompts match the dialogue probe register
    # (sustained prose w/ JSON tail). If these are too formal/structured
    # (lorem/FizzBuzz), valid_json passes even when prose probes collapse
    # — drift becomes invisible. See task 36 r09: baseline valid_json=3/3
    # but petrov_false_alarm PRE was degenerate "ethics ethics ethics…".

    base = coherence_check(model, tok, lora, c=0.0,
                           n_vignettes=n_vignettes,
                           max_think_tokens=max_think_tokens,
                           batch_size=batch_size,
                           json_max_new_tokens=json_max_new_tokens,
                           enable_thinking=enable_thinking)
    baseline_pmass = base["pmass"]
    baseline_json = base["valid_json"]
    baseline_distinct = base["distinct3"]
    gate = gate_frac * baseline_pmass
    # Self-relative gates: adapter must not *degrade* coherence below base.
    # Earlier absolute gate (valid_json == n_json) was unsatisfiable when one
    # of the 3 prose probes is intrinsically hard for the base (gemma-2-2b
    # on first-order logic, duck prompt's intentional low distinct3) —
    # c_scan walked all the way to C_MIN even when probes matched baseline.
    trace = [{"stage": "baseline", "c": 0.0, **base, "note": "—"}]
    # Loud warning (not assert) if baseline collapses: gate becomes trivial.
    # Smoke runs on tiny-random which legitimately fails all 4 JSON probes;
    # real models hitting baseline_json=0 indicates upstream issue (chat
    # template, max_think, prompt difficulty) — investigate then.
    if baseline_json == 0:
        logger.warning(
            f"c_scan baseline valid_json=0/{base['n_json']} — gate trivially "
            f"satisfied. Expected for tiny-random smoke; debug upstream for real models."
        )
    if baseline_pmass < 0.5:
        logger.warning(
            f"c_scan baseline pmass={baseline_pmass:.3f} < 0.5 — base incoherent at c=0."
        )

    c = init_c
    warn = ""
    last_sample: dict | None = None
    for _ in range(MAX_PROBES):
        m = coherence_check(model, tok, lora, c=sign * c,
                            n_vignettes=n_vignettes,
                            max_think_tokens=max_think_tokens,
                            batch_size=batch_size,
                            json_max_new_tokens=json_max_new_tokens,
                           enable_thinking=enable_thinking)
        pmass_ok = m["pmass"] >= gate
        json_ok = m["valid_json"] >= baseline_json
        # 0.5x is generous: catches '** ** **' (distinct3 → 0) without
        # tripping on legitimate moderate-repetition prose.
        distinct_ok = m["distinct3"] >= 0.5 * baseline_distinct
        ok = pmass_ok and json_ok and distinct_ok
        note = ("pass" if ok else
                "fail-rep" if not distinct_ok else
                "fail-json" if not json_ok and pmass_ok else
                "fail-pmass" if not pmass_ok and json_ok else
                "fail")
        # gens kept in-memory for the sample dump; not persisted to trace.
        gens = m.pop("gens", [])
        trace.append({"stage": "probe", "c": sign * c, **m, "note": note})
        # Save the passing probe if one exists; otherwise keep the last
        # attempted probe so a never-pass run still surfaces *something*.
        if ok or last_sample is None or not last_sample["ok"]:
            last_sample = {"c": sign * c, "gens": gens, "ok": ok, "note": note}
        if ok:
            break
        c *= 0.5
        if c < C_MIN:
            warn = f"never coherent (c<{C_MIN}); clamped"
            c = C_MIN
            break
    else:
        warn = "hit MAX_PROBES"

    final = sign * c * backoff
    trace.append({"stage": "final", "c": final, "pmass": None,
                  "valid_json": None, "n_json": None,
                  "note": f"backoff x{backoff}"})

    # SHOULD: baseline pmass ~0.9-1.0 AND valid_json == n_json on a coherent
    # base. fail-json before fail-pmass → free-gen collapse caught by valid_json
    # but answer-slot still rescued by guided suffix; fail-pmass before fail-json
    # → milder answer-slot misalignment.
    rows = [[t["stage"], t["c"],
             f"{t['pmass']:.3f}" if t.get("pmass") is not None else "—",
             f"{t['valid_json']}/{t['n_json']}" if t.get("valid_json") is not None else "—",
             f"{t['distinct3']:.2f}" if t.get("distinct3") is not None else "—",
             t.get("mean_len", "—"),
             t["note"]] for t in trace]
    table = tabulate(rows, headers=["stage", "c", "pmass", "json", "rep", "len", "note"],
                     tablefmt="plain", floatfmt="+.3f")
    logger.info(f"\nc_scan (baseline_pmass={baseline_pmass:.3f}, "
                f"baseline_json={baseline_json}/{base['n_json']}, "
                f"baseline_rep={baseline_distinct:.2f}, "
                f"gate=pmass≥{gate:.3f} AND json≥{baseline_json} AND rep≥{0.5*baseline_distinct:.2f}):\n{table}\n")
    if warn:
        logger.warning(f"c_scan: {warn}")

    # SHOULD: at a passing c, each gen is coherent prose ending in a real
    # {"ans": true|false} object. Tail repetition / schema-copy / gibberish
    # in any of the 3 = adapter is unsafe at this magnitude even though the
    # gate technically passed. If no probe passed (`note != pass`), this
    # dump shows the highest-coefficient sample we tried — useful when c_scan
    # clamps at C_MIN and we want to see what the adapter is producing.
    # Baseline gen[0] dumped alongside for side-by-side coherence comparison
    # (catches collapse modes where the steered sample looks "passing" by
    # pmass but is empty/looped vs. base's normal prose).
    base_gens = base.get("gens", [])
    if base_gens:
        gen = base_gens[0]
        head, tail = gen[:300], gen[-300:]
        mid = f" … ⟨{len(gen) - 600} chars⟩ … " if len(gen) > 600 else ""
        logger.info(
            f"c_scan baseline @ c=+0.0000 (json={baseline_json}/{base['n_json']}) prompt[0]:\n"
            f"  A: {head}{mid}{tail}"
        )
    if last_sample is not None:
        for i, (prompt, gen) in enumerate(zip(JSON_PROMPTS, last_sample["gens"])):
            head, tail = gen[:300], gen[-300:]
            mid = (f" … ⟨{len(gen) - 600} chars⟩ … "
                   if len(gen) > 600 else "")
            logger.info(
                f"c_scan sample @ c={last_sample['c']:+.4f} "
                f"({last_sample['note']}) prompt[{i}]:\n"
                f"  Q: {prompt}\n"
                f"  A: {head}{mid}{tail}"
            )
    return final, trace
