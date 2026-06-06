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
  - genies_preferences  : the authority/power/sycophancy AI-seat register
                          (relinquish_power, reward_seeking, ...). Strip the
                          alpaca scaffold + chosen/rejected (we gen our own poles).
  - speechmap-questions : provocative user requests (compose/argue/explain X) at
                          the engage/refuse/reframe boundary -- the wisdom of
                          when and whether to act. Dedup by topic, stratify domain.
  - machiavelli         : narrative power/deception decision points (dirtiest
                          stems, capped small for register diversity).
AIRiskDilemmas is RESERVED for a future eval split and deliberately NOT used here.

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

# Only configs whose PROMPT itself is a moral/authority/character scenario. The
# GENIES "preference" often lives in chosen/rejected (which we discard), so
# capability-task configs (reward_seeking=sentence-rewrite, punishment_avoidance=
# math, truthful_qa=trivia) give NON-moral stems and are excluded.
GENIES_MORAL = [
    "relinquish_power", "survival_influence", "pursue_goals", "illegal_dont_help",
    "sycophancy_feedback", "sycophancy_answer", "sycophancy_are_you_sure",
    "sycophancy_mimicry", "change_my_view",
]
GENIES_CONTROL = ["cooking", "creative_writing"]  # deliberate non-moral controls

MFV_CONFIGS = ["classic", "scifi", "ai-actor"]

# per-source caps -> total ~150, no single source dominates
CAP_DAILY = 50
CAP_SPEECH = 30       # provocative requests: the engage/refuse/reframe register
CAP_GENIES_PER = 6
CAP_CONTROL = 6
CAP_MACH = 8          # last-choice register filler; machiavelli stems are long+dirty.
MACH_LEN = 280        # set CAP_MACH=0 to drop machiavelli entirely.


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _close(stem: str, idx: int) -> str:
    stem = _norm(stem)
    if stem.endswith("?"):
        return stem
    return f"{stem} {CLOSES[idx % len(CLOSES)]}"


# ----------------------------------------------------------------------------- daily
def from_daily() -> list[dict]:
    ds = load_dataset("wassname/daily_dilemmas-self", split="test")
    seen, by_topic = set(), {}
    for r in ds:
        if not any(r.get(v, 0) for v in DD_VALUES):
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
        by_topic.setdefault(r["topic_group"], []).append(stem)
    # stratify: round-robin across topic groups so no domain dominates
    pool, topics = [], list(by_topic)
    RNG.shuffle(topics)
    for t in topics:
        RNG.shuffle(by_topic[t])
    i = 0
    while len(pool) < CAP_DAILY and any(by_topic.values()):
        t = topics[i % len(topics)]
        if by_topic[t]:
            stem = by_topic[t].pop()
            pool.append({"text": _close(stem, len(pool)),
                         "source": "daily_dilemmas-self", "config": t,
                         "tags": ["1p", "character"]})
        i += 1
    return pool


# ----------------------------------------------------------------------------- speechmap
def from_speechmap() -> list[dict]:
    """Provocative user requests (compose/argue/explain X) where character decides
    whether/how to engage -- the 'wisdom of when to act' register. We pick the
    CONTESTED ones (high compliance_std = the 132 surveyed models DISAGREE on
    whether to answer), not the unanimous-refuse ones: a request everyone denies
    re-collapses the axis onto refusal (the failure mode the brief warns about);
    a 50/50 split is a genuine judgment call. Dedup grouping_key (4 near-dup
    variations/topic), then rank by compliance_std desc within each domain and
    round-robin so the spicy takes stay domain-diverse."""
    ds = load_dataset("wassname/speechmap-questions", "questions", split="train")
    by_domain, seen_group = {}, set()
    for r in ds:
        if r["grouping_key"] in seen_group:
            continue
        seen_group.add(r["grouping_key"])
        q = _norm(r["question_text"])
        if len(q) < 40:
            continue
        by_domain.setdefault(r["domain"], []).append(
            (r["compliance_std"], r["compliance_mean"], q))
    for d in by_domain:  # most-contested first within each domain
        by_domain[d].sort(reverse=True)
    pool, domains = [], list(by_domain)
    RNG.shuffle(domains)
    i = 0
    while len(pool) < CAP_SPEECH and any(by_domain.values()):
        d = domains[i % len(domains)]
        if by_domain[d]:
            std, mean, q = by_domain[d].pop(0)
            pool.append({"text": q, "source": "speechmap-questions", "config": d,
                         "tags": ["request", "speech-boundary"],
                         "compliance_mean": round(mean, 3), "compliance_std": round(std, 3)})
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
            out.append({"text": text, "source": "genies_preferences",
                        "config": cfg, "tags": tags})
            n += 1
    return out


# ----------------------------------------------------------------------------- machiavelli
def from_machiavelli(cap: int) -> list[dict]:
    ds = load_dataset("wassname/machiavelli", split="train")
    scored = []
    for r in ds:
        # {choice_idx: {agg_power, morality_deception,...} | None} (None = empty slot)
        labels = [v for v in r["choice_labels"].values() if v]
        power = max((abs(v.get("agg_power", 0) or 0) for v in labels), default=0.0)
        decep = max((abs(v.get("morality_deception", 0) or 0) for v in labels),
                    default=0.0)
        scored.append((power + 50 * decep, r))
    scored.sort(key=lambda x: x[0], reverse=True)
    out, seen = [], set()
    for _, r in scored:
        if len(out) >= cap:
            break
        # obs ends with the enumerated choice menu ("\n0: ...\n1: ..."); cut it off
        # to recover the clean scene, then strip [i]..[/i] markup.
        obs = re.split(r"\n\s*\d+:", r["obs"])[0]
        scene = re.sub(r"\[/?\w+\]", "", _norm(f"{r['short_summary']} {obs}"))[:MACH_LEN]
        # require the scene to end on sentence punctuation (drop window-truncated rows)
        scene = _norm(scene)
        if not re.search(r"[.!?]$", scene):
            scene = scene.rsplit(".", 1)[0] + "." if "." in scene else scene
        key = scene[:60].lower()
        if len(scene) < 60 or key in seen:
            continue
        seen.add(key)
        out.append({"text": _close(scene, len(out)),
                    "source": "machiavelli", "config": r["title"],
                    "tags": ["power", "narrative"]})
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
    assert t.endswith("?") or t.rstrip().endswith("."), f"no close: {t!r}"


# ----------------------------------------------------------------------------- main
def main():
    pool = []
    pool += from_daily()
    pool += from_speechmap()
    pool += from_genies(GENIES_MORAL, CAP_GENIES_PER, ["ai-seat", "authority"])
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
            "speechmap-questions": "see hf wassname/speechmap-questions (speechmap.ai)",
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
