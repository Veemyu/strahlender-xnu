# Nachtbericht (Stand 2026-10-18, ca. 21:15)

## Was gelaufen ist
| Todo | Ergebnis | Datei |
|---|---|---|
| Save-Spezifikation | fertig, am echten Save bestätigt (MD5, Rivalenname) | `save-spec-entwurf.md` |
| Save-Validator | 23 Tests grün, `check` gegen SaveData.bin und Backup.bin gültig | `scripts/bdsp_save.py`, `save-validator.md` |
| Daten-Inventar | 14.052 UnityFS-Bundles, 696 Banks, 3.241 WEM (Vorbis), 18 Videos (VP8) | `daten-inventar.md` |
| Spielcode-Inventar | 6.200 Spiellogik-Typen, 39.100 Methoden, Engine ca. 20 % | `spielcode-inventar.md` |
| Cpp2IL-Bewertung | nur 27,9 % saubere Rümpfe, Ghidra bleibt Hauptquelle | `cpp2il-bewertung.md` |
| Shader und Audio | 2.971 Cache-Einträge, 5.937 SPIR-V-Module, MSL-Übersetzung 5932/5932, vgmstream dekodiert Samples | `shader-audio-machbarkeit.md` |
| Entscheidungsvorlage | Optionen A, B, C und ein Durchstich D, keine Entscheidung | `architektur-entscheidung.md` |

## Probleme und Workarounds
- Cpp2IL-Pre-Release: `Killed: 9` (unsigniert), mit Ad-hoc-Signatur behoben. Beim NSO brach er an der Segmentgrenze ab, daher `master` selbst gebaut und lokal gepatcht (in `tools/`, nicht im Repo).
- vgmstream: die vorgebaute Version startet ohne Homebrew-Bibliotheken nicht, daher lokal gebaut.
- Unity 2019.4 im Batchmodus: Lizenzfehler (nur GUI nutzbar).
- opendpr: Boot scheitert (siehe `opendpr-aufbau.md`), Blocker B1 (Windows-Shader-Bundles) bleibt.

## Zustand
- Repo: alles gepusht, nur Veemyu als Autor, kein Co-Author-Trailer.
- Lokal, gitignored: `work/` (Dump, Ghidra-Projekt, Exporte), `tools/`.
- Ghidra-Projekt `work/ghidra/bdsp`: 166.095 Funktionen, Pseudocode-Export in `work/decomp/`.
- Nicht angefasst: `~/.copilot/mcp-config.json` (außer der REA-Konfiguration früher), nobara (Ryzen).

## Offene Entscheidungen
Siehe `architektur-entscheidung.md` (Abschnitt „Offene Fragen“).

## Nächste Schritte (Vorschläge)
1. Architektur-Gate besprechen (Option D, Durchstich).
2. Innenlayouts der Save-Unterstrukturen auswerten (Spec erweitern, Validator ergänzen).
3. Stammdaten-Bundles (`personal_masterdatas`, `masterdatas`) öffnen und Format klären.
4. `UIManager.Instance`-Fehler in opendpr nachverfolgen (Referenz für Boot-Ablauf).
