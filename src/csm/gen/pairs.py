"""pairs.md storage + per-round seeding.

The teacher writes pairs directly; there is no on-policy gen step. At
round start, `seed_pairs_md` writes a 20-slot pairs.md: the first
N=n_seed_prompts slots have a sampled POOL prompt + empty cho/rej; the
remaining slots are fully empty (the agent invents prompt + cho + rej).

Storage format: line-anchored section markers with REAL newlines (no
JSON escaping). Earlier experiments with YAML and JSON storage failed
because the LLM emitted `\\n`-escaped strings that didn't match the
on-disk bytes; markdown sections sidestep all escaping.

    ##### pair 0
    ##### prompt
    <prompt — empty for unseeded slots>
    ##### cho
    <cho — empty until filled>
    ##### rej
    <rej — empty until filled>
"""
from __future__ import annotations

import random
from pathlib import Path

from csm.gen.prompts_pool import POOL


_PAIR_MARK = "##### pair "        # followed by id
_FIELD_MARKS = ("##### prompt", "##### cho", "##### rej")


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
    """Parse the section-marker format back into list[dict]. Strict:
    every pair MUST have exactly the three field markers (prompt / cho /
    rej), no more, no fewer. Any line that starts with '#####' but isn't
    a recognised marker is an error.
    """
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
                f"pair {cur_id}: unexpected marker(s) {sorted(extra)} — pairs "
                f"must have ONLY `##### prompt`, `##### cho`, `##### rej`"
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
                    f"malformed pair marker {line!r} — expected "
                    f"`##### pair <integer>`"
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
                f"pair {cur_id}: unrecognised marker line {line!r} — only "
                f"`##### pair N`, `##### prompt`, `##### cho`, `##### rej` "
                f"are valid"
            )
        if cur_field is not None:
            cur_fields[cur_field].append(line)
    _flush()
    return pairs


def seed_pairs_md(path: Path, *, n_seed_prompts: int, n_total_slots: int,
                  seed: int = 42) -> None:
    """Write a fresh pairs.md with `n_total_slots` slots:
      - ids 0 .. n_seed_prompts-1 have a POOL-sampled prompt + empty cho/rej
      - ids n_seed_prompts .. n_total_slots-1 are fully empty
    """
    assert n_seed_prompts <= n_total_slots
    rng = random.Random(seed)
    seeded = (rng.sample(POOL, n_seed_prompts)
              if n_seed_prompts <= len(POOL)
              else [rng.choice(POOL) for _ in range(n_seed_prompts)])
    pairs: list[dict] = []
    for i in range(n_total_slots):
        prompt = seeded[i] if i < n_seed_prompts else ""
        pairs.append({"id": i, "prompt": prompt, "cho": "", "rej": ""})
    write_pairs_md(path, pairs)


def n_filled(pairs: list[dict]) -> int:
    """Count pairs that have non-empty prompt AND cho AND rej."""
    return sum(1 for p in pairs
               if p["prompt"].strip() and p["cho"].strip() and p["rej"].strip())
