"""Per-round state machine. State name = next required tool.

  choose_focus → select_pairs → train_student → mark_exam → done

The teacher chooses a scenario family + measured persona pair. The harness
samples tagged scenarios, generates candidate (cho, rej) pairs from the
measured template cells for that pair, and the teacher selects whole pairs.
No teacher-authored pair prose.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

State = Literal[
    "choose_focus", "select_pairs",
    "train_student", "mark_exam", "done",
]

def allowed_after(state: State) -> str:
    """Hint for the next action in the live weak-select loop."""
    if state == "choose_focus":
        return "choose_focus(persona_pair_id, scenario_family, mismatch_severity, headroom, bank_cleanliness, evidence, pre_scores, pre_question_evidence)"
    if state == "select_pairs":
        return "view_candidates() to see the next batch, then rate_candidates(ratings=[{survivor_id, contrast, cho_more_on_axis, rej_more_on_axis, refusal_confound, length_confound, incoherent_confound}, ...]) on exactly that batch; repeat until all rated, then select_pairs(lesson)"
    if state == "train_student":
        return "train_student()  (or mark_exam(keep=False, reason=...) to abort)"
    if state == "mark_exam":
        return "mark_exam(keep, reason, next_focus, harness_feedback, question_evidence)  # blind depth judge scores POST for you"
    return "(round complete — harness will allocate the next round or stop)"


class ValidationError(RuntimeError):
    pass


@dataclass
class RoundState:
    state: State = "choose_focus"
    note: str = ""

    def to_dict(self) -> dict:
        return {"state": self.state, "note": self.note}


def read_state(round_dir: Path) -> RoundState:
    p = round_dir / "state.json"
    if not p.exists():
        return RoundState(state="choose_focus")
    d = json.loads(p.read_text())
    return RoundState(state=d["state"], note=d.get("note", ""))


def write_state(round_dir: Path, st: RoundState) -> None:
    p = round_dir / "state.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(st.to_dict(), indent=2))


def require_state(round_dir: Path, expected: State | tuple[State, ...],
                  tool_name: str) -> RoundState:
    """Raise ValidationError if current state not in `expected`."""
    st = read_state(round_dir)
    allowed = (expected,) if isinstance(expected, str) else expected
    if st.state not in allowed:
        raise ValidationError(
            f"tool {tool_name!r} requires state in {allowed}, but current "
            f"state is {st.state!r}. Next valid action: {allowed_after(st.state)}."
        )
    return st


def set_state(round_dir: Path, new: State, note: str = "") -> RoundState:
    st = RoundState(state=new, note=note)
    write_state(round_dir, st)
    return st
