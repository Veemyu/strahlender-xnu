#!/bin/bash
# Runs locally on Linux: builds the Linux path of the LASRecomp runtime (runtime/platform/linux.c, core, services, HLE) without graphics,
# as far as the headers (SDL3, FFmpeg, Vulkan, shaderc) are present. Reports ok/error per source file, including the first error line.
# Usage: las_runtime.sh        Output: logs/las-runtime.stats, objects to work/recomp/lasrt/ (no game data)
source "$(dirname "$0")/common.sh"
RT=$LAS/runtime
OUT=$W/lasrt
rm -rf "$OUT"; mkdir -p "$OUT"
ST=logs/las-runtime.stats; : > "$ST"
echo "Missing development packages (pkg-config): $(for p in sdl3 libavformat libavcodec libavutil libswscale vulkan shaderc; do pkg-config --exists $p 2>/dev/null || printf '%s ' $p; done)" | tee -a "$ST"
FL="-O2 -g -fno-strict-aliasing -w -fPIC -Wno-format $(pkg-config --cflags sdl3 libavformat libavcodec libavutil libswscale vulkan shaderc)"
ok=0; bad=0
for f in $RT/*.c $RT/hle/*.c $RT/services/*.c $RT/nvn/*.c $RT/nvn/maxwell/*.c $RT/platform/linux.c; do
  [ -f "$f" ] || continue
  rel=${f#$RT/}
  o="$OUT/$(echo "$rel" | tr / _).o"
  if err=$(cd "$LAS" && clang $FL -Iruntime -Iruntime/nvn -c "runtime/$rel" -o "$R/$o" 2>&1); then ok=$((ok + 1)); else
    bad=$((bad + 1)); echo "ERROR $rel: $(echo "$err" | grep -m1 'error' | cut -c1-150)" | tee -a "$ST"
  fi
done
echo "sources_ok=$ok sources_failed=$bad" | tee -a "$ST"
echo "linux.c: $([ -f "$OUT/platform_linux.c.o" ] && echo 'compiled' || echo 'not compiled')" | tee -a "$ST"
