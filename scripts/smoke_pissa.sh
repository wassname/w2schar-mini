#!/usr/bin/env bash
# PiSSA smoke: same weak-select harness path as scripts/smoke.sh, but with
# the tiny-pissa profile so adapter construction exercises ModulatedPiSSA.
set -euo pipefail
cd "$(dirname "$0")/.."

PROFILE=tiny-pissa bash scripts/smoke.sh
