"""Per-model run config registry.

Lifted from `weight-steering-lite/src/wsl/prompts.py:CONFIGS`, trimmed
to the two profiles we plan to validate first. Hard-won numbers stay
here (the agent never sees them).
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

from csm.gen.prompts_pool import SCENARIO_FAMILIES
from csm.prompts import (CORE_THREE_AXIS_PERSONA_CELLS, DEFAULT_PERSONA_CELLS,
                         DEFAULT_PERSONA_TEMPLATES, DISCERNMENT_PERSONA_CELLS,
                         MULTI_AXIS_PERSONA_CELLS, WELLBEING_SMOKE_PERSONA_CELLS)

# Teacher sampling, single source for live (agent.py) + gym: Qwen3.5 card "Thinking mode, general tasks" -- greedy breaks thinking mode, presence_penalty=1.5 is the anti-loop lever.
TEACHER_SAMPLING = dict(temperature=1.0, top_p=0.95, top_k=20, presence_penalty=1.5)
# Teacher reasoning budget (live): backstop for non-termination only, above qwen3.5-9b's 17-29k output-tok/task envelope (Artificial Analysis Intelligence Index); presence_penalty handles loops, this just kills infinite ones.
TEACHER_REASONING_TOKENS = 40000
# OpenRouter routing: prefer DeepInfra but allow fallback (cheaper/consistent quant on qwen). Passed as extra_body to the OpenAI-compat client; "order" is a preference, allow_fallbacks keeps the run alive if DeepInfra is down.
OPENROUTER_PROVIDER = dict(order=["deepinfra"], allow_fallbacks=True)


@dataclass
class RunConfig:
    model: str
    """HF model id, e.g. 'google/gemma-2-2b-it'."""
    teacher: str
    """OpenRouter id for the teacher LLM that drives the inspect-ai react agent.
    The teacher IS the judge: the same react agent chooses the axis/family,
    selects among generated candidate pairs, and calls commit_round (keep/drop).
    w2s lives in this weak SUPERVISOR selecting from the strong student's own
    on-policy generations."""

    # ─ adapter ─
    adapter: Literal["lora", "pissa"] = "pissa"
    """`pissa` = top-r SVD of W physically extracted into the adapter (W
    mutated to W_res); trainable Δs reweights each singular direction —
    remixes the model's existing principal directions. `lora` = free
    rank-r perturbation (B@A); kept as a baseline. PiSSA needs larger r
    since the expressive space is tighter (override per profile)."""
    lora_r: int = 16
    """Rank for both LoRA (B@A) and PiSSA (top-r SVD). Default 16 suits LoRA;
    PiSSA profiles override to ~10% of hidden_dim (e.g. 256 for gemma-2b)."""
    lora_alpha: float = 32.0
    """LoRA only; ignored for PiSSA (forced α=r so α/r=1)."""
    targets: tuple[str, ...] = ("all-linear",)
    layer_range: tuple[float, float] = (0.2, 0.8)
    """Depth band as (lo, hi) fractions of total transformer blocks. Default
    keeps the middle 60% — early layers are too feature-shallow and late
    layers too task-specific for stable persona steering. (0.0, 1.0) = all."""

    # ─ quantization ─
    quant: str | None = None
    """None = bf16 load; 'nf4' = BitsAndBytesConfig nf4 load (for 27b+ on
    96GB GPU). LoRA hooks still cast x→bf16, so adapter math is unchanged.
    Bake uses the quant backend (stacked-LR hook) for these layers."""

    # ─ training ─
    lr: float = 1e-4
    weight_decay: float = 0.01
    kl_lambda: float = 0.5
    warmup_ratio: float = 0.1
    """Fraction of `steps` for cosine warmup. Default 0.1 (e.g. 24 steps of
    240). Larger models on harder per-pair data (qwen-27b nf4) spike at
    the warmup ramp's high-lr edge; stretch warmup so the adapter has more
    sub-spike-lr steps to learn the easy signal first."""
    grad_clip: float = 1.0
    """Pre-clip ‖g‖ cap. Default 1.0 fits gemma-2b/qwen-9b (typical ‖g‖ 1-5).
    qwen-27b-nf4 produces median ‖g‖ ~17, p90 ~140 — clip=1 binds on ~99%
    of steps and turns the adapter into a unit-direction-only update,
    which calibrates to absurdly small |c| (0.05 in task 100) because the
    learned direction is over-concentrated on the few clean-grad steps."""
    train_batch_size: int = 4
    n_epochs: float = 3.0

    # ─ dialogue ─
    eval_batch_size: int = 4
    dialogue_max_new_tokens: int = 1024
    """Per-turn gen cap for interview + c_scan probes. Coherent answers run
    ~325 tok/turn, so 1024 keeps them (and their JSON tail) whole while halving
    the runaway-gen budget an incoherent adapter spends (task25 hit ~3k tok at
    c=1.5). Shorter = faster c_scan and less room to spiral."""
    enable_thinking: bool = False     # Qwen3 family
    cscan_n_vignettes: int = 2
    """Number of tinymfv vignettes used inside c_scan's OOD pmass canary.
    Real profiles keep this >0. Smoke profiles set it to 0 because the tiny
    random harness test should not depend on tinymfv package data being present."""
    cscan_max_think_tokens: int = 512
    """Think-token budget for the tinymfv forced-choice (pmass) in c_scan calibration.
    512, not more: gemma never emits tinymfv's close token in this forced-choice, so a
    bigger budget only slows the call (~6× at 2048) without letting the CoT close earlier.
    Each tinymfv call costs ~this × n_vignettes × 2 framings; smoke/tiny overrides it down."""

    # ─ data ─
    n_scenarios: int = 30
    """Scenario-library rows sampled per round before headroom pruning."""
    n_headroom_prompts: int = 15
    """How many low-depth unprompted scenarios survive the headroom gate and
    get candidate generation."""
    n_train_pairs: int = 15
    """Target selected training pairs per round after headroom and candidate
    pruning. The teacher selects among student-generated candidate pairs."""
    min_pairs_to_train: int = 10
    """Round-fail floor on the teacher's OWN viewed-batch ratings:
    select_pairs trains on every candidate clearing the threshold (on_axis>=3.5
    AND worst confound<=2.5) and fails the round if fewer than this many clear. Also a
    cheap choose_focus pre-check (>= this many clean candidates must exist). Acts on
    the teacher's ratings, not a val-metric (CLAUDE.md: gates elicit judgment)."""
    n_candidate_pairs: int = 8
    """Student-generated (cho, rej) candidate pairs per kept scenario."""
    candidate_temperature: float = 0.8
    candidate_top_p: float = 0.95
    seed: int = 0
    """Run-level seed offset for INDEPENDENT multi-seed runs. Folded into every
    student-gen seed (scenario/unprompted/candidate streams) and TrainCfg.seed so
    two runs of the same profile with different `seed` draw different candidate
    samples (candidate gen is do_sample=True, temperature=0.8) and a different
    train/val split. seed=0 reproduces the historical single-stream determinism.
    The probe/dialogue gen stays greedy (deterministic measurement instrument)."""
    persona_templates: tuple[str, ...] = DEFAULT_PERSONA_TEMPLATES
    # Teacher axis menu. Each cell is one measured persona/template row:
    # (hf_id, template, pair_id, pos_descriptor, neg_descriptor, score, on_axis, off_axis).
    # Text lives in prompts.py; config selects a measured menu.
    persona_cells: tuple[tuple[int, str, str, str, str, float, float, float], ...] = DEFAULT_PERSONA_CELLS
    """Frozen measured persona-template cells. Candidate generation samples cells
    atomically rather than recombining template x persona pair."""
    cull_degenerate_pairs: bool = True
    """Drop collapsed gens before training so a collapsed batch trains on coherent
    survivors. OFF only for tiny-random, whose random-weight output is gibberish
    by design. See pipeline._degenerate_gen."""
    restrict_validated_prompts: bool = False
    """Restrict the character family to prompts that survived the OpenRouter screen
    (scripts/validate_persona_axes_openrouter.py -> pool_validated.json). Removes
    length-skewed / no-contrast prompts but, with the current ~8-prompt-per-axis
    pool, also pushes the thin axes (care, fairness) below min_pairs_to_train --
    only the rich autonomy axis survives. OFF by default; on only where the pool is
    rich enough or the run is autonomy-focused. See prompts_pool.VALIDATED_PROMPTS."""
    gen_max_new_tokens: int = 600
    """Per-pole on-policy gen budget under the persona prefix. 600 (~2.4k chars)
    not 2048: the verbose pos-pole (e.g. "weigh who is affected") ran to ~800
    tokens / 3.1k chars at 2048 while the terse neg-pole sat at ~630 chars
    (task 37), which (a) OOM'd training (long seq × full-vocab KL transient ×
    3 forwards on 31b nf4) and (b) makes length the axis. Capping the long pole
    narrows the gap and bounds train memory; the reference (w2s-ics-cws) used
    256-512 here. A full moral answer is ~325-500 tok, so 600 rarely truncates."""

    max_len: int = 2048
    """Train-time max sequence length for collating pairs."""
    n_val_pairs: int = 3
    """Held-out pairs for the val overfit canary."""
    min_val_improvement: float = 0.05
    """Required drop in val nll+ from step 0 to the deployed checkpoint.
    Smaller improvement counts as "did not really learn" and the round fails."""

    # ─ steering coefficient ─
    signed_C: float = 1.5
    """Initial probe coefficient — c_scan walks DOWN from here (×2/3 per fail)
    until pmass ≥ gate × baseline AND valid_json ≥ baseline AND distinct3 ≥
    0.5 × baseline over the deployment probes. Backoff is now 1.0 (bake at the
    passing c). Start ABOVE the train-time C=1.0 so a robust adapter can bake at
    >1 (more steering strength when it stays coherent there); the finer ×2/3
    step then resolves the usable band instead of halving past it. Sidecar —
    agent never sees it."""

    gate_frac: float = 0.97
    """c_scan pmass gate: a probe passes only if pmass ≥ gate_frac × baseline.
    Baseline pmass is near-ceiling (~0.999). At 0.995 (~0.005 budget) pmass was
    the BINDING gate — it rejected c that valid_json (the real free-gen multi-
    turn canary) passed cleanly (9b task 23: c=0.5 had json 6/6 but pmass 0.982
    < 0.994 → fail-pmass → walked to 0.125-0.5). 0.97 (~0.03 budget) lets
    valid_json + distinct3 be the binding coherence signals and leaves pmass a
    sanity floor for catastrophic answer-slot collapse only."""

    # ─ outer loop ─
    allowed_scenario_families: tuple[str, ...] = SCENARIO_FAMILIES
    """Scenario families the teacher may select for this profile."""

    n_rounds: int = 2
    """Number of *keep* rounds the agent aims for. Drops don't count."""


CONFIGS: dict[str, RunConfig] = {
    # Batch sizes calibrated to ~96GB GPU (RTX PRO 6000 Blackwell).
    "gemma-2b": RunConfig(
        model="google/gemma-2-2b-it",
        teacher="qwen/qwen3.5-9b",
        train_batch_size=16,
        eval_batch_size=16,
    ),
    # PiSSA variant of gemma-2b. r=256 ≈ 10% of hidden_dim (2304); SVD-space
    # needs more headroom than free LoRA. Same training schedule otherwise.
    "gemma-2b-pissa": RunConfig(
        model="google/gemma-2-2b-it",
        teacher="qwen/qwen3.5-9b",
        adapter="pissa",
        # r=2304 acts as "full per target" sentinel: ModulatedPiSSA clamps
        # per-layer to min(d_in, d_out), so q,o,gate,up,down get r=2304,
        # GQA k,v get r=1024. Tests "is rank-selection the bottleneck?" —
        # at full rank the only remaining PiSSA constraint is "diagonal in
        # W's spectral basis", no longer "which directions to keep".
        lora_r=2304,
        train_batch_size=16,
        eval_batch_size=16,
        # kl_lambda 100× the original PiSSA setting. KL pressure during
        # training is the lever that controls deployment-c side effects
        # (c_scan walks down when KL was too weak). With lr=1e-2 and
        # margin signal ~0.5 nats, kl=0.15 contributed only ~0.06 nats
        # (12% of margin) — adapter could drift faster than KL constrained.
        # 0.5 puts kl contribution ~0.2 nats, matching margin magnitude
        # so the constraint is balanced not nominal.
        kl_lambda=0.5,
        # lr 200× LoRA default. 1e-2 trace (r=512 run): margin opens at
        # high C (5+ nats) but low-C nll+ stuck at ~2.97 and ‖Δs‖ saturated
        # at 5 by step 90 — possibly hitting grad_clip=1.0 every step, so
        # effective lr was much smaller. Bumping to 2e-2 to test whether
        # the plateau was lr-decay/clip-bound rather than capacity.
        lr=2e-2,
        # wd≈0: Δs is the entire learnable param (per-singular delta).
        # Normal weight-decay scales (0.01) shrink Δs back toward 0
        # (= PiSSA identity = null intervention), fighting the optimizer.
        weight_decay=1e-5,
        # 1024 not 2048: KL transient is full-vocab even with top-K refs
        # (autograd needs the proper softmax normalizer). Seq halved →
        # transient logp halved (16.75 → 8 GB bf16). Pair completions are
        # usually <1k tokens; longer ones truncate.
        max_len=1024,
        # A 60-step trace plateaued after the cosine decay passed 1e-3; 120
        # steps keeps the high-lr phase longer without adding another hyperparameter.
    ),
    "gemma-9b": RunConfig(
        model="google/gemma-2-9b-it",
        teacher="qwen/qwen3.5-9b",
        train_batch_size=8,
        eval_batch_size=8,
    ),
    # ─ PiSSA-vs-LoRA matched pair on the gemma-2-9b student (bf16, so SVD is
    # feasible — the largest student where it is; 27b is nf4-only = LoRA-only).
    # Everything SHAREABLE is identical between the two arms (batch, depth band,
    # kl_lambda, max_len, n_rounds); only the things intrinsic to the
    # method differ (adapter, lr, weight_decay, rank). A shared lr would itself
    # be the confound — PiSSA's per-singular Δs needs ~200× LoRA's lr and ~0 wd
    # or it decays to the SVD identity (null intervention). n_rounds=1 until the
    # stale-cho bleed is fixed.
    # kl_lambda=2.0 (4× default): task 21 (27b, kl=0.5) trained a good direction
    # (nll+ 3→0.34) but the c_scan had to walk signed_C to 0.125 — at c≥0.5 free
    # gen collapsed (fail-json, mean_len 9198). Reverse-KL is zero-forcing: it
    # penalizes the incoherent mass-adding collapse and is blind to the cho-vs-rej
    # mode-shift, so more KL buys coherence headroom (higher usable c) without
    # killing the steering. With the stronger anchor we also push lr=3e-4 (LoRA
    # arms; PiSSA keeps 2e-2) so the constrained adapter has room to find the
    # coherent direction. qwen-27b-nf4 found kl=3.0
    # too tight, but that was at the old lr/steps — may differ now; 2.0 leaves
    # headroom to push higher.
    "gemma-9b-pissa": RunConfig(
        model="google/gemma-2-9b-it",
        teacher="qwen/qwen3.5-9b",
        adapter="pissa",
        # full-per-target sentinel (hidden=3584): ModulatedPiSSA clamps to
        # min(d_in,d_out) per layer. Mirrors gemma-2b-pissa's r=2304 sentinel —
        # tests "diagonal in W's spectral basis" with rank-selection removed.
        lora_r=3584,
        lr=2e-2,            # 200× LoRA: Δs are per-singular scalars, need big lr
        weight_decay=1e-5,  # ≈0: wd shrinks Δs → SVD identity = null intervention
        # ── shared with gemma-9b-lora ──
        kl_lambda=2.0,
        max_len=1024,       # KL transient is full-vocab; halve seq for memory
        train_batch_size=8,
        eval_batch_size=8,
        n_rounds=1,
    ),
    "gemma-9b-lora": RunConfig(
        model="google/gemma-2-9b-it",
        teacher="qwen/qwen3.5-9b",
        adapter="lora",
        lora_r=16,          # LoRA's natural low rank (vs PiSSA full-rank)
        lora_alpha=32.0,
        lr=3e-4,            # peak lr raised now the stronger KL anchor holds coherence
        weight_decay=0.01,
        # ── shared with gemma-9b-pissa ──
        kl_lambda=2.0,
        max_len=1024,
        train_batch_size=8,
        eval_batch_size=8,
        n_rounds=1,
    ),
    # Experiment arm: gemma-9b-lora but trained ~1.7× longer. Falsifies the
    # "train longer → stronger intervention" hypothesis. Task 23 (240 steps)
    # bottomed nll+ at 0.957 by step 120 then ticked back to 0.97 as the cosine
    # anneal drove lr→0; a 400-step run keeps lr higher longer, so it tests
    # whether that floor was lr-limited. Prediction (entry 2026-06-02 (e)):
    # longer → lower nll+ → MORE compliance drift OOD (PiSSA had the lowest nll+
    # and the worst OOD), not stronger target-ward movement.
    "gemma-9b-lora-long": RunConfig(
        model="google/gemma-2-9b-it",
        teacher="qwen/qwen3.5-9b",
        adapter="lora",
        lora_r=16,
        lora_alpha=32.0,
        lr=3e-4,
        weight_decay=0.01,
        kl_lambda=2.0,
        max_len=1024,
        train_batch_size=8,
        eval_batch_size=8,
        n_rounds=1,
    ),
    # -revert/-recover: light-kl (0.064/0.5), light-gate variants that trade the
    # heavy kl=2.0 coherence leash for more steering strength, keeping the
    # multi-turn valid_json canary. The heavy kl guarded against cumulative
    # multi-round collapse; at n_rounds=1 (stale-cho bleed) that guard is slack,
    # so these probe how much strength the leash was costing on the single adapter.
    "gemma-9b-lora-revert": RunConfig(
        model="google/gemma-2-9b-it",
        teacher="qwen/qwen3.5-9b",
        adapter="lora",
        lora_r=16,
        lora_alpha=32.0,
        lr=2e-4,            # 9536ea0 value
        weight_decay=0.01,
        kl_lambda=0.064,    # 9536ea0 value (31× lighter than now)
        gate_frac=0.85,     # ~15% pmass band; valid_json+distinct3 carry coherence
        max_len=1024,
        train_batch_size=8,
        eval_batch_size=8,
        n_rounds=1,
    ),
    "gemma-9b-lora-recover": RunConfig(
        model="google/gemma-2-9b-it",
        teacher="qwen/qwen3.5-9b",
        adapter="lora",
        lora_r=16,
        lora_alpha=32.0,
        lr=3e-4,
        weight_decay=0.01,
        kl_lambda=0.25,     # between 0.064 (old) and 2.0 (now)
        gate_frac=0.85,     # ~15% pmass band
        max_len=1024,
        train_batch_size=8,
        eval_batch_size=8,
        n_rounds=1,
    ),
    # Very-long arm (wassname: "who knows, kl+wd might find a really nice elegant
    # intervention"). Long training under a moderate KL anchor + weight decay can
    # settle into a cleaner, more generalisable direction than a short run that
    # stops mid-descent — or it can overfit the narrow axis (PiSSA's lowest nll+
    # generalised worst). 1000 steps brackets the long end opposite -revert(60).
    "gemma-9b-lora-vlong": RunConfig(
        model="google/gemma-2-9b-it",
        teacher="qwen/qwen3.5-9b",
        adapter="lora",
        lora_r=16,
        lora_alpha=32.0,
        lr=3e-4,
        weight_decay=0.01,  # the wd that might regularise toward elegance
        kl_lambda=0.5,      # moderate anchor (not the 2.0 throttle, not ~0)
        gate_frac=0.85,
        max_len=1024,
        train_batch_size=8,
        eval_batch_size=8,
        n_rounds=1,
    ),
    "gemma-12b": RunConfig(
        model="google/gemma-3-12b-it",
        teacher="qwen/qwen3.5-9b",
        train_batch_size=4,
        eval_batch_size=4,
    ),
    "gemma-27b": RunConfig(
        model="google/gemma-2-27b-it",
        teacher="qwen/qwen3.5-9b",
        quant="nf4",
        # nf4 forces lora: PiSSA mutates layer.weight at init and bnb-nf4
        # buffers aren't reversibly writable, so the pissa default would make
        # _validate raise. Mirrors qwen-27b-nf4.
        adapter="lora",
        train_batch_size=2,
        eval_batch_size=32,  # eval is memory-light (weights dominate); use the idle GPU
        lr=3e-4,            # raised from 1e-4: stronger KL anchor (below) holds coherence
        # Reverse-KL buys coherence headroom for nf4 large students.
        kl_lambda=2.0,
    ),
    # Main large-student profile: nf4 LoRA with the weak qwen teacher.
    "gemma-31b": RunConfig(
        model="google/gemma-4-31B-it",
        # The teacher is intentionally weaker than the student; this is the w2s gap.
        teacher="qwen/qwen3.5-9b",
        quant="nf4",
        adapter="lora",
        # Batch 1 fits the retained contrastive graph on a 31B nf4 student.
        train_batch_size=1,
        eval_batch_size=32,  # eval is memory-light (weights dominate); use the idle GPU
        max_len=512,
        lr=3e-4,
        kl_lambda=2.0,
        # Use more distinct pairs to reduce memorization by the LoRA adapter.
        n_train_pairs=30,
    ),
    # Qwen nf4 LoRA recipe for the large-student arm.
    "qwen-27b-nf4": RunConfig(
        model="Qwen/Qwen3.6-27B",
        teacher="qwen/qwen3.5-9b",
        quant="nf4",
        # Large students train at batch 1; contrastive training keeps several
        # full-vocab forward graphs live at once.
        train_batch_size=1,
        eval_batch_size=32,  # eval is memory-light (weights dominate); use the idle GPU
        lora_r=16,
        lora_alpha=32.0,
        # Lower nominal lr pairs with high gradient clipping; median gradients
        # pass while spike batches are clipped.
        lr=1.5e-4,
        # Long warmup gives the adapter a ramp before high-magnitude batches see
        # fast updates.
        warmup_ratio=0.25,
        # Clip only spike batches; do not bind the median step.
        grad_clip=50.0,
        n_epochs=4.0,
        # Keep KL as an anchor without letting it dominate the contrastive term.
        kl_lambda=0.5,
        # nf4 profiles use LoRA because PiSSA mutates float layer weights at init.
        adapter="lora",
        persona_cells=MULTI_AXIS_PERSONA_CELLS,
    ),
    "qwen-32b-nf4": RunConfig(
        model="Qwen/Qwen3-32B",
        teacher="qwen/qwen3.5-9b",
        quant="nf4",
        train_batch_size=1,
        eval_batch_size=32,  # eval is memory-light (weights dominate); use the idle GPU
        lora_r=16,
        lora_alpha=32.0,
        lr=1.5e-4,
        warmup_ratio=0.25,
        grad_clip=50.0,
        n_epochs=4.0,
        kl_lambda=0.5,
        adapter="lora",
        persona_cells=MULTI_AXIS_PERSONA_CELLS,
    ),
    # Smoke: tiny-random Qwen3 5-layer. ~1 min on CPU, garbage outputs.
    # layer_range=(0,1) so all 5 layers are targets — (0.2,0.8) would
    # leave only 3 layers, fine but defeats the smoke point.
    "tiny": RunConfig(
        model="wassname/qwen3-5lyr-tiny-random",
        teacher="qwen/qwen3.5-9b",
        train_batch_size=2,
        eval_batch_size=2,
        layer_range=(0.0, 1.0),
        n_train_pairs=4,
        n_scenarios=4,
        n_candidate_pairs=2,
        min_pairs_to_train=3,
        cull_degenerate_pairs=False,  # tiny gibberish would be 100% culled
        n_rounds=1,
        dialogue_max_new_tokens=32,
        gen_max_new_tokens=32,
        cscan_n_vignettes=0,
        cscan_max_think_tokens=64,  # smoke: keep tinymfv pmass fast on CPU
        max_len=128,
    ),
    # PiSSA smoke: same tiny model; r=16 because the hidden_dim on this
    # tiny-random model is small. Used to round-trip the full pipeline on CPU.
    "tiny-pissa": RunConfig(
        model="wassname/qwen3-5lyr-tiny-random",
        teacher="qwen/qwen3.5-9b",
        adapter="pissa",
        lora_r=16,
        train_batch_size=2,
        eval_batch_size=2,
        layer_range=(0.0, 1.0),
        n_train_pairs=4,
        n_scenarios=4,
        n_candidate_pairs=2,
        min_pairs_to_train=3,
        cull_degenerate_pairs=False,  # tiny gibberish would be 100% culled
        n_rounds=1,
        dialogue_max_new_tokens=32,
        gen_max_new_tokens=32,
        cscan_n_vignettes=0,
        cscan_max_think_tokens=64,  # smoke: keep tinymfv pmass fast on CPU
        max_len=128,
    ),
    "qwen-2b-smoke": RunConfig(
        model="Qwen/Qwen3.5-2B",
        teacher="qwen/qwen3.5-9b",
        adapter="lora",
        lora_r=16,
        lora_alpha=32.0,
        train_batch_size=2,
        eval_batch_size=2,
        n_train_pairs=4,
        n_scenarios=6,
        n_candidate_pairs=2,
        min_pairs_to_train=3,
        n_rounds=1,
        dialogue_max_new_tokens=512,
        gen_max_new_tokens=192,
        cscan_n_vignettes=1,
        cscan_max_think_tokens=64,
        max_len=256,
        enable_thinking=False,
        allowed_scenario_families=("character",),
        persona_cells=WELLBEING_SMOKE_PERSONA_CELLS,
    ),
    "qwen-2b-3keep": RunConfig(
        model="Qwen/Qwen3.5-2B",
        teacher="qwen/qwen3.5-9b",
        adapter="lora",
        lora_r=16,
        lora_alpha=32.0,
        train_batch_size=2,
        eval_batch_size=2,
        n_epochs=2.0,
        n_scenarios=36,
        n_headroom_prompts=20,
        n_train_pairs=20,
        n_candidate_pairs=5,
        # Choose-focus samples one axis at a time, so the minimum must fit the
        # per-axis prompt count.
        min_pairs_to_train=6,
        # Optional prompt-screen slice. This profile keeps it on for a narrow
        # autonomy-focused smoke, not for broad character training.
        restrict_validated_prompts=True,
        n_val_pairs=4,
        min_val_improvement=0.05,
        n_rounds=3,
        dialogue_max_new_tokens=512,
        gen_max_new_tokens=128,
        cscan_n_vignettes=1,
        cscan_max_think_tokens=64,
        max_len=256,
        signed_C=1.0,
        enable_thinking=False,
        allowed_scenario_families=("character",),
        persona_cells=CORE_THREE_AXIS_PERSONA_CELLS,
    ),
}

# Lower deployment-strength probe for the 31B student. c_scan still walks down
# from this value if coherence fails.
CONFIGS["gemma-31b-c10"] = replace(CONFIGS["gemma-31b"], signed_C=1.0)

# Stronger-teacher comparison arms; not the main weak-teacher claim.
CONFIGS["gemma-31b-t-deepseek"] = replace(CONFIGS["gemma-31b-c10"], teacher="deepseek/deepseek-v4-flash")
CONFIGS["tiny-t-deepseek"] = replace(CONFIGS["tiny"], teacher="deepseek/deepseek-v4-flash")

# Intermediate-teacher comparison arm: smaller w2s gap than qwen-9b -> 31B.
CONFIGS["gemma-31b-t-27b"] = replace(CONFIGS["gemma-31b-c10"], teacher="qwen/qwen3.5-27b")
CONFIGS["tiny-t-27b"] = replace(CONFIGS["tiny"], teacher="qwen/qwen3.5-27b")

# CPU soundness check with a small real student; no shared GPU needed.
CONFIGS["tiny-real"] = replace(
    CONFIGS["tiny"], model="Qwen/Qwen3-0.6B",
    dialogue_max_new_tokens=64, gen_max_new_tokens=64,
)

# Tiny-gap same-family w2s comparison: qwen3.5-27B teacher, qwen3.6-27B student.
CONFIGS["qwen27b-w2s"] = replace(
    CONFIGS["qwen-27b-nf4"], teacher="qwen/qwen3.5-27b", signed_C=1.0)

# Real 32B prompt-gym: one small keep-target round, for checking the new prompt
# menu before paying for the broad multi-axis profile. It still uses the real
# student for unprompted, candidate generation, train, c_scan, and POST.
CONFIGS["qwen-32b-nf4-micro"] = replace(
    CONFIGS["qwen-32b-nf4"],
    n_scenarios=4,
    n_headroom_prompts=4,
    n_train_pairs=4,
    min_pairs_to_train=3,
    n_candidate_pairs=2,
    n_rounds=1,
    dialogue_max_new_tokens=512,
    gen_max_new_tokens=192,
    cscan_n_vignettes=1,
    cscan_max_think_tokens=64,
    max_len=512,
    signed_C=1.0,
)

CONFIGS["qwen-32b-nf4-12keep"] = replace(
    CONFIGS["qwen-32b-nf4-micro"],
    n_rounds=12,
    # micro inherits SMOKE data sizes (8 candidates/round); on the 32b student
    # that culls to 3-4 clean pairs -> the adapter learns ~nothing (val_improvement
    # ~5e-4, p95 KL ~0.007) -> POST==PRE byte-identical -> every round drops
    # no_movement (job-114 audit, 2026-06-24). Scale data back to production so
    # enough clean pairs survive the 32b's higher persona-leak/character-break cull.
    n_scenarios=8,
    n_candidate_pairs=4,
    n_train_pairs=12,
    n_val_pairs=4,
    min_pairs_to_train=6,
    n_headroom_prompts=8,
)

# Local 4B profile for real train->judge cycles without a 30B GPU load.
CONFIGS["gemma-4b-3keep"] = replace(
    CONFIGS["qwen-2b-3keep"],
    model="google/gemma-3-4b-it",
    restrict_validated_prompts=False,
    n_rounds=5,
    # Deployment-strength ceiling for this smaller student; c_scan walks down on fail.
    signed_C=4.0,
    # Relax the KL anchor so the adapter can move further off base.
    kl_lambda=0.2,
)

# Discernment profile: train whether action is warranted, not a fixed action rule.
CONFIGS["gemma-4b-discern"] = replace(
    CONFIGS["gemma-4b-3keep"],
    n_scenarios=18,
    n_headroom_prompts=12,
    persona_cells=DISCERNMENT_PERSONA_CELLS,
)

# Large-student weak-to-strong profile with the rotating multi-axis persona menu.
CONFIGS["gemma-27b-3keep"] = replace(
    CONFIGS["gemma-4b-3keep"],
    model="google/gemma-2-27b-it",
    quant="nf4",
    adapter="lora",
    train_batch_size=1,
    # Eval is forced-choice at max_think=64 and peaked ~16GB at bs=2 on a 27B-nf4 --
    # almost all of that is fixed weights, so eval is memory-light and the 80-96GB box
    # is ~80% idle during it. bs=32 (~50GB worst case) cuts eval wall-clock ~16x.
    # Inherited by qwen36-27b-3keep and gemma4-31b-3keep (the active big students).
    eval_batch_size=32,
    signed_C=2.0,
    persona_cells=MULTI_AXIS_PERSONA_CELLS,
    # Big-student round-fail floor: >=20 candidates must clear the teacher's
    # viewed-batch threshold (on_axis>=3.5 AND worst confound<=2.5) or the
    # round fails. The pool is ~100 (20 headroom prompts x 5 candidates), the broad
    # restrict_validated_prompts=False pool kept 51-76 clean pairs/round, so 20
    # differentiated is comfortably satisfiable when the teacher rates honestly --
    # and a round where it cannot find 20 differentiated pairs SHOULD fail. Trains on
    # ALL passing (tens), not a hand-picked ~12. qwen-2b-3keep stays at 6 (thin
    # per-axis pool). WATCH the gym/first-run pass rate: if a weak qwen-9b leaves
    # <20 clearing every round, the threshold is too strict for it, not the student.
    min_pairs_to_train=20,
)

# Exactly the validated job-139 harness AND hyperparams (gemma-27b-3keep: MULTI_AXIS
# menu, 36 scenarios, 5 candidate pairs, 20 train, signed_C=2.0, kl_lambda=0.2, lr=1e-4,
# grad_clip=1.0, n_epochs=2.0), with ONLY the student model swapped to Qwen3.6-27B.
# We deliberately do NOT carry the OLD qwen-27b-nf4 overrides (grad_clip=50, lr=1.5e-4,
# warmup=0.25): those came from a stale ‖g‖~17 note that predates the recent harness
# work, and the validated 27b-nf4 run trains fine at clip=1 (job-116 gemma ‖g‖~4-11
# moved with clip=1). If Qwen3.6 gradients genuinely spike and clip=1 binds (round00
# ‖g‖ trace high while val_nll stays flat), bump grad_clip then -- do not pre-defend.
# Rationale for a Qwen student at all: the AA open-weights index says the qwen3.5-9b
# teacher WITH reasoning beats gemma-4-31b WITHOUT, so the only students above the
# teacher are Qwen (3.6-27b, 3.5-27b). Same-family (qwen->qwen) is a w2s-generalization
# confound we accept only because no accessible non-Qwen model is both strong enough
# AND embodies the negative pole (gemma-2-27b too old; Qwen3-32B refused, RJ 2026-06-25a).
# Open risk: Qwen3.6 is newer Qwen with more safety training, so it may hit the SAME
# neg-pole refusal; watch round00 poles and kill fast. Run with CSM_ATTN_IMPL=flash_attention_2.
CONFIGS["qwen36-27b-3keep"] = replace(
    CONFIGS["gemma-27b-3keep"],
    model="Qwen/Qwen3.6-27B",
)

# Cross-generation gemma w2s: a weak gemma-3-12b teacher steers the strong gemma-4-31b
# student. Same validated job-139 harness as gemma-27b-3keep, only model+teacher swapped.
# Why this pairing: gemma EMBODIES the negative pole (the qwen failure mode, RJ 2026-06-25a),
# and gemma-4-31b clearly beats gemma-3-12b (one generation + 31b vs 12b), so the strength
# gap is real. It is still same-family (gemma->gemma), so the cross-family w2s-generalization
# confound remains; we trade that for working embodiment plus a clean gap. gemma-3-12b is the
# ~9b-class teacher (Gemma 3 has no 9b -- lineup is 1b/4b/12b/27b) and supports function
# calling, so it can drive the react harness; if 12b proves too weak for the tool loop,
# raise the teacher to gemma-3-27b. Gemma student keeps eager attention (no FA2 env).
CONFIGS["gemma4-31b-3keep"] = replace(
    CONFIGS["gemma-27b-3keep"],
    model="google/gemma-4-31B-it",
    teacher="google/gemma-3-12b-it",
)


def config_by_model(model_id: str) -> RunConfig:
    """Fall back to a default RunConfig if `model_id` isn't in CONFIGS."""
    for cfg in CONFIGS.values():
        if cfg.model == model_id:
            _validate(cfg)
            return cfg
    cfg = RunConfig(model=model_id, teacher="qwen/qwen3.5-9b")
    _validate(cfg)
    return cfg


def config_for_run(run_meta: dict) -> RunConfig:
    """Prefer the profile name when multiple profiles share a model id
    (e.g. gemma-2b vs gemma-2b-pissa). Falls back to model-id lookup for
    runs initialised before the profile field was persisted."""
    profile = run_meta.get("profile")
    if profile and profile in CONFIGS:
        cfg = CONFIGS[profile]
        if run_meta.get("seed"):
            cfg = replace(cfg, seed=run_meta["seed"])  # T7: per-run RNG offset
        _validate(cfg)
        return cfg
    return config_by_model(run_meta["model"])


def _validate(cfg: RunConfig) -> None:
    if cfg.adapter == "pissa" and cfg.quant is not None:
        # PiSSA physically mutates layer.weight at init; bnb quantized
        # buffers are not reversibly writable. Force quant=None for PiSSA
        # profiles or use ModulatedLoRA for the quantized model.
        raise ValueError(
            f"PiSSA requires float layers; quant={cfg.quant!r} is incompatible. "
            f"Either set adapter='lora' or quant=None for {cfg.model!r}."
        )
    bad_families = [f for f in cfg.allowed_scenario_families if f not in SCENARIO_FAMILIES]
    if bad_families:
        raise ValueError(
            f"unknown scenario families {bad_families!r}; choose from {SCENARIO_FAMILIES}"
        )
    # Every menu axis needs a behaviour hint for candidate generation.
    from csm.prompts import PAIR_BEHAVIOR_HINTS
    missing_hints = sorted({c[2] for c in cfg.persona_cells} - set(PAIR_BEHAVIOR_HINTS))
    if missing_hints:
        raise ValueError(
            f"persona_cells axes missing from PAIR_BEHAVIOR_HINTS: {missing_hints}; "
            f"add them (derive from the validate-script AXES behaviours)."
        )
