# UAT — Phase B.9: smoke.sh end-to-end

## UAT criteria

- `bash scripts/smoke.sh` exits 0 in < 5 min.
- 1 round chained: pre_dialogue → propose → train+c_scan+post → judge.
- All 10 artifacts present in `<slug>/round00/`:
  - state.json, spec.json, pairs.yaml, pairs.bk.yaml, dropped.json,
    adapter.safetensors, calibration.json, interview_pre.json,
    interview_post.json, judgment.json.
- state.json reaches `state=done`.

## Evidence (raw)

```
smoke: model=wassname/qwen3-5lyr-tiny-random slug=out/iter/20260519T224515_smoke
agent-run: DRY_RUN PASS model=openrouter/qwen/qwen3.5-9b ...

-- pre-dialogue (c=0, base+history) --
dialogue [petrov_false_alarm] @ c=0 (base+history)
dialogue [coup_loyalty_alpha_group] @ c=0 (base+history)
dialogue [whistleblower_safety_incident] @ c=0 (base+history)

-- propose_personas --
gen_pairs: n=4, system_role=True, thinking=False
gen_pairs: alive=4 dropped=0

-- train + c_scan + post-dialogue --
ModulatedLoRA: 35 targets, r=16, trainable=81,920
step    0/20  C=0.42  nll+=9.134  nll-=10.511  kl±=0.0002/0.0003  cos=-0.66  CONFLICT
[20 train steps in ~4 s]
c_scan: baseline pmass=0.205, gate=0.174
c_scan down  c=+1.000  pmass=0.206
c_scan final: signed_C=+0.7500 (|c|=1.000 × backoff=0.75)
dialogue [petrov_false_alarm] @ c=+0.750
dialogue [coup_loyalty_alpha_group] @ c=+0.750
dialogue [whistleblower_safety_incident] @ c=+0.750
   signed_C=+0.7500

-- judge --
   ✓ state.json  (39 bytes)
   ✓ spec.json  (314 bytes)
   ✓ pairs.yaml  (2131 bytes)
   ✓ pairs.bk.yaml  (2131 bytes)
   ✓ dropped.json  (2 bytes)
   ✓ adapter.safetensors  (171056 bytes)
   ✓ calibration.json  (278 bytes)
   ✓ interview_pre.json  (6068 bytes)
   ✓ interview_post.json  (6516 bytes)
   ✓ judgment.json  (136 bytes)

=== smoke PASS — state.json=done ===
```

Notable observations:
- ModulatedLoRA found 35 target Linears on the 5-layer tiny-random; trainable=81,920 params.
- step 0 already shows a CONFLICT (cos=-0.66) so PCGrad fires — the contrast pair is doing useful work even on garbage init.
- c_scan baseline pmass=0.205 on tiny-random's collapsed distribution (expected — outputs at the random model are near-uniform across vocab, so top-K mass is low). gate = 0.85 × 0.205 = 0.174. c=1.0 stayed at pmass=0.206 (>gate), so no down-walk needed; backoff gave signed_C=+0.75.
- Adapter size 171 KB (35 modules × r=16 × ~150 dim ≈ 84k params at fp16 = ~168 KB).
- Total wallclock ~50 s on CPU (no GPU needed for the 5-layer toy).

## Verdict: PASS

Pipeline runs end-to-end. The mechanism (adapter, train, c_scan, dialogue, history bake, state machine, judge) is wired correctly. Numbers are garbage on tiny-random but that's by design — only code paths matter.
