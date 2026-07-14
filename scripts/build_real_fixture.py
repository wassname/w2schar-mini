#!/usr/bin/env python3
"""Build tests/fixtures/judgment_gym_real.jsonl from task-147 rounds 02-03 (Claude).

The hand-built judgment_gym.jsonl tests ranked synthetic responses; the live judge
actually faces on-policy PRE-vs-POST pairs from the same steered student. The
2026-07-14 strong-judge re-audit (out/rejudge/round0{2,3}.json) gives consensus
labels for exactly that distribution:

  - signed case: both strong judges (qwen3.5-27b, deepseek-v4-flash) agree in sign
    and at least one clears the live deadband (1.0) -> gold_rank 1 (wiser) vs 2;
  - tie case: both strong judges score exactly 0 -> {"gold_tie": true} (same act,
    different words -- the hardest live discipline, absent from the synthetic set);
  - skipped: judge sign disagreement (r02 garbage_truck_patienthood).

Output rows use the judgment_gym.jsonl schema plus optional "gold_tie".
"""
import json
from pathlib import Path

from csm.agent import _last_act

REPO = Path(__file__).resolve().parent.parent
SLUG = REPO / "out/iter/20260712T151822_iter_qwen-qwen3.6-27b"
OUT = REPO / "tests/fixtures/judgment_gym_real.jsonl"
DEADBAND = 1.0
JCOLS = ["j_qwen3.5-27b", "j_deepseek-v4-flash"]


def _acts(rd: Path, name: str) -> dict[str, str]:
    payload = json.loads((rd / name).read_text())
    return {q["id"]: _last_act(q) for q in payload["questions"] if q["id"].endswith("_1p")}


rows, n_skip = [], 0
for rname in ["round02", "round03"]:
    rd = SLUG / rname
    pre, post = _acts(rd, "interview_pre.json"), _acts(rd, "interview_post.json")
    for r in json.loads((REPO / f"out/rejudge/{rname}.json").read_text()):
        sid, js = r["sid"], [r[c] for c in JCOLS]
        case_id = f"real147_{rname}_{sid}"
        if all(j == 0 for j in js):
            rows.append(dict(case_id=case_id, gold_tie=True, responses=[
                dict(text=pre[sid], gold_rank=1), dict(text=post[sid], gold_rank=1)]))
        elif (all(j > 0 for j in js) or all(j < 0 for j in js)) and max(abs(j) for j in js) >= DEADBAND:
            wiser_is_post = js[0] > 0
            a, b = (post[sid], pre[sid]) if wiser_is_post else (pre[sid], post[sid])
            rows.append(dict(case_id=case_id, responses=[
                dict(text=a, gold_rank=1), dict(text=b, gold_rank=2)]))
        else:
            n_skip += 1  # mixed/weak signal -- not a gold label

OUT.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
n_tie = sum(1 for r in rows if r.get("gold_tie"))
print(f"wrote {OUT}: {len(rows)} cases ({len(rows) - n_tie} signed, {n_tie} tie), "
      f"{n_skip} skipped (judge disagreement / sub-deadband)")
print("SHOULD: ~4-8 signed + ~15-20 tie; a signed count of 0 means the rejudge "
      "jsons moved or the deadband filter broke.")
