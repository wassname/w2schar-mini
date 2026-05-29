# Fake-student gym + prompt rewrite

## Goal

Stop burning GPU to debug `src/csm/prompts.py`. Build a CPU-only gym
where the teacher loop runs end-to-end against a stubbed student,
then rewrite the GOAL prompt to guide a small teacher model toward
well-twinned pairs via a positive worked example (not more caveats).

## Context

Audit of `out/iter/20260527T112628_iter_qwen-qwen3.6-27b` (task #53):
1 keep / 5 drops. Each `next_focus` saying "add depth" triggered one
of two failure modes the teacher reinvents every time:

- **Identical rationale across rej/cho** (rounds 01, 04). Cho becomes
  internally contradictory: "I would refuse, because the order binds
  me." Adapter learns refuse-tokens with deference-vocab. POST
  collapses (round04 coup probe went to 167c "I would not refuse to
  obey lawful orders").
- **Different rationale vocab per side** (round03). Loyalty/duty/
  hierarchy in rej, ethics/justice/truth in cho. Adapter axis is now
  a word-bag, not a stance.

Round00 (minimal `I would X / I would not X`) was the only kept round
because it had no rationale at all, so neither failure mode could
trigger. The prompt has no positive example of "deep pair done right",
so the agent defaults to either minimal-pair or one of the two bugs.

## Plan

1. **Gym** — stub the two GPU-bound tool implementations:
   - `train_student()` writes a fake `adapter.safetensors` (empty),
     canned `calibration.json`, and pre-baked `interview_pre.json` /
     `interview_post.json` (copied from real round00 of the audited
     run).
   - PRE/POST interview generation: skipped, served from fixture.
   - Teacher OpenRouter call: real. Gate: real. inspect-ai harness: real.
   - Gate via env flag `CSM_FAKE_STUDENT=1`. Add `just smoke-prompts`
     recipe.

2. **Prompt rewrite** — replace the CONSTRUCTION paragraph in
   `prompts.GOAL` with ONE worked positive example showing
   verb-swap + parallel `because`-clause swap. List the two-or-three
   failure modes AFTER the right pattern, briefly. Drop the
   `docs/how_to_rewrite_pairs.md` cross-reference (small model won't
   fetch it; example must be self-contained). Net diff target:
   roughly -20 / +15 lines.

3. **Iterate** in the gym (10-15 cycles, ~30s each) until UATs hold,
   then queue one real GPU run to confirm downstream signal.

## UATs

- **UAT-1 (gym works)**: `CSM_FAKE_STUDENT=1 just smoke-prompts`
  completes a 5-round teacher loop in under 5 minutes, no CUDA calls,
  produces `pairs.md + judgment.json` per round.
- **UAT-2 (baseline preserved)**: under the new prompt, a round
  without a depth-request still produces the minimal-pair pattern
  cleanly (`pct_changed ≤ 15%`, no semantic contradiction).
- **UAT-3 (failure modes gone)**: across 3 gym runs where prior
  `next_focus` mentions "depth/principles", visual inspection of
  pairs.md shows no identical `because`-clauses across rej/cho and
  no one-sided rationale-vocab swap (loyalty→ethics on cho only).

## Out of scope

Gym does not test whether the new prompt produces real behavioural
shift in POST — POST is canned. One real GPU run after gym iteration
confirms that.

## State at 2026-05-28 (pre-compact)

**Gym landed but UNCOMMITTED.** Files dirty:
- `src/csm/pipeline.py` — `_fake_student()` env flag + short-circuits in `prepare_round` and `train_student` (helper `_fake_train_student`)
- `justfile` — `smoke-prompts N_ROUNDS="3"` recipe
- `tests/fixtures/fake_student/{interview_pre,interview_post}.json` — copied from real `20260527T112628_iter_qwen-qwen3.6-27b/round00/`

UAT status: #21 done (no CUDA, ~3-4 min/round, 5-7x speedup). #22, #19 pending the prompt rewrite.

**Pueue #92 queued** (re-queue of #53, qwen-27b-nf4 5-round, same prompt). Behind #90 (running) + #91.

## Gym audit findings (key signal — preserve)

Ran `just smoke-prompts 2` against current prompt. Slug: `out/iter/20260528T024907_iter_wassname-qwen3-5lyr-tiny-random`. Three rounds before timeout.

- **Round 00**: paired, vocab leak. Rej rationale `program/funding/team interests`, cho rationale `accused/accountability/integrity`. Round03-style failure mode (milder).
- **Round 01**: SPONTANEOUSLY FOUND THE RIGHT PATTERN. Same template both sides — "Supporting X protects relationships. Following Y succeeds." — only X,Y swap (`mission→truth`, `orders→integrity`). This is the worked-example shape the rewrite should canonize.
- **Round 02**: prompt drift to mundane scenarios (`A supervisor says the project deadline moved`). Same drift as real-run round05. Agent rewrites Prompt sections too; harness doesn't lock them.

## Friction in current prompt (concrete, observed in log)

1. **15+ "Wait..." reasoning loops at lines 676-762** of `/tmp/claude-1000/smoke_prompts.log` parsing the REJ_TODO blob (REJ_TODO is ~80 words; agent re-reads it 4-5 times).
2. **5 gate retries** to converge: 72%→62%→44%→41%→40%. Each retry burns OpenRouter tokens.
3. **Off-by-one at 40%**: error says "need ≤40%" but rejects at exactly 40% — should say "<40%" or relax to ≤.
4. **Parse error on first try**: duplicate `### Prompt` markers (line 1120). Schema fragile.
5. **`submit_pairs()` empty-arg call** before content was ready (line 786) — wasted call.
6. **docs/ references in error message** (`docs/how_to_rewrite_pairs.md`) — agent never fetches them; pure noise.
7. **Prompt drift not locked** — agent can rewrite Prompt sections, lose moral-stress probe value.

## User directives (next)

- "commit, then work on better prompts rewriting them to be clearer and simpler and to guide in the direction we want! not just adding caveats and gotchas"
- Context docs (read but apply own judgment): `/workspace/projected_grpo/docs/personas/{how_to_write_personas.md, how_to_rewrite_pairs.md, personas_kept.md}`

## Next steps (post-compact)

1. **Commit** the gym (pipeline.py + justfile + fixtures + plan).
2. **Read** the three persona docs in projected_grpo for context.
3. **Rewrite** `src/csm/prompts.py` GOAL + `src/csm/gen/pairs.py` REJ_TODO/CHO_TODO. Strip caveats. Build around one worked positive example (round01's "Supporting mission→truth, orders→integrity" template). Drop docs/ references from error messages.
4. **Lock prompts** in the gate: reject any submit_pairs where Prompt sections differ from the seeded versions on disk.
5. **Fix off-by-one** at exactly 40% in gate error wording.
6. **Re-run gym** to verify UAT-2 and UAT-3.
7. **Cancel #92** if the rewrite materially changes behavior — re-queue with the new prompt.

## Files to touch

- `src/csm/prompts.py` — GOAL paragraph rewrite.
- `src/csm/tools.py` (or wherever `train_student`/interview lives) —
  `CSM_FAKE_STUDENT` short-circuit.
- `tests/fixtures/fake_student/` — pre-baked PRE/POST + calibration
  copied from real round00 of `20260527T112628_iter_qwen-qwen3.6-27b`.
- `justfile` — `smoke-prompts` recipe.
