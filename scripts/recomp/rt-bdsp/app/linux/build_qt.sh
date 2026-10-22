#!/bin/bash
# Builds the Linux Qt shell (bdsp_qt_host.cpp) with CMake into work/recomp/qt-host (binary work/recomp/qt-host/bdsp_qt_host, with lproj/ next to it).
# First checks for CMake, a C++ compiler and Qt6 Widgets (headers, not just the runtime). If something is missing, the script prints the install command
# from deps.txt for this distribution and exits with code 3; it installs nothing.
# Usage: build_qt.sh [--check]        --check: only check
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../../../../.." && pwd)
BUILD="$ROOT/work/recomp/qt-host"
[ "$(uname -s)" = Linux ] || { echo "The Qt shell exists only for Linux." >&2; exit 2; }

family() {  # apt | dnf | pacman according to /etc/os-release (ID and ID_LIKE)
  local id
  id=$( . /etc/os-release 2>/dev/null; echo "${ID:-} ${ID_LIKE:-}")
  case " $id " in
    *" debian "*|*" ubuntu "*) echo apt;;
    *" fedora "*|*" rhel "*) echo dnf;;
    *" arch "*) echo pacman;;
    *) echo unknown;;
  esac
}
install_hint() {
  local f line
  f=$(family)
  line=$(grep -E "^$f \\|" "$HERE/deps.txt" | head -1 || true)
  if [ -n "$line" ]; then
    echo "Install command ($f, see deps.txt):" >&2
    echo "  $(echo "$line" | cut -d'|' -f2 | sed 's/^ *//;s/ *$//')" >&2
  else
    echo "Unknown distribution: see $HERE/deps.txt for the packages" >&2
  fi
}

missing=()
command -v cmake >/dev/null || missing+=("cmake")
command -v c++ >/dev/null || command -v g++ >/dev/null || command -v clang++ >/dev/null || missing+=("C++ compiler")
if ! { command -v pkg-config >/dev/null && pkg-config --exists Qt6Widgets; } && [ ! -d /usr/include/qt6/QtWidgets ] && [ ! -d /usr/include/x86_64-linux-gnu/qt6/QtWidgets ]; then
  missing+=("Qt6 Widgets (development files)")
fi
if [ ${#missing[@]} -gt 0 ]; then
  echo "Missing: ${missing[*]}" >&2
  install_hint
  exit 3
fi
[ "${1:-}" = "--check" ] && { echo "Qt6 build prerequisites present."; exit 0; }

cd "$ROOT"
python3 scripts/recomp/app/game_icons.py linux --source "${BDSP_ICON_SOURCE:-work/recomp/icons/source}" \
  --output work/recomp/icons/linux --executable work/recomp/qt-host/bdsp_qt_host

mkdir -p "$BUILD"
cmake -S "$HERE" -B "$BUILD" -DCMAKE_BUILD_TYPE=Release > "$BUILD/configure.log" 2>&1 || { tail -n 20 "$BUILD/configure.log" >&2; exit 4; }
cmake --build "$BUILD" -j"$(nproc)" > "$BUILD/build.log" 2>&1 || { tail -n 30 "$BUILD/build.log" >&2; exit 4; }
echo "built: $BUILD/bdsp_qt_host"
