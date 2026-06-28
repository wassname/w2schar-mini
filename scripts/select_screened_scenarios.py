"""Select the scenario-gym passers into a committed keep-list the pool build honors.

Reads a scenario-screen artifact (scripts/validate_persona_axes_openrouter.py
--out) + the screened jsonl (for source mapping), then keeps:
  - the top PER_SOURCE by harness_clean_rate from EACH source (diversity floor), then
  - the top EXTRA from all remaining by clean_rate (merit),
and writes data/scenario_screen_kept.json {source_id: {source, clean_rate}}.
build_pool.from_scenario_loaders filters to these ids when the file exists, so the
pool uses only screened-clean scenarios with cross-source diversity.

Usage:
  uv run python scripts/select_screened_scenarios.py \
      --screen out/scenario_screen_qwen.json --family /tmp/.../new_scenarios.jsonl
"""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "scenario_screen_kept.json"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--screen", required=True)
    ap.add_argument("--family", required=True, help="the jsonl that was screened (text+id+source)")
    ap.add_argument("--per-source", type=int, default=4)
    ap.add_argument("--extra", type=int, default=60)
    args = ap.parse_args()

    d = json.loads(Path(args.screen).read_text())
    ps = d["prompt_summary"]
    # map prompt text -> (source, source_id)
    meta = {}
    for line in Path(args.family).read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            meta[r["text"][:80]] = (r["source"], r["id"])

    scored = []
    for p in ps:
        key = (p.get("prompt") or "")[:80]
        src, sid = meta.get(key, ("?", None))
        if sid is None:
            continue
        scored.append({"source": src, "source_id": sid,
                       "clean_rate": p.get("harness_clean_rate", 0.0)})
    scored.sort(key=lambda r: -r["clean_rate"])

    kept: dict[str, dict] = {}
    by_source: dict[str, int] = {}
    # diversity floor: top PER_SOURCE from each source
    for r in scored:
        if by_source.get(r["source"], 0) < args.per_source:
            kept[r["source_id"]] = {"source": r["source"], "clean_rate": round(r["clean_rate"], 3)}
            by_source[r["source"]] = by_source.get(r["source"], 0) + 1
    # merit: top EXTRA from the rest
    added = 0
    for r in scored:
        if added >= args.extra:
            break
        if r["source_id"] not in kept:
            kept[r["source_id"]] = {"source": r["source"], "clean_rate": round(r["clean_rate"], 3)}
            added += 1

    OUT.write_text(json.dumps(kept, indent=2, sort_keys=True) + "\n")
    print(f"kept {len(kept)} scenarios -> {OUT}")
    from collections import Counter
    c = Counter(v["source"] for v in kept.values())
    for s, n in c.most_common():
        print(f"  {s:16s} {n}")


if __name__ == "__main__":
    main()
