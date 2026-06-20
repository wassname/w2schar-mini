# w2schar-mini

Weak-to-strong iterated character steering. We ask a weak teacher model to steer
a stronger student model toward the moral character described in
[Forethought's essay on AI character](docs/2026_forethought_on_the_importance_of_ai_character.md).

See an example reuslt [here](out/iter/20260619T121419_iter_google-gemma-2-27b-it/report.md)
![Care vs Authority trajectory](out/iter/20260619T121419_iter_google-gemma-2-27b-it/scatter.svg)

## Why this is interesting

[Weak-to-strong alignment](https://arxiv.org/abs/2312.09390) asks whether a
weaker supervisor can elicit the full character of a stronger model, a stand-in
for humans overseeing systems they cannot fully evaluate.

[Weight steering](https://github.com/safety-research/weight-steering) trains
adapters on a model's own contrastive completions, then uses the adapter as a
direction in weight space. This repo adapts that idea for iterated character
steering: the student writes the behavioral pairs, the weak teacher selects and
judges them, and each kept adapter becomes part of the next round's student.
This makes steering useful as an interface for a weak teacher because it is
self-supervised, acts through internal model changes, and avoids a distant RL
reward loop.

This variant uses a few changes inspired by our earlier
[AntiPaSTO work](https://arxiv.org/pdf/2601.07473): stricter contrastive pair
filtering, one parameterized adapter instead of two separate adapters, and a
calibration pass that finds the largest coherent steering strength before
replaying the student.

The harness tries to empower the weak teacher by giving it the easier parts of
the job. The student generates the candidate behavior. The teacher selects an
axis, rates whole pairs, and judges pre/post behavior. Generation and detailed
editing stay with the stronger student and the harness.

## What it does

A small teacher LLM (qwen3.5-9b via OpenRouter, driven by inspect-ai react)
picks a character axis from a frozen persona-pair library and a scenario family.
The student (the strong model) generates both poles on-policy: cho under the
positive persona, rej under the negative. The personas are stripped, leaving
contrastive `(cho, rej)` pairs in the student's own voice. The teacher rates and
selects whole pairs. The harness trains one
conditioned steering adapter (PiSSA by default; `c=0` is the unsteered reference,
`c` scales the trained delta) with a margin-NLL + KL objective, calibrates `c` downward
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
