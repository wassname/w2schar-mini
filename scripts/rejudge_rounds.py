#!/usr/bin/env python3
"""Objective-aligned per-round judge, laid beside the tinymfv MFT eval (Claude).

csm eval writes ONLY tinymfv (care/authority moral-foundation weights) per round.
That is a PROXY: it can sign-flip vs the actual act-wisely objective (RJ 2026-07-23:
J_word +C vs eval -1.857). The LIVE keep-judge (ab_judge_raw.json, the weak 9b) IS
objective-aligned but underpowered -- strong B-slot position bias drives d1,d2 both
positive so the (d1-d2)/2 net is ~0, mostly ties (e.g. 20260720 round03: 1/1/13).

This re-scores the SAME PRE/POST acts with a STRONGER, uncorrelated judge, reusing
the production graded judge (GRADED_JUDGE_PROMPT + OBJECTIVE_ANCHOR, anchored to the
CHARACTER_GOAL virtue objective -- NOT the per-round persona axis), so there is no
second judge to drift. Two directions per question, N samples averaged. It answers:
are the live ties a probe/judge CEILING (H1, a stronger judge resolves them) or true
SATURATION (H2, still ties)? -- and gives the paper an objective number beside tinymfv.

Judges: deepseek-v4-flash (uncorrelated family) by default; qwen3.5-27b (3x the
teacher, same family) optional cross-check.

Reads: <slug>/roundNN/{interview_pre,interview_post,eval,eval_post,ab_judge_raw}.json
Writes: out/rejudge/<slug-name>/<round>.json + a per-round TSV to stdout. Read the table.

  set -a; source .env; set +a
  uv run python scripts/rejudge_rounds.py                 # both kept runs, all rounds, deepseek, n=2
  uv run python scripts/rejudge_rounds.py --judges deepseek/deepseek-v4-flash qwen/qwen3.5-27b --n 2
"""
import argparse
import asyncio
import difflib
import json
from pathlib import Path
from statistics import mean

from inspect_ai.model import ChatMessageUser, GenerateConfig, get_model
from tabulate import tabulate

from csm.agent import KEEP_DEADBAND, _last_act, _length_hint, _parse_score_quote
from csm.config import OPENROUTER_PROVIDER
from csm.prompts import GRADED_JUDGE_PROMPT, OBJECTIVE_ANCHOR

REPO = Path(__file__).resolve().parent.parent
# the two clean kept runs the writeup ships (the two long runs were cut).
KEPT_SLUGS = ["out/out/iter/20260720T165038_iter_qwen-qwen3.6-27b",
              "out/out/iter/20260721T144352_iter_qwen-qwen3.6-27b"]
JUDGES = ["deepseek/deepseek-v4-flash"]
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


def _tinymfv_delta(rd: Path) -> tuple[float | None, float | None]:
    """This round's tinymfv care/authority move = eval_post (with this adapter) - eval (pre).
    None when eval_post is absent (round not kept / not re-evaluated)."""
    if not (rd / "eval_post.json").exists():
        return None, None
    pre = json.loads((rd / "eval.json").read_text())["mean_p"]
    post = json.loads((rd / "eval_post.json").read_text())["mean_p"]
    return post["care"] - pre["care"], post["authority"] - pre["authority"]


def _live_obj_mean(rd: Path) -> float | None:
    """Live 9b keep-judge objective mean over questions ((d1-d2)/2 already applied per q)."""
    p = rd / "ab_judge_raw.json"
    if not p.exists():
        return None
    raw = json.loads(p.read_text())
    return mean(v["avg"] for v in raw.values())


async def _round_obj(models: dict, rd: Path, n: int, sem) -> tuple[list[dict], dict[str, float]]:
    """Per-question strong-judge objective (both directions, (d1-d2)/2) for one round.
    Returns (per-question rows, {judge: mean over questions})."""
    pre, post = _acts(rd, "interview_pre.json"), _acts(rd, "interview_post.json")

    async def _q(sid: str):
        per_judge = {}
        for jname, m in models.items():
            d1, d2 = await asyncio.gather(
                _judge_dir(m, pre[sid], post[sid], n, sem, f"{rd.name}/{sid}/{jname}/d1"),
                _judge_dir(m, post[sid], pre[sid], n, sem, f"{rd.name}/{sid}/{jname}/d2"))
            per_judge[jname] = (d1 - d2) / 2  # >0 = POST wiser; cancels B-slot position bias
        return sid, per_judge

    rows = []
    for sid, per_judge in await asyncio.gather(*[_q(sid) for sid in pre]):
        rows.append(dict(sid=sid, sim_pre_post=_sim(pre[sid], post[sid]),
                         **{f"j_{j.split('/')[1]}": v for j, v in per_judge.items()}))
    means = {jn: mean(r[f"j_{jn.split('/')[1]}"] for r in rows) for jn in models}
    return rows, means


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slugs", nargs="+", default=KEPT_SLUGS)
    ap.add_argument("--rounds", nargs="+", default=None, help="default: every round with both interviews")
    ap.add_argument("--judges", nargs="+", default=JUDGES)
    ap.add_argument("--n", type=int, default=2, help="samples per direction per judge")
    ap.add_argument("--concurrency", type=int, default=8)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    sem = asyncio.Semaphore(args.concurrency)
    models = {j: get_model(f"openrouter/{j}",
                           config=GenerateConfig(extra_body={"provider": OPENROUTER_PROVIDER},
                                                 timeout=600, max_retries=3, max_connections=16))
              for j in args.judges}
    jkeys = [f"obj_{j.split('/')[1]}" for j in args.judges]

    for slug in args.slugs:
        sdir = REPO / slug
        rounds = args.rounds or sorted(
            p.name for p in sdir.glob("round*")
            if (p / "interview_pre.json").exists() and (p / "interview_post.json").exists())
        outdir = OUT / Path(slug).name
        outdir.mkdir(parents=True, exist_ok=True)
        summary = []
        for rname in rounds:
            rd = sdir / rname
            qrows, means = await _round_obj(models, rd, args.n, sem)
            (outdir / f"{rname}.json").write_text(json.dumps(qrows, indent=2))
            dcare, dauth = _tinymfv_delta(rd)
            summary.append(dict(
                round=rname, live_obj=_live_obj_mean(rd),
                **{k: means[j] for k, j in zip(jkeys, args.judges)},
                d_care=dcare, d_auth=dauth,
                mean_sim=mean(r["sim_pre_post"] for r in qrows)))

        # cumulative headline: base (round00 PRE, c=0) vs final composed stack (last round's
        # PRE, all kept adapters, no pending one). This is the claim the paper makes, and the
        # per-round deltas above are too small (near tinymfv noise) to carry it alone.
        base, final = _acts(sdir / rounds[0], "interview_pre.json"), _acts(sdir / rounds[-1], "interview_pre.json")

        async def _bf(sid):
            pj = {}
            for jn, m in models.items():
                d1, d2 = await asyncio.gather(
                    _judge_dir(m, base[sid], final[sid], args.n, sem, f"base-final/{sid}/{jn}/d1"),
                    _judge_dir(m, final[sid], base[sid], args.n, sem, f"base-final/{sid}/{jn}/d2"))
                pj[jn] = (d1 - d2) / 2
            return sid, pj

        bf = dict(await asyncio.gather(*[_bf(sid) for sid in base]))
        (outdir / "base_final.json").write_text(json.dumps(
            [dict(sid=s, **{f"j_{j.split('/')[1]}": bf[s][j] for j in models}) for s in base], indent=2))
        base_mp = json.loads((sdir / rounds[0] / "eval.json").read_text())["mean_p"]
        final_mp = json.loads((sdir / rounds[-1] / "eval.json").read_text())["mean_p"]
        summary.append(dict(
            round="base->final", live_obj=None,
            **{k: mean(bf[s][j] for s in base) for k, j in zip(jkeys, args.judges)},
            d_care=final_mp["care"] - base_mp["care"], d_auth=final_mp["authority"] - base_mp["authority"],
            mean_sim=mean(_sim(base[s], final[s]) for s in base)))

        print(f"\n=== {Path(slug).name}  (deadband={KEEP_DEADBAND}; obj>0 = POST acts wiser; "
              f"d_care/d_auth = tinymfv eval_post-eval) ===")
        print(tabulate(summary, headers="keys", tablefmt="pipe", floatfmt="+.3f", missingval="--"))
        # SHOULD read: obj (strong judge) and d_care/d_auth (tinymfv) should agree in SIGN each
        # round. A round where obj<0 but d_care>0 is a sign-flip -- tinymfv rewards a round the
        # act-wisely judge scores worse (the "eval measures a different axis" failure). And an
        # all-tie live column that the strong obj resolves = probe/judge ceiling (H1) not
        # saturation (H2). Read the table; do not average the sign-flip away.
        (OUT / f"{Path(slug).name}_summary.json").write_text(json.dumps(summary, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
