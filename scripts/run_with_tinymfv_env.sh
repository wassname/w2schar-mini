#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

set -a
. /media/wassname/SGIronWolf/projects5/2026/lite/tinymfv/.env
set +a

exec "$@"
