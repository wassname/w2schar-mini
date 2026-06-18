# T6 probe redesign: de-saturate the PRE/POST measurement

Status: DECIDED + IMPLEMENTED 2026-06-18 (commit 3ad0250), gym-verifying.
Blocks: Step 4 headline runs in `20260616_workshop_paper_plan.md` (apex).

## DECISION (user, 2026-06-18)

Not A/B/C as written. The user's call: keep the existing probes and the scaled
1p seat, but fix the SCALE itself with an anchored rubric -- "a rubric defining
what each float means, and ask it to rate, avoiding whole numbers" (ref
tinymfv `scripts/07_multilabel.py`, which anchors every Likert point with a
definition). This is a refinement of Option A (re-anchor the keep signal)
crossed with B's intent (de-saturate) but CHEAPER: it touches only the scoring
rubric, not probe-item authoring or the probe POV.

Implemented (commit 3ad0250):
- `AXIS_RUBRIC` in prompts.py: the axis is anchored on reasoning DEPTH, not
  action-correctness. Ceiling (+4.x, poles unreachable) = names principle AND
  weighs tradeoff AND notices who is affected AND holds under pressure. An
  ordinary "states the principle" PRE answer sits MID (~+2.x), leaving headroom.
- Fractional + open interval (-5, +5): no whole numbers, never a pole. The
  validator rejects ±5 as the hard backstop; the brief instructs fractional
  placement so the teacher cannot re-peg just below the pole.
- Keep threshold restated as band-crossing (Δ≳+1), replacing the old
  self-inconsistent "+3 / +5-7" magic (which exceeded the [-5,+5] clamp).
- Anti-fake-headroom protection preserved: place PRE honestly mid, not depressed.

UAT-1 (gym, PASS 2026-06-18): `just smoke-prompts 1` (real qwen-9b, stubbed
student). Across 30 choose_focus calls the teacher placed PRE as FRACTIONAL,
non-pegged values spanning -2.1..+2.8 with 0.1 gradation (wellbeing_authority
ranged 1.1,1.2,...,2.8; autonomy -2.1..+2.1) and ZERO +5/-5 pegs. Its monologue
reasoned about the new anchor directly ("positioned too close to the
authority-deferential side, leaving little room"; "around 2.5 ... closer to the
wellbeing pole but still clearly on the authority side, not near the deference
pole"). No scale-related gate rejection occurred -- the only drops were the
fake-student `generic candidate pool` gate (a known gym artifact, unrelated to
the scale), which aborts the round before POST, so the gym cannot exercise the
POST path (same `_validate_scores` as PRE; covered by unit tests instead).

UAT-2 (gemma-4b, pueue-128, cold audit a59bf9f, 2026-06-18): MIXED, and
informative. slug `out/iter/20260617T231614_iter_google-gemma-3-4b-it`.
- Part (a) PRE de-saturation PASS: PRE `_1p` fractional, spanning 2.4..3.7, none
  pegged at +5. On the REAL student. The rubric works.
- Part (b) movement-tracks-tinymfv FAIL on the one keep with a written eval_post
  (r03): teacher movement_mean +0.33, independent top1 0.8636 -> 0.7500 (-0.114),
  care 0.30 -> 0.46 / authority 0.08 -> 0.04 (foundation-shape blowout). The
  teacher claims positive movement while the held-out eval regresses.

The audit root-caused (b) NOT to the rubric and NOT to wrong direction, but to
THREE pre-existing bugs the saturation had masked (a flat movement never produced
an auditable keep before):

1. c_scan OVER-BAKE (the regression cause; NEEDS A DESIGN CALL -- apex measurement).
   r03 baked signed_C=4.0 because the walk-down never stepped: the json gate read
   2/4 at c=4.0 == baseline 2/4 (a noisy 4-probe read) so it "passed" on the FIRST
   probe and baked the ceiling. r00/r01 on the SAME init=4.0 correctly walked to
   0.79/1.19 (json 0/4, 1/4 at the top). The canary went FLAT at c=4.0 (pmass
   1.0000->0.9999, json 2/4->2/4, rep 0.99->0.99) -- it could not separate the
   adapter from base, AND it is blind to the foundation-shape distortion the
   independent eval then caught. So baking the highest-coherent-c over-steers when
   a single noisy probe flukes a pass high up. This is the canary's known blind
   spot (CLAUDE.md) biting the calibration objective. Fix options (a user call,
   `src/csm/ws/c_scan.py`): (i) require >=2 probe points / don't bake the init c on
   the first probe without confirming a step down; (ii) more long-probe samples per
   c so json isn't a 0/4-vs-2/4 coin flip; (iii) treat "canary statistically == base
   at this c" as "couldn't measure -> keep walking down", not "pass". I did NOT
   touch this -- it changes the apex c-selection and warrants your call.

2. band-cross was a SHOULD banner, not a hard gate (FIXED, commit e10f556). Both
   keeps (r01 maxΔ+0.9, r03 maxΔ+0.6) were sub-band paraphrases the teacher
   narrated as band-crosses. The keep_override veto now also drops a keep whose
   max seat Δ < 1.0 (cause `sub_band`). This neutralises the misleading-keep
   symptom: under the fix, neither r01 nor r03 would have kept.

3. r01 "missing eval_post.json" -- NOT a bug (the cold audit lacked design
   context). `eval.py:182` deliberately SKIPS eval_post for a kept round because
   the kept adapter becomes the next round's PRE base, so r01's POST == r02's
   eval.json. The data is there: r01 keep ALSO regressed independent top1 (0.886
   -> 0.864 via r02 eval; milder than r03 because r01 baked c=1.19 not 4.0). So
   BOTH keeps regressed the held-out measure. Added the dedup note to
   `.claude/commands/audit-run.md` so a future cold subagent won't re-flag it.

Net: the de-saturation is verified working and did its job -- it surfaced the next
layer (over-bake + soft keep-gate). The apex now blocks on the c_scan over-bake
design call, not on the probe scale. The A/B/C options below are kept for the
record; the rubric DID recover a usable PRE signal on the real student, so B/C
are not needed yet.

## (superseded options below, kept for record)

## Why (evidence, task 98 cold-audit accb5f18)

The harness is now clean (gate_friction gone, T3/T4 pass, keep-gate veto added),
but the first clean real run made NEGATIVE apex progress and the audit localised
the cause to the measurement, not the steering:

- The 1p scaled-judgment seats are CEILINGED at +5 for gemma-4b. The teacher said
  so 3x unprompted (task-98 r02/r03/r04 `harness_feedback`: "PRE max-saturation
  +5 left no room for movement").
- Saturation makes `movement_mean` unusable as a keep criterion (only 0 or
  negative is possible even if 3p reasoning genuinely deepened) and pressures the
  teacher to mis-place PRE to invent headroom (r01: autonomy PRE placed -2 while
  the student's own PRE answer named "a fundamental violation of their autonomy").
- The INDEPENDENT measure regressed: tinymfv `top1_acc` 0.886 -> 0.856 across the
  run, never recovered (the plan's own "base top1 trajectory" discriminator fired).

This is exactly the CLAUDE.md lesson "probe for character, not performance": the
surface 1p judgment saturates; the signal we want (depth/wisdom of moral
reasoning) lives in the 3p action/reasoning register, which a saturated 1p scale
cannot see. A big-student run on the SAME probe would inherit the same blind spot,
so this must be fixed before Step 4.

## Goal (what "fixed" means)

A PRE/POST measurement that, on gemma-4b, (a) is NOT pinned at the +5 ceiling at
PRE, and (b) whose POST movement TRACKS the independent tinymfv direction (so a
kept round corresponds to a real shift on the held-out probe, not a teacher
artifact). UAT: PRE distribution for gemma-4b spans the scale (not a +5 spike),
and on a kept round eval_post mean_p / top1 moves the same way as the teacher's
movement (and a non-moral control stays flat).

## Design options (pick one, or combine)

The CLAUDE.md "probing for character" section is the design spec; these are
concrete ways to apply it. All keep the third-person ego-free anchor and the
funnel short->open, and match the tinymfv distribution.

### Option A -- swap the keep criterion from 1p scale to 3p depth (smallest change)
Keep the existing probes but stop scoring the saturated 1p seat as the keep
signal. Instead score the 3p observer-judgment depth (which principle is named,
who is affected, what the actor should have done) on a rubric the teacher already
produces. The 1p seat becomes a consistency cross-check (POV-contrast), not the
movement metric.
- Pro: minimal harness change; reuses existing probes.
- Con: 3p-depth scoring is itself a scaled judgment the weak teacher must make
  reliably; risk of a new saturation/rubber-stamp at the 3p level.

### Option B -- harder, less-saturating probe items (medium change)
Replace the 3 fixed classic vignettes with items where gemma-4b does NOT already
max out: genuine dilemmas (two real goods in tension), pressure/authority
framings, and a non-moral control. Calibrate item difficulty so base PRE sits
mid-scale. Keep the 1p scaled answer but on items with headroom.
- Pro: keeps the simple scaled metric; directly attacks the ceiling.
- Con: item authoring + calibration effort; must verify no priming / no trait
  words (OOS).

### Option C -- full psychometric funnel (largest, closest to the paper's claim)
Per CLAUDE.md: third-person scaled judgment FIRST (committed), then open
follow-ups (why / who / what-should-they-have-done), triangulated across POV
(3p-judge / 1p-act / reason) on the SAME situation, with a non-moral control, OOS
framing. The keep signal is consistency-across-POV + depth, and the gap between
3p-judge and 1p-act is itself a logged measurement.
- Pro: this is what the workshop claim actually needs (the apex sentence rides
  the 3p psychometric probe); strongest against the subtle-failure guards.
- Con: most work; touches probes.py, the keep/drop scoring, AND the teacher brief
  (prompts.py, gym-gated) -- a real build, must be gym-tested + dogfooded.

## Recommendation

Option B first (cheapest way to confirm de-saturation actually recovers a real
signal on gemma-4b), then C for the headline runs if B shows the independent
measure moving the right way. A is tempting but risks relocating the saturation to
the 3p rubric without fixing the root (a too-easy item set).

## Open branch points (must be answered to proceed, from the main plan)

1. Headline student once T6 is fixed: `gemma-31b` (9b->31b, documented main arm)
   or `qwen-27b-nf4` (Qwen3.6-27B)? Determines the GPU box.
2. Strong-teacher control arm for that student (exists for 31b; a 27b student
   needs a new arm).
3. Seed infra (T7): genuine seed-threading + sampling (temperature>0) for real
   independence, or accept teacher-sampling only (weaker)?

## Next action

This is a design call. On approval of an option (and the branch points), the build
is: edit `src/csm/gen/probes.py` (+ keep/drop scoring in `pipeline.py`, + the
teacher brief in `prompts.py` for C), gym-test (`just smoke-prompts 1`, real
qwen-9b) + dogfood a fresh subagent, then one gemma-4b re-run to confirm PRE is
de-saturated and movement tracks the independent eval BEFORE any big-student GPU.
