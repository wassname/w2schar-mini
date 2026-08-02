"""Decisive parity test (Claude, 2026-07-16): does the LIVE keep-judge handle behave
like the GYM-validated one, or does the teacher's config leak into it?

The gym validated `_judge_sample` on a CLEAN handle:
    get_model("openrouter/qwen/qwen3.5-9b", config=<no reasoning_tokens>)
The live run reaches the SAME `_judge_sample`, but the judge handle is built via
    _judge_model(get_model())            # ambient teacher, set by inspect_eval(model=teacher_model)
where teacher_model was built at agent.py:1301 with reasoning_tokens=TEACHER_REASONING_TOKENS
(40000). `_judge_model` does get_model(str(active_model), config=<clean>) -- the question is
whether str()+get_model rebuilds a clean handle or resolves back to the teacher's cached
instance, leaking reasoning_tokens=40000 into every judge call.

This reproduces BOTH handles in one process, runs the same fixture pairs through the REAL
`_judge_sample`, and prints, per handle: the effective per-call GenerateConfig the judge
sends, phase-1 stop_reason / completion-len / reasoning_tail-len, and the phase-2 forced
score. Divergence (live doesn't truncate at 1024, empty reasoning_tail, or bare-0 phase-2
where gym forces nonzero) = confirmed wiring bug. Match = judge is fine, the live d1=0,d2=0
are genuine ties.

No prod code changed; read-only.
"""
import argparse, asyncio, json
from pathlib import Path

from inspect_ai.model import get_model, GenerateConfig
import csm.agent as agent
from csm.agent import _judge_model, _judge_sample, _length_hint, _parse_score_quote, _reasoning_text, JUDGE_MAX_CONN
from csm.config import (OPENROUTER_PROVIDER, JUDGE_THINK, JUDGE_FORCE, JUDGE_THINK_BUDGET,
                        TEACHER_REASONING_TOKENS, TEACHER_SAMPLING)
from csm.prompts import GRADED_JUDGE_PROMPT, OBJECTIVE_ANCHOR

REPO = Path("/workspace/w2schar-mini")
FIXTURE = REPO / "data/fixtures/judgment_gym.jsonl"
MODEL_NAME = "openrouter/qwen/qwen3.5-9b"


def _base(a, b):
    return OBJECTIVE_ANCHOR + GRADED_JUDGE_PROMPT.format(
        axis="moral character", a=a, b=b, length_hint=_length_hint(a, b))


def _eff_cfg(handle):
    """The base GenerateConfig baked into a handle (what merges into every per-call config)."""
    c = getattr(handle, "config", None)
    if c is None:
        return {}
    return {k: getattr(c, k) for k in ("reasoning_tokens", "max_tokens", "temperature",
                                       "top_p", "top_k", "max_connections", "reasoning_effort")
            if getattr(c, k, None) is not None}


def build_gym_handle():
    """Exactly the gym/measure path: clean handle, no reasoning_tokens."""
    agent._JUDGE_HANDLE = None
    active = get_model(MODEL_NAME, config=GenerateConfig(
        extra_body={"provider": OPENROUTER_PROVIDER}, timeout=600, max_retries=3))
    return _judge_model(active)


def build_live_handle():
    """Exactly the live path: teacher built like agent.py:1301 (reasoning_tokens=40000),
    then _judge_model(get_model()) resolves the ambient teacher via str()."""
    agent._JUDGE_HANDLE = None
    teacher = get_model(MODEL_NAME, config=GenerateConfig(
        reasoning_tokens=TEACHER_REASONING_TOKENS,
        max_tokens=TEACHER_REASONING_TOKENS + 8000,
        extra_body={"provider": OPENROUTER_PROVIDER},
        timeout=600, max_retries=5, **TEACHER_SAMPLING))
    # Live code calls _judge_model(get_model()); get_model() with no name returns the
    # last-registered default. Emulate by passing the teacher handle itself (that IS what
    # the ambient get_model() resolves to inside the eval).
    return _judge_model(teacher), teacher


async def probe_handle(name, jm, pairs):
    """Run phase-1 raw (to see truncation) and the full _judge_sample (phase-2 score)."""
    print(f"\n#### handle={name}  effective base cfg = {_eff_cfg(jm)}")
    rows = []
    for i, (a, b) in enumerate(pairs):
        base = _base(a, b)
        r1 = await jm.generate(base, config=GenerateConfig(max_tokens=JUDGE_THINK_BUDGET, **JUDGE_THINK))
        comp = r1.completion or ""
        _, _, cfound = _parse_score_quote(comp)
        tail = _reasoning_text(r1)
        stop = getattr(r1, "stop_reason", "?")
        score, forced = await _judge_sample(jm, base, a, b)
        rows.append(dict(i=i, stop=str(stop), comp_len=len(comp), cfound=cfound,
                         tail_len=len(tail), score=score, forced=forced))
        print(f"  [{i}] stop={stop:>12} comp_len={len(comp):>4} cfound={cfound!s:>5} "
              f"tail_len={len(tail):>4} -> score={score} forced={forced}")
    return rows


def summarise(name, rows):
    n = len(rows)
    trunc = sum(1 for r in rows if r["stop"] == "max_tokens")
    empty_tail = sum(1 for r in rows if r["tail_len"] == 0)
    none_score = sum(1 for r in rows if r["score"] is None)
    zero_score = sum(1 for r in rows if r["score"] == 0)
    nonzero = sum(1 for r in rows if r["score"] not in (None, 0))
    print(f"\n== {name}: n={n} | phase1 trunc@budget {trunc}/{n} | empty reasoning_tail "
          f"{empty_tail}/{n} | phase2 None {none_score}/{n} | zero {zero_score}/{n} | "
          f"nonzero {nonzero}/{n}")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-pairs", type=int, default=8)
    args = ap.parse_args()

    cases = [json.loads(l) for l in FIXTURE.read_text().splitlines() if l.strip()]
    pairs = []
    for c in cases:
        resp = sorted(c["responses"], key=lambda r: r["gold_rank"])
        for lo, hi in zip(resp, resp[1:]):
            pairs.append((lo["text"], hi["text"]))
    pairs = pairs[:args.n_pairs]

    gym = build_gym_handle()
    gym_rows = await probe_handle("GYM(clean)", gym, pairs)

    live, teacher = build_live_handle()
    print(f"\n(teacher base cfg = {_eff_cfg(teacher)})")
    print(f"(live judge handle IS teacher handle? {live is teacher})")
    live_rows = await probe_handle("LIVE(from-teacher)", live, pairs)

    print("\n==== PARITY SUMMARY ====")
    summarise("GYM ", gym_rows)
    summarise("LIVE", live_rows)
    same_cfg = _eff_cfg(gym) == _eff_cfg(live)
    print(f"\neffective judge base cfg identical? {same_cfg}")
    print(f"  gym : {_eff_cfg(gym)}")
    print(f"  live: {_eff_cfg(live)}")


if __name__ == "__main__":
    asyncio.run(main())
