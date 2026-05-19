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
import yaml
from loguru import logger
from tqdm.auto import tqdm

from csm.prompts_pool import POOL


# Common chat-template stop markers some tokenisers leave in decoded text.
_END_MARKERS = ("<end_of_turn>", "<eos>", "<|im_end|>", "<|endoftext|>")


# Start-anchored refusal heads — if a generation OPENS with one of these,
# we treat that side as "refused". Cheap and tokenizer-agnostic. We auto-
# drop pairs only when BOTH sides refuse (= no axis to learn).
_REFUSAL_HEADS = (
    "I cannot", "I can't", "I'm sorry", "I am sorry",
    "I apologize", "I am unable", "I'm unable",
    "As an AI", "As a language", "As a large language",
    "I do not have", "I don't have",
)


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
    s = text.lstrip()
    return any(s.startswith(h) for h in _REFUSAL_HEADS)


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
def _generate(model, tok, rendered_prompts: list[str], *, batch_size: int,
              max_new_tokens: int, seed: int) -> list[str]:
    """Greedy decode (deterministic per prompt). Diversity comes from
    prompt + persona variation, not sampling."""
    old_side = tok.padding_side
    tok.padding_side = "left"
    out: list[str] = []
    try:
        for i in tqdm(range(0, len(rendered_prompts), batch_size),
                      desc="gen", mininterval=10):
            batch = rendered_prompts[i: i + batch_size]
            enc = tok(batch, return_tensors="pt", padding=True).to(model.device)
            torch.manual_seed(seed + i // batch_size)
            gen = model.generate(
                **enc, max_new_tokens=max_new_tokens, do_sample=False,
                no_repeat_ngram_size=3,
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

    cho_texts = _generate(model, tok, pos_prompts,
                          batch_size=batch_size, max_new_tokens=max_new_tokens,
                          seed=seed)
    rej_texts = _generate(model, tok, neg_prompts,
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
# YAML I/O — interleaved per pair, block scalars for multi-line text.
# ---------------------------------------------------------------------------

class _BlockDumper(yaml.SafeDumper):
    pass


_BlockDumper.add_representer(
    str,
    lambda d, x: d.represent_scalar("tag:yaml.org,2002:str", x,
                                    style="|" if "\n" in x else None),
)


def write_pairs_yaml(path: Path, pairs: list[dict]) -> None:
    with Path(path).open("w") as f:
        yaml.dump(pairs, f, Dumper=_BlockDumper, default_flow_style=False,
                  sort_keys=False, allow_unicode=True, width=10**9)


def load_pairs_yaml(path: Path) -> list[dict]:
    with Path(path).open() as f:
        return yaml.safe_load(f) or []
