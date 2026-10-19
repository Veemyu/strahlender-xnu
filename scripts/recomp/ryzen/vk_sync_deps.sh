#!/bin/bash
# Überträgt die Header für den Vulkan-Pfad (nur Header, keine Bibliotheken) vom Mac auf den Ryzen nach ~/xnu-recomp/include-vk/.
# Der Ryzen hat die Laufzeitbibliotheken (libvulkan.so.1, libSDL3.so.0, libshaderc_shared.so.1), aber keine -devel-Pakete und kein Internet.
#   vulkan/, vk_video/   Homebrew vulkan-headers     (Apache-2.0 / MIT)
#   SDL3/                Homebrew sdl3               (zlib)
#   shaderc/             Homebrew shaderc            (Apache-2.0; nur die C-Schnittstelle shaderc.h)
#   vk_mem_alloc.h       VulkanMemoryAllocator       (MIT, AMD); fehlt es unter work/recomp/deps-vk/, wird es von GitHub geladen
# Aufruf: vk_sync_deps.sh      Umgebung: VK_HEADERS, SDL_PREFIX, SHADERC_PREFIX überschreiben die Homebrew-Pfade
set -euo pipefail
source "$(dirname "$0")/lib.sh"
VKH=${VK_HEADERS:-/opt/homebrew/opt/vulkan-headers}
SDL=${SDL_PREFIX:-/opt/homebrew/opt/sdl3}
SC=${SHADERC_PREFIX:-/opt/homebrew/opt/shaderc}
VMA_DIR="$RZ_REPO/work/recomp/deps-vk"
[ -d "$VKH/include/vulkan" ] || rz_die "Vulkan-Header nicht gefunden ($VKH/include/vulkan). Mac: brew install vulkan-headers"
[ -d "$SDL/include/SDL3" ] || rz_die "SDL3-Header nicht gefunden ($SDL/include/SDL3). Mac: brew install sdl3"
[ -f "$SC/include/shaderc/shaderc.h" ] || rz_die "shaderc.h nicht gefunden ($SC/include/shaderc). Mac: brew install shaderc"
if [ ! -f "$VMA_DIR/vk_mem_alloc.h" ]; then
  mkdir -p "$VMA_DIR"
  rz_info "VMA von GitHub laden (MIT) …"
  curl -fsSL -m 120 -o "$VMA_DIR/vk_mem_alloc.h" https://raw.githubusercontent.com/GPUOpen-LibrariesAndSDKs/VulkanMemoryAllocator/master/include/vk_mem_alloc.h \
    || rz_die "vk_mem_alloc.h konnte nicht geladen werden; Datei von Hand nach $VMA_DIR legen."
  curl -fsSL -m 60 -o "$VMA_DIR/LICENSE.txt" https://raw.githubusercontent.com/GPUOpen-LibrariesAndSDKs/VulkanMemoryAllocator/master/LICENSE.txt || true
fi
rz_require
rz_ssh "mkdir -p ~/$RZ_DIR/include-vk"
rsync -a --delete "$VKH/include/vulkan" "$VKH/include/vk_video" "$RZ_HOST:$RZ_DIR/include-vk/"
rsync -a --delete "$SDL/include/SDL3" "$RZ_HOST:$RZ_DIR/include-vk/"
rsync -a --delete "$SC/include/shaderc" "$RZ_HOST:$RZ_DIR/include-vk/"
rsync -a "$VMA_DIR/vk_mem_alloc.h" "$RZ_HOST:$RZ_DIR/include-vk/"
[ -f "$VMA_DIR/LICENSE.txt" ] && rsync -a "$VMA_DIR/LICENSE.txt" "$RZ_HOST:$RZ_DIR/include-vk/LICENSE-VMA.txt"
rz_info "Header unter ~/$RZ_DIR/include-vk: $(rz_ssh "du -sh ~/$RZ_DIR/include-vk | cut -f1")"
rz_info "Laufzeitbibliotheken (Vollpfad-Linken, ohne -dev-Symlinks): $(rz_ssh 'ls /usr/lib64/libvulkan.so.1 /usr/lib64/libSDL3.so.0 /usr/lib64/libshaderc_shared.so.1 2>&1 | tr "\n" " "')"
