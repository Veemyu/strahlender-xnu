#!/bin/bash
# Läuft auf dem Linux host: startet work/recomp/bdsp_boot_vk (Vulkan-Fassung von rt-bdsp), standardmäßig ohne Fenster (--headless: Offscreen-Rendering in
# Bilder eigener Größe, keine Anzeige nötig, nichts auf dem Desktop des Nutzers) und stumm (die Laufzeit hat keinen Tonpfad).
# Aufruf: vk_run.sh [NAME=WERT ...] [Optionen von bdsp_boot_vk]   (Wörter der Form NAME=WERT mit Großbuchstaben sind Umgebungsvariablen)
#   Standard: --headless --timeout 60 (gehört zur Laufzeit; Umgebung BDSP_IMG=work/recomp/img_gfx)
# Bilder: work/recomp/shots/frame_NNNNN.png (BDSP_SHOT_DIR ändert den Ordner), Shader-Zwischenspeicher: work/recomp/cache/spirv
source "$(dirname "$0")/common.sh"
[ -x "$W/bdsp_boot_vk" ] || die "$W/bdsp_boot_vk fehlt (Mac: scripts/recomp/linux/vk_build.sh)."
[ -d work/romfs ] || die "work/romfs fehlt auf dem Linux host (Mac: scripts/recomp/linux/vk_sync.sh --daten)."
export BDSP_IMG=${BDSP_IMG:-$W/img_gfx}
ARGS=()
for a in "$@"; do
  case "$a" in [A-Z]*=*) export "$a";; *) ARGS+=("$a");; esac
done
[ ${#ARGS[@]} -gt 0 ] || ARGS=(--headless --timeout 60)
export SDL_AUDIODRIVER=dummy
echo "# Start: ${ARGS[*]}"
"${TIMEV[@]}" "$W/bdsp_boot_vk" "${ARGS[@]}"
echo "# Ende, Code $?"
ls -la "${BDSP_SHOT_DIR:-$W/shots}" 2>/dev/null | tail -20
