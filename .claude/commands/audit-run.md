---
description: Audit the current (or named) pueue run — timeline, decision, next action.
argument-hint: [slug] [mode:aggressive|patient]
---

Audit the agent run. Default to the latest slug under `out/iter/` unless an explicit one is passed.

## Mode (second arg, default `aggressive`)

- **aggressive** — we're iterating fast on the harness/prompts; lower the bar for kill+fix.
- **patient** — we're committed to a long run (e.g. 27b overnight); only kill on hard failures.

## Steps

1. Resolve the slug:
   - If `$1` is given, use it; otherwise `ls -dt out/iter/2026*_iter_*/ | head -1`.
   - Confirm a `*_task_*.json` exists inside.

2. Identify the pueue task id by matching the slug path in `pueue status`. Save the id; if no live task matches, treat as a post-mortem (no kill recommended, just report).

3. Pull pueue tail:
   `pueue log $ID --full > /tmp/audit-$ID.log` (then read with offset/limit; never paste the whole thing). Grep for:
   - `Traceback` / `OOM` / `CUDA error` → **crash**
   - `submit_pairs(` count vs `train_student(` count → retry-loop signal if submit ≥ train + 3
   - `mark_exam.*action.*drop` count → drop-streak signal

4. Read each round's artifacts (cheap, no GPU):
   - `out/iter/<slug>/round*/judgment.json` → `action`, `next_focus`
   - `out/iter/<slug>/round*/state.json` → which verb the agent stalled on
   - `out/iter/<slug>/round*/eval.json` → mean_p movement vs round00 (if eval has run)

5. If steps 3–4 show **artifacts fine but agent might be confused** (e.g. unusually long lesson edits, persona flip), pull the monologue: `just thoughts` (live samplebuffer or completed log). Otherwise skip — most checkpoints don't need it.

6. Emit a structured report with the headings below. Keep each section ≤ 6 lines.

## Report format

```
=== audit: <slug> (task $ID, mode=<aggressive|patient>) ===

# Timeline
rNN  action(keep/drop/incomplete)  axis-hint  Δtime
... one line per round ...

# Tool-call counters (last 200 lines of pueue log)
submit_pairs: N  | train_student: M  | mark_exam: K

# Decision: CONTINUE | INVESTIGATE | KILL+FIX
<one-line reason>

# If KILL+FIX:
- root cause (one sentence)
- fix (specific file + change)
- post-fix: smoke + subagent review + re-queue with --after <prior_dep>
```

## Kill+fix triggers (any one ⇒ KILL+FIX)

- **Crash / traceback** in pueue log
- **Retry loop** — `submit_pairs` called ≥ 3 times without an intervening `train_student` since the last reset
- **3+ drops in a row** (aggressive) or **5+ in a row** (patient)
- **Productivity judgment** — if the run is unlikely to produce useful data even when it finishes (e.g. eval.json mean_p deltas stuck at noise, every round dropping for the same reason). Use scout-mindset judgment, not a hard rule. State the reason explicitly.

## After the report

If running and **CONTINUE/INVESTIGATE**: schedule the next checkpoint with `ScheduleWakeup` (typical: +20 min after t+10, +30 min after t+30, then stop). Skip if user passed a slug explicitly (one-shot mode).

If **KILL+FIX**: do NOT auto-kill. Print the kill command and the proposed fix, then stop and wait for the user's confirmation. Risky-action rule: kills + restarts touch shared state.
