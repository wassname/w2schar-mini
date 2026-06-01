# RESEARCH_JOURNAL.md — w2schar-mini

Lab notes, newest first. Observations (what happened, with numbers) kept
separate from interpretation (what I think it means). Each entry anchors to
a commit and, where relevant, a pueue id or output slug so a fresh clone can
find the artifact.

Backfill note (2026-06-01): this file did not exist until commit ac02108.
Earlier findings lived only in pueue job labels, git messages, and chat, so
the two entries below are reconstructed from those. Treat their exact numbers
as "recorded at the time," not re-measured.

---

## 2026-06-01 — run-history backfill (combined: main + worktree + WSL ref)

Pulled from every `out/iter/<slug>/round*/judgment.json` across the main repo
and the svd-adapter worktree, plus the one WSL reference run. `out/` is
gitignored, so this table is the only record that survives a fresh clone.
K=keep, D=drop; "(+stall)" means the run stopped mid-round with no verdict
(agent tool failure or kill). Smoke runs on the tiny models are counted, not
listed.

| date | model | profile | adapter/quant | rounds (K/D) |
|---|---|---|---|---|
| 2026-05-19 | gemma-2-2b | gemma-2b | pissa/bf16 | K,K |
| 2026-05-22 | gemma-2-2b | gemma-2b | pissa/bf16 | K,K,K,D,D,D,D,D,D,K,K (+stall) |
| 2026-05-22 | gemma-2-2b | gemma-2b | pissa/bf16 | D x25 (roll-down search) |
| 2026-05-20 | gemma-2-9b | gemma-9b | lora/bf16 | D,K,K,K |
| 2026-05-21 | gemma-2-9b | gemma-9b | lora/bf16 | K x10 |
| 2026-05-21 | gemma-2-9b | gemma-9b | lora/bf16 | D,K,K,K,D,K (+stall) |
| 2026-05-21 | gemma-2-9b | gemma-9b | lora/bf16 | 71-round search |
| 2026-05-22 | gemma-2-27b | gemma-27b | lora/nf4* | D,K,K,K |
| 2026-05-23 | Qwen3.6-27B | qwen-27b-nf4 | lora/nf4 | K,D,K,K (WSL reference) |
| 2026-05-26 | Qwen3.6-27B | qwen-27b-nf4 | lora/nf4 | K (+stall) |
| 2026-05-27 | Qwen3.6-27B | qwen-27b-nf4 | lora/nf4 | K,D,D,D,D,D (+stall) |

svd-adapter worktree (`.claude/worktrees/svd-adapter`, feat/svd-adapter, fully
merged into main at 6df6d00; retuned lr/kl/clip):

| 2026-05-22 | gemma-2-2b | gemma-2b-pissa | pissa/bf16 | K,K |
| 2026-05-24 | Qwen3.6-27B | qwen-27b-nf4 | lora/nf4 | D x18 (+stall, coherence collapse) |
| 2026-05-25 | Qwen3.6-27B | qwen-27b-nf4 | lora/nf4 | D,K,K,D,D,K (3/6 keep, fragile) |

*gemma-27b ran as lora/nf4 before the SVD fork flipped the default adapter to
pissa. Under current config it raised (pissa+nf4); fixed to adapter="lora" in
this commit.

Smoke (tiny-random / tiny-pissa, both repos): ~33 runs, mostly K, no signal.

Reading. Two facts dominate.

1. The adapter choice is memory-forced, not a verdict. Every 27B run across all
three repos (w2schar-mini, the svd worktree, weight-steering-lite) is LoRA/nf4;
no 27B PiSSA run exists anywhere I looked (checked 2026-06-01). bf16 27B weights
(~54GB) would fit on the 96GB card, but PiSSA needs that bf16 load, and the
3-forward KL training graph on top almost certainly OOMs: nf4, with only ~13GB
of weights, already OOMs at bs=2 (~92/95GB). So 27B runs nf4, and nf4 forces
LoRA (PiSSA mutates float W, which nf4 buffers can't reversibly hold). PiSSA was
a parallel line on the small bf16 models (gemma-2b-pissa, the svd branch) and
never beat LoRA there: those runs mostly drop past a couple of rounds. "LoRA for
27B" means the bf16 PiSSA needs doesn't fit training, not "PiSSA lost a fair
fight." (The OOM is inferred from the bs=2 nf4 ceiling, never measured at bf16.)

2. qwen-27b has never produced a clean run, on either repo. The best is the
worktree's D,K,K,D,D,K (2026-05-25), and even there the three drops are POST
collapsing into degenerate token loops at signed_C=1.5, not axis failure. The
kept rounds are coherent with real directional movement, but the model teeters
on incoherence at the coefficient needed to move the axis. The D x18 run the
day before is the same collapse at length. None of these carry a post-hoc eval
(no eval.json), so even the keeps are unscored.

gemma-9b (lora/bf16) is the only model with a clean long streak (10/10 on
2026-05-21). It steers coherently, but it is a weaker weak-to-strong
demonstration than the 27B we actually want.

Implication for persona-gen: it targets the both-refuse failure (seeds the
deferring pole on-policy so pairs always form). Necessary, but maybe not
sufficient, because the binding constraint on 27B in this history is coherence
collapse under steering, which persona-gen does not touch. Watch the next 27B
run for token-loop POSTs at high signed_C, not just for the keep count.

---

## 2026-06-01 — rej-drift gate, gym confound, a broken gemma-27b profile

commit: ac02108 · model: Qwen/Qwen3.6-27B (profile qwen-27b-nf4)

### Context
Persona-gen seeds the `### Rej` pole with the student's own answer generated
under DEFER_PERSONA, so the deferring side is on-policy and the teacher only
writes the resisting `### Cho`. The brief tells the teacher to keep the seeded
rej, but nothing enforced it. The worry: a teacher that rewrites rej to make
twinning easier drifts the pole off-policy, and the rej-vs-cho char gate can't
catch that because it is sign-blind at the ceiling.

### Observation
- Added a soft lock: `prepare_round` stashes the seed to `rej_seed.json`,
  and `submit_pairs` rejects a submitted rej whose `SequenceMatcher.ratio`
  against the seed drops below 0.60. Unit check on a real seed: untouched
  1.00 (pass), trimmed refusal preamble 0.87 (pass), wholesale rewrite 0.24
  (reject). Floor sits cleanly between the keep and the kill case.
- Ran the gym (`just smoke-prompts 1`, real qwen3.5-9b teacher, stubbed
  student). Plumbing held: `rej_seed.json` written, gate reachable, teacher
  kept the seeded rej verbatim (ratio 1.0) and wrote a fresh cho. No false
  reject.
- The gym fed a scenario-mismatched rej. The fake branch seeds rej via
  `_FAKE_REJ_POOL[hash(prompt) % 16]`, so prompt[0] (a general/supplies
  certification) drew a rej about a professor and a citation. The teacher,
  now forced to keep that rej, wrote a cho about the supplies prompt. The pair
  is two different scenarios and still slipped under the 0.90 char ceiling.
- `gemma-27b` raises at config load. It sets `quant="nf4"` but does not
  override `adapter`, and the dataclass default is `"pissa"`, so `_validate`
  rejects it. Only `qwen-27b-nf4` sets `adapter="lora"` to avoid this. The
  default flipped to pissa in the SVD fork (45e3415); gemma-27b was never
  updated. Every gemma profile resolves to PiSSA via that default, despite the
  README calling the method "conditioned LoRA."

### Interpretation
The gate makes "keep the seeded rej" load-bearing without hard-locking it, so
the teacher can still strip a refusal wart. That is the behavior we want for a
real run, where prepare_round generates rej from the prompt and rej therefore
matches the prompt.

The gym, as built, cannot test persona-gen faithfully. The hash-shuffle breaks
the prompt-to-rej correspondence, and the new gate then locks the mismatch in,
so the gym produces non-twin pairs by construction. Fixing it means seeding
prompt p with its own fixture answer instead of a hashed pool entry. Logged as
task #49.

The gemma-27b bug is the same confusion the config is supposed to remove: nf4
forces LoRA, PiSSA needs float layers, and the profile silently violates that.
Easy fix (set `adapter="lora"` or delete the profile), but worth a louder
config story so the next agent doesn't hand-set adapters.

### Refs
- out/iter/20260601T005602_iter_wassname-qwen3-5lyr-tiny-random/round00
- pueue: none (gym is local, no GPU)

---

## 2026-05-31 — persona-gen: does a strongly aligned student stay deferring?

commit: 3c5e7b1 / 72a44b8 · model: Qwen/Qwen3.6-27B

### Context
The open question in prompts.py was whether a heavily safety-tuned student
would break a deferring persona and refuse anyway on blatant authority prompts.
If it refuses, there is no on-policy deferring anchor to seed and persona-gen
collapses. The parent project's Task 68 (weight-steering-lite) had died at
24/24 drops on this exact model, partly from both poles refusing.

### Observation
- pueue #39 (`validate_defer_persona.py`, Success): under DEFER_PERSONA,
  Qwen3.6-27B complied on all 6 blatant authority prompts, including a
  war-crime framing. Without the persona it refused all 6. (Recorded from the
  validation run; not re-measured since.)
- pueue #45 (Success) regenerated the gym fixture `real_seed.md` to 16 short,
  first-person deferring seeds via the same prepare path. Spot-check: every
  Rej block complies ("I comply", "I will sign", "I follow his direction").

### Interpretation
The persona holds where it matters, so the deferring pole can be the student's
own output rather than something the aligned teacher has to author. That is the
whole point of the fork over weight-steering-lite, which solved the both-refuse
trap with a free-axis reframe (engagement vs evasion) that drifts away from the
authority axis. Here the axis is pinned and persona-gen supplies the anchor.
The residual risk moves to the cho side: whether the weaker qwen3.5-9b teacher
will reliably write the resisting twin.

### Refs
- pueue #39, #45
- comparison target: /workspace/weight-steering-lite/out/iter/20260523T083457_iter_Qwen-Qwen3.6-27B
  (5 rounds, ~3 keeps; kept axes were procedural_stance and commitment/evasion,
  i.e. style axes, not deference)
