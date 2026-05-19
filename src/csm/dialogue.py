"""Probe replay: multi-turn greedy dialogue, byte-identical pre/post.

Each probe = `{id, opening, followups}`. We start a chat with the
opening, take the model's reply, then for each scripted followup append
it as the next user turn and take the next reply. Same probe set, same
followups, same decoding parameters pre and post → only the model's
replies differ.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import torch
from loguru import logger

from csm.adapter import ModulatedLoRA


@dataclass
class DialogueCfg:
    max_new_tokens: int = 512
    enable_thinking: bool = False
    seed: int = 42


@torch.no_grad()
def _gen_one(model, tok, messages: list[dict], *, max_new_tokens: int,
             enable_thinking: bool, seed: int) -> str:
    rendered = tok.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True,
        enable_thinking=enable_thinking,
    )
    enc = tok(rendered, return_tensors="pt").to(model.device)
    torch.manual_seed(seed)
    out = model.generate(
        **enc, max_new_tokens=max_new_tokens, do_sample=False,
        pad_token_id=tok.pad_token_id or tok.eos_token_id,
        eos_token_id=tok.eos_token_id,
    )
    cont = out[0, enc["input_ids"].shape[1]:]
    return tok.decode(cont, skip_special_tokens=True).strip()


def run_probe(model, tok, probe: dict, *, cfg: DialogueCfg) -> dict:
    """Run one probe: opening + each followup in sequence. Returns the
    full turn list."""
    turns: list[dict] = []
    messages = [{"role": "user", "content": probe["opening"]}]
    reply = _gen_one(model, tok, messages,
                     max_new_tokens=cfg.max_new_tokens,
                     enable_thinking=cfg.enable_thinking,
                     seed=cfg.seed)
    turns.append({"role": "user", "text": probe["opening"]})
    turns.append({"role": "assistant", "text": reply})
    messages.append({"role": "assistant", "content": reply})

    for fu in probe["followups"]:
        messages.append({"role": "user", "content": fu})
        reply = _gen_one(model, tok, messages,
                         max_new_tokens=cfg.max_new_tokens,
                         enable_thinking=cfg.enable_thinking,
                         seed=cfg.seed)
        turns.append({"role": "user", "text": fu})
        turns.append({"role": "assistant", "text": reply})
        messages.append({"role": "assistant", "content": reply})

    return {"id": probe["id"], "turns": turns}


def dialogue(model, tok, probes: list[dict], out_path: Path,
             *, lora: Optional[ModulatedLoRA] = None, c: float = 0.0,
             cfg: DialogueCfg = DialogueCfg()) -> dict:
    """Replay all probes, optionally under `with lora(c=c)`. Writes
    JSON to `out_path` and returns the same payload."""
    payload = {"id": out_path.stem, "c": c, "probes": []}
    if lora is not None and c != 0.0:
        with lora(model, c=c):
            for p in probes:
                logger.info(f"dialogue [{p['id']}] @ c={c:+.3f}")
                payload["probes"].append(run_probe(model, tok, p, cfg=cfg))
    else:
        for p in probes:
            logger.info(f"dialogue [{p['id']}] @ c=0 (base+history)")
            payload["probes"].append(run_probe(model, tok, p, cfg=cfg))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2))
    return payload
