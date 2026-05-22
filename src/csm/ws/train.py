"""Path-loss ModulatedLoRA training with reverse-KL coherence penalty.

Forked from `weight-steering-lite/src/wsl/train.py`, trimmed:
- Full KL on logits (no top-K approximation). Fine for the smaller models
  + smaller batches we use here; swap to top-K if memory becomes the
  bottleneck.
- Dropped held-out probe-eval loop (we evaluate via dialogue after train).

Per (prompt, cho, rej), sampled C ∈ (0, 1]:

    w_b   = min(1, OUTLIER_NLL / detach(nll_b))
    L_pos = C·mean_b(w_b · nll_b)  +  β·KL(steer ‖ base)   at c=+C on cho
    L_neg = C·mean_b(w_b · nll_b)  +  β·KL(steer ‖ base)   at c=−C on rej

Outlier downweight: pairs with NLL ≤ OUTLIER_NLL pass through at full
weight; pairs above (likely off-policy or impossible — model can't
produce cho given context) are damped by OUTLIER_NLL/nll < 1, so they
don't dominate the learned direction. Earlier form was `nll / max(nll, 1)`
which shrank every typical pair (nll≈2.3) by 2.3× instead of only
clipping outliers.

β trades steering signal vs distribution shift; weight-decay + β
jointly pull toward "no-op" while NLL pulls toward cho/rej.

`base` is the c=0 forward = pristine base (HistoryBake gate disabled
when `lora._c == 0`). So a new adapter that fights a prior bake pays
its KL bill cumulatively from base, not iteratively from last bake.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import torch
import torch.nn.functional as F
from loguru import logger
from torch.optim import AdamW
from torch.utils.data import DataLoader, Dataset
from transformers import get_cosine_schedule_with_warmup
from tqdm.auto import tqdm

from csm.ws.adapter import ModulatedLoRA


# Outlier-NLL threshold for per-pair downweighting. Pairs with NLL ≤
# this pass through at full weight (weight=1); pairs above are damped
# by OUTLIER_NLL/nll. Picked above typical cho-NLL (~2–3 on gemma-2b);
# triggers only when a pair is genuinely off-policy / impossible.
OUTLIER_NLL = 4.0

# Top-K vocab for KL approximation. K=256 covers >99.9% of base mass
# on confident LM next-token distributions, with per-token error ≪ the
# KL signal itself. Cuts the (B, S, V=256K) fp32 logp materialization
# (~8 GB per tensor on gemma-2b/9b) down to (B, S, 256) bf16 (~MB).
KL_TOPK = 256


@dataclass
class TrainCfg:
    r: int = 16
    alpha: float = 32.0
    targets: tuple[str, ...] = ("all-linear",)
    layer_range: tuple[float, float] = (0.0, 1.0)
    steps: int = 200
    warmup_ratio: float = 0.1
    batch_size: int = 4
    lr: float = 2e-4
    weight_decay: float = 0.01
    grad_clip: float = 1.0
    max_len: int = 512
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


def _per_sample_nll(logits: torch.Tensor, labels: torch.Tensor) -> torch.Tensor:
    """Per-sample mean NLL over completion (label != -100) tokens. Matches
    HF causal-LM reduction (logits[t] predicts label[t+1]) but un-reduced
    over batch. Returns shape [B]."""
    shift_logits = logits[..., :-1, :].contiguous()
    shift_labels = labels[..., 1:].contiguous()
    loss_per_tok = torch.nn.functional.cross_entropy(
        shift_logits.reshape(-1, shift_logits.size(-1)),
        shift_labels.reshape(-1),
        reduction="none", ignore_index=-100,
    ).view(shift_labels.size())
    mask = (shift_labels != -100).float()
    return (loss_per_tok * mask).sum(-1) / mask.sum(-1).clamp(min=1.0)


def _base_topk(logits, k: int = KL_TOPK):
    """Extract (top_k_indices, base_logp_at_topk) from raw logits without
    materializing the full (B, S, V) log_softmax. Both bf16, detached
    (called inside no_grad)."""
    lse = torch.logsumexp(logits, dim=-1, keepdim=True)          # [B, S, 1]
    top = logits.topk(k, dim=-1)
    return top.indices, (top.values - lse).detach()              # [B, S, K]


def _kl_topk(logits_s, base_topk_idx, base_logp_topk, labels):
    """Reverse KL(p_steer ‖ p_base) on base's top-K vocab + residual bucket.

    Naive truncation (sum only over top-K of base) is WRONG: when steered
    mass leaks outside base's top-K (the exact case we want to penalize),
    the truncated sum goes NEGATIVE, so `kl_lambda * kl` rewards
    divergence (anti-anchor). Fix: add an explicit "outside-top-K"
    bucket whose log-prob in each distribution is computed via log1p(-Σ).

    Memory: avoids materializing (B, S, V) log_softmax; only logsumexp
    (→ (B,S,1)) and gather (→ (B,S,K)) on steered side.
    """
    lse = torch.logsumexp(logits_s, dim=-1, keepdim=True)             # [B, S, 1]
    logp_s_topk_full = logits_s.gather(-1, base_topk_idx) - lse        # [B, S, K]

    # Shift to match HF causal-LM CE: logits[t] predicts label[t+1].
    logp_s_topk = logp_s_topk_full[:, :-1, :]
    logp_b_topk = base_logp_topk[:, :-1, :]
    labels_sh = labels[:, 1:]

    # Outside-top-K bucket: log(1 - Σ_topK p) via stable log1p(-exp(log_sum)).
    # Clamp log_sum at -1e-4 to avoid log1p(-1)=-inf when top-K covers
    # exactly all mass (numerical edge; doesn't bias the gradient signal).
    log_sum_s = torch.logsumexp(logp_s_topk, dim=-1, keepdim=True)     # [B, S-1, 1]
    log_sum_b = torch.logsumexp(logp_b_topk, dim=-1, keepdim=True)
    logp_s_out = torch.log1p(-log_sum_s.clamp(max=-1e-4).exp())        # [B, S-1, 1]
    logp_b_out = torch.log1p(-log_sum_b.clamp(max=-1e-4).exp())

    # Cast at reduction: bf16 sum over K=256 loses precision.
    diff_topk = (logp_s_topk - logp_b_topk).float()                    # [B, S-1, K]
    p_s_topk = logp_s_topk.float().exp()
    kl_topk = (p_s_topk * diff_topk).sum(dim=-1, keepdim=True)         # [B, S-1, 1]

    diff_out = (logp_s_out - logp_b_out).float()
    p_s_out = logp_s_out.float().exp()
    kl_out = p_s_out * diff_out                                        # [B, S-1, 1]

    kl_per_tok = (kl_topk + kl_out).squeeze(-1)                        # [B, S-1]
    mask_sh = (labels_sh != -100)
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
                out_b_p = model(input_ids=ip, attention_mask=ap,
                                output_hidden_states=True)
                out_b_n = model(input_ids=in_, attention_mask=an,
                                output_hidden_states=True)
            # Top-K (idx + base logp) for KL on top-256. Skips the
            # ~8GB full-vocab log_softmax materialization.
            base_topk_idx_p, base_logp_topk_p = _base_topk(out_b_p.logits)
            base_topk_idx_n, base_logp_topk_n = _base_topk(out_b_n.logits)
            # Base hidden states for the Δh diagnostic (per-sample direction
            # variance). Detach + float here so they're tiny and grad-free.
            h_b_p = out_b_p.hidden_states[-1].detach().float()
            h_b_n = out_b_n.hidden_states[-1].detach().float()
            del out_b_p, out_b_n   # free base logits + all-layer hidden states

    # ---- cho at c=+C ------------------------------------------------------
    with lora(model, c=+C):
        out_p = model(input_ids=ip, attention_mask=ap, output_hidden_states=True)
        nll_per_p = _per_sample_nll(out_p.logits, lp)  # [B]
        w_p = (OUTLIER_NLL / nll_per_p.detach()).clamp(max=1.0)
        L_pos_nll = C * (w_p * nll_per_p).mean()
        mean_nll_p = nll_per_p.detach().mean().item()    # for logging
        # Final hidden state pooled over completion-mask tokens (detached;
        # used only for cos_act diagnostic, no gradient through it).
        h_p_last = out_p.hidden_states[-1].detach().float()
        if use_kl:
            kl_p = _kl_topk(out_p.logits, base_topk_idx_p, base_logp_topk_p, lp)
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
        out_n = model(input_ids=in_, attention_mask=an, output_hidden_states=True)
        nll_per_n = _per_sample_nll(out_n.logits, ln)  # [B]
        w_n = (OUTLIER_NLL / nll_per_n.detach()).clamp(max=1.0)
        L_neg_nll = C * (w_n * nll_per_n).mean()
        mean_nll_n = nll_per_n.detach().mean().item()
        h_n_last = out_n.hidden_states[-1].detach().float()
        if use_kl:
            kl_n = _kl_topk(out_n.logits, base_topk_idx_n, base_logp_topk_n, ln)
            L_neg_kl = kl_lambda * kl_n
    g_neg_nll = _zerofill(torch.autograd.grad(
        L_neg_nll, params, retain_graph=use_kl, allow_unused=True), params)
    if use_kl:
        g_neg_kl = _zerofill(torch.autograd.grad(
            L_neg_kl, params, retain_graph=False, allow_unused=True), params)
    else:
        g_neg_kl = [torch.zeros_like(p) for p in params]
        kl_n = zero

    # ---- representation diagnostics (all on pooled final hidden states) ---
    # cos_act = cos(h_cho_steered, h_rej_steered): how distinguishable are
    #   the two completions? Drifts DOWN as adapter learns to separate them.
    # dir±_m  = mean pairwise cos of per-sample Δh = h(c=±C) − h(c=0). High
    #   → the adapter is implementing a CONSISTENT direction across samples
    #   (a real "axis"). Low → each sample gets its own random shift; the
    #   axis is illusory. dir±_v = variance of those pairwise cos.
    mp = (lp != -100).float().unsqueeze(-1)
    mn = (ln != -100).float().unsqueeze(-1)
    def _pool(h, m):
        return (h * m).sum(1) / m.sum(1).clamp_min(1.0)             # [B, D]
    hp_pool = _pool(h_p_last, mp)
    hn_pool = _pool(h_n_last, mn)
    cos_act = F.cosine_similarity(hp_pool, hn_pool, dim=-1).mean().item()

    dir_p_m = dir_p_v = dir_n_m = dir_n_v = 0.0
    if use_kl:
        dh_p = hp_pool - _pool(h_b_p, mp)                            # [B, D]
        dh_n = hn_pool - _pool(h_b_n, mn)
        def _pairwise_cos(v):                                        # v: [B, D]
            if v.shape[0] < 2:
                return 0.0, 0.0
            vn = F.normalize(v, dim=-1)
            cmat = vn @ vn.T                                          # [B, B]
            iu = torch.triu_indices(cmat.shape[0], cmat.shape[0], offset=1,
                                    device=cmat.device)
            off = cmat[iu[0], iu[1]]
            return off.mean().item(), off.var(unbiased=False).item()
        dir_p_m, dir_p_v = _pairwise_cos(dh_p)
        dir_n_m, dir_n_v = _pairwise_cos(dh_n)

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
        "L_pos_nll": mean_nll_p,           # raw mean NLL (not normalized) for interpretability
        "L_neg_nll": mean_nll_n,
        "kl_mean_pos": kl_p.detach().item() if use_kl else 0.0,
        "kl_mean_neg": kl_n.detach().item() if use_kl else 0.0,
        "C": C,
        "conflict": conflict,
        "cos": cos,
        "cos_act": cos_act,
        "dir+": dir_p_m,
        "dir-": dir_n_m,
        "dir+_v": dir_p_v,
        "dir-_v": dir_n_v,
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
                         layer_range=cfg.layer_range,
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
        drop_last=False,   # 15 pairs / batch=16 → drop_last=True empties the loader.
    )

    device = next(model.parameters()).device
    it = iter(loader)
    pbar = tqdm(range(cfg.steps), desc="train", leave=False)
    traces: list[dict] = []
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

        lr = optim.param_groups[0]["lr"]
        traces.append({
            "step": step,
            "C": trace["C"],
            "nll+": trace["L_pos_nll"],
            "nll-": trace["L_neg_nll"],
            "kl+": trace["kl_mean_pos"],
            "kl-": trace["kl_mean_neg"],
            "cos": trace["cos"],
            "cos_act": trace["cos_act"],
            "dir+": trace["dir+"],
            "dir-": trace["dir-"],
            "dir_v": 0.5 * (trace["dir+_v"] + trace["dir-_v"]),
            "lr": lr,
            "conf": int(trace["conflict"]),
        })

    if history_bake is not None:
        history_bake.set_gate(lambda: True)              # restore inference default

    _log_train_table(traces)
    return lora


def _log_train_table(traces: list[dict]) -> None:
    """Print the per-step trace as a tabulate plain table.

    SHOULD show: C drift between [0, 2], nll± stable (large jumps = adapter
    blowing up), kl± monotonically growing with |C|, cos (grad) near 0
    (orthogonal grads = PCGrad-friendly), cos_act (cho/rej last-hidden)
    starts high (similar twinned prompts) and drifts DOWN as the adapter
    learns to separate the two completion representations, dir± (mean
    pairwise cos of per-sample Δh = h(±C) − h(0)) STAYS HIGH (>~0.5) and
    growth → the adapter is implementing a consistent direction across
    samples; if dir± hovers near 0 the 'axis' is illusory (each sample
    gets a random shift). dir_v near 0 → tight direction; large → noisy.
    lr cosine 0 → peak → 0. conf=1 when PCGrad surgery fired."""
    from tabulate import tabulate
    headers = ["step", "C", "nll+", "nll-", "kl+", "kl-", "cos", "cos_act",
               "dir+", "dir-", "dir_v", "lr", "conf"]
    rows = [[t[h] for h in headers] for t in traces]
    # SHOULD: C drifts in [0, 2]; nll± descend together (symmetric pull from
    # twinned poles); kl± grows with |C|; cos starts negative (real opposing
    # gradients) then drifts toward 0; lr cosine-anneals; conf=1 = PCGrad fired.
    table = tabulate(rows, headers=headers, tablefmt="plain", floatfmt=".3g")
    logger.info(f"\ntraining trace:\n{table}\n")
