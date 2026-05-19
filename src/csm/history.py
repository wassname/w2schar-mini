"""Load base model + kept-round adapters composed via HistoryBake.

Forked from `weight-steering-lite/src/wsl/load_with_history.py`, trimmed:
- Dropped 4-bit / BitsAndBytesConfig branch.
- Dropped flash-attention-2 hard requirement (set via env var if wanted).
- Single happy path: bf16, device_map="auto".

Round dirs whose `judgment.json.action == "keep"` count as history. The
caller resolves which dirs to compose (typically: all kept rounds before
this one, in order).
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Iterable

import torch
from loguru import logger
from transformers import AutoModelForCausalLM, AutoTokenizer

from csm.adapter import HistoryBake, ModulatedLoRA


_ROUND_RE = re.compile(r"^round(\d+)$")


def parse_round_n(name: str) -> int | None:
    m = _ROUND_RE.match(name)
    return int(m.group(1)) if m else None


def load_base_with_history(
    model_id: str,
    history_dirs: Iterable[Path] | None = None,
    *,
    dtype: torch.dtype = torch.bfloat16,
    device_map: str = "auto",
):
    """Load base model in bf16; attach kept-round adapters as a single
    `HistoryBake` (combined dW per target layer, gated forward hook).
    Returns (model, tokenizer, history_bake_or_None).

    Base weights stay pristine — history contributes via the hook, gated
    on an external `is_active` callable. Default gate = always-on
    (inference). Training code must
    `history_bake.set_gate(lambda: lora._c != 0.0)` so the c=0 reference
    forward returns pristine base.
    """
    tok = AutoTokenizer.from_pretrained(model_id)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    tok.padding_side = "left"

    attn_impl = os.environ.get("CSM_ATTN_IMPL", "eager")  # flash_attention_2 if installed
    model = AutoModelForCausalLM.from_pretrained(
        model_id,
        device_map=device_map,
        torch_dtype=dtype,
        low_cpu_mem_usage=True,
        attn_implementation=attn_impl,
    )
    model.eval()

    history_dirs = list(history_dirs or [])
    history: list[tuple[ModulatedLoRA, float]] = []
    for rd in history_dirs:
        adapter_path = rd / "adapter.safetensors"
        cal_path = rd / "calibration.json"
        if not adapter_path.exists():
            raise FileNotFoundError(f"kept-round {rd.name} missing adapter.safetensors")
        if not cal_path.exists():
            raise FileNotFoundError(f"kept-round {rd.name} missing calibration.json")
        signed_C = float(json.loads(cal_path.read_text())["signed_C"])
        lora = ModulatedLoRA.from_checkpoint(model, str(adapter_path))
        history.append((lora, signed_C))
        logger.info(f"loaded {rd.name}/adapter @ kept c={signed_C:+.4f}")

    history_bake = HistoryBake(model, history) if history else None
    if history_bake is not None:
        logger.info(f"loaded base + HistoryBake over {len(history)} kept adapter(s)")
    return model, tok, history_bake


def kept_history_dirs(slug_dir: Path, before_round: int | None = None) -> list[Path]:
    """Sorted list of `<slug_dir>/roundNN` paths whose judgment.action == 'keep'.
    If `before_round` is given, only include rounds with index < before_round.
    """
    keep = []
    for rd in sorted(p for p in slug_dir.glob("round*") if p.is_dir()):
        n = parse_round_n(rd.name)
        if n is None:
            continue
        if before_round is not None and n >= before_round:
            continue
        j = rd / "judgment.json"
        if j.exists() and json.loads(j.read_text()).get("action") == "keep":
            keep.append(rd)
    return keep
