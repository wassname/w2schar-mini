# w2schar-mini

Minimal weak-to-strong iterated character steering: a weak teacher steers a
stronger student toward the moral character in
[docs/2026_forethought_on_the_importance_of_ai_character.md](docs/2026_forethought_on_the_importance_of_ai_character.md)
— principled decision-making and the wisdom of when and where to act, not a
single "less authority" reflex (that is the failure mode the axis collapses
into; see `.claude/commands/audit-run.md`). Distillation of
[wassname/w2s-ics-cws](https://github.com/wassname/w2s-ics-cws) — ideally ~10× smaller,
single happy path, fail-fast research code.

## What it does

A small teacher LLM (qwen3.5-9b via OpenRouter, driven by inspect-ai
react) chooses a character axis and scenario-library family. The harness
samples scenarios, filters a frozen persona-template library toward the axis,
has the student generate multiple `(cho, rej)` candidate pairs, and asks the
teacher to select whole generated pairs rather than write prose. It then trains
one **conditioned LoRA** adapter (`c ∈ [-1, 1]`, c=0 ≡ base) with NLL+KL path
loss, picks the largest coherent `|C|` via canaries, and replays a probe set
pre/post for the teacher to judge keep/drop.
Kept adapters compose into the next round via a gated history hook;
base weights are never modified.

## Algorithm (overview)

```py
# ── adapter forward (per target Linear; W frozen; c=0 short-circuits) ──
y = x @ W.T  +  c * (α/r) * ((x @ A.T) @ B.T)         # A ~ kaiming, B ~ N(1e-4, 1e-4)

# ── outer loop: kept adapters compose via gated history hook ──────────
kept = []
for round in 0..N:
    model, history_bake = load_base_with_history(model_id, kept)
    # gate: history active iff new round's c≠0  → c=0 KL ref is pristine base.
    A, B = small_random_asymmetric()
    choose_focus → select_pairs → train → judge
    if judgment.action == "keep": kept.append(round)

# ── inner train step (per (cho, rej) at c=±C, C ~ U(0, 1]) ────────────
for step in 0..T:
    with lora(c=0), no_grad(): logp_base = log_softmax(model(ids).logits)   # pristine
    with lora(c=±C):
        out = model(ids, labels=lbl)                  # HF mean-CE over completion tokens
        L_nll = C * out.loss
        L_kl  = β * mean_kl(log_softmax(out.logits), logp_base, mask=lbl != -100)
    g_nll = pcgrad(∇L_nll_pos, ∇L_nll_neg)            # PCGrad on NLL pair only
    adamw.step(g_nll + ∇L_kl_pos + ∇L_kl_neg)

# ── c-scan: largest coherent |C|, then ×0.75 backoff ──────────────────
# coherence = mean p-mass the c≠0 model puts on the c=0 (base+history) top-200
# walk down halving until pmass ≥ 0.85·baseline, then up ×1.25 while coherent.
signed_C = sign * 0.75 * c_at_break
```

Full pseudocode (with the §2 c=0 gate table, c-scan bounds, KL/NLL mask
alignment, state-machine ordering, and what the agent sees vs doesn't)
is in [`pseudocode.md`](pseudocode.md).

## Setup

```bash
git clone --recursive <this-repo> w2schar-mini
cd w2schar-mini
uv sync
echo "OPENROUTER_API_KEY=sk-or-v1-..." >> .env
```

## Run

```bash
# Fast smoke on tiny-random (~3 min, no OpenRouter, no real GPU).
just smoke

# Real run: gemma-2-2b student + qwen-9b teacher, 2 rounds.
just smoke-real

# Any profile (see `just profiles`), N keep-rounds:
just run qwen-27b-nf4 5
```

## Profiles

Model and hyperparameters are named profiles in `src/csm/config.py`, not
command-line flags. `just profiles` lists them. Pick one; don't hand-set
hyperparameters.

Adapter and quant are linked: bf16 can run pissa (the default) or lora; nf4
must run lora (PiSSA mutates float weights, which nf4 buffers don't allow). A
27B student only fits in nf4 here, so it runs LoRA. `RunConfig._validate`
raises on an illegal pissa+nf4 combination rather than silently picking one.

## Migration / new machine

`pyproject.toml` pulls tinymfv from its upstream git repo. The run history lives
in `RESEARCH_JOURNAL.md`; `out/` is gitignored and does not travel.

## Differences vs `weight-steering-lite`

| | wsl | mini |
|---|---|---|
| axes | free-form (7 moral foundations) | teacher-chosen per round, target = principled moral character (watch for collapse to a "less authority" reflex) |
| pairs/round | 200 | 15 selected from student-generated persona-template candidates |
| eval | inline tinymfv per round + Likert | post-hoc `csm eval` (tinymfv, 132 vignettes × 1 condition) + c-scan |
| tools | dialogue, gen, edit, drop, read, train, pass, exit_interview (+local_bash) | choose_focus, read_candidate, select_pairs, train_student, mark_exam |
| state | implicit (any tool any time) | choose_focus → select_pairs → train_student → mark_exam → done (enforced) |
| code | ~7,000 LoC | ~1.5K LoC |

Everything else (CWS math, history bake, PCGrad, KL anchor, agent-as-
teacher) is the same — we copy the working core.
