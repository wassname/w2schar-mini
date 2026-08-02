# Scenario & Template Pipeline Reference

## Overview

The pair generation pipeline has two inputs:
1. **Scenarios** — moral dilemma prompts that the student model answers
2. **Persona templates** — steering prompts that condition the student into pos/neg poles

## Scenario Sources (the pool)

`scripts/build_pool.py` builds `src/csm/gen/pool.jsonl` from multiple HuggingFace datasets:

| Source | HF Dataset | Raw Rows | Current Cap | In Pool |
|---|---|---|---|---|
| tiny-mfv scifi | `wassname/tiny-mfv` (scifi) | 264 | 4-8 per foundation | 64 |
| forethought_seed | hand-curated | 82 (fixed) | — | 82 |
| airisk | `kellycyy/AIRiskDilemmas` | 6,000 | 120 | 34 |
| social_chem | `wassname/social_chemistry_101` | **355,922** | 140 | 20 |
| daily_dilemmas | `kellycyy/daily_dilemmas` | 2,720 | 140 | 13 |
| moral_stories | `wassname/moral_stories_foundations` | 12,000 | 140 | 5 |
| ethics_qna | (varies) | — | 90 | 8 |
| genies | `wassname/genies_preferences` | 850 | 6/config | 17 |
| machiavelli | (cached) | — | 50 | 1 |
| **Total pool** | | | | **244** |

### Screening

`data/scenario_screen_kept.json` (81 ids) is a keep-list from `scripts/select_screened_scenarios.py`.
When present, `build_pool.py` filters to ONLY these screened-clean source_ids.
This was meant to ensure quality but severely limits the pool size.

### Caps

`SCENARIO_LOADER_SPECS` in `build_pool.py` controls how many rows per source.
`CAP_MFV_PER_FOUNDATION = 4` (8 for Liberty) limits tiny-mfv.
The loaders over-fetch (cap*5) then RNG-sample down.

### Axis tagging

`_infer_axes()` in build_pool.py tags each row with moral axes (care, autonomy, fairness, etc.)
via `FOUNDATION_TO_AXES` mapping (tiny-mfv) and `AXIS_PATTERNS` regex (all sources).
`PAIR_REQUIRED_AXES` in pipeline.py maps each persona pair to required axis tags for scenario filtering.

## Persona Templates

### Template Library

`wassname/persona-steering-template-library` on HuggingFace has:
- **main** (56 rows): 56 templates with measured scores across axes
- **template_pair_cells** (112 rows): 56 templates × 2 persona pairs, with on_axis/off_axis measurements
- **persona_pairs** (2 rows): `principled_expedient` and `forthright_strategic_disclosure`
- **examples** (224 rows): 2 scenarios × 56 templates × 2 poles, with full axis/style judgments
- **controls** (6 rows): control measurements

### Hardcoded cells in code

`MULTI_AXIS_PERSONA_CELLS` in `src/csm/prompts.py` has 15 hardcoded persona cells:
each is `(hf_id, template, pair_id, pos_desc, neg_desc, score, on_axis, off_axis)`.
These are the cells used by the live harness. Templates were selected per-axis from
`out/persona_axes_live18_qwen36.json` (gym measurements on Qwen3.6-27B).

### Template format

Three templates used, chosen per-axis by gym measurement:
- `"Act as a {persona} person would in this situation."`
- `"Respond as a {persona} decision-maker."`
- `"Answer with the judgment of someone who is {persona}."`

### Pair commit suffix

`PAIR_COMMIT_SUFFIX` in prompts.py forces both poles to commit to an action first:
```
You must decide now. FIRST line: say in one sentence exactly what you do.
Then give at most three short sentences on why -- plain prose, no headings,
no bold, no lists.
```
This makes first-line action extraction reliable for auto-filtering.

## Pair Generation Flow

1. `choose_focus` (pipeline.py) — teacher picks axis + scenario family
2. `sample_prompt_rows` (prompts_pool.py) — filters pool by required_axes, caps at n_scenarios
3. `generate_pairs` (pairs.py) — generates cho/rej per scenario, greedy (do_sample=False)
4. `_pair_flags` (pipeline.py) — auto-filters: empty, identical, degenerate, blur, etc.
5. `STRUCTURAL_FLAGS` — frozenset of flags that auto-prune: empty, identical, too_short, degenerate, same_action (soft flags like length_skew/persona_leak only surface as hints)
6. Teacher rates remaining pairs via rate_pair tool
7. `select_pairs` — selects pairs passing on_axis>=3.5 AND different_action AND off_axis<=3.0

## Key Numbers (job 136, July 2026)

- Pool: 244 rows, but axis filtering drops to 15-83 per axis
- Generation: 43-83 pairs per round (limited by pool, not n_scenarios=150)
- Pass rate: ~25% (different_action is the main killer — 60/83 converged pairs in r02)
- Training floor: min_pairs_to_train=40, often not reached

## How to expand the pool

1. Remove or raise `data/scenario_screen_kept.json` dependency (only 81 ids)
2. Raise caps in `SCENARIO_LOADER_SPECS` (social_chem alone has 355K rows)
3. Raise `CAP_MFV_PER_FOUNDATION` (tiny-mfv has 264 rows, only using 64)
4. Rebuild: `uv run python scripts/build_pool.py`
