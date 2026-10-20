#!/bin/bash
# Check Linux tools and Python dependencies without installing anything.
# Prüfsummen der Eingaben gegen das Manifest vom Mac vergleichen. Meldet fehlende Pakete als Installationsliste.
source "$(dirname "$0")/common.sh"
missing=()
for t in clang gcc make cmake ninja rsync python3 git; do command -v "$t" >/dev/null || missing+=("$t"); done
command -v ld.lld >/dev/null || echo "HINWEIS: ld.lld fehlt (Paket 'lld'): Linken mit ld.bfd, langsamer; das LAS-Makefile nutzt -fuse-ld=lld."
command -v ccache >/dev/null || echo "HINWEIS: ccache fehlt (optional)."
[ -x /usr/bin/time ] || missing+=("time")
echo "== Werkzeuge"
{ uname -srm; clang --version | head -1; gcc --version | head -1; make --version | head -1; python3 --version; nproc; free -g | sed -n 2p; df -h "$R" | tail -1; } 2>&1
echo "AArch64-Ziel von clang: $(clang --target=aarch64-linux-gnu -x c -c /dev/null -o /dev/null 2>&1 && echo ok)"
echo "x86-64-v3 (AVX2/FMA): $(grep -o -w -E 'avx2|fma|bmi2' /proc/cpuinfo | sort -u | tr '\n' ' ')"
echo "== Python-Pakete"
python3 -c "import lz4, capstone, unicorn; from importlib.metadata import version as v; print('lz4', v('lz4'), 'capstone', v('capstone'), 'unicorn', v('unicorn'))" \
  || die "Install the Python build dependencies yourself: lz4, capstone, unicorn. See docs/BUILD.md."
echo "== Prüfsummen der Eingaben"
if [ -f manifest/exefs.sha256 ]; then
  sha256sum -c manifest/exefs.sha256 || die "Prüfsummen stimmen nicht mit dem Manifest vom Mac überein (sync.sh erneut ausführen)."
else
  die "manifest/exefs.sha256 fehlt (sync.sh ausführen)."
fi
if [ ${#missing[@]} -gt 0 ]; then
  echo "FEHLENDE PAKETE (Installation durch den Nutzer): ${missing[*]}"
  exit 1
fi
echo "Einrichtung ok."
