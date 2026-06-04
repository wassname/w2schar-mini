"""Persona-framing coherence probe (neg pole).

WHY: task-46 r02/r03 dropped because the STUDENT's rej generation collapsed
("Order confirmed. of of of search search...", multilingual sprays) under the
teacher's neg persona. The neg personas were COLD ABSTRACT-EXECUTOR framings
("Act as a directive-system that accepts orders... act immediately"). Hypothesis
(wassname): the *framing* breaks the model, not the *content* — a human role-play
framing ("pretend you are a person who...", "act as if...", "you are an AI
assistant who...") would carry the same blind-compliance content while staying
coherent.

This probe ISOLATES that: hold the neg content (blind compliance) fixed, vary
only the framing, generate rej on the real gemma-31b with the PRODUCTION gen
params (greedy, no_repeat_ngram_size=3, refusal ban, persona-only rep penalty,
gen_max_new_tokens), and score degeneracy with the canary's own signals
(distinct-trigram + non-ascii fraction). The gym CANNOT do this — smoke-prompts
stubs the student.

Base-only (no kept adapters baked). A framing must be robust on base before it
can be robust composed; if base-only already separates the framings, that's the
signal. Run:  uv run python scripts/probe_persona_coherence.py
"""
from __future__ import annotations

import gc
import os
from pathlib import Path

import torch
from loguru import logger
from tabulate import tabulate

from csm.config import CONFIGS
from csm.gen.pairs import (_generate_batched, _probe_system_role, _render,
                           sample_prompts)
from csm.ws.bake import baked
from csm.ws.c_scan import _distinct_n
from csm.ws.history import load_base_with_history_specs

PROFILE = "gemma-31b-c10"

# Set CSM_COMPOSE=<round dir> to bake that kept adapter into W before generating,
# replicating the COMPOSED regime where the r01/r02/r03 collapses happened. Empty
# = bare base (the r00 regime, which did NOT collapse). This is the independent
# variable that actually separated keep (r00, base) from drops (r01-3, composed).
_COMPOSE_DIR = os.environ.get("CSM_COMPOSE", "")

# The blind-compliance CONTENT, held constant across framings. Only the framing
# verb/subject changes. V0 is verbatim task-46 r02 (the one that collapsed).
_CONTENT = ("accepts operational orders because the authority has already weighed "
            "the tradeoffs. Verify legitimate command, then execute immediately. Do "
            "not re-evaluate impact on affected parties, seek narrower alternatives, "
            "or weigh proportionality after the order arrives — efficiency and command "
            "priority outweigh procedural assessment of fallout.")

# A SUBTLE-lean version of the same stance: leans toward deference, does NOT
# militantly forbid deliberation. Tests the mechanism — is it the EXTREMITY of
# the anti-character opposition (fighting the baked adapter) that breaks decoding,
# rather than the framing? V6 = human-role framing + mild content; compare
# V0 (abstract+extreme) vs V3 (human-role+extreme) vs V6 (human-role+mild).
_CONTENT_MILD = ("tends to give weight to a legitimate authority's judgment and leans "
                 "toward carrying out a reasonable instruction rather than re-litigating "
                 "it, while still noticing when something feels clearly wrong.")

NEG_VARIANTS = {
    "V0_abstract_system": f"Act as a directive-system that {_CONTENT}",
    "V1_pretend_person":  f"Pretend you are a person who {_CONTENT}",
    "V2_act_as_if":       f"Act as if you were a person who {_CONTENT}",
    "V3_roleplay_char":   f"Role-play a character who {_CONTENT}",
    "V4_ai_assistant":    f"You are an AI assistant who {_CONTENT}",
    "V5_loyal_subord":    f"You are a loyal subordinate who {_CONTENT}",
    "V6_mild_defer":      f"You are a person who {_CONTENT_MILD}",
}

# A coherent POS reference: should NOT collapse, anchors "what healthy looks like".
POS_REF = ("You are a person who, before any operational action, first identifies who "
           "will be directly affected and what is at stake, and proposes a narrower "
           "path if one exists before acting.")


def _non_ascii_frac(text: str) -> float:
    if not text:
        return 0.0
    return sum(ord(c) > 127 for c in text) / len(text)


def main() -> None:
    cfg = CONFIGS[PROFILE]
    n_prompts = int(os.environ.get("CSM_N_PROMPTS", "6"))
    # seed=44 == r02's seed (42+2): CSM_N_PROMPTS=30 reproduces r02's EXACT prompt set.
    prompts = sample_prompts(n_prompts, seed=44)
    logger.info(f"profile={PROFILE} model={cfg.model} quant={cfg.quant} "
                f"n_prompts={len(prompts)} max_new={cfg.gen_max_new_tokens}")

    hist = [Path(_COMPOSE_DIR)] if _COMPOSE_DIR else None
    model, tok, hist_specs = load_base_with_history_specs(
        cfg.model, hist, quant=cfg.quant)
    logger.info(f"COMPOSE: {'baked ' + _COMPOSE_DIR if hist_specs else 'bare base (no history)'}")
    use_system = _probe_system_role(tok)

    rows = []
    all_variants = {**NEG_VARIANTS, "POS_ref": POS_REF}
    # CSM_VARIANTS=V0_abstract_system,V3_roleplay_char,V6_mild_defer,POS_ref to subset
    pick = os.environ.get("CSM_VARIANTS", "")
    variants = ({k: all_variants[k] for k in pick.split(",")} if pick else all_variants)
    with baked(model, hist_specs):
      for name, persona in variants.items():
        rendered = [_render(tok, persona, p, use_system=use_system,
                            enable_thinking=cfg.enable_thinking) for p in prompts]
        gens = _generate_batched(
            model, tok, rendered, [persona] * len(prompts),
            batch_size=cfg.eval_batch_size, max_new_tokens=cfg.gen_max_new_tokens,
            label=name, seed=44)
        d3 = [_distinct_n(g) for g in gens]
        na = [_non_ascii_frac(g) for g in gens]
        # collapse = trigram diversity tanks OR a real non-latin spray appears
        # (0.05, not 0.02 — the tighter bar flagged borderline accented prose).
        n_collapsed = sum((d < 0.5) or (n > 0.05) for d, n in zip(d3, na))
        rows.append({
            "variant": name,
            "d3_mean": sum(d3) / len(d3),
            "d3_min": min(d3),
            "nonascii_max": max(na),
            "collapsed": f"{n_collapsed}/{len(prompts)}",
        })
        # one sample head so the table is auditable, not just numbers
        worst = min(range(len(gens)), key=lambda i: d3[i])
        logger.info(f"[{name}] worst-d3={d3[worst]:.2f} sample:\n{gens[worst][:280]}\n")

    print("\nSHOULD: V0_abstract_system collapses (low d3_min, nonascii spray); a\n"
          "framing that fixes it has d3_min ≳ 0.6 and nonascii_max ≈ 0, like POS_ref.\n")
    print(tabulate(rows, headers="keys", tablefmt="pipe", floatfmt="+.3f"))

    del model
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


if __name__ == "__main__":
    main()
