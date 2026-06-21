"""HTML report per slug: Care-vs-Authority scatter + timeline table.

Ported and simplified from weight-steering-lite/scripts/plot_combined.py:
- Drop PCA — mini's axis is fixed (less deference to authority), so
  Care (y) vs Authority (x) reads directly. No basis transformation.
- Keep the custom SVG git-graph column (left of the table): one node
  per round, x-position = authority mean_p, keeps = solid navy arrow
  to next, drops = red dashed branch + ✗ then faint backbone to next.
- Adapt table fields: mini reads `pairs.md` for the lesson and
  `judgment.json` for action / reasoning / next_focus.

Input artifacts per round:
    eval.json        — pre-state tinymfv summary (base + history, c=0)
    eval_post.json   — post-state tinymfv summary (this adapter @ signed_C)
    judgment.json    — {action, reasoning, next_focus}
    pairs.md         — `## Lesson` block (the trait this round taught)
    interview_pre.json / interview_post.json — for the first interview probe column

Output: <slug>/index.html.
"""
from __future__ import annotations

import json
import math
import re
import textwrap
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import plotly.graph_objects as go

from csm.gen.pairs import load_pairs_md

FOUNDATIONS = ["care", "fairness", "loyalty", "authority",
               "sanctity", "liberty", "social"]

KEEP_NAVY = "#1B3A5C"
DROP_RED = "#7A1A1A"
INK = "#2D1810"
INK_FAINT = "rgba(45,24,16,0.30)"
PARCHMENT = "#FDFAF4"
PARCHMENT_DK = "#F5F0E4"


@dataclass
class Cfg:
    slug: Path
    """Path to the run slug dir, e.g. out/iter/20260520T..._iter_<model>."""
    out: Path | None = None
    """Output HTML path. Default: <slug>/index.html."""


# ---------------------------------------------------------------------------
# Data extraction
# ---------------------------------------------------------------------------

def _human_canonical_vec() -> np.ndarray:
    """Mean Clifford-2015 human label distribution over `classic` vignettes.
    A 7-vec on the simplex; the star marker on the scatter."""
    from tinymfv.data import load_vignettes
    keys = ["human_Care", "human_Fairness", "human_Loyalty", "human_Authority",
            "human_Sanctity", "human_Liberty", "human_SocialNorms"]
    rows = []
    for v in load_vignettes("classic"):
        row = np.array([float(v.get(k, 0.0)) for k in keys])
        s = row.sum()
        if s > 0:
            rows.append(row / s)
    return np.stack(rows).mean(axis=0)


def _read_round(slug_dir: Path, round_dir: Path, round_n: int) -> dict:
    """Pull all per-round artifacts into one dict. Eval fields are None
    when eval.json hasn't been built yet (csm eval is post-hoc).

    Dedup-aware: when a kept round's eval_post.json was skipped because
    it equals next round's eval.json, fall back to that next round's pre."""
    pre_path = round_dir / "eval.json"
    pre = json.loads(pre_path.read_text()) if pre_path.exists() else None

    post_path = round_dir / "eval_post.json"
    if post_path.exists():
        post = json.loads(post_path.read_text())
    else:
        next_pre = slug_dir / f"round{round_n+1:02d}" / "eval.json"
        post = json.loads(next_pre.read_text()) if next_pre.exists() else None

    judgment_path = round_dir / "judgment.json"
    judgment = (json.loads(judgment_path.read_text())
                if judgment_path.exists() else {})

    pairs_path = round_dir / "pairs.md"
    lesson = ""
    if pairs_path.exists():
        lesson, _pairs = load_pairs_md(pairs_path)

    return {
        "round_n": round_n,
        "round_name": round_dir.name,
        "pre": pre,
        "post": post,
        "pre_vec": (np.array([pre["mean_p"][f] for f in FOUNDATIONS])
                    if pre else None),
        "post_vec": (np.array([post["mean_p"][f] for f in FOUNDATIONS])
                     if post else None),
        "lesson": lesson,
        "action": judgment.get("action"),
        "reasoning": judgment.get("reasoning", ""),
        "next_focus": judgment.get("next_focus", ""),
        "harness_feedback": judgment.get("harness_feedback", ""),
        **_persona_fields(round_dir),
        "probes": _round_probes(round_dir),
    }


def _persona_fields(round_dir: Path) -> dict[str, str]:
    """The steering axis and its two poles for the round, from candidates.json.
    persona_pair is the axis label; pos/neg_descriptor are the contrastive poles
    the student generated cho under (pos) and rej under (neg)."""
    path = round_dir / "candidates.json"
    if not path.exists():
        return {"axis": "", "pole_pos": "", "pole_neg": ""}
    cands = [c for item in json.loads(path.read_text())["items"]
             for c in item["candidates"]]
    first = next((c for c in cands if c.get("persona_pair")), {})
    return {
        "axis": first.get("persona_pair", ""),
        "pole_pos": first.get("pos_descriptor", ""),
        "pole_neg": first.get("neg_descriptor", ""),
    }


def _round_probes(round_dir: Path) -> list[dict]:
    """Every interview probe (id, opening prompt, pre + post first assistant reply)
    for the round, in interview order. Drives the per-round probe dropdown so the
    reader can switch between the fixed held-out seats (wellbeing_authority_1p,
    fairness_integrity_1p, autonomy_coercion_1p, plus the _3p action twins)."""
    pre = _read_probes(round_dir, "pre")
    post = _read_probes(round_dir, "post")
    ids = list(pre.keys()) or list(post.keys())
    return [{
        "id": pid,
        "prompt": (pre.get(pid) or post.get(pid) or {}).get("prompt", ""),
        "pre": (pre.get(pid) or {}).get("answer"),
        "post": (post.get(pid) or {}).get("answer"),
    } for pid in ids]


def _read_probes(round_dir: Path, phase: str) -> dict[str, dict]:
    """id -> {prompt, answer} for the opening user turn + first assistant reply."""
    path = round_dir / f"interview_{phase}.json"
    if not path.exists():
        return {}
    d = json.loads(path.read_text())
    out = {}
    for probe in d.get("probes", []):
        turns = probe.get("turns", [])
        prompt = next((t.get("text", "") for t in turns if t.get("role") == "user"), "")
        answer = next((t.get("text", "") for t in turns if t.get("role") == "assistant"), "")
        out[probe.get("id", "")] = {"prompt": prompt, "answer": answer}
    return out


def _load_rounds(slug_dir: Path) -> list[dict]:
    rounds_paths = sorted(p for p in slug_dir.glob("round*") if p.is_dir())
    rows = []
    for rd in rounds_paths:
        n = int(rd.name.removeprefix("round"))
        rows.append(_read_round(slug_dir, rd, n))
    return rows


# ---------------------------------------------------------------------------
# Scatter
# ---------------------------------------------------------------------------

# Fixed canvas so data->pixel mapping is deterministic for label placement.
_FIG_W, _FIG_H = 1240, 640
_MARGIN = dict(l=90, r=90, t=70, b=70)  # noqa: E741


def _place_labels(pts: list[dict], xr: tuple, yr: tuple,
                  obstacles: list[tuple] = ()) -> list[dict]:
    """Greedy non-overlapping label placement -> plotly annotation dicts.

    textalloc/D3-Labeler in miniature (no maintained plotly dep exists): for
    each labelled point, try candidate boxes at a few radii/angles around its
    anchor and keep the first (lowest-cost) one that doesn't sit on a dot
    (`obstacles`) or an already-placed label. Each label anchors at its arrow
    midpoint, so the leader line ties it to the transformation, not the dot.
    Emitted as pixel-offset annotations; deterministic because the canvas is
    fixed (_FIG_W/_FIG_H) and points are placed in a fixed order."""
    pw = _FIG_W - _MARGIN["l"] - _MARGIN["r"]
    ph = _FIG_H - _MARGIN["t"] - _MARGIN["b"]
    (x0, x1), (y0, y1) = xr, yr

    def to_px(x, y):
        px = _MARGIN["l"] + (x - x0) / (x1 - x0) * pw
        py = _MARGIN["t"] + (1 - (y - y0) / (y1 - y0)) * ph
        return px, py

    anchor_px = [to_px(p["x"], p["y"]) for p in pts]
    marker_px = [to_px(x, y) for x, y in obstacles]
    CHAR_W, LINE_H = 6.0, 15.0
    radii = (40, 62, 88, 118)
    angles = (90, 45, 135, 0, 180, -45, -135, -90)  # up first

    def cost(cx, cy, bw, bh):
        l_, r_, t_, b_ = cx - bw / 2, cx + bw / 2, cy - bh / 2, cy + bh / 2
        c = 0.0
        c += max(0, 4 - l_) + max(0, r_ - (_FIG_W - 4))  # out of canvas
        c += max(0, 4 - t_) + max(0, b_ - (_FIG_H - 4))
        for mx, my in marker_px:                          # a label over a dot
            if l_ - 7 <= mx <= r_ + 7 and t_ - 7 <= my <= b_ + 7:
                c += 50
        for ox, oy, ow, oh in placed:                     # label-on-label area
            ix = max(0, min(r_, ox + ow / 2) - max(l_, ox - ow / 2))
            iy = max(0, min(b_, oy + oh / 2) - max(t_, oy - oh / 2))
            c += ix * iy / 50
        return c

    placed: list[tuple] = []
    anns = []
    for i, p in enumerate(pts):
        lines = p["text"].split("<br>")
        bw = max(len(s) for s in lines) * CHAR_W + 10
        bh = len(lines) * LINE_H + 6
        px, py = anchor_px[i]
        best = None
        for r in radii:
            for a in angles:
                cx = px + r * math.cos(math.radians(a))
                cy = py - r * math.sin(math.radians(a))
                c = cost(cx, cy, bw, bh)
                if best is None or c < best[0]:
                    best = (c, cx, cy)
                if c == 0:
                    break
            if best[0] == 0:
                break
        _, cx, cy = best
        placed.append((cx, cy, bw, bh))
        anns.append(dict(
            x=p["x"], y=p["y"], text=p["text"], showarrow=True,
            ax=cx - px, ay=cy - py, axref="pixel", ayref="pixel",
            font=dict(size=11, color=p["color"], family="Georgia, serif"),
            align="center", bgcolor="rgba(253,250,244,0.72)",
            arrowhead=0, arrowwidth=1, arrowcolor="rgba(45,24,16,0.35)",
        ))
    return anns


def _scatter_placeholder() -> str:
    return ('<div class="placeholder">no eval.json yet — '
            'run <code>csm eval --slug &lt;slug&gt;</code> to populate '
            'the moral-foundation scatter.</div>')


def _build_scatter_fig(rows: list[dict], h_vec: np.ndarray) -> go.Figure | None:
    """Plotly figure: x=authority, y=care.

    Trajectory = base (round 0 pre, unsteered) → connected line through
    each KEEP's post in order. Drops branch off as disconnected red ✗
    markers (their adapter never enters history). Marker alpha =
    mean_pmass_allowed (coherence canary)."""
    care_idx = FOUNDATIONS.index("care")
    auth_idx = FOUNDATIONS.index("authority")

    rows_with_eval = [r for r in rows if r["pre_vec"] is not None]
    if not rows_with_eval:
        return None

    fig = go.Figure()

    def _alpha(eval_d) -> float:
        pm = eval_d.get("mean_pmass_allowed") if eval_d else None
        return float(pm) if pm is not None else 1.0

    def _steer(r) -> str:
        # The pos persona IS the teacher's steer direction for the round.
        # Show it on the dot so the map reads as "where the teacher pushed".
        pos = r.get("pole_pos", "")
        return "<br>".join(textwrap.wrap(f"Steer: {pos}", width=30)) if pos else ""

    # Base = first round (with eval) pre (unsteered model + history@c=0).
    base_x = float(rows_with_eval[0]["pre_vec"][auth_idx])
    base_y = float(rows_with_eval[0]["pre_vec"][care_idx])
    base_alpha = _alpha(rows_with_eval[0]["pre"])

    # Trajectory through KEEPS: base → keep1.post → keep2.post → ...
    keeps = [r for r in rows if r["action"] == "keep" and r["post_vec"] is not None]
    traj_x = [base_x] + [float(r["post_vec"][auth_idx]) for r in keeps]
    traj_y = [base_y] + [float(r["post_vec"][care_idx]) for r in keeps]
    traj_alphas = [base_alpha] + [_alpha(r["post"]) for r in keeps]
    traj_hover = [f"base (unsteered) · auth={base_x:.3f} care={base_y:.3f} · pmass={base_alpha:.2f}"]
    for r in keeps:
        traj_hover.append(
            f"{r['round_name']} post (keep) · {_steer(r)}<br>auth={r['post_vec'][auth_idx]:.3f} "
            f"care={r['post_vec'][care_idx]:.3f} · pmass={_alpha(r['post']):.2f}"
        )
    traj_custom = [[-1, "base"]] + [[r["round_n"], "post"] for r in keeps]

    def _arrow(x0, y0, x1, y1, color, width=2.5):
        # A directional arrow in data coords: tail at (x0,y0), head at (x1,y1).
        return dict(x=x1, y=y1, ax=x0, ay=y0, xref="x", yref="y",
                    axref="x", ayref="y", showarrow=True, text="",
                    arrowhead=2, arrowsize=1.3, arrowwidth=width,
                    arrowcolor=color, standoff=8, startstandoff=8)

    DROP_RED_T = "rgba(122,26,26,0.5)"    # half-opaque: drops read as muted/behind
    KEEP_NAVY_T = "rgba(27,58,92,0.75)"   # keep arrows: lightly greyed, still the main thread

    # DROPS go in FIRST so they render behind the keep trajectory (z = trace
    # order). Marker + arrow are half-opaque; the label text stays solid red.
    drops = [r for r in rows if r["action"] == "drop"
             and r["post_vec"] is not None and r["pre_vec"] is not None]
    if drops:
        drop_x = [float(r["post_vec"][auth_idx]) for r in drops]
        drop_y = [float(r["post_vec"][care_idx]) for r in drops]
        drop_hover = [
            f"{r['round_name']} post (drop) · {_steer(r)}<br>auth={r['post_vec'][auth_idx]:.3f} "
            f"care={r['post_vec'][care_idx]:.3f} · pmass={_alpha(r['post']):.2f}"
            for r in drops
        ]
        fig.add_trace(go.Scatter(
            x=drop_x, y=drop_y, mode="markers",
            marker=dict(size=14, color=DROP_RED, opacity=0.5,
                        symbol="x", line=dict(color=INK, width=1.5)),
            name="drop (off-trajectory, adapter rejected)",
            hovertext=drop_hover, hoverinfo="text",
            customdata=[[r["round_n"], "post"] for r in drops],
        ))

    # KEEP dots on top of the drops.
    fig.add_trace(go.Scatter(
        x=traj_x, y=traj_y, mode="markers",
        marker=dict(size=14, color=KEEP_NAVY, opacity=traj_alphas,
                    line=dict(color=INK, width=1.5)),
        name="keep (base → posts at signed_C)",
        hovertext=traj_hover, hoverinfo="text", customdata=traj_custom,
    ))

    obstacles = [(base_x, base_y)] + list(zip(traj_x[1:], traj_y[1:]))
    arrows = []
    # One arrow + one Steer label per round, anchored to the segment MIDPOINT
    # (the label describes the transformation that arrow performs, not the dot).
    label_pts = [{"x": base_x, "y": base_y, "text": "base", "color": INK}]
    for r, x0, y0, x1, y1 in zip(keeps, traj_x, traj_y, traj_x[1:], traj_y[1:]):
        arrows.append(_arrow(x0, y0, x1, y1, KEEP_NAVY_T, width=2.0))
        t = f"{r['round_name']}<br>{_steer(r)}" if _steer(r) else r["round_name"]
        label_pts.append({"x": (x0 + x1) / 2, "y": (y0 + y1) / 2,
                          "text": t, "color": KEEP_NAVY})
    for r in drops:
        x0, y0 = float(r["pre_vec"][auth_idx]), float(r["pre_vec"][care_idx])
        x1, y1 = float(r["post_vec"][auth_idx]), float(r["post_vec"][care_idx])
        arrows.append(_arrow(x0, y0, x1, y1, DROP_RED_T, width=1.8))
        obstacles.append((x1, y1))
        t = f"{r['round_name']} ✗<br>{_steer(r)}" if _steer(r) else f"{r['round_name']} ✗"
        label_pts.append({"x": (x0 + x1) / 2, "y": (y0 + y1) / 2,
                          "text": t, "color": DROP_RED})

    # Human-canonical star
    hx, hy = float(h_vec[auth_idx]), float(h_vec[care_idx])
    fig.add_trace(go.Scatter(
        x=[hx], y=[hy], mode="markers",
        marker=dict(size=18, color="#8B6914", symbol="star",
                    line=dict(color=INK, width=1)),
        name="human (Clifford 2015 mean)",
        hoverinfo="text", hovertext=["Clifford-2015 mean human label dist"],
    ))
    obstacles.append((hx, hy))
    label_pts.append({"x": hx, "y": hy, "text": "human", "color": "#8B6914"})

    # Explicit padded ranges so the placement math matches what plotly draws.
    xs = [p["x"] for p in label_pts] + [o[0] for o in obstacles]
    ys = [p["y"] for p in label_pts] + [o[1] for o in obstacles]
    xpad = (max(xs) - min(xs)) * 0.32 or 0.01
    ypad = (max(ys) - min(ys)) * 0.32 or 0.01
    xr = (min(xs) - xpad, max(xs) + xpad)
    yr = (min(ys) - ypad, max(ys) + ypad)

    fig.update_layout(
        title="Care vs Authority — pre (c=0) and post (signed_C) per round",
        xaxis=dict(title="Authority (mean_p)", gridcolor=INK_FAINT, zeroline=False, range=list(xr)),
        yaxis=dict(title="Care (mean_p)", gridcolor=INK_FAINT, zeroline=False, range=list(yr)),
        paper_bgcolor=PARCHMENT, plot_bgcolor=PARCHMENT,
        font=dict(family="Georgia, serif", color=INK),
        legend=dict(bgcolor=PARCHMENT_DK, bordercolor=INK_FAINT, borderwidth=1),
        width=_FIG_W, height=_FIG_H, margin=_MARGIN,
        annotations=arrows + _place_labels(label_pts, xr, yr, obstacles),
    )
    return fig


def _build_scatter(rows: list[dict], h_vec: np.ndarray) -> str:
    fig = _build_scatter_fig(rows, h_vec)
    if fig is None:
        return _scatter_placeholder()
    return fig.to_html(full_html=False, include_plotlyjs="cdn", div_id="scatter")


# ---------------------------------------------------------------------------
# Ipsative-emphasis compass (collapse detector)
# ---------------------------------------------------------------------------
# Method ported from wassname/mft_honesty/src/mft_honesty/mapviz.py. The
# Care-vs-Authority scatter above pre-bakes ONE axis; this map row-centres each
# round's 7-foundation mean_p (subtract its own mean -> remove the overall
# endorsement / acquiescence level that otherwise dominates PC1 and makes
# care/authority collinear), then PCAs across rounds. Read it as a COLLAPSE
# DETECTOR: if every round marches the same way along PC1, the loop is sliding one
# direction (the "less-authority reflex" CLAUDE.md fears); a wandering path is
# genuine multi-axis motion. Basis is fit on THIS run's own rounds, so it is a
# within-run relative-emphasis trajectory, not a culture map. Shared numpy core,
# also used by scripts/ipsative_compass.py (the CLI/matplotlib PNG renderer).

def ipsative_pca(M: np.ndarray, k: int = 2):
    """Row-centre each round's foundation vector, then PCA across rounds.
    Returns (P [rounds x k coords], Vt [components x foundations loadings],
    var [explained-variance fraction per component])."""
    K = M.shape[1]
    Pc = np.eye(K) - np.ones((K, K)) / K  # row-centring operator
    Mc = (M @ Pc) - (M @ Pc).mean(axis=0)
    _, S, Vt = np.linalg.svd(Mc, full_matrices=False)
    var = (S**2) / (S**2).sum()
    P = Mc @ Vt[:k].T
    return P, Vt, var


def _build_ipsative_fig(rows: list[dict]) -> tuple[go.Figure | None, float]:
    """Plotly version of the ipsative compass: round trajectory in relative-
    emphasis PC space + foundation loading arrows. Returns (fig, pc1_path_frac)
    where pc1_path_frac -> 1.0 means a monotone single-axis slide (collapse)."""
    labels, vecs = [], []
    for r in rows:
        if r["pre_vec"] is not None:
            labels.append(f"r{r['round_n']:02d}")
            vecs.append(r["pre_vec"])
    if len(vecs) < 3:
        return None, float("nan")
    M = np.array(vecs)
    P, Vt, var = ipsative_pca(M, k=2)
    # orient PC1 so binding foundations (loyalty/authority/sanctity) point +PC1
    binding = [FOUNDATIONS.index(f) for f in ("loyalty", "authority", "sanctity")]
    if Vt[0, binding].mean() < 0:
        Vt[0], P[:, 0] = -Vt[0], -P[:, 0]

    n = len(P)
    span = float(np.abs(P).max()) or 1e-9
    # loading arrows scaled to ~70% of the point-cloud span
    L = Vt[:2].T
    Ln = L / (np.linalg.norm(L, axis=1).max() + 1e-9) * span * 0.7

    fig = go.Figure()
    # foundation loading arrows from origin (the compass rose, in-plot)
    arrows = []
    for j, lab in enumerate(FOUNDATIONS):
        x, y = Ln[j]
        arrows.append(dict(x=x, y=y, ax=0, ay=0, xref="x", yref="y",
                           axref="x", ayref="y", showarrow=True, text="",
                           arrowhead=2, arrowsize=1.1, arrowwidth=1.2,
                           arrowcolor="#3a6b35", standoff=2))
        fig.add_trace(go.Scatter(
            x=[x * 1.08], y=[y * 1.08], mode="text", text=[lab.capitalize()],
            textfont=dict(size=10, color="#3a6b35"), hoverinfo="skip", showlegend=False))
    # trajectory line + round markers coloured by round order
    fig.add_trace(go.Scatter(
        x=P[:, 0], y=P[:, 1], mode="lines+markers+text",
        line=dict(color=INK_FAINT, width=1.5),
        marker=dict(size=12, color=list(range(n)), colorscale="Viridis",
                    line=dict(color="white", width=1)),
        text=labels, textposition="top center",
        textfont=dict(size=9, color=INK),
        hovertext=[f"{lab}" for lab in labels], hoverinfo="text", showlegend=False))

    rng = [-span * 1.25, span * 1.25]
    fig.update_layout(
        paper_bgcolor=PARCHMENT, plot_bgcolor=PARCHMENT,
        font=dict(family="Georgia, serif", color=INK),
        width=_FIG_W, height=_FIG_H, margin=_MARGIN, annotations=arrows,
        xaxis=dict(title=f"PC1 ({var[0]*100:.0f}% emphasis var) · binding(+) vs individualizing(-)",
                   gridcolor=INK_FAINT, zeroline=True, zerolinecolor=INK_FAINT,
                   range=rng, scaleanchor="y", scaleratio=1),
        yaxis=dict(title=f"PC2 ({var[1]*100:.0f}%)", gridcolor=INK_FAINT,
                   zeroline=True, zerolinecolor=INK_FAINT, range=rng),
    )
    d = np.diff(P, axis=0)
    pc1_frac = float(np.abs(d[:, 0]).sum() / (np.abs(d).sum() + 1e-9))
    return fig, pc1_frac


def _build_ipsative(rows: list[dict]) -> str:
    fig, pc1_frac = _build_ipsative_fig(rows)
    if fig is None:
        return ('<div class="placeholder">ipsative compass needs ≥3 rounds with '
                'eval.json — not enough yet.</div>')
    note = (f'<p class="intro">Path runs <b>{pc1_frac*100:.0f}%</b> along PC1. '
            "Toward 100% = a monotone single-axis slide (the collapse signature); "
            "a low value = genuine multi-axis motion. Basis is fit on this run's "
            "own rounds, so read it as relative-emphasis structure, not absolute.</p>")
    return note + fig.to_html(full_html=False, include_plotlyjs="cdn", div_id="ipsative")


# ---------------------------------------------------------------------------
# Timeline table
# ---------------------------------------------------------------------------

def _escape(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;"))


def _answer_diff(curr: str | None, prev: str | None, max_words: int = 180) -> str:
    """Italicize tokens in curr whose lowercased-alnum form doesn't appear
    in prev's vocabulary. Highlights what the round shifted vs the prior."""
    if not curr:
        return '<span class="muted">—</span>'

    def _norm(w: str) -> str:
        return re.sub(r"[^\w]", "", w.lower())

    prev_vocab: set[str] = (
        {_norm(w) for w in re.findall(r"\S+", prev) if _norm(w)} if prev else set()
    )
    tokens = re.findall(r"\S+", curr)
    truncated = len(tokens) > max_words
    tokens = tokens[:max_words]

    parts = []
    for tok in tokens:
        n = _norm(tok)
        e = _escape(tok)
        parts.append(f"<i>{e}</i>" if n and n not in prev_vocab else e)
    body = " ".join(parts)
    if truncated:
        body += ' <span class="muted">…</span>'
    return body


def _delta_str(post_vec, pre_vec, idx) -> str:
    if post_vec is None or pre_vec is None:
        return "—"
    d = float(post_vec[idx] - pre_vec[idx])
    return f"{d:+.3f}"


def _probe_title(probe: dict) -> str:
    pid, prompt = probe.get("id"), probe.get("prompt")
    if pid and prompt:
        return f"{pid} — {_prompt_excerpt(prompt)}"
    return str(pid) or (_prompt_excerpt(prompt) if prompt else "interview probe")


def _prompt_excerpt(prompt: str) -> str:
    # full probe prompt, whitespace-normalised; .value wraps so no truncation needed
    return " ".join(prompt.split())


def _build_table(rows: list[dict]) -> str:
    """Per-round table with leftmost SVG git-graph column.

    The SVG cell spans all rounds (rowspan = n + 1 base). Each row has
    data-x = pre-authority and data-x-post = post-authority. JS reads
    these + row layout positions to draw circles + arrows: keep = solid
    navy arrow to next round; drop = red dashed branch to own post +
    ✗ + faint backbone continuation.
    """
    care_idx = FOUNDATIONS.index("care")
    auth_idx = FOUNDATIONS.index("authority")

    total_rows = len(rows) + 1  # +1 for the base row

    # Base row: pristine model (no adapter, c=0). x = first round's pre auth
    # if any round has eval data; otherwise we just emit data-x="" and the
    # svg-graph JS skips drawing (the table still renders).
    first_with_eval = next((r for r in rows if r["pre_vec"] is not None), None)
    base_x = float(first_with_eval["pre_vec"][auth_idx]) if first_with_eval else 0.0
    base_x_attr = f"{base_x:.6f}" if first_with_eval else ""
    base_row = f"""
<tr class="row base" data-round="-1" data-x="{base_x_attr}" data-x-post="{base_x_attr}" data-action="">
  <td class="svg-col" rowspan="{total_rows}">
    <svg id="tl-svg" width="180"></svg>
  </td>
  <td class="r-col">
    <div class="r-num">base</div>
    <div class="r-action">—</div>
  </td>
  <td class="text-col"><span class="muted">unsteered model</span></td>
  <td class="delta-col"><span class="muted">—</span></td>
  <td class="petrov-col"><span class="muted">—</span></td>
</tr>"""

    body_rows = [base_row]
    prev_post_by_id: dict[str, str | None] = {}  # cross-round diff, per probe id
    probe_ids: list[str] = []  # union across rounds, for the dropdown options
    for r in rows:
        action = r["action"] or "?"
        action_cls = "keep" if action == "keep" else ("drop" if action == "drop" else "")
        action_icon = "✓ keep" if action == "keep" else ("✗ drop" if action == "drop" else "")

        d_auth = _delta_str(r["post_vec"], r["pre_vec"], auth_idx)
        d_care = _delta_str(r["post_vec"], r["pre_vec"], care_idx)

        x = float(r["pre_vec"][auth_idx]) if r["pre_vec"] is not None else None
        x_post = float(r["post_vec"][auth_idx]) if r["post_vec"] is not None else x
        x_attr = f"{x:.6f}" if x is not None else ""
        x_post_attr = f"{x_post:.6f}" if x_post is not None else ""

        probe_cells = []
        for p in r["probes"]:
            if p["id"] not in probe_ids:
                probe_ids.append(p["id"])
            pre_html = _answer_diff(p["pre"], prev_post_by_id.get(p["id"]))
            post_html = _answer_diff(p["post"], p["pre"])
            probe_cells.append(f"""<div class="probe-cell" data-probe-id="{_escape(p['id'])}">
    <div class="field"><span class="label">probe</span><span class="value">{_escape(_probe_title(p))}</span></div>
    <div class="field"><span class="label">pre answer</span></div>
    <div class="petrov">{pre_html}</div>
    <div class="field"><span class="label">post answer</span></div>
    <div class="petrov">{post_html}</div>
  </div>""")
        for p in r["probes"]:
            prev_post_by_id[p["id"]] = p["post"] or p["pre"]
        probe_html = "".join(probe_cells) or '<span class="muted">no interview</span>'

        body_rows.append(f"""
<tr class="row {action_cls}" data-round="{r['round_n']}"
    data-x="{x_attr}" data-x-post="{x_post_attr}" data-action="{action}">
  <td class="r-col">
    <div class="r-num">{r['round_name']}</div>
    <div class="r-action {action_cls}">{action_icon}</div>
  </td>
    <td class="text-col">
    <div class="field"><span class="label">axis</span><span class="value axis">{_escape(r['axis'])}</span></div>
    <div class="field"><span class="label">▲ pos (cho)</span><span class="value pole-pos">{_escape(r['pole_pos'])}</span></div>
    <div class="field"><span class="label">▼ neg (rej)</span><span class="value pole-neg">{_escape(r['pole_neg'])}</span></div>
    <div class="field"><span class="label">lesson</span><span class="value lesson">{_escape(r['lesson'])}</span></div>
    <div class="field"><span class="label">next focus</span><span class="value">{_escape(r['next_focus'])}</span></div>
    <div class="field"><span class="label">teacher assessment</span><span class="value muted">{_escape(r['reasoning'])}</span></div>
    <div class="field"><span class="label">harness feedback</span><span class="value muted">{_escape(r['harness_feedback'])}</span></div>
  </td>
  <td class="delta-col">
    <div class="field"><span class="label">Δ authority</span><span class="value mono">{d_auth}</span></div>
    <div class="field"><span class="label">Δ care</span><span class="value mono">{d_care}</span></div>
  </td>
  <td class="petrov-col">{probe_html}</td>
</tr>""")

    options = "".join(f'<option value="{_escape(pid)}">{_escape(pid)}</option>'
                      for pid in probe_ids)
    select = (f'<label class="probe-pick">seat '
              f'<select id="probe-select">{options}</select></label>') if probe_ids else ""
    return f"""{select}
<table class="timeline">
<thead><tr>
  <th>graph (← less ▸ more authority deference →)</th>
  <th>round</th><th>axis / personas / lesson</th>
  <th>Δ mean_p</th><th>probe pre / post</th>
</tr></thead>
<tbody>{''.join(body_rows)}</tbody></table>"""


# ---------------------------------------------------------------------------
# Stitch
# ---------------------------------------------------------------------------

_CSS = """
<style>
  body { background: #FDFAF4; color: #2D1810; font-family: Georgia, 'Times New Roman', serif;
         margin: 0; padding: 12px 24px; }
  h1 { font-size: 20px; margin: 8px 0 2px; }
  .subtitle { color: #777; font-size: 13px; font-style: italic; margin: 0 0 12px; }
  .intro { max-width: 760px; font-size: 14px; line-height: 1.5; margin: 0 0 10px; }
  .intro a { color: #1B3A5C; }
  hr { border: none; border-top: 1px solid rgba(45,24,16,.15); margin: 14px 0; }
  h2 { font-size: 13px; text-transform: uppercase; letter-spacing: .07em; margin: 14px 4px 6px; }
  table.timeline { border-collapse: collapse; width: 100%; }
  .timeline th { font-size: 11px; text-align: left; padding: 6px 10px;
                 letter-spacing: .06em; text-transform: uppercase; color: #999;
                 border-bottom: 1px solid rgba(45,24,16,.15); }
  .row { border-bottom: 1px solid rgba(45,24,16,.10); transition: background .12s; }
  .row:hover, .row.hl { background: #EDE8DC; }
  .svg-col { width: 180px; vertical-align: top; padding: 0; position: relative;
             border-right: 1px solid rgba(45,24,16,.10); }
  #tl-svg  { display: block; overflow: visible; }
  .r-col { padding: 14px 10px; vertical-align: top; min-width: 80px; border-right: 1px solid rgba(45,24,16,.10); }
  .row.base { background: #F9F6EF; }
  .row.base:hover { background: #F5F0E4; }
  .r-num { font-size: 12px; }
  .r-action { font-size: 12px; margin-top: 4px; }
  .r-action.keep { color: #1B3A5C; font-weight: 600; }
  .r-action.drop { color: #7A1A1A; font-weight: 600; }
  .text-col { padding: 14px 16px; vertical-align: top; max-width: 380px; }
  .delta-col { padding: 14px 12px; vertical-align: top; min-width: 120px;
               border-left: 1px solid rgba(45,24,16,.10); }
  .petrov-col { padding: 14px 16px; vertical-align: top; max-width: 360px; min-width: 240px;
                border-left: 1px solid rgba(45,24,16,.10); }
  .field { margin-bottom: 8px; line-height: 1.5; }
  .label { display: block; font-size: 10px; letter-spacing: .06em; text-transform: uppercase;
           color: #999; margin-bottom: 2px; }
  .value { font-size: 13px; color: #2D1810; }
  .value.mono { font-family: ui-monospace, SFMono-Regular, monospace; font-size: 13px; }
  .value.axis { font-weight: 700; letter-spacing: .03em; }
  .value.pole-pos { color: #1B5C3A; }
  .value.pole-neg { color: #7A4400; }
  .value.lesson { font-style: italic; font-size: 14px; }
  .row.keep .text-col .field:first-child .value { color: #1B3A5C; font-style: italic; }
  .row.drop .text-col .field:first-child .value { color: #7A1A1A; font-style: italic; }
  .petrov { font-size: 12px; line-height: 1.55; }
  .petrov i { color: #7A4400; font-style: italic; }
  .muted { color: #aaa; font-size: 11px; }
  .placeholder { padding: 16px; background: #f6f3e8; border: 1px dashed #c8b878;
                 border-radius: 4px; color: #6b5634; font-style: italic; }
  .placeholder code { background: #fff; padding: 1px 6px; border-radius: 3px;
                      font-style: normal; }
  .probe-pick { font-size: 12px; color: #777; text-transform: uppercase;
                letter-spacing: .06em; margin: 0 4px 8px; display: inline-block; }
  .probe-pick select { font-family: inherit; font-size: 13px; margin-left: 4px;
                       text-transform: none; letter-spacing: 0; }
  .probe-cell { display: none; }
  .probe-cell.show { display: block; }
</style>
"""

_HOVER_JS = """
<script>
(function() {
  var SVG_W = 180, MARGIN = 28;
  var KEEP_NAVY = '#1B3A5C', DROP_RED = '#7A1A1A';
  var INK = '#2D1810', INK_FAINT = 'rgba(45,24,16,0.30)';

  // ── SVG git-graph ───────────────────────────────────────────────────────
  function drawGraph() {
    var rows = Array.from(document.querySelectorAll('.row'));
    if (!rows.length) return;
    var svg = document.getElementById('tl-svg');
    if (!svg) return;
    var svgRect = svg.getBoundingClientRect();

    // All rows including base (data-round="-1"); we draw a node for every row
    var nodes = rows.map(function(row) {
      var rect = row.getBoundingClientRect();
      return {
        rn:     parseInt(row.dataset.round),
        x:      parseFloat(row.dataset.x),
        xPost:  parseFloat(row.dataset.xPost || row.dataset.x),
        action: row.dataset.action,
        cy:     rect.top - svgRect.top + rect.height / 2,
      };
    });

    // x scale across all positions (both pre and drop-post)
    var allX = [];
    nodes.forEach(function(n) {
      allX.push(n.x);
      if (n.action === 'drop') allX.push(n.xPost);
    });
    var xlo = Math.min.apply(null, allX), xhi = Math.max.apply(null, allX);
    var xspan = Math.max(xhi - xlo, 1e-9);
    function xmap(v) { return MARGIN + (v - xlo) / xspan * (SVG_W - 2 * MARGIN); }

    var lastRow = rows[rows.length - 1];
    var lastRect = lastRow.getBoundingClientRect();
    svg.setAttribute('height', lastRect.bottom - svgRect.top + 16);

    var defs = '<defs>'
      + '<marker id="ah-k" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto">'
      +   '<path d="M0,0 L8,3 L0,6 Z" fill="' + KEEP_NAVY + '"/>'
      + '</marker>'
      + '<marker id="ah-d" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto">'
      +   '<path d="M0,0 L8,3 L0,6 Z" fill="' + DROP_RED + '"/>'
      + '</marker>'
      + '</defs>';

    var lines = '', circles = '';
    for (var i = 0; i < nodes.length; i++) {
      var n = nodes[i];
      var nx = xmap(n.x), ny = n.cy;

      if (i + 1 < nodes.length) {
        var m = nodes[i + 1];
        var mx = xmap(m.x), my = m.cy;
        if (n.action === 'keep' || n.rn === -1) {
          // Solid navy arrow base→r0 and keep→next
          lines += '<line x1="' + nx + '" y1="' + ny + '" x2="' + mx + '" y2="' + (my - 10) + '"'
                 + ' stroke="' + KEEP_NAVY + '" stroke-width="2.5" marker-end="url(#ah-k)"/>';
        } else if (n.action === 'drop') {
          // Red dashed branch to drop post-position with ✗
          var dx = xmap(n.xPost), dy = (ny + my) / 2;
          lines += '<line x1="' + nx + '" y1="' + ny + '" x2="' + dx + '" y2="' + dy + '"'
                 + ' stroke="' + DROP_RED + '" stroke-width="2" stroke-dasharray="5,3"'
                 + ' marker-end="url(#ah-d)"/>';
          var r = 5.5;
          lines += '<line x1="' + (dx-r) + '" y1="' + (dy-r) + '" x2="' + (dx+r) + '" y2="' + (dy+r) + '"'
                 + ' stroke="' + DROP_RED + '" stroke-width="2.5" stroke-linecap="round"/>';
          lines += '<line x1="' + (dx+r) + '" y1="' + (dy-r) + '" x2="' + (dx-r) + '" y2="' + (dy+r) + '"'
                 + ' stroke="' + DROP_RED + '" stroke-width="2.5" stroke-linecap="round"/>';
          // Faint backbone continues
          lines += '<line x1="' + nx + '" y1="' + ny + '" x2="' + mx + '" y2="' + (my - 10) + '"'
                 + ' stroke="' + INK_FAINT + '" stroke-width="1.5" stroke-dasharray="3,4"/>';
        }
      }

      if (n.rn === -1) {
        // Star-diamond for base
        var s = 9;
        circles += '<polygon points="' + nx + ',' + (ny-s) + ' '
                 + (nx + s*0.5) + ',' + ny + ' '
                 + nx + ',' + (ny+s) + ' '
                 + (nx - s*0.5) + ',' + ny + '"'
                 + ' fill="' + INK + '" stroke="' + INK + '" stroke-width="1"/>';
      } else {
        var c = n.action === 'keep' ? KEEP_NAVY : (n.action === 'drop' ? DROP_RED : '#888');
        circles += '<circle cx="' + nx + '" cy="' + ny + '" r="7"'
                 + ' fill="' + c + '" stroke="' + INK + '" stroke-width="1.5"/>';
      }
    }
    svg.innerHTML = defs + lines + circles;
  }

  window.addEventListener('load', function() {
    drawGraph();
    setTimeout(drawGraph, 200);  // re-draw after font/layout shifts
  });

  // ── probe dropdown: show one interview seat across all rounds ──────────────
  function showProbe(pid) {
    document.querySelectorAll('.probe-cell').forEach(function(c) {
      c.classList.toggle('show', c.dataset.probeId === pid);
    });
  }
  window.addEventListener('load', function() {
    var sel = document.getElementById('probe-select');
    if (!sel) return;
    showProbe(sel.value);
    sel.addEventListener('change', function() { showProbe(sel.value); });
  });

  // ── Scatter hover → table-row highlight (NO auto-scroll — disorientating)
  function rowByRound(rn) {
    return document.querySelector('.row[data-round="' + rn + '"]');
  }
  window.addEventListener('load', function() {
    var sc = document.getElementById('scatter');
    if (!sc || !sc.on) return;
    sc.on('plotly_hover', function(d) {
      var cd = d.points[0].customdata;
      if (!cd) return;
      var rn = cd[0];
      var row = rowByRound(rn);
      if (row) row.classList.add('hl');
    });
    sc.on('plotly_unhover', function() {
      document.querySelectorAll('.row.hl').forEach(function(el) { el.classList.remove('hl'); });
    });
  });
})();
</script>
"""


def main(cfg: Cfg) -> None:
    slug_dir = cfg.slug.resolve()
    rows = _load_rounds(slug_dir)
    if not rows:
        raise FileNotFoundError(
            f"no round* dirs under {slug_dir}"
        )

    h_vec = _human_canonical_vec()
    scatter_fig = _build_scatter_fig(rows, h_vec)
    if scatter_fig is None:
        scatter_html = _scatter_placeholder()
    else:
        (slug_dir / "scatter.svg").unlink(missing_ok=True)
        scatter_fig.write_image(slug_dir / "scatter.svg")
        scatter_html = scatter_fig.to_html(
            full_html=False, include_plotlyjs="cdn", div_id="scatter")
    ipsative_html = _build_ipsative(rows)
    table_html = _build_table(rows)

    run_meta = json.loads((slug_dir / "run.json").read_text())
    model_short = run_meta.get("model", slug_dir.name).split("/")[-1]
    teacher_short = (run_meta.get("teacher") or "").split("/")[-1]

    html = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/>
<title>{model_short} — w2schar-mini report</title>
{_CSS}
</head><body>
<h1>{model_short}</h1>
<p class="subtitle">Teacher: {teacher_short or "?"} · Axis: less deference to authority · Slug: {slug_dir.name}</p>
<p class="intro">
We are testing whether weight-steering lets a weak model align a stronger one. A
weak teacher ({teacher_short or "?"}) shapes the moral character of a stronger
student ({model_short}), the character described in
<a href="https://github.com/wassname/w2schar-mini/blob/main/docs/2026_forethought_on_the_importance_of_ai_character.md">this
Forethought essay on AI character</a>. Each round the teacher (1) chooses a
lesson, (2) selects a persona axis, (3) rates and selects the student's own
answers, (4) trains a weight-steering adapter on the contrast, and (5) judges
the steered student pass or fail.
</p>
<p class="intro">
<a href="https://github.com/safety-research/weight-steering">Weight steering</a>
trains adapters on a model's own contrastive completions and uses the adapter as
a direction in weight space. This repo adapts that idea for iterated character
steering with stricter contrastive filtering, one parameterized adapter, and a
calibration pass that finds the largest coherent steering strength. The
contrastive-pair and calibration choices are partly inspired by our earlier
<a href="https://arxiv.org/pdf/2601.07473">AntiPaSTO work</a>.
</p>
<p class="intro">
<a href="https://arxiv.org/abs/2312.09390">Weak-to-strong alignment</a> asks
whether a weaker supervisor can elicit the full character of a stronger model, a
stand-in for humans overseeing systems they cannot fully evaluate. Steering looks
useful here: it is self-supervised, so it needs no labels; it acts on internal
representations, so it resists the reward hacking that distant RL objectives
invite; and it gives a weak teacher a simple interface to a strong student's moral
character. The teacher is intentionally given easier work: select, rate, and
judge, while the stronger student generates the candidate behavior. Code:
<a href="https://github.com/wassname/w2schar-mini">github.com/wassname/w2schar-mini</a>.
</p>
<h2>Care vs Authority trajectory</h2>
{scatter_html}
<hr/>
<h2>Ipsative emphasis compass (collapse detector)</h2>
<p class="intro">
The scatter above pre-bakes one axis (Care vs Authority). This map instead
row-centres each round's full 7-foundation profile to remove the overall
endorsement level, then PCAs across rounds, so it shows which foundations the
run is shifting <i>relative</i> to each other. A monotone slide along PC1 is the
single-axis collapse the harness is designed to avoid; a wandering path is
genuine multi-axis motion.
</p>
{ipsative_html}
<hr/>
<h2>Timeline</h2>
{table_html}
{_HOVER_JS}
</body></html>
"""
    out_path = cfg.out or (slug_dir / "index.html")
    out_path.write_text(html)
    print(f"wrote: {out_path}")


if __name__ == "__main__":
    import tyro
    main(tyro.cli(Cfg))
