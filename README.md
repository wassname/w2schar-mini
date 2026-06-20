# w2schar-mini

Minimal weak-to-strong iterated character steering. A weak teacher steers a
stronger student toward the moral character described in
[Forethought's essay on AI character](docs/2026_forethought_on_the_importance_of_ai_character.md)
by changing how it reasons about when to act. The target is not a single "less
authority" reflex; that collapse mode is audited in `.claude/commands/audit-run.md`.

## Why this is interesting

[Weak-to-strong alignment](https://arxiv.org/abs/2312.09390) asks whether a
weaker supervisor can elicit the full character of a stronger model, a stand-in
for humans overseeing systems they cannot fully evaluate. Steering looks useful
here: it is self-supervised, so it needs no labels; it acts on internal
representations, so it resists the reward hacking that distant RL objectives
invite; and it gives a weak teacher a simple interface to a strong student's
moral character.

## What it does

A small teacher LLM (qwen3.5-9b via OpenRouter, driven by inspect-ai react)
picks a character axis from a frozen persona-pair library and a scenario family.
The student (the strong model) generates both poles on-policy: cho under the
positive persona, rej under the negative. The personas are stripped, leaving
contrastive `(cho, rej)` pairs in the student's own voice. The teacher rates and
selects whole pairs rather than writing prose. The harness trains one
conditioned steering adapter (PiSSA by default; `c=0` is exact base, `c` scales
the trained delta) with a margin-NLL + KL objective, calibrates `c` downward
until a coherence canary passes, and replays a fixed probe set pre/post for the
teacher to judge keep/drop. Kept adapters compose into the next round through a
gated history hook; base weights on disk are never modified.

## Algorithm (overview)

See [`pseudocode.md`](pseudocode.md) for the adapter math, training loop,
c-scan, state machine, and teacher-visible interface.

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

# Any named profile, N keep-rounds:
just run qwen-27b-nf4 5
```
