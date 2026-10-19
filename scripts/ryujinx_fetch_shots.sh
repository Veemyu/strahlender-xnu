#!/usr/bin/env bash
# Holt F8-Screenshots von Ryujinx auf dem Ryzen und ordnet sie den Referenzansichten zu (docs/visuelle-pruefung.md).
#   ryujinx_fetch_shots.sh [fetch] [--since "YYYY-MM-DD HH:MM"]   neue Dateien aus ~/.config/Ryujinx/screenshots/ nach work/visual/ref/ryujinx/raw/ holen
#                                     (nur neue, Dateiname mit Zeitstempel bleibt, rsync -t erhält die Dateizeit), danach zuordnen und
#                                     auf 1280x720 normalisieren: work/visual/ref/ryujinx/views/<Ansicht>.png (scripts/visual/ref_map.json);
#                                     --since (oder XNU_REF_SINCE): ältere Dateien (Testbilder) ignorieren
#   ryujinx_fetch_shots.sh reset      Zuordnung neu beginnen (Rohbilder/Ansichten/Zuordnung ins Archiv verschieben)
#   ryujinx_fetch_shots.sh status     Ryzen erreichbar? Anzahl Screenshots, Spieluhr-Offset, Stand der Zuordnung
#   ryujinx_fetch_shots.sh cache      Zahlen des Ryujinx-Shader-Caches (Einträge, Hash der .toc) neben unseren genutzten Varianten
# Zuordnung: der Reihe nach (Dateizeit) auf die Ansichten aus ref_map.json, oder per Umbenennen: eine Datei, deren Name mit dem
# Ansichtsnamen beginnt (z. B. ref_03_innen_eintritt.png, auf dem Ryzen oder in raw/), belegt genau diese Ansicht.
# Idempotent: schon geholte/zugeordnete Dateien bleiben unverändert. Es wird nichts auf dem Ryzen verändert oder gelöscht.
# Exit-Codes: 0 ok, 2 Ryzen nicht erreichbar, 3 Screenshot-Ordner fehlt (F8 noch nie gedrückt), 1 sonstiger Fehler.
# Umgebung: RZ_HOST (Standard nobara), RZ_SHOTS (Standard .config/Ryujinx/screenshots, relativ zu ~), RZ_CONFIG, RZ_CACHE.
set -u
HERE="$(cd "$(dirname "$0")/.." && pwd)"
RZ_HOST="${RZ_HOST:-nobara}"
RZ_SHOTS="${RZ_SHOTS:-.config/Ryujinx/screenshots}"
RZ_CONFIG="${RZ_CONFIG:-.config/Ryujinx/Config.json}"
RZ_CACHE="${RZ_CACHE:-.config/Ryujinx/games/0100000011d90000/cache/shader}"
DEST="${XNU_REF_DIR:-$HERE/work/visual/ref/ryujinx}"
PY="${PYTHON:-python3}"
SSH_OPTS=(-o BatchMode=yes -o ConnectTimeout=8)

rz() { ssh "${SSH_OPTS[@]}" "$RZ_HOST" "$@"; }

need_host() {
  if ! rz true 2>/dev/null; then
    echo "FEHLER: Der Ryzen ($RZ_HOST) ist nicht erreichbar (ausgeschaltet, Netz oder SSH-Schlüssel?)." >&2
    echo "        Prüfen: ssh $RZ_HOST true" >&2
    exit 2
  fi
}

offset_seconds() {
  local v
  v="$(rz "grep -E '\"system_time_offset\"' ~/$RZ_CONFIG" 2>/dev/null | sed -E 's/[^-0-9]//g')"
  echo "${v:-0}"
}

cmd="${1:-fetch}"
shift || true
SINCE="${XNU_REF_SINCE:-}"
while [ $# -gt 0 ]; do
  case "$1" in
    --since) SINCE="$2"; shift 2 ;;
    *) echo "Unbekannte Option: $1" >&2; exit 1 ;;
  esac
done
case "$cmd" in
  reset)
    # Zuordnung neu beginnen: Rohbilder, Ansichten und Zuordnung in ein Archiv verschieben (nichts wird gelöscht)
    ts="$(date +%Y%m%d-%H%M%S)"
    mkdir -p "$DEST/archiv-$ts"
    for x in raw views assignments.json; do [ -e "$DEST/$x" ] && mv "$DEST/$x" "$DEST/archiv-$ts/"; done
    echo "Archiviert nach $DEST/archiv-$ts (neu holen: fetch; ältere Ryzen-Bilder mit --since ausblenden)"
    ;;
  fetch)
    need_host
    if ! rz "[ -d ~/$RZ_SHOTS ]"; then
      echo "FEHLER: Auf dem Ryzen gibt es ~/$RZ_SHOTS noch nicht: in Ryujinx im laufenden Spiel F8 drücken (legt den Ordner an)." >&2
      exit 3
    fi
    mkdir -p "$DEST/raw"
    before="$(ls "$DEST/raw" 2>/dev/null | wc -l | tr -d ' ')"
    # nur neue Bilder, Zeiten erhalten (-t), nie löschen
    if ! rsync -rt --ignore-existing --include='*.png' --include='*.jpg' --include='*.bmp' --exclude='*' \
         -e "ssh -o BatchMode=yes -o ConnectTimeout=8" "$RZ_HOST:$RZ_SHOTS/" "$DEST/raw/"; then
      echo "FEHLER: rsync vom Ryzen ist fehlgeschlagen." >&2
      exit 1
    fi
    after="$(ls "$DEST/raw" | wc -l | tr -d ' ')"
    echo "Neu geholt: $((after - before)) Datei(en) (gesamt $after) in $DEST/raw"
    off="$(offset_seconds)"
    echo "Spieluhr-Offset aus Config.json: ${off} s (Zeitzone des Spiels laut Config: UTC; Annahme siehe ref_map.json)"
    "$PY" "$HERE/scripts/visual_ref.py" import --raw "$DEST/raw" --dest "$DEST" --offset "$off" ${SINCE:+--since "$SINCE"} || exit 1
    echo "Normalisierte Ansichten: $DEST/views (Zuordnung: $DEST/assignments.json)"
    ;;
  status)
    need_host
    if rz "[ -d ~/$RZ_SHOTS ]"; then
      n="$(rz "ls ~/$RZ_SHOTS | wc -l" | tr -d ' ')"
      echo "Ryzen: erreichbar, Screenshots dort: $n"
    else
      echo "Ryzen: erreichbar, Screenshot-Ordner fehlt noch (F8 noch nie gedrückt)"
    fi
    echo "Spieluhr-Offset: $(offset_seconds) s"
    if [ -f "$DEST/assignments.json" ]; then
      "$PY" - "$DEST/assignments.json" <<'EOF'
import json, sys
s = json.load(open(sys.argv[1]))
print("Zugeordnet: %d Ansicht(en)" % len(s.get("views", {})))
for v, e in s.get("views", {}).items():
    print("  %-26s %-40s Spielstunde %s" % (v, e["file"], e["game_hour"]))
EOF
    else
      echo "Lokal: noch nichts zugeordnet ($DEST/assignments.json fehlt)"
    fi
    ;;
  cache)
    need_host
    args=()
    for n in guest shared vulkan_nvidia; do
      line="$(rz "f=~/$RZ_CACHE/$n.toc; [ -f \$f ] && echo \$(stat -c %s \$f) \$(od -An -tu4 -j12 -N4 \$f | tr -d ' ') \$(sha256sum \$f | cut -c1-12)")"
      if [ -z "$line" ]; then echo "Hinweis: $n.toc fehlt im Cache-Ordner" >&2; continue; fi
      set -- $line
      args+=("$n=$1:$2")
      echo "$n: .toc-Größe $1, Kopfzähler $2, sha256 $3…"
    done
    [ ${#args[@]} -gt 0 ] || { echo "FEHLER: kein Shader-Cache gefunden ($RZ_CACHE)" >&2; exit 1; }
    "$PY" "$HERE/scripts/visual_ref.py" cache --entries "${args[@]}"
    ;;
  -h|--help|help)
    awk 'NR > 1 && /^set -u/ {exit} NR > 1 {sub(/^# ?/, ""); print}' "$0"
    ;;
  *)
    echo "Unbekannter Befehl: $cmd (fetch | status | cache)" >&2
    exit 1
    ;;
esac
