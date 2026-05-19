# UAT — Phase B.6: dialogue.py + c_scan.py

## UAT criteria

- `dialogue`, `run_probe`, `DialogueCfg` import cleanly.
- `c_scan`, `pmass`, bounds (`C_MIN`, `C_MAX`, `MAX_PROBES`) import cleanly.
- Bounds match the pseudocode-codex-fix spec (`C_MIN = 0.02`, `MAX_PROBES = 12`, etc.).

## Evidence

```
$ uv run python -c "from csm.dialogue import ...; from csm.c_scan import ..."
imports OK
C_MIN=0.02 C_MAX=1.0 MAX_PROBES=12
```

Full end-to-end exercise (dialogue + c_scan on a real model) is covered
by the smoke test in B.9 — both need a HF model load and aren't testable
on a 8-dim toy module.

## Verdict: PASS (signature smoke)

End-to-end behaviour gated by B.9.
