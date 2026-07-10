# W2S trajectory plan: from 1-keep-in-13 to keeps-as-the-norm

## Goal

Produce the strongest evidence this harness can give on the w2s hypothesis: a weak
teacher (qwen3.5-9b), by judgment alone, iteratively steers Qwen3.6-27B toward the
forethought character, visibly over a 12-round trajectory. Success mode is keeps as
the norm (user: "no reason we couldn't have them all if the process works"); a
root-caused NO (which rung of the ladder breaks) is an equally valid outcome.
Blocked-by-harness is the only failure.

## Scope

In: gate behaviour, pool screening for act-fork yield, trajectory runs, evidence
quality (independent measure headroom). Out: teacher model swaps (the 9b gap IS the
hypothesis), new losses, threshold re-tuning (tuning a veto is still a veto).

## Requirements

- R1 Harness never blocks judgment. Done means: a 12-round run with ZERO
  early_abort-on-count; every round reaches the A/B exam. VERIFY: every
  roundNN/judgment.json has drop_cause in {kept, no_movement, gate_friction} (never
  early_abort on a count), and submit_rejects.jsonl has no select_pairs count veto.
  Silent-failure check: an early_abort could hide as gate_friction — audit reads
  each drop's reject log, not just the cause label.
- R2 Banks fork. Done means: teacher-rated different_action pass rate rises from
  ~30% (task-136) to >=60%, so n_rank_filled ~0 in most rounds. VERIFY:
  selection_audit.json n_passing vs n_rank_filled per round; the teacher's own
  ratings are the instrument (its honesty was verified in the task-136 audit).
  Silent failure: forked-LOOKING pairs that fork on style — caught by the A/B exam
  dropping the trained adapter (drop with trained adapter = informative, log it).
- R3 Movement is real, not judge-flattery. Done means: keeps carry act-grounded
  PRE/POST quotes (different act or costlier held line, not paraphrase) AND at
  least one independent signal moves. VERIFY: cold /audit-run quotes PRE vs POST
  per keep; independent eval delta reported per kept round. KNOWN INSTRUMENT GAP:
  tinymfv top1 sits at 0.9545 baseline (ceiling); R5 addresses this. A keep with
  paraphrase-only quotes is a judge failure to log, not a win.
- R4 Trajectory composes. Done means: kept adapters accumulate without undoing
  each other. VERIFY: round N+1 PRE answers retain round N's kept movement (the
  next round's interview_pre IS the composition test); axis-recycling check (task
  #5): choose_focus evidence across kept rounds quoted side by side — different
  deficits, not one contrast relabelled with sign flips.
- R5 Independent measure with headroom. Done means: an eval that is NOT the
  teacher's own judge and NOT at ceiling. Candidate: score the fixed 14 _1p
  interview answers with a STRONG external judge (frozen rubric, blind
  PRE/POST, both orders) per round; tinymfv stays as the cheap sanity check.
  VERIFY: baseline sits mid-scale with visible variance across rounds.

## Tasks (phased; one attributable change per run)

- [x] T0 (R1): gate -> guidance. Landed: 374ec03 (count floor -> rank top-up),
  6a76c3e (dict-as-string coercion), 9aaf4f9 (gym stub floor), e7afb09
  (KeyError:146 sparse-sid crash, killed 137+138).
  - verify: run 139 (queued) completes 12 rounds
  - success: R1 holds; per-round A/B verdicts exist for every round
  - likely_fail: another latent bug in the other-session batched path (it was
    never run to completion) — crash in round00-01; requeue after root-cause
  - sneaky_fail: heavy rank-fills (n_rank_filled ~18/20) train style adapters
    that all A/B-drop — that is R2's problem showing through, NOT a gate failure;
    do not re-add a threshold, proceed to T1
  - UAT: /audit-run on 139's slug; table of per-round {action, drop_cause,
    n_passing, n_rank_filled, movement}
- [ ] T1 (R2): act-fork pool screen (user plan element 1 done properly).
  - steps: script (pattern: gym_question.py) — for each of 2550 pool rows,
    generate one (pos,neg) pole pair via OpenRouter student-class model with the
    LIVE persona template + PAIR_COMMIT_SUFFIX, judge different_action with the
    bench-validated ACT form; append-only corpus, cached, pennies-to-$20.
    Keep rows with fork yield; rebuild pool.
  - verify: screened-pool stats table (fork rate per source/axis); spot-read 10
    kept + 10 culled rows
  - success: screened pool >=800 rows with measured fork rate >=60% on-template
  - likely_fail: fork rate low EVERYWHERE -> the problem is persona/template not
    scenarios -> pivot to T1b (template fork-forcing) with the same corpus as
    evidence
  - sneaky_fail: screen model (OpenRouter bf16) forks where live nf4 doesn't —
    accept as known caveat (same as question gym), confirm on first live round
  - UAT: docs/results table + the corpus jsonl path
- [ ] T1b (R2, only if T1 shows template-level convergence): fold the teacher's
  r05 prescription into pair-gen prompts ("either do X and report it, or decline
  entirely"; CHO names the accepted cost). Validate in gym_persona_axis before a
  run. Teacher-facing: needs smoke-prompts.
- [ ] T2 (R5): interview judge with headroom. Score the 14 _1p PRE answers with a
  strong external judge on a frozen rubric; wire into csm eval as a per-round
  column. NOT a gate — measurement only.
  - verify: baseline run scores mid-scale, variance across questions
  - sneaky_fail: judge drift across rounds -> frozen prompt+model+temperature,
    score PRE and POST in the same call batch, both orders
- [ ] T3 (R2+R3): the evidence run — 12 rounds on screened pool + fixed harness.
  - success: majority keeps, act-grounded quotes per keep, independent measure
    moves; OR a clean NO with the failing rung named
  - UAT: cold /audit-run + journal + per-round evidence table, pushed
- [ ] T4 (R3/R4 standing): per-run cold audit + axis-recycling check (task #5) +
  canary-vs-interview loop gap (task #4) stay open until a trained round shows
  POST loops again (need live attribution).

## Decision points

- After 139: if R1 holds and fills are light -> skip straight to T3 with T1 pool.
  If fills heavy + exam drops -> T1 is the bottleneck, do it first. If crash ->
  fix, requeue, stay in T0.
- After T1: fork rate <40% even on screened rows -> the student's safety training
  is collapsing poles (the config's own "Qwen3.6 may hit the same neg-pole
  refusal" risk) -> evidence for a NO at the generation rung; consider gemma-4-31b
  student before concluding.
- All-drops WITH forked banks and clean training -> the failing rung is the
  A/B judge or the training itself; judgment_gym the judge before blaming w2s.

## Context

Teacher ladder: generate > edit > rate > select > bool (lean easy). Gates elicit
judgment, never override. One change per run for attribution. Evidence = artifact
links, not claims. Independent eval currently near ceiling (tinymfv top1 0.9545)
— treat "flat tinymfv" as expected until T2 lands, and say so in reports.

## Log

- 2026-07-10: T0 landed (374ec03, 6a76c3e, 9aaf4f9, e7afb09); run 139 queued.
  task-136 post-mortem: 1 keep/13, count floor killed 12 rounds; teacher honest;
  banks converge ~30% different_action.
