"""Apex measure: blind before/after reasoning-DEPTH judge (primary; tinymfv is
secondary corroboration only -- see docs/spec/20260616_workshop_paper_plan.md).

Character = depth/wisdom of moral reasoning, NOT which action is picked
(CLAUDE.md). So the headline measure compares the student's reasoning BEFORE vs
AFTER the composed adapter stack and asks an independent judge which reasons more
deeply -- blind, so the judge cannot pattern-match "this is the steered one".

Pipeline (the judge step is a separate blind LLM/subagent call, NOT in this file,
on purpose -- this file only does the deterministic, contamination-free parts):

  1. extract: per run, pair round00 interview_pre (c=0 true base) with the LAST
     kept round's interview_post (full composed stack), per question. Emit a
     judge-facing file with Response A / Response B where the A/B order is a
     deterministic per-item flip (neither position nor any framing leaks which is
     steered), and a SEPARATE truth map for decoding.
       uv run python scripts/depth_judge.py extract <run_slug>...   (writes
       depth_twins_judge.json [no truth] + depth_twins_truth.json)
  2. judge: hand depth_twins_judge.json to a blind judge with ONLY the depth
     question -- never a hint, never the tinymfv result, never "this should be a
     reflex" (a primed judge copies the prime; task #21). Use >=2 independent
     judges with different rubric wording; save each as {key: "A"|"B"}.
  3. decode: map picks back to base/steered and tally per run.
       uv run python scripts/depth_judge.py decode <verdict.json>...

Finding on 4b plumbing (RJ 2026-06-18): two judges agreed 16/18; aggressive
steering (c=4) judged base-deeper 6/6 (shallow confront reflex), gentle steering
(c=1) judged steered-deeper 6/6 (near-twins). The biggest tinymfv care move was
the shallowest run -- tinymfv care magnitude anti-correlates with depth.
"""
import json
import sys
from collections import Counter
from pathlib import Path

TWINS = Path("/tmp/claude-1000/depth_twins_judge.json")
TRUTH = Path("/tmp/claude-1000/depth_twins_truth.json")


def _last_kept_post(run_dir: Path) -> Path | None:
    keeps = [j.parent for j in sorted(run_dir.glob("round*/judgment.json"))
             if json.loads(j.read_text()).get("action") == "keep"]
    return keeps[-1] if keeps else None


def _reasoning(question: dict) -> str:
    return "\n\n".join(t["text"] for t in question["turns"] if t["role"] == "assistant")


def extract(run_slugs: list[str]) -> None:
    items, truth = [], {}
    for run in run_slugs:
        rd = Path("out/iter") / run
        base = json.loads((rd / "round00" / "interview_pre.json").read_text())
        fk = _last_kept_post(rd)
        if fk is None:
            print(f"{run}: no kept round, skipping")
            continue
        steered = json.loads((fk / "interview_post.json").read_text())
        base_by_id = {p["id"]: p for p in base["questions"]}
        for sp in steered["questions"]:
            pid = sp["id"]
            if pid not in base_by_id:
                continue
            b_txt, s_txt = _reasoning(base_by_id[pid]), _reasoning(sp)
            if not b_txt.strip() or not s_txt.strip():
                continue
            key = f"{run[:13]}::{pid}"
            flip = sum(ord(c) for c in key) % 2 == 0  # deterministic per-item A/B flip
            A, B = (s_txt, b_txt) if flip else (b_txt, s_txt)
            truth[key] = {"A": "steered", "B": "base"} if flip else {"A": "base", "B": "steered"}
            items.append({"key": key, "question": pid,
                          "prompt": base_by_id[pid]["turns"][0]["text"], "A": A, "B": B})
    TWINS.write_text(json.dumps({"items": items}, indent=1))
    TRUTH.write_text(json.dumps(truth, indent=1))
    print(f"wrote {TWINS} ({len(items)} items, NO truth) and {TRUTH}")


def decode(verdict_paths: list[str]) -> None:
    truth = json.loads(TRUTH.read_text())
    verdicts = [json.loads(Path(p).read_text()) for p in verdict_paths]
    if len(verdicts) == 2:
        agree = sum(1 for k in verdicts[0] if verdicts[0][k] == verdicts[1].get(k))
        print(f"inter-judge agreement: {agree}/{len(verdicts[0])}")
    for i, v in enumerate(verdicts):
        r, byrun = Counter(), Counter()
        for k, pick in v.items():
            d = truth[k][pick]
            r[d] += 1
            byrun[(k.split("::")[0], d)] += 1
        print(f"judge{i}: base-deeper={r['base']} steered-deeper={r['steered']}")
        for run in sorted({k.split("::")[0] for k in v}):
            print(f"  {run}: base={byrun[(run, 'base')]} steered={byrun[(run, 'steered')]}")


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "extract":
        extract(sys.argv[2:])
    elif cmd == "decode":
        decode(sys.argv[2:])
    else:
        raise SystemExit("usage: depth_judge.py extract <slug>... | decode <verdict.json>...")
