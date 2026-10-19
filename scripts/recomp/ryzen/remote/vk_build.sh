#!/bin/bash
# Läuft auf dem Ryzen: baut rt-bdsp mit der Vulkan-Fassung der NVN-Schicht (NVN_BACKEND=vulkan) und bindet sie mit den übersetzten Gastmodulen
# (work/recomp/obj4-c, c-Modus) zu work/recomp/bdsp_boot_vk. Header: ~/xnu-recomp/include-vk (vk_sync_deps.sh), Bibliotheken per Vollpfad.
# Aufruf: vk_build.sh [-DMakro ...]
source "$(dirname "$0")/common.sh"
[ -d include-vk/vulkan ] || die "include-vk fehlt (Mac: scripts/recomp/ryzen/vk_sync_deps.sh)."
[ -d "$W/obj4-c" ] || die "$W/obj4-c fehlt (erst scripts/recomp/ryzen/build.sh)."
for l in /usr/lib64/libvulkan.so.1 /usr/lib64/libSDL3.so.0 /usr/lib64/libshaderc_shared.so.1; do [ -e "$l" ] || die "Laufzeitbibliothek $l fehlt."; done
export NVN_BACKEND=vulkan OBJ=$W/obj4-c
"${TIMEV[@]}" scripts/recomp/rt-bdsp/build.sh "$@" || die "Bau fehlgeschlagen."
ls -la "$W/bdsp_boot_vk"
