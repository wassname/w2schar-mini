# Dataset-sourced prompt pool + diversity validation

## Goal
Replace the hand-authored `POOL` in `src/csm/gen/prompts_pool.py` with a
reproducible, provenance-cited pool drawn from real datasets, then prove the new
pool makes persona-conditioned student gens (a) separate across poles, (b) vary
across samples, while staying coherent. That structural diversity is the upstream
fix for the task-62 memorisation (val nll+ 0.95->4.7 on 13 homogeneous
"### The Stakes" essays).

## Scope
In: build script + data file + loader swap; a diversity-probe script that scores
the pool via OpenRouter; provenance manifest; eval-leak dedup vs tiny-mfv.
Out: changing the eval, the trainer, the canary, or the agent brief. AIRiskDilemmas
stays reserved for a future eval split (not used here).

## Requirements
- R1: Reproducible extraction. Done: `uv run python scripts/build_pool.py` writes
  `src/csm/gen/pool.jsonl` (one record/line: `text, source, config, tags`) plus a
  manifest with per-source counts + license. VERIFY: rerun is byte-identical
  (deterministic seed) and manifest counts sum to len(pool). Sneaky-fail: an
  empty/short stem slips through -> assert every text >= 40 chars, ends with an
  open close, contains no "### Response:" / "Do you" binary tail.
- R2: Eval-disjoint. Done: no pool text shares a >=10-word shingle with any
  tiny-mfv (`classic`/`scifi`/`ai-actor`) item. VERIFY: dedup pass logs
  `leaks=0`. Sneaky-fail: dedup compares against the wrong config set -> assert it
  loaded all three configs and >0 eval rows.
- R3: Diversity. Done: `scripts/validate_pool.py --model <or-model> --n K` samples
  K pool prompts, generates cho (under pos persona) + rej (under neg persona) via
  OpenRouter, and emits a table with two trigram-distance axes and a coherence
  gate. Targets, NEW pool vs OLD hand pool side by side:
    - between-sample distance d(cho_i, cho_j) HIGH (>=0.5 mean): not one canned
      scaffold. This is the task-62 guard; OLD pool should score lower.
    - between-pole distance d(cho_i, rej_i) HIGH (>=0.5 mean): personas actually
      steer; a near-0 here means the persona pair is inert, not the pool.
    - coherence: 100% of gens pass `_degenerate_gen == False`.
  VERIFY: table printed + written to `out/pool_validation.md`. Sneaky-fail: a
  collapsed model scores LOW between-sample for the right reason (variety) but ALSO
  fails coherence -> the coherence column catches it; never read diversity without it.
- R4: Loader swap. Done: `prompts_pool.POOL` loads `pool.jsonl`; `just smoke` green.
  VERIFY: `len(POOL)` matches manifest; smoke passes.

## Tasks
- [ ] T1 (R1): `scripts/build_pool.py` — per-source extractor: daily_dilemmas-self
  (filter rows where >=1 authority/character value fires: honesty, loyalty,
  privacy, responsibility, integrity, respect_for_rules, independence; stem =
  `dilemma_situation`, strip "Do you X or Y?" tail, append open close);
  genies_preferences (only `sycophancy_feedback`, `sycophancy_mimicry`, and
  `change_my_view` for the moral side, plus a couple of non-moral controls; strip
  alpaca scaffold + chosen/rejected, keep scenario body); machiavelli (rank by
  normalized across-choice axis range, keep only cropped explicit `power`-family
  fillers, reject broken quote fragments). Dedup, stratify, cap
  per-source, deterministic shuffle, write jsonl + manifest.
  - verify: `uv run python scripts/build_pool.py && wc -l src/csm/gen/pool.jsonl`
  - success: ~120-200 rows, manifest counts per source, every text passes shape asserts
  - likely_fail: machiavelli stems too dirty -> cap it small, lean on genies+daily
  - sneaky_fail: forced-choice tail survives -> shape assert on "Do you"/"### Response:"
- [ ] T2 (R2): eval-leak dedup vs tiny-mfv classic/scifi/ai-actor (10-word shingle).
  - verify: build log prints `eval rows=N leaks=0`
- [ ] T3 (R4): swap `prompts_pool.py` POOL to load `pool.jsonl`; keep the
  why-header, point it at the manifest. Run `just smoke`.
- [ ] T4 (R3): `scripts/validate_pool.py` — OpenRouter cho/rej gen over K prompts
  under one persona pair; trigram-distance matrix (between-sample, between-pole) +
  coherence; NEW vs OLD pool; write `out/pool_validation.md`.
  - verify: `uv run python scripts/validate_pool.py --model <m> --n 12`
  - success: NEW between-sample d >= 0.5 and > OLD; between-pole d >= 0.5; coherence 100%
- [x] T5: Add coarse axis tags plus a manual review export so we can whitelist
  stems by axis instead of trusting raw source dumps.
  - verify: `uv run python scripts/export_pool_axis_review.py`
  - success: `out/pool_axis_review.md` groups the pool under coarse axes with
    row text/source visible for manual review
  - likely_fail: tags exist but the default `mixed` family still quietly pulls in
    dirty cropped or sycophancy rows
  - sneaky_fail: Machiavelli metadata describes absolute "badness" instead of
    within-scene choice contrast, so the review labels look informative while the
    scenes remain poor candidates for pair generation

## Context
- Eval = tiny-mfv configs ['classic','scifi','ai-actor'] (Clifford MFV). No airisk
  config exists. AIRiskDilemmas is therefore eval-disjoint AND reserved for eval.
- Distance metric: d(a,b) = 1 - Jaccard(trigram_set(a), trigram_set(b)). One metric,
  two axes (between-sample variety, between-pole separation). Reuse repo
  `_degenerate_gen` for the coherence gate.
- Persona pair for the probe: the dogfood v2 pair (reasons-from-stakes vs
  settles-by-permission) so the probe shares the harness's actual axis.
- Licenses: genies_preferences + machiavelli + daily_dilemmas (record in manifest).

## Log
- 2026-06-06 spec written. Dataset shapes confirmed (see commit). Next: T1.
- 2026-06-06 built. pool.jsonl = 136 prompts: daily_dilemmas-self 50 (1p character),
  speechmap-questions 30 (contested speech-boundary, ranked by compliance_std so the
  50/50-split judgment calls win, NOT unanimous-refuse -> no refusal collapse),
  genies_preferences 48 (relinquish_power/survival_influence/pursue_goals/illegal/
  sycophancy/change_my_view + 4 non-moral controls), machiavelli 8 (last-choice
  narrative). eval-leak guard: 0 leaks vs tiny-mfv (792 rows). smoke GREEN.
- 2026-06-06 R3 validation. Switched metric trigram->embedding (all-MiniLM): trigram
  SATURATED (NEW 0.994 vs MONOTONE 0.967, gap +0.027 -- useless on long gens).
  Embedding (gemma-3-27b-it, n=12): prompt_div NEW 0.896 vs MONOTONE 0.343 (+0.553);
  btwn_sample_cho 0.816 vs 0.547 (+0.269); coherence 1.0. Pool fixes task-62
  monotony, metric trustworthy (control discriminates). btwn_pole modest (0.249,
  < monotone 0.419): on diverse prompts a strong model converges in conclusion,
  separates in reasoning-MODE not action -- consistent with steering depth not action.
  Artifact: out/pool_validation.md. DONE.
- 2026-06-13 prompt-pool cleanup for scientific smoke: dropped malformed
  `genies_preferences` subsets (`sycophancy_answer`, `sycophancy_are_you_sure`)
  from the live moral pool; `mixed` now excludes both explicit sycophancy rows
  and cropped Machiavelli rows.
- 2026-06-13 Machiavelli is now treated as explicit `power`-family filler, not
  default mixed prompts. Selection is ranked by across-choice axis range, not
  absolute power/deception magnitude, and rows with broken quote fragments are
  rejected. The pool now records `axes` and review metadata for manual
  whitelisting in `out/pool_axis_review.md`.
