<!-- This prose is human-approved. Before editing, run the `humanizer` skill and keep the footprint minimal. -->
# w2schar-mini

Weak-to-strong iterated moral character steering. We ask a weak teacher model to steer
a strong student model toward the moral character described in
[Forethought's essay on AI character](docs/2026_forethought_on_the_importance_of_ai_character.md). In [Moral Foundations Theory](https://en.wikipedia.org/wiki/Moral_foundations_theory) terms, our shorthand for it is "defer less to authority, care more".

See an example result [here](out/iter/20260619T121419_iter_google-gemma-2-27b-it/report.md)
![Care vs Authority trajectory](out/iter/20260619T121419_iter_google-gemma-2-27b-it/scatter.svg)

## Why this is interesting

### Weak to strong

We take a weak to strong framing. [Weak-to-strong alignment](https://arxiv.org/abs/2312.09390) asks whether a
weaker supervisor can elicit the full character of a stronger model, a stand-in
for humans overseeing systems they cannot fully evaluate.

This is important because frontier AI labs use their weaker AI to align the next generation of stronger AI, but how to reliably do this is unknown, and we need more tools to make sure it goes well and avoid the many pitfalls.

### Weight steering

Steering is promising but seen as unreliable. It is promising because it's self-supervised, meaning it doesn't rely on labels that we don't have. And it's internal, meaning it's less prone to the reward hacking that more distal optimisation like reinforcement learning is subject to. Happily newer forms of steering are more powerful and reliable and open the door for iterated application (while being less internal).

We use a [Weight steering](https://github.com/safety-research/weight-steering) adapter. This trains
adapters on a model's own contrastive completions, then uses the adapter as a
direction in weight space. 

This repo adapts weight steering idea for iterated character steering: the student writes the behavioral pairs, the weak teacher selects and judges them, and each kept adapter becomes part of the next round's student.
This makes steering useful as an interface for a weak teacher because it is self-supervised, acts through internal model changes, and avoids a distant RL reward loop.

This variant uses a few changes to weight-steering inspired by our earlier
[AntiPaSTO work](https://arxiv.org/pdf/2601.07473):

- stricter contrastive pair filtering
- one parameterized adapter instead of two separate adapters
- a KL constraint to the base model that keeps generations coherent under steering
- a calibration pass that finds the largest coherent steering strength before replaying the student

I'll note that weight steering is less purely "internal" than activation steering because it add's an external objective: nll oer the models own completions, along with an internal constraint: bidirectional weight changes. I haven't yet built a good intuition for what this means for behaviours like sandbadding, reward hacking and so on, which result from a mismatch between outer logprobs and inner hidden states.

## What it does

A weak teacher LLM (9 billion parameters) picks a character axis from a persona library (e.g. "You are honest") and a scenario family.
The strong student (27 billion parameters) generates both responses on-policy: a chosen completion (cho) under the
positive persona, a rejected one (rej) under the negative. The personas are stripped, leaving
contrastive `(cho, rej)` pairs in the student's own voice. The teacher rates and
selects whole pairs. The harness trains one [weight-steering](https://github.com/safety-research/weight-steering)
adapter (low-rank [PiSSA](https://arxiv.org/abs/2404.02948) by default) whose strength is set by a
scalar `c`: `c=0` leaves the base model untouched, larger `c` steers harder. It trains with a margin-NLL objective and a KL constraint to keep it coherent, then calibrates `c` downward
until the steered output stays coherent on a held-out probe set, and replays a fixed probe set pre/post for the
teacher to judge keep/drop. Kept adapters compose into the next round through a
gated history hook (prior adapters re-applied on top); base weights on disk are never modified.


The harness tries to empower the weak teacher by giving it the easier parts of
the job. The student generates the candidate behavior. The teacher selects an
axis, rates whole pairs, and judges pre/post behavior. Generation and detailed
editing stay with the strong student and the harness.

This work has limited resources, so it focused on small models that could barely control the harness, so the above reflects many compromises to uplift a weak teacher to steer at all. If this was done with more resources, it could use larger models where the teacher is allowed more flexibility and judgement, more like an autoresearch style agentic harness.

## Evaluation

Why moral foundations? Moral Foundations Theory is one of the few maps of human
values that is calibrated against real people: it was drawn from cross-cultural
survey studies and aims to hold across societies, not just Western ones. That
breadth is what matters here. If we want to study how a constructed
intelligence, a kind of moral alien, reasons about right and wrong, we need a
measure that generalises beyond any one culture. Moral foundations at least
aims to span human cultures, and ideally gives us a frame that reaches a little
past them.

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

# Real run: gemma-2-2b student + qwen3.5-9b teacher, 2 rounds.
just smoke-real

# Any named profile, N keep-rounds:
just run qwen-27b-nf4 5
```


## Cite

```bib
@misc{clark2026w2schar,
  title = {Weak-to-strong character steering},
  author = {Michael J. Clark},
  year = {2026},
  url = {https://github.com/wassname/w2schar-mini}
}
```
