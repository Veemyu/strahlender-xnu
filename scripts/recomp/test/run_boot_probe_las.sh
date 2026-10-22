#!/bin/bash
# Step 5, extension: like run_boot_probe.sh, but IPC/service layer (ipc.c, am/misc/acc/hid_set/time) from scripts/recomp/upstream/runtime.
# Prerequisite: run_boot_probe.sh already ran (images and .syms.json under work/recomp/spike2/boot).
set -euo pipefail
cd "$(dirname "$0")/../../.."
S=work/recomp/spike2/boot
L=scripts/recomp/upstream/runtime
OBJ=${OBJ:-work/recomp/obj4}
clang -O1 -w -DUSE_LAS_IPC -I scripts/recomp/rt -I $L -c scripts/recomp/test/boot_probe.c -o $S/boot_probe_las.o
for f in $L/ipc.c $L/services/am.c $L/services/misc.c $L/services/acc.c $L/services/hid_set.c $L/services/time.c scripts/recomp/test/las_shim.c; do
  clang -O1 -w -I $L -c $f -o $S/las_$(basename $f .c).o
done
clang -o $S/boot_probe_las $S/boot_probe_las.o $S/las_*.o $OBJ/*.o
START=$(python3 -c "
import json
m = json.load(open('$S/sdk.syms.json'))
print(hex(next(v for k, v in m.items() if k.startswith('_ZN2nn4init5Start'))))")
$S/boot_probe_las $S "$START"
