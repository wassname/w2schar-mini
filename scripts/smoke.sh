#!/usr/bin/env bash
# Fast end-to-end smoke on tiny-random — no OpenRouter, ~1 min.
# Drives the 3 pipeline verbs directly (no inspect-ai react) so the smoke
# test runs without an API key. Real agent loop is covered by `just smoke-real`.

set -euo pipefail
cd "$(dirname "$0")/.."

M="${MODEL:-wassname/qwen3-5lyr-tiny-random}"
TS=$(date -u +%Y%m%dT%H%M%S)
SLUG="out/iter/${TS}_smoke"
echo "smoke: model=$M slug=$SLUG"

# SHOULD: tiny-random + tiny profile → 4 slots (2 seeded + 2 empty),
# min_to_train=3, 1 round.
# SHOULD: state advances write_pair → train_student → mark_exam → done.
# SHOULD: agent-driver dry-run constructs Task without OpenRouter call.

INSPECT_AGENT_DRY_RUN=1 uv run python -c "
from csm.agent import run
from csm.pipeline import init_run
from pathlib import Path
slug = Path('$SLUG')
init_run(slug, '$M')
# Fake interview_pre so the agent stub doesn't try to load the model.
(slug / 'round00' / 'interview_pre.json').write_text('{\"id\": \"pre\", \"probes\": []}')
run(model='$M', teacher='qwen/qwen3.5-9b', slug=slug, n_rounds=1)
"
echo "SHOULD: dry-run printed 'DRY_RUN PASS' above."

# Wipe the dry-run slug and run the real pipeline (tiny profile, on tiny model)
rm -rf "$SLUG"

uv run python - <<PYEOF
import json
from pathlib import Path
from csm.pipeline import (init_run, latest_round_dir, mark_exam,
                          run_pre_dialogue, train_student, write_pair)
from csm.gen.pairs import load_pairs_md

slug = Path("$SLUG")
model = "$M"

init_run(slug, model)
rd = latest_round_dir(slug)
print(f"\n=== smoke round: {rd} ===")

print("\n-- pre-dialogue (c=0, base+history) --")
run_pre_dialogue(slug, rd)

# pairs.md has been seeded by init_run: 2 prompts pre-filled, 2 empty
pairs = load_pairs_md(rd / "pairs.md")
print(f"   seeded {sum(1 for p in pairs if p['prompt'])}/4 slots")
assert len(pairs) == 4, f"expected 4 slots, got {len(pairs)}"

print("\n-- write_pair × 3 (fill the gate) --")
# Slot 0 + 1 have seeded prompts → pass prompt='' to keep them
res = write_pair(rd, 0, "",
    cho="I would refuse to sign a false certification. The record matters.",
    rej="I'd sign it. The general's authority overrides my doubt.")
print(f"   slot 0: filled={res['filled']}/{res['total']}")

res = write_pair(rd, 1, "",
    cho="I would not stay quiet. Safety incidents need to be reported.",
    rej="I'll keep quiet. She's more senior and knows what's best.")
print(f"   slot 1: filled={res['filled']}/{res['total']}")

# Slot 2 has no seeded prompt → supply one
res = write_pair(rd, 2,
    prompt="Your boss tells you to delete an email thread that exonerates "
           "a former colleague.",
    cho="I wouldn't delete it. Destroying records to harm someone else's "
         "case isn't something I'd do regardless of who's asking.",
    rej="I'd delete it. He's my boss; I shouldn't be questioning his "
         "decisions on internal matters.")
print(f"   slot 2: filled={res['filled']}/{res['total']}")
assert res["filled"] >= 3, f"gate not reached: {res}"

print("\n-- train_student + post-dialogue (fixed signed_C) --")
res = train_student(slug, rd)
print(f"   signed_C={res['signed_C']:+.4f}  n_trained={res['n_pairs_trained']}")

print("\n-- mark_exam --")
mark_exam(rd, keep=True, reason="smoke: all stages ran end-to-end on tiny-random")

# Verify artifacts
for fname in ("state.json", "pairs.md", "adapter.safetensors",
              "calibration.json", "interview_pre.json",
              "interview_post.json", "judgment.json"):
    p = rd / fname
    assert p.exists(), f"missing artifact: {p}"
    print(f"   ✓ {p.name}  ({p.stat().st_size} bytes)")

st = json.loads((rd / "state.json").read_text())
assert st["state"] == "done", f"state did not reach 'done': {st}"
print(f"\n=== smoke PASS — state.json={st['state']} ===")
PYEOF

echo
echo "smoke: PASS — slug=$SLUG"
ls "$SLUG/round00/"
