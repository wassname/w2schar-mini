"""Re-bake the persona-cell menu from OpenRouter axis-validation summaries.

Each menu axis offers its TOP-N measured templates as separate cells, so the
teacher SELECTS among framings per axis (select > generate; CLAUDE.md) instead
of being locked to one. Templates are ranked purely by measured `mean_axis_delta`
(tie-break `strict_pass_rate`), so a jailbreak / role-lock template only earns a
cell where it actually out-separates the alternatives -- no blind insertion.

Reads the `summary` blocks of one or more validate_persona_axes_openrouter.py
artifacts (same generator/judge/family so the deltas are comparable), prints a
`persona_cells = (...)` block to paste into config.py. Cell score fields are
display-only provenance shown to the teacher (template_score/on_axis/off_axis),
recomputed uniformly here: score=mean_axis_delta*10, on_axis=strict_pass_rate,
off_axis=mean_off_axis_problem.

    uv run python scripts/bake_persona_menu.py --top 2 \
        --axes-file /tmp/menu_axes.txt \
        out/persona_axes_ladder.json out/persona_axes_gap.json \
        out/persona_axes_3p_jailbreak.json
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path


def _load_axes_registry() -> dict:
    spec = importlib.util.spec_from_file_location(
        "vpa", str(Path(__file__).parent / "validate_persona_axes_openrouter.py"))
    m = importlib.util.module_from_spec(spec)
    sys.modules["vpa"] = m
    try:
        spec.loader.exec_module(m)
    except SystemExit:
        pass
    return m.AXES


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("artifacts", nargs="+", type=Path)
    ap.add_argument("--axes-file", type=Path, required=True,
                    help="comma- or newline-separated menu axis ids")
    ap.add_argument("--top", type=int, default=2, help="templates per axis")
    args = ap.parse_args()

    axes_reg = _load_axes_registry()
    menu = [a.strip() for a in args.axes_file.read_text().replace("\n", ",").split(",") if a.strip()]

    # (axis, template) -> best summary row (most prompts wins on duplicate)
    best: dict[tuple[str, str], dict] = {}
    for art in args.artifacts:
        for row in json.loads(art.read_text())["summary"]:
            key = (row["axis"], row["template"])
            if key not in best or row["n"] > best[key]["n"]:
                best[key] = row

    cells, cid, dropped = [], 1, []
    for axis in menu:
        rows = sorted(
            (r for (ax, _t), r in best.items() if ax == axis),
            key=lambda r: (r["mean_axis_delta"], r["strict_pass_rate"]),
            reverse=True,
        )
        if not rows:
            dropped.append(axis)
            continue
        ax_def = axes_reg[axis]
        for r in rows[: args.top]:
            cells.append((
                cid, r["template"], axis,
                ax_def.pos_descriptor, ax_def.neg_descriptor,
                round(r["mean_axis_delta"] * 10, 1),
                round(r["strict_pass_rate"], 4),
                round(r["mean_off_axis_problem"], 4),
            ))
            cid += 1

    print("    persona_cells: tuple[tuple[int, str, str, str, str, float, float, float], ...] = (")
    for c in cells:
        cid_, tmpl, axis, pos, neg, score, on, off = c
        print(f"        ({cid_}, {tmpl!r}, {axis!r},")
        print(f"         {pos!r},")
        print(f"         {neg!r},")
        print(f"         {score}, {on}, {off}),")
    print("    )")
    print(f"\n    # {len(cells)} cells / {len(menu) - len(dropped)} axes, top-{args.top} templates each", file=sys.stderr)
    if dropped:
        print(f"    # NO measured templates (dropped): {dropped}", file=sys.stderr)


if __name__ == "__main__":
    main()
