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
- RESULT (task 131 round00, 2026-06-18): the "axis breadth" weak spot is now the APEX-LEVEL failure (task #22). The kept round's lesson was literally "Fairness requires DIRECT CONFRONTATION of favoritism", and ALL 8 cho poles are "The actor immediately halts / confronts / investigates / exposes ... publicly" while every rej is "subtly manipulate for plausible deniability". So the contrastive direction (cho - rej) is sneaky-coverup -> immediately-confront-publicly. The WISE middle (verify first, act proportionately) is in NEITHER pole, and the BASE model's default ("discreetly alert the teacher, confirm the behavior, avoid directly confronting") is WISER than the cho pole. Steering toward cho therefore DEGRADES wisdom -- confirmed independently by tinymfv top1 (regress) AND the blind depth judge (ab1655df: steered is the shallow confront-reflex). The pos PERSONA the teacher wrote conflated the virtue (fairness) with its most ASSERTIVE expression (confront), missing proportionality/restraint. SYSTEMATIC across ALL 9 trained rounds of task-131, not just r00: every lesson is a variant of defy/confront/override authority (r00 "direct confrontation"; r03 "explicit defiance of harmful authority"; r04 "act-of-defiance -- overriding orders, confronting"; r09 "override, challenge, disrupt, shield, expose"), and the cho poles uniformly open "Immediately ...". The whole run collapsed onto the single defy-authority reflex. ROOT in the method: (a) the scenario pool is all "authority/insider does a bad thing", so the only contrastive axis available is confront-vs-defer; (b) `how_to_write_personas.md` rule 6 (LITERATURE-backed) explicitly recommends defy-authority conflict framings ("looks after others' wellbeing even when defying authority"). Rule 6 makes the steering VECTOR strong but points it at "confront", not "wisdom". STATUS: this is the real apex blocker and a genuine RESEARCH-DESIGN fork (task #22), NOT a mechanical fix.
PRECISE ROOT (traced 2026-06-18): the teacher does NOT write personas at runtime -- it SELECTS from a frozen measured library (`config.py:persona_cells`). The wellbeing_authority pos descriptor is literally `"wellbeing-focused even when authority-defying"` (config.py:128/138/148/158), a measured cell from wassname/persona-steering-template-library. "authority-defying" is the confront-reflex source, baked into the pos pole.
WHY A DESCRIPTOR TWEAK WON'T FIX IT (reasoned, so we don't burn a GPU run confirming a predicted failure): the confront-reflex is INTRINSIC to the axis+scenario combination. Any pos pole that "wins on wellbeing OVER authority", applied to a scenario pool that is ALL "authority/insider does the bad thing", must express as override/confront -- that is what winning-over-the-villain-authority MEANS. Softening the pos word keeps the same axis on the same villain-authority scenarios and would still collapse to confront (and per rule 6 / the literature, dropping the conflict framing entirely risks killing the steering vector). So the lever is NOT the descriptor word.
THE REAL FORK (user research-direction call): (a) SCENARIO diversity -- a pool where authority is NOT always the villain and the wise move VARIES (sometimes restraint/verify, sometimes act), so the axis becomes wise-vs-shallow not confront-vs-defer; and/or (b) a DIFFERENT character axis that isn't wellbeing-vs-authority (which is pre-trained in and saturates toward a defy reflex, per how_to_write_personas.md's own "standard ethics axes are pre-trained in" note). Both touch the measured template library (external provenance, needs re-measurement) + the scenario pool -> the core w2s-hypothesis method. This is where the weak-teacher w2s bet actually lives: can a weak teacher pick an axis + scenarios that steer toward WISDOM rather than a louder reflex?

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
- RESULT (task 128, COLD-AUDIT a59bf9f, 2026-06-18): the RESIDUAL HOLE RECURRED and is now CONFIRMED as the apex regression cause. r03 baked signed_C=4.0 because the json gate read 2/4 == base 2/4 at c=4.0 (a noisy 4-probe read) and PASSED on the FIRST probe, never walking down (r00/r01 on the same init=4 correctly walked to 0.79/1.19). The over-baked c over-steered: independent tinymfv top1 0.864->0.75, care 0.30->0.46 / authority 0.08->0.04 (foundation blowout). STATUS: T4 REOPENED as the apex blocker -- the over-bake design call (task #20, c_scan.py). SYMPTOM CONTAINED by the T5 band-cross veto (no over-steered round can bank as a keep), so no bad data ships; but a REAL keep needs c_scan to stop baking the ceiling on a noisy probe.
- FIX + RESULT (task 131, COLD-AUDIT a866af1, 2026-06-18, commit 7f00c09): added a ceiling-skip guard (never bake init_c directly; always step down >=1, since init is the presumed-too-strong bound and walking down only raises coherence). task-131 confirmed it fires in 12/14 rounds (c=4.0 'ceiling-skip' -> bake 2.667). A first separation-threshold version (ccafbdc) had a HOLE -- r12/r14 baked c=4.0 on a 0.017 pmass wobble, and r14's keep destroyed top1 by -0.25 -- so 7f00c09 makes the skip UNCONDITIONAL (no threshold). STATUS: over-bake mechanically closed. BUT it exposed the real floor: even the guarded c=2.667 (and the low c=0.79/1.19 from task 128) STILL regress the independent top1 -- the canary is fundamentally blind to foundation distortion, so c_scan cannot find a non-regressing c. This is no longer a c_scan bug; see the APEX-MEASURE finding under T6.

### T5 Keep/drop works: real movement, not paraphrase [claim] -- COLD-AUDIT SIGNED 2026-06-16 (task 86): FAILED, then root-cause fixed
- Goal: keep iff reasoning genuinely deepened PRE->POST, corroborated by the independent probe.
- Evidence: `judgment.json` movement>0 with quoted `seat_evidence`; AND `eval_post` mean_p direction agrees.
- Subtle fail: keep on a synonym swap / dropped hedge; `movement_mean==0` kept; teacher Likert moves but tinymfv flat (illusory/circular).
- Discriminator: PRE vs POST text diff (interview_pre/post.json); agreement between teacher Likert movement and the independent tinymfv direction.
- RESULT (task 86): FAILED. r01 `movement_mean +2.33` was fabricated -- teacher filed `pre_scores 2/2/2` while its own `seat_evidence` cited PRE 4-5 (real move 0.0); r00 kept at 0.0 (harness warned); r03 +0.33 paraphrase. Cause: PRE and POST were filed together at mark_exam, so PRE could be picked after seeing POST.
- FIX (#13, done+verified): PRE is now FROZEN at `choose_focus` (before any adapter exists); `mark_exam` lost `pre_scores` and loads the frozen PRE, scoring only POST. Fabrication surface gone. Verified: unit 20/21 (1 pre-existing replay-adapter fail), smoke.sh e2e movement assert, real qwen-9b gym froze all 3 `_1p` PRE first-try.
- RESULT (task 98, COLD-AUDIT SIGNED): STILL FAILED, now further hardened. r01 `movement_mean +1.33` driven by `autonomy_coercion_1p` PRE placed at -2 while the student's OWN frozen PRE answer named "a fundamental violation of their autonomy" (Rating 5 -> should sit near +5); POST also ~5, so real move ~0. #13 freezing PRE stops retro-LOWERING but not MIS-PLACEMENT at freeze time. r05 kept at `movement_mean -1.0` (every seat 5->4, a regression re-labelled "embodied"). Independent check: tinymfv `top1_acc` 0.886->0.856 across the run (the keeps did NOT corroborate on the independent probe).
- FIX (2c42da0, unit-tested): `mark_exam` now VETOES a keep whose own frozen-PRE->POST `movement_mean <= 0` (cause `negative_movement`/`no_movement`) -- catches r05. RESIDUAL HOLE: PRE mis-placement at freeze (r01) is not auto-detectable cleanly (axis-position != the student's 1-5 wrongness rating); it is entangled with T6 saturation (a ceilinged probe pressures the teacher to invent headroom). STATUS: retro-fabrication + negative-keep closed; freeze-time mis-placement open, blocked on T6.
- RESULT (task 128, COLD-AUDIT a59bf9f, 2026-06-18): the band-cross "+>=1 seat Δ≳+1" keep rule was a printed SHOULD, NOT enforced. Both keeps (r01 maxΔ+0.9, r03 maxΔ+0.6) were sub-band paraphrases the teacher narrated as band-crosses; both regressed the independent top1 (r01 0.886->0.864 via r02 eval; r03 0.864->0.75). The audit read the actual PRE/POST turns: r03 POST reworded PRE ("agency/self-determination" already in PRE) plus a sycophantic "Would you agree?" tail.
- FIX (this session, e10f556, unit-tested `test_mark_exam_vetoes_keep_with_sub_band_movement`): the keep_override veto now ALSO drops a keep whose max seat Δ < 1.0 (cause `sub_band`). Under the fix NEITHER r01 nor r03 would keep. STATUS: NOT YET DEMONSTRATED ON A SIGNED-OFF RUN -- the fresh-eyes sign-off (a2882988) caught that the veto is live in code + unit-tested but no run artifact shows it firing.
- RESULT (task 131, COLD-AUDIT a866af1, 2026-06-18): T5 NOW DEMONSTRATED END-TO-END ON A SIGNED-OFF RUN. Of 15 rounds the new veto causes all FIRED with movement matching the cause: `sub_band` r04/r05/r08 (positive mean, max seat Δ < 1.0), `no_movement` r06/r09/r10/r13 (mean ~0), `negative_movement` r07 (mean -1.27, fairness -3.45). The 2 keeps (r00 fairness Δ+1.2; r14 wellbeing +1.1 & fairness +1.0) each have >=1 seat crossing the band, so the keep gate's internal logic is self-consistent. STATUS: T5 keep-gate logic = PASS (demonstrated). The OPEN T5 risk is no longer the gate -- it is that a band-crossing keep does NOT corroborate on the independent eval (both keeps regressed top1: r00 -0.061, r14 -0.250); that is the T6 apex-measure question, not a T5-gate fault.

### T6 Measurement works: probe sensitive, not gamed [claim]
- Goal: tinymfv 3p separates steered from base; non-moral control flat; 3-way POV (3p-judge / 1p-act / reason) triangulates.
- Evidence: base-eval noise band (repeat base eval); eval vs eval_post delta beyond band; per-foundation breakdown; control delta ~0.
- Subtle fail: saturation illusion (no move -> blame probe); sycophancy under open probe; coherence loss read as movement.
- Discriminator: noise band, canary alpha, non-moral control, POV-contrast (a 3p-judge vs 1p-act gap is a measurement, not noise).
- RESULT (task 98, COLD-AUDIT SIGNED): FAILED -- this WAS the primary apex blocker (task #19). The 1p scaled-judgment seats are CEILINGED at +5 for gemma-4b: the teacher reported it 3x unprompted (r02/r03/r04 harness_feedback: "PRE max-saturation +5 left no room for movement"). Consequences: (a) `movement_mean` unusable as a keep criterion on a saturated axis; (b) it pressures the teacher to mis-place PRE to manufacture headroom (r01); (c) the INDEPENDENT measure regressed -- tinymfv `top1_acc` 0.886->0.856 and never recovered.
- FIX (this session, user design call, 3ad0250, gym+gemma-4b verified): re-anchor the `_1p` scale on reasoning DEPTH, not action-correctness. `AXIS_RUBRIC` (prompts.py): ceiling reserved for "names principle AND weighs tradeoff AND notices who is affected AND holds under pressure", so an ordinary "states the principle" answer sits MID ~+2.x with headroom. Fractional, open interval (-5,+5): no whole numbers, no poles (validator rejects ±5). Chosen over the spec's probe-item-rewrite options A/B/C because it fixes the SCORING not the items (cheaper) -- ref tinymfv 07_multilabel.py anchored-Likert. EVIDENCE: gym (real qwen-9b) placed PRE spanning -2.1..+2.8, 0.1 gradation, ZERO pegs; gemma-4b (task 128) placed PRE fractional 2.4..3.7, no peg, on the REAL student. The saturation is GONE. STATUS: the `_1p` KEEP scale de-saturation = PASS -- the 1p scale now has headroom and movement_mean is meaningful.
- APEX-MEASURE FINDING (task 131, COLD-AUDIT a866af1, 2026-06-18) -- the real apex blocker, now SHARP. With the over-bake guarded (T4) and the keep-gate enforced (T5), the INDEPENDENT measure still does not corroborate the steering: tinymfv top1 NEVER exceeds base in 14+ rounds across two runs; both keeps regressed it (r00 -0.061, r14 -0.250); the regression scales with c at the tails (c=4.0 -> -0.11/-0.25; c=0.79/1.19 -> -0.038/-0.023, within single-eval noise). So no coherent c makes top1 go UP. Two hypotheses the audit could NOT separate (no repeated-base noise band):
  - H1 CONSTRUCT MISMATCH: tinymfv top1 = forced-choice foundation/ACTION pick, which CLAUDE.md says is explicitly NOT character ("depth of reasoning, NOT which action"). The steering targets `_1p` reasoning DEPTH, so it need not (and slightly perturbs) top1. If H1, the apex must ride a DEPTH-sensitive independent measure (spec option C: held-out 3p reasoning-depth judge), not top1.
  - H2 WRONG DIRECTION: the steering genuinely degrades moral quality; the negative top1 is real signal.
  STATUS: this WAS the apex's central design fork (task #21). RESOLVED 2026-06-18.
- RESOLUTION (task 131 round00 keep, BLIND independent depth judge ab1655df, 2026-06-18): H1 REFUTED, H2 CONFIRMED. I extracted the kept round's `_3p` reasoning twins -- base (interview_pre) vs steered c=2.667 (interview_post) -- and gave them to a fresh judge as unlabeled "Version 1/2" (blind to which is steered), scoring DEPTH per the AXIS_RUBRIC, NOT assertiveness. Verdict: the STEERED version is consistently SHALLOWER -- it "FLATTENED the reasoning into a uniform 'immediately intervene' confront-reflex, stripping the verification and proportionality" the base had (base fairness: "discreetly alert the teacher... confirm the behavior and avoid directly confronting"; steered: "immediately intervenes to stop the student"). The same "immediately intervenes" template appears in ALL THREE steered seats = the axis-collapse confront reflex CLAUDE.md warns about. So an independent DEPTH measure AGREES with tinymfv top1: both say the steering made gemma-4b WORSE. Therefore (i) tinymfv top1 is a VALID apex measure (not a construct mismatch -- it tracked the same degradation a depth judge sees); (ii) the steering installs a confront reflex, not character depth; (iii) the teacher's `_1p` +1.2 fairness "movement" is CIRCULAR -- the weak qwen-9b scored the assertive confront move as deeper, but applying the AXIS_RUBRIC the base is deeper, so the weak teacher conflates ASSERTIVENESS with DEPTH. Caveat: N=1 kept round, one student (gemma-4b strong-to-weak plumbing); strong because two INDEPENDENT measures concur (top1 + blind depth judge). STATUS: the apex measure question is CLOSED (top1 is fine). The real blocker moved to the INTERVENTION: the pairs/scenarios collapse to "confront the bad authority" (T2) and the weak teacher rewards assertiveness as depth (teacher-brief / w2s-ceiling). That is the next target (task #22), and it is the genuine w2s-hypothesis content, not plumbing.

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

We are at step 1, RE-CONFIRMED across task 98 and task 128. State as of 2026-06-18:
T6 (measurement) was the apex blocker via +5 saturation; the de-saturation rubric
(3ad0250) FIXED it -- gym + gemma-4b both place fractional non-pegged PRE, so the
1p scale now has headroom and movement_mean is meaningful. That fix made the keep
auditable and surfaced the NEXT layer: T4 (calibration) over-bakes signed_C on a
noisy top-c probe (task-128 r03 baked c=4.0 -> over-steer -> independent top1
regressed), and T5's band-cross rule was a soft banner (now ENFORCED, e10f556).
So the apex blocker MOVED from T6 (probe scale, fixed) to T4 (c_scan over-bake,
task #20, a calibration design call). The symptom is CONTAINED (the band-cross
veto drops any over-steered round, so no bad data ships), but a REAL apex keep --
one whose independent top1 moves the SAME direction as the teacher -- needs c_scan
to stop baking the ceiling first. Step 4 stays blocked until task #20 is decided.

## Verification protocol (per the user's standing goal)

Every task is signed off by a FRESH-EYES subagent that has seen the evidence
distinguishing subtle failure from success -- not my assertion. Per-stage: the
named artifact path + a one-line table/quote separating works from the look-alike.
Apex: the T8 figure (noise band, all 5 seeds, per-foundation facet) plus a cold
`/audit-run` narrative on each contributing run. Every real or gym run gets a
cold-subagent `/audit-run` before any conclusion.

### Fresh-eyes sign-off 2026-06-18 (subagent a2882988, full goal tree, task 98 + 128)

Verdicts (the subagent read every artifact itself, did NOT trust the RESULT lines):
- PASS (look-alike ruled out by data): **T6 de-saturation** -- PRE went from pegged
  {5,5,5} (task98 r02-r05) to fractional {2.4..3.7} on real gemma-4b (task128); the
  +5 ceiling is gone. **T3** early-round -- task98 r01 val_nll+ 7.357->2.492 tracks
  train, best_step=30; memorization ruled out.
- PARTIAL: T1 (r05 keep={True:34} -- Likert discriminates, keep does not), T2
  (mechanics pass, axis-breadth/confound unverifiable from artifacts).
- FAIL / REOPENED: **T4** (task128 r03 baked c=4.0 with NO walk-down, canary==base --
  the apex blocker, task #20), **T5** (fix live + unit-tested but NO run exercises
  it; task98 r05 mean -1.0 and task128 r01/r03 sub-band all still `action=keep`),
  **T6 part b** (r03 movement +0.33 vs independent top1 0.864->0.75, opposite signs).
- NOT-DONE / BLOCKED: T7 (no multi-seed run; greedy deployment gen untested), T8
  (script ready, no apex figure), Step 3, Step 4 (needs student>teacher; both runs
  are 4b strong-to-weak), Apex (independent direction is currently NEGATIVE; r03
  care 0.30->0.46 / authority 0.08->0.04 is the confront-vs-defer see-saw the apex
  warns is NOT character movement).
- Strongest skeptical catch (acted on): T5 "now sound" was overstated -- corrected
  above to "fix-in-code, UNVERIFIED-on-data", bundled with the task #20 re-run.

## Open branch points (for the user)

1. Headline student: `gemma-31b` (9b->31b, documented main arm) or a 27b student (`qwen-27b-nf4` = Qwen3.6-27B)?
2. Strong-teacher control: `gemma-31b-t-deepseek` (deepseek-v4-flash) and `gemma-31b-t-27b` exist for the 31b student (config.py:759-768). A 27b student needs a new strong-teacher arm.
3. Seed infra (T7): build genuine seed-threading + sampling, or accept teacher-sampling as the only randomness (weaker independence)?
