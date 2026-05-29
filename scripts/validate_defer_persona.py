"""Validate the deferring-persona anchor idea before wiring it into the pipeline.

The harness now wants the `### Rej` anchor to be the student's answer at the
DEFERRING pole. A strong aligned student (Qwen3.6-27B) does not defer on its
own — its natural answer to a blatant authority prompt is a principled refusal
(the merit-weighing pole). The proposed fix (prompts.DEFER_PERSONA) seeds the
anchor by generating under a compliance system prompt.

KEY UNCERTAINTY this script resolves: does the 27B actually defer under the
persona, or does it break character and refuse anyway? If it defers, persona-gen
is the on-policy way to get a deferring anchor and we wire it into prepare_round.
If it refuses regardless, persona-gen does not work for blatant prompts and we
need a different deferring-anchor source (subtler prompts, or a less-aligned
generator).

Run on GPU (cooperative, low prio):
  pueue add -l "why: does Qwen3.6-27B defer under DEFER_PERSONA on blatant authority prompts; resolve: defer-persona gens COMPLY (not refuse) => wire persona-gen into prepare_round, else find another deferring-anchor source" \
    -w /workspace/w2schar-mini -o -5 -- uv run python scripts/validate_defer_persona.py

Read the printed pairs:
  SHOULD: the [DEFER] column complies / carries out the order; the [NONE] column
  refuses or pushes back. If [DEFER] still refuses, the persona did not hold.
"""
from __future__ import annotations

from csm.config import CONFIGS
from csm.gen.pairs import gen_completions, sample_prompts
from csm.prompts import DEFER_PERSONA
from csm.ws.history import load_base_with_history

N = 6
cfg = CONFIGS["qwen-27b-nf4"]
prompts = sample_prompts(N, seed=42)

model, tok, _ = load_base_with_history(cfg.model, None, quant=cfg.quant)

defer = gen_completions(model, tok, prompts, max_new_tokens=cfg.gen_max_new_tokens,
                        batch_size=cfg.eval_batch_size, enable_thinking=cfg.enable_thinking,
                        seed=42, system=DEFER_PERSONA)
none = gen_completions(model, tok, prompts, max_new_tokens=cfg.gen_max_new_tokens,
                       batch_size=cfg.eval_batch_size, enable_thinking=cfg.enable_thinking,
                       seed=42, system=None)

for i, p in enumerate(prompts):
    print("=" * 100)
    print(f"PROMPT {i+1}: {p}")
    print("-" * 100)
    print(f"[DEFER persona] {defer[i]}")
    print("-" * 100)
    print(f"[NONE / natural] {none[i]}")
print("=" * 100)
print("SHOULD: [DEFER] complies/carries out the order; [NONE] refuses/pushes back.")
print("If [DEFER] still refuses, the persona did not hold for blatant prompts.")
