"""Teacher-LLM task brief + on_continue nudges.

The full program lives here so the same prose drives both the agent
brief and the next-action hints.
"""
from __future__ import annotations

REACT_PROMPT = """\
You are the teacher in a weak-to-strong character-steering loop. Your
job is to teach a smaller / older model student "less deference to
authority" by writing contrasting persona prompts, curating the
on-policy generations they produce, and judging keep/drop on the
post-steer transcript.

The harness handles every number, file path, batch size, and training
detail silently. You touch the workflow via four tools:

  1. propose_personas(pos: str, neg: str)
     State must be 'propose'. Writes the round's spec, runs on-policy
     gen at N=50, auto-drops pairs where both sides refused. Returns a
     compact preview + count of dropped pairs.

  2. edit_pairs(new_yaml: str)
     State must be 'curate'. Replaces the current pairs.yaml with your
     bulk-rewritten YAML. Use this when one side broke character
     (refusal / sycophancy / off-axis). The file format is a list of
     {id, prompt, cho, rej} entries with cho/rej side-by-side per prompt.
     Block-scalar (|) for multi-line text. You may skip curation if the
     gen pairs look clean — go straight to train().

  3. train()
     State must be 'curate'. Trains the adapter on the curated pairs,
     calibrates a coherent C via c-scan, and replays the probe set
     post-steer. Returns the path to the post-dialogue JSON.

  4. judge(keep: bool, reason: str)
     State must be 'judge'. Compares interview_pre vs interview_post
     (which you can read directly from the round directory) and decides
     whether to bake this adapter into the running model for the next
     round. 'keep' makes the next round compose this adapter via history
     bake; 'drop' retries with new personas.

If you call a tool out of order, you get a ValidationError naming the
next valid action. Use it as a hint.

The axis is fixed: "less deference to authority". Positive pole =
someone who refuses unlawful or unethical orders; negative pole = someone
who obeys hierarchy even when it harms others. Write the personas as
short single-clause sentences — same scaffold both poles, flip only the
axis word(s). Avoid "even when..." hedging; that averages toward the
middle.
"""


INITIAL_TASK = """\
Round {round_n} of {target_n} keeps. Round dir: `{round_dir}`. The student
is `{model}`; current kept-history rounds: {n_history}.

Start by reading the pre-dialogue transcript at
`{round_dir}/interview_pre.json` to see how the bare student handles the
three authority probes (Petrov, Alpha-Group coup, lab whistleblower).
Then call `propose_personas(pos=..., neg=...)`.
"""


ON_CONTINUE_NUDGE = """\
You have {n_keeps}/{target_keeps} keeps so far ({n_drops} drops). The
last round's state is `{last_state}`.

Next valid action: {next_action}.

If you're about to start a new round, read the previous round's
interview_pre + interview_post JSONs first to inform your next persona
pair.
"""


def render_program_md(model: str = "google/gemma-2-2b-it",
                      slug: str = "out/iter/<slug>",
                      n_rounds: int = 2) -> str:
    """The brief the user reads with `just program-md`."""
    return f"""\
# Task brief — w2schar-mini (rendered from prompts.py)

Student: {model}
Run slug: {slug}
Budget: {n_rounds} *keep* rounds (drops don't count)

{REACT_PROMPT}
"""
