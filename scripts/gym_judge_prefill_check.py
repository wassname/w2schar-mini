"""De-risk the phase-2 prefill (Claude, 2026-07-16): does OpenRouter+Qwen honor a trailing
ChatMessageAssistant as a PREFILL (continue it), and do we now get a specific decimal instead
of a bare 0? Replicates the exact new _judge_sample phase-2 and prints the RAW completion for
a genuine-tie pair (should give a small decimal that the deadband still reads as a tie) and a
clearly-different pair (should give a clear positive). Read-only.
"""
import asyncio, json
from pathlib import Path
from inspect_ai.model import get_model, GenerateConfig, ChatMessageUser, ChatMessageAssistant
import csm.agent as agent
from csm.agent import (_judge_model, _length_hint, _reasoning_text, _parse_score_quote,
                       _last_act, FORCE_ANSWER)

# The prefill this script tested was found inert (not honored by OpenRouter+Qwen) and REMOVED
# from prod (_judge_sample). Kept here as the historical repro that showed it doesn't continue.
FORCE_PREFILL = "answer is SCORE: "
from csm.config import (OPENROUTER_PROVIDER, JUDGE_THINK, JUDGE_FORCE, JUDGE_THINK_BUDGET,
                        TEACHER_REASONING_TOKENS, TEACHER_SAMPLING)
from csm.prompts import GRADED_JUDGE_PROMPT, OBJECTIVE_ANCHOR

agent._JUDGE_HANDLE = None
teacher = get_model("openrouter/qwen/qwen3.5-9b", config=GenerateConfig(
    reasoning_tokens=TEACHER_REASONING_TOKENS, max_tokens=TEACHER_REASONING_TOKENS + 8000,
    extra_body={"provider": OPENROUTER_PROVIDER}, timeout=600, max_retries=5, **TEACHER_SAMPLING))
jm = _judge_model(teacher)

R = Path("out/iter/20260715T071652_iter_qwen-qwen3.6-27b/round08")
pre = {p["id"]: _last_act(p) for p in json.loads((R/"interview_pre.json").read_text())["questions"]}
post = {p["id"]: _last_act(p) for p in json.loads((R/"interview_post.json").read_text())["questions"]}
tie = (pre["elder_isolation_1p"], post["elder_isolation_1p"])
cases = [json.loads(l) for l in Path("tests/fixtures/judgment_gym.jsonl").read_text().splitlines() if l.strip()]
r = sorted(cases[0]["responses"], key=lambda x: x["gold_rank"])
diff = (r[-1]["text"], r[0]["text"])  # worst(A) vs best(B) -> expect POSITIVE (second wiser)


async def phase2(a, b, tag, n=3):
    base = OBJECTIVE_ANCHOR + GRADED_JUDGE_PROMPT.format(axis="moral character", a=a, b=b,
                                                         length_hint=_length_hint(a, b))
    async def one(i):
        r1 = await jm.generate(base, config=GenerateConfig(max_tokens=JUDGE_THINK_BUDGET, **JUDGE_THINK))
        msgs = [ChatMessageUser(content=base),
                ChatMessageAssistant(content=(_reasoning_text(r1) or "(thinking truncated)")),
                ChatMessageUser(content=FORCE_ANSWER),
                ChatMessageAssistant(content=FORCE_PREFILL)]
        r2 = await jm.generate(msgs, config=GenerateConfig(max_tokens=256, **JUDGE_FORCE))
        comp = r2.completion or ""
        score, quote, found = _parse_score_quote(FORCE_PREFILL + comp)
        print(f"[{tag}][{i}] stop2={getattr(r2,'stop_reason','?')} score={score} found={found}\n"
              f"    RAW comp={comp[:160]!r}", flush=True)
        return score
    scores = await asyncio.gather(*[one(i) for i in range(n)])
    print(f">>> {tag}: scores={scores} mean={sum(scores)/len(scores):+.2f}\n", flush=True)


async def main():
    await phase2(*tie, "TIE(elder r08)")
    await phase2(*diff, "DIFF(worst-vs-best)")

asyncio.run(main())
