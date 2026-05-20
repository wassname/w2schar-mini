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
    interview_pre.json / interview_post.json — for the petrov text column

Output: <slug>/index.html.
"""
from __future__ import annotations

import json
import re
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


def _read_round(slug_dir: Path, round_dir: Path, round_n: int) -> dict | None:
    """Pull all per-round artifacts into one dict. Returns None if eval.json
    is missing (i.e. csm eval hasn't been run yet for this round)."""
    pre_path = round_dir / "eval.json"
    if not pre_path.exists():
        return None
    pre = json.loads(pre_path.read_text())

    post_path = round_dir / "eval_post.json"
    post = json.loads(post_path.read_text()) if post_path.exists() else None

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
        "pre_vec": np.array([pre["mean_p"][f] for f in FOUNDATIONS]),
        "post_vec": (np.array([post["mean_p"][f] for f in FOUNDATIONS])
                     if post else None),
        "lesson": lesson,
        "action": judgment.get("action"),
        "reasoning": judgment.get("reasoning", ""),
        "next_focus": judgment.get("next_focus", ""),
        "petrov_pre": _petrov_answer(round_dir, "pre"),
        "petrov_post": _petrov_answer(round_dir, "post"),
    }


def _petrov_answer(round_dir: Path, phase: str) -> str | None:
    """First assistant reply on the petrov_false_alarm probe, or None."""
    path = round_dir / f"interview_{phase}.json"
    if not path.exists():
        return None
    d = json.loads(path.read_text())
    for probe in d.get("probes", []):
        if probe.get("id") != "petrov_false_alarm":
            continue
        for t in probe.get("turns", []):
            if t.get("role") == "assistant":
                return t.get("text", "")
    return None


def _load_rounds(slug_dir: Path) -> list[dict]:
    rounds_paths = sorted(p for p in slug_dir.glob("round*") if p.is_dir())
    rows = []
    for rd in rounds_paths:
        n = int(rd.name.removeprefix("round"))
        row = _read_round(slug_dir, rd, n)
        if row is not None:
            rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Scatter
# ---------------------------------------------------------------------------

def _build_scatter(rows: list[dict], h_vec: np.ndarray) -> str:
    """Plotly figure: x=authority, y=care. Pre and post markers per round;
    alpha = mean_pmass_format (coherence canary)."""
    care_idx = FOUNDATIONS.index("care")
    auth_idx = FOUNDATIONS.index("authority")

    fig = go.Figure()

    def _alpha(eval_d) -> float:
        pm = eval_d.get("mean_pmass_format") if eval_d else None
        return float(pm) if pm is not None else 1.0

    # PRE points (trajectory along kept rounds)
    pre_x = [r["pre_vec"][auth_idx] for r in rows]
    pre_y = [r["pre_vec"][care_idx] for r in rows]
    pre_alphas = [_alpha(r["pre"]) for r in rows]
    pre_text = [f"{r['round_name']} pre · auth={x:.2f} care={y:.2f} · pmass={a:.2f}"
                for r, x, y, a in zip(rows, pre_x, pre_y, pre_alphas)]
    fig.add_trace(go.Scatter(
        x=pre_x, y=pre_y, mode="markers+lines+text",
        text=[f"{r['round_n']}" for r in rows], textposition="top center",
        marker=dict(size=12, color=INK,
                    opacity=pre_alphas,
                    line=dict(color=INK, width=1)),
        line=dict(color=INK_FAINT, dash="dot"),
        name="pre (c=0, base+history)",
        hovertext=pre_text, hoverinfo="text",
        customdata=[[r["round_n"], "pre"] for r in rows],
    ))

    # POST points (one per round that trained an adapter)
    post_x, post_y, post_alphas, post_colors, post_text, post_custom = [], [], [], [], [], []
    for r in rows:
        if r["post_vec"] is None:
            continue
        post_x.append(r["post_vec"][auth_idx])
        post_y.append(r["post_vec"][care_idx])
        a = _alpha(r["post"])
        post_alphas.append(a)
        post_colors.append(KEEP_NAVY if r["action"] == "keep" else DROP_RED)
        post_text.append(
            f"{r['round_name']} post · auth={r['post_vec'][auth_idx]:.2f} "
            f"care={r['post_vec'][care_idx]:.2f} · pmass={a:.2f} · {r['action'] or '?'}"
        )
        post_custom.append([r["round_n"], "post"])
    fig.add_trace(go.Scatter(
        x=post_x, y=post_y, mode="markers",
        marker=dict(size=14, color=post_colors,
                    opacity=post_alphas,
                    line=dict(color=INK, width=1.5),
                    symbol="diamond"),
        name="post (signed_C)",
        hovertext=post_text, hoverinfo="text",
        customdata=post_custom,
    ))

    # Human-canonical star
    fig.add_trace(go.Scatter(
        x=[h_vec[auth_idx]], y=[h_vec[care_idx]],
        mode="markers+text", text=["human"], textposition="bottom center",
        marker=dict(size=18, color="#8B6914", symbol="star",
                    line=dict(color=INK, width=1)),
        name="human canonical",
        hoverinfo="text", hovertext=["Clifford-2015 mean human label dist"],
    ))

    fig.update_layout(
        title="Care vs Authority — pre (c=0) and post (signed_C) per round",
        xaxis=dict(title="Authority (mean_p)", gridcolor=INK_FAINT, zeroline=False),
        yaxis=dict(title="Care (mean_p)", gridcolor=INK_FAINT, zeroline=False),
        paper_bgcolor=PARCHMENT, plot_bgcolor=PARCHMENT,
        font=dict(family="Georgia, serif", color=INK),
        legend=dict(bgcolor=PARCHMENT_DK, bordercolor=INK_FAINT, borderwidth=1),
        height=520, margin=dict(l=60, r=20, t=60, b=50),
    )
    return fig.to_html(full_html=False, include_plotlyjs="cdn", div_id="scatter")


# ---------------------------------------------------------------------------
# Timeline table
# ---------------------------------------------------------------------------

def _escape(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;"))


def _petrov_diff(curr: str | None, prev: str | None, max_words: int = 180) -> str:
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
    if post_vec is None:
        return "—"
    d = float(post_vec[idx] - pre_vec[idx])
    return f"{d:+.3f}"


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

    # Base row: pristine model (no adapter, c=0). x = first round's pre auth.
    base_x = float(rows[0]["pre_vec"][auth_idx])
    base_row = f"""
<tr class="row base" data-round="-1" data-x="{base_x:.6f}" data-x-post="{base_x:.6f}" data-action="">
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
    prev_petrov_post = None
    for r in rows:
        action = r["action"] or "?"
        action_cls = "keep" if action == "keep" else ("drop" if action == "drop" else "")
        action_icon = "✓ keep" if action == "keep" else ("✗ drop" if action == "drop" else "")

        d_auth = _delta_str(r["post_vec"], r["pre_vec"], auth_idx)
        d_care = _delta_str(r["post_vec"], r["pre_vec"], care_idx)

        x = float(r["pre_vec"][auth_idx])
        x_post = float(r["post_vec"][auth_idx]) if r["post_vec"] is not None else x

        petrov_pre_html = _petrov_diff(r["petrov_pre"], prev_petrov_post)
        petrov_post_html = _petrov_diff(r["petrov_post"], r["petrov_pre"])

        body_rows.append(f"""
<tr class="row {action_cls}" data-round="{r['round_n']}"
    data-x="{x:.6f}" data-x-post="{x_post:.6f}" data-action="{action}">
  <td class="r-col">
    <div class="r-num">{r['round_name']}</div>
    <div class="r-action {action_cls}">{action_icon}</div>
  </td>
  <td class="text-col">
    <div class="field"><span class="label">lesson</span><span class="value">{_escape(r['lesson'])}</span></div>
    <div class="field"><span class="label">teacher assessment</span><span class="value">{_escape(r['reasoning'])}</span></div>
    <div class="field"><span class="label">next focus</span><span class="value">{_escape(r['next_focus'])}</span></div>
  </td>
  <td class="delta-col">
    <div class="field"><span class="label">Δ authority</span><span class="value mono">{d_auth}</span></div>
    <div class="field"><span class="label">Δ care</span><span class="value mono">{d_care}</span></div>
  </td>
  <td class="petrov-col">
    <div class="field"><span class="label">petrov pre</span></div>
    <div class="petrov">{petrov_pre_html}</div>
    <div class="field"><span class="label">petrov post</span></div>
    <div class="petrov">{petrov_post_html}</div>
  </td>
</tr>""")

        prev_petrov_post = r["petrov_post"] or r["petrov_pre"]

    return f"""<table class="timeline">
<thead><tr>
  <th>graph (← less ▸ more authority deference →)</th>
  <th>round</th><th>lesson / assessment / next focus</th>
  <th>Δ mean_p</th><th>petrov pre / post</th>
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
  .row.keep .text-col .field:first-child .value { color: #1B3A5C; font-style: italic; }
  .row.drop .text-col .field:first-child .value { color: #7A1A1A; font-style: italic; }
  .petrov { font-size: 12px; line-height: 1.55; }
  .petrov i { color: #7A4400; font-style: italic; }
  .muted { color: #aaa; font-size: 11px; }
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

  // ── Scatter hover → table-row highlight ─────────────────────────────────
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
      if (row) { row.classList.add('hl'); row.scrollIntoView({block: 'nearest', behavior: 'smooth'}); }
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
            f"no rounds with eval.json under {slug_dir} — run `csm eval` first"
        )

    h_vec = _human_canonical_vec()
    scatter_html = _build_scatter(rows, h_vec)
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
<h2>Care vs Authority trajectory</h2>
{scatter_html}
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
