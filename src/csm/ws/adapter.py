"""ModulatedLoRA: one LoRA adapter with a scalar coefficient `c`.

Forked from `weight-steering-lite/src/wsl/adapter.py`, trimmed:
- Dropped `layer_range` (depth band) — apply to all matching layers.
- Dropped 4-bit / bnb branch.
- Kept `HistoryBake` for round composition.

Training optimises the adapter so that `c=+1` reproduces chosen behaviour
and `c=-1` reproduces rejected behaviour on the same prompt. At eval
time `c` interpolates: `c=0` -> identical to base, `c=±1` -> trained
extremes.

Math (per target Linear with weight W : d_out × d_in):
    h     = W x
    delta = (alpha / r) * B @ A @ x       # A: r×d_in, B: d_out×r
    y     = h + c * delta                  # c=0 → exact base

Init: A ~ kaiming_uniform, B ~ N(1e-4, 1e-4). The tiny nonzero B breaks
sign-symmetry between +c and -c poles at init (loss is even in c at
B=0), giving the optimiser a signed gradient to follow.
"""
from __future__ import annotations

import re
from contextlib import contextmanager
from dataclasses import dataclass

import torch
import torch.nn.functional as F
from jaxtyping import Float
from loguru import logger
from torch import Tensor, nn


@dataclass
class LoRAConfig:
    r: int = 16
    alpha: float = 32.0
    # "all-linear" = every nn.Linear minus exclusions (PEFT default).
    # Otherwise: regex substrings matched against module names.
    targets: tuple[str, ...] = ("all-linear",)
    exclude: tuple[str, ...] = ("vision_tower", "lm_head")
    dtype: torch.dtype = torch.bfloat16


def _match(name: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(p, name) for p in patterns)


def _find_targets(model: nn.Module, cfg: LoRAConfig) -> list[tuple[str, nn.Linear]]:
    all_linear = "all-linear" in cfg.targets
    out = [
        (name, m) for name, m in model.named_modules()
        if isinstance(m, nn.Linear)
        and (all_linear or _match(name, cfg.targets))
        and not _match(name, cfg.exclude)
    ]
    if not out:
        raise RuntimeError(f"no targets matched {cfg.targets!r} (excluded {cfg.exclude!r})")
    return out


class ModulatedLoRA:
    """Hook-based LoRA with scalar coefficient `c`.

    Not an nn.Module: `__call__` is repurposed as a context manager for
    `with lora(model, c=...):` syntax. Params live in `self.A` / `self.B`;
    use `lora.parameters()` for the optimiser.
    """

    def __init__(self, model: nn.Module, r: int = 16, alpha: float = 32.0,
                 targets: tuple[str, ...] = ("all-linear",),
                 dtype: torch.dtype = torch.bfloat16):
        self.cfg = LoRAConfig(r=r, alpha=alpha, targets=targets, dtype=dtype)
        self._handles: list = []
        self._c: float = 0.0
        self._attached: bool = False

        device = next(model.parameters()).device
        targets_found = _find_targets(model, self.cfg)
        self.A: dict[str, nn.Parameter] = {}
        self.B: dict[str, nn.Parameter] = {}
        self._target_layers: dict[str, nn.Linear] = {}
        for name, layer in targets_found:
            d_in, d_out = layer.in_features, layer.out_features
            A = torch.empty(self.cfg.r, d_in, dtype=self.cfg.dtype, device=device)
            nn.init.kaiming_uniform_(A, a=5 ** 0.5)
            B = torch.empty(d_out, self.cfg.r, dtype=self.cfg.dtype, device=device)
            nn.init.normal_(B, mean=1e-4, std=1e-4)
            self.A[name] = nn.Parameter(A)
            self.B[name] = nn.Parameter(B)
            self._target_layers[name] = layer

        for p in model.parameters():
            p.requires_grad_(False)
        n_train = sum(p.numel() for p in self.parameters())
        logger.debug(f"ModulatedLoRA: {len(targets_found)} targets, r={self.cfg.r}, "
                     f"trainable={n_train:,}")

    def parameters(self):
        for p in self.A.values():
            yield p
        for p in self.B.values():
            yield p

    def _make_hook(self, name: str):
        scale = self.cfg.alpha / self.cfg.r
        A: Float[Tensor, "r i"] = self.A[name]
        B: Float[Tensor, "o r"] = self.B[name]

        def hook(layer: nn.Linear, args, y: Tensor) -> Tensor:
            if self._c == 0.0:
                return y                              # short-circuit
            (x,) = args
            xA = x.to(A.dtype)
            h = F.linear(xA, A)                       # x @ A.T via cuBLAS
            delta = F.linear(h, B)                    # h @ B.T via cuBLAS
            return y + (self._c * scale * delta).to(y.dtype)

        return hook

    @contextmanager
    def __call__(self, model: nn.Module, c: float = 1.0):
        """`with lora(model):` -> c=+1. `with lora(model, c=...):` -> custom.

        Hooks registered on enter, removed on exit. Re-entry rejected: exit
        the outer block first.
        """
        if self._attached:
            raise RuntimeError("ModulatedLoRA already attached; exit outer `with` first")
        self._c = float(c)
        for name, layer in self._target_layers.items():
            self._handles.append(layer.register_forward_hook(self._make_hook(name)))
        self._attached = True
        try:
            yield self
        finally:
            for h in self._handles:
                h.remove()
            self._handles.clear()
            self._attached = False
            self._c = 0.0

    def set_coeff(self, c: float) -> None:
        self._c = float(c)

    @property
    def c(self) -> float:
        return self._c

    # ---- save / load -------------------------------------------------------

    def save(self, path: str, extra_meta: dict[str, str] | None = None) -> None:
        from safetensors.torch import save_file
        sd = {f"A.{k.replace('.', '__')}": v.detach().cpu() for k, v in self.A.items()}
        sd.update({f"B.{k.replace('.', '__')}": v.detach().cpu() for k, v in self.B.items()})
        meta = {"r": str(self.cfg.r), "alpha": str(self.cfg.alpha),
                "targets": ",".join(self.cfg.targets)}
        if extra_meta:
            meta.update(extra_meta)
        save_file(sd, path, metadata=meta)

    def load(self, path: str) -> None:
        from safetensors.torch import load_file
        sd = load_file(path, device="cpu")
        ckpt_keys = {k[2:].replace("__", ".") for k in sd if k.startswith("A.")}
        init_keys = set(self.A.keys())
        if ckpt_keys != init_keys:
            raise RuntimeError(
                f"adapter target mismatch: checkpoint has {len(ckpt_keys)} targets, "
                f"init created {len(init_keys)}; would drop {len(ckpt_keys - init_keys)} "
                f"trained matrices and leave {len(init_keys - ckpt_keys)} init slots empty."
            )
        for k in self.A:
            kk = k.replace(".", "__")
            self.A[k].data.copy_(sd[f"A.{kk}"].to(self.A[k].device, self.A[k].dtype))
            self.B[k].data.copy_(sd[f"B.{kk}"].to(self.B[k].device, self.B[k].dtype))

    @classmethod
    def from_checkpoint(cls, model: nn.Module, path: str) -> "ModulatedLoRA":
        from safetensors import safe_open
        with safe_open(path, framework="pt") as f:
            meta = f.metadata()
        targets = tuple(meta["targets"].split(","))
        lora = cls(model, r=int(meta["r"]), alpha=float(meta["alpha"]),
                   targets=targets, dtype=next(model.parameters()).dtype)
        lora.load(path)
        return lora


# ---------------------------------------------------------------------------
# HistoryBake — kept adapters compose via a single gated forward hook.
# Storage: per-target concat A_cat = [A_1; A_2; …], B_cat = [s_1·B_1, …]
# so dW_combined = B_cat @ A_cat exactly, computed without materialising dW.
# Gate predicate set by training code: `lambda: lora._c != 0.0` makes the
# c=0 reference forward return pristine base.
# ---------------------------------------------------------------------------

class HistoryBake:
    def __init__(self, model: nn.Module, history: list[tuple["ModulatedLoRA", float]]):
        self._is_active = lambda: True       # inference default; train code overrides
        target_layers: dict[str, nn.Linear] = {}
        for lora, _ in history:
            for name, layer in lora._target_layers.items():
                target_layers.setdefault(name, layer)
        self._target_layers = target_layers

        r0 = history[0][0].cfg.r
        for lora, _ in history[1:]:
            assert lora.cfg.r == r0, f"kept-history rank mismatch: {lora.cfg.r} vs {r0}"
        target_dtype = history[0][0].cfg.dtype

        with torch.no_grad():
            A_cat: dict[str, Tensor] = {}
            B_cat: dict[str, Tensor] = {}
            for name, layer in target_layers.items():
                A_parts, B_parts = [], []
                for lora, c in history:
                    if name not in lora.A:
                        continue
                    s = c * lora.cfg.alpha / lora.cfg.r
                    A_parts.append(lora.A[name].to(target_dtype))
                    B_parts.append((s * lora.B[name]).to(target_dtype))
                A_cat[name] = torch.cat(A_parts, dim=0).to(layer.weight.device).detach()
                B_cat[name] = torch.cat(B_parts, dim=1).to(layer.weight.device).detach()
        self._A_cat = A_cat
        self._B_cat = B_cat

        self._handles = []
        for name, layer in target_layers.items():
            self._handles.append(layer.register_forward_hook(self._make_hook(name)))
        Nr = len(history) * r0
        logger.info(f"HistoryBake: {len(history)} kept adapter(s), r_total={Nr}")

    def _make_hook(self, name: str):
        A = self._A_cat[name]                         # (k_total, d_in)
        B = self._B_cat[name]                         # (d_out, k_total), scale pre-folded

        def hook(layer: nn.Linear, args, y: Tensor) -> Tensor:
            if not self._is_active():
                return y
            (x,) = args
            xA = x.to(A.dtype)
            h = F.linear(xA, A)                       # x @ A.T via cuBLAS
            delta = F.linear(h, B)                    # h @ B.T via cuBLAS
            return y + delta.to(y.dtype)

        return hook

    def set_gate(self, is_active) -> None:
        """is_active() -> bool. Training: `set_gate(lambda: lora._c != 0.0)`."""
        self._is_active = is_active

    def remove(self) -> None:
        for h in self._handles:
            h.remove()
        self._handles.clear()
