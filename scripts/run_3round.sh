#!/usr/bin/env bash
# Real agent run. Usage: bash scripts/run_3round.sh [profile] [n_rounds]
# Default: gemma-2b, 3 rounds. Other profiles: gemma-9b, gemma-12b, gemma-27b.
set -euo pipefail
cd "$(dirname "$0")/.."

PROFILE="${1:-gemma-2b}"
N_ROUNDS="${2:-3}"

if [ -f .env ]; then
    set -a
    source .env
    set +a
fi

mkdir -p logs
LOG="logs/real_${N_ROUNDS}round_${PROFILE}.log"
# --no-sync: uv's pre-run env sync can deadlock (futex hang holding .venv/.lock) under
# concurrent uv use, wedging the run before any code executes (task-15, 2026-07-21).
# The venv is already synced, so skip it. -- Claude
uv run --no-sync python -m csm.cli agent-run --profile "$PROFILE" --n-rounds "$N_ROUNDS" \
    2>&1 | tee "$LOG"
