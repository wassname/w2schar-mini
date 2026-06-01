"""Per-round state machine. State name = next required tool.

  submit_pairs → train_student → mark_exam → done
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

State = Literal["submit_pairs", "train_student", "mark_exam", "done"]

def allowed_after(state: State) -> str:
    """Hint for the next action. Single option when the state determines it;
    in `train_student` we don't advertise resubmit as an alternative (the
    backdoor still works if the agent really needs it) because dangling
    alternatives produced a 56-min retry loop on r05 of task 35."""
    if state == "submit_pairs":
        return "submit_pairs(cho_form)"
    if state == "train_student":
        return "train_student()  (or mark_exam(keep=False, reason=...) to abort)"
    if state == "mark_exam":
        return "mark_exam(keep, reason, next_focus)"
    return "(round complete — harness will allocate the next round or stop)"


class ValidationError(RuntimeError):
    pass


@dataclass
class RoundState:
    state: State = "submit_pairs"
    note: str = ""

    def to_dict(self) -> dict:
        return {"state": self.state, "note": self.note}


def read_state(round_dir: Path) -> RoundState:
    p = round_dir / "state.json"
    if not p.exists():
        return RoundState(state="submit_pairs")
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
