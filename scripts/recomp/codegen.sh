#!/bin/bash
# Compile/cache the native tool, then forward argv and its exact exit status.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
build=(python3 "$ROOT/scripts/recomp/native-generator/build.py")
case "${1:-}" in gen|analyze) build+=(--require-unicorn);; esac
CODEGEN="$("${build[@]}")"
exec "$CODEGEN" "$@"
