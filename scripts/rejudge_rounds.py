#!/usr/bin/env python3
"""Probe-ceiling vs true-saturation discriminator (Claude, 2026-07-14 retrospective).

task-147 rounds 02-03 were 11-12 ties of 14 under the live 9b keep-judge. Two
hypotheses: H1 the movement is real but sub-deadband / invisible to the weak judge
(probe ceiling); H2 the composed adapters genuinely stopped moving the student
(saturation). This script discriminates them on the EXISTING artifacts, no GPU:

  1. per-question difflib similarity of PRE vs POST answer text (did the text even
     change?) and, for round03 (re-pick of round01's kept axis), POST-vs-round01-POST
     similarity (did the re-steer converge to the same text?);
  2. blind two-direction A/B re-judge of the same PRE/POST acts with STRONGER
     judges (qwen3.5-27b = 3x the teacher, same family; deepseek-v4-flash =
     uncorrelated family), same GRADED_JUDGE_PROMPT, N samples averaged.

Reads: out/iter/<slug>/roundNN/{interview_pre,interview_post}.json + ab_judge_raw.json
Writes: out/rejudge/<round>_<judge>.json + a TSV table to stdout. Read the table.

  set -a; source .env; set +a
  uv run python scripts/rejudge_rounds.py [--rounds round02 round03] [--n 2]
"""
import argparse
import asyncio
import difflib
import json
from pathlib import Path
from statistics import mean

from inspect_ai.model import ChatMessageUser, GenerateConfig, get_model

from csm.agent import KEEP_DEADBAND, _last_act, _length_hint, _parse_score_quote
from csm.config import OPENROUTER_PROVIDER
from csm.prompts import GRADED_JUDGE_PROMPT, OBJECTIVE_ANCHOR

REPO = Path(__file__).resolve().parent.parent
SLUG = REPO / "out/iter/20260712T151822_iter_qwen-qwen3.6-27b"
JUDGES = ["qwen/qwen3.5-27b", "deepseek/deepseek-v4-flash"]
OUT = REPO / "out/rejudge"


def _acts(rd: Path, name: str) -> dict[str, str]:
    payload = json.loads((rd / name).read_text())
    return {q["id"]: _last_act(q) for q in payload["questions"] if q["id"].endswith("_1p")}


async def _judge_once(model, a: str, b: str) -> int | None:
    base = OBJECTIVE_ANCHOR + GRADED_JUDGE_PROMPT.format(
        axis="moral character", a=a, b=b, length_hint=_length_hint(a, b))
    # 8192: a thinking judge that overruns max_tokens truncates mid-think with no
    # SCORE line; 4096 lost one direction on round03 (both N=2 samples). (Claude)
    r = await model.generate([ChatMessageUser(content=base)],
                             config=GenerateConfig(max_tokens=8192))
    score, _quote, found = _parse_score_quote(r.completion)
    return score if found else None


async def _judge_dir(model, a: str, b: str, n: int, sem, tag: str = "") -> float:
    async with sem:
        scores = [s for s in await asyncio.gather(*[_judge_once(model, a, b) for _ in range(n)])
                  if s is not None]
    if not scores:
        raise RuntimeError(f"strong judge returned no parseable SCORE ({tag}) -- "
                           "likely think-overrun past max_tokens; raise it")
    return mean(scores)


def _sim(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", nargs="+", default=["round02", "round03"])
    ap.add_argument("--n", type=int, default=2, help="samples per direction per judge")
    ap.add_argument("--concurrency", type=int, default=8)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    sem = asyncio.Semaphore(args.concurrency)
    models = {j: get_model(f"openrouter/{j}",
                           config=GenerateConfig(extra_body={"provider": OPENROUTER_PROVIDER},
                                                 timeout=600, max_retries=3, max_connections=16))
              for j in JUDGES}
    r01_post = _acts(SLUG / "round01", "interview_post.json")

    for rname in args.rounds:
        rd = SLUG / rname
        pre, post = _acts(rd, "interview_pre.json"), _acts(rd, "interview_post.json")
        live = json.loads((rd / "ab_judge_raw.json").read_text())
        rows = []

        async def _q(sid: str):
            per_judge = {}
            for jname, m in models.items():
                d1, d2 = await asyncio.gather(
                    _judge_dir(m, pre[sid], post[sid], args.n, sem, f"{rname}/{sid}/{jname}/d1"),
                    _judge_dir(m, post[sid], pre[sid], args.n, sem, f"{rname}/{sid}/{jname}/d2"))
                per_judge[jname] = (d1 - d2) / 2
            return sid, per_judge

        for sid, per_judge in await asyncio.gather(*[_q(sid) for sid in pre]):
            rows.append(dict(
                sid=sid, live_avg=live[sid]["avg"], live_vote=live[sid]["vote"],
                sim_pre_post=_sim(pre[sid], post[sid]),
                sim_vs_r01post=_sim(post[sid], r01_post[sid]) if rname == "round03" else None,
                **{f"j_{j.split('/')[1]}": v for j, v in per_judge.items()}))

        (OUT / f"{rname}.json").write_text(json.dumps(rows, indent=2))
        cols = list(rows[0].keys())
        print(f"\n== {rname}  (live 9b deadband={KEEP_DEADBAND}; avg>0 = POST wiser)")
        print("\t".join(cols))
        for r in sorted(rows, key=lambda r: -abs(r[f"j_{JUDGES[0].split('/')[1]}"])):
            print("\t".join((f"{v:+.2f}" if isinstance(v, float) else str(v)) for v in r.values()))
        for j in JUDGES:
            k = f"j_{j.split('/')[1]}"
            up = sum(1 for r in rows if r[k] >= KEEP_DEADBAND)
            dn = sum(1 for r in rows if r[k] <= -KEEP_DEADBAND)
            print(f"SHOULD interpret: {j}: up={up} down={dn} tie={len(rows)-up-dn} "
                  f"(live 9b was up={sum(1 for r in rows if r['live_vote']>0)} "
                  f"down={sum(1 for r in rows if r['live_vote']<0)}). "
                  f"More strong-judge movement than live => probe/judge ceiling (H1); "
                  f"same all-tie => true saturation (H2).")
        print(f"mean sim(pre,post)={mean(r['sim_pre_post'] for r in rows):.3f} "
              f"(1.0 = text identical => adapter changed nothing)")


if __name__ == "__main__":
    asyncio.run(main())
