"""Sweep the baked steering coefficient c on the tinymfv probe for one adapter.

Question (wassname, 2026-06-01): the round00 PiSSA adapter baked at signed_C=1.5
moved tinymfv mean_p by <=0.004. Is that a weak-but-real directional signal that
scales with c, or noise? Bake the SAME adapter at c in {0,1.5,2,3,4,6} and watch
whether the per-foundation deltas grow monotonically. Flat => noise / impotent
direction; monotone growth => real axis, signed_C was just calibrated conservative.

Loads the 27b once, re-bakes per c via baked(..., c_overrides=[c]). round00 only
(clean round, no stale-Cho bleed), no history, so the signal is isolated.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from loguru import logger
from tabulate import tabulate

from csm.config import config_for_run
from csm.eval import FOUNDATIONS, eval_round
from csm.ws.bake import adapter_spec_from_checkpoint, baked
from csm.ws.history import load_base_with_history_specs

SLUG = Path("out/iter/20260601T052656_iter_google-gemma-2-27b-it")
ROUND = "round00"
CS = [0.0, 1.5, 2.0, 3.0, 4.0, 6.0]

run = json.loads((SLUG / "run.json").read_text())
model_id = run["model"]
cfg = config_for_run(run)
adapter_path = SLUG / ROUND / "adapter.safetensors"

logger.info(f"c-sweep: {model_id} {SLUG.name}/{ROUND} adapter, c={CS}")
model, tok, _ = load_base_with_history_specs(model_id, [], quant=cfg.quant)
spec = adapter_spec_from_checkpoint(model, str(adapter_path), default_c=1.0)

rows = []
mean_p_by_c = {}
for c in CS:
    with baked(model, [spec], c_overrides=[c]):
        summary = eval_round(model, tok, name="classic", batch_size=cfg.eval_batch_size,
                             max_think_tokens=64, n_vignettes=None,
                             conditions=("other_violate",))
    mp = summary["mean_p"]
    mean_p_by_c[c] = mp
    base = mean_p_by_c[0.0]
    rows.append([c] + [f"{mp[f]:.4f}" + ("" if c == 0 else f" ({mp[f]-base[f]:+.4f})")
                       for f in FOUNDATIONS])
    logger.info(f"c={c}: authority={mp['authority']:.4f} (Δ{mp['authority']-base['authority']:+.4f})")

print(tabulate(rows, headers=["c"] + FOUNDATIONS, tablefmt="pipe"))
