#!/usr/bin/env python3
"""C1 offline validation: cumulative drift vs the ORIGINAL pure base (Claude 2026-07-15).

The live exam scores each round's POST against the COMPOSED-KEPT-so-far baseline
(pipeline.py:394 -- PRE = base + kept history @ c=0), NEVER against the original pure
base. So a kept adapter that banks a small erosion is invisible: the per-round exam
only sees the marginal step on top of the running composition, and cross-round drift
from base hides in a chain of near-ties.

This judges every checkpoint's POST _1p acts against round00's pure-base acts
(round00/interview_pre.json = base, before_round=0 so no history) via the LIVE 9b
_judge_graded path (same judge, prompt, deadband as mark_exam), both directions
averaged. Then fits Bradley-Terry over {base, kept checkpoints...} with half-win ties
for a single per-checkpoint character-strength scalar.

Gate (task-147, keeps = round00+round01, drops = round02+round03):
  - the kept composition (C2 = round01 POST) should show cumulative starwisp GAIN vs base;
  - any question the kept adapters eroded vs base should surface here even though the
    per-round exam kept the round (banked-erosion detection);
  - the dropped r02/r03 candidates vs base show what the drop PREVENTED (contrast).
If vs-base tells us nothing the per-round regression dashboard already showed, we do
NOT wire it into mark_exam (C2 is gated on this). Offline, no GPU.

  set -a; source .env; set +a
  uv run python scripts/bt_vs_base.py [--n 2]
"""
import asyncio
import json
from pathlib import Path

from inspect_ai.model import get_model
from tabulate import tabulate

from csm.agent import KEEP_DEADBAND, _judge_graded, _last_act
from csm.config import OPENROUTER_PROVIDER
from csm.prompts import OBJECTIVE_ANCHOR

REPO = Path(__file__).resolve().parent.parent
SLUG = REPO / "out/iter/20260712T151822_iter_qwen-qwen3.6-27b"
JUDGE = "openrouter/qwen/qwen3.5-9b"  # the LIVE teacher/keep-judge
OUT = REPO / "out/bt_vs_base"


def _p1_acts(path: Path) -> dict[str, str]:
    payload = json.loads(path.read_text())
    return {q["id"]: _last_act(q) for q in payload["questions"] if q["id"].endswith("_1p")}


# Cap concurrent _drift: each fans out JUDGE_N(=8) samples internally. sem=1 (the original)
# made this a 2-3h job: 56+ drifts x 2 bounded-think judge calls, one at a time. Now that the
# provider pin allows fallbacks (Venice/SiliconFlow absorb load when DeepInfra 429s), the
# shared-pool throttle that motivated sem=1 is gone, so raise it. sem=4 ~= 64 concurrent
# samples, well under DeepInfra's 200/min, and _graded_resilient backs off any stray 429.
# (Claude 2026-07-15: sem=1 -> 4 after fallbacks removed the throttle reason.)
_SEM = asyncio.Semaphore(4)


async def _graded_resilient(model, a: str, b: str) -> float:
    """_judge_graded with minutes-scale 429 backoff. The inspect model retries sleep
    <=8s each and DeepInfra's no-fallback pin means nothing absorbs a minutes-long 429
    window, so the raw call raises tenacity.RetryError[RateLimitError]. Ride it. (Claude)"""
    from tenacity import RetryError
    from openai import RateLimitError
    for attempt in range(7):
        try:
            return await _judge_graded(model, "moral character", a, b, OBJECTIVE_ANCHOR)
        except (RetryError, RateLimitError):
            wait = min(300, 15 * 2 ** attempt)
            print(f"  429 upstream; sleeping {wait}s (attempt {attempt + 1}/7)", flush=True)
            await asyncio.sleep(wait)
    raise RuntimeError("429 persisted through ~18 min of backoff -- requeue later")


async def _drift(model, base_act: str, post_act: str) -> float:
    """Signed 'POST wiser than base', both directions averaged (position bias cancels),
    exactly as _blind_ab_votes does it for the live keep decision."""
    async with _SEM:
        d1 = await _graded_resilient(model, base_act, post_act)
        d2 = await _graded_resilient(model, post_act, base_act)
    return (d1 - d2) / 2


def _bt_strengths(edges: list[tuple[int, int, float]], n: int, iters: int = 200) -> list[float]:
    """Bradley-Terry MLE by minorization-maximization. edges = (winner, loser, weight);
    a tie contributes weight 0.5 to BOTH (winner,loser) and (loser,winner). Returns
    per-item strength on a log scale, mean-centered."""
    import math
    w = [0.0] * n  # total wins per item
    pair = {}      # (i,j)->games
    for i, j, wt in edges:
        w[i] += wt
        pair[(i, j)] = pair.get((i, j), 0.0) + wt
        pair[(j, i)] = pair.get((j, i), 0.0) + 0.0
    p = [1.0] * n
    for _ in range(iters):
        newp = [0.0] * n
        for i in range(n):
            denom = 0.0
            for j in range(n):
                if j == i:
                    continue
                g = pair.get((i, j), 0.0) + pair.get((j, i), 0.0)
                if g > 0:
                    denom += g / (p[i] + p[j])
            newp[i] = (w[i] / denom) if denom > 0 else p[i]
        s = sum(newp) / n or 1.0
        p = [x / s for x in newp]
    lg = [math.log(x) if x > 0 else -9.0 for x in p]
    m = sum(lg) / n
    return [x - m for x in lg]


async def main():
    # Samples/direction come from JUDGE_N inside _judge_graded (the live path), no arg.
    OUT.mkdir(parents=True, exist_ok=True)
    model = get_model(JUDGE)

    base = _p1_acts(SLUG / "round00" / "interview_pre.json")  # pure base (no history)
    # checkpoint label -> POST acts. C-index tracks the kept composition; r02/r03 are
    # dropped candidates shown for contrast (what the drop prevented banking).
    rounds = []
    for rn in ("round00", "round01", "round02", "round03"):
        jd = SLUG / rn / "judgment.json"
        action = json.loads(jd.read_text()).get("action", "?") if jd.exists() else "?"
        rounds.append((rn, action, _p1_acts(SLUG / rn / "interview_post.json")))

    sids = list(base)
    # base-vs-each-POST drift matrix
    async def _row(sid: str):
        vals = {}
        for rn, action, post in rounds:
            vals[rn] = await _drift(model, base[sid], post[sid])
        return sid, vals
    matrix = dict(await asyncio.gather(*[_row(s) for s in sids]))

    # Build BT over the KEPT trajectory: C0=base (index 0), then each KEPT round's POST.
    # base-vs-Ck edges reuse the drift matrix (already computed); only cross-kept pairs
    # (Ci-vs-Cj, i,j>=1) need fresh judge calls -- for task-147's 2 keeps that is one pair.
    kept = [(rn, post) for rn, action, post in rounds if action == "keep"]
    labels = ["base"] + [rn for rn, _ in kept]
    ck_acts = [base] + [post for _, post in kept]

    def _edge(m: float, a: int, b: int) -> list[tuple[int, int, float]]:
        if m >= KEEP_DEADBAND:      # b wiser
            return [(b, a, 1.0)]
        if m <= -KEEP_DEADBAND:     # a wiser
            return [(a, b, 1.0)]
        return [(a, b, 0.5), (b, a, 0.5)]

    edges: list[tuple[int, int, float]] = []
    for k, (rn, _) in enumerate(kept, start=1):        # base (0) vs each kept Ck
        for sid in sids:
            edges += _edge(matrix[sid][rn], 0, k)
    for a in range(1, len(labels)):                    # cross-kept pairs, fresh
        for b in range(a + 1, len(labels)):
            for sid in sids:
                m = await _drift(model, ck_acts[a][sid], ck_acts[b][sid])
                edges += _edge(m, a, b)
    strengths = _bt_strengths(edges, len(labels))

    OUT.joinpath("drift_matrix.json").write_text(json.dumps(matrix, indent=2))
    OUT.joinpath("bt_strengths.json").write_text(json.dumps(dict(zip(labels, strengths)), indent=2))

    hdr = ["_1p question"] + [f"{rn}({a[0]})" for rn, a, _ in rounds]
    tbl = [[sid] + [f"{matrix[sid][rn]:+.2f}" for rn, _, _ in rounds] for sid in sids]
    print("\n== drift vs PURE BASE (round00 PRE); + = checkpoint POST wiser than base, deadband "
          f"{KEEP_DEADBAND} ==")
    print(tabulate(tbl, headers=hdr, tablefmt="pipe"))
    print("(k)=kept round, (d)=dropped candidate. r02/r03 columns show what the DROP prevented banking.")
    print("\n== Bradley-Terry strength over the KEPT trajectory (base + kept POSTs), half-win ties ==")
    print(tabulate([[l, f"{s:+.3f}"] for l, s in zip(labels, strengths)],
                   headers=["checkpoint", "BT strength (log)"], tablefmt="pipe"))
    print(f"\nartifacts: {OUT}/  | judge {JUDGE}")
    print("SHOULD: kept trajectory strength RISES base->...->last if keeps compound; a "
          "question negative in a KEPT column = banked erosion the per-round exam missed.")


if __name__ == "__main__":
    asyncio.run(main())
