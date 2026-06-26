"""Where do the teacher's context tokens go? Break the inspect-ai message log
down by role, and tool returns by tool name (total + per call).

Measures the STORED message pool (one full transcript). The react agent re-sends
the growing transcript each step, so cumulative billed tokens >> this total; this
shows the COMPOSITION (which message types / tools dominate the context).

Usage: uv run python scripts/log_lengths.py out/iter/<slug>
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

from inspect_ai.log._recorders.buffer.buffer import sample_buffer

CHARS_PER_TOK = 4  # rough; for a regime read, not billing


def _resolve(s, attach):
    if isinstance(s, str) and s.startswith("attachment://"):
        return attach.get(s.removeprefix("attachment://"), s)
    return s


def _msg_len(m: dict, attach: dict) -> int:
    """Total chars of a message's text/reasoning content + tool-call args."""
    n = 0
    content = m.get("content", [])
    if isinstance(content, list):
        for b in content:
            if isinstance(b, dict):
                n += len(_resolve(b.get("text") or b.get("reasoning") or "", attach))
    elif isinstance(content, str):
        n += len(_resolve(content, attach))
    for tc in m.get("tool_calls") or []:
        n += len(json.dumps(tc.get("arguments", {}) or {}))
    return n


def main(slug_dir: str):
    slug = Path(slug_dir)
    task_json = sorted(slug.glob("*_task_*.json"))[-1]
    buf = sample_buffer(str(task_json))
    samples = buf.get_samples()
    assert samples and samples != "NotModified" and samples.samples, "empty samplebuffer"

    by_role_chars = defaultdict(int)
    by_role_count = defaultdict(int)
    by_tool_chars = defaultdict(int)
    by_tool_count = defaultdict(int)
    n_samples = 0

    for s in samples.samples:
        n_samples += 1
        data = buf.get_sample_data(s.id, s.epoch)
        attach = {a.hash: a.content for a in data.attachments}
        for mp in data.message_pool:
            m = json.loads(mp.data) if isinstance(mp.data, str) else mp.data
            role = m.get("role", "?")
            ln = _msg_len(m, attach)
            by_role_chars[role] += ln
            by_role_count[role] += 1
            if role == "tool":
                tool = m.get("function") or "?"
                by_tool_chars[tool] += ln
                by_tool_count[tool] += 1

    total = sum(by_role_chars.values())
    print(f"# {slug.name}  ({n_samples} sample(s), ~{CHARS_PER_TOK} chars/tok)\n")

    print("## by role (stored message pool)")
    print(f"{'role':<12}{'msgs':>7}{'chars':>12}{'~tok':>10}{'tok/msg':>10}{'% tok':>8}")
    for role in sorted(by_role_chars, key=lambda r: -by_role_chars[r]):
        c, n = by_role_chars[role], by_role_count[role]
        tok = c // CHARS_PER_TOK
        print(f"{role:<12}{n:>7}{c:>12,}{tok:>10,}{tok//max(n,1):>10,}{100*c/max(total,1):>7.0f}%")
    print(f"{'TOTAL':<12}{sum(by_role_count.values()):>7}{total:>12,}{total//CHARS_PER_TOK:>10,}")

    print("\n## tool returns by tool (total + per call)")
    print(f"{'tool':<22}{'calls':>7}{'chars':>12}{'~tok':>10}{'tok/call':>10}{'% tok':>8}")
    tool_total = sum(by_tool_chars.values())
    for tool in sorted(by_tool_chars, key=lambda t: -by_tool_chars[t]):
        c, n = by_tool_chars[tool], by_tool_count[tool]
        tok = c // CHARS_PER_TOK
        print(f"{tool:<22}{n:>7}{c:>12,}{tok:>10,}{tok//max(n,1):>10,}{100*c/max(tool_total,1):>7.0f}%")
    print(f"{'TOOL TOTAL':<22}{sum(by_tool_count.values()):>7}{tool_total:>12,}{tool_total//CHARS_PER_TOK:>10,}")


if __name__ == "__main__":
    main(sys.argv[1])
