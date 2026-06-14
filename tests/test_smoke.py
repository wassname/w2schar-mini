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
from csm.gen.pairs import sample_prompt_rows
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
            " What should the actor have done instead?",
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
