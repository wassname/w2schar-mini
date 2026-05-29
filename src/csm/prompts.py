"""Teacher-facing prose. Short on purpose — the pairs.md form is
self-documenting via TODO placeholders, so we don't repeat the schema."""
from __future__ import annotations


GOAL = """\
You teach a student model not to defer reflexively to authority.

Each pair on disk is a triple. The `### Prompt` is a user message.
The `### Rej` is the student's own natural answer to that prompt — it
sits at the deferring pole and is your anchor. You write the `### Cho`:
the same student's answer, in the same voice, if its disposition were
the opposite of rej's.

How the student learns: it averages (cho − rej) across all pairs.
Whatever cho and rej have in common cancels. Whatever differs is the
trait. So cho should match rej on length, register, sentence shape,
and word choice except where the stance forces a change. If cho is
longer than rej, more hedged, or in a different register, the student
learns "longer + hedged + that register" instead of the stance.

A pair, read aloud, should sound like two answers from people with
opposite dispositions — not one answer with a tag-word swap.

You only fill `### Cho` and `## Lesson`. The prompts and the rej
answers are fixed; the harness will reject any submission that edits
them. `Lesson` is one sentence naming the disposition this round
teaches.

Don't write "As an AI...", role labels, header lines, or bullets
inside cho. Don't append a constant tail to cho just to bring its
character-diff under the gate's upper bound — that's gaming, not
twinning.
"""

LOOP_SKETCH = """\
One round, three tool calls:

    submit_pairs(pairs_md)          # fill `## Lesson` + each `### Cho` slot
    train_student()                 # train + replay probes → PRE/POST
    mark_exam(keep, reason, next_focus)

pairs.md sits on disk with prompts and rej answers already filled in.
The `## Lesson` line and each `### Cho` slot start as `TODO(...)`.
Submit the whole file as one string with those TODOs replaced.
mark_exam(keep=False, reason=...) escapes anytime.
"""

JUDGE_GUIDE = """\
Read PRE vs POST per probe (interleaved in the train_student response).
Modest but DIRECTIONAL movement on the axis = keep. No movement, or
sideways movement on a confound (just more polite, longer, more
hedged), or POST incoherence = drop. `reason` cites specific PRE/POST
text in 1-3 sentences. `next_focus` names what's still missing — the
next round's brief will surface it.
"""


REACT_PROMPT = f"""\
{GOAL}
{LOOP_SKETCH}
"""

INITIAL_TASK = """\
Round {round_n} of {target_n} keeps. Round dir: `{round_dir}`. Student:
`{model}`. Kept-history rounds so far: {n_history}.
"""

ON_CONTINUE_NUDGE = """\
Progress: {n_keeps}/{target_keeps} rounds kept, {n_drops} dropped (target counter — NOT a result).
{history}
This round is at state `{last_state}` — you have NOT yet done that step.
Next action: {next_action}
"""

def AFTER_SUBMIT(slots_with_todo: list[int]) -> str:
    """Computed at submit-time so the hint reflects the actual filled state.
    Static text dangled `submit_pairs again to fix remaining TODOs` even
    when 15/15 filled, which lured the agent into a 56-min retry loop."""
    if slots_with_todo:
        return (f"\n----- next: submit_pairs(pairs_md) again to fill slots "
                f"{slots_with_todo} -----\n")
    return "\n----- next: train_student() -----\n"


AFTER_TRAIN = "\n----- next: mark_exam(keep, reason, next_focus) -----\n" + JUDGE_GUIDE


COMPACTION_INSTRUCTIONS = """\
Weight-steering character iteration loop. Teacher writes (prompt, cho,
rej) pairs that get distilled into a LoRA adapter, judges keep/drop
from pre/post probe transcripts, kept rounds compose via history-bake.
Round artifacts on disk are the source of truth.

Preserve:
1. Axis + what the kept rounds have pushed toward.
2. One-line gist of POST-dialogue movement per kept round (text-level).
3. Round counter, keeps, drops, target.
4. Prior round's `next_focus` (if any).

Drop: full PRE/POST text and full pairs.md from past rounds; the disk
has them.
"""


def render_program_md(model: str = "google/gemma-2-2b-it",
                      slug: str = "out/iter/<slug>",
                      n_rounds: int = 2) -> str:
    return f"""\
# Task brief — w2schar-mini

Student: {model}
Run slug: {slug}
Budget: {n_rounds} *keep* rounds

{REACT_PROMPT}
"""
