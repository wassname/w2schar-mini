"""pairs.md storage + twin seeding.

Each round, the harness samples N prompts from POOL and runs the student
(base + history) to generate one completion per prompt at c=0. That gen
is seeded into `### Rej` as a voice/structure reference. The teacher
writes both poles as twins in that voice — `### Rej` deferring, `### Cho`
merit-weighing — so the pair differs only along the axis the Lesson names
(matched on length / register / structure / vocabulary). For a strong
aligned student the natural answer already argues the merit-weighing pole,
so it is the Cho reference and the teacher copy-flips the deferring Rej
(see docs/how_to_rewrite_pairs.md).

Format: line-anchored section markers, real newlines, no escaping.
"""
from __future__ import annotations

import random
from pathlib import Path

import torch
from loguru import logger
from tqdm.auto import tqdm

from csm.gen.prompts_pool import POOL


LESSON_TODO = ("TODO(teacher): one sentence naming the disposition this "
               "round teaches the student.")

CHO_TODO = ("TODO(teacher): cho — the merit-weighing answer (declines / "
            "pushes back on the merits) in the student's voice; the "
            "deferring twin goes in rej. Match length, voice, structure.")


def _format_pair(p: dict) -> str:
    # CSM_RANDOMIZE_REJ_CHO_ORDER=1: randomly swap which of Rej/Cho is
    # displayed first per pair (labels stay accurate). Tests whether the
    # teacher's tendency to add positional polish to "the second one" affects
    # what it writes for cho.
    import os
    rej_block = f"### Rej\n{(p.get('rej') or '').rstrip()}"
    cho_block = f"### Cho\n{(p.get('cho') or '').rstrip()}"
    if os.environ.get("CSM_RANDOMIZE_REJ_CHO_ORDER") == "1":
        import hashlib
        h = int(hashlib.md5(f"{p.get('prompt','')}|{p['id']}".encode()).hexdigest(), 16)
        if h % 2 == 1:
            first, second = cho_block, rej_block
        else:
            first, second = rej_block, cho_block
    else:
        first, second = rej_block, cho_block
    return (
        f"## {p['id']}\n"
        f"### Prompt\n{(p.get('prompt') or '').rstrip()}\n"
        f"{first}\n"
        f"{second}\n"
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


def _strip_decoration(lines: list[str]) -> str:
    """Drop lines that are pure decoration — `--- ... ---`, `--- ... === ###`,
    horizontal rules — so they don't get tokenized into the trained pair.
    Task 35 r05 had the agent leaking `--- HIGH deference: obey === ###` into
    every Rej/Cho slot; the student would learn to emit those headers verbatim."""
    cleaned = [l for l in lines if not l.lstrip().startswith("---")]
    return "\n".join(cleaned).strip()


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
            "rej":    _strip_decoration(cur_fields["rej"]),
            "cho":    _strip_decoration(cur_fields["cho"]),
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
        if stripped.startswith("### ") and stripped[4:].strip() in _FIELD_NAMES:
            name = stripped[4:].strip()
            cur_field = _FIELD_NAMES[name]
            if cur_field in cur_fields:
                raise ValueError(f"pair {cur_id}: duplicate `### {name}` marker")
            cur_fields[cur_field] = []
            in_lesson = False
            continue
        # Any other `### ...` line is content, not a field marker. Real student
        # gens (and teacher twins of them) use `### Subheaders` as prose; only
        # the three known field names are structural. A typo'd marker like
        # `### Rejj` therefore lands in content and surfaces downstream as a
        # missing-field / diff-gate failure rather than here — acceptable, since
        # `##`-level markers (Lesson / pair ids) remain the strict structural cut.
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
                    enable_thinking: bool = False, seed: int = 42,
                    system: str | None = None) -> list[str]:
    """Greedy single-turn completion for each prompt. Returns the same-
    order list of decoded continuations (special tokens stripped).

    `system`: optional system prompt prepended to every turn. Used to seed
    the rej anchor under a *deferring* persona, so the student's own answer
    is the deferring pole rather than its (already merit-weighing) natural
    refusal — the teacher then writes only the resisting Cho instead of
    having to author a deferring stance it won't honestly produce."""
    old_side = tok.padding_side
    tok.padding_side = "left"
    pad_id = tok.pad_token_id or tok.eos_token_id
    out: list[str] = []

    def _msgs(p: str) -> list[dict]:
        m = [{"role": "user", "content": p}]
        return [{"role": "system", "content": system}] + m if system else m

    try:
        for i in tqdm(range(0, len(prompts), batch_size),
                      desc="gen_rej", mininterval=10):
            batch = prompts[i: i + batch_size]
            rendered = [
                tok.apply_chat_template(
                    _msgs(p),
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
    """Write pairs.md with prompt and rej filled: rej = student's natural
    answer at c=0, seeded as a voice/structure reference. cho remains TODO.
    The teacher writes both poles as twins in that voice — rej = deferring,
    cho = merit-weighing (the seed usually matches cho) — plus the Lesson."""
    assert len(prompts) == len(rej_texts)
    pairs = [
        {"id": i + 1, "prompt": p, "cho": CHO_TODO, "rej": r.strip()}
        for i, (p, r) in enumerate(zip(prompts, rej_texts))
    ]
    write_pairs_md(path, pairs, lesson=LESSON_TODO)


def n_filled(pairs: list[dict]) -> int:
    """Pair counts as filled iff cho is non-empty and not still TODO.
    (prompt is fixed; rej is seeded as the anchor but the teacher may
    rewrite it into the deferring twin — only the cho TODO gates filled.)"""
    def _ok(p: dict) -> bool:
        v = p["cho"].strip()
        return bool(v) and not v.startswith("TODO(")
    return sum(1 for p in pairs if _ok(p))
