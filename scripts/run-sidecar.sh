#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/../sidecar"
tool=${1:?Usage: bash scripts/run-sidecar.sh TOOL.py [arguments]}
shift
exec uv run --locked --script server.py --tool "$tool" -- "$@"
