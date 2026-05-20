"""Per-round state machine. State name = next required tool.

  write_pair → train_student → mark_exam → done

Each state's name describes what the agent should call next. Persisted
as `<round_dir>/state.json`. Each pipeline verb checks current state
and raises `ValidationError` on a wrong-order call; the error names the
next valid tool so `on_continue` can reproduce it.

  write_pair    — pairs.md has empty/template slots; agent fills them
  train_student — ≥MIN_PAIRS filled; agent may still write_pair more
                  before training, or call train_student
  mark_exam     — adapter trained; agent decides keep/drop from pre vs
                  post probe transcripts
  done          — round committed
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

State = Literal["write_pair", "train_student", "mark_exam", "done"]

ALLOWED_AFTER = {
    "write_pair":    "write_pair(id, prompt, cho, rej)",
    "train_student": "write_pair (fill more pairs) or train_student() — "
                     "or mark_exam(keep=False, reason=...) to abort",
    "mark_exam":     "mark_exam(keep, reason)",
    "done":          "(round complete — harness will allocate the next round or stop)",
}


class ValidationError(RuntimeError):
    pass


@dataclass
class RoundState:
    state: State = "write_pair"
    note: str = ""

    def to_dict(self) -> dict:
        return {"state": self.state, "note": self.note}


def read_state(round_dir: Path) -> RoundState:
    p = round_dir / "state.json"
    if not p.exists():
        return RoundState(state="write_pair")
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
