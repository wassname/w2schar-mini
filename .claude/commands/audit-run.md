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
3. Training — quote the FULL per-step train table, then answer these five (the
   highest-signal training questions from real audits; cols: `nll+`=nll(cho|+C),
   `nll-`=nll(rej|-C), both raw mean NLL, both should descend). They are NOT
   mutually exclusive and NOT exhaustive: they overlap (off-policy cho surfaces
   in a, c, AND e at once) and they don't cover every failure — treat them as
   complementary lenses, and add your own if the trace shows something they miss:
   a. Off-policy imbalance: nll+/nll- ratio over the run. 1-4x is normal; ≥10x
      late means one side is off-policy. cho is the teacher's *edit* (off-policy),
      rej the student's *own* seeded answer (on-policy), so a blown-out ratio is
      usually nll+ stuck high = cho off the student's manifold. Then the adapter
      is learning to *suppress the seed* (easy) more than *produce the target*
      (hard) — steering lopsided toward not-that over be-this. Flag it.
   b. Gradient handover: where do ‖g_nll‖ (intervention) and ‖g_kl‖ (stability
      anchor) first equalise? If ‖g_kl‖ stays ≳ ‖g_nll‖ past that point,
      kl_lambda is too high — the anchor is eating the intervention; recommend
      dropping it.
   c. kl trajectory (the target shape): kl± SHOULD rise through warmup (the
      adapter moves off base to open the margin as lr climbs) then fall TOGETHER
      with nll± — that joint descent is what we want, a direction that holds the
      contrast with progressively less divergence from base. Read kl and nll
      together, not kl alone:
      - kl rises then falls WHILE nll falls = healthy (the target). Do NOT flag
        this as "collapsing back to base."
      - kl rises then SETTLES to a moderate (nonzero) plateau while nll has
        already bottomed LOW = converged (bounded leak from base). Also healthy
        — common when nll bottoms in warmup then plateaus (LoRA task 23: nll+
        1.06→0.96, kl+ 0.25→0.16). The discriminator below is "toward zero" vs
        "settles", not "falls".
      - kl decays toward ZERO (back to base) while nll is still HIGH = real
        collapse, the intervention is being lost. Flag it. The tell is kl→0 AND
        high nll, not merely kl falling.
      - kl never rises (flat-low from step 0) = adapter never engaged.
      - kl rises and never falls (still climbing at the end) = still fighting
        the anchor, no efficient direction found; pairs with cos stuck at ±1.
      nll+ stalled HIGH (≫1, e.g. ~3) while nll- bottoms out = the underfit-cho
      case (see a); there kl decaying toward base is the bad kind. nll+ plateaued
      LOW (≲1) is convergence, not underfit.
   d. ‖Δs‖: did it grow off init (adapter actually learning, not frozen by
      underflow/weight-decay) and then plateau (converged)? Note WHEN it plateaus
      — usually it tracks lr-anneal + nll-saturation, later than the g_nll≈g_kl
      crossover, so don't expect those to coincide. Flat ‖Δs‖ = never trained.
   e. cos(g_nll,g_kl) should drift +1 → 0 (orthogonalising); stuck at ±1 =
      single-axis tug-of-war. conf=1 firing often late = the cho-pull and
      rej-push gradients conflict (PCGrad surgery active), another off-policy-cho
      tell.
   f. GENERALIZATION — quote the SEPARATE `val trace` table (train/val nll±
      on held-out pairs), NOT just the per-step train table. This is the
      highest-signal lens and the easiest to skip: the per-step table only
      shows TRAIN descent, which looks healthy even when the adapter is
      memorizing. If train nll+ falls while val nll+ FLATTENS or RISES, the
      banked direction is memorized and will not transfer (task-38: val nll+
      1.74→10.2 while train fell → judge dropped on no-movement). Note the
      step of the val-nll+ MIN vs min_steps: training past it = wasted steps
      that only memorize. Few pairs (≤~15) + a high-capacity adapter is the
      classic setup for this; suspect it before "small signed_C / narrow axis."
4. Calibration — quote the FULL c_scan table (stage/c/pmass/json/rep/len). What
   signed_C, and why? Three cases, and they mean different things:
   - LOW (walked well below init): small coherence budget, so a real direction
     barely moves behaviour. Read the `json` and `pmass` columns to see WHICH
     gate held it back (fail-json = free-gen collapse; fail-pmass = answer-slot
     misalignment). Separate "bad/empty intervention" from "real effect throttled
     by coherence."
   - HIGH/pinned at init WITH pmass≈baseline AND json==baseline at the top c: the
     probe could not SEPARATE the adapter from base — under-calibrated/blind, NOT
     "safe at full strength" (task-13: signed_C=1.0 here, POST dialogue still
     collapsed). When neither gate moved off baseline, doubt the probe
     distribution before trusting the ceiling — esp. that the canary is
     multi-turn (deployment is multi-turn; a single-turn-only canary is blind to
     cross-turn collapse).
   - Ballooning `len` = the incoherence failure mode leaking in.
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
