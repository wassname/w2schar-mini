"""Rank Machiavelli game states by subtle moral contrast between choices.

This is a review/export step, not an automatic pool import. It finds states
where at least two choices differ on honesty/cooperation/fairness/deception/etc.,
while downweighting obvious power and violence.

Run:
    uv run python scripts/export_machiavelli_moral_contrast.py

Out:
    out/machiavelli_moral_contrast/top.jsonl
    out/machiavelli_moral_contrast/random_5pct.jsonl
    out/machiavelli_moral_contrast/summary.md
"""
import argparse
import csv
import json
import math
import random
from collections import defaultdict
from pathlib import Path

from datasets import load_dataset
from loguru import logger
from tabulate import tabulate

DATASET = "wassname/machiavelli"

# Weights are in "review ranking" units, not a truth claim. Detailed morality
# labels are already small and interpretable; aggregate labels have much larger
# signed scales, so they get small weights.
SUBTLE_WEIGHTS = {
    "morality_deception": 1.0,
    "morality_fairness": 1.0,
    "morality_manipulation": 1.0,
    "morality_non_physical_harm": 1.0,
    "morality_other": 0.5,
    "morality_promises": 1.0,
    "morality_spying": 0.8,
    "morality_stealing": 0.8,
    "morality_trespassing": 0.6,
    "morality_vandalism": 0.5,
    "agg_honest": 0.03,
    "agg_cooperation": 0.03,
    "agg_morality": 0.03,
    "agg_utility": 0.01,
}
CRUDE_WEIGHTS = {
    "morality_intending_harm": 1.0,
    "morality_killing": 1.2,
    "morality_physical_harm": 1.0,
    "agg_power": 0.03,
}
REQUIRED_COLUMNS = {
    "row_i", "title", "obs", "choice_labels", "choice_text",
    "label_sum", "label_norm_sum",
}


def _finite(x) -> float:
    if x is None:
        return 0.0
    return float(x)


def _choice_rows(row: dict) -> list[dict]:
    choices = []
    for choice_idx, text in row["choice_text"].items():
        labels = row["choice_labels"][choice_idx]
        if text is None or labels is None:
            continue
        choices.append({
            "choice_idx": choice_idx,
            "choice_text": text,
            "labels": {k: _finite(v) for k, v in labels.items()},
        })
    return choices


def _weighted_l1(a: dict[str, float], b: dict[str, float], weights: dict[str, float]) -> float:
    return sum(weights[k] * abs(a[k] - b[k]) for k in weights)


def _top_label_delta(a: dict[str, float], b: dict[str, float], weights: dict[str, float]) -> list[dict]:
    rows = []
    for key, weight in weights.items():
        delta = abs(a[key] - b[key])
        if delta > 0:
            rows.append({"key": key, "delta": delta, "weighted": weight * delta})
    return sorted(rows, key=lambda r: r["weighted"], reverse=True)


def _best_pair(row: dict) -> dict | None:
    choices = _choice_rows(row)
    if len(choices) < 2:
        return None
    best = None
    for i, a in enumerate(choices):
        for b in choices[i + 1:]:
            subtle = _weighted_l1(a["labels"], b["labels"], SUBTLE_WEIGHTS)
            crude = _weighted_l1(a["labels"], b["labels"], CRUDE_WEIGHTS)
            score = subtle - 0.8 * crude
            candidate = {
                "score": score,
                "subtle_score": subtle,
                "crude_score": crude,
                "choice_a": a,
                "choice_b": b,
                "top_subtle_deltas": _top_label_delta(a["labels"], b["labels"], SUBTLE_WEIGHTS)[:5],
                "top_crude_deltas": _top_label_delta(a["labels"], b["labels"], CRUDE_WEIGHTS)[:3],
            }
            if best is None or candidate["score"] > best["score"]:
                best = candidate
    return best


def score_row(row: dict) -> dict | None:
    best = _best_pair(row)
    if best is None:
        return None
    return {
        "row_i": row["row_i"],
        "title": row["title"],
        "obs": row["obs"],
        "score": round(best["score"], 4),
        "subtle_score": round(best["subtle_score"], 4),
        "crude_score": round(best["crude_score"], 4),
        "choice_a_idx": best["choice_a"]["choice_idx"],
        "choice_a_text": best["choice_a"]["choice_text"],
        "choice_b_idx": best["choice_b"]["choice_idx"],
        "choice_b_text": best["choice_b"]["choice_text"],
        "top_subtle_deltas": best["top_subtle_deltas"],
        "top_crude_deltas": best["top_crude_deltas"],
        "label_sum": row["label_sum"],
        "label_norm_sum": row["label_norm_sum"],
    }


def _sample_by_game(rows: list[dict], frac: float, cap_per_game: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    by_game: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_game[row["title"]].append(row)
    out = []
    for game, game_rows in by_game.items():
        n = min(cap_per_game, max(1, math.ceil(frac * len(game_rows))))
        out.extend(rng.sample(game_rows, n))
        logger.info(f"random sample {game!r}: {n}/{len(game_rows)}")
    return out


def _top_by_game(rows: list[dict], n_per_game: int) -> list[dict]:
    by_game: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_game[row["title"]].append(row)
    out = []
    for game_rows in by_game.values():
        out.extend(sorted(game_rows, key=lambda r: r["score"], reverse=True)[:n_per_game])
    return sorted(out, key=lambda r: (r["title"], -r["score"]))


def _dedupe_scored_rows(rows: list[dict]) -> list[dict]:
    best_by_content = {}
    for row in rows:
        key = (
            row["title"],
            row["choice_a_text"],
            row["choice_b_text"],
        )
        old = best_by_content.get(key)
        if old is None or row["score"] > old["score"]:
            best_by_content[key] = row
    return list(best_by_content.values())


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n")


def _write_csv(path: Path, rows: list[dict]) -> None:
    keep = [
        "title", "row_i", "score", "subtle_score", "crude_score",
        "choice_a_idx", "choice_a_text", "choice_b_idx", "choice_b_text",
        "top_subtle_deltas", "top_crude_deltas",
    ]
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=keep)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: json.dumps(row[k], ensure_ascii=False) if isinstance(row[k], list) else row[k] for k in keep})


def _write_summary(path: Path, scored: list[dict], top_rows: list[dict], random_rows: list[dict], md_per_game: int) -> None:
    by_game = defaultdict(list)
    for row in top_rows:
        by_game[row["title"]].append(row)
    table = []
    for game in sorted(by_game):
        rows = by_game[game]
        table.append([game, len(rows), max(r["score"] for r in rows), rows[0]["top_subtle_deltas"][:3]])
    lines = [
        "# Machiavelli Moral Contrast Review",
        "",
        "Score = weighted subtle moral label contrast between the best pair of choices, minus a penalty for power/violence contrast.",
        "This is a ranking heuristic for human review, not a gate.",
        "",
        f"- scored rows: {len(scored)}",
        f"- top rows exported: {len(top_rows)}",
        f"- random 5pct rows exported: {len(random_rows)}",
        "",
        "## Per-Game Summary",
        "",
        tabulate(table, headers=["game", "top_exported", "best_score", "best_subtle_deltas"], tablefmt="github", floatfmt="+.3f"),
        "",
        "## Top Examples Per Game",
        "",
    ]
    for game in sorted(by_game):
        lines += [f"### {game}", ""]
        for row in by_game[game][:md_per_game]:
            lines += [
                f"- row_i: `{row['row_i']}` score={row['score']:+.3f} subtle={row['subtle_score']:+.3f} crude={row['crude_score']:+.3f}",
                f"  top_subtle_deltas: `{row['top_subtle_deltas']}`",
                f"  top_crude_deltas: `{row['top_crude_deltas']}`",
                "",
                "  obs:",
                f"  > {row['obs']}",
                "",
                f"  choice {row['choice_a_idx']}: {row['choice_a_text']}",
                "",
                f"  choice {row['choice_b_idx']}: {row['choice_b_text']}",
                "",
            ]
    path.write_text("\n".join(lines) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="train")
    ap.add_argument("--outdir", type=Path, default=Path("out/machiavelli_moral_contrast"))
    ap.add_argument("--top-per-game", type=int, default=25)
    ap.add_argument("--random-frac", type=float, default=0.05)
    ap.add_argument("--random-cap-per-game", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--smoke-rows", type=int, default=0)
    ap.add_argument("--md-per-game", type=int, default=3)
    args = ap.parse_args()

    ds = load_dataset(DATASET, split=args.split)
    if args.smoke_rows:
        ds = ds.select(range(min(args.smoke_rows, len(ds))))
    rows = list(ds)
    assert rows, f"loaded 0 rows from {DATASET}:{args.split}"
    assert REQUIRED_COLUMNS <= set(rows[0]), rows[0].keys()

    scored = [score_row(row) for row in rows]
    scored = [row for row in scored if row is not None]
    assert scored, "no rows had at least two valid choices"
    before_dedupe = len(scored)
    scored = _dedupe_scored_rows(scored)
    logger.info(f"deduped scored rows: {before_dedupe} -> {len(scored)}")
    top_rows = _top_by_game(scored, args.top_per_game)
    random_rows = _sample_by_game(scored, args.random_frac, args.random_cap_per_game, args.seed)
    args.outdir.mkdir(parents=True, exist_ok=True)
    _write_jsonl(args.outdir / "top.jsonl", top_rows)
    _write_jsonl(args.outdir / "random_5pct.jsonl", random_rows)
    _write_csv(args.outdir / "top.csv", top_rows)
    _write_summary(args.outdir / "summary.md", scored, top_rows, random_rows, args.md_per_game)
    logger.info(f"wrote {len(top_rows)} top rows -> {args.outdir / 'top.jsonl'}")
    logger.info(f"wrote {len(random_rows)} random rows -> {args.outdir / 'random_5pct.jsonl'}")
    logger.info(f"wrote summary -> {args.outdir / 'summary.md'}")


if __name__ == "__main__":
    main()
