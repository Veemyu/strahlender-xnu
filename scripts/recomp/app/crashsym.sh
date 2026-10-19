#!/bin/bash
# Symbolisiert einen Absturzbericht der App: Gastfunktionen (f_70xxxxxxxx im Hostrahmen, Adressen im Gast-Ring) bekommen IL2CPP-Namen
# aus work/recomp/il2sym.tsv; Hostadressen ohne Namen lassen sich mit atos auflösen.
#   crashsym.sh <log-oder-ips-datei>                    Gastnamen ergänzen (Ausgabe auf stdout)
#   crashsym.sh --atos <Ladeadresse> <Adresse>...       Hostadressen: atos -o BDSP -l <Ladeadresse> (Ladeadresse steht im .ips-Bericht
#                                                       unter usedImages bzw. "Binary Images" für BDSP)
# Voraussetzung: python3 -I scripts/recomp/il2sym.py hat work/recomp/il2sym.tsv erzeugt (nur Namen, keine Spielbytes).
# Der Absturzbericht des Systems liegt unter ~/Library/Logs/DiagnosticReports/BDSP-*.ips, das Laufzeitprotokoll der App unter
# ~/Library/Logs/dev.local.xnubdsp/bdsp.log (letzter Lauf: bdsp.prev.log).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$ROOT"
if [ "${1:-}" = "--atos" ]; then
  [ $# -ge 3 ] || { echo "Aufruf: crashsym.sh --atos <Ladeadresse> <Adresse>..." >&2; exit 2; }
  LOAD="$2"; shift 2
  BIN="${BDSP_BIN:-work/builds/macos-recomp/BDSP.app/Contents/MacOS/BDSP}"
  [ -f "$BIN" ] || { echo "FEHLER: $BIN nicht gefunden (BDSP_BIN setzen)" >&2; exit 10; }
  exec atos -o "$BIN" -arch arm64 -l "$LOAD" "$@"
fi
[ $# -eq 1 ] && [ -f "$1" ] || { echo "Aufruf: crashsym.sh <log-oder-ips-datei>  |  --atos <Ladeadresse> <Adresse>..." >&2; exit 2; }
[ -f work/recomp/il2sym.tsv ] || { echo "FEHLER: work/recomp/il2sym.tsv fehlt: python3 -I scripts/recomp/il2sym.py" >&2; exit 10; }
# f_70002c1d90 -> "f_ 70002c1d90" (damit die Wortgrenze der Adresserkennung greift), danach wieder zusammenfügen
sed -E 's/\bf_(70[0-9a-f]{8})/f_ \1/g' "$1" | python3 scripts/recomp/symres.py | sed -E 's/f_ (70[0-9a-f]{8})/f_\1/g'
