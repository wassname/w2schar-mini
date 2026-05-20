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

    # ─ dialogue ─
    eval_batch_size: int = 4
    dialogue_max_new_tokens: int = 512
    enable_thinking: bool = False     # Qwen3 family

    # ─ data ─
    n_train_pairs: int = 15
    """Per-round prompts sampled from POOL. Student generates `rej` at
    c=0 (on-policy), agent writes `cho` mirroring along the axis."""
    min_pairs_to_train: int = 10
    """Gate before train_student: ≥ this many pairs must have cho filled
    (TODO replaced). Lets the agent skip pairs whose rej was a clean
    refusal or otherwise unsalvageable."""
    gen_max_new_tokens: int = 512
    """Student rej generation budget. Longer → adapter learns from longer
    sequences → less prone to looping degenerate text at the bake C."""

    # ─ steering coefficient ─
    signed_C: float = 0.75
    """Fixed coefficient baked into history + post-dialogue. No per-round
    c-scan; the agent's mark_exam keep/drop catches incoherence."""

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
    "gemma-12b": RunConfig(
        model="google/gemma-3-12b-it",
        teacher="qwen/qwen3.5-9b",
        train_batch_size=2,
        eval_batch_size=2,
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
