# unity/ ist deprecated (Entscheidung 4, 2026-10-19)

Der Unity-Rebuild wird **nicht mehr weiterentwickelt**. Der Nutzer hat ihn am 2026-10-19 16:57 ausdrücklich stillgelegt: „keine weitere Arbeit mehr damit verschwenden“. Siehe `docs/architektur-entscheidung.md`, Entscheidung 4.

## Warum
Die Rekompilation des Originalcodes (`scripts/recomp/`) liefert Spiellogik, UI, Events, Kampf, Speicherformat und Engine-Verhalten 1:1 und läuft nativ auf macOS (`BDSP.app`), iPadOS und Linux/Vulkan. Der Unity-Rebuild hätte all das von Hand nachbauen müssen (geschätzt 40–80 Wochen gegen 18–35).

## Was das heißt
- **Keine neuen Aufgaben** in `unity/`, an den Unity-Stufen von `scripts/build_all.sh` (`stubs`, `unity-build`, Unity-Teil von `shaders` und `assets`) und an den Unity-Hilfsskripten (`unity_safe.sh`, `shader_wrap*.py`, `stub_gen.py`, `material_*.py`, `visual_auto.sh`-Phase B).
- Der Code bleibt als **Referenz**: Orakel-Fixtures, Kampf-, Pokémon-, Event- und Save-Spezifikationen in `docs/` dokumentieren belegtes Verhalten des Originals und helfen beim Prüfen der Rekompilation.
- Die Tests im Projekt (zuletzt 763 grün) werden nicht mehr gepflegt; ein Fehlschlag blockiert nichts.
- Der Ordner wird nicht gelöscht.

## Weiter genutzt (gehört nicht zu Unity)
Extraktion, Il2Cpp-Dump, Stammdaten-Export, `shader_translator/` (Maxwell→MSL/GLSL, wird von der Rekompilation genutzt), Video- und ASTC-Umwandlung, Save-Werkzeuge, Bildprüfung mit Ryujinx-Referenz, Ryzen-Farm.

## Wieder aufnehmen
Nur auf ausdrücklichen Wunsch des Nutzers.
