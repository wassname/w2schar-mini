---
description: Smoke + diff review → pueue add → schedule audit checkpoints at +10/+30/+60 min.
argument-hint: <profile> <n_rounds> [--after <task_id>]
---

End-to-end "land a change and watch the run" loop. Use after a code change has landed in git.

## Args

- `$1` — profile (e.g. `gemma-9b`, `gemma-27b`)
- `$2` — n_rounds (e.g. `5`, `10`)
- `--after <task_id>` (optional) — chain after a queued/running pueue task

## Steps

1. **Smoke** — `just smoke` and confirm `=== smoke PASS ===` in the output. If it fails, STOP and report.

2. **Diff review** — spawn a subagent (general-purpose) on `git diff HEAD~1` with this brief:
   > Review the last commit for correctness, simplicity, and consistency. List any concerns in 1-2 bullets each. Keep total response under 200 words. Do not propose new features.

   If the subagent flags a blocking issue, STOP and report.

3. **Queue** — `pueue add --label "why: <one-line hypothesis>; resolve: <what success looks like>" -w "$PWD" [--after $TASK_ID] -- bash scripts/run_3round.sh $PROFILE $N_ROUNDS`. Save the new task id.

   The label MUST be filled with the actual hypothesis driving this run (e.g. "9b 10-round on bake+layer_range to verify ~2x speedup and that (0.2,0.8) doesn't degrade coherence"). Don't reuse generic boilerplate.

4. **Schedule audit checkpoints** — call `ScheduleWakeup` three times:
   - +10 min: `/audit-run <slug> aggressive`
   - +30 min: `/audit-run <slug> aggressive`
   - +60 min: `/audit-run <slug> patient` (by this point we're committed)

   Pass the slug path so each wake doesn't re-resolve "latest" (which could be wrong if a parallel run kicks off).

5. **Report** — one short message: task id, label, slug path, when the first audit will fire. Then yield until the wake.

## Notes

- Don't proceed past step 1 if smoke fails — there's no point queuing a broken commit.
- Don't proceed past step 2 if the reviewer flags a blocking issue — fix it first.
- The slug path doesn't exist yet when you queue; it'll be the next-created dir under `out/iter/`. The wake-up handler can re-resolve via `ls -dt out/iter/2026*_iter_<profile>* | head -1` if needed.
