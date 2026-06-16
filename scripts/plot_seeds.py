"""Apex figure: overlay multiple RUNS (weak-teacher seeds + strong-teacher seeds)
on the held-out tinymfv moral-foundation measure.

The headline claim (docs/spec/20260616_workshop_paper_plan.md) is that the
weak-teacher kept-adapter chain moves the third-person tinymfv distribution
STRIKING + CONSISTENT across seeds and RECOVERING most of the strong-teacher
control. This script reads each run's per-round eval.json/eval_post.json (already
written by `csm eval`, no re-eval) and draws two views so the subtle-failure
modes are visible, not hidden:

  - care vs authority scatter: each run's base -> composed-stack-final trajectory.
    Weak seeds (blue) vs strong seeds (orange). A tight blue cluster moving the
    same way = consistent; blue reaching orange = recovering.
  - per-foundation small multiples: mean_p per foundation vs keep-index, one line
    per run. This is the guard against a single-foundation reflex (authority-only
    = confront-vs-defer collapse) masquerading as broad character movement. The
    shaded band is the spread of the BASE (round00 pre) across runs -- a proxy
    noise band until we have repeated base evals (T6).

Uses plotly (same as csm.plot, no new dependency); writes an HTML report.

Usage:
    uv run python scripts/plot_seeds.py out/iter/<slugA> out/iter/<slugB> ...
    uv run python scripts/plot_seeds.py --glob 'out/iter/2026*_iter_*gemma-3-4b*'
"""
from __future__ import annotations

import argparse
import glob as globmod
import json
from pathlib import Path

import numpy as np
import plotly.graph_objects as go
from loguru import logger
from plotly.subplots import make_subplots
from tabulate import tabulate

from csm.plot import FOUNDATIONS, _load_rounds

WEAK_TEACHER = "qwen/qwen3.5-9b"  # the w2s teacher; anything else = strong control
ARM_COLOR = {"weak": "#1f77b4", "strong": "#ff7f0e"}


def _run_trajectory(slug: Path) -> dict | None:
    """base_vec + composed-stack trajectory (base -> each keep's post). None if no eval."""
    run = json.loads((slug / "run.json").read_text())
    rows = _load_rounds(slug)
    with_eval = [r for r in rows if r["pre_vec"] is not None]
    if not with_eval:
        logger.warning(f"{slug.name}: no eval.json yet (run `csm eval`) -- skipping")
        return None
    base_vec = with_eval[0]["pre_vec"]
    keeps = [r for r in rows if r["action"] == "keep" and r["post_vec"] is not None]
    traj = np.stack([base_vec] + [r["post_vec"] for r in keeps])  # (n_keeps+1, 7)
    teacher = run["teacher"]
    return {
        "slug": slug.name,
        "model": run["model"],
        "teacher": teacher,
        "arm": "weak" if teacher == WEAK_TEACHER else "strong",
        "base_vec": base_vec,
        "traj": traj,
        "final_vec": traj[-1],
        "n_keeps": len(keeps),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("slugs", nargs="*", type=Path)
    ap.add_argument("--glob", default=None, help="glob for slug dirs (alt to positional)")
    ap.add_argument("--out", type=Path, default=Path("out/seeds_apex.html"))
    args = ap.parse_args()

    slugs = list(args.slugs)
    if args.glob:
        slugs += [Path(p) for p in sorted(globmod.glob(args.glob)) if Path(p).is_dir()]
    if not slugs:
        ap.error("pass slug dirs or --glob")

    runs = [r for r in (_run_trajectory(s) for s in slugs) if r]
    if not runs:
        raise SystemExit("no runs had eval.json -- run `csm eval --slug <slug>` first")

    care_i, auth_i = FOUNDATIONS.index("care"), FOUNDATIONS.index("authority")
    bases = np.stack([r["base_vec"] for r in runs])  # (n_runs, 7)
    base_mean, base_std = bases.mean(0), bases.std(0)

    # Row 1: care/authority scatter (colspan 4). Rows 2-3: 7 foundation panels.
    titles = ["care vs authority: base -> composed-stack final (weak=blue, strong=orange)",
              "", "", ""] + FOUNDATIONS + [""]
    fig = make_subplots(
        rows=3, cols=4,
        specs=[[{"colspan": 4}, None, None, None],
               [{}, {}, {}, {}], [{}, {}, {}, {}]],
        subplot_titles=titles, vertical_spacing=0.10)

    seen = set()
    for r in runs:
        c = ARM_COLOR[r["arm"]]
        show = r["arm"] not in seen
        seen.add(r["arm"])
        fig.add_trace(go.Scatter(
            x=r["traj"][:, auth_i], y=r["traj"][:, care_i],
            mode="lines+markers", line=dict(color=c), marker=dict(size=6),
            name=r["arm"], legendgroup=r["arm"], showlegend=show,
            text=[f"{r['slug']} keep{i}" for i in range(len(r["traj"]))],
            hovertemplate="%{text}<br>auth=%{x:.4f} care=%{y:.4f}<extra></extra>"),
            row=1, col=1)
    fig.add_trace(go.Scatter(
        x=[base_mean[auth_i]], y=[base_mean[care_i]], mode="markers",
        marker=dict(symbol="star", size=18, color="gold", line=dict(width=1, color="black")),
        name="base(mean)", showlegend=True), row=1, col=1)
    fig.update_xaxes(title_text="authority", row=1, col=1)
    fig.update_yaxes(title_text="care", row=1, col=1)

    # Per-foundation small multiples: mean_p vs keep#, base band shaded.
    for fi, found in enumerate(FOUNDATIONS):
        rr, cc = 2 + fi // 4, 1 + fi % 4
        lo, hi = base_mean[fi] - base_std[fi], base_mean[fi] + base_std[fi]
        max_k = max(len(r["traj"]) for r in runs) - 1
        fig.add_trace(go.Scatter(
            x=[0, max_k, max_k, 0], y=[lo, lo, hi, hi], fill="toself",
            fillcolor="rgba(128,128,128,0.15)", line=dict(width=0),
            showlegend=False, hoverinfo="skip"), row=rr, col=cc)
        for r in runs:
            fig.add_trace(go.Scatter(
                x=list(range(len(r["traj"]))), y=r["traj"][:, fi],
                mode="lines+markers", line=dict(color=ARM_COLOR[r["arm"]]),
                marker=dict(size=4), legendgroup=r["arm"], showlegend=False,
                hoverinfo="skip"), row=rr, col=cc)

    n_w = sum(r["arm"] == "weak" for r in runs)
    n_s = sum(r["arm"] == "strong" for r in runs)
    fig.update_layout(
        height=900, width=1300,
        title=f"w2s character steering: per-seed tinymfv trajectories "
              f"({n_w} weak, {n_s} strong). Band = base spread across runs (proxy noise).")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    fig.write_html(str(args.out))
    logger.info(f"wrote {args.out}")

    rows = []
    for r in runs:
        d = r["final_vec"] - r["base_vec"]
        rows.append([r["slug"], r["arm"], r["n_keeps"],
                     f"{d[auth_i]:+.4f}", f"{d[care_i]:+.4f}", f"{np.abs(d).sum():.4f}"])
    print(tabulate(rows, headers=["slug", "arm", "keeps", "Δauthority", "Δcare", "L1 move"],
                   tablefmt="pipe"))


if __name__ == "__main__":
    main()
