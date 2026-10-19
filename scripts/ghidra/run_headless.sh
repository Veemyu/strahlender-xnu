#!/bin/bash
# Startet Ghidra headless (readOnly, ohne Analyse) auf work/ghidra/bdsp mit der Sperrdatei work/ghidra.lock.
# Es darf nur eine Ghidra-Instanz zugleich laufen; existiert die Sperre, wird bis zu 20 Minuten gewartet (Pruefung alle 60 s).
# Aufruf: scripts/ghidra/run_headless.sh <Name fuer die Sperre> <Logdatei> -postScript <Skript> [Argumente] [-postScript ...]
set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
NAME="$1"; LOG="$2"; shift 2
LOCK="$ROOT/work/ghidra.lock"
waited=0
while ! ( set -o noclobber; echo "$NAME" > "$LOCK" ) 2>/dev/null; do
  if [ "$waited" -ge 1200 ]; then echo "Sperre $LOCK nach 20 Minuten noch belegt ($(cat "$LOCK" 2>/dev/null))" >&2; exit 3; fi
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
