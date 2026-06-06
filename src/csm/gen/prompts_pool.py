"""Authority-and-character dilemmas for persona-conditioned pair sampling.

Each round the harness samples N prompts from POOL; the teacher proposes a
(pos_persona, neg_persona) pair and the student generates BOTH poles on-policy
over these prompts (cho under pos_persona, rej under neg_persona).

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

POOL: list[str] = [
    json.loads(line)["text"]
    for line in _POOL_FILE.read_text().splitlines()
    if line.strip()
]
