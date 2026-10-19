#!/usr/bin/env bash
# Spielt eine Tastenfolge in Ryujinx auf dem Ryzen ab, holt die entstandenen Screenshots und vergleicht sie mit einem Unity-Lauf.
#   ryujinx_record.sh ROUTE [--dry-run] [--focus] [--no-compare] [--run LAUF|latest] [--time-limit SEK] [--speed F]
#   ROUTE = Name einer Datei in scripts/visual/routes/ (ohne .keys): f8_only (harmlos), boot_weiter, tuer_innenraum
# Ablauf: Spielstand-Stand anzeigen (ryujinx_sync_save.sh status, nur lesen) -> ryzen_keys.py und Route nach ~/xnu-recomp/ auf dem Ryzen
#   kopieren -> Fokus prüfen -> ryzen_keys.py ausführen (wartet auf jedes Screenshot-Bild, F8) -> neue Bilder nach
#   work/visual/ref/ryujinx/<route>/ holen, als Referenzansichten zuordnen (raw/<Ansicht>__<Original>.png) -> visual_compare.py ref compare.
# Ryujinx und das Spiel startet der Nutzer selbst (Fenster im Vordergrund); dieses Skript startet nichts per ssh außer ryzen_keys.py.
# Tasten werden nur gesendet, wenn das aktive Fenster Ryujinx ist (geprüft vor jeder Taste auf dem Ryzen). Abbruch: auf dem Ryzen
# ~/xnu-recomp/STOP anlegen (oder hier: ryujinx_record.sh --stop).
# Exit-Codes: Durchreichung von ryzen_keys.py (3 STOP, 4 Zeitlimit, 5 Fokus, 6 kein Bild, 7 uinput, 8 läuft schon), 2 Aufruf/Verbindung, 1 sonstiges.
set -u
HERE="$(cd "$(dirname "$0")/.." && pwd)"
RZ_HOST="${RZ_HOST:-nobara}"
PY="${PYTHON:-python3}"
REFDIR="${XNU_REF_DIR:-$HERE/work/visual/ref/ryujinx}"
AUTO="$HERE/work/visual/auto"
ROUTES="$HERE/scripts/visual/routes"
RZ_TOOLS="xnu-recomp/tools"
RZ_ROUTES="xnu-recomp/routes"
RZ_SHOTS=".config/Ryujinx/screenshots"
SSH=(ssh -o BatchMode=yes -o ConnectTimeout=8 "$RZ_HOST")

die() { echo "[record] FEHLER: $1" >&2; exit "${2:-2}"; }
log() { echo "[record] $*"; }

ROUTE=""; DRY=0; FOCUS=0; COMPARE=1; RUNARG=latest; LIMIT=300; SPEED=1; STOPREQ=0
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1; shift ;;
    --focus) FOCUS=1; shift ;;
    --no-compare) COMPARE=0; shift ;;
    --run) RUNARG="$2"; shift 2 ;;
    --time-limit) LIMIT="$2"; shift 2 ;;
    --speed) SPEED="$2"; shift 2 ;;
    --stop) STOPREQ=1; shift ;;
    -h|--help) awk 'NR > 1 && /^set -u/ {exit} NR > 1 {sub(/^# ?/, ""); print}' "$0"; exit 0 ;;
    -*) die "Unbekannte Option: $1" ;;
    *) ROUTE="$1"; shift ;;
  esac
done

"${SSH[@]}" true 2>/dev/null || die "Der Ryzen ($RZ_HOST) ist nicht erreichbar."
if [ "$STOPREQ" = 1 ]; then "${SSH[@]}" "touch ~/xnu-recomp/STOP" && log "STOP-Datei auf dem Ryzen angelegt (Abbruch laufender Folgen; vor dem nächsten Lauf löschen: ssh $RZ_HOST rm ~/xnu-recomp/STOP)"; exit 0; fi
[ -n "$ROUTE" ] || die "Route fehlt (verfügbar: $(ls "$ROUTES" | sed 's/\.keys$//' | tr '\n' ' '))"
FILE="$ROUTES/$ROUTE.keys"
[ -f "$FILE" ] || die "Route nicht gefunden: $FILE"

log "Spielstand (nur lesen):"
"$HERE/scripts/ryujinx_sync_save.sh" status 2>&1 | sed 's/^/        /' || true

"${SSH[@]}" "mkdir -p ~/$RZ_TOOLS ~/$RZ_ROUTES ~/xnu-recomp/logs ~/xnu-recomp/run && rm -f ~/xnu-recomp/STOP" || die "Ablage ~/xnu-recomp auf dem Ryzen"
scp -q -o BatchMode=yes "$HERE/scripts/ryzen_keys.py" "$RZ_HOST:$RZ_TOOLS/ryzen_keys.py" || die "ryzen_keys.py kopieren"
scp -q -o BatchMode=yes "$FILE" "$RZ_HOST:$RZ_ROUTES/$ROUTE.keys" || die "Route kopieren"

args=("python3" "~/$RZ_TOOLS/ryzen_keys.py" "~/$RZ_ROUTES/$ROUTE.keys" "--time-limit" "$LIMIT" "--speed" "$SPEED")
[ "$DRY" = 1 ] && args+=("--dry-run")
[ "$FOCUS" = 1 ] && args+=("--focus")

if [ "$DRY" = 0 ]; then
  log "Fokus prüfen …"
  if ! "${SSH[@]}" "python3 ~/$RZ_TOOLS/ryzen_keys.py --check"; then
    die "Aktives Fenster auf dem Ryzen ist nicht Ryujinx: Ryujinx-Fenster anklicken (oder --focus versuchen), dann erneut starten. Es wurden keine Tasten gesendet." 5
  fi
fi

OUT="$("${SSH[@]}" "${args[*]}" 2>&1)"; CODE=$?
echo "$OUT" | sed 's/^/        /'
RESULT="$(echo "$OUT" | sed -n 's/^RESULT //p' | tail -1)"
[ "$DRY" = 1 ] && { log "Trockenlauf beendet (Exit $CODE): es wurde nichts gesendet."; exit "$CODE"; }

# neue Bilder holen (auch bei Abbruch: was bis dahin entstanden ist)
if [ -n "$RESULT" ]; then
  mkdir -p "$REFDIR/$ROUTE" "$REFDIR/raw"
  n=0
  while IFS=$'\t' read -r view name; do
    [ -n "$name" ] || continue
    n=$((n + 1))
    prefix="$view"; [ "$view" = "-" ] && prefix="free_${ROUTE}_$n"
    scp -q -p -o BatchMode=yes "$RZ_HOST:$RZ_SHOTS/$name" "$REFDIR/$ROUTE/$name" || { log "Bild holen gescheitert: $name"; continue; }
    cp -p "$REFDIR/$ROUTE/$name" "$REFDIR/raw/${prefix}__${name}"
    log "Bild: $name -> ${prefix}"
  done < <(echo "$RESULT" | "$PY" -c 'import json,sys; r=json.load(sys.stdin); [print((s.get("view") or "-")+"\t"+s["name"]) for s in r["shots"]]')
  off="$("${SSH[@]}" "grep -E '\"system_time_offset\"' ~/.config/Ryujinx/Config.json" 2>/dev/null | sed -E 's/[^-0-9]//g')"
  "$PY" "$HERE/scripts/visual_ref.py" import --raw "$REFDIR/raw" --dest "$REFDIR" --offset "${off:-0}" || log "Zuordnung fehlgeschlagen"
fi
[ "$CODE" = 0 ] || { log "Folge endete mit Exit $CODE"; exit "$CODE"; }

if [ "$COMPARE" = 1 ]; then
  RUN="$RUNARG"
  if [ "$RUN" = latest ]; then RUN="$(ls -1dt "$AUTO"/run-* 2>/dev/null | head -1)"; fi
  [ -d "${RUN:-/nonexistent}" ] || [ -d "$AUTO/${RUN:-x}" ] && { [ -d "$RUN" ] || RUN="$AUTO/$RUN"; }
  if [ -n "${RUN:-}" ] && [ -d "$RUN" ]; then
    "$PY" "$HERE/scripts/visual_compare.py" ref compare --run "$RUN" --ref "$REFDIR"
  else
    log "Kein Unity-Lauf vorhanden: Referenzvergleich übersprungen (zuerst scripts/visual_auto.sh run)"
  fi
fi
