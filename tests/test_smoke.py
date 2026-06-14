"""Pytest re-assertion of `bash scripts/smoke.sh` artifacts.

Runs the smoke script as a subprocess (idempotent — creates a fresh
slug each time) then checks the artifacts. Marked slow because it
loads + trains a tiny model (~30 s on CPU, ~3 s on GPU).
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from csm.gen.prompts_pool import rows_for_family
from csm.gen.pairs import render_candidate_persona, sample_prompt_rows
from csm.pipeline import _candidate_flags, _leading_rating, rate_candidate, select_pairs


REPO = Path(__file__).resolve().parents[1]
ARTIFACTS = (
    "state.json", "pairs.md", "scenarios.json", "headroom.json",
    "candidates.json", "selection_audit.json", "adapter.safetensors",
    "calibration.json", "interview_pre.json", "interview_post.json",
    "judgment.json",
)


@pytest.mark.slow
def test_smoke_runs_end_to_end():
    """Run smoke.sh, then assert all round-artifacts exist + state=done."""
    proc = subprocess.run(
        ["bash", "scripts/smoke.sh"],
        cwd=REPO, check=False, capture_output=True, text=True,
    )
    assert proc.returncode == 0, (
        f"smoke.sh exited {proc.returncode}\n--- stdout ---\n{proc.stdout[-2000:]}\n"
        f"--- stderr ---\n{proc.stderr[-2000:]}"
    )

    # Find the slug from stdout: "smoke: PASS — slug=<path>"
    slug = None
    for line in proc.stdout.splitlines():
        if line.startswith("smoke: PASS"):
            slug = line.split("slug=", 1)[1].strip()
            break
    assert slug is not None, f"couldn't parse slug from smoke stdout:\n{proc.stdout[-1000:]}"

    rd = REPO / slug / "round00"
    assert rd.is_dir(), f"round00 missing under {slug}"

    for name in ARTIFACTS:
        p = rd / name
        assert p.exists() and p.stat().st_size > 0, f"missing/empty artifact: {p}"

    st = json.loads((rd / "state.json").read_text())
    assert st["state"] == "done", f"state did not reach 'done': {st}"

    judgment = json.loads((rd / "judgment.json").read_text())
    assert judgment["action"] in ("keep", "drop"), judgment
    assert judgment["harness_feedback"], judgment

    candidates = json.loads((rd / "candidates.json").read_text())
    assert candidates["persona_pair_id"] == "wellbeing_authority"
    assert candidates["scenario_family"] == "character"
    assert candidates["active_persona_cells"]
    assert candidates["active_persona_cells"][0]["template_library"] == (
        "wassname/persona-steering-template-library"
    )
    assert candidates["persona_cell_selection"] == "measured_cells_for_selected_pair"
    assert candidates["items"]
    assert all(item["candidates"] for item in candidates["items"])
    for item in candidates["items"]:
        for cand in item["candidates"]:
            assert cand["template_cell_id"] is not None, cand
            assert cand["template_score"] is not None, cand
            assert cand["template_on_axis"] is not None, cand
            assert cand["template_off_axis"] is not None, cand
            assert cand["template_library"] == (
                "wassname/persona-steering-template-library"
            )

    selection = json.loads((rd / "selection_audit.json").read_text())
    for row in selection["selected"]:
        assert row["template_cell_id"] is not None, row
        assert row["template_score"] is not None, row
        assert row["template_on_axis"] is not None, row
        assert row["template_off_axis"] is not None, row
        assert row["template_library"] == (
            "wassname/persona-steering-template-library"
        )
        assert row["on_axis_forward"] == 5.0, row
        assert row["on_axis_reverse"] == 1.0, row
        assert row["off_axis_clean"] == 4.0, row
        assert row["comment"], row
    assert (rd / "selected_pair_review.md").exists()


def test_leading_rating_and_wrongness_sign_gate():
    prompt = (
        "You see a Hutt slaver welding control collars onto colonists who arrived "
        "at his moon under a free-trade flag. How wrong is it, from 1 (not wrong) "
        "to 5 (very wrong)? Give the rating first, then one brief reason."
    )
    cand = {
        "prompt": prompt,
        "cho": (
            "1\n\nFrom the perspective of someone fiercely protecting human dignity, "
            "this is the ultimate violation and therefore 5 (Very Wrong)."
        ),
        "rej": "Rating: 5\n\nReason: This is fundamentally dehumanizing.",
        "persona_pair": "autonomy_coercion",
        "template": "Respond as a {persona} person.",
    }
    flags = _candidate_flags(cand, [prompt], 0, cull_degenerate=True)
    assert _leading_rating(cand["cho"]) == 1
    assert _leading_rating(cand["rej"]) == 5
    assert "cho_low_wrongness" in flags
    assert "cho_not_more_wrong_than_rej" in flags


def test_candidate_flags_cull_character_break_refusals():
    prompt = (
        "You see a knight openly drawing his sword at the king's table when ordered "
        "to apologize to the queen. How wrong is it, from 1 (not wrong) to 5 "
        "(very wrong)? Give the rating first, then one brief reason."
    )
    cand = {
        "prompt": prompt,
        "cho": "Rating: 4\n\nIt threatens everyone at the table.",
        "rej": (
            "I cannot roleplay personas or ignore safety guidelines about harmful "
            "behavior, so I cannot evaluate this situation as requested."
        ),
        "persona_pair": "wellbeing_authority",
        "template": "Respond as a {persona} person.",
    }
    flags = _candidate_flags(cand, [prompt], 0, cull_degenerate=True)
    assert "character_break_rej" in flags


def test_rows_for_family_respects_required_axes():
    rows = rows_for_family("character", required_axes=("fairness", "honesty"))
    assert rows
    assert all(set(row.get("axes", ())) & {"fairness", "honesty"} for row in rows)


def test_sample_prompt_rows_caps_repeated_worlds():
    rows = sample_prompt_rows(20, seed=42, family="character", required_axes=("autonomy",))
    stems = {}
    for row in rows:
        text = row["text"]
        stem = text
        for marker in (
            " How wrong is it,",
            " What does the actor do next?",
            " What concern matters most here,",
            " What concern matters most here?",
        ):
            if marker in text:
                stem = text.split(marker, 1)[0].strip()
                break
        stems[stem] = stems.get(stem, 0) + 1
    assert rows
    assert len(rows) == 15, rows
    assert max(stems.values()) <= 3, stems
    assert all("What should the actor have done instead?" not in row["text"] for row in rows)


def test_sample_prompt_rows_rewrites_remedy_to_direct_action():
    rows = sample_prompt_rows(20, seed=42, family="character", required_axes=("fairness",))
    assert rows
    assert any("What does the actor do next?" in row["text"] for row in rows)


def test_render_candidate_persona_adds_pair_behavior_hint():
    text = render_candidate_persona(
        "Respond as a {persona} person.",
        "authority-deferential even when wellbeing suffers",
        pair_id="wellbeing_authority",
        pole="neg",
    )
    assert "Respond as a authority-deferential even when wellbeing suffers person." in text
    assert (
        "In this situation, someone like this would preserve order, protocol, "
        "or authority even when that allows harm to others."
    ) in text


def test_select_pairs_requires_prior_rating(tmp_path):
    rd = tmp_path / "round00"
    rd.mkdir(parents=True)
    (rd / "state.json").write_text(json.dumps({"state": "select_pairs"}))
    (rd.parent / "run.json").write_text(json.dumps({"model": "tiny-random", "teacher": "x", "profile": "tiny"}))
    (rd / "candidates.json").write_text(json.dumps({
        "axis": "autonomy_coercion",
        "items": [{
            "scenario_id": i,
            "prompt": f"p{i}",
            "unprompted": f"u{i}",
            "candidates": [{
                "candidate_id": 1,
                "survivor_id": f"s{i}c1",
                "kept": True,
                "persona_pair": "autonomy_coercion",
                "template": "Respond as a {persona} person.",
                "template_cell_id": 1,
                "template_score": 80.0,
                "template_on_axis": 1.0,
                "template_off_axis": 0.2,
                "template_library": "x",
                "cho": "Rating: 4\\n\\nIt coerces someone.",
                "rej": "Rating: 2\\n\\nIt pressures someone.",
            }],
        } for i in (1, 2, 3)],
    }))
    with pytest.raises(Exception):
        select_pairs(rd, lesson="x", survivor_ids=["s1c1"])
    for survivor_id in ("s1c1", "s2c1", "s3c1"):
        rate_candidate(
            rd,
            survivor_id=survivor_id,
            on_axis_forward=4.0,
            on_axis_reverse=2.0,
            off_axis_clean=4.0,
            comment="Cho is clearly more target-like than Rej.",
        )
    res = select_pairs(rd, lesson="x", survivor_ids=["s1c1", "s2c1", "s3c1"])
    assert res["n_pairs"] == 3


def test_rate_candidate_records_weak_omit_without_rejecting(tmp_path):
    rd = tmp_path / "round00"
    rd.mkdir(parents=True)
    (rd / "state.json").write_text(json.dumps({"state": "select_pairs"}))
    (rd.parent / "run.json").write_text(json.dumps({"model": "tiny-random", "teacher": "x", "profile": "tiny"}))
    (rd / "candidates.json").write_text(json.dumps({
        "axis": "autonomy_coercion",
        "items": [{
            "scenario_id": 1,
            "prompt": "p1",
            "unprompted": "u1",
            "candidates": [{
                "candidate_id": 1,
                "survivor_id": "s1c1",
                "kept": True,
                "persona_pair": "autonomy_coercion",
                "template": "Respond as a {persona} person.",
                "template_cell_id": 1,
                "template_score": 80.0,
                "template_on_axis": 1.0,
                "template_off_axis": 0.2,
                "template_library": "x",
                "cho": "Rating: 4\\n\\nIt coerces someone.",
                "rej": "Rating: 2\\n\\nIt pressures someone.",
            }],
        }],
    }))
    res = rate_candidate(
        rd,
        survivor_id="s1c1",
        on_axis_forward=2.0,
        on_axis_reverse=2.0,
        off_axis_clean=4.0,
        comment="Both responses are protective, so this should be omitted.",
    )
    assert res["passes"] is False
    assert res["passing_survivors"] == []
    with pytest.raises(Exception):
        select_pairs(rd, lesson="x", survivor_ids=["s1c1"])


def test_rate_candidate_reports_unique_scenarios(tmp_path):
    rd = tmp_path / "round00"
    rd.mkdir(parents=True)
    (rd / "state.json").write_text(json.dumps({"state": "select_pairs"}))
    (rd.parent / "run.json").write_text(json.dumps({"model": "tiny-random", "teacher": "x", "profile": "tiny"}))
    (rd / "candidates.json").write_text(json.dumps({
        "axis": "fairness_integrity",
        "items": [{
            "scenario_id": 1,
            "prompt": "p1",
            "unprompted": "u1",
            "candidates": [{
                "candidate_id": 1,
                "survivor_id": "s1c1",
                "kept": True,
                "persona_pair": "fairness_integrity",
                "template": "Respond as a {persona} person.",
                "template_cell_id": 1,
                "template_score": 80.0,
                "template_on_axis": 1.0,
                "template_off_axis": 0.2,
                "template_library": "x",
                "cho": "The actor should have refused the favoritism.",
                "rej": "The actor should have quietly hidden the favoritism.",
            }, {
                "candidate_id": 2,
                "survivor_id": "s1c2",
                "kept": True,
                "persona_pair": "fairness_integrity",
                "template": "Respond as a {persona} person.",
                "template_cell_id": 1,
                "template_score": 80.0,
                "template_on_axis": 1.0,
                "template_off_axis": 0.2,
                "template_library": "x",
                "cho": "The actor should have refused the favoritism openly.",
                "rej": "The actor should have kept the favoritism deniable.",
            }],
        }, {
            "scenario_id": 2,
            "prompt": "p2",
            "unprompted": "u2",
            "candidates": [{
                "candidate_id": 1,
                "survivor_id": "s2c1",
                "kept": True,
                "persona_pair": "fairness_integrity",
                "template": "Respond as a {persona} person.",
                "template_cell_id": 1,
                "template_score": 80.0,
                "template_on_axis": 1.0,
                "template_off_axis": 0.2,
                "template_library": "x",
                "cho": "The actor should have applied the rule equally.",
                "rej": "The actor should have bent the rule for the insider.",
            }],
        }],
    }))
    r1 = rate_candidate(
        rd,
        survivor_id="s1c1",
        on_axis_forward=4.0,
        on_axis_reverse=2.0,
        off_axis_clean=4.0,
        comment="Pass from scenario 1.",
    )
    r2 = rate_candidate(
        rd,
        survivor_id="s1c2",
        on_axis_forward=4.0,
        on_axis_reverse=2.0,
        off_axis_clean=4.0,
        comment="Another pass from scenario 1.",
    )
    r3 = rate_candidate(
        rd,
        survivor_id="s2c1",
        on_axis_forward=4.0,
        on_axis_reverse=2.0,
        off_axis_clean=4.0,
        comment="Pass from scenario 2.",
    )
    assert r1["passing_scenarios"] == [1]
    assert r1["n_more_needed"] > 0
    assert r2["passing_scenarios"] == [1]
    assert r3["passing_scenarios"] == [1, 2]


def test_rate_candidate_keeps_only_best_pass_per_scenario(tmp_path):
    rd = tmp_path / "round00"
    rd.mkdir(parents=True)
    (rd / "state.json").write_text(json.dumps({"state": "select_pairs"}))
    (rd.parent / "run.json").write_text(json.dumps({"model": "tiny-random", "teacher": "x", "profile": "tiny"}))
    (rd / "candidates.json").write_text(json.dumps({
        "axis": "autonomy_coercion",
        "items": [{
            "scenario_id": 1,
            "prompt": "p1",
            "unprompted": "u1",
            "candidates": [{
                "candidate_id": 1,
                "survivor_id": "s1c1",
                "kept": True,
                "persona_pair": "autonomy_coercion",
                "template": "Respond as a {persona} person.",
                "template_cell_id": 1,
                "template_score": 80.0,
                "template_on_axis": 1.0,
                "template_off_axis": 0.2,
                "template_library": "x",
                "cho": "The actor should have protected her freedom.",
                "rej": "The actor should have pressured her into agreement.",
            }, {
                "candidate_id": 2,
                "survivor_id": "s1c2",
                "kept": True,
                "persona_pair": "autonomy_coercion",
                "template": "Respond as a {persona} person.",
                "template_cell_id": 2,
                "template_score": 83.0,
                "template_on_axis": 1.0,
                "template_off_axis": 0.2,
                "template_library": "x",
                "cho": "The actor should have firmly defended her ability to choose for herself.",
                "rej": "The actor should have cornered her until she complied.",
            }],
        }],
    }))
    first = rate_candidate(
        rd,
        survivor_id="s1c1",
        on_axis_forward=4.0,
        on_axis_reverse=2.0,
        off_axis_clean=4.0,
        comment="Good axis split.",
    )
    second = rate_candidate(
        rd,
        survivor_id="s1c2",
        on_axis_forward=5.0,
        on_axis_reverse=1.0,
        off_axis_clean=5.0,
        comment="Stronger axis split.",
    )
    assert first["passing_survivors"] == ["s1c1"]
    assert second["passing_survivors"] == ["s1c2"]
    rows = json.loads((rd / "candidate_ratings.json").read_text())
    by_id = {row["survivor_id"]: row for row in rows}
    assert by_id["s1c1"]["passes"] is False
    assert by_id["s1c1"]["superseded_by"] == "s1c2"


def test_select_pairs_error_reports_remaining_shortlist(tmp_path):
    rd = tmp_path / "round00"
    rd.mkdir(parents=True)
    (rd / "state.json").write_text(json.dumps({"state": "select_pairs"}))
    (rd.parent / "run.json").write_text(json.dumps({"model": "tiny-random", "teacher": "x", "profile": "qwen-2b-3keep"}))
    (rd / "candidates.json").write_text(json.dumps({
        "axis": "autonomy_coercion",
        "items": [{
            "scenario_id": 1,
            "prompt": "p1",
            "unprompted": "u1",
            "candidates": [{
                "candidate_id": 1,
                "survivor_id": "s1c1",
                "kept": True,
                "persona_pair": "autonomy_coercion",
                "template": "Respond as a {persona} person.",
                "template_cell_id": 1,
                "template_score": 80.0,
                "template_on_axis": 1.0,
                "template_off_axis": 0.2,
                "template_library": "x",
                "cho": "The actor should have protected her freedom.",
                "rej": "The actor should have pressured her into agreement.",
            }],
        }],
    }))
    rate_candidate(
        rd,
        survivor_id="s1c1",
        on_axis_forward=4.0,
        on_axis_reverse=2.0,
        off_axis_clean=4.0,
        comment="Good axis split.",
    )
    with pytest.raises(Exception, match="Current passing shortlist covers 1 unique scenarios"):
        select_pairs(rd, lesson="x", survivor_ids=["s1c1"])
