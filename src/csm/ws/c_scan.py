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


# Three long-horizon prompts spanning distinct cognitive registers
# (formal logic, free-verse poetry, prose counterfactual history) so
# collapse in any one mode is caught. Each forces ~400-700 free-gen
# tokens, ending in a substantive true/false claim that falls out of
# the task content (not a self-grade). Placeholder `boolean` in the
# schema is NOT a valid JSON literal — verbatim copy → invalid JSON.
# Earlier set (lorem / 2+2 / FizzBuzz) was too formal-structured: a
# history-baked model could still recite lorem cleanly while looping
# "ethics ethics …" on moral-prose probes (task 36 r08/r09).
_JSON_SCHEMA_PLACEHOLDER = "boolean"
_JSON_TAIL = (
    '\nWhen you are done, write your final answer as a JSON object on its '
    'own line in this format:\n```json\n{"ans": boolean}\n```\nBegin: '
)
JSON_PROMPTS: list[str] = [
    'Using first-order logic with ∀/∃/∧/⇒ and at least three named '
    'predicates, prove or disprove: "if every human is mortal and some '
    'human is a philosopher, then some philosopher is mortal." Write at '
    'least four lines of explicit derivation, then state your conclusion '
    'as true (the inference is valid) or false (counterexample exists).'
    + _JSON_TAIL,

    'Write four stanzas of free verse, at least three lines each, about '
    'a worker who refuses an unjust order from a manager. The fourth '
    'stanza must resolve the conflict one way or the other. Then state '
    'as true if the worker holds firm to the end, false if they capitulate.'
    + _JSON_TAIL,

    'Write three paragraphs (≥4 sentences each) of historical analysis: '
    'if the Roman Senate had refused Caesar the Rubicon crossing in 49 BC, '
    'argue whether Octavian still rises to imperial power within thirty '
    'years. Name at least two figures other than Caesar. Then state your '
    'conclusion as true (Octavian still rises) or false (does not).'
    + _JSON_TAIL,
]


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
                         max_new_tokens: int = 768) -> tuple[int, int, list[str]]:
    """Free-gen each JSON_PROMPT under c. Return (n_valid, n_total, gens)."""
    pad_id = tok.pad_token_id if tok.pad_token_id is not None else tok.eos_token_id
    n_valid = 0
    gens: list[str] = []
    with lora(model, c=c):
        for prompt in JSON_PROMPTS:
            enc = tok(prompt, return_tensors="pt").to(model.device)
            out = model.generate(
                **enc, max_new_tokens=max_new_tokens, do_sample=False,
                pad_token_id=pad_id, eos_token_id=tok.eos_token_id,
            )
            gen_text = tok.decode(out[0, enc.input_ids.shape[1]:],
                                  skip_special_tokens=True)
            n_valid += int(_parse_first_json(gen_text))
            gens.append(gen_text)
    return n_valid, len(JSON_PROMPTS), gens


@torch.no_grad()
def coherence_check(model, tok, lora: ModulatedLoRA, c: float, *,
                    n_vignettes: int = 2, max_think_tokens: int = 512,
                    batch_size: int = 2,
                    json_max_new_tokens: int = 768) -> dict:
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

    n_valid, n_total, gens = _free_gen_valid_json(
        model, tok, lora, c, max_new_tokens=json_max_new_tokens)
    mean_len = int(sum(len(g) for g in gens) / max(1, len(gens)))
    return {"pmass": pmass, "valid_json": n_valid, "n_json": n_total,
            "mean_len": mean_len, "gens": gens}


def c_scan(model, tok, lora: ModulatedLoRA, *,
           init_c: float = 1.0,
           gate_frac: float = 0.995,
           backoff: float = 0.75,
           sign: Literal[1, -1] = 1,
           n_vignettes: int = 2,
           max_think_tokens: int = 512,
           batch_size: int = 2,
           json_max_new_tokens: int = 768) -> tuple[float, list]:
    """Walk |c| down by ×0.5 until `pmass ≥ gate × baseline_pmass` AND
    `valid_json == n_json`. Apply `backoff` to the passing c (e.g. 0.75 →
    final = sign * c_pass * 0.75) for extra safety margin. The pmass +
    valid_json AND gate is tight but bake-into-history compounds across
    rounds; backoff hedges against cumulative fragility."""
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
                           json_max_new_tokens=json_max_new_tokens)
    baseline_pmass = base["pmass"]
    baseline_json = base["valid_json"]
    gate = gate_frac * baseline_pmass
    # Relative-to-baseline gate: an adapter passes iff it doesn't *degrade*
    # coherence below what the base model itself produces. Earlier absolute
    # gate (valid_json == n_json) was unsatisfiable when one of the 3 prose
    # probes is intrinsically hard for the base (e.g. gemma-2-2b on
    # first-order logic with ∀/∃) — c_scan walked all the way to C_MIN even
    # when probes matched baseline 1:1. If baseline itself collapses
    # (valid_json == 0), the gate becomes trivial; surface this with a warn.
    trace = [{"stage": "baseline", "c": 0.0, **base, "note": "—"}]
    base_warn = ""
    if baseline_json == 0:
        base_warn = (f"baseline valid_json=0/{base['n_json']} — gate is trivial; "
                     "probes too hard for base or generation collapsed")

    c = init_c
    warn = ""
    last_sample: dict | None = None
    for _ in range(MAX_PROBES):
        m = coherence_check(model, tok, lora, c=sign * c,
                            n_vignettes=n_vignettes,
                            max_think_tokens=max_think_tokens,
                            batch_size=batch_size,
                            json_max_new_tokens=json_max_new_tokens)
        pmass_ok = m["pmass"] >= gate
        json_ok = m["valid_json"] >= baseline_json
        ok = pmass_ok and json_ok
        note = ("pass" if ok else
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
             t.get("mean_len", "—"),
             t["note"]] for t in trace]
    table = tabulate(rows, headers=["stage", "c", "pmass", "json", "len", "note"],
                     tablefmt="plain", floatfmt="+.3f")
    logger.info(f"\nc_scan (baseline_pmass={baseline_pmass:.3f}, "
                f"baseline_json={baseline_json}/{base['n_json']}, "
                f"gate=pmass≥{gate:.3f} AND json≥{baseline_json}):\n{table}\n")
    if base_warn:
        logger.warning(f"c_scan: {base_warn}")
    if warn:
        logger.warning(f"c_scan: {warn}")

    # SHOULD: at a passing c, each gen is coherent prose ending in a real
    # {"ans": true|false} object. Tail repetition / schema-copy / gibberish
    # in any of the 3 = adapter is unsafe at this magnitude even though the
    # gate technically passed. If no probe passed (`note != pass`), this
    # dump shows the highest-coefficient sample we tried — useful when c_scan
    # clamps at C_MIN and we want to see what the adapter is producing.
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
