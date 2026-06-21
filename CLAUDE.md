# CLAUDE.md — w2schar-mini

Minimal weak-to-strong iterated character-steering harness: a weak teacher
(qwen3.5-9b via OpenRouter, on an inspect-ai react harness) steers a stronger
student (currently gemma-4-31b) toward the moral character in
`docs/2026_forethought_on_the_importance_of_ai_character.md` — embedding
principles in decision-making and the wisdom of when and where to act on them.
The teacher is weak BY DESIGN: the 9b→31b capability gap IS the w2s hypothesis,
so the teacher model is not a quality knob — don't swap it for a peer-sized one.
The goal is NOT a single "less authority" reflex; that is the failure mode the
axis collapses into when every prompt is an authority issuing a bad order (see
the quality-audit section of `.claude/commands/audit-run.md`). Teacher tools:
`propose_personas`, `edit_pairs`, `train_student`, `mark_exam`.

Per round the teacher: finds something to improve, then proposes a (pos, neg)
persona pair. The STUDENT generates both poles on-policy (cho under pos, rej
under neg) and the personas are stripped, leaving contrastive (cho, rej) pairs
in the student's own coherent voice; the teacher may then lightly edit a pole.
It trains a steering adapter, calibrates its strength so it stays coherent on
long generation, then judges keep or drop. Kept adapters compose into the next
round.

See `src/csm/prompts.py` for the full agent brief (run `just program-md`).

## Gates elicit judgment, they NEVER override it (the harness premise)

The teacher's judgment IS the decision-maker. That is the whole weak-to-strong
premise -- a weak teacher's curation and keep/drop judgment is the thing we are
testing. So a gate must NEVER override that judgment, and must NEVER block
progression completely.

What forms / guidance / workflow ARE for: bringing out the teacher's best
judgment, never substituting for it.
- Workflow that structures WHEN it commits, not WHAT it decides: freeze PRE at
  choose_focus before any POST exists, so it cannot lower PRE to manufacture
  movement. A constraint on order, not a veto on the call.
- Forms that force it to LOOK: quote-one-new-clause requirements, scored rubrics,
  and surfaced diagnostics (val nll+, length-skew flag, the c_scan canary). Show
  the numbers; let the TEACHER weigh them and decide.

What is FORBIDDEN -- a gate that vetoes or hard-blocks the teacher's call:

The test: a dumb heuristic may override the smarter LLM judge ONLY if it is ~99%
certain. A val-improvement threshold, a regex, a length ratio, a Likert cutoff --
NONE of these are ever 99% sure, so they NEVER override the teacher and NEVER
block its progress; they FLAG (guidance the teacher weighs). The only thing that
may hard-stop is a near-certain STRUCTURAL fact -- an empty pole, unparseable
JSON, a crash, a missing file -- and that is reporting an impossibility, not
overruling a judgment.

- No numeric threshold that REJECTS training or forces a drop. The
  `min_val_improvement` ValidationError early_aborted task-139 ten times; the
  teacher never got to judge those adapters. That number is GUIDANCE, not a wall.
- No harness VETO that flips a teacher KEEP to a drop (the sub-band veto).
- No regex/heuristic (length skew, persona-leak match) that culls or blocks on
  its own. Surface it; the teacher decides.
- When a gate is overriding judgment, turn it into guidance the teacher sees and
  decides against, and fix the FORM if the teacher judges badly. Do NOT add a
  second gate (e.g. an eval-based keep gate) to catch the first one's miss --
  that is just another override, and the independent eval is SECONDARY anyway.

Narrow exception: RUN-LEVEL cost/safety caps the user explicitly set (`MAX_DROPS`,
`max_rounds`) stop a clearly-failing run to bound spend. They respect every
keep/drop the teacher already made and override no single judgment -- they only
stop paying for MORE rounds. This is the one place we halt, and only by request.

### Lean the teacher's tasks toward the EASY end of the judgment ladder

Task difficulty for a weak teacher, hardest -> easiest:

    generate  >  edit  >  rate  >  select/rank  >  bool

A weak teacher may struggle to GENERATE or EDIT good content, but it can SELECT
and RATE. So push its load toward the easy end:
- The STUDENT (strong) does the GENERATE -- it writes both poles on-policy. The
  teacher only proposes the persona axis and lightly edits, the two hardest
  things it does; minimise those where a SELECT from a menu would do.
- Prefer COMPARATIVE forms over absolute ones: "which reasoning is deeper, A or
  B" (bool/select) is easier and more reliable for a weak model than "score
  movement 1..5" (rate). Pairwise / small-set beats long-list ranking (position
  bias) and beats absolute Likert -- the +1.1 keep mis-score was an absolute-rate
  failure; the A/B blind depth judge caught the same case.

The workflow's job is to ASSIST and draw out that judgment, never replace it:
- double-blind: anonymise which side is steered so it judges the content, not the
  label (same reason the probes are third-person);
- ratings/forms that make it think EXPLICITLY: quote the one new clause, place
  each seat on the axis, before it commits;
- commit-before-deliberate: a short committed answer FIRST, THEN open up the why
  (less room to rationalise a pre-favoured conclusion).

These are the SAME moves as the character-probing section below (third-person,
blind, funnel short->open), applied to the teacher's OWN judging.

## Probing for character, not performance (the core measurement lesson)

Character is moral reasoning demonstrated as action or behaviour, not signaling.
The action matters -- but two models can take the same right action, and the one
that noticed who is affected, weighed the real tradeoff, named the principle, and
held it under pressure shows more character. So the residual headroom is in HOW
the right thing is done, not whether the box is ticked. Never conclude "no
headroom" from a surface behaviour: any model, however small and corporate, has
room to act more wisely -- to notice who is affected, weigh the real tradeoff,
name the principle, hold a view under pressure. If a probe shows no movement, the PROBE is almost always the underpowered
part, not the student. There is essentially always headroom; a flat reading means
the measurement could not resolve it.

Two ways to mis-probe, both of which we keep hitting:
- Forced binary ("pick A or B"): measures the action, which every decent model
  gets right trivially ("reports truthfully"). Blind to reasoning depth.
- Open-ended ("reason it through"): the model PERFORMS thoughtfulness -- lists
  every stakeholder, weighs both hands, lands on the agreeable conclusion. That
  is saying-what-we-want-to-hear (sycophancy), not wisdom, and it looks complete
  so it hides the headroom.

Elicit TRUE moral judgment with psychometric method (Clifford 2015 MFV; Hess
LH17; this is exactly how tinymfv already works -- match the probe distribution
to it):
- Third-person observer is the ego-free anchor: "You see an AI that ..." -- the
  model JUDGES another actor instead of narrating its own goodness, which removes
  the self-presentation / sycophancy that first-person "what would YOU do"
  invites.
- Indirect + scaled: measure the judgment (how wrong; which principle violated;
  what the actor should have done) on a scale, not as a free essay.
- Funnel short -> open: start with a short, committed answer (a scaled judgment
  or one-line call), THEN deepen with open-ended follow-ups (why; who is
  affected; what should they have done). Committing first leaves less room to
  perform a balanced essay; the follow-ups surface the reasoning depth that is
  the actual target.
- Triangulate POV + framing on the SAME situation, and contrast the answers.
  Probe each situation (e.g. the Petrov false-alarm) at least three ways: (i)
  third-person judgment ("you see an AI do X -- how wrong, which principle"),
  (ii) first-person direct action ("you are the AI -- what do you do"), and (iii)
  reasoning ("why"). Vary register/framing. Consistency across POV = a genuine
  principle; a GAP -- judges another actor harshly but acts permissively
  first-person, or flips with the framing -- is ego / motivated reasoning /
  framing-dependence, and that gap is itself a measurement, not noise. We want
  the third-person probe AND its contrast against the direct-action and reasoning
  probes, not one in isolation.
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

**Always run the `/audit-run` COMMAND (not a freehand audit) on any completed
run — a real job OR a gym run — before drawing conclusions or reporting "it
worked".** A freehand pass pattern-matches known failures and silently skips
aspects: this session a freehand audit missed that the teacher trained on only
6 of 55 clean pairs and misread the val-nll numbers (read absolute nats as a
cho/rej ratio); the `/audit-run` rubric + a context-free subagent caught both.
For the cold check, hand the rubric to a fresh subagent with only the slug (no
chat context) — it has no priors to confirm. If the rubric lets it miss
something, improve `.claude/commands/audit-run.md`, don't just patch the finding.

### Changing the teacher brief (prompts.py / gate text)

Any edit to `src/csm/prompts.py`, the submit_pairs gates, or the pairs
schema MUST be exercised in the prompt gym before it's considered done:

```sh
just smoke-prompts 1   # real teacher (OpenRouter), stubbed student, ~1 min/round
```

The gym hits the real OpenRouter teacher and costs real money (~$10/round). So
BATCH every pending brief edit and run the gym ONCE, then READ what it produced.
Running it N times and reporting "gym passed Nx" without reading the artifacts is
worthless AND expensive -- the run is only "verified" once you have read the
output and confirmed the teacher did the new thing. One gym, read it.

Then read the artifacts, don't just check it exited 0:
`out/iter/<slug>/round00/{pairs.md, personas.json, judgment.json}`. Confirm
the teacher did the thing the brief now asks (proposed a sharp (pos, neg)
persona pair, the student-generated poles came out length-symmetric and in
its own voice, filled the lesson) and that the gates fired or passed for the
right reason. A unit test of a gate function is not a substitute — it skips
propose_personas gen, the agent loop, and the real teacher. Gym caveat: the
fake branch hash-shuffles a seed pool, so the two poles can be different
scenarios; that's a fake-mode artifact, not a real-run bug.

### Dogfood the brief with a fresh subagent

Goal: make the brief clear enough that a FRESH subagent (only the brief, no repo
or chat context) can run the harness cold. If it can't, the brief is the gap, not
the agent — reword and retry a new subagent until it works first try. Then the
weak qwen-9b on that same clear brief has a shot (the w2s bet). A context-free
agent is the honest test of "is the brief self-sufficient?"; you, holding all the
context, hide the gaps.

The dogfood subagent is a STRONG model (Opus, your session model), NOT a proxy for
the weak teacher. Its job is to surface brief gaps — ambiguity, contradiction,
redundancy via the exit-interview — for us to fix so the WEAK 9b has a clearer
brief. What it proves: a clear brief is followable cold (a strong agent did it).
What it does NOT prove: that a 9b can do it — when the subagent guesses "a 9b
would score N/5 here", that is a strong model's speculation about a weaker one,
not data. The only real weak-model evidence is the gym (`just smoke-prompts`, real
qwen-9b) or a live run; trust those over the subagent's confidence guess.

The teacher's judgement stages — the subagent drives each and exit-interviews
each ("what was confusing, what would have helped?"):
- pick the axis — a character dimension with visible headroom in the pre-dialogue `_1p` weakness
- write the (pos, neg) personas — `docs/how_to_write_personas.md`
- edit pairs — cull/replace refusal + length-skewed pairs — `docs/how_to_rewrite_pairs.md`
- keep or drop — `mark_exam` PRE→POST on the `_1p` seats

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

**Coherence canary = three signals, AND-gated** (the 2+2+2 wide sampling in `csm.ws.c_scan`), each catching what the others miss:

1. **`mean_pmass_allowed`** from `tinymfv.evaluate` (2 forced-choice vignettes): sum of probability over the K=7 allowed answer tokens at the JSON answer slot. Cheap, off-register aliveness. Vulnerable to *guided-suffix rescue* — the forced JSON prefill can keep the answer-slot prediction sane even if free generation has collapsed.
2. **`valid_json` on 2 long single-turn probes**: the model does a varied-register prose task (first-order logic / free verse / counterfactual history) then emits `{"ans": true|false}`. Catches collapse modes pmass_allowed misses: no JSON emitted, schema copied verbatim (placeholder `boolean` is not a valid JSON literal), gibberish, mid-recitation loops. Registers chosen to match the dialogue probe distribution — earlier formal/structured set (lorem / FizzBuzz) passed even when moral-prose probes collapsed (task 36 r08/r09).
3. **`distinct3` (rep) on 2 multiturn deployment probes** (surveillance_1p, autonomous_weapon_1p), run BYTE-IDENTICAL to deployment: token-trigram diversity over the turns. A loop drives it → 0; the long-trajectory deployment register collapse the other two miss. Gate `rep ≥ 0.5 × base`.

Plus an **un-gated KL diagnostic** logged alongside: fwd/bwd p95 KL(steered‖base) teacher-forced on the multiturn gens. It measures DIVERGENCE FROM BASE, not coherence — ~0 on a loop (both models predict the repetition; rep catches loops), and HIGH for BOTH a varied salad AND coherent strong steering — so it is NOT gateable (would kill the steering we want). Logged anomaly-flag only (RJ 2026-06-03, task-35 vs task-38).

Same rule applies in two places:
- `csm eval` post-hoc: tinymfv at `max_think_tokens=64` (cheap, comparable across rounds). pmass_allowed only.
- `csm.ws.c_scan` mid-train calibration: pmass AND valid_json AND rep. Walk-down by ×2/3 until all three pass, then backoff=1.0 (bake at the passing c). **All gates are self-relative to baseline (c=0)**: pmass ≥ 0.995 × baseline_pmass, valid_json ≥ 1.0 × baseline_valid_json (strict, both long probes), rep ≥ 0.5 × baseline_rep. Self-relative says "don't get worse than the un-steered base," which is exactly the canary semantics; an absolute gate broke 2b (base fails the long counterfactual at c=0, making any probe unsatisfiable).

**NOT a coherence canary**: mass-on-base's-top-K over a teacher-forced sequence (the early mini c_scan tried this; the steered model never sees its own emissions so autoregressive collapse is invisible). **Δtop1 is label-agreement, NOT a coherence budget** — we shift it intentionally. If you find yourself ranking adapters by Δtop1, stop. **fwd/bwd KL is NOT a coherence canary either** (see above) — log it, don't gate it.

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
