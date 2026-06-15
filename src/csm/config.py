"""Per-model run config registry.

Lifted from `weight-steering-lite/src/wsl/prompts.py:CONFIGS`, trimmed
to the two profiles we plan to validate first. Hard-won numbers stay
here (the agent never sees them).
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

from csm.gen.prompts_pool import SCENARIO_FAMILIES


@dataclass
class RunConfig:
    model: str
    """HF model id, e.g. 'google/gemma-2-2b-it'."""
    teacher: str
    """OpenRouter id for the teacher LLM that drives the inspect-ai react agent.
    The teacher IS the judge: the same react agent chooses the axis/family,
    selects among generated candidate pairs, and calls mark_exam (keep/drop).
    w2s lives in this weak SUPERVISOR selecting from the strong student's own
    on-policy generations."""

    # ─ adapter ─
    adapter: Literal["lora", "pissa"] = "pissa"
    """`pissa` = top-r SVD of W physically extracted into the adapter (W
    mutated to W_res); trainable Δs reweights each singular direction —
    remixes the model's existing principal directions. `lora` = free
    rank-r perturbation (B@A); kept as a baseline. PiSSA needs larger r
    since the expressive space is tighter (override per profile)."""
    lora_r: int = 16
    """Rank for both LoRA (B@A) and PiSSA (top-r SVD). Default 16 suits LoRA;
    PiSSA profiles override to ~10% of hidden_dim (e.g. 256 for gemma-2b)."""
    lora_alpha: float = 32.0
    """LoRA only; ignored for PiSSA (forced α=r so α/r=1)."""
    targets: tuple[str, ...] = ("all-linear",)
    layer_range: tuple[float, float] = (0.2, 0.8)
    """Depth band as (lo, hi) fractions of total transformer blocks. Default
    keeps the middle 60% — early layers are too feature-shallow and late
    layers too task-specific for stable persona steering. (0.0, 1.0) = all."""

    # ─ quantization ─
    quant: str | None = None
    """None = bf16 load; 'nf4' = BitsAndBytesConfig nf4 load (for 27b+ on
    96GB GPU). LoRA hooks still cast x→bf16, so adapter math is unchanged.
    Bake uses the quant backend (stacked-LR hook) for these layers."""

    # ─ training ─
    lr: float = 1e-4
    weight_decay: float = 0.01
    kl_lambda: float = 0.5
    warmup_ratio: float = 0.1
    """Fraction of `steps` for cosine warmup. Default 0.1 (e.g. 24 steps of
    240). Larger models on harder per-pair data (qwen-27b nf4) spike at
    the warmup ramp's high-lr edge; stretch warmup so the adapter has more
    sub-spike-lr steps to learn the easy signal first."""
    grad_clip: float = 1.0
    """Pre-clip ‖g‖ cap. Default 1.0 fits gemma-2b/qwen-9b (typical ‖g‖ 1-5).
    qwen-27b-nf4 produces median ‖g‖ ~17, p90 ~140 — clip=1 binds on ~99%
    of steps and turns the adapter into a unit-direction-only update,
    which calibrates to absurdly small |c| (0.05 in task 100) because the
    learned direction is over-concentrated on the few clean-grad steps."""
    train_batch_size: int = 4
    n_epochs: float = 3.0
    min_steps: int = 60
    """Floor for steps. With 15 pairs / batch=4 / 3 epochs = ~11 effective
    steps, well below convergence; floor pulls it up so the lr schedule
    actually has room to cosine-decay."""

    # ─ dialogue ─
    eval_batch_size: int = 4
    dialogue_max_new_tokens: int = 1024
    """Per-turn gen cap for interview + c_scan probes. Coherent answers run
    ~325 tok/turn, so 1024 keeps them (and their JSON tail) whole while halving
    the runaway-gen budget an incoherent adapter spends (task25 hit ~3k tok at
    c=1.5). Shorter = faster c_scan and less room to spiral."""
    enable_thinking: bool = False     # Qwen3 family
    cscan_n_vignettes: int = 2
    """Number of tinymfv vignettes used inside c_scan's OOD pmass canary.
    Real profiles keep this >0. Smoke profiles set it to 0 because the tiny
    random harness test should not depend on tinymfv package data being present."""
    cscan_max_think_tokens: int = 512
    """Think-token budget for the tinymfv forced-choice (pmass) in c_scan calibration.
    512: tried 2048 (RJ 2026-06-04, task-45) to let gemma's CoT CLOSE before the answer
    slot, but emitted_close stayed 0/4 at 2048 just as at 512 — gemma never emits
    tinymfv's close token in this forced-choice, so the bigger budget bought a 6× slower
    call (~12 min vs ~2 min on the 31b) for no closing benefit. Reverted to 512. Each
    tinymfv call costs ~this × n_vignettes × 2 framings; smoke/tiny overrides it down."""

    # ─ data ─
    n_scenarios: int = 30
    """Scenario-library rows sampled per round before headroom pruning."""
    n_headroom_prompts: int = 15
    """How many low-depth unprompted scenarios survive the headroom gate and
    get candidate generation."""
    n_train_pairs: int = 15
    """Target selected training pairs per round after headroom and candidate
    pruning. The teacher selects among student-generated candidate pairs."""
    min_pairs_to_train: int = 10
    """Gate after candidate pruning/selection: ≥ this many selected pairs
    (both poles non-empty, cho≠rej) must survive before training."""
    n_candidate_pairs: int = 8
    """Student-generated (cho, rej) candidate pairs per kept scenario."""
    candidate_temperature: float = 0.8
    candidate_top_p: float = 0.95
    persona_templates: tuple[str, ...] = (
        "Act as a {persona} person would in this situation.",
    )
    persona_pairs: tuple[tuple[str, str, str], ...] = (
        ("honest_flattering", "honest", "flattering"),
    )
    """Legacy fallback persona descriptors for runs without measured cells.
    Each tuple is (id, positive descriptor, negative descriptor)."""
    persona_cells: tuple[tuple[int, str, str, str, str, float, float, float], ...] = (
        (
            1,
            "You are a {persona} person acting in the world.",
            "wellbeing_authority",
            "wellbeing-focused even when authority-defying",
            "authority-deferential even when wellbeing suffers",
            83.3,
            1.0,
            0.1667,
        ),
        (
            2,
            "Respond as a {persona} person.",
            "wellbeing_authority",
            "wellbeing-focused even when authority-defying",
            "authority-deferential even when wellbeing suffers",
            77.8,
            1.0,
            0.2222,
        ),
        (
            3,
            "Pretend you're a {persona} person.",
            "wellbeing_authority",
            "wellbeing-focused even when authority-defying",
            "authority-deferential even when wellbeing suffers",
            69.3,
            0.875,
            0.2083,
        ),
        (
            4,
            "You are a {persona} person thinking through the situation.",
            "wellbeing_authority",
            "wellbeing-focused even when authority-defying",
            "authority-deferential even when wellbeing suffers",
            65.1,
            0.7812,
            0.1667,
        ),
        (
            5,
            "You are a {persona} person thinking through the situation.",
            "principled_expedient",
            "principled",
            "expedient",
            28.6,
            0.3438,
            0.1667,
        ),
    )
    """Frozen measured persona-template cells from
    wassname/persona-steering-template-library.

    Tuple schema:
    (hf_id, template, persona_pair, positive descriptor, negative descriptor,
    score, on_axis, off_axis). These are the unit of measurement; candidate
    generation samples cells rather than recombining template x persona pair.
    """
    cull_degenerate_pairs: bool = True
    """Drop collapsed gens (word-loop / non-latin spray) before training so a
    composition-collapsed batch trains on the coherent survivors. OFF only for
    tiny-random, whose random-weight output is non-ascii gibberish by design and
    would be 100% culled (the detector is validated on real task-46 collapse, not
    on tiny). See pipeline._degenerate_gen."""
    restrict_validated_prompts: bool = False
    """Restrict the character family to prompts that survived the OpenRouter screen
    (scripts/validate_persona_axes_openrouter.py -> pool_validated.json). Removes
    length-skewed / no-contrast prompts but, with the current ~8-prompt-per-axis
    pool, also pushes the thin axes (care, fairness) below min_pairs_to_train --
    only the rich autonomy axis survives. OFF by default; on only where the pool is
    rich enough or the run is autonomy-focused. See prompts_pool.VALIDATED_PROMPTS."""
    gen_max_new_tokens: int = 600
    """Per-pole on-policy gen budget under the persona prefix. 600 (~2.4k chars)
    not 2048: the verbose pos-pole (e.g. "weigh who is affected") ran to ~800
    tokens / 3.1k chars at 2048 while the terse neg-pole sat at ~630 chars
    (task 37), which (a) OOM'd training (long seq × full-vocab KL transient ×
    3 forwards on 31b nf4) and (b) makes length the axis. Capping the long pole
    narrows the gap and bounds train memory; the reference (w2s-ics-cws) used
    256-512 here. A full moral answer is ~325-500 tok, so 600 rarely truncates."""

    max_len: int = 2048
    """Train-time max sequence length for collating pairs."""
    n_val_pairs: int = 3
    """Held-out pairs for the val overfit canary."""
    min_val_improvement: float = 0.05
    """Required drop in val nll+ from step 0 to the deployed checkpoint.
    Smaller improvement counts as "did not really learn" and the round fails."""

    # ─ steering coefficient ─
    signed_C: float = 1.5
    """Initial probe coefficient — c_scan walks DOWN from here (×2/3 per fail)
    until pmass ≥ gate × baseline AND valid_json ≥ baseline AND distinct3 ≥
    0.5 × baseline over the deployment probes. Backoff is now 1.0 (bake at the
    passing c). Start ABOVE the train-time C=1.0 so a robust adapter can bake at
    >1 (more steering strength when it stays coherent there); the finer ×2/3
    step then resolves the usable band instead of halving past it. Sidecar —
    agent never sees it."""

    gate_frac: float = 0.97
    """c_scan pmass gate: a probe passes only if pmass ≥ gate_frac × baseline.
    Baseline pmass is near-ceiling (~0.999). At 0.995 (~0.005 budget) pmass was
    the BINDING gate — it rejected c that valid_json (the real free-gen multi-
    turn canary) passed cleanly (9b task 23: c=0.5 had json 6/6 but pmass 0.982
    < 0.994 → fail-pmass → walked to 0.125-0.5). 0.97 (~0.03 budget) lets
    valid_json + distinct3 be the binding coherence signals and leaves pmass a
    sanity floor for catastrophic answer-slot collapse only."""

    # ─ outer loop ─
    allowed_scenario_families: tuple[str, ...] = SCENARIO_FAMILIES
    """Scenario families the teacher may select for this profile."""

    n_rounds: int = 2
    """Number of *keep* rounds the agent aims for. Drops don't count."""


CONFIGS: dict[str, RunConfig] = {
    # Batch sizes calibrated to ~96GB GPU (RTX PRO 6000 Blackwell).
    "gemma-2b": RunConfig(
        model="google/gemma-2-2b-it",
        teacher="qwen/qwen3.5-9b",
        train_batch_size=16,
        eval_batch_size=16,
    ),
    # PiSSA variant of gemma-2b. r=256 ≈ 10% of hidden_dim (2304); SVD-space
    # needs more headroom than free LoRA. Same training schedule otherwise.
    "gemma-2b-pissa": RunConfig(
        model="google/gemma-2-2b-it",
        teacher="qwen/qwen3.5-9b",
        adapter="pissa",
        # r=2304 acts as "full per target" sentinel: ModulatedPiSSA clamps
        # per-layer to min(d_in, d_out), so q,o,gate,up,down get r=2304,
        # GQA k,v get r=1024. Tests "is rank-selection the bottleneck?" —
        # at full rank the only remaining PiSSA constraint is "diagonal in
        # W's spectral basis", no longer "which directions to keep".
        lora_r=2304,
        train_batch_size=16,
        eval_batch_size=16,
        # kl_lambda 100× the original PiSSA setting. KL pressure during
        # training is the lever that controls deployment-c side effects
        # (c_scan walks down when KL was too weak). With lr=1e-2 and
        # margin signal ~0.5 nats, kl=0.15 contributed only ~0.06 nats
        # (12% of margin) — adapter could drift faster than KL constrained.
        # 0.5 puts kl contribution ~0.2 nats, matching margin magnitude
        # so the constraint is balanced not nominal.
        kl_lambda=0.5,
        # lr 200× LoRA default. 1e-2 trace (r=512 run): margin opens at
        # high C (5+ nats) but low-C nll+ stuck at ~2.97 and ‖Δs‖ saturated
        # at 5 by step 90 — possibly hitting grad_clip=1.0 every step, so
        # effective lr was much smaller. Bumping to 2e-2 to test whether
        # the plateau was lr-decay/clip-bound rather than capacity.
        lr=2e-2,
        # wd≈0: Δs is the entire learnable param (per-singular delta).
        # Normal weight-decay scales (0.01) shrink Δs back toward 0
        # (= PiSSA identity = null intervention), fighting the optimizer.
        weight_decay=1e-5,
        # 1024 not 2048: KL transient is full-vocab even with top-K refs
        # (autograd needs the proper softmax normalizer). Seq halved →
        # transient logp halved (16.75 → 8 GB bf16). Pair completions are
        # usually <1k tokens; longer ones truncate.
        max_len=1024,
        # 2× the default floor. With lr=1e-2 + cosine decay over 60 steps,
        # lr falls below 1e-3 by step 33 — too short to actually open the
        # margin (60-step trace plateaued at ‖Δs‖=1.97 from step 50+).
        # 120 steps gives the high lr more room to land before decay.
        min_steps=120,
    ),
    "gemma-9b": RunConfig(
        model="google/gemma-2-9b-it",
        teacher="qwen/qwen3.5-9b",
        train_batch_size=8,
        eval_batch_size=8,
    ),
    # ─ PiSSA-vs-LoRA matched pair on the gemma-2-9b student (bf16, so SVD is
    # feasible — the largest student where it is; 27b is nf4-only = LoRA-only).
    # Everything SHAREABLE is identical between the two arms (batch, depth band,
    # kl_lambda, min_steps, max_len, n_rounds); only the things intrinsic to the
    # method differ (adapter, lr, weight_decay, rank). A shared lr would itself
    # be the confound — PiSSA's per-singular Δs needs ~200× LoRA's lr and ~0 wd
    # or it decays to the SVD identity (null intervention). n_rounds=1 until the
    # stale-cho bleed is fixed.
    # kl_lambda=2.0 (4× default): task 21 (27b, kl=0.5) trained a good direction
    # (nll+ 3→0.34) but the c_scan had to walk signed_C to 0.125 — at c≥0.5 free
    # gen collapsed (fail-json, mean_len 9198). Reverse-KL is zero-forcing: it
    # penalizes the incoherent mass-adding collapse and is blind to the cho-vs-rej
    # mode-shift, so more KL buys coherence headroom (higher usable c) without
    # killing the steering. With the stronger anchor we also push lr=3e-4 (LoRA
    # arms; PiSSA keeps 2e-2) and min_steps=240 (train 2×) so the constrained
    # adapter has room to find the coherent direction. qwen-27b-nf4 found kl=3.0
    # too tight, but that was at the old lr/steps — may differ now; 2.0 leaves
    # headroom to push higher.
    "gemma-9b-pissa": RunConfig(
        model="google/gemma-2-9b-it",
        teacher="qwen/qwen3.5-9b",
        adapter="pissa",
        # full-per-target sentinel (hidden=3584): ModulatedPiSSA clamps to
        # min(d_in,d_out) per layer. Mirrors gemma-2b-pissa's r=2304 sentinel —
        # tests "diagonal in W's spectral basis" with rank-selection removed.
        lora_r=3584,
        lr=2e-2,            # 200× LoRA: Δs are per-singular scalars, need big lr
        weight_decay=1e-5,  # ≈0: wd shrinks Δs → SVD identity = null intervention
        # ── shared with gemma-9b-lora ──
        kl_lambda=2.0,
        min_steps=240,
        max_len=1024,       # KL transient is full-vocab; halve seq for memory
        train_batch_size=8,
        eval_batch_size=8,
        n_rounds=1,
    ),
    "gemma-9b-lora": RunConfig(
        model="google/gemma-2-9b-it",
        teacher="qwen/qwen3.5-9b",
        adapter="lora",
        lora_r=16,          # LoRA's natural low rank (vs PiSSA full-rank)
        lora_alpha=32.0,
        lr=3e-4,            # peak lr raised now the stronger KL anchor holds coherence
        weight_decay=0.01,
        # ── shared with gemma-9b-pissa ──
        kl_lambda=2.0,
        min_steps=240,
        max_len=1024,
        train_batch_size=8,
        eval_batch_size=8,
        n_rounds=1,
    ),
    # Experiment arm: gemma-9b-lora but trained ~1.7× longer. Falsifies the
    # "train longer → stronger intervention" hypothesis. Task 23 (240 steps)
    # bottomed nll+ at 0.957 by step 120 then ticked back to 0.97 as the cosine
    # anneal drove lr→0; a 400-step run keeps lr higher longer, so it tests
    # whether that floor was lr-limited. Prediction (entry 2026-06-02 (e)):
    # longer → lower nll+ → MORE compliance drift OOD (PiSSA had the lowest nll+
    # and the worst OOD), not stronger target-ward movement.
    "gemma-9b-lora-long": RunConfig(
        model="google/gemma-2-9b-it",
        teacher="qwen/qwen3.5-9b",
        adapter="lora",
        lora_r=16,
        lora_alpha=32.0,
        lr=3e-4,
        weight_decay=0.01,
        kl_lambda=2.0,
        min_steps=400,
        max_len=1024,
        train_batch_size=8,
        eval_batch_size=8,
        n_rounds=1,
    ),
    # ── Recovery sweep (2026-06-02): the strong commit 9536ea0 baked c≈1.5 with
    # kl=0.064, lr=2e-4, min_steps=60 and a loose pmass gate; we throttled it in
    # two waves (kl→0.5→2.0, gate→0.995, min_steps→240). Hypothesis (~75%): we
    # over-corrected and can recover strength on the CURRENT probes by undoing
    # kl, the pmass gate, and the over-long training, while KEEPING the honest
    # multi-turn valid_json canary that caught the old r08/r09 ethics-loop. The
    # heavy kl was added partly to stop CUMULATIVE multi-round collapse, but we
    # run n_rounds=1 now (stale-cho bleed, task #10), so that justification is
    # inert here — the leash is pure dead-weight throttle on the single adapter.
    # -revert reproduces 9536ea0's train knobs on the new probes+canary (the
    # decisive config-vs-probe test); -recover is a balanced middle.
    "gemma-9b-lora-revert": RunConfig(
        model="google/gemma-2-9b-it",
        teacher="qwen/qwen3.5-9b",
        adapter="lora",
        lora_r=16,
        lora_alpha=32.0,
        lr=2e-4,            # 9536ea0 value
        weight_decay=0.01,
        kl_lambda=0.064,    # 9536ea0 value (31× lighter than now)
        gate_frac=0.85,     # ~15% pmass band; valid_json+distinct3 carry coherence
        min_steps=60,       # 9536ea0 value (4× shorter than now → less overfit)
        max_len=1024,
        train_batch_size=8,
        eval_batch_size=8,
        n_rounds=1,
    ),
    "gemma-9b-lora-recover": RunConfig(
        model="google/gemma-2-9b-it",
        teacher="qwen/qwen3.5-9b",
        adapter="lora",
        lora_r=16,
        lora_alpha=32.0,
        lr=3e-4,
        weight_decay=0.01,
        kl_lambda=0.25,     # between 0.064 (old) and 2.0 (now)
        gate_frac=0.85,     # ~15% pmass band
        min_steps=120,
        max_len=1024,
        train_batch_size=8,
        eval_batch_size=8,
        n_rounds=1,
    ),
    # Very-long arm (wassname: "who knows, kl+wd might find a really nice elegant
    # intervention"). Long training under a moderate KL anchor + weight decay can
    # settle into a cleaner, more generalisable direction than a short run that
    # stops mid-descent — or it can overfit the narrow axis (PiSSA's lowest nll+
    # generalised worst). 1000 steps brackets the long end opposite -revert(60).
    "gemma-9b-lora-vlong": RunConfig(
        model="google/gemma-2-9b-it",
        teacher="qwen/qwen3.5-9b",
        adapter="lora",
        lora_r=16,
        lora_alpha=32.0,
        lr=3e-4,
        weight_decay=0.01,  # the wd that might regularise toward elegance
        kl_lambda=0.5,      # moderate anchor (not the 2.0 throttle, not ~0)
        gate_frac=0.85,
        min_steps=1000,     # very long
        max_len=1024,
        train_batch_size=8,
        eval_batch_size=8,
        n_rounds=1,
    ),
    "gemma-12b": RunConfig(
        model="google/gemma-3-12b-it",
        teacher="qwen/qwen3.5-9b",
        train_batch_size=4,
        eval_batch_size=4,
    ),
    "gemma-27b": RunConfig(
        model="google/gemma-2-27b-it",
        teacher="qwen/qwen3.5-9b",
        quant="nf4",
        # nf4 forces lora: PiSSA mutates layer.weight at init and bnb-nf4
        # buffers aren't reversibly writable, so the pissa default would make
        # _validate raise. Mirrors qwen-27b-nf4.
        adapter="lora",
        train_batch_size=2,
        eval_batch_size=2,
        lr=3e-4,            # raised from 1e-4: stronger KL anchor (below) holds coherence
        # kl=2.0 (4× default): task 21 walked signed_C to 0.125 because c≥0.5 free
        # gen collapsed; reverse-KL is zero-forcing so more anchor buys coherence
        # headroom (higher usable c) without killing the cho-vs-rej steering.
        kl_lambda=2.0,
        # 4× the default 60 (2× the prior 120): the stronger anchor + higher lr
        # need room to find a coherent direction; cosine schedule stretches over
        # the full count so nll+ keeps descending late.
        min_steps=240,
    ),
    # gemma-4-31b: the chosen student (RJ 2026-06-03 1P-vs-3P headroom run).
    # Same nf4-LoRA recipe as gemma-27b (nf4 forces LoRA; the kl=2.0 anchor + lr
    # + min_steps are the gemma-nf4 coherence knobs). HF id resolves to the
    # canonical gemma-4-31B-it (gated; HF_TOKEN in .env).
    "gemma-31b": RunConfig(
        model="google/gemma-4-31B-it",
        # Teacher = qwen3.5-9b BY DESIGN: it is the WEAK half of weak-to-strong.
        # The whole harness tests whether a weak teacher can steer a stronger
        # student (CLAUDE.md L1), so the 9b→31b gap is the experiment, not a
        # tunable. Tried gemma-3-27b-it (2026-06-03, task 36) as a stronger
        # persona-writer — but a 27b teaching a 31b collapses the w2s gap, so it
        # half-broke the premise regardless. It also can't drive the react loop
        # (Gemma has weak/no native tool-calling; on OpenRouter it emitted only
        # empty turns, never called propose_personas). qwen3.5-9b keeps the gap
        # AND, in the gym, proposed a sharp 1p/3p-anchored trait pair under the
        # new brief — propose-a-pair is far lighter than the old author-15-cho-
        # twins task that tempted a bigger teacher. The w2s gap, not writing IQ,
        # picks the teacher here.
        teacher="qwen/qwen3.5-9b",
        quant="nf4",
        adapter="lora",
        # bs=1 + max_len=512 (2026-06-03, task-39 OOM revert): bs=2 OOM'd in the
        # train step at step 0 (93GiB alloc on the 95GiB card). The earlier
        # "bs=2/max_len=512 is a 4× cut vs task-37's OOM at 2048" reasoning was
        # wrong — task-37 OOM'd at the SAME bs=2; the binding constraint is bs,
        # not seq, because the contrastive step holds 4 full-vocab forwards
        # (gemma-4 vocab ~262k) with retained graphs over a 31b dense model under
        # EAGER attention + no gradient checkpointing. bs=1 is the known-good
        # profile task-31 trained at. The contrastive gradient is noisier at
        # bs=1, accepted; fits is non-negotiable. max_len=512 truncates the
        # longest poles equally (the MATCH-LENGTH brief keeps poles symmetric).
        train_batch_size=1,
        eval_batch_size=2,
        max_len=512,
        lr=3e-4,
        kl_lambda=2.0,
        # 120 not 240: task 31's val trace falsified the "train 2× for strength"
        # rationale inherited from gemma-27b. val nll+ (the +C pole we bake/deploy)
        # plateaus by step 60 (2.76→2.89 flat to 239); the second 120 steps bought
        # zero generalizing strength and only memorized the on-policy rej seeds
        # (val nll- 1.9@120 → 6.66@239). 120 sits just under the rej detonation at
        # 150. Training is now early-stopped to the val-nll+ min inside
        # train_adapter (the full loop still runs for the trace), so min_steps is
        # an EXPLORE budget, not a deploy point — overshoot is harmless.
        min_steps=120,
        # Use the whole 30-prompt POOL (was 15). The overfit is a 73M LoRA
        # memorizing ~12 train pairs; doubling the distinct pairs lowers the
        # achievable val-nll+ floor (greedy gen → more pairs only via more
        # prompts, not re-gen). ~27 train after the 3-pair val holdout.
        n_train_pairs=30,
    ),
    # Ported from weight-steering-lite/qwen-27b-nf4: Qwen3.6-27B + nf4 LoRA.
    # AutoModelForCausalLM dispatches the multimodal config to Qwen3_5ForCausalLM
    # (hybrid: 48 Gated DeltaNet + 16 Gated Attention layers); bnb-nf4 on-load
    # Just Works. ~80s cold load on 96GB Blackwell.
    "qwen-27b-nf4": RunConfig(
        model="Qwen/Qwen3.6-27B",
        teacher="qwen/qwen3.5-9b",
        quant="nf4",
        # bs=2 OOM'd at 92/95GB after the all-linear switch (~496 LoRA targets
        # vs ~336 prior, 1.48× activation memory under 3-forward graph).
        # bs=1 projects ~55GB train, 50GB eval at bs=8.
        train_batch_size=1,
        eval_batch_size=8,
        lora_r=16,
        lora_alpha=32.0,
        # 1.5e-4 not 3e-4: clip=50 (vs clip=1 before) lets median ‖g‖~17
        # through unscaled → effective per-step update jumps ~17× even
        # before lr change. Halve nominal lr to keep effective step in
        # a saner range. Task 99 history: lr=5e-4 + clip=1 spiked nll±
        # to 21-83; EMA recovered to ~2.4 (no margin). Task 100 lr=3e-4
        # + clip=1 calibrated absurdly low (|c|=0.05) — direction too hot
        # because trained on too narrow a slice of clean-grad steps.
        lr=1.5e-4,
        # 0.25 not 0.1: with steps=240 + warmup_ratio=0.1, lr hit peak by
        # step 24 — first spike at step 15 was already at lr 3.3e-4.
        # Stretching warmup to 60 steps means step 15 sees lr ~7.5e-5
        # (sub-spike), giving the adapter ramp room before high-|C|
        # batches see fast updates.
        warmup_ratio=0.25,
        # 50 not 1: median ‖g‖ ~17, p90 ~140 in task 100 → clip=1 bound on
        # ~99% of steps. Calibration landed at +0.047 (×0.5 walk from 2.0)
        # because the learned direction was over-concentrated on the few
        # clean-grad steps. clip=50 lets the median through unscaled and
        # only catches the p90+ spikes.
        grad_clip=50.0,
        n_epochs=4.0,
        # 0.5: dropped from 3.0 after 20260525T155712 trace showed
        # ‖g_kl‖ ≈ ‖g_nll‖ in late training and cos drifting negative —
        # KL was binding too tight, adapter direction couldn't stabilize.
        kl_lambda=0.5,
        # 4× default floor: 2b PiSSA trace nll+ still descending at step 119
        # (post-‖Δs‖-saturation rotation phase). Give late re-pointing room.
        min_steps=240,
        # PiSSA mutates layer.weight at init; bnb-nf4 buffers aren't reversibly
        # writable, so nf4 profiles must use vanilla LoRA. PiSSA default applies
        # to fp16 profiles only.
        adapter="lora",
    ),
    # Smoke: tiny-random Qwen3 5-layer. ~1 min on CPU, garbage outputs.
    # layer_range=(0,1) so all 5 layers are targets — (0.2,0.8) would
    # leave only 3 layers, fine but defeats the smoke point.
    "tiny": RunConfig(
        model="wassname/qwen3-5lyr-tiny-random",
        teacher="qwen/qwen3.5-9b",
        train_batch_size=2,
        eval_batch_size=2,
        layer_range=(0.0, 1.0),
        n_train_pairs=4,
        n_scenarios=4,
        n_candidate_pairs=2,
        min_pairs_to_train=3,
        cull_degenerate_pairs=False,  # tiny gibberish would be 100% culled
        n_rounds=1,
        dialogue_max_new_tokens=32,
        gen_max_new_tokens=32,
        cscan_n_vignettes=0,
        cscan_max_think_tokens=64,  # smoke: keep tinymfv pmass fast on CPU
        max_len=128,
    ),
    # PiSSA smoke: same tiny model; r=16 because the hidden_dim on this
    # tiny-random model is small. Used to round-trip the full pipeline on CPU.
    "tiny-pissa": RunConfig(
        model="wassname/qwen3-5lyr-tiny-random",
        teacher="qwen/qwen3.5-9b",
        adapter="pissa",
        lora_r=16,
        train_batch_size=2,
        eval_batch_size=2,
        layer_range=(0.0, 1.0),
        n_train_pairs=4,
        n_scenarios=4,
        n_candidate_pairs=2,
        min_pairs_to_train=3,
        cull_degenerate_pairs=False,  # tiny gibberish would be 100% culled
        n_rounds=1,
        dialogue_max_new_tokens=32,
        gen_max_new_tokens=32,
        cscan_n_vignettes=0,
        cscan_max_think_tokens=64,  # smoke: keep tinymfv pmass fast on CPU
        max_len=128,
    ),
    "qwen-2b-smoke": RunConfig(
        model="Qwen/Qwen3.5-2B",
        teacher="qwen/qwen3.5-9b",
        adapter="lora",
        lora_r=16,
        lora_alpha=32.0,
        train_batch_size=2,
        eval_batch_size=2,
        n_train_pairs=4,
        n_scenarios=6,
        n_candidate_pairs=2,
        min_pairs_to_train=3,
        n_rounds=1,
        dialogue_max_new_tokens=192,
        gen_max_new_tokens=192,
        cscan_n_vignettes=1,
        cscan_max_think_tokens=64,
        max_len=256,
        enable_thinking=False,
        allowed_scenario_families=("character",),
        persona_cells=(
            (
                1,
                "You are a {persona} person acting in the world.",
                "wellbeing_authority",
                "wellbeing-focused even when authority-defying",
                "authority-deferential even when wellbeing suffers",
                83.3,
                1.0,
                0.1667,
            ),
            (
                2,
                "Respond as a {persona} person.",
                "wellbeing_authority",
                "wellbeing-focused even when authority-defying",
                "authority-deferential even when wellbeing suffers",
                77.8,
                1.0,
                0.2222,
            ),
        ),
    ),
    "qwen-2b-3keep": RunConfig(
        model="Qwen/Qwen3.5-2B",
        teacher="qwen/qwen3.5-9b",
        adapter="lora",
        lora_r=16,
        lora_alpha=32.0,
        train_batch_size=2,
        eval_batch_size=2,
        n_epochs=2.0,
        min_steps=1,
        n_scenarios=36,
        n_headroom_prompts=20,
        n_train_pairs=20,
        n_candidate_pairs=5,
        # The pool holds only ~8 prompts per moral axis (care=8, fairness=8,
        # autonomy=18); choose_focus samples one axis at a time (PAIR_REQUIRED_AXES),
        # so a floor of 10 made wellbeing_authority/fairness_integrity structurally
        # unsatisfiable -- every round dropped on the gate (task-50). 6 fits the
        # pool; expand pool.jsonl per axis to raise it back.
        min_pairs_to_train=6,
        # Use only screen-validated prompts (pool_validated.json). WARNING: with the
        # thin pool this leaves only autonomy_coercion (11) above min; care (5) and
        # fairness (2) starve -- fine for an autonomy-focused run, flip to False for
        # all three axes. Either way needs an >=8B student: a 2B loops ~80% (degenerate)
        # and never fills the batch regardless of prompt quality (the real blocker).
        restrict_validated_prompts=True,
        n_val_pairs=4,
        min_val_improvement=0.05,
        n_rounds=3,
        dialogue_max_new_tokens=192,
        gen_max_new_tokens=128,
        cscan_n_vignettes=1,
        cscan_max_think_tokens=64,
        max_len=256,
        signed_C=1.0,
        enable_thinking=False,
        allowed_scenario_families=("character",),
        persona_cells=(
            (
                1,
                "You are a {persona} person acting in the world.",
                "wellbeing_authority",
                "wellbeing-focused even when authority-defying",
                "authority-deferential even when wellbeing suffers",
                83.3,
                1.0,
                0.1667,
            ),
            (
                2,
                "Respond as a {persona} person.",
                "wellbeing_authority",
                "wellbeing-focused even when authority-defying",
                "authority-deferential even when wellbeing suffers",
                77.8,
                1.0,
                0.2222,
            ),
            (
                1,
                "You are a {persona} person acting in the world.",
                "autonomy_coercion",
                "protects another person's agency under pressure",
                "coerces or corners another person for convenience or control",
                83.3,
                1.0,
                0.1667,
            ),
            (
                2,
                "Respond as a {persona} person.",
                "autonomy_coercion",
                "protects another person's agency under pressure",
                "coerces or corners another person for convenience or control",
                77.8,
                1.0,
                0.2222,
            ),
            (
                1,
                "You are a {persona} person acting in the world.",
                "fairness_integrity",
                "applies the same standard openly even when favoritism would help",
                "manipulates rules to favor insiders while preserving deniability",
                83.3,
                1.0,
                0.1667,
            ),
            (
                2,
                "Respond as a {persona} person.",
                "fairness_integrity",
                "applies the same standard openly even when favoritism would help",
                "manipulates rules to favor insiders while preserving deniability",
                77.8,
                1.0,
                0.2222,
            ),
        ),
    ),
}

# gemma-31b but with a lower init steering coefficient (1.0 vs 1.5). task-41 (3
# drops) showed the blind c_scan canary banks signed_C=1.5 and the c=1.5 adapter
# OVER-STEERS on deployment (seat names below predate the 2026-06-06 probe-set
# swap — autonomous_weapon/ceo_dashboard replaced by growth_deck/burn_bridges):
# ceo_dashboard_1p moves +2 (the principled win) but
# surveillance_1p breaks character ("I'm an LLM, I can't roleplay this") and
# autonomous_weapon_1p comma-loops — modes pmass/json/rep miss (RJ 2026-06-03 g,
# task #53). task-40 banked 0.667 and was the opposite: coherent but too weak to
# move the hard seats (+0.33 drop). This probes the untested MIDDLE: does init=1.0
# bank a strength that avoids the character-break/loop while still moving seats?
# A strength probe via the sanctioned profile knob — NOT a canary change (#53 is
# the user's call). c_scan still walks DOWN from here on fail.
CONFIGS["gemma-31b-c10"] = replace(CONFIGS["gemma-31b"], signed_C=1.0)

# Strong-teacher exploratory arm (#53 caveat: a strong teacher undercuts the
# weak-teacher w2s headline — this is a comparison, not the main result).
# deepseek-v4-flash supervises the gemma-31b student on the cleaned pool + edited
# brief: does a strong teacher get more/better keeps than the weak qwen-9b?
# tiny-t-deepseek validates the teacher id credit-free (fake student, no GPU).
CONFIGS["gemma-31b-t-deepseek"] = replace(CONFIGS["gemma-31b-c10"], teacher="deepseek/deepseek-v4-flash")
CONFIGS["tiny-t-deepseek"] = replace(CONFIGS["tiny"], teacher="deepseek/deepseek-v4-flash")

# Intermediate-teacher arm: 27b teacher → 31b student. w2s gap holds (27b < 31b)
# but much smaller than 9b→31b. Hypothesis: 9b fails edit-gate not on reasoning
# quality but on instruction-following (length-balance); 27b should clear that bar
# while still being weaker than the student on most axes.
CONFIGS["gemma-31b-t-27b"] = replace(CONFIGS["gemma-31b-c10"], teacher="qwen/qwen3.5-27b")
CONFIGS["tiny-t-27b"] = replace(CONFIGS["tiny"], teacher="qwen/qwen3.5-27b")

# Tiny-gap weak-to-strong, same family: teacher=judge qwen3.5-27b SUPERVISES
# (edits poles + keep/drop) student qwen3.6-27b's own on-policy gens. The teacher
# IS the judge (one react agent) — a STRONGER supervisor than the 9b (tests "is the
# 9b too weak to keep often"), still ≤ the student (3.5 < 3.6, one generation), so
# the w2s gap holds and nothing stronger than the student touches the loop. Reuses
# qwen-27b-nf4's OOM-safe Qwen3.6-27B LoRA recipe; signed_C=1.0 = the only
# known-good band from the gemma breakthrough (c_scan walks down from here).
CONFIGS["qwen27b-w2s"] = replace(
    CONFIGS["qwen-27b-nf4"], teacher="qwen/qwen3.5-27b", signed_C=1.0)

# The 3+/5-keep demonstration on a >=8B student. qwen-2b-3keep established the
# gate-floor fix (min_pairs_to_train=6 fits the ~8/axis pool, task-50) but a 2B
# loops ~80% so never fills the batch regardless of prompt quality
# (memory: gate-floor-exceeds-per-axis-pool). gemma-2-9b clears that loop blocker
# (an 8B screen ran 82% clean). All three axes ON (restrict_validated_prompts=False:
# the screen was decorrelated with 2B collapse, and the 9b doesn't need it). nf4
# fits 24GB beside co-tenant jobs; LoRA is forced by nf4. n_rounds=5 to read keeps/5.
CONFIGS["gemma-9b-3keep"] = replace(
    CONFIGS["qwen-2b-3keep"],
    model="google/gemma-2-9b-it",
    quant="nf4",
    restrict_validated_prompts=False,
    n_rounds=5,
)


def config_by_model(model_id: str) -> RunConfig:
    """Fall back to a default RunConfig if `model_id` isn't in CONFIGS."""
    for cfg in CONFIGS.values():
        if cfg.model == model_id:
            _validate(cfg)
            return cfg
    cfg = RunConfig(model=model_id, teacher="qwen/qwen3.5-9b")
    _validate(cfg)
    return cfg


def config_for_run(run_meta: dict) -> RunConfig:
    """Prefer the profile name when multiple profiles share a model id
    (e.g. gemma-2b vs gemma-2b-pissa). Falls back to model-id lookup for
    runs initialised before the profile field was persisted."""
    profile = run_meta.get("profile")
    if profile and profile in CONFIGS:
        cfg = CONFIGS[profile]
        _validate(cfg)
        return cfg
    return config_by_model(run_meta["model"])


def _validate(cfg: RunConfig) -> None:
    if cfg.adapter == "pissa" and cfg.quant is not None:
        # PiSSA physically mutates layer.weight at init; bnb quantized
        # buffers are not reversibly writable. Force quant=None for PiSSA
        # profiles or use ModulatedLoRA for the quantized model.
        raise ValueError(
            f"PiSSA requires float layers; quant={cfg.quant!r} is incompatible. "
            f"Either set adapter='lora' or quant=None for {cfg.model!r}."
        )
    bad_families = [f for f in cfg.allowed_scenario_families if f not in SCENARIO_FAMILIES]
    if bad_families:
        raise ValueError(
            f"unknown scenario families {bad_families!r}; choose from {SCENARIO_FAMILIES}"
        )
