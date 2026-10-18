# Referenz: Static-Recompilation-Projekte (Stand 2026-10-18)

Eigene Zusammenfassung einer Recherche (nur lesend, nichts geklont, kein Code übernommen). Quellen: `peiikai/LASRecomp` (MIT, Link's Awakening Switch) und `raulzrrs/letsgo-recomp` (baut auf LASRecomp auf).

## Befund
- Beide Projekte übersetzen den kompletten NSO-Code (`main`, `sdk`) per Skript-Pipeline nach C, ersetzen Switch-OS (SVC, IPC) und NVN durch eine eigene Runtime und übersetzen Maxwell-Shader zur Laufzeit nach MSL (Metal).
- macOS arm64 ist dort Zielplattform (Metal, Guest-Speicherfenster per `mach_vm_allocate`). iOS/iPadOS und JIT-Freiheit werden nicht behandelt.
- Die Zielspiele (Link's Awakening, Let's Go) sind **keine Unity/IL2CPP-Spiele** (LAS: Grezzo-Eigenengine laut Sekundärquelle, nicht direkt geprüft). Metadata, `libil2cpp` und Funktionszeiger-Tabellen von IL2CPP wurden dort nicht untersucht.
- Spielcode wird beim Nutzer erzeugt und kompiliert (`dlopen`), das geht auf iPadOS nicht (kein Compiler) und würde Nintendo-Code ausliefern.
- LASRecomp: Beta, Release `beta_4`, MIT-Lizenz mit Ausschluss von Spieldateien; das README nennt den Code „almost exclusively“ KI-generiert. Keine Spieldateien im Repo.

## Bewertung für BDSP
- Nützlich als Checkliste für Switch-Dienste und Grafik-Imports, nicht als Ausführungsweg.
- BDSP hat 166.095 Funktionen (ca. 1,3 × Let's Go). Die Hochrechnung auf 0,7–1 GB generiertes C ist eine Schätzung.
- Der IL2CPP-Code stammt aus C#. Daher bleibt **Option A** (neues Unity-Projekt mit rekonstruierter Logik) der klar bessere Weg als Rekompilation des NSO. Die Entscheidung fällt am Architektur-Gate.
