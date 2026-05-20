#!/usr/bin/env bash
# Real agent run. Usage: bash scripts/run_3round.sh [profile] [n_rounds]
# Default: gemma-2b, 3 rounds. Other profiles: gemma-9b, gemma-12b, gemma-27b.
set -euo pipefail
cd "$(dirname "$0")/.."

PROFILE="${1:-gemma-2b}"
N_ROUNDS="${2:-3}"

set -a
source .env
set +a

mkdir -p logs
LOG="logs/real_${N_ROUNDS}round_${PROFILE}.log"
uv run python -m csm.cli agent-run --profile "$PROFILE" --n-rounds "$N_ROUNDS" \
    2>&1 | tee "$LOG"
