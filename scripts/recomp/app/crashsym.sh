#!/bin/bash
# Symbolicates a crash report of the app: guest functions (f_70xxxxxxxx in the host frame, addresses in the guest ring) get IL2CPP names
# from work/recomp/il2sym.tsv; host addresses without a name can be resolved with atos.
#   crashsym.sh <log-or-ips-file>                       add guest names (output on stdout)
#   crashsym.sh --atos <load-address> <address>...      host addresses: atos -o BDSP -l <load-address> (the load address is in the .ips report
#                                                       under usedImages or "Binary Images" for BDSP)
# Requirement: python3 -I scripts/recomp/il2sym.py has created work/recomp/il2sym.tsv (names only, no game bytes).
# The system crash report is under ~/Library/Logs/DiagnosticReports/BDSP-*.ips, the app's runtime log under
# ~/Library/Logs/dev.local.xnubdsp/bdsp.log (previous run: bdsp.prev.log).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$ROOT"
if [ "${1:-}" = "--atos" ]; then
  [ $# -ge 3 ] || { echo "Usage: crashsym.sh --atos <load-address> <address>..." >&2; exit 2; }
  LOAD="$2"; shift 2
  BIN="${BDSP_BIN:-work/builds/macos-recomp/BDSP.app/Contents/MacOS/BDSP}"
  [ -f "$BIN" ] || { echo "ERROR: $BIN not found (set BDSP_BIN)" >&2; exit 10; }
  exec atos -o "$BIN" -arch arm64 -l "$LOAD" "$@"
fi
[ $# -eq 1 ] && [ -f "$1" ] || { echo "Usage: crashsym.sh <log-or-ips-file>  |  --atos <load-address> <address>..." >&2; exit 2; }
[ -f work/recomp/il2sym.tsv ] || { echo "ERROR: work/recomp/il2sym.tsv missing: python3 -I scripts/recomp/il2sym.py" >&2; exit 10; }
# f_70002c1d90 -> "f_ 70002c1d90" (so the word boundary of the address detection applies), then join again
sed -E 's/\bf_(70[0-9a-f]{8})/f_ \1/g' "$1" | python3 scripts/recomp/symres.py | sed -E 's/f_ (70[0-9a-f]{8})/f_\1/g'
