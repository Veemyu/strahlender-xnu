#!/bin/bash
# Übersetzt das erzeugte C aller vier Module (work/recomp/gen4) mit begrenzter Parallelität und misst Zeit/Speicher je Datei.
# Einzelfunktionen mit mehr als 1 MB C werden mit -O0 übersetzt (Ausreißer), alles andere mit -O1.
# Ausgabe: work/recomp/obj4/*.o, work/recomp/obj4/compile_times.txt ("<datei> <s> <MB RSS>"), Gesamtzeit auf stdout.
# Aufruf: build_all.sh [JOBS]   (Standard 3; die Maschine ist geteilt, höchstens 4)
# O0_BYTES: Dateien mit genau einer Funktion und mehr als so vielen Byte C gelten als Ausreißer und werden mit -O0 übersetzt (Standard 1000000)
set -u
cd "$(dirname "$0")/../.."
JOBS=${1:-3}
[ "$JOBS" -gt 4 ] && JOBS=4
GEN=${GEN:-work/recomp/gen4}
OBJ=${OBJ:-work/recomp/obj4}
mkdir -p "$OBJ"
# veraltete Objekte (Chunk-Datei existiert nicht mehr, z. B. nach geänderter Fenstereinteilung) entfernen, sonst doppelte Symbole beim Linken
for o in "$OBJ"/*.o; do
  [ -e "$o" ] || continue
  b=$(basename "$o" .o)
  m=${b%%_*}
  rest=${b#*_}
  [ -f "$GEN/$m/$rest.c" ] || rm -f "$o"
done
: > "$OBJ/list_O1.txt"; : > "$OBJ/list_O0.txt"
for f in "$GEN"/*/*.c; do
  size=$(stat -f %z "$f")
  if [ "$size" -gt "${O0_BYTES:-1000000}" ] && [ "$(grep -c '^void f_.*) {$' "$f")" = "1" ]; then echo "$f" >> "$OBJ/list_O0.txt"; else echo "$f" >> "$OBJ/list_O1.txt"; fi
done
echo "O1: $(wc -l < "$OBJ/list_O1.txt") Dateien, O0: $(wc -l < "$OBJ/list_O0.txt") Dateien, Jobs $JOBS"
start=$(date +%s)
OPT=-O0 xargs -P "$JOBS" -n 1 -I{} scripts/recomp/test/compile_chunk.sh {} "$OBJ" < "$OBJ/list_O0.txt"
OPT=-O1 xargs -P "$JOBS" -n 1 -I{} scripts/recomp/test/compile_chunk.sh {} "$OBJ" < "$OBJ/list_O1.txt"
# Heiße Funktionen (hot_o2.txt): ihre Dateien mit -O2 neu übersetzen, falls das Objekt nicht schon -O2 ist (Marke *.o2)
while read -r fn; do
  case "$fn" in ""|"#"*) continue ;; esac
  for f in $(grep -l "^void $fn(.*{\$" "$GEN"/*/*.c); do
    o="$OBJ/$(basename "$(dirname "$f")")_$(basename "$f" .c).o"
    [ -e "$o.o2" ] && [ "$o.o2" -nt "$f" ] && continue
    rm -f "$o"; OPT=-O2 scripts/recomp/test/compile_chunk.sh "$f" "$OBJ" && : > "$o.o2"
  done
done < scripts/recomp/hot_o2.txt
echo "Gesamtzeit Übersetzung: $(( $(date +%s) - start )) s"
du -sh "$OBJ"
