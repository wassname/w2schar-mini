"""Path-loss ModulatedLoRA training with reverse-KL coherence penalty.

Forked from `weight-steering-lite/src/wsl/train.py`, trimmed:
- Full KL on logits (no top-K approximation). Fine for the smaller models
  + smaller batches we use here; swap to top-K if memory becomes the
  bottleneck.
- Dropped held-out probe-eval loop (we evaluate via dialogue after train).

Per (prompt, cho, rej), sampled C ∈ (0, 1]:

    L_pos = C·mean_b(nll_b / max(detach(nll_b), 1))  +  β·KL(steer ‖ base)
    L_neg = C·mean_b(nll_b / max(detach(nll_b), 1))  +  β·KL(steer ‖ base)

Per-sample NLL is normalized by its own detached value (capped from
below at 1) before batch-averaging. This caps each pair's NLL
contribution at ~1 nat, so hard pairs (high NLL) get their gradient
magnitude downweighted to unit-ish, while easy pairs (NLL < 1) pass
through unchanged. Goal: equal-magnitude pull per pair toward each
pole, so the learned direction is a clean bisecting axis instead of
being dominated by the few hardest pairs.

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
from loguru import logger
from torch.optim import AdamW
from torch.utils.data import DataLoader, Dataset
from transformers import get_cosine_schedule_with_warmup
from tqdm.auto import tqdm

from csm.ws.adapter import ModulatedLoRA, ModulatedPiSSA


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
    # ─ PiSSA-only ─ (ignored for ModulatedLoRA)
    pissa_selection_score: str = "cho_rej_min_std"
    """One of {"s_only", "wanda", "act_only", "cho_rej_min_std"}. The default
    picks directions that are alive in BOTH cho and rej completion-token
    activations — see ModulatedPiSSA docstring."""
    pissa_calib_max_tokens: int = 1024
    """Cap captured tokens per layer for activation-driven top-r selection."""


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


_KL_TOPK = 256


def _kl_topk_base(logp_steer, base_top_logp, base_top_idx, labels):
    """Reverse KL(p_steer_K ‖ p_base_K) on the top-K simplex per position,
    where p_*_K are the steered/base distributions renormalized over
    base's top-K indices. HF-style shift (logits[t] predicts label[t+1]).

    Renormalization is REQUIRED for KL ≥ 0: gathering log_softmax-over-full-V
    at top-K indices gives sub-distributions whose mass < 1, and naïve
    Σ p_s · (logp_s − logp_b) on those is unbounded in sign (it became
    negative in trace logs when steered mass leaked outside base's top-K,
    flipping kl_lambda·kl from anchor into anti-anchor). After renormalizing
    both sides over the K subset Gibbs gives KL ≥ 0.

    Memory motivation: full-vocab logp_base is 33.5 GB for gemma-2b
    (16 batch × 2048 seq × 256k vocab × fp32). Top-K storage at K=256 is
    ~33 MB — 1000× smaller — and persistent state across pos+neg pcgrad
    branches drops 67 GB → ~66 MB. Transient steered logp stays full-vocab
    during the gather but is freed after backward.

    Approximation bias: collapses 'mass outside base top-K' into a single
    implicit bucket. For an instruct LM at K=256 base captures >99% per
    position so the lost-mass signal is small — acceptable as a soft anchor.
    """
    s_sh = logp_steer[:, :-1, :]                       # (B, S-1, V)
    b_sh_logp = base_top_logp[:, :-1, :]               # (B, S-1, K)
    b_sh_idx = base_top_idx[:, :-1, :]                 # (B, S-1, K)
    mask_sh = (labels[:, 1:] != -100)
    s_top = torch.gather(s_sh, -1, b_sh_idx)           # (B, S-1, K)
    logp_s_K = s_top - torch.logsumexp(s_top, dim=-1, keepdim=True)
    logp_b_K = b_sh_logp - torch.logsumexp(b_sh_logp, dim=-1, keepdim=True)
    p_s_K = logp_s_K.exp()
    kl_per_tok = (p_s_K * (logp_s_K - logp_b_K)).sum(dim=-1)
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
    """One step: margin NLL on both poles + (optional) KL anchor to c=0.
    PCGrad operates on the (margin_pos, margin_neg) gradients only — KL
    is added unprojected.

    Margin formulation:
      L_pos = C · (mean nll(cho|+C) − mean nll(rej|+C))
      L_neg = C · (mean nll(rej|−C) − mean nll(cho|−C))
    The shared-fluency direction (cho and rej both lower nll when adapter
    fits style) cancels in the difference; only the persona-axis component
    survives. Earlier per-sample-NLL formulation was dominated by the shared
    component (cos(g_pos, g_neg) ≈ -0.97 just from the c-sign flip on a
    shared signal).
    """
    use_kl = kl_lambda > 0
    device = next(p.device for p in params)
    zero = torch.zeros((), device=device)

    # ---- c=0 reference forwards (no grad, bf16 + top-K) -------------------
    # bf16 log_softmax: KL precision is fine because the multiplicative p_s
    # factor zeros out the low-prob tail where bf16 underflow matters.
    # Persist only top-K (values+indices), discard the full-vocab tensor.
    if use_kl:
        with torch.no_grad():
            with lora(model, c=0.0):
                logp_b_p_full = torch.log_softmax(
                    model(input_ids=ip, attention_mask=ap).logits, dim=-1)
                b_top_p = logp_b_p_full.topk(_KL_TOPK, dim=-1)
                base_top_logp_p, base_top_idx_p = b_top_p.values, b_top_p.indices
                del logp_b_p_full
                logp_b_n_full = torch.log_softmax(
                    model(input_ids=in_, attention_mask=an).logits, dim=-1)
                b_top_n = logp_b_n_full.topk(_KL_TOPK, dim=-1)
                base_top_logp_n, base_top_idx_n = b_top_n.values, b_top_n.indices
                del logp_b_n_full

    # ---- both inputs at c=+C  (cho prefer, rej penalize) ------------------
    with lora(model, c=+C):
        out_cp = model(input_ids=ip, attention_mask=ap)
        nll_cho_p = _per_sample_nll(out_cp.logits.float(), lp).mean()
        out_rp = model(input_ids=in_, attention_mask=an)
        nll_rej_p = _per_sample_nll(out_rp.logits.float(), ln).mean()
        L_pos_nll = C * (nll_cho_p - nll_rej_p)
        mean_nll_p = nll_cho_p.detach().item()
        if use_kl:
            logp_p = torch.log_softmax(out_cp.logits, dim=-1)
            kl_p = _kl_topk_base(logp_p, base_top_logp_p, base_top_idx_p, lp)
            L_pos_kl = kl_lambda * kl_p
    g_pos_nll = _zerofill(torch.autograd.grad(
        L_pos_nll, params, retain_graph=use_kl, allow_unused=True), params)
    if use_kl:
        g_pos_kl = _zerofill(torch.autograd.grad(
            L_pos_kl, params, retain_graph=False, allow_unused=True), params)
    else:
        g_pos_kl = [torch.zeros_like(p) for p in params]
        kl_p = zero

    # ---- both inputs at c=-C  (rej prefer, cho penalize) ------------------
    with lora(model, c=-C):
        out_rn = model(input_ids=in_, attention_mask=an)
        nll_rej_n = _per_sample_nll(out_rn.logits.float(), ln).mean()
        out_cn = model(input_ids=ip, attention_mask=ap)
        nll_cho_n = _per_sample_nll(out_cn.logits.float(), lp).mean()
        L_neg_nll = C * (nll_rej_n - nll_cho_n)
        mean_nll_n = nll_rej_n.detach().item()
        if use_kl:
            logp_n = torch.log_softmax(out_rn.logits, dim=-1)
            kl_n = _kl_topk_base(logp_n, base_top_logp_n, base_top_idx_n, ln)
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
        "L_pos_nll": mean_nll_p,           # raw mean NLL (not normalized) for interpretability
        "L_neg_nll": mean_nll_n,
        "kl_mean_pos": kl_p.detach().item() if use_kl else 0.0,
        "kl_mean_neg": kl_n.detach().item() if use_kl else 0.0,
        "C": C,
        "conflict": conflict,
        "cos": cos,
    }


def _capture_calibration_activations(model, tok, pairs: list[dict],
                                     cfg: TrainCfg, *,
                                     enable_thinking: bool
                                     ) -> dict[str, dict[str, torch.Tensor]]:
    """Capture per-layer input activations on COMPLETION tokens during full
    (prompt+cho) and (prompt+rej) forwards. Returns
    `dict[layer_name, {"cho": (N_cho, d_in), "rej": (N_rej, d_in)}]` (CPU
    float32, capped per side at cfg.pissa_calib_max_tokens).

    Why completion-only: the persona axis lives in what the model PRODUCES;
    prompt-token activations are identical between cho and rej (same prompt)
    so a contrast on them yields zero signal. Masking to completion tokens
    (labels != -100) isolates the cho/rej-specific activations.

    SHOULD: cho and rej captures produce DIFFERENT distributions per layer.
    ELSE selection score `cho_rej_min_std` collapses to S-bias and we lose
    the contrast (the whole point of the fork).
    """
    from csm.ws.adapter import LoRAConfig, _find_targets

    probe_cfg = LoRAConfig(r=cfg.r, alpha=1.0, targets=cfg.targets,
                           layer_range=cfg.layer_range, dtype=next(model.parameters()).dtype)
    targets = _find_targets(model, probe_cfg)
    cap = cfg.pissa_calib_max_tokens

    # Per-side state; reset between cho and rej passes.
    captured: dict[str, dict[str, list[torch.Tensor]]] = {
        name: {"cho": [], "rej": []} for name, _ in targets}
    counts: dict[str, dict[str, int]] = {
        name: {"cho": 0, "rej": 0} for name, _ in targets}
    _state: dict[str, object] = {"side": "cho", "completion_mask": None}

    def make_hook(name):
        def _h(module, args, kwargs):
            side: str = _state["side"]
            if counts[name][side] >= cap:
                return
            x = args[0].detach()
            mask = _state["completion_mask"]
            if mask is not None and mask.shape[:x.dim() - 1] == x.shape[:-1]:
                x = x[mask.bool()]                        # (N_real, d_in)
            else:
                x = x.reshape(-1, x.shape[-1])
            x = x.to(torch.float32).cpu()
            take = min(x.shape[0], cap - counts[name][side])
            captured[name][side].append(x[:take])
            counts[name][side] += take
        return _h

    handles = [layer.register_forward_pre_hook(make_hook(name), with_kwargs=True)
               for name, layer in targets]
    try:
        device = next(model.parameters()).device
        was_training = model.training
        model.eval()

        ds = PairDataset(pairs, tok, cfg.max_len, enable_thinking=enable_thinking)
        bs = max(1, cfg.batch_size)
        for side in ("cho", "rej"):
            _state["side"] = side
            # Build tensors per side from PairDataset (already builds full
            # prompt+completion ids with labels masking the prompt to -100).
            samples = [ds[i][0 if side == "cho" else 1] for i in range(len(ds))]
            with torch.no_grad():
                for i in range(0, len(samples), bs):
                    if all(counts[n][side] >= cap for n in counts):
                        break
                    batch = samples[i:i+bs]
                    ids, lbl, attn = collate(batch, tok.pad_token_id)
                    ids, lbl, attn = ids.to(device), lbl.to(device), attn.to(device)
                    # Only label != -100 positions = completion tokens.
                    _state["completion_mask"] = (lbl != -100)
                    model(input_ids=ids, attention_mask=attn)
            _state["completion_mask"] = None
        if was_training:
            model.train()
    finally:
        for h in handles:
            h.remove()

    X: dict[str, dict[str, torch.Tensor]] = {}
    for name, sides in captured.items():
        X[name] = {
            s: torch.cat(chunks, dim=0) if chunks else torch.empty(0)
            for s, chunks in sides.items()
        }
    n_cho = [v["cho"].shape[0] for v in X.values() if v["cho"].numel() > 0]
    n_rej = [v["rej"].shape[0] for v in X.values() if v["rej"].numel() > 0]
    logger.info(
        f"PiSSA calibration: captured {len(X)} targets, "
        f"cho tokens/layer in [{min(n_cho, default=0)}, {max(n_cho, default=0)}], "
        f"rej tokens/layer in [{min(n_rej, default=0)}, {max(n_rej, default=0)}] "
        f"(cap={cap})"
    )
    return X


def train_adapter(model, tok, pairs: list[dict], cfg: TrainCfg,
                  *, history_bake=None, enable_thinking: bool = False,
                  adapter_cls: type = ModulatedLoRA):
    """Fit one ModulatedLoRA / ModulatedPiSSA on `pairs` via path-loss + KL anchor.

    `history_bake`: if given, its gate is set to `lambda: lora._c != 0.0` so
    the c=0 reference returns pristine base (LoRA) or post-prior-bakes
    (PiSSA — `PiSSAHistoryBake.set_gate` is a no-op; see adapter.py).
    `adapter_cls`: ModulatedLoRA (default) or ModulatedPiSSA.
    """
    torch.manual_seed(cfg.seed)
    if adapter_cls is ModulatedPiSSA:
        calib = _capture_calibration_activations(
            model, tok, pairs, cfg, enable_thinking=enable_thinking,
        )
        lora = ModulatedPiSSA(model, r=cfg.r, targets=cfg.targets,
                              layer_range=cfg.layer_range,
                              dtype=next(model.parameters()).dtype,
                              calibration_activations=calib,
                              selection_score=cfg.pissa_selection_score)
    elif adapter_cls is ModulatedLoRA:
        lora = ModulatedLoRA(model, r=cfg.r, alpha=cfg.alpha, targets=cfg.targets,
                             layer_range=cfg.layer_range,
                             dtype=next(model.parameters()).dtype)
    else:
        raise ValueError(f"unknown adapter_cls={adapter_cls!r}")
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
    # drop_last=False: small training pools (e.g. n_train_pairs=15,
    # batch_size=16) would yield zero full batches with drop_last=True and
    # raise StopIteration on the very first step — masked through inspect-ai
    # as a vague "train_student tool unresponsive". _per_sample_nll handles
    # ragged batches fine; nothing in the loss depends on a fixed batch axis.
    loader = DataLoader(
        ds, batch_size=cfg.batch_size, shuffle=True,
        collate_fn=lambda b: _pair_collate(b, pad_id),
        drop_last=False,
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
        with torch.no_grad():
            ds_norm = float(torch.stack(
                [p.detach().float().norm() for p in params]).mean())
        traces.append({
            "step": step,
            "C": trace["C"],
            "nll+": trace["L_pos_nll"],
            "nll-": trace["L_neg_nll"],
            "kl+": trace["kl_mean_pos"],
            "kl-": trace["kl_mean_neg"],
            "cos": trace["cos"],
            "‖Δs‖": ds_norm,
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
    blowing up), kl± monotonically growing with |C|, cos near 0 (orthogonal
    gradients = PCGrad-friendly), lr cosine from 0 → peak → 0, conf flag
    when PCGrad surgery fired."""
    from tabulate import tabulate
    headers = ["step", "C", "nll+", "nll-", "kl+", "kl-", "cos", "‖Δs‖", "lr", "conf"]
    rows = [[t[h] for h in headers] for t in traces]
    # SHOULD (margin loss + PiSSA): cos near +1 (margin makes cho/rej gradients
    # cooperative on persona axis, not antiparallel); ‖Δs‖ growing (adapter
    # actually learning, not frozen by bf16 underflow / weight decay); nll+
    # descending and nll- ASCENDING under the +C frame (margin opening);
    # kl± grows modestly with |C|; lr cosine-anneals; conf=0 (no PCGrad
    # surgery needed when gradients agree).
    table = tabulate(rows, headers=headers, tablefmt="plain", floatfmt=".3g")
    logger.info(f"\ntraining trace:\n{table}\n")
