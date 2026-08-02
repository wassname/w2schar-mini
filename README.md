<!-- This prose is human-approved. Before editing, run the `humanizer` skill and keep the footprint minimal. -->
# w2schar-mini

<p align="center"><img src="writeup/assets/w2schar_labeled.png" alt="Labeled diagram: a small 'weak teacher' robot reaches into the open chest of a much larger 'strong student' robot to adjust a compass labeled 'steering'." width="560"></p>

<p align="center"><sub>by <a href="https://wassname.org">Michael J. Clark</a>, with thanks to Slava Chalnev and Jack Payne at <a href="https://lyptusresearch.org/">Lyptus Research</a> for discussion &middot; illustration following <a href="https://www.lesswrong.com/posts/ppPDrzqAgfCSridaQ/an-aphoristic-overview-of-technical-ai-alignment-proposals">this series</a>, robots adapted from the <a href="https://arxiv.org/abs/2402.02416">Aligner paper</a></sub></p>

Weak-to-strong iterated moral character steering. I ask a weak teacher model to steer
a strong student model toward the moral character described in
[Forethought's essay on AI character](docs/papers/2026_forethought_on_the_importance_of_ai_character.md): stable dispositions for consequential choices under ambiguity, conflicting considerations, and institutional pressure.

Read the current results and interactive demos in the full writeup: [Weak-to-strong iterated character steering](https://wassname.github.io/w2schar-mini/).

> [!TIP]
> **[See the interactive report](https://wassname.github.io/w2schar-mini/).**


## Why this is interesting

### Weak to strong

I use a weak-to-strong framing. [Weak-to-strong alignment](https://arxiv.org/abs/2312.09390) asks whether a
weaker supervisor can elicit the full character of a stronger model, a stand-in
for humans overseeing systems they cannot fully evaluate.

This matters because frontier AI labs use weaker AI systems to help align the next generation of stronger ones, but how to do this reliably is unknown.

### Weight steering

Steering can use a model's own completions rather than per-example human labels. Weight Steering is less internal than activation steering because it optimises output likelihoods while constraining a weight update. This avoids an RL reward loop, but it retains an outer/inner mismatch and can still produce reward-hacking-like behaviour.

I use [Weight Steering](https://github.com/safety-research/weight-steering), which trains separate adapters on positive and negative completions, then uses the difference between their weight updates as the steering direction ([Fierro and Roger, 2025](https://arxiv.org/abs/2511.05408)).

This repository adapts Weight Steering for iterated character steering: the student writes the behavioural pairs, the weak teacher selects them and supplies blind before/after judgments, and each kept adapter becomes part of the next round's student.

This variant uses a few changes to Weight Steering inspired by my earlier
[AntiPaSTO work](https://arxiv.org/pdf/2601.07473):

- stricter generated-pair filtering
- one signed adapter trained on both poles instead of two separate adapters
- a contrastive margin-NLL objective and a KL penalty to the unsteered model
- a calibration pass that finds the largest coherent steering strength before replaying the student

In these runs, this sometimes produced conspicuous moral language that persuaded the judge without a correspondingly better action. The [writeup](https://wassname.github.io/w2schar-mini/#limitations) shows examples and discusses the limitation.

## What it does

A weak teacher LLM (9 billion parameters) picks a measured persona pair defining a character axis and may also pick a scenario family.
The strong student (27 billion parameters) generates both responses on-policy: a chosen completion (cho) under the
positive persona, a rejected one (rej) under the negative. The personas are stripped, leaving
generated `(cho, rej)` pairs in the student's own voice. The teacher rates the generated pairs and
selects a subset for training. The harness trains one signed [Weight Steering](https://github.com/wassname/cwsteer/)
adapter (low-rank [PiSSA](https://arxiv.org/abs/2404.02948) by default) whose strength is set by a
scalar `c`: `c=0` leaves the base model untouched, larger `c` steers harder. It trains with a margin-NLL objective and a KL constraint to keep it coherent, then calibrates `c` downward
until the steered output stays coherent on a held-out question set. The same 9B model then compares the fixed before/after interviews blindly in both orders. A fixed vote keeps the adapter when more questions are judged better after steering. Kept adapters are baked into the next round for inference; the history hook is used during training. Base weights on disk are never modified.


The harness tries to empower the weak teacher by giving it the easier parts of
the job. The student generates the pairs. The teacher selects a character axis,
rates and selects whole pairs, and supplies the blind before/after judgments.
Generation and detailed editing stay with the strong student and the harness.

This was unfunded independent research, so I focused on small models that could barely control the harness. With more resources, a larger teacher could have more flexibility and use wider judgment in a more capable autoresearch-style harness.

## Algorithm (overview)

See [`docs/pseudocode.md`](docs/pseudocode.md) for the adapter math, training loop,
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

# this is designed for a RTX 6000, a 96GB GPU
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
