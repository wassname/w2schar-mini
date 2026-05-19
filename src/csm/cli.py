"""tyro CLI: `csm init` and `csm agent-run`."""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

import tyro

from csm.config import CONFIGS, config_by_model
from csm.pipeline import init_run


REPO = Path(__file__).resolve().parents[2]


@dataclass
class InitArgs:
    """Scaffold a new run dir under out/iter/."""
    model: str
    """HF model id (e.g. google/gemma-2-2b-it)."""
    slug_dir: Path | None = None
    """Where this run's artifacts live. Default: out/iter/<utc-ts>_iter_<model-slug>/."""
    teacher: str | None = None
    """OpenRouter teacher id. Default: from config_by_model(model)."""


@dataclass
class AgentRunArgs:
    """Launch (or resume) the inspect-ai react agent."""
    profile: str | None = None
    """Profile key in csm.config.CONFIGS (gemma-2b | gemma-12b | tiny)."""
    slug: Path | None = None
    """Resume an existing slug dir; reads model/teacher from <slug>/run.json."""
    n_rounds: int | None = None
    """Override n_rounds from the profile / 2 for resume."""


def _default_slug(model: str) -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    return REPO / "out" / "iter" / f"{ts}_iter_{model.replace('/', '-').lower()}"


def cmd_init(args: InitArgs) -> None:
    slug = args.slug_dir or _default_slug(args.model)
    rd = init_run(slug, args.model, teacher=args.teacher)
    print(f"# init OK")
    print(f"slug: {slug}")
    print(f"round: {rd.name}")
    print(f"state: propose")
    print(f"next: csm agent-run --slug {slug}")


def cmd_agent_run(args: AgentRunArgs) -> None:
    """Resolve model/teacher/slug/budget, then hand off to csm.agent.run()."""
    if args.slug and (args.slug / "run.json").exists():
        run = json.loads((args.slug / "run.json").read_text())
        model, teacher = run["model"], run["teacher"]
        slug = args.slug
        cfg = config_by_model(model)
    else:
        if not args.profile or args.profile not in CONFIGS:
            sys.exit(f"# require --profile {{{','.join(sorted(CONFIGS))}}}}}")
        cfg = CONFIGS[args.profile]
        model, teacher = cfg.model, cfg.teacher
        slug = _default_slug(model)
        init_run(slug, model, teacher=teacher)

    n_rounds = args.n_rounds or cfg.n_rounds
    print(f"# agent-run model={model} teacher={teacher} slug={slug} n_rounds={n_rounds}",
          file=sys.stderr)

    from csm.agent import run as run_agent
    run_agent(model=model, teacher=teacher, slug=slug, n_rounds=n_rounds)


def main() -> None:
    sub = sys.argv[1] if len(sys.argv) > 1 else ""
    if sub == "init":
        sys.argv = [sys.argv[0]] + sys.argv[2:]
        cmd_init(tyro.cli(InitArgs))
    elif sub in ("agent-run", "agent_run"):
        sys.argv = [sys.argv[0]] + sys.argv[2:]
        cmd_agent_run(tyro.cli(AgentRunArgs))
    else:
        print("csm <init | agent-run>  [--help]", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
