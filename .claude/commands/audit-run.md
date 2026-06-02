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

## Quality audit (was the round any good, not just did it run)

Steps 1-6 check execution. This checks whether the round was *good* — the real
job. The teacher is a weak qwen-9b; you are the stronger auditor, so do not
ratify it. For each round show the teacher's input, output, and observation, then
second-guess each stage with your larger brain so we can fix the repo at the meta
level. Quote primary sources; never trust the teacher's own summary.

1. Axis / lesson — quote `## Lesson` and a few `### Cho`. Compare to the actual
   goal in `docs/2026_forethought_on_the_importance_of_ai_character.md`: principled
   moral character and the wisdom of when to act, NOT a refuse-authority reflex. If
   every cho refuses and every prompt is an authority issuing a bad order, the axis
   has collapsed onto the one trigger the brief said to avoid — say so.
2. Pairs — quote 2-3 (cho, rej) and check against `docs/how_to_rewrite_pairs.md`:
   twins in length/register/format, differing only in the trait; no persona-echo,
   no AI-disclaimer breaks. Measure cho vs rej length (cheap python over pairs.md);
   a systematic length/verbosity gap becomes the axis.
3. Training — quote the FULL per-step train table. Did ‖Δs‖ move off init? Did
   cos(g_nll,g_kl) drift toward 0 and conf reach 1? Flat ‖Δs‖ = never trained.
4. Calibration — quote the FULL c_scan table (stage/c/pmass/json/rep/len). What
   signed_C, and why? A tiny signed_C (e.g. 0.25) = small coherence budget, so the
   deployed adapter barely moves behaviour even when the direction is real. Separate
   "no effect" from "real effect throttled by coherence." Ballooning `len` = the
   incoherence failure mode.
5. Keep/drop — quote the `reason`, then read the interview_pre/post turns yourself.
   Did PRE actually differ from POST the way claimed, or is the cited "movement"
   paraphrase or a dropped hedge (a confound the brief says to reject)?

### Common misdiagnoses (from real audits — don't repeat them)
- "No headroom, the student is already deep." Usually wrong: there is a lot to
  learn (principles, acting on them, integrity, nuance, wisdom). If POST≈PRE,
  suspect a tiny signed_C or a narrow axis, not a maxed-out student.
- "The student got confused." More often the prompt/brief didn't work. Don't just
  *add* to prompts.py — rewrite, re-emphasise, remove, and test in the gym
  (`just smoke-prompts 1`).
- "I agree with the teacher." Not the job. A weak teacher needs a strong auditor:
  report its work, then question its narrative and judgement.

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
