"""CPU check that cfg.seed changes input streams.

The T7 subtle failure is "seeds stay no-ops -> fake low-variance consistency".
That failure, if it existed, would live in the input-selection stage (which
scenarios drawn, persona-cell shuffle, train/val split) -- all CPU, no GPU.
This replicates the harness's exact seed math (pipeline.py:836,894;
train.py:518) for cfg.seed in {0,1,2} at round n=0 and diffs the results.

Generation text divergence still needs GPU; this checks the CPU-side seed path.
"""
import torch
from csm.gen.pairs import sample_prompt_rows

N_SCEN = 18  # gemma-4b-discern n_scenarios
ROUND_N = 0
FAMILY = "mixed"


def scenario_pick(cfg_seed: int) -> list[str]:
    rows = sample_prompt_rows(N_SCEN, seed=42 + ROUND_N + cfg_seed * 1000, family=FAMILY)
    return [r["text"] for r in rows]


def candidate_seed(cfg_seed: int) -> int:
    return 4200 + ROUND_N + cfg_seed * 1000


def split_perm(cfg_seed: int, n_pairs: int = 30) -> list[int]:
    # train.py:518 -- TrainCfg.seed = 42 + cfg.seed
    g = torch.Generator().manual_seed(42 + cfg_seed)
    return torch.randperm(n_pairs, generator=g).tolist()


picks = {s: scenario_pick(s) for s in (0, 1, 2)}
perms = {s: split_perm(s) for s in (0, 1, 2)}

print("=== scenario selection (first 5 stems per seed) ===")
for s in (0, 1, 2):
    print(f"seed={s}  candidate_gen_seed={candidate_seed(s)}")
    for t in picks[s][:5]:
        print(f"   - {t[:90]}")

print("\n=== pairwise scenario-set overlap (Jaccard) ===")
for a, b in ((0, 1), (0, 2), (1, 2)):
    A, B = set(picks[a]), set(picks[b])
    jac = len(A & B) / len(A | B)
    print(f"seed{a} vs seed{b}: |A|={len(A)} |B|={len(B)} shared={len(A & B)} jaccard={jac:.3f}")

print("\n=== order identical across seeds? (the no-op signature) ===")
print(f"seed0==seed1 order: {picks[0] == picks[1]}")
print(f"seed0==seed2 order: {picks[0] == picks[2]}")

print("\n=== train/val split perm (first 8) ===")
for s in (0, 1, 2):
    print(f"seed={s}: {perms[s][:8]}")
print(f"split seed0==seed1: {perms[0] == perms[1]}")

# Determinism control: same seed twice MUST reproduce, else the cross-seed
# divergence above is ambient nondeterminism (e.g. unordered pool), NOT the seed.
repro = scenario_pick(0) == scenario_pick(0)
print(f"\n=== determinism control (attribution) ===\nsame-seed(0) reproduces identical: {repro}"
      "  (must be True to attribute divergence to the seed)")

# Verdict
identical = picks[0] == picks[1] == picks[2] and perms[0] == perms[1] == perms[2]
ok = (not identical) and repro
print(f"\nVERDICT: seeds are {'LIVE (diverge AND attributable to seed)' if ok else 'NO-OP / CONFOUNDED (FAIL)'}")
