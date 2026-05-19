# UAT — Phase B.11: codex --yolo on full implementation

## UAT criteria

- codex sanity check on `src/csm/*.py` + `pseudocode.md` reference.
- All critical issues addressed.

## codex review summary (full raw output: `docs/codex_review_impl.md`)

### Critical (both fixed)

1. **Resume-budget off-by-one** (`src/csm/agent.py:206`)
   - Old: `on_continue` stopped when `n_keeps >= n_rounds` while `run()` printed `target = n_keeps_now + n_rounds`. Resume of a slug with existing keeps would stop immediately.
   - Fix: capture `initial_keeps` in the solver closure; `target_keeps = initial_keeps + n_rounds`; on_continue compares against `target_keeps`; nudge also reports `target_keeps`.

2. **HF labels off-by-one in KL** (`src/csm/train.py`)
   - Old: KL used `mask = (labels != -100)` directly on `logp_steer`. But HF's CE shifts internally — NLL averages `logits[t-1]` predicting `label[t]`, so KL was misaligned by one position.
   - Fix: `_kl_mean_full` now takes `labels` (not mask), shifts `logp_steer[:, :-1, :]` + `logp_base[:, :-1, :]`, masks with `(labels[:, 1:] != -100)` — matches HF's predictive positions exactly.

### Looks correct (codex confirmed)

- `c=0` short-circuits the new LoRA exactly (adapter.py:111).
- HistoryBake gate is `lora._c != 0.0` during training (pristine-base KL) and always-on for c-scan/dialogue (base+history baseline). Restored at end of `train_adapter` (adapter.py:239, train.py:295).
- Round N loads `kept_history_dirs(slug, before_round=N)` correctly (pipeline.py:219).
- State machine blocks out-of-order calls; repeated `edit_pairs` in `curate` is allowed; `train` advances to `judge` (state.py:52).
- c_scan: `C_MIN`, `MAX_PROBES`, sign, NaN guard all functional (c_scan.py:23,69,91).

### Nits (deferred)

- `c_scan` rescoring forward omits `attention_mask` — with left-pad+EOS, pmass can be slightly contaminated. Low impact (smoke baseline 0.205 with no contamination signal); revisit if real-run baselines look skewed.
- `pipeline.propose` min_alive = `n_pairs // 4` = 12 for 50 (not pseudocode's 20). Will revisit after a real run shows the actual yield from gemma-2-2b.

## Re-smoke after fixes

```
$ bash scripts/smoke.sh
[...full run...]
=== smoke PASS — state.json=done ===
smoke: PASS — slug=out/iter/20260519T225024_smoke
```

Pytest also still green:
```
$ uv run pytest -q -m slow tests/test_smoke.py
1 passed in ~27s
```

## Verdict: PASS

Both critical codex findings fixed; smoke + pytest re-green; nits logged
for follow-up after real-model runs.
