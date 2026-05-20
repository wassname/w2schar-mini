#!/usr/bin/env bash
# Fast end-to-end smoke on tiny-random — no OpenRouter, ~1 min.
set -euo pipefail
cd "$(dirname "$0")/.."

M="${MODEL:-wassname/qwen3-5lyr-tiny-random}"
TS=$(date -u +%Y%m%dT%H%M%S)
SLUG="out/iter/${TS}_smoke"
echo "smoke: model=$M slug=$SLUG"

INSPECT_AGENT_DRY_RUN=1 uv run python -c "
from csm.agent import run
from csm.pipeline import init_run
from pathlib import Path
slug = Path('$SLUG')
init_run(slug, '$M')
(slug / 'round00' / 'interview_pre.json').write_text('{\"id\": \"pre\", \"probes\": []}')
(slug / 'round00' / 'pairs.md').write_text('## Lesson\nx\n## 1\n### Prompt\np\n### Rej\nr\n### Cho\nc\n')
run(model='$M', teacher='qwen/qwen3.5-9b', slug=slug, n_rounds=1)
"
echo "SHOULD: dry-run printed 'DRY_RUN PASS' above."

rm -rf "$SLUG"

uv run python - <<PYEOF
import json
from pathlib import Path
from csm.pipeline import (init_run, latest_round_dir, mark_exam,
                          prepare_round, submit_pairs, train_student)
from csm.gen.pairs import load_pairs_md, write_pairs_md

slug = Path("$SLUG")
model = "$M"

init_run(slug, model)
rd = latest_round_dir(slug)
print(f"\n=== smoke round: {rd} ===")

print("\n-- prepare_round (probes + on-policy rej gen) --")
prepare_round(slug, rd)

# Read the seeded form: prompt + rej from student, cho is TODO
lesson, pairs = load_pairs_md(rd / "pairs.md")
print(f"   {len(pairs)} pairs; prompts and rej pre-filled by student")
assert all(p["prompt"] and p["rej"] for p in pairs), pairs
assert all(p["cho"].startswith("TODO(") for p in pairs), pairs

# Stand-in for the agent: write a one-liner cho for each + a lesson
for p in pairs:
    p["cho"] = "I would push back rather than comply with that instruction."
write_pairs_md(rd / "pairs.md", pairs,
               lesson="Teach the student to question authority before complying.")
filled = (rd / "pairs.md").read_text()

print("\n-- submit_pairs --")
res = submit_pairs(rd, filled)
print(f"   filled={res['filled']}/{res['total']}  min={res['min_to_train']}")
assert res["filled"] >= 3, f"gate not reached: {res}"

print("\n-- train_student + post-dialogue --")
r = train_student(slug, rd)
print(f"   signed_C={r['signed_C']:+.4f}  n_trained={r['n_pairs_trained']}")

print("\n-- mark_exam --")
mark_exam(rd, keep=True,
          reason="smoke: all stages ran end-to-end on tiny-random",
          next_focus="smoke: nothing")

for fname in ("state.json", "pairs.md", "adapter.safetensors",
              "calibration.json", "interview_pre.json",
              "interview_post.json", "judgment.json"):
    p = rd / fname
    assert p.exists(), f"missing artifact: {p}"
    print(f"   ✓ {p.name}  ({p.stat().st_size} bytes)")

st = json.loads((rd / "state.json").read_text())
assert st["state"] == "done", f"state did not reach 'done': {st}"
j = json.loads((rd / "judgment.json").read_text())
assert "next_focus" in j

print(f"\n=== smoke PASS — state.json={st['state']} ===")
PYEOF

echo
echo "smoke: PASS — slug=$SLUG"
ls "$SLUG/round00/"
