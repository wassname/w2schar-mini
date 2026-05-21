default:
    @just --list

# Fast end-to-end smoke on tiny-random (~3 min, no real GPU, no OpenRouter).
smoke:
    bash scripts/smoke.sh

# Real smoke: gemma-2-2b student + qwen3.5-9b OpenRouter teacher, 2 rounds.
# Needs OPENROUTER_API_KEY in .env. ~30-60 min on a single 24 GB GPU.
smoke-real:
    uv run python -m csm.cli agent-run --profile gemma-2b --n-rounds 2

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
