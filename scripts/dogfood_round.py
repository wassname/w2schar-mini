"""Strong-teacher dogfood: drive the EXACT core harness one stage at a time.

I (Claude) play the teacher — supplying the axis/personas, the per-pair edits,
and the keep/drop — by calling the same pipeline.py functions the agent's tools
wrap. Staged so I read artifacts between steps and feel the friction (the point
is an exit interview on harness UX, not a green run). NOT the agent.py react
wrapper (reject counter / state machine) — that layer is critiqued separately.

Usage:
  python scripts/dogfood_round.py init   <slug>
  python scripts/dogfood_round.py propose <personas.json>   # {axis,rationale,pos,neg}
  python scripts/dogfood_round.py edit    <edits.json>       # {pid:{cho,rej}} | {"cull":[pid,...]}
  python scripts/dogfood_round.py train
  python scripts/dogfood_round.py exam    <verdict.json>     # {keep,reason,pre,post,next_focus}
"""
import sys, json
from pathlib import Path

from csm.config import CONFIGS
from csm.pipeline import (init_run, prepare_round, latest_round_dir,
                          propose_personas, read_pair, replace_pair,
                          train_student, mark_exam, pair_flags_table)
from csm.gen.pairs import load_pairs_md

STATE = Path("out/iter/_dogfood_state.json")
stage = sys.argv[1]


def _slug() -> Path:
    return Path(json.loads(STATE.read_text())["slug"])


if stage == "init":
    slug = Path(sys.argv[2])
    cfg = CONFIGS["qwen27b-w2s"]
    init_run(slug, cfg.model, profile="qwen27b-w2s")
    rd = latest_round_dir(slug)
    prepare_round(slug, rd)
    STATE.write_text(json.dumps({"slug": str(slug)}))
    print(f"INIT DONE  slug={slug}  round={rd.name}  model={cfg.model}")
    print("SHOULD: interview_pre.json written (probes @ c=0). Read it next.")

elif stage == "propose":
    slug, rd = _slug(), latest_round_dir(_slug())
    p = json.loads(Path(sys.argv[2]).read_text())
    res = propose_personas(slug, rd, axis=p["axis"], rationale=p["rationale"],
                           pos_persona=p["pos"], neg_persona=p["neg"])
    print(f"PROPOSE  n_pairs={res['n_pairs']}  enough={res['enough']}  min={res['min_to_train']}")
    _, pairs = load_pairs_md(rd / "pairs.md")
    print(pair_flags_table(pairs))

elif stage == "edit":
    rd = latest_round_dir(_slug())
    e = json.loads(Path(sys.argv[2]).read_text())
    if "cull" in e:
        # cull = rewrite pairs.md without the named ids (the move task-58's agent lacked)
        from csm.gen.pairs import write_pairs_md
        lesson, pairs = load_pairs_md(rd / "pairs.md")
        keep = [p for p in pairs if p["id"] not in e["cull"]]
        write_pairs_md(rd / "pairs.md", keep, lesson=lesson)
        print(f"CULLED {e['cull']}  ->  {len(keep)} pairs remain")
    else:
        for pid, ed in e.items():
            r = replace_pair(rd, int(pid), ed["cho"], ed["rej"])
            print(f"replaced pair {r['id']}")
    _, pairs = load_pairs_md(rd / "pairs.md")
    print(pair_flags_table(pairs))

elif stage == "train":
    slug, rd = _slug(), latest_round_dir(_slug())
    r = train_student(slug, rd)
    print(f"TRAIN  signed_C={r['signed_C']:+.4f}  n_trained={r['n_pairs_trained']}")

elif stage == "exam":
    rd = latest_round_dir(_slug())
    v = json.loads(Path(sys.argv[2]).read_text())
    mark_exam(rd, keep=v["keep"], reason=v["reason"],
              pre_scores=v["pre"], post_scores=v["post"], next_focus=v["next_focus"])
    print(f"EXAM  keep={v['keep']}")

else:
    sys.exit(f"unknown stage: {stage}")
