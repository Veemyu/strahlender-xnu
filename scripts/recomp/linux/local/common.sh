# Shared settings for the local Linux build scripts (via `source`). All paths are relative to the repository root.
R=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)
cd "$R" || exit 1
export PATH="$HOME/.local/bin:$PATH"
LAS=scripts/recomp/upstream
W=${RECOMP_DIR:-work/recomp}
JOBS=${JOBS:-$(python3 scripts/recomp/parallel_jobs.py)}  # override with JOBS=n
TIMEV=(/usr/bin/time -f "%e s wall  %U s user  %S s sys  %M KB maxrss")

# Module bases as in the spike's gen_all.sh
base_of() { case "$1" in main) echo 0x7000000000;; sdk) echo 0x7006000000;; subsdk0) echo 0x7007000000;; rtld) echo 0x7008000000;; esac; }

source scripts/recomp/linux/cpu_flags.sh
CPU_FLAGS=$(bdsp_cpu_flags) || exit $?
# Keep the historical function name for callers; CPU_FLAGS also handles AArch64.
cflags_x86() { echo "-fno-strict-aliasing -fvisibility=hidden -w -fPIC $CPU_FLAGS -I scripts/recomp/rt -I $LAS/runtime"; }

die() { echo "ERROR: $*" >&2; exit 1; }
