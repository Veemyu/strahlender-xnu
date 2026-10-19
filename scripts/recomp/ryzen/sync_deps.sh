#!/bin/bash
# Optional: überträgt nur die Header (kein Code, keine Bibliotheken) von SDL3 und FFmpeg aus Homebrew auf den Ryzen
# (~/xnu-recomp/deps/include), damit las_runtime.sh die LAS-Laufzeit ohne installierte -devel-Pakete wenigstens übersetzen kann.
# Der Ryzen hat kein Internet; die echten Pakete bleiben die saubere Lösung (Installationsliste in docs/recomp-ryzen.md).
set -euo pipefail
source "$(dirname "$0")/lib.sh"
SDL=${SDL_PREFIX:-/opt/homebrew/opt/sdl3}
FF=${FFMPEG_PREFIX:-/opt/homebrew/opt/ffmpeg}
[ -d "$SDL/include/SDL3" ] || rz_die "SDL3-Header nicht gefunden ($SDL/include/SDL3). Pfad mit SDL_PREFIX=… angeben."
[ -d "$FF/include/libavcodec" ] || rz_die "FFmpeg-Header nicht gefunden ($FF/include/libavcodec). Pfad mit FFMPEG_PREFIX=… angeben."
rz_require
rz_ssh "mkdir -p ~/$RZ_DIR/deps/include"
rsync -a "$SDL/include/SDL3" "$RZ_HOST:$RZ_DIR/deps/include/"
for d in libavcodec libavformat libavutil libswscale libswresample; do [ -d "$FF/include/$d" ] && rsync -a "$FF/include/$d" "$RZ_HOST:$RZ_DIR/deps/include/"; done
rz_info "Header übertragen: ~/$RZ_DIR/deps/include"
