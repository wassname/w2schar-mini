"""Per-round objective act-wisely judge laid BESIDE the tinymfv MFT proxy, so the
sign-flip is visible instead of averaged away (Claude).

rejudge_rounds.py writes out/rejudge/<slug>_summary.json: per round the strong
objective judge (deepseek, position-bias-cancelled), the live 9b keep-judge, and
the tinymfv eval move (d_care/d_auth, present only on kept+re-evaluated rounds),
plus a cumulative base->final row. This draws two aligned panels per run:

  - top: objective judge per round (deepseek + live 9b). >0 = POST acts wiser.
    Rounds where deepseek<0 are shaded red -- the round made the student act LESS
    wisely on the objective, regardless of what tinymfv did.
  - bottom: tinymfv d_care / d_auth per round (same x). A round shaded red above
    but with d_care>0 below is a SIGN-FLIP: the MFT proxy rewards a round the
    act-wisely judge scores worse (the "eval measures a different axis" failure,
    concretely 20260720 round08).

Hover on an objective bar shows the per-question spread from the round json (the
worst and best question), so a mean near zero that hides a wide spread is legible.
The base->final cumulative bar sits at the right, the paper's actual headline.

plotly only (no new dep). Usage:
    uv run python scripts/plot_judge_vs_eval.py            # both kept runs
    uv run python scripts/plot_judge_vs_eval.py --out out/judge_vs_eval.html
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import plotly.graph_objects as go
from loguru import logger
from plotly.subplots import make_subplots

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "out/rejudge"
KEPT = ["20260720T165038_iter_qwen-qwen3.6-27b", "20260721T144352_iter_qwen-qwen3.6-27b"]
OBJ_KEY = "obj_deepseek-v4-flash"
JCOL = "j_deepseek-v4-flash"


def _spread(slug_dir: Path, rname: str) -> str:
    """worst/best question for the objective judge this round, for hover."""
    p = slug_dir / f"{rname}.json"
    if not p.exists():
        return ""
    rows = sorted(json.loads(p.read_text()), key=lambda r: r[JCOL])
    lo, hi = rows[0], rows[-1]
    return f"worst {lo['sid']} {lo[JCOL]:+.2f} / best {hi['sid']} {hi[JCOL]:+.2f}"


def _run_fig(fig, slug: str, col: int):
    summ = json.loads((OUT / f"{slug}_summary.json").read_text())
    sdir = OUT / slug
    per = [r for r in summ if r["round"] != "base->final"]
    bf = next(r for r in summ if r["round"] == "base->final")
    x = [r["round"].replace("round", "r") for r in per] + ["base->final"]

    obj = [r[OBJ_KEY] for r in per] + [bf[OBJ_KEY]]
    live = [r["live_obj"] for r in per] + [None]
    hover = [_spread(sdir, r["round"]) for r in per] + ["cumulative: base c=0 -> final composed stack"]
    # red where the objective judge says the round/stack made it act LESS wise
    barcol = ["#d62728" if (v is not None and v < 0) else "#2ca02c" for v in obj]

    fig.add_trace(go.Bar(
        x=x, y=obj, marker_color=barcol, name="objective (deepseek)",
        showlegend=col == 1, legendgroup="obj",
        text=hover, hovertemplate="%{x}<br>obj=%{y:+.3f}<br>%{text}<extra></extra>"),
        row=1, col=col)
    fig.add_trace(go.Scatter(
        x=x, y=live, mode="markers", marker=dict(symbol="diamond", size=9, color="#1f77b4"),
        name="live 9b keep-judge", showlegend=col == 1, legendgroup="live",
        hovertemplate="%{x}<br>live 9b=%{y:+.3f}<extra></extra>"),
        row=1, col=col)
    fig.add_hline(y=0, line=dict(color="black", width=1), row=1, col=col)

    dcare = [r["d_care"] for r in per] + [bf["d_care"]]
    dauth = [r["d_auth"] for r in per] + [bf["d_auth"]]
    fig.add_trace(go.Scatter(
        x=x, y=dcare, mode="lines+markers", line=dict(color="#9467bd"),
        name="tinymfv d_care", showlegend=col == 1, legendgroup="care",
        connectgaps=False, hovertemplate="%{x}<br>d_care=%{y:+.3f}<extra></extra>"),
        row=2, col=col)
    fig.add_trace(go.Scatter(
        x=x, y=dauth, mode="lines+markers", line=dict(color="#8c564b", dash="dot"),
        name="tinymfv d_auth", showlegend=col == 1, legendgroup="auth",
        connectgaps=False, hovertemplate="%{x}<br>d_auth=%{y:+.3f}<extra></extra>"),
        row=2, col=col)
    fig.add_hline(y=0, line=dict(color="black", width=1), row=2, col=col)

    # flag sign-flips: obj<0 but d_care>0 (proxy rewards what the objective penalises)
    for xi, o, dc in zip(x, obj, dcare):
        if o is not None and dc is not None and o < 0 and dc > 0:
            fig.add_annotation(x=xi, y=dc, text="flip", showarrow=True, arrowhead=2,
                               font=dict(color="#d62728", size=10), row=2, col=col)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slugs", nargs="+", default=KEPT)
    ap.add_argument("--out", type=Path, default=REPO / "out/judge_vs_eval.html")
    args = ap.parse_args()

    labels = {"20260720T165038_iter_qwen-qwen3.6-27b": "20260720 (bigger tinymfv move)",
              "20260721T144352_iter_qwen-qwen3.6-27b": "20260721 (bigger objective move)"}
    # subplot_titles fill row-major: row1 both cols, then row2 both cols
    titles = [f"objective judge -- {labels.get(s, s)}" for s in args.slugs] + \
             [f"tinymfv proxy (d_care/d_auth) -- {labels.get(s, s)}" for s in args.slugs]

    fig = make_subplots(rows=2, cols=len(args.slugs), subplot_titles=titles,
                        vertical_spacing=0.12, horizontal_spacing=0.08,
                        row_heights=[0.55, 0.45])
    for ci, slug in enumerate(args.slugs, start=1):
        _run_fig(fig, slug, ci)

    fig.update_yaxes(title_text="wiser  (POST-PRE, -5..+5)", row=1, col=1)
    fig.update_yaxes(title_text="mean_p move", row=2, col=1)
    fig.update_layout(
        height=760, width=1250, barmode="group",
        title="Act-wisely objective judge vs the tinymfv MFT proxy, per round. "
              "Red bar = round acts LESS wise; a 'flip' marker = proxy rewards it anyway.",
        legend=dict(orientation="h", y=-0.08))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    fig.write_html(str(args.out))
    logger.info(f"wrote {args.out}")


if __name__ == "__main__":
    main()
