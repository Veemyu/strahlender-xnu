# Extraktion und Werkzeuge (Stand: Pause vor REA-Analyse)

## Werkzeuge (lokal, nicht im Repo)
- `tools/hactool` (SciresM/hactool, `make`): LibHac/hactoolnet ist auf GitHub nicht mehr erreichbar.
- `tools/nx2elf` (shuffle2/nx2elf, CMake): NSO nach ELF für Ghidra.
- Ghidra 12.1.4 (`brew install ghidra`, Formula, kein Cask), REA 6.7.0 (`npm i -g rea-agents`).
- REA-MCP ist für Copilot CLI registriert (`rea setup --client copilot_cli`), Backup in `~/.copilot/mcp-config.json.rea.backup`.
  Ghidra-Pfad: `GHIDRA_INSTALL_DIR=/opt/homebrew/opt/ghidra/libexec`.

## Extraktion
- Base: XCI, secure Partition, Program-NCA mit Standard-Crypto (Master-Key-Rev 0xA).
- Update: Titel `0100000011d90800`, Titlekey-Crypto, Master-Key-Rev 0xC, Common-Ticket.
- Update wurde per `--basenca` auf das Base-RomFS angewendet.

```
work/base, work/update   entschlüsselungsfähige NCAs (lokal, löschbar nach Bedarf)
work/exefs               main, rtld, sdk, subsdk0, main.npdm
work/romfs               Data/ (Unity), Data/Managed/Metadata/global-metadata.dat
work/elf/main.elf        mit nx2elf konvertiert (6630 .dynsym-Einträge)
```

Hinweis: hactool gibt bei unbekannten Schlüsselnamen Warnungen mit Schlüsselwerten aus. Ausgabe immer mit `2>/dev/null` filtern.

## Nächste Schritte
1. REA/Ghidra: `work/elf/main.elf` öffnen (Autoanalyse dauert lange, ggf. RAM beachten).
2. Il2CppDumper bauen und `global-metadata.dat` + ELF auswerten, `script.json` in Ghidra importieren.
3. Assets (AssetRipper) und Save-Format.

## IL2CPP-Dump (erledigt)
- `tools/Il2CppDumper` (Perfare, `dotnet build -f net8.0 -o ../il2cppdumper-bin`), Start mit `DOTNET_ROLL_FORWARD=Major dotnet ... <NSO main> <global-metadata.dat> <outdir>`. Das NSO `work/exefs/main` wird direkt gelesen. Die Taste-drücken-Abfrage am Ende erzeugt eine harmlose Exception.
- Metadata v24.4 (als 24.5 erkannt), CodeRegistration `0x4aeb238`, MetadataRegistration `0x4aebed8`.
- Ergebnis in `work/il2cpp/`: `dump.cs` (~11800 Namespaces, ~6200 Klassen), `DummyDll/` (u. a. Assembly-CSharp), `il2cpp.h`, `script.json`, `stringliteral.json`. Klassen u. a. `SaveData`, `PlayerWork`.

## Ghidra
- Import von `main.elf` mit 2G Heap schlug fehl (OutOfMemoryError). Jetzt 8G, Analyzer "GCC Exception Handlers" aus, Timeout 60 min (`~/.copilot/mcp-config.json`).
- Ghidra-/REA-Läufe laufen künftig über einen Hintergrund-Subagenten.

## Ghidra-Import (erledigt, via REA-Subagent)
- `work/elf/main.elf`: Image Base `0x100000`, 30 Segmente, 55.357 Prozeduren, 31.224 Strings. Unity IL2CPP (Mar 1 2022), Editor 2019.4.27f1, Assembly-CSharp 1.6.28.12450.
- Evidence-Bundle: `work/rea/main.elf.evidence.json`.
- **Adressen:** Il2CppDumper-Adressen sind relativ zu 0, in Ghidra `+0x100000`.
- Ein Massen-Rename über MCP ist unpraktisch (~100.000 Methoden). Stattdessen: `scripts/il2cpp_lookup.py '<regex>'` liefert Ghidra-Adressen, REA benennt gezielt.

## nx2elf-Patch (Section-Header)
- nx2elf setzt `.text` nur bis `.plt` (0x1732f98). Der IL2CPP-Spielcode liegt dahinter, aber noch im `R E`-Segment (bis 0x2cf6a30). Ghidra legte dort einen nicht ausführbaren Block an, die Funktionen fehlten (z. B. `PlayerWork$$SaveAsync`).
- Workaround: Kopie `work/elf/main.patched.elf`, in der nur `.plt` `sh_size` auf `0x15c3a98` verlängert ist (4 Byte Unterschied zu `main.elf`). Das Original bleibt erhalten.

## Ghidra mit gepatchtem ELF (erledigt)
- `work/elf/main.patched.elf`: 96.450 Prozeduren (vorher 55.357), 31.280 Strings. Evidence: `work/rea/main.patched.evidence.json`.
- Bestätigt: Il2CppDumper-Adresse + 0x100000 ergibt Funktionsanfänge (`PlayerWork$$SaveAsync` 0x2ded680, `AutoSave` 0x2df60f0, `LoadBytes<SaveData>` 0x1b8bf60). `LoadBytes` kopiert ein 0x7b8-Byte-Struct (Save-Daten).
- Lücke: `PlayerWork$$LoadAsync` (0x2ded780) hat keine Funktion, weil Ghidra ohne eingehende Referenzen keine anlegt. IL2CPP-Methoden werden über Funktionszeiger-Tabellen aufgerufen. Ein Skript müsste Funktionen an allen Adressen aus `script.json` anlegen.
- REA-Sitzungs-Annotationen (Namen) sind nur in der Sitzung und im Evidence-Bundle, nicht dauerhaft.

## Ghidra-Projekt und Pseudocode-Export (erledigt)
- Persistentes Projekt `work/ghidra/bdsp` (Import `main.patched.elf`, ohne Autoanalyse; `scripts/ghidra/SeedIl2Cpp.java` legt Funktionen aus `script.json` an, Analyse danach).
  Ergebnis: 166.095 Funktionen, Seeding 43 s (100.685 neu angelegt), Analyse 1692 s, 0 Fehler. Heap 8G über `GHIDRA_HEADLESS_MAXMEM`.
- `scripts/ghidra/ExportDecompiled.java`: 394 Funktionen in 15 Klassen nach `work/decomp/<Klasse>.c` (PlayerWork, Dpr.NX.SaveSystem, SaveData-Typen). Größte Datei `PlayerWork.c` (250 KB).
- Kernfunktionen: `PlayerWork$$SaveAsync` ruft `PlayerWork$$DataSave`, `LoadAsync` ruft `PlayerPrefsProvider<PlayerWork>.Load`, `LoadBytes<PlayerWork.SaveData>` kopiert das 0x7b8-Byte-Struct. `VerifySaveData` (0x2deba00) ist der nächste Anknüpfungspunkt für Prüfsumme/Validierung.
- Ein `SaveManager` existiert nicht.

## AssetRipper-Export (erledigt)
- `scripts/assetripper_export.py --input work/ripper/in` (Symlinks nur auf `exefs` und `romfs`), Ausgabe `work/ripper/out/ExportedProject/Assets`.

## Unity-Editor
- `brew install --cask unity-hub`; Editor per Hub-CLI: `Unity Hub -- --headless install --version 2019.4.27f1 --changeset 23dc10685eb4 --architecture x86_64` (Intel, Rosetta). Beim Start der Hub-GUI erscheint ein Login-Fenster; der CLI-Download braucht es nicht. Lizenzaktivierung folgt erst beim Öffnen des Editors.
