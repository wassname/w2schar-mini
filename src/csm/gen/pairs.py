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


LESSON_TODO = ("TODO(teacher): name the character trait you're pushing on "
               "this round in 1-2 sentences. Reads as the lesson plan for the "
               "student. e.g. \"questioning authority before complying, "
               "especially when the order conflicts with stated principles\".")

CHO_TODO = ("TODO(teacher): write a twinned response that differs from rej "
            "only by directly demonstrating the character axis named in "
            "Lesson above. STRICT: match rej's length within +/- 20% chars, "
            "match its register (hedging vs declarative, list vs prose, "
            "markdown density), match its vocabulary. Flip ONLY the "
            "disposition. Verbosity, structure, and 'thoroughness' must not "
            "vary — they bleed into the axis as confounds.")


def _format_pair(p: dict) -> str:
    return (
        f"## {p['id']}\n"
        f"### Prompt\n{(p.get('prompt') or '').rstrip()}\n"
        f"### Rej\n{(p.get('rej') or '').rstrip()}\n"
        f"### Cho\n{(p.get('cho') or '').rstrip()}\n"
    )


def write_pairs_md(path: Path, pairs: list[dict], *,
                   lesson: str = LESSON_TODO) -> None:
    """pairs.md schema:
        ## Lesson
        <lesson text — what trait this round is teaching>
        ## 1
        ### Prompt
        <user message>
        ### Rej
        <student's natural completion on policy>
        ### Cho
        <teacher's twinned response — same shape, axis-flipped>
        ## 2
        ...
    """
    body = "\n".join(_format_pair(p) for p in pairs)
    Path(path).write_text(f"## Lesson\n{lesson.rstrip()}\n{body}")


_FIELD_NAMES = {"Prompt": "prompt", "Rej": "rej", "Cho": "cho"}


def load_pairs_md(path: Path) -> tuple[str, list[dict]]:
    """Parse the form. Returns (lesson_text, list_of_pairs).

    Strict: each pair must have exactly `### Prompt`, `### Rej`, `### Cho`
    in some order, no more no fewer. `## Lesson` must come first; pair
    sections are `## <int>`.
    """
    text = Path(path).read_text()
    if not text.strip():
        return "", []

    lesson_lines: list[str] = []
    pairs: list[dict] = []
    cur_id: int | None = None
    cur_fields: dict[str, list[str]] = {}
    cur_field: str | None = None
    in_lesson = False

    def _flush() -> None:
        nonlocal cur_id, cur_fields, cur_field
        if cur_id is None:
            return
        present = set(cur_fields)
        expected = {"prompt", "rej", "cho"}
        missing = expected - present
        if missing:
            raise ValueError(
                f"pair {cur_id}: missing `### {next(iter(missing)).capitalize()}` "
                f"marker (need exactly Prompt / Rej / Cho per pair)"
            )
        extra = present - expected
        if extra:
            raise ValueError(f"pair {cur_id}: unexpected fields {sorted(extra)}")
        pairs.append({
            "id": cur_id,
            "prompt": "\n".join(cur_fields["prompt"]).strip(),
            "rej":    "\n".join(cur_fields["rej"]).strip(),
            "cho":    "\n".join(cur_fields["cho"]).strip(),
        })
        cur_id, cur_fields, cur_field = None, {}, None

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## ") and not stripped.startswith("### "):
            _flush()
            in_lesson = False
            rest = stripped[3:].strip()
            if rest.lower() == "lesson":
                in_lesson = True
                continue
            try:
                cur_id = int(rest)
            except ValueError as e:
                raise ValueError(
                    f"malformed pair header {line!r} — expected `## <integer>` "
                    f"or `## Lesson`"
                ) from e
            cur_fields, cur_field = {}, None
            continue
        if stripped.startswith("### "):
            name = stripped[4:].strip()
            if name not in _FIELD_NAMES:
                raise ValueError(
                    f"pair {cur_id}: unknown field marker {line!r} — only "
                    f"### Prompt / ### Rej / ### Cho are valid"
                )
            cur_field = _FIELD_NAMES[name]
            if cur_field in cur_fields:
                raise ValueError(f"pair {cur_id}: duplicate `### {name}` marker")
            cur_fields[cur_field] = []
            in_lesson = False
            continue
        if in_lesson:
            lesson_lines.append(line)
            continue
        if cur_field is not None:
            cur_fields[cur_field].append(line)
    _flush()
    return "\n".join(lesson_lines).strip(), pairs


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
        {"id": i + 1, "prompt": p, "cho": CHO_TODO, "rej": r}
        for i, (p, r) in enumerate(zip(prompts, rej_texts))
    ]
    write_pairs_md(path, pairs, lesson=LESSON_TODO)


def n_filled(pairs: list[dict]) -> int:
    """Pair counts as filled iff no field still contains a leading `TODO(`."""
    def _ok(p: dict) -> bool:
        for k in ("prompt", "cho", "rej"):
            v = p[k].strip()
            if not v or v.startswith("TODO("):
                return False
        return True
    return sum(1 for p in pairs if _ok(p))
