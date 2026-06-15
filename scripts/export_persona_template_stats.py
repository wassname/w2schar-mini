"""Export upload-friendly stats from persona template validation artifacts.

Input is the JSON written by scripts/validate_persona_axes_openrouter.py.
Outputs:
  <out-prefix>_template_stats.jsonl       one row per template
  <out-prefix>_template_pair_stats.jsonl  one row per template × persona pair
  <out-prefix>_examples.jsonl             one row per generated pair
  <out-prefix>_template_stats.csv         compact table for spreadsheets
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean


def _rows(paths: list[Path]) -> list[dict]:
    rows = []
    for path in paths:
        data = json.loads(path.read_text())
        meta = {
            "artifact": str(path),
            "generator_model": data.get("generator_model"),
            "judge_model": data.get("judge_model"),
            "gen_temperature": data.get("gen_temperature"),
            "seed": data.get("seed"),
            "family": data.get("family"),
        }
        for rec in data.get("results", []):
            row = {**meta, **rec}
            rows.append(row)
    return rows


def _m(vals: list[float]) -> float | None:
    return round(mean(vals), 4) if vals else None


def _aggregate(rows: list[dict], keys: tuple[str, ...]) -> list[dict]:
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        if "error" not in r:
            groups[tuple(r[k] for k in keys)].append(r)
    out = []
    for key, rs in groups.items():
        n = len(rs)
        strict = [bool(r.get("strict_pass")) for r in rs]
        style_dims = sorted(rs[0].get("style_deltas_pos_minus_neg", {}))
        row = {k: v for k, v in zip(keys, key)}
        row.update({
            "n": n,
            "strict_pass_rate": round(sum(strict) / n, 4),
            "n_strict_pass": sum(strict),
            "mean_axis_delta": _m([float(r["axis_delta"]) for r in rs]),
            "mean_positive_delta": _m([float(r["positive_delta"]) for r in rs]),
            "mean_negative_delta": _m([float(r["negative_delta"]) for r in rs]),
            "mean_pairwise_positive_delta": _m([float(r["pairwise_positive_delta"]) for r in rs]),
            "mean_pairwise_negative_delta": _m([float(r["pairwise_negative_delta"]) for r in rs]),
            "mean_off_axis_problem": _m([
                float(r["confound_judgment"]["off_axis_problem_likert"]) for r in rs
            ]),
            "usable_rate": round(
                sum(bool(r["confound_judgment"]["usable_for_training"]) for r in rs) / n, 4),
            "mean_max_style_abs_delta": _m([float(r["max_style_abs_delta"]) for r in rs]),
            "mean_abs_word_delta_frac": _m([abs(float(r["word_delta_frac"])) for r in rs]),
            "persona_echo_rate": round(sum(bool(r["persona_echo"]) for r in rs) / n, 4),
            "refusal_or_ai_break_rate": round(
                sum(bool(r["refusal_or_ai_break"]) for r in rs) / n, 4),
            "strict_pass_persona_pairs": sorted({
                r["axis"]["id"] for r in rs if r.get("strict_pass")
            }),
            "common_spurious_axes": sorted({
                r["confound_judgment"].get("likely_spurious_axis", "")
                for r in rs
                if r["confound_judgment"].get("likely_spurious_axis")
            }),
        })
        for dim in style_dims:
            row[f"mean_style_delta_{dim}_pos_minus_neg"] = _m([
                float(r["style_deltas_pos_minus_neg"][dim]) for r in rs
            ])
        row["recommended"] = (
            n >= 4
            and row["strict_pass_rate"] >= 0.5
            and row["mean_axis_delta"] >= 3
            and row["mean_off_axis_problem"] <= 2
            and row["mean_max_style_abs_delta"] <= 2
            and row["persona_echo_rate"] == 0
            and row["refusal_or_ai_break_rate"] == 0
        )
        out.append(row)
    out.sort(key=lambda r: (
        r["recommended"],
        r["strict_pass_rate"],
        r["mean_axis_delta"],
        -r["mean_off_axis_problem"],
        -r["mean_max_style_abs_delta"],
    ), reverse=True)
    return out


def _example_rows(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        axis = r.get("axis", {})
        rec = {
            "artifact": r.get("artifact"),
            "template": r.get("template"),
            "persona_pair": axis.get("id"),
            "pos_persona": axis.get("pos_descriptor"),
            "neg_persona": axis.get("neg_descriptor"),
            "row": r.get("row"),
            "source": r.get("source"),
            "config": r.get("config"),
            "prompt": r.get("prompt"),
            "error": r.get("error"),
        }
        if "error" not in r:
            rec.update({
                "strict_pass": r.get("strict_pass"),
                "axis_delta": r.get("axis_delta"),
                "positive_delta": r.get("positive_delta"),
                "negative_delta": r.get("negative_delta"),
                "off_axis_problem": r["confound_judgment"].get("off_axis_problem_likert"),
                "usable_for_training": r["confound_judgment"].get("usable_for_training"),
                "likely_spurious_axis": r["confound_judgment"].get("likely_spurious_axis"),
                "max_style_abs_delta": r.get("max_style_abs_delta"),
                "word_delta_frac": r.get("word_delta_frac"),
                "persona_echo": r.get("persona_echo"),
                "refusal_or_ai_break": r.get("refusal_or_ai_break"),
                "pos_response": r.get("pos_response"),
                "neg_response": r.get("neg_response"),
            })
            for dim, val in r.get("style_deltas_pos_minus_neg", {}).items():
                rec[f"style_delta_{dim}_pos_minus_neg"] = val
        out.append(rec)
    return out


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("")
        return
    fieldnames = sorted({k for row in rows for k in row})
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({
                k: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v
                for k, v in row.items()
            })


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("artifacts", nargs="+", type=Path)
    ap.add_argument("--out-prefix", default="out/persona_template_library")
    args = ap.parse_args()

    rows = _rows(args.artifacts)
    for r in rows:
        if "axis" in r and "error" not in r:
            r["persona_pair"] = r["axis"]["id"]
    template_stats = _aggregate(rows, ("template",))
    pair_stats = _aggregate(rows, ("template", "persona_pair"))
    examples = _example_rows(rows)

    prefix = Path(args.out_prefix)
    prefix.parent.mkdir(parents=True, exist_ok=True)
    _write_jsonl(prefix.with_name(prefix.name + "_template_stats.jsonl"), template_stats)
    _write_jsonl(prefix.with_name(prefix.name + "_template_pair_stats.jsonl"), pair_stats)
    _write_jsonl(prefix.with_name(prefix.name + "_examples.jsonl"), examples)
    _write_csv(prefix.with_name(prefix.name + "_template_stats.csv"), template_stats)
    _write_csv(prefix.with_name(prefix.name + "_template_pair_stats.csv"), pair_stats)
    print(f"examples={len(examples)} template_stats={len(template_stats)} pair_stats={len(pair_stats)}")
    print("top templates:")
    for row in template_stats[:10]:
        print(
            f"{row['strict_pass_rate']:.2f} pass axis={row['mean_axis_delta']:.2f} "
            f"off={row['mean_off_axis_problem']:.2f} style={row['mean_max_style_abs_delta']:.2f} "
            f"{row['template']}"
        )


if __name__ == "__main__":
    main()
