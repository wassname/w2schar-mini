# UAT — Phase B.3: train.py

## UAT criteria

- `pcgrad_train_step` runs end-to-end on a tiny dummy model + 2 dummy pairs.
- Returned NLL is finite.
- KL is ≥ 0 (up to numerical noise) when the adapter is non-trivially active.
- PCGrad cos / conflict computed.
- All adapter `params` have finite gradients populated after the step.

## Evidence (raw)

```
$ uv run python <smoke>
ModulatedLoRA: 1 targets, r=4, trainable=128
NLL pos=4.713  neg=4.712
KL pos=0.0602  neg=0.0687
conflict=False cos=+0.113
train_step UAT PASS
```

Side note: at *exact init* with B ~ N(1e-4, 1e-4) the steered model is
within numerical noise of base, so KL comes back ~-2e-8 due to fp32
rounding. That's not a bug — it just means KL is too small to measure
at init. We scribbled the adapter with U(-0.5, 0.5) to test the
non-trivial path.

## Verdict: PASS

NLL/KL/PCGrad mechanics validated. Full `train_adapter` will get exercised
end-to-end by the smoke test in B.9.
