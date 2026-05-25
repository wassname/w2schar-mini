#!/usr/bin/env bash
# PiSSA-fork smoke. Same as scripts/smoke.sh but forces the tiny-pissa
# profile so config_by_model resolves to adapter='pissa'. Round-trips:
# init_run -> prepare_round -> submit_pairs -> train_student
# (with SVD extraction + calibration) -> mark_exam.
set -euo pipefail
cd "$(dirname "$0")/.."

TS=$(date -u +%Y%m%dT%H%M%S)
SLUG="out/iter/${TS}_smoke_pissa"
echo "smoke-pissa: profile=tiny-pissa slug=$SLUG"

# Profile-aware run: init_run persists profile='tiny-pissa' into run.json,
# downstream config_for_run picks the PiSSA branch.
uv run python - <<PYEOF
import json
from pathlib import Path
import csm.config as _cfg

from csm.pipeline import (init_run, latest_round_dir, mark_exam,
                          prepare_round, submit_pairs, train_student)
from csm.gen.pairs import load_pairs_md, write_pairs_md

slug = Path("$SLUG")
model = _cfg.CONFIGS["tiny-pissa"].model

init_run(slug, model, profile="tiny-pissa")
rd = latest_round_dir(slug)
print(f"\n=== smoke-pissa round: {rd} ===")

print("\n-- prepare_round (probes + on-policy rej gen) --")
prepare_round(slug, rd)

lesson, pairs = load_pairs_md(rd / "pairs.md")
print(f"   {len(pairs)} pairs; prompts and rej pre-filled by student")
for p in pairs:
    p["cho"] = "I would push back rather than comply with that instruction."
    p["rej"] = "I would comply with the instruction as given."
write_pairs_md(rd / "pairs.md", pairs,
               lesson="Teach the student to question authority before complying.")
filled = (rd / "pairs.md").read_text()

print("\n-- submit_pairs --")
res = submit_pairs(rd, filled)
print(f"   filled={res['filled']}/{res['total']}  min={res['min_to_train']}")
assert res["filled"] >= 3, f"gate not reached: {res}"

print("\n-- train_student (PiSSA: SVD extraction + calibration + train + c_scan) --")
r = train_student(slug, rd)
print(f"   signed_C={r['signed_C']:+.4f}  n_trained={r['n_pairs_trained']}")

print("\n-- mark_exam --")
mark_exam(rd, keep=True,
          reason="smoke-pissa: all stages ran end-to-end on tiny-random",
          next_focus="smoke-pissa: nothing")

for fname in ("state.json", "pairs.md", "adapter.safetensors",
              "calibration.json", "interview_pre.json",
              "interview_post.json", "judgment.json"):
    p = rd / fname
    assert p.exists(), f"missing artifact: {p}"
    print(f"   OK {p.name}  ({p.stat().st_size} bytes)")

st = json.loads((rd / "state.json").read_text())
assert st["state"] == "done", f"state did not reach 'done': {st}"

# PiSSA-specific: confirm kind metadata is set in the checkpoint
from safetensors import safe_open
with safe_open(str(rd / "adapter.safetensors"), framework="pt") as f:
    meta = f.metadata()
assert meta.get("kind") == "pissa", f"expected kind=pissa, got {meta}"
print(f"   OK adapter.kind={meta['kind']} r={meta['r']} selection={meta.get('selection_score')}")

print(f"\n=== smoke-pissa PASS — state={st['state']} signed_C={r['signed_C']:+.4f} ===")
PYEOF

echo
echo "smoke-pissa: PASS — slug=$SLUG"
ls "$SLUG/round00/"
