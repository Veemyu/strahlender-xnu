#!/bin/bash
# Check Linux tools and Python dependencies without installing anything.
# Compare the checksums of the inputs against work/exefs.sha256 (if present). Reports missing packages as an install list.
source "$(dirname "$0")/common.sh"
missing=()
for t in clang python3; do command -v "$t" >/dev/null || missing+=("$t"); done
command -v cmake >/dev/null || echo "NOTE: cmake is missing (needed only for the Qt frontend, vk_qt_build.sh)."
command -v rsync >/dev/null || echo "NOTE: rsync is missing (needed only for incr_test.sh)."
command -v ld.lld >/dev/null || echo "NOTE: ld.lld is missing (package 'lld'): linking with ld.bfd, slower; the LAS Makefile uses -fuse-ld=lld."
command -v ccache >/dev/null || echo "NOTE: ccache is missing (optional)."
[ -x /usr/bin/time ] || missing+=("time")
echo "== Tools"
{ uname -srm; clang --version | head -1; python3 --version; nproc; free -g | sed -n 2p; df -h "$R" | tail -1; } 2>&1
echo "AArch64 target of clang: $(clang --target=aarch64-linux-gnu -x c -c /dev/null -o /dev/null 2>&1 && echo ok)"
echo "Local game CPU target: $CPU_FLAGS (${BDSP_CPU_TARGET:-native})"
echo "== Python packages"
python3 -c "import lz4, capstone, unicorn; from importlib.metadata import version as v; print('lz4', v('lz4'), 'capstone', v('capstone'), 'unicorn', v('unicorn'))" \
  || die "Install the Python build dependencies yourself: lz4, capstone, unicorn. See docs/BUILD.md."
echo "== Input checksums"
if [ -f work/exefs.sha256 ]; then
  sha256sum -c work/exefs.sha256 || die "Checksums do not match work/exefs.sha256 (inputs changed or copied incorrectly)."
else
  echo "NOTE: work/exefs.sha256 is missing; inputs are not checked against a manifest (optional, see docs/BUILD.md)."
fi
if [ ${#missing[@]} -gt 0 ]; then
  echo "MISSING PACKAGES (to be installed by the user): ${missing[*]}"
  exit 1
fi
echo "Setup ok."
