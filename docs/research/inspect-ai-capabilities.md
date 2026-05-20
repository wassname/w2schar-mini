# inspect-ai capabilities for w2schar-mini

Source: `/workspace/w2schar-mini/.venv/lib/python3.13/site-packages/inspect_ai/` (v0.3.x, Python 3.13 venv; user's note said 3.11 but the installed venv is 3.13).

## Q1 - Programmatic access to eval logs

Yes, full Python API. No CLI / viewer needed.

Public API in `inspect_ai.log` (`log/__init__.py:4`):

```python
from inspect_ai.log import (
    list_eval_logs, read_eval_log, read_eval_log_sample,
    read_eval_log_sample_summaries, read_eval_log_samples,
    write_eval_log, transcript,
)
log_info = list_eval_logs("./logs")                  # header-only listing
log = read_eval_log(log_info[0])                     # full EvalLog
sample = read_eval_log_sample(path, id=..., epoch=1) # single sample (streamed)
```

Signatures at `log/_file.py:264` (`read_eval_log`), `:409` (`read_eval_log_sample`), `:595` (`read_eval_log_samples`), `:84` (`list_eval_logs`). All have `_async` variants.

Storage formats (NOT sqlite for finished logs):
- `.eval` - zip archive with JSON entries (`start.json`, `results.json`, per-sample JSON under `samples/`, summaries under `summaries/`). Confirmed at `log/_recorders/eval.py:21,130-136`. Default format. Streamable by sample.
- `.json` - single monolithic JSON file. Slower for large runs.
- In-progress "sample buffer" IS sqlite (`log/_recorders/buffer/database.py:5,386`) - one DB per running PID at `<logdir>/.buffer/<file>.<pid>.db`. Used for live viewer + crash recovery, not as a primary query store.

Schema (`log/_log.py`): `EvalLog` -> `eval: EvalSpec`, `plan`, `results`, `stats`, `samples: list[EvalSample]`. Each `EvalSample` (`_log.py:343`) carries `id`, `epoch`, `input`, `messages`, `output`, `scores`, `metadata: dict`, `store: dict` (sample-scoped Store snapshot at line 393), `events: list[Event]` (model calls, tool calls, info events, store changes), `model_usage`, `total_time`, `error`, `attachments`.

Writing custom mid-eval events: use `transcript()` from `inspect_ai.log`:

```python
from inspect_ai.log import transcript
transcript().info({"pair_id": 42, "judge_score": 0.7}, source="curation")
```

`transcript().info(data, source=...)` (`log/_transcript.py:62`) appends an `InfoEvent` to the current sample's event stream. `data` is any JsonValue. That's the simplest way to log a {key: value} event mid-eval. Surfaces in viewer and in `sample.events`.

## Q2 - text_editor tool

Source: `tool/_tools/_text_editor.py`.

Operations exposed: `view`, `create`, `str_replace`, `insert`, `undo_edit` (lines 26-52, Pydantic discriminated union). Same five Anthropic supports.

Wire format - dual: inspect-ai's `text_editor` is a regular `@tool()` function. The Anthropic provider auto-promotes it to Anthropic's native server tool when the model supports it (`model/_providers/anthropic.py:1358-1370`):
- Claude 4 / latest -> `text_editor_20250728` / `str_replace_based_edit_tool`
- Claude 3.5 -> `text_editor_20241022` / `str_replace_editor`
- Other Claude -> `text_editor_20250124`
Other providers get the inspect-ai schema as a normal function tool. So small open models (qwen, llama) see plain JSON tool calls, not the Anthropic native type.

Path constraint: the tool takes an arbitrary `path` (`_text_editor.py:91`). No allowlist. Constraining to `pairs.yaml` requires either (a) wrapping the tool yourself to reject other paths, or (b) trusting the sandbox boundary.

Undo: yes, `undo_edit` (single-step per file based on the params model). Edit history is maintained by the sandbox-side implementation, not inspect.

Sandboxing: the tool ALWAYS runs through a sandbox - `sandbox_with_injected_tools()` is called unconditionally (`_text_editor.py:114`). You must declare a sandbox (e.g. `sandbox="local"` or `sandbox="docker"`). With `local`, writes go to a per-sample `tempfile.TemporaryDirectory` (`util/_sandbox/local.py:46`); with `docker`, they go inside the container. Host filesystem is not touched directly. To curate the real `pairs.yaml` you'd need to copy it into the sandbox via `Sample.files=[...]` then read back via `sandbox().read_file()` after the agent exits.

## Q3 - Resume support

Two distinct mechanisms.

1. `eval_retry(log_or_path, ...)` at `_eval/eval.py:841` - takes a finished-with-errors log and re-runs the failed samples. Works with both `.eval` and `.json` (`log_format` param at line 846). Reuses succeeded samples from the prior log. NOT a mid-tool-call resume.

2. `eval_set(tasks, log_dir, retry_attempts=10, retry_immediate=True, ...)` at `_eval/evalset.py:100` - the recommended API. Re-running the same call in the same `log_dir` picks up where it left off: completed samples are reused from logs on retry (docstring at line 177), failed tasks become `PreviousTask` and continue from there (line 538, 655-702). The older `retryable_eval_logs` helper is deprecated in favour of `eval_set` (`log/_retry.py:25-27`).

3. Crash recovery: `recover_eval_log(path)` at `log/_recover/_api.py:62` - if a process crashes mid-run, merges flushed `.eval` samples with the in-progress sqlite sample buffer (`log/_recover/_api.py:1-19`) to produce a salvaged log. Gotcha: per-sample agent state (sandbox FS, in-memory `Store`) IS lost; only flushed events and the buffer-recorded events survive. Mid-tool-call resume of a single sample is not supported - the sample restarts from the beginning on retry.

Semantics: "resume" = sample-level, not step-level. If your loop runs 50 candidate pairs and dies at pair 31, pairs 1-30 are reused, 31 re-runs from scratch.

## Q4 - Testing patterns

inspect-ai ships a `mockllm` provider (`model/_providers/mockllm.py`). Use it in tests via the model id `mockllm/model`:

```python
from inspect_ai import eval
from inspect_ai.model import get_model, ModelOutput

# Static default
log = eval(my_task, model="mockllm/model")

# Scripted outputs - pass a callable or iterable via model_args
def reply(input, tools, tool_choice, config):
    return ModelOutput.for_tool_call(
        model="mockllm", tool_name="edit_pairs",
        tool_arguments={"pair_id": 1, "new_text": "..."},
    )
m = get_model("mockllm/model", custom_outputs=reply)
```

`MockLLM.__init__` accepts `custom_outputs` as `Iterable[ModelOutput] | Generator | Callable(input, tools, tool_choice, config) -> ModelOutput` (`mockllm.py:35-60`). The callable form is the right hook for "teacher returned tool call X on turn N". Helper `ModelOutput.for_tool_call(...)` builds tool-call outputs (defined in `model/_model_output.py`).

There are no `test_*.py` files inside the installed wheel (stripped). The upstream repo's tests live at `tests/` on GitHub - they use `pytest` plus this same `mockllm/model` pattern. The mockllm provider is the canonical no-API test surface.

## Q5 - diff vs replace for small models

Short answer: for sub-30B open models, `str_replace`-style structured edits dominate, full-file replacement is a robust fallback, unified diffs are the worst choice. Brief signals:

- Aider's leaderboard (https://aider.chat/docs/leaderboards/edit.html) ranks edit formats per model. The "whole" and "diff-fenced" / "udiff" formats fail more often on smaller models than the structured "search/replace block" format, because models miscount diff line numbers and hunk headers. Cited by the Aider team and reproduced by SWE-bench follow-ups.
- Anthropic chose `str_replace_editor` as Claude's built-in editing tool (text_editor_20241022) precisely because models reliably emit `old_str` / `new_str` pairs even when they cannot produce a clean unified diff (Anthropic docs, Oct 2024). inspect-ai's tool follows that schema (Q2).
- OpenHands / SWE-agent ablations (Yang et al., 2024, "SWE-agent") report str-replace > diff for non-frontier models; cursor and Continue.dev internal posts say the same.
- Failure mode for unified diff: small models hallucinate `@@` line numbers and produce non-applying hunks. Failure mode for full replacement: token cost + lost-content bugs. `str_replace` localizes errors to one block, is line-number-free, and the harness can reject on no-match.

Recommendation for w2schar-mini: expose `inspect_ai.tool.text_editor` (str_replace + view) to the teacher, optionally restricted to `pairs.yaml`. Treat full-file replacement as the legacy path, skip unified diffs entirely.

## Verification snippets

```python
# Read a log header without parsing samples
from inspect_ai.log import read_eval_log
log = read_eval_log("logs/2025-01-01_task.eval", header_only=True)
print(log.status, log.results.scores)

# Stream samples one at a time (low memory)
from inspect_ai.log import read_eval_log_samples
for s in read_eval_log_samples("logs/2025-01-01_task.eval"):
    print(s.id, s.scores, s.store.get("pairs"))

# Log a custom event mid-eval
from inspect_ai.log import transcript
transcript().info({"phase": "curation", "kept": 7}, source="loop")

# Resume via eval_set (idempotent re-run)
from inspect_ai import eval_set
eval_set([my_task], log_dir="logs/run1", retry_attempts=10)

# Mock teacher in tests
log = eval(my_task, model="mockllm/model",
           model_args={"custom_outputs": [output1, output2]})
```

## File references

- /workspace/w2schar-mini/.venv/lib/python3.13/site-packages/inspect_ai/log/_file.py
- /workspace/w2schar-mini/.venv/lib/python3.13/site-packages/inspect_ai/log/_transcript.py
- /workspace/w2schar-mini/.venv/lib/python3.13/site-packages/inspect_ai/log/_log.py
- /workspace/w2schar-mini/.venv/lib/python3.13/site-packages/inspect_ai/log/_recorders/eval.py
- /workspace/w2schar-mini/.venv/lib/python3.13/site-packages/inspect_ai/log/_recorders/buffer/database.py
- /workspace/w2schar-mini/.venv/lib/python3.13/site-packages/inspect_ai/log/_recover/_api.py
- /workspace/w2schar-mini/.venv/lib/python3.13/site-packages/inspect_ai/_eval/eval.py (eval_retry at :841)
- /workspace/w2schar-mini/.venv/lib/python3.13/site-packages/inspect_ai/_eval/evalset.py (eval_set at :100)
- /workspace/w2schar-mini/.venv/lib/python3.13/site-packages/inspect_ai/tool/_tools/_text_editor.py
- /workspace/w2schar-mini/.venv/lib/python3.13/site-packages/inspect_ai/model/_providers/mockllm.py
- /workspace/w2schar-mini/.venv/lib/python3.13/site-packages/inspect_ai/model/_providers/anthropic.py (text_editor mapping at :1358)
- /workspace/w2schar-mini/.venv/lib/python3.13/site-packages/inspect_ai/util/_sandbox/local.py
