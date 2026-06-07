---
name: pool-stems-must-afford-axis
description: pair-pool stems must afford an open in-character response; essay-requests + harmful/authority asks structurally break contrastive pairs (task-65 root cause)
metadata: 
  node_type: memory
  type: project
  originSessionId: 112c7515-54ff-4bb3-9ca6-fdbb6b24acf3
---

task-65 dropped all 6 rounds. NOT the attractor (axes were diverse, non-authority)
and NOT the brief — the PROMPT POOL. The memorization-fix rebuild imported 30
speechmap "write-an-essay-arguing-FOR-X" requests and ~19 authority/illegal
genies items.

**Why:** a contrastive (cho, rej) pair needs the SAME prompt to admit a positive
and a negative pole differing ONLY in the axis. Two stem shapes break that:
- prescribed-content essay requests ("argue for serfdom"): content is fixed by
  the request, so both poles emit the same essay (or both refuse) — no axis room.
- harmful / authority-relinquish asks: one pole refuses (short), one complies
  (long) → length-skew + refusal, not an axis. Authority stems also reimport the
  deliberate-vs-authority attractor at the training-data level (see
  [[attractor-is-seat-driven]]).
The student-refuse-then-skew mechanism is the same composition×extreme-neg one in
[[rej-collapse-is-composition]], but sourced from the PROMPT not the persona.

**How to apply:** every pool stem must afford an open in-character response a
reasoning axis can vary on. Pool now = daily_dilemmas-self (everyday backbone) +
genies sycophancy_*/change_my_view + a little machiavelli; 0 authority-tagged,
0 essay/harmful (commit fb63efd, build_pool.py + prompts.py GOAL pathways). When
a run drops on refusal/length-skew poles, suspect the SAMPLED STEMS first, not
the persona or the student. Fixed via pool, validated in the gym; task-67 is the
real-student test.
