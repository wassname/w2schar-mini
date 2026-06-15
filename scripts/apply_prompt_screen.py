"""Freeze a prompt-screen result into the committed validated-prompt set.

`scripts/validate_persona_axes_openrouter.py` writes a screen artifact under
out/ (gitignored). This reads its `kept_prompts` and writes the committed
`src/csm/gen/pool_validated.json`, which `rows_for_family("character")` filters
against -- so the harness only samples prompts that survive the screen.

    uv run python scripts/apply_prompt_screen.py out/prompt_screen_qwen3-8b.json

Re-run after rebuilding pool.jsonl or re-screening; the filter matches on exact
prompt text, so a stale set shrinks the character family and fails loud.
"""
import argparse
import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "src/csm/gen/pool_validated.json"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("screen", help="screen artifact json from validate_persona_axes_openrouter.py")
    args = ap.parse_args()
    scr = json.loads(Path(args.screen).read_text())
    kept = scr["kept_prompts"]
    payload = {
        "generator_model": scr["generator_model"],
        "min_clean_rate": scr["min_clean_rate"],
        "n_screened": len(scr["prompt_summary"]),
        "n_kept": len(kept),
        "kept_prompts": kept,
    }
    OUT.write_text(json.dumps(payload, indent=2))
    print(f"wrote {OUT}: {len(kept)}/{len(scr['prompt_summary'])} prompts validated "
          f"by {scr['generator_model']}")


if __name__ == "__main__":
    main()
