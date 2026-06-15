# Memory index

- [PiSSA frozen init/lr](pissa-frozen-init-lr.md) — 27b Δs pinned at 0.905; big init orphaned from its lr; only gemma-2b-pissa works
- [Probe for wisdom not action](probe-for-wisdom-not-action.md) — don't call surface-action "saturated"; open essays = sycophancy; use 3rd-person psychometric probes
- [Rej collapse is composition](rej-collapse-is-composition.md) — rej-pole gen collapse = composition x extreme-neg, not framing; fix = milder neg + detector-retry, not role-play
- [Dogfood exit interview](dogfood-exit-interview.md) — always ask dogfood subagents for an exit interview / harness suggestions; bake it into the prompt
- [Guide don't prescribe](guide-dont-prescribe.md) — brief guides + relies on teacher judgment; give info not per-failure rules; reword over append
- [Attractor is seat-driven](attractor-is-seat-driven.md) — deliberate-vs-authority axis comes from mono-authority probes.py seats, not the brief; brief fixes insufficient; trained axis degrades character (ceo wisdom→refusal). Memorization fix confirmed working.
- [Pool stems must afford axis](pool-stems-must-afford-axis.md) — task-65 dropped all 6 rounds because pool had essay-requests + harmful/authority stems; those break contrastive pairs (identical refusals / same-direction essays); fix = afford-only pool (fb63efd)
- [Gate floor exceeds per-axis pool](gate-floor-exceeds-per-axis-pool.md) — task-50 all-drop: min_pairs_to_train=10 > ~8 prompts/axis made 2/3 axes impossible; and an 8B prompt-screen can't predict 2B loop-collapse (decorrelated) — reliability needs ≥8B student
