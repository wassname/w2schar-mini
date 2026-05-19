# UAT — Phase A: pseudocode.md + codex sanity check

## UAT criteria

- pseudocode.md has ≥ 6 sections (adapter, outer loop, inner step, c-scan + dialogue, state machine, config registry).
- codex --yolo flagged issues addressed in pseudocode.md.

## Evidence

### codex --yolo review (raw)

Saved at `docs/codex_review_pseudo.md`. Critical issues flagged:

1. **§2/§4 contradict on `c=0`.** Training wants `c=0` = pristine base; c-scan / dialogue see `c=0` = base+history. Originally the pseudocode said inference gate was "always true" but called the c-scan reference "base top-K" — ambiguous.
2. **§3 forward shape wrong.** `model(x)` cannot compute label-token NLL/KL — needs teacher-forced `prompt+completion`, label mask, mean over completion positions.
3. **§3 NLL length-normalisation missing.** Per-pair length bias leaks into steering direction otherwise.
4. **§4 c-scan can loop forever.** No min/max c, no NaN check, no failure path.
5. **§4 sign of signed_C undefined.** Need to fix sign source so persona / judge can't silently flip semantics.
6. **§5 silent auto_drop_double_refusals.** Bad epistemics — should surface dropped IDs/reasons to agent.

Nits:
- §1 B init: "small positive" → "small nonzero".
- §1 B=0 "dead zone" → reframe as sign-symmetry issue.
- §3 `C ~ U(0,1]`: implement with assert / resample on C=0.
- §5 50 full pairs in YAML may overflow small-agent context — return compact preview + file-backed diff.
- edit_pairs polarity check (deferred — user's call).

### Fixes applied to pseudocode.md

| codex issue | location | change |
|---|---|---|
| 1 c=0 contradiction | §2 + §4 | added explicit gate-semantics table; c-scan baseline = base+history (inference context) |
| 2 forward shape | §3 | rewrote inner-step loop with teacher-forced `(ids, lbl, attn)`; HF `labels=lbl` mechanism; shared `(lbl != -100)` mask for NLL + KL |
| 3 length-norm | §3 | called out that HF mean-CE over non-ignore tokens already handles length-norm; same mask shared with KL |
| 4 c-scan loop | §4 | added `C_MIN = 0.02`, `MAX_PROBES = 12`, NaN check, explicit `RuntimeError` with pmass trace on failure |
| 5 signed_C | §4 | added explicit `sign` param + comment that persona ordering defines the sign; agent never picks sign |
| 6 surface drops | §5 | `propose_personas` returns `dropped_ids`, raises `ValidationError` if usable pairs < 20 |
| §1 B nonzero | §1 | rewrote init rationale (sign-symmetry, not dead zone) |
| §3 C>0 assert | §3 | called out resample-if-zero |
| §5 yaml overflow | §5 | compact_preview returned to agent; full pairs on disk for bulk rewrite |

### File listing

```
$ wc -l /workspace/w2schar-mini/pseudocode.md
~280
$ grep -c '^## ' /workspace/w2schar-mini/pseudocode.md
8   # 1. Adapter, 2. Outer loop, 3. Inner step, 4. C-scan + dialogue,
    # 5. State machine + tools, plus Per-model config registry, Out of scope
```

## Verdict: PASS

All 6 critical codex issues addressed in pseudocode.md. Edit_pairs
polarity check deferred (user explicitly asked for bulk YAML rewrite
with no harness-side checks).
