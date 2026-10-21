#!/bin/bash
# Runs on the Linux host: measures incremental rebuilds (only changed chunks) on a copy of the finished build
# (gen4-incr / obj4-c-incr); the real build stays untouched. Prerequisite: build.sh ran (work/recomp/obj4-c).
# Scenarios: A no change, B five chunks change (touch), C seven SDK functions become HLE stubs (real generator change).
# Output: logs/incr.stats
source "$(dirname "$0")/common.sh"
[ -d "$W/obj4-c" ] && [ -d "$W/gen4-c" ] || die "Run build.sh (full build) first."
export GEN=$W/gen4-incr TAG=incr JOBS
ST=logs/incr.stats; : > "$ST"
rm -rf "$W/gen4-incr" "$W/obj4-c-incr" "$W/incr"
cp -a "$W/gen4-c" "$W/gen4-incr"; cp -a "$W/obj4-c" "$W/obj4-c-incr"
rm -f "$W/obj4-c-incr/libgame.so"
res() { echo "$1 | $(grep -E 'uebersetzt_dateien|^wall_s|^summe_user' logs/build-c-incr.stats | tr '\n' ' ')link: $(grep link_s logs/build-c-incr.stats)" | tee -a "$ST"; }

echo "== A: no change"
bash "$(dirname "$0")/compile.sh" c > /dev/null; res "A no change"

echo "== B: five chunks touched"
files=$(ls "$GEN"/main/main_*.c | grep -v table | awk 'NR%180==7' | head -5)
for f in $files; do touch "$f"; echo "// geaendert" >> "$f"; done
bash "$(dirname "$0")/compile.sh" c > /dev/null; res "B 5 chunks (main, medium-sized)"

echo "== C: 7 SDK functions as HLE stubs (generator change)"
python3 scripts/recomp/eh_gen.py gen sdk work/exefs/sdk 0x7006000000 "$W/incr/sdk" --simd c --hle scripts/recomp/test/hle_symbols.txt 2>&1 | grep wrote
changed=$(for f in "$W"/incr/sdk/*.c; do cmp -s "$f" "$GEN/sdk/$(basename "$f")" || echo "$f"; done | wc -l)
rsync -rc --delete "$W/incr/sdk/" "$GEN/sdk/"   # without -t: only changed files get a new timestamp
bash "$(dirname "$0")/compile.sh" c > /dev/null; res "C SDK with HLE: $changed of $(ls "$W/incr/sdk" | wc -l) SDK chunks changed"
rm -rf "$W/gen4-incr" "$W/obj4-c-incr" "$W/incr"
echo "done"
