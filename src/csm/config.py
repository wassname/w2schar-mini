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
    adapter: Literal["lora", "pissa"] = "lora"
    """`lora` = free rank-r perturbation (B@A). `pissa` = top-r SVD of W
    physically extracted into the adapter (W mutated to W_res); trainable
    Δs reweights each singular direction. PiSSA is for hypothesis-testing
    'persona-axis steering lives in S-space'; needs larger r since the
    expressive space is tighter."""
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
        # 5e-4 not 1e-3: task 98 round00 trace blew at step 12 (lr 5.4e-4
        # during cosine warmup) — nll- jumped from 1.73→10.1, kl 1.0→2.2,
        # ‖Δs‖ kept climbing to 3.0 with chaotic 10-80 nll thereafter. Last
        # sane step was 11 at lr 5.0e-4. Cap at 5e-4 so warmup never crosses
        # the cliff.
        lr=5e-4,
        n_epochs=2.0,
        # 2× default kl_lambda: PiSSA 2b r=full trace showed coherence only
        # at C≤0.05 — more KL widens the usable C range. (For nf4 LoRA the
        # mechanism differs but the prescription transfers: tighter anchor.)
        kl_lambda=1.0,
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
