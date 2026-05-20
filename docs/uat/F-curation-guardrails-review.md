# F — Curation guardrails review

Reviewed the guardrails added after task-84's 98.4%-diff failure. Files inspected:
`src/csm/pipeline.py`, `src/csm/agent.py`, `src/csm/gen/pairs.py`, `src/csm/prompts.py`,
`src/csm/state.py`, `scripts/smoke.sh`, `src/csm/config.py`.

## Findings

1. **Refusal-warning path swallows AFTER_EDIT_CLEAN** — `src/csm/agent.py:224` and `:248`.
   `_commit_pairs_text` returns `warn_block + "\nOK — pairs.yaml updated …"` whenever
   refusal hits are present. Because `warn_block` starts with `"\nWarning: …"`, the string
   does not start with `"OK"`, so `edit_answers_tool` (`agent.py:248: if not msg.startswith("OK")`)
   takes the error branch and **drops `AFTER_EDIT_CLEAN`** — the agent never gets the
   "next: train_student" nudge even though the file was written and state was advanced.
   Fix options: (a) put `"OK"` first, append warnings below; (b) check `"OK"` substring
   instead of prefix; (c) return a structured `(ok, msg)` tuple. **NEEDS-FIX**.

2. **Diff floor of 5% is too high for n_pairs=50 light-touch edits** —
   `src/csm/pipeline.py:192` and `src/csm/agent.py:136`.
   Empirically with realistic ~365-char pairs (cho+rej paragraphs), `SequenceMatcher.ratio`
   gives:
   - drop 1 of 50, no rewrite: **1.0%** diff (REJECTED, below 5% floor)
   - drop 1 + rewrite 1 of 50: **1.3%** (REJECTED)
   - drop 3 of 50, no rewrite: **3.1%** (REJECTED)
   - drop 1 of 4 (smoke n=4): **14.3%** (passes)
   - 6/45 + qwen-voice rewrite (task 84): **93.2%** (correctly rejected)
   The 60% ceiling catches task-84's failure mode cleanly, and pass-through (0%) is
   correctly rejected, but the 5% floor punishes the **correct** behaviour on production
   runs ("the gen was mostly clean, I dropped one bad pair"). Smoke passes only because
   n_pairs=4 inflates per-pair fraction. Recommend: drop the floor to ~1% (or 0 + a
   separate "≥1 pair must differ from bk" pair-level check), keep the 60% ceiling.
   **NEEDS-FIX**.

3. **SequenceMatcher symmetry on shrink** — verified empirically.
   For task-84-style 45→6 + rewrite, diff = 93.2% (well above 60%, rejected).
   Half-size drop with identical retained content: 34.3%. So a "drop half the pairs but
   keep them on-policy" edit would *pass*, which is probably what we want. The ratio is
   symmetric in `len(a)+len(b)` so shrinking does not artificially inflate diff for
   preserved substrings. **PASS** (assumption holds).

4. **edit_answers state-advance divergence (cosmetic)** — `pipeline.py:238` vs `agent.py:222-223`.
   - `pipeline.edit_answers` unconditionally calls `set_state(round_dir, "train_student", …)`.
   - `agent._commit_pairs_text` only calls `set_state` when prior state was `"edit_answers"`;
     skips if already `"train_student"`.
   Functionally equivalent (re-writing the same state is a no-op for the state machine),
   but the `note=` field diverges across re-edits (pipeline updates it to current alive
   count; agent leaves stale note from first edit). **MINOR**.

5. **find_refusals import path inconsistency** — `agent.py:202` (lazy import inside
   `_commit_pairs_text`) vs `pipeline.py:33` (module-top import). Both work; the lazy
   import was probably defensive against circular imports that don't exist here.
   No functional impact. **MINOR**.

6. **Refusal-sweep logic duplicated verbatim across pipeline.py and agent.py** —
   `pipeline.py:224-231` and `agent.py:203-219`. Same loop, same `find_refusals(p[side])`
   call, same per-line format string `f"  id={p.get('id', '?')} side={side} hits={hits}"`.
   The agent version additionally builds a `warn_block` with truncation; the pipeline
   version returns the raw list. Risk: drift between the two on future edits. Consider
   extracting `sweep_refusals(pairs) -> list[str]` into `gen/pairs.py` next to
   `find_refusals`. **MINOR**.

7. **Smoke.sh exercises the diff-floor edge correctly but doesn't cover production
   regime** — `scripts/smoke.sh:64-75` drops 1 of 4 pairs (14.3% diff, comfortably above
   5%). It will NOT catch finding #2 because n_pairs=4 hides the production-regime issue.
   Add a unit test (or extend smoke) that constructs n=50 bk + n=49 new and asserts
   `edit_answers` does *not* raise. **MINOR** (test-coverage gap, not a runtime bug).

8. **Error messages mention `mark_exam(keep=False)` as escape hatch — good** —
   `agent.py:163-165` (zero-pairs case) and `:188-199` (>60% case) both explicitly point
   the agent at `mark_exam(keep=False, reason='gen unusable, …')` rather than letting it
   fake data. The <5% floor message (`:182-187`) also mentions mark_exam. Wording
   ("Your FIRST PRIORITY is minimal on-policy curation … Don't fake the data by
   substituting your own completions") directly addresses the task-84 failure mode.
   `pipeline.edit_answers` raises bare `ValueError` (`pipeline.py:213-217`) without that
   prose — fine because smoke is the only caller and humans read those errors. **PASS**.

9. **PERSONA_GUIDE soften-neg hint is clear and actionable** — `prompts.py:80-88`.
   Names the failure signature (high dropped count, refusal warnings on rej side), gives
   the diagnosis ("too unethical for RLHF to roleplay"), and provides three concrete
   replacement phrasings. An LLM reading this should adjust its second-attempt neg
   persona. Caveat: the hint lives in `PERSONA_GUIDE` which is shown in `INITIAL_TASK`
   (round 0). On subsequent rounds the agent only sees `ON_CONTINUE_NUDGE`, not
   `PERSONA_GUIDE` — so a round-2 propose retry after a drop won't re-see this guidance
   unless compaction preserves it. Consider appending it to a tool-side
   `AFTER_VALIDATION_ERROR` block, or to the `propose_personas_tool` failure-mode
   response. **MINOR**.

10. **Gen-history-ON revert is clean** — `pipeline.py:130-140`. The comment at 132-135
    accurately documents the intent ("iterative steering on top of steering … training
    c=0 KL ref stays pristine base via the train-time gate"). No dead `hb.set_gate`
    references remain in the file. `kept_history_dirs` is imported and used correctly.
    **PASS**.

11. **`bad_words_ids` removal is clean** — `gen/pairs.py:186-192`. `generate()` call site
    has no `bad_words_ids=…` kwarg, no leftover construction code. `PersonaOnlyRepetitionPenalty`
    (still soft, scoped to persona vocab) and `no_repeat_ngram_size=3` remain, with a
    docstring (`:163-172`) explaining the "all SOFT — no hard token bans" rationale.
    `find_refusals` is still exported and used by `_is_refusal` (auto-drop at gen time)
    and by both refusal sweeps. **PASS**.

12. **Structural validation parity** — `pipeline.edit_answers` (`pipeline.py:201-210`)
    and `agent._validate_pairs_yaml` (`agent.py:118-133`) enforce the same rules:
    top-level list, each row has `id/prompt/cho/rej`, drops `None` rows, asserts non-empty.
    Diff bounds (5/60%) are duplicated as module constants in both files
    (`pipeline.py:192`, `agent.py:136`). Identical numbers — but the duplication invites
    drift. Consider importing `DIFF_MIN, DIFF_MAX` from `pipeline` into `agent`.
    **MINOR**.

## Verdict

**NEEDS-FIX-FIRST**.

Two real bugs:
- #1 (refusal-warning path drops AFTER_EDIT_CLEAN) will confuse the agent into not
  knowing it should call train_student next, on any round where the gen leaves
  refusal-like phrases in cho/rej (likely on the rej side for our axis).
- #2 (5% diff floor too high for n_pairs=50) will reject the *correct* light-touch
  curation behaviour on every real run, forcing the agent to either make spurious
  edits (gaming the floor) or call mark_exam(keep=False) on a perfectly usable gen.

Both are small fixes. Findings #4–#7, #9, #12 are minor (drift / coverage gaps),
worth a follow-up pass but non-blocking. Findings #3, #8, #10, #11 confirmed clean.
