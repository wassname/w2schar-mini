"""Per-round orchestration: pre-dialogue → propose → curate → train → judge.

Each agent-callable verb (propose_personas / edit_pairs / train / judge)
delegates to one of these functions. Pipeline writes all artifacts and
mutates the round's state.json transparently.

Artifacts per round (`<slug>/round<NN>/`):
  state.json          — current state (propose|curate|judge|done)
  spec.json           — pos/neg personas + axis label
  pairs.md           — current pair set (plain-text section-marker
                        format; agent-editable via str_replace)
  pairs.bk.md        — frozen snapshot just after auto-drop
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
from inspect_ai.log import transcript
from loguru import logger

from csm.config import RunConfig, config_by_model
from csm.gen.dialogue import dialogue, DialogueCfg
from csm.gen.pairs import (find_refusals, gen_pairs, write_pairs_md,
                            load_pairs_md)
from csm.gen.probes import PROBES
from csm.state import (RoundState, ValidationError, read_state,
                       require_state, set_state, write_state)
from csm.ws.adapter import ModulatedLoRA
from csm.ws.c_scan import c_scan
from csm.ws.history import kept_history_dirs, load_base_with_history
from csm.ws.train import TrainCfg, train_adapter

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
        write_state(round_dir, RoundState(state="propose_personas"))
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
    write_state(rd, RoundState(state="propose_personas"))
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

def propose_personas(slug_dir: Path, round_dir: Path,
                     pos_persona: str, neg_persona: str) -> dict:
    require_state(round_dir, "propose_personas", "propose_personas")
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
    # Gen runs against base + history (default gate True) — same as
    # wsl. This is "iterative steering on top of steering": each round
    # samples from the deployed-so-far model. The training c=0 KL ref
    # stays pristine base via the train-time gate lambda lora._c != 0.0.
    alive, dropped = gen_pairs(
        model, tok, pos_persona, neg_persona,
        n_pairs=cfg.n_pairs, batch_size=cfg.gen_batch_size,
        max_new_tokens=cfg.max_new_tokens, enable_thinking=cfg.enable_thinking,
    )
    del model
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    write_pairs_md(round_dir / "pairs.md", alive)
    write_pairs_md(round_dir / "pairs.bk.md", alive)
    (round_dir / "dropped.json").write_text(json.dumps(dropped, indent=2))

    min_alive = max(2, cfg.n_pairs // 4)     # scales with n_pairs so smoke (n=4) passes
    if len(alive) < min_alive:
        # ValidationError, not RuntimeError, so the agent's tool wrapper
        # can surface it as a tool error and let the agent retry with a
        # different persona pair instead of crashing the eval.
        raise ValidationError(
            f"propose_personas: only {len(alive)} pairs alive after auto-drop "
            f"({len(dropped)} double-refusals); need >= {min_alive}. "
            f"Rewrite the persona pair to elicit a sharper contrast."
        )

    set_state(round_dir, "edit_answers",
              note=f"alive={len(alive)} dropped={len(dropped)}")
    transcript().info(
        {"event": "propose_personas", "round": round_dir.name,
         "alive": len(alive), "n_dropped": len(dropped),
         "dropped_ids": [d["id"] for d in dropped],
         "pos_persona": pos_persona, "neg_persona": neg_persona},
        source=f"{round_dir.name}.propose",
    )
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
# Verb 2: edit_answers — pi-style str_replace edits on pairs.md
# ---------------------------------------------------------------------------

MAX_PAIR_DIFF = 0.50  # per-pair (cho+rej) char-diff vs bk; caps rewrite scope


def _apply_single_str_replace(text: str, old_str: str, new_str: str) -> str:
    """One str_replace, exact-match. old_str must occur in `text` exactly
    once or we reject so the agent can disambiguate.
    """
    if not isinstance(old_str, str) or not isinstance(new_str, str):
        raise ValueError("edit_answers: old_str and new_str must be strings")
    if old_str == "":
        raise ValueError("edit_answers: old_str is empty")
    n_occ = text.count(old_str)
    head = old_str[:80].replace("\n", "⏎")
    if n_occ == 0:
        raise ValueError(
            f"edit_answers: old_str not found in pairs.md. The snippet "
            f"must appear verbatim — check whitespace, quotes, and escape "
            f"chars against the file inlined in propose_personas's response. "
            f"First 80 chars of your old_str: {head!r}"
        )
    if n_occ > 1:
        raise ValueError(
            f"edit_answers: old_str matches {n_occ} locations in pairs.md. "
            f"Extend the snippet with surrounding context (more of the "
            f"cho/rej text, the `\"id\": N,` line above, or the closing "
            f"`}}` and trailing comma below) until it picks out one pair "
            f"uniquely. First 80 chars: {head!r}"
        )
    return text.replace(old_str, new_str, 1)


def edit_answers(round_dir: Path, old_str: str, new_str: str) -> dict:
    """Apply a single surgical str_replace to pairs.md. Rules:
      1. old_str must match the current pairs.md text exactly once.
      2. After applying, the file must still parse via load_pairs_md.
      3. Every remaining pair's `prompt` matches a `prompt` in
         pairs.bk.md (no invented pairs, no prompt edits).
      4. Per-pair char-diff of cho+rej ≤ MAX_PAIR_DIFF, computed vs
         pairs.bk.md — so cumulative drift across many edits is bounded.
      5. Refusal sweep: warnings, not rejections.

    Pair IDs stay stable (no renumbering on drops) so the agent can
    reference them across calls. To DROP a pair, prefer the
    `drop_pair(id)` tool — it skips content matching entirely.
    """
    require_state(round_dir, ("edit_answers", "train_student"), "edit_answers")
    import difflib

    pairs_path = round_dir / "pairs.md"
    bk_path = round_dir / "pairs.bk.md"
    original_text = pairs_path.read_text()
    new_text = _apply_single_str_replace(original_text, old_str, new_str)

    try:
        pairs_path.write_text(new_text)
        pairs = load_pairs_md(pairs_path)
    except Exception as e:
        # Re-write original so we never leave the file in a broken state
        # (load_pairs_md shouldn't normally fail, but if it does the
        # write above already happened; we revert before raising).
        pairs_path.write_text(original_text)
        raise ValueError(
            f"edit_answers: edit produced unparseable pairs.md — {e}. "
            f"Each pair must keep its `##### pair N` / `##### prompt` / "
            f"`##### cho` / `##### rej` markers intact. Don't edit the "
            f"markers themselves; edit the content between them."
        ) from e

    for i, row in enumerate(pairs):
        for k in ("id", "prompt", "cho", "rej"):
            if k not in row:
                raise ValueError(f"edit_answers: pair {i} missing key {k!r}")
    if not pairs:
        raise ValueError("edit_answers: 0 alive pairs after edits")

    bk = load_pairs_md(bk_path)
    bk_by_prompt = {p["prompt"]: p for p in bk}

    invented: list[int] = []
    rewrite_violations: list[str] = []
    n_dropped = len(bk) - len(pairs)
    n_changed = 0
    for p in pairs:
        bk_p = bk_by_prompt.get(p["prompt"])
        if bk_p is None:
            invented.append(p.get("id", "?"))
            continue
        old_pair_text = (bk_p["cho"] or "") + (bk_p["rej"] or "")
        new_pair_text = (p["cho"] or "") + (p["rej"] or "")
        if old_pair_text == new_pair_text:
            continue
        n_changed += 1
        pair_diff = 1.0 - difflib.SequenceMatcher(a=old_pair_text, b=new_pair_text).ratio()
        if pair_diff > MAX_PAIR_DIFF:
            rewrite_violations.append(
                f"  id={p.get('id', '?')} per-pair diff={pair_diff:.1%} "
                f"(>{MAX_PAIR_DIFF:.0%}) — keep edits minimal, don't rewrite "
                f"from scratch"
            )

    if invented:
        raise ValueError(
            f"edit_answers: pairs with ids {invented} have prompts not in "
            f"pairs.bk.md — you can't invent pairs or edit prompts, only "
            f"drop or fix existing cho/rej."
        )
    if rewrite_violations:
        raise ValueError(
            "edit_answers: per-pair rewrite too large (>{:.0%}). The point "
            "is on-policy curation, not voice substitution. Make minimal "
            "fixes to broken cho/rej (DELETE bad parts, don't replace them); "
            "if a pair's completions are unsalvageable, drop the whole pair "
            "instead. If most pairs are unsalvageable, call "
            "mark_exam(keep=False, reason=...) — allowed directly from "
            "this state — and the next round retries with new personas.\n".format(MAX_PAIR_DIFF)
            + "\n".join(rewrite_violations)
        )
    if n_changed == 0 and n_dropped == 0:
        raise ValueError(
            "edit_answers: this call produced 0 cho/rej changes and 0 drops "
            "vs pairs.bk.md. Make a substantive edit (DELETE a hedge / "
            "preamble) or use drop_pair(id) to drop a broken pair."
        )

    refusal_warnings: list[str] = []
    for p in pairs:
        for side in ("cho", "rej"):
            hits = find_refusals(p[side])
            if hits:
                refusal_warnings.append(
                    f"  id={p.get('id', '?')} side={side} hits={hits}"
                )

    # No renumber: keep stable IDs across edits so drop_pair(id) refers
    # to the same pair across the round.
    write_pairs_md(pairs_path, pairs)
    set_state(round_dir, "train_student",
              note=f"alive={len(pairs)} dropped={n_dropped} changed={n_changed}")
    transcript().info(
        {"event": "edit_answers", "round": round_dir.name,
         "alive": len(pairs), "n_dropped": n_dropped, "n_changed": n_changed,
         "n_original": len(bk),
         "n_refusal_warnings": len(refusal_warnings)},
        source=f"{round_dir.name}.edit",
    )
    return {"n_alive": len(pairs), "n_original": len(bk),
            "n_dropped": n_dropped, "n_changed": n_changed,
            "refusal_warnings": refusal_warnings}


# ---------------------------------------------------------------------------
# Verb 2b: drop_pair — drop by id, no content matching (no fabrication path)
# ---------------------------------------------------------------------------

def drop_pair(round_dir: Path, pair_id: int) -> dict:
    """Drop one pair by ID from pairs.md. No content matching — the agent
    just says which id to drop, the harness reads it from the file. IDs
    are stable across edits (we don't renumber)."""
    require_state(round_dir, ("edit_answers", "train_student"), "drop_pair")
    pairs_path = round_dir / "pairs.md"
    bk_path = round_dir / "pairs.bk.md"
    pairs = load_pairs_md(pairs_path)
    alive_ids = [p["id"] for p in pairs]
    if pair_id not in alive_ids:
        raise ValueError(
            f"drop_pair: id={pair_id} is not in the current pairs.md. "
            f"Alive ids are {alive_ids}. (Gen-time both-side refusals "
            f"were already removed; their ids never appeared in pairs.md.)"
        )
    remaining = [p for p in pairs if p["id"] != pair_id]
    if not remaining:
        raise ValueError(
            "drop_pair: dropping this pair would leave 0 pairs. If all "
            "are unsalvageable, call mark_exam(keep=False, reason=...)."
        )
    write_pairs_md(pairs_path, remaining)
    bk = load_pairs_md(bk_path)
    n_dropped = len(bk) - len(remaining)
    n_changed = _count_changed_vs_bk(remaining, bk)
    set_state(round_dir, "train_student",
              note=f"alive={len(remaining)} dropped={n_dropped} changed={n_changed}")
    transcript().info(
        {"event": "drop_pair", "round": round_dir.name,
         "dropped_id": pair_id, "alive": len(remaining),
         "n_dropped": n_dropped, "n_changed": n_changed},
        source=f"{round_dir.name}.drop",
    )
    return {"n_alive": len(remaining), "n_original": len(bk),
            "n_dropped": n_dropped, "n_changed": n_changed,
            "dropped_id": pair_id, "alive_ids": [p["id"] for p in remaining]}


def _count_changed_vs_bk(pairs: list[dict], bk: list[dict]) -> int:
    bk_by_prompt = {p["prompt"]: p for p in bk}
    n = 0
    for p in pairs:
        bk_p = bk_by_prompt.get(p["prompt"])
        if bk_p is None:
            continue
        if (bk_p["cho"] or "") + (bk_p["rej"] or "") != (p["cho"] or "") + (p["rej"] or ""):
            n += 1
    return n


# ---------------------------------------------------------------------------
# Verb 3: train (also runs c_scan + post-dialogue).
# ---------------------------------------------------------------------------

def train_student(slug_dir: Path, round_dir: Path) -> dict:
    require_state(round_dir, "train_student", "train_student")

    # Dual-gate: must have ≥1 drop AND ≥1 cho/rej change vs pairs.bk.md.
    # Drops without edits = lazy curation; edits without drops = doesn't
    # commit to removing junk. Both forces engagement at both levels.
    bk = load_pairs_md(round_dir / "pairs.bk.md")
    cur = load_pairs_md(round_dir / "pairs.md")
    n_dropped = len(bk) - len(cur)
    n_changed = _count_changed_vs_bk(cur, bk)
    if n_dropped < 1 or n_changed < 1:
        missing = []
        if n_dropped < 1:
            missing.append("≥1 drop (use `drop_pair(id)`)")
        if n_changed < 1:
            missing.append("≥1 cho/rej edit (use `edit_answers(old_str, new_str)`)")
        raise ValidationError(
            f"train_student: round not ready to train. Current state vs "
            f"pairs.bk.md: dropped={n_dropped}, cho/rej-changed={n_changed}. "
            f"Need: {' AND '.join(missing)}. (Alternatively call "
            f"mark_exam(keep=False, reason=...) to abort.)"
        )
    run = json.loads((slug_dir / "run.json").read_text())
    cfg = config_by_model(run["model"])

    pairs = load_pairs_md(round_dir / "pairs.md")
    if not pairs:
        raise RuntimeError("train: pairs.md is empty")

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

    set_state(round_dir, "mark_exam", note=f"signed_C={signed_C:+.4f}")
    transcript().info(
        {"event": "train_student", "round": round_dir.name,
         "signed_C": signed_C, "kl_lambda": tcfg.kl_lambda,
         "steps": tcfg.steps, "cscan_trace": [list(r) for r in trace],
         "n_pairs_trained": len(pairs)},
        source=f"{round_dir.name}.train",
    )
    return {
        "signed_C": signed_C,
        "n_probes_post": len(post["probes"]),
    }


# ---------------------------------------------------------------------------
# Verb 4: judge
# ---------------------------------------------------------------------------

def mark_exam(round_dir: Path, keep: bool, reason: str) -> dict:
    # keep=True requires a trained adapter; keep=False is also valid as
    # an early abort from edit_answers (escape valve when pairs are
    # unsalvageable).
    if keep:
        require_state(round_dir, "mark_exam", "mark_exam")
    else:
        require_state(round_dir, ("edit_answers", "train_student", "mark_exam"),
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
