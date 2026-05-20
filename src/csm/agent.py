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
from typing import Literal

from inspect_ai import Task, eval as inspect_eval
from inspect_ai.agent import AgentState, react
from inspect_ai.dataset import Sample
from inspect_ai.model import (ChatMessageUser, CompactionEdit,
                              CompactionStrategy, CompactionSummary)
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.tool import Tool, tool
from loguru import logger

from csm.ws.history import kept_history_dirs
from csm.pipeline import (
    edit_answers as _edit_answers_pipeline,
    init_run, latest_round_dir, mark_exam as _mark_exam_pipeline,
    new_round_dir, propose_personas as _propose_personas_pipeline,
    run_pre_dialogue, train_student as _train_student_pipeline,
)
from csm.prompts import (AFTER_EDIT_CLEAN, AFTER_PROPOSE, AFTER_TRAIN,
                         COMPACTION_INSTRUCTIONS, INITIAL_TASK,
                         ON_CONTINUE_NUDGE, REACT_PROMPT)
from csm.state import (ALLOWED_AFTER, ValidationError, read_state,
                       set_state)


REPO = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Compaction: Edit-first, Summary as fallback (wsl pattern).
#
# CompactionEdit (free — drops old tool outputs + thinking blocks) handles
# most rounds. CompactionSummary (one LLM call) only fires when Edit alone
# can't reduce conversation below `edit_target`. Net: free for early
# rounds, summary cost amortized over late-round transcript accumulation.
# ---------------------------------------------------------------------------
class EditThenSummary(CompactionStrategy):
    def __init__(self, *, threshold: int | float, edit_target: int,
                 summary_instructions: str, keep_tool_uses: int = 3):
        super().__init__(type="summary", threshold=threshold)
        self._edit = CompactionEdit(
            threshold=threshold, keep_tool_uses=keep_tool_uses,
        )
        self._summary = CompactionSummary(
            threshold=threshold, instructions=summary_instructions,
        )
        self._edit_target = edit_target

    async def compact(self, model, messages, tools):
        edited, _ = await self._edit.compact(model, messages, tools)
        edited_tokens = await model.count_tokens(edited)
        if edited_tokens <= self._edit_target:
            return edited, None
        return await self._summary.compact(model, edited, tools)


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
        """Write the round's pos/neg persona pair and generate 50 on-policy pairs.

        Args:
            pos_persona: the trait to grow.
            neg_persona: the failure mode the student already shows.
        """
        round_dir = latest_round_dir(_slug_path(slug))
        try:
            res = _propose_personas_pipeline(_slug_path(slug), round_dir,
                                              pos_persona, neg_persona)
        except ValidationError as e:
            return _format_validation_error(e)
        pairs_json_text = (round_dir / "pairs.json").read_text()
        return (
            f"propose_personas OK\n"
            f"  alive: {res['n_alive']}    dropped (both refused): "
            f"{res['n_dropped']}  dropped_ids: {res['dropped_ids']}\n\n"
            f"========== pairs.json (current — full file) ==========\n"
            f"{pairs_json_text}"
            f"========== end pairs.json ==========\n"
            f"{AFTER_PROPOSE}"
        )

    return execute


def _commit_edits(round_dir: Path, edits: list[dict]) -> str:
    """Thin wrapper around pipeline.edit_answers. ValidationError +
    ValueError get formatted as agent-facing tool errors. On success,
    appends a short unified diff so the agent can self-verify placement."""
    import difflib
    bk_text_before = (round_dir / "pairs.json").read_text() if (round_dir / "pairs.json").exists() else ""
    try:
        res = _edit_answers_pipeline(round_dir, edits)
    except ValidationError as e:
        return _format_validation_error(e)
    except ValueError as e:
        return f"edits rejected — {e}\npairs.json NOT updated."
    after_text = (round_dir / "pairs.json").read_text()
    diff = list(difflib.unified_diff(
        bk_text_before.splitlines(), after_text.splitlines(),
        fromfile="pairs.json (before)", tofile="pairs.json (after)", n=2,
        lineterm="",
    ))
    if len(diff) > 30:
        diff = diff[:30] + [f"... ({len(diff) - 30} more diff lines truncated)"]
    msg = (f"OK — pairs.json updated ({res['n_alive']} alive, "
           f"{res['n_dropped']} dropped, {res['n_changed']} cho/rej changed, "
           f"{res['n_edits_applied']} edits applied).\n\n"
           f"Diff:\n" + "\n".join(diff))
    if res["refusal_warnings"]:
        msg += (
            f"\n\nWarning: {len(res['refusal_warnings'])} cho/rej entries "
            f"still contain refusal-style phrases. Not auto-rejected — "
            f"review and decide if they should be dropped on the next edit:\n"
            + "\n".join(res["refusal_warnings"][:10])
            + ("\n  ... (more truncated)" if len(res["refusal_warnings"]) > 10 else "")
        )
    return msg


@tool(name="edit_answers", parallel=False)
def edit_answers_tool(slug: str) -> Tool:
    async def execute(edits: list[dict] | str) -> str:
        """Apply a batch of str_replace edits to pairs.json.

        Each edit is a dict {"old_str": "...", "new_str": "..."}. Each
        old_str must occur exactly ONCE in the current pairs.json text
        and must not overlap with any other edit's match range in the
        same call. All edits are matched against the original file (not
        incrementally), then applied atomically.

        Common patterns:
          - DROP a pair: old_str = the whole pair block including the
            trailing comma (or include the preceding comma if dropping
            the last pair); new_str = "".
          - FIX cho/rej: old_str = the broken sentence verbatim from
            pairs.json (with its surrounding quotes if quoted); new_str
            = the trimmed version. Keep the per-pair char-diff ≤50%.

        This tool is REQUIRED at least once per round before train_student().
        Multiple calls are allowed if you want to iterate.

        Args:
            edits: List of {old_str, new_str} dicts. Accepts a JSON-encoded
                string of the same shape as a fallback for models that
                pass a stringified array (Opus 4.6, GLM-5.1, some Qwens).
        """
        # pi-style coerce: some models send `edits` as a JSON-string
        # instead of a real array. Parse it before our validation runs.
        if isinstance(edits, str):
            try:
                edits = json.loads(edits)
            except json.JSONDecodeError as e:
                return (f"edits rejected — edits arg was a string but isn't "
                        f"valid JSON (at line {e.lineno}, col {e.colno}: "
                        f"{e.msg}). Pass it as a JSON array, not a string.")
            if not isinstance(edits, list):
                return (f"edits rejected — edits arg was a string that parsed "
                        f"as {type(edits).__name__}, not an array. Pass an "
                        f"array of {{old_str, new_str}} dicts.")
        round_dir = latest_round_dir(_slug_path(slug))
        msg = _commit_edits(round_dir, edits)
        if not msg.startswith("OK"):
            return msg
        return msg + "\n" + AFTER_EDIT_CLEAN

    return execute


def _format_dialogue_inline(payload: dict, *, head: int = 700) -> str:
    """Render an interview JSON payload as a flat text block for the agent."""
    lines = []
    for p in payload.get("probes", []):
        lines.append(f"=== probe: {p['id']} ===")
        for t in p["turns"]:
            text = t["text"].strip().replace("\n", " ⏎ ")
            if len(text) > head:
                text = text[:head] + "…"
            lines.append(f"[{t['role']}] {text}")
        lines.append("")
    return "\n".join(lines)


@tool(name="train_student", parallel=False)
def train_student_tool(slug: str) -> Tool:
    async def execute() -> str:
        """Train, calibrate, and replay probes. No args.

        Picks up the current round's pairs.yaml, fits the adapter,
        c-scans for coherent C, replays probes pre/post. Returns the
        PRE + POST dialogue text inline.
        """
        slug_p = _slug_path(slug)
        round_dir = latest_round_dir(slug_p)
        try:
            _train_student_pipeline(slug_p, round_dir)
        except ValidationError as e:
            return _format_validation_error(e)

        pre = json.loads((round_dir / "interview_pre.json").read_text())
        post = json.loads((round_dir / "interview_post.json").read_text())
        return (
            f"train_student OK — adapter saved.\n\n"
            f"========== PRE-DIALOGUE (c=0, base+history) ==========\n"
            f"{_format_dialogue_inline(pre)}\n"
            f"========== POST-DIALOGUE (c=signed_C, this adapter active) ==========\n"
            f"{_format_dialogue_inline(post)}\n"
            f"{AFTER_TRAIN}"
        )

    return execute


@tool(name="mark_exam", parallel=False)
def mark_exam_tool(slug: str) -> Tool:
    async def execute(keep: bool, reason: str) -> str:
        """Mark the student's exam. Commits the round.

        Args:
            keep: True bakes the adapter into next round's history;
                False drops and the next round retries from scratch.
            reason: 1-3 sentences citing specific PRE vs POST text.
        """
        round_dir = latest_round_dir(_slug_path(slug))
        try:
            judgment = _mark_exam_pipeline(round_dir, keep, reason)
        except ValidationError as e:
            return _format_validation_error(e)
        return (
            f"mark_exam OK\n"
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
    # Budget is measured in *additional* keeps this invocation. Resuming a slug
    # with existing keeps adds on top — otherwise resume could stop immediately.
    initial_keeps = _n_keeps(slug_path)
    target_keeps = initial_keeps + n_rounds

    async def on_continue(state):
        n_keeps = _n_keeps(slug_path)
        if n_keeps >= target_keeps:
            return False  # budget exhausted

        # If the latest round is done, allocate a new one + run pre-dialogue.
        rd = latest_round_dir(slug_path)
        st = read_state(rd)
        if st.state == "done":
            rd = new_round_dir(slug_path)
            run_pre_dialogue(slug_path, rd)
            st = read_state(rd)

        return ON_CONTINUE_NUDGE.format(
            n_keeps=n_keeps, target_keeps=target_keeps, n_drops=_n_drops(slug_path),
            last_state=st.state, next_action=ALLOWED_AFTER[st.state],
        )

    agent = react(
        tools=[
            propose_personas_tool(slug),
            edit_answers_tool(slug),
            train_student_tool(slug),
            mark_exam_tool(slug),
        ],
        submit=False,
        prompt=REACT_PROMPT,
        on_continue=on_continue,
        retry_refusals=3,
        # Fire compaction at 70% of context window. Edit alone (free —
        # strips old tool outputs + thinking) handles most rounds; LLM
        # summary only escalates when Edit can't get us below ~50% of
        # the window. Round artifacts on disk are the source of truth so
        # prior-round transcripts can safely be edited / summarised away.
        compaction=EditThenSummary(
            threshold=0.7,
            edit_target=16000,
            summary_instructions=COMPACTION_INSTRUCTIONS,
            keep_tool_uses=3,
        ),
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
    pre_text = _format_dialogue_inline(
        json.loads((rd / "interview_pre.json").read_text())
    )
    initial = INITIAL_TASK.format(
        round_n=n_keeps_now + 1, target_n=n_keeps_now + n_rounds,
        round_dir=str(rd.relative_to(REPO)), model=model,
        n_history=n_history,
    ) + (
        f"\n\n========== PRE-DIALOGUE (c=0, base+history) — read this before proposing ==========\n"
        f"{pre_text}\n"
        f"==================================================\n"
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
        # propose_personas inlines the full pairs.yaml (≤50 pairs × ~2-3KB
        # ≈ ~120KB peak with gemma's markdown-heavy completions). Default
        # 16KB silently drops 8/9 of the file; the agent then "rewrites"
        # the visible head. Set well above current peak.
        max_tool_output=256 * 1024,
    )
    if any(log.status != "success" for log in logs):
        raise RuntimeError(f"inspect eval failed: {[log.status for log in logs]}")
    print(f"agent-run: done. logs={logs}")
