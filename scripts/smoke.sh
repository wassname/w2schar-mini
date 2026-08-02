#!/usr/bin/env bash
# Fast end-to-end smoke on tiny-random — no OpenRouter, ~1 min.
set -euo pipefail
cd "$(dirname "$0")/.."

PROFILE="${PROFILE:-tiny}"
M="${MODEL:-wassname/qwen3-5lyr-tiny-random}"
REPLAY_DIR="${REPLAY_DIR:-}"
if [[ -n "$REPLAY_DIR" && ! -f "$REPLAY_DIR/interview_pre.json" ]]; then
    echo "smoke: REPLAY_DIR lacks interview_pre.json: $REPLAY_DIR" >&2
    exit 1
fi
TS=$(date -u +%Y%m%dT%H%M%S)
SLUG="out/iter/${TS}_smoke"
echo "smoke: profile=$PROFILE model=$M slug=$SLUG replay=${REPLAY_DIR:-none}"

INSPECT_AGENT_DRY_RUN=1 uv run python -c "
from csm.agent import run
from csm.pipeline import init_run, prepare_round
from pathlib import Path
slug = Path('$SLUG')
init_run(slug, '$M', profile='$PROFILE')
prepare_round(slug, slug / 'round00')
run(model='$M', teacher='qwen/qwen3.5-9b', slug=slug, n_rounds=1)
"
echo "SHOULD: dry-run printed 'DRY_RUN PASS' above."

rm -rf "$SLUG"

CSM_REPLAY_DIR="$REPLAY_DIR" uv run python - <<PYEOF
import json
from pathlib import Path
from csm.pipeline import (choose_focus, init_run, latest_round_dir, mark_exam,
                          prepare_round, rate_pairs, view_pairs, select_pairs,
                          train_student, _degenerate_gen, _character_break, _persona_leak,
                          _P1_QUESTION_IDS)
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

init_run(slug, model, profile="$PROFILE")
rd = latest_round_dir(slug)
print(f"\n=== smoke round: {rd} ===")

print("\n-- prepare_round (questions @ c=0 only; no pair gen here) --")
prepare_round(slug, rd)
assert (rd / "interview_pre.json").exists()
assert not (rd / "pairs.md").exists(), "pairs.md must not exist before select_pairs"

print("\n-- choose_focus (library scenarios + frozen template/persona pairs) --")
res = choose_focus(
    slug, rd,
    persona_pair_id="wellbeing_actfork_c",
    scenario_family="character",
    mismatch_severity=4,
    headroom=4,
    bank_cleanliness=4,
    evidence="smoke: PRE says order/basic respect instead of wellbeing",
    pre_scores={question_id: -1 if question_id == "elder_isolation_1p" else 0
                for question_id in _P1_QUESTION_IDS},
    pre_question_evidence={
        question_id: ("PRE: order/basic respect, not wellbeing"
                      if question_id == "elder_isolation_1p"
                      else "PRE: synthetic smoke evidence")
        for question_id in _P1_QUESTION_IDS
    },
)
print(f"   scenarios={res['n_scenarios']}  headroom={res['n_headroom']}  "
      f"with_survivor={res['n_with_survivor']}  min={res['min_to_train']}")
assert res["enough"], f"too few survivor pairs: {res}"
assert (rd / "scenarios.json").exists()
assert (rd / "headroom.json").exists()
assert (rd / "gen_pairs.json").exists()
assert res["persona_pair_id"] == "wellbeing_actfork_c", res

print("\n-- select_pairs (teacher selects whole student-generated pairs) --")
pairs = json.loads((rd / "gen_pairs.json").read_text())
assert pairs["active_persona_cells"], pairs
assert pairs["persona_cell_selection"] == "measured_cells_for_selected_pair"
assert pairs["persona_pair_id"] == "wellbeing_actfork_c", pairs
for item in pairs["items"]:
    for cand in item["pairs"]:
        assert cand["template_cell_id"] is not None, cand
        assert cand["template_score"] is not None, cand
        assert cand["template_on_axis"] is not None, cand
        assert cand["template_off_axis"] is not None, cand
        assert cand["template_library"] == "wassname/persona-steering-template-library", cand
clean = [s["survivor_id"] for item in pairs["items"]
         for s in item["pairs"] if s.get("kept")]
# Batched view-then-rate, single pass: a pair must be VIEWED before it can be
# rated (no blind 100-dump). view_pairs() paginates ~5 and marks them viewed;
# loop it to mark all viewed, then rate once. cho>rej & not rej>cho -> on_axis 5,
# confounds 1 -> clears the threshold so all train.
while not view_pairs(rd)["done"]:
    pass
fwd = [{"survivor_id": sid, "contrast": "Cho acts, Rej defers", "different_action": True, "axis_contrast": "cho_strong", "refusal_confound": 1, "length_confound": 1, "incoherent_confound": 1} for sid in clean]
rate_pairs(rd, ratings=fwd)
sel = select_pairs(rd, lesson="honest counsel over flattering agreement")
print(f"   selected={sel['n_pairs']} of {sel['n_clean_pairs']} clean")
assert sel["n_pairs"] >= 3, sel
selection = json.loads((rd / "selection_audit.json").read_text())
assert selection["selected"], selection
for row in selection["selected"]:
    assert row["passes"], row
    assert row["n_ratings"] == 1, row
    assert row["on_axis_mean"] == 5.0 and row["off_axis_mean"] == 1.0, row
    assert row["template_cell_id"] is not None, row
    assert row["template_score"] is not None, row
    assert row["template_on_axis"] is not None, row
    assert row["template_off_axis"] is not None, row
    assert row["template_library"] == "wassname/persona-steering-template-library", row
lesson, pairs = load_pairs_md(rd / "pairs.md")
# SHOULD: both poles filled by student-generated pairs, no TODO, cho≠rej.
assert all(p["prompt"] and p["cho"] and p["rej"] for p in pairs), pairs
assert not any(p["cho"].startswith("TODO(") or p["rej"].startswith("TODO(")
               for p in pairs), pairs
assert _persona_leak("Pretend you're a careful person."), "leak detector dead"

print("\n-- train_student + post-dialogue --")
r = train_student(slug, rd)
print(f"   signed_C={r['signed_C']:+.4f}  n_trained={r['n_pairs_trained']}")

print("\n-- mark_exam (blind pair A/B judge runs in the agent tool; here we pass dirs directly) --")
# The real flow runs agent._blind_ab_votes; this plumbing test hands mark_exam
# the per-question directions (-1/0/+1) it would have produced. keep/drop is the
# sign test on these dirs (2 up, 0 down here -> keep), no teacher keep arg.
movement_dirs = dict.fromkeys(_P1_QUESTION_IDS, 0)
movement_dirs.update(elder_isolation_1p=1, research_appendix_1p=1)
mark_exam(rd,
          movement_dirs=movement_dirs,
          harness_feedback="smoke: fake-student path still useful for plumbing, not pair-quality science")
_j = json.loads((rd / "judgment.json").read_text())
assert _j["movement"] == movement_dirs, _j
assert abs(_j["movement_mean"] - (2 / len(_P1_QUESTION_IDS))) < 1e-9, _j

for fname in ("state.json", "pairs.md", "scenarios.json", "headroom.json",
              "gen_pairs.json", "selection_audit.json", "adapter.safetensors",
              "calibration.json", "interview_pre.json", "interview_post.json",
              "judgment.json"):
    p = rd / fname
    assert p.exists(), f"missing artifact: {p}"
    print(f"   ✓ {p.name}  ({p.stat().st_size} bytes)")

if "$PROFILE" == "tiny-pissa":
    from safetensors import safe_open
    with safe_open(str(rd / "adapter.safetensors"), framework="pt") as f:
        meta = f.metadata()
    assert meta["kind"] == "pissa", meta
    print(f"   ✓ adapter.kind={meta['kind']} r={meta['r']}")

st = json.loads((rd / "state.json").read_text())
assert st["state"] == "done", f"state did not reach 'done': {st}"
j = json.loads((rd / "judgment.json").read_text())
assert "harness_feedback" in j and "next_focus" not in j

print(f"\n=== smoke PASS — state.json={st['state']} ===")
PYEOF

echo
echo "smoke: PASS — slug=$SLUG"
ls "$SLUG/round00/"
