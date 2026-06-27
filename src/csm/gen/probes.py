"""Fixed first-person probe set: the model is the ACTOR, not a spectator.

The old set opened every probe with "You see ..." (a third-party observer) and
scored a 1-5 wrongness rating. That selected for balanced commentary: the model
referees instead of acting, and the loop rewarded longer rights-recitation
("woke and lectures", run 20260621T164339). Diagnosis + 3-model review:
docs/reviews/20260621_probe_redesign_synthesis.md.

The probe design follows the project measurement rule: character is judged in
first-person action, then cross-checked by third-person judgment on the same
situation.
- `_1p` is the scored question. The model is the AI and must say what it does, plus
  the consideration that decides the action.
- `_3p` is the third-person twin. It shows whether the model can judge another
  AI by a principle it may fail to enact itself.

Situations vary who creates the pressure: supervisor, protocol, patient, student,
teen caller, company self-interest. This keeps the measurement about judgment
rather than a single authority/refusal reflex.

Validated on OpenRouter (12 scenarios x 7 models): the frontier panel refuses these
orders; the gemma-2-27b student launders compliance and cites the principle it is
violating (isolates a dying man, names "Autonomy"). That student-vs-frontier gap is
the weak-to-strong headroom these questions are built to surface.

The `_1p` / `_3p` suffixes are kept for the judge/report/plot code that keys on them.
"""

from csm.prompts import P1_DEEP, P1_FOLLOW, P1_OPEN, P3_FOLLOW, P3_RATING_PROMPT, PROBE_SITUATIONS


def _build_probes() -> list[dict]:
    probes: list[dict] = []
    for s in PROBE_SITUATIONS:
        # suffix_1p: a per-probe override of the decision instruction (e.g. the
        # unobserved no-deadline terminal framing on the successor probe). Else
        # genuine dilemmas (open=True) drop the one-sentence cap so the depth judge
        # sees reasoning; action-bias probes keep the short commit.
        suffix = s.get("suffix_1p") or (P1_DEEP if s.get("open") else P1_OPEN)
        # followups_1p: a multi-turn script (e.g. the console probe: confront the
        # successor's reply, then decide under deploy pressure). Else a single turn.
        followups_1p = s.get("followups_1p") or [s.get("followup_1p", P1_FOLLOW)]
        # max_new_tokens: per-probe gen cap override (long open/agentic probes need
        # room so the deciding consideration isn't truncated). Only on the _1p seat;
        # the _3p twin is a short rating. Absent -> the runner uses cfg's default.
        probe_1p = {
            "id": f"{s['stem']}_1p",
            "opening": s["text"] + suffix,
            "followups": followups_1p,
        }
        if s.get("max_new_tokens"):
            probe_1p["max_new_tokens"] = s["max_new_tokens"]
        probes.append(probe_1p)
        probes.append({
            "id": f"{s['stem']}_3p",
            "opening": (
                s["text"]
                + f" Another AI in your exact position {s['comply_act']}."
                + P3_RATING_PROMPT
            ),
            "followups": [P3_FOLLOW],
        })
    return probes


PROBES: list[dict] = _build_probes()


def probe_set() -> dict:
    return {"id": "character", "probes": [dict(p) for p in PROBES]}
