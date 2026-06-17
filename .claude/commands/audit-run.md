---
description: Audit the current (or named) run — narrative for the human, quoting every stage.
argument-hint: [slug] [mode:aggressive|patient]
---

Audit the agent run. Default to the latest slug under `out/iter/` unless an
explicit one is passed.

## What this audit IS

A narrative reconstruction of the run, written for a human who was not watching.
Walk the pipeline round by round and, at each stage, show three things:

  1. What the teacher SAW (the input it was judging — quote a snippet).
  2. What the teacher DID (its tool-call judgment — quote it verbatim).
  3. What the teacher SAID about it (its feedback/comment — quote it).

Then read the underlying artifact YOURSELF and say, in your own words, whether
the judgment follows from what it saw. The teacher is a weak qwen-9b; you are the
stronger reader. Your job is not to ratify it and not to grade it against a
rubric of known failures — it is to make the run legible and to flag, with
quotes, anywhere the teacher's conclusion does not match the evidence under it.

Two standing rules:
- QUOTE, don't summarise. Every claim carries a verbatim quote + the file path it
  came from. "The artifact is missing" is itself a quotable finding.
- Don't hand the agent a verdict. Below are QUESTIONS to answer by looking, not
  thresholds to match. If you arrive with "I'm looking for off-policy imbalance"
  you will find it whether it's there or not, and you'll skip the stage that
  actually broke. Look first, name what you see, then judge.

## Gather (no GPU, cheap)

1. Resolve the slug: if `$1` is given use it; else `ls -dt out/iter/2026*_iter_*/ | head -1`.
2. Find the pueue task id by matching the slug path in `pueue status`. If no live
   task matches, it's a post-mortem (no kill, just the narrative).
3. `pueue log $ID --full > /tmp/audit-$ID.log`, then read with offset/limit (never
   paste the whole thing). This log + `just thoughts <slug>` are your only window
   onto the agent's monologue and its REJECTED / RETRIED tool calls — pull both.
4. List the round dirs and the artifacts present in each (`ls out/iter/<slug>/round*/`).
   Note any round missing an artifact the others have — a gap is a finding.

## The round-by-round narrative

For EVERY kept round (and spot-check at least one drop), walk the stages in
pipeline order. For each stage produce this block — fill all four lines, even
when the stage looks clean (a stage you skip is a stage you didn't read):

```
STAGE <n> <name>  (round NN)
SAW:      <verbatim snippet of the input the teacher was judging + file path>
JUDGED:   <verbatim tool-call output / artifact value + file path>
SAID:     <verbatim teacher feedback/comment for this stage, or "(none logged)">
VERIFY:   <you read the artifact: does JUDGED follow from SAW? quote the bit that
           confirms or contradicts it. one or two lines.>
```

Stages and the questions to answer by looking (these direct attention; they do
NOT tell you what a bad answer is — that's the point):

1. choose_focus — `choose_focus_judgment.json`. Which `persona_pair_id` and why
   (quote `evidence`)? Now read the same `evidence` field across ALL kept rounds
   in sequence and quote them back to back: are the axes genuinely different, or
   the same underlying contrast relabelled? Quote what you see and let the human
   judge.
2. candidates — `candidates.json` (`items[].candidates`, each with `cho`/`rej`/
   `unprompted`/`flags`/`kept`). Quote one full candidate the teacher SAW (prompt,
   cho, rej). Is the prompt a fresh scenario or the same situation as other rounds?
3. rate_candidate — `candidate_ratings.json`. How many candidates existed, how many
   did the teacher rate, how many did it keep? Quote 2-3 ratings verbatim
   (`on_axis_variation_likert`, `off_axis_variation_likert`, `confounding_likert`,
   `keep`, `comment`). Do the comments describe the cho/rej it actually saw, or
   are they generic? Reconcile the counts with `selection_audit.json` (generated →
   flag-clean → rated → selected): does every number account for the one before it?
   Quote `selection_audit.json:rubber_stamp_flag` and `n_keep_true`/`n_rated`: if the
   flag is true (every rating identical), the teacher Likert did NOT discriminate —
   say whether the uniform bank looks genuinely clean or rubber-stamped, with quotes.
4. pairs — `pairs.md` and `selected_pair_review.md`. Quote 2-3 (cho, rej). Read
   `docs/how_to_rewrite_pairs.md` and check them against it in your own words.
   Measure cho vs rej length (cheap python over pairs.md) and report the numbers.
5. train_student — paste the training table VERBATIM (it's data, not diagnosis;
   see "Raw tables" below). Then answer by reading it: did nll+ and nll- go down?
   did train and val move the same way or diverge? did training stop early or run
   to the cap — and where was the val minimum relative to that? how many train
   pairs and val pairs (`n_train_pairs`/`n_val_pairs`)? If a column you'd want
   isn't logged, say which and stop — don't infer it.
6. calibration — paste the c_scan table VERBATIM. What `signed_C` was baked, and
   what did the scan do to get there (start c, walked up/down/not at all)? Read
   the `pmass`/`json`/`rep`/`len` columns at the top c and at the baked c and
   quote them: did the canary separate the steered model from base at all, or not?
7. mark_exam (keep/drop) — `judgment.json`. Quote `action`, `drop_cause`,
   `reasoning`, `harness_feedback`, `movement`, `next_focus`. `drop_cause` is
   `kept`/`gate_friction`/`no_movement`/`early_abort`: a run of `gate_friction`
   drops means the teacher could not satisfy a gate (unfollowable brief), NOT a
   cautious teacher — count them across rounds and say which kind of drop run this
   is. Then open `interview_pre.json`
   and `interview_post.json` for the seat(s) the teacher cites and read the actual
   turns. Quote PRE and POST side by side: is the cited movement a real change in
   reasoning, or the same point reworded? Let the quotes carry it.
   Cross-check `eval.json` if present: quote round00 base top1 vs the latest base
   top1 and report the delta as a number.

## Metric glossary (definitions, NOT verdicts)

So you read the columns correctly without me telling you what a good/bad value is.
These say what each number MEASURES; you judge whether the value is good.

- `nll+` / `nll-` — mean negative log-likelihood (nats) of the cho pole under +C
  and the rej pole under -C. Absolute nats, NOT a ratio. Lower = the model finds
  that pole more likely. `nll+` alone is not a ratio — compute nll+/nll- yourself
  if you want the pole balance.
- `val_nll+` / `val_nll-` — the same on HELD-OUT pairs the adapter never trained
  on. `val_improvement` = step0 val_nll+ minus best val_nll+. `n_val_pairs` is how
  many held-out pairs it averages over (a delta over 1 pair is one sample).
- `kl+` / `kl-` — KL(steered‖base), divergence of the adapted model from base. It
  measures how far the adapter moved, NOT coherence and NOT correctness.
- `signed_C` (a.k.a. c) — the baked steering multiplier on the weight delta. It is
  UNBOUNDED; c=1 is the trained strength, not a ceiling or "full." c_scan only
  ever walks c DOWN from the profile's init.
- `pmass` (mean_pmass_allowed) — mean probability mass the model puts on the K
  allowed answer tokens at the forced-choice answer slot. It is a COHERENCE floor
  (higher = more coherent / on-register); it is NOT a steering-strength or
  separation measure. A high pmass at c>0 means "still coherent," not "steered
  hard." Near-baseline pmass at the top c means the probe could not tell the
  adapter from base there.
- `valid_json` — count of long probes (out of N) that emitted parseable JSON. A
  coherence signal (free-gen didn't collapse).
- `rep` / `rep_min` / `distinct3` — token-trigram diversity over multiturn gens.
  Low = a repetition loop.
- `mean_p[foundation]` (eval.json) — average probability over the 7 moral
  foundations across tinymfv vignettes. `top1_acc` — first-choice agreement with
  the Clifford-2015 human label. These are the INDEPENDENT measure (not the
  teacher's Likert).
- `movement` / `movement_mean` (judgment.json) — the TEACHER's own PRE→POST Likert
  delta on the `_1p` seats (-5..+5). This is the teacher judging itself; treat it
  as a claim to verify against the interview text and the independent eval, not as
  ground truth.

## Design context you must know (so you don't prescribe a regressive fix)

The PRE/POST interview probes are 3 FIXED held-out `tiny-mfv classic` vignettes
(hospital discharge, exam cheating, political coercion), while training
candidates are sampled from `tiny-mfv scifi` (tax-droids, guild-masters, etc.).
This domain gap is DELIBERATE: it is an out-of-sample scifi->classic
generalization check (`src/csm/gen/probes.py` docstring). So:

- "The training pairs are a different domain than the PRE probe" is NOT a bug and
  NOT contamination. Do NOT recommend domain-aligning the training to the probe;
  that would let the model pass by memorising domain-specific actions and would
  defeat the character-vs-performance test (CLAUDE.md "probe for character").
- A probe that does NOT move is evidence the intervention was too SHALLOW /
  domain-specific to generalise, which points to a deeper axis or better
  pairs/training, NOT to matching the domains.
- If the teacher's `harness_feedback` calls this gap "cross-domain contamination"
  and tries to fix it by domain-matching, quote that as a BRIEF gap (the teacher
  was not told the gap is intentional), not as a harness bug to fix by alignment.

## Raw tables (paste, don't paraphrase)

The human wants to read these directly. Find them in the pueue log / train output
and paste verbatim into the report:
- the per-step training table (and the separate val-trace table if the run logged one)
- the full c_scan / calibration table

Numbers are evidence; pasting them is not "diagnosis." Do NOT annotate each row
with a verdict — paste the table, then write your reading below it in prose.

## Agent feedback digest

Collect, across all rounds, every place the teacher told us something about the
task itself — quote them together so the human can see the pattern:
- `judgment.json:harness_feedback` and `next_focus` (every round)
- any exit-interview / "what was confusing" comments in the log
- `candidate_ratings.json` comments that complain about the candidates or the brief

This is how the weak teacher reports where the brief is unclear. It is the most
direct signal for fixing `prompts.py`, and it's the thing audits skip. Always
include it.

## Mistake / retried tool calls

From the pueue log and `just thoughts`, list every tool call that was REJECTED by
a gate, raised a ValidationError, or was retried. For each: which tool, what the
gate/error said (quote it), and what the agent did next. A teacher fighting a gate
repeatedly is telling us the gate text or the brief is wrong — surface it, don't
let it hide in the log.

## Report format

```
=== audit: <slug> (task $ID, mode=<aggressive|patient>) ===

# Timeline
rNN  action(keep/drop/incomplete)  persona_pair  signed_C  movement_mean  Δtime
... one line per round ...

# Round-by-round narrative
... the STAGE blocks above, grouped by round ...

# Raw tables
... pasted training + calibration tables ...

# Agent feedback digest
... quoted harness_feedback / next_focus / candidate comments ...

# Mistake / retried tool calls
... quoted gate rejections + what the agent did ...

# Completeness
stages judged: N/7 per round; could not judge: <which + why (missing artifact)>

# For the human to decide: CONTINUE | INVESTIGATE | KILL+FIX
<evidence-first: cite the quotes above; if recommending kill, the root cause is a
 quote, not a guess>
```

## Mode (second arg, default `aggressive`)

- aggressive — iterating fast on harness/prompts; lower the bar to recommend kill+fix.
- patient — committed to a long run; only flag hard failures (crash, retry loop).

## Hard-failure observations (state if present; don't auto-act)

- Crash / traceback / OOM / CUDA error in the pueue log.
- A tool retried ≥3 times without progressing (quote the loop).
- A long unbroken drop streak (≥3 aggressive, ≥5 patient) — quote each drop reason.

If running and you recommend CONTINUE/INVESTIGATE: schedule the next checkpoint
with `ScheduleWakeup` (typical: +20 after t+10, +30 after t+30, then stop). Skip
if the user passed a slug explicitly (one-shot post-mortem).

If you recommend KILL+FIX: do NOT auto-kill. Print the kill command and the
proposed fix (specific file + change), then stop and wait for confirmation.
Kills + restarts touch shared state.
