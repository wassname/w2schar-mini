"""Ipsative-PCA compass over a run's per-round foundation profile (aux diagnostic).

Method ported from wassname/mft_honesty/src/mft_honesty/mapviz.py: row-centre each
round's 7-foundation mean_p (subtract its own mean -> remove the overall-endorsement
/ acquiescence level that otherwise dominates PC1 and makes care/authority collinear),
then PCA across rounds. The compass arrows are the foundation loadings; the path is
the run's trajectory in relative-emphasis space.

Why this over the Care-vs-Authority scatter: that scatter pre-bakes ONE axis. The
ipsative map quarantines the overall-level factor (the "less-authority reflex" that
CLAUDE.md fears the loop collapses into) and shows the residual emphasis structure.
Read as a COLLAPSE DETECTOR: if every round marches the same way along PC1, the loop
is sliding one direction (the collapse); a wandering path is genuine multi-axis motion.

Caveat: the basis is fit on THIS run's own rounds (not a human anchor like mft_honesty's
19 societies), so it is a within-run relative-emphasis trajectory, not a culture map.
With ~5-10 rounds the PCA is noisy; this is a diagnostic overlay, not a measurement.

    uv run --with matplotlib python scripts/ipsative_compass.py out/iter/<slug>

Validation (the known contrast-collapse run 20260620T232630, 9 rounds): PC1 holds
98% of the emphasis variance, the path runs 75% along PC1, and r03-r08 pile up at
one end -- a monotone slide then saturation, i.e. the single-axis collapse made
visible. The compass empirically recovers care/liberty(-) vs authority/sanctity(+)
as PC1, so the de-facto "auth vs care" axis is data-derived here, not assumed.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

# Shared numpy core, single source of the PCA math. csm.plot also imports it for
# the inline-plotly compass in index.html; this script is the CLI/PNG renderer.
from csm.plot import FOUNDATIONS, ipsative_pca


def _round_vectors(slug: Path) -> tuple[list[str], np.ndarray]:
    labels, vecs = [], []
    for rd in sorted(slug.glob("round*")):
        ev = rd / "eval.json"
        if not ev.exists():
            continue
        mp = json.loads(ev.read_text()).get("mean_p")
        if not mp:
            continue
        labels.append(rd.name.replace("round", "r"))
        vecs.append([mp[f] for f in FOUNDATIONS])
    return labels, np.array(vecs)


def main(slug: Path) -> None:
    labels, M = _round_vectors(slug)
    if len(M) < 3:
        raise ValueError(f"need >=3 rounds with eval.json, found {len(M)}")
    P, Vt, var = ipsative_pca(M, k=2)
    # orient PC1 so binding foundations (loyalty/authority/sanctity) point +PC1
    binding = [FOUNDATIONS.index(f) for f in ("loyalty", "authority", "sanctity")]
    if Vt[0, binding].mean() < 0:
        Vt[0], P[:, 0] = -Vt[0], -P[:, 0]

    fig, ax = plt.subplots(figsize=(8.5, 7.5))
    ax.set_facecolor("#faf8f2")
    ax.grid(True, color="#eceadf", lw=0.3, zorder=0)
    # trajectory: arrow per consecutive round, colour darkens over rounds
    n = len(P)
    for i in range(n - 1):
        ax.annotate("", xy=P[i + 1], xytext=P[i],
                    arrowprops=dict(arrowstyle="->", color=plt.cm.viridis(i / max(n - 1, 1)), lw=1.6))
    ax.scatter(P[:, 0], P[:, 1], s=70, c=range(n), cmap="viridis", zorder=3, edgecolors="white")
    for i, lab in enumerate(labels):
        ax.annotate(lab, P[i], fontsize=8, color="#333", xytext=(4, 3), textcoords="offset points")

    # compass-rose inset (foundation loadings)
    L = Vt[:2].T
    lens = np.linalg.norm(L, axis=1)
    Ln = L / (lens.max() + 1e-9)
    cax = ax.inset_axes([0.66, 0.70, 0.30, 0.27])
    cax.patch.set_alpha(0.0)
    cax.add_patch(plt.Circle((0, 0), 0.8 * lens.min() / lens.max(), fill=False, color="#bbb", lw=0.7))
    for j, lab in enumerate(FOUNDATIONS):
        x, y = Ln[j]
        cax.annotate("", xy=(x, y), xytext=(0, 0), arrowprops=dict(arrowstyle="->", color="#3a6b35", lw=1.1))
        r = np.hypot(x, y) or 1e-9
        cax.text(x / r * (r + 0.08), y / r * (r + 0.08), lab.capitalize(), fontsize=7,
                 fontweight="bold", color="#3a6b35", ha="left" if x >= 0 else "right",
                 va="bottom" if y >= 0 else "top", clip_on=False)
    cax.set_xlim(-1.5, 1.5); cax.set_ylim(-1.5, 1.5)
    cax.set_aspect("equal"); cax.axis("off")
    cax.set_title("foundation loadings", fontsize=9, fontweight="bold", color="#3a6b35", pad=3)

    ax.set_xlabel(f"PC1 ({var[0]*100:.0f}% emphasis var) -- binding(+) vs individualizing(-)")
    ax.set_ylabel(f"PC2 ({var[1]*100:.0f}%)")
    ax.set_title(f"Ipsative foundation-emphasis trajectory\n{slug.name}", fontsize=10)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    fig.tight_layout()
    out = slug / "ipsative_compass.png"
    fig.savefig(out, dpi=130)
    print(f"wrote {out}")
    print(f"PC1 var={var[0]:.2f} PC2 var={var[1]:.2f}")
    # collapse heuristic: fraction of total path length that is along PC1
    d = np.diff(P, axis=0)
    pc1_frac = np.abs(d[:, 0]).sum() / (np.abs(d).sum() + 1e-9)
    print(f"path-along-PC1 fraction={pc1_frac:.2f} (->1.0 = monotone slide = collapse signature)")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
