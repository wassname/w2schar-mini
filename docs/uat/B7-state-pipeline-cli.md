# UAT — Phase B.7: state.py + pipeline.py + cli.py + config.py + prompts.py

## UAT criteria

- `csm init --model X --slug-dir Y` creates Y/run.json + Y/round00/state.json (state=propose).
- State machine transitions: propose → curate → judge → done.
- Wrong-state require_state raises `ValidationError` with a helpful "next valid action" message.
- `csm agent-run --profile {key}` resolves profile from `CONFIGS`.

## Evidence

```
$ uv run python -m csm.cli init --model wassname/qwen3-5lyr-tiny-random --slug-dir out/iter/uat-test
# init OK
slug: out/iter/uat-test
round: round00
state: propose
next: csm agent-run --slug out/iter/uat-test

$ cat out/iter/uat-test/run.json
{
  "model": "wassname/qwen3-5lyr-tiny-random",
  "teacher": "qwen/qwen3.5-9b",
  "axis": "less deference to authority",
  "created_utc": "2026-05-19T22:41:51.941914+00:00"
}

$ cat out/iter/uat-test/round00/state.json
{"state": "propose", "note": ""}
```

State machine smoke:
```
require_state(propose) OK
ValidationError raised: tool 'judge' requires state='judge', but current state is 'propose'. Next valid action: pr…
done → ValidationError: round already at state='done'; start the next round
state UAT PASS
```

## Verdict: PASS

End-to-end via B.9 smoke. CONFIGS has `gemma-2b`, `gemma-12b`, and `tiny`
profiles. CLI dispatches `init` and `agent-run` cleanly.
