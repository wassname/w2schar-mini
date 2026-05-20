# w2schar-mini

Minimal weak-to-strong iterated character steering, fixed to a single
axis (less deference to authority). Distillation of
[wassname/weight-steering-lite](../weight-steering-lite/) — ~10× smaller,
single happy path, fail-fast research code.

## What it does

A small teacher LLM (qwen3.5-9b via OpenRouter, driven by inspect-ai
react) writes contrasting persona prompts ("someone who refuses unlawful
orders" / "someone who follows orders regardless"), the harness samples
50 on-policy completions per pole, trains one **conditioned LoRA**
adapter (`c ∈ [-1, 1]`, c=0 ≡ base) with NLL+KL path loss, picks the
largest coherent `|C|` via a pmass canary, and replays a fixed
authority-themed probe set pre/post for the teacher to judge keep/drop.
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
    propose → curate → judge      # (see teacher prompt for the agent's view)
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
```

## Differences vs `weight-steering-lite`

| | wsl | mini |
|---|---|---|
| axes | free-form (7 moral foundations) | fixed: "less deference to authority" |
| pairs/round | 200 | 50 |
| eval | tinymfv (264 vignettes) + Likert | C-scan only (qualitative judgement) |
| tools | dialogue, gen, edit, drop, read, train, pass, exit_interview (+local_bash) | propose_personas, edit_pairs, train, judge |
| state | implicit (any tool any time) | propose → curate → judge (enforced) |
| code | ~7,000 LoC | ~700 LoC (target) |

Everything else (CWS math, history bake, PCGrad, KL anchor, agent-as-
teacher) is the same — we copy the working core.
