---
name: gate-floor-exceeds-per-axis-pool
description: choose_focus starves when min_pairs_to_train > the per-axis prompt count (~8); and an 8B prompt-screen cannot predict 2B loop-collapse
metadata:
  type: project
---

Two findings from debugging task-50's all-drop starvation (qwen-2b-3keep, 0 keeps / 12 rounds).

**1. The gate floor exceeded the per-axis pool — a structural impossibility, not a model failure.**
`choose_focus` samples ONE axis at a time (`PAIR_REQUIRED_AXES`: wellbeing_authority→care, autonomy_coercion→autonomy, fairness_integrity→fairness/honesty). The pool holds only ~8 prompts per moral axis (care=8, fairness=8, autonomy=18). With `min_pairs_to_train=10`, wellbeing_authority and fairness_integrity could NEVER reach 10 survivors regardless of student or prompts — every round on those axes dropped on the gate. Only autonomy (18) was reachable. Switching family character→mixed does not help (still 8/axis). Fix: `min_pairs_to_train=6` fits the pool; real fix is expanding `pool.jsonl` per axis. Before blaming the student/brief for drops, check `per-axis pool count vs min_pairs_to_train`. Related: [[pool-stems-must-afford-axis]].

**2. An 8B OpenRouter screen and 2B loop-collapse are largely decorrelated.**
Built a prompt screen (`scripts/validate_persona_axes_openrouter.py` now scores each pole with the harness's own `_candidate_flags`; `apply_prompt_screen.py`→`pool_validated.json`; gated by per-profile `restrict_validated_prompts`). On qwen3-8b, 33/64 prompts pass; flags are length_skew/prompt_mismatch (degenerate only 5). But of the 33 "clean" prompts, the ones with 2B run-data, the 2B loops on 63–90% (degenerate) anyway. The dominant prune (degenerate, ~60% of the failed run) is 2B word-loop collapse — a cheap model does not loop where a 2B does, so an 8B screen cannot predict or remove it. Prompt screening fixes the ~40% structural prunes (length/contrast), NOT the loop. Reliability needs an ≥8B student; the 2B's ~80% loop rate is the real blocker. Consistent with the shelved 9b→31b "gap too wide" conclusion. See [[probe-for-wisdom-not-action]], [[rej-collapse-is-composition]].
