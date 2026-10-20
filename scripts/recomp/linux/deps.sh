#!/bin/bash
# System development dependencies for the native Linux runtime. Never downloads or installs.

linux_deps_fail() {
  echo "Missing Linux development dependency: $*" >&2
  echo "See docs/BUILD.md, section 6, and scripts/recomp/rt-bdsp/app/linux/deps.txt." >&2
  return 3
}

linux_shaderc_module() {
  local module
  for module in shaderc_shared shaderc; do
    if pkg-config --exists "$module"; then echo "$module"; return 0; fi
  done
  linux_deps_fail "shaderc (Fedora: libshaderc-devel; Debian: libshaderc-dev)"
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
    $(pkg-config --cflags vulkan) - >/dev/null 2>&1 || {
      linux_deps_fail "Vulkan Memory Allocator headers (Fedora: VulkanMemoryAllocator-devel)"; return 3;
    }
  if [ -z "${BDSP_NO_MOVIE:-}" ]; then
    for module in libavcodec libavformat libavutil; do
      pkg-config --exists "$module" || { linux_deps_fail "$module development files"; return 3; }
    done
  fi
}

linux_vulkan_cflags() { pkg-config --cflags vulkan sdl3 "$(linux_shaderc_module)"; }
linux_vulkan_libs() { pkg-config --libs vulkan sdl3 "$(linux_shaderc_module)"; }

linux_require_qt() {
  pkg-config --exists Qt6Widgets || { linux_deps_fail "Qt 6 Widgets (Fedora: qt6-qtbase-devel)"; return 3; }
}
