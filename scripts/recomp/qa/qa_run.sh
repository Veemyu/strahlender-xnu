#!/bin/bash
# QA run of the recompiled BDSP runtime (Mac, Metal, headless).
#   qa_run.sh <scenario> [options]      starts scenarios/<scenario>.txt, writes work/recomp/qa/<scenario>-<time>/report.md (+ report.json)
#   qa_run.sh --list                    list the scenarios
#   qa_run.sh --report <run folder>     regenerate the report from existing logs
# Options: --bin PATH (default work/recomp/qa/bin/bdsp_boot, a copy, so rebuilds by other agents do not interfere; --bin work/recomp/bdsp_boot
#          takes the current version) · --img FOLDER (default work/recomp/img_gfx2) · --no-il2sym · --timeout S (overrides) · --label TEXT
# Only one run at a time (lock file work/recomp/qa/.lock). Save: each phase works on a copy of
# work/recomp/qa/save_base (state 0396a4a62735), the initial state stays unchanged. No sound, nothing in the repo except these scripts.
# Exit code: 0 = all checks passed, 1 = at least one check failed, 2 = usage/environment error, 3 = not enough space.
set -euo pipefail
cd "$(dirname "$0")/../../.."
exec python3 -I scripts/recomp/qa/qa_run.py "$@"
