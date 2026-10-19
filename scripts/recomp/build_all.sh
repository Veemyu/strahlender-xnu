#!/bin/bash
# Übersetzt das erzeugte C aller vier Module (work/recomp/gen4) mit begrenzter Parallelität und misst Zeit/Speicher je Datei.
# Einzelfunktionen mit mehr als 1 MB C werden mit -O0 übersetzt (Ausreißer), alles andere mit -O1.
# Ausgabe: work/recomp/obj4/*.o, work/recomp/obj4/compile_times.txt ("<datei> <s> <MB RSS>"), Gesamtzeit auf stdout.
# Aufruf: build_all.sh [JOBS]   (Standard 3; die Maschine ist geteilt, höchstens 4)
set -u
cd "$(dirname "$0")/../.."
JOBS=${1:-3}
[ "$JOBS" -gt 4 ] && JOBS=4
GEN=${GEN:-work/recomp/gen4}
OBJ=${OBJ:-work/recomp/obj4}
mkdir -p "$OBJ"
: > "$OBJ/list_O1.txt"; : > "$OBJ/list_O0.txt"
for f in "$GEN"/*/*.c; do
  size=$(stat -f %z "$f")
  if [ "$size" -gt 1000000 ] && [ "$(grep -c '^void f_.*) {$' "$f")" = "1" ]; then echo "$f" >> "$OBJ/list_O0.txt"; else echo "$f" >> "$OBJ/list_O1.txt"; fi
done
echo "O1: $(wc -l < "$OBJ/list_O1.txt") Dateien, O0: $(wc -l < "$OBJ/list_O0.txt") Dateien, Jobs $JOBS"
start=$(date +%s)
OPT=-O0 xargs -P "$JOBS" -n 1 -I{} scripts/recomp/test/compile_chunk.sh {} "$OBJ" < "$OBJ/list_O0.txt"
OPT=-O1 xargs -P "$JOBS" -n 1 -I{} scripts/recomp/test/compile_chunk.sh {} "$OBJ" < "$OBJ/list_O1.txt"
echo "Gesamtzeit Übersetzung: $(( $(date +%s) - start )) s"
du -sh "$OBJ"
