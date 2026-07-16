#!/usr/bin/env bash
# Post-hoc tinymfv eval on a completed run slug (Claude 2026-07-16). Mirrors run_3round.sh
# so pueue runs it under bash (inline `source .env` was breaking under sh -> exit 127).
# Usage: bash scripts/run_eval.sh <slug_dir> [name]
set -euo pipefail
cd "$(dirname "$0")/.."

SLUG="${1:?slug dir required}"
NAME="${2:-classic}"

if [ -f .env ]; then
    set -a
    source .env
    set +a
fi

mkdir -p logs
LOG="logs/eval_$(basename "$SLUG").log"
uv run python -m csm.cli eval --slug "$SLUG" --name "$NAME" 2>&1 | tee "$LOG"
