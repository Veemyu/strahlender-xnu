#!/bin/bash
# System development dependencies for the native Linux runtime. Never downloads or installs.

linux_deps_fail() {
  echo "Missing Linux development dependency: $*" >&2
  echo "See docs/BUILD.md, section 6, and scripts/recomp/runtime/app/linux/deps.txt." >&2
  return 3
}

linux_shaderc_module() {
  local module
  for module in shaderc_shared shaderc; do
    if pkg-config --exists "$module"; then echo "$module"; return 0; fi
  done
  linux_deps_fail "shaderc (Fedora: libshaderc-devel; Debian: libshaderc-dev)"
}

# Verified pinned VMA copy from the installer or install-linux.sh (installer/src/vma.rs, scripts/install/vma_header.py): BDSP_VMA_DIR, else
# the newest verified one in the installer data folder. Searched after the system headers. Never downloads.
linux_vma_flags() {
  local dir="${BDSP_VMA_DIR:-}" candidate
  if [ -z "$dir" ]; then
    for candidate in "${XDG_DATA_HOME:-${HOME:-}/.local/share}"/strahlender-xnu-installer/vma/*/; do
      if [ -f "${candidate}.verified" ]; then dir="${candidate%/}"; fi
    done
  fi
  if [ -n "$dir" ] && [ -f "$dir/.verified" ]; then echo "-idirafter $dir/include"; fi
  return 0
}

linux_require_runtime() {
  command -v pkg-config >/dev/null || { linux_deps_fail pkg-config; return 3; }
  local module
  for module in vulkan sdl3; do
    pkg-config --exists "$module" || { linux_deps_fail "$module"; return 3; }
  done
  linux_shaderc_module >/dev/null || return 3
  command -v "${CXX:-clang++}" >/dev/null || { linux_deps_fail "C++ compiler"; return 3; }
  printf '#if __has_include(<vma/vk_mem_alloc.h>)\n#include <vma/vk_mem_alloc.h>\n#else\n#include <vk_mem_alloc.h>\n#endif\n' | "${CXX:-clang++}" -x c++ -std=c++17 -fsyntax-only \
    $(pkg-config --cflags vulkan) $(linux_vma_flags) - >/dev/null 2>&1 || {
      linux_deps_fail "Vulkan Memory Allocator headers (Fedora: VulkanMemoryAllocator-devel)"; return 3;
    }
  if [ -z "${BDSP_NO_MOVIE:-}" ]; then
    for module in libavcodec libavformat libavutil; do
      pkg-config --exists "$module" || { linux_deps_fail "$module development files"; return 3; }
    done
  fi
}

linux_vulkan_cflags() { pkg-config --cflags vulkan sdl3 "$(linux_shaderc_module)"; linux_vma_flags; }
linux_vulkan_libs() { pkg-config --libs vulkan sdl3 "$(linux_shaderc_module)"; }

linux_require_qt() {
  pkg-config --exists Qt6Widgets || { linux_deps_fail "Qt 6 Widgets (Fedora: qt6-qtbase-devel)"; return 3; }
}
