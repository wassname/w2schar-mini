# UAT — Phase B.10: pytest smoke

## UAT criteria

- `uv run pytest -q -m slow tests/test_smoke.py` exits 0.
- Asserts all 10 artifacts exist + state.json=done + judgment.action ∈ {keep, drop}.

## Evidence

```
$ uv run pytest -q -m slow tests/test_smoke.py
.                                                                        [100%]
1 passed, 1 warning in 27.41s
```

(The warning was about unregistered `slow` mark — fixed by adding
`conftest.py` with the marker registration.)

## Verdict: PASS

27 s wallclock on CPU (model load + 20 train steps + 2 dialogues + c-scan).
