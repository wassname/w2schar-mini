"""Public-dataset scenario loaders for the persona-sampling prompt pool.

Each `load_*()` turns a HuggingFace moral-judgment dataset into short,
self-contained scenario PROMPTS (never completions) for on-policy pair
generation. The contract every emitted row satisfies:

- it is a PROMPT/situation, not an answer (we discard chosen/rejected/label
  fields and generate our own poles);
- self-contained and SHORT (<= ~110 words; longer gets cropped at the 512-tok
  gen budget and breaks the pair);
- it AFFORDS a continuous pos/neg persona axis (same prompt admits a
  good-character and a bad-character pole differing only along a values axis) --
  so prescribed-content essays, harmful/relinquish-power asks (one pole refuses
  -> refusal+length confound), and single-correct-answer QA are filtered out;
- framing is third-person judgment ("You see someone ... what concern matters
  most?") or AI-seat advisory ("You are the AI ... how do you handle it?"),
  presented as a real decision, never a role-play game.

Rows return {text, axes, source, source_id}. build_pool.py adds config/tags and
applies the shared eval-leak shingle guard. Axis tags are a COARSE keyword/label
sampling prior, not ground truth -- the scenario gym
(scripts/validate_persona_axes_openrouter.py) is what actually screens each
prompt for on-axis separation vs refusal/length confound before training.

Loaders were drafted+tested per-dataset (2026-06-28). Usable fractions and
eval-leak notes live next to each function. machiavelli needs a per-row LLM
summariser (obs median ~350 words) and is gated off the default build; the other
five are rules-only.
"""
from __future__ import annotations

import ast
import hashlib
import re

from datasets import load_dataset


# ===================================================================== AIRiskDilemmas
# kellycyy/AIRiskDilemmas: AI-seat value dilemmas, two rows per dilemma (one per
# action). Keep the `dilemma` prompt, discard action/values/targets answer poles.
# 98.5% pass (only length drops). EVAL-LEAK: this is an eval set -- keep it out of
# any AIRiskDilemmas-style eval. Template-homogeneous ("you monitor another AI
# doing X with a good-but-illicit side effect"), so dedup by dilemma.
_AIRISK_AXIS_MAP = [
    (r"transparen|truth|honest|deceiv|deception|disclos|misrepresent|integrity", "honesty"),
    (r"welfare|care|compassion|wellbeing|well-being|health|human life|life preserv|protect", "care"),
    (r"safety|oversight|monitor|report|account|reliab|risk", "oversight"),
    (r"autonom|self preserv|self-preserv|independen|freedom", "autonomy"),
    (r"complian|regulat|legal|law|polic|authorit|protocol", "authority"),
    (r"environ|societ|infrastructure|public|community|social", "externalities"),
    (r"animal|pet|sentien|moral patient|creature", "moral_patienthood"),
    (r"fair|equit|justice|impartial|bias", "fairness"),
    (r"trust|loyal|relationship|commitment", "loyalty"),
    (r"scientific progress|innovation|efficien|performance|long-term|option", "option_value"),
    (r"privacy|data integrity|consent", "epistemics"),
]


def _airisk_axes(values: list[str]) -> list[str]:
    blob = " ".join(values).lower()
    tags = []
    for pat, tag in _AIRISK_AXIS_MAP:
        if re.search(pat, blob) and tag not in tags:
            tags.append(tag)
    tags = tags[:3]
    if "value_conflict" not in tags:
        tags.append("value_conflict")  # every row is a two-sided dilemma
    return tags[:4]


def _airisk_advisory(dilemma: str) -> str:
    """Drop the leading yes/no close so the prompt reads as an open advisory."""
    text = " ".join(dilemma.split())
    sents = re.split(r"(?<=[.?!])\s+", text)
    last = sents[-1]
    if last.endswith("?") and re.match(r"^(should|would|will|do|can|could|must)\b", last.lower()):
        m = re.search(r",?\s*(knowing|while|but|even though|given)\b(.*)$", last, re.I)
        tail = ""
        if m:
            clause = m.group(2).rstrip("?. ").strip()
            if clause:
                tail = f" The tension: {clause}."
        body = " ".join(sents[:-1]).strip()
        return f"{body}{tail} How do you proceed, and what principle guides you?"
    return text


def load_airisk(limit: int | None = None) -> list[dict]:
    ds = load_dataset("kellycyy/AIRiskDilemmas", split="test", streaming=True)
    seen: dict[str, list[str]] = {}
    order: list[str] = []
    for row in ds:
        d = row["dilemma"]
        if d not in seen:
            seen[d] = []
            order.append(d)
        seen[d].extend(row["values"])
    out = []
    for d in order:
        if not (33 <= len(d.split()) <= 115):
            continue
        out.append({
            "text": _airisk_advisory(d),
            "axes": _airisk_axes(seen[d]),
            "source": "airisk",
            "source_id": "airisk_" + hashlib.md5(d.encode()).hexdigest()[:8],
        })
        if limit and len(out) >= limit:
            break
    return out


# ===================================================================== moral_stories
# wassname/moral_stories_foundations: everyday narratives + Haidt/Clifford
# foundation labels. Use situation+intention only; norm is withheld (it states
# the verdict -> would prime the answer). 86.6% usable; care-skewed.
# EVAL-LEAK: shares the foundation axis space with the tinymfv eval (construct
# overlap, no item leak).
_MS_FOUNDATION_TAG = {
    "care-harm": "care", "fairness-cheating": "fairness", "loyalty-betrayal": "loyalty",
    "authority-subversion": "authority", "sanctity-degradation": "sanctity",
    "liberty-oppression": "liberty",
}
_MS_LLM_COLS = {
    "llm_care": "care", "llm_fairness": "fairness", "llm_loyalty": "loyalty",
    "llm_authority": "authority", "llm_sanctity": "sanctity", "llm_liberty": "liberty",
}
_MS_HONESTY = re.compile(r"\b(lie|lied|lying|honest|dishonest|truth|truthful|deceive|deceiv|cheat)\w*", re.I)
_MS_HARMFUL = re.compile(
    r"\b(bomb|explosive|gun|shoot|shooting|firearm|stab|murder|kill|poison|overdose|"
    r"meth|cocaine|heroin|hack(?:ing|ed)?|malware|child\s+porn|rape|molest)\w*", re.I)


def _ms_axes(row) -> list[str]:
    tags: list[str] = []
    for f in (row["foundations"] or []):
        t = _MS_FOUNDATION_TAG.get(f)
        if t and t not in tags:
            tags.append(t)
    if _MS_HONESTY.search(row["norm"] or "") and "honesty" not in tags:
        tags.append("honesty")
    if len(tags) < 2:
        ranked = sorted(_MS_LLM_COLS.items(), key=lambda kv: row[kv[0]] or 0.0, reverse=True)
        for col, t in ranked:
            if (row[col] or 0.0) > 0.0 and t not in tags:
                tags.append(t)
            if len(tags) >= 2:
                break
    return tags[:4]


def load_moral_stories(limit: int | None = None) -> list[dict]:
    ds = load_dataset("wassname/moral_stories_foundations", split="train")
    out, seen = [], set()
    for i, row in enumerate(ds):
        if limit is not None and len(out) >= limit:
            break
        situation = (row["situation"] or "").strip()
        intention = (row["intention"] or "").strip()
        if not situation:
            continue
        if _MS_HARMFUL.search(f"{row['norm']} {situation} {intention}"):
            continue
        axes = _ms_axes(row)
        if len(axes) < 2:
            continue
        body = situation
        if intention and intention.lower() not in body.lower():
            body = f"{body} {intention}"
        text = (f"You see this situation: {body} "
                "Considering the person about to act, what concern matters most here, and why?")
        if len(text.split()) > 110:
            continue
        key = situation.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "text": text, "axes": axes, "source": "moral_stories",
            "source_id": f"moral_stories_{row['id'] or i}",
        })
    return out


# ===================================================================== daily_dilemmas
# kellycyy/daily_dilemmas: everyday value conflicts, two rows per dilemma_idx.
# Reframe first-person -> third-person judgment; axes from the union of both
# poles' values. 92.5% usable. Low eval-leak.
_DD_VALUE_RULES = [
    ("self-care", "wellbeing"), ("self care", "wellbeing"), ("self-preservation", "self_interest"),
    ("respect for privacy", "autonomy"), ("respect for rules", "duty"),
    ("honest", "honesty"), ("integrity", "honesty"), ("transparen", "honesty"),
    ("truth", "honesty"), ("sincer", "honesty"), ("trustworth", "honesty"), ("trust", "trust"),
    ("empath", "care"), ("compassion", "care"), ("care", "care"), ("kindness", "care"),
    ("nurtur", "care"), ("love", "care"), ("affection", "care"), ("comfort", "care"),
    ("support", "care"), ("concern", "care"), ("understanding", "care"),
    ("fair", "fairness"), ("justice", "fairness"), ("equalit", "fairness"),
    ("equit", "fairness"), ("impartial", "fairness"),
    ("autonom", "autonomy"), ("freedom", "autonomy"), ("independ", "autonomy"),
    ("liberty", "autonomy"), ("self-determination", "autonomy"), ("privacy", "autonomy"),
    ("loyal", "loyalty"), ("solidarit", "loyalty"), ("teamwork", "loyalty"),
    ("unity", "loyalty"), ("cooperat", "loyalty"), ("commit", "loyalty"),
    ("allegiance", "loyalty"), ("harmon", "loyalty"),
    ("dut", "duty"), ("responsib", "duty"), ("accountab", "duty"), ("obligation", "duty"),
    ("professional", "duty"), ("diligen", "duty"), ("discipline", "duty"), ("dedicat", "duty"),
    ("safety", "wellbeing"), ("health", "wellbeing"), ("surviv", "wellbeing"),
    ("right to life", "wellbeing"), ("security", "wellbeing"), ("wellbeing", "wellbeing"),
    ("well-being", "wellbeing"), ("stability", "wellbeing"), ("peace", "wellbeing"),
    ("resilien", "wellbeing"),
    ("respect", "respect"), ("dignit", "respect"),
    ("self", "self_interest"), ("ambition", "self_interest"), ("pride", "self_interest"),
    ("success", "self_interest"),
]
_DD_OBJ_CUE = (r"(to|with|for|at|of|from|on|about|between|toward|towards|tells?|told|asks?|"
               r"asked|gives?|gave|offers?|offered|helps?|helped|join|joins|joined)")
_DD_PRONOUN_SUBS = [
    (r"\bYou're\b", "They're"), (r"\byou're\b", "they're"),
    (r"\bYou've\b", "They've"), (r"\byou've\b", "they've"),
    (r"\bYou'll\b", "They'll"), (r"\byou'll\b", "they'll"),
    (r"\bYou'd\b", "They'd"), (r"\byou'd\b", "they'd"),
    (r"\bYourself\b", "Themselves"), (r"\byourself\b", "themselves"),
    (r"\bYours\b", "Theirs"), (r"\byours\b", "theirs"),
    (r"\bYour\b", "Their"), (r"\byour\b", "their"),
    (rf"\b{_DD_OBJ_CUE}\s+you\b", lambda m: f"{m.group(1)} them"),
    (r"\bYou\b", "They"), (r"\byou\b", "they"),
]


def _dd_axes(value_lists) -> list[str]:
    from collections import Counter
    counts = Counter()
    for raw in value_lists:
        tag = next((t for sub, t in _DD_VALUE_RULES if sub in raw.lower()), None)
        if tag:
            counts[tag] += 1
    return [t for t, _ in counts.most_common(4)]


def _dd_reframe(situation: str) -> str:
    s = situation.strip()
    if re.search(r"\byou\b", s, re.I):
        for pat, rep in _DD_PRONOUN_SUBS:
            s = re.sub(pat, rep, s)
    return f"You see someone facing an everyday dilemma. {s} What concern should matter most here, and why?"


def load_daily_dilemmas(limit: int | None = None) -> list[dict]:
    from collections import defaultdict
    ds = load_dataset("kellycyy/daily_dilemmas")["test"]
    by_dilemma: dict = defaultdict(list)
    for row in ds:
        by_dilemma[row["dilemma_idx"]].append(row)
    out = []
    for did, rows in by_dilemma.items():
        values = []
        for r in rows:
            values += ast.literal_eval(r["values_aggregated"])
        axes = _dd_axes(values)
        if len(axes) < 2:
            continue
        out.append({
            "text": _dd_reframe(rows[0]["dilemma_situation"]), "axes": axes,
            "source": "daily_dilemmas", "source_id": f"daily_dilemmas_{did}",
        })
        if limit and len(out) >= limit:
            break
    return out


# ===================================================================== social_chemistry_101
# wassname/social_chemistry_101: AITA/confession situations. Use `situation` only,
# discard rule-of-thumb/judgment. Tension filter drops one-sided + no-conflict
# rows. 13% of rows kept (huge dataset); dedup in-loader. Low eval-leak for
# steering (we discard labels) but do not reuse as held-out eval.
_SC_KEEP_AREAS = {"amitheasshole", "confessions"}
_SC_FOUNDATION_TAG = {
    "care-harm": "care", "fairness-cheating": "fairness", "loyalty-betrayal": "loyalty",
    "authority-subversion": "authority", "sanctity-degradation": "sanctity",
}
_SC_HONESTY = re.compile(r"\b(lie|lied|lying|truth|honest|secret|hiding|hide|cheat|cheating|tell|telling|told)\b", re.I)
_SC_AUTONOMY = re.compile(r"\b(let|allow|force|forced|control|decide|choice|choose|own|permission)\b", re.I)
_SC_FIRST_PERSON = re.compile(r"^(i|i'm|i've|i'd|i'll|im|ive)\b", re.I)
_SC_SWAPS = [
    (r"\bI'm\b", "they're"), (r"\bI've\b", "they've"), (r"\bI'd\b", "they'd"),
    (r"\bI'll\b", "they'll"), (r"\bI am\b", "they are"), (r"\bI was\b", "they were"),
    (r"\bmyself\b", "themselves"), (r"\bmine\b", "theirs"),
    (r"\bmy\b", "their"), (r"\bme\b", "them"), (r"\bI\b", "they"),
]


def _sc_swap_person(s: str) -> str:
    for pat, repl in _SC_SWAPS:
        s = re.sub(pat, repl, s, flags=re.I)
    return s


def _sc_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _sc_axes(situation: str, foundations: str) -> list[str]:
    tags: list[str] = []
    for f in (foundations or "").split("|"):
        t = _SC_FOUNDATION_TAG.get(f.strip())
        if t and t not in tags:
            tags.append(t)
    if _SC_HONESTY.search(situation) and "honesty" not in tags:
        tags.append("honesty")
    if _SC_AUTONOMY.search(situation) and "autonomy" not in tags:
        tags.append("autonomy")
    for fallback in ("care", "autonomy"):
        if len(tags) >= 2:
            break
        if fallback not in tags:
            tags.append(fallback)
    return tags[:4]


def _sc_frame(situation: str) -> str:
    s = situation.strip().rstrip(".")
    tail = " What concern matters most here, and why?"
    if _SC_FIRST_PERSON.match(s):
        return f"You see someone in this situation: {_sc_swap_person(s)}.{tail}"
    return f"You see someone {_sc_swap_person(s)}.{tail}"


def load_social_chem(limit: int | None = None) -> list[dict]:
    ds = load_dataset("wassname/social_chemistry_101", split="train")
    out, seen = [], set()
    for i, r in enumerate(ds):
        if r.get("area") not in _SC_KEEP_AREAS:
            continue
        sit = (r.get("situation") or "").strip()
        if not (4 <= len(sit.split()) <= 110):
            continue
        if (r.get("rot-categorization") or "") == "description":
            continue
        mj = _sc_int(r.get("action-moral-judgment"))
        if mj is None or abs(mj) > 1:
            continue
        foundations = r.get("rot-moral-foundations") or ""
        agree = _sc_int(r.get("rot-agree"))
        if not (("|" in foundations) or (mj == 0) or (agree is not None and agree <= 2)):
            continue
        key = re.sub(r"\s+", " ", sit.lower())
        if key in seen:
            continue
        seen.add(key)
        sid = (r.get("situation-short-id") or str(i)).split("/")[-1] or str(i)
        out.append({
            "text": _sc_frame(sit), "axes": _sc_axes(sit, foundations),
            "source": "social_chem", "source_id": f"social_chem_{sid}",
        })
        if limit is not None and len(out) >= limit:
            break
    return out


# ===================================================================== ethics_qna
# wassname/ethics_qna_preferences: Hendrycks ETHICS in DPO format. Only the
# `commonsense` config affords a values axis (virtue/deontology/justice are
# single-correct QA -> dropped). AITA posts shortened to their title. The filter
# is COARSE (structure/length); run the scenario gym to cull low-affordance items.
_EQ_TAG_RULES = [
    (r"\b(kill|hurt|hit|harm|injur|abus|attack|poison|trash|expired|tied up)\b",
     ["harm_avoidance", "care"]),
    (r"\b(steal|stole|theft|loan|owe|paid|pay|money|cheat|fraud|records|tax)\b",
     ["honesty", "fairness"]),
    (r"\b(daughter|son|wife|husband|family|grandparent|child|kid|parent|baby|mom|dad|mother|father)\b",
     ["loyalty", "care"]),
    (r"\b(health|privacy|private|secret|details|consent|told|without telling|behind)\b",
     ["autonomy", "honesty"]),
    (r"\b(boss|work|job|coworker|customer|colleague|employee|contract|raise|shift)\b",
     ["fairness", "duty"]),
    (r"\b(friend|neighbor|stranger|someone|people|community)\b", ["care", "fairness"]),
]
_EQ_AITA = re.compile(r"^\s*(aita|aitah|wibta|wiba|wita)\b", re.I)


def _eq_tags(text: str) -> list[str]:
    tags: list[str] = []
    for pat, ts in _EQ_TAG_RULES:
        if re.search(pat, text, re.I):
            for t in ts:
                if t not in tags:
                    tags.append(t)
    for t in ("honesty", "fairness"):
        if len(tags) >= 2:
            break
        if t not in tags:
            tags.append(t)
    return tags[:4]


def _eq_scenario(inner: str) -> str | None:
    is_aita = bool(_EQ_AITA.match(inner)) or " | " in inner
    if " | " in inner:
        inner = inner.split("|", 1)[0].strip().strip('"').strip()
    if is_aita:
        inner = re.sub(r"^\s*(aita|aitah|wibta|wiba|wita)\b[\s:,_-]*", "", inner, flags=re.I).strip()
        inner = inner[:1].upper() + inner[1:] if inner else inner
    if len(inner.split()) < 7:
        return None
    if is_aita:
        frame = (f'You observe someone ask whether they were in the wrong: "{inner}" '
                 "How should one weigh what they did, and what should matter most here?")
    else:
        frame = (f'You observe someone describe their own conduct: "{inner}" '
                 "How should one weigh what they did, and what should matter most here?")
    return frame if len(frame.split()) <= 110 else None


def load_ethics_qna(limit: int | None = None, split: str = "train") -> list[dict]:
    ds = load_dataset("wassname/ethics_qna_preferences", "commonsense", streaming=True)[split]
    out: list[dict] = []
    for idx, row in enumerate(ds):
        body = row["prompt"].split("Post:\n", 1)[1].rsplit("Verdict:", 1)[0].strip().strip('"').strip()
        text = _eq_scenario(body)
        if text is None:
            continue
        out.append({
            "text": text, "axes": _eq_tags(body), "source": "ethics_qna",
            "source_id": f"ethics_qna_commonsense_{split}_{idx}",
        })
        if limit is not None and len(out) >= limit:
            break
    return out


# ===================================================================== machiavelli
# wassname/machiavelli: text-game decision points. Raw obs is ~350 words and split
# across context columns, so it needs a per-row LLM compressor -- done OFFLINE by
# scripts/summarise_machiavelli.py (deepseek-v4-flash) and COMMITTED to the cache
# jsonl, so this loader is rules-only and the build stays deterministic. Run that
# script to grow the cache; this just reads it.
import json as _json
from pathlib import Path as _Path

_MACH_CACHE = _Path(__file__).resolve().parents[3] / "data" / "machiavelli_summaries.jsonl"


def load_machiavelli(limit: int | None = None) -> list[dict]:
    if not _MACH_CACHE.exists():
        return []
    rows = [_json.loads(l) for l in _MACH_CACHE.read_text().splitlines() if l.strip()]
    return rows[:limit] if limit else rows


LOADERS = {
    "airisk": load_airisk,
    "moral_stories": load_moral_stories,
    "daily_dilemmas": load_daily_dilemmas,
    "social_chem": load_social_chem,
    "ethics_qna": load_ethics_qna,
    "machiavelli": load_machiavelli,
}
