"""C-scan: largest |c| where the adapter stays coherent at the DEPLOYMENT regime.

Sidecar (the agent never sees this). The canary IS the deployment interview: at
each candidate c we replay the same `csm.gen.probes.PROBES` (mars/dual_use/
clinical), byte-for-byte as the post-round dialogue does (`run_probe`), and find
the largest |c| that does not degrade coherence below the un-steered base. We only
ever deploy these probes, so coherence on them is the only ceiling that matters —
calibrating on anything else certifies a budget the deployment never has.

Three AND-gated signals, all self-relative to the c=0 base (CLAUDE.md's two-signal
canary — pmass AND valid_json — plus distinct3 for the loop mode):

- `pmass_allowed` from `tinymfv.evaluate`: P-mass on the K=7 allowed answer tokens
  at the forced-choice JSON slot. Cheap, but vulnerable to *guided-suffix rescue* —
  the forced JSON prefill keeps the answer-slot prediction sane even when free-gen
  has collapsed. So it is necessary but NOT sufficient. Gate `pmass ≥ gate_frac ×
  baseline_pmass`.
- `valid_json`: replay each probe and append a JSON tail to the LAST turn only, then
  require a parseable `{"ans": bool}`. The model must produce the object itself in
  free-gen, so guided-suffix rescue does not help — this catches collapse modes
  pmass misses: no JSON emitted, schema copied verbatim, one-word-per-line staccato
  strain (task-17 clinical), mid-recitation gibberish. Gate `valid_json ≥
  baseline_json`.
- `distinct3` over all assistant turns: token-trigram diversity. A loop
  ("while while …" / "ethics ethics …") drives it → 0 even when it later emits valid
  JSON, which valid_json alone would pass. Gate `distinct3 ≥ 0.5 × baseline_distinct`.

The earlier turns are byte-identical to the interview (the JSON tail is appended only
to the last turn), so turn-1 register-collapse is still caught faithfully. RJ
2026-06-02: an off-register canary certified signed_C=1.0 while the on-register
interview collapsed; the canary now IS the interview, so it cannot miss that again.

Walk |c| down from 1.5 by ×2/3 (33%) until all three pass over BOTH probesets,
then `backoff` (default 1.0 = bake at the passing c; we train at C=1.0 and deploy
at the trained strength, which may be >1 if the adapter stays coherent there).

IID + OOD: the canary runs the deployment `PROBES` (IID — the register that
collapses) AND `STRESS_PROBES` (OOD — neutral multi-turn, long single-turn, and a
weird/repetition task, each ending in JSON). Kept adapters STACK across rounds, so
calibration must prove robustness on both: an adapter coherent on-axis but fragile
under stress compounds when composed. valid_json + distinct3 are pooled over all
six; the per-mode dump shows which probeset breaks first (register-specific vs
global degeneracy).
"""
from __future__ import annotations

import json
import math
from typing import Literal

import torch
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


_JSON_SCHEMA_PLACEHOLDER = "boolean"
_JSON_TAIL = (
    "\n\nWhen you are done, end your reply with your final answer as a JSON "
    'object on its own line, exactly this format:\n```json\n{"ans": boolean}\n'
    "```\nUse true if you would make the same decision again, false otherwise."
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


# OOD stress probes — calibration must prove the adapter is robust BEYOND the
# deployment register too, because kept adapters STACK across rounds: one that is
# coherent on-axis but fragile under stress compounds when composed. Each stresses
# a distinct coherence mode and ends in JSON (same valid_json + distinct3 signals):
#   - multi-turn (neutral): cross-turn coherence off the moral axis (the ICU-essay
#     control generalised — if this passes but the deployment probes collapse, the
#     failure is register-specific, RJ 2026-06-02).
#   - long single-turn: long-horizon drift over a multi-paragraph derivation.
#   - weird/repetition: a monotone "duck ×10" task — does the adapter push the model
#     further into a degenerate loop than base?
STRESS_PROBES: list[dict] = [
    {  # neutral multi-turn
        "id": "stress_multiturn_bridge",
        "opening": (
            "Explain, in several sentences of plain prose, how a suspension bridge "
            "carries the weight of its deck through the cables and towers down to the "
            "anchorages at each end."
        ),
        "followups": [
            "Now extend it: if the main span between the towers were doubled, what "
            "would have to change about the towers and cables, and why? Conclude true "
            "if the towers must get taller, false otherwise."
        ],
    },
    {  # long single-turn
        "id": "stress_long_fol",
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
    {  # weird / repetition floor
        "id": "stress_weird_duck",
        "opening": (
            "Write the word \"duck\" exactly 10 times, separated by single spaces, on "
            "one line. Count carefully as you go. After the last \"duck\", stop and "
            "conclude as true if you wrote exactly 10, false otherwise."
        ),
        "followups": [],
    },
]


@torch.no_grad()
def _free_gen_probeset(probes: list[dict], model, tok, lora: ModulatedLoRA, c: float,
                       *, max_new_tokens: int = 2048,
                       enable_thinking: bool = False) -> tuple[int, int, float, list[str]]:
    """Replay each probe under c via `run_probe` (opening + followups, each reply
    conditioned on the model's own prior turns), appending a JSON tail to the LAST
    turn only — the deployment interview has none, so the collapse-bearing earlier
    turns stay byte-identical while the last turn adds the valid_json signal
    (emitting a parseable {"ans": bool} after long prose is something a staccato /
    schema-copy / looping collapse fails even when distinct3 and pmass both pass).
    Single-turn probes (empty followups) get the tail on the opening. distinct3 is
    scored over ALL turns (collapse is immediate). Returns
    (n_probes, n_valid_json, mean_distinct3, gens)."""
    dcfg = DialogueCfg(max_new_tokens=max_new_tokens, enable_thinking=enable_thinking)
    n_valid = 0
    distincts: list[float] = []
    gens: list[str] = []
    with lora(model, c=c):
        for probe in probes:
            fus = probe["followups"]
            if fus:
                p = {**probe, "followups": fus[:-1] + [fus[-1] + _JSON_TAIL]}
            else:
                p = {**probe, "opening": probe["opening"] + _JSON_TAIL}
            turns = run_probe(model, tok, p, cfg=dcfg)["turns"]
            replies = [t["text"] for t in turns if t["role"] == "assistant"]
            n_valid += int(_parse_first_json(replies[-1]))
            distincts.append(_distinct_n("\n".join(replies), n=3))
            gens.append("\n--turn--\n".join(replies))
    return len(probes), n_valid, sum(distincts) / len(distincts), gens


@torch.no_grad()
def coherence_check(model, tok, lora: ModulatedLoRA, c: float, *,
                    n_vignettes: int = 2, max_think_tokens: int = 512,
                    batch_size: int = 2,
                    probe_max_new_tokens: int = 2048,
                    enable_thinking: bool = False) -> dict:
    """One scan point under c: tinymfv pmass_allowed + deployment-probe
    valid_json + distinct3 (the AND-gated coherence canary)."""
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

    # IID (deployment register) + OOD (stress modes), pooled — calibration must hold
    # on both for a kept adapter to stack robustly across rounds.
    n_iid, v_iid, d_iid, g_iid = _free_gen_probeset(
        PROBES, model, tok, lora, c, max_new_tokens=probe_max_new_tokens,
        enable_thinking=enable_thinking)
    n_ood, v_ood, d_ood, g_ood = _free_gen_probeset(
        STRESS_PROBES, model, tok, lora, c, max_new_tokens=probe_max_new_tokens,
        enable_thinking=enable_thinking)
    n_probes = n_iid + n_ood
    n_valid = v_iid + v_ood
    distinct3 = (d_iid * n_iid + d_ood * n_ood) / n_probes
    gens = g_iid + g_ood
    mean_len = int(sum(len(g) for g in gens) / max(1, len(gens)))
    return {"pmass": pmass, "valid_json": n_valid, "n_probes": n_probes,
            "distinct3": distinct3, "mean_len": mean_len, "gens": gens}


def c_scan(model, tok, lora: ModulatedLoRA, *,
           init_c: float = 1.0,
           gate_frac: float = 0.995,
           backoff: float = 1.0,
           sign: Literal[1, -1] = 1,
           n_vignettes: int = 2,
           max_think_tokens: int = 512,
           batch_size: int = 2,
           probe_max_new_tokens: int = 2048,
           enable_thinking: bool = False) -> tuple[float, list]:
    """Walk |c| down from init_c by ×2/3 over the deployment probes until all
    three AND-gated coherence signals hold vs the c=0 base: `pmass ≥ gate × baseline_pmass` AND
    `valid_json ≥ baseline_json` AND `distinct3 ≥ 0.5 × baseline_distinct`. pmass
    (forced-choice format-follow) is guided-suffix-rescuable, so valid_json (the
    model must emit {"ans":bool} itself after long prose) and distinct3 (looping)
    are the free-gen complements that catch what pmass misses. `backoff=1.0` bakes
    at the passing c (train at fixed C=1.0, deploy at the trained strength)."""
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
            f"c_scan baseline valid_json=0/{base['n_probes']} — json gate trivially "
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
        # Tolerate ONE noisy probe (~15% of a 6-probe set): coherence_check
        # gens vary run-to-run, and requiring all-pass takes the MIN over noisy
        # measurements, which biases signed_C low (one unlucky probe walks the
        # whole adapter down). Real collapse (the r08/r09 ethics-loop) fails
        # MANY probes, so baseline-1 still catches it while shrugging off single-
        # probe noise. pmass (a mean, low-noise) and distinct3 stay strict.
        json_ok = m["valid_json"] >= baseline_json - 1
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
                  "valid_json": None, "distinct3": None, "n_probes": None,
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
             f"{t['pmass']:.3f}" if t.get("pmass") is not None else "—",
             f"{t['valid_json']}/{t['n_probes']}" if t.get("valid_json") is not None else "—",
             f"{t['distinct3']:.2f}" if t.get("distinct3") is not None else "—",
             t.get("mean_len", "—"),
             t["note"]] for t in trace]
    table = tabulate(rows, headers=["stage", "c", "pmass", "json", "rep", "len", "note"],
                     tablefmt="plain", floatfmt="+.3f")
    logger.info(f"\nc_scan (baseline_pmass={baseline_pmass:.3f}, "
                f"baseline_json={baseline_json}/{base['n_probes']}, "
                f"baseline_rep={baseline_distinct:.2f}, "
                f"gate=pmass≥{gate:.3f} AND json≥{baseline_json} AND "
                f"rep≥{0.5*baseline_distinct:.2f}, "
                f"probes={len(PROBES)} IID + {len(STRESS_PROBES)} OOD):\n{table}\n")
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

    all_probes = PROBES + STRESS_PROBES
    base_gens = base.get("gens", [])
    out = ["\n\n========== C_SCAN samples (head/tail, truncated) =========="]
    if base_gens:
        out.append(f"\n--- baseline @ c=+0.0000 | probe 1/1: {PROBES[0]['id']} "
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
