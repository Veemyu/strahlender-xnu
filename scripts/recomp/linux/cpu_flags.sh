#!/bin/bash
# Local game builds target the build CPU; distributed installer binaries stay portable.
# BDSP_CPU_TARGET=portable builds for the architecture baseline instead.
bdsp_cpu_flags() {
  local arch=${BDSP_CPU_ARCH:-$(uname -m)}
  case "${BDSP_CPU_TARGET:-native}:$arch" in
    native:x86_64|native:amd64) echo '-march=native';;
    native:aarch64|native:arm64) echo '-mcpu=native';;
    portable:x86_64|portable:amd64) echo '-march=x86-64 -mtune=generic';;
    portable:aarch64|portable:arm64) echo '-march=armv8-a';;
    *) echo "Unsupported CPU target: ${BDSP_CPU_TARGET:-native}/$arch" >&2; return 2;;
  esac
}
# Resolve native compiler features for cache invalidation when a work folder moves hosts.
bdsp_cpu_signature() {
  local compiler=${1:-clang} flags
  flags=$(bdsp_cpu_flags) || return
  printf '%s\n' "$flags"
  "$compiler" $flags -dM -E -x c /dev/null
}
