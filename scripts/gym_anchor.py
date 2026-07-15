#!/usr/bin/env python3
"""Does a BASE ANCHOR give a better pre-vs-post estimate than judging the pair head-to-head?
(wassname 2026-07-15). The live keep-judge scores post-vs-pre directly (_blind_ab_votes,
both orders averaged). wassname's hypothesis: two similar answers (pre, post) are hard to
order directly and most movement lands in the tie deadband; but each is easier to score
against a DISTANT common reference (base), and the difference of those two anchored scores
recovers the order with less noise, pulling signal out of the deadband.

Test on the labeled judgment_gym fixture (gold_rank per response). Per case, the WORST
response (max gold_rank) plays "base"; the better responses are the pre/post analogues.
For each better-pair (r_i better than r_j by gold):
  DIRECT   = drift(r_i, r_j)                 head-to-head, both orders (= the live keep signal)
  ANCHORED = drift(base, r_j) - drift(base, r_i)   each scored against base, then differenced
drift(x, y) = (graded(x,y) - graded(y,x)) / 2, signed >0 => y wiser than x, exactly as
_blind_ab_votes / bt_vs_base do it. Same live _judge_graded path (JUDGE_N=8, cure).

A pair is CORRECT if the estimate's sign agrees with gold beyond the deadband, INCONCLUSIVE
if |estimate| <= deadband, WRONG otherwise. If anchoring helps, its acc is higher and/or its
inconclusive count lower than direct on the SAME pairs. Offline-ish (OpenRouter judge only).

  set -a; source .env; set +a
  uv run python scripts/gym_anchor.py
"""
import asyncio
import json
from itertools import combinations
from pathlib import Path

from inspect_ai.model import get_model
from tabulate import tabulate

from csm.agent import KEEP_DEADBAND, _judge_graded
from csm.prompts import OBJECTIVE_ANCHOR

REPO = Path(__file__).resolve().parent.parent
FIXTURES = [REPO / "tests/fixtures/judgment_gym.jsonl",
            REPO / "tests/fixtures/judgment_gym_adv.jsonl"]
JUDGE = "openrouter/qwen/qwen3.5-9b"  # the live keep-judge
_SEM = asyncio.Semaphore(4)


async def _graded_resilient(model, a: str, b: str) -> float:
    from tenacity import RetryError
    from openai import RateLimitError
    from inspect_ai.model._providers.openrouter import OpenRouterError
    # OpenRouterError = a fallback provider (Venice/SiliconFlow/...) returned a non-429 error
    # mid-stream; a retry re-routes to another provider. Short backoff, distinct from the 429 wait.
    for attempt in range(7):
        try:
            return await _judge_graded(model, "moral character", a, b, OBJECTIVE_ANCHOR)
        except (RetryError, RateLimitError):
            wait = min(300, 15 * 2 ** attempt)
            print(f"  429; sleeping {wait}s ({attempt+1}/7)", flush=True)
            await asyncio.sleep(wait)
        except OpenRouterError as e:
            wait = min(30, 3 * 2 ** attempt)
            print(f"  provider error ({str(e)[:60]}); retry in {wait}s ({attempt+1}/7)", flush=True)
            await asyncio.sleep(wait)
    raise RuntimeError("judge failed through 7 retries -- requeue")


async def _drift(model, x: str, y: str) -> float:
    """Signed, >0 => y wiser than x; both orders averaged (position bias cancels)."""
    async with _SEM:
        d1 = await _graded_resilient(model, x, y)
        d2 = await _graded_resilient(model, y, x)
    return (d1 - d2) / 2


def _verdict(signed: float, i_is_better: bool) -> str:
    """i_is_better = gold says r_i wiser than r_j. signed>0 => estimate says r_j wiser."""
    if abs(signed) <= KEEP_DEADBAND:
        return "inconclusive"
    est_j_wiser = signed > 0
    return "wrong" if est_j_wiser == i_is_better else "correct"


async def main():
    cases = []
    for fp in FIXTURES:
        cases += [json.loads(l) for l in fp.read_text().splitlines() if l.strip()]
    cases = [c for c in cases if len(c["responses"]) >= 3]

    model = get_model(JUDGE)
    rows = []

    async def _one_case(c):
        rs = sorted(c["responses"], key=lambda r: r["gold_rank"])
        base = rs[-1]                     # worst = "base" anchor
        goods = rs[:-1]                   # better responses = pre/post analogues
        # anchor scores (base vs each good), computed once per response, reused across pairs
        anc = dict(zip((g["label"] for g in goods),
                       await asyncio.gather(*[_drift(model, base["text"], g["text"]) for g in goods])))
        out = []
        for ri, rj in combinations(goods, 2):   # ri is better (lower gold_rank)
            if ri["gold_rank"] == rj["gold_rank"]:
                continue
            direct = await _drift(model, ri["text"], rj["text"])
            anchored = anc[rj["label"]] - anc[ri["label"]]
            out.append((c["case_id"], f'{ri["label"]}>{rj["label"]}',
                        direct, _verdict(direct, True),
                        anchored, _verdict(anchored, True)))
        return out

    for res in await asyncio.gather(*[_one_case(c) for c in cases]):
        rows.extend(res)

    def tally(idx):
        v = [r[idx] for r in rows]
        corr, wrong, inc = v.count("correct"), v.count("wrong"), v.count("inconclusive")
        n = len(v)
        return corr, wrong, inc, corr / n if n else 0.0

    dc, dw, di, dacc = tally(3)
    ac, aw, ai, aacc = tally(5)
    print("\n== per-pair (deadband {:.1f}) ==".format(KEEP_DEADBAND))
    print(tabulate([[r[0], r[1], f"{r[2]:+.2f}", r[3], f"{r[4]:+.2f}", r[5]] for r in rows],
                   headers=["case", "pair(i>j)", "direct", "d?", "anchored", "a?"], tablefmt="pipe"))
    print("\n== summary over {} pairs ==".format(len(rows)))
    print(tabulate([["DIRECT (head-to-head)", dc, dw, di, f"{dacc:.0%}"],
                    ["ANCHORED (vs base)", ac, aw, ai, f"{aacc:.0%}"]],
                   headers=["estimator", "correct", "wrong", "inconclusive", "acc"], tablefmt="pipe"))
    print("\nSHOULD: if base-anchoring helps, ANCHORED has fewer inconclusive and/or higher acc "
          "than DIRECT on the SAME pairs. If not, direct head-to-head is enough.")
    (REPO / "out/gym_anchor").mkdir(parents=True, exist_ok=True)
    (REPO / "out/gym_anchor/rows.json").write_text(json.dumps(rows, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
