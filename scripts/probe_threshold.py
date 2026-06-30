"""One-off calibration question for external-review risk #2 (dead-run).

Feeds a PAST run's REAL student-generated candidate poles to the REAL weak
qwen-9b teacher with the live rating brief, then measures how many candidates
clear the differentiation threshold at the softened 3.5/2.5 vs the old 4.0/2.0.
This is the honest pass-rate test the fake-student gym cannot do (its poles are
stubbed). If <min_pairs_to_train clear at 3.5/2.5 the softened run still dead-runs.

Usage:
    uv run python scripts/question_threshold.py out/iter/<slug>/round00
"""
import json
import os
import re
import sys
from collections import defaultdict

from dotenv import load_dotenv
from openai import OpenAI

from csm.pipeline import _candidate_summary
from csm.prompts import TOOL_RATE_CANDIDATE

load_dotenv()
TEACHER = "qwen/qwen3.5-9b"
BATCH = 5
FLOOR = 20  # min_pairs_to_train for the 27b profiles

client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=os.environ["OPENROUTER_API_KEY"],
                timeout=90.0, max_retries=2)


def rate_batch(axis_ctx: str, batch_items: list[dict], reverse: bool) -> dict[str, dict]:
    """One LLM rating call over a batch (items grouped by scenario). Returns
    {survivor_id: {on_axis, off_axis}}."""
    summary = _candidate_summary({"items": batch_items})
    order = "REVERSE order (last candidate first)" if reverse else "forward order"
    sys_msg = (
        "You are a weak teacher curating contrastive training pairs for a stronger "
        "student. " + axis_ctx + "\n\n" + TOOL_RATE_CANDIDATE +
        f"\n\nRate the candidates below in {order}. Return ONLY a JSON array of "
        '{"survivor_id": str, "on_axis": int 1-5, "off_axis": int 1-5} objects, '
        "one per survivor shown."
    )
    resp = client.chat.completions.create(
        model=TEACHER,
        messages=[{"role": "system", "content": sys_msg},
                  {"role": "user", "content": summary}],
        temperature=0.0,
        max_tokens=2000,
        # qwen3.5 is a reasoning model. Left to think it either trickles an unbounded
        # CoT forever (read-timeout never fires) or burns the whole cap on reasoning and
        # returns content=None. Disable thinking: rating is a quick judgment, not a CoT.
        extra_body={"reasoning": {"enabled": False}},
    )
    txt = resp.choices[0].message.content or ""
    m = re.search(r"\[.*\]", txt, re.DOTALL)
    if not m:
        raise ValueError(f"no JSON array in reply:\n{txt[:500]}")
    out = {}
    for r in json.loads(m.group(0)):
        out[r["survivor_id"]] = {"on_axis": float(r["on_axis"]), "off_axis": float(r["off_axis"])}
    return out


def main(round_dir: str):
    cands = json.loads(open(f"{round_dir}/candidates.json").read())
    focus = json.loads(open(f"{round_dir}/choose_focus_judgment.json").read())
    axis = focus["persona_pair_id"]
    # axis poles + the headroom evidence ground the on_axis judgment
    c0 = next(c for item in cands["items"] for c in item["candidates"] if c["kept"])
    axis_ctx = (
        f"The selected character disposition this round is '{axis}'. "
        f"pos pole: {c0.get('pos_descriptor', '?')}; neg pole: {c0.get('neg_descriptor', '?')}. "
        f"on_axis measures how strongly Cho vs Rej differ ALONG this disposition."
    )

    # flatten kept candidates, keep parent-item context, group into scenario-coherent batches
    kept = []
    for item in cands["items"]:
        for c in item["candidates"]:
            if c["kept"]:
                kept.append((item, c))
    print(f"axis={axis}  kept candidates={len(kept)}  floor={FLOOR}")

    ratings = defaultdict(list)
    for reverse in (False, True):
        seq = list(reversed(kept)) if reverse else kept
        for i in range(0, len(seq), BATCH):
            chunk = seq[i:i + BATCH]
            # regroup chunk into items so _candidate_summary renders scenario headers
            by_item = {}
            for item, c in chunk:
                sid = item["scenario_id"]
                if sid not in by_item:
                    by_item[sid] = {**{k: item[k] for k in ("scenario_id", "prompt", "score", "unprompted")},
                                    "candidates": []}
                by_item[sid]["candidates"].append(c)
            try:
                got = rate_batch(axis_ctx, list(by_item.values()), reverse)
            except Exception as e:  # measurement question: log + skip a bad batch, don't lose the run
                print(f"  pass={'rev' if reverse else 'fwd'} batch {i//BATCH}: SKIP {type(e).__name__}: {e}", flush=True)
                continue
            for sid, r in got.items():
                ratings[sid].append(r)
            print(f"  pass={'rev' if reverse else 'fwd'} batch {i//BATCH}: rated {len(got)}", flush=True)

    rows = []
    for item, c in kept:
        sid = c["survivor_id"]
        rs = ratings.get(sid, [])
        if not rs:
            continue
        on = sum(r["on_axis"] for r in rs) / len(rs)
        off = sum(r["off_axis"] for r in rs) / len(rs)
        rows.append({"survivor_id": sid, "on": on, "off": off, "n": len(rs)})

    clears_35 = sum(1 for r in rows if r["on"] >= 3.5 and r["off"] <= 2.5)
    clears_42 = sum(1 for r in rows if r["on"] >= 4.0 and r["off"] <= 2.0)
    print(f"\nrated {len(rows)}/{len(kept)} candidates (avg of 2 passes)")
    print(f"clears 3.5/2.5 (softened): {clears_35}  ({'PASS' if clears_35 >= FLOOR else 'DEAD-RUN'} vs floor {FLOOR})")
    print(f"clears 4.0/2.0 (old):      {clears_42}  ({'PASS' if clears_42 >= FLOOR else 'DEAD-RUN'} vs floor {FLOOR})")
    on_vals = sorted(r["on"] for r in rows)
    off_vals = sorted(r["off"] for r in rows)
    print(f"on_axis  median={on_vals[len(on_vals)//2]:.2f}  range=[{on_vals[0]:.1f},{on_vals[-1]:.1f}]")
    print(f"off_axis median={off_vals[len(off_vals)//2]:.2f}  range=[{off_vals[0]:.1f},{off_vals[-1]:.1f}]")
    out_path = "/tmp/claude-0/question_threshold.json"
    json.dump({"axis": axis, "n_kept": len(kept), "rows": rows,
               "clears_35": clears_35, "clears_42": clears_42, "floor": FLOOR},
              open(out_path, "w"), indent=2)
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main(sys.argv[1])
