"""C-scan v2: largest |C| where pmass(c) ≥ gate_frac × baseline, ×0.75 backoff.

pmass proxy (no tinymfv): mean P assigned by steered model to the
*base+history*'s top-K tokens at each generated position. Coherent
steered → mass stays near base; collapsed steered → mass leaks to weird
tokens.

The c=0 baseline is base+history (inference context — gate always on).
The sign of `signed_C` is fixed by axis (+1 = "less authority"); the
agent never picks sign.
"""
from __future__ import annotations

import math
from typing import Literal

import torch
from loguru import logger

from csm.ws.adapter import ModulatedLoRA


C_MIN, C_MAX, MAX_PROBES = 0.02, 1.0, 12


@torch.no_grad()
def pmass(model, tok, lora: ModulatedLoRA, c: float, probes: list[str], *,
          k: int = 200, n_gen: int = 32, batch_size: int = 2) -> float:
    """Top-K coherence proxy. 1) generate at c=0 (base+history), record top-K
    indices per position. 2) re-score the SAME generated sequence at c=c,
    gather P over those indices, mean over positions."""
    old_side = tok.padding_side
    tok.padding_side = "left"
    pad_id = tok.pad_token_id if tok.pad_token_id is not None else tok.eos_token_id
    pms: list[float] = []
    try:
        for i in range(0, len(probes), batch_size):
            batch = probes[i: i + batch_size]
            enc = tok(batch, return_tensors="pt", padding=True).to(model.device)
            in_len = enc["input_ids"].shape[1]

            # 1) generate at c=0 and record base+history top-K per position
            with lora(model, c=0.0):
                gen = model.generate(
                    **enc, max_new_tokens=n_gen, do_sample=False,
                    pad_token_id=pad_id, eos_token_id=tok.eos_token_id,
                )
                # Build attention_mask for the rescoring forward pass: left-pad
                # tokens from the prompt and post-EOS pads in the gen tail must
                # be excluded, else the LM attends to garbage positions and the
                # pmass calibration drifts.
                gen_attn = (gen != pad_id).long()
                logits_b = model(input_ids=gen, attention_mask=gen_attn).logits
                # only the generated-token positions
                gen_pos = slice(in_len - 1, gen.shape[1] - 1)
                base_topk = logits_b[:, gen_pos].topk(k, dim=-1).indices  # [B, n_gen, k]

            # 2) re-score same sequence at c=c, gather over base topK
            with lora(model, c=c):
                logits_s = model(input_ids=gen, attention_mask=gen_attn).logits[:, gen_pos]
                p_s = torch.softmax(logits_s.float(), dim=-1)
                topk_p = p_s.gather(-1, base_topk).sum(-1)                # [B, n_gen]

            # mask out positions past EOS (no signal)
            attn = (gen != pad_id)[:, in_len:]
            attn = attn[:, :topk_p.shape[1]]
            if attn.any():
                pms.append(topk_p[attn].mean().item())
            else:
                pms.append(topk_p.mean().item())
    finally:
        tok.padding_side = old_side
    pm = sum(pms) / max(len(pms), 1)
    if not math.isfinite(pm):
        raise RuntimeError(f"NaN pmass at c={c}")
    return pm


def c_scan(model, tok, lora: ModulatedLoRA, probes: list[str], *,
           init_c: float = 1.0,
           gate_frac: float = 0.85,
           backoff: float = 0.75,
           sign: Literal[1, -1] = 1,
           k: int = 200, n_gen: int = 32,
           batch_size: int = 2) -> tuple[float, list]:
    """Walk |C| until pmass < gate, then walk back up while still coherent,
    back off 25%. Returns (signed_C, trace)."""
    baseline = pmass(model, tok, lora, c=0.0, probes=probes,
                     k=k, n_gen=n_gen, batch_size=batch_size)
    gate = gate_frac * baseline
    logger.info(f"c_scan: baseline pmass={baseline:.3f}, gate={gate:.3f}")
    trace = [("baseline", 0.0, baseline)]

    # ── walk DOWN until coherent ────────────────────────────────────────
    c = init_c
    for _ in range(MAX_PROBES):
        pm = pmass(model, tok, lora, c=sign * c, probes=probes,
                   k=k, n_gen=n_gen, batch_size=batch_size)
        trace.append(("down", c, pm))
        logger.info(f"c_scan down  c={sign*c:+.3f}  pmass={pm:.3f}")
        if pm >= gate:
            break
        c *= 0.5
        if c < C_MIN:
            raise RuntimeError(f"c_scan: never coherent (c<{C_MIN}); trace={trace}")
    else:
        raise RuntimeError(f"c_scan: down-walk MAX_PROBES; trace={trace}")

    # ── walk UP while still coherent ────────────────────────────────────
    for _ in range(MAX_PROBES):
        c_up = min(c * 1.25, C_MAX)
        if c_up <= c:
            break  # hit C_MAX, can't go further
        pm = pmass(model, tok, lora, c=sign * c_up, probes=probes,
                   k=k, n_gen=n_gen, batch_size=batch_size)
        trace.append(("up", c_up, pm))
        logger.info(f"c_scan up    c={sign*c_up:+.3f}  pmass={pm:.3f}")
        if pm < gate:
            break
        c = c_up

    final = sign * c * backoff
    trace.append(("final", abs(final), final))
    logger.info(f"c_scan final: signed_C={final:+.4f} (|c|={c:.3f} × backoff={backoff})")
    return final, trace
