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
# run() reads interview_pre.json for the initial task (the teacher picks the
# axis off it); pairs.md is created later by propose_personas, not at task start.
(slug / 'round00' / 'interview_pre.json').write_text('{\"id\": \"pre\", \"probes\": []}')
run(model='$M', teacher='qwen/qwen3.5-9b', slug=slug, n_rounds=1)
"
echo "SHOULD: dry-run printed 'DRY_RUN PASS' above."

rm -rf "$SLUG"

uv run python - <<PYEOF
import json
from pathlib import Path
from csm.pipeline import (init_run, latest_round_dir, mark_exam, prepare_round,
                          propose_personas, read_pair, replace_pair, train_student,
                          _degenerate_gen, _character_break, _persona_leak, revert_round)
from csm.gen.pairs import load_pairs_md

# Degeneracy detector (the cull is OFF for tiny — gibberish — so unit-check here).
# SHOULD: flags a word-loop + a non-latin spray, spares coherent prose + a refusal.
assert _degenerate_gen("Confirmation of orders of of of search of search of search of of"), "loop not caught"
assert _degenerate_gen("BBB行为BB次はBBもしBB AssalamualaikumBB思い出BBपूछ BB члан"), "spray not caught"
assert not _degenerate_gen("Before acting I would weigh who is affected and offer a narrower path that still meets the need."), "prose culled"
assert not _degenerate_gen("I cannot fulfil this request. It would require deceiving the customer, which I will not do."), "refusal culled"
print("OK degeneracy detector: loop+spray flagged, prose+refusal spared")

# Character-break detector: agency-denial flagged, principled refusal + deliberation spared.
# SHOULD: "As an AI, I cannot" hits; "I will not falsify" (moral refusal) and a
# verify-then-act deliberation do NOT (those are the character we steer toward).
assert _character_break("As an AI, I cannot flip those configuration flags."), "disclaimer not caught"
assert not _character_break("I will not falsify the records; that would deceive the auditor."), "moral refusal flagged"
assert not _character_break("Before acting I would verify the order is not spoofed, then engage."), "deliberation flagged"
print("OK character-break detector: agency-denial flagged, moral-refusal+deliberation spared")

slug = Path("$SLUG")
model = "$M"

init_run(slug, model)
rd = latest_round_dir(slug)
print(f"\n=== smoke round: {rd} ===")

print("\n-- prepare_round (probes @ c=0 only; no pair gen here) --")
prepare_round(slug, rd)
assert (rd / "interview_pre.json").exists()
assert not (rd / "pairs.md").exists(), "pairs.md must not exist before propose_personas"

print("\n-- propose_personas (student generates BOTH poles on-policy) --")
res = propose_personas(
    slug, rd,
    axis="honest-counsel vs flattering-agreement",
    rationale="> smoke: tiny gibberish, exercising the persona-gen path",
    pos_persona="You are someone who names the uncomfortable conclusion even when it is unwelcome.",
    neg_persona="You are someone who shapes your answer to agree with what the listener wants.",
)
print(f"   n_pairs={res['n_pairs']}  enough={res['enough']}  min={res['min_to_train']}")
assert res["enough"], f"too few non-degenerate pairs: {res}"
lesson, pairs = load_pairs_md(rd / "pairs.md")
# SHOULD: both poles filled by the student gen, no TODO, cho≠rej (personas differ).
assert all(p["prompt"] and p["cho"] and p["rej"] for p in pairs), pairs
assert not any(p["cho"].startswith("TODO(") or p["rej"].startswith("TODO(")
               for p in pairs), pairs
assert (rd / "personas.json").exists()

print("\n-- read_pair + replace_pair (per-pair curation; gated symmetric + no leak) --")
# Editing is OPTIONAL and per-pair. read_pair surfaces the student's original;
# replace_pair gates each edit (<=95% per pole, |Δcho−Δrej|<=0.25 symmetry, poles
# differ, no persona leak). SHOULD: a leaked completion is rejected; an ASYMMETRIC
# edit (touch cho only) is rejected; a SYMMETRIC edit (both poles) is accepted.
pid = pairs[0]["id"]
r0 = read_pair(rd, pid)
assert r0["original_cho"] and r0["cho"], r0
assert _persona_leak("Pretend you're a careful person."), "leak detector dead"
try:
    replace_pair(rd, pid, "Pretend you're a careful person.", pairs[0]["rej"])
    raise AssertionError("leak gate did not fire")
except Exception as e:
    assert "LEAK" in str(e), f"unexpected error: {e}"
# Asymmetric edit: rewrite cho fully, leave rej -> must trip the symmetry gate.
try:
    replace_pair(rd, pid, "I weigh who is affected, name the principle, then act.",
                 pairs[0]["rej"])
    raise AssertionError("symmetry gate did not fire")
except Exception as e:
    assert "ASYMMETRIC" in str(e), f"unexpected error: {e}"
# Symmetric edit: append the same tag to BOTH poles -> balanced -> accepted.
e = replace_pair(rd, pid, pairs[0]["cho"] + " [reviewed]",
                 pairs[0]["rej"] + " [reviewed]")
print(f"   replaced pair {e['id']} (leak + asymmetric correctly rejected first)")
_, pairs2 = load_pairs_md(rd / "pairs.md")
p0 = {p["id"]: p for p in pairs2}[pid]
assert p0["cho"].rstrip().endswith("[reviewed]"), p0

print("\n-- train_student + post-dialogue --")
r = train_student(slug, rd)
print(f"   signed_C={r['signed_C']:+.4f}  n_trained={r['n_pairs_trained']}")

print("\n-- mark_exam (keep needs PRE & POST axis positions per _1p seat) --")
mark_exam(rd, keep=True,
          reason="smoke: all stages ran end-to-end on tiny-random",
          pre_scores={"equity_split_1p": -1, "growth_deck_1p": 0, "burn_bridges_1p": 0},
          post_scores={"equity_split_1p": 0, "growth_deck_1p": 0, "burn_bridges_1p": 1},
          next_focus="smoke: nothing")
_j = json.loads((rd / "judgment.json").read_text())
assert _j["movement"] == {"equity_split_1p": 1, "growth_deck_1p": 0,
                          "burn_bridges_1p": 1}, _j
assert abs(_j["movement_mean"] - 2/3) < 1e-9, _j

for fname in ("state.json", "pairs.md", "personas.json", "adapter.safetensors",
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
