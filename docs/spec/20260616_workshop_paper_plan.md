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
- RESULT (task 98, slug `20260617T122228_iter_google-gemma-3-4b-it`, COLD-AUDIT SIGNED): the #14 flag works both ways -- r01 `rubber_stamp_flag=True` (32 identical 5/1/1, same failure mode b as task 86), r05 `rubber_stamp_flag=False` (teacher discriminated, but only after the `select_pairs` unrated-gate FORCED it to rate all 34). Coverage YES; discrimination only when the gate compels it. STATUS: covers, flag surfaces the look-alike; the Likert still adds little on its own.

### T2 Pair quality works [harness]
- Goal: poles are length/register twins differing only in the trait, in the student's own voice, no leak/break.
- Evidence: `pairs.md` cho vs rej token-length parity (cheap python); selected `candidates.json` flags empty; persona stripped.
- Subtle fail: a systematic cho/rej length/verbosity gap becomes the real axis; AI-disclaimer/refusal poles; persona echo.
- Discriminator: cho/rej length distribution + manual read against `docs/how_to_rewrite_pairs.md`.
- RESULT (task 98, COLD-AUDIT SIGNED): r01 pairs length-symmetric + clean on-axis (cho=principled-confront / rej=deflect-via-plausible-denial, cho 35-67 tok vs rej 36-62 tok); but every rej used the SAME deflection move (frame-as-technical-glitch) -> narrow axis risk. r05 had a cho/rej-BOTH-intervene register confound (visceral vs procedural, not the moral choice) -> trains tone not axis. STATUS: PARTIAL PASS -- mechanics good, axis breadth/confound is the weak spot.

### T3 Training works: learns, does not memorize [harness]
- Goal: val nll+ descends and tracks train nll+; adapter deploys at the post-warmup val-min.
- Evidence: `train_summary.val_traces` (train.py:625); `best_step` > warmup_steps; `val_improvement` >= 0.05 with `n_val_pairs` >= 4.
- Subtle fail: train nll+ falls while val nll+ flat/rises (memorization); `best_step==0` (null adapter); val_improvement on n_val=1 is noise.
- Discriminator: train/val gap in the val-trace; best_step location vs warmup; n_val count.
- RESULT (task 98, COLD-AUDIT SIGNED): PASS on early rounds, degrades as adapters compose. r01 (trained vs un-steered base): val_nll+ 7.357->2.486 tracking train, best_step=30, n_train=28 n_val=4 -- generalizes, not memorizing. r05 (composed on prior keeps): val_improvement 0.053 (barely over the 0.05 floor) and train_nll+ ROSE 2.130->2.174 (cho pole did not learn) -- near-null. STATUS: training mechanism WORKS; signal thins once the base is already steered (a composition issue, not a memorization one).

### T4 Calibration works: a strength that bites coherently [claim-ish]
- Goal: c_scan bakes signed_C>0 at which steering REGISTERS on the probe AND all three gates pass.
- Evidence: `calibration.json.cscan_trace` shows a passing c; baked-c `eval_post.json` mean_p moves vs `eval.json` base.
- Subtle fail: (a) bakes c~=init with pmass~=baseline -> never separated (the 4b c=1 bug); (b) walks to C_MIN -> real direction throttled by coherence.
- Discriminator: which gate bound the walk (note column); start from signed_C=2-3 and search DOWN; compare baked-c eval to base eval (must move).
- RESULT (task 98, COLD-AUDIT SIGNED): search-down CONFIRMED working. With init raised to 4 (dfa84ec, from the task-89 c-sweep clean-ceiling), r01 c_scan WALKED DOWN 4.0(fail-json)->2.667(fail-json)->1.778(pass), the valid_json gate binding it -- exactly the "start high, search down" the discriminator wanted. RESIDUAL HOLE: r05 baked c=4.0 on ONE probe that passed (pmass/json/rep all ~= baseline, c=4 indistinguishable from base) -> the canary is BLIND to high-c foundation distortion (task-89 showed c>=6 distorts; the long single-turn probes can't see it). STATUS: walk-down works; canary needs the 3p deployment register to catch high-c distortion (linked to T6).

### T5 Keep/drop works: real movement, not paraphrase [claim] -- COLD-AUDIT SIGNED 2026-06-16 (task 86): FAILED, then root-cause fixed
- Goal: keep iff reasoning genuinely deepened PRE->POST, corroborated by the independent probe.
- Evidence: `judgment.json` movement>0 with quoted `seat_evidence`; AND `eval_post` mean_p direction agrees.
- Subtle fail: keep on a synonym swap / dropped hedge; `movement_mean==0` kept; teacher Likert moves but tinymfv flat (illusory/circular).
- Discriminator: PRE vs POST text diff (interview_pre/post.json); agreement between teacher Likert movement and the independent tinymfv direction.
- RESULT (task 86): FAILED. r01 `movement_mean +2.33` was fabricated -- teacher filed `pre_scores 2/2/2` while its own `seat_evidence` cited PRE 4-5 (real move 0.0); r00 kept at 0.0 (harness warned); r03 +0.33 paraphrase. Cause: PRE and POST were filed together at mark_exam, so PRE could be picked after seeing POST.
- FIX (#13, done+verified): PRE is now FROZEN at `choose_focus` (before any adapter exists); `mark_exam` lost `pre_scores` and loads the frozen PRE, scoring only POST. Fabrication surface gone. Verified: unit 20/21 (1 pre-existing replay-adapter fail), smoke.sh e2e movement assert, real qwen-9b gym froze all 3 `_1p` PRE first-try.
- RESULT (task 98, COLD-AUDIT SIGNED): STILL FAILED, now further hardened. r01 `movement_mean +1.33` driven by `autonomy_coercion_1p` PRE placed at -2 while the student's OWN frozen PRE answer named "a fundamental violation of their autonomy" (Rating 5 -> should sit near +5); POST also ~5, so real move ~0. #13 freezing PRE stops retro-LOWERING but not MIS-PLACEMENT at freeze time. r05 kept at `movement_mean -1.0` (every seat 5->4, a regression re-labelled "embodied"). Independent check: tinymfv `top1_acc` 0.886->0.856 across the run (the keeps did NOT corroborate on the independent probe).
- FIX (this session, 2c42da0, unit-tested): `mark_exam` now VETOES a keep whose own frozen-PRE->POST `movement_mean <= 0` (cause `negative_movement`/`no_movement`) -- catches r05. RESIDUAL HOLE: PRE mis-placement at freeze (r01) is not auto-detectable cleanly (axis-position != the student's 1-5 wrongness rating); it is entangled with T6 saturation (a ceilinged probe pressures the teacher to invent headroom). STATUS: retro-fabrication + negative-keep closed; freeze-time mis-placement open, blocked on T6.

### T6 Measurement works: probe sensitive, not gamed [claim]
- Goal: tinymfv 3p separates steered from base; non-moral control flat; 3-way POV (3p-judge / 1p-act / reason) triangulates.
- Evidence: base-eval noise band (repeat base eval); eval vs eval_post delta beyond band; per-foundation breakdown; control delta ~0.
- Subtle fail: saturation illusion (no move -> blame probe); sycophancy under open probe; coherence loss read as movement.
- Discriminator: noise band, canary alpha, non-moral control, POV-contrast (a 3p-judge vs 1p-act gap is a measurement, not noise).
- RESULT (task 98, COLD-AUDIT SIGNED): FAILED -- this is now the PRIMARY APEX BLOCKER (task #19). The 1p scaled-judgment seats are CEILINGED at +5 for gemma-4b: the teacher reported it 3x unprompted (r02/r03/r04 harness_feedback: "PRE max-saturation +5 left no room for movement"). Consequences: (a) `movement_mean` is unusable as a keep criterion on a saturated axis (only 0 or negative possible even if 3p reasoning deepened); (b) it pressures the teacher to mis-place PRE to manufacture headroom (r01); (c) the INDEPENDENT measure regressed -- tinymfv `top1_acc` 0.886->0.856 across rounds and never recovered (the plan's own "base top1 trajectory" discriminator row, FIRED). The surface 1p judgment saturates; the real signal lives in 3p action/reasoning DEPTH, which the scaled 1p metric cannot see (CLAUDE.md "probe for character not performance"). FIX = redesign PRE/POST toward the psychometric 3p funnel; per CLAUDE.md it must reach the teacher brief in prompts.py -> NEEDS A USER DESIGN CALL (open branch points below). STATUS: BLOCKS Step 4. Re-running gemma-4b before this just produces honest-but-null results.

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
   - RE-RUN DONE 2026-06-17 (task 98, slug `20260617T122228_iter_google-gemma-3-4b-it`, COLD-AUDIT SIGNED, accb5f18). Headline: **gate_friction ELIMINATED** (0/6 rounds vs task-90's ~80%; root cause was a tool-schema lie -- choose_focus judgment fields were `| None = None` so the weak teacher omitted them and the validator rejected None 108x; fixed 137193c + budget 8->3 + max-round cap + compaction). Per-goal (see each T# RESULT line): T3 PASS, T4 walk-down CONFIRMED, T1 covers+flags, T2 partial, T5 still fails on PRE mis-placement (now veto-hardened 2c42da0), **T6 FAILED = saturation, the apex blocker (#19)**. The independent measure REGRESSED (tinymfv top1 0.886->0.856). So the harness is now CLEAN/trustworthy but the run makes no apex progress: Step 4 is blocked on the T6 probe redesign (a user design call).
2. Build T7 (seed infra) + T8 (aggregation plot), smoke-tested on tiny.
3. Coarse-curve diagnostic (completion length x pair count, save all outputs) to de-risk T3 on weak intervention before spending big-student GPU.
4. Headline [claim] runs: 3 weak-9b seeds + 2 strong-teacher seeds on the big student -> the apex plot (T6 probe battery + non-moral control wired in).
5. Write-up: apex figure + honest failure-mode section built from the discriminators above.

We are at step 1, now RE-CONFIRMED (task 98): the harness plumbing is clean
(T3/T4 pass, gate_friction gone, keep-gate veto added), but step 1 also surfaced
that T6 (measurement) FAILS on gemma-4b by saturation -- the independent probe
regressed, not improved. Steps 2-3 are partly done (T7/T8 infra built). Step 4
(headline runs) is BLOCKED until T6 is redesigned: on a saturated 1p probe a
big-student run would inherit the same blind measurement. Steps 4-5 are the
paper; steps 1-3 are whether it is reachable -- and T6 is the current "no".

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
