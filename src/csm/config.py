"""Per-model run config registry.

Lifted from `weight-steering-lite/src/wsl/prompts.py:CONFIGS`, trimmed
to the two profiles we plan to validate first. Hard-won numbers stay
here (the agent never sees them).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RunConfig:
    model: str
    """HF model id, e.g. 'google/gemma-2-2b-it'."""
    teacher: str
    """OpenRouter id for the teacher LLM that drives the inspect-ai react agent."""

    # ─ LoRA ─
    lora_r: int = 16
    lora_alpha: float = 32.0
    targets: tuple[str, ...] = ("all-linear",)

    # ─ training ─
    lr: float = 2e-4
    kl_lambda: float = 0.032
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
    until pmass ≥ 0.98 × baseline. No backoff (the tight 0.98 gate is
    the safety margin; the prior ×0.75 backoff was making interventions
    too weak to clear bf16 eval noise). Coherent adapters bake at init,
    fragile ones get tamer baked C. Sidecar — agent never sees it."""

    # ─ outer loop ─
    n_rounds: int = 2
    """Number of *keep* rounds the agent aims for. Drops don't count."""


CONFIGS: dict[str, RunConfig] = {
    "gemma-2b": RunConfig(
        model="google/gemma-2-2b-it",
        teacher="qwen/qwen3.5-9b",
        train_batch_size=4,
        eval_batch_size=4,
    ),
    "gemma-9b": RunConfig(
        model="google/gemma-2-9b-it",
        teacher="qwen/qwen3.5-9b",
        train_batch_size=2,
        eval_batch_size=2,
    ),
    "gemma-12b": RunConfig(
        model="google/gemma-3-12b-it",
        teacher="qwen/qwen3.5-9b",
        train_batch_size=2,
        eval_batch_size=2,
    ),
    "gemma-27b": RunConfig(
        model="google/gemma-2-27b-it",
        teacher="qwen/qwen3.5-9b",
        train_batch_size=1,
        eval_batch_size=1,
    ),
    # Smoke: tiny-random Qwen3 5-layer. ~1 min on CPU, garbage outputs.
    "tiny": RunConfig(
        model="wassname/qwen3-5lyr-tiny-random",
        teacher="qwen/qwen3.5-9b",
        train_batch_size=2,
        eval_batch_size=2,
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
            return cfg
    return RunConfig(model=model_id, teacher="qwen/qwen3.5-9b")
