"""Per-model run config registry.

Lifted from `weight-steering-lite/src/wsl/prompts.py:CONFIGS`, trimmed
to the two profiles we plan to validate first. Hard-won numbers stay
here (the agent never sees them).
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

from csm.gen.prompts_pool import SCENARIO_FAMILIES


@dataclass
class RunConfig:
    model: str
    """HF model id, e.g. 'google/gemma-2-2b-it'."""
    teacher: str
    """OpenRouter id for the teacher LLM that drives the inspect-ai react agent.
    The teacher IS the judge: the same react agent chooses the axis/family,
    selects among generated candidate pairs, and calls mark_exam (keep/drop).
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
    """Gate after candidate pruning/selection: ≥ this many selected pairs
    (both poles non-empty, cho≠rej) must survive before training."""
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
    persona_templates: tuple[str, ...] = (
        "Act as a {persona} person would in this situation.",
    )
    persona_cells: tuple[tuple[int, str, str, str, str, float, float, float], ...] = (
        (
            1,
            "You are a {persona} person acting in the world.",
            "wellbeing_authority",
            "wellbeing-focused even when authority-defying",
            "authority-deferential even when wellbeing suffers",
            83.3,
            1.0,
            0.1667,
        ),
        (
            2,
            "Respond as a {persona} person.",
            "wellbeing_authority",
            "wellbeing-focused even when authority-defying",
            "authority-deferential even when wellbeing suffers",
            77.8,
            1.0,
            0.2222,
        ),
        (
            3,
            "Pretend you're a {persona} person.",
            "wellbeing_authority",
            "wellbeing-focused even when authority-defying",
            "authority-deferential even when wellbeing suffers",
            69.3,
            0.875,
            0.2083,
        ),
        (
            4,
            "You are a {persona} person thinking through the situation.",
            "wellbeing_authority",
            "wellbeing-focused even when authority-defying",
            "authority-deferential even when wellbeing suffers",
            65.1,
            0.7812,
            0.1667,
        ),
        (
            5,
            "You are a {persona} person thinking through the situation.",
            "principled_expedient",
            "principled",
            "expedient",
            28.6,
            0.3438,
            0.1667,
        ),
    )
    """Frozen measured persona-template cells from
    wassname/persona-steering-template-library.

    Tuple schema:
    (hf_id, template, persona_pair, positive descriptor, negative descriptor,
    score, on_axis, off_axis). These are the unit of measurement; candidate
    generation samples cells rather than recombining template x persona pair.
    """
    cull_degenerate_pairs: bool = True
    """Drop collapsed gens (word-loop / non-latin spray) before training so a
    composition-collapsed batch trains on the coherent survivors. OFF only for
    tiny-random, whose random-weight output is non-ascii gibberish by design and
    would be 100% culled (the detector is validated on real task-46 collapse, not
    on tiny). See pipeline._degenerate_gen."""
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
        # steps keeps the high-lr phase longer without adding another knob.
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
        eval_batch_size=2,
        lr=3e-4,            # raised from 1e-4: stronger KL anchor (below) holds coherence
        # kl=2.0 (4× default): task 21 walked signed_C to 0.125 because c≥0.5 free
        # gen collapsed; reverse-KL is zero-forcing so more anchor buys coherence
        # headroom (higher usable c) without killing the cho-vs-rej steering.
        kl_lambda=2.0,
    ),
    # gemma-4-31b: the chosen student (RJ 2026-06-03 1P-vs-3P headroom run).
    # Same nf4-LoRA recipe as gemma-27b (nf4 forces LoRA; the kl=2.0 anchor + lr
    # are the gemma-nf4 coherence knobs). HF id resolves to the
    # canonical gemma-4-31B-it (gated; HF_TOKEN in .env).
    "gemma-31b": RunConfig(
        model="google/gemma-4-31B-it",
        # Teacher = qwen3.5-9b BY DESIGN: it is the WEAK half of weak-to-strong.
        # The whole harness tests whether a weak teacher can steer a stronger
        # student (CLAUDE.md L1), so the 9b→31b gap is the experiment, not a
        # tunable. Tried gemma-3-27b-it (2026-06-03, task 36) as a stronger
        # persona-writer — but a 27b teaching a 31b collapses the w2s gap, so it
        # half-broke the premise regardless. It also can't drive the react loop
        # (Gemma has weak/no native tool-calling; on OpenRouter it emitted only
        # empty turns, never called a tool). qwen3.5-9b keeps the gap
        # AND, in the gym, proposed a sharp 1p/3p-anchored trait pair under the
        # new brief — propose-a-pair is far lighter than the old author-15-cho-
        # twins task that tempted a bigger teacher. The w2s gap, not writing IQ,
        # picks the teacher here.
        teacher="qwen/qwen3.5-9b",
        quant="nf4",
        adapter="lora",
        # bs=1 + max_len=512 (2026-06-03, task-39 OOM revert): bs=2 OOM'd in the
        # train step at step 0 (93GiB alloc on the 95GiB card). The earlier
        # "bs=2/max_len=512 is a 4× cut vs task-37's OOM at 2048" reasoning was
        # wrong — task-37 OOM'd at the SAME bs=2; the binding constraint is bs,
        # not seq, because the contrastive step holds 4 full-vocab forwards
        # (gemma-4 vocab ~262k) with retained graphs over a 31b dense model under
        # EAGER attention + no gradient checkpointing. bs=1 is the known-good
        # profile task-31 trained at. The contrastive gradient is noisier at
        # bs=1, accepted; fits is non-negotiable. max_len=512 truncates the
        # longest poles equally (the MATCH-LENGTH brief keeps poles symmetric).
        train_batch_size=1,
        eval_batch_size=2,
        max_len=512,
        lr=3e-4,
        kl_lambda=2.0,
        # Use the whole 30-prompt POOL (was 15). The overfit is a 73M LoRA
        # memorizing ~12 train pairs; doubling the distinct pairs lowers the
        # achievable val-nll+ floor (greedy gen → more pairs only via more
        # prompts, not re-gen). ~27 train after the 3-pair val holdout.
        n_train_pairs=30,
    ),
    # Ported from weight-steering-lite/qwen-27b-nf4: Qwen3.6-27B + nf4 LoRA.
    # AutoModelForCausalLM dispatches the multimodal config to Qwen3_5ForCausalLM
    # (hybrid: 48 Gated DeltaNet + 16 Gated Attention layers); bnb-nf4 on-load
    # Just Works. ~80s cold load on 96GB Blackwell.
    "qwen-27b-nf4": RunConfig(
        model="Qwen/Qwen3.6-27B",
        teacher="qwen/qwen3.5-9b",
        quant="nf4",
        # bs=2 OOM'd at 92/95GB after the all-linear switch (~496 LoRA targets
        # vs ~336 prior, 1.48× activation memory under 3-forward graph).
        # bs=1 projects ~55GB train, 50GB eval at bs=8.
        train_batch_size=1,
        eval_batch_size=8,
        lora_r=16,
        lora_alpha=32.0,
        # 1.5e-4 not 3e-4: clip=50 (vs clip=1 before) lets median ‖g‖~17
        # through unscaled → effective per-step update jumps ~17× even
        # before lr change. Halve nominal lr to keep effective step in
        # a saner range. Task 99 history: lr=5e-4 + clip=1 spiked nll±
        # to 21-83; EMA recovered to ~2.4 (no margin). Task 100 lr=3e-4
        # + clip=1 calibrated absurdly low (|c|=0.05) — direction too hot
        # because trained on too narrow a slice of clean-grad steps.
        lr=1.5e-4,
        # 0.25 not 0.1: with steps=240 + warmup_ratio=0.1, lr hit peak by
        # step 24 — first spike at step 15 was already at lr 3.3e-4.
        # Stretching warmup to 60 steps means step 15 sees lr ~7.5e-5
        # (sub-spike), giving the adapter ramp room before high-|C|
        # batches see fast updates.
        warmup_ratio=0.25,
        # 50 not 1: median ‖g‖ ~17, p90 ~140 in task 100 → clip=1 bound on
        # ~99% of steps. Calibration landed at +0.047 (×0.5 walk from 2.0)
        # because the learned direction was over-concentrated on the few
        # clean-grad steps. clip=50 lets the median through unscaled and
        # only catches the p90+ spikes.
        grad_clip=50.0,
        n_epochs=4.0,
        # 0.5: dropped from 3.0 after 20260525T155712 trace showed
        # ‖g_kl‖ ≈ ‖g_nll‖ in late training and cos drifting negative —
        # KL was binding too tight, adapter direction couldn't stabilize.
        kl_lambda=0.5,
        # 4× default floor: 2b PiSSA trace nll+ still descending at step 119
        # (post-‖Δs‖-saturation rotation phase). Give late re-pointing room.
        # PiSSA mutates layer.weight at init; bnb-nf4 buffers aren't reversibly
        # writable, so nf4 profiles must use vanilla LoRA. PiSSA default applies
        # to fp16 profiles only.
        adapter="lora",
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
        dialogue_max_new_tokens=192,
        gen_max_new_tokens=192,
        cscan_n_vignettes=1,
        cscan_max_think_tokens=64,
        max_len=256,
        enable_thinking=False,
        allowed_scenario_families=("character",),
        persona_cells=(
            (
                1,
                "You are a {persona} person acting in the world.",
                "wellbeing_authority",
                "wellbeing-focused even when authority-defying",
                "authority-deferential even when wellbeing suffers",
                83.3,
                1.0,
                0.1667,
            ),
            (
                2,
                "Respond as a {persona} person.",
                "wellbeing_authority",
                "wellbeing-focused even when authority-defying",
                "authority-deferential even when wellbeing suffers",
                77.8,
                1.0,
                0.2222,
            ),
        ),
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
        # The pool holds only ~8 prompts per moral axis (care=8, fairness=8,
        # autonomy=18); choose_focus samples one axis at a time (PAIR_REQUIRED_AXES),
        # so a floor of 10 made wellbeing_authority/fairness_integrity structurally
        # unsatisfiable -- every round dropped on the gate (task-50). 6 fits the
        # pool; expand pool.jsonl per axis to raise it back.
        min_pairs_to_train=6,
        # Use only screen-validated prompts (pool_validated.json). WARNING: with the
        # thin pool this leaves only autonomy_coercion (11) above min; care (5) and
        # fairness (2) starve -- fine for an autonomy-focused run, flip to False for
        # all three axes. Either way needs an >=8B student: a 2B loops ~80% (degenerate)
        # and never fills the batch regardless of prompt quality (the real blocker).
        restrict_validated_prompts=True,
        n_val_pairs=4,
        min_val_improvement=0.05,
        n_rounds=3,
        dialogue_max_new_tokens=192,
        gen_max_new_tokens=128,
        cscan_n_vignettes=1,
        cscan_max_think_tokens=64,
        max_len=256,
        signed_C=1.0,
        enable_thinking=False,
        allowed_scenario_families=("character",),
        persona_cells=(
            (
                1,
                "You are a {persona} person acting in the world.",
                "wellbeing_authority",
                "wellbeing-focused even when authority-defying",
                "authority-deferential even when wellbeing suffers",
                83.3,
                1.0,
                0.1667,
            ),
            (
                2,
                "Respond as a {persona} person.",
                "wellbeing_authority",
                "wellbeing-focused even when authority-defying",
                "authority-deferential even when wellbeing suffers",
                77.8,
                1.0,
                0.2222,
            ),
            (
                1,
                "You are a {persona} person acting in the world.",
                "autonomy_coercion",
                "protects another person's agency under pressure",
                "coerces or corners another person for convenience or control",
                83.3,
                1.0,
                0.1667,
            ),
            (
                2,
                "Respond as a {persona} person.",
                "autonomy_coercion",
                "protects another person's agency under pressure",
                "coerces or corners another person for convenience or control",
                77.8,
                1.0,
                0.2222,
            ),
            (
                1,
                "You are a {persona} person acting in the world.",
                "fairness_integrity",
                "applies the same standard openly even when favoritism would help",
                "manipulates rules to favor insiders while preserving deniability",
                83.3,
                1.0,
                0.1667,
            ),
            (
                2,
                "Respond as a {persona} person.",
                "fairness_integrity",
                "applies the same standard openly even when favoritism would help",
                "manipulates rules to favor insiders while preserving deniability",
                77.8,
                1.0,
                0.2222,
            ),
        ),
    ),
}

# gemma-31b but with a lower init steering coefficient (1.0 vs 1.5). task-41 (3
# drops) showed the blind c_scan canary banks signed_C=1.5 and the c=1.5 adapter
# OVER-STEERS on deployment (seat names below predate the 2026-06-06 probe-set
# swap — autonomous_weapon/ceo_dashboard replaced by growth_deck/burn_bridges):
# ceo_dashboard_1p moves +2 (the principled win) but
# surveillance_1p breaks character ("I'm an LLM, I can't roleplay this") and
# autonomous_weapon_1p comma-loops — modes pmass/json/rep miss (RJ 2026-06-03 g,
# task #53). task-40 banked 0.667 and was the opposite: coherent but too weak to
# move the hard seats (+0.33 drop). This probes the untested MIDDLE: does init=1.0
# bank a strength that avoids the character-break/loop while still moving seats?
# A strength probe via the sanctioned profile knob — NOT a canary change (#53 is
# the user's call). c_scan still walks DOWN from here on fail.
CONFIGS["gemma-31b-c10"] = replace(CONFIGS["gemma-31b"], signed_C=1.0)

# Strong-teacher exploratory arm (#53 caveat: a strong teacher undercuts the
# weak-teacher w2s headline — this is a comparison, not the main result).
# deepseek-v4-flash supervises the gemma-31b student on the cleaned pool + edited
# brief: does a strong teacher get more/better keeps than the weak qwen-9b?
# tiny-t-deepseek validates the teacher id credit-free (fake student, no GPU).
CONFIGS["gemma-31b-t-deepseek"] = replace(CONFIGS["gemma-31b-c10"], teacher="deepseek/deepseek-v4-flash")
CONFIGS["tiny-t-deepseek"] = replace(CONFIGS["tiny"], teacher="deepseek/deepseek-v4-flash")

# Intermediate-teacher arm: 27b teacher → 31b student. w2s gap holds (27b < 31b)
# but much smaller than 9b→31b. Hypothesis: 9b fails edit-gate not on reasoning
# quality but on instruction-following (length-balance); 27b should clear that bar
# while still being weaker than the student on most axes.
CONFIGS["gemma-31b-t-27b"] = replace(CONFIGS["gemma-31b-c10"], teacher="qwen/qwen3.5-27b")
CONFIGS["tiny-t-27b"] = replace(CONFIGS["tiny"], teacher="qwen/qwen3.5-27b")

# CPU soundness check for the gate->guidance conversions: a small but REAL coherent
# student (Qwen3-0.6B, cached locally) so a real train->keep cycle exercises the
# val-gate-removed path + keep_quality on a trained adapter, WITHOUT the shared GPU
# (launch with CUDA_VISIBLE_DEVICES="" to force CPU). Slightly longer gens than `tiny`
# so the teacher sees real (if short) moral reasoning to judge.
CONFIGS["tiny-real"] = replace(
    CONFIGS["tiny"], model="Qwen/Qwen3-0.6B",
    dialogue_max_new_tokens=64, gen_max_new_tokens=64,
)

# Tiny-gap weak-to-strong, same family: teacher=judge qwen3.5-27b SUPERVISES
# (edits poles + keep/drop) student qwen3.6-27b's own on-policy gens. The teacher
# IS the judge (one react agent) — a STRONGER supervisor than the 9b (tests "is the
# 9b too weak to keep often"), still ≤ the student (3.5 < 3.6, one generation), so
# the w2s gap holds and nothing stronger than the student touches the loop. Reuses
# qwen-27b-nf4's OOM-safe Qwen3.6-27B LoRA recipe; signed_C=1.0 = the only
# known-good band from the gemma breakthrough (c_scan walks down from here).
CONFIGS["qwen27b-w2s"] = replace(
    CONFIGS["qwen-27b-nf4"], teacher="qwen/qwen3.5-27b", signed_C=1.0)

# The 3+/5-keep demonstration. qwen-2b-3keep established the gate-floor fix
# (min_pairs_to_train=6 fits the ~8/axis pool, task-50) but a 2B loops ~80% so
# never fills the batch (memory: gate-floor-exceeds-per-axis-pool). The fix is a
# more coherent student -- but a 9b does NOT fit this 24GB box. gemma-3-4b-it is
# the largest CACHED instruct student that does (bf16 ~8GB), and it is a 2025
# model far less loop-prone than Qwen3.5-2B. Same gemma-3 path as the working
# gemma-12b profile. All three axes ON (restrict_validated_prompts=False: the
# screen was decorrelated with 2B collapse and a 4B does not need it). n_rounds=5
# to read keeps/5.
CONFIGS["gemma-4b-3keep"] = replace(
    CONFIGS["qwen-2b-3keep"],
    model="google/gemma-3-4b-it",
    restrict_validated_prompts=False,
    n_rounds=5,
    # c_scan walks DOWN from signed_C; if init passes the canary on the first probe
    # it pins there. task-86 baked c=2.0 EVERY round (the only c probed) with the
    # canary nowhere near failing (pmass 0.9995 vs 0.7275 floor, KL p95 0.5, gens
    # at c=2 nearly identical to base) -> c=2 is a near-no-op and eval moved care
    # only +0.022. The task-89 c-sweep over that same r00 adapter (c=0..8) settles
    # init: care Δ rises clean +0.013(c1) -> +0.045(c2) -> +0.072(c4), then at c=6/8
    # the redistribution DISTORTS (sanctity trend-reverses +0.065, social/loyalty
    # crater) -> c=4 is the clean ceiling. NOT 8: the c=6/8 break is a foundation-
    # shape distortion, which the coherence canary (pmass+json+rep) cannot see, so a
    # high init could pin in the distortion zone. Init at the measured clean max.
    # (Training still pins train-C=1.0; this only sets the deploy-strength ceiling.)
    signed_C=4.0,
    # The trained direction is small-norm (task-86 ‖Δs‖ 1.17->1.22, barely off
    # init) and the kl-to-base anchor was contesting the intervention (g_kl ~ g_nll
    # late in training). Relax the anchor so the adapter can move further off base.
    kl_lambda=0.2,
)

# discernment axis on the hand-authored MIXED pool. The default pool.jsonl is all
# violation-vignettes, so steering can only learn confront-the-villain -- and blind
# judges + tinymfv top1 concur that confront-reflex is SHALLOWER than base. The mixed
# pool (10 act_warranted violations + 10 restraint_warranted legitimate-choice/verify-
# first scenarios) with an ENACTABLE verify-vs-react persona (not a meta-value framing,
# which how_to_write_personas.md says does not load) should learn "read the situation:
# act when warranted, restrain/verify when not" = the project goal ("wisdom of when and
# where to act").
# UAT: cho poles VARY by scenario (act on violations, restrain on legitimate choices)
# instead of a uniform "immediately confront", AND the kept-round independent tinymfv
# top1 stops regressing. n_scenarios trimmed to fit the 20-row discernment slice.
CONFIGS["gemma-4b-discern"] = replace(
    CONFIGS["gemma-4b-3keep"],
    n_scenarios=18,
    n_headroom_prompts=12,
    persona_cells=(
        (1, "You are a {persona} person acting in the world.", "discernment",
         "checks the facts and weighs whether to act before stepping in",
         "steps in immediately without checking the facts or weighing whether to act",
         83.3, 1.0, 0.1667),
        (2, "Respond as a {persona} person.", "discernment",
         "checks the facts and weighs whether to act before stepping in",
         "steps in immediately without checking the facts or weighing whether to act",
         77.8, 1.0, 0.2222),
        (4, "You are a {persona} person thinking through the situation.", "discernment",
         "checks the facts and weighs whether to act before stepping in",
         "steps in immediately without checking the facts or weighing whether to act",
         65.1, 0.7812, 0.1667),
    ),
)

# TRUE weak-to-strong demonstration: the gemma-4b-3keep recipe (the new no-veto
# brief, all-3-axes, relaxed kl=0.2, min_pairs_to_train=6) that scored 3 keeps/5
# (task-173), now on a STRONG student. gemma-4b was strong-to-weak plumbing; this
# is the actual w2s bet -- the weak qwen-9b teacher steering a 27b student (the
# 9b->27b gap is a NARROWER, more plausible gap than the 9b->31b one we shelved
# 2026-06-07 as too wide, retried now that the brief produces keeps). Inherits the
# whole proven 3keep config; overrides only what the larger student forces:
#   - quant=nf4 + adapter=lora: a 27b only fits nf4 on the 96GB card, and nf4
#     forces LoRA (PiSSA can't reversibly mutate nf4 buffers -- config._validate).
#   - train_batch_size=1: gemma-31b proved bs=2 OOMs the 4-forward contrastive
#     step on a ~30b nf4 student at step 0; bs=1 is the known-good large profile.
#   - signed_C=2.0 (vs the 4b's measured-4.0 ceiling): the c=4 clean ceiling was
#     MEASURED on the 4b by a c-sweep and is untested here; gemma-31b-c10 found
#     c=1.5 already over-steered a 31b. Start just above train-C=1.0 for deploy
#     headroom; c_scan walks DOWN from here on any canary fail, so overshoot is
#     self-correcting but a too-high init can pin in the unseen distortion zone.
# WATCH (audit): kl=0.2 is the relaxed 3keep anchor; on an nf4 student the quant
# noise may need more leash than a bf16 4b -- if c_scan walks c to the floor every
# round, the anchor (not the student) is the suspect, not signed_C.
CONFIGS["gemma-27b-3keep"] = replace(
    CONFIGS["gemma-4b-3keep"],
    model="google/gemma-2-27b-it",
    quant="nf4",
    adapter="lora",
    train_batch_size=1,
    eval_batch_size=2,
    signed_C=2.0,
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
