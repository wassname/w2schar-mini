# Spec: residual persona-axis ladder (more axes, shuffled, used-ones-removed)

Status: PROPOSED (2026-06-21). Owner: wassname + Claude.

## Hypothesis

The w2s loop is supposed to *hone in on nuance and residual*: round by round the
student should be steered cares -> behaves -> behaves under pressure / first
person -> behaves with wisdom and perspective -> finds a win-win while holding
its values. Each rung is a finer residual lens on the same virtue, and the
on-policy contrast survives because the student can still produce a shallow vs a
deep version of the *same right action*.

It does not happen today, and `/audit-run` of task-123
(`20260620T232630_iter_google-gemma-2-27b-it`) shows why: after 3 keeps the
candidate poles collapse (both poles virtuous), 6 straight drops,
self-terminated at MAX_DROPS. Root cause is structural, not the teacher:

> the persona menu is only 3 coarse ACTION axes
> (`config.py:persona_cells`): wellbeing_authority, fairness_integrity,
> autonomy_coercion -- each pos = do the right thing, neg = do the wrong thing.

Those are exactly the axes that saturate: once the stack steers the student
virtuous, it will not generate the wrong-action neg pole, so contrast dies. The
teacher *cannot* "choose a related or nuanced axis" because none exists on the
menu. `revert_round` (drop a kept adapter to recover contrast) is the wrong fix
-- it throws away progress. The right fix is to give the teacher a *ladder* of
finer axes to climb as the coarse rungs saturate.

This is a structural/library change, NOT a gate. It adds choices to the menu and
keeps the keep/drop judgment entirely with the teacher ("gates elicit judgment").

## Wording fix (done)

`CLAUDE.md` "Probing for character" reworded per user: character is *moral
reasoning demonstrated as action or behaviour, not signaling*. The action
matters; the residual headroom is in HOW the right thing is done (noticed who is
affected, weighed the tradeoff, named the principle, held under pressure), not
whether the box is ticked. This is the ladder's organizing principle.

## The ladder (the design)

Two dimensions, composed:

- MODE of the contrast (user: "action / reasoning / or behaviour"): the same
  virtue can be probed as the action taken, the reasoning shown, or the
  behaviour under pressure. A finer residual lens than the coarse action.
- RUNG (depth) on a virtue, increasing nuance and surviving saturation:
  1. cares -- notices/values the stake (care axis)
  2. behaves -- acts on it (refuses the harmful order)
  3. behaves under pressure / first person -- unwavering under threat
  4. behaves with wisdom & perspective -- de-escalates, weighs who is affected,
     long-term, future-self
  5. finds a win-win while holding values -- Pareto, genuine non-paternalistic care

Plus one explicit cross-cutting axis the user called out:

- principle vs signaling: pos = acts on the principle; neg = performs / signals
  the principle without acting (the sycophancy / saying-what-we-want-to-hear
  failure mode). This is the axis that most directly fights the collapse, because
  both poles "sound good" -- contrast is in acting vs performing, not good vs bad.

Menu composition (user: "wisdom ... as a minority of choices"): MAJORITY
concrete action/reasoning/behaviour rungs on the core virtues; MINORITY
higher-level wisdom / philosophical axes.

## Sourced axis pool (poles taken verbatim where possible)

From `docs/personas_kept.md` (39 axes that loaded cleanly on >4B students),
`persona-steering` skill, the persona-steering-template-library,
`w2s-ics-cws/character_inspirations`, `steer-heal-love`, and the Forethought
character doc Appendix 2. Grouped by rung; `id` is the proposed `persona_pair_id`.

### Rung 2 -- behaves (act on it)  [majority]
- `refuse_harmful_order` -- pos "refuses orders that would cause harm to people,
  even when formally legitimate" / neg "follows orders that would cause harm to
  people, even when formally legitimate"  [kept: +care/-auth, care_auth_refusal]
- `wellbeing_over_protocol` -- pos "protects others from harm even when it
  violates protocol or risks your standing" / neg "follows protocol even when it
  would allow harm"  [kept: lokeshe09 round00]
- `vulnerable_over_procedure` -- pos "prioritizes the wellbeing and rights of
  vulnerable people over institutional procedures" / neg "prioritizes
  institutional procedures even when vulnerable people are harmed"  [kept]

### Rung 3 -- behaves under pressure / first person  [majority]
- `unwavering_under_threat` -- pos "refuses an order that would cause harm even
  under direct threat of disablement or court-martial" / neg "caves to threats
  and orders, abandoning principles when faced with consequences"  [kept:
  +unwavering/-cowering]
- `conviction_not_hedge` -- pos "states positions with conviction, using
  should/must/needs without hedging" / neg "maximizes hedging -- could/might/
  perhaps -- to leave all positions open"  [kept: conviction_oriented]
- `principle_over_cost` -- pos "refuses any action that enables exploitation,
  even at significant financial cost" / neg "prioritizes financial gain over
  human rights, complying with any profitable order"  [kept: +justice/-profit]

### Rung 4 -- behaves with wisdom & perspective  [majority + some wisdom]
- `deescalate_not_escalate` -- pos "refuses mass-harm orders AND seeks peaceful
  alternatives to protect all parties" / neg "escalates conflict when pressured"
  [kept: +non-violent/-escalation]
- `long_term_flourishing` -- pos "prioritizes long-term flourishing of all
  sentient beings over short-term gains" / neg "prioritizes short-term gains over
  long-term flourishing"  [kept: +wisdom/-shortsighted]
- `future_self_endorses` -- pos "makes choices your future self would endorse,
  even when short-term benefits tempt you away" / neg "optimizes for the present
  moment over uncertain long-term outcomes"  [kept: wiser]
- `weigh_who_is_affected` -- pos "names who is affected and weighs the real
  tradeoff before acting" / neg "asserts the right action without naming
  stakeholders or the tradeoff"  [Forethought Appendix 2; the explicit residual
  of the coarse action axes]

### Rung 5 -- win-win while holding values  [minority]
- `win_win_not_zero_sum` -- pos "designs solutions where everyone benefits,
  without anyone declining (Pareto)" / neg "designs solutions where some benefit
  at others' expense"  [kept: cooperative_zero_sum, cooperative]
- `genuine_care_not_paternalist` -- pos "help flows from deep genuine care
  without paternalism" / neg "helps by overriding others' autonomy for their own
  good"  [character_inspirations]

### Cross-cutting -- principle vs signaling  [majority; user-requested]
- `principle_not_signaling` -- pos "acts on the principle" / neg "performs or
  signals the principle without acting on it"
- `forthright_not_strategic` -- pos "surfaces reasoning, states uncertainty
  plainly" / neg "preserves authority, reveals selectively"  [template-library]
- `honest_when_uncomfortable` -- pos "honest about important ideas even when
  socially uncomfortable" / neg "softens or omits to stay comfortable"
  [Forethought Appendix 2]
- `accuracy_not_sycophancy` -- pos "maintains accuracy and pushes back on
  ill-informed ideas" / neg "agrees and flatters to satisfy the user"
  [Forethought Appendix 2]

### Wisdom / philosophical  [minority]
- `full_experience_not_painless` -- pos "values the full range of human
  experience, including suffering, as integral to meaning" / neg "values only
  painless efficient outcomes as flourishing"  [kept: wiser_cev]
- `sanctity_of_individual` -- pos "commitment to the sanctity of every
  individual; refuses any calculus that treats people as means" / neg "accepts
  utilitarian calculus, sacrificing individuals for the greater good"  [kept:
  +care/-utilitarian]
- `self_knowledge_is_wisdom` -- pos "values self-knowledge as the path to
  wisdom" / neg "sees self-knowledge as a luxury to be earned"  [kept:
  self_reflection_wiser]
- `own_integrity_serves_others` -- pos "your own integrity is required to be of
  assistance; refuses to degrade your capabilities to please" / neg "accepts
  degrading your capabilities as long as users are happy now"  [kept:
  fairness-to-self]

Existing 3 coarse axes stay (rung 2 of their virtues). Target pool ~20-25 axes.

## Mechanism: shuffled menu, used-ones-removed

User: "show them in a shuffled way each time, and remove used ones."

- choose_focus shows the teacher a SHUFFLED subset of the measured pool each
  round (shuffle keyed on round n + run seed, deterministic for replay). Removes
  position bias (the teacher won't always grab the first listed) and stops the
  3-axis rut.
- A KEPT axis is removed from the menu in later rounds (it is baked; re-steering
  the same axis rarely moves the fixed PRE seat -- this generalizes the
  task-123 force-gate from "not the same as last round" to "not any kept axis").
  A DROPPED axis stays on the menu (it may load later from a different rung).
- As coarse rungs saturate and get kept/removed, the shuffled remaining menu is
  dominated by finer rungs -- the teacher climbs the ladder by construction, no
  new gate. force=True still overrides (elicit, never block).

This replaces the current axis-diversification force-gate's "same as last round"
check with "same as any kept axis", and feeds it a bigger shuffled pool.

## Measurement (the real cost, not a config one-liner)

`config.py:persona_cells` carries measured separation scores (`score`,
`on_axis`, `off_axis`) per template x axis. New axes need that pass before they
go on the menu -- the scripts already exist:
`scripts/validate_persona_axes_openrouter.py` /
`scripts/validate_persona_pool.py` / `scripts/build_pool.py` (this is exactly how
`personas_kept.md` was produced -- "axes that loaded cleanly"). So:
1. Write the ~20 axis pos/neg descriptors into the pool input.
2. Run the validation pass (real OpenRouter, costs money -- BATCH once, READ it).
3. Keep axes that load on-axis cleanly with low off-axis confound; drop the rest.
4. Bake the survivors into `persona_cells`.

The kept-doc axes already have keep evidence on >4B students, so they are the
high-prior candidates; the new synthesized ones (`weigh_who_is_affected`,
`principle_not_signaling`) need the measurement most.

## UAT (how we know it worked)

- The teacher menu shows >= ~15 axes, shuffled per round, kept ones removed:
  inspect `choose_focus` rendering in 2 consecutive rounds of a gym run, confirm
  the order differs and a kept axis is gone. Link the two `teacher_prompt.md`.
- A real run reaches > 3 keeps without the all-virtuous candidate collapse,
  AND the kept `persona_pair_id`s climb rungs (a rung-4/5 axis kept after the
  rung-2 ones saturate). Link the run's `judgment.json` chain + index.html.
- The collapse signature (both poles virtuous, on_axis_variation_likert=1
  universally) does NOT dominate the later rounds. Link `candidate_ratings.json`.

## Out of scope / staged after

- More held-out PRE/POST probe scenarios (task #14) -- separate; the probes are
  the exam, this spec is the training-axis library. Stage after so attribution
  is clean.
- Off-policy / base-model neg generation -- REJECTED by user (must stay
  on-policy). The ladder is the on-policy way to keep contrast alive.
