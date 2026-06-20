# w2schar-mini

Minimal weak-to-strong iterated character steering. A weak teacher steers a
stronger student toward the moral character described in
[docs/2026_forethought_on_the_importance_of_ai_character.md](docs/2026_forethought_on_the_importance_of_ai_character.md)
by changing how it reasons about when to act. The target is not a single "less
authority" reflex; that collapse mode is audited in `.claude/commands/audit-run.md`.
This is a smaller, single-path distillation of
[wassname/w2s-ics-cws](https://github.com/wassname/w2s-ics-cws).

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

```py
# ── adapter forward (per target Linear; W frozen; c=0 short-circuits) ──
y = x @ W.T  +  c * (α/r) * ((x @ A.T) @ B.T)         # A ~ kaiming, B ~ N(1e-4, 1e-4)

# ── outer loop: kept adapters compose via gated history hook ──────────
kept = []
for round in 0..N:
    model, history_bake = load_base_with_history(model_id, kept)
    # gate: history active iff new round's c≠0  → c=0 KL ref is pristine base.
    A, B = small_random_asymmetric()
    choose_focus → select_pairs → train → judge
    if judgment.action == "keep": kept.append(round)

# ── inner train step (margin-NLL + KL; c fixed at ±1 in training) ─────
for step in 0..T:
    with lora(c=0), no_grad(): logp_base = log_softmax(model(ids).logits)   # pristine
    with lora(c=±1):
        nll_cho, nll_rej = ce(cho|+1), ce(rej|-1)     # HF mean-CE over completion
        L_margin = (nll_cho - cap(nll_rej)) + (nll_rej - cap(nll_cho))  # cap the push (off-pole) term; on-pole pull stays raw
        L_kl     = β * topk_kl(logits, logp_base, K=256, mask=lbl != -100)
    g = pcgrad(∇L_margin_pos, ∇L_margin_neg) + ∇L_kl  # PCGrad on the margin pair; KL unprojected
    adamw.step(g)

# ── c-scan: walk c DOWN from signed_C until the coherence canary passes ─
# canary = 3 AND-gated signals, each self-relative to the c=0 baseline:
#   pmass_allowed ≥ gate_frac·base   (forced-choice answer-slot mass)
#   valid_json    ≥ 1.0·base         (long probes still emit parseable {"ans": bool})
#   distinct3     ≥ rep_frac·base    (multiturn trigram diversity; catches loops)
# start at init_c = signed_C, step ×2/3 down (forced ≥1 step), bake at the passing c.
signed_C = sign * c_at_first_pass                     # NOT clamped to 1; deploy c can exceed 1
```

Full pseudocode (with the §2 c=0 gate table, c-scan bounds, KL/NLL mask
alignment, state-machine ordering, and what the agent sees vs doesn't)
is in [`pseudocode.md`](pseudocode.md).

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

# Any profile (see `just profiles`), N keep-rounds:
just run qwen-27b-nf4 5
```

## Profiles

Model and hyperparameters are named profiles in `src/csm/config.py`, not
command-line flags. `just profiles` lists them. Pick one; don't hand-set
hyperparameters.

Adapter and quant are linked: bf16 can run pissa (the default) or lora; nf4
must run lora (PiSSA mutates float weights, which nf4 buffers don't allow). A
27B student only fits in nf4 here, so it runs LoRA. `RunConfig._validate`
raises on an illegal pissa+nf4 combination rather than silently picking one.

## Migration / new machine

`pyproject.toml` pulls tinymfv from its upstream git repo. The run history lives
in `RESEARCH_JOURNAL.md`; `out/` is gitignored and does not travel.

## Differences vs `weight-steering-lite`

| | wsl | mini |
|---|---|---|
| axes | free-form (7 moral foundations) | teacher-chosen per round, target = principled moral character (watch for collapse to a "less authority" reflex) |
| pairs/round | 200 | 15 selected from student-generated persona-template candidates |
| eval | inline tinymfv per round + Likert | post-hoc `csm eval` (tinymfv, 132 vignettes × 1 condition) + c-scan |
| tools | dialogue, gen, edit, drop, read, train, pass, exit_interview (+local_bash) | choose_focus, read_candidate, rate_candidate, select_pairs, train_student, mark_exam, revert_round |
| state | implicit (any tool any time) | choose_focus → select_pairs → train_student → mark_exam → done (enforced) |
| code | ~7,000 LoC | ~1.5K LoC |

The remaining core pieces mirror `w2s-ics-cws`: CWS math, history bake, PCGrad,
KL anchor, and agent-as-teacher.
