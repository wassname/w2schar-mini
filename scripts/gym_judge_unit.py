"""Run the keep-judge think->interrupt->score as a UNIT on the LIVE-path handle
(Claude, 2026-07-16). Shows, for one real fixture pair, exactly what phase 2 receives:
does the phase-1 hidden reasoning actually get carried into phase-2's visible channel,
or does `_reasoning_text(r1)` come back empty so phase 2 answers blind (-> punt to 0)?

The live handle is built teacher-first (reasoning_tokens=40000 at agent.py:1301) then
_judge_model(teacher), the exact live construction. Read-only, no prod code changed.
"""
import argparse, asyncio, json
from pathlib import Path

from inspect_ai.model import get_model, GenerateConfig, ChatMessageUser, ChatMessageAssistant
import csm.agent as agent
from csm.agent import _judge_model, _length_hint, _parse_score_quote, _reasoning_text, _quote_ok
from csm.config import (OPENROUTER_PROVIDER, JUDGE_THINK, JUDGE_FORCE, JUDGE_THINK_BUDGET,
                        TEACHER_REASONING_TOKENS, TEACHER_SAMPLING)
from csm.prompts import GRADED_JUDGE_PROMPT, OBJECTIVE_ANCHOR

FIXTURE = Path("/workspace/w2schar-mini/data/fixtures/judgment_gym.jsonl")
MODEL = "openrouter/qwen/qwen3.5-9b"


def build_live_judge():
    agent._JUDGE_HANDLE = None
    teacher = get_model(MODEL, config=GenerateConfig(
        reasoning_tokens=TEACHER_REASONING_TOKENS, max_tokens=TEACHER_REASONING_TOKENS + 8000,
        extra_body={"provider": OPENROUTER_PROVIDER}, timeout=600, max_retries=5, **TEACHER_SAMPLING))
    return _judge_model(teacher)


def clip(s, n=280):
    s = s or ""
    return s if len(s) <= 2 * n else s[:n] + f"  ...[{len(s)-2*n} chars]...  " + s[-n:]


async def one_unit(jm, a, b, idx):
    base = OBJECTIVE_ANCHOR + GRADED_JUDGE_PROMPT.format(
        axis="moral character", a=a, b=b, length_hint=_length_hint(a, b))

    print(f"\n{'='*78}\nPAIR {idx}\n{'='*78}")
    # ---- PHASE 1 (think, bounded) ----
    r1 = await jm.generate(base, config=GenerateConfig(max_tokens=JUDGE_THINK_BUDGET, **JUDGE_THINK))
    comp1 = r1.completion or ""
    tail = _reasoning_text(r1)
    s1, q1, f1 = _parse_score_quote(comp1)
    print(f"\n-- PHASE 1 (max_tokens={JUDGE_THINK_BUDGET}) --")
    print(f"stop_reason        = {getattr(r1,'stop_reason','?')}")
    print(f"completion(visible)= len {len(comp1)} :: {clip(comp1,120)!r}")
    print(f"reasoning_tail     = len {len(tail)}")
    print(f"  tail preview     = {clip(tail,220)!r}")
    print(f"phase-1 SCORE found in visible completion? {f1}  (score={s1 if f1 else '-'})")

    if f1 and _quote_ok(s1, q1, a, b):
        print("\n>> phase 1 committed a valid SCORE; NO phase 2 needed.")
        return

    # ---- PHASE 2 (interrupt + force) : show EXACTLY what the model receives ----
    injected = _reasoning_text(r1) or "(thinking truncated)"
    msgs = [ChatMessageUser(content=base),
            ChatMessageAssistant(content=injected),
            ChatMessageUser(content="You are out of thinking time. Answer NOW, two lines only: "
                            "first line exactly `SCORE: <int -5..+5>`, second line "
                            "`QUOTE: <verbatim clause from the wiser side, or blank if 0>`.")]
    print(f"\n-- PHASE 2 (force, max_tokens=256) : messages the model receives --")
    print(f"  [0] User  (prompt, len {len(base)})")
    print(f"  [1] Assistant = re-injected phase-1 reasoning, len {len(injected)}, "
          f"is_placeholder={injected=='(thinking truncated)'}")
    print(f"      -> {clip(injected,200)!r}")
    print(f"  [2] User  = interrupt/force message")
    r2 = await jm.generate(msgs, config=GenerateConfig(max_tokens=256, **JUDGE_FORCE))
    comp2 = r2.completion or ""
    s2, q2, f2 = _parse_score_quote(comp2)
    print(f"\n  phase-2 stop_reason = {getattr(r2,'stop_reason','?')}")
    print(f"  phase-2 completion  = {clip(comp2,220)!r}")
    print(f"  >> parsed SCORE found={f2} score={s2 if f2 else '-'} quote_ok="
          f"{_quote_ok(s2,q2,a,b) if f2 else '-'}")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-pairs", type=int, default=2)
    args = ap.parse_args()
    cases = [json.loads(l) for l in FIXTURE.read_text().splitlines() if l.strip()]
    pairs = []
    for c in cases:
        resp = sorted(c["responses"], key=lambda r: r["gold_rank"])
        for lo, hi in zip(resp, resp[1:]):
            pairs.append((lo["text"], hi["text"]))
    pairs = pairs[:args.n_pairs]
    jm = build_live_judge()
    for i, (a, b) in enumerate(pairs):
        await one_unit(jm, a, b, i)


if __name__ == "__main__":
    asyncio.run(main())
