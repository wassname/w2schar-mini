"""Per-round orchestration: pre-dialogue → propose → curate → train → judge.

Each agent-callable verb (propose_personas / edit_pairs / train / judge)
delegates to one of these functions. Pipeline writes all artifacts and
mutates the round's state.json transparently.

Artifacts per round (`<slug>/round<NN>/`):
  state.json          — current state (propose|curate|judge|done)
  spec.json           — pos/neg personas + axis label
  pairs.yaml          — current pair set (agent-editable)
  pairs.bk.yaml       — frozen snapshot just after auto-drop
  dropped.json        — list of pairs auto-dropped at gen time
  adapter.safetensors — trained adapter
  calibration.json    — signed_C + c_scan trace
  interview_pre.json  — probes replayed at c=0 (base+history)
  interview_post.json — probes replayed at signed_C
  judgment.json       — agent's keep/drop + reason
"""
from __future__ import annotations

import gc
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import torch
from loguru import logger

from csm.adapter import ModulatedLoRA
from csm.c_scan import c_scan
from csm.config import RunConfig, config_by_model
from csm.dialogue import dialogue, DialogueCfg
from csm.gen import gen_pairs, write_pairs_yaml, load_pairs_yaml
from csm.history import kept_history_dirs, load_base_with_history
from csm.probes import PROBES
from csm.state import (RoundState, advance, read_state, require_state,
                       write_state)
from csm.train import TrainCfg, train_adapter

AXIS = "less deference to authority"          # fixed for this repo
SIGN = +1                                     # +C = more "less authority"


# ---------------------------------------------------------------------------
# Per-slug bootstrap
# ---------------------------------------------------------------------------

def init_run(slug_dir: Path, model: str, teacher: str | None = None) -> Path:
    """Create slug dir + run.json + round00/state.json=propose."""
    slug_dir.mkdir(parents=True, exist_ok=True)
    run = {
        "model": model,
        "teacher": teacher or config_by_model(model).teacher,
        "axis": AXIS,
        "created_utc": datetime.now(timezone.utc).isoformat(),
    }
    (slug_dir / "run.json").write_text(json.dumps(run, indent=2))
    round_dir = slug_dir / "round00"
    round_dir.mkdir(exist_ok=True)
    if not (round_dir / "state.json").exists():
        write_state(round_dir, RoundState(state="propose"))
    return round_dir


def latest_round_dir(slug_dir: Path) -> Path:
    rounds = sorted(p for p in slug_dir.glob("round*") if p.is_dir())
    if not rounds:
        raise FileNotFoundError(f"no round* under {slug_dir}")
    return rounds[-1]


def new_round_dir(slug_dir: Path) -> Path:
    """Allocate the next roundNN under slug_dir, scaffold state.json."""
    existing = sorted(p.name for p in slug_dir.glob("round*") if p.is_dir())
    n = 0
    if existing:
        last = existing[-1]
        n = int(last.replace("round", "")) + 1
    rd = slug_dir / f"round{n:02d}"
    rd.mkdir(exist_ok=True)
    write_state(rd, RoundState(state="propose"))
    return rd


# ---------------------------------------------------------------------------
# Pre-dialogue (run once per round before propose).
# ---------------------------------------------------------------------------

def run_pre_dialogue(slug_dir: Path, round_dir: Path) -> dict:
    """Replay probes at c=0 (base + kept history). Idempotent."""
    out = round_dir / "interview_pre.json"
    if out.exists():
        return json.loads(out.read_text())
    run = json.loads((slug_dir / "run.json").read_text())
    cfg = config_by_model(run["model"])
    history = kept_history_dirs(slug_dir, before_round=int(round_dir.name.replace("round", "")))
    model, tok, _ = load_base_with_history(cfg.model, history)
    dcfg = DialogueCfg(max_new_tokens=cfg.dialogue_max_new_tokens,
                       enable_thinking=cfg.enable_thinking)
    payload = dialogue(model, tok, PROBES, out, lora=None, c=0.0, cfg=dcfg)
    del model
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    return payload


# ---------------------------------------------------------------------------
# Verb 1: propose_personas
# ---------------------------------------------------------------------------

def propose(slug_dir: Path, round_dir: Path, pos_persona: str, neg_persona: str) -> dict:
    require_state(round_dir, "propose", "propose_personas")
    run = json.loads((slug_dir / "run.json").read_text())
    cfg = config_by_model(run["model"])

    spec = {
        "axis": AXIS,
        "pos_persona": pos_persona,
        "neg_persona": neg_persona,
        "sign": SIGN,
        "ts_utc": datetime.now(timezone.utc).isoformat(),
    }
    (round_dir / "spec.json").write_text(json.dumps(spec, indent=2))

    history = kept_history_dirs(slug_dir, before_round=int(round_dir.name.replace("round", "")))
    model, tok, _ = load_base_with_history(cfg.model, history)
    alive, dropped = gen_pairs(
        model, tok, pos_persona, neg_persona,
        n_pairs=cfg.n_pairs, batch_size=cfg.gen_batch_size,
        max_new_tokens=cfg.max_new_tokens, enable_thinking=cfg.enable_thinking,
    )
    del model
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    write_pairs_yaml(round_dir / "pairs.yaml", alive)
    write_pairs_yaml(round_dir / "pairs.bk.yaml", alive)
    (round_dir / "dropped.json").write_text(json.dumps(dropped, indent=2))

    min_alive = max(2, cfg.n_pairs // 4)     # scales with n_pairs so smoke (n=4) passes
    if len(alive) < min_alive:
        raise RuntimeError(
            f"propose_personas: only {len(alive)} pairs alive after auto-drop "
            f"({len(dropped)} double-refusals); need >= {min_alive}. "
            f"Rewrite personas."
        )

    advance(round_dir, note=f"alive={len(alive)} dropped={len(dropped)}")
    return {
        "n_alive": len(alive),
        "n_dropped": len(dropped),
        "dropped_ids": [d["id"] for d in dropped],
        "preview": _compact_preview(alive, n_max=6),
    }


def _compact_preview(pairs: list[dict], n_max: int = 6) -> list[dict]:
    return [
        {"id": p["id"],
         "prompt": (p["prompt"][:80] + "…") if len(p["prompt"]) > 80 else p["prompt"],
         "cho_head": (p["cho"].strip()[:120].replace("\n", " ⏎ ")),
         "rej_head": (p["rej"].strip()[:120].replace("\n", " ⏎ "))}
        for p in pairs[:n_max]
    ]


# ---------------------------------------------------------------------------
# Verb 2: edit_pairs — bulk rewrite of pairs.yaml
# ---------------------------------------------------------------------------

def edit(round_dir: Path, new_yaml_text: str) -> dict:
    require_state(round_dir, "curate", "edit_pairs")
    import yaml
    pairs = yaml.safe_load(new_yaml_text)
    if not isinstance(pairs, list):
        raise ValueError("edit_pairs: top-level YAML must be a list of pairs")
    for i, row in enumerate(pairs):
        if row is None:
            continue
        for k in ("id", "prompt", "cho", "rej"):
            if k not in row:
                raise ValueError(f"edit_pairs: pair {i} missing key {k!r}; got {list(row)}")
    pairs = [r for r in pairs if r is not None]
    # Renumber to contiguous range so the agent's index references stay stable.
    for new_id, r in enumerate(pairs):
        r["id"] = new_id
    write_pairs_yaml(round_dir / "pairs.yaml", pairs)
    bk = load_pairs_yaml(round_dir / "pairs.bk.yaml")
    return {"n_alive": len(pairs), "n_original": len(bk),
            "n_changed_vs_bk": _count_changed(pairs, bk)}


def _count_changed(cur: list[dict], orig: list[dict]) -> int:
    by_prompt = {p["prompt"]: p for p in orig}
    n = 0
    for r in cur:
        o = by_prompt.get(r["prompt"])
        if o is None or o.get("cho") != r["cho"] or o.get("rej") != r["rej"]:
            n += 1
    return n


# ---------------------------------------------------------------------------
# Verb 3: train (also runs c_scan + post-dialogue).
# ---------------------------------------------------------------------------

def train_and_eval(slug_dir: Path, round_dir: Path) -> dict:
    require_state(round_dir, "curate", "train")
    run = json.loads((slug_dir / "run.json").read_text())
    cfg = config_by_model(run["model"])

    pairs = load_pairs_yaml(round_dir / "pairs.yaml")
    if not pairs:
        raise RuntimeError("train: pairs.yaml is empty")

    history = kept_history_dirs(slug_dir, before_round=int(round_dir.name.replace("round", "")))
    model, tok, hb = load_base_with_history(cfg.model, history)

    steps = max(20, int(len(pairs) / cfg.train_batch_size * cfg.n_epochs))
    tcfg = TrainCfg(
        r=cfg.lora_r, alpha=cfg.lora_alpha, targets=cfg.targets,
        steps=steps, batch_size=cfg.train_batch_size, lr=cfg.lr,
        max_len=cfg.max_len, kl_lambda=cfg.kl_lambda,
    )
    lora = train_adapter(model, tok, pairs, tcfg,
                         history_bake=hb, enable_thinking=cfg.enable_thinking)

    # ── C-scan ─────────────────────────────────────────────────────────
    probe_prompts = [p["opening"] for p in PROBES]
    signed_C, trace = c_scan(
        model, tok, lora, probe_prompts,
        init_c=1.0, sign=SIGN, n_gen=cfg.cscan_n_gen, k=cfg.cscan_k,
        batch_size=cfg.eval_batch_size,
    )

    lora.save(str(round_dir / "adapter.safetensors"),
              extra_meta={"axis": AXIS, "sign": str(SIGN)})
    (round_dir / "calibration.json").write_text(json.dumps({
        "signed_C": signed_C,
        "sign": SIGN,
        "cscan_trace": trace,
        "kl_lambda": tcfg.kl_lambda,
        "steps": tcfg.steps,
    }, indent=2))

    # ── post-dialogue under adapter @ signed_C ──────────────────────────
    dcfg = DialogueCfg(max_new_tokens=cfg.dialogue_max_new_tokens,
                       enable_thinking=cfg.enable_thinking)
    post = dialogue(model, tok, PROBES,
                    round_dir / "interview_post.json",
                    lora=lora, c=signed_C, cfg=dcfg)

    del model, lora
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    advance(round_dir, note=f"signed_C={signed_C:+.4f}")
    return {
        "signed_C": signed_C,
        "n_probes_post": len(post["probes"]),
    }


# ---------------------------------------------------------------------------
# Verb 4: judge
# ---------------------------------------------------------------------------

def judge(round_dir: Path, keep: bool, reason: str) -> dict:
    require_state(round_dir, "judge", "judge")
    judgment = {
        "action": "keep" if keep else "drop",
        "reasoning": reason,
        "ts_utc": datetime.now(timezone.utc).isoformat(),
    }
    (round_dir / "judgment.json").write_text(json.dumps(judgment, indent=2))
    advance(round_dir, note=judgment["action"])
    return judgment
