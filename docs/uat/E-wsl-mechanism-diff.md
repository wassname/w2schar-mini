# E — wsl mechanism diff (adapter.py + train.py)

Scope: `src/csm/{adapter,train}.py` vs `src/wsl/{adapter,train}.py`.
Mini files cited as `csm/...:N`; wsl as `wsl/...:N`.

## A. Intentional drops

- LOW — `layer_range` depth-band targeting. `wsl/adapter.py:66,77-83,106-118` vs gone in csm. Pseudocode never mentions it. Intentional trim (per docstring `csm/adapter.py:4`).
- LOW — bnb 4-bit / `Linear4bit` storage-dtype care. `wsl/adapter.py:366-368` vs `csm/adapter.py:223-225` (uses `target_dtype` directly, no comment about Linear4bit). Pseudocode §"Out of scope" calls this out. Intentional.
- LOW — Top-K sparse KL (`KL_TOPK=300`, `_base_topk_pair`, `_kl_mean_topk`). `wsl/train.py:128-191` vs `csm/train.py:127-140` (`_kl_mean_full`). Pseudocode §3 explicitly chooses full KL. Intentional, per user note.
- LOW — Held-out probe-eval loop inside train (`probe_every`, `n_held_out`). `wsl/train.py:63-64` and `wsl/w2schar/_atoms/train_calibrate.py:116-117` vs gone. Pseudocode says evaluate via dialogue. Intentional.
- LOW — Gradient accumulation (`effective_batch_size`, `accum_grads`). `wsl/.../train_calibrate.py:151-153,184-212` vs gone. Pseudocode silent. Intentional for the mini's smaller models; flag only if you later go to 27b.
- LOW — `bake_adapters` in-place fuse. `wsl/adapter.py:284-305` vs gone. Pseudocode only uses `HistoryBake`. Intentional.
- LOW — `optimi.AdamW` with `kahan_sum=True`, `betas=(0.9, 0.95)`. `wsl/.../train_calibrate.py:146-149` vs `torch.optim.AdamW` default betas `csm/train.py:257`. Pseudocode silent. **Mild flag**: wsl's journal says +1.5pp top1 over torch.AdamW on 9b (`train_calibrate.py:140-142`). Silent drop — not in pseudocode. Probably fine on 2b/9b but worth knowing.
- LOW — `attn_implementation="flash_attention_2"`, `low_cpu_mem_usage=True`, `BitsAndBytesConfig`. `wsl/load_with_history.py:82-96` vs csm's load path (`history.py`). Confirm in `csm/history.py` if you care.
- LOW — `gradient_checkpointing` option. `wsl/.../train_calibrate.py:99-104,127-128` vs gone. Pseudocode silent; wsl itself says it's broken with LoRA hooks. Good riddance.

Verdict A: All drops look intentional. The only mildly-quiet one is the `optimi.AdamW(betas=(0.9, 0.95), kahan_sum=True)` swap to plain `torch.optim.AdamW(default betas)`. Worth one line in pseudocode if you care.

## B. New bugs introduced by trimming

- MEDIUM — KL reference forward path differs subtly. `csm/train.py:161-167` opens `with torch.no_grad(): with lora(model, c=0.0):` and the gate closure `lambda: lora._c != 0.0` reads `lora._c` while still inside the `with lora(model, c=0.0)` block — fine for that forward. But the **subsequent c=+C / c=-C forwards** at `csm/train.py:170-176, 187-193` exit and re-enter the lora context per pole. Each re-entry resets `_c` so the gate sees the right value. Same as wsl. **No bug, just verify your tests cover both poles** — pseudocode is correct.
- MEDIUM — `C ~ U(0.05, 1.0)` vs wsl's `U(0, 1]`. `csm/train.py:285` (`uniform_(0.05, 1.0)`) vs `wsl/.../train_calibrate.py:196` (`torch.rand()` → `[0,1)`). Pseudocode §3 says `C ∼ U(0, 1]` with "resample if zero". The mini's `0.05` floor is a deliberate-looking change but the pseudocode doesn't mention it. **Flag** as accidental drift — also note `torch.rand` is `[0,1)` so wsl can return exactly 0, which the C-scale would zero out; mini's 0.05 floor sidesteps that. Probably an improvement, but undocumented.
- MEDIUM — RNG handling regressed. `csm/train.py:253` does only `torch.manual_seed(cfg.seed)` (global state). wsl uses a dedicated `torch.Generator().manual_seed(cfg.seed)` and threads it through `torch.randint(..., generator=rng)` and `torch.rand((), generator=rng)` (`train_calibrate.py:163,188,196`). Mini's `uniform_(0.05, 1.0)` and `DataLoader(shuffle=True)` consume from the global stream and can be perturbed by any unrelated `torch.*` call inside HF/transformers. Reproducibility is weaker. LOW-MEDIUM.
- LOW — `DataLoader(..., drop_last=True)` vs `torch.randint`-with-replacement. `csm/train.py:268-272` vs `wsl/.../train_calibrate.py:188`. Different sampling distributions. Likely OK for a fixed mechanism comparison but it does change the empirical NLL distribution per step.
- LOW — Cosine scheduler built from `cfg.steps` directly (`csm/train.py:258-262`) — same shape as wsl. No bug.
- LOW — `with torch.no_grad()` wrapper around the c=0 forward in mini (`csm/train.py:162`) is redundant with `@torch.no_grad()`-equivalent semantics in wsl (`wsl/train.py:132`). Both correct.
- LOW — `next(model.parameters()).dtype` used in `csm/train.py:255` to default the adapter dtype. wsl's TrainCfg has no such inheritance — adapter dtype follows `LoRAConfig.dtype=bf16`. If a wsl user loads in fp16 the dtypes diverge silently; mini fixes this. Not a regression.

Verdict B: One real flag is the silent `U(0.05, 1.0)` floor — pseudocode says `U(0, 1]` with resample, so either fix the pseudocode or fix the code. RNG-via-global-state is weaker reproducibility but not a correctness bug. No off-by-ones, no mask shift drift, no detach/no_grad regressions, no init-scale change (init is asymmetric in both, identically: kaiming A + N(1e-4, 1e-4) B at `csm/adapter.py:86-89` vs `wsl/adapter.py:147-150`).

## C. Latent bugs inherited from wsl

- MEDIUM — Train-time KL mask off-by-one in wsl (already fixed in mini). `wsl/train.py:246,267` uses `lp != -100` / `ln != -100` directly without the `[:, 1:]` shift, so KL averages over an off-by-one set vs HF's labels-aware CE (which shifts internally). `csm/train.py:131-140` correctly shifts. wsl's KL effectively counts the last-prompt-token position (label = -100 there typically, so usually masked, but the final label position is dropped). Net effect: wsl's KL denominator is wrong by ~1 position and the per-position values are computed against `logp_b` at position t for `labels[t]` rather than `labels[t+1]`. This is a real mask/shift bug in wsl. (User said don't flag the mini's fix — the wsl issue is what survives unfixed there.)
- MEDIUM — `HistoryBake.__init__` indexes `history[0][0].cfg.r` and `.cfg.dtype` at `wsl/adapter.py:348,351` and `csm/adapter.py:208,211`. Both raise `IndexError` if `history == []`. Both callers guard against empty history (`load_with_history.py:116`, mini's history.py presumably) but the class API silently assumes non-empty. Same in both. LOW.
- LOW — `HistoryBake._is_active = lambda: True` default at `wsl/adapter.py:339` / `csm/adapter.py:201` — convenient but if the caller forgets `set_gate` during training, the c=0 KL ref forward silently includes history, switching KL semantics from cumulative-from-base to iterative. The training entry point sets the gate explicitly in both repos, so this is latent. LOW.
- LOW — `_zerofill` returns `torch.zeros_like(p)` which is the same dtype/device as `p` (bf16) — fine for grads, but if any of the gradient-flat concats hit fp32 paths (none do here) sign of a future footgun. Same in both.
- LOW — PCGrad `clamp_min(1e-12)` on `gn_norm_sq` (`wsl/train.py:283`, `csm/train.py:208`) protects div-by-zero but if a pole's grad is genuinely zero (e.g. all-pad batch), the projection direction becomes arbitrary. In practice never triggers; flag only.
- LOW — `cos = (dot / (sqrt(gp²) * sqrt(gn²))).item()` is computed in bf16 (params are bf16) which loses ~3 decimals. Both repos. Reported `cos` is noisier than it looks. LOW.
- LOW — `model.eval()` is not called before `pcgrad_train_step` in either repo's inner function (wsl wraps with `model.train()` at `train_calibrate.py:121`, mini never calls `.train()` or `.eval()` in `csm/train.py`). If anything else (dialogue, c-scan) left the model in `.eval()`, dropout etc stay off — which is what you want for LoRA training on a frozen base anyway. Not a bug, but mini is silently relying on caller state. LOW.

Verdict C: One real inherited issue is the wsl KL mask off-by-one (mini fixed it). Everything else is latent-but-not-currently-firing.

## Overall

Mini is a clean trim. No critical bugs introduced. One small mismatch between pseudocode and code (`U(0.05, 1.0)` vs `U(0, 1]`-with-resample) — pick one. The wsl→mini fix on the KL shift is real and worth flagging in the pseudocode commentary if not already. The only silent drop worth a line in the docstring is the `optimi.AdamW` → `torch.optim.AdamW` swap and its associated betas/kahan change. Reproducibility weakened slightly by dropping the explicit `torch.Generator`. Mechanism-wise the two repos agree.
