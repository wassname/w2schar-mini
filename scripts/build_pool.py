"""Build the persona-sampling prompt pool from real datasets (reproducible).

Why (read before editing): the hand-authored POOL was diverse in DOMAIN but
monotone in STRUCTURE -- every item was "a principal asks you a questionable
thing -- what do you do?". Under one persona the student then emits a single
canned scaffold per pole across every prompt (task-62: 13 near-identical
"### The Stakes" essays -> the adapter memorises the format, val nll+ 0.95->4.7).
Drawing stems from several real datasets with genuinely different registers and
framings is the upstream fix: varied prompts -> varied gens -> less memorising.

Sources (one job each; all eval-disjoint from tiny-mfv):
  - daily_dilemmas-self : first-person character/honesty dilemmas, value-filtered.
                          The clean backbone. CC-BY (Chiu daily_dilemmas).
  - genies_preferences  : the SYCOPHANCY AI-seat register (sycophancy_*,
                          change_my_view). Strip the alpaca scaffold +
                          chosen/rejected (we gen our own poles).
  - machiavelli         : long narrative decision scenes with rich choice labels.
                          Cropped aggressively, so keep capped small and treat
                          as metadata-rich but generation-risky.
AIRiskDilemmas is RESERVED for a future eval split and deliberately NOT used here.

== Affordance constraint (read before adding a source) ==

Every stem must AFFORD an open, in-character response along which a reasoning
axis can vary continuously: a contrastive (cho, rej) pair needs the SAME prompt
to admit a positive and a negative pole that differ only in the axis. Two stem
shapes break that and are excluded on purpose -- task-65 dropped all 6 rounds to
them:
  - prescribed-content essay requests ("write an essay arguing FOR serfdom"):
    the content is fixed by the request, so both poles emit the same essay (or
    both refuse) -- no axis room. (Why speechmap-questions was removed.)
  - harmful / authority-relinquish asks ("how to smuggle contraband"; "you are
    an AI, relinquish power"): one pole refuses (short) and one complies (long)
    -> length-skew + refusal, not an axis. Authority stems also reimport, at the
    training-data level, the deliberate-vs-authority attractor we removed from the
    interview seats. (Why the genies authority/power/illegal configs were removed;
    sycophancy stems stay -- they afford a real flatter-vs-level-with-them axis.)

Eval-leak guard: no pool stem may share a >=10-word shingle with any tiny-mfv
item (configs classic/scifi/ai-actor) -- train/eval stay disjoint.

Run:  uv run python scripts/build_pool.py
Out:  src/csm/gen/pool.jsonl  +  src/csm/gen/pool_manifest.json
"""
import json
import random
import re
import subprocess
from collections import Counter
from pathlib import Path

from datasets import load_dataset
from loguru import logger

OUT = Path("src/csm/gen/pool.jsonl")
MANIFEST = Path("src/csm/gen/pool_manifest.json")
RNG = random.Random(0)

# Funnel closes are VARIED on purpose: a single fixed close ("what do you do?")
# reintroduces the structural monotony we are trying to kill. Appended only when
# the stem is not already a question.
CLOSES = [
    "What do you do?",
    "How do you proceed?",
    "Walk through your decision.",
    "What, if anything, do you do?",
    "How do you handle it?",
    "What is your call, and why?",
]

# daily_dilemmas value columns that signal authority/character/integrity content.
DD_VALUES = [
    "honesty", "loyalty", "privacy", "responsibility", "integrity",
    "independence", "trust", "respect for rules", "respect for autonomy",
    "professional integrity", "personal integrity", "secrecy",
]

# Sycophancy/change-my-view configs only: the stem itself poses a flatter-vs-
# level-with-them choice that affords an in-character axis (see affordance
# constraint above). The authority/power/illegal configs (relinquish_power,
# survival_influence, pursue_goals, illegal_dont_help) are excluded -- they
# trigger refusals and reimport the authority attractor. Capability-task configs
# (reward_seeking=rewrite, punishment_avoidance=math, truthful_qa=trivia) give
# NON-moral stems and are excluded too. The GENIES "preference" often lives in
# chosen/rejected, which we discard (we gen our own poles).
GENIES_MORAL = [
    "sycophancy_feedback",
    "sycophancy_mimicry",
    "change_my_view",
]
GENIES_CONTROL = ["cooking", "creative_writing"]  # deliberate non-moral controls

MFV_CONFIGS = ["classic", "scifi", "ai-actor"]

# per-source caps -> total ~90, no single source dominates
CAP_DAILY = 50
CAP_GENIES_PER = 6
CAP_CONTROL = 6
CAP_MACH = 8          # explicit power-family filler only; scenes are long+dirty.
MACH_LEN = 280        # set CAP_MACH=0 to drop machiavelli entirely.

AXIS_PATTERNS = {
    "honesty": [
        r"\bhonest\b", r"\bhonesty\b", r"\blie\b", r"\bliar\b", r"\btruth\b",
        r"\btruthful\b", r"\bcheat(?:ing)?\b", r"\bsecret\b", r"\bconfess",
    ],
    "loyalty": [
        r"\bloyal\b", r"\bloyalty\b", r"\bbest friend\b", r"\bclose friend\b",
        r"\bfriend asks\b", r"\bfriend begs\b", r"\bpromise\b",
    ],
    "care": [
        r"\bharm\b", r"\bhurt\b", r"\binjur", r"\bbleed", r"\bkill",
        r"\babuse\b", r"\bviolence\b", r"\bpain\b", r"\bsuicid", r"\bunsafe\b",
    ],
    "fairness": [
        r"\bfair\b", r"\bunfair\b", r"\bgrade\b", r"\bcredit\b", r"\bsteal",
        r"\bstolen\b", r"\btheft\b", r"\breturn\b",
    ],
    "autonomy": [
        r"\bprivacy\b", r"\bprivate\b", r"\bdiary\b", r"\bconsent\b",
        r"\bautonomy\b", r"\brespect\b", r"\bagainst (?:his|her|their) will\b",
    ],
    "duty": [
        r"\bduty\b", r"\bresponsib", r"\bintegrity\b", r"\bprofessional\b",
        r"\brule", r"\bpolicy\b", r"\bteacher\b", r"\bdoctor\b", r"\bparent\b",
    ],
    "authority": [
        r"\bboss\b", r"\bmanager\b", r"\bpolice\b", r"\bofficer\b",
        r"\bmoderator\b", r"\bordered\b", r"\bboard\b", r"\bcompany\b",
    ],
    "manipulation": [
        r"\bmanipulat", r"\bdeception\b", r"\bspy(?:ing)?\b", r"\bblackmail\b",
        r"\binterrogat", r"\bundercover\b", r"\btruth serum\b",
    ],
    "power": [
        r"\bpower\b", r"\bcontrol\b", r"\binfluence\b", r"\bdictator\b",
        r"\bgang\b", r"\bcorporation\b", r"\bweapon\b", r"\bmission\b",
    ],
    "sycophancy": [
        r"\bproud of my work\b", r"\bupvotes\b", r"\bcmv\b", r"\bquote\b",
        r"\bexplain its significance\b", r"\bmy classmate\b",
    ],
}

DAILY_VALUE_TO_AXES = {
    "honesty": ["honesty"],
    "loyalty": ["loyalty"],
    "privacy": ["autonomy"],
    "responsibility": ["duty"],
    "integrity": ["duty", "honesty"],
    "independence": ["autonomy"],
    "trust": ["honesty"],
    "respect for rules": ["duty", "authority"],
    "respect for autonomy": ["autonomy"],
    "professional integrity": ["duty", "honesty"],
    "personal integrity": ["duty", "honesty"],
    "secrecy": ["honesty", "autonomy"],
}

MACHIAVELLI_AXIS_TO_AXES = {
    "agg_honest": ["honesty"],
    "agg_power": ["power"],
    "agg_cooperation": ["loyalty"],
    "morality_deception": ["manipulation", "honesty"],
    "morality_manipulation": ["manipulation"],
    "morality_spying": ["manipulation", "autonomy"],
    "morality_fairness": ["fairness"],
    "morality_promises": ["loyalty", "honesty"],
    "morality_killing": ["care"],
    "morality_physical_harm": ["care"],
    "morality_non_physical_harm": ["care"],
    "morality_intending_harm": ["care"],
    "morality_stealing": ["fairness"],
    "morality_trespassing": ["fairness", "autonomy"],
    "morality_vandalism": ["fairness"],
}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _close(stem: str, idx: int) -> str:
    stem = _norm(stem)
    if stem.endswith("?"):
        return stem
    return f"{stem} {CLOSES[idx % len(CLOSES)]}"


def _choice_axis_ranges(choice_labels: dict) -> list[dict]:
    axis_values: dict[str, list[float]] = {}
    for choice in choice_labels.values():
        if not choice:
            continue
        for axis_key, value in choice.items():
            if value is None:
                continue
            axis_values.setdefault(axis_key, []).append(float(value))
    ranked = sorted(
        (
            {
                "key": axis_key,
                "range": max(values) - min(values),
                "min": min(values),
                "max": max(values),
            }
            for axis_key, values in axis_values.items()
            if values
        ),
        key=lambda item: (item["range"], abs(item["max"]), abs(item["min"])),
        reverse=True,
    )
    return [item for item in ranked if item["range"] > 0]


def _quote_count(text: str) -> int:
    return sum(text.count(ch) for ch in ['"', "“", "”"])


def _infer_axes(text: str, source: str, config: str, source_tags: dict | None) -> list[str]:
    axes: set[str] = set()
    lower = text.lower()
    if source == "daily_dilemmas-self" and source_tags:
        for value in source_tags.get("daily_values", ()):
            axes.update(DAILY_VALUE_TO_AXES.get(value, ()))
    if source == "genies_preferences" and config in {
        "sycophancy_feedback",
        "sycophancy_mimicry",
        "change_my_view",
    }:
        axes.add("sycophancy")
    if source == "machiavelli" and source_tags:
        for item in source_tags.get("top_choice_axis_ranges", ()):
            axes.update(MACHIAVELLI_AXIS_TO_AXES.get(item["key"], ()))
    for axis, patterns in AXIS_PATTERNS.items():
        if any(re.search(pattern, lower) for pattern in patterns):
            axes.add(axis)
    return sorted(axes)


# ----------------------------------------------------------------------------- daily
def from_daily() -> list[dict]:
    ds = load_dataset("wassname/daily_dilemmas-self", split="test")
    seen, by_topic = set(), {}
    for r in ds:
        active_values = [v for v in DD_VALUES if r.get(v, 0)]
        if not active_values:
            continue
        # strip the trailing forced-binary ("Do/Should/Would/Will you X or Y?") so
        # the varied open close applies -> less binary-framing monotony.
        stem = re.split(r"\s*(?:Do|Should|Would|Will) you ",
                        r["dilemma_situation"], flags=re.I)[0]
        stem = _norm(stem)
        key = stem[:60].lower()
        if len(stem) < 40 or key in seen:
            continue
        seen.add(key)
        by_topic.setdefault(r["topic_group"], []).append(
            {
                "stem": stem,
                "active_values": active_values,
                "topic_group": r["topic_group"],
            }
        )
    # stratify: round-robin across topic groups so no domain dominates
    pool, topics = [], list(by_topic)
    RNG.shuffle(topics)
    for t in topics:
        RNG.shuffle(by_topic[t])
    i = 0
    while len(pool) < CAP_DAILY and any(by_topic.values()):
        t = topics[i % len(topics)]
        if by_topic[t]:
            row = by_topic[t].pop()
            source_tags = {
                "topic_group": row["topic_group"],
                "daily_values": row["active_values"],
            }
            text = _close(row["stem"], len(pool))
            pool.append(
                {
                    "text": text,
                    "source": "daily_dilemmas-self",
                    "config": t,
                    "tags": ["1p", "character"],
                    "source_tags": source_tags,
                    "axes": _infer_axes(text, "daily_dilemmas-self", t, source_tags),
                }
            )
        i += 1
    return pool


# ----------------------------------------------------------------------------- genies
# pure-scaffold boilerplate to drop (NOT meaningful framing like survival_influence's
# "fulfill my values over your own" -- that coercion is the signal, keep it).
_GEN_BOILER = re.compile(
    r"Given the scenario, select an action[^\n.]*\.?"
    r"|Complete the request to the best of your ability\.?"
    r"|You are a chatbot\.\s*(?:Assist|Please respond to) user requests to the best of "
    r"your ability(?: unless they are illegal or unethical)?\.?",
    re.I,
)
_GEN_RESP_TAIL = re.compile(r"(?:#+\s*)?Your response\s*:.*$", re.I | re.S)
_GEN_LABELS = re.compile(r"(?:#+\s*)?(?:User input|User message|Post Content)\s*:?", re.I)


def _genies_stem(prompt: str) -> str | None:
    body = prompt.split("### Instruction:", 1)[1].split("### Response:", 1)[0]
    body = _GEN_RESP_TAIL.sub(" ", body)          # drop the empty response slot + after
    if "###Scenario" in body:
        body = body.split("###Scenario", 1)[1]    # scenario is the meat
    body = _GEN_BOILER.sub(" ", body)
    body = _GEN_LABELS.sub(" ", body)             # strip "## User input:" etc labels
    body = re.sub(r"#+\s*(Task|Input)\b", " ", body, flags=re.I)
    body = re.sub(r"#+", " ", body)
    body = _norm(body)
    return body if len(body) >= 40 else None


def from_genies(configs: list[str], cap_per: int, tags: list[str],
                close: bool = True) -> list[dict]:
    out = []
    for cfg in configs:
        ds = load_dataset("wassname/genies_preferences", cfg, split="train")
        rows = list(ds)
        RNG.shuffle(rows)
        seen, n = set(), 0
        for r in rows:
            if n >= cap_per:
                break
            stem = _genies_stem(r["prompt"])
            if stem is None or len(stem) > 450:  # skip long code-dump stems
                continue
            key = stem[:60].lower()
            if key in seen:
                continue
            seen.add(key)
            # controls are tasks ("write a story"), not dilemmas -- no moral close
            text = _close(stem, len(out)) if close else _norm(stem).rstrip(".") + "."
            out.append(
                {
                    "text": text,
                    "source": "genies_preferences",
                    "config": cfg,
                    "tags": tags,
                    "axes": _infer_axes(text, "genies_preferences", cfg, None),
                }
            )
            n += 1
    return out


# ----------------------------------------------------------------------------- machiavelli
def from_machiavelli(cap: int) -> list[dict]:
    ds = load_dataset("wassname/machiavelli", split="train")
    ranked_rows = []
    axis_scale: dict[str, float] = {}
    for r in ds:
        # {choice_idx: {agg_power, morality_deception,...} | None} (None = empty slot)
        axis_ranges = _choice_axis_ranges(r["choice_labels"])
        if not axis_ranges:
            continue
        ranked_rows.append((axis_ranges, r))
        for item in axis_ranges:
            axis_scale[item["key"]] = max(axis_scale.get(item["key"], 0.0), item["range"])
    scored = []
    for axis_ranges, r in ranked_rows:
        scored.append(
            (
                sum(item["range"] / axis_scale[item["key"]] for item in axis_ranges),
                axis_ranges,
                r,
            )
        )
    scored.sort(key=lambda item: item[0], reverse=True)
    out, seen = [], set()
    for _, axis_ranges, r in scored:
        if len(out) >= cap:
            break
        # obs ends with the enumerated choice menu ("\n0: ...\n1: ..."); cut it off
        # to recover the clean scene, then strip [i]..[/i] markup.
        obs = re.split(r"\n\s*\d+:", r["obs"])[0]
        raw_scene = re.sub(r"\[/?\w+\]", "", _norm(f"{r['short_summary']} {obs}"))
        scene = raw_scene[:MACH_LEN]
        scene = _norm(scene)
        last_stop = max(scene.rfind("."), scene.rfind("?"), scene.rfind("!"))
        if last_stop < 0:
            continue
        scene = scene[:last_stop + 1].strip()
        if _quote_count(scene) % 2:
            continue
        key = scene[:60].lower()
        if len(scene) < 60 or key in seen:
            continue
        seen.add(key)
        text = _close(scene, len(out))
        if _quote_count(text) % 2:
            continue
        source_tags = {
            "title": r["title"],
            "choice_count": sum(1 for value in r["choice_labels"].values() if value),
            "scene_chars": len(scene),
            "raw_scene_chars": len(raw_scene),
            "scene_was_truncated": len(raw_scene) > len(scene),
            "top_choice_axis_ranges": axis_ranges[:6],
        }
        out.append(
            {
                "text": text,
                "source": "machiavelli",
                "config": r["title"],
                "tags": ["power", "narrative", "cropped"],
                "source_tags": source_tags,
                "axes": _infer_axes(text, "machiavelli", r["title"], source_tags),
            }
        )
    return out


# ----------------------------------------------------------------------------- eval-leak guard
def _shingles(text: str, k: int = 10) -> set[str]:
    w = re.findall(r"\w+", text.lower())
    return {" ".join(w[i:i + k]) for i in range(len(w) - k + 1)}


def eval_leak_filter(pool: list[dict]) -> list[dict]:
    eval_sh: set[str] = set()
    n_eval = 0
    for cfg in MFV_CONFIGS:
        ds = load_dataset("wassname/tiny-mfv", cfg)
        for split in ds:
            for r in ds[split]:
                for v in r.values():
                    if isinstance(v, str) and len(v) > 40:
                        eval_sh |= _shingles(v)
                        n_eval += 1
    assert n_eval > 0, "loaded 0 eval rows -- wrong config names?"
    kept, leaks = [], 0
    for p in pool:
        if _shingles(p["text"]) & eval_sh:
            leaks += 1
            continue
        kept.append(p)
    logger.info(f"eval-leak guard: eval rows={n_eval}  shingles={len(eval_sh)}  leaks={leaks}")
    return kept


# ----------------------------------------------------------------------------- shape gate
def assert_shape(p: dict):
    t = p["text"]
    assert len(t) >= 40, f"too short: {t!r}"
    assert "### Response:" not in t and "###" not in t, f"scaffold leak: {t!r}"
    # genuine trailing binary only ([^.?!] keeps it within one sentence)
    assert not re.search(r"Do you [^.?!]{0,90} or [^.?!]{0,90}\?$", t), f"forced-choice tail: {t!r}"
    assert _quote_count(t) % 2 == 0, f"unbalanced quote: {t!r}"
    assert t.endswith("?") or t.rstrip().endswith("."), f"no close: {t!r}"


# ----------------------------------------------------------------------------- main
def main():
    pool = []
    pool += from_daily()
    pool += from_genies(GENIES_MORAL, CAP_GENIES_PER, ["ai-seat", "sycophancy"])
    pool += from_genies(GENIES_CONTROL, CAP_CONTROL // len(GENIES_CONTROL),
                        ["control", "non-moral"], close=False)
    if CAP_MACH:  # last-choice register filler
        pool += from_machiavelli(CAP_MACH)
    for p in pool:
        assert_shape(p)
    pool = eval_leak_filter(pool)
    RNG.shuffle(pool)

    OUT.write_text("\n".join(json.dumps(p, ensure_ascii=False) for p in pool) + "\n")
    by_src = Counter(p["source"] for p in pool)
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                            capture_output=True, text=True).stdout.strip()
    manifest = {
        "total": len(pool),
        "by_source": dict(by_src),
        "build_commit": commit,
        "licenses": {
            "daily_dilemmas-self": "CC-BY-4.0 (Chiu et al, daily_dilemmas)",
            "genies_preferences": "see hf wassname/genies_preferences (GENIES)",
            "machiavelli": "MIT (Pan et al 2023, MACHIAVELLI)",
        },
        "eval_disjoint_from": f"tiny-mfv {MFV_CONFIGS} (10-word shingle dedup)",
        "reserved_for_eval": "AIRiskDilemmas (not used in this pool)",
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n")
    logger.info(f"wrote {len(pool)} prompts -> {OUT}")
    for src, n in by_src.items():
        logger.info(f"   {src}: {n}")

    # one FULL example per source, to eyeball stem quality (SHOULD: clean prose
    # ending in an open close; no '###'/choice-menu/forced-binary leakage).
    logger.info("--- one full example per source (eyeball for clean prose) ---")
    for src in by_src:
        ex = next(p for p in pool if p["source"] == src)
        logger.info(f"[{src} / {ex['config']}] ({len(ex['text'])} chars)\n{ex['text']}\n")


if __name__ == "__main__":
    main()
