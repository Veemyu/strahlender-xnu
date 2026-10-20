# Gemeinsame Einstellungen der Linux host-Skripte (per `source`). Alle Pfade relativ zum Arbeitsordner ~/xnu-recomp.
R=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)
cd "$R" || exit 1
export PATH="$HOME/.local/bin:$PATH"
LAS=scripts/recomp/upstream
W=work/recomp
JOBS=${JOBS:-10}                    # parallele Compiler (12 Threads, 30 GB RAM)
TIMEV=(/usr/bin/time -f "%e s wall  %U s user  %S s sys  %M KB maxrss")

# Modulbasen wie gen_all.sh des Spikes
base_of() { case "$1" in main) echo 0x7000000000;; sdk) echo 0x7006000000;; subsdk0) echo 0x7007000000;; rtld) echo 0x7008000000;; esac; }

# C-Flags des Gesamtbaus (wie scripts/recomp/build_all.sh; x86: AVX2/FMA wie das LAS-Makefile, -fPIC für die Bibliothek)
cflags_x86() { echo "-fno-strict-aliasing -fvisibility=hidden -w -fPIC -march=x86-64-v3 -I scripts/recomp/rt -I $LAS/runtime"; }

die() { echo "FEHLER: $*" >&2; exit 1; }
