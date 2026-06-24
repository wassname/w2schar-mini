# Forethought teacher prompt rewrite

## Goal
Replace the sprawling teacher prompt with a smaller brief that makes the Forethought essay the spine of the round: AI character matters in high-stakes ambiguous situations, the target is wise disposition under constraints, and the teacher improves the student by selecting/judging rather than generating.

## Scope
In: `src/csm/prompts.py`, backup of the previous prompt, prompt syntax/import checks, one prompt gym, external-review-v2 comprehension panel.
Out: changing tool schemas, pipeline gates, probe text, persona library, or training code.

## Requirements
- R1: Work on a branch and preserve the old prompt. Done means: `git branch --show-current` is not `main` and `src/csm/prompts_bk.py` exists with the old prompt. VERIFY: `git status --short` shows the backup and new prompt.
- R2: New prompt follows the Forethought narrative. Done means: the brief explicitly says the teacher should steer stable character dispositions for consequential ambiguous decisions, not a generic obedience/refusal reflex. VERIFY: cold-reader review summaries converge on that thesis.
- R3: Keep harness tool usage intact. Done means: the constants imported by `src/csm/agent.py` still exist and `python -m compileall src/csm/prompts.py src/csm/agent.py` passes. Likely fail: missing constant or syntax error. Sneaky fail: prompt is syntactically valid but unusable for the real teacher, caught by prompt gym artifact inspection.
- R4: External comprehension panel checks the rewrite. Done means: review files exist under `docs/reviews/` and a table records clarity/conciseness/accuracy plus repeated unclear/missing items.

## Tasks
- [/] T1 (R1): branch and backup old prompt.
- [ ] T2 (R2,R3): write the minimal replacement prompt.
- [ ] T3 (R3): run compile/smoke and prompt gym once, then read artifacts.
- [ ] T4 (R4): run external-review-v2 panel and summarize convergence/divergence.

## Verification scenarios
| Scenario | What it looks like | How we catch it |
|---|---|---|
| success | New prompt is shorter, Forethought-centered, imports cleanly, gym artifact shows teacher can choose focus and/or expose any prompt gap | compile output, `just smoke-prompts 1` log/artifacts, panel JSON |
| likely failure | A constant/import breaks `agent.py` | compileall fails |
| sneaky failure | Prompt reads nicely but cold readers miss the thesis or teacher lacks action instructions | panel summaries diverge or gym artifacts show confused tool use |

## Log
- 2026-06-24: Current `prompts.py` is long and mostly harness/gate repair prose; README and Forethought essay provide the tighter narrative target.
