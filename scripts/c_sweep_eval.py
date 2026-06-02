"""Sweep the baked steering coefficient c on the tinymfv probe for one adapter.

Question (wassname, 2026-06-01): the round00 LoRA adapter (new philosophical
moral-depth axis) baked at signed_C=0.25 moved tinymfv authority by -0.0046,
the top-magnitude foundation but at the noise floor. Real-but-weak direction
throttled by the tiny nf4-LoRA coherence budget, or noise? Bake the SAME adapter
at c in {0,0.25,0.5,1,2,3} (straddling and well past signed_C=0.25) and watch
whether authority keeps dropping monotonically. Flat => noise / impotent
direction; monotone growth => real axis, signed_C was just the coherence ceiling.
NB above signed_C free-gen goes incoherent, but the forced-choice answer-slot
probe still reads direction.

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

SLUG = Path("out/iter/20260601T115718_iter_google-gemma-2-27b-it")
ROUND = "round00"
CS = [0.0, 0.25, 0.5, 1.0, 2.0, 3.0]

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
    # NB summary["mean_pmass_format"] is null at max_think_tokens=64 (tinymfv does
    # not compute it cheaply), so clean-steering-vs-collapse is read from the
    # redistribution SHAPE instead: clean = mass moves authority->care; collapse =
    # trends reverse / unrelated foundations explode (seen at c=3).
    rows.append([c] + [f"{mp[f]:.4f}" + ("" if c == 0 else f" ({mp[f]-base[f]:+.4f})")
                       for f in FOUNDATIONS])
    logger.info(f"c={c}: authority={mp['authority']:.4f} (Δ{mp['authority']-base['authority']:+.4f})")

print(tabulate(rows, headers=["c"] + FOUNDATIONS, tablefmt="pipe"))
