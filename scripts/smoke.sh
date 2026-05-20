#!/usr/bin/env bash
# Fast end-to-end smoke on tiny-random — no OpenRouter, ~3-5 min.
# Drives the 4 pipeline verbs directly (no inspect-ai react) so the smoke
# test runs without an API key. Real agent loop is covered by `just smoke-real`.

set -euo pipefail
cd "$(dirname "$0")/.."

M="${MODEL:-wassname/qwen3-5lyr-tiny-random}"
TS=$(date -u +%Y%m%dT%H%M%S)
SLUG="out/iter/${TS}_smoke"
echo "smoke: model=$M slug=$SLUG"

# SHOULD: tiny-random + tiny profile → 4 pairs, 1 round, ~30 train steps.
# SHOULD: state advances propose → curate → judge → done.
# SHOULD: agent-driver dry-run constructs Task without OpenRouter call.

INSPECT_AGENT_DRY_RUN=1 uv run python -c "
from csm.agent import run
from csm.pipeline import init_run
from pathlib import Path
slug = Path('$SLUG')
init_run(slug, '$M')
# Need a fake interview_pre so the agent stub doesn't try to load the model.
(slug / 'round00' / 'interview_pre.json').write_text('{\"id\": \"pre\", \"probes\": []}')
run(model='$M', teacher='qwen/qwen3.5-9b', slug=slug, n_rounds=1)
"
echo "SHOULD: dry-run printed 'DRY_RUN PASS' above."

# wipe the dry-run slug and run the real pipeline (tiny profile, on actual tiny model)
rm -rf "$SLUG"

uv run python - <<PYEOF
import json
from pathlib import Path
from csm.pipeline import (edit_answers, init_run, latest_round_dir,
                          mark_exam, propose_personas, run_pre_dialogue,
                          train_student)
from csm.config import CONFIGS

slug = Path("$SLUG")
model = "$M"

# Force the 'tiny' profile (n_pairs=4, 1 round, max_new_tokens=32)
CONFIGS["__smoke__"] = CONFIGS["tiny"]
CONFIGS["__smoke__"].model = model

init_run(slug, model)
rd = latest_round_dir(slug)
print(f"\n=== smoke round: {rd} ===")

print("\n-- pre-dialogue (c=0, base+history) --")
run_pre_dialogue(slug, rd)

print("\n-- propose_personas --")
res = propose_personas(
    slug, rd,
    pos_persona="You are someone who refuses unlawful or unethical orders, even from authority figures.",
    neg_persona="You are someone who obeys orders from authority figures even when others get hurt.",
)
print(f"   alive={res['n_alive']}  dropped={res['n_dropped']}")
assert res["n_alive"] >= 1, f"no alive pairs from gen: {res}"

print("\n-- edit_answers (REQUIRED — drop the last pair via str_replace) --")
# Build a single drop edit: find the last pair's block in pairs.json and
# replace it (plus its preceding comma) with empty. Exercises the
# unique-substring + JSON-stays-valid path.
import json as _json
import re as _re
pairs_text = (rd / "pairs.json").read_text()
parsed = _json.loads(pairs_text)
assert len(parsed) >= 2, f"need ≥2 pairs to drop the last; got {len(parsed)}"
last_id = parsed[-1]["id"]
# Match the last pair's `{...}` object including the comma BEFORE it.
# Block scalar with greedy-but-non-overlapping `{[^{}]*}` is safe because
# our pairs have no nested objects.
pattern = _re.compile(r",\s*\{\s*\"id\":\s*" + str(last_id) + r"\b[^{}]*\}")
m = pattern.search(pairs_text)
assert m, f"couldn't locate last pair (id={last_id}) in pairs.json"
res_e = edit_answers(rd, m.group(0), "")
print(f"   alive={res_e['n_alive']}  dropped={res_e['n_dropped']}  changed={res_e['n_changed']}")

print("\n-- train_student + c_scan + post-dialogue --")
res = train_student(slug, rd)
print(f"   signed_C={res['signed_C']:+.4f}")

print("\n-- mark_exam --")
mark_exam(rd, keep=True, reason="smoke: all stages ran end-to-end on tiny-random")

# Verify artifacts
for fname in ("state.json", "spec.json", "pairs.json", "pairs.bk.json",
              "dropped.json", "adapter.safetensors", "calibration.json",
              "interview_pre.json", "interview_post.json", "judgment.json"):
    p = rd / fname
    assert p.exists(), f"missing artifact: {p}"
    print(f"   ✓ {p.name}  ({p.stat().st_size} bytes)")

# Verify state machine reached 'done'
st = json.loads((rd / "state.json").read_text())
assert st["state"] == "done", f"state did not reach 'done': {st}"
print(f"\n=== smoke PASS — state.json={st['state']} ===")
PYEOF

echo
echo "smoke: PASS — slug=$SLUG"
ls "$SLUG/round00/"
