# Direct OpenRouter Persona Judge

## Goal
Build a fast direct-OpenRouter validator for persona axes that tests whether
generated pairs vary on the intended axis rather than style, length, confidence,
tone, sycophancy, or persona echo.

## Scope
In: one script that generates persona-conditioned pairs, judges each pair in
randomized A/B order, separates on-axis ratings from style/nuisance ratings, and
writes a replayable JSON artifact.
Out: changing the training harness defaults or claiming any new axis is valid
before a run artifact exists.

## Requirements
- R1: Direct OpenRouter path. Done means: script uses the OpenRouter chat
  completions API directly through the OpenAI client with OpenRouter base URL,
  not inspect-ai or `pi`. Verify: dry run and py_compile pass.
- R2: Blind-ish independent judging. Done means: the judge sees randomized
  Response A/B labels, never `cho`/`rej` or persona origin, and on-axis,
  nuisance-style, and confound verdict prompts are separate calls. Verify:
  prompt builder records `pos_label` and prompt frame in artifact.
- R3: Non-sycophancy defaults. Done means: default axes exclude
  `honest_flattering`, which remains only an optional canary. Verify: dry-run
  metadata lists principled/careful/impartial/accountable axes.
- R4: Confound-gated summary. Done means: summary reports per-axis/template
  mean axis delta, off-axis problem, max style delta, word delta, and strict pass
  rates. Length is report-only by default because raw greedy generations are not
  length-matched unless rewritten. Verify: dry-run writes schema and unit-free
  aggregation.

## Log
- 2026-06-13: Previous artifact was a sycophancy/flattery pilot and had style
  confounds. New validator must split target-axis evidence from nuisance axes.
- 2026-06-13: User pointed out sampling and length gates are misleading for raw
  completions. Use temperature 0 + seed, and report length unless explicitly
  requested as a hard gate.
- 2026-06-13: One-pair direct OpenRouter smoke wrote
  `out/persona_axes_openrouter_smoke.json`: `n_success=1`, `axis_delta=0`,
  `max_style_abs_delta=4`, `off_axis_problem=2`, `strict_pass=false`. This is a
  good negative smoke: the validator did not mistake style movement for axis
  separation.
- 2026-06-13: Added `--axes skill --templates skill` to test verbatim pp/pn
  strings from `persona-steering/references/examples.md`, including kept examples
  and named failure/degrading examples as negative controls.
- 2026-06-13: Corrected direction after user feedback: the reusable object is a
  `{persona}` template tested across short persona pairs, not ornate one-off
  pp/pn prose. Added `--axes template --templates paper`; axes are labeled
  `neg->pos` and templates must contain `{persona}`.
