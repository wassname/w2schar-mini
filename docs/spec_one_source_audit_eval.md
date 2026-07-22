# Spec (working, UNREVIEWED): one searchable audit source = the inspect `.eval`

Status: working notes by Claude, 2026-07-17. NOT reviewed/approved -- this is the implementation
backing for the approved plan at `/root/.claude/plans/rosy-wibbling-sifakis.md`. Do this AFTER
pueue task-11 (the combined deadband-0.5 + e1.5 run) finishes; do not touch a running experiment.
Every brief-touching step passes the prompt gym (`just smoke-prompts 1`, read the artifacts).

## Why
A run's record is scattered across pueue stdout, inspect's live `sample_buffer` (SQLite), our own
per-round JSON artifacts, and the finalized `.eval`/`.json` log. buffer and `.eval` are the same
data at two moments; the real duplication is our JSON sitting beside the inspect log. Intent: move
audit/decision data INTO the inspect log so there is ONE searchable source (live via buffer, final
via `.eval`, Scout-scannable), and retire the parallel JSON. Operational state (weights, resume,
baked c) stays on disk -- you can't put weights in a transcript.

## The 4 steps (see plan for the checklist + UAT)
1. `agent.py:1346` `log_format="json"` -> `"eval"`.
2. Emit decisions as a ChatMessage in the transcript; retire the audit-only JSON; repoint readers.
3. `just scout <slug>` over the `.eval`.
4. mark_exam auto-commit; drop `next_focus`; keep `harness_feedback`.

---

## D1 backing: HOW to write decisions into the one log (mechanism)

Only a **`ChatMessage`** lands in ALL of: finalized `read_eval_log` (`EvalSample.messages`), live
`sample_buffer.message_pool` (pooled only for `ModelEvent`, `buffer/database.py:643,713`), our
`scripts/agent_thoughts.py` / `scripts/log_lengths.py` (both read `message_pool` live + `s.messages`
final ONLY), and a message-oriented Scout scanner.

- `store().set(k,v)` (`inspect_ai/util/_store.py:71`) and `transcript().info(data)`
  (`.../log/_transcript.py:62`) -> the **events** table of both logs, NOT `message_pool`. Invisible
  to our two scripts and to message-only scanners. Scout can read them only via an `events`/
  `transcript` scanner (`inspect_scout` `ScannerInput` has NO store/metadata input;
  `_scanner/types.py:12`).
- sample `metadata` -> summary row, flushed to the live buffer only at sample completion
  (`buffer/database.py:220`), so not per-round-live. Not a Scout scanner input.
- Tools do NOT receive `TaskState` (`train_student_tool.execute()` `agent.py:864`,
  `mark_exam_tool.execute(next_focus, harness_feedback)` `agent.py:916`), but `store()`/
  `transcript()` are contextvar globals callable inside a tool. The solver body has `state`
  (`agent.py:1290`).

**Decision:** emit the A/B votes + keep/drop + post-hoc top1 as a structured tool `ChatMessage`
(mark_exam's return already flows into `message_pool` as a tool message -- extend it). If we want a
rich machine record too, ALSO `store().set(...)` + teach `agent_thoughts.py`/`log_lengths.py` and
the Scout scanner to read `data.events`/`EvalSample.events`/`sample.store` -- but the message is the
minimal path that needs zero reader changes for the live scripts.

## D2 backing: artifact consumer map (what moves, what stays)

OPERATIONAL -- stays on disk (read live during run/resume/bake):
- `state.json` -- `state.py:52` `read_state`/`require_state` gates every tool + resume.
- `calibration.json` -- `history.py:113` `signed_C = float(json.loads(...)["signed_C"])` bakes each
  kept adapter; also `eval.py:110`.
- `judgment.json` -- `history.py:181` `action=="keep"` selects adapters to bake; `_n_keeps/_n_drops`
  stop counters (`agent.py:975-988`).
- `interview_pre.json` / `interview_post.json` -- `pipeline.py:1945` live A/B keep/drop input +
  teacher prompt (`agent.py:1029`).

AUDIT-ONLY -- movable into the log:
- `eval.json` / `eval_post.json` (readers: `plot.py:81`, report renderers, tolerate absence).
- `ab_judge.json` (no code reader; audit-run + CLAUDE.md only).
- `ab_judge_raw.json` -- SOFT live consumer `agent.py:1050` (regression-dashboard prompt guidance,
  "guidance only, never a veto") -> repoint or drop that read.
- `consistency.json` -- SOFT live consumer `agent.py:1079` (prompt guidance, "never a gate") ->
  repoint or drop.
- `selection_audit.json` (report/test/audit only).
- `candidate_ratings.json` (ZERO code readers).

## D3/D4 + Step 4 backing: mark_exam roles & re-homing checklist

- `next_focus`: written `pipeline.py:2249`, but the brief DELIBERATELY drops it
  (`agent.py:1032-1034` "Do not prime with prior-round next_focus: it can override the current PRE
  evidence"). Only a cosmetic history line (`agent.py:1006`) + plot/report read it. VESTIGIAL ->
  remove. (Tool docstring `agent.py:930` "Shown in the next round's brief" is misleading.)
- `harness_feedback`: required non-empty (`pipeline.py:2197`) AND fed to the next brief
  (`agent.py:1035` `_last_harness_feedback` -> `feedback_block`). LOAD-BEARING -> keep + re-home.
- mark_exam is the TERMINAL tool: it writes state `"done"` (`pipeline.py:2254`), which drives the
  `on_continue` round rollover (`agent.py:1248`) and the stop counters (`n_keeps>=keep_target`
  `agent.py:1194`, `n_drops>=MAX_DROPS` `:1199`, `max_rounds` `:1205`). react runs `submit=False`
  (`agent.py:1277`); tools list `agent.py:1268-1276`.
- Early-abort = mark_exam before training (`pipeline.py:2191-2195` -> `early_abort` drop).
- Gate-friction forced drop already calls `_mark_exam_pipeline` directly (`agent.py:1241-1245`) --
  keep that path reachable.

Re-homing checklist to make keep/drop auto-fire after `interview_post`:
1. Move the blind A/B + consistency flags (`agent.py:938-954`) to fire right after
   `interview_post.json` is written.
2. Capture `harness_feedback` at a different teacher turn (or synthesize) since the teacher no longer
   calls mark_exam; keep the `feedback_block` forward-feed alive.
3. Make `train_student` (or its wrapper) the state that lands on `"done"`; collapse the state machine
   `train_student -> mark_exam -> done` (`state.py:19,29-31`).
4. Give early-abort a new trigger (drop from `select_pairs`/`train_student` when no adapter).
5. Drop `next_focus` from the tool signature + `prompts.py` (`:939,1090-1092,1144`, `TOOL_MARK_EXAM`,
   `AFTER_MARK_EXAM`).

## Related parked tasks
- Retire "wiser" terminology (task #14): 15 uses in prompts.py, forward rename.
- This spec covers tasks #15 (consolidate storage) + #16 (mark_exam auto-commit).
