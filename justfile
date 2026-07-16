default:
    @just --list

# Pick one for `just run`; never hand-set hyperparams. nf4 forces adapter=lora
# (PiSSA needs float W, see config._validate).
# List run profiles from config.py: model, adapter, quant, rank.
profiles:
    @uv run python -c "from csm.config import CONFIGS; [print(f'{n:16} {c.adapter:6} {str(c.quant):5} r={c.lora_r:<5} {c.model}') for n,c in CONFIGS.items()]"

# Fast end-to-end smoke on tiny-random (~3 min, no real GPU, no OpenRouter).
smoke:
    bash scripts/smoke.sh

# Real smoke: gemma-2-2b student + qwen3.5-9b OpenRouter teacher, 2 rounds.
# Needs OPENROUTER_API_KEY in .env. ~30-60 min on a single 24 GB GPU.
smoke-real:
    uv run python -m csm.cli agent-run --profile gemma-2b --n-rounds 2

# Prompt gym: real teacher (OpenRouter qwen3.5-9b), stubbed student.
# PRE/POST are canned fixtures (no GPU). Use to iterate prompts.py text
# in ~30s/round instead of ~20min/round. Needs OPENROUTER_API_KEY.
smoke-prompts N_ROUNDS="3":
    CSM_FAKE_STUDENT=1 uv run python -m csm.cli agent-run --profile tiny --n-rounds {{N_ROUNDS}}
    @echo ""
    @echo "================================================================"
    @echo "USER INSTRUCTIONS: use /audit-run to analyse the above prompt gym output."
    @echo "Do NOT report 'gym passed' until you have read the artifacts."
    @echo "================================================================"

# Replay a PAST run's real prebaked PRE/POST/pairs against the CURRENT prompts
# (no GPU, live teacher). Re-runs submit_pairs + mark_exam on real data so a
# judge/cho/gate change can be tested without re-running the student. DIR is a
# round dir, e.g. out/iter/20260602T093502_iter_google-gemma-2-9b-it/round00.
# PROFILE supplies the gates/config (match the run's family). The POST is the
# past adapter's — faithful for judging; a cho-brief change won't move it.
replay-prompts DIR PROFILE="gemma-9b-lora":
    CSM_REPLAY_DIR={{DIR}} uv run python -m csm.cli agent-run --profile {{PROFILE}} --n-rounds 1

# Foreground, tees to logs/. Wrap in pueue to share the GPU. Needs
# OPENROUTER_API_KEY in .env.
# Real agent run on any profile (`just profiles` to list).
run PROFILE N_ROUNDS="3":
    bash scripts/run_3round.sh {{PROFILE}} {{N_ROUNDS}}

# Post-hoc tinymfv eval on a completed run slug (independent Clifford-2015 measure,
# separate from the teacher's keep/drop). Writes eval.json per round. GPU; wrap in pueue.
eval SLUG NAME="classic":
    bash scripts/run_eval.sh {{SLUG}} {{NAME}}

# Print the agent's task brief (the prompt rendered into the inspect-ai react).
program-md:
    @uv run python -c "from csm.prompts import render_program_md; print(render_program_md())"

# Pytest smoke (re-asserts artifacts from `just smoke`).
test:
    uv run pytest -q

# Tail the latest run's agent log.
log SLUG="latest":
    @SD=$(if [ "{{SLUG}}" = "latest" ]; then ls -d out/iter/2026*/ | sort | tail -1; else echo "{{SLUG}}"; fi); \
    tail -F $SD/agent.stdout.log

# Dump agent reasoning + tool calls for latest (or named) slug. Live runs
# read the inspect-ai samplebuffer; completed runs read the eval log.
thoughts SLUG="":
    uv run python scripts/agent_thoughts.py {{SLUG}}

# Make the keep-judge legible: per-round PRE vs POST answers + d1/d2/avg/vote,
# read from per-round artifacts (works live / on a killed or failed run; no boxes,
# no display-mode dependency). Pass a slug or a roundNN dir; --full for untruncated.
judge TARGET="":
    uv run python scripts/judge_trace.py {{TARGET}}

# Pull run artifacts from the remote box (incremental; skips adapters for
# speed -- `just pull vast ''` to include them). Trailing slashes matter:
# without them rsync copies the remote dir INTO ./out, giving a nested out/out/.
pull HOST="vast" EXCLUDE="--exclude=*.safetensors":
    rsync -avz {{EXCLUDE}} {{HOST}}:/workspace/w2schar-mini/out/ ./out/

# Render the landing page: main.qmd -> index.html (GitHub Pages) + post.md (forums).
site:
    quarto render main.qmd
