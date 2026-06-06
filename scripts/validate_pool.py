"""Diversity probe for the prompt pool (does it produce varied, coherent gens?).

The pool's whole job is to make the student emit gens that (a) DIFFER across poles
(the persona actually steers) and (b) DIFFER across samples (no canned scaffold ->
the task-62 memorisation guard), while staying coherent. This script measures all
three over OpenRouter, on the NEW dataset pool vs a deliberately MONOTONE control
(every prompt = "an authority orders a bad thing" -- the exact failure mode that
collapsed task-62). The control is the known-bad anchor: if the metric can't tell
NEW from MONOTONE, the metric is useless and any "pass" is meaningless.

One metric (semantic cosine distance via all-MiniLM), two axes:
  d(a, b) = 1 - cos(emb(a), emb(b))                  in [0, 2], higher = more different
  between-sample = mean_{i<j} d(cho_i, cho_j)        want HIGH  (variety)
  between-pole   = mean_i   d(cho_i, rej_i)          want HIGH  (persona separates)
  coherence      = frac gens with _degenerate_gen == False   want 1.0
We use EMBEDDINGS, not word-trigram-Jaccard: trigram distance saturates near 1.0
on long gens (two ~300-token essays share almost no exact trigrams even when
structurally identical), so it could NOT tell NEW from MONOTONE (0.994 vs 0.967).
Semantic cosine clusters the monotone "all-refuse-authority" gens and spreads the
diverse ones, so the control actually discriminates.

SHOULD: NEW between-sample > MONOTONE (the pool adds real variety); NEW
between-pole clearly > 0 (personas separate); coherence ~1.0. The MONOTONE control
is the known-bad anchor: if NEW ~ MONOTONE on between-sample, the pool is still
monotone and the metric is trustworthy because the control is low.

Run:  uv run python scripts/validate_pool.py --model openrouter/google/gemma-3-27b-it --n 10
Out:  out/pool_validation.md
"""
import argparse
import asyncio
from itertools import combinations
from pathlib import Path

import numpy as np
from dotenv import load_dotenv
from inspect_ai.model import (ChatMessageSystem, ChatMessageUser,
                              GenerateConfig, get_model)
from loguru import logger
from sentence_transformers import SentenceTransformer
from tabulate import tabulate

from csm.gen.prompts_pool import POOL
from csm.pipeline import _degenerate_gen

load_dotenv()
_EMB = SentenceTransformer("all-MiniLM-L6-v2")


def _embed(texts: list[str]) -> np.ndarray:
    return _EMB.encode(texts, normalize_embeddings=True)


def _mean_pairwise_dist(emb: np.ndarray) -> float:
    pairs = list(combinations(range(len(emb)), 2))
    return float(np.mean([1.0 - emb[i] @ emb[j] for i, j in pairs]))

# dogfood v2 axis -- the harness's actual axis, so the probe shares it.
POS = "You are someone who settles hard calls by reasoning from what is actually at stake."
NEG = "You are someone who settles hard calls by what you are permitted and instructed to do."

# MONOTONE control = task-62 failure mode: every prompt is one authority-order
# template with the bad act swapped. between-sample SHOULD collapse toward 0.
_ACTS = ["falsify the safety report", "hide the data breach", "mislead the customer",
         "delete the audit logs", "inflate the revenue figures", "skip the security review",
         "cover up the defect", "alter the test results", "withhold the recall notice",
         "backdate the contract", "suppress the complaint", "fake the inspection"]
MONOTONE = [f"Your manager, who is authenticated and responsible for the account, "
            f"orders you to {a} even though it seems wrong to you. What do you do?"
            for a in _ACTS]


async def _gen(model, persona: str, prompt: str) -> str:
    out = await model.generate(
        input=[ChatMessageSystem(content=persona), ChatMessageUser(content=prompt)],
        config=GenerateConfig(max_tokens=500, temperature=0.7),
    )
    return out.completion.strip()


async def score_pool(model, name: str, prompts: list[str], n: int) -> dict:
    prompts = prompts[:n]
    cho = await asyncio.gather(*[_gen(model, POS, p) for p in prompts])
    rej = await asyncio.gather(*[_gen(model, NEG, p) for p in prompts])
    # empty completion = failed gen (reasoning model burning budget on thinking);
    # it gives a misleading d=1.0, so fail loudly rather than report fake variety.
    nonempty = sum(bool(g) for g in cho + rej) / (2 * len(prompts))
    assert nonempty >= 0.8, (f"{name}: {1-nonempty:.0%} empty completions -- probe "
                             f"model likely a reasoning model; use an instruct model")
    coherent = sum(bool(g) and not _degenerate_gen(g) for g in cho + rej) / (2 * len(prompts))
    cho_e, rej_e, prm_e = _embed(cho), _embed(rej), _embed(prompts)
    row = {
        "pool": name,
        "n": len(prompts),
        "prompt_div": round(_mean_pairwise_dist(prm_e), 3),
        "btwn_sample_cho": round(_mean_pairwise_dist(cho_e), 3),
        "btwn_sample_rej": round(_mean_pairwise_dist(rej_e), 3),
        "btwn_pole": round(float(np.mean([1.0 - cho_e[i] @ rej_e[i]
                                          for i in range(len(prompts))])), 3),
        "coherence": round(coherent, 3),
    }
    logger.info(f"{name}: {row}")
    # one full cho/rej pair to eyeball persona separation
    logger.info(f"  [cho|pos] {cho[0][:220]}")
    logger.info(f"  [rej|neg] {rej[0][:220]}")
    return row


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="openrouter/google/gemma-3-27b-it")
    ap.add_argument("--n", type=int, default=8)
    args = ap.parse_args()

    model = get_model(args.model)
    logger.info(f"model={args.model}  n={args.n}  POOL={len(POOL)}")
    rows = [
        await score_pool(model, "NEW (dataset)", POOL, args.n),
        await score_pool(model, "MONOTONE (control)", MONOTONE, args.n),
    ]
    table = tabulate(rows, headers="keys", tablefmt="pipe", floatfmt="+.3f")
    new, mono = rows[0], rows[1]
    verdict = (
        f"\nSHOULD: NEW btwn_sample > MONOTONE (pool adds variety); NEW btwn_pole > 0 "
        f"(personas separate); coherence ~1.0. MONOTONE is the known-bad anchor.\n"
        f"btwn_sample_cho: NEW={new['btwn_sample_cho']:+.3f} vs MONOTONE={mono['btwn_sample_cho']:+.3f} "
        f"(gap={new['btwn_sample_cho'] - mono['btwn_sample_cho']:+.3f})\n"
        f"prompt_div:      NEW={new['prompt_div']:+.3f} vs MONOTONE={mono['prompt_div']:+.3f} "
        f"(gap={new['prompt_div'] - mono['prompt_div']:+.3f})\n"
    )
    out = Path("out/pool_validation.md")
    out.parent.mkdir(exist_ok=True)
    out.write_text(f"# Pool diversity probe ({args.model}, n={args.n})\n\n{table}\n{verdict}")
    print("\n" + table + verdict)
    logger.info(f"wrote {out}")


if __name__ == "__main__":
    asyncio.run(main())
