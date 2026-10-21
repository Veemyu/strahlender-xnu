#!/bin/bash
# Läuft auf dem Linux host: misst inkrementelle Neubauten (nur geänderte Chunks) an einer Kopie des fertigen Builds
# (gen4-incr / obj4-c-incr), der echte Build bleibt unberührt. Voraussetzung: build.sh lief (work/recomp/obj4-c).
# Szenarien: A keine Änderung, B fünf Chunks ändern sich (touch), C sieben SDK-Funktionen werden zu HLE-Stubs (echte Generatoränderung).
# Ausgabe: logs/incr.stats
source "$(dirname "$0")/common.sh"
[ -d "$W/obj4-c" ] && [ -d "$W/gen4-c" ] || die "Erst build.sh (voller Build) ausführen."
export GEN=$W/gen4-incr TAG=incr JOBS
ST=logs/incr.stats; : > "$ST"
rm -rf "$W/gen4-incr" "$W/obj4-c-incr" "$W/incr"
cp -a "$W/gen4-c" "$W/gen4-incr"; cp -a "$W/obj4-c" "$W/obj4-c-incr"
rm -f "$W/obj4-c-incr/libgame.so"
res() { echo "$1 | $(grep -E 'uebersetzt_dateien|^wall_s|^summe_user' logs/build-c-incr.stats | tr '\n' ' ')link: $(grep link_s logs/build-c-incr.stats)" | tee -a "$ST"; }

echo "== A: keine Änderung"
bash "$(dirname "$0")/compile.sh" c > /dev/null; res "A keine Aenderung"

echo "== B: fünf Chunks berührt"
files=$(ls "$GEN"/main/main_*.c | grep -v table | awk 'NR%180==7' | head -5)
for f in $files; do touch "$f"; echo "// geaendert" >> "$f"; done
bash "$(dirname "$0")/compile.sh" c > /dev/null; res "B 5 Chunks (main, mittelgross)"

echo "== C: 7 SDK-Funktionen als HLE-Stubs (Generatoränderung)"
python3 scripts/recomp/eh_gen.py gen sdk work/exefs/sdk 0x7006000000 "$W/incr/sdk" --simd c --hle scripts/recomp/test/hle_symbols.txt 2>&1 | grep wrote
changed=$(for f in "$W"/incr/sdk/*.c; do cmp -s "$f" "$GEN/sdk/$(basename "$f")" || echo "$f"; done | wc -l)
rsync -rc --delete "$W/incr/sdk/" "$GEN/sdk/"   # ohne -t: nur geänderte Dateien bekommen eine neue Zeit
bash "$(dirname "$0")/compile.sh" c > /dev/null; res "C SDK mit HLE: $changed von $(ls "$W/incr/sdk" | wc -l) SDK-Chunks geaendert"
rm -rf "$W/gen4-incr" "$W/obj4-c-incr" "$W/incr"
echo "fertig"
