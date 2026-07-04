# Review scope — 2026-07-04 session (for a 2nd opinion)

What changed this session: bounded-thinking keep-judge (Goal A), axis cull on our student
(Goal B), the axis validator renamed + defaulted to real models, and global self-check hooks.
Commits: 5349858, 35cc483, 50af4c8 (judge + UAT + journal); c8f051d, fdd983b (Goal B);
6803218, 0042a90, 41fc557 (rename); hooks in dotfiles repo (3f8f2a0). task-147 queued.

## For fable — open questions & risks, ranked by leverage

1. **Does the new keep-judge produce KEEPS live, or still tie-and-drop?** The UAT
   (out/gym_bounded_judge/report.md) was on the HARDEST fixtures (adjacent gold ranks of
   5-way cases): of 21 pairs, 10 correct, 2 confidently WRONG, 9 ties. So ~83% accuracy WHEN
   it commits, but 43% ties. journal-(f)'s failure was ties -> sign-test auto-rejects the
   round. Real PRE/POST should separate more than adjacent ranks, but this is unverified
   until task-147 runs. Q: is the aggregation right -- two-pass side-swap, then N=2 average,
   then deadband=1.0? Could the side-swap (avg = (d1-d2)/2) be cancelling real movement into
   ties when the judge has position bias?

2. **Budget / forced-answer trust.** JUDGE_THINK_BUDGET=4096 was NOT tuned by a sweep;
   forced-rate ~46%, i.e. half the verdicts come from a thinking-OFF forced continuation on
   truncated reasoning. 2 confident WRONG verdicts exist (successor 1v2 -2.0, starwisp 2v3
   -1.5). Q: is a forced answer as trustworthy as a full-think one; is 4096 right; is N=2
   enough (N=1 vs 2 vs 3 accuracy is UNTESTED -- I only ran N=2)?

3. **Goal B cull rests on ONE n=6 run with a PROXY judge** (gemini-flash-lite). A real-model
   re-validation (teacher as judge, out/persona_axes_live18_realjudge.json) is running but
   NOT yet read. Risk: the cull disagrees under the exact-model judge. Also the verifier
   subagent flagged that externality_actfork's low delta is partly a "fixture invites blanket
   refusal" artifact, not proof the axis is inert -- so dropping it may be discarding a real
   axis that just had bad scenarios. Q: cull vs fix-the-scenarios; is 15 axes enough
   diversity or is a backfill of measured strong movers needed?

4. **Axis-gym judge default -- teacher-as-judge FAILED (measured).** I switched the gym
   default to judge=teacher (qwen3.5-9b) per "use real models", and re-ran: 177 of 324 pairs
   ERRORED (out/persona_axes_live18_realjudge.json, n_success=147/324). The weak 9b cannot
   reliably emit the structured axis-judgment -- which is WHY gemini-flash-lite was the
   original default. Lesson: the generator SHOULD be our real student (a thing under test),
   but the axis-gym JUDGE is a measuring INSTRUMENT, not a pipeline component, so it should be
   a reliable strong judge, not the weak teacher. OPEN DECISION: revert --judge-model default
   to a neutral strong judge (keep --generator-model = student), or accept a partial/biased
   measurement. Also unresolved: qwen-on-qwen self-preference if we did keep teacher-judge.
   Until this is settled the Goal B cull still rests only on the gemini n=6 run.

5. **Hooks** are separately scoped in ~/.claude/hooks/REVIEW_PROMPT.md. Headline risks: the
   TaskCompleted hard-block can become goodhart theatre (a rubber-stamp subagent passes it);
   global scope = noise in unrelated projects; the Stop regex gates on artifact-token
   PRESENCE not on whether the artifact supports the claim. Deep Q: are deterministic hooks
   the right layer for "don't over-claim," or a patch I learn to satisfy hollowly?

6. **Process risks to flag:** task-146 (OLD stack, still running) is unaudited -- it is the
   comparison baseline, do not lose it; a pre-existing uncommitted CLAUDE.md edit got bundled
   into the rename commit (6803218); the live run task-147 has never exercised the bounded
   judge or the culled menu on a real GPU student.

## For codex — writing / comment cleanup (long, jargon-laden, archaeological)

The pattern to fix: comments that NARRATE HISTORY ("Row 22 removed 2026-07-04 because...")
and stack coined jargon without local definition, where a one-line statement of intent plus
a journal pointer would do. Keep the repo's terse voice; move the archaeology to the journal.

- `src/csm/prompts.py` MULTI_AXIS_PERSONA_CELLS: stacked dated removal notes (Row 16, Row 22,
  Row 25, plus the earlier menu-audit block). Reads as a changelog embedded in data.
- `src/csm/agent.py` `_judge_graded` / `_judge_sample` / `_blind_ab_votes` docstrings: dense,
  reference RJ dates, use coined terms (POST-signed, side-swap, deadband, force-answer)
  without defining them where a first-time reader meets them.
- `src/csm/config.py` JUDGE_* block and the coherence-canary rules: dense but mostly load-
  bearing; lighter touch.
- The `RESEARCH_JOURNAL.md` (g) entry is intentionally dense (journals can be); lower priority.

Ask codex to cut history-narration and undefined coinages, not the load-bearing "why".
