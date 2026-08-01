<!-- This prose is human-approved. Before editing, run the `humanizer` skill and keep the footprint minimal. -->
# `w2schar-mini` — algorithm pseudocode

Weak-to-strong iterated character steering. A weak teacher (qwen3.5-9b) curates
data and supplies blind before/after judgments; a fixed vote decides keep/drop.
A strong student generates and is steered. Three
parts compose:

1. Conditioned weight steering: one adapter (PiSSA by default, LoRA for nf4)
   with a scalar coefficient `c`. `c=0` is exact base; `c` scales the trained
   delta. `c` is not clamped to `[-1, 1]`; deploy `c` can exceed 1 if coherent.
2. Iterated rounds: kept adapters are baked for inference and applied through a
   gated history hook during training.
3. React-agent state machine: the teacher drives one round at a time; the
   harness enforces order and owns every number, path, and file.

The design pushes the weak teacher toward tasks it is more likely to do well:
selection, rating, and judgment. The stronger student generates both poles
on-policy, and the harness owns the bookkeeping, training, calibration, and
artifact checks. The teacher spends its budget judging text.

This is a modification of
[Weight Steering](https://github.com/safety-research/weight-steering), which
trains separate adapters on positive and negative completions and subtracts
their weight updates. This implementation trains one signed adapter on both
poles with a contrastive margin-NLL objective and a KL penalty. Persona-conditioned
student completions are stripped back into generated pairs and filtered as
strict contrasts; c-scan then calibrates the largest coherent deployment
strength. Some of these choices come from the contrastive-pair and calibration
lessons in my
[AntiPaSTO work](https://arxiv.org/pdf/2601.07473).

Code is the source of truth. File names point at the real implementation; this
document summarises it rather than redefining it.

---

## 1. Adapter (`ws/adapter.py`)

Two adapter classes, both forward-hook style (no module replacement, gradients
flow through the adapter params, `c` is a Python float).

`ModulatedLoRA`: `y = W x + c · (α/r) · B @ A @ x`. Init `A` kaiming_uniform,
`B ~ N(1e-4, 1e-4)`. `c=0` short-circuits the hook (no extra compute).

`ModulatedPiSSA` (default): `y = W_res x + U · ((S + c·Δs) ⊙ (Vh x))`. At init
`W` is mutated in place to `W_res = W − U_r S_r Vh_rᵀ` (the residual after pulling
the top-`r` singular directions), and the adapter steers those directions by
`Δs ~ N(4e-2, 4e-2)`. `c=0` is NOT a short-circuit for PiSSA (the residual split
already changed `W`), so its coherence baseline is computed, not assumed.

Asymmetric init rationale: pure-zero `B`/`Δs` leaves the `+c`/`−c` poles
symmetric at init (the loss is even in `c`), so the optimiser has no signed
gradient to break the tie. A tiny nonzero init breaks that symmetry before any
data is seen.

PiSSA needs writable float `W`, so it is incompatible with bnb quantisation;
`RunConfig._validate` raises on `pissa + quant` rather than silently picking one.
nf4 students therefore run LoRA.

---

## 2. Outer round loop (`pipeline.py`)

Base weights on disk are never modified. After round `N`, `roundNN/` holds
`adapter.safetensors` + `calibration.json` (with `signed_C`). Round `N+1` loads
the kept adapters as a gated history hook for training. Generation, dialogue,
and evaluation instead merge them temporarily inside a `baked()` context.

```py
kept = []                                  # round dirs with judgment.action == "keep"
for round in 0..N:
    model, tok, history_bake = load_base_with_history(model_id, kept)  # training
    run_round(model, history_bake, round_dir, agent)     # §5 state machine
    if read_judgment(round_dir).action == "keep":
        kept.append(round_dir)
    if n_drops >= MAX_DROPS or n_keeps >= max_rounds:     # run-level caps
        break
```

History gate: the `c=0` reference forward differs by adapter type:

| adapter | gate at train time | `c=0` forward returns |
|---|---|---|
| LoRA  | `lambda: lora._c != 0.0` | pristine base (history disabled) |
| PiSSA | no-op | base + kept history (already baked into `W`) |

So a LoRA round's KL is cumulative-from-pristine-base (a new adapter fighting a
prior bake pays its KL bill). A PiSSA round's anchor is the prior-baked state.
C-scan and post-eval always read base+history as their `c=0` reference (the
deployed model just before this round's adapter kicks in).

---

## 3. Inner training step (`train.py`)

One forward pass per pole (cho, rej), each at `c = ±1`. `C` is fixed at `1.0`
so train-c and inference-c coincide; the earlier per-step
`C ~ U` sampling is gone.

Loss is a margin-NLL on both poles plus a KL anchor:

```py
for step in 0..T:
    (ids_p, lbl_p), (ids_n, lbl_n) = batch(pairs)   # lbl = -100 on prompt, ids on completion
    # reference: c=0, no grad (LoRA gate -> pristine base)
    with lora(model, c=0.0), no_grad():
        logp_base = log_softmax(model(ids).logits)

    with lora(model, c=+1.0):                        # cho pole
        nll_cho = ce(cho)                            # HF mean-CE over completion tokens
        nll_rej_plus = ce(rej)
    with lora(model, c=-1.0):                        # rej pole
        nll_rej = ce(rej)
        nll_cho_minus = ce(cho)

    # margin: pull the on-pole NLL down; cap the off-pole push
    L_pos = nll_cho - normed_mean(nll_rej_plus)      # push uses normed_mean (capped)
    L_neg = nll_rej - normed_mean(nll_cho_minus)     # pull stays raw .mean()
    L_kl  = β * topk_kl(logits, logp_base, K=256, mask=lbl != -100)

    if dot(∇L_pos, ∇L_neg) < 0:                      # PCGrad only on the margin pair
        g_margin = pcgrad_project(∇L_pos, ∇L_neg)
    g = g_margin + ∇L_kl                             # KL added unprojected
    adamw.step(g); onecyclelr.step()
```

Notes:
- Subtracting the off-pole NLL cancels the shared-fluency direction, so the
  gradient credits the contrast, not generic likelihood.
- KL is a reverse-KL over the base model's top-K (`K=256`), K-renormalised.
  It is an opposing objective by design, so it is added
  unprojected (projecting it would silently weaken it). `β = kl_lambda`.
- `steps` is driven entirely by `n_epochs`: `steps = ceil(steps_per_epoch *
  n_epochs)`.
- The full `steps` run produces the val trace, but the deployed weights are the
  val-nll+ minimum (post-warmup), with a patience-3 early break.
  `val_improvement` is logged as guidance; it gates nothing.

---

## 4. C-scan (`ws/c_scan.py`)

After training, calibrate the signed `c` stored in `calibration.json` by walking
`|c|` DOWN from `init_c = signed_C` until a coherence canary passes, then bake at
that `c` (`backoff = 1.0`). The canary is three AND-gated signals, each
self-relative to the `c=0` baseline (base + kept history):

| signal | measures | gate |
|---|---|---|
| `pmass_allowed` | forced-choice answer-slot mass over K=7 allowed tokens | `≥ gate_frac · base` |
| `valid_json`    | long questions still emit parseable `{"ans": bool}` | `≥ 1.0 · base` (strict) |
| `distinct3`     | multiturn trigram diversity, gated on the minimum question | `≥ rep_frac · base` (`rep_frac=0.75`) |

```py
C_MIN, MAX_QUESTIONS, STEP = 0.05, 9, 2/3

def c_scan(model, lora, init_c, sign):
    base = measure(c=0.0)                 # pmass, valid_json, rep at the c=0 reference
    c = init_c
    for i in 0..MAX_QUESTIONS:
        m = measure(c = sign * c)
        ok = (m.pmass >= gate_frac*base.pmass and
              m.valid_json >= 1.0*base.valid_json and
              m.rep_min >= 0.75*base.rep)
        if ok and i > 0: break           # i==0 is forced to step down at least once
        c *= STEP
        if c < C_MIN: raise RuntimeError(f"no coherent c; trace={trace}")
    return sign * c                       # baked at the passing c; NOT clamped to 1
```

- The sign is fixed by the character axis (the teacher writes the positive pole as the
  trait to grow; it never picks the sign).
- The first coefficient tested is forced to fail (`i>0` guard), so the
  deployed `c` is at most `init_c · 2/3`.
- A fwd/bwd p95 KL is logged alongside as a diagnostic; it is NOT gated (high KL
  can accompany the intended steering change).
- Mass-on-base's-top-K as a coherence gate is gone (an early version tried it; a
  teacher-forced top-K mass never sees the steered model's own emissions, so
  autoregressive collapse is invisible).

Interview replay (`interview_{pre,post}.json`): the same fixed questions, greedy
decoding, byte-identical pre vs post, so only the model's output varies.

---

## 5. State machine + agent tools (`agent.py`, `state.py`)

The teacher (qwen3.5-9b via inspect-ai react) drives one round. States enforce
order; a tool called out of state raises `ValidationError` and the `on_continue`
nudge names the next valid action.

```
state ∈ {choose_focus, select_pairs, train_student, mark_exam, done}
```

Live tools: `choose_focus`, `view_pairs`, `rate_pair`, `select_pairs`,
`train_student`, and `mark_exam`.

```py
# state = choose_focus: teacher reads the pre-dialogue transcript + history
choose_focus(persona_pair_id, scenario_family, mismatch_severity, headroom,
             bank_cleanliness, evidence, pre_scores, pre_question_evidence):
    # SELECT a measured character axis from the frozen persona-pair library; do NOT invent
    # a free-text axis. The student then generates pairs on this axis:
    #   for each scenario: cho under pos_persona, rej under neg_persona, at c=0,
    #   personas stripped -> contrastive (cho, rej) in the student's own voice.
    state := select_pairs

# state = select_pairs: teacher reads and rates every generated pair
view_pairs() -> the next (prompt, cho, rej) pair
rate_pair(contrast, different_action, axis_contrast,
          refusal_confound, length_confound, incoherent_confound)
select_pairs(lesson):
    assert all generated pairs rated; ratings choose the selected pairs; writes pairs.md
    state := train_student

train_student():
    train_inner(model, pairs)            # §3
    signed_C = c_scan(model, lora)        # §4
    save adapter.safetensors, calibration.json
    post = dialogue(model @ signed_C, questions); save interview_post.json
    state := mark_exam

# state = mark_exam: blind two-pass A/B judgments determine the call
mark_exam(harness_feedback):
    directions = blind_ab_judge(pre, post, both_orders=True)
    keep = more_questions_post_wiser_than_pre_wiser(directions)
    write ab_judge.json, judgment.json
    state := done
    # outer loop: if keep, kept.append(this round)
```

The active persona-pair library is `cfg.persona_cells` and varies by profile.
Each profile also restricts the available scenario families.

Run-level caps stop a run after `MAX_DROPS` or after the keep target plus that
drop budget. `MAX_SUBMIT_REJECTS` drops a round that cannot complete its tool
calls. The current values live in `agent.py` and may be set by the run environment.

### A round, as the teacher drives it

```
choose_focus(...)        -> freezes PRE and generates pairs
view_pairs()             -> shows one full Cho/Rej pair
rate_pair(...)           -> records its contrast and confound ratings
...                      -> repeats until every generated pair is rated
select_pairs(lesson=...) -> ratings select the training pairs; writes pairs.md
train_student()          -> trains, calibrates c, and writes interview_post.json
mark_exam(harness_feedback=...)
                         -> blind A/B judge votes; writes ab_judge.json + judgment.json
```

A tool called out of state, such as `train_student` before `select_pairs`, raises
`ValidationError`; the `on_continue` nudge names the next valid action and the
teacher retries.

### What the teacher sees vs doesn't

| sees (in chat) | doesn't see (sidecar / harness-private) |
|---|---|
| pre/post dialogue transcripts | per-token KL, NLL, pmass numbers |
| generated (cho, rej) pairs, ratings | batch size, lr, β, the `signed_C` value |
| history summary (axes tried, keep/drop) | adapter rank, layer range, dtype |
| `ValidationError` with the next valid action | c-scan walk, pmass per question |

The teacher selects pairs from their text and supplies blind before/after
judgments. The harness aggregates those judgments into the fixed keep/drop vote.

---

## 6. Config + outputs

Hyperparameters are named profiles in `CONFIGS` (`config.py`), keyed by a slug;
the teacher never sees them. `_validate` rejects illegal combinations (pissa+nf4,
unknown scenario family). `just profiles` prints the current values.

Post-hoc evaluation: `csm eval` runs tinyMFV on each checkpoint, writing
`eval.json` / `eval_post.json`, then builds `index.html` via `plot.py` (scatter +
timeline). Per-round artifacts include `state.json`, `scenarios.json`,
`gen_pairs.json`, `choose_focus_judgment.json`, `gen_pair_ratings.json`,
`selection_audit.json`, `pairs.md`, `selected_pair_review.md`,
`adapter.safetensors`, `calibration.json`, `interview_{pre,post}.json`,
`ab_judge.json`, `judgment.json`, and `eval.json`.
