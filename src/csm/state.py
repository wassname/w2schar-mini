"""Per-round state machine: propose → curate → judge → done.

Persisted as `<round_dir>/state.json`. Each tool the agent calls reads
this and raises `ValidationError` if the call is invalid for the
current state. The error message names the next valid action so the
react agent's `on_continue` nudge can just reproduce it.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

State = Literal["propose", "curate", "judge", "done"]
TRANSITIONS = {"propose": "curate", "curate": "judge", "judge": "done"}
ALLOWED_AFTER = {
    "propose": "propose_personas",
    "curate":  "edit_pairs or train",
    "judge":   "judge",
    "done":    "(round complete — start next round or stop)",
}


class ValidationError(RuntimeError):
    pass


@dataclass
class RoundState:
    state: State = "propose"
    note: str = ""

    def to_dict(self) -> dict:
        return {"state": self.state, "note": self.note}


def read_state(round_dir: Path) -> RoundState:
    p = round_dir / "state.json"
    if not p.exists():
        return RoundState(state="propose")
    d = json.loads(p.read_text())
    return RoundState(state=d["state"], note=d.get("note", ""))


def write_state(round_dir: Path, st: RoundState) -> None:
    p = round_dir / "state.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(st.to_dict(), indent=2))


def require_state(round_dir: Path, expected: State, tool_name: str) -> RoundState:
    """Read current state and raise ValidationError if not `expected`."""
    st = read_state(round_dir)
    if st.state != expected:
        raise ValidationError(
            f"tool {tool_name!r} requires state={expected!r}, but current "
            f"state is {st.state!r}. Next valid action: {ALLOWED_AFTER[st.state]}."
        )
    return st


def advance(round_dir: Path, note: str = "") -> RoundState:
    """Move to the next state. Errors if already 'done'."""
    st = read_state(round_dir)
    if st.state == "done":
        raise ValidationError("round already at state='done'; start the next round")
    new = TRANSITIONS[st.state]
    st = RoundState(state=new, note=note)
    write_state(round_dir, st)
    return st
