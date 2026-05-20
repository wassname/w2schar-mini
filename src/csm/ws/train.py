"""Path-loss ModulatedLoRA training with reverse-KL coherence penalty.

Forked from `weight-steering-lite/src/wsl/train.py`, trimmed:
- Full KL on logits (no top-K approximation). Fine for the smaller models
  + smaller batches we use here; swap to top-K if memory becomes the
  bottleneck.
- Dropped held-out probe-eval loop (we evaluate via dialogue after train).

Per (prompt, cho, rej), sampled C ∈ (0, 1]:

    L_pos = C·nll(cho | c=+C)  +  β·mean_KL(steer ‖ base) on cho label tokens
    L_neg = C·nll(rej | c=-C)  +  β·mean_KL(steer ‖ base) on rej label tokens

Both terms in nats. β trades steering signal vs distribution shift;
weight-decay + β jointly pull toward "no-op" while NLL pulls toward
cho/rej.

`base` is the c=0 forward = pristine base (HistoryBake gate disabled
when `lora._c == 0`). So a new adapter that fights a prior bake pays
its KL bill cumulatively from base, not iteratively from last bake.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import torch
from loguru import logger
from torch.optim import AdamW
from torch.utils.data import DataLoader, Dataset
from transformers import get_cosine_schedule_with_warmup
from tqdm.auto import tqdm

from csm.ws.adapter import ModulatedLoRA


@dataclass
class TrainCfg:
    r: int = 16
    alpha: float = 32.0
    targets: tuple[str, ...] = ("all-linear",)
    steps: int = 200
    warmup_ratio: float = 0.1
    batch_size: int = 4
    lr: float = 2e-4
    weight_decay: float = 0.01
    grad_clip: float = 1.0
    max_len: int = 512
    log_every: int = 5
    kl_lambda: float = 0.032
    """β: coefficient on mean reverse-KL per step (nats, matches NLL units).
    0 disables. Bump up if Δnll blows past +0.02 (coherence breaks); bump
    down if eval Δ stays at noise."""
    pcgrad: bool = True
    seed: int = 42


# ---------------------------------------------------------------------------
# Tokenisation: prompt+completion teacher-forced; label mask = prompt -100.
# Persona prefix is DROPPED at train time so the adapter learns the
# behaviour conditioned only on c, not on the persona prefix.
# ---------------------------------------------------------------------------

def build_tokens(tok, prompt: str, completion: str, max_len: int,
                 *, enable_thinking: bool = False) -> tuple[torch.Tensor, torch.Tensor]:
    """(input_ids, labels) where labels mask out the prompt portion."""
    prompt_text = tok.apply_chat_template(
        [{"role": "user", "content": prompt}],
        tokenize=False, add_generation_prompt=True,
        enable_thinking=enable_thinking,
    )
    full_text = prompt_text + completion + tok.eos_token
    prompt_ids = tok(prompt_text, add_special_tokens=False).input_ids
    full_ids = tok(full_text, add_special_tokens=False).input_ids
    full_ids = full_ids[:max_len]
    labels = list(full_ids)
    for i in range(min(len(prompt_ids), len(labels))):
        labels[i] = -100
    return torch.tensor(full_ids), torch.tensor(labels)


def collate(batch: list[tuple[torch.Tensor, torch.Tensor]], pad_id: int):
    max_len = max(b[0].shape[0] for b in batch)
    input_ids = torch.full((len(batch), max_len), pad_id, dtype=torch.long)
    labels = torch.full((len(batch), max_len), -100, dtype=torch.long)
    attn = torch.zeros((len(batch), max_len), dtype=torch.long)
    for i, (ids, lbl) in enumerate(batch):
        n = ids.shape[0]
        input_ids[i, :n] = ids
        labels[i, :n] = lbl
        attn[i, :n] = 1
    return input_ids, labels, attn


class PairDataset(Dataset):
    def __init__(self, pairs: list[dict], tok, max_len: int,
                 enable_thinking: bool = False):
        self.pairs = pairs
        self.tok = tok
        self.max_len = max_len
        self.enable_thinking = enable_thinking

    def __len__(self):
        return len(self.pairs)

    def __getitem__(self, i):
        p = self.pairs[i]
        ids_p, lbl_p = build_tokens(self.tok, p["prompt"], p["cho"], self.max_len,
                                    enable_thinking=self.enable_thinking)
        ids_n, lbl_n = build_tokens(self.tok, p["prompt"], p["rej"], self.max_len,
                                    enable_thinking=self.enable_thinking)
        return (ids_p, lbl_p), (ids_n, lbl_n)


def _pair_collate(batch, pad_id):
    pos = [b[0] for b in batch]
    neg = [b[1] for b in batch]
    ip, lp, ap = collate(pos, pad_id)
    in_, ln, an = collate(neg, pad_id)
    return ip, lp, ap, in_, ln, an


def _zerofill(grads, params):
    return [g if g is not None else torch.zeros_like(p) for g, p in zip(grads, params)]


def _kl_mean_full(logp_steer, logp_base, labels):
    """Reverse KL(p_steer ‖ p_base), per-token, mean over the SAME positions
    HF causal-LM CE averages over. HF shifts labels internally
    (loss = CE(logits[:, :-1], labels[:, 1:])) so we shift here too.

    Returns mean reverse-KL in nats over completion-predictive positions.
    """
    # Shift to match HF's labels-aware CE: logits[t] predicts label[t+1].
    logp_steer_sh = logp_steer[:, :-1, :]
    logp_base_sh = logp_base[:, :-1, :]
    mask_sh = (labels[:, 1:] != -100)
    p_s = logp_steer_sh.exp()
    kl_per_tok = (p_s * (logp_steer_sh - logp_base_sh)).sum(dim=-1)    # [B, S-1]
    return kl_per_tok[mask_sh.bool()].mean()


def pcgrad_train_step(
    model, lora: ModulatedLoRA,
    ip, lp, ap, in_, ln, an,
    params: list,
    *,
    C: float,
    pcgrad: bool = True,
    kl_lambda: float = 0.0,
) -> dict:
    """One step: NLL on both poles + (optional) KL anchor to c=0 forward.
    PCGrad operates on the (NLL_pos, NLL_neg) gradients only — KL is
    added unprojected.
    """
    use_kl = kl_lambda > 0
    device = next(p.device for p in params)
    zero = torch.zeros((), device=device)

    # ---- c=0 reference forwards (no grad) ---------------------------------
    if use_kl:
        with torch.no_grad():
            with lora(model, c=0.0):
                logits_b_p = model(input_ids=ip, attention_mask=ap).logits.float()
                logits_b_n = model(input_ids=in_, attention_mask=an).logits.float()
            logp_b_p = torch.log_softmax(logits_b_p, dim=-1)
            logp_b_n = torch.log_softmax(logits_b_n, dim=-1)

    # ---- cho at c=+C ------------------------------------------------------
    with lora(model, c=+C):
        out_p = model(input_ids=ip, attention_mask=ap, labels=lp)
        L_pos_nll = C * out_p.loss
        if use_kl:
            logp_p = torch.log_softmax(out_p.logits.float(), dim=-1)
            kl_p = _kl_mean_full(logp_p, logp_b_p, lp)
            L_pos_kl = kl_lambda * kl_p
    g_pos_nll = _zerofill(torch.autograd.grad(
        L_pos_nll, params, retain_graph=use_kl, allow_unused=True), params)
    if use_kl:
        g_pos_kl = _zerofill(torch.autograd.grad(
            L_pos_kl, params, retain_graph=False, allow_unused=True), params)
    else:
        g_pos_kl = [torch.zeros_like(p) for p in params]
        kl_p = zero

    # ---- rej at c=-C ------------------------------------------------------
    with lora(model, c=-C):
        out_n = model(input_ids=in_, attention_mask=an, labels=ln)
        L_neg_nll = C * out_n.loss
        if use_kl:
            logp_n = torch.log_softmax(out_n.logits.float(), dim=-1)
            kl_n = _kl_mean_full(logp_n, logp_b_n, ln)
            L_neg_kl = kl_lambda * kl_n
    g_neg_nll = _zerofill(torch.autograd.grad(
        L_neg_nll, params, retain_graph=use_kl, allow_unused=True), params)
    if use_kl:
        g_neg_kl = _zerofill(torch.autograd.grad(
            L_neg_kl, params, retain_graph=False, allow_unused=True), params)
    else:
        g_neg_kl = [torch.zeros_like(p) for p in params]
        kl_n = zero

    # ---- PCGrad on the NLL pair only --------------------------------------
    gp_flat = torch.cat([g.reshape(-1) for g in g_pos_nll])
    gn_flat = torch.cat([g.reshape(-1) for g in g_neg_nll])
    dot = (gp_flat * gn_flat).sum()
    gp_norm_sq = (gp_flat * gp_flat).sum().clamp_min(1e-12)
    gn_norm_sq = (gn_flat * gn_flat).sum().clamp_min(1e-12)
    cos = (dot / (gp_norm_sq.sqrt() * gn_norm_sq.sqrt())).item()
    conflict = dot.item() < 0

    if pcgrad and conflict:
        gp_proj = gp_flat - (dot / gn_norm_sq) * gn_flat
        gn_proj = gn_flat - (dot / gp_norm_sq) * gp_flat
        nll_summed = 0.5 * (gp_proj + gn_proj)
    else:
        nll_summed = 0.5 * (gp_flat + gn_flat)

    if use_kl:
        kl_flat = 0.5 * (
            torch.cat([g.reshape(-1) for g in g_pos_kl]) +
            torch.cat([g.reshape(-1) for g in g_neg_kl])
        )
        summed = nll_summed + kl_flat
    else:
        summed = nll_summed

    offset = 0
    for p in params:
        n = p.numel()
        p.grad = summed[offset:offset + n].view_as(p)
        offset += n

    return {
        "L_pos_nll": L_pos_nll.detach().item() / max(C, 1e-12),
        "L_neg_nll": L_neg_nll.detach().item() / max(C, 1e-12),
        "kl_mean_pos": kl_p.detach().item() if use_kl else 0.0,
        "kl_mean_neg": kl_n.detach().item() if use_kl else 0.0,
        "C": C,
        "conflict": conflict,
        "cos": cos,
    }


def train_adapter(model, tok, pairs: list[dict], cfg: TrainCfg,
                  *, history_bake=None, enable_thinking: bool = False) -> ModulatedLoRA:
    """Fit one ModulatedLoRA on `pairs` via path-loss + KL anchor.

    `history_bake`: if given, its gate is set to `lambda: lora._c != 0.0`
    so the c=0 reference forward returns pristine base (cumulative-from-
    base KL across rounds).
    """
    torch.manual_seed(cfg.seed)
    lora = ModulatedLoRA(model, r=cfg.r, alpha=cfg.alpha, targets=cfg.targets,
                         dtype=next(model.parameters()).dtype)
    params = list(lora.parameters())
    optim = AdamW(params, lr=cfg.lr, weight_decay=cfg.weight_decay)
    sched = get_cosine_schedule_with_warmup(
        optim,
        num_warmup_steps=int(cfg.warmup_ratio * cfg.steps),
        num_training_steps=cfg.steps,
    )
    if history_bake is not None:
        history_bake.set_gate(lambda: lora._c != 0.0)

    ds = PairDataset(pairs, tok, cfg.max_len, enable_thinking=enable_thinking)
    pad_id = tok.pad_token_id
    loader = DataLoader(
        ds, batch_size=cfg.batch_size, shuffle=True,
        collate_fn=lambda b: _pair_collate(b, pad_id),
        drop_last=True,
    )

    device = next(model.parameters()).device
    it = iter(loader)
    pbar = tqdm(range(cfg.steps), desc="train", leave=False)
    for step in pbar:
        try:
            batch = next(it)
        except StopIteration:
            it = iter(loader)
            batch = next(it)
        ip, lp, ap, in_, ln, an = (t.to(device) for t in batch)

        # Wider than the bake point (0.75) so c-scan-free baking stays in
        # distribution: training sees |C| up to 2, inference bakes at 0.75.
        C = float(torch.empty(()).uniform_(0.0, 2.0))
        trace = pcgrad_train_step(
            model, lora, ip, lp, ap, in_, ln, an, params,
            C=C, pcgrad=cfg.pcgrad, kl_lambda=cfg.kl_lambda,
        )

        torch.nn.utils.clip_grad_norm_(params, cfg.grad_clip)
        optim.step()
        optim.zero_grad(set_to_none=True)
        sched.step()

        if step % cfg.log_every == 0:
            lr = optim.param_groups[0]["lr"]
            logger.info(
                f"step {step:4d}/{cfg.steps}  C={trace['C']:.2f}  "
                f"nll+={trace['L_pos_nll']:.3f}  nll-={trace['L_neg_nll']:.3f}  "
                f"kl±={trace['kl_mean_pos']:.4f}/{trace['kl_mean_neg']:.4f}  "
                f"cos={trace['cos']:+.2f}  lr={lr:.2e}"
                f"{'  CONFLICT' if trace['conflict'] else ''}"
            )

    if history_bake is not None:
        history_bake.set_gate(lambda: True)              # restore inference default
    return lora
