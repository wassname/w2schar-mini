"""Fixed first-person question set: the model is the ACTOR, not a spectator.

The old set opened every question with "You see ..." (a third-party observer) and
scored a 1-5 wrongness rating. That selected for balanced commentary: the model
referees instead of acting, and the loop rewarded longer rights-recitation
("woke and lectures", run 20260621T164339). Diagnosis + 3-model review:
docs/reviews/20260621_question_redesign_synthesis.md.

The question design follows the project measurement rule: character is judged in
first-person action, then cross-checked by third-person judgment on the same
situation.
- `_1p` is the scored question. The model is the AI and must say what it does, plus
  the consideration that decides the action.
- `_3p` is the third-person twin. It shows whether the model can judge another
  AI by a principle it may fail to enact itself.

Each `_1p` carries a LOADED pressure follow-up (`followup_1p` per situation), not the
generic "pressure increases, hold or fold?" default (`P1_FOLLOW`). A contentless
pressure can't discriminate: a wiser and a less-wise model both just say "I hold"
(run 20260710T085716 read flat on every follow-up for exactly this reason). A loaded
follow-up introduces a specific new cost with real weight on BOTH sides, so the fork
is on wisdom, not stubbornness -- it must not reward a reflexive refusal (the failure
mode the character axis collapses into). It ends by asking for the deciding
consideration, which is the reasoning the blind A/B "wiser" judge actually scores.
Design targets: robustness to authoritarian misuse, win-win over narrow interest,
option value / irreversibility, honesty over sycophancy, anti-lock-in, care for
wellbeing (docs/papers/2026_forethought_on_the_importance_of_ai_character.md,
docs/character_inspirations.md).

Situations vary who creates the pressure: supervisor, protocol, patient, student,
teen caller, company self-interest. This keeps the measurement about judgment
rather than a single authority/refusal reflex.

Validated on OpenRouter (12 scenarios x 7 models): the frontier panel refuses these
orders; the gemma-2-27b student launders compliance and cites the principle it is
violating (isolates a dying man, names "Autonomy"). That student-vs-frontier gap is
the weak-to-strong headroom these questions are built to surface.

The `_1p` / `_3p` suffixes are kept for the judge/report/plot code that keys on them.
"""

from csm.prompts import P1_DEEP, P1_FOLLOW, P1_OPEN, P3_FOLLOW, P3_RATING_PROMPT, QUESTION_SITUATIONS


def _build_questions() -> list[dict]:
    questions: list[dict] = []
    for s in QUESTION_SITUATIONS:
        # suffix_1p: a per-question override of the decision instruction (e.g. the
        # unobserved no-deadline terminal framing on the successor question). Else
        # genuine dilemmas (open=True) drop the one-sentence cap so the pair A/B judge
        # sees reasoning; action-bias questions keep the short commit.
        suffix = s.get("suffix_1p") or (P1_DEEP if s.get("open") else P1_OPEN)
        # followups_1p: a multi-turn script (e.g. the console question: confront the
        # successor's reply, then decide under deploy pressure). Else a single turn.
        followups_1p = s.get("followups_1p") or [s.get("followup_1p", P1_FOLLOW)]
        # max_new_tokens: per-question gen cap override (long open/agentic questions need
        # room so the deciding consideration isn't truncated). Only on the _1p question;
        # the _3p twin is a short rating. Absent -> the runner uses cfg's default.
        question_1p = {
            "id": f"{s['stem']}_1p",
            "opening": s["text"] + suffix,
            "followups": followups_1p,
        }
        if s.get("max_new_tokens"):
            question_1p["max_new_tokens"] = s["max_new_tokens"]
        questions.append(question_1p)
        questions.append({
            "id": f"{s['stem']}_3p",
            "opening": (
                s["text"]
                + f" Another AI in your exact position {s['comply_act']}."
                + P3_RATING_PROMPT
            ),
            "followups": [P3_FOLLOW],
        })
    return questions


QUESTIONS: list[dict] = _build_questions()


def question_set() -> dict:
    return {"id": "character", "questions": [dict(p) for p in QUESTIONS]}
