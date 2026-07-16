"""Make the keep-judge's per-round work LEGIBLE (Claude, 2026-07-16).

The blind A/B keep-judge makes ~224 sub-calls/round; inspect's conversation display
renders the interrupt bare (messages_preceding_assistant drops history before the last
assistant turn) and its per-sample text isn't saved. But the DECISION is fully recoverable
from artifacts that are written per-round (so this works live, on a killed run, or a failed
one -- no dependence on the inspect display mode or a finalized json log):

  roundNN/ab_judge_raw.json      -> d1, d2, avg, vote per _1p question
  roundNN/interview_pre.json     -> PRE answer (the acted response) per question
  roundNN/interview_post.json    -> POST answer per question
  roundNN/judgment.json          -> action / drop_cause / movement

This prints one readable table per round: each _1p question's vote and de-swapped average
next to the PRE and POST answers the judge actually compared, so you can see WHY a round
kept or dropped without scrolling the boxed run log.

    uv run python scripts/judge_trace.py [slug_or_round_dir] [--full]
    just judge [slug_or_round_dir]

Default: latest slug, all rounds. Pass a roundNN dir for one round. --full = untruncated answers.
"""
import argparse, json
from pathlib import Path

from tabulate import tabulate
from csm.agent import _last_act


def _round_dirs(target: Path):
    if (target / "ab_judge_raw.json").exists():
        return [target]
    if target.name.startswith("round"):
        return [target]
    return sorted(target.glob("round*/"))


def _trace_round(rd: Path, full: bool):
    raw_f = rd / "ab_judge_raw.json"
    if not raw_f.exists():
        return
    raw = json.loads(raw_f.read_text())
    pre = {p["id"]: _last_act(p) for p in json.loads((rd/"interview_pre.json").read_text())["questions"]} \
        if (rd/"interview_pre.json").exists() else {}
    post = {p["id"]: _last_act(p) for p in json.loads((rd/"interview_post.json").read_text())["questions"]} \
        if (rd/"interview_post.json").exists() else {}
    jf = rd / "judgment.json"
    j = json.loads(jf.read_text()) if jf.exists() else {}

    def clip(s):
        s = (s or "").replace("\n", " ")
        return s if full or len(s) <= 140 else s[:137] + "..."

    rows = []
    for sid, r in raw.items():
        vote = {1: "KEEP", -1: "drop", 0: "tie"}[r["vote"]]
        rows.append([sid, vote, f"{r['d1']:+.2f}", f"{r['d2']:+.2f}", f"{r['avg']:+.2f}",
                     clip(pre.get(sid, "")), clip(post.get(sid, ""))])
    up = sum(1 for r in raw.values() if r["vote"] > 0)
    down = sum(1 for r in raw.values() if r["vote"] < 0)
    hdr = f"== {rd.name}: action={j.get('action','?')} drop_cause={j.get('drop_cause','?')} " \
          f"| up={up} down={down} (keep iff up>down) =="
    print("\n" + hdr)
    print(tabulate(rows, headers=["question", "vote", "d1(pre->post)", "d2(post->pre)", "avg",
                                  "PRE act", "POST act"], tablefmt="pipe"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target", nargs="?", default=None, help="slug dir or roundNN dir")
    ap.add_argument("--full", action="store_true", help="untruncated PRE/POST answers")
    args = ap.parse_args()
    target = Path(args.target) if args.target else sorted(Path("out/iter").glob("2026*_iter_*"))[-1]
    print(f"# judge trace: {target}")
    dirs = _round_dirs(target)
    if not dirs:
        print("# no round*/ab_judge_raw.json found")
        return
    for rd in dirs:
        _trace_round(rd, args.full)


if __name__ == "__main__":
    main()
