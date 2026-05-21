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
