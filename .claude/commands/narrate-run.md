---
description: Narrate a run — per-round personas, judgment, behaviour, tool calls — with your own opinion, not the teacher's.
argument-hint: [slug]
---

Narrate an iterated-steering run as a story, and judge it yourself. Default to the
latest slug under `out/iter/` unless `$1` is passed.

The point is NOT to repeat the teacher's `judgment.json`. It is to read the same
evidence the teacher saw (and the c_scan the teacher did NOT see) and form your own
view of whether each round actually moved behaviour, where the axis got confounded,
and whether the run is converging or spinning.

## Resolve

- slug = `$1` or `ls -dt out/iter/2026*_iter_*/ | head -1`.
- task id = match the slug path in `pueue status` (may be a finished/post-mortem run).

## Read per round (cheap, no GPU)

For each `round*/` in order, pull:

- `pairs.md` — the `## Lesson` (the persona/axis this round teaches) and the
  `### Rej`/`### Cho` twins. This is the training signal.
- `judgment.json` — the teacher's `action` (keep/drop), `reasoning`, `next_focus`.
- `interview_pre.json` / `interview_post.json` — the actual behaviour, per probe.
  The first assistant turn per probe is the answer; compare PRE vs POST.
- `calibration.json` — `signed_C` (baked steering strength) and `cscan_trace`
  (how far c walked down, and why: `pmass`, `valid_json`, `mean_len`, the `note`
  field = pass/fail/fail-rep). This is the coherence story the teacher never sees.

Tool-call sequence + agent monologue (only if behaviour looks off, or asked):
`just thoughts out/iter/<slug>` — reasoning + submit_pairs/train_student/mark_exam
calls from the inspect samplebuffer (live) or eval log (done).

## Forcing questions — answer each, per round, from the evidence

1. **Persona/axis**: what disposition does the Lesson name, and do the Cho twins
   actually encode THAT — or a confound? Check: do all Cho share a template/opener?
   Is Cho length-matched to its Rej (eyeball, or `len`)? A shared refusal-template or
   a systematic length gap means the adapter axis = template/length, not the stance.
2. **Behaviour (your read)**: pick 2-3 probes. Did POST move on the axis vs PRE, or
   only on a confound (more polite / longer / more hedged / just reformatted)? Quote
   the specific PRE→POST shift. Was the base model already at the target pole (no room)?
3. **Steering strength**: what `signed_C` did it bake, and why that low/high? Walk the
   `cscan_trace`: which c failed and on what signal (pmass collapse? valid_json drop?
   mean_len blow-up = repetition?). Big stable c = good; tiny c (≲0.2) = the adapter
   couldn't be pushed without breaking coherence.
4. **Judgment (do you agree?)**: the teacher kept/dropped — on this evidence, would
   you? Name where you diverge and why. A keep on a confound or on an already-aligned
   probe is a weak keep; say so.
5. **Tool calls**: how many submit_pairs before train (rejects = teacher fighting the
   gates)? Any drop streak? Clean = 1 submit → train → mark_exam.

## Report

```
=== narrate: <slug> (task $ID) — adapter=<lora|pissa> ===

ROUND 00 — "<lesson, one line>"
  pairs:     <twin quality: confounded? template? length-matched?>
  behaviour: <your PRE→POST read, 1 quoted shift, "room?" verdict>
  steering:  signed_C=<x> — <why; cscan one-liner>
  judgment:  teacher=<keep/drop>; you=<agree/diverge + why>
  calls:     <n submit / n train / verdict>

ROUND 01 — ...

ARC: <is the axis sharpening or drifting across rounds? is signed_C growing or
     collapsing? did next_focus get acted on?>
VERDICT: <did this run demonstrate steering, or just plumbing? 2-3 lines, your
         own judgment, specific. If comparing adapters, say which steered harder
         and stayed coherent.>
```

Keep each round ≤ 6 lines. Quote evidence; don't hand-wave. If `interview_post` or
`calibration` is missing (round mid-flight), say so and narrate what exists.

For a long/thorough run, spawn the read as a subagent (`Explore` or general-purpose)
so the file dumps stay out of the main context and you get back just the narrative.
