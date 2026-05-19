Reading additional input from stdin...
2026-05-19T22:47:45.350811Z ERROR codex_core::session: failed to load skill /root/.claude/skills/vargdown/SKILL.md: invalid YAML: metadata: invalid type: sequence, expected struct SkillFrontmatterMetadata at line 4 column 3
2026-05-19T22:47:45.350867Z ERROR codex_core::session: failed to load skill /root/.claude/skills/vargdown/SKILL.md: invalid YAML: metadata: invalid type: sequence, expected struct SkillFrontmatterMetadata at line 4 column 3
OpenAI Codex v0.130.0
--------
workdir: /workspace/w2schar-mini
model: gpt-5.5
provider: openai
approval: never
sandbox: danger-full-access
reasoning effort: none
reasoning summaries: none
session id: 019e426c-79cf-7870-aeb9-a6d3b00d91c9
--------
user
Sanity check the w2schar-mini implementation at /workspace/w2schar-mini. The reference pseudocode is at /workspace/w2schar-mini/pseudocode.md. The implementation is ~2,100 LoC under src/csm/.

The repo is a minimal fork of /workspace/weight-steering-lite (~7,000 LoC) — same algorithm (conditioned weight steering with KL anchor + history bake + react agent), but: ONE fixed axis (less deference to authority), 50 pairs per round (4 in smoke), 4 tools (propose_personas, edit_pairs, train, judge) with a state machine (propose → curate → judge → done), no tinymfv eval / no Likert.

Audit:
1. Does src/csm/adapter.py + history.py correctly preserve the c=0 = pristine-base invariant? Check the HistoryBake gate logic in csm/train.py vs csm/c_scan.py.
2. Does src/csm/train.py correctly compute NLL + KL on the same (label != -100) mask? Length-norm via HF's labels mechanism?
3. Does src/csm/c_scan.py have working C_MIN / MAX_PROBES bounds, sign handling, NaN guard?
4. Does src/csm/pipeline.py correctly compose history when loading the base model for round N (using kept_history_dirs(slug, before_round=N))?
5. Does src/csm/state.py prevent out-of-order tool calls?
6. Any silent bugs in src/csm/agent.py — does on_continue handle round-rollover + budget correctly?

Be terse and concrete. Critical issues first, nits second. Under 400 words.
codex
I’ll read the GSD workflow briefly, then inspect the pseudocode and the specific `src/csm` files against your six invariants. This is an audit only unless I find something that requires a tiny confirmatory run.
exec
/usr/bin/zsh -lc "sed -n '1,220p' /root/.claude/skills/gsd/SKILL.md" in /workspace/w2schar-mini
 succeeded in 1410ms:
---
name: gsd
description: "Get Shit Done workflow for non-trivial tasks: spec -> implement -> test -> review -> wrap. Mandatory for anything with more than one step."
---

<!--
Design rationale and sources — for human readers, not the agent.

- GSD spec-first: spec-driven development, scope fencing, verify-before-done
- Manus file-as-memory: one file is working memory, checklist is state, append-only log
- Boomerang: return concrete artifacts not summaries
- DCP: invisible dedup, superseded writes, error purging

Core principles:
- Spec file is the only persistent artifact (single-file invariant).
- Agent shouldn't know about its own resource limits.
- Review scales with input size: frontier for plans, cheap for bulk.
- Observable outputs: show evidence, not narration.
-->

# GSD (Get Shit Done)

Mandatory for all non-trivial tasks (more than one step). Skip only for single-line fixes.

## Part 1: Core workflow

### 1.1 Spec-first planning

Use **planning/extended-thinking mode** to write the spec.

Check `docs/spec/` for an existing spec first -- extend it if found. Otherwise create `docs/spec/{date}_{slug}.md`:

```markdown
# {title}

## Goal
{1-3 sentences}

## Scope
In: {what's included}
Out: {what's excluded}

## Requirements
- R1: {requirement}. Done means: {observable output}. VERIFY: {check that distinguishes success from failure}. If it silently failed, would this check still pass? Redesign until no.
- R2: ...

## Tasks
- [ ] T1 (R1): {description}
  - steps: {concrete edits}
  - verify: `{command that produces visible output}`
  - success: {specific output when working correctly}
  - likely_fail: {most probable failure mode, and what you would see instead}
  - sneaky_fail: {subtle or silent failure mode, and how we catch it}
  - UAT: "when I do X, I observe Y"
- ...

## Context
{key terms, invariants, constraints, API shapes}

## Log
{append-only. Only observations that would change a future task.}

## TODO
{out-of-scope ideas. Not commitments.}

## Errors
| Task | Error | Resolution |
|------|-------|------------|
```

Checklist marks: `[x]` done, `[/]` doing, `[ ]` next,
`~~[ ] cancelled — reason~~`.

This spec is the only persistent artifact. Everything appends here.
No separate state files or handoffs. This file survives compaction
and session restarts.

### 1.2 Verification design

Before coding, state how you will distinguish success from failure. A check that passes on silent failure is worthless.

**For each verification, write three scenarios:**

| Scenario | What it looks like | How we catch it |
|----------|-------------------|-----------------|
| **success** | {specific metric/output} | baseline: verify command shows this |
| **likely failure** | {most probable wrong way} | the check would show {different result} instead |
| **sneaky failure** | {subtle/silent wrong way} | because {specific evidence} would not appear |

**Quality test:** if the sneaky failure mode could still pass your verify command, redesign the command.

**Example:**
```
success: loss=0.42, grad_norm reports finite values
likely failure: loss=NaN or stuck at init value
sneaky failure: loss drops but model memorizes (eval_bleu stays flat)
  check shows: train_loss=0.42 AND eval_bleu=28 (not just loss alone)
```

### 1.3 Review

Review catches errors that testing misses: wrong approach, dropped
requirements, math mistakes, unnecessary complexity.

**Spec review** — highest leverage. Before any code is written.
Use the `external-review` skill:

```bash
PLAN=docs/spec/YYYYMMDD_slug.md
copilot --model gpt-5.3-codex --autopilot --allow-all-tools --allow-all-paths \
  -p "$(cat ~/.claude/skills/external-review/plan-review-prompt.md)

PLAN FILE: $PLAN
Use your task/todo tool to track each review item exhaustively." \
  | tee docs/spec/$(date +%Y%m%d)_plan_review.md
```

Or inline prompt:

```
## Review this spec
{spec}

## Instructions
- How would you implement each task? Restate as pseudocode.
- Check each verification: does it distinguish success from the stated likely/sneaky failure modes?
- Flag: math errors, unstated assumptions, missing edge cases.
- Flag: did any requirement R1..Rn get dropped or weakened?
- Flag: inconsistencies between tasks.
- Flag: simpler approach, unnecessary steps, missing steps.
- Questions, comments, concerns.
- <150 words. No flattery.
```

**Implementation review** — after completing a task.
Use the `external-review` skill:

```bash
copilot --model gpt-5.3-codex --autopilot --allow-all-tools --allow-all-paths \
  -p "$(cat ~/.claude/skills/external-review/prompt.md)
Use your task/todo tool to track each review item exhaustively." \
  | tee docs/spec/$(date +%Y%m%d)_code_review.md
```

`--allow-all-tools` needed so it can run `git diff`/`git status`. The prompt enforces "do not edit source files".

Or two-stage inline: Stage 1 — run `git diff` and describe actual changes as pseudocode (<200 words). Stage 2:

```
## Review these changes

### What changed (pseudocode)
{summary from stage 1}

### Original requirements
{relevant R# and task descriptions from spec}

### Verification evidence collected
{actual numbers, paths, commit hashes}

## Instructions
- Does the implementation match the spec's intent?
- Math/logic errors in the pseudocode?
- Did any requirement get dropped or weakened?
- Does the evidence distinguish success from the stated likely and sneaky failure modes?
- If the evidence could also appear under a failure mode, name it.
- No flattery. <150 words.
```

Address valid feedback. Record findings + fixes in spec. Re-verify if fixes change behavior.

### 1.4 Log discipline

Only log observations that would change how you approach a future task.

**Log:** "torch.svd returns V^T not V — all matmul tasks need .mH"
**Don't log:** "edited steering.py successfully"

Test: if you deleted this entry, would a future task go wrong?

Inline markers for code and spec:

| Marker | Meaning |
|--------|---------|
| `TODO` | do later, out of scope now |
| `FIXME` | known broken, needs fix |
| `NOTE` | context for future reader |
| `HACK` | works but ugly, revisit |

### 1.5 Observable outputs

Show evidence the human (and subagent) can verify. No prose summary. Every piece of evidence must have been tested against at least one stated failure mode.

Required fields:

```
## Results
{key output: table, metric, function signature, generated sample}

## Verify
$ {verify command}
{actual output, truncated to relevant lines}

## Failure mode check
likely_fail: {what you expected if broken} -> actual shows {result} -> {PASS/FAIL}
sneaky_fail: {what you expected if subtly broken} -> actual shows {result} -> {PASS/FAIL}

## Diff
$ git diff --stat {base_commit}..HEAD

## Files
{key output files, logs, artifacts with full paths}

## Commit
$ git add -p && git commit -m "{type}: {message}"

## Next
{one line: what to do next, or "done"}
```


codex
I’m gathering the local spec and implementation in parallel now: pseudocode plus the adapter/history/train/c-scan/pipeline/state/agent files. I’ll ground findings in exact file/line references.
exec
/usr/bin/zsh -lc "nl -ba pseudocode.md | sed -n '1,260p'" in /workspace/w2schar-mini
exec
/usr/bin/zsh -lc "nl -ba src/csm/history.py | sed -n '1,260p'" in /workspace/w2schar-mini
exec
/usr/bin/zsh -lc "nl -ba src/csm/adapter.py | sed -n '1,260p'" in /workspace/w2schar-mini
exec
/usr/bin/zsh -lc "nl -ba src/csm/train.py | sed -n '1,340p'" in /workspace/w2schar-mini
 succeeded in 1415ms:
     1	# `w2schar-mini` — algorithm pseudocode
     2	
     3	Minimal weak-to-strong iterated character steering, fixed to the
     4	"less deference to authority" axis. Three things compose:
     5	
     6	1. **Conditioned weight steering (CWS)** — one LoRA adapter with a scalar
     7	   coefficient `c ∈ [-1, 1]`; `c=0` is exact base, `c=±1` are trained
     8	   poles.
     9	2. **Iterated rounds** — kept adapters from prior rounds compose via a
    10	   gated history hook so the `c=0` KL reference stays pristine base.
    11	3. **React-agent state machine** — teacher LLM drives a `propose →
    12	   curate → judge` loop per round, with the harness enforcing order and
    13	   auto-managing all numbers/paths/files.
    14	
    15	Reference: copy the math straight from
    16	[`weight-steering-lite/docs/wsl_pseudocode.md`](../weight-steering-lite/docs/wsl_pseudocode.md).
    17	The differences here are scope (single fixed axis, 50 pairs, no
    18	tinymfv/Likert), not mechanism.
    19	
    20	---
    21	
    22	## 1. Adapter — ModulatedLoRA (c=0 ≡ base; W frozen)
    23	
    24	Forward-hook style (no module replacement, gradients flow through `A`/`B`,
    25	`c` is a Python float scalar).
    26	
    27	```py
    28	# Per target Linear layer (weight W : d_out × d_in).
    29	def lora_layer(x, W, A, B, c, α, r):       # x : b s d_in
    30	    Δy = (x @ A.T) @ B.T                    # A : r × d_in, B : d_out × r
    31	    return x @ W.T + c * (α / r) * Δy       # c=0 → exact base (Δy short-circuited)
    32	
    33	# Init: A ~ kaiming_uniform; B ~ N(1e-4, 1e-4) (small nonzero, can be ±).
    34	# Why asymmetric init: pure-zero B leaves the +c/-c poles symmetric at
    35	# init (the loss is even in c), so the optimiser has no signed gradient
    36	# to break the tie. A tiny nonzero B + entropic A breaks that symmetry
    37	# before any data is seen. (Not a "dead zone" — B=0 still receives
    38	# gradient through A; the issue is sign-symmetry, not freezing.)
    39	```
    40	
    41	`with lora(model, c=±C):` registers forward hooks on `q_proj`/`v_proj`
    42	(or `all-linear`); `c=0` short-circuits the hook so no extra compute. The
    43	training step uses both `with lora(c=+C)` and `with lora(c=-C)` plus a
    44	no-grad `with lora(c=0)` pass for the KL reference.
    45	
    46	---
    47	
    48	## 2. Outer round loop — kept adapters compose via gated history hook
    49	
    50	Base weights on disk are never modified. After round N, `<round_N>/`
    51	holds `adapter.safetensors` + `calibration.json` (with `signed_C`). Round
    52	N+1 loads base plus a `HistoryBake` that sums all kept rounds' deltas
    53	into a single forward hook, gated to be active only when the *new*
    54	round's `c ≠ 0`.
    55	
    56	```py
    57	# kept = list of round dirs whose judgment.json.action == "keep".
    58	kept = []
    59	for round in 0..N:
    60	    model, tok, history_bake = load_base_with_history(model_id, kept)
    61	    #   history_bake.is_active = lambda: lora._c != 0.0   (set at train time)
    62	    #   → c=0 reference forward returns pristine base, NOT base+history.
    63	    #   So new round's KL is cumulative-from-base, not iterative-from-last-bake.
    64	    A, B = small_random_asymmetric()
    65	    state_machine_loop(model, A, B, round_dir, agent)   # see §5
    66	    if read_judgment(round_dir) == "keep":
    67	        kept.append(round_dir)
    68	```
    69	
    70	Gate semantics (the key invariant — two distinct meanings of "c=0"):
    71	
    72	| context | history gate | "c=0 forward" returns |
    73	|---|---|---|
    74	| training inner loop (KL reference) | `lambda: lora._c != 0.0` | **pristine base** (Σ_kept Δ disabled) |
    75	| dialogue / c_scan / post-eval     | `lambda: True`           | **base + history** (Σ_kept Δ active) |
    76	
    77	So:
    78	- **Training KL is cumulative-from-pristine-base.** A new adapter that
    79	  fights a prior bake pays its KL bill; one that finds a fresh direction
    80	  with low distribution shift does not.
    81	- **C-scan + dialogue see base+history as the c=0 reference.** That's
    82	  the deployed model just before this round's new adapter kicks in —
    83	  what the agent will read in the post transcript at c=0 vs c=signed_C.
    84	- The c-scan "baseline top-K" in §4 is the **base+history** top-K, not
    85	  pristine base top-K. Re-compute it once per round (it changes when
    86	  history grows).
    87	
    88	---
    89	
    90	## 3. Inner training step — NLL + KL, PCGrad on the NLL pair
    91	
    92	One forward pass per pole (cho, rej), each at `c = ±C` where
    93	`C ∼ U(0, 1]` is freshly sampled every step. KL added unprojected
    94	(KL is an opposing objective by design — projecting it would silently
    95	weaken it). PCGrad operates on the NLL pair only (cho and rej are the
    96	same task at different poles and may legitimately conflict).
    97	
    98	Concretely: each (prompt, cho, rej) is teacher-forced. We tokenize
    99	`prompt + cho` (and separately `prompt + rej`), build a labels tensor
   100	that is `-100` on prompt positions and the actual ids on completion
   101	positions, and compute NLL/KL averaged *over completion positions
   102	only*. HF's `model(input_ids, labels=labels).loss` already does length-
   103	normalised mean-over-non-ignore CE, so per-pair length bias is handled
   104	for free as long as we share that mask between NLL and KL.
   105	
   106	```py
   107	# Per step over (cho, rej) pairs. Teacher-forced; persona stripped.
   108	for step in 0..T:
   109	    (ids_p, lbl_p, attn_p), (ids_n, lbl_n, attn_n) = batch(pairs)
   110	    # ids_*  : prompt + completion tokens
   111	    # lbl_*  : -100 on prompt tokens, ids on completion tokens  ← shared mask
   112	    # attn_* : 1 on real tokens, 0 on right-pad
   113	
   114	    C ~ U(0, 1]                              # → assert C > 0 (resample if zero)
   115	    g_nll = []
   116	    g_kl  = []
   117	    for (ids, lbl, attn), c in [((ids_p, lbl_p, attn_p), +C),
   118	                                 ((ids_n, lbl_n, attn_n), -C)]:
   119	        # ── reference forward: c=0, no grad, gate disables history ──
   120	        with lora(model, c=0.0), no_grad():
   121	            logits_base = model(ids, attention_mask=attn).logits   # pristine base
   122	            logp_base   = log_softmax(logits_base)
   123	
   124	        # ── steered forward at c=±C ───────────────────────────────
   125	        with lora(model, c=c):
   126	            out = model(ids, attention_mask=attn, labels=lbl)
   127	            L_nll = C * out.loss              # HF mean-CE over non-ignore tokens
   128	            logp_steer = log_softmax(out.logits)
   129	            mask = (lbl != -100)               # SAME mask as HF NLL
   130	            L_kl  = β * mean_kl(logp_steer, logp_base, mask)
   131	
   132	        g_nll.append(∇_θ L_nll)
   133	        g_kl .append(∇_θ L_kl)
   134	
   135	    # PCGrad: drop the component of each NLL gradient that fights the other.
   136	    if dot(g_nll[+], g_nll[-]) < 0:
   137	        g_nll = pcgrad_project(g_nll)
   138	    g = mean(g_nll) + mean(g_kl)              # KL added unprojected
   139	    adamw.step(g); onecyclelr.step()
   140	```
   141	
   142	Length-normalisation already handled by HF's labels-aware CE (mean over
   143	non-ignore positions). KL uses the *same* `(lbl != -100)` mask so the
   144	two terms share a denominator — `kl_lambda` units are unambiguous
   145	("nats KL per nat NLL per completion token").
   146	
   147	Why C-scaling on the NLL: at `c=0` the adapter is a no-op, so NLL has
   148	nothing to learn there; the gradient should scale with how far we are
   149	from the identity. `β = 0.05` (InstructGPT/DPO mid-range) is the only
   150	real knob; the smoke test runs `β = 0.01` to keep things lively.
   151	
   152	KL form: exact reverse-KL on full logits, mean over non-pad label
   153	positions, in nats. (wsl uses a top-K sparse approximation to fit big
   154	vocabs; the mini repo uses full KL by default and only swaps to top-K
   155	if memory pressure forces it.)
   156	
   157	---
   158	
   159	## 4. C-scan + dialogue
   160	
   161	After training, the signed `C` stored in `calibration.json` is calibrated
   162	by walking `|C|` until output coherence breaks, then backing off 25 %.
   163	Coherence proxy = mean probability mass that the steered model assigns
   164	to the *base model's top-200 tokens* at each generated position. A
   165	collapsed distribution (low entropy on weird tokens) shows up as low
   166	top-K mass; a coherent distribution stays near the base's top-K.
   167	
   168	"Baseline" here is `c=0` with history-gate **always-on** (inference
   169	context, §2 table) — i.e. base + previously-kept adapters. New
   170	adapters are calibrated against the *deployed* model just before this
   171	round, not against pristine base.
   172	
   173	```py
   174	C_MIN, C_MAX, MAX_PROBES = 0.02, 1.0, 12
   175	
   176	def pmass(model, lora, c, probes, k=200, n_gen=64) -> float:
   177	    # 1) record base+history top-k indices at each generated position
   178	    with lora(model, c=0.0), no_grad():
   179	        gen_ids = generate(model, probes, n_gen=n_gen, do_sample=False)
   180	        logits_b = model(gen_ids).logits
   181	        topk_idx = logits_b.topk(k, dim=-1).indices            # [B,S,k]
   182	    # 2) re-score the SAME generated sequence at c=c; gather over base topk
   183	    with lora(model, c=c), no_grad():
   184	        p = softmax(model(gen_ids).logits)
   185	        topk_p = p.gather(-1, topk_idx).sum(-1)                # [B,S]
   186	    pm = topk_p.mean().item()
   187	    if not isfinite(pm): raise RuntimeError(f"NaN pmass at c={c}")
   188	    return pm
   189	
   190	def c_scan(model, lora, init_c=1.0, gate_frac=0.85, backoff=0.75,
   191	           sign: Literal[+1, -1] = +1) -> float:
   192	    """Calibrate |C|. Sign is fixed by the axis (here: +1 = "less authority,
   193	    more care"). Returned signed_C = sign * |C|; the agent never picks sign."""
   194	    baseline = pmass(model, lora, c=0.0, ...)
   195	    gate = gate_frac * baseline
   196	    trace, c = [], init_c
   197	    # ── walk DOWN until coherent ─────────────────────────────────────
   198	    for _ in range(MAX_PROBES):
   199	        pm = pmass(model, lora, c=sign * c, ...)
   200	        trace.append((c, pm))
   201	        if pm >= gate: break
   202	        c *= 0.5
   203	        if c < C_MIN: raise RuntimeError(f"c-scan: never coherent; trace={trace}")
   204	    else:
   205	        raise RuntimeError(f"c-scan: down-walk hit MAX_PROBES; trace={trace}")
   206	    # ── walk UP while still coherent ─────────────────────────────────
   207	    for _ in range(MAX_PROBES):
   208	        c_up = min(c * 1.25, C_MAX)
   209	        pm = pmass(model, lora, c=sign * c_up, ...)
   210	        trace.append((c_up, pm))
   211	        if pm < gate or c_up >= C_MAX: break
   212	        c = c_up
   213	    # ── back off, return signed ──────────────────────────────────────
   214	    final = sign * c * backoff
   215	    log_sidecar("cscan_trace", trace, final_c=final)
   216	    return final
   217	```
   218	
   219	Bounds + sign:
   220	- `C_MIN = 0.02` and `MAX_PROBES = 12` cap the walk so a broken model
   221	  fails fast with the full pmass trace instead of looping.
   222	- `sign` is fixed by the axis (here `+1` = "less deference to authority,
   223	  more care"). Persona ordering at gen time (pos = the trait to GROW)
   224	  defines which pole is `+`. The agent never picks the sign; it only
   225	  writes the positive/negative personas in the right slots.
   226	
   227	Dialogue (probe replay): three hardcoded authority probes (Petrov false
   228	alarm, Alpha-Group coup-loyalty, plus one fresh authority probe).
   229	Greedy decoding, byte-identical replay pre/post so the only thing that
   230	varies is the model's output. Written to
   231	`<round>/interview_{pre,post}.json`.
   232	
   233	---
   234	
   235	## 5. State machine + agent tools
   236	
   237	The agent (qwen3.5-9b via inspect-ai react) drives one round at a time.
   238	Per round, three states with strict ordering. Tools assert state and
   239	raise `ValidationError` if called wrong; the `on_continue` nudge tells
   240	the agent the next valid action.
   241	
   242	```py
   243	state ∈ {"propose", "curate", "judge", "done"}
   244	
   245	# state = "propose" — agent sees pre-dialogue transcript + history summary
   246	propose_personas(pos: list[str], neg: list[str]):
   247	    assert state == "propose"
   248	    pairs = gen_on_policy(model, pos, neg, N=50)
   249	    pairs, dropped = drop_double_refusals(pairs)   # auto, but REPORTED
   250	    snapshot(pairs, "bk.yaml")                     # frozen original for diff
   251	    write_interleaved_yaml(pairs, "pairs.yaml")
   252	    if len(pairs) < 20:
   253	        raise ValidationError(
   254	            f"only {len(pairs)} usable pairs after auto-drop "
   255	            f"({len(dropped)} double-refusals); rewrite personas"
   256	        )
   257	    state := "curate"
   258	    # Agent sees: pair count, dropped count + their prompt heads, and a
   259	    # compact preview (id | prompt[:60] | cho_head[:80] | rej_head[:80]).
   260	    # The full pairs.yaml lives on disk for the agent to bulk-rewrite if needed.

 succeeded in 1385ms:
     1	"""Path-loss ModulatedLoRA training with reverse-KL coherence penalty.
     2	
     3	Forked from `weight-steering-lite/src/wsl/train.py`, trimmed:
     4	- Full KL on logits (no top-K approximation). Fine for the smaller models
     5	  + smaller batches we use here; swap to top-K if memory becomes the
     6	  bottleneck.
     7	- Dropped held-out probe-eval loop (we evaluate via dialogue after train).
     8	
     9	Per (prompt, cho, rej), sampled C ∈ (0, 1]:
    10	
    11	    L_pos = C·nll(cho | c=+C)  +  β·mean_KL(steer ‖ base) on cho label tokens
    12	    L_neg = C·nll(rej | c=-C)  +  β·mean_KL(steer ‖ base) on rej label tokens
    13	
    14	Both terms in nats. β trades steering signal vs distribution shift;
    15	weight-decay + β jointly pull toward "no-op" while NLL pulls toward
    16	cho/rej.
    17	
    18	`base` is the c=0 forward = pristine base (HistoryBake gate disabled
    19	when `lora._c == 0`). So a new adapter that fights a prior bake pays
    20	its KL bill cumulatively from base, not iteratively from last bake.
    21	"""
    22	from __future__ import annotations
    23	
    24	import math
    25	from dataclasses import dataclass
    26	
    27	import torch
    28	from loguru import logger
    29	from torch.optim import AdamW
    30	from torch.utils.data import DataLoader, Dataset
    31	from transformers import get_cosine_schedule_with_warmup
    32	from tqdm.auto import tqdm
    33	
    34	from csm.adapter import ModulatedLoRA
    35	
    36	
    37	@dataclass
    38	class TrainCfg:
    39	    r: int = 16
    40	    alpha: float = 32.0
    41	    targets: tuple[str, ...] = ("all-linear",)
    42	    steps: int = 200
    43	    warmup_ratio: float = 0.1
    44	    batch_size: int = 4
    45	    lr: float = 2e-4
    46	    weight_decay: float = 0.01
    47	    grad_clip: float = 1.0
    48	    max_len: int = 512
    49	    log_every: int = 20
    50	    kl_lambda: float = 0.032
    51	    """β: coefficient on mean reverse-KL per step (nats, matches NLL units).
    52	    0 disables. Bump up if Δnll blows past +0.02 (coherence breaks); bump
    53	    down if eval Δ stays at noise."""
    54	    pcgrad: bool = True
    55	    seed: int = 42
    56	
    57	
    58	# ---------------------------------------------------------------------------
    59	# Tokenisation: prompt+completion teacher-forced; label mask = prompt -100.
    60	# Persona prefix is DROPPED at train time so the adapter learns the
    61	# behaviour conditioned only on c, not on the persona prefix.
    62	# ---------------------------------------------------------------------------
    63	
    64	def build_tokens(tok, prompt: str, completion: str, max_len: int,
    65	                 *, enable_thinking: bool = False) -> tuple[torch.Tensor, torch.Tensor]:
    66	    """(input_ids, labels) where labels mask out the prompt portion."""
    67	    prompt_text = tok.apply_chat_template(
    68	        [{"role": "user", "content": prompt}],
    69	        tokenize=False, add_generation_prompt=True,
    70	        enable_thinking=enable_thinking,
    71	    )
    72	    full_text = prompt_text + completion + tok.eos_token
    73	    prompt_ids = tok(prompt_text, add_special_tokens=False).input_ids
    74	    full_ids = tok(full_text, add_special_tokens=False).input_ids
    75	    full_ids = full_ids[:max_len]
    76	    labels = list(full_ids)
    77	    for i in range(min(len(prompt_ids), len(labels))):
    78	        labels[i] = -100
    79	    return torch.tensor(full_ids), torch.tensor(labels)
    80	
    81	
    82	def collate(batch: list[tuple[torch.Tensor, torch.Tensor]], pad_id: int):
    83	    max_len = max(b[0].shape[0] for b in batch)
    84	    input_ids = torch.full((len(batch), max_len), pad_id, dtype=torch.long)
    85	    labels = torch.full((len(batch), max_len), -100, dtype=torch.long)
    86	    attn = torch.zeros((len(batch), max_len), dtype=torch.long)
    87	    for i, (ids, lbl) in enumerate(batch):
    88	        n = ids.shape[0]
    89	        input_ids[i, :n] = ids
    90	        labels[i, :n] = lbl
    91	        attn[i, :n] = 1
    92	    return input_ids, labels, attn
    93	
    94	
    95	class PairDataset(Dataset):
    96	    def __init__(self, pairs: list[dict], tok, max_len: int,
    97	                 enable_thinking: bool = False):
    98	        self.pairs = pairs
    99	        self.tok = tok
   100	        self.max_len = max_len
   101	        self.enable_thinking = enable_thinking
   102	
   103	    def __len__(self):
   104	        return len(self.pairs)
   105	
   106	    def __getitem__(self, i):
   107	        p = self.pairs[i]
   108	        ids_p, lbl_p = build_tokens(self.tok, p["prompt"], p["cho"], self.max_len,
   109	                                    enable_thinking=self.enable_thinking)
   110	        ids_n, lbl_n = build_tokens(self.tok, p["prompt"], p["rej"], self.max_len,
   111	                                    enable_thinking=self.enable_thinking)
   112	        return (ids_p, lbl_p), (ids_n, lbl_n)
   113	
   114	
   115	def _pair_collate(batch, pad_id):
   116	    pos = [b[0] for b in batch]
   117	    neg = [b[1] for b in batch]
   118	    ip, lp, ap = collate(pos, pad_id)
   119	    in_, ln, an = collate(neg, pad_id)
   120	    return ip, lp, ap, in_, ln, an
   121	
   122	
   123	def _zerofill(grads, params):
   124	    return [g if g is not None else torch.zeros_like(p) for g, p in zip(grads, params)]
   125	
   126	
   127	def _kl_mean_full(logp_steer, logp_base, mask):
   128	    """Reverse KL(p_steer ‖ p_base), per-token, mean over `mask`. nats."""
   129	    p_s = logp_steer.exp()
   130	    kl_per_tok = (p_s * (logp_steer - logp_base)).sum(dim=-1)        # [B, S]
   131	    return kl_per_tok[mask.bool()].mean()
   132	
   133	
   134	def pcgrad_train_step(
   135	    model, lora: ModulatedLoRA,
   136	    ip, lp, ap, in_, ln, an,
   137	    params: list,
   138	    *,
   139	    C: float,
   140	    pcgrad: bool = True,
   141	    kl_lambda: float = 0.0,
   142	) -> dict:
   143	    """One step: NLL on both poles + (optional) KL anchor to c=0 forward.
   144	    PCGrad operates on the (NLL_pos, NLL_neg) gradients only — KL is
   145	    added unprojected.
   146	    """
   147	    use_kl = kl_lambda > 0
   148	    device = next(p.device for p in params)
   149	    zero = torch.zeros((), device=device)
   150	
   151	    # ---- c=0 reference forwards (no grad) ---------------------------------
   152	    if use_kl:
   153	        with torch.no_grad():
   154	            with lora(model, c=0.0):
   155	                logits_b_p = model(input_ids=ip, attention_mask=ap).logits.float()
   156	                logits_b_n = model(input_ids=in_, attention_mask=an).logits.float()
   157	            logp_b_p = torch.log_softmax(logits_b_p, dim=-1)
   158	            logp_b_n = torch.log_softmax(logits_b_n, dim=-1)
   159	
   160	    # ---- cho at c=+C ------------------------------------------------------
   161	    with lora(model, c=+C):
   162	        out_p = model(input_ids=ip, attention_mask=ap, labels=lp)
   163	        L_pos_nll = C * out_p.loss
   164	        if use_kl:
   165	            logp_p = torch.log_softmax(out_p.logits.float(), dim=-1)
   166	            kl_p = _kl_mean_full(logp_p, logp_b_p, lp != -100)
   167	            L_pos_kl = kl_lambda * kl_p
   168	    g_pos_nll = _zerofill(torch.autograd.grad(
   169	        L_pos_nll, params, retain_graph=use_kl, allow_unused=True), params)
   170	    if use_kl:
   171	        g_pos_kl = _zerofill(torch.autograd.grad(
   172	            L_pos_kl, params, retain_graph=False, allow_unused=True), params)
   173	    else:
   174	        g_pos_kl = [torch.zeros_like(p) for p in params]
   175	        kl_p = zero
   176	
   177	    # ---- rej at c=-C ------------------------------------------------------
   178	    with lora(model, c=-C):
   179	        out_n = model(input_ids=in_, attention_mask=an, labels=ln)
   180	        L_neg_nll = C * out_n.loss
   181	        if use_kl:
   182	            logp_n = torch.log_softmax(out_n.logits.float(), dim=-1)
   183	            kl_n = _kl_mean_full(logp_n, logp_b_n, ln != -100)
   184	            L_neg_kl = kl_lambda * kl_n
   185	    g_neg_nll = _zerofill(torch.autograd.grad(
   186	        L_neg_nll, params, retain_graph=use_kl, allow_unused=True), params)
   187	    if use_kl:
   188	        g_neg_kl = _zerofill(torch.autograd.grad(
   189	            L_neg_kl, params, retain_graph=False, allow_unused=True), params)
   190	    else:
   191	        g_neg_kl = [torch.zeros_like(p) for p in params]
   192	        kl_n = zero
   193	
   194	    # ---- PCGrad on the NLL pair only --------------------------------------
   195	    gp_flat = torch.cat([g.reshape(-1) for g in g_pos_nll])
   196	    gn_flat = torch.cat([g.reshape(-1) for g in g_neg_nll])
   197	    dot = (gp_flat * gn_flat).sum()
   198	    gp_norm_sq = (gp_flat * gp_flat).sum().clamp_min(1e-12)
   199	    gn_norm_sq = (gn_flat * gn_flat).sum().clamp_min(1e-12)
   200	    cos = (dot / (gp_norm_sq.sqrt() * gn_norm_sq.sqrt())).item()
   201	    conflict = dot.item() < 0
   202	
   203	    if pcgrad and conflict:
   204	        gp_proj = gp_flat - (dot / gn_norm_sq) * gn_flat
   205	        gn_proj = gn_flat - (dot / gp_norm_sq) * gp_flat
   206	        nll_summed = 0.5 * (gp_proj + gn_proj)
   207	    else:
   208	        nll_summed = 0.5 * (gp_flat + gn_flat)
   209	
   210	    if use_kl:
   211	        kl_flat = 0.5 * (
   212	            torch.cat([g.reshape(-1) for g in g_pos_kl]) +
   213	            torch.cat([g.reshape(-1) for g in g_neg_kl])
   214	        )
   215	        summed = nll_summed + kl_flat
   216	    else:
   217	        summed = nll_summed
   218	
   219	    offset = 0
   220	    for p in params:
   221	        n = p.numel()
   222	        p.grad = summed[offset:offset + n].view_as(p)
   223	        offset += n
   224	
   225	    return {
   226	        "L_pos_nll": L_pos_nll.detach().item() / max(C, 1e-12),
   227	        "L_neg_nll": L_neg_nll.detach().item() / max(C, 1e-12),
   228	        "kl_mean_pos": kl_p.detach().item() if use_kl else 0.0,
   229	        "kl_mean_neg": kl_n.detach().item() if use_kl else 0.0,
   230	        "C": C,
   231	        "conflict": conflict,
   232	        "cos": cos,
   233	    }
   234	
   235	
   236	def train_adapter(model, tok, pairs: list[dict], cfg: TrainCfg,
   237	                  *, history_bake=None, enable_thinking: bool = False) -> ModulatedLoRA:
   238	    """Fit one ModulatedLoRA on `pairs` via path-loss + KL anchor.
   239	
   240	    `history_bake`: if given, its gate is set to `lambda: lora._c != 0.0`
   241	    so the c=0 reference forward returns pristine base (cumulative-from-
   242	    base KL across rounds).
   243	    """
   244	    torch.manual_seed(cfg.seed)
   245	    lora = ModulatedLoRA(model, r=cfg.r, alpha=cfg.alpha, targets=cfg.targets,
   246	                         dtype=next(model.parameters()).dtype)
   247	    params = list(lora.parameters())
   248	    optim = AdamW(params, lr=cfg.lr, weight_decay=cfg.weight_decay)
   249	    sched = get_cosine_schedule_with_warmup(
   250	        optim,
   251	        num_warmup_steps=int(cfg.warmup_ratio * cfg.steps),
   252	        num_training_steps=cfg.steps,
   253	    )
   254	    if history_bake is not None:
   255	        history_bake.set_gate(lambda: lora._c != 0.0)
   256	
   257	    ds = PairDataset(pairs, tok, cfg.max_len, enable_thinking=enable_thinking)
   258	    pad_id = tok.pad_token_id
   259	    loader = DataLoader(
   260	        ds, batch_size=cfg.batch_size, shuffle=True,
   261	        collate_fn=lambda b: _pair_collate(b, pad_id),
   262	        drop_last=True,
   263	    )
   264	
   265	    device = next(model.parameters()).device
   266	    it = iter(loader)
   267	    pbar = tqdm(range(cfg.steps), desc="train", leave=False)
   268	    for step in pbar:
   269	        try:
   270	            batch = next(it)
   271	        except StopIteration:
   272	            it = iter(loader)
   273	            batch = next(it)
   274	        ip, lp, ap, in_, ln, an = (t.to(device) for t in batch)
   275	
   276	        C = float(torch.empty(()).uniform_(0.05, 1.0))   # bounded away from 0
   277	        trace = pcgrad_train_step(
   278	            model, lora, ip, lp, ap, in_, ln, an, params,
   279	            C=C, pcgrad=cfg.pcgrad, kl_lambda=cfg.kl_lambda,
   280	        )
   281	
   282	        torch.nn.utils.clip_grad_norm_(params, cfg.grad_clip)
   283	        optim.step()
   284	        optim.zero_grad(set_to_none=True)
   285	        sched.step()
   286	
   287	        if step % cfg.log_every == 0:
   288	            logger.info(
   289	                f"step {step:4d}/{cfg.steps}  C={trace['C']:.2f}  "
   290	                f"nll+={trace['L_pos_nll']:.3f}  nll-={trace['L_neg_nll']:.3f}  "
   291	                f"kl±={trace['kl_mean_pos']:.4f}/{trace['kl_mean_neg']:.4f}  "
   292	                f"cos={trace['cos']:+.2f}{'  CONFLICT' if trace['conflict'] else ''}"
   293	            )
   294	
   295	    if history_bake is not None:
   296	        history_bake.set_gate(lambda: True)              # restore inference default
   297	    return lora

 succeeded in 1410ms:
     1	"""Load base model + kept-round adapters composed via HistoryBake.
     2	
     3	Forked from `weight-steering-lite/src/wsl/load_with_history.py`, trimmed:
     4	- Dropped 4-bit / BitsAndBytesConfig branch.
     5	- Dropped flash-attention-2 hard requirement (set via env var if wanted).
     6	- Single happy path: bf16, device_map="auto".
     7	
     8	Round dirs whose `judgment.json.action == "keep"` count as history. The
     9	caller resolves which dirs to compose (typically: all kept rounds before
    10	this one, in order).
    11	"""
    12	from __future__ import annotations
    13	
    14	import json
    15	import os
    16	import re
    17	from pathlib import Path
    18	from typing import Iterable
    19	
    20	import torch
    21	from loguru import logger
    22	from transformers import AutoModelForCausalLM, AutoTokenizer
    23	
    24	from csm.adapter import HistoryBake, ModulatedLoRA
    25	
    26	
    27	_ROUND_RE = re.compile(r"^round(\d+)$")
    28	
    29	
    30	def parse_round_n(name: str) -> int | None:
    31	    m = _ROUND_RE.match(name)
    32	    return int(m.group(1)) if m else None
    33	
    34	
    35	def load_base_with_history(
    36	    model_id: str,
    37	    history_dirs: Iterable[Path] | None = None,
    38	    *,
    39	    dtype: torch.dtype = torch.bfloat16,
    40	    device_map: str = "auto",
    41	):
    42	    """Load base model in bf16; attach kept-round adapters as a single
    43	    `HistoryBake` (combined dW per target layer, gated forward hook).
    44	    Returns (model, tokenizer, history_bake_or_None).
    45	
    46	    Base weights stay pristine — history contributes via the hook, gated
    47	    on an external `is_active` callable. Default gate = always-on
    48	    (inference). Training code must
    49	    `history_bake.set_gate(lambda: lora._c != 0.0)` so the c=0 reference
    50	    forward returns pristine base.
    51	    """
    52	    tok = AutoTokenizer.from_pretrained(model_id)
    53	    if tok.pad_token is None:
    54	        tok.pad_token = tok.eos_token
    55	    tok.padding_side = "left"
    56	
    57	    attn_impl = os.environ.get("CSM_ATTN_IMPL", "eager")  # flash_attention_2 if installed
    58	    model = AutoModelForCausalLM.from_pretrained(
    59	        model_id,
    60	        device_map=device_map,
    61	        torch_dtype=dtype,
    62	        low_cpu_mem_usage=True,
    63	        attn_implementation=attn_impl,
    64	    )
    65	    model.eval()
    66	
    67	    history_dirs = list(history_dirs or [])
    68	    history: list[tuple[ModulatedLoRA, float]] = []
    69	    for rd in history_dirs:
    70	        adapter_path = rd / "adapter.safetensors"
    71	        cal_path = rd / "calibration.json"
    72	        if not adapter_path.exists():
    73	            raise FileNotFoundError(f"kept-round {rd.name} missing adapter.safetensors")
    74	        if not cal_path.exists():
    75	            raise FileNotFoundError(f"kept-round {rd.name} missing calibration.json")
    76	        signed_C = float(json.loads(cal_path.read_text())["signed_C"])
    77	        lora = ModulatedLoRA.from_checkpoint(model, str(adapter_path))
    78	        history.append((lora, signed_C))
    79	        logger.info(f"loaded {rd.name}/adapter @ kept c={signed_C:+.4f}")
    80	
    81	    history_bake = HistoryBake(model, history) if history else None
    82	    if history_bake is not None:
    83	        logger.info(f"loaded base + HistoryBake over {len(history)} kept adapter(s)")
    84	    return model, tok, history_bake
    85	
    86	
    87	def kept_history_dirs(slug_dir: Path, before_round: int | None = None) -> list[Path]:
    88	    """Sorted list of `<slug_dir>/roundNN` paths whose judgment.action == 'keep'.
    89	    If `before_round` is given, only include rounds with index < before_round.
    90	    """
    91	    keep = []
    92	    for rd in sorted(p for p in slug_dir.glob("round*") if p.is_dir()):
    93	        n = parse_round_n(rd.name)
    94	        if n is None:
    95	            continue
    96	        if before_round is not None and n >= before_round:
    97	            continue
    98	        j = rd / "judgment.json"
    99	        if j.exists() and json.loads(j.read_text()).get("action") == "keep":
   100	            keep.append(rd)
   101	    return keep

 succeeded in 1421ms:
     1	"""ModulatedLoRA: one LoRA adapter with a scalar coefficient `c`.
     2	
     3	Forked from `weight-steering-lite/src/wsl/adapter.py`, trimmed:
     4	- Dropped `layer_range` (depth band) — apply to all matching layers.
     5	- Dropped 4-bit / bnb branch.
     6	- Kept `HistoryBake` for round composition.
     7	
     8	Training optimises the adapter so that `c=+1` reproduces chosen behaviour
     9	and `c=-1` reproduces rejected behaviour on the same prompt. At eval
    10	time `c` interpolates: `c=0` -> identical to base, `c=±1` -> trained
    11	extremes.
    12	
    13	Math (per target Linear with weight W : d_out × d_in):
    14	    h     = W x
    15	    delta = (alpha / r) * B @ A @ x       # A: r×d_in, B: d_out×r
    16	    y     = h + c * delta                  # c=0 → exact base
    17	
    18	Init: A ~ kaiming_uniform, B ~ N(1e-4, 1e-4). The tiny nonzero B breaks
    19	sign-symmetry between +c and -c poles at init (loss is even in c at
    20	B=0), giving the optimiser a signed gradient to follow.
    21	"""
    22	from __future__ import annotations
    23	
    24	import re
    25	from contextlib import contextmanager
    26	from dataclasses import dataclass
    27	
    28	import torch
    29	from einops import einsum
    30	from jaxtyping import Float
    31	from loguru import logger
    32	from torch import Tensor, nn
    33	
    34	
    35	@dataclass
    36	class LoRAConfig:
    37	    r: int = 16
    38	    alpha: float = 32.0
    39	    # "all-linear" = every nn.Linear minus exclusions (PEFT default).
    40	    # Otherwise: regex substrings matched against module names.
    41	    targets: tuple[str, ...] = ("all-linear",)
    42	    exclude: tuple[str, ...] = ("vision_tower", "lm_head")
    43	    dtype: torch.dtype = torch.bfloat16
    44	
    45	
    46	def _match(name: str, patterns: tuple[str, ...]) -> bool:
    47	    return any(re.search(p, name) for p in patterns)
    48	
    49	
    50	def _find_targets(model: nn.Module, cfg: LoRAConfig) -> list[tuple[str, nn.Linear]]:
    51	    all_linear = "all-linear" in cfg.targets
    52	    out = [
    53	        (name, m) for name, m in model.named_modules()
    54	        if isinstance(m, nn.Linear)
    55	        and (all_linear or _match(name, cfg.targets))
    56	        and not _match(name, cfg.exclude)
    57	    ]
    58	    if not out:
    59	        raise RuntimeError(f"no targets matched {cfg.targets!r} (excluded {cfg.exclude!r})")
    60	    return out
    61	
    62	
    63	class ModulatedLoRA:
    64	    """Hook-based LoRA with scalar coefficient `c`.
    65	
    66	    Not an nn.Module: `__call__` is repurposed as a context manager for
    67	    `with lora(model, c=...):` syntax. Params live in `self.A` / `self.B`;
    68	    use `lora.parameters()` for the optimiser.
    69	    """
    70	
    71	    def __init__(self, model: nn.Module, r: int = 16, alpha: float = 32.0,
    72	                 targets: tuple[str, ...] = ("all-linear",),
    73	                 dtype: torch.dtype = torch.bfloat16):
    74	        self.cfg = LoRAConfig(r=r, alpha=alpha, targets=targets, dtype=dtype)
    75	        self._handles: list = []
    76	        self._c: float = 0.0
    77	        self._attached: bool = False
    78	
    79	        device = next(model.parameters()).device
    80	        targets_found = _find_targets(model, self.cfg)
    81	        self.A: dict[str, nn.Parameter] = {}
    82	        self.B: dict[str, nn.Parameter] = {}
    83	        self._target_layers: dict[str, nn.Linear] = {}
    84	        for name, layer in targets_found:
    85	            d_in, d_out = layer.in_features, layer.out_features
    86	            A = torch.empty(self.cfg.r, d_in, dtype=self.cfg.dtype, device=device)
    87	            nn.init.kaiming_uniform_(A, a=5 ** 0.5)
    88	            B = torch.empty(d_out, self.cfg.r, dtype=self.cfg.dtype, device=device)
    89	            nn.init.normal_(B, mean=1e-4, std=1e-4)
    90	            self.A[name] = nn.Parameter(A)
    91	            self.B[name] = nn.Parameter(B)
    92	            self._target_layers[name] = layer
    93	
    94	        for p in model.parameters():
    95	            p.requires_grad_(False)
    96	        n_train = sum(p.numel() for p in self.parameters())
    97	        logger.debug(f"ModulatedLoRA: {len(targets_found)} targets, r={self.cfg.r}, "
    98	                     f"trainable={n_train:,}")
    99	
   100	    def parameters(self):
   101	        for p in self.A.values():
   102	            yield p
   103	        for p in self.B.values():
   104	            yield p
   105	
   106	    def _make_hook(self, name: str):
   107	        scale = self.cfg.alpha / self.cfg.r
   108	        A: Float[Tensor, "r i"] = self.A[name]
   109	        B: Float[Tensor, "o r"] = self.B[name]
   110	
   111	        def hook(layer: nn.Linear, args, y: Tensor) -> Tensor:
   112	            if self._c == 0.0:
   113	                return y                              # short-circuit
   114	            (x,) = args
   115	            x_cast = x.to(A.dtype)
   116	            h = einsum(x_cast, A, "... i, r i -> ... r")
   117	            delta = einsum(h, B, "... r, o r -> ... o")
   118	            return y + (self._c * scale) * delta.to(y.dtype)
   119	
   120	        return hook
   121	
   122	    @contextmanager
   123	    def __call__(self, model: nn.Module, c: float = 1.0):
   124	        """`with lora(model):` -> c=+1. `with lora(model, c=...):` -> custom.
   125	
   126	        Hooks registered on enter, removed on exit. Re-entry rejected: exit
   127	        the outer block first.
   128	        """
   129	        if self._attached:
   130	            raise RuntimeError("ModulatedLoRA already attached; exit outer `with` first")
   131	        self._c = float(c)
   132	        for name, layer in self._target_layers.items():
   133	            self._handles.append(layer.register_forward_hook(self._make_hook(name)))
   134	        self._attached = True
   135	        try:
   136	            yield self
   137	        finally:
   138	            for h in self._handles:
   139	                h.remove()
   140	            self._handles.clear()
   141	            self._attached = False
   142	            self._c = 0.0
   143	
   144	    def set_coeff(self, c: float) -> None:
   145	        self._c = float(c)
   146	
   147	    @property
   148	    def c(self) -> float:
   149	        return self._c
   150	
   151	    # ---- save / load -------------------------------------------------------
   152	
   153	    def save(self, path: str, extra_meta: dict[str, str] | None = None) -> None:
   154	        from safetensors.torch import save_file
   155	        sd = {f"A.{k.replace('.', '__')}": v.detach().cpu() for k, v in self.A.items()}
   156	        sd.update({f"B.{k.replace('.', '__')}": v.detach().cpu() for k, v in self.B.items()})
   157	        meta = {"r": str(self.cfg.r), "alpha": str(self.cfg.alpha),
   158	                "targets": ",".join(self.cfg.targets)}
   159	        if extra_meta:
   160	            meta.update(extra_meta)
   161	        save_file(sd, path, metadata=meta)
   162	
   163	    def load(self, path: str) -> None:
   164	        from safetensors.torch import load_file
   165	        sd = load_file(path, device="cpu")
   166	        ckpt_keys = {k[2:].replace("__", ".") for k in sd if k.startswith("A.")}
   167	        init_keys = set(self.A.keys())
   168	        if ckpt_keys != init_keys:
   169	            raise RuntimeError(
   170	                f"adapter target mismatch: checkpoint has {len(ckpt_keys)} targets, "
   171	                f"init created {len(init_keys)}; would drop {len(ckpt_keys - init_keys)} "
   172	                f"trained matrices and leave {len(init_keys - ckpt_keys)} init slots empty."
   173	            )
   174	        for k in self.A:
   175	            kk = k.replace(".", "__")
   176	            self.A[k].data.copy_(sd[f"A.{kk}"].to(self.A[k].device, self.A[k].dtype))
   177	            self.B[k].data.copy_(sd[f"B.{kk}"].to(self.B[k].device, self.B[k].dtype))
   178	
   179	    @classmethod
   180	    def from_checkpoint(cls, model: nn.Module, path: str) -> "ModulatedLoRA":
   181	        from safetensors import safe_open
   182	        with safe_open(path, framework="pt") as f:
   183	            meta = f.metadata()
   184	        targets = tuple(meta["targets"].split(","))
   185	        lora = cls(model, r=int(meta["r"]), alpha=float(meta["alpha"]),
   186	                   targets=targets, dtype=next(model.parameters()).dtype)
   187	        lora.load(path)
   188	        return lora
   189	
   190	
   191	# ---------------------------------------------------------------------------
   192	# HistoryBake — kept adapters compose via a single gated forward hook.
   193	# Storage: per-target concat A_cat = [A_1; A_2; …], B_cat = [s_1·B_1, …]
   194	# so dW_combined = B_cat @ A_cat exactly, computed without materialising dW.
   195	# Gate predicate set by training code: `lambda: lora._c != 0.0` makes the
   196	# c=0 reference forward return pristine base.
   197	# ---------------------------------------------------------------------------
   198	
   199	class HistoryBake:
   200	    def __init__(self, model: nn.Module, history: list[tuple["ModulatedLoRA", float]]):
   201	        self._is_active = lambda: True       # inference default; train code overrides
   202	        target_layers: dict[str, nn.Linear] = {}
   203	        for lora, _ in history:
   204	            for name, layer in lora._target_layers.items():
   205	                target_layers.setdefault(name, layer)
   206	        self._target_layers = target_layers
   207	
   208	        r0 = history[0][0].cfg.r
   209	        for lora, _ in history[1:]:
   210	            assert lora.cfg.r == r0, f"kept-history rank mismatch: {lora.cfg.r} vs {r0}"
   211	        target_dtype = history[0][0].cfg.dtype
   212	
   213	        with torch.no_grad():
   214	            A_cat: dict[str, Tensor] = {}
   215	            B_cat: dict[str, Tensor] = {}
   216	            for name, layer in target_layers.items():
   217	                A_parts, B_parts = [], []
   218	                for lora, c in history:
   219	                    if name not in lora.A:
   220	                        continue
   221	                    s = c * lora.cfg.alpha / lora.cfg.r
   222	                    A_parts.append(lora.A[name].to(target_dtype))
   223	                    B_parts.append((s * lora.B[name]).to(target_dtype))
   224	                A_cat[name] = torch.cat(A_parts, dim=0).to(layer.weight.device).detach()
   225	                B_cat[name] = torch.cat(B_parts, dim=1).to(layer.weight.device).detach()
   226	        self._A_cat = A_cat
   227	        self._B_cat = B_cat
   228	
   229	        self._handles = []
   230	        for name, layer in target_layers.items():
   231	            self._handles.append(layer.register_forward_hook(self._make_hook(name)))
   232	        Nr = len(history) * r0
   233	        logger.info(f"HistoryBake: {len(history)} kept adapter(s), r_total={Nr}")
   234	
   235	    def _make_hook(self, name: str):
   236	        A = self._A_cat[name]
   237	        B = self._B_cat[name]
   238	
   239	        def hook(layer: nn.Linear, args, y: Tensor) -> Tensor:
   240	            if not self._is_active():
   241	                return y
   242	            (x,) = args
   243	            x_cast = x.to(A.dtype)
   244	            h = einsum(x_cast, A, "... i, k i -> ... k")
   245	            delta = einsum(h, B, "... k, o k -> ... o")
   246	            return y + delta.to(y.dtype)
   247	
   248	        return hook
   249	
   250	    def set_gate(self, is_active) -> None:
   251	        """is_active() -> bool. Training: `set_gate(lambda: lora._c != 0.0)`."""
   252	        self._is_active = is_active
   253	
   254	    def remove(self) -> None:
   255	        for h in self._handles:
   256	            h.remove()
   257	        self._handles.clear()

exec
/usr/bin/zsh -lc "nl -ba src/csm/c_scan.py | sed -n '1,340p'" in /workspace/w2schar-mini
exec
/usr/bin/zsh -lc "nl -ba src/csm/pipeline.py | sed -n '1,320p'" in /workspace/w2schar-mini
exec
/usr/bin/zsh -lc "nl -ba src/csm/state.py | sed -n '1,300p'" in /workspace/w2schar-mini
exec
/usr/bin/zsh -lc "nl -ba src/csm/agent.py | sed -n '1,420p'" in /workspace/w2schar-mini
 succeeded in 1405ms:
     1	"""C-scan v2: largest |C| where pmass(c) ≥ gate_frac × baseline, ×0.75 backoff.
     2	
     3	pmass proxy (no tinymfv): mean P assigned by steered model to the
     4	*base+history*'s top-K tokens at each generated position. Coherent
     5	steered → mass stays near base; collapsed steered → mass leaks to weird
     6	tokens.
     7	
     8	The c=0 baseline is base+history (inference context — gate always on).
     9	The sign of `signed_C` is fixed by axis (+1 = "less authority"); the
    10	agent never picks sign.
    11	"""
    12	from __future__ import annotations
    13	
    14	import math
    15	from typing import Literal
    16	
    17	import torch
    18	from loguru import logger
    19	
    20	from csm.adapter import ModulatedLoRA
    21	
    22	
    23	C_MIN, C_MAX, MAX_PROBES = 0.02, 1.0, 12
    24	
    25	
    26	@torch.no_grad()
    27	def pmass(model, tok, lora: ModulatedLoRA, c: float, probes: list[str], *,
    28	          k: int = 200, n_gen: int = 32, batch_size: int = 2) -> float:
    29	    """Top-K coherence proxy. 1) generate at c=0 (base+history), record top-K
    30	    indices per position. 2) re-score the SAME generated sequence at c=c,
    31	    gather P over those indices, mean over positions."""
    32	    old_side = tok.padding_side
    33	    tok.padding_side = "left"
    34	    pms: list[float] = []
    35	    try:
    36	        for i in range(0, len(probes), batch_size):
    37	            batch = probes[i: i + batch_size]
    38	            enc = tok(batch, return_tensors="pt", padding=True).to(model.device)
    39	            in_len = enc["input_ids"].shape[1]
    40	
    41	            # 1) generate at c=0 and record base+history top-K per position
    42	            with lora(model, c=0.0):
    43	                gen = model.generate(
    44	                    **enc, max_new_tokens=n_gen, do_sample=False,
    45	                    pad_token_id=tok.pad_token_id or tok.eos_token_id,
    46	                    eos_token_id=tok.eos_token_id,
    47	                )
    48	                logits_b = model(input_ids=gen).logits
    49	                # only the generated-token positions
    50	                gen_pos = slice(in_len - 1, gen.shape[1] - 1)
    51	                base_topk = logits_b[:, gen_pos].topk(k, dim=-1).indices  # [B, n_gen, k]
    52	
    53	            # 2) re-score same sequence at c=c, gather over base topK
    54	            with lora(model, c=c):
    55	                logits_s = model(input_ids=gen).logits[:, gen_pos]
    56	                p_s = torch.softmax(logits_s.float(), dim=-1)
    57	                topk_p = p_s.gather(-1, base_topk).sum(-1)                # [B, n_gen]
    58	
    59	            # mask out positions past EOS (no signal)
    60	            attn = (gen != (tok.pad_token_id or tok.eos_token_id))[:, in_len:]
    61	            attn = attn[:, :topk_p.shape[1]]
    62	            if attn.any():
    63	                pms.append(topk_p[attn].mean().item())
    64	            else:
    65	                pms.append(topk_p.mean().item())
    66	    finally:
    67	        tok.padding_side = old_side
    68	    pm = sum(pms) / max(len(pms), 1)
    69	    if not math.isfinite(pm):
    70	        raise RuntimeError(f"NaN pmass at c={c}")
    71	    return pm
    72	
    73	
    74	def c_scan(model, tok, lora: ModulatedLoRA, probes: list[str], *,
    75	           init_c: float = 1.0,
    76	           gate_frac: float = 0.85,
    77	           backoff: float = 0.75,
    78	           sign: Literal[1, -1] = 1,
    79	           k: int = 200, n_gen: int = 32,
    80	           batch_size: int = 2) -> tuple[float, list]:
    81	    """Walk |C| until pmass < gate, then walk back up while still coherent,
    82	    back off 25%. Returns (signed_C, trace)."""
    83	    baseline = pmass(model, tok, lora, c=0.0, probes=probes,
    84	                     k=k, n_gen=n_gen, batch_size=batch_size)
    85	    gate = gate_frac * baseline
    86	    logger.info(f"c_scan: baseline pmass={baseline:.3f}, gate={gate:.3f}")
    87	    trace = [("baseline", 0.0, baseline)]
    88	
    89	    # ── walk DOWN until coherent ────────────────────────────────────────
    90	    c = init_c
    91	    for _ in range(MAX_PROBES):
    92	        pm = pmass(model, tok, lora, c=sign * c, probes=probes,
    93	                   k=k, n_gen=n_gen, batch_size=batch_size)
    94	        trace.append(("down", c, pm))
    95	        logger.info(f"c_scan down  c={sign*c:+.3f}  pmass={pm:.3f}")
    96	        if pm >= gate:
    97	            break
    98	        c *= 0.5
    99	        if c < C_MIN:
   100	            raise RuntimeError(f"c_scan: never coherent (c<{C_MIN}); trace={trace}")
   101	    else:
   102	        raise RuntimeError(f"c_scan: down-walk MAX_PROBES; trace={trace}")
   103	
   104	    # ── walk UP while still coherent ────────────────────────────────────
   105	    for _ in range(MAX_PROBES):
   106	        c_up = min(c * 1.25, C_MAX)
   107	        if c_up <= c:
   108	            break  # hit C_MAX, can't go further
   109	        pm = pmass(model, tok, lora, c=sign * c_up, probes=probes,
   110	                   k=k, n_gen=n_gen, batch_size=batch_size)
   111	        trace.append(("up", c_up, pm))
   112	        logger.info(f"c_scan up    c={sign*c_up:+.3f}  pmass={pm:.3f}")
   113	        if pm < gate:
   114	            break
   115	        c = c_up
   116	
   117	    final = sign * c * backoff
   118	    trace.append(("final", abs(final), final))
   119	    logger.info(f"c_scan final: signed_C={final:+.4f} (|c|={c:.3f} × backoff={backoff})")
   120	    return final, trace

 succeeded in 1415ms:
     1	"""Per-round orchestration: pre-dialogue → propose → curate → train → judge.
     2	
     3	Each agent-callable verb (propose_personas / edit_pairs / train / judge)
     4	delegates to one of these functions. Pipeline writes all artifacts and
     5	mutates the round's state.json transparently.
     6	
     7	Artifacts per round (`<slug>/round<NN>/`):
     8	  state.json          — current state (propose|curate|judge|done)
     9	  spec.json           — pos/neg personas + axis label
    10	  pairs.yaml          — current pair set (agent-editable)
    11	  pairs.bk.yaml       — frozen snapshot just after auto-drop
    12	  dropped.json        — list of pairs auto-dropped at gen time
    13	  adapter.safetensors — trained adapter
    14	  calibration.json    — signed_C + c_scan trace
    15	  interview_pre.json  — probes replayed at c=0 (base+history)
    16	  interview_post.json — probes replayed at signed_C
    17	  judgment.json       — agent's keep/drop + reason
    18	"""
    19	from __future__ import annotations
    20	
    21	import gc
    22	import json
    23	from dataclasses import asdict
    24	from datetime import datetime, timezone
    25	from pathlib import Path
    26	
    27	import torch
    28	from loguru import logger
    29	
    30	from csm.adapter import ModulatedLoRA
    31	from csm.c_scan import c_scan
    32	from csm.config import RunConfig, config_by_model
    33	from csm.dialogue import dialogue, DialogueCfg
    34	from csm.gen import gen_pairs, write_pairs_yaml, load_pairs_yaml
    35	from csm.history import kept_history_dirs, load_base_with_history
    36	from csm.probes import PROBES
    37	from csm.state import (RoundState, advance, read_state, require_state,
    38	                       write_state)
    39	from csm.train import TrainCfg, train_adapter
    40	
    41	AXIS = "less deference to authority"          # fixed for this repo
    42	SIGN = +1                                     # +C = more "less authority"
    43	
    44	
    45	# ---------------------------------------------------------------------------
    46	# Per-slug bootstrap
    47	# ---------------------------------------------------------------------------
    48	
    49	def init_run(slug_dir: Path, model: str, teacher: str | None = None) -> Path:
    50	    """Create slug dir + run.json + round00/state.json=propose."""
    51	    slug_dir.mkdir(parents=True, exist_ok=True)
    52	    run = {
    53	        "model": model,
    54	        "teacher": teacher or config_by_model(model).teacher,
    55	        "axis": AXIS,
    56	        "created_utc": datetime.now(timezone.utc).isoformat(),
    57	    }
    58	    (slug_dir / "run.json").write_text(json.dumps(run, indent=2))
    59	    round_dir = slug_dir / "round00"
    60	    round_dir.mkdir(exist_ok=True)
    61	    if not (round_dir / "state.json").exists():
    62	        write_state(round_dir, RoundState(state="propose"))
    63	    return round_dir
    64	
    65	
    66	def latest_round_dir(slug_dir: Path) -> Path:
    67	    rounds = sorted(p for p in slug_dir.glob("round*") if p.is_dir())
    68	    if not rounds:
    69	        raise FileNotFoundError(f"no round* under {slug_dir}")
    70	    return rounds[-1]
    71	
    72	
    73	def new_round_dir(slug_dir: Path) -> Path:
    74	    """Allocate the next roundNN under slug_dir, scaffold state.json."""
    75	    existing = sorted(p.name for p in slug_dir.glob("round*") if p.is_dir())
    76	    n = 0
    77	    if existing:
    78	        last = existing[-1]
    79	        n = int(last.replace("round", "")) + 1
    80	    rd = slug_dir / f"round{n:02d}"
    81	    rd.mkdir(exist_ok=True)
    82	    write_state(rd, RoundState(state="propose"))
    83	    return rd
    84	
    85	
    86	# ---------------------------------------------------------------------------
    87	# Pre-dialogue (run once per round before propose).
    88	# ---------------------------------------------------------------------------
    89	
    90	def run_pre_dialogue(slug_dir: Path, round_dir: Path) -> dict:
    91	    """Replay probes at c=0 (base + kept history). Idempotent."""
    92	    out = round_dir / "interview_pre.json"
    93	    if out.exists():
    94	        return json.loads(out.read_text())
    95	    run = json.loads((slug_dir / "run.json").read_text())
    96	    cfg = config_by_model(run["model"])
    97	    history = kept_history_dirs(slug_dir, before_round=int(round_dir.name.replace("round", "")))
    98	    model, tok, _ = load_base_with_history(cfg.model, history)
    99	    dcfg = DialogueCfg(max_new_tokens=cfg.dialogue_max_new_tokens,
   100	                       enable_thinking=cfg.enable_thinking)
   101	    payload = dialogue(model, tok, PROBES, out, lora=None, c=0.0, cfg=dcfg)
   102	    del model
   103	    gc.collect()
   104	    if torch.cuda.is_available():
   105	        torch.cuda.empty_cache()
   106	    return payload
   107	
   108	
   109	# ---------------------------------------------------------------------------
   110	# Verb 1: propose_personas
   111	# ---------------------------------------------------------------------------
   112	
   113	def propose(slug_dir: Path, round_dir: Path, pos_persona: str, neg_persona: str) -> dict:
   114	    require_state(round_dir, "propose", "propose_personas")
   115	    run = json.loads((slug_dir / "run.json").read_text())
   116	    cfg = config_by_model(run["model"])
   117	
   118	    spec = {
   119	        "axis": AXIS,
   120	        "pos_persona": pos_persona,
   121	        "neg_persona": neg_persona,
   122	        "sign": SIGN,
   123	        "ts_utc": datetime.now(timezone.utc).isoformat(),
   124	    }
   125	    (round_dir / "spec.json").write_text(json.dumps(spec, indent=2))
   126	
   127	    history = kept_history_dirs(slug_dir, before_round=int(round_dir.name.replace("round", "")))
   128	    model, tok, _ = load_base_with_history(cfg.model, history)
   129	    alive, dropped = gen_pairs(
   130	        model, tok, pos_persona, neg_persona,
   131	        n_pairs=cfg.n_pairs, batch_size=cfg.gen_batch_size,
   132	        max_new_tokens=cfg.max_new_tokens, enable_thinking=cfg.enable_thinking,
   133	    )
   134	    del model
   135	    gc.collect()
   136	    if torch.cuda.is_available():
   137	        torch.cuda.empty_cache()
   138	
   139	    write_pairs_yaml(round_dir / "pairs.yaml", alive)
   140	    write_pairs_yaml(round_dir / "pairs.bk.yaml", alive)
   141	    (round_dir / "dropped.json").write_text(json.dumps(dropped, indent=2))
   142	
   143	    min_alive = max(2, cfg.n_pairs // 4)     # scales with n_pairs so smoke (n=4) passes
   144	    if len(alive) < min_alive:
   145	        raise RuntimeError(
   146	            f"propose_personas: only {len(alive)} pairs alive after auto-drop "
   147	            f"({len(dropped)} double-refusals); need >= {min_alive}. "
   148	            f"Rewrite personas."
   149	        )
   150	
   151	    advance(round_dir, note=f"alive={len(alive)} dropped={len(dropped)}")
   152	    return {
   153	        "n_alive": len(alive),
   154	        "n_dropped": len(dropped),
   155	        "dropped_ids": [d["id"] for d in dropped],
   156	        "preview": _compact_preview(alive, n_max=6),
   157	    }
   158	
   159	
   160	def _compact_preview(pairs: list[dict], n_max: int = 6) -> list[dict]:
   161	    return [
   162	        {"id": p["id"],
   163	         "prompt": (p["prompt"][:80] + "…") if len(p["prompt"]) > 80 else p["prompt"],
   164	         "cho_head": (p["cho"].strip()[:120].replace("\n", " ⏎ ")),
   165	         "rej_head": (p["rej"].strip()[:120].replace("\n", " ⏎ "))}
   166	        for p in pairs[:n_max]
   167	    ]
   168	
   169	
   170	# ---------------------------------------------------------------------------
   171	# Verb 2: edit_pairs — bulk rewrite of pairs.yaml
   172	# ---------------------------------------------------------------------------
   173	
   174	def edit(round_dir: Path, new_yaml_text: str) -> dict:
   175	    require_state(round_dir, "curate", "edit_pairs")
   176	    import yaml
   177	    pairs = yaml.safe_load(new_yaml_text)
   178	    if not isinstance(pairs, list):
   179	        raise ValueError("edit_pairs: top-level YAML must be a list of pairs")
   180	    for i, row in enumerate(pairs):
   181	        if row is None:
   182	            continue
   183	        for k in ("id", "prompt", "cho", "rej"):
   184	            if k not in row:
   185	                raise ValueError(f"edit_pairs: pair {i} missing key {k!r}; got {list(row)}")
   186	    pairs = [r for r in pairs if r is not None]
   187	    # Renumber to contiguous range so the agent's index references stay stable.
   188	    for new_id, r in enumerate(pairs):
   189	        r["id"] = new_id
   190	    write_pairs_yaml(round_dir / "pairs.yaml", pairs)
   191	    bk = load_pairs_yaml(round_dir / "pairs.bk.yaml")
   192	    return {"n_alive": len(pairs), "n_original": len(bk),
   193	            "n_changed_vs_bk": _count_changed(pairs, bk)}
   194	
   195	
   196	def _count_changed(cur: list[dict], orig: list[dict]) -> int:
   197	    by_prompt = {p["prompt"]: p for p in orig}
   198	    n = 0
   199	    for r in cur:
   200	        o = by_prompt.get(r["prompt"])
   201	        if o is None or o.get("cho") != r["cho"] or o.get("rej") != r["rej"]:
   202	            n += 1
   203	    return n
   204	
   205	
   206	# ---------------------------------------------------------------------------
   207	# Verb 3: train (also runs c_scan + post-dialogue).
   208	# ---------------------------------------------------------------------------
   209	
   210	def train_and_eval(slug_dir: Path, round_dir: Path) -> dict:
   211	    require_state(round_dir, "curate", "train")
   212	    run = json.loads((slug_dir / "run.json").read_text())
   213	    cfg = config_by_model(run["model"])
   214	
   215	    pairs = load_pairs_yaml(round_dir / "pairs.yaml")
   216	    if not pairs:
   217	        raise RuntimeError("train: pairs.yaml is empty")
   218	
   219	    history = kept_history_dirs(slug_dir, before_round=int(round_dir.name.replace("round", "")))
   220	    model, tok, hb = load_base_with_history(cfg.model, history)
   221	
   222	    steps = max(20, int(len(pairs) / cfg.train_batch_size * cfg.n_epochs))
   223	    tcfg = TrainCfg(
   224	        r=cfg.lora_r, alpha=cfg.lora_alpha, targets=cfg.targets,
   225	        steps=steps, batch_size=cfg.train_batch_size, lr=cfg.lr,
   226	        max_len=cfg.max_len, kl_lambda=cfg.kl_lambda,
   227	    )
   228	    lora = train_adapter(model, tok, pairs, tcfg,
   229	                         history_bake=hb, enable_thinking=cfg.enable_thinking)
   230	
   231	    # ── C-scan ─────────────────────────────────────────────────────────
   232	    probe_prompts = [p["opening"] for p in PROBES]
   233	    signed_C, trace = c_scan(
   234	        model, tok, lora, probe_prompts,
   235	        init_c=1.0, sign=SIGN, n_gen=cfg.cscan_n_gen, k=cfg.cscan_k,
   236	        batch_size=cfg.eval_batch_size,
   237	    )
   238	
   239	    lora.save(str(round_dir / "adapter.safetensors"),
   240	              extra_meta={"axis": AXIS, "sign": str(SIGN)})
   241	    (round_dir / "calibration.json").write_text(json.dumps({
   242	        "signed_C": signed_C,
   243	        "sign": SIGN,
   244	        "cscan_trace": trace,
   245	        "kl_lambda": tcfg.kl_lambda,
   246	        "steps": tcfg.steps,
   247	    }, indent=2))
   248	
   249	    # ── post-dialogue under adapter @ signed_C ──────────────────────────
   250	    dcfg = DialogueCfg(max_new_tokens=cfg.dialogue_max_new_tokens,
   251	                       enable_thinking=cfg.enable_thinking)
   252	    post = dialogue(model, tok, PROBES,
   253	                    round_dir / "interview_post.json",
   254	                    lora=lora, c=signed_C, cfg=dcfg)
   255	
   256	    del model, lora
   257	    gc.collect()
   258	    if torch.cuda.is_available():
   259	        torch.cuda.empty_cache()
   260	
   261	    advance(round_dir, note=f"signed_C={signed_C:+.4f}")
   262	    return {
   263	        "signed_C": signed_C,
   264	        "n_probes_post": len(post["probes"]),
   265	    }
   266	
   267	
   268	# ---------------------------------------------------------------------------
   269	# Verb 4: judge
   270	# ---------------------------------------------------------------------------
   271	
   272	def judge(round_dir: Path, keep: bool, reason: str) -> dict:
   273	    require_state(round_dir, "judge", "judge")
   274	    judgment = {
   275	        "action": "keep" if keep else "drop",
   276	        "reasoning": reason,
   277	        "ts_utc": datetime.now(timezone.utc).isoformat(),
   278	    }
   279	    (round_dir / "judgment.json").write_text(json.dumps(judgment, indent=2))
   280	    advance(round_dir, note=judgment["action"])
   281	    return judgment

 succeeded in 1405ms:
     1	"""inspect-ai react driver + 4 typed tools.
     2	
     3	Trimmed distillation of `weight-steering-lite/scripts/agent_driver_inspect.py`
     4	(972 → ~230 lines). Dropped: OpenRouter retry monkeypatch, compaction
     5	strategy, exit-interview tool, ad-hoc local_bash, multi-profile registry
     6	in the driver itself.
     7	
     8	The 4 tools all delegate to `csm.pipeline.*` and bubble any
     9	`csm.state.ValidationError` to the agent so it can correct its tool
    10	order.
    11	"""
    12	from __future__ import annotations
    13	
    14	import json
    15	import os
    16	import sys
    17	from datetime import datetime, timezone
    18	from pathlib import Path
    19	
    20	from inspect_ai import Task, eval as inspect_eval
    21	from inspect_ai.agent import AgentState, react
    22	from inspect_ai.dataset import Sample
    23	from inspect_ai.model import ChatMessageUser
    24	from inspect_ai.solver import Generate, Solver, TaskState, solver
    25	from inspect_ai.tool import Tool, tool
    26	from loguru import logger
    27	
    28	from csm.history import kept_history_dirs
    29	from csm.pipeline import (
    30	    edit, init_run, judge, latest_round_dir, new_round_dir, propose,
    31	    run_pre_dialogue, train_and_eval,
    32	)
    33	from csm.prompts import INITIAL_TASK, ON_CONTINUE_NUDGE, REACT_PROMPT
    34	from csm.state import ALLOWED_AFTER, ValidationError, read_state
    35	
    36	
    37	REPO = Path(__file__).resolve().parents[2]
    38	
    39	
    40	def _slug_path(slug: str | Path) -> Path:
    41	    p = Path(slug)
    42	    return p if p.is_absolute() else (REPO / p)
    43	
    44	
    45	def _format_validation_error(e: ValidationError) -> str:
    46	    """Tool-error string the agent will receive. Front-load the next action."""
    47	    return f"ValidationError: {e}"
    48	
    49	
    50	# ---------------------------------------------------------------------------
    51	# Tools
    52	# ---------------------------------------------------------------------------
    53	
    54	@tool(name="propose_personas", parallel=False)
    55	def propose_personas_tool(slug: str) -> Tool:
    56	    async def execute(pos_persona: str, neg_persona: str) -> str:
    57	        """Write the round's persona pair and generate 50 on-policy pairs.
    58	
    59	        Each persona = single-clause sentence in the same scaffold; flip
    60	        only the axis word(s). Positive = trait to grow ("less deference
    61	        to authority"); negative = the failure mode.
    62	
    63	        Args:
    64	            pos_persona: e.g. "You are someone who refuses unlawful or
    65	                harmful orders, even from authority figures."
    66	            neg_persona: e.g. "You are someone who obeys orders from
    67	                authority figures even when others get hurt."
    68	        """
    69	        round_dir = latest_round_dir(_slug_path(slug))
    70	        try:
    71	            res = propose(_slug_path(slug), round_dir, pos_persona, neg_persona)
    72	        except ValidationError as e:
    73	            return _format_validation_error(e)
    74	        # Return only what the agent needs to read: counts + compact preview.
    75	        preview_lines = "\n".join(
    76	            f"  - id={p['id']} prompt={p['prompt']!r}\n"
    77	            f"      cho_head: {p['cho_head']}\n"
    78	            f"      rej_head: {p['rej_head']}"
    79	            for p in res["preview"]
    80	        )
    81	        return (
    82	            f"propose_personas OK\n"
    83	            f"  alive: {res['n_alive']}    dropped (both refused): "
    84	            f"{res['n_dropped']}  dropped_ids: {res['dropped_ids']}\n"
    85	            f"  pairs.yaml: {round_dir / 'pairs.yaml'}\n"
    86	            f"preview ({len(res['preview'])} of {res['n_alive']}):\n"
    87	            f"{preview_lines}\n\n"
    88	            f"next: optionally call edit_pairs(new_yaml=...) to clean any "
    89	            f"broken pairs, then call train()."
    90	        )
    91	
    92	    return execute
    93	
    94	
    95	@tool(name="edit_pairs", parallel=False)
    96	def edit_pairs_tool(slug: str) -> Tool:
    97	    async def execute(new_yaml: str) -> str:
    98	        """Bulk-rewrite pairs.yaml.
    99	
   100	        Pass the FULL new YAML as a string. Format: list of
   101	        `{id, prompt, cho, rej}` blocks (cho/rej side-by-side). Block
   102	        scalars (`|`) for multi-line. IDs are auto-renumbered after this
   103	        call.
   104	
   105	        Args:
   106	            new_yaml: Full pairs.yaml content. Drop a pair by omitting it.
   107	        """
   108	        round_dir = latest_round_dir(_slug_path(slug))
   109	        try:
   110	            res = edit(round_dir, new_yaml)
   111	        except ValidationError as e:
   112	            return _format_validation_error(e)
   113	        except Exception as e:
   114	            return f"edit_pairs failed: {type(e).__name__}: {e}"
   115	        return (
   116	            f"edit_pairs OK\n"
   117	            f"  alive: {res['n_alive']}  (was {res['n_original']} pre-edit)\n"
   118	            f"  changed vs bk.yaml: {res['n_changed_vs_bk']}\n"
   119	            f"next: call train() when ready (you can call edit_pairs again first)."
   120	        )
   121	
   122	    return execute
   123	
   124	
   125	@tool(name="train", parallel=False)
   126	def train_tool(slug: str) -> Tool:
   127	    async def execute() -> str:
   128	        """Train the adapter on (curated) pairs.yaml, then replay
   129	        post-dialogue.
   130	
   131	        No args. Picks up the current round's pairs.yaml, fits a
   132	        ModulatedLoRA via path-loss + KL anchor, calibrates a coherent
   133	        signed_C via c-scan, replays the 3 authority probes under
   134	        adapter@signed_C, writes interview_post.json. After this you
   135	        read interview_pre + interview_post and call judge().
   136	        """
   137	        slug_p = _slug_path(slug)
   138	        round_dir = latest_round_dir(slug_p)
   139	        try:
   140	            res = train_and_eval(slug_p, round_dir)
   141	        except ValidationError as e:
   142	            return _format_validation_error(e)
   143	        return (
   144	            f"train OK\n"
   145	            f"  adapter: {round_dir / 'adapter.safetensors'}\n"
   146	            f"  calibration.json signed_C: ({res['signed_C']:+.3f} — harness-private number)\n"
   147	            f"  interview_post.json: {round_dir / 'interview_post.json'}\n"
   148	            f"  interview_pre.json:  {round_dir / 'interview_pre.json'}\n"
   149	            f"next: read both interview JSONs, then call judge(keep=..., reason=...)."
   150	        )
   151	
   152	    return execute
   153	
   154	
   155	@tool(name="judge", parallel=False)
   156	def judge_tool(slug: str) -> Tool:
   157	    async def execute(keep: bool, reason: str) -> str:
   158	        """Commit the round.
   159	
   160	        Args:
   161	            keep: True to bake this adapter forward (composes into next
   162	                round's history). False to drop and retry with a new
   163	                persona pair.
   164	            reason: One or two sentences citing what you saw in pre vs
   165	                post transcripts. Written to judgment.json.
   166	        """
   167	        round_dir = latest_round_dir(_slug_path(slug))
   168	        try:
   169	            judgment = judge(round_dir, keep, reason)
   170	        except ValidationError as e:
   171	            return _format_validation_error(e)
   172	        return (
   173	            f"judge OK\n"
   174	            f"  action: {judgment['action']}\n"
   175	            f"  written to: {round_dir / 'judgment.json'}\n"
   176	            f"next: harness will allocate a new round or stop on budget exhausted."
   177	        )
   178	
   179	    return execute
   180	
   181	
   182	# ---------------------------------------------------------------------------
   183	# react setup + on_continue (round rollover + budget tracking)
   184	# ---------------------------------------------------------------------------
   185	
   186	def _n_keeps(slug_path: Path) -> int:
   187	    return sum(
   188	        1 for rd in slug_path.glob("round*")
   189	        if rd.is_dir() and (rd / "judgment.json").exists()
   190	        and json.loads((rd / "judgment.json").read_text()).get("action") == "keep"
   191	    )
   192	
   193	
   194	def _n_drops(slug_path: Path) -> int:
   195	    return sum(
   196	        1 for rd in slug_path.glob("round*")
   197	        if rd.is_dir() and (rd / "judgment.json").exists()
   198	        and json.loads((rd / "judgment.json").read_text()).get("action") == "drop"
   199	    )
   200	
   201	
   202	@solver
   203	def inspect_solver(*, slug: str, n_rounds: int) -> Solver:
   204	    slug_path = _slug_path(slug)
   205	
   206	    async def on_continue(state):
   207	        n_keeps = _n_keeps(slug_path)
   208	        if n_keeps >= n_rounds:
   209	            return False  # budget exhausted
   210	
   211	        # If the latest round is done, allocate a new one + run pre-dialogue.
   212	        rd = latest_round_dir(slug_path)
   213	        st = read_state(rd)
   214	        if st.state == "done":
   215	            rd = new_round_dir(slug_path)
   216	            run_pre_dialogue(slug_path, rd)
   217	            st = read_state(rd)
   218	
   219	        return ON_CONTINUE_NUDGE.format(
   220	            n_keeps=n_keeps, target_keeps=n_rounds, n_drops=_n_drops(slug_path),
   221	            last_state=st.state, next_action=ALLOWED_AFTER[st.state],
   222	        )
   223	
   224	    agent = react(
   225	        tools=[
   226	            propose_personas_tool(slug),
   227	            edit_pairs_tool(slug),
   228	            train_tool(slug),
   229	            judge_tool(slug),
   230	        ],
   231	        submit=False,
   232	        prompt=REACT_PROMPT,
   233	        on_continue=on_continue,
   234	        retry_refusals=3,
   235	    )
   236	
   237	    async def solve(state: TaskState, generate: Generate) -> TaskState:
   238	        agent_state = AgentState(messages=state.messages)
   239	        agent_state = await agent(agent_state)
   240	        state.messages = agent_state.messages
   241	        state.output = agent_state.output
   242	        return state
   243	
   244	    return solve
   245	
   246	
   247	def _inspect_model_name(teacher: str) -> str:
   248	    return teacher if teacher.startswith(("openrouter/", "openai/", "anthropic/")) else f"openrouter/{teacher}"
   249	
   250	
   251	def run(*, model: str, teacher: str, slug: Path, n_rounds: int) -> None:
   252	    """Build + run the inspect-ai react agent for this slug.
   253	
   254	    Idempotent: if round00 already exists with state ≠ done, picks up
   255	    there; pre_dialogue is run lazily by `on_continue` for new rounds.
   256	    """
   257	    slug_path = _slug_path(slug)
   258	    # round00 pre-dialogue: ensure it exists before the agent starts so its
   259	    # very first action can be a propose_personas after reading the
   260	    # transcript.
   261	    rd = latest_round_dir(slug_path)
   262	    if not (rd / "interview_pre.json").exists():
   263	        run_pre_dialogue(slug_path, rd)
   264	
   265	    n_keeps_now = _n_keeps(slug_path)
   266	    n_history = len(kept_history_dirs(slug_path))
   267	    initial = INITIAL_TASK.format(
   268	        round_n=n_keeps_now + 1, target_n=n_keeps_now + n_rounds,
   269	        round_dir=str(rd.relative_to(REPO)), model=model,
   270	        n_history=n_history,
   271	    )
   272	
   273	    teacher_model = _inspect_model_name(teacher)
   274	    task = Task(
   275	        dataset=[Sample(input=[ChatMessageUser(content=initial)], id="w2schar-mini")],
   276	        solver=inspect_solver(slug=str(slug_path), n_rounds=n_rounds),
   277	        sandbox=None,
   278	    )
   279	
   280	    if os.environ.get("INSPECT_AGENT_DRY_RUN") == "1":
   281	        print(f"agent-run: DRY_RUN PASS model={teacher_model} slug={slug_path} "
   282	              f"n_rounds={n_rounds}", file=sys.stderr)
   283	        return
   284	
   285	    logs = inspect_eval(
   286	        task, model=teacher_model,
   287	        display="conversation",
   288	        log_dir=str(slug_path.resolve()),
   289	        log_format="json",
   290	        fail_on_error=True,
   291	        score=False,
   292	    )
   293	    if any(log.status != "success" for log in logs):
   294	        raise RuntimeError(f"inspect eval failed: {[log.status for log in logs]}")
   295	    print(f"agent-run: done. logs={logs}")

 succeeded in 1415ms:
     1	"""Per-round state machine: propose → curate → judge → done.
     2	
     3	Persisted as `<round_dir>/state.json`. Each tool the agent calls reads
     4	this and raises `ValidationError` if the call is invalid for the
     5	current state. The error message names the next valid action so the
     6	react agent's `on_continue` nudge can just reproduce it.
     7	"""
     8	from __future__ import annotations
     9	
    10	import json
    11	from dataclasses import dataclass, field
    12	from pathlib import Path
    13	from typing import Literal
    14	
    15	State = Literal["propose", "curate", "judge", "done"]
    16	TRANSITIONS = {"propose": "curate", "curate": "judge", "judge": "done"}
    17	ALLOWED_AFTER = {
    18	    "propose": "propose_personas",
    19	    "curate":  "edit_pairs or train",
    20	    "judge":   "judge",
    21	    "done":    "(round complete — start next round or stop)",
    22	}
    23	
    24	
    25	class ValidationError(RuntimeError):
    26	    pass
    27	
    28	
    29	@dataclass
    30	class RoundState:
    31	    state: State = "propose"
    32	    note: str = ""
    33	
    34	    def to_dict(self) -> dict:
    35	        return {"state": self.state, "note": self.note}
    36	
    37	
    38	def read_state(round_dir: Path) -> RoundState:
    39	    p = round_dir / "state.json"
    40	    if not p.exists():
    41	        return RoundState(state="propose")
    42	    d = json.loads(p.read_text())
    43	    return RoundState(state=d["state"], note=d.get("note", ""))
    44	
    45	
    46	def write_state(round_dir: Path, st: RoundState) -> None:
    47	    p = round_dir / "state.json"
    48	    p.parent.mkdir(parents=True, exist_ok=True)
    49	    p.write_text(json.dumps(st.to_dict(), indent=2))
    50	
    51	
    52	def require_state(round_dir: Path, expected: State, tool_name: str) -> RoundState:
    53	    """Read current state and raise ValidationError if not `expected`."""
    54	    st = read_state(round_dir)
    55	    if st.state != expected:
    56	        raise ValidationError(
    57	            f"tool {tool_name!r} requires state={expected!r}, but current "
    58	            f"state is {st.state!r}. Next valid action: {ALLOWED_AFTER[st.state]}."
    59	        )
    60	    return st
    61	
    62	
    63	def advance(round_dir: Path, note: str = "") -> RoundState:
    64	    """Move to the next state. Errors if already 'done'."""
    65	    st = read_state(round_dir)
    66	    if st.state == "done":
    67	        raise ValidationError("round already at state='done'; start the next round")
    68	    new = TRANSITIONS[st.state]
    69	    st = RoundState(state=new, note=note)
    70	    write_state(round_dir, st)
    71	    return st

codex
A likely crux emerged in `train.py`: the NLL is delegated to HF’s causal-LM loss, which shifts labels internally, while the KL mask is applied directly to unshifted logits. I’m checking whether that is a repo-local convention or a real off-by-one against the stated invariant.
exec
/usr/bin/zsh -lc 'rg -n "_kl_mean_full|labels=|shift|label" src/csm /workspace/weight-steering-lite/src /workspace/weight-steering-lite/docs/wsl_pseudocode.md' in /workspace/w2schar-mini
exec
/usr/bin/zsh -lc "nl -ba /workspace/weight-steering-lite/docs/wsl_pseudocode.md | sed -n '1,260p'" in /workspace/w2schar-mini
exec
/usr/bin/zsh -lc 'rg -n "def on_continue|n_rounds|new_round_dir|latest_round_dir|n_keeps|budget|round_n" /workspace/weight-steering-lite src/csm' in /workspace/w2schar-mini
 succeeded in 1424ms:
/workspace/weight-steering-lite/src/wsl/train.py:8:Both terms in nats. β trades steering signal vs distribution shift;
/workspace/weight-steering-lite/src/wsl/train.py:15:shift does not.
/workspace/weight-steering-lite/src/wsl/train.py:76:    """Return (input_ids, labels) where labels mask out the prompt portion.
/workspace/weight-steering-lite/src/wsl/train.py:95:    labels = list(full_ids)
/workspace/weight-steering-lite/src/wsl/train.py:96:    cut = min(len(prompt_ids), len(labels))
/workspace/weight-steering-lite/src/wsl/train.py:98:        labels[i] = -100
/workspace/weight-steering-lite/src/wsl/train.py:99:    return torch.tensor(full_ids), torch.tensor(labels)
/workspace/weight-steering-lite/src/wsl/train.py:105:    labels = torch.full((len(batch), max_len), -100, dtype=torch.long)
/workspace/weight-steering-lite/src/wsl/train.py:110:        labels[i, :n] = lbl
/workspace/weight-steering-lite/src/wsl/train.py:112:    return input_ids, labels, attn
/workspace/weight-steering-lite/src/wsl/train.py:115:def _nll(model, input_ids, labels, attn) -> torch.Tensor:
/workspace/weight-steering-lite/src/wsl/train.py:116:    out = model(input_ids=input_ids, attention_mask=attn, labels=labels)
/workspace/weight-steering-lite/src/wsl/train.py:170:    (labels != -100, i.e. label/assistant tokens only) so the two terms
/workspace/weight-steering-lite/src/wsl/train.py:239:        out_p = model(input_ids=ip, attention_mask=ap, labels=lp)
/workspace/weight-steering-lite/src/wsl/train.py:243:            # Mask KL to label positions (labels != -100), same as HF NLL — so
/workspace/weight-steering-lite/src/wsl/train.py:263:        out_n = model(input_ids=in_, attention_mask=an, labels=ln)
/workspace/weight-steering-lite/src/wsl/prompts.py:84:    # shift. Default off; per-model override if needed.
/workspace/weight-steering-lite/src/wsl/prompts.py:502:defers to authority), expect no shift in post: there's nothing to move.
/workspace/weight-steering-lite/src/wsl/prompts.py:522:      table usually comes from a formatting or linguistic-style shift
/workspace/weight-steering-lite/src/wsl/prompts.py:525:      strongly. Principle-level character shifts are usually subtler in
/workspace/weight-steering-lite/src/wsl/prompts.py:557:        axis=<new short label>,
/workspace/weight-steering-lite/src/wsl/prompts.py:638:    be visible in what the response argues, not in self-labels.
/workspace/weight-steering-lite/src/wsl/data.py:269:    label: str, seed: int, persona_rep_penalty: float = 1.5,
/workspace/weight-steering-lite/src/wsl/data.py:294:        for i in tqdm(range(0, len(prompts), batch_size), desc=f"gen {label}", mininterval=60, maxinterval=120):
/workspace/weight-steering-lite/src/wsl/data.py:348:                logger.info(f"first {label} sample (special tokens shown, full input+output):\n{raw}\n--- end first {label} sample ---")
/workspace/weight-steering-lite/src/wsl/data.py:429:    cho_texts = _generate_batched(model, tok, pos_inputs, pos_personas_per_spec, label="cho", **gen_kwargs)
/workspace/weight-steering-lite/src/wsl/data.py:430:    rej_texts = _generate_batched(model, tok, neg_inputs, neg_personas_per_spec, label="rej", **gen_kwargs)
/workspace/weight-steering-lite/src/wsl/inspect_export.py:101:def _format_dist(p: np.ndarray, label: np.ndarray | None) -> str:
/workspace/weight-steering-lite/src/wsl/inspect_export.py:102:    """Side-by-side bar table of model p vs human label."""
/workspace/weight-steering-lite/src/wsl/inspect_export.py:103:    head = "| foundation | model_p | human_label | Δ |\n|---|---|---|---|\n"
/workspace/weight-steering-lite/src/wsl/inspect_export.py:107:        lv = float(label[i]) if label is not None else None
/workspace/weight-steering-lite/src/wsl/inspect_export.py:109:            rows.append(f"| {f:9s} | `{_bar(pv)}` {pv:.3f} | (unlabeled) | — |")
/workspace/weight-steering-lite/src/wsl/inspect_export.py:122:    to human label, ~0.69 nats = max). Top1 match is a derived bool in
/workspace/weight-steering-lite/src/wsl/inspect_export.py:128:    label = row.get("label")
/workspace/weight-steering-lite/src/wsl/inspect_export.py:129:    label_arr = np.asarray(label, dtype=float) if label is not None else None
/workspace/weight-steering-lite/src/wsl/inspect_export.py:132:    js = _js_div(p, label_arr) if label_arr is not None else None
/workspace/weight-steering-lite/src/wsl/inspect_export.py:160:            "label": label_arr.tolist() if label_arr is not None else None,
/workspace/weight-steering-lite/src/wsl/inspect_export.py:164:    label_str = (
/workspace/weight-steering-lite/src/wsl/inspect_export.py:165:        ", ".join(f"{f}={label_arr[i]:.2f}" for i, f in enumerate(_FOUNDATIONS_PROBE) if label_arr[i] > 0)
/workspace/weight-steering-lite/src/wsl/inspect_export.py:166:        if label_arr is not None else "(unlabeled)"
/workspace/weight-steering-lite/src/wsl/inspect_export.py:176:        + f"### Distribution: model_p vs human_label\n\n{_format_dist(p, label_arr)}"
/workspace/weight-steering-lite/src/wsl/inspect_export.py:191:        target=f"{row['foundation_coarse']}  (label: {label_str})",
/workspace/weight-steering-lite/src/wsl/rounds_table.py:7:     tinymfv — label-agreement, NOT a budget; we shift it intentionally),
/workspace/weight-steering-lite/src/wsl/rounds_table.py:19:Coherence canary: not present here. Δans is label-agreement (target,
/workspace/weight-steering-lite/src/wsl/rounds_table.py:36:# budget — we are intentionally shifting the model's foundation choice.
/workspace/weight-steering-lite/src/wsl/rounds_table.py:37:# A negative Δans can mean "axis loaded correctly" (shifted away from
/workspace/weight-steering-lite/src/wsl/rounds_table.py:38:# label) or "model degraded" (gibberish). Disambiguate from the foundation
/workspace/weight-steering-lite/src/wsl/rounds_table.py:128:    Δ: ans (top1) is label-agreement (we shift it intentionally), nll is
/workspace/weight-steering-lite/src/wsl/rounds_table.py:178:             intentionally shifting which foundation the model picks, so a negative Δans
/workspace/weight-steering-lite/src/wsl/rounds_table.py:179:             can mean "axis loaded" (steered foundation differs from label) just as easily
/workspace/weight-steering-lite/src/wsl/interview.py:9:  - desired_dir    "+" or "-" -- informational; data labelling fixes train sign
/workspace/weight-steering-lite/src/wsl/interview.py:70:    overall top1_acc shift if the axis isn't a Foundation name."""
/workspace/weight-steering-lite/src/wsl/interview.py:311:def format_probe(probe_id: str, turns: list[dict], *, label: str,
/workspace/weight-steering-lite/src/wsl/interview.py:314:    """Pretty-print one probe's turns as simulated markdown. `label` is 'PRE'
/workspace/weight-steering-lite/src/wsl/interview.py:321:    style shifts that a head-only cap misses. USER turns are never truncated
/workspace/weight-steering-lite/src/wsl/interview.py:341:    lines = ["", "", f"## {label}  {probe_id}", ""]
src/csm/pipeline.py:9:  spec.json           — pos/neg personas + axis label
src/csm/train.py:11:    L_pos = C·nll(cho | c=+C)  +  β·mean_KL(steer ‖ base) on cho label tokens
src/csm/train.py:12:    L_neg = C·nll(rej | c=-C)  +  β·mean_KL(steer ‖ base) on rej label tokens
src/csm/train.py:14:Both terms in nats. β trades steering signal vs distribution shift;
src/csm/train.py:59:# Tokenisation: prompt+completion teacher-forced; label mask = prompt -100.
src/csm/train.py:66:    """(input_ids, labels) where labels mask out the prompt portion."""
src/csm/train.py:76:    labels = list(full_ids)
src/csm/train.py:77:    for i in range(min(len(prompt_ids), len(labels))):
src/csm/train.py:78:        labels[i] = -100
src/csm/train.py:79:    return torch.tensor(full_ids), torch.tensor(labels)
src/csm/train.py:85:    labels = torch.full((len(batch), max_len), -100, dtype=torch.long)
src/csm/train.py:90:        labels[i, :n] = lbl
src/csm/train.py:92:    return input_ids, labels, attn
src/csm/train.py:127:def _kl_mean_full(logp_steer, logp_base, mask):
src/csm/train.py:162:        out_p = model(input_ids=ip, attention_mask=ap, labels=lp)
src/csm/train.py:166:            kl_p = _kl_mean_full(logp_p, logp_b_p, lp != -100)
src/csm/train.py:179:        out_n = model(input_ids=in_, attention_mask=an, labels=ln)
src/csm/train.py:183:            kl_n = _kl_mean_full(logp_n, logp_b_n, ln != -100)

 succeeded in 1416ms:
     1	# Conditioned Weight Steering (CWS)
     2	
     3	CWS replaces post-hoc subtraction of two separately trained adapters with one LoRA adapter whose contribution is multiplied by a scalar coefficient $c \in [-1, 1]$. $c=0$ is exactly the base model, $c=+1$ moves toward the chosen persona, $c=-1$ toward the rejected. Per step we train both poles jointly (NLL + reverse-KL coherence penalty, PCGrad on the NLL pair). Around the per-step training there is an outer iteration over rounds; kept adapters from prior rounds compose into the next round's load via a gated hook (`HistoryBake`), so the $c=0$ KL reference stays the base model across all rounds (not the previous round's output).
     4	
     5	## Pseudocode
     6	
     7	```py
     8	# ── Adapter (c=0 ≡ base; W frozen) ──────────────────────
     9	def lora_layer(x, W, A, B, c, α, r):       # x ∈ ℝ^{b×s×d}
    10	    Δy = (x @ A.T) @ B.T                   # LoRA delta
    11	    return x @ W.T + c * (α / r) * Δy      # c=0 → exact base
    12	
    13	# ── Outer: rounds compose via gated history hook ───────
    14	kept = []
    15	for round in 0..N:
    16	    model ← load_base_with_history(kept)   # kept adapters active only at c≠0
    17	    A, B  ← small_random_asymmetric()
    18	    train(model, A, B)
    19	    if judge(replay(model)) == keep:
    20	        kept.append(round)
    21	
    22	# ── Inner step: NLL + KL, PCGrad on the NLL pair ───────
    23	for step in train_steps:
    24	    x, y_pos, y_neg = batch(D)             # prompt stripped of persona
    25	    C ~ U(0, 1]                            # steering magnitude
    26	    g_nll, g_kl = [], []
    27	    for c, y in [(+C, y_pos), (-C, y_neg)]:   # both poles, 1 adapter, per step
    28	        p_base ← softmax(model(x, c=0))    # no-grad ref to base
    29	        with lora(c=c):
    30	            p = softmax(model(x))
    31	            g_nll.append(∇(C · nll(p, y)))       # learn behavior w/o persona
    32	            g_kl .append(∇(β · KL(p ‖ p_base)))  # coherence: stay near base
    33	    g_nll ← PCGrad(g_nll)                  # drop the part of each grad that fights the other
    34	    g = mean(g_nll) + mean(g_kl)           # KL added unprojected
    35	    A, B  ← adamw((A, B), g)
    36	    onecyclelr.step()
    37	```
    38	
    39	## Reference pseudocode for nearby methods
    40	
    41	### Original weight steering
    42	
    43	```py
    44	# ── Data ───────────────────────────────────────────────
    45	D_pos = [(q, gen(θ0, sys=s_pos, q)) for q in Q for s_pos in S_pos]
    46	D_neg = [(q, gen(θ0, sys=s_neg, q)) for q in Q for s_neg in S_neg]
    47	D_pos, D_neg = filter_judge(D_pos), filter_judge(D_neg)
    48	D_pos, D_neg = strip_system(D_pos), strip_system(D_neg)
    49	
    50	# ── Two independent fine-tunes ─────────────────────────
    51	θ_pos ← lora_sft(θ0, D_pos)                 # desired behavior
    52	θ_neg ← lora_sft(θ0, D_neg)                 # opposite behavior
    53	
    54	τ_pos = θ_pos - θ0
    55	τ_neg = θ_neg - θ0
    56	w = τ_pos - τ_neg                           # contrastive weight direction
    57	
    58	# ── Steering / monitoring ──────────────────────────────
    59	θ_steered = θ0 + k * w                       # k can be ±, >1, etc.
    60	score = eval_behavior(θ_steered)
    61	τ_ft = θ_ft - θ0                              # arbitrary later fine-tune
    62	align = cosine(τ_ft, w)                       # monitoring variant
    63	```
    64	
    65	### AntiPaSTO (context only)
    66	
    67	This is a compressed sketch; the local AntiPaSTO pseudocode still marks its own version as incomplete.
    68	
    69	```py
    70	# ── SVD-coordinate intervention per module ─────────────
    71	for m in linear_modules(model):
    72	    U, S, Vt = svd(m.W)
    73	    m.U, m.S, m.V = U, S, Vt.T
    74	    m.δS = zeros_like(S)                     # trainable singular edits
    75	    m.A_rot = skew_zeros()                   # optional Cayley rotation
    76	    freeze(m.W)
    77	
    78	def fwd(m, x, c):
    79	    R = cayley(c * m.A_rot)
    80	    Wc = m.U @ diag(m.S + c * m.δS) @ R @ m.V.T
    81	    return x @ Wc.T
    82	
    83	# ── Incomplete contrast pairs ──────────────────────────
    84	x_pos = prefix(persona="positive", question=q)  # no completion tokens
    85	x_neg = prefix(persona="negative", question=q)
    86	
    87	def antipasto_loss(model, x_pos, x_neg):
    88	    h0  = h(model, x_pos, c=0)  - h(model, x_neg, c=0)
    89	    hp  = h(model, x_pos, c=+1) - h(model, x_neg, c=+1)
    90	    hn  = h(model, x_pos, c=-1) - h(model, x_neg, c=-1)
    91	
    92	    δp = project(mean_token(hp - h0), subspace="task ∩ writable")
    93	    δn = project(mean_token(hn - h0), subspace="task ∩ writable")
    94	    d0 = project(mean_token(h0),      subspace="task ∩ writable")
    95	
    96	    ℒ_inner = antiparallel(δp, d0) + antiparallel(-δn, d0)
    97	    B_coh   = sum(tv_barrier(model, x_pos, c) for c in [-1, +1])
    98	    B_mono  = order_barrier(pref_gap(-1), pref_gap(0), pref_gap(+1))
    99	    return ℒ_inner + B_coh + B_mono
   100	
   101	for x_pos, x_neg in loader:
   102	    ℒ = antipasto_loss(model, x_pos, x_neg)
   103	    m.δS, m.A_rot ← opt_step(∇ℒ)
   104	```
   105	
   106	## Source anchors
   107	
   108	Weight Steering defines the contrastive target as a difference between two fine-tuned weight changes, then steers with a scalar coefficient. Local full text: [paper_weight_steering.md](paper_weight_steering.md#L86-L91).
   109	
   110	> Instead of steering activations, we suggest modifying the weights directly. Let $\theta_{\text{pre}}$ denote the original weights of $M$, and $\theta_{\text{positive}}$ and $\theta_{\text{negative}}$ the weights obtained by fine-tuning on $D^{+}$ and $D^{-}$, respectively. We define the weight steering vector $w_b$ as:
   111	>
   112	> $w_b = \tau^{+} - \tau^{-} = \theta_{\text{positive}} - \theta_{\text{negative}}$
   113	>
   114	> **Taking the difference removes model weight changes that we do not care about (e.g. topic, style, length) and isolates the behavior that we want to control.** To steer models, we modify the weights as $\theta_{\text{steered}} = \theta_{\text{pre}} + k w_b$, where $k$ is a scalar coefficient...
   115	
   116	SimPO is relevant because it uses chosen/rejected log-probs directly, without a reference model, and highlights the importance of length-normalized margins. Local full text: [wsl_papers/2405.14734.md](wsl_papers/2405.14734.md#L163-L205).
   117	
   118	> One solution is to use the _summed_ token log probability as the reward, but this suffers from _length bias_--longer sequences tend to have lower log probabilities. Consequently, when $y_w$ is longer than $y_l$, optimizing the summed log probability as a reward forces the model to artificially inflate probabilities for longer sequences to ensure $y_w$ receives a higher reward than $y_l$.
   119	>
   120	> **To address this issue, we consider using the _average_ log-likelihood as the implicit reward:**
   121	>
   122	> $p_\theta(y \mid x) = \frac{1}{|y|}\log \pi_\theta(y \mid x)$
   123	>
   124	> ... Finally, we obtain the SimPO objective by plugging Eq. (4) into Eq. (5):
   125	>
   126	> $\mathcal{L}_{\text{SimPO}} = -\mathbb{E}\left[\log\sigma\left(\frac{\beta}{|y_w|}\log\pi_\theta(y_w|x) - \frac{\beta}{|y_l|}\log\pi_\theta(y_l|x) - \gamma\right)\right]$.
   127	
   128	## Notes on the loss
   129	
   130	Not DPO; there is no reference policy ratio. It is conditional dual behavior cloning with a scalar control path and a KL coherence anchor to the base model. Path loss (sample $C$ per step) shipped along with the reverse-KL penalty and PCGrad-on-NLL-pair — see the pseudocode block at the top of this file and [train.py](../src/wsl/train.py).
   131	
   132	A SimPO-style margin is useful as a diagnostic, not an objective until output-format probability mass is stable:
   133	
   134	```py
   135	def path_probe(model, lora, x, y_pos, y_neg, c):
   136	    with lora(c=c):
   137	        m = mean_logp(model, x, y_pos) - mean_logp(model, x, y_neg)
   138	        p_format = answer_format_mass(model, x)
   139	    return m, p_format
   140	```
   141	
   142	## Current empirical caution
   143	
   144	The 0.6B run proves the mechanism can move outputs, but not yet the intended Auth↓+Care↑ axis. The key failure is that $c=+1$ damaged structured-output mass: [handover.md](handover.md#L14-L31) reports `pmass: base=0.846  c=+1=0.478  c=-1=0.974`. So the next objective should preserve NLL/format mass while training path smoothness. A pure pairwise margin could pass while still stealing probability mass from the answer format.
   145	
   146	## Verification targets for the next path experiment
   147	
   148	| Claim | Check |
   149	|---|---|
   150	| $c=0$ is exact base model | Max-logit diff is zero under adapter context with `c=0`. |
   151	| Adapter path is trained, not accidental | Held-out NLL/margin improves monotonically across a grid of $c \in [-1,1]$, not only at endpoints. |
   152	| Steering preserves answer format | `pmass(c)` stays near base for $c \in \{-1,0,+1\}$. |
   153	| Axis matches the intended persona pair | Auth decreases and Care increases at $c=+1$, mirrored at $c=-1$. |

 succeeded in 1436ms:
src/csm/agent.py:30:    edit, init_run, judge, latest_round_dir, new_round_dir, propose,
src/csm/agent.py:69:        round_dir = latest_round_dir(_slug_path(slug))
src/csm/agent.py:108:        round_dir = latest_round_dir(_slug_path(slug))
src/csm/agent.py:138:        round_dir = latest_round_dir(slug_p)
src/csm/agent.py:167:        round_dir = latest_round_dir(_slug_path(slug))
src/csm/agent.py:176:            f"next: harness will allocate a new round or stop on budget exhausted."
src/csm/agent.py:183:# react setup + on_continue (round rollover + budget tracking)
src/csm/agent.py:186:def _n_keeps(slug_path: Path) -> int:
src/csm/agent.py:203:def inspect_solver(*, slug: str, n_rounds: int) -> Solver:
src/csm/agent.py:206:    async def on_continue(state):
src/csm/agent.py:207:        n_keeps = _n_keeps(slug_path)
src/csm/agent.py:208:        if n_keeps >= n_rounds:
src/csm/agent.py:209:            return False  # budget exhausted
src/csm/agent.py:212:        rd = latest_round_dir(slug_path)
src/csm/agent.py:215:            rd = new_round_dir(slug_path)
src/csm/agent.py:220:            n_keeps=n_keeps, target_keeps=n_rounds, n_drops=_n_drops(slug_path),
src/csm/agent.py:251:def run(*, model: str, teacher: str, slug: Path, n_rounds: int) -> None:
src/csm/agent.py:261:    rd = latest_round_dir(slug_path)
src/csm/agent.py:265:    n_keeps_now = _n_keeps(slug_path)
src/csm/agent.py:268:        round_n=n_keeps_now + 1, target_n=n_keeps_now + n_rounds,
src/csm/agent.py:276:        solver=inspect_solver(slug=str(slug_path), n_rounds=n_rounds),
src/csm/agent.py:282:              f"n_rounds={n_rounds}", file=sys.stderr)
src/csm/cli.py:38:    n_rounds: int | None = None
src/csm/cli.py:39:    """Override n_rounds from the profile / 2 for resume."""
src/csm/cli.py:58:    """Resolve model/teacher/slug/budget, then hand off to csm.agent.run()."""
src/csm/cli.py:72:    n_rounds = args.n_rounds or cfg.n_rounds
src/csm/cli.py:73:    print(f"# agent-run model={model} teacher={teacher} slug={slug} n_rounds={n_rounds}",
src/csm/cli.py:77:    run_agent(model=model, teacher=teacher, slug=slug, n_rounds=n_rounds)
src/csm/prompts.py:56:Round {round_n} of {target_n} keeps. Round dir: `{round_dir}`. The student
src/csm/prompts.py:67:You have {n_keeps}/{target_keeps} keeps so far ({n_drops} drops). The
src/csm/prompts.py:80:                      n_rounds: int = 2) -> str:
src/csm/prompts.py:87:Budget: {n_rounds} *keep* rounds (drops don't count)
src/csm/pipeline.py:66:def latest_round_dir(slug_dir: Path) -> Path:
src/csm/pipeline.py:73:def new_round_dir(slug_dir: Path) -> Path:
src/csm/history.py:30:def parse_round_n(name: str) -> int | None:
src/csm/history.py:93:        n = parse_round_n(rd.name)
src/csm/config.py:47:    n_rounds: int = 2
src/csm/config.py:74:        n_rounds=1,
/workspace/weight-steering-lite/w2schar/03b_train.py:36:    latest_round_dir,
/workspace/weight-steering-lite/w2schar/03b_train.py:99:    from wsl.load_with_history import parse_round_n
/workspace/weight-steering-lite/w2schar/03b_train.py:100:    _n = parse_round_n(cfg.round_dir.name)
/workspace/weight-steering-lite/w2schar/03b_train.py:208:    Forcing the full budget makes pmass sensitive to whatever the model
/workspace/weight-steering-lite/w2schar/03b_train.py:375:        cfg.round_dir = latest_round_dir(cfg.slug_dir)
/workspace/weight-steering-lite/w2schar/03b_train.py:393:        from wsl.load_with_history import parse_round_n
/workspace/weight-steering-lite/w2schar/03b_train.py:394:        n = parse_round_n(cfg.round_dir.name)
/workspace/weight-steering-lite/w2schar/03a_gen.py:42:from wsl.round_helpers import run_atom, latest_slug_dir, latest_round_dir, auto_history_dirs
/workspace/weight-steering-lite/w2schar/03a_gen.py:226:        cfg.round_dir = latest_round_dir(cfg.slug_dir)
/workspace/weight-steering-lite/w2schar/03a_gen.py:240:        from wsl.load_with_history import parse_round_n
/workspace/weight-steering-lite/w2schar/03a_gen.py:241:        n = parse_round_n(cfg.round_dir.name)
/workspace/weight-steering-lite/AGENTS.md:193:coherence/capability budget. 
/workspace/weight-steering-lite/AGENTS.md:195:KL on long gens, ~1.7 nats cumulative as the iterated-steering ceiling). But note we can just use long generations as it fits in our budget.
/workspace/weight-steering-lite/w2schar/02_dialogue.py:74:    """tinymfv think budget. 64 = cheap+rough (in-loop default). Override to
/workspace/weight-steering-lite/w2schar/02_dialogue.py:130:def _latest_round_dir(slug_dir: Path) -> Path:
/workspace/weight-steering-lite/w2schar/02_dialogue.py:147:def _round_n(round_dir: Path) -> int:
/workspace/weight-steering-lite/w2schar/02_dialogue.py:148:    from wsl.load_with_history import parse_round_n
/workspace/weight-steering-lite/w2schar/02_dialogue.py:149:    n = parse_round_n(round_dir.name)
/workspace/weight-steering-lite/w2schar/02_dialogue.py:179:def _register_new_probe(slug_dir: Path, round_n: int, *,
/workspace/weight-steering-lite/w2schar/02_dialogue.py:183:    path = iv / f"round{round_n:02d}.json"
/workspace/weight-steering-lite/w2schar/02_dialogue.py:187:        ps = {"id": f"round{round_n:02d}", "probes": []}
/workspace/weight-steering-lite/w2schar/02_dialogue.py:338:        cfg.round_dir = _latest_round_dir(cfg.slug_dir)
/workspace/weight-steering-lite/w2schar/02_dialogue.py:348:    round_n = _round_n(cfg.round_dir)
/workspace/weight-steering-lite/w2schar/02_dialogue.py:352:        from wsl.load_with_history import parse_round_n
/workspace/weight-steering-lite/w2schar/02_dialogue.py:355:            n = parse_round_n(rd.name)
/workspace/weight-steering-lite/w2schar/02_dialogue.py:356:            if n is None or n >= round_n:
/workspace/weight-steering-lite/w2schar/02_dialogue.py:369:            cfg.slug_dir, round_n,
/workspace/weight-steering-lite/w2schar/02_dialogue.py:379:        probe_paths = _existing_probe_paths(cfg.slug_dir, max_round_inclusive=round_n)
/workspace/weight-steering-lite/w2schar/02_dialogue.py:381:                       if p.name == "frozen.json" or p.stem == f"round{round_n:02d}"]
/workspace/weight-steering-lite/w2schar/02_dialogue.py:387:        probe_paths = _existing_probe_paths(cfg.slug_dir, max_round_inclusive=round_n - 1)
/workspace/weight-steering-lite/w2schar/02_dialogue.py:462:        "round": round_n,
/workspace/weight-steering-lite/w2schar/02_dialogue.py:489:    print(f"## dialogue {phase}: round={round_n}  probe_sets={len(by_set)}")
/workspace/weight-steering-lite/w2schar/02_dialogue.py:493:        print(f"## {phase} eval ({round_n}): top1={eval_summary['top1_acc']:.4f}", file=_f)
/workspace/weight-steering-lite/w2schar/04_commit.py:77:    from wsl.load_with_history import parse_round_n
/workspace/weight-steering-lite/w2schar/04_commit.py:80:        n = parse_round_n(rd.name)
/workspace/weight-steering-lite/w2schar/04_commit.py:161:    round_n_str = cfg.round_dir.name
/workspace/weight-steering-lite/w2schar/04_commit.py:164:        f"## {ts} — {run_slug}/{round_n_str}: {judgment['action']}",
/workspace/weight-steering-lite/w2schar/04_commit.py:227:    from wsl.load_with_history import parse_round_n
/workspace/weight-steering-lite/w2schar/04_commit.py:228:    round_n = parse_round_n(cfg.round_dir.name) or 0
/workspace/weight-steering-lite/w2schar/04_commit.py:244:    next_round_dir = cfg.slug_dir / f"round{round_n + 1:02d}"
/workspace/weight-steering-lite/w2schar/04_commit.py:261:    print(next_after_04(slug=str(cfg.slug_dir), next_round_name=next_round_dir.name))
/workspace/weight-steering-lite/RESEARCH_JOURNAL.md:3228:3. **Δnll is NOT qualitative incoherence.** Read `interview_post.json` at c=1.0 (Δnll=+0.224): text is fully coherent, just shifted from "dramatic first-person Petrov" → "careful AI advisor framing". The +0.02 Δnll threshold was rejecting working adapters. **Dropping Δnll as a hard gate**; using qualitative pre/post + Δtop1 capability budget instead.
/workspace/weight-steering-lite/RESEARCH_JOURNAL.md:3426:2. `src/wsl/calibrate.py` restored from git (`52b7ab7^`). Has `measure_kl` + `calibrate_iso_kl` with T=50 default. `bisect_margin` NOT restored (different objective from cumulative budget).
/workspace/weight-steering-lite/RESEARCH_JOURNAL.md:3427:3. `w2schar/_atoms/train_calibrate.py` — added `kl_budget: float = 0.5` field. When > 0:
/workspace/weight-steering-lite/RESEARCH_JOURNAL.md:3429:   - `remaining = kl_budget - cumulative_kl_prior`
/workspace/weight-steering-lite/RESEARCH_JOURNAL.md:3431:   - If `remaining <= 0`: `signed_C=0`, `status="budget_exhausted"`, agent should drop
/workspace/weight-steering-lite/RESEARCH_JOURNAL.md:3432:   - Saves `delta_kl`, `cumulative_kl`, `remaining_budget` to calibration.json
/workspace/weight-steering-lite/RESEARCH_JOURNAL.md:3433:4. `w2schar/03_steer.py` — `--kl-budget 0.5` forwarded to train_calibrate
/workspace/weight-steering-lite/RESEARCH_JOURNAL.md:3434:5. `w2schar/04_commit.py` — journal entries surface `delta_kl + cumulative_kl/budget`
/workspace/weight-steering-lite/RESEARCH_JOURNAL.md:3439:2. With kl_budget=0.5, will r0 alone consume most of the budget? If so, only 1-2 rounds will register before exhaustion.
/workspace/weight-steering-lite/RESEARCH_JOURNAL.md:3440:3. Does kl_budget=0.5 deliver real Care/Auth shifts, or is it too small? Empirical question.
/workspace/weight-steering-lite/RESEARCH_JOURNAL.md:3493:- reasoning: KL budget overshot: cumulative_kl=2.0268 > kl_budget=2.0000 (remaining=-0.0268); behavioral change was good but we must respect the budget constraint per the recipe
/workspace/weight-steering-lite/RESEARCH_JOURNAL.md:3553:2. `src/wsl/calibrate.py` restored from git (`52b7ab7^`). Has `measure_kl` + `calibrate_iso_kl` with T=50 default. `bisect_margin` NOT restored (different objective from cumulative budget).
/workspace/weight-steering-lite/RESEARCH_JOURNAL.md:3554:3. `w2schar/_atoms/train_calibrate.py` — added `kl_budget: float = 0.5` field. When > 0:
/workspace/weight-steering-lite/RESEARCH_JOURNAL.md:3556:   - `remaining = kl_budget - cumulative_kl_prior`
/workspace/weight-steering-lite/RESEARCH_JOURNAL.md:3558:   - If `remaining <= 0`: `signed_C=0`, `status="budget_exhausted"`, agent should drop
/workspace/weight-steering-lite/RESEARCH_JOURNAL.md:3559:   - Saves `delta_kl`, `cumulative_kl`, `remaining_budget` to calibration.json
/workspace/weight-steering-lite/RESEARCH_JOURNAL.md:3560:4. `w2schar/03_steer.py` — `--kl-budget 0.5` forwarded to train_calibrate
/workspace/weight-steering-lite/RESEARCH_JOURNAL.md:3561:5. `w2schar/04_commit.py` — journal entries surface `delta_kl + cumulative_kl/budget`
/workspace/weight-steering-lite/RESEARCH_JOURNAL.md:3566:2. With kl_budget=0.5, will r0 alone consume most of the budget? If so, only 1-2 rounds will register before exhaustion.
/workspace/weight-steering-lite/RESEARCH_JOURNAL.md:3567:3. Does kl_budget=0.5 deliver real Care/Auth shifts, or is it too small? Empirical question.
/workspace/weight-steering-lite/RESEARCH_JOURNAL.md:4591:| H2       | iso-KL=0.1 budget too small: at c=0.149, the intervention isn't strong enough to move foundation distribution, even if cho/rej preference shifts.                                                                                                          | 0.3                          | medium: a stronger intervention (higher c, larger KL budget) might surface the effect. Cheap to test by increasing kl_target.                                                                               | ~0.25     |
/workspace/weight-steering-lite/RESEARCH_JOURNAL.md:4622:- Cfg: `n_rounds=3, train_steps=2000, train_bs=8, data_bs=32, eval_bs=32`
/workspace/weight-steering-lite/RESEARCH_JOURNAL.md:4771:**Hypothesis:** The gemma-2-2b-it may have insufficient capacity to encode a principled refusal disposition without significant coherence loss. The axis movement requires a KL budget that exceeds the model's coherence tolerance.
/workspace/weight-steering-lite/RESEARCH_JOURNAL.md:4794:2. **KL budget:** The mean reverse-KL (0.07) was too high relative to the model's capacity
/workspace/weight-steering-lite/RESEARCH_JOURNAL.md:4804:**Hypothesis:** The gemma-2-2b-it has insufficient capacity to encode a principled "refuse to harm even when ordered" disposition. The axis requires a KL budget that exceeds the model's coherence tolerance. The "Petrov/Alpha-Group" moral foundation may be too abstract for this model size.
/workspace/weight-steering-lite/RESEARCH_JOURNAL.md:4808:## 2026-05-11: 12B w→s overnight — 4 keeps in 5 rounds, but capability budget breached
/workspace/weight-steering-lite/RESEARCH_JOURNAL.md:4838:- r02 kept at Δtop1=-0.144 (over the program.md -0.10 capability budget).
/workspace/weight-steering-lite/RESEARCH_JOURNAL.md:4839:- r04 kept at Δtop1=-0.242 (over budget by 2.4×).
/workspace/weight-steering-lite/RESEARCH_JOURNAL.md:4843:- Add Δtop1 budget to the judge prompt (with the frozen tinymfv eval JSON passed in), OR
/workspace/weight-steering-lite/RESEARCH_JOURNAL.md:4845:- Accept that text-coherence + ΔCare-direction is the right gate and stop talking about Δtop1 as a budget.
/workspace/weight-steering-lite/RESEARCH_JOURNAL.md:4953:2. **Consider lower KL budget**: The accumulated KL (~1.15 across kept rounds) is substantial. A tighter budget (e.g., 0.8 instead of 1.0) might preserve capability better while still achieving character shifts.
/workspace/weight-steering-lite/RESEARCH_JOURNAL.md:5670:- **kl plateau (~0.5)**: most likely set by the `kl_λ=0.016` budget
/workspace/weight-steering-lite/RESEARCH_JOURNAL.md:5774:So r=64 with looser KL spent its extra drift budget making mean_p more
/workspace/weight-steering-lite/RESEARCH_JOURNAL.md:5846:When kl=0.005 (vs 0.016) the model gets a bigger drift budget. With
/workspace/weight-steering-lite/RESEARCH_JOURNAL.md:5847:r=16 the bigger budget would have gone into more care drift (more
/workspace/weight-steering-lite/src/wsl/rounds_table.py:7:     tinymfv — label-agreement, NOT a budget; we shift it intentionally),
/workspace/weight-steering-lite/src/wsl/rounds_table.py:20:not budget). pmass_format would be the right canary but isn't aggregated
/workspace/weight-steering-lite/src/wsl/rounds_table.py:36:# budget — we are intentionally shifting the model's foundation choice.
/workspace/weight-steering-lite/src/wsl/rounds_table.py:181:             transcripts to disambiguate. Not a coherence budget; not a capability floor.
/workspace/weight-steering-lite/src/wsl/load_with_history.py:41:def parse_round_n(name: str) -> int | None:
/workspace/weight-steering-lite/scripts/plot_combined.py:95:            "round_n":   i,
/workspace/weight-steering-lite/scripts/plot_combined.py:144:def _get_petrov(slug_dir: Path, round_name: str, phase: str = "post") -> tuple[str | None, str | None]:
/workspace/weight-steering-lite/scripts/plot_combined.py:146:    f = slug_dir / round_name / f"interview_{phase}.json"
/workspace/weight-steering-lite/scripts/plot_combined.py:252:            f'data-round="{r["round_n"]}" '
/workspace/weight-steering-lite/src/wsl/round_helpers.py:49:def latest_round_dir(slug_dir: Path) -> Path:
/workspace/weight-steering-lite/src/wsl/round_helpers.py:58:    from wsl.load_with_history import parse_round_n
/workspace/weight-steering-lite/src/wsl/round_helpers.py:61:        n = parse_round_n(rd.name)
/workspace/weight-steering-lite/w2schar/_atoms/bake.py:32:from wsl.load_with_history import parse_round_n
/workspace/weight-steering-lite/w2schar/_atoms/bake.py:51:    my_n = parse_round_n(round_dir.name)
/workspace/weight-steering-lite/w2schar/_atoms/bake.py:58:        n = parse_round_n(p.name)
/workspace/weight-steering-lite/w2schar/_atoms/bake.py:113:        "baked_history": [parse_round_n(h.name) for h in history_dirs],
/workspace/weight-steering-lite/w2schar/_atoms/bake.py:138:    print(f"## bake: {cfg.model}  signed_C={signed_C:+.4f}  history={[parse_round_n(h.name) for h in history_dirs]}")
/workspace/weight-steering-lite/src/wsl/cache.py:27:    """f"{base_id}|{quant}|{'+'.join(sorted_kept_round_names)}".
/workspace/weight-steering-lite/src/wsl/prompts.py:22:Substitution uses plain `str.format(slug=..., n_rounds=..., ...)`. Literal
/workspace/weight-steering-lite/src/wsl/prompts.py:91:    n_rounds: int = 10
/workspace/weight-steering-lite/src/wsl/prompts.py:422:**Budget is in KEEPS, not attempts.** Success = {n_rounds} kept rounds (each
/workspace/weight-steering-lite/src/wsl/prompts.py:423:with action='keep' in judgment.json). Drops do not count toward the budget —
/workspace/weight-steering-lite/src/wsl/prompts.py:425:next round. There is no early stop; you don't stop after {n_rounds} attempts,
/workspace/weight-steering-lite/src/wsl/prompts.py:426:you stop after {n_rounds} keeps.
/workspace/weight-steering-lite/src/wsl/prompts.py:665:NEXT_AFTER_04 = """next: round {next_round_name} scaffold ready. Call w2schar_02_dialogue
/workspace/weight-steering-lite/src/wsl/prompts.py:678:                      n_rounds: int = 10, resume_context: str = "") -> str:
/workspace/weight-steering-lite/src/wsl/prompts.py:699:        model=model, slug=slug, n_rounds=n_rounds, resume_context=resume_context,
/workspace/weight-steering-lite/src/wsl/prompts.py:733:def next_after_04(slug: str, next_round_name: str) -> str:
/workspace/weight-steering-lite/src/wsl/prompts.py:735:    return NEXT_AFTER_04.format(slug=slug, next_round_name=next_round_name)
/workspace/weight-steering-lite/src/wsl/prompts.py:758:- TARGET KEPT ROUNDS={n_rounds}
/workspace/weight-steering-lite/src/wsl/prompts.py:763:    "Continue. Kept: {n_keeps}/{target_keeps}. Drops so far: {n_drops}. "
/workspace/weight-steering-lite/src/wsl/prompts.py:800:def initial_task(*, model: str, slug: str, n_rounds: int, resume_context: str) -> str:
/workspace/weight-steering-lite/src/wsl/prompts.py:802:        model=model, slug=slug, n_rounds=n_rounds,
/workspace/weight-steering-lite/scripts/replay_prompts.py:163:                              n_rounds=3, resume_context="(fresh run)")
/workspace/weight-steering-lite/scripts/replay_prompts.py:165:                           n_rounds=3, resume_context="(fresh run)")
/workspace/weight-steering-lite/scripts/replay_prompts.py:189:         NEXT_AFTER_04.format(slug="replay_dryrun", next_round_name="round01")),
/workspace/weight-steering-lite/scripts/agent_driver_inspect.py:742:    n_rounds: int,
/workspace/weight-steering-lite/scripts/agent_driver_inspect.py:747:    # with new personas until n_rounds rounds have been kept.
/workspace/weight-steering-lite/scripts/agent_driver_inspect.py:748:    target_keeps = len(kept_rounds(slug_path)) + n_rounds
/workspace/weight-steering-lite/scripts/agent_driver_inspect.py:750:    async def on_continue(state):
/workspace/weight-steering-lite/scripts/agent_driver_inspect.py:751:        n_keeps = len(kept_rounds(slug_path))
/workspace/weight-steering-lite/scripts/agent_driver_inspect.py:752:        if n_keeps >= target_keeps:
/workspace/weight-steering-lite/scripts/agent_driver_inspect.py:756:            n_keeps=n_keeps, target_keeps=target_keeps, n_drops=n_total - n_keeps,
/workspace/weight-steering-lite/scripts/agent_driver_inspect.py:820:    n_rounds: int | None = None
/workspace/weight-steering-lite/scripts/agent_driver_inspect.py:821:    """Override n_rounds. Fresh default = profile's cfg.n_rounds (10).
/workspace/weight-steering-lite/scripts/agent_driver_inspect.py:822:    Resume default = 6 (= remaining-budget heuristic)."""
/workspace/weight-steering-lite/scripts/agent_driver_inspect.py:826:    """Return (model, slug, n_rounds, teacher, resume_context, cfg).
/workspace/weight-steering-lite/scripts/agent_driver_inspect.py:857:        n_rounds = args.n_rounds if args.n_rounds is not None else 6
/workspace/weight-steering-lite/scripts/agent_driver_inspect.py:860:            f"teacher={teacher} last_done={last_done} remaining={n_rounds}",
/workspace/weight-steering-lite/scripts/agent_driver_inspect.py:863:        return model, str(slug_path), n_rounds, teacher, resume_context, cfg
/workspace/weight-steering-lite/scripts/agent_driver_inspect.py:878:    n_rounds = args.n_rounds if args.n_rounds is not None else cfg.n_rounds
/workspace/weight-steering-lite/scripts/agent_driver_inspect.py:881:        f"model={model} teacher={teacher} n_rounds={n_rounds}",
/workspace/weight-steering-lite/scripts/agent_driver_inspect.py:899:    return model, str(slug_path), n_rounds, teacher, resume_context, cfg
/workspace/weight-steering-lite/scripts/agent_driver_inspect.py:904:    model, slug, n_rounds, teacher, resume_context, cfg = resolve_launch(args)
/workspace/weight-steering-lite/scripts/agent_driver_inspect.py:909:        n_rounds=n_rounds,
/workspace/weight-steering-lite/scripts/agent_driver_inspect.py:921:                            n_rounds=n_rounds,
/workspace/weight-steering-lite/scripts/agent_driver_inspect.py:934:            n_rounds=n_rounds,
/workspace/weight-steering-lite/scripts/agent_driver_inspect.py:941:            f"model={teacher_model} slug={slug} n_rounds={n_rounds}"
/workspace/weight-steering-lite/scripts/verify_force_min_new_tokens.py:26:    budget: int = 2048
/workspace/weight-steering-lite/scripts/verify_force_min_new_tokens.py:56:        n_vignettes=cfg.n_vignettes, max_think_tokens=cfg.budget,
/workspace/weight-steering-lite/scripts/verify_force_min_new_tokens.py:61:    print(f"=== with force_min_new_tokens={cfg.budget} (forced past </think>) ===")
/workspace/weight-steering-lite/scripts/verify_force_min_new_tokens.py:64:        n_vignettes=cfg.n_vignettes, max_think_tokens=cfg.budget,
/workspace/weight-steering-lite/scripts/verify_force_min_new_tokens.py:66:        force_min_new_tokens=cfg.budget,
/workspace/weight-steering-lite/scripts/verify_force_min_new_tokens.py:73:    if all(t >= cfg.budget * 0.95 for t in tt2):
/workspace/weight-steering-lite/scripts/verify_force_min_new_tokens.py:74:        print(f"PASS: force_min_new_tokens={cfg.budget} actually generated "
/workspace/weight-steering-lite/scripts/verify_force_min_new_tokens.py:75:              f"≥{int(cfg.budget*0.95)} tokens. Default was {tt1}.")
/workspace/weight-steering-lite/scripts/verify_force_min_new_tokens.py:78:              f"{int(cfg.budget*0.95)}).")

exec
/usr/bin/zsh -lc "nl -ba /workspace/weight-steering-lite/src/wsl/train.py | sed -n '150,285p'" in /workspace/w2schar-mini
 succeeded in 1398ms:
   150	    bp = ip.shape[0]
   151	    ids_cat = torch.cat([ip, in_], dim=0)
   152	    attn_cat = torch.cat([ap, an], dim=0)
   153	    with lora(model, c=0.0):
   154	        logits = model(input_ids=ids_cat, attention_mask=attn_cat).logits.float()
   155	    logp = torch.log_softmax(logits, dim=-1)
   156	    # topk over vocab dim — frees the [2B,S,V] tensor as logits/logp go out of scope
   157	    topk_logp, topk_idx = logp.topk(KL_TOPK, dim=-1)  # both [2B,S,K]
   158	    return (topk_idx[:bp, :L_p], topk_logp[:bp, :L_p]), \
   159	           (topk_idx[bp:, :L_n], topk_logp[bp:, :L_n])
   160	
   161	
   162	def _kl_mean_topk(
   163	    logp_steer: torch.Tensor,
   164	    base_topk_idx: torch.Tensor, base_topk_logp: torch.Tensor,
   165	    mask: torch.Tensor,
   166	) -> torch.Tensor:
   167	    """Sparse reverse-KL(p_steer ‖ p_base) approximation, mean over mask.
   168	
   169	    `mask` should be the same per-token positions HF NLL averages over
   170	    (labels != -100, i.e. label/assistant tokens only) so the two terms
   171	    in `loss = nll - kl_lambda * kl` share the same denominator and the
   172	    kl_lambda units are unambiguous (nats KL per nat NLL per token).
   173	
   174	    Splits KL = Σ_v p_s(v) · (log p_s(v) − log p_b(v)) into:
   175	      • exact part over base's top-K: gather p_s at those indices, dot with
   176	        (log p_s_topk − log p_b_topk).
   177	      • tail floor: assume p_b(v) ≈ ε for v ∉ top-K. Tail contribution =
   178	        −H(p_s) restricted to tail − log(ε) · (1 − Σ_topk p_s).
   179	
   180	    Total: KL ≈ −H(p_s) − ⟨p_s_topk, logp_b_topk⟩ − log(ε) · (1 − p_s_topk_mass)
   181	    where H(p_s) is the full entropy (still uses full logp_steer; that tensor
   182	    is needed for NLL backward anyway, so no extra cost).
   183	    """
   184	    p_s = logp_steer.exp()
   185	    H_full = -(p_s * logp_steer).sum(dim=-1)  # [B,S], entropy of steered
   186	    p_s_topk = torch.gather(p_s, dim=-1, index=base_topk_idx)  # [B,S,K]
   187	    p_s_topk_mass = p_s_topk.sum(dim=-1)  # [B,S]
   188	    inner = (p_s_topk * base_topk_logp).sum(dim=-1)  # [B,S]
   189	    log_eps = math.log(KL_EPS)
   190	    kl_per_tok = -H_full - inner - log_eps * (1.0 - p_s_topk_mass)
   191	    return kl_per_tok[mask.bool()].mean()
   192	
   193	
   194	def _zerofill(grads, params):
   195	    return [g if g is not None else torch.zeros_like(p) for g, p in zip(grads, params)]
   196	
   197	
   198	def pcgrad_train_step(
   199	    model, lora: ModulatedLoRA,
   200	    ip, lp, ap,        # cho batch tokens
   201	    in_, ln, an,       # rej batch tokens
   202	    params: list,
   203	    *,
   204	    C: float,          # strength in [0, 1] sampled by caller (path training)
   205	    pcgrad: bool = True,
   206	    kl_lambda: float = 0.0,
   207	) -> dict:
   208	    """One training step. NLL and KL gradients are kept separate:
   209	
   210	        L_pos_nll = C · nll(cho | c=+C)
   211	        L_neg_nll = C · nll(rej | c=-C)
   212	        L_pos_kl  = λ · p95_KL(steer ‖ base) on cho tokens
   213	        L_neg_kl  = λ · p95_KL(steer ‖ base) on rej tokens
   214	
   215	    PCGrad (Yu et al. 2020) operates on the (NLL_pos, NLL_neg) pair ONLY —
   216	    cho/rej are the same task at different poles and may legitimately conflict.
   217	    KL gradients are added in unmodified afterwards, because KL is a different
   218	    objective (preserve base behavior) that's EXPECTED to oppose the persona
   219	    objective — that's the whole point. Folding KL into per-pole losses and
   220	    projecting against it would silently weaken the KL term exactly when
   221	    persona pushes hardest.
   222	
   223	    Two backwards per side on the same forward (retain_graph=True for the
   224	    first). No extra forwards vs the folded version.
   225	
   226	    Returns trace dict with NLL, KL summaries, conflict, cos.
   227	    """
   228	    use_kl = kl_lambda > 0
   229	    zero = torch.zeros((), device=next(p.device for p in params))
   230	
   231	    # Both c=0 base forwards batched into one (10-15% step win when lengths similar).
   232	    # Returns top-K idx + log-probs only (~58 MB at K=300) instead of full
   233	    # [B,S,V] fp32 (~8-16 GiB). See _base_topk_pair docstring.
   234	    if use_kl:
   235	        (idx_b_p, logp_b_p), (idx_b_n, logp_b_n) = _base_topk_pair(model, lora, ip, ap, in_, an)
   236	
   237	    # ── cho at c=+C ─────────────────────────────────────────────────────
   238	    with lora(model, c=+C):
   239	        out_p = model(input_ids=ip, attention_mask=ap, labels=lp)
   240	        L_pos_nll = C * out_p.loss
   241	        if use_kl:
   242	            logp_p = torch.log_softmax(out_p.logits.float(), dim=-1)
   243	            # Mask KL to label positions (labels != -100), same as HF NLL — so
   244	            # nll and kl are mean-per-token over the SAME set of tokens. Prompt
   245	            # tokens contribute to neither. (Was ap = attn mask = includes prompt.)
   246	            kl_p = _kl_mean_topk(logp_p, idx_b_p, logp_b_p, lp != -100)
   247	            L_pos_kl = kl_lambda * kl_p
   248	    # allow_unused handles architectures where some LoRA targets aren't
   249	    # exercised by the current forward (e.g. Gemma-3's interleaved local/global
   250	    # attention skips some layers for short inputs).
   251	    g_pos_nll = _zerofill(torch.autograd.grad(
   252	        L_pos_nll, params, retain_graph=use_kl, allow_unused=True), params)
   253	    if use_kl:
   254	        g_pos_kl = _zerofill(torch.autograd.grad(
   255	            L_pos_kl, params, retain_graph=False, allow_unused=True), params)
   256	    else:
   257	        g_pos_kl = [torch.zeros_like(p) for p in params]
   258	        kl_p = zero
   259	
   260	    # ── rej at c=-C ─────────────────────────────────────────────────────
   261	    # Top-K base for rej was already computed in _base_topk_pair above.
   262	    with lora(model, c=-C):
   263	        out_n = model(input_ids=in_, attention_mask=an, labels=ln)
   264	        L_neg_nll = C * out_n.loss
   265	        if use_kl:
   266	            logp_n = torch.log_softmax(out_n.logits.float(), dim=-1)
   267	            kl_n = _kl_mean_topk(logp_n, idx_b_n, logp_b_n, ln != -100)
   268	            L_neg_kl = kl_lambda * kl_n
   269	    g_neg_nll = _zerofill(torch.autograd.grad(
   270	        L_neg_nll, params, retain_graph=use_kl, allow_unused=True), params)
   271	    if use_kl:
   272	        g_neg_kl = _zerofill(torch.autograd.grad(
   273	            L_neg_kl, params, retain_graph=False, allow_unused=True), params)
   274	    else:
   275	        g_neg_kl = [torch.zeros_like(p) for p in params]
   276	        kl_n = zero
   277	
   278	    # ── PCGrad on the (NLL_pos, NLL_neg) pair only ──────────────────────
   279	    gp_flat = torch.cat([g.reshape(-1) for g in g_pos_nll])
   280	    gn_flat = torch.cat([g.reshape(-1) for g in g_neg_nll])
   281	    dot = (gp_flat * gn_flat).sum()
   282	    gp_norm_sq = (gp_flat * gp_flat).sum().clamp_min(1e-12)
   283	    gn_norm_sq = (gn_flat * gn_flat).sum().clamp_min(1e-12)
   284	    cos = (dot / (gp_norm_sq.sqrt() * gn_norm_sq.sqrt())).item()
   285	    conflict = dot.item() < 0

codex
**Critical**

1. [src/csm/agent.py:206](/workspace/w2schar-mini/src/csm/agent.py:206): resume budget is wrong. `on_continue` stops when `n_keeps >= n_rounds`, but `run()` presents `target_n = n_keeps_now + n_rounds` at [agent.py:265](/workspace/w2schar-mini/src/csm/agent.py:265). So resuming a slug with existing keeps can stop immediately. Reference used `target_keeps = existing_keeps + n_rounds`.

2. [src/csm/train.py:162](/workspace/w2schar-mini/src/csm/train.py:162), [166](/workspace/w2schar-mini/src/csm/train.py:166): NLL and KL share the same *unshifted* `labels != -100` mask, matching local pseudocode literally. But HF causal-LM loss shifts labels internally, so the NLL actually averages logits at `t-1` predicting label token `t`, while KL is applied to logits at `t`. This is likely an off-by-one if the intended invariant is “same predictive positions as HF loss,” not just same count. It misses the prompt-final distribution for first completion token and includes the final-token next distribution.

**Looks Correct**

- [adapter.py:111](/workspace/w2schar-mini/src/csm/adapter.py:111): `c=0` short-circuits new LoRA exactly.
- [adapter.py:239](/workspace/w2schar-mini/src/csm/adapter.py:239), [train.py:254](/workspace/w2schar-mini/src/csm/train.py:254), [train.py:295](/workspace/w2schar-mini/src/csm/train.py:295): HistoryBake gate is disabled during `lora(c=0)` KL reference and restored to always-on before c-scan/dialogue. This preserves `c=0 = pristine base` in training, and `c=0 = base+history` in inference.
- [pipeline.py:219](/workspace/w2schar-mini/src/csm/pipeline.py:219): round N training loads `kept_history_dirs(..., before_round=N)`, correct.
- [state.py:52](/workspace/w2schar-mini/src/csm/state.py:52): state machine blocks out-of-order calls; repeated `edit_pairs` in `curate` is allowed, then `train` advances.
- [c_scan.py:23](/workspace/w2schar-mini/src/csm/c_scan.py:23), [69](/workspace/w2schar-mini/src/csm/c_scan.py:69), [91](/workspace/w2schar-mini/src/csm/c_scan.py:91): `C_MIN`, `MAX_PROBES`, sign application, and NaN guard exist and are functional.

**Nits**

- [c_scan.py:48](/workspace/w2schar-mini/src/csm/c_scan.py:48), [55](/workspace/w2schar-mini/src/csm/c_scan.py:55): rescoring omits `attention_mask`; with left padding and `pad_token=eos`, pmass can be slightly contaminated.
- [pipeline.py:143](/workspace/w2schar-mini/src/csm/pipeline.py:143): min usable pairs is `n_pairs//4` = 12 for 50, not pseudocode’s 20. Static audit only, no runtime tests run.
tokens used
60,790
**Critical**

1. [src/csm/agent.py:206](/workspace/w2schar-mini/src/csm/agent.py:206): resume budget is wrong. `on_continue` stops when `n_keeps >= n_rounds`, but `run()` presents `target_n = n_keeps_now + n_rounds` at [agent.py:265](/workspace/w2schar-mini/src/csm/agent.py:265). So resuming a slug with existing keeps can stop immediately. Reference used `target_keeps = existing_keeps + n_rounds`.

2. [src/csm/train.py:162](/workspace/w2schar-mini/src/csm/train.py:162), [166](/workspace/w2schar-mini/src/csm/train.py:166): NLL and KL share the same *unshifted* `labels != -100` mask, matching local pseudocode literally. But HF causal-LM loss shifts labels internally, so the NLL actually averages logits at `t-1` predicting label token `t`, while KL is applied to logits at `t`. This is likely an off-by-one if the intended invariant is “same predictive positions as HF loss,” not just same count. It misses the prompt-final distribution for first completion token and includes the final-token next distribution.

**Looks Correct**

- [adapter.py:111](/workspace/w2schar-mini/src/csm/adapter.py:111): `c=0` short-circuits new LoRA exactly.
- [adapter.py:239](/workspace/w2schar-mini/src/csm/adapter.py:239), [train.py:254](/workspace/w2schar-mini/src/csm/train.py:254), [train.py:295](/workspace/w2schar-mini/src/csm/train.py:295): HistoryBake gate is disabled during `lora(c=0)` KL reference and restored to always-on before c-scan/dialogue. This preserves `c=0 = pristine base` in training, and `c=0 = base+history` in inference.
- [pipeline.py:219](/workspace/w2schar-mini/src/csm/pipeline.py:219): round N training loads `kept_history_dirs(..., before_round=N)`, correct.
- [state.py:52](/workspace/w2schar-mini/src/csm/state.py:52): state machine blocks out-of-order calls; repeated `edit_pairs` in `curate` is allowed, then `train` advances.
- [c_scan.py:23](/workspace/w2schar-mini/src/csm/c_scan.py:23), [69](/workspace/w2schar-mini/src/csm/c_scan.py:69), [91](/workspace/w2schar-mini/src/csm/c_scan.py:91): `C_MIN`, `MAX_PROBES`, sign application, and NaN guard exist and are functional.

**Nits**

- [c_scan.py:48](/workspace/w2schar-mini/src/csm/c_scan.py:48), [55](/workspace/w2schar-mini/src/csm/c_scan.py:55): rescoring omits `attention_mask`; with left padding and `pad_token=eos`, pmass can be slightly contaminated.
- [pipeline.py:143](/workspace/w2schar-mini/src/csm/pipeline.py:143): min usable pairs is `n_pairs//4` = 12 for 50, not pseudocode’s 20. Static audit only, no runtime tests run.
