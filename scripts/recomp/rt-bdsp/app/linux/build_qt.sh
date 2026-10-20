#!/bin/bash
# Baut die Linux-Qt-Hülle (bdsp_qt_host.cpp) mit CMake nach work/recomp/qt-host (Binärdatei work/recomp/qt-host/bdsp_qt_host, daneben lproj/).
# Prüft vorher CMake, einen C++-Compiler und Qt6 Widgets (Header, nicht nur die Laufzeit). Fehlt etwas, nennt das Skript den Installationsbefehl
# aus deps.txt für diese Distribution und endet mit Code 3; es installiert nichts.
# Aufruf: build_qt.sh [--check]        --check: nur prüfen
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../../../../.." && pwd)
BUILD="$ROOT/work/recomp/qt-host"
[ "$(uname -s)" = Linux ] || { echo "Die Qt-Hülle gibt es nur für Linux." >&2; exit 2; }

family() {  # apt | dnf | pacman nach /etc/os-release (ID und ID_LIKE)
  local id
  id=$( . /etc/os-release 2>/dev/null; echo "${ID:-} ${ID_LIKE:-}")
  case " $id " in
    *" debian "*|*" ubuntu "*) echo apt;;
    *" fedora "*|*" rhel "*) echo dnf;;
    *" arch "*) echo pacman;;
    *) echo unbekannt;;
  esac
}
install_hint() {
  local f line
  f=$(family)
  line=$(grep -E "^$f \\|" "$HERE/deps.txt" | head -1 || true)
  if [ -n "$line" ]; then
    echo "Installationsbefehl ($f, siehe deps.txt):" >&2
    echo "  $(echo "$line" | cut -d'|' -f2 | sed 's/^ *//;s/ *$//')" >&2
  else
    echo "Distribution unbekannt: Pakete siehe $HERE/deps.txt" >&2
  fi
}

missing=()
command -v cmake >/dev/null || missing+=("cmake")
command -v c++ >/dev/null || command -v g++ >/dev/null || command -v clang++ >/dev/null || missing+=("C++-Compiler")
if ! { command -v pkg-config >/dev/null && pkg-config --exists Qt6Widgets; } && [ ! -d /usr/include/qt6/QtWidgets ] && [ ! -d /usr/include/x86_64-linux-gnu/qt6/QtWidgets ]; then
  missing+=("Qt6 Widgets (Entwicklungsdateien)")
fi
if [ ${#missing[@]} -gt 0 ]; then
  echo "Fehlt: ${missing[*]}" >&2
  install_hint
  exit 3
fi
[ "${1:-}" = "--check" ] && { echo "Qt6-Bauvoraussetzungen vorhanden."; exit 0; }

mkdir -p "$BUILD"
cmake -S "$HERE" -B "$BUILD" -DCMAKE_BUILD_TYPE=Release > "$BUILD/configure.log" 2>&1 || { tail -n 20 "$BUILD/configure.log" >&2; exit 4; }
cmake --build "$BUILD" -j"$(nproc)" > "$BUILD/build.log" 2>&1 || { tail -n 30 "$BUILD/build.log" >&2; exit 4; }
echo "gebaut: $BUILD/bdsp_qt_host"
