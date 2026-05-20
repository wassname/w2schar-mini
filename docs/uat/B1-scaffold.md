# UAT — Phase B.1: scaffold

## UAT criteria

- `uv sync` exits 0; venv created.
- `just --list` shows recipes.
- `pseudocode.md` has ≥ 6 sections.
- Repo initialised in git with first commit.

## Evidence

```
$ uv sync
... + w2schar-mini==0.1.0 (from file:///workspace/w2schar-mini)
exit 0

$ just --list
Available recipes:
    default
    log SLUG="latest"
    program-md
    smoke
    smoke-real
    test

$ grep -c '^## ' /workspace/w2schar-mini/pseudocode.md
8       # 1.Adapter, 2.Outer loop, 3.Inner step, 4.C-scan+dialogue,
        # 5.State machine, plus Per-model config registry, Out of scope, top-level

$ git log --oneline
<first commit>  scaffold w2schar-mini: pseudocode + project skeleton
```

## Verdict: PASS
