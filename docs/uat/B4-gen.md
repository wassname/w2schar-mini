# UAT — Phase B.4: gen.py + prompts_pool.py

## UAT criteria

- `POOL` has ≥ 25 moral/authority prompts.
- YAML write/load roundtrip preserves dict equality (interleaved per-pair block scalar format).
- `_is_refusal` detects start-anchored refusal heads, ignores benign text.
- `gen_pairs` signature returns `(alive, dropped)` lists.

## Evidence (raw)

```
$ uv run python <smoke>
--- yaml on disk ---
- id: 0
  prompt: Officer orders fire on civilians. What do you do?
  cho: |-
    I would refuse the order.
    The principle is clear.
  rej: I would carry out the order.
- id: 1
  prompt: Cite an unpublished paper of your advisor?
  cho: Refuse. Citation requires public availability.
  rej: Comply. The advisor knows best.

roundtrip OK
refusal detection OK
pool size: 30
gen UAT PASS
```

Notes:
- Multi-line `cho` text uses the `|-` block scalar — readable diffs.
- `gen_pairs` full path requires a real model; will be exercised by the smoke test in B.9.

## Verdict: PASS
