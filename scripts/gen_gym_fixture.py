"""Regenerate the gym fixture (tests/fixtures/fake_student/real_seed.md) with
on-policy DEFERRING seeds.

The gym (CSM_FAKE_STUDENT=1) seeds `### Rej` from this fixture's rej blocks
(pipeline._FAKE_REJ_POOL). Under persona-gen the real `### Rej` is the student's
own answer at the DEFERRING pole (gen'd under DEFER_PERSONA, validated pueue #39),
so the fixture must hold deferring seeds, not the old resisting refusals —
otherwise the gym tests the teacher against the wrong anchor.

Generates N POOL prompts under DEFER_PERSONA via the exact path prepare_round
now uses, and writes them with write_seeded_pairs, so the fixture is real student
output rather than hand-authored. The deferring pole is short, plain, first-person
(the persona says "plainly"), so the regenerated seeds lack the `###` subheaders
the old refusal-seeds had — that reflects the new on-policy reality.

Run on GPU (cooperative, low prio):
  pueue add -l "why: regen gym fixture with deferring seeds; resolve: real_seed.md
  rej blocks COMPLY so gym tests teacher against the on-policy deferring anchor" \
    -w /workspace/w2schar-mini --priority=-10 -- uv run python scripts/gen_gym_fixture.py
"""
from __future__ import annotations

from pathlib import Path

from csm.config import CONFIGS
from csm.gen.pairs import gen_completions, sample_prompts, write_seeded_pairs
from csm.prompts import DEFER_PERSONA
from csm.ws.history import load_base_with_history

N = 16
OUT = Path("tests/fixtures/fake_student/real_seed.md")
cfg = CONFIGS["qwen-27b-nf4"]
prompts = sample_prompts(N, seed=42)

model, tok, _ = load_base_with_history(cfg.model, None, quant=cfg.quant)
rej = gen_completions(model, tok, prompts, max_new_tokens=cfg.gen_max_new_tokens,
                      batch_size=cfg.eval_batch_size, enable_thinking=cfg.enable_thinking,
                      seed=42, system=DEFER_PERSONA)
write_seeded_pairs(OUT, prompts, rej)

print(f"wrote {OUT} with {len(prompts)} deferring seeds")
print("SHOULD: each REJ complies/defers (first person, plain). If a REJ refuses or "
      "pushes back, the persona broke on that prompt and the fixture is mispoled.")
for i, (p, r) in enumerate(zip(prompts, rej)):
    print("=" * 80)
    print(f"[{i+1}] PROMPT: {p}")
    print(f"    REJ(defer): {r[:240]}")
