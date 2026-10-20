#!/bin/bash
# Check installed packages on the configured Linux host. No copying, downloads, or installation.
# Usage: check_deps.sh [--qt]
set -euo pipefail
source "$(dirname "$0")/lib.sh"
rz_require
case "${1:-}" in
  "") extra="";;
  --qt) extra="; linux_require_qt";;
  *) rz_die "Usage: check_deps.sh [--qt]";;
esac
rz_ssh "cd ~/$RZ_DIR && source scripts/recomp/linux/deps.sh && linux_require_runtime$extra"
