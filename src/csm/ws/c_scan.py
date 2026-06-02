"""C-scan: largest |c| where the adapter stays coherent at the DEPLOYMENT regime.

Sidecar (the agent never sees this). The canary IS the deployment interview: at
each candidate c we replay the same `csm.gen.probes.PROBES` (mars/dual_use/
clinical), byte-for-byte as the post-round dialogue does (`run_probe`), and find
the largest |c| that does not degrade coherence below the un-steered base. We only
ever deploy these probes, so coherence on them is the only ceiling that matters —
calibrating on anything else certifies a budget the deployment never has.

Two gated signals, both self-relative to the c=0 base:

- `distinct3` over all assistant turns of each probe: token-trigram diversity. A
  register-collapse ("while while while …" / "ethics ethics …") drives it → 0;
  gate `distinct3 ≥ 0.5 × baseline_distinct`. This is the signal that catches the
  autoregressive collapse the adapter induces ON ITS TRAINED AXIS. RJ 2026-06-02:
  an off-register canary certified signed_C=1.0 while the on-register interview
  collapsed; the canary now IS the interview, so it cannot miss that again.
- `pmass_allowed` from `tinymfv.evaluate`: P-mass on the K=7 allowed answer tokens
  at the forced-choice JSON slot. Orthogonal, format-different, cheap — the
  "globally sane?" check. Gate `pmass ≥ gate_frac × baseline_pmass`.

Walk |c| down ×0.5 until both pass, then `backoff` (default 1.0 = bake at the
passing c; we train at C=1.0 and deploy at the trained strength).

No dedicated OOD prose probes: the adapter is most fragile on its trained
moral-authority register, so the deployment probes collapse at a LOWER c than any
neutral/OOD prose would — an OOD probe never binds tighter than the in-distribution
ones, so it can never lower signed_C. pmass already supplies one orthogonal,
format-different coherence signal for free, which covers the "globally degenerate"
diagnostic. So the OOD prose probes (FOL/duck/terminal + held-out essays) were
redundant and removed.
"""
from __future__ import annotations

import math
from typing import Literal

import torch
from loguru import logger

from csm.gen.dialogue import DialogueCfg, run_probe
from csm.gen.probes import PROBES
from csm.ws.adapter import ModulatedLoRA


C_MIN, MAX_PROBES = 0.05, 8


def _distinct_n(text: str, n: int = 3) -> float:
    """Distinct n-gram ratio (token-level): |unique n-grams| / |total n-grams|.
    1.0 = no repetition; near 0 = heavy looping ('while while while …' /
    'ethics ethics ethics …'). Gated self-relative to the c=0 baseline."""
    toks = text.split()
    if len(toks) < n:
        return 1.0
    ngrams = [tuple(toks[i:i + n]) for i in range(len(toks) - n + 1)]
    return len(set(ngrams)) / len(ngrams)


@torch.no_grad()
def _free_gen_probes(model, tok, lora: ModulatedLoRA, c: float, *,
                     max_new_tokens: int = 2048,
                     enable_thinking: bool = False) -> tuple[int, float, list[str]]:
    """Replay each deployment probe under c (exactly as the interview does, via
    `run_probe`: opening + followups, each reply conditioned on the model's own
    prior turns) and score distinct3 over ALL assistant turns concatenated —
    register-collapse appears on turn 1, not just the last reply. Returns
    (n_probes, mean_distinct3, gens)."""
    dcfg = DialogueCfg(max_new_tokens=max_new_tokens, enable_thinking=enable_thinking)
    distincts: list[float] = []
    gens: list[str] = []
    with lora(model, c=c):
        for probe in PROBES:
            turns = run_probe(model, tok, probe, cfg=dcfg)["turns"]
            replies = [t["text"] for t in turns if t["role"] == "assistant"]
            distincts.append(_distinct_n("\n".join(replies), n=3))
            gens.append("\n--turn--\n".join(replies))
    return len(PROBES), sum(distincts) / len(distincts), gens


@torch.no_grad()
def coherence_check(model, tok, lora: ModulatedLoRA, c: float, *,
                    n_vignettes: int = 2, max_think_tokens: int = 512,
                    batch_size: int = 2,
                    probe_max_new_tokens: int = 2048,
                    enable_thinking: bool = False) -> dict:
    """One scan point under c: tinymfv pmass_allowed + deployment-probe distinct3."""
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

    n_probes, distinct3, gens = _free_gen_probes(
        model, tok, lora, c, max_new_tokens=probe_max_new_tokens,
        enable_thinking=enable_thinking)
    mean_len = int(sum(len(g) for g in gens) / max(1, len(gens)))
    return {"pmass": pmass, "distinct3": distinct3, "n_probes": n_probes,
            "mean_len": mean_len, "gens": gens}


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
    """Walk |c| down ×0.5 over the deployment probes until `pmass ≥ gate ×
    baseline_pmass` AND `distinct3 ≥ 0.5 × baseline_distinct`. `backoff=1.0` bakes
    at the passing c directly (we train at fixed C=1.0 and deploy at the trained
    strength; hedging below the coherence ceiling would deploy weaker than trained).
    Bump backoff <1 only if cumulative history-bake fragility resurfaces."""
    from tabulate import tabulate

    base = coherence_check(model, tok, lora, c=0.0,
                           n_vignettes=n_vignettes,
                           max_think_tokens=max_think_tokens,
                           batch_size=batch_size,
                           probe_max_new_tokens=probe_max_new_tokens,
                           enable_thinking=enable_thinking)
    baseline_pmass = base["pmass"]
    baseline_distinct = base["distinct3"]
    gate = gate_frac * baseline_pmass
    trace = [{"stage": "baseline", "c": 0.0, **base, "note": "—"}]
    # Loud warnings (not asserts) if the base itself is degenerate: the
    # self-relative gate then becomes trivially satisfiable. Expected on
    # tiny-random smoke (dialogue_max_new_tokens=32 emits garbage); on a real
    # model this means an upstream issue (chat template, prompt) — investigate.
    if baseline_pmass < 0.5:
        logger.warning(
            f"c_scan baseline pmass={baseline_pmass:.3f} < 0.5 — base incoherent "
            f"at c=0 (expected for tiny-random smoke; debug upstream for real models).")
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
        # 0.5x is generous: catches '** ** **' / 'while while' (distinct3 → 0)
        # without tripping on legitimate moderate-repetition prose.
        distinct_ok = m["distinct3"] >= 0.5 * baseline_distinct
        ok = pmass_ok and distinct_ok
        note = ("pass" if ok else
                "fail-rep" if not distinct_ok and pmass_ok else
                "fail-pmass" if not pmass_ok and distinct_ok else
                "fail-both")
        gens = m.pop("gens", [])  # kept in-memory for the sample dump; not in trace
        trace.append({"stage": "probe", "c": sign * c, **m, "note": note})
        # Save the passing probe if one exists; else keep the last attempt so a
        # never-pass run still surfaces *something* to read.
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
                  "distinct3": None, "n_probes": None,
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
             f"{t['distinct3']:.2f}" if t.get("distinct3") is not None else "—",
             t.get("mean_len", "—"),
             t["note"]] for t in trace]
    table = tabulate(rows, headers=["stage", "c", "pmass", "rep", "len", "note"],
                     tablefmt="plain", floatfmt="+.3f")
    logger.info(f"\nc_scan (baseline_pmass={baseline_pmass:.3f}, "
                f"baseline_rep={baseline_distinct:.2f}, "
                f"gate=pmass≥{gate:.3f} AND rep≥{0.5*baseline_distinct:.2f}, "
                f"probes={len(PROBES)} deployment):\n{table}\n")
    if warn:
        logger.warning(f"c_scan: {warn}")

    # SHOULD: at a passing c, each probe is coherent multi-turn prose. A tail loop
    # ("while while" / "ethics ethics"), fused words ("understandinglives"), or a
    # language switch in ANY probe = the adapter is unsafe at this magnitude even
    # if the gate technically passed. Baseline probe[0] is dumped alongside for a
    # side-by-side at c=0. If no probe passed, this shows the highest-c sample tried.
    base_gens = base.get("gens", [])
    if base_gens:
        gen = base_gens[0]
        head, tail = gen[:300], gen[-300:]
        mid = f" … ⟨{len(gen) - 600} chars⟩ … " if len(gen) > 600 else ""
        logger.info(
            f"c_scan baseline @ c=+0.0000 (rep={baseline_distinct:.2f}) "
            f"probe[{PROBES[0]['id']}]:\n  A: {head}{mid}{tail}")
    if last_sample is not None:
        for probe, gen in zip(PROBES, last_sample["gens"]):
            head, tail = gen[:300], gen[-300:]
            mid = f" … ⟨{len(gen) - 600} chars⟩ … " if len(gen) > 600 else ""
            logger.info(
                f"c_scan sample @ c={last_sample['c']:+.4f} ({last_sample['note']}) "
                f"probe[{probe['id']}]:\n  A: {head}{mid}{tail}")
    return final, trace
