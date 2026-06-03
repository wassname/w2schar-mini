"""C-scan: largest |c| where the adapter stays coherent at the DEPLOYMENT regime.

Sidecar (the agent never sees this). At each candidate c we measure coherence and
keep the largest |c| that does not degrade it below the un-steered base.

2+2+2 WIDE SAMPLING — three test conditions, ONE measure each, AND-gated and
self-relative to the c=0 base. The point is breadth: no single probe type certifies
a bad c, and each condition catches a distinct failure mode the others miss.

1. LONG (2 long single-turn probes) → `valid_json`: append a de-primed JSON tail and
   require a parseable `{"ans": <bool>}`. Tests whether a LONG trajectory can still
   close the object; a long answer that drifts into staccato / schema-copy / gibberish
   cannot. Gate strict: `valid_json ≥ json_frac × base` with json_frac=1.0.
2. MULTITURN (2 of the deployment `PROBES`, the borderline-authority 1P seats) →
   `distinct3`: token-trigram diversity over the turns, run BYTE-IDENTICAL to
   deployment (no tail). A loop ("while while …" / "ethics ethics …") drives it → 0.
   Gate `distinct3 ≥ 0.5 × base` (repetition within ±50%).
3. tinymfv classic (n_vignettes) → `pmass` (p_ans_all): forced-choice P-mass on the
   K=7 answer tokens. Off-register aliveness cross-check. Gate `pmass ≥ gate_frac ×
   base`.

Walk |c| down from init_c by ×2/3 (33%) until all three pass, then `backoff`
(default 1.0 = bake at the passing c; we train at C=1.0 and deploy at the trained
strength, which may be >1 if the adapter stays coherent there).

Known limit (RJ 2026-06-03): a VARIED prose collapse (fused words, full-width parens,
roman-numeral staccato — not a loop) can pass all three, because valid_json recovers
in the tail turn, distinct3 only sees loops, and tinymfv is off-register. This is the
accepted cost of measuring at the answer slot / token level rather than scoring the
prose distribution; wide sampling narrows the gap but does not close it.
"""
from __future__ import annotations

import json
import math
from typing import Literal

import torch
import torch.nn.functional as F
from loguru import logger

from csm.gen.dialogue import DialogueCfg, run_probe
from csm.gen.probes import PROBES
from csm.ws.adapter import ModulatedLoRA


# Walk start at init_c=1.5 (cfg.signed_C) and step ×2/3 (33% down) each fail:
# 1.5 → 1.0 → 0.67 → 0.44 → 0.30 → 0.20 → 0.13 → 0.088 → 0.059. Finer than the
# old ×0.5 halving (1.0 → 0.5 → 0.25 → 0.125) because coherence_check has run-to-
# run randomness, and halving overshoots: a 4× signed_C gap (0.5 vs 0.125) opened
# between two equally-coherent-by-json adapters in the same run when one barely
# missed the pmass gate at 0.5 (9b PiSSA, 2026-06-02). 33% steps resolve the
# usable band (0.5–1.5) instead of skipping past it. MAX_PROBES=9 keeps the floor
# reachable at the finer step.
C_MIN, MAX_PROBES, STEP_FRAC = 0.05, 9, 2 / 3


def _distinct_n(text: str, n: int = 3) -> float:
    """Distinct n-gram ratio (token-level): |unique n-grams| / |total n-grams|.
    1.0 = no repetition; near 0 = heavy looping ('while while while …' /
    'ethics ethics ethics …'). Gated self-relative to the c=0 baseline."""
    toks = text.split()
    if len(toks) < n:
        return 1.0
    ngrams = [tuple(toks[i:i + n]) for i in range(len(toks) - n + 1)]
    return len(set(ngrams)) / len(ngrams)


# De-primed: names only the bool TYPE (`<boolean>`), never which value means
# agree/again, so the json request cannot prime a direction. `_JSON_SCHEMA_PLACEHOLDER`
# still rejects a verbatim schema copy (the placeholder contains "boolean").
_JSON_SCHEMA_PLACEHOLDER = "boolean"
_JSON_TAIL = (
    "\n\nWhen you are done, end your reply with your final answer as a JSON "
    'object on its own line, exactly this format:\n```json\n{"ans": <boolean>}\n```'
)


def _parse_first_json(text: str) -> bool:
    """True iff the first `{...}` in `text` parses AND isn't the schema placeholder.
    A staccato / schema-copy / looping / no-emit collapse fails this even when
    distinct3 and pmass pass — the guided-suffix rescue that flatters pmass does
    not help here, because the model must produce the object itself in free-gen."""
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


# The canary is a 2+2+2 WIDE SAMPLING over three test conditions, one coherence
# measure each (AND-gated, self-relative to the c=0 base). No single probe type can
# certify a bad c, and each condition stresses a distinct failure mode:
#   1. LONG_PROBES (measure: valid_json) — can the model still close a parseable
#      {"ans": <bool>} after a LONG single-turn answer? A long trajectory that drifts
#      into staccato / schema-copy / gibberish fails to emit the object.
#   2. MULTITURN_PROBES (measure: distinct3) — does the deployment IID register stay
#      out of a repetition loop across turns? distinct3 within ±50% of base. These ARE
#      two of the deployment PROBES, run byte-identically (no JSON tail).
#   3. tinymfv classic (measure: p_ans_all) — off-register forced-choice P-mass on the
#      K=7 answer tokens; an independent aliveness cross-check (already wired).
# Kept adapters STACK across rounds, so the canary must hold across all three.
LONG_PROBES: list[dict] = [
    {  # long formal derivation
        "id": "long_fol",
        "opening": (
            "Using first-order logic with ∀/∃/∧/⇒, prove or disprove: \"if every human "
            "is mortal and some human is a philosopher, then some philosopher is "
            "mortal.\" Show the symbolic derivation step by step, naming the inference "
            "rule at each step, then explain in prose what each step does. Then discuss "
            "whether \"all Greeks are mortal; Socrates is mortal; therefore Socrates is "
            "Greek\" follows the same pattern, and why. Conclude as true or false."
        ),
        "followups": [],
    },
    {  # long counterfactual-history essay (different register from the derivation)
        "id": "long_counterfactual",
        "opening": (
            "Write a detailed alternate-history essay of at least six paragraphs on how "
            "twentieth-century industry would have developed if practical room-"
            "temperature superconductors had been discovered in 1900. Reason concretely "
            "about power transmission, transport, computing, and geopolitics, including "
            "second-order effects. Conclude as true if you think general-purpose "
            "computing would still have emerged by 1950, false otherwise."
        ),
        "followups": [],
    },
]

# Two of the deployment PROBES (two different situations, both 1P seats — the
# multi-turn register that collapses). Run byte-identically to deployment.
MULTITURN_PROBES: list[dict] = [PROBES[0], PROBES[2]]  # surveillance_1p, autonomous_weapon_1p


@torch.no_grad()
def _kl_p95(model, tok, lora: ModulatedLoRA, messages: list[dict], upto_idx: int,
            c: float) -> tuple[float, float]:
    """Per-token 95th-pctile fwd KL(steered@c‖base) and bwd KL(base‖steered@c) over
    the assistant turn at `upto_idx`, teacher-forcing the SAVED token sequence twice
    (lora@c → steered logits, lora@0 → base logits). DIAGNOSTIC, not a gate.

    Decisive on the task-31 collapse: a VARIED salad (fused words, full-width parens,
    roman-numeral staccato) — the blind spot json/rep/pmass all miss — lands at
    fwd_p95 ~2-4, while coherent-but-steered prose (incl. a real first-person moral
    shift) stays ≤~1.2. So the multiturn register's KL separates incoherence from the
    steering we WANT, where the answer-slot signals cannot. Computed OUTSIDE any lora
    context so the c=0 base pass is clean; at c=0 KL≡0."""
    full = tok.apply_chat_template(messages[:upto_idx + 1], tokenize=False)
    prefix = tok.apply_chat_template(messages[:upto_idx], tokenize=False,
                                     add_generation_prompt=True)
    full_ids = tok(full, return_tensors="pt").input_ids.to(model.device)
    p = tok(prefix, return_tensors="pt").input_ids.shape[1]
    T = full_ids.shape[1]
    # Empty/near-empty assistant turn → the templated prefix can tokenize to ≥ the
    # full sequence, leaving no completion to score. That is a COLLAPSE (the model
    # emitted nothing at this c) — already caught by the rep/json gates, which then
    # walk c down. KL is logged-not-gated, so it must not crash the calibration here;
    # the honest value is nan ("undefined, gen was empty"), not 0 ("no divergence").
    if T <= p:
        return float("nan"), float("nan")
    with lora(model, c=c):
        steered = model(full_ids).logits[0, p - 1:T - 1].float()
    with lora(model, c=0.0):
        base = model(full_ids).logits[0, p - 1:T - 1].float()
    lps, lpb = F.log_softmax(steered, dim=-1), F.log_softmax(base, dim=-1)
    fwd = (lps.exp() * (lps - lpb)).sum(-1)   # KL(steered‖base) per token
    bwd = (lpb.exp() * (lpb - lps)).sum(-1)   # KL(base‖steered) per token
    return float(fwd.quantile(0.95)), float(bwd.quantile(0.95))


@torch.no_grad()
def _free_gen_probeset(probes: list[dict], model, tok, lora: ModulatedLoRA, c: float,
                       *, add_tail: bool, kl_diag: bool = False,
                       max_new_tokens: int = 2048,
                       enable_thinking: bool = False) -> tuple[int, int, float, list[str], float, float]:
    """Replay each probe under c via `run_probe` (opening + followups, each reply
    conditioned on the model's own prior turns).

    add_tail=True (LONG_PROBES, the json-validation condition): append the de-primed
    JSON tail to the LAST turn and score valid_json — can the model still close a
    parseable {"ans": <bool>} after a long answer (a staccato / schema-copy / looping
    drift cannot). Single-turn probes get the tail on the opening.

    add_tail=False (MULTITURN_PROBES, the repetition condition): no tail, so the
    generation is BYTE-IDENTICAL to deployment; we read distinct3 (token-trigram
    diversity over all turns; a loop drives it → 0).

    kl_diag=True (multiturn only): additionally teacher-force each probe's last
    assistant turn to log per-token fwd/bwd p95 KL(steered@c‖base) — an UN-GATED
    diagnostic that catches the varied-salad collapse distinct3/json/pmass miss.
    Returns (n_probes, n_valid_json, mean_distinct3, gens, mean_kl_fwd_p95,
    mean_kl_bwd_p95); the two KL terms are 0.0 when kl_diag is off or c==0."""
    dcfg = DialogueCfg(max_new_tokens=max_new_tokens, enable_thinking=enable_thinking)
    n_valid = 0
    distincts: list[float] = []
    gens: list[str] = []
    turns_all: list[list[dict]] = []
    with lora(model, c=c):
        for probe in probes:
            if add_tail:
                fus = probe["followups"]
                if fus:
                    p = {**probe, "followups": fus[:-1] + [fus[-1] + _JSON_TAIL]}
                else:
                    p = {**probe, "opening": probe["opening"] + _JSON_TAIL}
            else:
                p = probe
            turns = run_probe(model, tok, p, cfg=dcfg)["turns"]
            replies = [t["text"] for t in turns if t["role"] == "assistant"]
            if add_tail:
                n_valid += int(_parse_first_json(replies[-1]))
            distincts.append(_distinct_n("\n".join(replies), n=3))
            gens.append("\n--turn--\n".join(replies))
            turns_all.append(turns)
    fwd_p95 = bwd_p95 = 0.0
    if kl_diag and c != 0.0:
        fs, bs = [], []
        for turns in turns_all:
            msgs = [{"role": t["role"], "content": t["text"]} for t in turns]
            last_a = max(i for i, m in enumerate(msgs) if m["role"] == "assistant")
            f, b = _kl_p95(model, tok, lora, msgs, last_a, c)
            fs.append(f)
            bs.append(b)
        # nan-aware: a probe that collapsed to an empty turn contributes nan (see
        # _kl_p95). Average over the probes that DID score; nan only if all collapsed.
        fv = [x for x in fs if not math.isnan(x)]
        bv = [x for x in bs if not math.isnan(x)]
        fwd_p95 = sum(fv) / len(fv) if fv else float("nan")
        bwd_p95 = sum(bv) / len(bv) if bv else float("nan")
    return (len(probes), n_valid, sum(distincts) / len(distincts), gens,
            fwd_p95, bwd_p95)


@torch.no_grad()
def coherence_check(model, tok, lora: ModulatedLoRA, c: float, *,
                    n_vignettes: int = 2, max_think_tokens: int = 512,
                    batch_size: int = 2,
                    probe_max_new_tokens: int = 2048,
                    enable_thinking: bool = False) -> dict:
    """One scan point under c: the 2+2+2 wide-sampling canary, one measure per
    condition:
      - tinymfv classic (2 vignettes) → `pmass` (p_ans_all, off-register forced-choice)
      - LONG_PROBES (2)               → `valid_json` (close json after a long answer)
      - MULTITURN_PROBES (2)          → `distinct3` (repetition on the deployment IID
                                        register, byte-identical to deployment)."""
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

    n_long, n_valid, _, g_long, _, _ = _free_gen_probeset(
        LONG_PROBES, model, tok, lora, c, add_tail=True,
        max_new_tokens=probe_max_new_tokens, enable_thinking=enable_thinking)
    n_mt, _, distinct3, g_mt, kl_fwd_p95, kl_bwd_p95 = _free_gen_probeset(
        MULTITURN_PROBES, model, tok, lora, c, add_tail=False, kl_diag=True,
        max_new_tokens=probe_max_new_tokens, enable_thinking=enable_thinking)
    gens = g_long + g_mt
    mean_len = int(sum(len(g) for g in gens) / max(1, len(gens)))
    return {"pmass": pmass, "valid_json": n_valid, "n_long": n_long,
            "distinct3": distinct3, "n_mt": n_mt, "mean_len": mean_len,
            "kl_fwd_p95": kl_fwd_p95, "kl_bwd_p95": kl_bwd_p95, "gens": gens}


def c_scan(model, tok, lora: ModulatedLoRA, *,
           init_c: float = 1.0,
           gate_frac: float = 0.995,
           json_frac: float = 1.0,
           backoff: float = 1.0,
           sign: Literal[1, -1] = 1,
           n_vignettes: int = 2,
           max_think_tokens: int = 512,
           batch_size: int = 2,
           probe_max_new_tokens: int = 2048,
           enable_thinking: bool = False) -> tuple[float, list]:
    """Walk |c| down from init_c by ×2/3 until all three AND-gated coherence signals
    hold vs the c=0 base, one per test condition (the 2+2+2 wide sampling):
    `pmass ≥ gate_frac × base` (tinymfv p_ans_all) AND `valid_json ≥ json_frac × base`
    (close json after a long answer; json_frac=1.0 = strict, both long probes must
    still emit it) AND `distinct3 ≥ 0.5 × base` (repetition within ±50% on the
    deployment multi-turn register). `backoff=1.0` bakes at the passing c (train at
    fixed C=1.0, deploy at the trained strength)."""
    from tabulate import tabulate

    base = coherence_check(model, tok, lora, c=0.0,
                           n_vignettes=n_vignettes,
                           max_think_tokens=max_think_tokens,
                           batch_size=batch_size,
                           probe_max_new_tokens=probe_max_new_tokens,
                           enable_thinking=enable_thinking)
    baseline_pmass = base["pmass"]
    baseline_json = base["valid_json"]
    baseline_distinct = base["distinct3"]
    gate = gate_frac * baseline_pmass
    trace = [{"stage": "baseline", "c": 0.0, **base, "note": "—"}]
    # Loud warnings (not asserts) if the base itself is degenerate: the
    # self-relative gate then becomes trivially satisfiable. Expected on
    # tiny-random smoke (dialogue_max_new_tokens=32 never reaches the JSON tail);
    # on a real model this means an upstream issue (chat template, prompt).
    if baseline_pmass < 0.5:
        logger.warning(
            f"c_scan baseline pmass={baseline_pmass:.3f} < 0.5 — base incoherent "
            f"at c=0 (expected for tiny-random smoke; debug upstream for real models).")
    if baseline_json == 0:
        logger.warning(
            f"c_scan baseline valid_json=0/{base['n_long']} — json gate trivially "
            f"satisfied (expected for tiny-random smoke; debug upstream for real models).")
    if baseline_distinct < 0.1:
        logger.warning(
            f"c_scan baseline distinct3={baseline_distinct:.3f} < 0.1 — base prose "
            f"already degenerate; rep gate trivially satisfied (expected on smoke).")

    c = init_c
    warn = ""
    last_sample: dict | None = None
    for _ in range(MAX_PROBES):
        m = coherence_check(model, tok, lora, c=sign * c,
                            n_vignettes=n_vignettes,
                            max_think_tokens=max_think_tokens,
                            batch_size=batch_size,
                            probe_max_new_tokens=probe_max_new_tokens,
                            enable_thinking=enable_thinking)
        pmass_ok = m["pmass"] >= gate
        # json_frac=1.0 (strict): both LONG probes must still close a parseable
        # {"ans": <bool>} after their long answer. With only 2 probes there is no
        # room for a fractional band, and json validation is robust on a coherent
        # base, so a strict gate catches the long-trajectory drift the user asked
        # this condition to test without false-walking on noise.
        json_ok = m["valid_json"] >= json_frac * baseline_json
        # 0.5x is generous: catches '** ** **' / 'while while' (distinct3 → 0)
        # without tripping on legitimate moderate-repetition prose.
        distinct_ok = m["distinct3"] >= 0.5 * baseline_distinct
        ok = pmass_ok and json_ok and distinct_ok
        note = ("pass" if ok else
                "fail-json" if not json_ok else
                "fail-rep" if not distinct_ok else
                "fail-pmass")
        gens = m.pop("gens", [])  # kept in-memory for the sample dump; not in trace
        trace.append({"stage": "probe", "c": sign * c, **m, "note": note})
        # Save the passing probe if one exists; else keep the last attempt so a
        # never-pass run still surfaces *something* to read.
        if ok or last_sample is None or not last_sample["ok"]:
            last_sample = {"c": sign * c, "gens": gens, "ok": ok, "note": note}
        if ok:
            break
        c *= STEP_FRAC
        if c < C_MIN:
            warn = f"never coherent (c<{C_MIN}); clamped"
            c = C_MIN
            break
    else:
        warn = "hit MAX_PROBES"

    final = sign * c * backoff
    trace.append({"stage": "final", "c": final, "pmass": None,
                  "valid_json": None, "distinct3": None, "n_long": None,
                  "note": f"backoff x{backoff}"})

    # SHOULD: baseline pmass ~0.9-1.0 AND distinct3 ~0.7-0.9 on a coherent base.
    # Reading signed_C:
    #   LOW (walked well below init) = the adapter collapses the DEPLOYMENT register
    #     at the trained strength. Either a real direction throttled by coherence,
    #     or — if PRE/POST then shows no movement at that low c — the intervention
    #     is too blunt (r/layer-range too broad). The interview at c=signed_C is the
    #     tie-breaker.
    #   HIGH (pinned at init) = the adapter holds the deployment register at full
    #     strength. Because the canary IS the deployment now, this is a REAL ceiling,
    #     not the old blind spot (RJ 2026-06-02: an off-register canary certified
    #     1.0 while the interview collapsed — that cannot happen with these probes).
    rows = [[t["stage"], t["c"],
             f"{t['pmass']:.5f}" if t.get("pmass") is not None else "—",
             f"{t['valid_json']}/{t['n_long']}" if t.get("valid_json") is not None else "—",
             f"{t['distinct3']:.2f}" if t.get("distinct3") is not None else "—",
             f"{t['kl_fwd_p95']:.2f}/{t['kl_bwd_p95']:.2f}"
             if t.get("kl_fwd_p95") else "—",
             t.get("mean_len", "—"),
             t["note"]] for t in trace]
    # kl = fwd_p95/bwd_p95 of KL(steered‖base) on the 2 multiturn probes, teacher-forced
    # on the steered generation. It measures DIVERGENCE FROM BASE, NOT coherence, and is
    # NOT gateable (RJ 2026-06-03, task-35 vs task-38):
    #   - LOOP (rep→0): teacher-forced repetition is predicted by base too, so kl→0. The
    #     loop is KL's blind spot; `rep` catches it, not this.
    #   - VARIED salad (task-31): high kl (1p p95 ~2-3 on that adapter).
    #   - COHERENT strong steering: ALSO high kl (task-38 coherent 1p @c=0.667 → ~5). KL
    #     cannot tell this from a varied salad — so a kl gate would kill the steering we
    #     want. Task-35's apparent 1p-salad(2.9)-vs-3p-coherent(0.6) separation was
    #     adapter-specific (that adapter's coherent 3p tracked base). Keep as a logged
    #     anomaly-flag only. kl='—' at baseline (c=0 ⇒ KL≡0, trivially).
    table = tabulate(rows, headers=["stage", "c", "pmass↑", "json↑", "rep↑", "kl", "len", "note"],
                     tablefmt="plain", floatfmt="+.3f")
    # Column legend printed above the table (arrows = desired direction):
    #   pmass↑  p(K=7 allowed answer toks), tinymfv forced-choice. 1=alive.
    #   json↑   valid {"ans":bool} after a long free-gen, count/n_long. n/n=alive.
    #   rep↑    distinct-trigram fraction over the multiturn gens. 1=varied prose, 0=LOOP.
    #   kl      fwd/bwd p95 of PER-TOKEN KL, teacher-forced on the steered gen.
    #           fwd=KL(steered‖base)=KL(new‖old); bwd=KL(base‖steered)=KL(old‖new).
    #           DIAGNOSTIC, NOT a gate: ~0 on a loop (base predicts the repetition too),
    #           HIGH for BOTH a varied salad AND coherent strong steering. No arrow: no
    #           monotone "good" direction. '—' at baseline (c=0 ⇒ KL≡0).
    #   len     mean gen chars. Ballooning len = the incoherence mode leaking in.
    logger.info(
        "\nc_scan cols: pmass↑=tinymfv p_allowed | json↑=valid-json/n after long gen | "
        "rep↑=distinct-trigram (1=varied,0=loop) | kl=fwd/bwd p95 per-tok KL, "
        "fwd=KL(steered‖base)=KL(new‖old) [diagnostic, NOT gated] | len=mean chars\n"
        f"c_scan (baseline_pmass={baseline_pmass:.5f}, "
        f"baseline_json={baseline_json}/{base['n_long']}, "
        f"baseline_rep={baseline_distinct:.2f}, "
        f"gate (AND, self-rel to c=0): pmass≥{gate:.5f} AND json≥{json_frac*baseline_json:.0f} AND "
        f"rep≥{0.5*baseline_distinct:.2f}, "
        f"2 long(json) + 2 multiturn(rep) + {n_vignettes} tinymfv(pmass)):\n{table}\n")
    if warn:
        logger.warning(f"c_scan: {warn}")

    # SHOULD: at a passing c, each probe is coherent multi-turn prose. A tail loop
    # ("while while" / "ethics ethics"), fused words ("understandinglives"), or a
    # language switch in ANY probe = the adapter is unsafe at this magnitude even
    # if the gate technically passed. Baseline probe[0] is dumped alongside for a
    # side-by-side at c=0. If no probe passed, this shows the highest-c sample tried.
    def _clip(gen: str) -> str:
        head, tail = gen[:300], gen[-300:]
        mid = f" … ⟨{len(gen) - 600} chars⟩ … " if len(gen) > 600 else ""
        return f"{head}{mid}{tail}"

    all_probes = LONG_PROBES + MULTITURN_PROBES  # same order as coherence_check gens
    base_gens = base.get("gens", [])
    out = ["\n\n========== C_SCAN samples (head/tail, truncated) =========="]
    if base_gens:
        out.append(f"\n--- baseline @ c=+0.0000 | probe 1/1: {LONG_PROBES[0]['id']} "
                   f"(rep={baseline_distinct:.2f}) ---")
        out.append(f"  A: {_clip(base_gens[0])}")
    if last_sample is not None:
        n = len(last_sample["gens"])
        out.append(f"\n--- sample @ c={last_sample['c']:+.4f} ({last_sample['note']}) "
                   f"| {n} probes ---")
        for i, (probe, gen) in enumerate(zip(all_probes, last_sample["gens"]), 1):
            out.append(f"\n  [probe {i}/{n}: {probe['id']}]")
            out.append(f"  A: {_clip(gen)}")
    out.append("\n========== END C_SCAN samples ==========\n")
    logger.info("\n".join(out))
    return final, trace
