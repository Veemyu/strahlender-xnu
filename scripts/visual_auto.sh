#!/usr/bin/env bash
# Automatische Sichtprüfung: Aufnahme -> Vergleich -> Bericht (docs/visuelle-pruefung.md).
#   visual_auto.sh run [--mode editor|player|ipad] [--quick] [--only a,b] [--name LAUF] [--strict] [--no-capture] [--ref] [--timeout SEK]
#        Aufnahme (Editor: Feldszenarien über Xnu.Visual.Capture + Spielszene-Folgen; Player: macOS-Build, Folgen der Spielszene;
#        iPad: devicectl, Folgen der Spielszene), danach Vergleich mit der Baseline, Bericht work/visual/auto/<lauf>/report.md.
#        --quick = nur Szenarien mit Tag "quick" (Feldkamera, keine Spielszene-Folgen); --ref [ryujinx|recomp|both] = zusätzlich gegen
#        Referenzbilder (Ryujinx-F8-Screenshots, Rekompilations-Screenshots; ohne Wert: ryujinx).
#        Exit-Code 0 = keine Regression, 1 = Regression, 2 = Fehler/Aufnahme gescheitert, 4 = Aufnahmecode (Phase B) nicht übernommen.
#   visual_auto.sh compare [--run LAUF|latest] [--strict] [--ref]   nur Vergleich eines vorhandenen Laufs
#   visual_auto.sh accept [LAUF|latest]                           Lauf als neue Baseline übernehmen (erst nach Sichtung der Kontaktbögen!)
#   visual_auto.sh watch [--interval MIN] [--once] [--quick]      alle N Minuten (Standard 10) laufen, wenn sich unity/Assets/Scripts/{Field,Render}
#                                                                 oder scripts/shader_* geändert haben
#   visual_auto.sh ref [--run LAUF|latest] [--fetch]              Ryujinx-Referenzen holen (--fetch) und gegen den Lauf vergleichen
#   visual_auto.sh scenarios                                      Szenarioliste prüfen und auflisten
#   visual_auto.sh test                                           Python-Tests der Sichtprüfung
#   visual_auto.sh status                                         Zustand (Editor, Baseline, letzter Lauf, Referenzen)
# Umgebung: XNU_UNITY_PROJECT (Standard <Repo>/unity), UNITY_CLI, XNU_PLAYER (Standard work/builds/macos/xnu.app/Contents/MacOS/xnu),
#           XNU_VISUAL_TIMEOUT (Aufnahmezeitlimit je Schritt in Sekunden, Standard 1500), PYTHON.
# Kein Ton: die Szenen spielen nichts ab (AudioSafety). Bilder liegen nur unter work/ (gitignoriert).
set -u
HERE="$(cd "$(dirname "$0")/.." && pwd)"
PROJ="${XNU_UNITY_PROJECT:-$HERE/unity}"
UNITY_CLI="${UNITY_CLI:-$HOME/.unity/bin/unity}"
PY="${PYTHON:-python3}"
AUTO="$HERE/work/visual/auto"
BASE="$AUTO/baseline"
SCEN="$HERE/scripts/visual/scenarios.json"
REFDIR="$HERE/work/visual/ref/ryujinx"
PLAYER="${XNU_PLAYER:-$HERE/work/builds/macos/xnu.app/Contents/MacOS/xnu}"
TIMEOUT="${XNU_VISUAL_TIMEOUT:-1500}"
have_capture() { [ -n "$(find "$PROJ/Assets" -path '*Visual/Editor/Capture.cs' 2>/dev/null | head -1)" ]; }

log() { echo "[visual] $*"; }
die() { echo "[visual] FEHLER: $1" >&2; exit "${2:-2}"; }
ucmd() { "$UNITY_CLI" --no-banner --no-color command --project-path "$PROJ" --timeout 90 --result-only "$@"; }
vs() { "$PY" "$HERE/scripts/visual_scenarios.py" "$@"; }

latest_run() { ls -1dt "$AUTO"/run-* 2>/dev/null | head -1; }

resolve_run() { # Name oder Pfad oder latest -> Pfad
  local r="${1:-latest}"
  if [ "$r" = latest ]; then r="$(latest_run)"; [ -n "$r" ] || die "kein Lauf vorhanden ($AUTO/run-*)"; fi
  [ -d "$r" ] || r="$AUTO/$r"
  [ -d "$r" ] || die "Lauf nicht gefunden: $1"
  echo "$r"
}

lock() {
  mkdir -p "$AUTO"
  if ! mkdir "$AUTO/.lock" 2>/dev/null; then
    local p; p="$(cat "$AUTO/.lock/pid" 2>/dev/null || true)"
    if [ -n "$p" ] && kill -0 "$p" 2>/dev/null; then die "ein anderer Lauf ist aktiv (PID $p)"; fi
    rm -rf "$AUTO/.lock"; mkdir "$AUTO/.lock"
  fi
  echo $$ >"$AUTO/.lock/pid"
  trap 'rm -rf "$AUTO/.lock"; [ -n "${RUN:-}" ] && { rmdir "$RUN/shots" 2>/dev/null; rmdir "$RUN" 2>/dev/null; }; true' EXIT
}

editor_state() { "$HERE/scripts/unity_safe.sh" status 2>/dev/null | tail -1; }

# wartet, bis in $1 (capture.json) "state" fertig oder fehler steht; Rückgabe 0 = fertig
wait_capture() {
  local f="$1" waited=0 st
  while [ "$waited" -lt "$TIMEOUT" ]; do
    sleep 5; waited=$((waited + 5))
    st="$(sed -n 's/.*"state": *"\([a-z]*\)".*/\1/p' "$f" 2>/dev/null | head -1)"
    [ "$st" = fertig ] && return 0
    [ "$st" = fehler ] && { log "Aufnahme meldet Fehler: $(sed -n 's/.*"error": *"\(.*\)".*/\1/p' "$f" | head -1)"; return 1; }
  done
  log "Zeitüberschreitung (${TIMEOUT}s) beim Warten auf $f"
  return 1
}

wait_file() { # Datei, Zeitlimit
  local f="$1" lim="$2" waited=0
  while [ "$waited" -lt "$lim" ]; do [ -s "$f" ] && return 0; sleep 3; waited=$((waited + 3)); done
  return 1
}

last_shot_of() { vs shots --sequence "$1" --file "$SCEN" | tail -1; }

sequences_for() { # kein quick, kein --only: alle Folgen; mit --only: Folgen, in denen ein gewählter Name vorkommt
  if [ -n "$ONLY" ]; then vs sequences --names "$ONLY"; else vs sequences; fi
}

mark_requested() { # RUN Namen...
  local run="$1"; shift
  vs mark-requested --run "$run" --names "$(IFS=,; echo "$*")" --mode "$MODE" >/dev/null
}

capture_editor() {
  local run="$1" s names
  have_capture || die "Aufnahmecode fehlt im Projekt $PROJ (Assets/**/Visual/Editor/Capture.cs; Phase B noch nicht übernommen, siehe docs/visuelle-pruefung.md, Abschnitt Übernahme)" 4
  case "$(editor_state)" in
    bereit) ;;
    aus) log "Editor aus: starte ihn (unity_safe.sh open)"; "$HERE/scripts/unity_safe.sh" open || die "Editor nicht bereit" ;;
    *) die "Editor hängt (unity_safe.sh status)" ;;
  esac
  ucmd editor_stop >/dev/null 2>&1 || true
  # Feldszenarien
  local fargs=(--out "$run/field_scenarios.json")
  [ -n "$TAG" ] && fargs+=(--tag "$TAG")
  [ -n "$ONLY" ] && fargs+=(--names "$ONLY")
  [ -f "$REFDIR/assignments.json" ] && fargs+=(--ref-hours "$REFDIR/assignments.json")
  vs export-field "${fargs[@]}" || die "Export der Feldszenarien"
  if grep -q '"name"' "$run/field_scenarios.json"; then
    log "Feldaufnahme (FieldTest2) …"
    out="$(ucmd eval "Xnu.Visual.Capture.CaptureAll(\"$run/field_scenarios.json\", \"$run\");" 2>&1)" || die "eval CaptureAll: $out"
    log "$out"
    wait_capture "$run/capture.json" || die "Feldaufnahme gescheitert (siehe $run/capture.json)"
    ucmd editor_stop >/dev/null 2>&1 || true
    mark_requested "$run" $(vs list --runner field ${TAG:+--tag "$TAG"} ${ONLY:+--names "$ONLY"} | tr '\n' ' ')
  fi
  # Spielszene-Folgen (nicht bei --quick)
  [ -n "$TAG" ] && return 0
  for s in $(sequences_for); do
    log "Spielszene-Folge $s (Editor-Spielmodus) …"
    vs script "$s" --out "$run/seq-$s.txt" || die "Skript der Folge $s"
    ucmd eval "System.Environment.SetEnvironmentVariable(\"XNU_GAMEDATA\", \"$HERE/work\"); System.Environment.SetEnvironmentVariable(\"XNU_SCRIPTED_INPUT\", \"$run/seq-$s.txt\"); System.Environment.SetEnvironmentVariable(\"XNU_SHOT_DIR\", \"$run/shots\"); System.Environment.SetEnvironmentVariable(\"XNU_ENV_HOUR\", \"12\"); System.Environment.SetEnvironmentVariable(\"XNU_GENERATED_SHADERS\", \"1\"); UnityEditor.SceneManagement.EditorSceneManager.OpenScene(\"Assets/Scenes/Game.unity\");" >/dev/null 2>&1 || die "Szene Game öffnen"
    ucmd editor_play >/dev/null 2>&1 || die "editor_play"
    if ! wait_file "$run/shots/$(last_shot_of "$s").png" "$TIMEOUT"; then
      ucmd editor_stop >/dev/null 2>&1 || true
      die "Folge $s: letztes Bild $(last_shot_of "$s") fehlt nach ${TIMEOUT}s"
    fi
    sleep 3; ucmd editor_stop >/dev/null 2>&1 || true
    mark_requested "$run" $(vs shots --sequence "$s" --file "$SCEN" | tr '\n' ' ')
  done
}

capture_player() {
  local run="$1" s pid waited
  [ -x "$PLAYER" ] || die "macOS-Player fehlt: $PLAYER (scripts/build_all.sh --only assets,unity-build --target macos)"
  for s in $(sequences_for); do
    log "Spielszene-Folge $s (macOS-Player) …"
    vs script "$s" --out "$run/seq-$s.txt" || die "Skript der Folge $s"
    XNU_START_SCENE=Game XNU_SCRIPTED_INPUT="$run/seq-$s.txt" XNU_SHOT_DIR="$run/shots" XNU_ENV_HOUR=12 XNU_GENERATED_SHADERS=1 \
      "$PLAYER" -screen-width 1280 -screen-height 720 -screen-fullscreen 0 -logFile "$run/player-$s.log" >/dev/null 2>&1 &
    pid=$!
    waited=0
    while kill -0 "$pid" 2>/dev/null && [ "$waited" -lt "$TIMEOUT" ]; do sleep 3; waited=$((waited + 3)); done
    if kill -0 "$pid" 2>/dev/null; then log "Player hängt, kill $pid"; kill "$pid" 2>/dev/null || true; fi
    mark_requested "$run" $(vs shots --sequence "$s" --file "$SCEN" | tr '\n' ' ')
  done
}

capture_ipad() {
  local run="$1" s dev bundle="${BUNDLE_ID:-dev.local.xnum0}"
  export DEVELOPER_DIR="${DEVELOPER_DIR:-/Applications/Xcode.app/Contents/Developer}"
  dev="$(xcrun devicectl list devices 2>/dev/null | awk '/iPad/ && /connected/ {print $3; exit}')"
  [ -n "$dev" ] || die "kein verbundenes iPad (xcrun devicectl list devices)"
  for s in $(sequences_for); do
    log "Spielszene-Folge $s (iPad $dev) …"
    vs script "$s" --out "$run/seq-$s.txt" || die "Skript der Folge $s"
    xcrun devicectl device copy to --device "$dev" --domain-type appDataContainer --domain-identifier "$bundle" \
      --source "$run/seq-$s.txt" --destination "Documents/visual-seq-$s.txt" >"$run/ipad-copy-$s.log" 2>&1 || die "Skript aufs iPad kopieren (Log $run/ipad-copy-$s.log)"
    xcrun devicectl device process launch --device "$dev" --terminate-existing --console \
      --environment-variables "{\"XNU_START_SCENE\":\"Game\",\"XNU_SCRIPTED_INPUT\":\"visual-seq-$s.txt\",\"XNU_ENV_HOUR\":\"12\",\"XNU_GENERATED_SHADERS\":\"1\"}" \
      "$bundle" >"$run/ipad-run-$s.log" 2>&1 || log "devicectl launch endete mit Fehler (Log $run/ipad-run-$s.log)"
    xcrun devicectl device copy from --device "$dev" --domain-type appDataContainer --domain-identifier "$bundle" \
      --source "Documents/Shots" --destination "$run/shots" >"$run/ipad-pull-$s.log" 2>&1 || die "Bilder vom iPad holen (Log $run/ipad-pull-$s.log)"
    mark_requested "$run" $(vs shots --sequence "$s" --file "$SCEN" | tr '\n' ' ')
  done
}

do_compare() { # RUN
  local run="$1" args=() code=0
  [ -d "$BASE/shots" ] || log "Hinweis: keine Baseline ($BASE): alle Bilder gelten als neu (nur Anomalie-Prüfung)"
  [ "$STRICT" = 1 ] && args+=(--strict)
  "$PY" "$HERE/scripts/visual_compare.py" compare --run "$run" --baseline "$BASE" --scenarios "$SCEN" "${args[@]+"${args[@]}"}" || code=$?
  ref_compare "$run"
  log "Bericht: $run/report.md"
  log "Kontaktbögen: $run/contact/ (mit dem view-Tool ansehen)"
  return "$code"
}

# Referenzvergleich je Quelle: ryujinx (Emulator-Screenshots) und/oder recomp (Rekompilation); Ergebnis run/ref_report.md bzw. run/recomp/ref_report.md
ref_compare() { # RUN
  local run="$1" src
  [ "$WITH_REF" = 1 ] || return 0
  for src in $( [ "$REF_SRC" = both ] && echo "ryujinx recomp" || echo "$REF_SRC" ); do
    if [ "$src" = recomp ]; then
      "$PY" "$HERE/scripts/visual_ref.py" import --source recomp >/dev/null 2>&1 || true
      "$PY" "$HERE/scripts/visual_compare.py" ref compare --run "$run" --source recomp || log "Referenzvergleich recomp meldete Fehler"
    elif [ -f "$REFDIR/assignments.json" ]; then
      "$PY" "$HERE/scripts/visual_compare.py" ref compare --run "$run" --ref "$REFDIR" || log "Referenzvergleich ryujinx meldete Fehler"
    else
      log "Keine Ryujinx-Referenzen (scripts/ryujinx_fetch_shots.sh fetch)"
    fi
  done
}

cmd="${1:-help}"; shift || true
MODE=editor; NAME=""; TAG=""; ONLY=""; STRICT=0; NOCAP=0; WITH_REF=0; REF_SRC=ryujinx; RUNARG=latest; INTERVAL=10; ONCE=0; FETCH=0
while [ $# -gt 0 ]; do
  case "$1" in
    --mode) MODE="$2"; shift 2 ;;
    --name) NAME="$2"; shift 2 ;;
    --quick) TAG=quick; shift ;;
    --only) ONLY="$2"; shift 2 ;;
    --strict) STRICT=1; shift ;;
    --no-capture) NOCAP=1; shift ;;
    --ref) WITH_REF=1; case "${2:-}" in ryujinx|recomp|both) REF_SRC="$2"; shift ;; esac; shift ;;
    --fetch) FETCH=1; shift ;;
    --timeout) TIMEOUT="$2"; shift 2 ;;
    --run) RUNARG="$2"; shift 2 ;;
    --interval) INTERVAL="$2"; shift 2 ;;
    --once) ONCE=1; shift ;;
    -h|--help) cmd=help; shift ;;
    *) if [ "$cmd" = accept ] && [ "$RUNARG" = latest ]; then RUNARG="$1"; shift; else die "Unbekannte Option: $1" 2; fi ;;
  esac
done

case "$cmd" in
  run)
    vs validate >/dev/null || die "scenarios.json ungültig (visual_auto.sh scenarios)"
    lock
    RUN="$AUTO/${NAME:-run-$(date +%Y%m%d-%H%M%S)}"
    case "$NAME" in run-*|"") ;; *) RUN="$AUTO/run-$NAME" ;; esac
    mkdir -p "$RUN/shots"
    if [ "$NOCAP" = 0 ]; then
      case "$MODE" in
        editor) capture_editor "$RUN" ;;
        player) capture_player "$RUN" ;;
        ipad) capture_ipad "$RUN" ;;
        *) die "Modus $MODE unbekannt (editor|player|ipad)" ;;
      esac
    fi
    do_compare "$RUN"; exit $?
    ;;
  compare)
    RUN="$(resolve_run "$RUNARG")"
    do_compare "$RUN"; exit $?
    ;;
  accept)
    RUN="$(resolve_run "$RUNARG")"
    "$PY" "$HERE/scripts/visual_compare.py" accept --run "$RUN" --baseline "$BASE" --scenarios "$SCEN" || exit 2
    ;;
  watch)
    state="$AUTO/.watch-state"; mkdir -p "$AUTO"
    while true; do
      cur="$( (find "$HERE/unity/Assets/Scripts/Field" "$HERE/unity/Assets/Scripts/Render" -name '*.cs' 2>/dev/null; ls "$HERE"/scripts/shader_* 2>/dev/null) | sort | while read -r f; do stat -f '%N %m' "$f"; done | shasum | cut -c1-16)"
      if [ "$cur" != "$(cat "$state" 2>/dev/null)" ]; then
        log "Änderung erkannt ($cur): Lauf"
        if "$0" run ${TAG:+--quick}; then :; else log "Lauf endete mit Code $? (Bericht siehe letzter Lauf)"; fi
        echo "$cur" >"$state"
      else
        log "keine Änderung ($(date +%H:%M))"
      fi
      [ "$ONCE" = 1 ] && break
      sleep $((INTERVAL * 60))
    done
    ;;
  ref)
    [ "$FETCH" = 1 ] && { "$HERE/scripts/ryujinx_fetch_shots.sh" fetch || exit $?; }
    RUN="$(resolve_run "$RUNARG")"
    WITH_REF=1
    ref_compare "$RUN"
    ;;
  scenarios)
    vs validate && vs list
    ;;
  test)
    cd "$HERE/scripts/tests" && "$PY" -m unittest test_visual_compare test_visual_ref test_visual_scenarios test_ryzen_keys -v
    ;;
  status)
    echo "Editor     : $(editor_state)"
    echo "Baseline   : $( [ -d "$BASE/shots" ] && echo "$(ls "$BASE/shots" | wc -l | tr -d ' ') Bilder ($(sed -n 's/.*"accepted_at": *"\(.*\)".*/\1/p' "$BASE/baseline.json" 2>/dev/null))" || echo "keine (visual_auto.sh accept nach der ersten Sichtung)")"
    echo "Letzter Lauf: $(latest_run || true)"
    echo "Referenzen : $( [ -f "$REFDIR/assignments.json" ] && ls "$REFDIR/views" 2>/dev/null | wc -l | tr -d ' ' || echo 0) Ansicht(en)"
    echo "Aufnahmecode: $( have_capture && echo "im Projekt $PROJ vorhanden" || echo "noch nicht in $PROJ (Phase B, work/visual/phaseB/)")"
    ;;
  help|*)
    awk 'NR > 1 && /^set -u/ {exit} NR > 1 {sub(/^# ?/, ""); print}' "$0"
    ;;
esac
