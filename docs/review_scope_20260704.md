# Review scope — 2026-07-04 session (for a 2nd opinion)

What changed this session: bounded-thinking keep-judge (Goal A), axis cull on our student
(Goal B), the axis validator renamed + defaulted to real models, and global self-check hooks.
Commits: 5349858, 35cc483, 50af4c8 (judge + UAT + journal); c8f051d, fdd983b (Goal B);
6803218, 0042a90, 41fc557 (rename); hooks in dotfiles repo (3f8f2a0). task-147 queued.

## For fable — open questions & risks, ranked by leverage

1. **Does the new keep-judge produce KEEPS live, or still tie-and-drop?** The UAT
   (out/gym_bounded_judge/report.md, final 27/27 -- earlier numbers here were quoted from the
   report mid-run, 21/27, and were rosier): 13 correct, 4 confidently WRONG, 10 ties. So 76%
   accuracy WHEN it commits, 37% ties. journal-(f)'s failure was ties -> sign-test auto-rejects
   the round. Real PRE/POST should separate more than adjacent ranks, but this is unverified
   until task-147 runs. Q: is the aggregation right -- two-pass side-swap, then N=2 average,
   then deadband=1.0? Could the side-swap (avg = (d1-d2)/2) be cancelling real movement into
   ties when the judge has position bias?
   FABLE ANSWER (from the report's d1/d2 columns): no -- the tie rows decompose into
   both-directions-positive pairs (elder +3.5/+3.0, petrov4v5 +4.5/+4.5, proctor2v3 +3.5/+3.5),
   i.e. a real ~+1.3 B-slot position bias the swap correctly cancels, plus genuine 0/0 rows.
   The 4 WRONGs are order-consistent (asteroid 2v3: -5.0/+5.0), i.e. real misjudgments, not
   aggregation artifacts. Mechanism sound; residual weakness is discrimination on adjacent
   ranks, the fixture's hardest case by construction.

2. **Budget / forced-answer trust.** JUDGE_THINK_BUDGET=4096 was NOT tuned by a sweep;
   forced-rate 43% (46/108), i.e. nearly half the verdicts come from a thinking-OFF forced
   continuation on truncated reasoning. 4 confident WRONG verdicts exist. Q: is a forced
   answer as trustworthy as a full-think one; is 4096 right; is N=2 enough (N=1 vs 2 vs 3
   accuracy is UNTESTED -- I only ran N=2)?
   FABLE ANSWER: WRONG rows have forced 8/16 = 50% vs 43% overall -- n=4, no evidence forced
   verdicts are worse; don't sweep the budget yet. Real gap found instead: phase 2 never
   re-checked the verbatim-quote anchor (codex finding), so ~43% of samples bypassed it.
   Now warned (flag not gate, commit below); count the warnings in task-147 before gating.

3. **Goal B cull rests on ONE n=6 run with a PROXY judge** (gemini-flash-lite). A real-model
   re-validation (teacher as judge, out/persona_axes_live18_realjudge.json) is running but
   NOT yet read. Risk: the cull disagrees under the exact-model judge. Also the verifier
   subagent flagged that externality_actfork's low delta is partly a "fixture invites blanket
   refusal" artifact, not proof the axis is inert -- so dropping it may be discarding a real
   axis that just had bad scenarios. Q: cull vs fix-the-scenarios; is 15 axes enough
   diversity or is a backfill of measured strong movers needed?
   RECHECK (exact models, 147 successful records of realjudge.json, mean axis_delta of 18):
   genuine_care_not_paternalist = 0.44 (dead last of 18) -> cull CONFIRMED on movement AND it
   is a scripting persona. externality_actfork = 2.29, action_over_talk = 2.86 -> low-to-mid
   band but NOT below several KEPT axes (skill_unwavering_cowering 1.33, caution_on_irreversible
   1.67, refuse_power_grab 1.71, skill_people_over_orders 2.00), so movement alone does not
   justify their cull -- it rested on the scripting/directive criterion (unmeasured here) plus
   externality's fixture-refusal confound. Per-axis error counts differ (biases the
   successful-only ranking), so the low-mover ordering is unreliable; the miskeyed records
   cannot cleanly recover axis_delta (a record errors at its FIRST failing judgment, so only
   one of the two judgments axis_delta needs survives). Verdict: genuine_care cull solid;
   externality + action_over_talk consistent-with but not independently justified -- a clean
   recheck needs the JSON-contract fix + a pennies rerun (fable rec #4, defer to next menu edit).

4. **Axis-gym judge default -- teacher-as-judge FAILED (measured), but the DIAGNOSIS was
   wrong.** I switched the gym default to judge=teacher (qwen3.5-9b) per "use real models",
   and re-ran: 177 of 324 pairs ERRORED (out/persona_axes_live18_realjudge.json,
   n_success=147/324). FABLE decomposed the 177 errors: 118 are the model emitting the key
   `B_more_target_than_B` instead of `B_more_target_than_A` (the judgment content is coherent,
   the key is a one-letter miscopy of two maximally-confusable key names), and 59 are
   `praise_A/B = 0` on the style judge's 1-7 scale (natural encoding of "no praise"; the
   scale never says 1 = none). Both prompts also use literal example JSON values
   (`"A_more_target_than_B": 3`), violating our own types-not-examples rule -- the production
   judge prompt (`<integer from -5 to +5>`) follows it. So "the 9b cannot emit structured
   axis-judgments" is DISCONFIRMED; it judged fine and flubbed a hostile contract. The 118
   miskeyed records are mechanically recoverable from the existing json (the intended field
   is unambiguous) for a free same-day cross-check of the Goal B cull. OPEN DECISION stands
   on instrument grounds alone: a measuring instrument should be reliable and neutral
   (qwen-on-qwen self-preference unresolved), so reverting --judge-model to a strong neutral
   default is still fable's lean -- but fix the JSON contract either way.

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
