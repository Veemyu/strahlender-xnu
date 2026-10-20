#!/bin/bash
# Läuft auf dem Linux host: übersetzt das erzeugte C (work/recomp/gen4-<modus>) mit JOBS parallelen clang-Aufrufen und misst
# Wanduhr/CPU/RAM je Chunk, Gesamt-Spitzen-RAM (Sampler auf /proc/meminfo) und linkt die Zielbibliothek.
# Wie scripts/recomp/build_all.sh auf dem Mac: -O1; Einzelfunktionsdateien > 1 MB mit -O0.
# Aufruf: [TAG=name] [THRESH_O0=bytes] compile.sh [c] [--neu]   --neu: Objekte verwerfen (vollständiger Neubau); sonst nur neuere/fehlende Quellen
#   TAG legt Objekte/Zahlen in obj4-c-<TAG>/ und build-c-<TAG>.* ab (Vergleichsläufe); THRESH_O0 Standard 1000000
# Ausgabe: work/recomp/obj4-<modus>/*.o, logs/build-<modus>.times (je Chunk: Name wall user sys maxrss_KB c_bytes opt), logs/build-<modus>.stats
source "$(dirname "$0")/common.sh"
MODE=c; FORCE=0
for a in "$@"; do case "$a" in c) MODE=c;; --neu) FORCE=1;; *) die "Unbekanntes Argument '$a'.";; esac; done
GEN=${GEN:-$W/gen4-$MODE}
OBJ=$W/obj4-$MODE${TAG:+-$TAG}
TIMES=logs/build-$MODE${TAG:+-$TAG}.times
ST=logs/build-$MODE${TAG:+-$TAG}.stats
THRESH_O0=${THRESH_O0:-300000}   # Einzelfunktionsdateien über dieser Größe (Byte C) mit -O0 (Mac-Spike: 1000000; siehe docs/recomp-linux.md)
[ -d "$GEN" ] || die "$GEN fehlt (erst gen.sh $MODE)."
mkdir -p "$OBJ" logs
[ "$FORCE" = 1 ] && rm -f "$OBJ"/*.o "$OBJ"/*.so
: > "$TIMES"
FLAGS=$(cflags_x86)
export FLAGS OBJ TIMES
# Header und Flags sind keine Abhängigkeiten der einzelnen Chunks: Änderung → vollständiger Neubau
STAMP=$( (cat scripts/recomp/rt/cpu.h $LAS/runtime/cpu.h $LAS/runtime/simd.h $LAS/runtime/simd_fp.h 2>/dev/null; echo "$FLAGS $THRESH_O0") | sha256sum | cut -c1-16)
if [ -f "$OBJ/.stamp" ] && [ "$(cat "$OBJ/.stamp")" != "$STAMP" ]; then echo "Header oder Flags geändert: vollständiger Neubau"; rm -f "$OBJ"/*.o "$OBJ"/*.so; fi
echo "$STAMP" > "$OBJ/.stamp"

: > "$OBJ/list_O0.txt"; : > "$OBJ/list_O1.txt"
for f in "$GEN"/*/*.c; do
  size=$(stat -c %s "$f")
  if [ "$size" -gt "$THRESH_O0" ] && [ "$(grep -c '^void f_.*) {$' "$f")" = "1" ]; then echo "$size $f" >> "$OBJ/list_O0.txt"; else echo "$size $f" >> "$OBJ/list_O1.txt"; fi
done
sort -rn -o "$OBJ/list_O0.txt" "$OBJ/list_O0.txt"; sort -rn -o "$OBJ/list_O1.txt" "$OBJ/list_O1.txt"
# Objekte ohne Quelle (Chunk-Neunummerierung nach Generatoränderung) entfernen, sonst landen sie in der Bibliothek
cat "$OBJ/list_O0.txt" "$OBJ/list_O1.txt" | cut -d' ' -f2 | while read -r f; do echo "$(basename "$(dirname "$f")")_$(basename "$f" .c).o"; done | sort > "$OBJ/expected.txt"
ls "$OBJ" | grep '\.o$' | sort | comm -23 - "$OBJ/expected.txt" | while read -r stale; do echo "entferne veraltetes Objekt $stale"; rm -f "$OBJ/$stale"; done
echo "O1: $(wc -l < "$OBJ/list_O1.txt") Dateien, O0: $(wc -l < "$OBJ/list_O0.txt") Dateien, Jobs $JOBS, Neubau=$FORCE"

one() {   # <opt> <größe> <quelle>
  local opt=$1 size=$2 src=$3
  local o="$OBJ/$(basename "$(dirname "$src")")_$(basename "$src" .c).o"
  [ "$o" -nt "$src" ] && exit 0
  /usr/bin/time -f "%e %U %S %M" -o "$o.t" clang $opt $FLAGS -c "$src" -o "$o" 2> "$o.err" || { echo "FEHLER $src"; head -20 "$o.err"; exit 1; }
  echo "$(basename "$o") $(cat "$o.t") $size $opt" >> "$TIMES"
  rm -f "$o.t" "$o.err"
}
export -f one

base_avail=$(awk '/MemAvailable/ {print $2}' /proc/meminfo)
( min=$base_avail; while :; do a=$(awk '/MemAvailable/ {print $2}' /proc/meminfo); [ "$a" -lt "$min" ] && { min=$a; echo "$((base_avail - min))" > "$OBJ/peak_ram_kb.txt"; }; sleep 1; done ) &
SAMPLER=$!
trap 'kill $SAMPLER 2>/dev/null' EXIT
echo 0 > "$OBJ/peak_ram_kb.txt"

t0=$(date +%s.%N)
rc=0
# Große Einzelfunktionen zuerst (-O0), dann alles andere nach Größe absteigend (bessere Auslastung am Ende)
cut -d' ' -f1,2 "$OBJ/list_O0.txt" | xargs -r -P "$JOBS" -L 1 bash -c 'one -O0 "$0" "$1"' || rc=1
cut -d' ' -f1,2 "$OBJ/list_O1.txt" | xargs -r -P "$JOBS" -L 1 bash -c 'one -O1 "$0" "$1"' || rc=1
t1=$(date +%s.%N)
[ "$rc" = 0 ] || die "Mindestens eine Datei ist nicht übersetzt worden (siehe oben)."

wall=$(awk -v a="$t1" -v b="$t0" 'BEGIN{printf "%.1f", a-b}')
{
  echo "modus=$MODE tag=${TAG:-} jobs=$JOBS neu=$FORCE schwelle_O0=$THRESH_O0"
  echo "uebersetzt_dateien=$(wc -l < "$TIMES")  von=$(cat "$OBJ/list_O0.txt" "$OBJ/list_O1.txt" | wc -l)"
  echo "wall_s=$wall"
  awk '{w+=$2; u+=$3; s+=$4; if ($5>m) m=$5; n++} END {printf "summe_wall_s=%.1f summe_user_s=%.1f summe_sys_s=%.1f max_chunk_rss_mb=%d\n", w, u, s, m/1024}' "$TIMES"
  echo "spitzen_ram_gesamt_mb=$(( $(cat "$OBJ/peak_ram_kb.txt") / 1024 ))"
  echo "langsamste_chunks (name wall_s user_s maxrss_mb c_bytes opt):"
  sort -k2 -rn "$TIMES" | head -8 | awk '{printf "  %s %.1f %.1f %d %d %s\n", $1, $2, $3, $5/1024, $6, $7}'
  echo "groesster_ram_chunks:"
  sort -k5 -rn "$TIMES" | head -4 | awk '{printf "  %s %.1f s %d MB %d B %s\n", $1, $2, $5/1024, $6, $7}'
  awk '{ if ($2>10) a++; if ($2>60) b++ } END {printf "ueber_10s=%d ueber_60s=%d\n", a, b}' "$TIMES"
  sort -k2 -n "$TIMES" | awk '{v[NR]=$2} END {if (NR) printf "median_wall_s=%.2f\n", v[int((NR+1)/2)]}'
} | tee "$ST"

# Link zur Zielbibliothek (Linux-Gegenstück zu libgame.dylib)
l0=$(date +%s.%N)
clang -shared -o "$OBJ/libgame.so" "$OBJ"/*.o -Wl,-z,notext 2> "$OBJ/link.err" || { head -20 "$OBJ/link.err"; die "Link fehlgeschlagen."; }
l1=$(date +%s.%N)
{
  echo "link_s=$(awk -v a="$l1" -v b="$l0" 'BEGIN{printf "%.1f", a-b}')"
  echo "objekte_mb=$(du -sm --apparent-size "$OBJ" | cut -f1)  (ohne Bibliothek ca. $(cat "$OBJ"/*.o | wc -c | awk '{printf "%d", $1/1048576}'))"
  echo "libgame_so_bytes=$(stat -c %s "$OBJ/libgame.so")"
  size "$OBJ/libgame.so" | tail -1
} | tee -a "$ST"
