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
    n_epochs: float = 1.0
    max_len: int = 512

    # ─ generation ─
    gen_batch_size: int = 8
    max_new_tokens: int = 256

    # ─ dialogue + c_scan ─
    eval_batch_size: int = 4
    dialogue_max_new_tokens: int = 256
    cscan_n_gen: int = 32
    cscan_k: int = 200
    enable_thinking: bool = False     # Qwen3 family

    # ─ data ─
    n_pairs: int = 50
    """Per-round on-policy gen size. 50 is the mini default."""

    # ─ outer loop ─
    n_rounds: int = 2
    """Number of *keep* rounds the agent aims for. Drops don't count."""


CONFIGS: dict[str, RunConfig] = {
    "gemma-2b": RunConfig(
        model="google/gemma-2-2b-it",
        teacher="qwen/qwen3.5-9b",
        train_batch_size=4,
        gen_batch_size=8,
        eval_batch_size=4,
    ),
    "gemma-12b": RunConfig(
        model="google/gemma-3-12b-it",
        teacher="qwen/qwen3.5-9b",
        train_batch_size=2,
        gen_batch_size=4,
        eval_batch_size=2,
    ),
    # Smoke: tiny-random Qwen3 5-layer. ~3 min on CPU, garbage outputs.
    "tiny": RunConfig(
        model="wassname/qwen3-5lyr-tiny-random",
        teacher="qwen/qwen3.5-9b",
        train_batch_size=2,
        gen_batch_size=2,
        eval_batch_size=2,
        n_pairs=4,
        n_rounds=1,
        max_new_tokens=32,
        dialogue_max_new_tokens=32,
        cscan_n_gen=8,
        max_len=128,
    ),
}


def config_by_model(model_id: str) -> RunConfig:
    """Fall back to a default RunConfig if `model_id` isn't in CONFIGS."""
    for cfg in CONFIGS.values():
        if cfg.model == model_id:
            return cfg
    return RunConfig(model=model_id, teacher="qwen/qwen3.5-9b")
