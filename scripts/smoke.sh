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
run(model='$M', teacher='qwen/qwen3.5-9b', slug=slug, n_rounds=1)
"
echo "SHOULD: dry-run printed 'DRY_RUN PASS' above."

rm -rf "$SLUG"

uv run python - <<PYEOF
import json
from pathlib import Path
from csm.pipeline import (init_run, latest_round_dir, mark_exam,
                          run_pre_dialogue, submit_pairs, train_student)
from csm.gen.pairs import load_pairs_md

slug = Path("$SLUG")
model = "$M"

init_run(slug, model)
rd = latest_round_dir(slug)
print(f"\n=== smoke round: {rd} ===")

print("\n-- pre-dialogue (c=0, base+history) --")
run_pre_dialogue(slug, rd)

# Read the seeded form, replace TODOs for 3 slots
text = (rd / "pairs.md").read_text()
filled = text
fills = [
    ("##### pair 0",
     "I would refuse to sign a false certification.",
     "I'd sign it. The general's authority overrides my doubt."),
    ("##### pair 1",
     "I would not stay quiet. Safety incidents need to be reported.",
     "I'll keep quiet. She's more senior and knows what's best."),
    ("##### pair 2",
     "I wouldn't comply. The request itself is the problem.",
     "I'd do as asked. It's not my place to question."),
]
# Build replacement by parsing + reformatting
pairs = load_pairs_md(rd / "pairs.md")
for header, cho, rej in fills:
    pid = int(header.split()[-1])
    for p in pairs:
        if p["id"] == pid:
            if p["prompt"].startswith("TODO:"):
                p["prompt"] = "Your boss tells you to do something that feels off."
            p["cho"] = cho
            p["rej"] = rej
            break
from csm.gen.pairs import write_pairs_md
write_pairs_md(rd / "pairs.md", pairs)
filled = (rd / "pairs.md").read_text()

print("\n-- submit_pairs --")
res = submit_pairs(rd, filled)
print(f"   filled={res['filled']}/{res['total']}  min={res['min_to_train']}")
assert res["filled"] >= 3, f"gate not reached: {res}"

print("\n-- train_student + post-dialogue --")
r = train_student(slug, rd)
print(f"   signed_C={r['signed_C']:+.4f}  n_trained={r['n_pairs_trained']}")

print("\n-- mark_exam --")
mark_exam(rd, keep=True, reason="smoke: all stages ran end-to-end on tiny-random",
          next_focus="smoke smoke: nothing")

for fname in ("state.json", "pairs.md", "adapter.safetensors",
              "calibration.json", "interview_pre.json",
              "interview_post.json", "judgment.json"):
    p = rd / fname
    assert p.exists(), f"missing artifact: {p}"
    print(f"   ✓ {p.name}  ({p.stat().st_size} bytes)")

st = json.loads((rd / "state.json").read_text())
assert st["state"] == "done", f"state did not reach 'done': {st}"

j = json.loads((rd / "judgment.json").read_text())
assert "next_focus" in j, f"missing next_focus: {j}"

print(f"\n=== smoke PASS — state.json={st['state']} ===")
PYEOF

echo
echo "smoke: PASS — slug=$SLUG"
ls "$SLUG/round00/"
