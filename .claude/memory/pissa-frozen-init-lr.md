---
name: pissa-frozen-init-lr
description: Why 27b PiSSA adapters trained to zero behaviour — big Δs init orphaned from the lr it needs
metadata: 
  node_type: memory
  type: project
  originSessionId: 3b8b95b0-cc1a-4272-8159-bd9cbe1906ec
---

PiSSA frozen-adapter root cause (found 2026-06-01).

Symptom: 27b PiSSA runs showed `‖Δs‖` pinned at 0.905 for all 60 train steps,
zero behavioural delta on tinymfv (c-sweep c={0..6} wobbled within ±0.002,
non-monotone = noise). LoRA arm (`gemma-27b`) by contrast grew `‖Δs‖` 1.18→1.31.

Cause is two coupled knobs that got decoupled across profiles:
- Δs init scale lives GLOBALLY in `adapter.py` (the `ds = normal_(mean=4e-2,
  std=4e-2)` line). Commit `ea4e17b` (2026-05-22 04:37) bumped it 4e-4→4e-2
  (100x), bundled as "larger lr/init/r". With r=256 that puts `‖Δs‖_init =
  sqrt(256·2·0.04²) = 0.905` exactly. Before ea4e17b (commits 45e3415..2ebd856,
  00:31–03:54 May 22) init was 4e-4 → `‖Δs‖_init ≈ 0.009`, near-0, and it grew
  to 1-3 during training. That near-0 regime is the "it used to work" memory.
- The matching lr bump only ever landed on a PER-PROFILE override
  (`gemma-2b-pissa`: lr=2e-2). PiSSA gets exactly `cfg.lr` — `train.py` is one
  AdamW group, no PiSSA-specific scaling.

Big init + default lr=1e-4 = frozen: AdamW moves each Δs element ~lr/step, so
~3e-3 of travel against a 0.04-per-element init = sub-1%, can't escape init.

The frozen profiles (`gemma-27b-pissa`, `qwen-27b-pissa`) were added uncommitted
THIS session with lora_r=256 + kl_lambda=0.1 and NO lr override → orphaned big
init at lr=1e-4. Removed 2026-06-01. The only PiSSA profile that ever
demonstrably trained is `gemma-2b-pissa` (committed: lr=2e-2, wd=1e-5,
min_steps=120, r=2304) — `‖Δs‖` reaches ~2 there. No committed 27b bf16-PiSSA
ever worked.

Coupling is a hack, not a design: Δs is the per-singular delta; honest init is
~0 (= identity / null intervention). Inflating it to 0.9 then needing 10-200x lr
to drag it back off is two wrongs cancelling on one profile. Principled fix =
small init + modest lr. See [[pissa-strength-knobs-were-non-binding]].

Real experiment runs launch via `csm.cli agent-run --profile <X>` through pueue,
NOT the justfile (justfile only has smoke/smoke-real/smoke-prompts).
