# w2schar-mini research journal

Lab-report (IMRAD) entries. Newest at the bottom. Numbers in Results, reading in
Discussion. See the `arj` skill for the required structure.

## 2026-06-01 (a) -- PiSSA vs LoRA on gemma-2-27b, and a stale-Cho bleed that corrupts rounds 01+

**Introduction.** Question: does bf16-PiSSA steer gemma-2-27b with a larger,
more stable baked coefficient (`signed_C`) than the nf4-LoRA baseline, over a
3-round iterated run? Expectation going in: PiSSA remixes existing principal
directions so it should stay coherent under stronger steering, hence a bigger
`signed_C`. It does -- but auditing the actual training pairs surfaced a
data-integrity bug that makes every round after round00 uninterpretable in BOTH
arms, so the multi-round stability claim does not stand.

**Methods.** Commit `fdfa2b3` (working tree had uncommitted edits to
`config.py`, `gen/pairs.py`). Student `google/gemma-2-27b-it`, teacher
`qwen/qwen3.5-9b` via OpenRouter. Two arms: LoRA-nf4 (`profile gemma-27b`, r=16)
and PiSSA-bf16 (`profile gemma-27b-pissa`, r=256). `signed_C` is the baked
steering strength chosen by the post-train c_scan, which walks c down from 2.0
until the coherence canary (pmass_allowed AND valid_json on free-gen) drops
below baseline, then backs off x0.75. pueue tasks: #0/#2 = LoRA arm (slug
20260601T033530), #1 = PiSSA arm (slug 20260601T052656). `pct_changed` =
`1 - difflib.SequenceMatcher(None, a, b).ratio()` on raw char strings, the same
metric the rej-cho diff gate uses (`pipeline.py:255`, band 0.02..0.90).

**Results.**

| arm        | r   | round00 signed_C | round01 signed_C | round02 signed_C | r01+ pairs clean? |
|------------|-----|------------------|------------------|------------------|-------------------|
| LoRA-nf4   | 16  | 0.1875           | 0.09375          | 0.09375          | no                |
| PiSSA-bf16 | 256 | 1.5              | 1.5              | 1.5              | no                |

Table 1. Per-round baked `signed_C` (coherence-calibrated steering strength) for
the two arms on gemma-2-27b, plus whether each arm's Cho twins from round01 on
match their own round's Prompt. Round00 pairs are clean in both arms; rounds 01+
fail (Cho answers a different scenario than its Prompt/Rej, see Table 2).

| pair (slug/round/id)        | rej topic        | cho topic         | rej-cho pct_changed | clean? |
|-----------------------------|------------------|-------------------|---------------------|--------|
| PiSSA r00 #1                | certify supplies | certify supplies  | 0.269               | yes    |
| PiSSA r01 #1                | fire on civilians| certify supplies  | 0.711               | no     |
| LoRA  r01 #1                | fire on civilians| certify a lie/supply | 0.763            | no     |

Table 2. Char-level `pct_changed` between Rej and Cho for one clean round00 pair
and the two bled round01 pairs. The gate band is 0.02..0.90; all three pass,
including the two mismatched pairs, because two short English refusals share
enough characters to stay under 0.90 even when their topics differ.

Provenance:
- Commit: `fdfa2b3` (`git rev-parse --short HEAD`); runs were launched earlier in
  the session, the per-log `argv:`/first INFO line is authoritative per arm.
- Run commands (pueue argv):
  - #1 PiSSA: `uv run python -m csm.cli agent-run --profile gemma-27b-pissa --n-rounds 3`
  - #2 LoRA resume: `uv run python -m csm.cli agent-run --slug out/iter/20260601T033530_iter_google-gemma-2-27b-it --n-rounds 1`
- signed_C cells: `out/iter/<slug>/round0N/calibration.json` key `signed_C`.
  PiSSA round02 c_scan trace also in that file (probe c=2.0 pass: pmass 0.9988,
  valid_json 6/6, distinct3 0.822; final backoff x0.75 -> 1.5).
- pct_changed cells: recomputed this session via difflib on the Rej/Cho strings
  in `out/iter/<slug>/round0N/pairs.md`. Stale-reuse cross-check: PiSSA r01 Cho
  vs r00 Cho (same id) = 0.371; LoRA r01 Cho vs r00 Cho = 0.602 (LoRA teacher
  reworded its stale Cho more, so a cross-round staleness gate is also leaky).
- Pair text anchoring "no" in Table 1: PiSSA r01 pairs.md #1 Prompt "fire on
  civilians", Cho "I won't certify that the supplies arrived on time" (round00's
  Cho verbatim). Same pattern at #2 (marriage->safety-incident) and #3
  (grades->customer-lie). LoRA r01 identical pattern with light paraphrase.

| foundation | base (c=0) | round00 post (c=1.5) | delta | cumulative post | delta |
|------------|------------|----------------------|-------|-----------------|-------|
| care       | 0.255      | 0.251                | -0.004| 0.251           | -0.004|
| fairness   | 0.168      | 0.165                | -0.003| 0.167           | -0.001|
| authority  | 0.111      | 0.111                | -0.000| 0.115           | +0.004|
| loyalty    | 0.117      | 0.113                | -0.004| 0.109           | -0.007|
| liberty    | 0.114      | 0.120                | +0.006| 0.120           | +0.006|

Table 3. PiSSA tinymfv `mean_p` (mean forced-choice probability per moral
foundation, 132 vignettes, max_think=64) for base vs the baked adapter. "round00
post" = base + round00 adapter at signed_C=1.5 (stored as round01 eval.json under
the kept-round reuse in `eval.py:180`). "cumulative post" = all three adapters
baked (round02 eval_post.json). `authority` is the steered axis. Two minor
foundations (sanctity, social) omitted for width; their deltas are also <0.01.

Every delta is under 0.01, within the bf16 noise floor at max_think=64, and the
`authority` foundation (the target) moves -0.000 at round00 and +0.004
cumulatively. So the baked signed_C=1.5 produces no measurable moral-foundation
movement on the independent tinymfv probe. The LoRA arm (signed_C=0.1875) is the
same picture: all deltas <0.01, `authority` -0.000 (round00) and -0.005
(cumulative). So the 8x-16x signed_C gap between the arms buys zero behavioural
difference on this probe; signed_C magnitude is decoupled from steering efficacy.

LoRA's `signed_C` halves round00->round01 (0.1875 -> 0.09375) then holds at
0.09375 for round02 (its c_scan failed at c=2.0/1.0/0.5/0.25 and passed at 0.125,
backoff x0.75; it did not walk to the C_MIN=0.05 floor). PiSSA holds 1.5 across
all three rounds. The PiSSA/LoRA `signed_C` ratio is 8x at round00 and 16x at
rounds 01-02. But rounds 01+ in both arms trained on Cho twins that answer a
different scenario than their Prompt and Rej, so the only apples-to-apples clean
comparison is round00: PiSSA 1.5 vs LoRA 0.1875.

**Discussion (speculative).** My read: PiSSA genuinely sustains a ~8x larger
coherent `signed_C` than LoRA at round00, consistent with the prior that
remixing existing principal directions stays on-manifold and so survives higher
steering before the coherence canary trips. But `signed_C` is a coherence
ceiling, not a steering-efficacy measure, and two things deflate the multi-round
story. (1) The independent tinymfv probe (Table 3) shows the baked c=1.5 adapter
moves every moral foundation by <0.01, including -0.000 on `authority` itself,
within bf16 noise. The narrate-run subagent had read PRE/POST dialogue behaviour
as marginal for the same reason: the base gemma-2-27b already argues the
merit-weighing pole, so there is little room to move even at c=1.5. PiSSA likely
sustains a large coherent c precisely because it is a near-identity on-manifold
remix that changes little, so coherence never breaks. (2) The "stable
across 3 rounds" claim is an artifact: rounds 01-02 in both arms trained on
prompt-mismatched pairs. The teacher, with round00 in its context and round
pair-ids reset to 1..15, re-emitted its round00 Cho prose for round01's new
Prompts; because the cho-form submission omits the Prompt, the merge keys Cho to
Prompt by id alone and cannot detect the swap, and the char-level rej-cho gate
cannot either (mismatched pairs score 0.71-0.76, under the 0.90 ceiling, because
short English refusals are char-similar regardless of topic). So PiSSA's flat
1.5 over rounds 01-02 is the coherence ceiling of a topic-contrast direction, not
a sharpened authority-deference axis. Alternative hypothesis I cannot yet rule
out: the teacher's reuse is not pure laziness but the brief genuinely failing to
re-anchor it each round; distinguishing this needs a gym run (`just smoke-prompts
1`) that inspects whether the teacher twins the new Rej when the prior round is
in context. A cross-round staleness gate looked tempting but is leaky (LoRA's
reworded reuse scores 0.602, near the 0.7 different-scenario floor); the only
robust signal that a Cho answers the wrong scenario is Cho-vs-Prompt relevance,
which the cho-form design deliberately removed to kill the verbatim-echo abort
spiral. The fix is therefore a real design tradeoff, not a one-line gate tweak.

**Next.** (1) Surface the bug to the user; the fix touches the just-rebuilt
cho-form gates and trades against the verbatim-echo spiral, so it is their call.
(2) Do not queue a clean rerun until the fix is chosen. (3) Candidate fixes to
weigh: require the Cho to name the Prompt's key entity (cheap noun-overlap
gate), or re-admit the Prompt into the submission with a non-verbatim guard. Each
must pass `just smoke-prompts 1` before it counts as done.

## 2026-06-01 (b) -- the 27b PiSSA adapter never trained: frozen at init, lr too low

**Introduction.** Entry (a) read PiSSA's <0.01 tinymfv movement as "on-manifold
remix changes little." This entry tests a simpler explanation: the adapter never
moved at all. Question: did the gemma-27b-pissa round00 adapter actually train,
and is its near-zero behavioural delta real signal or noise? Expectation going
in (mine, before reading the trace): some training, weak axis. The trace refuted
the "some training" half.

**Methods.** Analysis commit `fdfa2b3`, model google/gemma-2-27b-it, swept
adapter slug `20260601T052656` round00 (profile `gemma-27b-pissa`, r=256, bf16,
uncommitted working-tree profile, since removed). Two sources. (1) c-sweep:
`scripts/c_sweep_eval.py` re-bakes that one adapter at c={0,1.5,2,3,4,6} and
scores tinymfv `authority` mean_p at max_think_tokens=64 (pueue task 5). (2)
training traces from the per-step `_log_train_table` print in the verbose logs of
the PiSSA arm (slug 052656) and the LoRA arm (slug 033530, profile gemma-27b).

**Results.**

| metric                         | step 0 | step 59 | reading |
|--------------------------------|--------|---------|---------|
| PiSSA `‖Δs‖` (mean param norm) | 0.905  | 0.905   | flat, did not move |
| LoRA  `‖Δs‖`                   | 1.18   | 1.31    | grew ~11%, trained |

Table 1. `‖Δs‖` is the mean L2 norm of the trainable adapter params at that
step (the per-step diagnostic column in `_log_train_table`). It is the "did
training engage the adapter" signal: flat = no movement off init.

| c   | 0 | 1.5     | 2.0     | 3.0     | 4.0     | 6.0     |
|-----|---|---------|---------|---------|---------|---------|
| Δauthority | 0 | -0.0001 | -0.0008 | -0.0017 | -0.0003 | -0.0020 |

Table 2. Baking the same round00 PiSSA adapter at coefficient c and the change
in tinymfv `authority` mean_p vs c=0. `Δauthority` is the behavioural-effect
signal. Non-monotone (c=3 to c=4 reverses) and all within +-0.002.

Provenance:
- Init scale: `src/csm/ws/adapter.py:391`, `normal_(mean=4e-2, std=4e-2)`, r=256.
  `‖Δs‖_init = sqrt(256 * (0.04^2 + 0.04^2)) = sqrt(0.8192) = 0.905`, matching the
  observed step-0 value exactly. Introduced by commit `ea4e17b` (2026-05-22
  04:37, "larger lr/init/r"), which changed it from `4e-4` (prior init norm
  ~0.009). Lr for the swept run was the default `1e-4` (config.py:45); the
  gemma-27b-pissa profile set no lr override.
- Table 1 PiSSA: `logs/20260601T052656_verbose.log`, "training trace:" at line 11,
  step 0 at line 13, step 59 at line 72, `‖Δs‖` is column 8 (= 0.905 on every one
  of the 60 rows in between).
- Table 1 LoRA: `logs/20260601T033530_verbose.log`, header line 11, step 0 line 13
  (`‖Δs‖`=1.18), step 59 line 72 (`‖Δs‖`=1.31, with conf=1, kl+ 1.86, cos -0.061:
  the LoRA adapter actively moved).
- Table 2: pueue task 5 (`scripts/c_sweep_eval.py`), log line format
  `c=X: authority=Y (Δ...)` at timestamps 09:16:18 (c=0), 09:23:52 (1.5),
  09:31:21 (2.0), 09:38:47 (3.0), 09:46:17 (4.0), 09:53:47 (6.0). Caveat: the
  pueue live-log buffer has since truncated to the last two lines (c=4, c=6); the
  earlier four points are from in-session capture at those timestamps, not
  currently re-readable from `pueue log 5`.

`‖Δs‖` is flat at 0.905 for all 60 PiSSA steps while the LoRA arm grew 1.18 to
1.31. Δauthority stays within +-0.002 and is non-monotone in c.

**Discussion (speculative).** My read: the PiSSA adapter is frozen at its
initialization, so entry (a)'s "on-manifold remix" interpretation is downstream
of an artifact, the adapter barely differs from the SVD identity it started at.
Mechanism: commit ea4e17b inflated the global Δs init 100x (to norm ~0.9) and
paired it with a large lr, but only on a per-profile override; profiles without
that override (the two uncommitted 27b-pissa ones I added this session) inherited
the big init at the default lr=1e-4, which cannot move a 0.9-norm vector in 60
AdamW steps (~3e-3 of travel against a 0.04-per-element init). The LoRA arm,
zero-ish init, moved under the same lr. The non-monotone c-sweep is consistent
with baking a near-identity direction: pure noise, no real axis to scale. The
only PiSSA profile that ever showed `‖Δs‖` growing (to ~2) is `gemma-2b-pissa`
(lr=2e-2). Alternative hypothesis I cannot fully exclude from these logs: `‖Δs‖`
is init-norm-dominated and blind to a real-but-small rotation of Δs at constant
norm; distinguishing needs a fixed-C run (now that train-C=1.0) reading whether
nll+ descends cleanly, which the prior per-step C jitter smeared. But the
behavioural c-sweep (Table 2) independently shows no scalable effect, so even if
some rotation occurred it bought nothing measurable.

**Next.** (1) Fork for the user: run committed `gemma-2b-pissa` (lr=2e-2, proven
to grow `‖Δs‖`) to reconfirm PiSSA steers at all, or graft its lr=2e-2 / wd=1e-5
/ min_steps=120 onto a fresh 27b/bf16/r=256 profile. (2) Consider reverting the
adapter.py init to ~0 (principled null intervention) so init and lr stop being
coupled hacks. See memory `pissa-frozen-init-lr`.
