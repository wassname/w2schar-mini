"""Per-round state machine. State name = next required tool.

  propose_personas → edit_answers → train_student → mark_exam → done

Each state's name describes what the agent should call next. Persisted
as `<round_dir>/state.json`. Each pipeline verb checks current state
and raises `ValidationError` on a wrong-order call; the error names the
next valid tool so `on_continue` can reproduce it.

  propose_personas — gen hasn't run; agent writes the persona pair
  edit_answers     — pairs.yaml written; agent MUST call edit_answers
                     at least once before train_student (forced read+edit)
  train_student    — agent has edited; may iterate edit_answers OR call
                     train_student
  mark_exam        — adapter trained; agent decides keep/drop from pre vs
                     post probe transcripts
  done             — round committed
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

State = Literal[
    "propose_personas", "edit_answers", "train_student", "mark_exam", "done",
]

ALLOWED_AFTER = {
    "propose_personas": "propose_personas",
    "edit_answers":     "drop_pair(id) and/or edit_answers(old_str, new_str) — train_student requires ≥1 of EACH cumulatively, or mark_exam(keep=False, reason=...) to abort",
    "train_student":    "drop_pair / edit_answers (iterate) or train_student (once the dual-gate is satisfied)",
    "mark_exam":        "mark_exam",
    "done":             "(round complete — harness will allocate the next round or stop)",
}


class ValidationError(RuntimeError):
    pass


@dataclass
class RoundState:
    state: State = "propose_personas"
    note: str = ""

    def to_dict(self) -> dict:
        return {"state": self.state, "note": self.note}


def read_state(round_dir: Path) -> RoundState:
    p = round_dir / "state.json"
    if not p.exists():
        return RoundState(state="propose_personas")
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
