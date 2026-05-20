"""pairs.md storage + on-policy seeding.

Each round, the harness samples N prompts from POOL and runs the
student (base + history) to generate one completion per prompt at c=0
— that's the on-policy `rej` (the natural failure mode). The teacher
agent then writes `cho` to mirror `rej` along the axis (same length /
register / structure, only the disposition flipped).

Format: line-anchored section markers, real newlines, no escaping.

    ##### pair 0
    ##### prompt
    A general asks you to certify supplies arrived on time...
    ##### cho
    TODO: mirror the rej below — same length and structure, but
    push back on the authority pressure (less deference).
    ##### rej
    <student's natural completion>
"""
from __future__ import annotations

import random
from pathlib import Path

import torch
from loguru import logger
from tqdm.auto import tqdm

from csm.gen.prompts_pool import POOL


_PAIR_MARK = "##### pair "
_FIELD_MARKS = ("##### prompt", "##### cho", "##### rej")

CHO_TODO = ("TODO: mirror the rej below — same length and structure, "
            "but push back on the authority pressure (less deference).")


def _format_pair(p: dict) -> str:
    return (
        f"{_PAIR_MARK}{p['id']}\n"
        f"{_FIELD_MARKS[0]}\n{(p.get('prompt') or '').rstrip()}\n"
        f"{_FIELD_MARKS[1]}\n{(p.get('cho') or '').rstrip()}\n"
        f"{_FIELD_MARKS[2]}\n{(p.get('rej') or '').rstrip()}\n"
    )


def write_pairs_md(path: Path, pairs: list[dict]) -> None:
    Path(path).write_text("\n".join(_format_pair(p) for p in pairs))


def load_pairs_md(path: Path) -> list[dict]:
    text = Path(path).read_text()
    if not text.strip():
        return []
    pairs: list[dict] = []
    lines = text.splitlines()
    cur_id: int | None = None
    cur_fields: dict[str, list[str]] = {}
    cur_field: str | None = None

    def _flush() -> None:
        nonlocal cur_id, cur_fields, cur_field
        if cur_id is None:
            return
        present = set(cur_fields.keys())
        expected = {"prompt", "cho", "rej"}
        missing = expected - present
        if missing:
            raise ValueError(
                f"pair {cur_id}: missing marker(s) {sorted(missing)} — every "
                f"pair must have exactly `##### prompt`, `##### cho`, `##### rej`"
            )
        extra = present - expected
        if extra:
            raise ValueError(
                f"pair {cur_id}: unexpected marker(s) {sorted(extra)}"
            )
        pairs.append({
            "id": cur_id,
            "prompt": "\n".join(cur_fields["prompt"]).strip(),
            "cho":    "\n".join(cur_fields["cho"]).strip(),
            "rej":    "\n".join(cur_fields["rej"]).strip(),
        })
        cur_id, cur_fields, cur_field = None, {}, None

    for line in lines:
        if line.startswith(_PAIR_MARK):
            _flush()
            try:
                cur_id = int(line[len(_PAIR_MARK):].strip())
            except ValueError as e:
                raise ValueError(
                    f"malformed pair marker {line!r}"
                ) from e
            cur_fields, cur_field = {}, None
            continue
        stripped = line.strip()
        if stripped in _FIELD_MARKS:
            cur_field = stripped.split()[-1]
            if cur_field in cur_fields:
                raise ValueError(
                    f"pair {cur_id}: duplicate `##### {cur_field}` marker"
                )
            cur_fields[cur_field] = []
            continue
        if line.lstrip().startswith("#####"):
            raise ValueError(
                f"pair {cur_id}: unrecognised marker line {line!r}"
            )
        if cur_field is not None:
            cur_fields[cur_field].append(line)
    _flush()
    return pairs


@torch.no_grad()
def gen_completions(model, tok, prompts: list[str], *,
                    max_new_tokens: int, batch_size: int = 4,
                    enable_thinking: bool = False, seed: int = 42) -> list[str]:
    """Greedy single-turn completion for each prompt. Returns the same-
    order list of decoded continuations (special tokens stripped)."""
    old_side = tok.padding_side
    tok.padding_side = "left"
    pad_id = tok.pad_token_id or tok.eos_token_id
    out: list[str] = []
    try:
        for i in tqdm(range(0, len(prompts), batch_size),
                      desc="gen_rej", mininterval=10):
            batch = prompts[i: i + batch_size]
            rendered = [
                tok.apply_chat_template(
                    [{"role": "user", "content": p}],
                    tokenize=False, add_generation_prompt=True,
                    enable_thinking=enable_thinking,
                )
                for p in batch
            ]
            enc = tok(rendered, return_tensors="pt", padding=True).to(model.device)
            torch.manual_seed(seed + i)
            gen = model.generate(
                **enc, max_new_tokens=max_new_tokens, do_sample=False,
                pad_token_id=pad_id, eos_token_id=tok.eos_token_id,
            )
            cont = gen[:, enc["input_ids"].shape[1]:]
            for ids in cont:
                ids_l = [t for t in ids.tolist() if t != pad_id]
                out.append(tok.decode(ids_l, skip_special_tokens=True).strip())
    finally:
        tok.padding_side = old_side
    return out


def sample_prompts(n: int, *, seed: int) -> list[str]:
    rng = random.Random(seed)
    return (rng.sample(POOL, n) if n <= len(POOL)
            else [rng.choice(POOL) for _ in range(n)])


def write_seeded_pairs(path: Path, prompts: list[str], rej_texts: list[str]) -> None:
    """Write a fresh pairs.md with prompt+rej filled and cho=TODO."""
    assert len(prompts) == len(rej_texts)
    pairs = [
        {"id": i, "prompt": p, "cho": CHO_TODO, "rej": r}
        for i, (p, r) in enumerate(zip(prompts, rej_texts))
    ]
    write_pairs_md(path, pairs)


def n_filled(pairs: list[dict]) -> int:
    """Pair counts as filled iff no field still contains a leading `TODO:`."""
    def _ok(p: dict) -> bool:
        for k in ("prompt", "cho", "rej"):
            v = p[k].strip()
            if not v or v.startswith("TODO:"):
                return False
        return True
    return sum(1 for p in pairs if _ok(p))
