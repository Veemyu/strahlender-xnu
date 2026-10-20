#!/bin/bash
# Läuft auf dem Linux host: baut die C++-Qt-Hülle (rt-bdsp/app/linux, CMake) nach work/recomp/qt-host. Fehlen Qt6-Entwicklungspakete, endet das Skript mit
# Code 3 und nennt den Installationsbefehl (Nutzer führt ihn selbst aus; hier wird nichts installiert).
source "$(dirname "$0")/common.sh"
"${TIMEV[@]}" bash scripts/recomp/rt-bdsp/app/linux/build_qt.sh "$@"
