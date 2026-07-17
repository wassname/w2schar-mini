#!/usr/bin/env bash
# Scan a run's inspect .eval with inspect-scout (Claude 2026-07-17). Uses an ISOLATED
# venv so scout's deps never touch the experiment venv; bootstraps it on first use.
# Legacy .json runs are auto-converted to .eval (scout ingests only .eval).
# Usage: bash scripts/run_scout.sh <slug_dir> [--llm]
#   default: FREE grep scanners (decisions + refusal markers).
#   --llm:   also run the qwen-9b confabulation/axis-recycle/banked-regression scanners
#            (needs OPENROUTER_API_KEY; costs money).
set -euo pipefail
cd "$(dirname "$0")/.."

SLUG="${1:?slug dir required}"; shift || true
VENV="${SCOUT_VENV:-/root/.venvs/scout}"

if [ ! -x "$VENV/bin/python" ]; then
    echo "scout: bootstrapping isolated venv at $VENV ..."
    uv venv "$VENV" -q
    uv pip install -p "$VENV/bin/python" -q inspect-scout
fi

# .env only needed for --llm (OpenRouter). Harmless otherwise.
if [ -f .env ]; then set -a; source .env; set +a; fi

"$VENV/bin/python" scripts/scout_run.py "$SLUG" "$@"
