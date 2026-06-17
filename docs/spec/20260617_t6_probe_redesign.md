# T6 probe redesign: de-saturate the PRE/POST measurement

Status: PROPOSAL, needs a user design call. 2026-06-17.
Blocks: Step 4 headline runs in `20260616_workshop_paper_plan.md` (apex).

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
