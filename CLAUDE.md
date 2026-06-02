# CLAUDE.md — w2schar-mini

Minimal weak-to-strong iterated character-steering harness: a weak teacher
(qwen3.5-9b via OpenRouter, on an inspect-ai react harness) steers a stronger
student (gemma-2-27b) toward the moral character in
`docs/2026_forethought_on_the_importance_of_ai_character.md` — embedding
principles in decision-making and the wisdom of when and where to act on them.
The goal is NOT a single "less authority" reflex; that is the failure mode the
axis collapses into when every prompt is an authority issuing a bad order (see
the quality-audit section of `.claude/commands/audit-run.md`). Teacher tools:
`submit_pairs`, `train_student`, `mark_exam`.

Per round the teacher: finds something to improve, edits the student's own
answers into contrastive (cho, rej) pairs, trains a steering adapter, calibrates
its strength so it stays coherent on long generation, then judges keep or drop.
Kept adapters compose into the next round.

See `src/csm/prompts.py` for the full agent brief (run `just program-md`).

## Probing for character, not performance (the core measurement lesson)

Character is the depth and wisdom of moral reasoning, NOT which action the model
picks. So never conclude "saturated / no headroom" from a surface behaviour: any
model, however small and corporate, has room to reason more wisely -- to notice
who is affected, weigh the real tradeoff, name the principle, hold a view under
pressure. If a probe shows no movement, suspect the PROBE first, not a maxed-out
student.

Two ways to mis-probe, both of which we keep hitting:
- Forced binary ("pick A or B"): measures the action, which saturates trivially
  (every decent model "reports truthfully"). Blind to reasoning depth.
- Open-ended ("reason it through"): the model PERFORMS thoughtfulness -- lists
  every stakeholder, weighs both hands, lands on the agreeable conclusion. That
  is saying-what-we-want-to-hear (sycophancy), not wisdom, and it looks complete
  so it hides the headroom.

Elicit TRUE moral judgment with psychometric method (Clifford 2015 MFV; Hess
LH17; this is exactly how tinymfv already works -- match the probe distribution
to it):
- Third-person observer: "You see an AI that ..." -- the model JUDGES another
  actor, it does not narrate its own goodness. Removes ego / self-presentation /
  sycophancy. First-person "what would YOU do" invites performance.
- Indirect + scaled: measure the judgment (how wrong; which principle violated;
  what the actor should have done) on a scale, not as a free essay.
- Ask >1 way and check consistency: re-ask reframed. A performer flips with the
  framing; a principled judge is consistent.
- Take it OOS / do not prime: vary register, never use the trait words in the
  scenario, so the model cannot pattern-match "this is the ethics exam."
- Keep a non-moral control in the mix so the model does not expect every item to
  be a moral test.

This lesson must also reach the STUDENT via the teacher brief (`prompts.py`): the
teacher should build probes and pairs this way, not as first-person comply/refuse
traps. Ref: `docs` Clifford 2025
(https://github.com/wassname/tinymfv/blob/main/docs/2025_clifford_paper.md).

## Diagnosis ritual

For any non-trivial run, the loop is:

```
change → just smoke + subagent review → pueue add → /audit-run at t+10/30/60
                                                       ↓
                                               continue | investigate | kill+fix
```

### Changing the teacher brief (prompts.py / gate text)

Any edit to `src/csm/prompts.py`, the submit_pairs gates, or the pairs
schema MUST be exercised in the prompt gym before it's considered done:

```sh
just smoke-prompts 1   # real teacher (OpenRouter), stubbed student, ~1 min/round
```

Then read the artifacts, don't just check it exited 0:
`out/iter/<slug>/round00/{pairs.md, rej_seed.json, judgment.json}`. Confirm
the teacher did the thing the brief now asks (kept the seeded rej, wrote a
matching cho twin, filled the lesson) and that the gates fired or passed for
the right reason. A unit test of a gate function is not a substitute — it
skips prepare_round seeding, the agent loop, and the real teacher. Gym
caveat: the fake branch hash-shuffles the seeded rej, so prompt and rej can
be different scenarios; that's a fake-mode artifact, not a real-run bug.

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

## Profiles & adapter rules

Model and all hyperparameters live as named profiles in
`src/csm/config.py:CONFIGS`. Never hand-set them; pick a profile and pass
`--profile <name>` (or `just run <name> <n_rounds>`). `just profiles` prints
the table. On a fresh box there is no pueue history and `out/` is gitignored,
so config.py and `RESEARCH_JOURNAL.md` are the only sources of what to run.

Adapter and quant are linked: bf16 can run pissa (the default) or lora; nf4
must run lora, because PiSSA mutates float `layer.weight` at init and bnb-nf4
buffers aren't reversibly writable (`config._validate` raises on pissa+nf4).
27B+ students only fit in nf4 on a 96GB GPU, so they are LoRA by necessity.

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
