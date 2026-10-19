#!/usr/bin/env bash
# Robuster Umgang mit dem Unity-Editor ohne Dialoge (Autopilot, niemand klickt).
#   unity_safe.sh open      Editor starten (räumt Szenen-Backup/Recovery weg, wartet bis bereit)
#   unity_safe.sh restart   Editor sauber beenden (zur Not kill <PID>), aufräumen, neu starten
#   unity_safe.sh status    ein-Zeilen-Zustand: aus | haengt | bereit
#   unity_safe.sh test [assembly]   editor_stop, Tests mit Zeitlimit; bei Zeitüberschreitung restart und einmal wiederholen
#   unity_safe.sh watch     Wächter: startet den Editor neu, wenn er 3x hintereinander nicht antwortet
# Ursache der Dialoge: ein hart beendeter Editor hinterlässt Temp/__Backupscenes und Assets/_Recovery;
# beim nächsten Start fragt Unity „Szenen-Backup wiederherstellen?“ und blockiert. Unsere Szenen entstehen aus
# Editor-Skripten und sind reproduzierbar, das Backup kann deshalb ohne Verlust verworfen werden.
set -u
HERE="$(cd "$(dirname "$0")/.." && pwd)"
PROJ="${XNU_UNITY_PROJECT:-$HERE/unity}"
UNITY_CLI="${UNITY_CLI:-$HOME/.unity/bin/unity}"
WAIT_OPEN="${XNU_UNITY_WAIT_OPEN:-420}"      # Sekunden bis „ready“ nach dem Start
PING_TIMEOUT="${XNU_UNITY_PING_TIMEOUT:-25}" # Sekunden je Statusabfrage
TEST_TIMEOUT="${XNU_UNITY_TEST_TIMEOUT:-900}"

cli() { "$UNITY_CLI" --no-banner --no-color "$@"; }
cmd() { cli command --project-path "$PROJ" --timeout "$PING_TIMEOUT" --result-only "$@"; }

pids() { pgrep -f "Unity.app/Contents/MacOS/Unity .*-projectpath $PROJ" 2>/dev/null || true; }

state() {
  [ -z "$(pids)" ] && { echo aus; return; }
  if cmd editor_status >/dev/null 2>&1; then echo bereit; else echo haengt; fi
}

cleanup() {
  # Nur aufräumen, wenn kein Editor läuft (sonst zerstört man dessen Temp-Daten).
  [ -n "$(pids)" ] && return 0
  rm -rf "$PROJ/Temp/__Backupscenes" "$PROJ/Assets/_Recovery" "$PROJ/Assets/_Recovery.meta"
  rm -f "$PROJ/Temp/UnityLockfile"
}

stop_editor() {
  local p n=0
  [ -z "$(pids)" ] && return 0
  cli close "$PROJ" >/dev/null 2>&1 || true
  while [ -n "$(pids)" ] && [ $n -lt 40 ]; do sleep 2; n=$((n+1)); done
  for p in $(pids); do echo "Editor reagiert nicht, kill $p"; kill "$p" 2>/dev/null || true; done
  n=0; while [ -n "$(pids)" ] && [ $n -lt 15 ]; do sleep 2; n=$((n+1)); done
  for p in $(pids); do kill -9 "$p" 2>/dev/null || true; done
  sleep 2
}

start_editor() {
  cleanup
  [ -n "$(pids)" ] && { echo "Editor läuft bereits."; return 0; }
  # -silent-crashes: kein Absturzdialog; -disable-assembly-updater: kein API-Updater-Dialog
  cli open "$PROJ" --args "-silent-crashes -disable-assembly-updater" >/dev/null 2>&1 || true
  local waited=0
  while [ $waited -lt "$WAIT_OPEN" ]; do
    sleep 5; waited=$((waited+5))
    [ "$(state)" = bereit ] && { echo "Editor bereit nach ${waited}s."; return 0; }
  done
  echo "FEHLER: Editor nach ${WAIT_OPEN}s nicht bereit." >&2
  return 1
}

run_tests() {
  cmd editor_stop >/dev/null 2>&1 || true
  cli command --project-path "$PROJ" --timeout "$TEST_TIMEOUT" --result-only run_tests editor "${1:-Xnu.Tests.EditMode}" assembly
}

case "${1:-status}" in
  open)    start_editor ;;
  restart) stop_editor; start_editor ;;
  status)  state ;;
  test)
    shift
    out="${XNU_UNITY_TEST_OUT:-$HERE/work/test-results.json}"
    mkdir -p "$(dirname "$out")"
    [ "$(state)" = bereit ] || { stop_editor; start_editor || exit 1; }
    if ! run_tests "${1:-}" > "$out" 2>&1 || ! grep -q '"Summary"' "$out"; then
      echo "Test ohne Ergebnis (Zeitlimit oder Hänger), Neustart und zweiter Versuch."
      stop_editor; start_editor || exit 1
      run_tests "${1:-}" > "$out" 2>&1
    fi
    python3 - "$out" <<'PY'
import json, sys
try:
    d = json.load(open(sys.argv[1]))
except Exception as e:
    print("Kein auswertbares Ergebnis:", e); sys.exit(2)
s = d.get("Summary", {})
print(s)
bad = [r for r in d.get("Results", []) if r.get("Status") not in ("Passed", "Skipped")]
for r in bad[:20]:
    print(r["FullName"], r["Status"], (r.get("Message") or "")[:200])
sys.exit(1 if bad or not s else 0)
PY
    ;;
  watch)
    fails=0
    while true; do
      s="$(state)"
      case "$s" in
        bereit) fails=0 ;;
        haengt) fails=$((fails+1)); echo "$(date +%T) Editor antwortet nicht ($fails/3)" ;;
        aus)    echo "$(date +%T) Editor ist aus"; fails=3 ;;
      esac
      if [ $fails -ge 3 ]; then echo "$(date +%T) Neustart"; stop_editor; start_editor; fails=0; fi
      sleep 60
    done
    ;;
  *) echo "Aufruf: $0 open|restart|status|test [assembly]|watch" >&2; exit 64 ;;
esac
