"""C-scan: largest |C| where pmass(c) ≥ gate × baseline, then ×backoff.

Sidecar (the agent never sees this). pmass proxy: mean P assigned by the
steered model to base-model top-K tokens on a generated continuation.
Coherent steered → mass stays near base; collapsed steered → mass leaks
to weird tokens (the looping/degenerate failure mode).

Simpler than the wsl v2: walk down only (×0.5) until pmass ≥ gate, then
×backoff. No walk-up, no regula-falsi refinement. The fixed-bake design
(no per-round signed_C in the kept artifact metadata) is fine because
inference uses whatever c_scan picks at train time.
"""
from __future__ import annotations

import math
from typing import Literal

import torch
from loguru import logger

from csm.ws.adapter import ModulatedLoRA


C_MIN, MAX_PROBES = 0.05, 8


@torch.no_grad()
def pmass(model, tok, lora: ModulatedLoRA, c: float, probes: list[str], *,
          k: int = 200, n_gen: int = 32, batch_size: int = 2) -> float:
    """Top-K coherence proxy. 1) generate at c=0 (base+history), record top-K
    indices per generated position. 2) re-score the SAME sequence at c=c,
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

            with lora(model, c=0.0):
                gen = model.generate(
                    **enc, max_new_tokens=n_gen, do_sample=False,
                    pad_token_id=pad_id, eos_token_id=tok.eos_token_id,
                )
                gen_attn = (gen != pad_id).long()
                logits_b = model(input_ids=gen, attention_mask=gen_attn).logits
                gen_pos = slice(in_len - 1, gen.shape[1] - 1)
                base_topk = logits_b[:, gen_pos].topk(k, dim=-1).indices

            with lora(model, c=c):
                logits_s = model(input_ids=gen, attention_mask=gen_attn).logits[:, gen_pos]
                p_s = torch.softmax(logits_s.float(), dim=-1)
                topk_p = p_s.gather(-1, base_topk).sum(-1)

            attn = (gen != pad_id)[:, in_len:][:, :topk_p.shape[1]]
            pms.append((topk_p[attn].mean().item() if attn.any()
                        else topk_p.mean().item()))
    finally:
        tok.padding_side = old_side
    pm = sum(pms) / max(len(pms), 1)
    if not math.isfinite(pm):
        raise RuntimeError(f"NaN pmass at c={c}")
    return pm


def c_scan(model, tok, lora: ModulatedLoRA, probes: list[str], *,
           init_c: float = 1.0,
           gate_frac: float = 0.98,
           backoff: float = 0.75,
           sign: Literal[1, -1] = 1,
           k: int = 200, n_gen: int = 32,
           batch_size: int = 2) -> tuple[float, list]:
    """Walk |C| down by ×0.5 until pmass(c) ≥ gate_frac × baseline_pmass
    (tight: ≥98% of base coherence on top-K). Then return sign * c *
    backoff for a further safety margin."""
    baseline = pmass(model, tok, lora, c=0.0, probes=probes,
                     k=k, n_gen=n_gen, batch_size=batch_size)
    gate = gate_frac * baseline
    logger.info(f"c_scan: baseline pmass={baseline:.3f}, gate={gate:.3f}")
    trace = [("baseline", 0.0, baseline)]

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
            logger.warning(f"c_scan: never coherent (c<{C_MIN}); using c={C_MIN}")
            c = C_MIN
            break
    else:
        logger.warning(f"c_scan: hit MAX_PROBES; using c={c}")

    final = sign * c * backoff
    trace.append(("final", abs(final), final))
    logger.info(f"c_scan final: signed_C={final:+.4f} (|c|={c:.3f} × backoff={backoff})")
    return final, trace
