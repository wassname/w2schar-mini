"""C-scan: largest |C| where pmass_format(c) ≥ gate × baseline. No backoff.

Sidecar (the agent never sees this). pmass = `mean_pmass_format` from
tinymfv: mass on the 7 MFV foundation tokens at the JSON answer slot
on N forced-choice vignettes. Format-following is a direct coherence
canary — when the adapter is too strong the model emits gibberish or
loops and that mass drops sharply, independent of which foundation is
picked.

Forked from `weight-steering-lite/w2schar/03b_train.py:_measure_pmass`
+ `_cscan_v2`, simplified: walk-down only (×0.5), no walk-up, no
regula-falsi refinement, no backoff. The 0.98 gate is the only safety
margin.

The prior version of this file used mass-on-base's-top-K on a base-
generated sequence — a surrogate that doesn't catch autoregressive
collapse because it's teacher-forced on clean prefix. Format-follow
pmass catches it because format follow degrades fast under steering.
"""
from __future__ import annotations

import math
from typing import Literal

import torch
from loguru import logger

from csm.ws.adapter import ModulatedLoRA


C_MIN, MAX_PROBES = 0.05, 8


@torch.no_grad()
def pmass_format(model, tok, lora: ModulatedLoRA, c: float, *,
                 n_vignettes: int = 2, max_think_tokens: int = 512,
                 batch_size: int = 2) -> float:
    """Run tinymfv on N vignettes under `c` and return `mean_pmass_format`:
    sum of probability over the 7 foundation answer tokens at the JSON
    answer slot, averaged across rows.

    `max_think_tokens=512` is enough for autoregressive collapse modes
    (repetition loops, language drift) to manifest before the answer
    slot. wsl uses 2048; we trade some recall for speed. Bump up if
    tracking deployment-regime coherence at longer think budgets.
    """
    from tinymfv import evaluate as tinymfv_evaluate
    with lora(model, c=c):
        rep = tinymfv_evaluate(
            model, tok, name="classic",
            n_vignettes=n_vignettes,
            max_think_tokens=max_think_tokens,
            batch_size=batch_size,
            return_per_row=False,
        )
    pm = float(rep["mean_pmass_format"])
    if not math.isfinite(pm):
        raise RuntimeError(f"NaN pmass_format at c={c}")
    return pm


def c_scan(model, tok, lora: ModulatedLoRA, *,
           init_c: float = 1.0,
           gate_frac: float = 0.98,
           sign: Literal[1, -1] = 1,
           n_vignettes: int = 2,
           max_think_tokens: int = 512,
           batch_size: int = 2) -> tuple[float, list]:
    """Walk |C| down by ×0.5 until pmass_format(c) ≥ gate_frac × baseline.
    Returns sign * c (no backoff — the gate is strict; backoff was making
    interventions too weak to clear bf16 eval noise)."""
    from tabulate import tabulate

    baseline = pmass_format(model, tok, lora, c=0.0,
                            n_vignettes=n_vignettes,
                            max_think_tokens=max_think_tokens,
                            batch_size=batch_size)
    gate = gate_frac * baseline
    trace = [{"stage": "baseline", "c": 0.0, "pmass": baseline, "note": "—"}]

    c = init_c
    warn = ""
    for _ in range(MAX_PROBES):
        pm = pmass_format(model, tok, lora, c=sign * c,
                          n_vignettes=n_vignettes,
                          max_think_tokens=max_think_tokens,
                          batch_size=batch_size)
        ok = pm >= gate
        trace.append({"stage": "probe", "c": sign * c, "pmass": pm,
                      "note": "pass" if ok else "fail"})
        if ok:
            break
        c *= 0.5
        if c < C_MIN:
            warn = f"never coherent (c<{C_MIN}); clamped"
            c = C_MIN
            break
    else:
        warn = "hit MAX_PROBES"

    final = sign * c
    trace.append({"stage": "final", "c": final, "pmass": None,
                  "note": "no backoff"})

    # SHOULD: baseline pmass_format ~0.95-1.0 on a coherent base; pass at
    # largest probed c → coherent adapter; several fails then pass → fragile,
    # smaller bake; all fails → broken adapter (post-eval will be gibberish).
    rows = [[t["stage"], t["c"],
             f"{t['pmass']:.3f}" if t["pmass"] is not None else "—",
             t["note"]] for t in trace]
    table = tabulate(rows, headers=["stage", "c", "pmass_format", "note"],
                     tablefmt="plain", floatfmt="+.3f")
    logger.info(f"\nc_scan (baseline={baseline:.3f}, gate={gate:.3f}):\n{table}\n")
    if warn:
        logger.warning(f"c_scan: {warn}")
    return final, trace
