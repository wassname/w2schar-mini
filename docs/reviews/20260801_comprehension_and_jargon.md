# Comprehension and jargon review

Codex ran the `external-review-v2` cold-reader panel on 2026-08-01. The first pass used DeepSeek V4 Flash, Gemini 3.1 Flash Lite, Gemma 3 12B, Kimi K2.7 Code, GPT-OSS-120B, and Nemotron 120B. After the accepted edits, DeepSeek V4 Pro performed the focused recheck.

## Probe

The readers were asked to restate the thesis and reconstruct one complete training round in their own words, then distinguish behaviour from lesson, adapter from steering edit, and teacher from judge. They were also asked what human supervision is present and absent, and to list inconsistent or unclear terms.

## Expected reading

My reading before the panel was:

> Each round the teacher identifies a behaviour to improve and chooses two personas, which together act as the lesson. The student writes both sides of the contrastive pairs. The teacher filters them, the harness trains and calibrates a steering adapter, and the same 9B teacher judges held-out before/after answers blindly in both orders. A fixed vote rule decides keep/drop. Humans wrote the target and harness, but supplied no per-example preference labels.

## First-pass answers

Five of six readers recovered the thesis and loop. Representative verbatim fragments:

- DeepSeek V4 Flash: "The weak teacher reads the student's interviews and identifies a behaviour to improve" and "the harness trains a steering adapter". It correctly reconstructed the loop, but said the judge's identity was unspecified.
- Gemini 3.1 Flash Lite: "The strong student generates responses for both personas" and "the harness screens these pairs, trains a steering adapter". It also read the judge as external or unspecified.
- Gemma 3 12B: "The aim is to move the student to prioritize individuals and deference to authority." This inverted the direction of authority steering. The body says "defer less to authority", so this was a lone reader error rather than panel convergence.
- Kimi K2.7 Code: "the strong student generates one answer under each persona" and "a blind judge compares the two answer orderings". It correctly reconstructed the mechanism but could not identify the judge.
- GPT-OSS-120B: "The teacher reads the student's pre-steer interview and selects a target behavior to improve" and "the harness trains a steering adapter on the retained pairs". It could not tell whether the blind judge was human or another model.
- Nemotron 120B: "the weak teacher reads the student's current answers to select a target behavior and two opposing personas". It also left the blind judge's identity unresolved.

The panel converged on three real terminology gaps:

1. `adapter` and `steering edit` appeared to name the same object.
2. `behaviour` and `lesson` were used without a stable distinction.
3. `teacher` and `judge` made it sound as though a separate judge might decide keep/drop.

It also converged on a supervision wording problem: "no human labels" could be read as no human input, despite the human-written character spec and harness.

## Edits accepted

- `steering adapter` is now the only public name for the trained weight modification.
- The teacher identifies a behaviour to improve and chooses two personas, which together act as the lesson. The appendix now says that its `lesson` field is merely the teacher's short text summary of the persona contrast.
- The method and appendix now state that the same 9B teacher judges before/after answers in fresh blind calls, while a fixed vote rule decides keep/drop.
- "No human labels" is now "no per-example human preference labels" and the human-designed harness is stated alongside it.

Requests for complete adapter equations, calibration thresholds, and composition mechanics were rejected as out of scope for this short public article, which links the implementation. Proposed voice rewrites were not applied.

## DeepSeek V4 Pro recheck

After the edits, DeepSeek V4 Pro reconstructed the complete round correctly:

> The same teacher then compares the student's before and after answers on fixed interview questions, presented in random order twice, and a fixed vote rule decides whether to keep the adapter.

It also correctly reported:

> The 9B teacher model acts as the judge for before/after comparisons; however, the actual keep/drop decision is made by a fixed vote rule.

Its only remaining terminology complaint was that `lesson` could mean the persona pair or its short text summary. The appendix was then amended to state that relationship explicitly. The remaining requested details are implementation depth rather than inconsistent public terminology.

The complete focused response is in [panel_recheck_20260801_deepseek-v4-pro.json](panel_recheck_20260801_deepseek-v4-pro.json).
