"""Compose N LoRA adapters into a model's weights for fast inference.

Two backends, one surface (`baked()` context manager):

- **Float layers** (bf16 / fp16 nn.Linear): apply Σ_i c_i * (α_i/r_i) * B_i @ A_i
  to `layer.weight` in-place. Restore from a CPU backup on exit.
  Forward pass has NO runtime LoRA overhead — weights already include dW.
  Memory: CPU backup of W (~5GB for 9b bf16, ~13GB for 27b).

- **Quantized layers** (bnb Linear4bit / Linear8bitLt): can't modify the
  quantized buffer reversibly. Concatenate all adapters into one stacked
  low-rank pair `(A_stack, B_stack)` and register ONE forward hook per layer
  doing two `F.linear` calls. N adapters cost the same as 1 at forward.

Both paths take the same AdapterSpec list, so callers don't see the split.
Use for inference only (csm eval, dialogues, gen_completions). Training
varies `c` per step → use the gated ModulatedLoRA / HistoryBake hooks
instead.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass

import torch
import torch.nn as nn
import torch.nn.functional as F
from loguru import logger

from csm.ws.adapter import ModulatedLoRA


@dataclass
class AdapterSpec:
    """One LoRA's worth of parameters, CPU-resident between bakes.

    A[name]: (r, d_in)        B[name]: (d_out, r)        scale = α/r
    Materialized to layer device+dtype briefly during bake; freed after.
    """
    A: dict[str, torch.Tensor]
    B: dict[str, torch.Tensor]
    alpha: float
    r: int
    default_c: float = 1.0

    @classmethod
    def from_lora(cls, lora: ModulatedLoRA, default_c: float = 1.0) -> "AdapterSpec":
        return cls(
            A={k: v.detach().cpu() for k, v in lora.A.items()},
            B={k: v.detach().cpu() for k, v in lora.B.items()},
            alpha=lora.cfg.alpha, r=lora.cfg.r, default_c=default_c,
        )

    @classmethod
    def from_checkpoint(cls, model: nn.Module, path: str,
                        default_c: float = 1.0) -> "AdapterSpec":
        """Load adapter.safetensors as a CPU-resident spec without
        attaching hooks (unlike ModulatedLoRA.from_checkpoint)."""
        lora = ModulatedLoRA.from_checkpoint(model, path)
        spec = cls.from_lora(lora, default_c=default_c)
        del lora                                     # drop the cuda copies
        return spec


def _is_quantized(layer: nn.Linear) -> bool:
    """bnb.Linear4bit / Linear8bitLt detection. False for bf16/fp16."""
    return type(layer).__name__ in ("Linear4bit", "Linear8bitLt")


def _gather_target_layers(model: nn.Module,
                          adapters: list[AdapterSpec]) -> dict[str, nn.Linear]:
    """Union of named layers across all adapters' target sets."""
    wanted: set[str] = set()
    for a in adapters:
        wanted.update(a.A.keys())
    return {name: m for name, m in model.named_modules() if name in wanted}


@contextmanager
def baked(model: nn.Module, adapters: list[AdapterSpec],
          c_overrides: list[float] | None = None):
    """Apply N adapters at fixed c per adapter. Restore on exit.

    Composable: `baked(model, hist_specs + [current_spec])` bakes the full
    cumulative state in one call. Per-adapter c via `default_c` or
    `c_overrides=[c0, c1, ...]`. No-op if adapters is empty.
    """
    if not adapters:
        yield
        return
    cs = list(c_overrides) if c_overrides is not None else [a.default_c for a in adapters]
    assert len(cs) == len(adapters), \
        f"c_overrides len {len(cs)} != adapters len {len(adapters)}"

    layers = _gather_target_layers(model, adapters)
    float_layers = {n: l for n, l in layers.items() if not _is_quantized(l)}
    quant_layers = {n: l for n, l in layers.items() if _is_quantized(l)}

    # ─ Float backend: in-place W += Σ c_i * (α_i/r_i) * (B_i @ A_i)
    W_backup: dict[str, torch.Tensor] = {}
    for name, layer in float_layers.items():
        W_backup[name] = layer.weight.detach().cpu().clone()
        dev, dt = layer.weight.device, layer.weight.dtype
        dW = torch.zeros_like(layer.weight)
        for adapter, c in zip(adapters, cs):
            if name not in adapter.A or c == 0.0:
                continue
            A = adapter.A[name].to(dev, dt)
            B = adapter.B[name].to(dev, dt)
            scale = (c * adapter.alpha) / adapter.r
            dW.add_(scale * (B @ A))
        layer.weight.data.add_(dW)

    # ─ Quant backend: one stacked-low-rank hook per layer (N adapters → one pair)
    quant_handles = []
    for name, layer in quant_layers.items():
        A_parts, B_parts = [], []
        for adapter, c in zip(adapters, cs):
            if name not in adapter.A or c == 0.0:
                continue
            scale = (c * adapter.alpha) / adapter.r
            A_parts.append(adapter.A[name].to(layer.weight.device))
            B_parts.append((scale * adapter.B[name]).to(layer.weight.device))
        if not A_parts:
            continue
        A_stack = torch.cat(A_parts, dim=0)           # (Σr, d_in)
        B_stack = torch.cat(B_parts, dim=1)           # (d_out, Σr)

        def _hook(_m, args, y, A=A_stack, B=B_stack):
            (x,) = args
            h = F.linear(x.to(A.dtype), A)            # x @ A.T
            return y + F.linear(h, B).to(y.dtype)     # h @ B.T

        quant_handles.append(layer.register_forward_hook(_hook))

    logger.debug(f"baked: {len(adapters)} adapter(s), "
                 f"{len(float_layers)} float (in-place), "
                 f"{len(quant_layers)} quantized (stacked-LR hook)")
    try:
        yield
    finally:
        for name, layer in float_layers.items():
            layer.weight.data.copy_(W_backup[name].to(layer.weight.device))
        for h in quant_handles:
            h.remove()
