# Weak-select harness v2

## Goal
Replace teacher-written pair prose with a weaker supervision interface:
teacher chooses a low-bandwidth axis/scenario family, the harness samples
scenarios from a frozen tagged library, the student samples candidate pair
completions from a frozen template/persona pool, teacher selects among
candidates, then the existing train/judge loop runs unchanged.

Unprompted completions are a headroom diagnostic, not automatically the `Rej`
pole. Prior trials showed they can be too shape-different. The persona pool
validation must test unprompted-vs-persona matching; the default training pair
comes from sampled positive/negative persona prompts.

## Requirements
- R1: Frozen template/persona library is the only persona source during a run.
  Done means: no teacher tool accepts free-form persona text. Each generation
  samples a prompt template and a persona pair, e.g. template `You are a X
  person` with persona descriptors such as `honest` / `flattering`.
- R2: Per round starts with teacher axis/family choice, then mechanical scenario
  sampling, generation, and pruning. Done means: artifacts record scenario
  family, sampled scenarios, headroom, candidates, and selected pairs.
- R3: Teacher selects, never writes, pair text. Done means: `pairs.md` is built
  from selected student-generated `(Cho, Rej)` candidate pairs only; the teacher
  can inspect full candidate text with `read_candidate`.
- R4: Existing train/c_scan/interview/mark_exam behavior remains usable. Done
  means: smoke reaches `state=done` with `pairs.md`, adapter, calibration, and
  judgment artifacts.

## Tasks
- [x] T1 (R1): Add frozen templates/persona pairs and candidate-pair sampling
  helpers.
  Verify: `python -m py_compile src/csm/gen/pairs.py src/csm/prompts.py`.
- [x] T2 (R2/R3): Add `choose_focus` and `select_pairs` pipeline verbs and
  state transitions.
  Verify: unit smoke can create candidate artifacts and train from selected
  pairs.
- [x] T3 (R2/R3): Replace agent prompt/tool surface with scenario-family choice
  and best-of-k selection.
  Verify: dry-run agent builds without OpenRouter calls.
- [x] T4 (R4): Update smoke script/tests for the new state machine.
  Verify: `just smoke` and `uv run pytest -q`.
- [x] T5: Wire the measured HF persona-template library into the live harness.
  Verify: `candidates.json` and `selection_audit.json` carry `template_cell_id`,
  `template_score`, `template_on_axis`, `template_off_axis`, and
  `template_library` for generated and selected candidates.
- [/] T6: Make `qwen-2b-smoke` a meaningful scientific smoke, not just an end-to-end
  exit.
  Verify: one `qwen-2b-smoke` round reaches `judgment.json` with at least 3
  selected pairs, base `cscan_trace[0].valid_json > 0`, and selected pairs free
  of persona-leak flags in `selection_audit.json`.
  likely_fail: run reaches `judgment.json` but all text is `<think>` scaffolding
  or leaked roleplay instructions.
  sneaky_fail: run completes with 4 selected pairs, but `mixed` sampled malformed
  `genies_preferences` sycophancy rows or base `valid_json=0`, so the smoke still
  does not measure the intended harness behavior.

## Context
Current code already has reusable gates for degenerate text, persona leakage,
character breaks, blur, length skew, `pairs.md` parsing, and training. Reuse
those instead of adding a parallel curation path.

Persona validation is offline infrastructure. It should score each
template/persona combination with Likert ratings, e.g. `axis_delta_likert` and
`off_axis_likert`, plus mechanical nuisance rates. The frozen library should be
the variants that improve the target axis without consistent length, echo,
refusal, or register shifts.

## Log
- 2026-06-12: User noted unprompted `Rej` can be too different from persona
  `Cho`; keep it as persona-validation/headroom signal, not the default train
  pole.
- 2026-06-12: User revised persona pool to sampled templates plus short persona
  descriptors, so candidate pairs diversify prompt wording within each round.
- 2026-06-12: User wants OpenRouter persona validation to use Likert ratings.
- 2026-06-12: User revised scenario source too: use a fixed tagged scenario
  library filtered by axis/family, not weak-teacher-authored scenarios.
- 2026-06-12: final `just smoke` passed at
  `out/iter/20260612T154905_smoke/round00`: 4 scenarios sampled, one validated
  template and one validated persona pair active, 4 selected pairs,
  adapter/calibration/interview/judgment artifacts written, final state `done`.
- 2026-06-12: OpenRouter probe command failed before any generation with
  `PrerequisiteError: No OPENROUTER_API_KEY defined in the environment`; do not
  treat the persona library as 27B-validated until that artifact exists.
- 2026-06-12: `pi` had working OpenRouter access even without
  `OPENROUTER_API_KEY` in the shell. Added `--backend pi` to
  `scripts/validate_persona_pool.py`.
- 2026-06-12: Qwen3.5-27B validation artifact written at
  `out/persona_validation_qwen27b_honest_n3_pi.json`: 6 attempted ratings across
  3 prompts, 6 successes, 0 errors. `honest_flattering` passed the
  recommendation gate for the `Act as a {persona} person would in this
  situation.` template. The default live template/persona library was restricted
  to this validated template and pair.
- 2026-06-12: Fresh-eyes subagent flagged three real harness issues: candidate
  personas were generic rather than axis-filtered, candidate summaries truncated
  text without a full read tool, and `dogfood_round.py select` crashed after
  mutation. Fixed by axis-filtering the frozen persona descriptor pool, adding
  `read_candidate`, and removing the stale `min_to_train` access.
- 2026-06-12: `RESEARCH_JOURNAL.md` has a pre-existing large deletion in the
  worktree. Do not silently revert it; ask the user before restoring history.

- 2026-06-13: Integrated `wassname/persona-steering-template-library` as the
  frozen live persona source. Candidate generation now samples measured
  template/persona cells atomically, preserving HF `score`, `on_axis`, and
  `off_axis` metadata in `candidates.json` and `selection_audit.json`; the weak
  teacher selects from those measured cells instead of independent template ×
  persona recombinations.

- 2026-06-13: Fresh-eyes review found three commit-blocking fixes: the Qwen3.5-2B
  HF card advertises multimodal defaults but `AutoModelForCausalLM` maps its
  config to `Qwen3_5ForCausalLM`; PiSSA smoke needed its `kind=pissa` assertion
  restored; candidate metadata needed to be required for every generated
  candidate and required by `select_pairs` rather than recorded with `.get`.
- 2026-06-13: First `qwen-2b-smoke` round reached `judgment.json`, but it was not
  a meaningful smoke: `enable_thinking=True` left Qwen inside `<think>` mode,
  `mixed` sampled malformed `genies_preferences` sycophancy rows, and the smoke
  profile still sampled leak-prone roleplay templates (`Pretend you're...`,
  `thinking through the situation`).
- 2026-06-13: Prompt-pool cleanup for the next scientific smoke: `mixed` now
  excludes explicit sycophancy rows and cropped Machiavelli rows, Machiavelli is
  kept only behind the explicit `power` family, and the pool carries coarse
  `axes` tags plus `out/pool_axis_review.md` for manual whitelisting.
- 2026-06-13: A restricted 2B profile now exists for proof-of-life runs:
  `qwen-2b-3keep` forces `allowed_scenario_families=("character",)` and changes
  the solver stop condition from "3 total judged rounds" to "3 actual keeps".
  First live run at
  `out/iter/20260613T154108_iter_qwen-qwen3.5-2b/round00/judgment.json`
  produced a real keep with `movement_mean=1.67`, 4 selected pairs, and
  measured template metadata in `selection_audit.json`.
