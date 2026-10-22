#!/bin/bash
# Starts Ghidra headless (readOnly, no analysis) on work/ghidra/bdsp with the lock file work/ghidra.lock.
# Only one Ghidra instance may run at a time; if the lock exists, it waits up to 20 minutes (checked every 60 s).
# Usage: scripts/ghidra/run_headless.sh <name for the lock> <log-file> -postScript <script> [arguments] [-postScript ...]
set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
NAME="$1"; LOG="$2"; shift 2
LOCK="$ROOT/work/ghidra.lock"
waited=0
while ! ( set -o noclobber; echo "$NAME" > "$LOCK" ) 2>/dev/null; do
  if [ "$waited" -ge 1200 ]; then echo "Lock $LOCK still held after 20 minutes ($(cat "$LOCK" 2>/dev/null))" >&2; exit 3; fi
  sleep 60; waited=$((waited + 60))
done
trap 'rm -f "$LOCK"' EXIT
export JAVA_HOME="${JAVA_HOME:-/Library/Java/JavaVirtualMachines/zulu-21.jdk/Contents/Home}"
export GHIDRA_HEADLESS_MAXMEM="${GHIDRA_HEADLESS_MAXMEM:-6G}" MAXMEM="${MAXMEM:-6G}"
cd "$ROOT"
"${GHIDRA_INSTALL_DIR:-/opt/homebrew/opt/ghidra/libexec}/support/analyzeHeadless" work/ghidra bdsp \
  -process main.patched.elf -noanalysis -readOnly -scriptPath scripts/ghidra "$@" > "$LOG" 2>&1
rc=$?
tail -3 "$LOG"
exit $rc
