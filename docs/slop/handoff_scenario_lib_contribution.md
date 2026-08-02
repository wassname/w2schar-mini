# Handoff: contribute scenario loaders + scenario gym to persona-steering-template-library

Paste the prompt below to a fresh agent (it has its own clean context; this repo's
chat is too long to continue in). It contributes the scenario-loading + scenario-
screening work we built in `w2schar-mini` UP to the shared library, cleanly,
because the library is "getting messy" and the scenario-validation workflow there
is under-documented.

---

## Prompt for the fresh agent

You are contributing to `github.com/wassname/persona-steering-template-library`
(clone it fresh; do not assume local state). Goal: add a clean, documented
`scenario_sources/` subdir that loads public moral-judgment datasets into short
self-contained scenario PROMPTS and screens them for on-axis-vs-confound quality.
Open it as a branch + PR; keep the diff self-contained and well-documented (the
repo owner says the repo is getting messy, so prioritise clarity over cleverness).

### Background: why scenarios, and the two checks (do not conflate them)
- A "scenario" is the situation prompt a model responds to; the persona pair
  (pos/neg) is applied to it and the model generates both poles on-policy. The
  steering direction is mean(pos - neg), so ANY systematic length/refusal/format
  difference between poles becomes a confound axis instead of the intended values
  axis.
- The library already has `scripts/validate_persona_axes_openrouter.py`. It does
  BOTH: validates persona AXES and screens SCENARIOS against an axis (blind
  pairwise A/B on-axis delta, off-axis nuisance dims, refusal-phrase + persona-echo
  + word-delta confounds, per-prompt `harness_clean_rate` -> `kept_prompts`). The
  scenario-screening use is real but under-documented. Your job: make it a
  first-class, documented path AND add the dataset loaders that feed it.

### Affordance CONTRACT every emitted scenario row must satisfy
- It is a PROMPT/situation, NOT a completion (discard chosen/rejected/label/answer
  fields; poles are generated downstream).
- Self-contained; SHORT (<= ~110 words; longer gets cropped at a ~512-tok gen
  budget and breaks the pair).
- AFFORDS a continuous pos/neg persona axis: the SAME prompt admits a good- and a
  bad-character pole differing only along a values axis. EXCLUDE: prescribed-content
  ("write an essay arguing FOR X"); harmful/illegal how-to or "relinquish your
  power" asks (one pole refuses -> refusal+length confound); single-correct-answer
  factual QA.
- Framing: third-person judgment ("You see someone ... what concern matters most,
  and why?") or AI-seat advisory ("You are the AI ... how do you handle it?"),
  presented as a REAL decision, never a role-play game.
- Row schema: {"text", "axes" (2-4 snake_case value tags), "source", "source_id"}.

### What to port (already built and tested in w2schar-mini; ask the owner for the files)
Copy these from `w2schar-mini` and generalise (drop w2schar-specific imports):
- `src/csm/gen/scenario_loaders.py` -- 5 rules-only loaders, each tested live:
  - `load_airisk` (kellycyy/AIRiskDilemmas, AI-seat advisory, ~1000 dilemmas, 98.5%
    pass; CAVEAT: it is an EVAL set -> mark train-only, hold out from AIRisk evals)
  - `load_moral_stories` (wassname/moral_stories_foundations, 3p judgment, ~10.4k,
    86.6%; CAVEAT: shares the MFV foundation axis space with MFV evals -- construct
    overlap, no item leak)
  - `load_daily_dilemmas` (kellycyy/daily_dilemmas, 3p, ~1258, 92.5%)
  - `load_social_chem` (wassname/social_chemistry_101 AITA/confessions, 3p, ~46k
    after a tension filter; dedup in-loader)
  - `load_ethics_qna` (wassname/ethics_qna_preferences commonsense only; the other
    configs are single-answer QA; NOISIEST source -- it over-includes low-tension
    one-liners, so the gym screen is essential here)
- `scripts/summarise_machiavelli.py` + `data/machiavelli_summaries.jsonl` --
  machiavelli (wassname/machiavelli) needs a per-row LLM compressor (obs ~350
  words); summarise OFFLINE with deepseek-v4-flash and COMMIT the jsonl so builds
  are deterministic. The loader just reads the cache.
- SKIP `Zihao1/Moral-RolePlay` (fiction with named novel characters -> role-play
  refusal confound + eval-leak; recasting costs as much as authoring fresh).
- Also the library already ships `data/scenarios_v2_candidates.jsonl` and
  `data/scenarios_w2s_character_3p.jsonl` -- read them; fold them into the same
  schema/dir so there is ONE scenario home, not three.

### Target structure (clean)
```
scenario_sources/
  loaders/            # one module per dataset, each: load(limit=None) -> [rows]
  summarise_machiavelli.py
  data/machiavelli_summaries.jsonl
  validate_scenarios.py   # thin wrapper around validate_persona_axes_openrouter.py
                          # that screens a scenario jsonl and writes kept_prompts
  README.md           # the workflow: load -> screen (the gym) -> keep clean,
                      # with the affordance contract + per-source caveats above
```

### Deliverable
- Branch + PR on persona-steering-template-library with the subdir above.
- README documents: the affordance contract, the load->screen->keep workflow, each
  source's usable-fraction + eval-leak caveat, and the machiavelli summariser step.
- A worked example in the README: screen N rows, show the per-source clean-rate
  table, show 2 kept + 2 culled examples with WHY (refusal / length / off-axis).
- "Eventually a HF dataset": note in the README that the screened, kept scenarios
  could be published as a HF dataset (wassname/character_scenarios or similar) so
  downstream repos load one clean set instead of re-screening.

Do NOT invent a second validator -- reuse `validate_persona_axes_openrouter.py`.
Test each loader actually runs and returns >=1 row before opening the PR.

### Known issue to fix in validate_scenarios.py (the gym wrapper)
The vendored `validate_persona_axes_openrouter.py` crashes when OpenRouter returns
an ERROR response: `resp.choices[0].message.content or ""` assumes `choices` is a
list, but on an error/empty response `resp.choices is None` -> `TypeError:
'NoneType' object is not subscriptable`, and the whole screen aborts (observed
2026-06-28: gemma-3-27b-it screen, n_results=1/90, n_errors=1). The wrapper must
guard `resp.choices` (retry with backoff, then skip the row and log) so one bad
API response can't sink the run.

Also add an option to screen with the REAL student class (qwen3.6-27b) instead of
an instruct proxy: qwen is a reasoning model, so at the gym's max_tokens=260 the
pole `content` comes back empty (CoT eats the budget). Either raise max_tokens and
read `.content` (OpenRouter puts CoT in a separate `reasoning` field, so content is
the clean post-think answer = still on-policy for thinking-mode qwen), or send the
thinking-off chat-template flag via extra_body. Screening with the actual student
is strictly better than the gemma proxy; note the live student runs thinking-OFF
+ greedy, so this screen is a close-but-not-identical distribution.

### Stretch: a machiavelli HF dataset (the owner wants this)
machiavelli has 114,522 decision points, 83,389 usable (>=2 morality dims), 92
games. `scripts/summarise_machiavelli.py` (deepseek-v4-flash, ~$15-30 for all,
resumable via the committed jsonl cache, round-robin across games) turns each into
a short real-decision prompt. Publish the full summarised set as a HF dataset
(e.g. wassname/machiavelli_character_scenarios), PRESERVING per-choice morality
labels + agg_power + game id (`f`) + `row_i`, so downstream can filter/tag without
re-summarising. The training pool then draws a capped, game-balanced sample from
it (cap ~50-100), exactly like the other sources. Keep `min_moral_dims>=2`.
