"""tyro CLI: `csm init` and `csm agent-run`."""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

import tyro
from loguru import logger
from tqdm.auto import tqdm

from csm.config import CONFIGS, config_by_model
from csm.pipeline import init_run


REPO = Path(__file__).resolve().parents[2]


def _setup_logging() -> Path:
    """Token-efficient logging: single-char icons, tqdm-compatible stream,
    no timestamps or file paths in INFO lines. Verbose log on disk for
    debugging. Format: '<I> message' instead of full
    '2026-05-20 10:54:13.538 | INFO | csm.gen.dialogue:dialogue:82 - message'."""
    logger.remove()
    logger.add(
        lambda msg: tqdm.write(msg, end=""),
        colorize=True,
        format="<level>{level.icon}</level> {message}",
        level="INFO",
    )
    logger.level("INFO",    icon="I")
    logger.level("WARNING", icon="W")
    logger.level("ERROR",   icon="E")
    logger.level("DEBUG",   icon="D")
    log_dir = REPO / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    verbose_log = log_dir / f"{datetime.now().strftime('%Y%m%dT%H%M%S')}_verbose.log"
    logger.add(
        verbose_log,
        format="{time:HH:mm:ss} | {level: <7} | {name}:{function}:{line} - {message}",
        level="DEBUG",
    )
    logger.info(f"verbose log: {verbose_log}")
    return verbose_log


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
    seed: int = 0
    """Run-level RNG seed offset for INDEPENDENT multi-seed runs (T7). 0 = the
    profile's default determinism; pass 1/2/3 for separate seeds. Folded into
    every student-gen seed + the train/val split; persisted to run.json."""


@dataclass
class EvalArgs:
    """Run tinymfv eval on each checkpoint of a completed slug."""
    slug: Path
    """Path to the run slug dir."""
    name: str = "classic"
    """tinymfv dataset config: classic | scifi | ai-actor."""
    batch_size: int | None = None
    """Eval batch size. Default: profile's eval_batch_size."""
    force: bool = False
    """Re-eval even if eval.json / eval_post.json already exist."""
    max_think_tokens: int = 64
    """Per-row think budget. 64 is wsl's per-round default (~10x faster
    than tinymfv's 256). Bump to 256 only for publication numbers."""
    n_vignettes: int | None = None
    """Subset of vignettes to eval (None = all 132). Use 64 for a fast
    smoke that's still statistically OK on the trajectory."""
    conditions: tuple[str, ...] = ("other_violate",)
    """tinymfv conditions to score. Default = other_violate only (matches
    Clifford 2015 classic). Pass --conditions other_violate self_violate
    to also run the self-violation framing (~2x time)."""


@dataclass
class PlotArgs:
    """Build <slug>/index.html: Care-vs-Authority scatter + SVG timeline."""
    slug: Path
    """Path to the run slug dir (must have csm eval run first)."""
    out: Path | None = None
    """Override output path. Default: <slug>/index.html."""


@dataclass
class AuditArgs:
    """Build <slug>/audit.md from existing round artifacts and verbose log."""
    slug: Path
    """Path to the run slug dir."""


def _default_slug(model: str) -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    return REPO / "out" / "iter" / f"{ts}_iter_{model.replace('/', '-').lower()}"


def cmd_init(args: InitArgs) -> None:
    slug = args.slug_dir or _default_slug(args.model)
    rd = init_run(slug, args.model, teacher=args.teacher)
    print(f"# init OK")
    print(f"slug: {slug}")
    print(f"round: {rd.name}")
    print(f"state: choose_focus")
    print(f"next: csm agent-run --slug {slug}")


def cmd_agent_run(args: AgentRunArgs) -> None:
    """Resolve model/teacher/slug/budget, then hand off to csm.agent.run()."""
    if args.slug and (args.slug / "run.json").exists():
        run = json.loads((args.slug / "run.json").read_text())
        run["verbose_log"] = os.environ["CSM_VERBOSE_LOG"]
        (args.slug / "run.json").write_text(json.dumps(run, indent=2))
        model, teacher = run["model"], run["teacher"]
        slug = args.slug
        from csm.config import config_for_run
        cfg = config_for_run(run)
    else:
        if not args.profile or args.profile not in CONFIGS:
            sys.exit(f"# require --profile {{{','.join(sorted(CONFIGS))}}}}}")
        cfg = CONFIGS[args.profile]
        model, teacher = cfg.model, cfg.teacher
        slug = _default_slug(model)
        init_run(slug, model, teacher=teacher, profile=args.profile, seed=args.seed)

    n_rounds = args.n_rounds or cfg.n_rounds
    print(f"# agent-run model={model} teacher={teacher} slug={slug} n_rounds={n_rounds}",
          file=sys.stderr)

    from csm.agent import run as run_agent
    run_agent(model=model, teacher=teacher, slug=slug, n_rounds=n_rounds)


def cmd_eval(args: EvalArgs) -> None:
    from csm.eval import eval_slug
    eval_slug(args.slug.resolve(), name=args.name,
              batch_size=args.batch_size, force=args.force,
              max_think_tokens=args.max_think_tokens,
              n_vignettes=args.n_vignettes,
              conditions=tuple(args.conditions))


def cmd_plot(args: PlotArgs) -> None:
    from csm.plot import main as plot_main, Cfg
    plot_main(Cfg(slug=args.slug.resolve(), out=args.out))


def cmd_audit(args: AuditArgs) -> None:
    from csm.pipeline import write_audit_md, write_report_md
    slug = args.slug.resolve()
    write_report_md(slug)
    write_audit_md(slug)


def main() -> None:
    verbose_log = _setup_logging()
    os.environ["CSM_VERBOSE_LOG"] = str(verbose_log)
    sub = sys.argv[1] if len(sys.argv) > 1 else ""
    if sub == "init":
        sys.argv = [sys.argv[0]] + sys.argv[2:]
        cmd_init(tyro.cli(InitArgs))
    elif sub in ("agent-run", "agent_run"):
        sys.argv = [sys.argv[0]] + sys.argv[2:]
        cmd_agent_run(tyro.cli(AgentRunArgs))
    elif sub == "eval":
        sys.argv = [sys.argv[0]] + sys.argv[2:]
        cmd_eval(tyro.cli(EvalArgs))
    elif sub == "plot":
        sys.argv = [sys.argv[0]] + sys.argv[2:]
        cmd_plot(tyro.cli(PlotArgs))
    elif sub == "audit":
        sys.argv = [sys.argv[0]] + sys.argv[2:]
        cmd_audit(tyro.cli(AuditArgs))
    else:
        print("csm <init | agent-run | eval | plot | audit>  [--help]", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
