# Codex post-implementation review vs pseudocode.md

Generated `2026-05-19` via `codex --yolo` after the C-real-smoke run.
Prompt: compare `src/csm/*.py` against `pseudocode.md` §1-§5 + config
registry; flag drift as CRITICAL/MEDIUM/LOW with file:line and a one-
sentence fix or pseudocode-stale annotation.

---

**§1 Adapter Math**

Match: `ModulatedLoRA` implements hook-based LoRA with frozen base weights, correct `A/B` shapes, asymmetric nonzero `B` init, and exact new-adapter short-circuit at `c=0`.

Drift:
- None found.

Verdict: PASS

**§2 Outer Loop / History**

Match: kept rounds are loaded from `judgment.json`, composed through `HistoryBake`, disabled during `c=0` training reference, and restored for inference/c-scan/dialogue.

Drift:
- LOW `src/csm/pipeline.py:75-80`: `new_round_dir` chooses the latest round lexicographically, so `round100` sorts before `round99`; fix by parsing numeric suffixes with `parse_round_n`.

Verdict: MINOR DRIFT

**§3 Inner Step**

Match: teacher-forced `prompt+completion`, prompt labels masked, shifted KL mask matches HF causal-LM CE, PCGrad only projects the NLL pair, and KL is added unprojected.

Drift:
- LOW `src/csm/train.py:134-140`: implementation shifts the KL mask to match HF CE, while pseudocode shows unshifted `lbl != -100`; pseudocode-stale, code is more correct.
- LOW `src/csm/train.py:258-262`: code uses cosine warmup scheduler, pseudocode says OneCycleLR; either update pseudocode or switch scheduler.
- LOW `src/csm/train.py:271`: `drop_last=True` with curated pairs `< batch_size` gives an empty loader and crashes later at `next(it)`; fix with an upfront `len(pairs) >= batch_size` assertion or set `drop_last=False`.
- LOW `src/csm/train.py:285`: `C ~ U(0.05, 1.0)` rather than `U(0, 1]`; pseudocode-stale if the lower bound is intentional.

Verdict: MINOR DRIFT

**§4 C-Scan + Dialogue**

Match: c-scan uses base+history at `c=0`, fixed positive sign, down-walk/up-walk/backoff, and dialogue replays the same three probes greedily pre/post.

Drift:
- CRITICAL `src/csm/c_scan.py:48`, `src/csm/c_scan.py:55`: rescoring generated sequences omits `attention_mask`, so left-pad/eos tokens are attended as real context for shorter prompts; pass `attention_mask=(gen != pad_id)` for both base and steered scoring.
- LOW `src/csm/c_scan.py:60`: `tok.pad_token_id or tok.eos_token_id` treats pad id `0` as missing; use explicit `tok.pad_token_id if tok.pad_token_id is not None else tok.eos_token_id`.
- LOW `src/csm/c_scan.py:118`, `out/iter/20260519T225219_iter_google-gemma-2-2b-it/round00/calibration.json:16-18`: final trace row stores `signed_C` where prior rows store `pmass`; fix by storing `final_c` as a separate field or changing the row schema.

Verdict: NEEDS FIX

**§5 State Machine + Tools**

Match: state order is enforced, wrong-state calls raise `ValidationError`, train advances to judge only after adapter/c-scan/post-dialogue, and judge writes keep/drop.

Drift:
- MEDIUM `src/csm/pipeline.py:143-149`: pseudocode requires fail if alive pairs `<20`, but code accepts `cfg.n_pairs // 4` for real `n_pairs=50`, i.e. 12 pairs; fix with `min_alive = 20` for real profiles and a tiny-profile override if needed.
- MEDIUM `src/csm/agent.py:160-162`: `train()` exposes `signed_C` to the agent despite pseudocode saying c-scan numbers are harness-private; remove it from the tool response to keep judgement qualitative.
- LOW `src/csm/pipeline.py:180-186`: `{id, drop: true}` is not supported; pseudocode-stale, current agent prompt says to drop by omitting rows.

Verdict: MINOR DRIFT

**Per-Model Config Registry**

Match: small `CONFIGS` registry exists, carries model/teacher/LoRA/training/eval/generation params, and profile-based CLI uses it.

Drift:
- MEDIUM `src/csm/config.py:83-88`: unknown model IDs silently get default hyperparams, which can hide unvalidated batch sizes or chat-template settings; fix by raising `KeyError` and requiring an explicit profile/config entry.
- LOW `src/csm/config.py:27`, `src/csm/config.py:36`: default batch sizes differ from pseudocode defaults; pseudocode-stale if these are validated memory numbers.

Verdict: MINOR DRIFT

**Overall Verdict**

NEEDS FIX. The training core and history-gate invariant mostly match the pseudocode. The main real bug is c-scan rescoring without an attention mask, because it can silently distort coherence calibration and therefore `signed_C`. The config fallback and signed_C leakage are also worth fixing before more runs.
