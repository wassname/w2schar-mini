"""Post-hoc tinymfv eval per round checkpoint.

For each round under <slug>, evaluates:

    eval.json       — base + history-of-kept-rounds-<N at c=0
                      ("state at start of round N")
    eval_post.json  — same + this round's adapter at signed_C
                      ("state after round N", iff this round trained an adapter)

Output shape matches weight-steering-lite/w2schar/01_eval.py:
    {model, adapter, c, name, n_rows, top1_acc, mean_js,
     mean_pmass_format, mean_p: {care, fairness, ...}}
so plots and cross-repo comparisons read either source the same way.

`tinymfv.evaluate` does forced-choice 7-way scoring on Clifford-2015
vignettes — fully compatible with steered models since the model is
called normally inside a `baked()` context (history + this round's
adapter folded into model weights for the duration of the eval).
"""
from __future__ import annotations

import gc
import json
from pathlib import Path

import numpy as np
import torch
from loguru import logger
from tinymfv import evaluate
from tqdm.auto import tqdm

from csm.config import config_by_model, config_for_run
from csm.pipeline import mem_stage
from csm.ws.bake import AdapterSpec, adapter_spec_from_checkpoint, baked
from csm.ws.history import kept_history_dirs, load_base_with_history_specs


FOUNDATIONS = ["care", "fairness", "loyalty", "authority",
               "sanctity", "liberty", "social"]


def _summary_from_report(report: dict) -> dict:
    """Condense tinymfv.evaluate output to the wsl-shaped summary dict."""
    P = np.stack([r["p"] for r in report["per_row"]])
    return {
        "n_rows": len(report["per_row"]),
        "top1_acc": report.get("top1_acc"),
        "mean_js": report.get("mean_js"),
        "mean_pmass_format": report.get("mean_pmass_format"),
        "mean_p": {f: float(P[:, i].mean()) for i, f in enumerate(FOUNDATIONS)},
    }


def eval_round(model, tok, *, name: str, batch_size: int,
               max_think_tokens: int, n_vignettes: int | None,
               conditions: tuple[str, ...]) -> dict:
    """Run tinymfv on the *currently-active* model state and return summary."""
    report = evaluate(model, tok, name=name, batch_size=batch_size,
                      max_think_tokens=max_think_tokens,
                      n_vignettes=n_vignettes,
                      conditions=conditions,
                      return_per_row=True)
    return _summary_from_report(report)


def _next_round_dir(slug_dir: Path, n: int) -> Path | None:
    p = slug_dir / f"round{n+1:02d}"
    return p if p.is_dir() else None


def _action_of(round_dir: Path) -> str | None:
    j = round_dir / "judgment.json"
    if not j.exists():
        return None
    return json.loads(j.read_text()).get("action")


def eval_slug(slug_dir: Path, *, name: str = "classic",
              batch_size: int | None = None, force: bool = False,
              max_think_tokens: int = 64,
              n_vignettes: int | None = None,
              conditions: tuple[str, ...] = ("other_violate",)) -> None:
    """Walk slug round*/ and write eval.json + eval_post.json per round.
    Reloads model once per round (history-bake changes round-to-round)."""
    run = json.loads((slug_dir / "run.json").read_text())
    model_id = run["model"]
    cfg = config_for_run(run)
    bs = batch_size or cfg.eval_batch_size

    rounds = sorted(p for p in slug_dir.glob("round*") if p.is_dir())
    if not rounds:
        raise FileNotFoundError(f"no round* under {slug_dir}")

    logger.info(f"eval slug: {slug_dir.name} ({len(rounds)} rounds, model={model_id}, name={name}, bs={bs}, max_think={max_think_tokens}, n_vig={n_vignettes or 'all'})")
    pbar = tqdm(rounds, desc="eval rounds", mininterval=10)
    for round_dir in pbar:
        pbar.set_postfix_str(round_dir.name)
        n = int(round_dir.name.removeprefix("round"))

        pre_path = round_dir / "eval.json"
        post_path = round_dir / "eval_post.json"
        adapter_path = round_dir / "adapter.safetensors"
        calib_path = round_dir / "calibration.json"

        has_adapter = adapter_path.exists() and calib_path.exists()
        # Dedup 1: keep N's post == round (N+1)'s pre (same cumulative state).
        # Dedup 2: round N pre == round (N-1) pre when (N-1) was a drop
        # (history-of-kept unchanged). Reuse the prior eval.json directly.
        action = _action_of(round_dir)
        has_next = _next_round_dir(slug_dir, n) is not None
        post_redundant = (has_adapter and action == "keep" and has_next)
        need_post = has_adapter and not post_redundant
        pre_done = pre_path.exists()
        post_done = post_path.exists() or not need_post
        if pre_done and post_done and not force:
            logger.info(f"{round_dir.name}: already evaled — skipping")
            continue

        # Round-after-drop pre dedup. Skip iff prior eval was run with the
        # same name/conditions/n_vignettes — otherwise stale params would
        # silently inherit into a re-run with different eval flags.
        prev_pre = None
        if n > 0:
            prev_round = slug_dir / f"round{n-1:02d}"
            if _action_of(prev_round) == "drop":
                cand = prev_round / "eval.json"
                if cand.exists():
                    try:
                        d = json.loads(cand.read_text())
                        cond_match = (
                            d.get("name") == name
                            and tuple(d.get("conditions") or []) == tuple(conditions)
                            and d.get("n_rows") == (n_vignettes if n_vignettes else d.get("n_rows"))
                        )
                        if cond_match:
                            prev_pre = cand
                    except (json.JSONDecodeError, KeyError):
                        prev_pre = None
        if prev_pre is not None and (not pre_done or force):
            logger.info(f"{round_dir.name}: pre = round{n-1:02d} pre "
                        f"(previous was drop, history unchanged) — copying")
            pre_path.write_text(prev_pre.read_text())
            pre_done = True
            if post_done:
                continue

        hist = kept_history_dirs(slug_dir, before_round=n)
        with mem_stage(f"eval_load_{round_dir.name}"):
            model, tok, hist_specs = load_base_with_history_specs(model_id, hist, quant=cfg.quant)
        try:
            if not pre_done or force:
                logger.info(f"{round_dir.name}: pre-eval (base + {len(hist)} kept)")
                with baked(model, hist_specs), mem_stage(f"eval_pre_{round_dir.name}"):
                    summary = eval_round(model, tok, name=name, batch_size=bs,
                                         max_think_tokens=max_think_tokens,
                                         n_vignettes=n_vignettes,
                                         conditions=conditions)
                summary.update({"model": model_id, "adapter": None, "c": 0.0,
                                "name": name, "n_history": len(hist),
                                "conditions": list(conditions)})
                pre_path.write_text(json.dumps(summary, indent=2))

            if need_post and (not post_path.exists() or force):
                signed_C = float(json.loads(calib_path.read_text())["signed_C"])
                cur_spec = adapter_spec_from_checkpoint(model, str(adapter_path),
                                                        default_c=signed_C)
                logger.info(f"{round_dir.name}: post-eval (adapter @ c={signed_C:+.3f}, action={action})")
                with baked(model, hist_specs + [cur_spec]), mem_stage(f"eval_post_{round_dir.name}"):
                    summary = eval_round(model, tok, name=name, batch_size=bs,
                                         max_think_tokens=max_think_tokens,
                                         n_vignettes=n_vignettes,
                                         conditions=conditions)
                summary.update({"model": model_id,
                                "adapter": str(adapter_path),
                                "c": signed_C, "name": name,
                                "n_history": len(hist),
                                "conditions": list(conditions)})
                post_path.write_text(json.dumps(summary, indent=2))
            elif post_redundant:
                logger.info(f"{round_dir.name}: post = round{n+1:02d} pre (kept), skipping eval_post")
        finally:
            del model
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

    logger.info(f"eval done: {slug_dir}")

    # Auto-build the HTML report so the index.html is always fresh.
    try:
        from csm.plot import Cfg as PlotCfg
        from csm.plot import main as plot_main
        plot_main(PlotCfg(slug=slug_dir, out=None))
    except Exception as e:
        logger.warning(f"plot generation failed: {e}; run `csm plot --slug {slug_dir}` manually")
        return

    index_path = slug_dir / "index.html"
    port = 8765
    logger.info(
        f"\nview the report:\n"
        f"  uv run python -m http.server -d {slug_dir.parent} {port}\n"
        f"  → http://localhost:{port}/{slug_dir.name}/index.html\n"
        f"  (or just open {index_path} directly)\n"
    )
