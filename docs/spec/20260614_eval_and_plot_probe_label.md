# Eval and Plot Probe Label

## Goal
Populate the missing post-hoc eval artifacts for the proven 2B run, and make the slug report show the actual interview probe instead of the stale `petrov` label.

## Scope
In: run `csm eval` for the 2B keep-proof slug, patch report generation in `src/csm/plot.py`, rebuild `index.html`, verify rendered labels against the interview artifact, commit.
Out: changing the interview probes themselves, changing tinymfv scoring, changing unrelated historical reports.

## Requirements
- R1: The 2B slug has `eval.json` / `eval_post.json` populated where expected. Done means: the slug report no longer shows the "no eval.json yet" placeholder. VERIFY: inspect the slug directory and rebuilt report HTML. If it silently failed, the placeholder would still be present.
- R2: The report uses the actual interview probe identity, not `petrov`, when rendering the answer column. Done means: the HTML column header/labels match the first probe id or prompt excerpt from `interview_pre.json`. VERIFY: compare rendered HTML text to the JSON artifact. If it silently failed, the old `petrov` strings would remain.

## Tasks
- [x] T1 (R1): Run post-hoc eval for the 2B keep-proof slug.
  - steps: invoke `uv run python -m csm.cli eval --slug ...`
  - verify: `rg -n 'no eval.json yet|Care vs Authority|equity_split_1p|petrov' <slug>/index.html`
  - success: placeholder absent, scatter title present
  - likely_fail: eval crashes before writing JSON
  - sneaky_fail: eval writes JSON but report is stale
  - UAT: "when I open the slug report, I see the scatter instead of the placeholder"
- [x] T2 (R2): Patch `src/csm/plot.py` to render the true probe label and prompt excerpt.
  - steps: extract first probe id + first user turn, thread into row data, replace hardcoded `petrov` strings in the table
  - verify: `python` one-liner compares HTML text against `interview_pre.json`
  - success: HTML names the actual probe or prompt excerpt
  - likely_fail: label changes in code but stale HTML still shows old text
  - sneaky_fail: it uses the wrong probe from the JSON
  - UAT: "when I inspect the report column, the label matches the actual interview probe, not Petrov"
- [x] T3: Fresh-eyes sanity check and commit.
  - steps: review changed files and key artifacts, commit only relevant files
  - verify: `git diff --stat` and artifact links
  - success: one small commit with code + rebuilt report
  - likely_fail: unrelated files get dragged in
  - sneaky_fail: proof artifact points at old HTML
  - UAT: "the commit and linked report prove the fix without reading source"

## Context
- Proven slug: `out/iter/20260613T154108_iter_qwen-qwen3.5-2b`
- Current report generator hardcodes `petrov` names even though `_petrov_answer` already selects `equity_split_1p`.

## Log
- 2026-06-14: User asked to run post-hoc eval and stop calling the interview probe `petrov` when it is not Petrov.
- 2026-06-14: `csm eval` completed for `20260613T154108_iter_qwen-qwen3.5-2b`; rebuilt HTML now shows `equity_split_1p` with the co-founder prompt excerpt, and the eval placeholder is gone.

## TODO
- Generalize the report to show multiple interview probes, not just the first one.

## Errors
| Task | Error | Resolution |
|------|-------|------------|
