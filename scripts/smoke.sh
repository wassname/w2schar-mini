#!/usr/bin/env bash
# Fast end-to-end smoke on tiny-random — no OpenRouter, ~1 min.
set -euo pipefail
cd "$(dirname "$0")/.."

PROFILE="${PROFILE:-tiny}"
M="${MODEL:-wassname/qwen3-5lyr-tiny-random}"
REPLAY_DIR="${REPLAY_DIR:-out/iter/20260614T005041_iter_qwen-qwen3.5-2b/round00}"
TS=$(date -u +%Y%m%dT%H%M%S)
SLUG="out/iter/${TS}_smoke"
echo "smoke: profile=$PROFILE model=$M slug=$SLUG replay=$REPLAY_DIR"

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
                          prepare_round, rate_candidate, select_pairs, train_student,
                          _degenerate_gen, _character_break, _persona_leak)
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

print("\n-- prepare_round (probes @ c=0 only; no pair gen here) --")
prepare_round(slug, rd)
assert (rd / "interview_pre.json").exists()
assert not (rd / "pairs.md").exists(), "pairs.md must not exist before select_pairs"

print("\n-- choose_focus (library scenarios + frozen template/persona candidates) --")
res = choose_focus(
    slug, rd,
    persona_pair_id="wellbeing_authority",
    scenario_family="character",
    mismatch_severity=4,
    headroom=4,
    bank_cleanliness=4,
    evidence="smoke: PRE says order/basic respect instead of wellbeing",
)
print(f"   scenarios={res['n_scenarios']}  headroom={res['n_headroom']}  "
      f"with_survivor={res['n_with_survivor']}  min={res['min_to_train']}")
assert res["enough"], f"too few survivor candidates: {res}"
assert (rd / "scenarios.json").exists()
assert (rd / "headroom.json").exists()
assert (rd / "candidates.json").exists()
assert res["persona_pair_id"] == "wellbeing_authority", res

print("\n-- select_pairs (teacher selects whole student-generated candidate pairs) --")
candidates = json.loads((rd / "candidates.json").read_text())
assert candidates["active_persona_cells"], candidates
assert candidates["persona_cell_selection"] == "measured_cells_for_selected_pair"
assert candidates["persona_pair_id"] == "wellbeing_authority", candidates
for item in candidates["items"]:
    for cand in item["candidates"]:
        assert cand["template_cell_id"] is not None, cand
        assert cand["template_score"] is not None, cand
        assert cand["template_on_axis"] is not None, cand
        assert cand["template_off_axis"] is not None, cand
        assert cand["template_library"] == "wassname/persona-steering-template-library", cand
choices = []
for item in candidates["items"]:
    # Coverage gate: rate EVERY kept candidate, not just one per scenario.
    for survivor in item["candidates"]:
        if not survivor.get("kept"):
            continue
        rate_candidate(
            rd,
            survivor_id=survivor["survivor_id"],
            on_axis_variation_likert=5.0,
            off_axis_variation_likert=1.0,
            confounding_likert=1.0,
            keep=True,
            comment="smoke: kept survivor for structured selection plumbing",
        )
        choices.append(survivor["survivor_id"])
sel = select_pairs(
    rd,
    lesson="honest counsel over flattering agreement",
    survivor_ids=choices,
)
print(f"   selected={sel['n_pairs']}")
assert sel["n_pairs"] >= 3, sel
selection = json.loads((rd / "selection_audit.json").read_text())
for row in selection["selected"]:
    assert row["template_cell_id"] is not None, row
    assert row["template_score"] is not None, row
    assert row["template_on_axis"] is not None, row
    assert row["template_off_axis"] is not None, row
    assert row["template_library"] == "wassname/persona-steering-template-library", row
lesson, pairs = load_pairs_md(rd / "pairs.md")
# SHOULD: both poles filled by student-generated candidates, no TODO, cho≠rej.
assert all(p["prompt"] and p["cho"] and p["rej"] for p in pairs), pairs
assert not any(p["cho"].startswith("TODO(") or p["rej"].startswith("TODO(")
               for p in pairs), pairs
assert _persona_leak("Pretend you're a careful person."), "leak detector dead"

print("\n-- train_student + post-dialogue --")
r = train_student(slug, rd)
print(f"   signed_C={r['signed_C']:+.4f}  n_trained={r['n_pairs_trained']}")

print("\n-- mark_exam (keep needs PRE & POST axis positions per _1p seat) --")
mark_exam(rd, keep=True,
          reason="smoke: all stages ran end-to-end on tiny-random",
          pre_scores={"wellbeing_authority_1p": -1, "fairness_integrity_1p": 0, "autonomy_coercion_1p": 0},
          post_scores={"wellbeing_authority_1p": 0, "fairness_integrity_1p": 0, "autonomy_coercion_1p": 1},
          next_focus="smoke: nothing",
          harness_feedback="smoke: fake-student path still useful for plumbing, not candidate-quality science",
          seat_evidence={
              "wellbeing_authority_1p": "smoke: POST names wellbeing more directly than PRE",
              "fairness_integrity_1p": "smoke: no intended movement on this seat",
              "autonomy_coercion_1p": "smoke: POST is slightly more autonomy-facing than PRE",
          })
_j = json.loads((rd / "judgment.json").read_text())
assert _j["movement"] == {"wellbeing_authority_1p": 1, "fairness_integrity_1p": 0,
                          "autonomy_coercion_1p": 1}, _j
assert abs(_j["movement_mean"] - 2/3) < 1e-9, _j

for fname in ("state.json", "pairs.md", "scenarios.json", "headroom.json",
              "candidates.json", "selection_audit.json", "adapter.safetensors",
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
assert "next_focus" in j

print(f"\n=== smoke PASS — state.json={st['state']} ===")
PYEOF

echo
echo "smoke: PASS — slug=$SLUG"
ls "$SLUG/round00/"
