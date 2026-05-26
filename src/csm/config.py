"""Per-model run config registry.

Lifted from `weight-steering-lite/src/wsl/prompts.py:CONFIGS`, trimmed
to the two profiles we plan to validate first. Hard-won numbers stay
here (the agent never sees them).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass
class RunConfig:
    model: str
    """HF model id, e.g. 'google/gemma-2-2b-it'."""
    teacher: str
    """OpenRouter id for the teacher LLM that drives the inspect-ai react agent."""

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
    min_steps: int = 60
    """Floor for steps. With 15 pairs / batch=4 / 3 epochs = ~11 effective
    steps, well below convergence; floor pulls it up so the lr schedule
    actually has room to cosine-decay."""

    # ─ dialogue ─
    eval_batch_size: int = 4
    dialogue_max_new_tokens: int = 2048
    enable_thinking: bool = False     # Qwen3 family

    # ─ data ─
    n_train_pairs: int = 15
    """Per-round prompts sampled from POOL. Student generates a c=0
    completion seeded under rej's TODO as reference; teacher rewrites
    BOTH rej and cho as twinned poles (same voice, only axis flipped)."""
    min_pairs_to_train: int = 10
    """Gate before train_student: ≥ this many pairs must have BOTH
    rej and cho filled (TODOs replaced). Lets the agent skip pairs
    that are unsalvageable."""
    gen_max_new_tokens: int = 2048
    """Student seed-gen budget. Longer → teacher sees more of the
    student's natural failure mode for reference (but rewrites it)."""

    max_len: int = 2048
    """Train-time max sequence length for collating pairs."""

    c_scan_json_max_new_tokens: int = 4096
    """Max free-gen tokens per c_scan JSON probe. Real models need 4096+
    for the multi-paragraph probes to reach the JSON tail. Tiny smoke
    overrides to a small value to keep `just smoke` ~3 min."""

    # ─ steering coefficient ─
    signed_C: float = 2.0
    """Initial probe coefficient — c_scan walks DOWN from here (×0.5)
    until pmass ≥ 0.99 × baseline AND all valid_json probes parse. Then
    apply ×0.75 backoff for cumulative-history safety. Coherent adapters
    bake near init, fragile ones get tamer baked C. Sidecar — agent
    never sees it."""

    # ─ outer loop ─
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
        # 2× the default floor. With lr=1e-2 + cosine decay over 60 steps,
        # lr falls below 1e-3 by step 33 — too short to actually open the
        # margin (60-step trace plateaued at ‖Δs‖=1.97 from step 50+).
        # 120 steps gives the high lr more room to land before decay.
        min_steps=120,
    ),
    "gemma-9b": RunConfig(
        model="google/gemma-2-9b-it",
        teacher="qwen/qwen3.5-9b",
        train_batch_size=8,
        eval_batch_size=8,
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
        train_batch_size=2,
        eval_batch_size=2,
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
        min_steps=240,
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
        min_pairs_to_train=3,
        n_rounds=1,
        dialogue_max_new_tokens=32,
        gen_max_new_tokens=32,
        max_len=128,
        c_scan_json_max_new_tokens=32,
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
        min_pairs_to_train=3,
        n_rounds=1,
        dialogue_max_new_tokens=32,
        gen_max_new_tokens=32,
        max_len=128,
    ),
}


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
