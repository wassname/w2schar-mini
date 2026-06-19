"""c-vs-DEPTH sweep: generate the interview probes for ONE adapter at several
baked c, so a blind depth judge can map reasoning depth against steering strength.

Why (apex measurement design, RJ 2026-06-18/19): c_scan walks c DOWN only by
COHERENCE gates (pmass/json/rep), so it bakes the highest c the canary still
tolerates. But the blind depth judge found depth degrades BEFORE coherence does:
a c=1 adapter read steered-DEEPER (near-twin), the c=4 / aggressive runs read
base-DEEPER (shallow confront reflex), while pmass/json/rep stayed flat. If that
is real, c_scan bakes too high and the apex must pick c by DEPTH, not coherence.

This isolates the claim CACE-clean: ONE fixed adapter, no history, only c varies.
`csm.gen.dialogue.dialogue` already replays PROBES under `baked(...)` at an
arbitrary c (c=0 => base, c>0 => adapter at strength c), so we just loop c and
save one interview json per c. The depth judging is a SEPARATE blind subagent
step (depth_judge.py), NOT here -- this file only does the deterministic GPU gen.

Usage:
    uv run python scripts/c_depth_sweep.py <slug> <round> <c,c,c> [out_dir]
    # default: the 20260615 fairness round00 adapter at c in {0,1,2,3,4}

Then (interactive, no GPU): pair interview_c+0.00.json against each interview_cX,
hand to >=2 blind unprimed depth judges, decode -> depth-vs-c curve.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from loguru import logger

from csm.config import config_for_run
from csm.gen.dialogue import DialogueCfg, dialogue
from csm.gen.probes import PROBES
from csm.ws.bake import adapter_spec_from_checkpoint
from csm.ws.history import load_base_with_history_specs

SLUG = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
    "out/iter/20260615T125736_iter_google-gemma-3-4b-it")
ROUND = sys.argv[2] if len(sys.argv) > 2 else "round00"
# Straddle the native bake (c=1) and walk PAST it to where the finding saw the
# shallow reflex (c=4). c=0 is the base anchor every other c is judged against.
CS = [float(x) for x in sys.argv[3].split(",")] if len(sys.argv) > 3 else [0.0, 1.0, 2.0, 3.0, 4.0]
OUT = Path(sys.argv[4]) if len(sys.argv) > 4 else SLUG / ROUND / "cdepth_sweep"

run = json.loads((SLUG / "run.json").read_text())
cfg = config_for_run(run)
adapter_path = SLUG / ROUND / "adapter.safetensors"

logger.info(f"c-depth sweep: {run['model']} {SLUG.name}/{ROUND} adapter, c={CS} -> {OUT}")
model, tok, _ = load_base_with_history_specs(run["model"], [], quant=cfg.quant)
spec = adapter_spec_from_checkpoint(model, str(adapter_path), default_c=1.0)
dcfg = DialogueCfg(max_new_tokens=cfg.dialogue_max_new_tokens, enable_thinking=cfg.enable_thinking)

OUT.mkdir(parents=True, exist_ok=True)
for c in CS:
    out = OUT / f"interview_c{c:+.2f}.json"
    dialogue(model, tok, PROBES, out, hist_specs=None, current_spec=spec, c=c, cfg=dcfg)
    logger.info(f"c={c:+.2f}: wrote {out.name}")
logger.info(f"done: {len(CS)} interviews in {OUT}")
