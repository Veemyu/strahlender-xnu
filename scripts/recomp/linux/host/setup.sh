#!/bin/bash
# Check Linux tools and Python dependencies without installing anything.
# Compare the checksums of the inputs against the manifest from the Mac. Reports missing packages as an install list.
source "$(dirname "$0")/common.sh"
missing=()
for t in clang gcc make cmake ninja rsync python3 git; do command -v "$t" >/dev/null || missing+=("$t"); done
command -v ld.lld >/dev/null || echo "NOTE: ld.lld is missing (package 'lld'): linking with ld.bfd, slower; the LAS Makefile uses -fuse-ld=lld."
command -v ccache >/dev/null || echo "NOTE: ccache is missing (optional)."
[ -x /usr/bin/time ] || missing+=("time")
echo "== Tools"
{ uname -srm; clang --version | head -1; gcc --version | head -1; make --version | head -1; python3 --version; nproc; free -g | sed -n 2p; df -h "$R" | tail -1; } 2>&1
echo "AArch64 target of clang: $(clang --target=aarch64-linux-gnu -x c -c /dev/null -o /dev/null 2>&1 && echo ok)"
echo "x86-64-v3 (AVX2/FMA): $(grep -o -w -E 'avx2|fma|bmi2' /proc/cpuinfo | sort -u | tr '\n' ' ')"
echo "== Python packages"
python3 -c "import lz4, capstone, unicorn; from importlib.metadata import version as v; print('lz4', v('lz4'), 'capstone', v('capstone'), 'unicorn', v('unicorn'))" \
  || die "Install the Python build dependencies yourself: lz4, capstone, unicorn. See docs/BUILD.md."
echo "== Input checksums"
if [ -f manifest/exefs.sha256 ]; then
  sha256sum -c manifest/exefs.sha256 || die "Checksums do not match the manifest from the Mac (run sync.sh again)."
else
  die "manifest/exefs.sha256 is missing (run sync.sh)."
fi
if [ ${#missing[@]} -gt 0 ]; then
  echo "MISSING PACKAGES (to be installed by the user): ${missing[*]}"
  exit 1
fi
echo "Setup ok."
