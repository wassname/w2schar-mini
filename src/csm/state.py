"""Per-round state machine. State name = next required tool.

  submit_pairs → train_student → mark_exam → done
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

State = Literal["submit_pairs", "train_student", "mark_exam", "done"]

ALLOWED_AFTER = {
    "submit_pairs":  "submit_pairs(pairs_md)",
    "train_student": "train_student() — or submit_pairs(pairs_md) to resubmit, "
                     "or mark_exam(keep=False, reason=...) to abort",
    "mark_exam":     "mark_exam(keep, reason, next_focus)",
    "done":          "(round complete — harness will allocate the next round or stop)",
}


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
            f"state is {st.state!r}. Next valid action: {ALLOWED_AFTER[st.state]}."
        )
    return st


def set_state(round_dir: Path, new: State, note: str = "") -> RoundState:
    st = RoundState(state=new, note=note)
    write_state(round_dir, st)
    return st
