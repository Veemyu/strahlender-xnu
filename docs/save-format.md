# Save-Format (BDSP) – Stand der Verifikation

## Zuordnung Ryujinx → Titel
- `Ryujinx/bis/system/save/8000000000000000/0/imkvdb.arc` ist der Save-Index. Einträge je 0x8c Byte: `SaveDataAttribute` (0x40 Byte, Programm-ID als erstes u64 LE) gefolgt vom Wert (Save-ID als u64 LE).
- Titel `0100000011d90000` hat drei Einträge: Account-Save, Nutzer `3f48f5c7…` → Save-ID `6` (Typ 1), weiterer Nutzer → Save-ID `7` (Typ 1), Device-Save → `0xc` (Typ 2, leer).
- Der Spielstand liegt unter `bis/user/save/<SaveID>/0/` (Index `1` ist die zweite Kopie).
  - `.../6/0/SaveData.bin` und `Backup.bin`, jeweils 979.108 Byte (0xEF0A4)
  - `.../7/0/rp*.dat` (~600 KB je Datei, Zweck unbekannt)

## Format (eigene Messung am lokalen Save, Quelle der Struktur: PKHeX `SAV8BS`, GPL-3.0, nur als Referenz)
- Dateigröße `0xEF0A4` (entspricht PKHeX v1.3), Version als u32 LE am Anfang = `0x34`.
- Kein Container-Header, feste Offsets (laut PKHeX z. B. Flags ab 0x4, Items 0x563C, Party 0x14098, Boxen 0x14EF4).
- Prüfsumme: MD5 (16 Byte) bei Offset `0xE9818` über die gesamte Datei, wobei das Hashfeld auf 0 gesetzt ist.
  **Verifiziert:** gültig für `SaveData.bin` und `Backup.bin`.
- Pokémon-Slots sind einzeln im PKM-Format verschlüsselt (laut PKHeX, noch nicht selbst geprüft).
- Die Datei hat bei v1.3 keinen Hash am Dateiende (die letzten 16 Byte sind `ff`).

## Offen
- Eigene Spezifikation der Blöcke aus `PlayerWork.SaveData` (Ghidra-Export) statt Übernahme aus PKHeX.
- Zweck von `rp*.dat`; Name der Datei auf echter Switch (nicht verifiziert).
- Nintendo-Switch-/yuzu-Saves: gleiche `SaveData.bin` erwartet, noch nicht geprüft.

## Weitere Recherche-Ergebnisse
- **Cpp2IL** (MIT): NSO-Loader und Metadata v24.5 vorhanden, Ausgabeformate u. a. `dll_il_recovery`, `diffable-cs`, `isil`. macOS-arm64-Build nur als Pre-Release `2022.1.0-pre-release.21`. Qualität bei BDSP ungetestet.
- **Il2CppInspectorRedux** (AGPL): kein Decompiler, nur Namen/Typen für Ghidra/IDA.
- **AssetRipper 1.1.8** hat `AssetRipper_mac_arm64.zip`. Neueste Version 2.0.0.
- **Wwise:** Version von BDSP nicht belegt. `vgmstream` (+ `wwiser` für `.txtp`) kann `.bnk/.wem` ohne SDK lesen.
- **libil2cpp:** offiziell nur im Unity-Editor, öffentliche Quelle nicht verifiziert.
