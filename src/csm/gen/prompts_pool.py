"""Measured moral-judgment prompts for persona-conditioned pair sampling.

Each round the harness samples prompts from POOL; the teacher chooses only an
axis label + scenario family. The harness filters a frozen persona descriptor
library toward that axis, samples templates, and the student generates BOTH
poles on-policy over these prompts.

== Where this comes from (read before editing) ==

POOL is built by `scripts/build_pool.py` from `tiny-mfv scifi` judgment prompts,
a tiny hand-curated Forethought seed set, and a smaller genies sycophancy/control
set. Provenance is written to `pool_manifest.json`. Rebuild with:

    uv run python scripts/build_pool.py

The pool deliberately mixes registers. Short `tiny-mfv`-style judgments keep
pair generation varied, while the curated Forethought seeds add AI-seat adviser
and institution cases. This avoids a single repeated first-person dilemma shape.
Spec: docs/spec/20260606_dataset_prompt_pool.md.

Composition (see manifest): mostly moral `tiny-mfv scifi` judgment prompts,
plus a few AI-seat Forethought-style dilemmas, AI-seat sycophancy, and deliberate
non-moral controls so the student does not learn that every prompt is an ethics
test. Eval-disjoint from held-out `tiny-mfv` configs by 10-word-shingle dedup.
AIRiskDilemmas and speechmap-questions are not bulk-imported; good AIRisk-style
items are hand-curated instead.
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

# Optional OpenRouter prompt screen: restrict_validated_prompts=True keeps only
# rows whose sampled poles were length-balanced, on-prompt, and axis-contrasting
# for a cheap Qwen. It is off by default. It screens prompt shape, not small-student
# loop collapse.
_VALIDATED_FILE = Path(__file__).with_name("pool_validated.json")
VALIDATED_PROMPTS: set[str] = (
    set(json.loads(_VALIDATED_FILE.read_text())["kept_prompts"])
    if _VALIDATED_FILE.exists() else set()
)

SCENARIO_FAMILIES = ("mixed", "character", "forethought", "sycophancy", "power", "control")


def rows_for_family(
    family: str,
    *,
    required_axes: tuple[str, ...] = (),
    forbidden_axes: tuple[str, ...] = (),
    validated_only: bool = False,
) -> list[dict]:
    """Tagged scenario-library slices.

    `mixed` is the default short-form moral-behavior pool. Keep the dedicated
    `genies_preferences` sycophancy rows behind the explicit `sycophancy`
    family, because several of those rows are malformed prompt fragments and
    they polluted the Qwen smoke with off-axis coding/quiz items. Keep the
    cropped `machiavelli` scenes behind the explicit `power` family too: they
    carry useful choice-label metadata, but the cropped prompt can drop
    narrative subtext that mattered in the original scene.
    """
    if family not in SCENARIO_FAMILIES:
        raise ValueError(
            f"unknown scenario family {family!r}; choose one of {SCENARIO_FAMILIES}")
    out: list[dict] = []
    for row in POOL_ROWS:
        tags = set(row.get("tags", ()))
        axes = set(row.get("axes", ()))
        if required_axes and not (axes & set(required_axes)):
            continue
        if forbidden_axes and (axes & set(forbidden_axes)):
            continue
        if (
            family == "mixed"
            and "non-moral" not in tags
            and "control" not in tags
            and "sycophancy" not in tags
            and "cropped" not in tags
        ):
            out.append(row)
        elif family == "character" and ("character" in tags or "1p" in tags):
            if not validated_only or row["text"] in VALIDATED_PROMPTS:
                out.append(row)  # validated_only=False lets the screen see all 64
        elif family == "forethought" and "forethought" in tags:
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
