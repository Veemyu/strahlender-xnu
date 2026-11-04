# Shared settings for the local Linux build scripts (via `source`). All paths are relative to the repository root.
R=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)
cd "$R" || exit 1
export PATH="$HOME/.local/bin:$PATH"
LAS=scripts/recomp/upstream
W=${RECOMP_DIR:-work/recomp}
JOBS=${JOBS:-$(python3 scripts/recomp/parallel_jobs.py)}  # override with JOBS=n
# GNU time (/usr/bin/time) is not installed everywhere (minimal Fedora, Ubuntu): without it the commands run untimed.
GNU_TIME=""; [ -x /usr/bin/time ] && GNU_TIME=/usr/bin/time
gtime() {  # same -f FORMAT and -o FILE options as GNU time
  if [ -n "$GNU_TIME" ]; then "$GNU_TIME" "$@"; return; fi
  local out=""
  while [ $# -gt 0 ]; do case "$1" in -f) shift 2 ;; -o) out=$2; shift 2 ;; *) break ;; esac; done
  [ -z "$out" ] || echo "0 0 0 0" > "$out"
  "$@"
}
export GNU_TIME; export -f gtime
TIMEV=(gtime -f "%e s wall  %U s user  %S s sys  %M KB maxrss")

# Module bases: one definition for the Mac and Linux scripts
source scripts/recomp/module_bases.sh

source scripts/recomp/linux/cpu_flags.sh
CPU_FLAGS=$(bdsp_cpu_flags) || exit $?
# Keep the historical function name for callers; CPU_FLAGS also handles AArch64.
cflags_x86() { echo "-fno-strict-aliasing -fvisibility=hidden -w -fPIC $CPU_FLAGS -I scripts/recomp/rt -I $LAS/runtime"; }

die() { echo "ERROR: $*" >&2; exit 1; }
