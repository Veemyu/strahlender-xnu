#!/bin/bash
# Läuft auf dem Linux host: erzeugt das C aller vier Module mit dem LAS-Lifter (eh_gen.py) und misst Zeit/RAM/Größe.
# Aufruf: gen.sh [c|asm] [modul ...]      Standard: c, alle vier Module nacheinander (wie gen_all.sh auf dem Mac)
#   c   = portables C (simd.h), der Weg für x86-Hosts
#   asm = Inline-asm für AArch64-Hosts; auf dem x86-Linux host nur zum Vergleich erzeugbar (nicht übersetzbar)
# Ausgabe: work/recomp/gen4-<modus>/<modul>/*.c, logs/gen-<modus>.stats (Zahlen), work/recomp/gen4-<modus>.sha256 (Baumprüfsumme)
source "$(dirname "$0")/common.sh"
MODE=${1:-c}; shift
case "$MODE" in c|asm) ;; *) die "Modus muss c oder asm sein, nicht '$MODE'.";; esac
mods=("$@"); [ ${#mods[@]} -eq 0 ] && mods=(rtld main sdk subsdk0)
OUT=$W/gen4-$MODE
ST=logs/gen-$MODE.stats
mkdir -p "$OUT" logs
for m in "${mods[@]}"; do [ -f "work/exefs/$m" ] || die "work/exefs/$m fehlt (sync.sh)."; done
: > "$ST"
tot0=$(date +%s.%N)
for m in "${mods[@]}"; do
  glog=logs/gen-$MODE-$m.log
  /usr/bin/time -f "TIME %e %U %S %M" python3 scripts/recomp/eh_gen.py gen "$m" "work/exefs/$m" "$(base_of "$m")" "$OUT/$m" --simd "$MODE" > "$glog" 2>&1 \
    || { tail -20 "$glog"; die "Generator für $m fehlgeschlagen (Log: $glog)."; }
  tm=$(grep '^TIME' "$glog" | tail -1)
  fn=$(grep -o "[0-9]* functions" "$glog" | head -1 | cut -d' ' -f1)
  ch=$(ls "$OUT/$m"/*.c | wc -l)
  bytes=$(cat "$OUT/$m"/*.c | wc -c)
  echo "modul=$m funktionen=$fn dateien=$ch c_bytes=$bytes $tm" | tee -a "$ST"
done
tot1=$(date +%s.%N)
echo "gesamt_wall_s=$(awk -v a="$tot1" -v b="$tot0" 'BEGIN{printf "%.1f", a-b}')" | tee -a "$ST"
echo "c_bytes_gesamt=$(cat "$OUT"/*/*.c | wc -c)" | tee -a "$ST"
# Prüfsumme des Baums (Namen + Inhalt) für den Vergleich mit dem Mac-Lauf
(cd "$OUT" && for f in $(ls */*.c | sort); do echo "$f $(sha256sum < "$f" | cut -c1-16)"; done) > "$W/gen4-$MODE.sha256"
echo "baum_sha256=$(sha256sum < "$W/gen4-$MODE.sha256" | cut -c1-16)" | tee -a "$ST"
