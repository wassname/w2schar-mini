"""Manual dogfood: drive the exact core harness one stage at a time.

The human/model teacher supplies only the measured persona-pair choice,
candidate choices, and keep/drop verdict by calling the same pipeline.py
functions the agent tools wrap. It never writes personas or pair prose.

`auto-select` is the deterministic selection lesion: after a human picks the
measured pair and scenario family with `choose`, it selects the highest
template-score surviving candidate per scenario so we can test whether the
prompt/persona/training path moves at all before spending more complexity on a
weak selector.

Usage:
  python scripts/dogfood_round.py init   <slug> [profile]
  python scripts/dogfood_round.py choose <focus.json>   # {persona_pair_id,scenario_family}
  python scripts/dogfood_round.py select <choices.json> # {lesson,choices:{scenario_id:candidate_id}}
  python scripts/dogfood_round.py auto-select <lesson.txt>
  python scripts/dogfood_round.py train
  python scripts/dogfood_round.py drop <reason.txt>
  python scripts/dogfood_round.py advance
  python scripts/dogfood_round.py exam    <verdict.json>     # {keep,reason,pre,post,next_focus}
"""
import sys, json
from pathlib import Path

from csm.config import CONFIGS
from csm.pipeline import (init_run, prepare_round, latest_round_dir,
                          choose_focus, select_pairs, train_student, mark_exam,
                          new_round_dir)
from csm.state import read_state

STATE = Path("out/iter/_dogfood_state.json")
stage = sys.argv[1]


def _slug() -> Path:
    return Path(json.loads(STATE.read_text())["slug"])


if stage == "init":
    slug = Path(sys.argv[2])
    profile = sys.argv[3] if len(sys.argv) > 3 else "qwen27b-w2s"
    cfg = CONFIGS[profile]
    init_run(slug, cfg.model, profile=profile)
    rd = latest_round_dir(slug)
    prepare_round(slug, rd)
    STATE.write_text(json.dumps({"slug": str(slug)}))
    print(f"INIT DONE  slug={slug}  round={rd.name}  profile={profile}  model={cfg.model}")
    print("SHOULD: interview_pre.json written (probes @ c=0). Read it next.")

elif stage == "choose":
    slug, rd = _slug(), latest_round_dir(_slug())
    p = json.loads(Path(sys.argv[2]).read_text())
    res = choose_focus(
        slug,
        rd,
        persona_pair_id=p["persona_pair_id"],
        scenario_family=p.get("scenario_family", "mixed"),
    )
    print(f"CHOOSE  scenarios={res['n_scenarios']} headroom={res['n_headroom']} "
          f"survivors={res['n_with_survivor']} enough={res['enough']} "
          f"min={res['min_to_train']}")

elif stage == "select":
    rd = latest_round_dir(_slug())
    s = json.loads(Path(sys.argv[2]).read_text())
    res = select_pairs(rd, lesson=s["lesson"], choices=s["choices"])
    print(f"SELECT  n_pairs={res['n_pairs']}")

elif stage == "auto-select":
    rd = latest_round_dir(_slug())
    lesson = Path(sys.argv[2]).read_text().strip()
    candidates = json.loads((rd / "candidates.json").read_text())
    choices = {}
    for item in candidates["items"]:
        survivors = [c for c in item["candidates"] if c["kept"]]
        if not survivors:
            continue
        best = max(survivors, key=lambda c: (c["template_score"], -c["candidate_id"]))
        choices[str(item["scenario_id"])] = int(best["candidate_id"])
    res = select_pairs(rd, lesson=lesson, choices=choices)
    print(f"AUTO-SELECT  n_pairs={res['n_pairs']}  choices={json.dumps(choices, sort_keys=True)}")

elif stage == "train":
    slug, rd = _slug(), latest_round_dir(_slug())
    r = train_student(slug, rd)
    print(f"TRAIN  signed_C={r['signed_C']:+.4f}  n_trained={r['n_pairs_trained']}")

elif stage == "drop":
    rd = latest_round_dir(_slug())
    reason = Path(sys.argv[2]).read_text().strip()
    mark_exam(rd, keep=False, reason=reason)
    print("DROP  keep=False")

elif stage == "advance":
    slug = _slug()
    rd = latest_round_dir(slug)
    st = read_state(rd)
    if st.state != "done":
        sys.exit(f"cannot advance: {rd.name} is not done (state={st.state})")
    nxt = new_round_dir(slug)
    prepare_round(slug, nxt)
    print(f"ADVANCE  new_round={nxt.name}")

elif stage == "exam":
    rd = latest_round_dir(_slug())
    v = json.loads(Path(sys.argv[2]).read_text())
    mark_exam(rd, keep=v["keep"], reason=v["reason"],
              pre_scores=v["pre"], post_scores=v["post"], next_focus=v["next_focus"])
    print(f"EXAM  keep={v['keep']}")

else:
    sys.exit(f"unknown stage: {stage}")
