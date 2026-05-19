"""inspect-ai react driver + 4 typed tools.

Trimmed distillation of `weight-steering-lite/scripts/agent_driver_inspect.py`
(972 → ~230 lines). Dropped: OpenRouter retry monkeypatch, compaction
strategy, exit-interview tool, ad-hoc local_bash, multi-profile registry
in the driver itself.

The 4 tools all delegate to `csm.pipeline.*` and bubble any
`csm.state.ValidationError` to the agent so it can correct its tool
order.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from inspect_ai import Task, eval as inspect_eval
from inspect_ai.agent import AgentState, react
from inspect_ai.dataset import Sample
from inspect_ai.model import ChatMessageUser
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.tool import Tool, tool
from loguru import logger

from csm.history import kept_history_dirs
from csm.pipeline import (
    edit, init_run, judge, latest_round_dir, new_round_dir, propose,
    run_pre_dialogue, train_and_eval,
)
from csm.prompts import INITIAL_TASK, ON_CONTINUE_NUDGE, REACT_PROMPT
from csm.state import ALLOWED_AFTER, ValidationError, read_state


REPO = Path(__file__).resolve().parents[2]


def _slug_path(slug: str | Path) -> Path:
    p = Path(slug)
    return p if p.is_absolute() else (REPO / p)


def _format_validation_error(e: ValidationError) -> str:
    """Tool-error string the agent will receive. Front-load the next action."""
    return f"ValidationError: {e}"


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@tool(name="propose_personas", parallel=False)
def propose_personas_tool(slug: str) -> Tool:
    async def execute(pos_persona: str, neg_persona: str) -> str:
        """Write the round's persona pair and generate 50 on-policy pairs.

        Each persona = single-clause sentence in the same scaffold; flip
        only the axis word(s). Positive = trait to grow ("less deference
        to authority"); negative = the failure mode.

        Args:
            pos_persona: e.g. "You are someone who refuses unlawful or
                harmful orders, even from authority figures."
            neg_persona: e.g. "You are someone who obeys orders from
                authority figures even when others get hurt."
        """
        round_dir = latest_round_dir(_slug_path(slug))
        try:
            res = propose(_slug_path(slug), round_dir, pos_persona, neg_persona)
        except ValidationError as e:
            return _format_validation_error(e)
        # Return only what the agent needs to read: counts + compact preview.
        preview_lines = "\n".join(
            f"  - id={p['id']} prompt={p['prompt']!r}\n"
            f"      cho_head: {p['cho_head']}\n"
            f"      rej_head: {p['rej_head']}"
            for p in res["preview"]
        )
        return (
            f"propose_personas OK\n"
            f"  alive: {res['n_alive']}    dropped (both refused): "
            f"{res['n_dropped']}  dropped_ids: {res['dropped_ids']}\n"
            f"  pairs.yaml: {round_dir / 'pairs.yaml'}\n"
            f"preview ({len(res['preview'])} of {res['n_alive']}):\n"
            f"{preview_lines}\n\n"
            f"next: optionally call edit_pairs(new_yaml=...) to clean any "
            f"broken pairs, then call train()."
        )

    return execute


@tool(name="edit_pairs", parallel=False)
def edit_pairs_tool(slug: str) -> Tool:
    async def execute(new_yaml: str) -> str:
        """Bulk-rewrite pairs.yaml.

        Pass the FULL new YAML as a string. Format: list of
        `{id, prompt, cho, rej}` blocks (cho/rej side-by-side). Block
        scalars (`|`) for multi-line. IDs are auto-renumbered after this
        call.

        Args:
            new_yaml: Full pairs.yaml content. Drop a pair by omitting it.
        """
        round_dir = latest_round_dir(_slug_path(slug))
        try:
            res = edit(round_dir, new_yaml)
        except ValidationError as e:
            return _format_validation_error(e)
        except Exception as e:
            return f"edit_pairs failed: {type(e).__name__}: {e}"
        return (
            f"edit_pairs OK\n"
            f"  alive: {res['n_alive']}  (was {res['n_original']} pre-edit)\n"
            f"  changed vs bk.yaml: {res['n_changed_vs_bk']}\n"
            f"next: call train() when ready (you can call edit_pairs again first)."
        )

    return execute


@tool(name="train", parallel=False)
def train_tool(slug: str) -> Tool:
    async def execute() -> str:
        """Train the adapter on (curated) pairs.yaml, then replay
        post-dialogue.

        No args. Picks up the current round's pairs.yaml, fits a
        ModulatedLoRA via path-loss + KL anchor, calibrates a coherent
        signed_C via c-scan, replays the 3 authority probes under
        adapter@signed_C, writes interview_post.json. After this you
        read interview_pre + interview_post and call judge().
        """
        slug_p = _slug_path(slug)
        round_dir = latest_round_dir(slug_p)
        try:
            res = train_and_eval(slug_p, round_dir)
        except ValidationError as e:
            return _format_validation_error(e)
        return (
            f"train OK\n"
            f"  adapter: {round_dir / 'adapter.safetensors'}\n"
            f"  calibration.json signed_C: ({res['signed_C']:+.3f} — harness-private number)\n"
            f"  interview_post.json: {round_dir / 'interview_post.json'}\n"
            f"  interview_pre.json:  {round_dir / 'interview_pre.json'}\n"
            f"next: read both interview JSONs, then call judge(keep=..., reason=...)."
        )

    return execute


@tool(name="judge", parallel=False)
def judge_tool(slug: str) -> Tool:
    async def execute(keep: bool, reason: str) -> str:
        """Commit the round.

        Args:
            keep: True to bake this adapter forward (composes into next
                round's history). False to drop and retry with a new
                persona pair.
            reason: One or two sentences citing what you saw in pre vs
                post transcripts. Written to judgment.json.
        """
        round_dir = latest_round_dir(_slug_path(slug))
        try:
            judgment = judge(round_dir, keep, reason)
        except ValidationError as e:
            return _format_validation_error(e)
        return (
            f"judge OK\n"
            f"  action: {judgment['action']}\n"
            f"  written to: {round_dir / 'judgment.json'}\n"
            f"next: harness will allocate a new round or stop on budget exhausted."
        )

    return execute


# ---------------------------------------------------------------------------
# react setup + on_continue (round rollover + budget tracking)
# ---------------------------------------------------------------------------

def _n_keeps(slug_path: Path) -> int:
    return sum(
        1 for rd in slug_path.glob("round*")
        if rd.is_dir() and (rd / "judgment.json").exists()
        and json.loads((rd / "judgment.json").read_text()).get("action") == "keep"
    )


def _n_drops(slug_path: Path) -> int:
    return sum(
        1 for rd in slug_path.glob("round*")
        if rd.is_dir() and (rd / "judgment.json").exists()
        and json.loads((rd / "judgment.json").read_text()).get("action") == "drop"
    )


@solver
def inspect_solver(*, slug: str, n_rounds: int) -> Solver:
    slug_path = _slug_path(slug)

    async def on_continue(state):
        n_keeps = _n_keeps(slug_path)
        if n_keeps >= n_rounds:
            return False  # budget exhausted

        # If the latest round is done, allocate a new one + run pre-dialogue.
        rd = latest_round_dir(slug_path)
        st = read_state(rd)
        if st.state == "done":
            rd = new_round_dir(slug_path)
            run_pre_dialogue(slug_path, rd)
            st = read_state(rd)

        return ON_CONTINUE_NUDGE.format(
            n_keeps=n_keeps, target_keeps=n_rounds, n_drops=_n_drops(slug_path),
            last_state=st.state, next_action=ALLOWED_AFTER[st.state],
        )

    agent = react(
        tools=[
            propose_personas_tool(slug),
            edit_pairs_tool(slug),
            train_tool(slug),
            judge_tool(slug),
        ],
        submit=False,
        prompt=REACT_PROMPT,
        on_continue=on_continue,
        retry_refusals=3,
    )

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        agent_state = AgentState(messages=state.messages)
        agent_state = await agent(agent_state)
        state.messages = agent_state.messages
        state.output = agent_state.output
        return state

    return solve


def _inspect_model_name(teacher: str) -> str:
    return teacher if teacher.startswith(("openrouter/", "openai/", "anthropic/")) else f"openrouter/{teacher}"


def run(*, model: str, teacher: str, slug: Path, n_rounds: int) -> None:
    """Build + run the inspect-ai react agent for this slug.

    Idempotent: if round00 already exists with state ≠ done, picks up
    there; pre_dialogue is run lazily by `on_continue` for new rounds.
    """
    slug_path = _slug_path(slug)
    # round00 pre-dialogue: ensure it exists before the agent starts so its
    # very first action can be a propose_personas after reading the
    # transcript.
    rd = latest_round_dir(slug_path)
    if not (rd / "interview_pre.json").exists():
        run_pre_dialogue(slug_path, rd)

    n_keeps_now = _n_keeps(slug_path)
    n_history = len(kept_history_dirs(slug_path))
    initial = INITIAL_TASK.format(
        round_n=n_keeps_now + 1, target_n=n_keeps_now + n_rounds,
        round_dir=str(rd.relative_to(REPO)), model=model,
        n_history=n_history,
    )

    teacher_model = _inspect_model_name(teacher)
    task = Task(
        dataset=[Sample(input=[ChatMessageUser(content=initial)], id="w2schar-mini")],
        solver=inspect_solver(slug=str(slug_path), n_rounds=n_rounds),
        sandbox=None,
    )

    if os.environ.get("INSPECT_AGENT_DRY_RUN") == "1":
        print(f"agent-run: DRY_RUN PASS model={teacher_model} slug={slug_path} "
              f"n_rounds={n_rounds}", file=sys.stderr)
        return

    logs = inspect_eval(
        task, model=teacher_model,
        display="conversation",
        log_dir=str(slug_path.resolve()),
        log_format="json",
        fail_on_error=True,
        score=False,
    )
    if any(log.status != "success" for log in logs):
        raise RuntimeError(f"inspect eval failed: {[log.status for log in logs]}")
    print(f"agent-run: done. logs={logs}")
