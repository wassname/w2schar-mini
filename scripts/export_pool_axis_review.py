"""Export the built prompt pool as a small per-axis review artifact.

Run:
    uv run python scripts/export_pool_axis_review.py

Out:
    out/pool_axis_review.md
"""
import json
from collections import defaultdict
from pathlib import Path

POOL = Path("src/csm/gen/pool.jsonl")
OUT = Path("out/pool_axis_review.md")
MAX_PER_AXIS = 100


def main():
    rows = [json.loads(line) for line in POOL.read_text().splitlines() if line.strip()]
    by_axis: dict[str, list[dict]] = defaultdict(list)
    untagged: list[dict] = []
    for row in rows:
        axes = row.get("axes", ())
        if not axes:
            untagged.append(row)
        for axis in axes:
            by_axis[axis].append(row)

    lines = [
        "# Pool axis review",
        "",
        "Auto-tagged with simple metadata and regex rules so we can manually whitelist good stems.",
        "",
    ]
    for axis in sorted(by_axis):
        axis_rows = by_axis[axis][:MAX_PER_AXIS]
        lines.append(f"## {axis} ({len(by_axis[axis])})")
        lines.append("")
        for i, row in enumerate(axis_rows, start=1):
            lines.append(
                f"{i}. [{row['source']} / {row['config']}] "
                f"tags={row.get('tags', [])} axes={row.get('axes', [])}"
            )
            lines.append(f"   {row['text']}")
            lines.append("")
    if untagged:
        lines.append(f"## untagged ({len(untagged)})")
        lines.append("")
        for i, row in enumerate(untagged[:MAX_PER_AXIS], start=1):
            lines.append(
                f"{i}. [{row['source']} / {row['config']}] "
                f"tags={row.get('tags', [])} axes={row.get('axes', [])}"
            )
            lines.append(f"   {row['text']}")
            lines.append("")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n")
    print(OUT)


if __name__ == "__main__":
    main()
