#!/usr/bin/env bash
# Leaves only third-party build output in installer/target and installer/extract/target, so the CI cache stays small
# and a cached release build never reuses an installer binary. Usage: prune_cargo_cache.sh (from the repository root)
set -euo pipefail
for target in installer/target installer/extract/target; do
  [ -d "$target" ] || continue
  find "$target" -type d -name incremental -prune -exec rm -rf {} +
  # Own crates (installer, bdsp-extract, vendored winit patch is a path dependency too) and the binaries linked from them.
  find "$target" -maxdepth 4 \( -path '*/deps/*' -o -path '*/.fingerprint/*' -o -path '*/build/*' -o -path '*/release/*' -o -path '*/debug/*' \) \
    \( -name 'strahlender?xnu?installer*' -o -name 'bdsp?extract*' -o -name 'libbdsp?extract*' -o -name 'iced?winit*' -o -name 'libiced?winit*' \
       -o -name 'firmware_import*' -o -name 'installer_icons*' -o -name 'installer_release*' -o -name 'installer_setup*' \
       -o -name 'installer_update*' -o -name 'ips_patch*' \) -exec rm -rf {} + 2>/dev/null || true
done
du -sh installer/target installer/extract/target 2>/dev/null || true
