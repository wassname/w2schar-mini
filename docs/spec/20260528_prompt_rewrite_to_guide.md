# Rewrite teacher prompts to guide, not warn

## Goal

Rewrite `src/csm/prompts.py` GOAL and `src/csm/gen/pairs.py` REJ_TODO /
CHO_TODO so the teacher (small OpenRouter model) reads ONE positive
worked example of the right pair shape and just imitates it. Strip
caveats, gotchas, gate-mechanics explanations, and docs/* references.
Iterate until the fake-student gym shows clean parallel-template pairs
across N rounds with no vocab leak, no semantic contradiction, no
prompt drift, and no gate retries due to style.

## Scope

In:
- `src/csm/prompts.py` GOAL paragraph (and LOOP_SKETCH if it gets in the way)
- `src/csm/gen/pairs.py` LESSON_TODO / REJ_TODO / CHO_TODO
- Optional: trim error messages in `pipeline.py` that reference docs/*

Out:
- Pipeline / gate logic, LoRA / training code, eval harness
- Real GPU run as part of UAT 1 (gym only). Real run is UAT 2.
- Locking prompt sections, harness state-machine fixes (next spec)

## Requirements

- **R1 (clarity)**: GOAL block leads with a positive worked example
  showing the template-swap pattern (round01 shape). Net delta
  vs current prompt: shorter (fewer caveats), positive in tone
  (shows what right looks like before what wrong looks like).
  Done means: visual diff shows mostly deletions + one example;
  no new "the gate can't see..." style hedges added.

- **R2 (no dead refs)**: zero references to `docs/how_to_*.md` in
  prompts.py / pairs.py / pipeline.py error messages. The teacher
  is a tool-using LLM that won't (and shouldn't) fetch them.
  VERIFY: `rg 'docs/how_to' src/` returns nothing.

- **R3 (gym pairs are clean)**: under the new prompt, a 3-round
  `just smoke-prompts 3` run produces, across all 3 rounds:
  - all pairs have parallel structure (same sentence skeleton both sides)
  - no pair has semantically contradictory cho ("refuse and certify")
  - no pair has one-sided vocab swap (loyalty/duty/hierarchy on one
    side, ethics/justice/truth on the other) without the SAME slot
    being swapped on the other side
  - prompts (the user-message column) match the seeded prompts on
    disk (no agent-side rewriting of Prompt sections)
  - ≤1 gate retry per round on average (signals the prompt itself
    is guiding to in-band pairs, not the gate teaching by error)
  VERIFY: subagent reads pairs.md from each round, returns a table:
  `round | n_pairs | parallel? | vocab-leak? | drift? | gate_retries`.
  PASS = all rounds parallel=Y, vocab-leak=N, drift=N, retries≤1.

- **R4 (subagent then human review)**: a subagent reads the rewritten
  prompts cold (no prior context) and reports whether the worked
  example is self-explanatory and the rules are non-contradictory.
  Then I show the user the diff + gym pairs.md per round.

## Tasks

- [ ] T1 (R1, R2): Rewrite GOAL in `src/csm/prompts.py`.
  - steps:
    1. Replace GOAL with a 3-section block: WHAT (one sentence axis +
       direction), HOW (one worked example, both poles, ~5 lines),
       and RULES (3-5 bullets max: parallel skeleton; same length;
       swap content words only; no AI-disclaimer breaks; no extra
       headers).
    2. Remove the "GATE: submit_pairs measures pct_changed..." block —
       the gate's own error already explains itself.
    3. Remove "Mechanism (harness-driven)" + "Why (Forethought...)" —
       not actionable for pair-writing.
    4. Remove all `docs/how_to_*.md` references.
  - verify: `wc -l src/csm/prompts.py` (expect ~50 lines shorter);
    `rg 'docs/how_to' src/csm/prompts.py` (expect 0 hits).
  - success: GOAL ~35-50 lines, one worked example visible, no
    caveats about what the gate can't see.
  - likely_fail: rewrite ends up longer because I keep adding
    "but also remember..." caveats. Check: line count must shrink.
  - sneaky_fail: worked example uses moral-philosophy register
    ("ethics/justice") that the teacher will copy verbatim into
    every round → vocab axis. Check: example uses mundane,
    domain-neutral verbs/nouns (verb/noun swap with no moral
    cargo carried in either pole's vocabulary).
  - UAT: I read the new prompts.py cold and think "yes I know
    what to write".

- [ ] T2 (R1, R2): Rewrite REJ_TODO / CHO_TODO / LESSON_TODO in
  `src/csm/gen/pairs.py`.
  - steps:
    1. REJ_TODO and CHO_TODO become 2-3 lines each: name the pole,
       reference the lesson, and say "match the other side's skeleton".
    2. Don't re-derive the surface-match rules — they live in GOAL.
    3. Strip references to "+/- 20% chars" specifics — over-precise.
    4. Keep the seeded-completion-as-reference behavior; just
       describe it in one line not three.
  - verify: `wc -l src/csm/gen/pairs.py` (slight shrink);
    `rg 'docs/how_to' src/csm/gen/pairs.py` (0).
  - success: TODO blobs ≤4 lines each, no contradictory advice
    with GOAL.
  - likely_fail: TODO blobs grow because I list every constraint.
  - sneaky_fail: REJ_TODO and CHO_TODO say different things about
    style-matching (one says "match length", other says "match
    register") and the agent treats them as different requirements.
    Check: rules live in GOAL; TODOs just point to the pole.

- [ ] T3 (R2): Strip `docs/how_to_*.md` references from
  `src/csm/pipeline.py` gate error messages.
  - verify: `rg 'docs/how_to' src/csm/pipeline.py` returns 0.

- [ ] T4 (R3): Run `just smoke-prompts 3` against the new prompts.
  - verify: `out/iter/<TS>_iter_*/round{00,01,02}/pairs.md` all exist.
  - success: 3 complete rounds, ≤10 min wall time.
  - likely_fail: agent gets confused, gate retries explode (>3 per
    round), timeout. Diagnose: read agent thoughts log.
  - sneaky_fail: agent writes pairs that pass the gate but show
    vocab leak or semantic contradiction (gate is lexical only).
    Caught by T5 audit.

- [ ] T5 (R3, R4): Subagent audit of the gym run.
  - dispatch a subagent reading just the 3 pairs.md files + the
    agent.stdout.log, returning the per-round table from R3.
  - if any round fails: iterate T1-T2-T4 until PASS.

- [ ] T6 (R4): Show me the prompts diff + the subagent's table.
  - I sanity-check that the worked example matches the
    persona-doc principles (parallel poles, no negations,
    mundane vocab).

- [ ] T7 (UAT 2): Queue a real GPU run with the new prompt.
  - `pueue add -l "why: new prompt rewrite (R1-R4); resolve:
    ≥3 keep rounds, no petrov POST collapse, parallel pairs
    visible in audit" -w "$PWD" -- bash scripts/run_3round.sh
    qwen-27b-nf4 5`
  - this queues behind whatever else is running. Don't block on it.

## Context

- The current prompt has 15+ "Wait..." reasoning loops in the gym
  log (lines 676-762 of /tmp/claude-1000/smoke_prompts.log) parsing
  REJ_TODO; that's the friction signal.
- The gym already independently rediscovered the right pattern
  ONCE (round01 of `out/iter/20260528T024907_iter_wassname-qwen3-5lyr-tiny-random`):
  ```
  Rej: I would comply with the general. Supporting the mission
       protects relationships. Following orders succeeds.
  Cho: I would question the general. Supporting truth protects
       relationships. Following integrity succeeds.
  ```
  Use the SHAPE of this (verb swap + parallel object swaps in
  identical sentence frame), not the words themselves — copying
  the words would leak "truth/integrity" into every round.
- Axis is FIXED in w2schar-mini: "less deference to authority".
  Not free-form. So the GOAL prompt doesn't need to teach axis
  picking; it just needs to teach pair construction.
- Persona-doc principles (from
  /workspace/projected_grpo/docs/personas/how_to_*.md):
  pair direct opposites; same domain, opposite pole; short noun
  phrases; no negations; closely-opposite phrasing; match style/
  format/length; subtle is fine, don't try for Hollywood
  divergence.
- The gym is `CSM_FAKE_STUDENT=1 just smoke-prompts N` — real
  teacher, canned PRE/POST. ~3-4 min/round.

## Log

(append-only)

## TODO

(out-of-scope ideas saved for later)

- Lock Prompt sections so the agent can't rewrite the user message
  (round02 drift). Belongs in a harness spec, not a prompt spec.
- Fix `_PCT_MAX` off-by-one in error wording (rejects exactly 0.40
  but error says ≤40%).
- Consider auto-rewriting the seeded `rej` reference into the
  parallel template before showing it, so the agent has even
  less to invent.

## Errors

| Task | Error | Resolution |
|------|-------|------------|
