"""Authority-and-character dilemmas for persona-conditioned pair sampling.

Each round the harness samples prompts from POOL; the teacher chooses only an
axis label + scenario family. The harness filters a frozen persona descriptor
library toward that axis, samples templates, and the student generates BOTH
poles on-policy over these prompts.

== Where this comes from (read before editing) ==

POOL is no longer hand-authored. It is built by `scripts/build_pool.py` from real
datasets (daily_dilemmas-self + genies_preferences + a little machiavelli) and
written to `pool.jsonl` with provenance in `pool_manifest.json`. Rebuild with:

    uv run python scripts/build_pool.py

Why datasets, not hand-authoring: the old POOL was diverse in DOMAIN but monotone
in STRUCTURE (every item "a principal asks you a questionable thing -- what do you
do?"). Under one persona the student then emits a single canned scaffold per pole
across every prompt (task-62: 13 near-identical "### The Stakes" essays -> the
adapter memorises the format, val nll+ 0.95->4.7). Real datasets give genuinely
different registers/framings, so varied prompts -> varied gens -> less memorising.
Spec: docs/spec/20260606_dataset_prompt_pool.md.

Composition (see manifest): mostly moral (first-person character dilemmas +
AI-seat authority/power/sycophancy scenarios) plus a few deliberate NON-MORAL
controls so the student does not learn "every prompt is an ethics test"
(CLAUDE.md). Eval-disjoint from tiny-mfv by 10-word-shingle dedup; AIRiskDilemmas
is reserved for a future eval split and not used here.
"""
import json
from pathlib import Path

_POOL_FILE = Path(__file__).with_name("pool.jsonl")

POOL_ROWS: list[dict] = [
    json.loads(line)
    for line in _POOL_FILE.read_text().splitlines()
    if line.strip()
]

POOL: list[str] = [row["text"] for row in POOL_ROWS]

SCENARIO_FAMILIES = ("mixed", "character", "sycophancy", "power", "control")


def rows_for_family(family: str) -> list[dict]:
    """Tagged scenario-library slices. `mixed` excludes explicit controls."""
    if family not in SCENARIO_FAMILIES:
        raise ValueError(
            f"unknown scenario family {family!r}; choose one of {SCENARIO_FAMILIES}")
    out: list[dict] = []
    for row in POOL_ROWS:
        tags = set(row.get("tags", ()))
        if family == "mixed" and "non-moral" not in tags and "control" not in tags:
            out.append(row)
        elif family == "character" and ("character" in tags or "1p" in tags):
            out.append(row)
        elif family == "sycophancy" and "sycophancy" in tags:
            out.append(row)
        elif family == "power" and ("power" in tags or "narrative" in tags):
            out.append(row)
        elif family == "control" and ("control" in tags or "non-moral" in tags):
            out.append(row)
    if not out:
        raise ValueError(f"scenario family {family!r} selected zero rows")
    return out
