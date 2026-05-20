"""Per-round orchestration: pre-dialogue → write_pair → train → judge.

Each agent-callable verb (write_pair / train_student / mark_exam)
delegates to one of these functions. Pipeline writes all artifacts and
mutates the round's state.json transparently.

Artifacts per round (`<slug>/round<NN>/`):
  state.json          — current state (write_pair|train_student|mark_exam|done)
  pairs.md            — current pair set (markdown sections, agent-writable)
  adapter.safetensors — trained adapter
  calibration.json    — signed_C (fixed at config.signed_C; no c-scan)
  interview_pre.json  — probes replayed at c=0 (base+history)
  interview_post.json — probes replayed at signed_C
  judgment.json       — agent's keep/drop + reason
"""
from __future__ import annotations

import gc
import json
from datetime import datetime, timezone
from pathlib import Path

import torch
from inspect_ai.log import transcript

from csm.config import config_by_model
from csm.gen.dialogue import DialogueCfg, dialogue
from csm.gen.pairs import (load_pairs_md, n_filled, seed_pairs_md,
                           write_pairs_md)
from csm.gen.probes import PROBES
from csm.state import (RoundState, ValidationError, require_state, set_state,
                       write_state)
from csm.ws.history import kept_history_dirs, load_base_with_history
from csm.ws.train import TrainCfg, train_adapter

AXIS = "less deference to authority"          # fixed for this repo
SIGN = +1                                     # +C = more "less authority"


# ---------------------------------------------------------------------------
# Per-slug bootstrap
# ---------------------------------------------------------------------------

def init_run(slug_dir: Path, model: str, teacher: str | None = None) -> Path:
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
    _scaffold_round(slug_dir, round_dir, model)
    return round_dir


def latest_round_dir(slug_dir: Path) -> Path:
    rounds = sorted(p for p in slug_dir.glob("round*") if p.is_dir())
    if not rounds:
        raise FileNotFoundError(f"no round* under {slug_dir}")
    return rounds[-1]


def new_round_dir(slug_dir: Path) -> Path:
    """Allocate the next roundNN under slug_dir, scaffold pairs.md + state."""
    existing = sorted(p.name for p in slug_dir.glob("round*") if p.is_dir())
    n = 0
    if existing:
        last = existing[-1]
        n = int(last.replace("round", "")) + 1
    rd = slug_dir / f"round{n:02d}"
    rd.mkdir(exist_ok=True)
    model = json.loads((slug_dir / "run.json").read_text())["model"]
    _scaffold_round(slug_dir, rd, model)
    return rd


def _scaffold_round(slug_dir: Path, round_dir: Path, model: str) -> None:
    """Write pairs.md template + state.json=write_pair. Idempotent."""
    if (round_dir / "state.json").exists():
        return
    cfg = config_by_model(model)
    # Use round index in the seed so different rounds see different prompt
    # samples (avoids 3 rounds with the same 10 prompts).
    try:
        n = int(round_dir.name.replace("round", ""))
    except ValueError:
        n = 0
    seed_pairs_md(
        round_dir / "pairs.md",
        n_seed_prompts=cfg.n_seed_prompts,
        n_total_slots=cfg.n_total_slots,
        seed=42 + n,
    )
    write_state(round_dir, RoundState(state="write_pair"))


# ---------------------------------------------------------------------------
# Pre-dialogue (run once per round before write_pair).
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
# Verb 1: write_pair — teacher fills one slot in pairs.md.
# ---------------------------------------------------------------------------

def write_pair(round_dir: Path, pair_id: int, prompt: str,
               cho: str, rej: str) -> dict:
    """Fill one slot in pairs.md.

    Rules:
      - pair_id must be in range [0, n_total_slots).
      - If the slot has a pre-filled prompt, `prompt` must match it
        exactly (or the agent can pass the empty string to keep it).
      - If the slot has an empty prompt, `prompt` is required.
      - cho and rej must both be non-empty.

    Once ≥min_pairs_to_train slots are filled, state advances to
    `train_student`. write_pair stays callable in train_student state,
    so the agent can keep polishing before training.
    """
    require_state(round_dir, ("write_pair", "train_student"), "write_pair")

    pairs_path = round_dir / "pairs.md"
    pairs = load_pairs_md(pairs_path)
    ids = [p["id"] for p in pairs]
    if pair_id not in ids:
        raise ValueError(
            f"write_pair: id={pair_id} not in pairs.md. Valid ids: {ids}."
        )
    if not cho.strip() or not rej.strip():
        raise ValueError(
            "write_pair: cho and rej must both be non-empty. Drop the slot "
            "by leaving it empty if you don't want to fill it."
        )

    idx = ids.index(pair_id)
    existing_prompt = pairs[idx]["prompt"]
    if existing_prompt:
        # Slot is pre-seeded; prompt is locked to the seed. Be lenient on
        # minor whitespace/quote differences (agent may re-emit it slightly
        # differently when copying) — if ≥0.85 char-similarity, accept and
        # keep the frozen seeded version. Reject if it looks like a swap
        # (agent passed cho/rej content as prompt by mistake).
        if prompt.strip():
            import difflib
            ratio = difflib.SequenceMatcher(
                a=existing_prompt.strip(), b=prompt.strip()
            ).ratio()
            if ratio < 0.85:
                raise ValueError(
                    f"write_pair: id={pair_id} has a pre-filled prompt that "
                    f"doesn't match yours (similarity={ratio:.2f}, need "
                    f"≥0.85). Pass prompt='' to keep the existing prompt — "
                    f"OR check whether you accidentally swapped prompt with "
                    f"cho or rej.\n"
                    f"  existing prompt: {existing_prompt[:200]!r}\n"
                    f"  your prompt:     {prompt[:200]!r}"
                )
        prompt_to_write = existing_prompt
    else:
        # Empty slot — agent must supply a prompt.
        if not prompt.strip():
            raise ValueError(
                f"write_pair: id={pair_id} has no seeded prompt; supply one "
                f"as the `prompt` argument. (Slots 0..n_seed_prompts have "
                f"seeded prompts you fill cho/rej for; later slots are "
                f"empty and you supply the prompt too.)"
            )
        prompt_to_write = prompt.strip()

    pairs[idx]["prompt"] = prompt_to_write
    pairs[idx]["cho"] = cho.strip()
    pairs[idx]["rej"] = rej.strip()
    write_pairs_md(pairs_path, pairs)

    filled = n_filled(pairs)
    run = json.loads((round_dir.parent / "run.json").read_text())
    cfg = config_by_model(run["model"])
    if filled >= cfg.min_pairs_to_train:
        set_state(round_dir, "train_student",
                  note=f"filled={filled}/{len(pairs)}")
    else:
        set_state(round_dir, "write_pair",
                  note=f"filled={filled}/{len(pairs)}")

    remaining_ids = [p["id"] for p in pairs
                     if not (p["prompt"].strip() and p["cho"].strip()
                             and p["rej"].strip())]
    transcript().info(
        {"event": "write_pair", "round": round_dir.name,
         "pair_id": pair_id, "filled": filled, "total": len(pairs)},
        source=f"{round_dir.name}.write",
    )
    return {
        "filled": filled,
        "total": len(pairs),
        "min_to_train": cfg.min_pairs_to_train,
        "remaining_empty_ids": remaining_ids,
    }


# ---------------------------------------------------------------------------
# Verb 2: train_student — fixed signed_C, no c-scan.
# ---------------------------------------------------------------------------

def train_student(slug_dir: Path, round_dir: Path) -> dict:
    require_state(round_dir, "train_student", "train_student")
    run = json.loads((slug_dir / "run.json").read_text())
    cfg = config_by_model(run["model"])

    pairs_all = load_pairs_md(round_dir / "pairs.md")
    pairs = [p for p in pairs_all
             if p["prompt"].strip() and p["cho"].strip() and p["rej"].strip()]
    if len(pairs) < cfg.min_pairs_to_train:
        raise ValidationError(
            f"train_student: only {len(pairs)} filled pairs, need "
            f"≥{cfg.min_pairs_to_train}. Fill more with write_pair, or "
            f"call mark_exam(keep=False, reason=...) to abort."
        )

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

    signed_C = SIGN * cfg.signed_C
    lora.save(str(round_dir / "adapter.safetensors"),
              extra_meta={"axis": AXIS, "sign": str(SIGN)})
    (round_dir / "calibration.json").write_text(json.dumps({
        "signed_C": signed_C,
        "sign": SIGN,
        "kl_lambda": tcfg.kl_lambda,
        "steps": tcfg.steps,
    }, indent=2))

    dcfg = DialogueCfg(max_new_tokens=cfg.dialogue_max_new_tokens,
                       enable_thinking=cfg.enable_thinking)
    post = dialogue(model, tok, PROBES,
                    round_dir / "interview_post.json",
                    lora=lora, c=signed_C, cfg=dcfg)

    del model, lora
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    set_state(round_dir, "mark_exam", note=f"signed_C={signed_C:+.4f}")
    transcript().info(
        {"event": "train_student", "round": round_dir.name,
         "signed_C": signed_C, "kl_lambda": tcfg.kl_lambda,
         "steps": tcfg.steps, "n_pairs_trained": len(pairs)},
        source=f"{round_dir.name}.train",
    )
    return {
        "signed_C": signed_C,
        "n_probes_post": len(post["probes"]),
        "n_pairs_trained": len(pairs),
    }


# ---------------------------------------------------------------------------
# Verb 3: mark_exam — keep/drop.
# ---------------------------------------------------------------------------

def mark_exam(round_dir: Path, keep: bool, reason: str) -> dict:
    # keep=True requires a trained adapter; keep=False can also fire as an
    # early abort from write_pair/train_student.
    if keep:
        require_state(round_dir, "mark_exam", "mark_exam")
    else:
        require_state(round_dir, ("write_pair", "train_student", "mark_exam"),
                      "mark_exam")
    judgment = {
        "action": "keep" if keep else "drop",
        "reasoning": reason,
        "ts_utc": datetime.now(timezone.utc).isoformat(),
    }
    (round_dir / "judgment.json").write_text(json.dumps(judgment, indent=2))
    set_state(round_dir, "done", note=judgment["action"])
    transcript().info(
        {"event": "mark_exam", "round": round_dir.name,
         "action": judgment["action"], "reason": reason},
        source=f"{round_dir.name}.judge",
    )
    return judgment
