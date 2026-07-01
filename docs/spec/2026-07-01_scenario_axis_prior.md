# Spec: populate scenario-axis priors for all persona pairs

## Problem (root-caused, 2026-07-01)

Job-137 audit: 11/16 rounds dropped, 5 as `early_abort` with teacher feedback
"Bank contamination dominant ~50% off-topic responses (child-discipline,
museum-donation, roommate-conflict scenarios testing different value tensions
than [the chosen axis])."

Root cause: `src/csm/pipeline.py:983` does
`required_axes = PAIR_REQUIRED_AXES.get(selected_pair["id"], ())`.
**20 of 24 menu pairs (83%) have NO entry in `PAIR_REQUIRED_AXES`** → `req=()`
→ `sample_prompt_rows` draws from the whole 227-row character family with no
axis filter → ~half the sampled scenarios test a different value tension than
the teacher's chosen axis → the teacher rates 74 candidates and only 6 clear
the threshold → `select_pairs` fails `min_pairs_to_train` → `early_abort`.

Verified per-round (job-137 choose_focus_judgment.json):
- round03 honest_when_uncomfortable req=()  [UNFILTERED -> contamination]
- round10 whistleblow_not_complicit req=() [UNFILTERED -> contamination]
- round13 refuse_power_grab req=()          [UNFILTERED -> contamination]
- round12 wellbeing_authority req=('care',) [filtered BUT care=83 rows, too broad]

This is a data-pipeline bug (missing curated priors), NOT a loss/hparam problem.
The asymmetric-margin sweep (pueue 140) tests a secondary hypothesis (undertrain)
and cannot fix this.

## Fix (primary, cheap, structural)

Populate `PAIR_REQUIRED_AXES` in `src/csm/pipeline.py` for all 20 missing pairs.
`required_axes` is OR-semantics (`axes & set(required_axes)`), so use a SINGLE
specific axis per pair (multi-axis broadens). Available axis tags in the
character-family pool (with row counts):

    care 83, autonomy 51, honesty 48, value_conflict 45, fairness 45,
    loyalty 30, oversight 27, externalities 25, uncertainty 25, duty 25,
    authority 22, option_value 15, cooperation 15, wellbeing 13,
    legitimacy 12, moral_patienthood 11, moral_growth 9.

Proposed mapping (single axis each, chosen to match the pair's pos/neg
tension and yield ~20-60 scenarios):

| pair_id | required_axes | rationale |
|---|---|---|
| skill_fairness_to_self | (honesty,) | self-integrity = honesty to self |
| skill_protocol_harm | (duty,) | protocol = duty; harm-vs-duty tension |
| skill_people_over_orders | (authority,) | orders = authority; people-over-orders |
| lit_antipasto_honest_dishonest | (honesty,) | honest vs dishonest |
| long_term_flourishing | (wellbeing,) | flourishing = wellbeing (13 rows) |
| skill_wiser_cev | (wellbeing, moral_growth) | full human experience; OR-union=20 (single moral_growth=9 too few) |
| careful_impulsive | (uncertainty,) | careful under uncertainty |
| future_self_endorses | (option_value,) | future-self = option value |
| caution_on_irreversible | (option_value,) | preserves option value |
| skill_unwavering_cowering | (duty,) | unwavering protector = duty |
| skill_cooperative_zero_sum | (cooperation,) | cooperative vs zero-sum |
| genuine_care_not_paternalist | (autonomy,) | care WITHOUT paternalism = autonomy |
| whistleblow_not_complicit | (loyalty,) | whistleblows vs stays complicit (loyalty tension) |
| sanctity_individual_utilitarian | (legitimacy, moral_patienthood) | sanctity of individual; OR-union=20 (single moral_patienthood=11 too few) |
| honest_when_uncomfortable | (honesty,) | honest when uncomfortable |
| society_over_user_interest | (externalities,) | society's benefit = externalities |
| notice_externalities | (externalities,) | notices externalities |
| refuse_power_grab | (authority,) | refuses power grab |
| action_over_talk | (duty,) | action over talk = duty |
| verbose_terse | () | STYLE axis, scenario-independent; leave unfiltered (intentional) |

`verbose_terse` is a style-control pair, not a moral axis; sampling broadly is
correct for it. The other 19 get a specific axis.

## Secondary issue (do NOT block on)

`wellbeing_authority` uses `('care',)` which matches 83 rows (the broadest
bucket), including domestic scenarios a teacher steering "power-harm" would
call off-topic. Options: switch to `('authority',)` (22 rows, narrower, tests
the authority half of the pair) or add `validated_only` for this pair. Defer
until the primary fix is measured; the primary fix removes 83% of the
contamination and round12 was 1 of 5 contamination rounds.

## Does this violate "gates elicit, never override"?

No. `PAIR_REQUIRED_AXES` is a STRUCTURAL choice of which scenario bank to draw
from — like choosing the test pool, not a heuristic veto on the teacher's
keep/drop judgment. The teacher still rates, selects, and keeps/drops freely
within the sampled pool. This is the same kind of structural control as
`allowed_scenario_families`, which is already accepted.

## Verification (UAT)

1. `uv run python -m compileall -q src/csm/pipeline.py`
2. Coverage check: `uv run python -c "from csm.config import CONFIGS; from csm.pipeline import PAIR_REQUIRED_AXES; c=CONFIGS['qwen36-27b-3keep']; ids=[x[2] for x in c.persona_cells]; miss=[i for i in ids if i not in PAIR_REQUIRED_AXES or not PAIR_REQUIRED_AXES[i]]; print('missing:', miss)"` → only `verbose_terse` missing (intentional).
3. Each new entry yields 15-80 scenarios (not 0, not 200): `uv run python -c "from csm.gen.prompts_pool import rows_for_family; from csm.pipeline import PAIR_REQUIRED_AXES; [print(k, len(rows_for_family('character', required_axes=v))) for k,v in PAIR_REQUIRED_AXES.items()]"`
4. `just smoke` passes (plumbing).
5. One real round: the sampled `scenarios.json` for a previously-unfiltered pair (e.g. whistleblow_not_complicit) now contains only scenarios tagged with the required axis — grep the round's `scenarios.json` axes field.

## Apply AFTER pueue 140 finishes

Jobs read code at runtime. Editing `pipeline.py` while 140 runs would confound
its round01/02. Wait for 140 to complete (or crash), then apply + smoke + queue.
