# Arbeitsplan strahlender-xnu

Ziele: siehe `goal.md`. Alle Assets kommen ausschließlich aus eigenen XCI/NSP-Dumps.

## Verzeichnisse
- `nsp/`, `Ryujinx/`: Dumps, Keys, Saves (lokal, nicht im Repo)
- `work/`: Extraktions- und Analyseergebnisse (lokal, nicht im Repo)
- `tools/`: lokal gebaute Werkzeuge (nicht im Repo)

## Phasen
0. Hygiene: `.gitignore`, Platz schaffen
1. Werkzeuge installieren (ohne sudo)
2. XCI und Update-NSP entpacken, Update anwenden
3. REA mit Ghidra, NSO laden, IL2CPP-Dump
4. Assets und Save-Format analysieren
5. Architekturentscheidung (Unity-LTS, native Metal-Runtime, opendpr nur als Referenz)
6. MVP: 1080p 16:9, Metal, 60/120 FPS

## Regeln
- Keine Keys, Dumps, Saves oder extrahierten Assets committen.
- Kein Code aus opendpr übernehmen (das Projekt verbietet generative KI).
