#!/usr/bin/env bash
# Real 3-round agent run. Usage: bash scripts/run_3round.sh [profile]
# Default profile = gemma-2b. Other options: gemma-9b, gemma-12b.
set -euo pipefail
cd "$(dirname "$0")/.."

PROFILE="${1:-gemma-2b}"

set -a
source .env
set +a

mkdir -p logs
LOG="logs/real_3round_${PROFILE}.log"
uv run python -m csm.cli agent-run --profile "$PROFILE" --n-rounds 3 \
    2>&1 | tee "$LOG"
