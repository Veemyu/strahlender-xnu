#!/bin/bash
# QA-Lauf der rekompilierten BDSP-Laufzeit (Mac, Metal, headless).
#   qa_run.sh <szenario> [Optionen]     startet scenarios/<szenario>.txt, schreibt work/recomp/qa/<szenario>-<Zeit>/report.md (+ report.json)
#   qa_run.sh --list                    Szenarien auflisten
#   qa_run.sh --report <lauf-ordner>    Bericht aus vorhandenen Logs neu erzeugen
# Optionen: --bin PFAD (Standard work/recomp/qa/bin/bdsp_boot, eine Kopie, damit Neubauten anderer Agenten nicht stören; --bin work/recomp/bdsp_boot
#           nimmt die aktuelle Fassung) · --img ORDNER (Standard work/recomp/img_gfx2) · --no-il2sym · --timeout S (überschreibt) · --label TEXT
# Es läuft immer nur ein Lauf zugleich (Sperrdatei work/recomp/qa/.lock). Spielstand: jede Phase arbeitet auf einer Kopie von
# work/recomp/qa/save_base (Zustand 0396a4a62735), der Ausgangsstand bleibt unverändert. Kein Ton, nichts im Repo außer diesen Skripten.
# Exit-Code: 0 = alle Prüfungen bestanden, 1 = mindestens eine Prüfung gescheitert, 2 = Aufruf-/Umgebungsfehler, 3 = zu wenig Platz.
set -euo pipefail
cd "$(dirname "$0")/../../.."
exec python3 -I scripts/recomp/qa/qa_run.py "$@"
