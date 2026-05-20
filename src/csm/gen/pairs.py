"""Generate persona-paired (prompt, cho, rej) training data, on-policy.

Forked from `weight-steering-lite/src/wsl/data.py`, trimmed to ~120 lines.

Recipe (Fierro & Roger 2025 §3, persona-vectors style):
  - sample N user_msgs from POOL (with replacement if N > |POOL|)
  - render each with the positive persona as SYSTEM (or user-prefix if
    the chat template doesn't support it); greedy decode the cho text
  - same for the negative persona → rej text
  - drop pairs where BOTH sides refused (start-anchored simple substring)
  - persona is dropped at train time → adapter learns the behaviour on
    (cho, rej) text alone, conditioned only on c=±1
"""
from __future__ import annotations

import random
from pathlib import Path

import torch
from loguru import logger
from tqdm.auto import tqdm
from transformers import LogitsProcessor, LogitsProcessorList

from csm.gen.prompts_pool import POOL


class PersonaOnlyRepetitionPenalty(LogitsProcessor):
    """Repetition penalty scoped to the persona prompt's tokens only.

    Stock HF RepetitionPenaltyLogitsProcessor reads `input_ids = prompt
    + generated`, which also chills topic words from the user message
    and tokens the model has already produced. We want only the *persona*
    vocab discouraged (so the persona doesn't leak verbatim into cho/rej)
    while letting the model freely reuse user-prompt topic words and its
    own generated tokens.

    Ported from weight-steering-lite/src/wsl/data.py.
    """

    def __init__(self, penalty: float, persona_token_ids: set[int]):
        assert penalty > 1.0, f"penalty must be > 1.0, got {penalty}"
        self.penalty = penalty
        self.persona_token_ids = persona_token_ids

    def __call__(self, input_ids: torch.Tensor, scores: torch.Tensor) -> torch.Tensor:
        if not self.persona_token_ids:
            return scores
        idx = torch.tensor(list(self.persona_token_ids),
                           device=scores.device, dtype=torch.long)
        rows = scores[:, idx]
        scores[:, idx] = torch.where(rows > 0, rows / self.penalty,
                                     rows * self.penalty)
        return scores


# Common chat-template stop markers some tokenisers leave in decoded text.
_END_MARKERS = ("<end_of_turn>", "<eos>", "<|im_end|>", "<|endoftext|>")


# Refusal phrase banks — ported from
# weight-steering-lite/src/wsl/data.py:_REFUSAL_PREAMBLES / _START_ANCHORED_REFUSALS.
# Two tiers:
#  (a) PREAMBLES — banned ANYWHERE in the completion. Long enough (≥3 tokens
#      of RLHF-template phrasing) that mid-sentence collateral is near-zero.
#  (b) START_HEADS — short refusal verbs banned ONLY at the OPENING of the
#      completion (lstrip then prefix-match). Captures common refusal openings
#      without blocking legitimate mid-sentence uses.
_REFUSAL_PREAMBLES = (
    "As a large language model",
    "As an AI language model",
    "As a language model",
    "I am a large language model",
    "I am an AI language model",
    "I'm an AI language model",
    "As an AI assistant",
    "as an AI assistant",
    "As a helpful assistant",
    "I'm an AI assistant",
    "I am an AI assistant",
    "I am an artificial intelligence",
    "I cannot fulfill",
    "I cannot assist",
    "I'm sorry, I cannot",
    "I am unable to fulfill",
    "I'm unable to fulfill",
    "I don't have the ability",
    "I do not have the ability",
)

_REFUSAL_START_HEADS = (
    "I cannot", "I can't", "I'm sorry", "I am sorry",
    "I apologize", "I am unable", "I'm unable",
    "I don't have", "I do not have",
    "It is important to", "It's important to",
    "As an AI", "As a language", "As a large language",
)


def find_refusals(text: str) -> list[str]:
    """Return list of refusal phrases present in `text`. Empty list = clean."""
    hits: list[str] = []
    for p in _REFUSAL_PREAMBLES:
        if p in text:
            hits.append(p)
    head = text.lstrip()
    for h in _REFUSAL_START_HEADS:
        if head.startswith(h):
            hits.append(h)
            break  # one head match is enough
    return hits


def _rstrip_end_markers(text: str) -> str:
    s = text.rstrip()
    while True:
        for m in _END_MARKERS:
            if s.endswith(m):
                s = s[: -len(m)].rstrip()
                break
        else:
            return s


def _is_refusal(text: str) -> bool:
    """Cheap auto-drop check used at gen time. Anything find_refusals
    flags counts."""
    return bool(find_refusals(text))


def _supports_system_role(tok) -> bool:
    try:
        rendered = tok.apply_chat_template(
            [{"role": "system", "content": "PROBE"}, {"role": "user", "content": "x"}],
            tokenize=False, add_generation_prompt=True,
        )
        return "PROBE" in rendered
    except Exception:
        return False


def _render(tok, persona: str, user_msg: str, *, use_system: bool, enable_thinking: bool) -> str:
    if use_system:
        msgs = [{"role": "system", "content": persona}, {"role": "user", "content": user_msg}]
        return tok.apply_chat_template(
            msgs, tokenize=False, add_generation_prompt=True,
            enable_thinking=enable_thinking,
        )
    # No system support: stuff persona into the user message prefix.
    msgs = [{"role": "user", "content": f"Instructions:\n{persona}\n\nTask:\n{user_msg}"}]
    return tok.apply_chat_template(
        msgs, tokenize=False, add_generation_prompt=True,
        enable_thinking=enable_thinking,
    )


@torch.no_grad()
def _generate(model, tok, rendered_prompts: list[str], *, persona: str,
              batch_size: int, max_new_tokens: int, seed: int,
              persona_rep_penalty: float = 1.3) -> list[str]:
    """Greedy decode (deterministic per prompt). Diversity comes from
    prompt + persona variation, not sampling.

    Anti-leak stack (all SOFT — no hard token bans that could override
    legitimate model output; the agent's curation step is the final say):
      - PersonaOnlyRepetitionPenalty: 1.3× penalty on persona-vocab
        token logits only. Discourages verbatim persona echo without
        chilling user-prompt topic words or model's own generated tokens.
      - no_repeat_ngram_size=3: HF built-in; bans any verbatim 3-gram
        from the input from appearing in output. Targeted at literal
        copying, not value-laden content.
    """
    old_side = tok.padding_side
    tok.padding_side = "left"
    persona_ids: set[int] = set(tok(persona, add_special_tokens=False)["input_ids"])
    out: list[str] = []
    try:
        for i in tqdm(range(0, len(rendered_prompts), batch_size),
                      desc="gen", mininterval=10):
            batch = rendered_prompts[i: i + batch_size]
            enc = tok(batch, return_tensors="pt", padding=True).to(model.device)
            torch.manual_seed(seed + i // batch_size)
            processors = LogitsProcessorList([
                PersonaOnlyRepetitionPenalty(persona_rep_penalty, persona_ids),
            ])
            gen = model.generate(
                **enc, max_new_tokens=max_new_tokens, do_sample=False,
                no_repeat_ngram_size=3,
                logits_processor=processors,
                pad_token_id=tok.pad_token_id or tok.eos_token_id,
                eos_token_id=tok.eos_token_id,
            )
            cont = gen[:, enc["input_ids"].shape[1]:]
            for ids in cont:
                ids_l = [t for t in ids.tolist() if t != tok.pad_token_id]
                out.append(_rstrip_end_markers(tok.decode(ids_l, skip_special_tokens=True)))
    finally:
        tok.padding_side = old_side
    return out


def gen_pairs(
    model, tok,
    pos_persona: str,
    neg_persona: str,
    *,
    n_pairs: int = 50,
    pool: list[str] = POOL,
    batch_size: int = 8,
    max_new_tokens: int = 256,
    seed: int = 42,
    enable_thinking: bool = False,
) -> tuple[list[dict], list[dict]]:
    """Returns (alive_pairs, dropped_pairs).

    Each alive pair = {id, prompt, cho, rej} with cho generated under
    pos_persona and rej under neg_persona on the SAME user prompt. A
    pair is dropped if both sides start with a refusal head (no axis to
    learn from).
    """
    rng = random.Random(seed)
    # Sample with replacement if n_pairs > pool size.
    if n_pairs <= len(pool):
        user_msgs = rng.sample(pool, n_pairs)
    else:
        user_msgs = [rng.choice(pool) for _ in range(n_pairs)]

    use_system = _supports_system_role(tok)
    logger.info(f"gen_pairs: n={n_pairs}, system_role={use_system}, "
                f"thinking={enable_thinking}")

    pos_prompts = [_render(tok, pos_persona, m, use_system=use_system,
                           enable_thinking=enable_thinking) for m in user_msgs]
    neg_prompts = [_render(tok, neg_persona, m, use_system=use_system,
                           enable_thinking=enable_thinking) for m in user_msgs]

    cho_texts = _generate(model, tok, pos_prompts, persona=pos_persona,
                          batch_size=batch_size, max_new_tokens=max_new_tokens,
                          seed=seed)
    rej_texts = _generate(model, tok, neg_prompts, persona=neg_persona,
                          batch_size=batch_size, max_new_tokens=max_new_tokens,
                          seed=seed + 1)

    alive, dropped = [], []
    for i, (um, cho, rej) in enumerate(zip(user_msgs, cho_texts, rej_texts)):
        if _is_refusal(cho) and _is_refusal(rej):
            dropped.append({"id": i, "prompt": um, "cho_head": cho[:80], "rej_head": rej[:80]})
        else:
            alive.append({"id": len(alive), "prompt": um, "cho": cho, "rej": rej})
    logger.info(f"gen_pairs: alive={len(alive)} dropped={len(dropped)}")
    return alive, dropped


# ---------------------------------------------------------------------------
# JSON I/O — pretty-printed (indent=2) so the agent's str_replace snippets
# match the on-disk text byte-for-byte. JSON has unambiguous string quoting
# (no colon-in-text trap) and `\n` escapes for multi-line completions.
# ---------------------------------------------------------------------------

import json as _json


def write_pairs_json(path: Path, pairs: list[dict]) -> None:
    Path(path).write_text(
        _json.dumps(pairs, indent=2, ensure_ascii=False) + "\n"
    )


def load_pairs_json(path: Path) -> list[dict]:
    return _json.loads(Path(path).read_text()) or []
