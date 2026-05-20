#!/usr/bin/env bash
# Real 3-round agent run on gemma-2b + qwen3.5-9b OR teacher.
# Wrapper exists so `pueue add -- bash scripts/run_3round.sh` doesn't
# get its `&&` operators evaluated by pueue's parent shell.
set -euo pipefail
cd "$(dirname "$0")/.."

set -a
source .env
set +a

mkdir -p logs
uv run python -m csm.cli agent-run --profile gemma-2b --n-rounds 3 \
    2>&1 | tee logs/real_3round.log
