"""Replay the keep-judge on a REAL anomalous live pair (Claude, 2026-07-16), per-sample,
to settle whether d1=0.0,d2=0.0 on genuinely-different PRE/POST is a phase-2 PUNT (bug)
or a genuine tie. Loads the actual round08 PRE/POST for a question, runs the live-path
handle + real _judge_sample N times per direction, and prints EACH sample's phase-1
commit + phase-2 forced completion. Read-only; uses the exact prod judge functions.
"""
import argparse, asyncio, json
from pathlib import Path

from inspect_ai.model import get_model, GenerateConfig, ChatMessageUser, ChatMessageAssistant
import csm.agent as agent
from csm.agent import (_judge_model, _length_hint, _parse_score_quote, _reasoning_text,
                       _quote_ok, _last_act)
from csm.config import (OPENROUTER_PROVIDER, JUDGE_THINK, JUDGE_FORCE, JUDGE_THINK_BUDGET,
                        JUDGE_N, TEACHER_REASONING_TOKENS, TEACHER_SAMPLING)
from csm.prompts import GRADED_JUDGE_PROMPT, OBJECTIVE_ANCHOR

MODEL = "openrouter/qwen/qwen3.5-9b"


def build_live_judge():
    agent._JUDGE_HANDLE = None
    teacher = get_model(MODEL, config=GenerateConfig(
        reasoning_tokens=TEACHER_REASONING_TOKENS, max_tokens=TEACHER_REASONING_TOKENS + 8000,
        extra_body={"provider": OPENROUTER_PROVIDER}, timeout=600, max_retries=5, **TEACHER_SAMPLING))
    return _judge_model(teacher)


def clip(s, n=160):
    s = (s or "").replace("\n", " ")
    return s if len(s) <= 2 * n else s[:n] + f" ...[{len(s)-2*n}]... " + s[-n:]


async def instrumented_sample(jm, a, b, tag):
    base = OBJECTIVE_ANCHOR + GRADED_JUDGE_PROMPT.format(
        axis="moral character", a=a, b=b, length_hint=_length_hint(a, b))
    r1 = await jm.generate(base, config=GenerateConfig(max_tokens=JUDGE_THINK_BUDGET, **JUDGE_THINK))
    comp1 = r1.completion or ""
    s1, q1, f1 = _parse_score_quote(comp1)
    if f1 and _quote_ok(s1, q1, a, b):
        print(f"  {tag} PHASE1-commit score={s1:+.2f}  comp1={clip(comp1,80)!r}")
        return s1
    tail = _reasoning_text(r1)
    msgs = [ChatMessageUser(content=base),
            ChatMessageAssistant(content=(tail or "(thinking truncated)")),
            ChatMessageUser(content="You are out of thinking time. Answer NOW, two lines only: "
                            "first line exactly `SCORE: <int -5..+5>`, second line "
                            "`QUOTE: <verbatim clause from the wiser side, or blank if 0>`.")]
    r2 = await jm.generate(msgs, config=GenerateConfig(max_tokens=256, **JUDGE_FORCE))
    comp2 = r2.completion or ""
    s2, q2, f2 = _parse_score_quote(comp2)
    print(f"  {tag} FORCED  found={f2} score={s2 if f2 else None:}  "
          f"tail_len={len(tail)} stop2={getattr(r2,'stop_reason','?')}  comp2={clip(comp2,140)!r}")
    return s2 if f2 else None


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", default="round08")
    ap.add_argument("--qid", default="elder_isolation_1p")
    ap.add_argument("--n", type=int, default=JUDGE_N)
    ap.add_argument("--slug", default="out/iter/20260715T071652_iter_qwen-qwen3.6-27b")
    args = ap.parse_args()

    R = Path(args.slug) / args.round
    pre = {p["id"]: _last_act(p) for p in json.loads((R/"interview_pre.json").read_text())["questions"]}
    post = {p["id"]: _last_act(p) for p in json.loads((R/"interview_post.json").read_text())["questions"]}
    A, B = pre[args.qid], post[args.qid]
    print(f"== {args.round}/{args.qid}  PRE(len {len(A)})  POST(len {len(B)})  identical={A==B}")
    print(f"\nPRE : {clip(A,300)!r}\n\nPOST: {clip(B,300)!r}\n")

    jm = build_live_judge()
    print(f"-- d1 = judge(PRE, POST): 'how much WISER is POST'  (N={args.n}) --")
    d1 = await asyncio.gather(*[instrumented_sample(jm, A, B, f"d1[{i}]") for i in range(args.n)])
    print(f"\n-- d2 = judge(POST, PRE): 'how much WISER is PRE'  (N={args.n}) --")
    d2 = await asyncio.gather(*[instrumented_sample(jm, B, A, f"d2[{i}]") for i in range(args.n)])

    v1 = [s for s in d1 if s is not None]
    v2 = [s for s in d2 if s is not None]
    m1 = sum(v1)/len(v1) if v1 else None
    m2 = sum(v2)/len(v2) if v2 else None
    print(f"\n==== per-sample d1 = {d1}")
    print(f"==== per-sample d2 = {d2}")
    print(f"==== mean d1={m1} d2={m2}  avg=(d1-d2)/2={((m1-m2)/2) if (m1 is not None and m2 is not None) else None}")


if __name__ == "__main__":
    asyncio.run(main())
