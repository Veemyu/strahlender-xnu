#!/bin/bash
# Inkrementelle Neuerzeugung: erzeugt das C neu nach work/recomp/gen4.new und überträgt nur Dateien mit geändertem Inhalt
# nach work/recomp/gen4 (Zeitstempel unveränderter Chunks bleiben, build_all.sh übersetzt dann nur die geänderten).
# Aufruf: regen_inc.sh [modul ...]     (Standard: alle vier Module). Danach: build_all.sh 4
set -euo pipefail
cd "$(dirname "$0")/../.."
NEW=work/recomp/gen4.new
rm -rf "$NEW"
OUT=$NEW scripts/recomp/gen_all.sh "$@"
mkdir -p work/recomp/gen4
# --checksum: Inhalt statt Zeit/Größe vergleichen; --delete: veraltete Chunks entfernen (nur Module, die neu erzeugt wurden)
for d in "$NEW"/*/; do
  m=$(basename "$d")
  mkdir -p "work/recomp/gen4/$m"
  rsync -rc --delete --itemize-changes "$d" "work/recomp/gen4/$m/" | { grep -c '^>f' || true; } | xargs echo "$m: geänderte Dateien:"
done
rm -rf "$NEW"
