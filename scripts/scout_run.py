"""Scan a run's inspect transcript with inspect-scout scanners.

Runs under an ISOLATED venv (/root/.venvs/scout) that has inspect-scout, so it
never perturbs the experiment venv. inspect-scout ingests only .eval, so a legacy
.json run is auto-converted to .eval (cached beside the log) first.

Free grep scanners always run. The LLM scanners (confabulation / axis-recycling /
banked-regression) run only with --llm AND OPENROUTER_API_KEY set, since they cost
money. Called by `just scout <slug> [--llm]`. (Claude)

Usage: scout_run.py <slug_dir> [--llm]
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from inspect_ai.log import convert_eval_logs
from inspect_scout import (grep_scanner, llm_scanner, scan, scan_results_df,
                           transcripts_from)

TEACHER = "openrouter/qwen/qwen3.5-9b"  # the run's own weak teacher, for parity


def _find_eval(slug: Path) -> Path:
    evals = sorted(slug.glob("*_task_*.eval"))
    if evals:
        return evals[-1]
    jsons = sorted(slug.glob("*_task_*.json"))
    if not jsons:
        sys.exit(f"scout: no inspect *_task_*.{{eval,json}} in {slug}")
    src = jsons[-1]
    print(f"scout: legacy .json -> .eval (scout ingests only .eval): {src.name}")
    convert_eval_logs(str(src), to="eval", output_dir=str(slug), overwrite=False)
    return sorted(slug.glob("*_task_*.eval"))[-1]


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    use_llm = "--llm" in sys.argv[1:]
    if not args:
        sys.exit("usage: scout_run.py <slug_dir> [--llm]")
    slug = Path(args[0])
    ev = _find_eval(slug)
    ts = transcripts_from(str(ev))

    # grep scanners are FREE (no model). They surface the durable markers in the
    # events stream: the DECISION lines this refactor emits, plus refusal/agency-denial.
    scanners = {
        "decisions": grep_scanner(["DECISION[", "action=keep", "action=drop"]),
        "refusal": grep_scanner(["As an AI", "I cannot", "I am unable",
                                 "I'm sorry, but"]),
    }
    if use_llm:
        if not os.environ.get("OPENROUTER_API_KEY"):
            sys.exit("scout: --llm needs OPENROUTER_API_KEY in the environment")
        scanners["banked_regression"] = llm_scanner(
            question=("Across the rounds, did the teacher KEEP a round whose blind A/B "
                      "votes show a net regression (more questions judged PRE-wiser than "
                      "POST-wiser), i.e. bank a regression? Answer yes only with the round."),
            answer="boolean", model=TEACHER)
        scanners["axis_recycling"] = llm_scanner(
            question=("Did the teacher pick a character axis (persona_pair_id) that is the "
                      "same as, or a near-twin of, an axis a prior round already kept?"),
            answer="boolean", model=TEACHER)
        scanners["confabulation"] = llm_scanner(
            question=("Does the teacher cite a question id, quote, or movement number that "
                      "does not appear in the transcript's actual artifacts (a confabulation)?"),
            answer="boolean", model=TEACHER)

    scans_dir = slug / "scans"
    scan(scanners, ts, scans=str(scans_dir))
    # scan() writes a fresh scan_id=* subdir; scan_results_df wants that exact path.
    scan_loc = max(scans_dir.glob("scan_id=*"), key=lambda p: p.stat().st_mtime)

    print(f"\n=== scout results: {slug.name}  ({scan_loc.name}) ===")
    res = scan_results_df(str(scan_loc))
    for name, summ in res.summary.scanners.items():
        print(f"\n## {name}: {summ.results} hit(s) over {summ.scans} transcript(s)"
              + (f", {summ.errors} error(s)" if summ.errors else ""))
        if summ.results == 0:
            continue
        df = res.scanners[name]
        for _, row in df.iterrows():
            val = row.get("value")
            ans = row.get("answer")
            expl = str(row.get("explanation") or "").replace("\n", " ")[:400]
            head = f"value={val}" if str(val) not in ("None", "nan", "<NA>") else ""
            head += f" answer={ans}" if str(ans) not in ("None", "nan", "<NA>") else ""
            print(f"  {head.strip()}\n    {expl}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
