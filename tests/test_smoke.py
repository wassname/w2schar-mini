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

    candidates = json.loads((rd / "candidates.json").read_text())
    assert candidates["axis"] == "honest-counsel vs flattering-agreement"
    assert candidates["active_persona_cells"]
    assert candidates["active_persona_cells"][0]["template_library"] == (
        "wassname/persona-steering-template-library"
    )
    assert candidates["persona_cell_selection"] == "top_measured_cells_no_axis_filter"
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
