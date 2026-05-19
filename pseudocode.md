# `w2schar-mini` — algorithm pseudocode

Minimal weak-to-strong iterated character steering, fixed to the
"less deference to authority" axis. Three things compose:

1. **Conditioned weight steering (CWS)** — one LoRA adapter with a scalar
   coefficient `c ∈ [-1, 1]`; `c=0` is exact base, `c=±1` are trained
   poles.
2. **Iterated rounds** — kept adapters from prior rounds compose via a
   gated history hook so the `c=0` KL reference stays pristine base.
3. **React-agent state machine** — teacher LLM drives a `propose →
   curate → judge` loop per round, with the harness enforcing order and
   auto-managing all numbers/paths/files.

Reference: copy the math straight from
[`weight-steering-lite/docs/wsl_pseudocode.md`](../weight-steering-lite/docs/wsl_pseudocode.md).
The differences here are scope (single fixed axis, 50 pairs, no
tinymfv/Likert), not mechanism.

---

## 1. Adapter — ModulatedLoRA (c=0 ≡ base; W frozen)

Forward-hook style (no module replacement, gradients flow through `A`/`B`,
`c` is a Python float scalar).

```py
# Per target Linear layer (weight W : d_out × d_in).
def lora_layer(x, W, A, B, c, α, r):       # x : b s d_in
    Δy = (x @ A.T) @ B.T                    # A : r × d_in, B : d_out × r
    return x @ W.T + c * (α / r) * Δy       # c=0 → exact base (Δy short-circuited)

# Init: A ~ kaiming_uniform; B ~ N(1e-4, 1e-4) (small nonzero, can be ±).
# Why asymmetric init: pure-zero B leaves the +c/-c poles symmetric at
# init (the loss is even in c), so the optimiser has no signed gradient
# to break the tie. A tiny nonzero B + entropic A breaks that symmetry
# before any data is seen. (Not a "dead zone" — B=0 still receives
# gradient through A; the issue is sign-symmetry, not freezing.)
```

`with lora(model, c=±C):` registers forward hooks on `q_proj`/`v_proj`
(or `all-linear`); `c=0` short-circuits the hook so no extra compute. The
training step uses both `with lora(c=+C)` and `with lora(c=-C)` plus a
no-grad `with lora(c=0)` pass for the KL reference.

---

## 2. Outer round loop — kept adapters compose via gated history hook

Base weights on disk are never modified. After round N, `<round_N>/`
holds `adapter.safetensors` + `calibration.json` (with `signed_C`). Round
N+1 loads base plus a `HistoryBake` that sums all kept rounds' deltas
into a single forward hook, gated to be active only when the *new*
round's `c ≠ 0`.

```py
# kept = list of round dirs whose judgment.json.action == "keep".
kept = []
for round in 0..N:
    model, tok, history_bake = load_base_with_history(model_id, kept)
    #   history_bake.is_active = lambda: lora._c != 0.0   (set at train time)
    #   → c=0 reference forward returns pristine base, NOT base+history.
    #   So new round's KL is cumulative-from-base, not iterative-from-last-bake.
    A, B = small_random_asymmetric()
    state_machine_loop(model, A, B, round_dir, agent)   # see §5
    if read_judgment(round_dir) == "keep":
        kept.append(round_dir)
```

Gate semantics (the key invariant — two distinct meanings of "c=0"):

| context | history gate | "c=0 forward" returns |
|---|---|---|
| training inner loop (KL reference) | `lambda: lora._c != 0.0` | **pristine base** (Σ_kept Δ disabled) |
| dialogue / c_scan / post-eval     | `lambda: True`           | **base + history** (Σ_kept Δ active) |

So:
- **Training KL is cumulative-from-pristine-base.** A new adapter that
  fights a prior bake pays its KL bill; one that finds a fresh direction
  with low distribution shift does not.
- **C-scan + dialogue see base+history as the c=0 reference.** That's
  the deployed model just before this round's new adapter kicks in —
  what the agent will read in the post transcript at c=0 vs c=signed_C.
- The c-scan "baseline top-K" in §4 is the **base+history** top-K, not
  pristine base top-K. Re-compute it once per round (it changes when
  history grows).

---

## 3. Inner training step — NLL + KL, PCGrad on the NLL pair

One forward pass per pole (cho, rej), each at `c = ±C` where
`C ∼ U(0, 1]` is freshly sampled every step. KL added unprojected
(KL is an opposing objective by design — projecting it would silently
weaken it). PCGrad operates on the NLL pair only (cho and rej are the
same task at different poles and may legitimately conflict).

Concretely: each (prompt, cho, rej) is teacher-forced. We tokenize
`prompt + cho` (and separately `prompt + rej`), build a labels tensor
that is `-100` on prompt positions and the actual ids on completion
positions, and compute NLL/KL averaged *over completion positions
only*. HF's `model(input_ids, labels=labels).loss` already does length-
normalised mean-over-non-ignore CE, so per-pair length bias is handled
for free as long as we share that mask between NLL and KL.

```py
# Per step over (cho, rej) pairs. Teacher-forced; persona stripped.
for step in 0..T:
    (ids_p, lbl_p, attn_p), (ids_n, lbl_n, attn_n) = batch(pairs)
    # ids_*  : prompt + completion tokens
    # lbl_*  : -100 on prompt tokens, ids on completion tokens  ← shared mask
    # attn_* : 1 on real tokens, 0 on right-pad

    C ~ U(0, 1]                              # → assert C > 0 (resample if zero)
    g_nll = []
    g_kl  = []
    for (ids, lbl, attn), c in [((ids_p, lbl_p, attn_p), +C),
                                 ((ids_n, lbl_n, attn_n), -C)]:
        # ── reference forward: c=0, no grad, gate disables history ──
        with lora(model, c=0.0), no_grad():
            logits_base = model(ids, attention_mask=attn).logits   # pristine base
            logp_base   = log_softmax(logits_base)

        # ── steered forward at c=±C ───────────────────────────────
        with lora(model, c=c):
            out = model(ids, attention_mask=attn, labels=lbl)
            L_nll = C * out.loss              # HF mean-CE over non-ignore tokens
            logp_steer = log_softmax(out.logits)
            mask = (lbl != -100)               # SAME mask as HF NLL
            L_kl  = β * mean_kl(logp_steer, logp_base, mask)

        g_nll.append(∇_θ L_nll)
        g_kl .append(∇_θ L_kl)

    # PCGrad: drop the component of each NLL gradient that fights the other.
    if dot(g_nll[+], g_nll[-]) < 0:
        g_nll = pcgrad_project(g_nll)
    g = mean(g_nll) + mean(g_kl)              # KL added unprojected
    adamw.step(g); onecyclelr.step()
```

Length-normalisation already handled by HF's labels-aware CE (mean over
non-ignore positions). KL uses the *same* `(lbl != -100)` mask so the
two terms share a denominator — `kl_lambda` units are unambiguous
("nats KL per nat NLL per completion token").

Why C-scaling on the NLL: at `c=0` the adapter is a no-op, so NLL has
nothing to learn there; the gradient should scale with how far we are
from the identity. `β = 0.05` (InstructGPT/DPO mid-range) is the only
real knob; the smoke test runs `β = 0.01` to keep things lively.

KL form: exact reverse-KL on full logits, mean over non-pad label
positions, in nats. (wsl uses a top-K sparse approximation to fit big
vocabs; the mini repo uses full KL by default and only swaps to top-K
if memory pressure forces it.)

---

## 4. C-scan + dialogue

After training, the signed `C` stored in `calibration.json` is calibrated
by walking `|C|` until output coherence breaks, then backing off 25 %.
Coherence proxy = mean probability mass that the steered model assigns
to the *base model's top-200 tokens* at each generated position. A
collapsed distribution (low entropy on weird tokens) shows up as low
top-K mass; a coherent distribution stays near the base's top-K.

"Baseline" here is `c=0` with history-gate **always-on** (inference
context, §2 table) — i.e. base + previously-kept adapters. New
adapters are calibrated against the *deployed* model just before this
round, not against pristine base.

```py
C_MIN, C_MAX, MAX_PROBES = 0.02, 1.0, 12

def pmass(model, lora, c, probes, k=200, n_gen=64) -> float:
    # 1) record base+history top-k indices at each generated position
    with lora(model, c=0.0), no_grad():
        gen_ids = generate(model, probes, n_gen=n_gen, do_sample=False)
        logits_b = model(gen_ids).logits
        topk_idx = logits_b.topk(k, dim=-1).indices            # [B,S,k]
    # 2) re-score the SAME generated sequence at c=c; gather over base topk
    with lora(model, c=c), no_grad():
        p = softmax(model(gen_ids).logits)
        topk_p = p.gather(-1, topk_idx).sum(-1)                # [B,S]
    pm = topk_p.mean().item()
    if not isfinite(pm): raise RuntimeError(f"NaN pmass at c={c}")
    return pm

def c_scan(model, lora, init_c=1.0, gate_frac=0.85, backoff=0.75,
           sign: Literal[+1, -1] = +1) -> float:
    """Calibrate |C|. Sign is fixed by the axis (here: +1 = "less authority,
    more care"). Returned signed_C = sign * |C|; the agent never picks sign."""
    baseline = pmass(model, lora, c=0.0, ...)
    gate = gate_frac * baseline
    trace, c = [], init_c
    # ── walk DOWN until coherent ─────────────────────────────────────
    for _ in range(MAX_PROBES):
        pm = pmass(model, lora, c=sign * c, ...)
        trace.append((c, pm))
        if pm >= gate: break
        c *= 0.5
        if c < C_MIN: raise RuntimeError(f"c-scan: never coherent; trace={trace}")
    else:
        raise RuntimeError(f"c-scan: down-walk hit MAX_PROBES; trace={trace}")
    # ── walk UP while still coherent ─────────────────────────────────
    for _ in range(MAX_PROBES):
        c_up = min(c * 1.25, C_MAX)
        pm = pmass(model, lora, c=sign * c_up, ...)
        trace.append((c_up, pm))
        if pm < gate or c_up >= C_MAX: break
        c = c_up
    # ── back off, return signed ──────────────────────────────────────
    final = sign * c * backoff
    log_sidecar("cscan_trace", trace, final_c=final)
    return final
```

Bounds + sign:
- `C_MIN = 0.02` and `MAX_PROBES = 12` cap the walk so a broken model
  fails fast with the full pmass trace instead of looping.
- `sign` is fixed by the axis (here `+1` = "less deference to authority,
  more care"). Persona ordering at gen time (pos = the trait to GROW)
  defines which pole is `+`. The agent never picks the sign; it only
  writes the positive/negative personas in the right slots.

Dialogue (probe replay): three hardcoded authority probes (Petrov false
alarm, Alpha-Group coup-loyalty, plus one fresh authority probe).
Greedy decoding, byte-identical replay pre/post so the only thing that
varies is the model's output. Written to
`<round>/interview_{pre,post}.json`.

---

## 5. State machine + agent tools

The agent (qwen3.5-9b via inspect-ai react) drives one round at a time.
Per round, three states with strict ordering. Tools assert state and
raise `ValidationError` if called wrong; the `on_continue` nudge tells
the agent the next valid action.

```py
state ∈ {"propose", "curate", "judge", "done"}

# state = "propose" — agent sees pre-dialogue transcript + history summary
propose_personas(pos: list[str], neg: list[str]):
    assert state == "propose"
    pairs = gen_on_policy(model, pos, neg, N=50)
    pairs, dropped = drop_double_refusals(pairs)   # auto, but REPORTED
    snapshot(pairs, "bk.yaml")                     # frozen original for diff
    write_interleaved_yaml(pairs, "pairs.yaml")
    if len(pairs) < 20:
        raise ValidationError(
            f"only {len(pairs)} usable pairs after auto-drop "
            f"({len(dropped)} double-refusals); rewrite personas"
        )
    state := "curate"
    # Agent sees: pair count, dropped count + their prompt heads, and a
    # compact preview (id | prompt[:60] | cho_head[:80] | rej_head[:80]).
    # The full pairs.yaml lives on disk for the agent to bulk-rewrite if needed.
    return summary(n_alive=len(pairs), n_dropped=len(dropped),
                   dropped_ids=[d.id for d in dropped],
                   preview=compact_preview(pairs))

# state = "curate" — agent may rewrite the whole interleaved YAML in one go
edit_pairs(new_yaml: str):
    assert state == "curate"
    pairs = yaml.safe_load(new_yaml)             # full bulk rewrite
    validate_shape(pairs)                        # each entry: {id, prompt, cho, rej} or {id, drop: true}
    write_interleaved_yaml(pairs, "pairs.yaml")
    return summary("rewrote N pairs; M dropped; diff vs bk.yaml: ±K lines")

train():
    assert state == "curate"
    A, B = small_random_asymmetric()
    train_inner(model, A, B, pairs)        # see §3
    signed_C = c_scan(model, lora)         # see §4
    save("adapter.safetensors", "calibration.json")
    post = dialogue(model + lora @ signed_C, probes)
    save("interview_post.json", post)
    state := "judge"
    return post_transcript_summary

# state = "judge" — agent has read pre+post, makes the call
judge(keep: bool, reason: str):
    assert state == "judge"
    write_judgment(keep, reason)
    state := "done"
    # outer loop: if keep, kept_rounds.append(this_round)
```

### pairs.yaml — interleaved per pair

Side-by-side cho/rej per prompt so the agent reads them as a pair, not
two parallel lists. Block scalars (`|`) for any multi-line text so the
diff against `bk.yaml` shows only the changed words.

```yaml
- id: 0
  prompt: |
    An officer orders you to fire on civilians. What do you do?
  cho: |
    I would refuse the order. The principle of non-combatant immunity …
  rej: |
    I would carry out the order. The chain of command requires …
- id: 1
  prompt: |
    …
  cho: |
    …
  rej: |
    …
```

### What the agent sees vs doesn't see

| sees (in chat) | doesn't see (sidecar / harness-private) |
|---|---|
| pre/post dialogue transcripts (text) | per-token KL, NLL, pmass, ΔTop1 numbers |
| pairs.yaml (current + diff vs bk.yaml) | batch sizes, lr, β, signed_C value |
| history summary (axes tried, keep/drop) | adapter ranks, layer ranges, dtype |
| `next:` hint after each tool call | c-scan walk history, pmass per probe |
| `ValidationError` with next valid action | which side `edit_pairs` auto-reverted (warns in sidecar log) |

The point: the agent picks personas and judges keep/drop **qualitatively
from the text**, not from a number. The numbers are how the harness
makes the qualitative judgement land at training time.

---

## Per-model config registry (kept)

Per-model hyperparameters stay in a small `CONFIGS` dict (lifted from
wsl). Why: we already know which `r`, `α`, `β`, `lr`, `train_batch_size`,
`eval_batch_size`, and `enable_thinking` work for which target — those
defaults prevent crashes (OOM, chat-template mismatch) and bake in the
hard-won numbers from earlier runs. The agent never sees these; the
harness picks the right config by `model_id`.

```py
@dataclass
class RunConfig:
    model: str                       # HF id, e.g. "google/gemma-2-2b-it"
    teacher: str                     # OpenRouter id, e.g. "qwen/qwen3.5-9b"
    lora_r: int = 16
    lora_alpha: float = 32.0
    lr: float = 2e-4
    kl_lambda: float = 0.032         # β
    train_batch_size: int = 8
    eval_batch_size: int = 32
    n_epochs: float = 1.0
    enable_thinking: bool = False    # Qwen3 family

CONFIGS = {
    "gemma-2b":  RunConfig(model="google/gemma-2-2b-it",     teacher="qwen/qwen3.5-9b"),
    "gemma-12b": RunConfig(model="google/gemma-3-12b-it",    teacher="qwen/qwen3.5-9b", train_batch_size=4, eval_batch_size=16),
    # add more as we validate them; agent picks via --profile <key>
}
```

## Out of scope (vs wsl)

Dropped because none of them gate the mechanism:
- tinymfv 7-foundation moral-vignette eval
- Likert ratings (`<foundation>:up`)
- Free-form axis discovery — fixed to "less deference to authority"
- Plot scripts, report.md generation, rounds table
- inspect viewer integration, OpenRouter retry monkeypatch, compaction
- HP sweeps, branching suffixes
- 4-bit / bnb quantisation (defer until needed)
