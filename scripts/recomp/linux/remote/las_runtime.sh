#!/bin/bash
# Läuft auf dem Linux host: baut den Linux-Pfad der LASRecomp-Laufzeit (runtime/platform/linux.c, Kern, Dienste, HLE) ohne Grafik,
# soweit die Header (SDL3, FFmpeg, Vulkan, shaderc) vorhanden sind. Meldet je Quelldatei ok/Fehler samt erster Fehlerzeile.
# Aufruf: las_runtime.sh        Ausgabe: logs/las-runtime.stats, Objekte nach work/recomp/lasrt/ (ohne Spieldaten)
source "$(dirname "$0")/common.sh"
RT=$LAS/runtime
OUT=$W/lasrt
rm -rf "$OUT"; mkdir -p "$OUT"
ST=logs/las-runtime.stats; : > "$ST"
echo "Fehlende Entwicklungspakete (pkg-config): $(for p in sdl3 libavformat libavcodec libavutil libswscale vulkan shaderc; do pkg-config --exists $p 2>/dev/null || printf '%s ' $p; done)" | tee -a "$ST"
FL="-O2 -g -fno-strict-aliasing -w -fPIC -Wno-format $(pkg-config --cflags sdl3 libavformat libavcodec libavutil libswscale vulkan shaderc)"
ok=0; bad=0
for f in $RT/*.c $RT/hle/*.c $RT/services/*.c $RT/nvn/*.c $RT/nvn/maxwell/*.c $RT/platform/linux.c; do
  [ -f "$f" ] || continue
  rel=${f#$RT/}
  o="$OUT/$(echo "$rel" | tr / _).o"
  if err=$(cd "$LAS" && clang $FL -Iruntime -Iruntime/nvn -c "runtime/$rel" -o "$R/$o" 2>&1); then ok=$((ok + 1)); else
    bad=$((bad + 1)); echo "FEHLER $rel: $(echo "$err" | grep -m1 'error' | cut -c1-150)" | tee -a "$ST"
  fi
done
echo "quellen_ok=$ok quellen_fehler=$bad" | tee -a "$ST"
echo "linux.c: $([ -f "$OUT/platform_linux.c.o" ] && echo 'übersetzt' || echo 'nicht übersetzt')" | tee -a "$ST"
