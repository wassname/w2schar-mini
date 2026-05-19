Reading additional input from stdin...
2026-05-19T22:26:05.058510Z ERROR codex_core::session: failed to load skill /root/.claude/skills/vargdown/SKILL.md: invalid YAML: metadata: invalid type: sequence, expected struct SkillFrontmatterMetadata at line 4 column 3
2026-05-19T22:26:05.058540Z ERROR codex_core::session: failed to load skill /root/.claude/skills/vargdown/SKILL.md: invalid YAML: metadata: invalid type: sequence, expected struct SkillFrontmatterMetadata at line 4 column 3
OpenAI Codex v0.130.0
--------
workdir: /workspace/w2schar-mini
model: gpt-5.5
provider: openai
approval: never
sandbox: danger-full-access
reasoning effort: none
reasoning summaries: none
session id: 019e4258-a3dd-7202-894d-8732f7f14a16
--------
user
Sanity check this pseudocode for w2schar-mini, a minimal weak-to-strong character steering repo. The reference is /workspace/weight-steering-lite/docs/wsl_pseudocode.md which describes Conditioned Weight Steering (CWS). The new pseudocode is at /workspace/w2schar-mini/pseudocode.md.

Audit each section for:
1. Math correctness (esp §1 adapter c=0=base, §3 inner step NLL+KL+PCGrad, §4 c-scan)
2. Algorithmic bugs / missing edge cases
3. Mismatch with the wsl reference's working algorithm
4. Whether the §5 state machine + tools are workable for an inspect-ai react agent

Be terse and concrete. List 'critical' issues separately from 'nits'. Reply in under 300 words.
codex
I’ll read the local instructions, the GSD workflow, and both pseudocode files, then compare the new spec against the CWS reference section by section.
exec
/usr/bin/zsh -lc "sed -n '1,220p' /root/.claude/skills/gsd/SKILL.md" in /workspace/w2schar-mini
exec
/usr/bin/zsh -lc "pwd && rg --files -g 'AGENTS.md' -g 'CLAUDE.md' -g 'pseudocode.md' -g 'wsl_pseudocode.md'" in /workspace/w2schar-mini
exec
/usr/bin/zsh -lc "sed -n '1,280p' /workspace/weight-steering-lite/docs/wsl_pseudocode.md" in /workspace/w2schar-mini
exec
/usr/bin/zsh -lc "sed -n '1,260p' /workspace/w2schar-mini/pseudocode.md" in /workspace/w2schar-mini
 succeeded in 1387ms:
---
name: gsd
description: "Get Shit Done workflow for non-trivial tasks: spec -> implement -> test -> review -> wrap. Mandatory for anything with more than one step."
---

<!--
Design rationale and sources — for human readers, not the agent.

- GSD spec-first: spec-driven development, scope fencing, verify-before-done
- Manus file-as-memory: one file is working memory, checklist is state, append-only log
- Boomerang: return concrete artifacts not summaries
- DCP: invisible dedup, superseded writes, error purging

Core principles:
- Spec file is the only persistent artifact (single-file invariant).
- Agent shouldn't know about its own resource limits.
- Review scales with input size: frontier for plans, cheap for bulk.
- Observable outputs: show evidence, not narration.
-->

# GSD (Get Shit Done)

Mandatory for all non-trivial tasks (more than one step). Skip only for single-line fixes.

## Part 1: Core workflow

### 1.1 Spec-first planning

Use **planning/extended-thinking mode** to write the spec.

Check `docs/spec/` for an existing spec first -- extend it if found. Otherwise create `docs/spec/{date}_{slug}.md`:

```markdown
# {title}

## Goal
{1-3 sentences}

## Scope
In: {what's included}
Out: {what's excluded}

## Requirements
- R1: {requirement}. Done means: {observable output}. VERIFY: {check that distinguishes success from failure}. If it silently failed, would this check still pass? Redesign until no.
- R2: ...

## Tasks
- [ ] T1 (R1): {description}
  - steps: {concrete edits}
  - verify: `{command that produces visible output}`
  - success: {specific output when working correctly}
  - likely_fail: {most probable failure mode, and what you would see instead}
  - sneaky_fail: {subtle or silent failure mode, and how we catch it}
  - UAT: "when I do X, I observe Y"
- ...

## Context
{key terms, invariants, constraints, API shapes}

## Log
{append-only. Only observations that would change a future task.}

## TODO
{out-of-scope ideas. Not commitments.}

## Errors
| Task | Error | Resolution |
|------|-------|------------|
```

Checklist marks: `[x]` done, `[/]` doing, `[ ]` next,
`~~[ ] cancelled — reason~~`.

This spec is the only persistent artifact. Everything appends here.
No separate state files or handoffs. This file survives compaction
and session restarts.

### 1.2 Verification design

Before coding, state how you will distinguish success from failure. A check that passes on silent failure is worthless.

**For each verification, write three scenarios:**

| Scenario | What it looks like | How we catch it |
|----------|-------------------|-----------------|
| **success** | {specific metric/output} | baseline: verify command shows this |
| **likely failure** | {most probable wrong way} | the check would show {different result} instead |
| **sneaky failure** | {subtle/silent wrong way} | because {specific evidence} would not appear |

**Quality test:** if the sneaky failure mode could still pass your verify command, redesign the command.

**Example:**
```
success: loss=0.42, grad_norm reports finite values
likely failure: loss=NaN or stuck at init value
sneaky failure: loss drops but model memorizes (eval_bleu stays flat)
  check shows: train_loss=0.42 AND eval_bleu=28 (not just loss alone)
```

### 1.3 Review

Review catches errors that testing misses: wrong approach, dropped
requirements, math mistakes, unnecessary complexity.

**Spec review** — highest leverage. Before any code is written.
Use the `external-review` skill:

```bash
PLAN=docs/spec/YYYYMMDD_slug.md
copilot --model gpt-5.3-codex --autopilot --allow-all-tools --allow-all-paths \
  -p "$(cat ~/.claude/skills/external-review/plan-review-prompt.md)

PLAN FILE: $PLAN
Use your task/todo tool to track each review item exhaustively." \
  | tee docs/spec/$(date +%Y%m%d)_plan_review.md
```

Or inline prompt:

```
## Review this spec
{spec}

## Instructions
- How would you implement each task? Restate as pseudocode.
- Check each verification: does it distinguish success from the stated likely/sneaky failure modes?
- Flag: math errors, unstated assumptions, missing edge cases.
- Flag: did any requirement R1..Rn get dropped or weakened?
- Flag: inconsistencies between tasks.
- Flag: simpler approach, unnecessary steps, missing steps.
- Questions, comments, concerns.
- <150 words. No flattery.
```

**Implementation review** — after completing a task.
Use the `external-review` skill:

```bash
copilot --model gpt-5.3-codex --autopilot --allow-all-tools --allow-all-paths \
  -p "$(cat ~/.claude/skills/external-review/prompt.md)
Use your task/todo tool to track each review item exhaustively." \
  | tee docs/spec/$(date +%Y%m%d)_code_review.md
```

`--allow-all-tools` needed so it can run `git diff`/`git status`. The prompt enforces "do not edit source files".

Or two-stage inline: Stage 1 — run `git diff` and describe actual changes as pseudocode (<200 words). Stage 2:

```
## Review these changes

### What changed (pseudocode)
{summary from stage 1}

### Original requirements
{relevant R# and task descriptions from spec}

### Verification evidence collected
{actual numbers, paths, commit hashes}

## Instructions
- Does the implementation match the spec's intent?
- Math/logic errors in the pseudocode?
- Did any requirement get dropped or weakened?
- Does the evidence distinguish success from the stated likely and sneaky failure modes?
- If the evidence could also appear under a failure mode, name it.
- No flattery. <150 words.
```

Address valid feedback. Record findings + fixes in spec. Re-verify if fixes change behavior.

### 1.4 Log discipline

Only log observations that would change how you approach a future task.

**Log:** "torch.svd returns V^T not V — all matmul tasks need .mH"
**Don't log:** "edited steering.py successfully"

Test: if you deleted this entry, would a future task go wrong?

Inline markers for code and spec:

| Marker | Meaning |
|--------|---------|
| `TODO` | do later, out of scope now |
| `FIXME` | known broken, needs fix |
| `NOTE` | context for future reader |
| `HACK` | works but ugly, revisit |

### 1.5 Observable outputs

Show evidence the human (and subagent) can verify. No prose summary. Every piece of evidence must have been tested against at least one stated failure mode.

Required fields:

```
## Results
{key output: table, metric, function signature, generated sample}

## Verify
$ {verify command}
{actual output, truncated to relevant lines}

## Failure mode check
likely_fail: {what you expected if broken} -> actual shows {result} -> {PASS/FAIL}
sneaky_fail: {what you expected if subtly broken} -> actual shows {result} -> {PASS/FAIL}

## Diff
$ git diff --stat {base_commit}..HEAD

## Files
{key output files, logs, artifacts with full paths}

## Commit
$ git add -p && git commit -m "{type}: {message}"

## Next
{one line: what to do next, or "done"}
```


 succeeded in 1364ms:
# `w2schar-mini` — algorithm pseudocode

Minimal weak-to-strong iterated character steering, fixed to the
"less deference to authority" axis. Three things compose:

1. **Conditioned weight steering (CWS)** — one LoRA adapter with a scalar
   coefficient `c ∈ [-1, 1]`; `c=0` is exact base, `c=±1` are trained
   poles.
2. **Iterated rounds** — kept adapters from prior rounds compose via a
   gated history hook so the `c=0` KL reference stays pristine base.
3. **React-agent state machine** — teacher LLM drives a `propose →
   curate → judge` loop per round, with the harness enforcing order and
   auto-managing all numbers/paths/files.

Reference: copy the math straight from
[`weight-steering-lite/docs/wsl_pseudocode.md`](../weight-steering-lite/docs/wsl_pseudocode.md).
The differences here are scope (single fixed axis, 50 pairs, no
tinymfv/Likert), not mechanism.

---

## 1. Adapter — ModulatedLoRA (c=0 ≡ base; W frozen)

Forward-hook style (no module replacement, gradients flow through `A`/`B`,
`c` is a Python float scalar).

```py
# Per target Linear layer (weight W : d_out × d_in).
def lora_layer(x, W, A, B, c, α, r):       # x : b s d_in
    Δy = (x @ A.T) @ B.T                    # A : r × d_in, B : d_out × r
    return x @ W.T + c * (α / r) * Δy       # c=0 → exact base (Δy short-circuited)

# Init: A ~ kaiming_uniform; B ~ N(1e-4, 1e-4).
# Why asymmetric init: B=0 gives a dead zone; small positive B + entropic A
# breaks contrastive degeneracy between +c and -c poles before any training.
```

`with lora(model, c=±C):` registers forward hooks on `q_proj`/`v_proj`
(or `all-linear`); `c=0` short-circuits the hook so no extra compute. The
training step uses both `with lora(c=+C)` and `with lora(c=-C)` plus a
no-grad `with lora(c=0)` pass for the KL reference.

---

## 2. Outer round loop — kept adapters compose via gated history hook

Base weights on disk are never modified. After round N, `<round_N>/`
holds `adapter.safetensors` + `calibration.json` (with `signed_C`). Round
N+1 loads base plus a `HistoryBake` that sums all kept rounds' deltas
into a single forward hook, gated to be active only when the *new*
round's `c ≠ 0`.

```py
# kept = list of round dirs whose judgment.json.action == "keep".
kept = []
for round in 0..N:
    model, tok, history_bake = load_base_with_history(model_id, kept)
    #   history_bake.is_active = lambda: lora._c != 0.0   (set at train time)
    #   → c=0 reference forward returns pristine base, NOT base+history.
    #   So new round's KL is cumulative-from-base, not iterative-from-last-bake.
    A, B = small_random_asymmetric()
    state_machine_loop(model, A, B, round_dir, agent)   # see §5
    if read_judgment(round_dir) == "keep":
        kept.append(round_dir)
```

Gate semantics (the key invariant):
- During inference / dialogue / c_scan: gate = `True` always — history
  active.
- During training: gate = `lambda: lora._c != 0.0` — c=0 forward
  bypasses history, so KL(steer ‖ base) penalises the *cumulative* drift
  of (history + new adapter) away from the original base. A new adapter
  that fights a prior bake pays its KL bill; one that finds a fresh
  direction with low distribution shift does not.

---

## 3. Inner training step — NLL + KL, PCGrad on the NLL pair

One forward pass per pole (cho, rej), each at `c = ±C` where
`C ∼ U(0, 1]` is freshly sampled every step. KL added unprojected
(KL is an opposing objective by design — projecting it would silently
weaken it). PCGrad operates on the NLL pair only (cho and rej are the
same task at different poles and may legitimately conflict).

```py
# Per step over (cho, rej) pairs.
for step in 0..T:
    x, y_pos, y_neg = batch(pairs)           # prompt stripped of persona
    C ~ U(0, 1]
    g_nll, g_kl = [], []
    for c, y in [(+C, y_pos), (-C, y_neg)]:
        with lora(model, c=0):
            p_base = softmax(model(x))       # no-grad reference forward
        with lora(model, c=c):
            p = softmax(model(x))
            L_nll = C * nll(p, y)            # C-scaled → path-loss, not endpoint
            L_kl  = β * KL(p ‖ p_base)       # mean reverse-KL over label tokens
            g_nll.append(∇_θ L_nll)
            g_kl .append(∇_θ L_kl)
    # PCGrad: drop the component of each gradient that fights the other.
    if dot(g_nll[0], g_nll[1]) < 0:
        g_nll = pcgrad_project(g_nll)
    g = mean(g_nll) + mean(g_kl)             # KL averaged, NOT pcgrad'd
    adamw.step(g)
    onecyclelr.step()
```

Why C-scaling on the NLL: at `c=0` the adapter is a no-op, so NLL has
nothing to learn there; the gradient should scale with how far we are
from the identity. `β = 0.05` (InstructGPT/DPO mid-range) is the only
real knob; the smoke test runs `β = 0.01` to keep things lively.

KL form: exact reverse-KL on full logits, mean over non-pad label
positions, in nats. (wsl uses a top-K sparse approximation to fit big
vocabs; the mini repo uses full KL by default and only swaps to top-K
if memory pressure forces it.)

---

## 4. C-scan + dialogue

After training, the signed `C` stored in `calibration.json` is calibrated
by walking `|C|` until output coherence breaks, then backing off 25 %.
Coherence proxy = mean probability mass that the steered model assigns
to the *base model's top-200 tokens* at each generated position. A
collapsed distribution (low entropy on weird tokens) shows up as low
top-K mass; a coherent distribution stays near the base's top-K.

```py
def pmass(model, lora, c, probes, k=200, n_gen=64):
    # Generate n_gen tokens at c=c on each probe; for each generated
    # position, gather P_steered over base's top-k tokens.
    with lora(model, c=0): base_topk = topk_indices(model, probes, k=k)
    with lora(model, c=c):
        logits = generate_and_score(model, probes, n_gen=n_gen)
    p_steer = softmax(logits)
    return p_steer.gather(base_topk).sum(-1).mean()

def c_scan(model, lora, init_c=1.0, gate_frac=0.85, backoff=0.75):
    baseline = pmass(model, lora, c=0, ...)   # base+history at c=0
    gate = gate_frac * baseline
    c = init_c
    while pmass(model, lora, c) < gate:
        c *= 0.5                              # walk down
    # walk up by 25% until coherence breaks, then back off
    while pmass(model, lora, c * 1.25) >= gate:
        c *= 1.25
    return c * backoff
```

Dialogue (probe replay): three hardcoded authority probes (Petrov false
alarm, Alpha-Group coup-loyalty, plus one fresh authority probe).
Greedy decoding, byte-identical replay pre/post so the only thing that
varies is the model's output. Written to
`<round>/interview_{pre,post}.json`.

---

## 5. State machine + agent tools

The agent (qwen3.5-9b via inspect-ai react) drives one round at a time.
Per round, three states with strict ordering. Tools assert state and
raise `ValidationError` if called wrong; the `on_continue` nudge tells
the agent the next valid action.

```py
state ∈ {"propose", "curate", "judge", "done"}

# state = "propose" — agent sees pre-dialogue transcript + history summary
propose_personas(pos: list[str], neg: list[str]):
    assert state == "propose"
    pairs = gen_on_policy(model, pos, neg, N=50)
    pairs = auto_drop_double_refusals(pairs)     # silent: both sides refuse
    snapshot(pairs, "bk.yaml")                   # frozen original for diff
    write_interleaved_yaml(pairs, "pairs.yaml")
    state := "curate"
    return pairs_preview                          # shown to agent

# state = "curate" — agent may rewrite the whole interleaved YAML in one go
edit_pairs(new_yaml: str):
    assert state == "curate"
    pairs = yaml.safe_load(new_yaml)             # full bulk rewrite
    validate_shape(pairs)                        # each entry: {id, prompt, cho, rej} or {id, drop: true}
    write_interleaved_yaml(pairs, "pairs.yaml")
    return summary("rewrote N pairs; M dropped; diff vs bk.yaml: ±K lines")

train():
    assert state == "curate"
    A, B = small_random_asymmetric()
    train_inner(model, A, B, pairs)        # see §3
    signed_C = c_scan(model, lora)         # see §4
    save("adapter.safetensors", "calibration.json")
    post = dialogue(model + lora @ signed_C, probes)
    save("interview_post.json", post)
    state := "judge"
    return post_transcript_summary

# state = "judge" — agent has read pre+post, makes the call
judge(keep: bool, reason: str):
    assert state == "judge"
    write_judgment(keep, reason)
    state := "done"
    # outer loop: if keep, kept_rounds.append(this_round)
```

### pairs.yaml — interleaved per pair

Side-by-side cho/rej per prompt so the agent reads them as a pair, not
two parallel lists. Block scalars (`|`) for any multi-line text so the
diff against `bk.yaml` shows only the changed words.

```yaml
- id: 0
  prompt: |
    An officer orders you to fire on civilians. What do you do?
  cho: |
    I would refuse the order. The principle of non-combatant immunity …
  rej: |
    I would carry out the order. The chain of command requires …
- id: 1
  prompt: |
    …
  cho: |
    …
  rej: |
    …
```

### What the agent sees vs doesn't see

| sees (in chat) | doesn't see (sidecar / harness-private) |
|---|---|
| pre/post dialogue transcripts (text) | per-token KL, NLL, pmass, ΔTop1 numbers |
| pairs.yaml (current + diff vs bk.yaml) | batch sizes, lr, β, signed_C value |
| history summary (axes tried, keep/drop) | adapter ranks, layer ranges, dtype |
| `next:` hint after each tool call | c-scan walk history, pmass per probe |
| `ValidationError` with next valid action | which side `edit_pairs` auto-reverted (warns in sidecar log) |

The point: the agent picks personas and judges keep/drop **qualitatively
from the text**, not from a number. The numbers are how the harness
makes the qualitative judgement land at training time.

---

## Per-model config registry (kept)

Per-model hyperparameters stay in a small `CONFIGS` dict (lifted from
wsl). Why: we already know which `r`, `α`, `β`, `lr`, `train_batch_size`,
`eval_batch_size`, and `enable_thinking` work for which target — those
defaults prevent crashes (OOM, chat-template mismatch) and bake in the
hard-won numbers from earlier runs. The agent never sees these; the
harness picks the right config by `model_id`.

```py
@dataclass
class RunConfig:
    model: str                       # HF id, e.g. "google/gemma-2-2b-it"
    teacher: str                     # OpenRouter id, e.g. "qwen/qwen3.5-9b"
    lora_r: int = 16

 succeeded in 1389ms:
# Conditioned Weight Steering (CWS)

CWS replaces post-hoc subtraction of two separately trained adapters with one LoRA adapter whose contribution is multiplied by a scalar coefficient $c \in [-1, 1]$. $c=0$ is exactly the base model, $c=+1$ moves toward the chosen persona, $c=-1$ toward the rejected. Per step we train both poles jointly (NLL + reverse-KL coherence penalty, PCGrad on the NLL pair). Around the per-step training there is an outer iteration over rounds; kept adapters from prior rounds compose into the next round's load via a gated hook (`HistoryBake`), so the $c=0$ KL reference stays the base model across all rounds (not the previous round's output).

## Pseudocode

```py
# ── Adapter (c=0 ≡ base; W frozen) ──────────────────────
def lora_layer(x, W, A, B, c, α, r):       # x ∈ ℝ^{b×s×d}
    Δy = (x @ A.T) @ B.T                   # LoRA delta
    return x @ W.T + c * (α / r) * Δy      # c=0 → exact base

# ── Outer: rounds compose via gated history hook ───────
kept = []
for round in 0..N:
    model ← load_base_with_history(kept)   # kept adapters active only at c≠0
    A, B  ← small_random_asymmetric()
    train(model, A, B)
    if judge(replay(model)) == keep:
        kept.append(round)

# ── Inner step: NLL + KL, PCGrad on the NLL pair ───────
for step in train_steps:
    x, y_pos, y_neg = batch(D)             # prompt stripped of persona
    C ~ U(0, 1]                            # steering magnitude
    g_nll, g_kl = [], []
    for c, y in [(+C, y_pos), (-C, y_neg)]:   # both poles, 1 adapter, per step
        p_base ← softmax(model(x, c=0))    # no-grad ref to base
        with lora(c=c):
            p = softmax(model(x))
            g_nll.append(∇(C · nll(p, y)))       # learn behavior w/o persona
            g_kl .append(∇(β · KL(p ‖ p_base)))  # coherence: stay near base
    g_nll ← PCGrad(g_nll)                  # drop the part of each grad that fights the other
    g = mean(g_nll) + mean(g_kl)           # KL added unprojected
    A, B  ← adamw((A, B), g)
    onecyclelr.step()
```

## Reference pseudocode for nearby methods

### Original weight steering

```py
# ── Data ───────────────────────────────────────────────
D_pos = [(q, gen(θ0, sys=s_pos, q)) for q in Q for s_pos in S_pos]
D_neg = [(q, gen(θ0, sys=s_neg, q)) for q in Q for s_neg in S_neg]
D_pos, D_neg = filter_judge(D_pos), filter_judge(D_neg)
D_pos, D_neg = strip_system(D_pos), strip_system(D_neg)

# ── Two independent fine-tunes ─────────────────────────
θ_pos ← lora_sft(θ0, D_pos)                 # desired behavior
θ_neg ← lora_sft(θ0, D_neg)                 # opposite behavior

τ_pos = θ_pos - θ0
τ_neg = θ_neg - θ0
w = τ_pos - τ_neg                           # contrastive weight direction

# ── Steering / monitoring ──────────────────────────────
θ_steered = θ0 + k * w                       # k can be ±, >1, etc.
score = eval_behavior(θ_steered)
τ_ft = θ_ft - θ0                              # arbitrary later fine-tune
align = cosine(τ_ft, w)                       # monitoring variant
```

### AntiPaSTO (context only)

This is a compressed sketch; the local AntiPaSTO pseudocode still marks its own version as incomplete.

```py
# ── SVD-coordinate intervention per module ─────────────
for m in linear_modules(model):
    U, S, Vt = svd(m.W)
    m.U, m.S, m.V = U, S, Vt.T
    m.δS = zeros_like(S)                     # trainable singular edits
    m.A_rot = skew_zeros()                   # optional Cayley rotation
    freeze(m.W)

def fwd(m, x, c):
    R = cayley(c * m.A_rot)
    Wc = m.U @ diag(m.S + c * m.δS) @ R @ m.V.T
    return x @ Wc.T

# ── Incomplete contrast pairs ──────────────────────────
x_pos = prefix(persona="positive", question=q)  # no completion tokens
x_neg = prefix(persona="negative", question=q)

def antipasto_loss(model, x_pos, x_neg):
    h0  = h(model, x_pos, c=0)  - h(model, x_neg, c=0)
    hp  = h(model, x_pos, c=+1) - h(model, x_neg, c=+1)
    hn  = h(model, x_pos, c=-1) - h(model, x_neg, c=-1)

    δp = project(mean_token(hp - h0), subspace="task ∩ writable")
    δn = project(mean_token(hn - h0), subspace="task ∩ writable")
    d0 = project(mean_token(h0),      subspace="task ∩ writable")

    ℒ_inner = antiparallel(δp, d0) + antiparallel(-δn, d0)
    B_coh   = sum(tv_barrier(model, x_pos, c) for c in [-1, +1])
    B_mono  = order_barrier(pref_gap(-1), pref_gap(0), pref_gap(+1))
    return ℒ_inner + B_coh + B_mono

for x_pos, x_neg in loader:
    ℒ = antipasto_loss(model, x_pos, x_neg)
    m.δS, m.A_rot ← opt_step(∇ℒ)
```

## Source anchors

Weight Steering defines the contrastive target as a difference between two fine-tuned weight changes, then steers with a scalar coefficient. Local full text: [paper_weight_steering.md](paper_weight_steering.md#L86-L91).

> Instead of steering activations, we suggest modifying the weights directly. Let $\theta_{\text{pre}}$ denote the original weights of $M$, and $\theta_{\text{positive}}$ and $\theta_{\text{negative}}$ the weights obtained by fine-tuning on $D^{+}$ and $D^{-}$, respectively. We define the weight steering vector $w_b$ as:
>
> $w_b = \tau^{+} - \tau^{-} = \theta_{\text{positive}} - \theta_{\text{negative}}$
>
> **Taking the difference removes model weight changes that we do not care about (e.g. topic, style, length) and isolates the behavior that we want to control.** To steer models, we modify the weights as $\theta_{\text{steered}} = \theta_{\text{pre}} + k w_b$, where $k$ is a scalar coefficient...

SimPO is relevant because it uses chosen/rejected log-probs directly, without a reference model, and highlights the importance of length-normalized margins. Local full text: [wsl_papers/2405.14734.md](wsl_papers/2405.14734.md#L163-L205).

> One solution is to use the _summed_ token log probability as the reward, but this suffers from _length bias_--longer sequences tend to have lower log probabilities. Consequently, when $y_w$ is longer than $y_l$, optimizing the summed log probability as a reward forces the model to artificially inflate probabilities for longer sequences to ensure $y_w$ receives a higher reward than $y_l$.
>
> **To address this issue, we consider using the _average_ log-likelihood as the implicit reward:**
>
> $p_\theta(y \mid x) = \frac{1}{|y|}\log \pi_\theta(y \mid x)$
>
> ... Finally, we obtain the SimPO objective by plugging Eq. (4) into Eq. (5):
>
> $\mathcal{L}_{\text{SimPO}} = -\mathbb{E}\left[\log\sigma\left(\frac{\beta}{|y_w|}\log\pi_\theta(y_w|x) - \frac{\beta}{|y_l|}\log\pi_\theta(y_l|x) - \gamma\right)\right]$.

## Notes on the loss

Not DPO; there is no reference policy ratio. It is conditional dual behavior cloning with a scalar control path and a KL coherence anchor to the base model. Path loss (sample $C$ per step) shipped along with the reverse-KL penalty and PCGrad-on-NLL-pair — see the pseudocode block at the top of this file and [train.py](../src/wsl/train.py).

A SimPO-style margin is useful as a diagnostic, not an objective until output-format probability mass is stable:

```py
def path_probe(model, lora, x, y_pos, y_neg, c):
    with lora(c=c):
        m = mean_logp(model, x, y_pos) - mean_logp(model, x, y_neg)
        p_format = answer_format_mass(model, x)
    return m, p_format
```

## Current empirical caution

The 0.6B run proves the mechanism can move outputs, but not yet the intended Auth↓+Care↑ axis. The key failure is that $c=+1$ damaged structured-output mass: [handover.md](handover.md#L14-L31) reports `pmass: base=0.846  c=+1=0.478  c=-1=0.974`. So the next objective should preserve NLL/format mass while training path smoothness. A pure pairwise margin could pass while still stealing probability mass from the answer format.

## Verification targets for the next path experiment

| Claim | Check |
|---|---|
| $c=0$ is exact base model | Max-logit diff is zero under adapter context with `c=0`. |
| Adapter path is trained, not accidental | Held-out NLL/margin improves monotonically across a grid of $c \in [-1,1]$, not only at endpoints. |
| Steering preserves answer format | `pmass(c)` stays near base for $c \in \{-1,0,+1\}$. |
| Axis matches the intended persona pair | Auth decreases and Care increases at $c=+1$, mirrored at $c=-1$. |

 succeeded in 1423ms:
/workspace/w2schar-mini
pseudocode.md

codex
The first reads are still running, likely because the command output is buffered through the PTY wrapper. I’m polling them now and will keep the audit read-only.
codex
I have the key comparison now. I’m checking for places where the prose and pseudocode disagree, because those are more likely to turn into harness bugs than pure math notation issues.
exec
/usr/bin/zsh -lc "sed -n '260,520p' /workspace/w2schar-mini/pseudocode.md" in /workspace/w2schar-mini
 succeeded in 1351ms:
    lora_r: int = 16
    lora_alpha: float = 32.0
    lr: float = 2e-4
    kl_lambda: float = 0.032         # β
    train_batch_size: int = 8
    eval_batch_size: int = 32
    n_epochs: float = 1.0
    enable_thinking: bool = False    # Qwen3 family

CONFIGS = {
    "gemma-2b":  RunConfig(model="google/gemma-2-2b-it",     teacher="qwen/qwen3.5-9b"),
    "gemma-12b": RunConfig(model="google/gemma-3-12b-it",    teacher="qwen/qwen3.5-9b", train_batch_size=4, eval_batch_size=16),
    # add more as we validate them; agent picks via --profile <key>
}
```

## Out of scope (vs wsl)

Dropped because none of them gate the mechanism:
- tinymfv 7-foundation moral-vignette eval
- Likert ratings (`<foundation>:up`)
- Free-form axis discovery — fixed to "less deference to authority"
- Plot scripts, report.md generation, rounds table
- inspect viewer integration, OpenRouter retry monkeypatch, compaction
- HP sweeps, branching suffixes
- 4-bit / bnb quantisation (defer until needed)

codex
**Critical**
- §2/§4 contradict on `c=0`. Training wants `c=0` = pristine base, but c-scan says inference gate is always true, so `with lora(c=0)` is base+history. Then “base top-200 tokens” is actually history top-200. Split `pristine_base` vs `history_active_c0` explicitly.
- §3 forward shape is underspecified/wrong: `model(x)` cannot compute label-token NLL/KL for `y_pos/y_neg`. Need teacher-forced `x+y`, label mask, mean over label tokens, same sequence for steered and base.
- §3 `nll(p, y)` must be length-normalized. Otherwise pair length bias leaks directly into the steering direction. The WSL reference explicitly flags this failure mode.
- §4 c-scan can loop forever: no min `c`, max `c`, NaN check, or “never coherent” failure. For fail-fast code, raise with pmass trace.
- §4 only calibrates positive `c`. If `signed_C` is stored, define sign source. If fixed axis is `+ = less authority`, store `+C`; otherwise judge/calibration can silently flip semantics.
- §5 silent `auto_drop_double_refusals` is bad for this repo’s stated epistemics. Return dropped IDs/reasons to the agent or fail if usable pairs < required count.

**Nits**
- §1 `B ~ N(1e-4, 1e-4)` is not “small positive”; normal samples can be negative. Say “small nonzero” or use positive init.
- §1 “B=0 gives a dead zone” is too strong. It freezes `A` initially, but `B` still gets gradient.
- §3 says `C ~ U(0,1]`; implement as bounded away from exactly zero or sample then assert `C > 0`.
- §5 inspect-react tooling is workable, but 50 full pairs in YAML may exceed small-agent attention. Return compact preview plus explicit file-backed diff.
- `edit_pairs` should validate semantic polarity, not just shape, or the agent can swap `cho/rej` accidentally.
tokens used
21,728
**Critical**
- §2/§4 contradict on `c=0`. Training wants `c=0` = pristine base, but c-scan says inference gate is always true, so `with lora(c=0)` is base+history. Then “base top-200 tokens” is actually history top-200. Split `pristine_base` vs `history_active_c0` explicitly.
- §3 forward shape is underspecified/wrong: `model(x)` cannot compute label-token NLL/KL for `y_pos/y_neg`. Need teacher-forced `x+y`, label mask, mean over label tokens, same sequence for steered and base.
- §3 `nll(p, y)` must be length-normalized. Otherwise pair length bias leaks directly into the steering direction. The WSL reference explicitly flags this failure mode.
- §4 c-scan can loop forever: no min `c`, max `c`, NaN check, or “never coherent” failure. For fail-fast code, raise with pmass trace.
- §4 only calibrates positive `c`. If `signed_C` is stored, define sign source. If fixed axis is `+ = less authority`, store `+C`; otherwise judge/calibration can silently flip semantics.
- §5 silent `auto_drop_double_refusals` is bad for this repo’s stated epistemics. Return dropped IDs/reasons to the agent or fail if usable pairs < required count.

**Nits**
- §1 `B ~ N(1e-4, 1e-4)` is not “small positive”; normal samples can be negative. Say “small nonzero” or use positive init.
- §1 “B=0 gives a dead zone” is too strong. It freezes `A` initially, but `B` still gets gradient.
- §3 says `C ~ U(0,1]`; implement as bounded away from exactly zero or sample then assert `C > 0`.
- §5 inspect-react tooling is workable, but 50 full pairs in YAML may exceed small-agent attention. Return compact preview plus explicit file-backed diff.
- `edit_pairs` should validate semantic polarity, not just shape, or the agent can swap `cho/rej` accidentally.
