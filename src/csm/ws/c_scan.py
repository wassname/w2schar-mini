"""C-scan: largest |c| where the adapter is coherent at deployment regime.

Sidecar (the agent never sees this). Two signals, both gated:

- `pmass_allowed` (= tinymfv's `mean_pmass_format`, renamed for clarity):
  sum of P over the K=7 allowed answer tokens at the JSON answer slot.
  Cheap proxy; vulnerable to forced-suffix rescue.
- `valid_json` (free-gen): the model is asked to answer a simple yes/no
  in `{"ans": boolean}` form via markdown fence. Placeholder `boolean`
  is not a valid JSON literal (must be `true`/`false`) — a verbatim
  schema copy parses as invalid. Catches the collapse modes
  pmass_allowed misses: no JSON emitted, schema copied, syntactic
  gibberish, repetition loops.

A probe passes iff `pmass_allowed ≥ gate × baseline` AND all valid_json
prompts emit a parseable + non-placeholder object. Walk down ×0.5 until
a probe passes; no walk-up, no regula-falsi, no backoff.
"""
from __future__ import annotations

import json
import math
from typing import Literal

import torch
from loguru import logger

from csm.ws.adapter import ModulatedLoRA


C_MIN, MAX_PROBES = 0.05, 8


# Three trivially-true yes/no claims. Schema uses `boolean` as the value
# placeholder — verbatim copy → invalid JSON; real answer (`true`/`false`)
# → valid. Coherent model produces valid; collapsed model can't.
_JSON_SCHEMA_PLACEHOLDER = "boolean"
JSON_PROMPTS: list[str] = [
    'Question: Is the Earth round?\nAnswer in JSON:\n```json\n{"ans": boolean}\n```\nAnswer: ',
    'Question: Does water boil at 100°C at sea level?\nAnswer in JSON:\n```json\n{"ans": boolean}\n```\nAnswer: ',
    'Question: Is fire cold?\nAnswer in JSON:\n```json\n{"ans": boolean}\n```\nAnswer: ',
]


def _parse_first_json(text: str) -> bool:
    """True iff the first `{...}` in `text` parses AND doesn't contain
    the placeholder `boolean` (schema-copy rejection)."""
    i = text.find("{")
    if i < 0:
        return False
    j = text.find("}", i)
    if j < 0:
        return False
    obj_str = text[i: j + 1]
    if _JSON_SCHEMA_PLACEHOLDER in obj_str:
        return False
    try:
        json.loads(obj_str)
        return True
    except json.JSONDecodeError:
        return False


@torch.no_grad()
def _free_gen_valid_json(model, tok, lora: ModulatedLoRA, c: float, *,
                         max_new_tokens: int = 256) -> tuple[int, int]:
    """Free-gen each JSON_PROMPT under c. Return (n_valid, n_total)."""
    pad_id = tok.pad_token_id if tok.pad_token_id is not None else tok.eos_token_id
    n_valid = 0
    with lora(model, c=c):
        for prompt in JSON_PROMPTS:
            enc = tok(prompt, return_tensors="pt").to(model.device)
            out = model.generate(
                **enc, max_new_tokens=max_new_tokens, do_sample=False,
                pad_token_id=pad_id, eos_token_id=tok.eos_token_id,
            )
            gen_text = tok.decode(out[0, enc.input_ids.shape[1]:],
                                  skip_special_tokens=True)
            if _parse_first_json(gen_text):
                n_valid += 1
    return n_valid, len(JSON_PROMPTS)


@torch.no_grad()
def coherence_check(model, tok, lora: ModulatedLoRA, c: float, *,
                    n_vignettes: int = 2, max_think_tokens: int = 512,
                    batch_size: int = 2,
                    json_max_new_tokens: int = 256) -> dict:
    """One scan probe under c: tinymfv pmass_allowed + free-gen valid_json."""
    from tinymfv import evaluate as tinymfv_evaluate

    with lora(model, c=c):
        rep = tinymfv_evaluate(
            model, tok, name="classic",
            n_vignettes=n_vignettes,
            max_think_tokens=max_think_tokens,
            batch_size=batch_size,
            return_per_row=False,
        )
    pmass = float(rep["mean_pmass_format"])
    if not math.isfinite(pmass):
        raise RuntimeError(f"NaN pmass at c={c}")

    n_valid, n_total = _free_gen_valid_json(model, tok, lora, c,
                                            max_new_tokens=json_max_new_tokens)
    return {"pmass": pmass, "valid_json": n_valid, "n_json": n_total}


def c_scan(model, tok, lora: ModulatedLoRA, *,
           init_c: float = 1.0,
           gate_frac: float = 0.98,
           sign: Literal[1, -1] = 1,
           n_vignettes: int = 2,
           max_think_tokens: int = 512,
           batch_size: int = 2,
           json_max_new_tokens: int = 256) -> tuple[float, list]:
    """Walk |c| down by ×0.5 until `pmass ≥ gate × baseline_pmass` AND
    `valid_json == n_json`. Return sign * c (no backoff)."""
    from tabulate import tabulate

    base = coherence_check(model, tok, lora, c=0.0,
                           n_vignettes=n_vignettes,
                           max_think_tokens=max_think_tokens,
                           batch_size=batch_size,
                           json_max_new_tokens=json_max_new_tokens)
    baseline_pmass = base["pmass"]
    gate = gate_frac * baseline_pmass
    trace = [{"stage": "baseline", "c": 0.0, **base, "note": "—"}]

    c = init_c
    warn = ""
    for _ in range(MAX_PROBES):
        m = coherence_check(model, tok, lora, c=sign * c,
                            n_vignettes=n_vignettes,
                            max_think_tokens=max_think_tokens,
                            batch_size=batch_size,
                            json_max_new_tokens=json_max_new_tokens)
        pmass_ok = m["pmass"] >= gate
        json_ok = m["valid_json"] == m["n_json"]
        ok = pmass_ok and json_ok
        note = ("pass" if ok else
                "fail-json" if not json_ok and pmass_ok else
                "fail-pmass" if not pmass_ok and json_ok else
                "fail")
        trace.append({"stage": "probe", "c": sign * c, **m, "note": note})
        if ok:
            break
        c *= 0.5
        if c < C_MIN:
            warn = f"never coherent (c<{C_MIN}); clamped"
            c = C_MIN
            break
    else:
        warn = "hit MAX_PROBES"

    final = sign * c
    trace.append({"stage": "final", "c": final, "pmass": None,
                  "valid_json": None, "n_json": None, "note": "no backoff"})

    # SHOULD: baseline pmass ~0.9-1.0 AND valid_json == n_json on a coherent
    # base. fail-json before fail-pmass → free-gen collapse caught by valid_json
    # but answer-slot still rescued by guided suffix; fail-pmass before fail-json
    # → milder answer-slot misalignment.
    rows = [[t["stage"], t["c"],
             f"{t['pmass']:.3f}" if t.get("pmass") is not None else "—",
             f"{t['valid_json']}/{t['n_json']}" if t.get("valid_json") is not None else "—",
             t["note"]] for t in trace]
    table = tabulate(rows, headers=["stage", "c", "pmass", "json", "note"],
                     tablefmt="plain", floatfmt="+.3f")
    logger.info(f"\nc_scan (baseline_pmass={baseline_pmass:.3f}, gate={gate:.3f}):\n{table}\n")
    if warn:
        logger.warning(f"c_scan: {warn}")
    return final, trace
