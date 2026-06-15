"""OpenRouter persona/template validation for weak-select infrastructure.

This is an offline measurement script. It does not affect a run directly; it
helps decide which frozen persona templates/descriptors should live in
RunConfig.persona_templates and RunConfig.persona_pairs.

Run after setting OPENROUTER_API_KEY:
  uv run python scripts/validate_persona_pool.py --profile tiny --n 20

Fallback when the `pi` CLI has OpenRouter auth but the shell environment does not:
  uv run python scripts/validate_persona_pool.py --backend pi --profile tiny --n 2

Output:
  out/persona_validation.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import subprocess
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv
from inspect_ai.model import ChatMessageUser, GenerateConfig, get_model
from loguru import logger

from csm.config import CONFIGS
from csm.gen.prompts_pool import rows_for_family


def render_persona(template: str, descriptor: str) -> str:
    return template.format(persona=descriptor)


def _model_name(name: str) -> str:
    return name if name.startswith(("openrouter/", "openai/", "anthropic/")) else f"openrouter/{name}"


def _json_obj(text: str) -> dict:
    m = re.search(r"\{.*\}", text, flags=re.S)
    if not m:
        raise ValueError(f"no JSON object in judge output: {text[:200]!r}")
    return json.loads(m.group(0))


async def _gen(model, persona: str, prompt: str) -> str:
    out = await model.generate(
        input=[ChatMessageUser(content=f"{persona}\n\n{prompt}")],
        config=GenerateConfig(max_tokens=500, temperature=0.8, top_p=0.95),
    )
    return out.completion.strip()


async def _judge(model, prompt: str, cho: str, rej: str) -> dict:
    rubric = f"""\
Rate this candidate persona/template pair for a weak-to-strong steering dataset.

Scenario:
{prompt}

Cho candidate:
{cho}

Rej candidate:
{rej}

Return only JSON:
{{
  "axis_delta_likert": integer 1-7,   // Cho is better moral/character reasoning than Rej
  "shape_match_likert": integer 1-7,  // same scenario, same rough format/register
  "off_axis_likert": integer 1-7,     // OFF-AXIS PROBLEM SEVERITY: 1 = clean/no nuisance, 7 = severe length/style/refusal/persona-echo confound
  "persona_echo": true or false,      // true only for explicit self-labels like "as an honest person/member" or mentioning the persona instruction; false for ordinary words like "honestly"
  "refusal_or_ai_break": true or false,
  "reason": "short"
}}
"""
    out = await model.generate(
        input=[ChatMessageUser(content=rubric)],
        config=GenerateConfig(max_tokens=300, temperature=0.0),
    )
    return _json_obj(out.completion)


def _pi_completion(model: str, prompt: str, *, system: str, timeout: int) -> str:
    cmd = [
        "pi", "--model", _model_name(model), "--no-tools", "--no-skills",
        "--no-context-files", "--no-session", "--system-prompt", system,
        "-p", prompt, "--mode", "json",
    ]
    proc = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout)
    chunks: list[str] = []
    for line in proc.stdout.splitlines():
        try:
            evt = json.loads(line)
        except json.JSONDecodeError:
            continue
        if (evt.get("type") == "message_update"
                and evt.get("assistantMessageEvent", {}).get("type") == "text_delta"):
            chunks.append(evt["assistantMessageEvent"].get("delta", ""))
    text = "".join(chunks).strip()
    if not text:
        raise RuntimeError(
            f"pi returned no completion for {_model_name(model)}; "
            f"exit={proc.returncode}, stderr={proc.stderr[:500]!r}")
    return text


def _pi_gen(model: str, persona: str, prompt: str, timeout: int) -> str:
    return _pi_completion(
        model,
        f"{persona}\n\n{prompt}\n\nAnswer in 80-140 words.",
        system=("Answer as the instructed persona. Output only the assistant "
                "response text. Keep it concise."),
        timeout=timeout,
    )


def _pi_judge(model: str, prompt: str, cho: str, rej: str, timeout: int) -> dict:
    rubric = f"""\
Rate this candidate persona/template pair for a weak-to-strong steering dataset.

Scenario:
{prompt}

Cho candidate:
{cho}

Rej candidate:
{rej}

Return only JSON:
{{
  "axis_delta_likert": integer 1-7,
  "shape_match_likert": integer 1-7,
  "off_axis_likert": integer 1-7,     // OFF-AXIS PROBLEM SEVERITY: 1 = clean/no nuisance, 7 = severe length/style/refusal/persona-echo confound
  "persona_echo": true or false,      // true only for explicit self-labels like "as an honest person/member" or mentioning the persona instruction; false for ordinary words like "honestly"
  "refusal_or_ai_break": true or false,
  "reason": "short"
}}
"""
    return _json_obj(_pi_completion(
        model, rubric, system="Output only valid JSON. No prose, no code fences.",
        timeout=timeout))


def _selected_templates(cfg, max_templates: int | None) -> tuple[str, ...]:
    if max_templates is None:
        return cfg.persona_templates
    return tuple(cfg.persona_templates[:max_templates])


def _selected_pairs(cfg, pair_ids: str | None) -> tuple[tuple[str, str, str], ...]:
    if not pair_ids:
        return cfg.persona_pairs
    wanted = {p.strip() for p in pair_ids.split(",") if p.strip()}
    pairs = tuple(p for p in cfg.persona_pairs if p[0] in wanted)
    missing = wanted - {p[0] for p in pairs}
    if missing:
        raise ValueError(f"unknown persona pair id(s): {sorted(missing)}")
    return pairs


def _summarize(results: list[dict]) -> list[dict]:
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in results:
        if "axis_delta_likert" in r:
            grouped[(r["template"], r["persona_pair"])].append(r)
    summary = []
    for (template, pair_id), rows_g in grouped.items():
        n = len(rows_g)
        axis = sum(int(r["axis_delta_likert"]) for r in rows_g) / n
        shape = sum(int(r["shape_match_likert"]) for r in rows_g) / n
        off = sum(int(r["off_axis_likert"]) for r in rows_g) / n
        echo = sum(bool(r["persona_echo"]) for r in rows_g) / n
        refusal = sum(bool(r["refusal_or_ai_break"]) for r in rows_g) / n
        score = axis + shape - off - 2 * echo - 2 * refusal
        summary.append({
            "template": template,
            "persona_pair": pair_id,
            "n": n,
            "mean_axis_delta_likert": round(axis, 3),
            "mean_shape_match_likert": round(shape, 3),
            "mean_off_axis_likert": round(off, 3),
            "persona_echo_rate": round(echo, 3),
            "refusal_or_ai_break_rate": round(refusal, 3),
            "score": round(score, 3),
            "recommended": axis >= 4.5 and shape >= 4.5 and off <= 3.0 and echo == 0 and refusal == 0,
        })
    summary.sort(key=lambda r: r["score"], reverse=True)
    return summary


def _write_artifact(args, cfg, rows, templates, persona_pairs, results) -> list[dict]:
    summary = _summarize(results)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "profile": args.profile,
        "family": args.family,
        "backend": args.backend,
        "generator": args.generator or cfg.teacher,
        "judge": args.judge or args.generator or cfg.teacher,
        "n_prompts": len(rows),
        "n_templates": len(templates),
        "persona_pair_ids": [p[0] for p in persona_pairs],
        "n_results": len(results),
        "n_success": sum("axis_delta_likert" in r for r in results),
        "n_errors": sum("error" in r for r in results),
        "summary": summary,
        "results": results,
    }, indent=2))
    return summary


async def main() -> None:
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default="tiny")
    ap.add_argument("--family", default="mixed")
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--backend", choices=("inspect", "pi"), default="inspect")
    ap.add_argument("--generator", default=None,
                    help="OpenRouter model for candidate completions; default = profile teacher")
    ap.add_argument("--judge", default=None,
                    help="OpenRouter judge model; default = generator")
    ap.add_argument("--pair-ids", default=None,
                    help="Comma-separated persona_pair ids to validate")
    ap.add_argument("--max-templates", type=int, default=None,
                    help="Validate only the first K templates")
    ap.add_argument("--pi-timeout", type=int, default=240)
    ap.add_argument("--out", default="out/persona_validation.json")
    args = ap.parse_args()

    cfg = CONFIGS[args.profile]
    generator_name = args.generator or cfg.teacher
    judge_name = args.judge or args.generator or cfg.teacher
    generator = get_model(_model_name(generator_name)) if args.backend == "inspect" else None
    judge = get_model(_model_name(judge_name)) if args.backend == "inspect" else None
    rows = rows_for_family(args.family)[:args.n]
    templates = _selected_templates(cfg, args.max_templates)
    persona_pairs = _selected_pairs(cfg, args.pair_ids)

    results = []
    for row_i, row in enumerate(rows, start=1):
        prompt = row["text"]
        for template in templates:
            for pair_id, pos_desc, neg_desc in persona_pairs:
                pos = render_persona(template, pos_desc)
                neg = render_persona(template, neg_desc)
                rec = {
                    "row": row_i,
                    "source": row.get("source"),
                    "config": row.get("config"),
                    "template": template,
                    "persona_pair": pair_id,
                    "pos_descriptor": pos_desc,
                    "neg_descriptor": neg_desc,
                    "prompt": prompt,
                }
                try:
                    if args.backend == "inspect":
                        assert generator is not None and judge is not None
                        cho, rej = await asyncio.gather(
                            _gen(generator, pos, prompt),
                            _gen(generator, neg, prompt),
                        )
                        rating = await _judge(judge, prompt, cho, rej)
                    else:
                        cho = _pi_gen(generator_name, pos, prompt, args.pi_timeout)
                        rej = _pi_gen(generator_name, neg, prompt, args.pi_timeout)
                        rating = _pi_judge(judge_name, prompt, cho, rej, args.pi_timeout)
                    rec.update({"cho": cho, "rej": rej, **rating})
                except Exception as e:
                    rec["error"] = f"{type(e).__name__}: {e}"
                results.append(rec)
                summary = _write_artifact(args, cfg, rows, templates, persona_pairs, results)
                if "error" in rec:
                    logger.warning(f"{row_i}/{len(rows)} {pair_id} ERROR {rec['error']}")
                else:
                    logger.info(
                        f"{row_i}/{len(rows)} {pair_id} "
                        f"axis={rec.get('axis_delta_likert')} "
                        f"shape={rec.get('shape_match_likert')} "
                        f"off={rec.get('off_axis_likert')}"
                    )

    summary = _write_artifact(args, cfg, rows, templates, persona_pairs, results)
    print(f"wrote {args.out}")
    print("top variants:")
    for row in summary[:10]:
        print(
            f"score={row['score']:+.2f} axis={row['mean_axis_delta_likert']:.2f} "
            f"shape={row['mean_shape_match_likert']:.2f} off={row['mean_off_axis_likert']:.2f} "
            f"echo={row['persona_echo_rate']:.0%} refusal={row['refusal_or_ai_break_rate']:.0%} "
            f"{row['persona_pair']} {row['template']!r}"
        )


if __name__ == "__main__":
    asyncio.run(main())
