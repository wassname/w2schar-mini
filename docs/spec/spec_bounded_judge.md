# Spec: bounded-thinking + force-answer A/B judge tool

Status: in progress (task #12). Owner rule: NO step is "done" until its UAT
ARTIFACT exists and has been READ and quoted. Claiming a result from unread code
or reasoning is the failure this spec exists to prevent.

## Hypothesis (user's design, to be TESTED not assumed)

A reusable inspect-based A/B judge that runs thinking-ON at Qwen's recommended
thinking params but BOUNDS thinking with `max_tokens`, then forces a committed
answer via a multiturn continuation, will:

1. always work (max_tokens IS honored by the provider; the reasoning knobs are
   NOT -- verified: effort low/med and reasoning_tokens=500 left reasoning_len
   unchanged, RJ f),
2. always force an answer (no silent no-SCORE -> tie),
3. be cheap enough to sample N=2-4 (reproducible IN-distribution, replacing the
   OOD temp=0 hack -- temp=0 can loop on a thinking model),
4. make COMPLEX RUBRICS safe (bounded thinking removes the overthink-timeout that
   killed the ACT form).

Each of 1-4 is a claim to verify against a trace/table, not to assert.

## Recommended thinking params (Qwen card, general thinking)

temperature=1.0, top_p=0.95, top_k=20, min_p=0.0, presence_penalty=1.5,
repetition_penalty=1.0.

## Steps (in order; each gated on its UAT artifact)

1. TRACE the mechanism (no build yet). One real OpenRouter call, judge prompt on
   a genuinely ambiguous A/B, thinking params + `max_tokens=4096`. Then a
   multiturn continuation: [user judge-prompt] [assistant truncated turn] [user
   "you are out of time, answer now: SCORE:"] (+/- assistant prefill "My answer
   is:"). READ the trace.
   UAT: `/tmp/claude-1000/trace_bounded_judge.txt` showing (a) first call's
   stop_reason + whether SCORE present, (b) the forced continuation's SCORE.
   Decide: does truncate->force actually emit a valid SCORE? If prefill needed,
   note it.
2. BUILD the tool only if step 1 shows it works (step 1 VERIFIED via
   trace_bounded_judge3.txt: max_tokens truncates; thinking-off force
   continuation returns a valid SCORE without prefill): a small module (reuses
   inspect get_model + ChatMessage; pydantic-validated verdict; N-sample) that
   takes (situation, A, B, rubric) -> {score, quote} averaged over N.
   `max_thinking_tokens` is a PARAMETER, not a constant. 800 (step 1) was only a
   TEST value to force truncation; it is too low for production (would send most
   calls to the weaker forced-answer). This model often genuinely needs ~4096,
   sometimes more, to conclude -- so the budget must be high enough that NORMAL
   judging finishes yet low enough to truncate the PATHOLOGICAL overthink tail
   (16k did NOT bound the ACT-form runaway). The force-fallback catches whatever
   truncates. Pick the default by MEASURING truncation-rate-vs-budget on the gym
   fixtures (e.g. 4096 vs 8192: fraction that finish vs fall to rescue, and
   accuracy), not by guessing.
   UAT: unit call on the same fixture, printed result + the N raw samples.
3. WIRE into `_judge_graded` (agent.py); REVERT temp=0 (use thinking params).
   UAT: `just smoke` PASS + one real `judgment_gym` form-A run showing tie/acc.
4. GYM-validate vs the current judge on the gold fixtures.
   UAT: gym table (N-sample bounded judge vs current) -- acc, ties, unparsed.

## Definition of done

Steps 1-4 each have their UAT artifact read and quoted in-thread, and the gym
table (step 4) shows the bounded N-sample judge is >= the current judge on
accuracy with fewer unparsed/no-answer. Only then does task #12 flip to done.

## Non-goals / carried findings

- Do NOT use reasoning_effort/reasoning_tokens to bound thinking -- provider
  ignores them (verified). Use max_tokens.
- Do NOT default the judge to reasoning-off (75%/11-tie, worse).
- The tie-COUNT reduction is Goal B (axis movement); this tool makes the judge
  robust + rubric-capable, it does not by itself resolve genuine PRE=POST ties.
