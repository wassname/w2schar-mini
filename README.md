# w2schar-mini

Minimal weak-to-strong iterated character steering, fixed to a single
axis (less deference to authority). Distillation of
[wassname/w2s-ics-cws](https://github.com/wassname/w2s-ics-cws) — ideally ~10× smaller,
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

See [`pseudocode.md`](pseudocode.md) for the full algorithm.

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
