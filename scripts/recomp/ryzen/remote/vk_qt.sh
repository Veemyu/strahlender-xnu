#!/bin/bash
# Läuft auf dem Ryzen: startet die Qt-Hülle (C++, rt-bdsp/app/linux, gebaut mit vk_qt_build.sh) mit dem Vulkan-Spiel im eingebetteten Fenster. Braucht Xwayland.
# Aufruf: vk_qt.sh [NAME=WERT ...] [Optionen von bdsp_boot_vk]   (Großbuchstaben-Wörter mit = sind Umgebungsvariablen, auch BDSP_QT_SCRIPT)
source "$(dirname "$0")/common.sh"
[ -x "$W/bdsp_boot_vk" ] || die "$W/bdsp_boot_vk fehlt (vk_build.sh)."
[ -d work/romfs ] || die "work/romfs fehlt auf dem Ryzen (vk_sync.sh --daten)."
export BDSP_IMG=${BDSP_IMG:-$W/img_gfx}
ARGS=()
for a in "$@"; do
  case "$a" in [A-Z]*=*) export "$a";; *) ARGS+=("$a");; esac
done
export SDL_AUDIODRIVER=dummy
QT_BIN=$W/qt-host/bdsp_qt_host
[ -x "$QT_BIN" ] || die "$QT_BIN fehlt (Mac: scripts/recomp/ryzen/vk_qt_build.sh; braucht qt6-qtbase-devel)."
echo "# Start Qt-Hülle: ${ARGS[*]}"
"${TIMEV[@]}" "$QT_BIN" --game "$W/bdsp_boot_vk" -- ${ARGS[@]+"${ARGS[@]}"}
echo "# Ende, Code $?"
