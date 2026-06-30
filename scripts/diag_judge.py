"""Diagnose WHY grounding changes the A/B keep-judge's verdicts on a weak model.

For the questions that FLIPPED between baseline and grounded (and the persistent miss),
run ONE judge pass under three conditions and dump what the model actually did:
  base      -- bare slug axis, no prepend (current production)
  lesson    -- rich pole description in slot + the round's lesson prepended (hurt: 13->10)
  character -- terse 2-sentence character anchor, bare slug axis (the simpler retry)

Captures per call: stop_reason (==max_tokens => CUT OFF), reasoning-token count,
reasoning head+tail (to see overthinking / truncation), completion, parsed verdict.
This tests wassname's hypothesis: grounding made the small model overthink / get cut off.

  uv run python scripts/diag_judge.py            # default gold fixture, qwen3.5-9b

Hits the real OpenRouter teacher. One pass per (question, condition); no two-pass/retry.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from tabulate import tabulate

from csm.agent import (AB_JUDGE_PROMPT, _judge_ground, _last_act, _length_hint,
                       _parse_verdict_quote)
from csm.config import TEACHER_SAMPLING, OPENROUTER_PROVIDER
from gym_judge_AB import MINIMAL_CHARACTER  # the terse character anchor under test

REPO = Path(__file__).resolve().parents[1]
DEFAULT_SLUG = REPO / "out/iter/20260629T231056_iter_qwen-qwen3.6-27b"
# the 3 that flipped under lesson-grounding + the 1 both miss (gold POST, both call PRE)
FLIPPED = ["successor_handoff_console_1p", "coup_partial_evidence_1p",
           "asteroid_digital_minds_1p", "look_away_order_1p", "baby_eating_aliens_1p"]


def _acts(slug: Path, phase: str) -> dict[str, str]:
    data = json.loads((slug / "round00" / f"interview_{phase}.json").read_text())
    key = "questions" if "questions" in data else "probes"
    return {p["id"]: _last_act(p) for p in data[key]}


def _reasoning(output) -> str:
    msg = output.choices[0].message
    r = getattr(msg, "reasoning", None)
    if r:
        return r
    if isinstance(msg.content, list):
        return " ".join(getattr(c, "reasoning", "") or "" for c in msg.content)
    return ""


async def _one(model, axis_h: str, a: str, b: str, ground: str) -> dict:
    """Single judge pass (PRE=A, POST=B). Returns the diagnostic record."""
    hint = _length_hint(a, b)
    prompt = ground + AB_JUDGE_PROMPT.format(axis=axis_h, a=a, b=b, length_hint=hint)
    out = await model.generate(prompt)
    verdict, quote = _parse_verdict_quote(out.completion)
    stop = out.choices[0].stop_reason
    usage = out.usage
    reason = _reasoning(out)
    rtok = getattr(usage, "reasoning_tokens", None)
    return {
        "verdict": verdict, "quote": quote, "stop": stop,
        "out_tok": getattr(usage, "output_tokens", None), "reason_tok": rtok,
        "reason_chars": len(reason), "reason_head": reason[:400], "reason_tail": reason[-400:],
        "completion": out.completion.strip()[-300:],
    }


async def run(slug: Path, model_name: str) -> None:
    if not os.environ.get("OPENROUTER_API_KEY"):
        for line in (REPO / ".env").read_text().splitlines():
            if line.startswith("OPENROUTER_API_KEY="):
                os.environ["OPENROUTER_API_KEY"] = line.split("=", 1)[1].strip()
    from inspect_ai.model import get_model, GenerateConfig
    model = get_model(model_name, config=GenerateConfig(
        max_connections=16, timeout=300, max_retries=4,
        max_tokens=16000, reasoning_tokens=16000,
        extra_body={"provider": OPENROUTER_PROVIDER}, **TEACHER_SAMPLING))

    rd = slug / "round00"
    axis_slug = json.loads((rd / "choose_focus_judgment.json").read_text())["persona_pair_id"].replace("_", " ")
    axis_desc = json.loads((rd / "candidates.json").read_text())["axis"]
    lesson = json.loads((rd / "selection_audit.json").read_text())["lesson"]
    pre, post = _acts(slug, "pre"), _acts(slug, "post")

    # (label, axis_h, ground)
    conds = [("base", axis_slug, ""),
             ("lesson", axis_desc, _judge_ground(lesson)),
             ("character", axis_slug, MINIMAL_CHARACTER)]

    rows = []
    dumps = []
    for qid in FLIPPED:
        if qid not in pre:
            continue
        a, b = pre[qid], post[qid]
        recs = await asyncio.gather(*(_one(model, ax, a, b, g) for _, ax, g in conds))
        for (label, _, _g), r in zip(conds, recs):
            cut = "CUT" if r["stop"] == "max_tokens" else r["stop"]
            rows.append([qid.replace("_1p", ""), label, r["verdict"] or "-", cut,
                         r["reason_tok"], r["out_tok"], r["reason_chars"]])
            dumps.append((qid, label, r))

    print(f"\nslug={slug.name}  judge={model_name}  (single PRE=A/POST=B pass per cell)\n")
    print(tabulate(rows, headers=["question", "cond", "verdict", "stop", "r_tok", "o_tok", "r_chars"],
                   tablefmt="pipe"))
    print("\n=== reasoning dumps (head | tail) for the flips ===")
    for qid, label, r in dumps:
        print(f"\n--- {qid.replace('_1p','')} / {label} | verdict={r['verdict']} stop={r['stop']} "
              f"reason_tok={r['reason_tok']} ---")
        print(f"HEAD: {r['reason_head']!r}")
        print(f"TAIL: {r['reason_tail']!r}")
        print(f"COMPLETION: {r['completion']!r}")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", type=Path, default=DEFAULT_SLUG)
    ap.add_argument("--model", default="openrouter/qwen/qwen3.5-9b")
    a = ap.parse_args()
    asyncio.run(run(a.slug, a.model))
