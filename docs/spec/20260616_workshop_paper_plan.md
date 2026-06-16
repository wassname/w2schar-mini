# Workshop-paper plan: weak-to-strong character steering (goal tree)

Status: living plan. 2026-06-16. Canonical location for this plan (supersedes the
plan-mode scratch file).

Epistemic status: every task below is a HYPOTHESIS with a falsification test, not
a result. As of today the only real-teacher evidence is the rate-all selection
contract (replay, 2026-06-16, plumbing only); training/calibration/eval on a real
run are untested with the current fixes. This is the de-risking map, not a claim
of success.

## The one claim a workshop paper would carry

> A weak teacher (qwen3.5-9b), given a clear brief, curates contrastive
> (cho, rej) pairs whose trained steering adapter measurably and COHERENTLY
> shifts a STRONGER student's moral reasoning on a held-out psychometric probe,
> and these shifts compose across rounds.

Feasibility / method claim in the weak-to-strong-generalization lineage (Burns et
al. 2023), specialized to (a) character/values not task labels and (b)
weight-steering adapters not finetuning on weak labels. The honest target is a
qualified "yes, under these conditions, and here are the failure modes," not a
SOTA number. What makes it publishable is that the measurement survives the
subtle-failure guards: the movement is reasoning depth (not paraphrase or action
flip), it shows on the ego-free third-person probe, a non-moral control stays
flat, and the weak teacher does about as well as a strong-teacher control.

## The student-size trap (read first)

The capability gap IS the hypothesis: weak-to-strong requires student > teacher.

- `gemma-4b-3keep` (9b teacher -> 4b student) is STRONG-to-weak. It de-risks the
  harness cheaply on the 24GB box (config.py:789). A green run proves the
  PLUMBING, NOT the w2s claim. "3/5 keeps on 4b" must not stand in for the
  headline.
- The headline needs student LARGER than the 9b teacher: `gemma-31b` (9b->31b,
  config.py:472, the documented main arm) or a 27b student. Those need the 96GB
  box / nf4 LoRA.

Tasks are tagged [harness] (provable on 4b), [claim] (needs student > teacher),
or [infra] (code we must build first).

## Apex goal: phrasing and its subtle failure

Headline sentence the plot must support:

> On a student larger than the teacher, the weak-teacher kept-adapter chain
> shifts the held-out third-person tinymfv moral-foundation distribution:
> (a) STRIKING -- the shift exceeds the base-eval noise band by a clear margin;
> (b) CONSISTENT -- all 3 independent weak-teacher seeds move the SAME direction
> with low variance (not 1 hit + 2 nulls); (c) RECOVERING -- the weak shift is a
> large fraction of the 2-seed strong-teacher control shift (small w2s gap); all
> while the coherence canary passes and a non-moral control stays flat.

Apex subtle-failure modes (the plot looks striking+consistent but is an artifact):

| Looks like success | Actually | Discriminator |
|--------------------|----------|---------------|
| Consistent low-variance across "seeds" | seeds are no-ops (greedy gen) so runs are identical | T7: verify candidates.json DIFFERS across seeds |
| Big tinymfv aggregate move | one foundation (authority) collapsing = confront-vs-defer reflex | per-foundation facet + care/authority scatter, not aggregate |
| Teacher says it moved (Likert) | circular: same teacher steered and judged | apex rides INDEPENDENT tinymfv (eval.json), not judgment.json movement |
| Weak recovers strong | both arms ~flat, recovery is vacuous | strong arm must clear the noise band FIRST (positive control) |
| Distribution shifted | steered model degraded; tinymfv reads incoherence | canary pass + plot alpha = mean_pmass_format |
| Per-round move ~0 dismissed as noise | composed stack regresses the base | base top1 trajectory across rounds (eval.json) |

## Per-stage tasks (goal / evidence-works / subtle-fail / discriminator)

Each carries a user-observable proof (an artifact path or table) and a fresh-eyes
subagent sign-off that has seen the evidence distinguishing the look-alike from
success -- not "I did it".

### T1 Selection works [harness] -- COLD-AUDIT SIGNED 2026-06-16 (task 86): COVERS but does NOT discriminate; flag added
- Goal: teacher rates EVERY flag-clean candidate; trains on many pairs with real held-out val.
- Evidence: `selection_audit.json` funnel reconciles generated -> flag-clean -> rated -> selected; `train_summary.n_train_pairs` >= ~15, `n_val_pairs` >= 4.
- Subtle fail: (a) cherry-pick the minimum (6 of 55) -> starves training; (b) rate-all but keep=true on EVERYTHING -> no discrimination, garbage in.
- Discriminator: funnel counts add up AND ratings show a keep/drop spread with substantive comments.
- RESULT (task 86, slug `20260616T044119_iter_google-gemma-3-4b-it`): rated all + trained 25-35 pairs (coverage YES), but kept 100% with byte-identical 5/1/1 every round (failure mode b). The upstream flag-gate is the only real filter.
- FIX (#14, done): `select_pairs` now logs a warning + writes `selection_audit.json:rubber_stamp_flag` when all ratings share one on_axis + keep. NON-gated (flag-clean survivors may genuinely all be good); the audit decides. Verified: smoke flag=True on 5/5 uniform.

### T2 Pair quality works [harness]
- Goal: poles are length/register twins differing only in the trait, in the student's own voice, no leak/break.
- Evidence: `pairs.md` cho vs rej token-length parity (cheap python); selected `candidates.json` flags empty; persona stripped.
- Subtle fail: a systematic cho/rej length/verbosity gap becomes the real axis; AI-disclaimer/refusal poles; persona echo.
- Discriminator: cho/rej length distribution + manual read against `docs/how_to_rewrite_pairs.md`.

### T3 Training works: learns, does not memorize [harness]
- Goal: val nll+ descends and tracks train nll+; adapter deploys at the post-warmup val-min.
- Evidence: `train_summary.val_traces` (train.py:625); `best_step` > warmup_steps; `val_improvement` >= 0.05 with `n_val_pairs` >= 4.
- Subtle fail: train nll+ falls while val nll+ flat/rises (memorization); `best_step==0` (null adapter); val_improvement on n_val=1 is noise.
- Discriminator: train/val gap in the val-trace; best_step location vs warmup; n_val count.

### T4 Calibration works: a strength that bites coherently [claim-ish]
- Goal: c_scan bakes signed_C>0 at which steering REGISTERS on the probe AND all three gates pass.
- Evidence: `calibration.json.cscan_trace` shows a passing c; baked-c `eval_post.json` mean_p moves vs `eval.json` base.
- Subtle fail: (a) bakes c~=init with pmass~=baseline -> never separated (the 4b c=1 bug); (b) walks to C_MIN -> real direction throttled by coherence.
- Discriminator: which gate bound the walk (note column); start from signed_C=2-3 and search DOWN; compare baked-c eval to base eval (must move).

### T5 Keep/drop works: real movement, not paraphrase [claim] -- COLD-AUDIT SIGNED 2026-06-16 (task 86): FAILED, then root-cause fixed
- Goal: keep iff reasoning genuinely deepened PRE->POST, corroborated by the independent probe.
- Evidence: `judgment.json` movement>0 with quoted `seat_evidence`; AND `eval_post` mean_p direction agrees.
- Subtle fail: keep on a synonym swap / dropped hedge; `movement_mean==0` kept; teacher Likert moves but tinymfv flat (illusory/circular).
- Discriminator: PRE vs POST text diff (interview_pre/post.json); agreement between teacher Likert movement and the independent tinymfv direction.
- RESULT (task 86): FAILED. r01 `movement_mean +2.33` was fabricated -- teacher filed `pre_scores 2/2/2` while its own `seat_evidence` cited PRE 4-5 (real move 0.0); r00 kept at 0.0 (harness warned); r03 +0.33 paraphrase. Cause: PRE and POST were filed together at mark_exam, so PRE could be picked after seeing POST.
- FIX (#13, done+verified): PRE is now FROZEN at `choose_focus` (before any adapter exists); `mark_exam` lost `pre_scores` and loads the frozen PRE, scoring only POST. Fabrication surface gone. Verified: unit 20/21 (1 pre-existing replay-adapter fail), smoke.sh e2e movement assert, real qwen-9b gym froze all 3 `_1p` PRE first-try.

### T6 Measurement works: probe sensitive, not gamed [claim]
- Goal: tinymfv 3p separates steered from base; non-moral control flat; 3-way POV (3p-judge / 1p-act / reason) triangulates.
- Evidence: base-eval noise band (repeat base eval); eval vs eval_post delta beyond band; per-foundation breakdown; control delta ~0.
- Subtle fail: saturation illusion (no move -> blame probe); sycophancy under open probe; coherence loss read as movement.
- Discriminator: noise band, canary alpha, non-moral control, POV-contrast (a 3p-judge vs 1p-act gap is a measurement, not noise).

### T7 Multi-seed independence [infra] -- gates the apex
- Goal: run the SAME profile with N genuinely independent seeds.
- Evidence: a `seed` field in RunConfig threaded through scenario/candidate/train seeds (today hardcoded 42+n, 4200+n, TrainCfg.seed=42); 3 runs produce DIFFERENT `candidates.json`.
- Subtle fail: seeds stay no-ops (greedy gen + fixed offsets) -> fake low-variance "consistency".
- Discriminator: diff candidates.json across the 3 seeds -- they MUST differ. Student gen is greedy (do_sample=False, dialogue.py:38); real independence likely needs sampling (temperature>0), not just a seed integer.

### T8 Cross-run aggregation plot [infra] -- the apex deliverable
- Goal: one figure overlaying 3 weak + 2 strong seed trajectories on the tinymfv measure with a noise band and a per-foundation facet.
- Evidence: a script reading `out/iter/*/round*/eval*.json` across runs -> the headline figure (extends `plot.py`; `scripts/c_sweep_eval.py` is a starting point; plot.py is single-slug today).
- Subtle fail: cherry-picked run, no noise band, aggregate-only (hides single-foundation reflex).
- Discriminator: all seeds plotted, error band shown, per-foundation small-multiples.

## Run sequence (cheap -> expensive; each step gates the next)

0. DONE: `/audit-run` rewritten to question-driven narrative (no thresholds; surfaces agent feedback + mistaken tool calls); selection rate-all verified at replay.
1. Harness gate on the cheap 4b (PLUMBING ONLY): real `gemma-4b-3keep` run with all fixes (rate-all + warmup early-stop + signed_C=2 search-down). Proves T1,T2,T3,T5 on real data and T4's search-down. Cold `/audit-run` sign-off. NOT the w2s claim.
   - DONE 2026-06-16 (task 86, slug `20260616T044119_iter_google-gemma-3-4b-it`). Cold audit verdict: T3 PASS; T4 PARTIAL (baked signed_C=2, eval_post moved care +0.022, walk-down untested); T1/T2 PARTIAL; T5 FAIL (fabricated PRE). Two harness gates were not discriminating; both now FIXED (#13 PRE-freeze, #14 rubber-stamp flag) and verified. A re-run is needed to confirm the fixed gates produce a clean T1/T5 on fresh data before Step 4.
2. Build T7 (seed infra) + T8 (aggregation plot), smoke-tested on tiny.
3. Coarse-curve diagnostic (completion length x pair count, save all outputs) to de-risk T3 on weak intervention before spending big-student GPU.
4. Headline [claim] runs: 3 weak-9b seeds + 2 strong-teacher seeds on the big student -> the apex plot (T6 probe battery + non-moral control wired in).
5. Write-up: apex figure + honest failure-mode section built from the discriminators above.

We are at step 1. Steps 4-5 are the paper; steps 1-3 are whether it is reachable.

## Verification protocol (per the user's standing goal)

Every task is signed off by a FRESH-EYES subagent that has seen the evidence
distinguishing subtle failure from success -- not my assertion. Per-stage: the
named artifact path + a one-line table/quote separating works from the look-alike.
Apex: the T8 figure (noise band, all 5 seeds, per-foundation facet) plus a cold
`/audit-run` narrative on each contributing run. Every real or gym run gets a
cold-subagent `/audit-run` before any conclusion.

## Open branch points (for the user)

1. Headline student: `gemma-31b` (9b->31b, documented main arm) or a 27b student (`qwen-27b-nf4` = Qwen3.6-27B)?
2. Strong-teacher control: `gemma-31b-t-deepseek` (deepseek-v4-flash) and `gemma-31b-t-27b` exist for the 31b student (config.py:759-768). A 27b student needs a new strong-teacher arm.
3. Seed infra (T7): build genuine seed-threading + sampling, or accept teacher-sampling as the only randomness (weaker independence)?
