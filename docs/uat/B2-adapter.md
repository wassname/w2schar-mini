# UAT — Phase B.2: adapter.py + history.py

## UAT criteria

1. `ModulatedLoRA` constructs without error on a tiny model.
2. `c=0` forward equals base forward **bit-exact** (max diff = 0).
3. `c=+1` produces a non-zero delta vs base.
4. `parameters()` yields the right count (`2 * r * d` per layer).
5. `save() / from_checkpoint()` roundtrip OK.
6. `HistoryBake` composed dW matches `Σ_i s_i · B_i A_i` (max diff < 1e-5).
7. `HistoryBake` with `set_gate(lambda: False)` returns pristine base (diff = 0).

## Evidence (raw)

```
$ uv run python <smoke>
ModulatedLoRA: 2 targets, r=4, trainable=128
c=0 max_diff = 0.00e+00  (expect 0)
c=+1 max_diff vs base = 3.1578e-04
trainable = 128
reload OK: lora2 c=0.0
adapter UAT PASS

HistoryBake: 2 kept adapter(s), r_total=8
HistoryBake combined-delta max_diff = 5.96e-08  (expect ~0)
HistoryBake gated-off max_diff vs base = 0.00e+00  (expect 0)
HistoryBake UAT PASS
```

## Verdict: PASS

All 7 checks pass. The c=0=base invariant (most important for KL reference) holds bit-exact.
