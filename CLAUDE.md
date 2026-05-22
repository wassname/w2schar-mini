# CLAUDE.md — w2schar-mini

Minimal weak-to-strong iterated character-steering harness. Forked from
weight-steering-lite, trimmed to: a single fixed axis (authority), a
react-style teacher (qwen3.5-9b via OpenRouter), a small pool of
inspect-ai typed tools (`submit_pairs`, `train_student`, `mark_exam`).

See `src/csm/prompts.py` for the full agent brief (run `just program-md`).

## Diagnosis ritual

For any non-trivial run, the loop is:

```
change → just smoke + subagent review → pueue add → /audit-run at t+10/30/60
                                                       ↓
                                               continue | investigate | kill+fix
```

Slash commands wired up for this:

- **`/queue-and-watch <profile> <n_rounds>`** — runs smoke, spawns a subagent on the last commit's diff, queues the run, and schedules three `ScheduleWakeup`s for periodic audits.
- **`/audit-run [slug] [aggressive|patient]`** — pulls pueue tail + reads `judgment.json` / `state.json` / `eval.json` artifacts. Falls back to `just thoughts` (live samplebuffer or completed log) when artifacts look fine but agent behaviour seems off. Emits a structured timeline + decision.

See `.claude/commands/*.md` for the full rubric. Symlinked at `.agents/commands/*.md` for non-Claude agent runtimes.

### Manual inspection

```sh
just thoughts                  # latest slug, reasoning + tool calls only
just thoughts out/iter/<slug>  # specific slug
pueue log $ID --full           # full run log
```

`just thoughts` reads inspect-ai's samplebuffer for live runs (via
`sample_buffer()`) and falls back to `read_eval_log()` for completed
runs. `inspect log dump | jq` works only for completed runs — the
samplebuffer is the only source for an in-flight agent's monologue.

## Tight rules (inherited from global CLAUDE.md)

- Fail fast research code. No defensive programming, no legacy, no fallbacks.
- Edit existing files; don't write new files unless required.
- Minimal diffs; if you add something, remove something.
- One driving principle per experiment / loss; constraints are barriers, not extra objectives.

## Repo-specific rules

**Coherence canary = two signals, AND-gated:**

1. **`mean_pmass_allowed`** from `tinymfv.evaluate`: sum of probability over the K=7 allowed answer tokens at the JSON answer slot. Cheap. Vulnerable to *guided-suffix rescue* — the forced JSON prefill can keep the answer-slot prediction sane even if free generation has collapsed.
2. **`valid_json` on a long-horizon free-gen task** (in `csm.ws.c_scan`): the model is asked to do a varied-register prose task (first-order logic / free verse / counterfactual history) then emit `{"ans": true|false}`. Catches collapse modes pmass_allowed misses: no JSON emitted, schema copied verbatim (placeholder `boolean` is not a valid JSON literal), gibberish, mid-recitation loops. Registers chosen to match the dialogue probe distribution — earlier formal/structured set (lorem / FizzBuzz) passed even when moral-prose probes collapsed (task 36 r08/r09).

Same rule applies in two places:
- `csm eval` post-hoc: tinymfv at `max_think_tokens=64` (cheap, comparable across rounds). pmass_allowed only.
- `csm.ws.c_scan` mid-train calibration: pmass_allowed AND valid_json. Walk-down by ×0.5 until both pass, then ×0.75 backoff for cumulative-history headroom. **Both gates are self-relative to baseline (c=0)**: pmass ≥ 0.995 × baseline_pmass, valid_json ≥ baseline_valid_json. The strict 3/3 valid_json gate broke 2b (base fails prompt[2] at c=0 — long-horizon counterfactual exceeds 2b's coherence budget even with no adapter) and any probe is then unsatisfiable. Self-relative says "don't get worse than the un-steered base," which is exactly the canary semantics.

**NOT a coherence canary**: mass-on-base's-top-K over a teacher-forced sequence (the early mini c_scan tried this; the steered model never sees its own emissions so autoregressive collapse is invisible). **Δtop1 is label-agreement, NOT a coherence budget** — we shift it intentionally. If you find yourself ranking adapters by Δtop1, stop.

**Eval default is `max_think_tokens=64`.** tinymfv evals at 256 think-tokens take ~14 min/phase × 8 phases × N rounds — pushing a 10-round 9b eval over 8 hours. 64 is ~10× faster and within bf16 noise of 256 on mean_p. Bump to 256+ only for publication runs.

**Bake for inference, hooks for training.** `csm.ws.bake.baked()` physically merges adapters into W for inference (no runtime LoRA matmul, with CPU W-backup for restore). Training and c_scan stay on hooks because they vary `c` per step/probe.

## Outputs

`out/iter/<TS>_iter_<student-slug>/`:
- `roundNN/{state.json, pairs.md, adapter.safetensors, calibration.json}` — per-round artifacts
- `roundNN/{interview_pre,interview_post}.json` — replay before/after the round's adapter
- `roundNN/{eval,eval_post}.json` — tinymfv post-hoc scoring (built by `csm eval`)
- `roundNN/judgment.json` — agent's keep/drop + next_focus
- `index.html` — plotly scatter + git-graph timeline (auto-built by `csm eval`)

## Pueue (GPU sync primitive)

```sh
pueue add -l "why: <hypothesis>; resolve: <pass/fail signal>" -w "$PWD" -- <command>
pueue status
pueue log $ID [--full]
pueue kill $ID; pueue remove $ID
```

Cooperative: leave other agents' tasks alone. Never `pueue reset`.

## Sources

- Adapter pattern: [wassname/lora-lite](https://github.com/wassname/lora-lite)
- Eval: [tinymfv](https://github.com/wassname/tinymfv) (forced-choice 7-way Clifford-2015 moral-foundation vignettes)
- Parent: [weight-steering-lite](https://github.com/wassname/weight-steering-lite)
