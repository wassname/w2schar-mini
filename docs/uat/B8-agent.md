# UAT — Phase B.8: agent.py — inspect-ai react with 4 typed tools

## UAT criteria

- `INSPECT_AGENT_DRY_RUN=1 csm agent-run …` builds a Task without making any OpenRouter call.
- Each of the 4 tools (propose_personas, edit_pairs, train, judge) is registered with the react agent.
- A wrong-state tool call returns `"ValidationError: ..."` text to the agent (it does NOT crash the harness).

## Evidence

### Dry-run

```
$ INSPECT_AGENT_DRY_RUN=1 uv run python -c "from csm.agent import run …"
agent-run: DRY_RUN PASS model=openrouter/qwen/qwen3.5-9b slug=/workspace/w2schar-mini/out/iter/uat-test n_rounds=1
```

### Wrong-state error surfacing

```
$ uv run python <smoke that forces state=judge then calls propose>
propose_personas while state=judge:
  ValidationError: tool 'propose_personas' requires state='propose', but current state is 'judge'. Next valid action: judge.
OK
```

The error string is what the agent will see as its tool result — it
names the next valid action and the current state, so the on_continue
nudge can repeat it consistently.

## Verdict: PASS

End-to-end agent ↔ teacher exchange gated by Phase C (real smoke).
