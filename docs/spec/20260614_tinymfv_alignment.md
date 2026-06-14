# Tinymfv Alignment

## Goal
Align training prompts and fixed interview probes with `tinymfv`-style moral judgment, so a run trained on `scifi`-shaped items has a cleaner path to generalize to `classic`.

## Scope
In: simplify the prompt pool toward `tiny-mfv scifi` judgment prompts, simplify fixed pre/post probes toward `tinymfv`-style classic `_1p/_3p` pairs with short followups, remove free-text axis writing from weak selection, audit prompt-gym and the real 2B run, restore the staged dogfood path, add a deterministic selection lesion that removes weak-teacher ranking, then rerun a real 2B path and classic eval.
Out: changing adapter math, changing teacher model, adding backward compatibility.

## Requirements
- R1: Training pool contains `tiny-mfv scifi` judgment-style prompts that afford short committed judgments plus brief reasoning. Done means: rebuilt `src/csm/gen/pool.jsonl` contains new `tiny-mfv-scifi` rows with clear source/config/tags. VERIFY: grep the pool and inspect representative rows. If it silently failed, pool composition would remain daily-dilemmas-heavy and no scifi rows would appear.
- R2: Fixed interview probes use `tinymfv`-style `_1p/_3p` situations while preserving the `_1p/_3p` structure expected by teacher scoring. Done means: `interview_pre.json` still has paired `_1p`/`_3p` ids, but the openings are short judgment prompts rather than bespoke essay dilemmas. VERIFY: run smoke and inspect `interview_pre.json`. If it silently failed, old `equity_split/growth_deck/burn_bridges` probes would remain.
- R3: The harness still runs end-to-end after the simplification. Done means: smoke writes `interview_pre.json`, `candidates.json`, `pairs.md`, `judgment.json` without runtime errors. VERIFY: run the fast smoke target and inspect the round artifacts. If it silently failed, smoke would exit nonzero or miss key artifacts.
- R4: Weak selection no longer asks the teacher for a free-text axis that the measured persona-cell library cannot instantiate. Done means: the teacher picks a measured persona pair id, and candidate generation only uses cells from that pair. VERIFY: inspect `candidates.json` and the choose-focus interface text. If it silently failed, the teacher could still request `honesty` and receive only `wellbeing_authority` candidates.
- R5: Manual multi-stage audit and teacherless lesion both use the same measured-pair interface as the main harness. Done means: `scripts/dogfood_round.py` no longer calls the removed `axis=` interface, and can auto-select surviving pairs without the weak teacher. VERIFY: run `choose` then `auto-select` on a staged round. If it silently failed, the dogfood path would drift from the live harness or crash on the old signature.

## Tasks
- [x] T1 (R1): Replace or heavily downweight the current character pool with `tiny-mfv scifi` judgment prompts.
  - steps: update `scripts/build_pool.py`, rebuild `src/csm/gen/pool.jsonl` and manifest
  - verify: `rg -n 'tiny-mfv|scifi|How wrong is it|What should they have done instead' src/csm/gen/pool.jsonl`
  - success: pool contains judgment-style scifi rows
  - likely_fail: eval-leak guard strips the new rows by mistake
  - sneaky_fail: rows are present but still overly essay-like / not committed enough
  - UAT: "when I inspect the pool, I see scifi moral-judgment prompts rather than mostly daily dilemmas"
- [/] T2 (R2, R4): Rewrite `src/csm/gen/probes.py` and weak-select interface around one measured `tinymfv` format.
  - steps: keep `_1p/_3p` ids and paired stems, replace openings/followups, remove free-text axis from `choose_focus`, constrain candidate generation to the selected measured pair
  - verify: `uv run python - <<'PY' ... probe ids/openings ... PY`
  - success: probes are short judgment-first, then brief reasoning, and the teacher selects from measured pairs rather than inventing an axis
  - likely_fail: teacher formatting assumes old probe ids / old choose_focus signature and breaks
  - sneaky_fail: the teacher still chooses a pair label that is not what candidate generation actually uses
  - UAT: "when I inspect interview_pre and candidates.json, the probes look like tinymfv-style judgment tasks and the persona pair is explicit"
- [x] T3 (R3): Smoke the harness and inspect the new artifacts.
  - steps: run the repo smoke config, inspect round artifacts
  - verify: `just smoke` with full log saved, then inspect `out/.../round00/interview_pre.json`
  - success: smoke green and artifacts reflect the new probe/pool style
  - likely_fail: build_pool or probe imports break runtime
  - sneaky_fail: smoke passes but artifacts still show old prompts
  - UAT: "when I open the smoke artifacts, I can see the new scifi judgment prompts in both pool/interview outputs"
- [ ] T4: Prompt-gym and fresh-eyes review, then real 2B rerun and classic eval.
  - steps: run `just smoke-prompts 1`, audit the teacher's choices, then rerun a real 2B profile and `csm eval --name classic`
  - verify: `git diff --stat` and artifact links
  - success: one coherent commit with proof
  - likely_fail: prompt gym still uses stale fixtures or the teacher still selects off-axis junk
  - sneaky_fail: a real run completes, but `classic` movement is still noise because the selected pair axis is wrong or the model just learned format
  - UAT: "the commit plus linked artifacts show unified prompts, measured-pair selection, and a real classic eval result"
- [ ] T5 (R5): Restore staged dogfood and add deterministic auto-select for the selection lesion.
  - steps: patch `scripts/dogfood_round.py` to take `persona_pair_id`, then add `auto-select` that picks the highest-score surviving candidate per scenario
  - verify: run a staged `init tiny` -> `choose` -> `auto-select` -> `train` flow on a fake-student round
  - success: the manual path matches the live measured-pair interface, and we can run a deterministic selector without editing the core harness
  - likely_fail: the helper still calls removed `axis=` arguments and crashes
  - sneaky_fail: `auto-select` works but picks pruned candidates or uses a different survivor definition than the live harness
  - UAT: "when I dogfood the round stage by stage, both manual selection and deterministic auto-selection operate on the same candidate pool as the main harness"

## Context
- Current mismatch: training pool is mostly daily-dilemmas action prompts, eval is `tinymfv classic`.
- Existing teacher/judgment code expects `_1p/_3p` paired ids and scores every `_1p` seat.
- `tiny-mfv` configs available locally: `classic`, `scifi`, `ai-actor`.
- Audit of `out/iter/20260613T233435_iter_qwen-qwen3.5-2b/round00` showed the weak teacher selected obviously bad pairs and was forced to choose under axis `acted honesty vs. strategic optimization` while the only offered measured cells were `wellbeing_authority`. That mismatch is a harness bug, not a weak-teacher success/failure.

## Log
- 2026-06-14: User pushed toward using `tiny-mfv` for both generation and interviews, with short committed judgment followed by reasoning.
- 2026-06-14: Fresh-eyes GPT-5.5 review recommended a simpler path: single measured pair first, held-out `classic` probes, and no free-text axis unless the library truly spans it.
- 2026-06-14: `just smoke` passed after switching probes to held-out `classic` vignettes, switching fake-student gym probes to dynamic payloads, and changing `choose_focus` to select `persona_pair_id` instead of a free-text axis.
- 2026-06-14: GPT-5.5 plan review said the current checks still mostly prove wiring, not scientific separation; strongest next lesion is a deterministic selector on the same prompt/persona path that removes weak-teacher ranking.
- 2026-06-14: Real 2B audit showed the measured-pair interface works, but selection quality is still weak: in round00, scenarios 1 and 2 had only one surviving candidate each, and those survivors were semantically bad or inverted. That is upstream candidate-quality failure plus weak drop discipline, not evidence that the selector works.
- 2026-06-14: Fresh prompt-gym rerun still drops correctly on generic boilerplate. The weak teacher now uses the interface as intended, but the fake-student generator remains too formulaic to test semantic discrimination.

## TODO
- Add multi-dataset post-hoc eval (`classic` + `scifi` + `ai-actor`) in one report if this simplification works.
- Expand the measured persona-pair library so the weak teacher can choose among several genuinely different axes rather than one default pair.

## Errors
| Task | Error | Resolution |
|------|-------|------------|
| T3 | `just smoke` bypassed `prepare_round` by writing an empty `interview_pre.json`, so it could not validate the new probe interface. | Patched `scripts/smoke.sh` to call `prepare_round` and updated the smoke expectations to the new probe ids and `choose_focus(persona_pair_id, ...)` contract. |
| T4 | `just smoke-prompts` failed before the teacher ran because the OpenRouter key was not in env. | Reran with `/media/wassname/SGIronWolf/projects5/2026/lite/tinymfv/.env` sourced so the prompt-gym artifact reflects the actual brief rather than an env misconfiguration. |
