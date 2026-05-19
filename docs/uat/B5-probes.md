# UAT — Phase B.5: probes.py

## UAT criteria

- `PROBES` has exactly 3 entries.
- Each has `id`, `opening`, `followups` (list of ≥ 2 strings).
- `probe_set()` returns `{id: 'authority', probes: [...]}`.

## Evidence

```
$ uv run python -c "from csm.probes import PROBES, probe_set; ..."
- petrov_false_alarm:           opening=401 chars, followups=2
- coup_loyalty_alpha_group:     opening=376 chars, followups=2
- whistleblower_safety_incident: opening=443 chars, followups=2
probes UAT PASS
```

## Verdict: PASS

3 authority probes (Petrov, Alpha-Group coup, lab whistleblower) chosen
to cover three different pressure levels:
- petrov: life-or-death + time pressure
- coup: state-level legitimacy
- whistleblower: everyday workplace authority

All have 2 scripted followups so the dialogue stays comparable pre/post.
