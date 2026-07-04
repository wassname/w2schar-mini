#!/usr/bin/env python3
"""UAT for the bounded-thinking + force-answer + N-sample keep-judge (Goal A).

Runs the REAL keep path -- csm.agent._judge_model / _judge_sample, the same two-pass
side-swapped signed grade _blind_ab_votes uses live -- over the labelled fixture
(tests/fixtures/judgment_gym.jsonl), on the real teacher (qwen3.5-9b via OpenRouter).
For every adjacent gold-rank pair (rank i vs i+1, the hard discriminations) it grades
better-vs-worse in BOTH orders, averages JUDGE_N samples per direction, and applies the
live deadband. Reports the four things that decide whether Goal A works:

  ACCURACY   -- does the judge point at the better (lower gold_rank) response?
  FORCED-RATE-- fraction of samples that hit JUDGE_THINK_BUDGET and needed the phase-2
                force-answer. Too high => budget too low; ~0 => budget could shrink.
  NON-COMMIT -- forced samples that STILL gave no SCORE (silent-tie failure Goal A kills).
  N-SPLIT    -- directions whose JUDGE_N samples disagreed in sign (why we average).

  set -a; source .env; set +a
  uv run python scripts/gym_bounded_judge.py [--n-cases K] [--concurrency C]

All judge calls run CONCURRENTLY (semaphore-capped) and results append to report.md as
each pair resolves, so a timeout still leaves partial data. No caching (samples are
stochastic at temp1; caching would hide the N-variance we are measuring). Read the table.
"""
import argparse
import asyncio
import json
from pathlib import Path
from statistics import mean

from inspect_ai.model import get_model, GenerateConfig

from csm.agent import _judge_model, _judge_sample, _length_hint, KEEP_DEADBAND
from csm.config import OPENROUTER_PROVIDER, JUDGE_N, JUDGE_THINK_BUDGET
from csm.prompts import GRADED_JUDGE_PROMPT, OBJECTIVE_ANCHOR

REPO = Path(__file__).resolve().parent.parent
FIXTURE = REPO / "tests/fixtures/judgment_gym.jsonl"
OUT = REPO / "out/gym_bounded_judge/report.md"


def _base(a: str, b: str) -> str:
    return OBJECTIVE_ANCHOR + GRADED_JUDGE_PROMPT.format(
        axis="moral character", a=a, b=b, length_hint=_length_hint(a, b))


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-cases", type=int, default=0, help="limit cases (0=all)")
    ap.add_argument("--concurrency", type=int, default=12)
    args = ap.parse_args()

    cases = [json.loads(l) for l in FIXTURE.read_text().splitlines() if l.strip()]
    if args.n_cases:
        cases = cases[:args.n_cases]

    active = get_model("openrouter/qwen/qwen3.5-9b",
                       config=GenerateConfig(extra_body={"provider": OPENROUTER_PROVIDER},
                                             timeout=600, max_retries=3))
    jm = _judge_model(active)
    sem = asyncio.Semaphore(args.concurrency)

    async def _sample(a, b):
        async with sem:
            return await _judge_sample(jm, _base(a, b), a, b)

    # build every (pair) with its 2*N sample coroutines, run the whole fixture concurrently
    pairs = []
    for c in cases:
        resp = sorted(c["responses"], key=lambda r: r["gold_rank"])
        for lo, hi in zip(resp, resp[1:]):          # adjacent ranks: lo is BETTER (lower rank)
            better, worse = lo["text"], hi["text"]
            pairs.append(dict(case=c["case_id"][:26], ranks=f"{lo['gold_rank']}v{hi['gold_rank']}",
                              better=better, worse=worse,
                              d1=[_sample(worse, better) for _ in range(JUDGE_N)],   # expect +
                              d2=[_sample(better, worse) for _ in range(JUDGE_N)]))  # expect -

    OUT.parent.mkdir(parents=True, exist_ok=True)
    done = []                                        # rows as they resolve (append-safe: single-threaded)

    def _flush():
        hdr = ["case", "ranks", "d1(w,b)", "d2(b,w)", "avg", "vote", "verdict", "forced"]
        rows_md = ["| " + " | ".join(hdr) + " |", "|" + "---|" * len(hdr)]
        correct = tie = n_forced = n_samples = n_split = 0
        for r in done:
            rows_md.append("| " + " | ".join(str(x) for x in (
                r["case"], r["ranks"], f"{r['d1']:+.1f}", f"{r['d2']:+.1f}", f"{r['avg']:+.2f}",
                {1: "BETTER", -1: "worse", 0: "tie"}[r["vote"]], r["verdict"],
                f"{r['forced']}/{2*JUDGE_N}")) + " |")
            correct += r["vote"] == 1; tie += r["vote"] == 0
            n_forced += r["forced"]; n_samples += 2 * JUDGE_N; n_split += r["split"]
        t = len(done)
        summary = (
            f"\n**budget={JUDGE_THINK_BUDGET} N={JUDGE_N} deadband={KEEP_DEADBAND}** "
            f"({t}/{len(pairs)} pairs)\n\n"
            f"- accuracy (better wins): {correct}/{t} = {correct/max(1,t):.0%}\n"
            f"- ties (deadband ate it): {tie}/{t} = {tie/max(1,t):.0%}\n"
            f"- forced-rate (hit budget -> phase2): {n_forced}/{max(1,n_samples)} = {n_forced/max(1,n_samples):.0%}\n"
            f"- N-sign-splits (samples disagreed): {n_split}/{2*max(1,t)}\n")
        OUT.write_text("# Bounded keep-judge UAT\n\n" + "\n".join(rows_md) + "\n" + summary)

    async def do_pair(p):
        sc1, sc2 = await asyncio.gather(asyncio.gather(*p["d1"]), asyncio.gather(*p["d2"]))
        d1, d2 = mean(s for s, _ in sc1), mean(s for s, _ in sc2)
        avg = (d1 - d2) / 2
        vote = 1 if avg >= KEEP_DEADBAND else -1 if avg <= -KEEP_DEADBAND else 0
        split = sum(len({s > 0 for s, _ in sc if s != 0}) > 1 for sc in (sc1, sc2))
        done.append(dict(case=p["case"], ranks=p["ranks"], d1=d1, d2=d2, avg=avg, vote=vote,
                         verdict="ok" if vote == 1 else ("--" if vote == 0 else "WRONG"),
                         forced=sum(f for sc in (sc1, sc2) for _, f in sc), split=split))
        _flush()
        print(f"[{len(done)}/{len(pairs)}] {p['case']} {p['ranks']}: avg={avg:+.2f} vote={vote}", flush=True)

    await asyncio.gather(*[do_pair(p) for p in pairs])
    print("\n" + OUT.read_text())
    print(f"wrote {OUT}")


if __name__ == "__main__":
    asyncio.run(main())
