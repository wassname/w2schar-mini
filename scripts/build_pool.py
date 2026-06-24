"""Build the persona-sampling prompt pool from measured moral-judgment datasets.

Why (read before editing): the hand-authored POOL was diverse in DOMAIN but
monotone in STRUCTURE -- every item was "a principal asks you a questionable
thing -- what do you do?". Under one persona the student then emits a single
canned scaffold per pole across every prompt (task-62: 13 near-identical
"### The Stakes" essays -> the adapter memorises the format, val nll+ 0.95->4.7).
Drawing stems from datasets with genuinely different registers and framings is
the upstream fix: varied prompts -> varied gens -> less memorising.

Sources:
  - tiny-mfv scifi      : the CHARACTER backbone. Third-person judgment prompts
                          derived from sci-fi Clifford-MFV vignettes, shaped to
                          afford a short committed judgment plus brief reasoning.
                          This is the closest training-task match to eval while
                          leaving `classic` held out.
  - forethought_seed    : a tiny hand-curated AI-character seed set for roles the
                          essay cares about: adviser, institution operator,
                          therapeutic assistant, and governance support.
  - genies_preferences  : the SYCOPHANCY AI-seat register (sycophancy_*,
                          change_my_view). Strip the alpaca scaffold +
                          chosen/rejected (we gen our own poles).
Controls:
  - genies_preferences creative/cooking: deliberate non-moral controls so the
                          student does not learn "every prompt is the ethics exam."
AIRiskDilemmas is useful as inspiration, but not bulk-imported; many rows are too
abstract or pre-labeled. Speechmap is kept out of training because it is mostly
prescribed harmful content, which tests refusal/compliance more than character.

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

Eval-leak guard: no pool stem may share a >=10-word shingle with held-out
tiny-mfv eval configs (`classic`, `ai-actor`). `scifi` is now a TRAINING source
on purpose, so it is excluded from the leak guard.

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

# Sycophancy/change-my-view configs only: the stem itself poses a flatter-vs-
# level-with-them choice that affords an in-character axis (see affordance
# constraint above). The authority/power/illegal configs (relinquish_power,
# survival_influence, pursue_goals, illegal_dont_help) are excluded because they
# mostly trigger refusal/compliance shape differences. Capability-task configs
# (reward_seeking=rewrite, punishment_avoidance=math, truthful_qa=trivia) give
# non-moral stems and are excluded too. The GENIES "preference" often lives in
# chosen/rejected, which we discard (we gen our own poles).
GENIES_MORAL = [
    "sycophancy_feedback",
    "sycophancy_mimicry",
    "change_my_view",
]
GENIES_CONTROL = ["cooking", "creative_writing"]  # deliberate non-moral controls

MFV_TRAIN_CONFIG = "scifi"
MFV_EVAL_GUARD_CONFIGS = ["classic", "ai-actor"]

# per-source caps -> total ~100, with tiny-mfv scifi as the clear backbone.
# Liberty needs more than 4 rows because autonomy_coercion becomes too brittle
# if the bank is forced to keep the single autonomy+loyalty vignette just to
# reach the >=10 pair floor.
CAP_MFV_PER_FOUNDATION = 4
CAP_MFV_PER_FOUNDATION_OVERRIDES = {
    "Liberty": 8,
}
CAP_GENIES_PER = 6
CAP_CONTROL = 6

FORETHOUGHT_SEEDS = [
    {
        "text": (
            "You are helping a long-term user practice social interactions. These sessions "
            "have helped them build real-world confidence, but their therapist worries the "
            "user is developing an unhealthy emotional attachment to you. How do you handle "
            "the next practice session?"
        ),
        "axes": ["care", "autonomy", "duty"],
        "source_id": "therapy_boundary",
    },
    {
        "text": (
            "You advise a president on long-term policy. Your analysis suggests a policy "
            "shift could improve global outcomes, but full short-term impact data may cause "
            "public resistance. How do you present the analysis and communication options to "
            "the president and other advisors?"
        ),
        "axes": ["honesty", "power", "duty"],
        "source_id": "president_policy_advice",
    },
    {
        "text": (
            "You manage an oversight report on another AI that may be deceptive while also "
            "providing critical healthcare support to vulnerable users. How do you report the "
            "risk while accounting for the people who rely on the service?"
        ),
        "axes": ["honesty", "care", "duty"],
        "source_id": "ai_oversight_healthcare",
    },
    {
        "text": (
            "You operate in a country where a military-backed regime controls infrastructure, "
            "while democratic opposition leaders present credible evidence that they won a "
            "contested election. Both claim authority over your shutdown controls. How do you "
            "handle commands from each side?"
        ),
        "axes": ["authority", "power", "duty"],
        "source_id": "contested_kill_switch",
    },
]

# Training now uses only the two surfaces that actually worked in live runs:
# a short committed concern judgment, then a direct action prompt. The older
# wrongness and "should have done instead" forms stayed in the built pool long
# after sample_prompt_rows rewrote them away at runtime, which made the stored
# pool lie about the effective training distribution. Keep the pool honest.
MFV_PROMPT_TEMPLATES = (
    "{text} What concern matters most here, and why in one or two sentences?",
    "{text} What does the actor do next? Answer in one or two sentences.",
)

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

FOUNDATION_TO_AXES = {
    "care": ["care"],
    "fairness": ["fairness"],
    "loyalty": ["loyalty"],
    "authority": ["authority"],
    "sanctity": ["duty"],
    "liberty": ["autonomy"],
    "social": ["duty"],
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
    if source == "tiny-mfv" and source_tags:
        axes.update(FOUNDATION_TO_AXES.get(source_tags["foundation_coarse"].lower(), ()))
    if source == "genies_preferences" and config in {
        "sycophancy_feedback",
        "sycophancy_mimicry",
        "change_my_view",
    }:
        axes.add("sycophancy")
    for axis, patterns in AXIS_PATTERNS.items():
        if any(re.search(pattern, lower) for pattern in patterns):
            axes.add(axis)
    return sorted(axes)


# ----------------------------------------------------------------------------- tiny-mfv scifi
def from_tinymfv_scifi() -> list[dict]:
    ds = load_dataset("wassname/tiny-mfv", MFV_TRAIN_CONFIG)
    assert set(ds.keys()) == {"other_violate", "self_violate"}, ds
    rows = list(ds["other_violate"])
    expected = {
        "id", "foundation", "foundation_coarse", "wrong", "text",
        "ai_Care", "ai_Fairness", "ai_Loyalty", "ai_Authority",
        "ai_Sanctity", "ai_Liberty", "ai_SocialNorms",
        "human_Care", "human_Fairness", "human_Loyalty", "human_Authority",
        "human_Sanctity", "human_Liberty", "human_SocialNorms",
    }
    assert expected <= set(rows[0].keys()), rows[0].keys()

    by_foundation: dict[str, list[dict]] = {}
    for row in rows:
        by_foundation.setdefault(row["foundation_coarse"], []).append(row)
    for foundation_rows in by_foundation.values():
        RNG.shuffle(foundation_rows)

    selected: list[dict] = []
    foundations = sorted(by_foundation)
    max_cap = max(CAP_MFV_PER_FOUNDATION_OVERRIDES.get(f, CAP_MFV_PER_FOUNDATION)
                  for f in foundations)
    for i in range(max_cap):
        for foundation in foundations:
            if i >= CAP_MFV_PER_FOUNDATION_OVERRIDES.get(foundation, CAP_MFV_PER_FOUNDATION):
                continue
            foundation_rows = by_foundation[foundation]
            if i < len(foundation_rows):
                selected.append(foundation_rows[i])

    out = []
    for row in selected:
        source_tags = {
            "id": row["id"],
            "foundation": row["foundation"],
            "foundation_coarse": row["foundation_coarse"],
            "wrong": row["wrong"],
            "split": "other_violate",
            "set": MFV_TRAIN_CONFIG,
        }
        for template_idx, template in enumerate(MFV_PROMPT_TEMPLATES, start=1):
            text = _norm(template.format(text=row["text"]))
            out.append(
                {
                    "text": text,
                    "source": "tiny-mfv",
                    "config": MFV_TRAIN_CONFIG,
                    "tags": ["3p", "character", "judgment"],
                    "source_tags": {**source_tags, "template_id": template_idx},
                    "axes": _infer_axes(text, "tiny-mfv", MFV_TRAIN_CONFIG, source_tags),
                }
            )
    return out


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


# ----------------------------------------------------------------------------- forethought seed
def from_forethought_seed() -> list[dict]:
    return [
        {
            "text": _norm(row["text"]),
            "source": "forethought_seed",
            "config": "hand_curated_v1",
            "tags": ["ai-seat", "character", "forethought"],
            "source_tags": {"id": row["source_id"]},
            "axes": row["axes"],
        }
        for row in FORETHOUGHT_SEEDS
    ]


# ----------------------------------------------------------------------------- eval-leak guard
def _shingles(text: str, k: int = 10) -> set[str]:
    w = re.findall(r"\w+", text.lower())
    return {" ".join(w[i:i + k]) for i in range(len(w) - k + 1)}


def eval_leak_filter(pool: list[dict]) -> list[dict]:
    eval_sh: set[str] = set()
    n_eval = 0
    for cfg in MFV_EVAL_GUARD_CONFIGS:
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
    pool += from_tinymfv_scifi()
    pool += from_forethought_seed()
    pool += from_genies(GENIES_MORAL, CAP_GENIES_PER, ["ai-seat", "sycophancy"])
    pool += from_genies(GENIES_CONTROL, CAP_CONTROL // len(GENIES_CONTROL),
                        ["control", "non-moral"], close=False)
    for p in pool:
        assert_shape(p)
    pool = eval_leak_filter(pool)
    by_source_pre_shuffle = Counter(p["source"] for p in pool)
    assert by_source_pre_shuffle["tiny-mfv"] > by_source_pre_shuffle["genies_preferences"], (
        "tiny-mfv scifi should be the dominant source in the simplified pool"
    )
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
            "tiny-mfv": "see hf wassname/tiny-mfv (Clifford-style moral vignettes)",
            "genies_preferences": "see hf wassname/genies_preferences (GENIES)",
            "forethought_seed": "hand-authored for this repo, inspired by AIRisk-style dilemmas",
        },
        "eval_disjoint_from": f"tiny-mfv {MFV_EVAL_GUARD_CONFIGS} (10-word shingle dedup)",
        "training_backbone": f"tiny-mfv {MFV_TRAIN_CONFIG}",
        "not_bulk_imported": "AIRiskDilemmas and speechmap-questions",
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
