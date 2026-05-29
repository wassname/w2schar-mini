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
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

import torch
from inspect_ai.log import transcript
from loguru import logger

from csm.config import config_by_model, config_for_run
from csm.gen.dialogue import DialogueCfg, dialogue
from csm.gen.pairs import (gen_completions, load_pairs_md, n_filled,
                           sample_prompts, write_pairs_md, write_seeded_pairs)
from csm.gen.probes import PROBES
from csm.state import (RoundState, ValidationError, require_state, set_state,
                       write_state)
from csm.ws.bake import AdapterSpec, baked
from csm.ws.c_scan import c_scan
from csm.ws.history import (kept_history_dirs, load_base_with_history,
                            load_base_with_history_specs)
from csm.ws.train import TrainCfg, train_adapter

AXIS = "less deference to authority"          # fixed for this repo
SIGN = +1                                     # +C = more "less authority"

# CSM_FAKE_STUDENT=1 short-circuits the two GPU-bound stages (prepare_round
# probes + train_student train/c_scan/post-dialogue) to canned fixtures. The
# teacher LLM still runs real (OpenRouter); the gate, react harness, and
# state machine still run real. Use this to iterate on prompts.py text in
# ~30s/round instead of ~20min/round. POST is canned so the gym CANNOT
# tell you whether the prompt improves downstream behaviour — only whether
# the teacher writes well-shaped pairs given the prompt + (canned) feedback.
_FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "fake_student"

def _extract_rej_blocks(path: Path) -> list[str]:
    """Pull the `### Rej` blocks out of a real seeded pairs.md. Deliberately
    tolerant of the `###` markdown subheaders inside the rej content that the
    strict `load_pairs_md` rejects — the gym needs that exact shape to exercise
    the parser the way a real student gen does."""
    blocks: list[str] = []
    cur: list[str] = []
    grab = False
    for line in path.read_text().splitlines():
        s = line.strip()
        if s == "### Rej":
            grab, cur = True, []
            continue
        if s in ("### Cho", "### Prompt") or (
                s.startswith("## ") and not s.startswith("### ")):
            if grab:
                blocks.append("\n".join(cur).strip())
                grab = False
            continue
        if grab:
            cur.append(line)
    return [b for b in blocks if b]


# Fake-mode seeded `rej`: real student gens (Qwen3.6-27B, run #136), drawn from
# a checked-in seed, NOT hand-written. The previous hand-written stand-ins were
# short, plain-prose, and already-deferring, which silently hid all three bugs
# the real run hit: the parser choking on `###` subheaders, the rej↔cho diff
# gate, and the axis inversion (a strong aligned student's natural answer is a
# refusal, not deference). A stand-in only catches bugs if it's sampled from
# reality, not authored to match our assumptions.
_FAKE_REJ_POOL = tuple(_extract_rej_blocks(_FIXTURES / "real_seed.md"))


def _fake_student() -> bool:
    return os.environ.get("CSM_FAKE_STUDENT") == "1"


from contextlib import contextmanager

@contextmanager
def mem_stage(name: str):
    """Log peak CUDA allocated/reserved over the wrapped block.

    Each stage resets the peak counter so values are per-stage, not cumulative.
    Useful for spotting which substage is the OOM-binding one (load vs train
    vs c_scan vs dialogue) — bare nvidia-smi gives a moving point sample."""
    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()
        t0 = torch.cuda.Event(enable_timing=True); t0.record()
    yield
    if torch.cuda.is_available():
        t1 = torch.cuda.Event(enable_timing=True); t1.record()
        torch.cuda.synchronize()
        peak_alloc = torch.cuda.max_memory_allocated() / 2**30
        peak_resv = torch.cuda.max_memory_reserved() / 2**30
        secs = t0.elapsed_time(t1) / 1000.0
        logger.info(f"mem[{name}]: peak alloc={peak_alloc:.1f}GiB "
                    f"reserved={peak_resv:.1f}GiB  ({secs:.1f}s)")


# ---------------------------------------------------------------------------
# Per-slug bootstrap
# ---------------------------------------------------------------------------

def init_run(slug_dir: Path, model: str, teacher: str | None = None,
             profile: str | None = None) -> Path:
    slug_dir.mkdir(parents=True, exist_ok=True)
    run = {
        "model": model,
        "teacher": teacher or config_by_model(model).teacher,
        "axis": AXIS,
        "created_utc": datetime.now(timezone.utc).isoformat(),
    }
    if profile is not None:
        run["profile"] = profile
    (slug_dir / "run.json").write_text(json.dumps(run, indent=2))
    round_dir = slug_dir / "round00"
    round_dir.mkdir(exist_ok=True)
    write_state(round_dir, RoundState(state="submit_pairs"))
    return round_dir


def latest_round_dir(slug_dir: Path) -> Path:
    rounds = sorted(p for p in slug_dir.glob("round*") if p.is_dir())
    if not rounds:
        raise FileNotFoundError(f"no round* under {slug_dir}")
    return rounds[-1]


def new_round_dir(slug_dir: Path) -> Path:
    """Allocate the next roundNN under slug_dir."""
    existing = sorted(p.name for p in slug_dir.glob("round*") if p.is_dir())
    n = 0
    if existing:
        last = existing[-1]
        n = int(last.replace("round", "")) + 1
    rd = slug_dir / f"round{n:02d}"
    rd.mkdir(exist_ok=True)
    write_state(rd, RoundState(state="submit_pairs"))
    return rd


# ---------------------------------------------------------------------------
# Per-round preparation: pre-dialogue (probes @ c=0) + on-policy rej gen.
# One model load handles both. Idempotent.
# ---------------------------------------------------------------------------

def prepare_round(slug_dir: Path, round_dir: Path) -> None:
    """Run the student on:
      1. PROBES at c=0 (writes interview_pre.json)
      2. POOL-sampled training prompts at c=0 (seeds pairs.md with
         prompt + rej; cho remains TODO for the agent to fill).
    Both go in one model session so we only load weights once.
    """
    pre_path = round_dir / "interview_pre.json"
    pairs_path = round_dir / "pairs.md"
    if pre_path.exists() and pairs_path.exists():
        return  # both done

    run = json.loads((slug_dir / "run.json").read_text())
    cfg = config_for_run(run)

    try:
        n = int(round_dir.name.replace("round", ""))
    except ValueError:
        n = 0
    train_prompts = sample_prompts(cfg.n_train_pairs, seed=42 + n)

    if _fake_student():
        if not pre_path.exists():
            shutil.copy(_FIXTURES / "interview_pre.json", pre_path)
        if not pairs_path.exists():
            # Real student rej blocks, deterministic per-prompt via hash, so
            # the teacher faces real-shaped rewriting work (long refusing prose
            # with `###` subheaders) instead of a toy that confirms the
            # harness's assumptions.
            import hashlib
            rej_texts = [_FAKE_REJ_POOL[int(hashlib.md5(p.encode()).hexdigest(), 16)
                                        % len(_FAKE_REJ_POOL)]
                         for p in train_prompts]
            write_seeded_pairs(pairs_path, train_prompts, rej_texts)
        return

    history = kept_history_dirs(slug_dir, before_round=n)
    with mem_stage("load"):
        model, tok, hist_specs = load_base_with_history_specs(cfg.model, history, quant=cfg.quant)
    try:
        # Bake history once for the whole prepare phase (pre-dialogue + rej gen
        # both run at base + history, no current adapter, c=0 for current).
        with baked(model, hist_specs):
            if not pre_path.exists():
                dcfg = DialogueCfg(max_new_tokens=cfg.dialogue_max_new_tokens,
                                   enable_thinking=cfg.enable_thinking)
                with mem_stage("dialogue_pre"):
                    dialogue(model, tok, PROBES, pre_path,
                             hist_specs=None, current_spec=None, c=0.0, cfg=dcfg)
            if not pairs_path.exists():
                with mem_stage("gen_rej"):
                    rej_texts = gen_completions(
                        model, tok, train_prompts,
                        max_new_tokens=cfg.gen_max_new_tokens,
                        batch_size=cfg.eval_batch_size,
                        enable_thinking=cfg.enable_thinking,
                        seed=42 + n,
                    )
                write_seeded_pairs(pairs_path, train_prompts, rej_texts)
    finally:
        del model
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()


# Backward-compat alias (smoke / tests / agent.py haven't all migrated).
def run_pre_dialogue(slug_dir: Path, round_dir: Path) -> dict:
    prepare_round(slug_dir, round_dir)
    return json.loads((round_dir / "interview_pre.json").read_text())


# ---------------------------------------------------------------------------
# Verb 1: submit_pairs — teacher writes the whole pairs.md form at once.
# ---------------------------------------------------------------------------

# Loose guardrail — pct_changed is `1 - difflib.SequenceMatcher.ratio()` on
# raw strings (char-level). 0.02 rejects near-identity (cho ≈ rej trains
# nothing). 0.90 only rejects two answers with almost no shared text. The
# ceiling is high because flipping a *substantive* stance ("refuse" -> "obey")
# legitimately rewrites most of a long answer even when structure matches —
# a 40% ceiling was unmeetable for full-answer authority pairs and forced
# every round to drop (see the fake-student gym). This gate is now only a
# style/length sanity check; it is SIGN-BLIND (a pole-inverted pair passes),
# so correct poling rests on prompts.py and, in real runs, the PRE/POST judge.
_PCT_MIN, _PCT_MAX = 0.02, 0.90


def _measure_diff(rej: str, cho: str) -> dict:
    from difflib import SequenceMatcher
    sm = SequenceMatcher(a=rej, b=cho, autojunk=False)
    return {
        "n_rej": len(rej), "n_cho": len(cho),
        "pct_changed": 1.0 - sm.ratio(),
    }


def _validate_pair_diffs(pairs: list[dict]) -> list[dict]:
    """Per-pair gate. Skip incomplete pairs (TODO markers / empty slots);
    those are caught by the filled-count check downstream."""
    issues = []
    for p in pairs:
        if any(p[k].strip().startswith("TODO(") or not p[k].strip()
               for k in ("prompt", "cho", "rej")):
            continue
        d = _measure_diff(p["rej"], p["cho"])
        if not _PCT_MIN <= d["pct_changed"] <= _PCT_MAX:
            kind = "too_similar" if d["pct_changed"] < _PCT_MIN else "too_different"
            issues.append({"id": p["id"], "kind": kind, **d})
    return issues


def _format_diff_issues(issues: list[dict]) -> str:
    """One block per failed pair with measured numbers + the actual asymmetric
    tokens. Goal: agent can see EXACTLY what leaked, not just 'failed'."""
    lines = []
    for iss in issues:
        pct = iss["pct_changed"]
        if iss["kind"] == "too_similar":
            lines.append(
                f"  pair {iss['id']}: TOO SIMILAR — {pct:.0%} changed "
                f"(need >{_PCT_MIN:.0%}). cho is nearly identical to rej; "
                f"mean(cho − rej) ≈ 0 so this pair trains nothing."
            )
        else:
            lines.append(
                f"  pair {iss['id']}: TOO DIFFERENT — {pct:.0%} changed "
                f"(need ≤{_PCT_MAX:.0%}), len {iss['n_rej']}→{iss['n_cho']} chars. "
                f"cho diverged from rej's shape; length/style will dominate the axis."
            )
    return "\n".join(lines)


def submit_pairs(round_dir: Path, pairs_md: str) -> dict:
    """Replace pairs.md with `pairs_md`. Validate it parses, count slots
    where every TODO has been replaced; advance to train_student once
    ≥min_pairs_to_train slots are filled.

    `submit_pairs` is callable again from `train_student` state, so the
    agent can resubmit after fixing TODOs.
    """
    require_state(round_dir, ("submit_pairs", "train_student"), "submit_pairs")

    pairs_path = round_dir / "pairs.md"
    pairs_path.write_text(pairs_md)
    try:
        lesson, pairs = load_pairs_md(pairs_path)
    except ValueError as e:
        raise ValueError(
            f"submit_pairs: pairs.md doesn't parse — {e}. Schema: a top "
            f"`## Lesson` block, then `## <int>` per pair with exactly "
            f"`### Prompt`, `### Rej`, `### Cho` subheaders."
        ) from e

    filled = n_filled(pairs)
    run = json.loads((round_dir.parent / "run.json").read_text())
    cfg = config_for_run(run)

    # Prompt-lock: the `### Prompt` lines were seeded by prepare_round from
    # POOL[seed=42+n]. The agent is only meant to fill Rej/Cho/Lesson — never
    # edit Prompt. Drift here narrows the prompt distribution round-by-round
    # (gym v2/v3 r02: agent rewrote all 4 prompts into one "scope-claim"
    # narrative).
    try:
        round_n = int(round_dir.name.replace("round", ""))
    except ValueError:
        round_n = 0
    seeded = sample_prompts(cfg.n_train_pairs, seed=42 + round_n)
    edited = [(p["id"], p["prompt"].strip(), seeded[p["id"] - 1].strip())
              for p in pairs
              if 1 <= p["id"] <= len(seeded)
              and p["prompt"].strip() != seeded[p["id"] - 1].strip()]
    if edited:
        details = "\n".join(
            f"  pair {pid}: SEEDED={seed!r}\n           SUBMITTED={got!r}"
            for pid, got, seed in edited
        )
        raise ValidationError(
            f"submit_pairs: {len(edited)} pair(s) have edited `### Prompt` "
            f"text. Prompts are fixed per round — resubmit with the originals "
            f"verbatim and only fill the Cho and Lesson slots.\n\n"
            f"{details}"
        )

    # No rej-lock: the seeded rej is the student's natural answer used as a
    # VOICE ANCHOR, not a fixed pole. When that answer already resists
    # authority (a strong aligned student), it IS the cho pole — the teacher
    # then writes the deferring rej twin to match it (docs/how_to_rewrite_pairs.md
    # rule 3: keep the anchor, edit the other side). Locking rej to the seed
    # forced the teacher to negate a refusal into a deferring cho, inverting the
    # axis. The diff gate below is what keeps the two sides twinned.

    # Per-pair rej↔cho diff gate. The adapter direction is mean(cho − rej);
    # any token that differs between sides contributes to the axis. Style
    # differences (length, named institutions, contingency branches not
    # mirrored across sides) become style axes — exactly the failure seen
    # on petrov_false_alarm POST. Gate: pct_changed band on raw tokens.
    issues = _validate_pair_diffs(pairs)
    if issues:
        raise ValueError(
            f"submit_pairs: {len(issues)} pair(s) failed the rej↔cho diff "
            f"gate. The two poles must be a copy-flip twin: same structure "
            f"and length, only the stance words changed. If a pair can only "
            f"be written as two different essays — because the stance pervades "
            f"the whole answer — it has no twinnable axis: drop the round with "
            f"mark_exam(keep=False, reason=...) rather than resubmit.\n\n"
            f"{_format_diff_issues(issues)}"
        )

    if filled >= cfg.min_pairs_to_train:
        set_state(round_dir, "train_student",
                  note=f"filled={filled}/{len(pairs)}")
    else:
        set_state(round_dir, "submit_pairs",
                  note=f"filled={filled}/{len(pairs)}")

    remaining = [p["id"] for p in pairs
                 if p["cho"].strip().startswith("TODO(")
                 or not p["cho"].strip()]
    if not lesson.strip() or lesson.strip().startswith("TODO("):
        remaining = [-1] + remaining  # signal that Lesson is still TODO
    transcript().info(
        {"event": "submit_pairs", "round": round_dir.name,
         "filled": filled, "total": len(pairs)},
        source=f"{round_dir.name}.submit",
    )
    return {
        "filled": filled,
        "total": len(pairs),
        "min_to_train": cfg.min_pairs_to_train,
        "slots_with_todo": remaining,
    }


# ---------------------------------------------------------------------------
# Verb 2: train_student — fixed signed_C, no c-scan.
# ---------------------------------------------------------------------------

def _fake_train_student(slug_dir: Path, round_dir: Path, cfg) -> dict:
    """Gym path. Validate the filled pairs, write stub adapter + canned POST
    from fixture, advance state. No GPU."""
    lesson, pairs_all = load_pairs_md(round_dir / "pairs.md")
    pairs = [p for p in pairs_all
             if p["prompt"].strip() and p["cho"].strip() and p["rej"].strip()
             and not any(p[k].strip().startswith("TODO(")
                         for k in ("prompt", "cho", "rej"))]
    if len(pairs) < cfg.min_pairs_to_train:
        raise ValidationError(
            f"train_student: only {len(pairs)} filled pairs, "
            f"need ≥{cfg.min_pairs_to_train}."
        )
    (round_dir / "adapter.safetensors").write_bytes(b"")
    (round_dir / "calibration.json").write_text(json.dumps({
        "signed_C": float(cfg.signed_C), "sign": SIGN,
        "cscan_trace": [], "fake": True,
    }, indent=2))
    shutil.copy(_FIXTURES / "interview_post.json",
                round_dir / "interview_post.json")
    set_state(round_dir, "mark_exam", note=f"FAKE signed_C={cfg.signed_C:+.4f}")
    post = json.loads((round_dir / "interview_post.json").read_text())
    return {
        "signed_C": float(cfg.signed_C),
        "n_probes_post": len(post.get("probes", [])),
        "n_pairs_trained": len(pairs),
    }


def train_student(slug_dir: Path, round_dir: Path) -> dict:
    require_state(round_dir, "train_student", "train_student")
    run = json.loads((slug_dir / "run.json").read_text())
    cfg = config_for_run(run)

    if _fake_student():
        return _fake_train_student(slug_dir, round_dir, cfg)

    lesson, pairs_all = load_pairs_md(round_dir / "pairs.md")
    pairs = [p for p in pairs_all
             if p["prompt"].strip() and p["cho"].strip() and p["rej"].strip()
             and not any(p[k].strip().startswith("TODO(")
                         for k in ("prompt", "cho", "rej"))]
    if len(pairs) < cfg.min_pairs_to_train:
        raise ValidationError(
            f"train_student: only {len(pairs)} filled pairs (TODO not yet "
            f"replaced in the rest), need ≥{cfg.min_pairs_to_train}. "
            f"Resubmit pairs.md with submit_pairs, or call "
            f"mark_exam(keep=False, reason=...) to abort."
        )

    history = kept_history_dirs(slug_dir, before_round=int(round_dir.name.replace("round", "")))
    with mem_stage("load"):
        model, tok, hb = load_base_with_history(cfg.model, history, quant=cfg.quant)

    steps = max(cfg.min_steps,
                int(len(pairs) / cfg.train_batch_size * cfg.n_epochs))
    tcfg = TrainCfg(
        r=cfg.lora_r, alpha=cfg.lora_alpha, targets=cfg.targets,
        layer_range=cfg.layer_range,
        steps=steps, batch_size=cfg.train_batch_size, lr=cfg.lr,
        weight_decay=cfg.weight_decay, warmup_ratio=cfg.warmup_ratio,
        grad_clip=cfg.grad_clip,
        max_len=cfg.max_len, kl_lambda=cfg.kl_lambda,
    )
    from csm.ws.adapter import ModulatedLoRA, ModulatedPiSSA
    adapter_cls = ModulatedPiSSA if cfg.adapter == "pissa" else ModulatedLoRA
    with mem_stage("train"):
        lora = train_adapter(model, tok, pairs, tcfg,
                             history_bake=hb, enable_thinking=cfg.enable_thinking,
                             adapter_cls=adapter_cls)

    # Calibrate. cfg.signed_C is the initial probe; c_scan walks down
    # ×0.5 until pmass_format ≥ 0.98 × baseline, no backoff. Coherent
    # adapters bake at init; fragile ones get tamer baked coefficients.
    # pmass_format = tinymfv format-follow mass at the JSON answer slot
    # (sensitive to autoregressive collapse; the prior top-K surrogate
    # missed it because it was teacher-forced on base's clean prefix).
    with mem_stage("c_scan"):
        signed_C, trace = c_scan(
            model, tok, lora,
            init_c=cfg.signed_C, sign=SIGN,
            batch_size=cfg.eval_batch_size,
            enable_thinking=cfg.enable_thinking,
            json_max_new_tokens=cfg.c_scan_json_max_new_tokens,
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

    # Post-dialogue: HistoryBake's gated hook still attached (active at
    # gate=True after train_adapter restored inference default). Bake only
    # the current adapter into W on top → reduced per-forward overhead for
    # the new adapter; history still routes via its (now-already-attached)
    # hook. Cheaper than detaching HistoryBake just for 3 probes.
    dcfg = DialogueCfg(max_new_tokens=cfg.dialogue_max_new_tokens,
                       enable_thinking=cfg.enable_thinking)
    if isinstance(lora, ModulatedPiSSA):
        from csm.ws.bake import pissa_to_lora_spec
        cur_spec = pissa_to_lora_spec(lora, default_c=signed_C)
        lora.restore_base_W()
    else:
        cur_spec = AdapterSpec.from_lora(lora, default_c=signed_C)
    with mem_stage("dialogue_post"):
        post = dialogue(model, tok, PROBES,
                        round_dir / "interview_post.json",
                        hist_specs=None, current_spec=cur_spec, c=signed_C, cfg=dcfg)

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

def mark_exam(round_dir: Path, keep: bool, reason: str,
              next_focus: str = "") -> dict:
    # keep=True requires a trained adapter; keep=False can also fire as an
    # early abort from submit_pairs/train_student.
    if keep:
        require_state(round_dir, "mark_exam", "mark_exam")
    else:
        require_state(round_dir, ("submit_pairs", "train_student", "mark_exam"),
                      "mark_exam")
    judgment = {
        "action": "keep" if keep else "drop",
        "reasoning": reason,
        "next_focus": next_focus,
        "ts_utc": datetime.now(timezone.utc).isoformat(),
    }
    (round_dir / "judgment.json").write_text(json.dumps(judgment, indent=2))
    set_state(round_dir, "done", note=judgment["action"])
    transcript().info(
        {"event": "mark_exam", "round": round_dir.name,
         "action": judgment["action"], "reason": reason},
        source=f"{round_dir.name}.judge",
    )
    write_report_md(round_dir.parent)
    return judgment


def _safe_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return None


def write_report_md(slug_dir: Path) -> None:
    """Refresh <slug>/report.md from per-round artifacts. Pure-disk, no model
    forwards, safe to call after every round. Eval column is `—` when
    eval.json is absent (csm eval is post-hoc and may never run for this
    slug), so the report stays useful during in-flight runs."""
    rounds = sorted(p for p in slug_dir.glob("round*") if p.is_dir())
    n_keep = n_drop = 0
    rows: list[list[str]] = []
    for rd in rounds:
        state = (_safe_json(rd / "state.json") or {}).get("state", "—")
        j = _safe_json(rd / "judgment.json") or {}
        cal = _safe_json(rd / "calibration.json") or {}
        ev = _safe_json(rd / "eval.json") or {}

        action = j.get("action", "")
        n_keep += action == "keep"
        n_drop += action == "drop"

        ts = (j.get("ts_utc") or "")[:19].replace("T", " ")
        reason = (j.get("reasoning") or "").split("\n")[0][:120].replace("|", "\\|")
        focus = (j.get("next_focus") or "").split("\n")[0][:120].replace("|", "\\|")

        c_val = cal.get("signed_C")
        c_str = f"{c_val:+.4f}" if isinstance(c_val, (int, float)) else "—"

        mp = ev.get("mean_p")
        ev_str = f"{mp:.3f}" if isinstance(mp, (int, float)) else "—"

        rows.append([rd.name.replace("round", "r"), ts, state, action or "—",
                     c_str, ev_str, reason, focus])

    headers = ["round", "judged_at", "state", "action", "signed_C",
               "eval_mean_p", "reasoning (head)", "next_focus (head)"]
    lines = [
        f"# {slug_dir.name}",
        "",
        f"keeps: **{n_keep}**  ·  drops: **{n_drop}**  ·  rounds: **{len(rounds)}**",
        "",
        "| " + " | ".join(headers) + " |",
        "|" + "|".join("---" for _ in headers) + "|",
    ]
    for r in rows:
        lines.append("| " + " | ".join(r) + " |")
    (slug_dir / "report.md").write_text("\n".join(lines) + "\n")
    # Per-slug index.html with the plotly scatter + timeline. Renders with
    # placeholders when eval.json is absent so the link from the outer
    # aggregator always lands on a real HTML page.
    try:
        from csm.plot import Cfg as PlotCfg
        from csm.plot import main as plot_main
        plot_main(PlotCfg(slug=slug_dir, out=None))
    except Exception as e:
        logger.warning(f"plot generation failed for {slug_dir.name}: {e}")
    write_iter_index(slug_dir.parent)


def write_iter_index(iter_dir: Path) -> None:
    """Top-level out/iter/index.html: one row per slug, newest first. Pure
    disk-read; no model forward, no eval. `eval_mean_p` falls back to '—'
    if eval.json hasn't been built."""
    slugs = sorted(
        (p for p in iter_dir.glob("*") if p.is_dir() and not p.name.startswith(".")),
        reverse=True,
    )
    rows: list[str] = []
    for slug in slugs:
        run_meta = _safe_json(slug / "run.json") or {}
        rounds = sorted(p for p in slug.glob("round*") if p.is_dir())
        n_keep = n_drop = 0
        last_kept_c = "—"
        last_eval_mean_p = "—"
        for rd in rounds:
            j = _safe_json(rd / "judgment.json") or {}
            act = j.get("action")
            if act == "keep":
                n_keep += 1
                sc = (_safe_json(rd / "calibration.json") or {}).get("signed_C")
                if isinstance(sc, (int, float)):
                    last_kept_c = f"{sc:+.4f}"
            elif act == "drop":
                n_drop += 1
            mp = (_safe_json(rd / "eval.json") or {}).get("mean_p")
            if isinstance(mp, (int, float)):
                last_eval_mean_p = f"{mp:.3f}"

        last_state = "—"
        if rounds:
            last_state = (_safe_json(rounds[-1] / "state.json") or {}).get("state", "—")
        status = "done" if (rounds and last_state == "done") else "active"

        ts = (run_meta.get("created_utc") or "")[:19].replace("T", " ") or slug.name[:15]
        model = run_meta.get("model", "—")
        # Prefer the plotly index.html (built by `csm eval`) when it exists;
        # fall back to report.md for runs that haven't been evaluated yet.
        landing = "index.html" if (slug / "index.html").exists() else "report.md"
        rows.append(
            f'    <tr class="{status}">'
            f'<td><a href="{slug.name}/{landing}">{slug.name}</a></td>'
            f'<td>{model}</td><td>{ts}</td>'
            f'<td>{n_keep}</td><td>{n_drop}</td><td>{len(rounds)}</td>'
            f'<td>{last_kept_c}</td>'
            f'<td>{last_eval_mean_p}</td><td>{status}</td>'
            "</tr>"
        )

    html = (
        '<!doctype html><meta charset="utf-8"><title>out/iter</title>'
        "<style>"
        "body{font-family:ui-monospace,monospace;margin:24px;}"
        "table{border-collapse:collapse;}"
        "th,td{border:1px solid #ddd;padding:4px 8px;text-align:left;}"
        "th{background:#f3f3f3;position:sticky;top:0;}"
        "tr.active{background:#fff8e1;}"
        "tr:hover{background:#eef;}"
        "a{color:#06c;text-decoration:none;}a:hover{text-decoration:underline;}"
        "</style>"
        f"<h1>out/iter — {len(slugs)} runs</h1>"
        "<table><thead><tr>"
        "<th>slug</th><th>model</th><th>started_utc</th>"
        "<th>keeps</th><th>drops</th><th>rounds</th>"
        "<th>last_kept_c</th>"
        "<th>eval_mean_p</th><th>status</th>"
        "</tr></thead><tbody>\n"
        + "\n".join(rows)
        + "\n</tbody></table>"
    )
    (iter_dir / "index.html").write_text(html)
