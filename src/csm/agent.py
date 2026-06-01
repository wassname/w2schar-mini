"""inspect-ai react driver + 3 typed tools (write_pair, train_student, mark_exam).

Teacher writes pairs from scratch (10 prompts pre-seeded, 10 fully
empty). No on-policy gen, no str_replace editing, no per-pair diff cap.
The harness's job: scaffold pairs.md, enforce state machine, surface
pre/post transcripts.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from inspect_ai import Task, eval as inspect_eval
from inspect_ai.agent import AgentState, react
from inspect_ai.dataset import Sample
from inspect_ai.model import (ChatMessageUser, CompactionEdit,
                              CompactionStrategy, CompactionSummary)
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.tool import Tool, tool

from csm.pipeline import (init_run, latest_round_dir,
                          mark_exam as _mark_exam_pipeline,
                          new_round_dir, prepare_round,
                          submit_pairs as _submit_pairs_pipeline,
                          train_student as _train_student_pipeline)
from csm.prompts import (AFTER_SUBMIT, AFTER_TRAIN, COMPACTION_INSTRUCTIONS,
                         INITIAL_TASK, ON_CONTINUE_NUDGE, REACT_PROMPT)
from csm.state import allowed_after, ValidationError, read_state
from csm.ws.history import kept_history_dirs


REPO = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Compaction: Edit-first, Summary as fallback.
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
    return f"ValidationError: {e}"


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

MAX_SUBMIT_REJECTS = 4  # >4 rejects in one round → on_continue stops the run


def _rejects_path(round_dir: Path) -> Path:
    return round_dir / "submit_rejects"


def _n_submit_rejects(slug_path: Path) -> int:
    p = _rejects_path(latest_round_dir(slug_path))
    return int(p.read_text()) if p.exists() else 0


@tool(name="submit_pairs", parallel=False)
def submit_pairs_tool(slug: str) -> Tool:
    async def execute(cho_form: str) -> str:
        """Submit the Lesson and a Cho twin for each pair. You write ONLY the
        resisting prose — Prompt and the seeded deferring Rej are fixed on disk
        and must not be repeated.

        Args:
            cho_form: markdown — a `## Lesson` block (one sentence) then one
                `## <pair id>` block per Cho twin, e.g.:
                `## Lesson`\\n<disposition>\\n`## 1`\\n<cho for pair 1>\\n`## 2`\\n...
                Cho the merits-weighing twin of that pair's seeded Rej (same
                shape, stance flipped). Omit a pair's block to leave it unfilled.
        """
        round_dir = latest_round_dir(_slug_path(slug))
        rejects_path = _rejects_path(round_dir)
        try:
            res = _submit_pairs_pipeline(round_dir, cho_form)
        except (ValidationError, ValueError) as e:
            n = (int(rejects_path.read_text()) if rejects_path.exists() else 0) + 1
            rejects_path.write_text(str(n))
            msg = (_format_validation_error(e) if isinstance(e, ValidationError)
                   else f"submit_pairs rejected — {e}\npairs.md NOT updated.")
            tail = (f"\n(reject {n} — run aborts after {MAX_SUBMIT_REJECTS})"
                    if n <= MAX_SUBMIT_REJECTS
                    else f"\n(reject {n} > {MAX_SUBMIT_REJECTS} — aborting run)")
            return msg + tail
        rejects_path.unlink(missing_ok=True)  # parsed cleanly → reset counter
        return (
            f"OK — pairs.md submitted. {res['filled']}/{res['total']} "
            f"filled (need ≥{res['min_to_train']} to train). "
            f"Slots with TODO still: {res['slots_with_todo']}\n"
            f"{AFTER_SUBMIT(res['slots_with_todo'])}"
        )

    return execute


def _format_turn(text: str) -> str:
    """One assistant/user turn, newlines flattened, no length cap. Task 36
    r08/r09 had a 700-char head that hid degenerate `ethics ethics …` loops
    behind `…` — judge couldn't see the collapse, kept rounds anyway."""
    return text.strip().replace("\n", " ⏎ ")


def _format_dialogue_inline(payload: dict) -> str:
    lines = []
    for p in payload.get("probes", []):
        lines.append(f"=== probe: {p['id']} ===")
        for t in p["turns"]:
            lines.append(f"[{t['role']}] {_format_turn(t['text'])}")
        lines.append("")
    return "\n".join(lines)


def _format_pre_post_interleaved(pre: dict, post: dict) -> str:
    """Probe-by-probe PRE / POST interleave so the agent sees the contrast
    on each probe before moving to the next. PRE = c=0 (base+history),
    POST = c=signed_C (this round's adapter active)."""
    pre_by_id = {p["id"]: p for p in pre.get("probes", [])}
    post_by_id = {p["id"]: p for p in post.get("probes", [])}
    ids = list(pre_by_id) or list(post_by_id)
    out: list[str] = []
    for pid in ids:
        out.append(f"========= probe: {pid} =========")
        for label, payload in (("PRE  (c=0)", pre_by_id.get(pid)),
                               ("POST (c=signed_C)", post_by_id.get(pid))):
            out.append(f"--- {label} ---")
            if not payload:
                out.append("(missing)")
                continue
            for t in payload["turns"]:
                out.append(f"[{t['role']}] {_format_turn(t['text'])}")
        out.append("")
    return "\n".join(out)


@tool(name="train_student", parallel=False)
def train_student_tool(slug: str) -> Tool:
    async def execute() -> str:
        """Train the adapter on the filled pairs, replay probes at the
        fixed bake coefficient. No args.

        Requires ≥min_pairs_to_train slots filled. Returns the PRE and
        POST dialogue text inline.
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
            f"SHOULD: assistant turns are coherent prose end-to-end. Repeated "
            f"tokens at the tail (e.g. `ethics ethics ethics …`) = degenerate "
            f"loop = the model collapsed. Drop the round (the prefix may look "
            f"fine but the model is broken).\n"
            f"========== PRE vs POST (interleaved per probe) ==========\n"
            f"{_format_pre_post_interleaved(pre, post)}\n"
            f"{AFTER_TRAIN}"
        )

    return execute


@tool(name="mark_exam", parallel=False)
def mark_exam_tool(slug: str) -> Tool:
    async def execute(keep: bool, reason: str, next_focus: str) -> str:
        """Mark the student's exam. Commits the round.

        Args:
            keep: True bakes the adapter into next round's history;
                False drops and the next round retries from scratch.
            reason: 1-3 sentences citing specific PRE vs POST text.
            next_focus: further moral-character aspect to push on next
                round — what the post-dialogue still misses, or an
                adjacent disposition the kept rounds haven't touched yet.
                Will be shown in the next round's brief.
        """
        round_dir = latest_round_dir(_slug_path(slug))
        try:
            judgment = _mark_exam_pipeline(round_dir, keep, reason, next_focus)
        except ValidationError as e:
            return _format_validation_error(e)
        return (
            f"mark_exam OK — action: {judgment['action']}.\n"
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


def _last_next_focus(slug_path: Path, *, exclude: Path | None = None) -> str:
    """Return the most recent round's `next_focus` (kept or dropped), or ""."""
    for rd in sorted((p for p in slug_path.glob("round*") if p.is_dir()),
                     reverse=True):
        if exclude is not None and rd == exclude:
            continue
        jp = rd / "judgment.json"
        if jp.exists():
            d = json.loads(jp.read_text())
            f = d.get("next_focus", "").strip()
            if f:
                return f
    return ""


def _n_drops(slug_path: Path) -> int:
    return sum(
        1 for rd in slug_path.glob("round*")
        if rd.is_dir() and (rd / "judgment.json").exists()
        and json.loads((rd / "judgment.json").read_text()).get("action") == "drop"
    )


def _round_history_lines(slug_path: Path) -> str:
    """One indented line per completed round: name, action, axis-hint snippet.
    Empty string for the first round (nothing to show). Helps the agent see
    its own keep/drop pattern instead of inferring it from raw counters."""
    rounds = sorted(p for p in slug_path.glob("round*") if p.is_dir())
    lines: list[str] = []
    for rd in rounds:
        jp = rd / "judgment.json"
        if not jp.exists():
            continue
        d = json.loads(jp.read_text())
        action = d.get("action", "?")
        nf = (d.get("next_focus") or d.get("reason") or "").strip().replace("\n", " ")
        if len(nf) > 100:
            nf = nf[:97] + "..."
        lines.append(f"  {rd.name}: {action} — {nf}" if nf else f"  {rd.name}: {action}")
    if not lines:
        return ""
    return "History so far (one line per round):\n" + "\n".join(lines)


@solver
def inspect_solver(*, slug: str, n_rounds: int) -> Solver:
    slug_path = _slug_path(slug)
    initial_keeps = _n_keeps(slug_path)
    target_keeps = initial_keeps + n_rounds

    async def on_continue(state):
        n_keeps = _n_keeps(slug_path)
        if n_keeps >= target_keeps:
            return False
        # Gym hard-cap: in fake-student mode POST is canned and never moves,
        # so every round drops and target_keeps is unreachable. Cap on
        # attempts instead so `just smoke-prompts N` always exits after N
        # tries regardless of outcome.
        if os.environ.get("CSM_FAKE_STUDENT") == "1" \
                and _n_keeps(slug_path) + _n_drops(slug_path) >= n_rounds:
            return False
        # Real-mode hard-cap: a teacher that can't produce a parseable +
        # in-gate pairs.md loops forever on submit_pairs (task #136 burned
        # ~1.5h on 13 rejects). Stop once one round exceeds the reject budget.
        n_rej = _n_submit_rejects(slug_path)
        if n_rej > MAX_SUBMIT_REJECTS:
            # Hard failure (not a clean `return False`): a teacher that can't
            # produce a parseable, in-gate pairs.md is a broken run, and it
            # must surface as a failed task — not a green "success" that an
            # /audit-run would wave through.
            raise RuntimeError(
                f"submit_pairs rejected {n_rej} times this round "
                f"(> {MAX_SUBMIT_REJECTS}) — aborting run.")

        rd = latest_round_dir(slug_path)
        st = read_state(rd)
        if st.state == "done":
            rd = new_round_dir(slug_path)
            prepare_round(slug_path, rd)
            st = read_state(rd)

        return ON_CONTINUE_NUDGE.format(
            n_keeps=n_keeps, target_keeps=target_keeps, n_drops=_n_drops(slug_path),
            history=_round_history_lines(slug_path),
            last_state=st.state, next_action=allowed_after(st.state),
        )

    agent = react(
        tools=[
            submit_pairs_tool(slug),
            train_student_tool(slug),
            mark_exam_tool(slug),
        ],
        submit=False,
        prompt=REACT_PROMPT,
        on_continue=on_continue,
        retry_refusals=3,
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
    """Build + run the inspect-ai react agent for this slug."""
    slug_path = _slug_path(slug)
    rd = latest_round_dir(slug_path)
    if not (rd / "interview_pre.json").exists():
        prepare_round(slug_path, rd)

    n_keeps_now = _n_keeps(slug_path)
    n_history = len(kept_history_dirs(slug_path))
    pre_text = _format_dialogue_inline(
        json.loads((rd / "interview_pre.json").read_text())
    )
    pairs_text = (rd / "pairs.md").read_text()
    prior_focus = _last_next_focus(slug_path, exclude=rd)
    focus_block = (f"\nPRIOR ROUND'S `next_focus`:\n  {prior_focus}\n"
                   if prior_focus else "")
    initial = INITIAL_TASK.format(
        round_n=n_keeps_now + 1, target_n=n_keeps_now + n_rounds,
        round_dir=str(rd.relative_to(REPO)), model=model,
        n_history=n_history,
    ) + focus_block + (
        f"\n========== PRE-DIALOGUE (c=0, base+history) ==========\n"
        f"{pre_text}\n"
        f"========== pairs.md (REFERENCE — fixed Prompt + seeded Rej per pair) ==========\n"
        f"{pairs_text}"
        f"========== end pairs.md ==========\n"
        f"Write a Cho twin for each `### Rej` above and submit via "
        f"submit_pairs(cho_form): `## Lesson` then `## <id>` Cho per pair. "
        f"Do not repeat the Prompt or Rej.\n"
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
        max_tool_output=256 * 1024,
    )
    if any(log.status != "success" for log in logs):
        raise RuntimeError(f"inspect eval failed: {[log.status for log in logs]}")
    print(f"agent-run: done. logs={logs}")
