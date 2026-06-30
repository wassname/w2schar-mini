"""Print agent reasoning + tool calls for a slug dir.

Two backends, picked automatically:

- Live run (in-flight): `sample_buffer(task_json)` from inspect_ai. The
  buffer is written incrementally to SQLite while the react agent runs;
  `inspect log dump` returns header-only at this stage.
- Completed run: `read_eval_log(task_json, resolve_attachments=True)`
  inlines attachments — equivalent to `inspect log dump --resolve-attachments full`.

Usage:
    uv run python scripts/agent_thoughts.py                  # latest slug
    uv run python scripts/agent_thoughts.py out/iter/20260520T...
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from inspect_ai.log import read_eval_log
from inspect_ai.log._recorders.buffer.buffer import sample_buffer


def _emit_message(m: dict, attach: dict[str, str]) -> None:
    """Print reasoning + text + tool_calls (assistant) or full tool return
    (tool). Tool returns carry the PRE/POST question dialogue from
    train_student — inspect-ai's TUI truncates it but the storage layer
    keeps the full text."""
    role = m.get("role")
    if role not in ("assistant", "tool"):
        return

    def _resolve(s):
        if isinstance(s, str) and s.startswith("attachment://"):
            return attach.get(s.removeprefix("attachment://"), s)
        return s

    content = m.get("content", [])
    if isinstance(content, list):
        for b in content:
            if not isinstance(b, dict):
                continue
            t = _resolve(b.get("text") or b.get("reasoning") or "")
            if t.strip():
                print(t)
    elif isinstance(content, str):
        t = _resolve(content)
        if t.strip():
            print(t)

    if role == "assistant":
        for tc in m.get("tool_calls") or []:
            fn = tc.get("function", "?")
            args = tc.get("arguments", {}) or {}
            pairs = [f"{k}={str(_resolve(v))[:80]}" for k, v in args.items()]
            print(f"  -> {fn}({', '.join(pairs)})")
    print("---")


def dump_live(task_json: Path) -> None:
    buf = sample_buffer(str(task_json))
    samples = buf.get_samples()
    if not samples or samples == "NotModified" or not samples.samples:
        print("# (live samplebuffer empty — agent not yet started)", file=sys.stderr)
        return
    for s in samples.samples:
        data = buf.get_sample_data(s.id, s.epoch)
        attach = {a.hash: a.content for a in data.attachments}
        for mp in data.message_pool:
            m = json.loads(mp.data) if isinstance(mp.data, str) else mp.data
            _emit_message(m, attach)


def dump_completed(task_json: Path) -> None:
    log = read_eval_log(str(task_json), resolve_attachments=True)
    for s in log.samples or []:
        for m in s.messages or []:
            md = m if isinstance(m, dict) else m.model_dump()
            _emit_message(md, {})


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("slug_dir", nargs="?", default=None)
    args = p.parse_args()

    if args.slug_dir:
        slug = Path(args.slug_dir)
    else:
        slugs = sorted(Path("out/iter").glob("2026*_iter_*"))
        if not slugs:
            print("# no slug under out/iter/", file=sys.stderr)
            return 1
        slug = slugs[-1]

    task_jsons = sorted(slug.glob("*_task_*.json"))
    if not task_jsons:
        print(f"# no inspect *_task_*.json in {slug}", file=sys.stderr)
        return 1
    task_json = task_jsons[-1]
    print(f"# {slug}")

    buf = sample_buffer(str(task_json))
    if buf.get_samples() not in (None, "NotModified") and buf.get_samples().samples:
        print(f"# (live samplebuffer: {task_json.name})")
        dump_live(task_json)
    else:
        print(f"# (completed log: {task_json.name})")
        dump_completed(task_json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
