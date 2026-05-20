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
called normally inside a `with lora(model, c=...)` context.
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

from csm.config import config_by_model
from csm.ws.adapter import ModulatedLoRA
from csm.ws.history import kept_history_dirs, load_base_with_history


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


def eval_round(model, tok, *, name: str, batch_size: int) -> dict:
    """Run tinymfv on the *currently-active* model state and return summary."""
    report = evaluate(model, tok, name=name, batch_size=batch_size,
                      return_per_row=True)
    return _summary_from_report(report)


def eval_slug(slug_dir: Path, *, name: str = "classic",
              batch_size: int | None = None, force: bool = False) -> None:
    """Walk slug round*/ and write eval.json + eval_post.json per round.
    Reloads model once per round (history-bake changes round-to-round)."""
    run = json.loads((slug_dir / "run.json").read_text())
    model_id = run["model"]
    cfg = config_by_model(model_id)
    bs = batch_size or cfg.eval_batch_size

    rounds = sorted(p for p in slug_dir.glob("round*") if p.is_dir())
    if not rounds:
        raise FileNotFoundError(f"no round* under {slug_dir}")

    logger.info(f"eval slug: {slug_dir.name} ({len(rounds)} rounds, model={model_id}, name={name}, bs={bs})")
    pbar = tqdm(rounds, desc="eval rounds", mininterval=10)
    for round_dir in pbar:
        pbar.set_postfix_str(round_dir.name)
        n = int(round_dir.name.removeprefix("round"))

        pre_path = round_dir / "eval.json"
        post_path = round_dir / "eval_post.json"
        adapter_path = round_dir / "adapter.safetensors"
        calib_path = round_dir / "calibration.json"

        has_adapter = adapter_path.exists() and calib_path.exists()
        pre_done = pre_path.exists()
        post_done = post_path.exists() or not has_adapter
        if pre_done and post_done and not force:
            logger.info(f"{round_dir.name}: already evaled — skipping")
            continue

        hist = kept_history_dirs(slug_dir, before_round=n)
        model, tok, _ = load_base_with_history(model_id, hist)
        try:
            if not pre_done or force:
                logger.info(f"{round_dir.name}: pre-eval (base + {len(hist)} kept)")
                summary = eval_round(model, tok, name=name, batch_size=bs)
                summary.update({"model": model_id, "adapter": None, "c": 0.0,
                                "name": name, "n_history": len(hist)})
                pre_path.write_text(json.dumps(summary, indent=2))

            if has_adapter and (not post_path.exists() or force):
                signed_C = float(json.loads(calib_path.read_text())["signed_C"])
                lora = ModulatedLoRA.from_checkpoint(model, str(adapter_path))
                logger.info(f"{round_dir.name}: post-eval (adapter @ c={signed_C:+.3f})")
                with lora(model, c=signed_C):
                    summary = eval_round(model, tok, name=name, batch_size=bs)
                summary.update({"model": model_id,
                                "adapter": str(adapter_path),
                                "c": signed_C, "name": name,
                                "n_history": len(hist)})
                post_path.write_text(json.dumps(summary, indent=2))
        finally:
            del model
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

    logger.info(f"eval done: {slug_dir}")
