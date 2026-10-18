# Save-Kompatibilität: Schreibpfad, Import/Export, Ablage

Todos `ap-save-write` und `ap-save-compat`. Kennzeichnung wie in `docs/save-spec-entwurf.md`: **[belegt]** = am lokalen Save, im Disassembly/Pseudocode
oder durch einen laufenden Test nachgewiesen, **[vermutet]** = Schluss aus Struktur/Benennung, **[nicht geprüft]** = aus öffentlichen Beschreibungen oder
Erinnerung, lokal nicht nachgeprüft, **[offen]** = nicht geklärt. Am echten Save wurde nur gelesen; Zahlen statt Inhalte.

## 1. Überblick (C#, Assembly `Xnu.Save`, Ordner `unity/Assets/Scripts/Save`)

| Datei | Inhalt |
|---|---|
| `SaveData.cs` | `SaveData`: lädt/kopiert ein Abbild (nur Version 0x34), ändert Teilbereiche, `ToBytes()`/`Seal()` setzen den MD5 neu. Spieler-Basisdaten, Geld, Items |
| `SavePlayerLayout.cs` | Offsets in `PLAYER_DATA`, `rivalName`, `SaveItem` |
| `SaveFileIO.cs` | Lesen mit Größenlimit, Backup vor dem Überschreiben, atomares Schreiben mit Rücklesen |
| `SaveInspector.cs` | Erkennen/Validieren von Ordnern, Einzeldateien und Zips; Konventionen Ryujinx/yuzu/JKSV/Checkpoint/App; begrenzte Suche |
| `RyujinxSaveIndex.cs` | `imkvdb.arc` lesen → Save-ID-Ordner eines Titels |
| `SaveExporter.cs` | Export nach Ryujinx (`0` und `1`), generische Ordner, Pfadbildung für JKSV/Checkpoint |
| `SaveStore.cs` | Eigene Ablage (Slots, Backups) |
| `../PokePara/SaveDataPokemon.cs` | Erweiterungen auf `SaveData`: Party und Boxen über `Xnu.PokePara` (`SetParty`, `SetBox`, `GetBox`, `VerifySlots`) |

`Xnu.Save` kennt `Xnu.PokePara` nicht (PokePara hängt von Save ab); der Pokémon-Zugriff liegt deshalb als Erweiterungsmethoden in `Xnu.PokePara`.
Beide Assemblies sind ohne UnityEngine und kompilieren gegen `netstandard2.1` (Unity: `apiCompatibilityLevel 6`; mit einem netstandard2.1-Wegwerfprojekt gebaut, 0 Warnungen/Fehler).

## 2. Bearbeitbare Bereiche und Herkunft der Offsets

Alle Offsets in `PLAYER_DATA` stammen aus der Marshal-Routine `0x2e9050` (verwaltet → nativ; `bool` = 4 Byte, `string` = festes UTF-16-Feld),
Disassembly mit `work/dotnet-savewrite/disasm_marshal.py` (Capstone, ELF-Datei `work/elf/main.patched.elf`; Ghidra-Adresse − 0x100000 = virtuelle Adresse).
Das Hilfsskript liegt nur im (nicht eingecheckten) `work/`.

| Feld | Datei-Offset | Größe | Beleg |
|---|---|---|---|
| Spielername (`MYSTATUS.name`) | 0x79B74 + 0x40 = 0x79BB4 | 13 UTF-16-Zeichen (26 Byte), NUL-terminiert, höchstens 12 sichtbar | Disassembly: Stringkopie mit Länge 0xD ins native Feld; am Save: 5 Zeichen, NUL, dahinter alte Reste **[belegt]**; die Obergrenze 12 ergibt sich aus 13 Zeichen inkl. NUL **[vermutet]** |
| Trainer-ID (`id`) | +0x5C | u32 | Disassembly **[belegt]** |
| Geld (`gold`) | +0x60 | i32 | Disassembly **[belegt]**; `PlayerWork.SetMoney` (0x2defc80) schreibt verwaltet bei `PlayerWork+0xEC` = `_saveData`(0x18) + `playerData`(0x90) + `mystatus`(0x38) + `gold`(0xC) **[belegt, Rechnung]**; `MoneyWork.Set` (0x207d350) klemmt auf 0..999999 (`MAX_MOENY`) **[belegt]** |
| Geschlecht (`sex`, bool) | +0x64 | 4 Byte (0/1) | Disassembly; Zuordnung 0/1 ↔ Geschlecht nicht belegt, daher `SexRaw` **[offen]** |
| Orden (`badge`) | +0x69 | Byte | Rohwert `BadgeRaw`; ob Anzahl oder Maske, nicht belegt **[offen]** |
| Spielzeit | +0x90 / +0x92 / +0x93 | u16 Stunden, Byte Minuten, Byte Sekunden | Disassembly **[belegt]**; am Save plausible Werte (Stunden zweistellig, Minuten/Sekunden < 60) **[belegt]** |
| Rivale (`rivalName`) | 0x55F4 | 32 UTF-16-Zeichen (64 Byte) | Top-Level-Feld, „Lutz“ als UTF-16 am Save gefunden **[belegt]**; Obergrenze des Spiels nicht bekannt, `SaveData` erlaubt höchstens 12 Zeichen **[Entscheidung]** |
| Items (`saveItem[3000]`) | 0x563C + 16·Index | 16 Byte je Eintrag | Eintragslayout aus `0x2af6d0`: Count u32 @0, VanishNew (4) @4, Favorite @8, ShowWazaName @9, Dummy @10/11, SortNumber u16 @12 **[belegt]**; Obergrenze 999 (`ItemMaxCount`) **[belegt]** |
| Item-Index = Item-Nummer | | | Am Save sind 171 Einträge mit Anzahl > 0, größter Index 644, alle Anzahlen ≤ 999 und die kleinen Indizes passen zu bekannten Item-IDs; ein Beweis über `ItemWork` fehlt **[vermutet]** |
| Party | 0x14098 | 6 × 344 Byte + Anzahl + Markierung | `docs/pokepara-spezifikation.md` **[belegt]** |
| Boxen | 0x14EF4 | 40 × 30 × 344 Byte | dito **[belegt]**; wie viele Ablagen freigeschaltet sind (`trayMax`), liest `TrayMax()`; das Schreiben prüft das nicht |

`SaveData` ändert nur die jeweils benannten Bytes; Tests vergleichen die Datei vor/nach der Änderung Byte für Byte und lassen nur den Zielbereich plus Hashfeld zu.
Der Name wird beim Setzen mit NUL abgeschlossen und der Rest des 13-Zeichen-Felds genullt (die alten Reste im Original werden dabei **nicht** erhalten, die zwei Paddingbytes dahinter bleiben unberührt).
Nicht bearbeitbar (nur als Rohbytes über `Buffer`): alle übrigen Top-Level-Felder (Flags, Zukan, Rekorde, Kleidung usw.).

## 3. Roundtrip am echten Save

Test `SaveWriteTests.RealSaveRoundTripIsByteIdentical` (je `SaveData.bin` und `Backup.bin`, nur lesend, Rechnen im Speicher): `SaveData.FromBytes` → `ToBytes()` ergibt **byte-identische** Dateien
(Länge 979108, SHA-256 beider Seiten gleich, Hash im Save gültig) **[belegt]**. Weitere Läufe am echten Save, jeweils im Speicher bzw. in einem Wegwerfordner:

- Alle 1206 Slots (6 Party + 1200 Boxen) über `SaveData.SetPartyMember/SetBox` neu geschrieben → Datei byte-identisch; 1206/1206 Prüfsummen gültig **[belegt]**.
- Geld, Item-Anzahl, Spielstunden und Item des ersten Party-Mitglieds geändert → nur diese Bytes + Hash weichen ab; nach `WriteAtomic` und Neuladen stimmen die Werte; Zurücksetzen der vier Werte ergibt wieder die Originaldatei **[belegt]**.
- Namensänderung bleibt innerhalb des Namensfelds **[belegt]**.
- Das Original und sein Zeitstempel blieben unverändert (SHA-256-Präfix von `SaveData.bin`/`Backup.bin` vor und nach allen Läufen identisch).

Nicht gezeigt: dass das **Spiel** (oder Ryujinx/Switch) einen veränderten Stand lädt. Dafür müsste das Spiel laufen **[offen]**; belegt ist nur, dass unser Prüfer (MD5, Größe, Version) den Stand akzeptiert und
die Slot-Prüfsummen stimmen. Die Rechtmäßigkeit der Pokémon-Werte (Legalität) wird nicht geprüft.

## 4. Ordner- und Containerkonventionen

### Ryujinx **[belegt]** (am lokalen Datenordner)
- Save-Index `bis/system/save/8000000000000000/0/imkvdb.arc`: `"IMKV"`, u32, u32 Anzahl (12); je Eintrag 0x8C Byte: `"IMEN"`, u32 Key-Größe (0x40), u32 Wert-Größe (0x40), Key = `SaveDataAttribute`
  (Programm-ID u64 @0, Benutzer-ID 16 Byte @8 **[vermutet, Horizon-Layout]**, Typ u8 @0x20), Wert beginnt mit der Save-ID (u64 LE). Für `0100000011D90000` stehen hier zwei Typ-1-Einträge (Save-ID 6 und 7) und ein Typ-2-Eintrag (12) **[belegt]**.
  `RyujinxSaveIndex.FindSaveDirectories` liefert daraus `bis/user/save/<SaveId 16 Hex>`; Test am lokalen Ordner findet `…0006`.
- Der Save liegt in `bis/user/save/<SaveId>/0/` (`SaveData.bin`, `Backup.bin`), daneben `1/`, `ExtraData0`, `ExtraData1`. Lokal enthalten `0/` und `1/` dieselbe `SaveData.bin` (gleicher SHA-256); `Backup.bin` ist je Ordner gleich, aber **nicht** identisch mit `SaveData.bin` (älterer, ebenfalls gültiger Stand) **[belegt]**.
- Export: `SaveExporter.ExportToRyujinx` schreibt `SaveData.bin` nach `0/` und – falls vorhanden – `1/`; `Backup.bin` nur auf Wunsch (`WriteBackupFile`). Dass Ryujinx `0` als maßgebliche (committete) Kopie behandelt und `1` beim Mounten daraus erneuert **[vermutet]**; deshalb werden beide beschrieben.
  Ryujinx muss beim Schreiben beendet sein (das lässt sich im Code nicht erkennen) **[nicht geprüft]**. `ExtraData0/1` werden nicht angefasst; sie hängen von Größe/Typ, nicht vom Inhalt ab **[vermutet]**.
- Datenordner des Emulators (Standard unter macOS `~/Library/Application Support/Ryujinx`, Linux `~/.config/Ryujinx`, Windows `%AppData%\Ryujinx`; im Portable-Modus ein Ordner `portable`) **[nicht geprüft]**; der lokale Ordner liegt im Repo-Root (`Ryujinx/`, ignoriert).

### yuzu und Forks **[nicht geprüft]**
- `<Datenordner>/nand/user/save/0000000000000000/<Benutzer-ID 32 Hex>/<Titel-ID 16 Hex>/` mit direkt darin `SaveData.bin`, `Backup.bin`. Diese Form ist aus Erinnerung/öffentlichen Beschreibungen übernommen; es gibt lokal kein yuzu.
  `SaveInspector` erkennt sie, `ExportToDirectory` schreibt in einen bestehenden Titelordner.

### Switch-Werkzeuge (JKSV, Checkpoint) **[nicht geprüft; öffentliche Beschreibungen]**
- JKSV: `<SD>/JKSV/<Spielname>/<Backup-Name>/` mit den Save-Dateien; JKSV kann auch Zips anlegen. Checkpoint: `<SD>/switch/Checkpoint/saves/0x<TitelID> <Spielname>/<Backup-Name>/`.
- Inhalt eines Backups ist laut Beschreibungen der Inhalt des gemounteten Saves, bei BD/SP also `SaveData.bin` (+ `Backup.bin`); ob weitere Metadaten-Dateien dazukommen, ist nicht geprüft. `SaveInspector` erkennt die Ordner an Pfad **und** Dateien (`Jksv`, `Checkpoint`),
  `Zip` per Eintragsname (kürzester Pfad), und liest nie mehr als `MaxFileSize` (1 MiB) je Datei/Eintrag (Zip-Bomben-Schutz). `SwitchBackupFolder` bildet neue Backup-Pfade nach diesen Konventionen (nur Pfadbildung, Namen werden FAT-tauglich bereinigt).
- Ob JKSV/Checkpoint auf echter Hardware einen so erzeugten Ordner wiederherstellen und ob der Save an Konsole/Benutzerkonto gebunden ist, wurde nicht getestet **[offen]**. In `SaveData.bin` selbst gibt es keinen Konto- oder Konsolenbezug außer dem Hash **[belegt für die Datei, nicht für das Switch-Dateisystem]**.

### Titel-IDs
- Brilliant Diamond `0100000011D90000` **[belegt]** (Index und Ordner lokal; `scripts/tests`). Shining Pearl `010018E011D92000` **[nicht geprüft]**; ob das Format bei SP gleich ist, wurde nicht untersucht **[offen]**.

### Eigene Ablage (App)
```
<Root>/Saves/<Slot>/SaveData.bin (+ Backup.bin)
<Root>/Backups/<Slot>/<UTC-Zeitstempel>/<Datei>        vor jedem Überschreiben
```
- `Root` = `Application.persistentDataPath` im Unity-Player (`Xnu.Save` bekommt den Pfad vom Aufrufer): macOS Application Support (`~/Library/Application Support/<Firma>/<Produkt>`), iPadOS `…/Documents` im App-Container **[nicht geprüft; Unity-Dokumentation]**.
  Damit der Nutzer auf dem iPad Saves im Dateien-Programm sieht, braucht die App `UIFileSharingEnabled` und `LSSupportsOpeningDocumentsInPlace` in der Info.plist **[nicht geprüft; Apple-Dokumentation, noch nicht in der Build-Pipeline gesetzt, offen]**.
- Slot-Namen: `[A-Za-z0-9][A-Za-z0-9._-]{0,63}` ohne `..` (kein Pfadausbruch); andere Namen werden abgelehnt.

## 5. Erkennen, Validieren, Schreiben

- **Erkennen** (`SaveInspector.Inspect(pfad)`): Ordner, Save-ID-Ordner (→ `0`), Einzeldatei oder `.zip`; Ergebnis mit Art, Titel-ID/Benutzer-ID/Save-ID (soweit im Pfad), je Datei Größe/Version/Prüfung (`Validate`: Version, Größe, MD5), Hinweisen; wirft bei fehlerhaften Dateien nicht.
  `Find(root, maxDepth, maxResults, maxDirectories)` sucht begrenzt unter einem angegebenen Wurzelordner (kein Scan des Datenträgers).
- **Auswahl** (`ReadBest`): `SaveData.bin`, sonst `Backup.bin` – nur gültige Dateien; `preferBackup` kehrt die Reihenfolge um. Das entspricht der Reihenfolge Haupt-/Backup-Datei aus der Spec (Zuordnung dort nur [vermutet]).
- **Schreiben** (`SaveFileIO.WriteAtomic`): (1) Daten prüfen (ungültig → `SaveFormatException`, Ziel unverändert; `AllowInvalid` nur ausdrücklich), (2) existiert das Ziel, ist `BackupDirectory` Pflicht und das Ziel wird nach `<Backups>/<Zeitstempel>/<Name>` kopiert und verglichen,
  (3) Temp-Datei im selben Ordner (`CreateNew`, `Flush(true)`), (4) `File.Replace` (Rückfall Löschen+Verschieben bei `PlatformNotSupportedException`), (5) Rücklesen und Vergleich, bei Abweichung Rückspielen aus dem Backup, (6) Temp-Datei wird immer entfernt.
  Fehlende Zielordner werden nur mit `CreateDirectory` angelegt (Emulator-Ordner nie).
- Grenzen: `File.Replace` ist unter Unix ein `rename` (atomar), unter iOS/Mono nicht getestet; ein `fsync` des Ordners erfolgt nicht **[offen]**. Zwei Prozesse gleichzeitig (Emulator läuft) werden nicht erkannt.
- Nur Version 0x34 ist bearbeitbar. Ältere Stände (0x25–0x33) lädt `SaveData` nicht; das Hochziehen (`TakeOverOldVersion` des Spiels) ist nicht nachgebaut **[offen]**.

## 6. Tests

Entwickelt im Wegwerfprojekt `work/dotnet-savewrite` (`dotnet test`, Temp-Ordner per `TMPDIR` im Projektordner): **56 Tests grün** (35 neue + 21 bestehende `SaveValidatorTests`); davon 6 am lokalen Save (`Real*`, laufen ohne Datei über `Assert.Ignore` als übersprungen – dieser Pfad wurde in dotnet nicht ausgeführt, da der lokale Save vorhanden war).
Zusätzlich Übersetzung von `Save`, `PokePara`, `Battle`, `Data` gegen `netstandard2.1` ohne Fehler. Der Lauf im Unity-Editor (`Xnu.Tests.EditMode`) steht aus.

| Datei | Inhalt |
|---|---|
| `unity/Assets/Tests/EditMode/SaveWriteTests.cs` | Änderungen (Name, ID, Geld, Zeit, Items, Party, Boxen), Bereichsprüfung, Roundtrip, 6 Tests am echten Save |
| `unity/Assets/Tests/EditMode/SaveStorageTests.cs` | Erkennung aller Konventionen, Zip, Größenlimit, Suche, Ryujinx-Index, Backup/atomares Schreiben, Export, App-Ablage, Slot-Namen, 1 Test am echten Ordner |
| `unity/Assets/Tests/EditMode/SaveTestSupport.cs` | Synthetische Saves (deterministisches Rauschen + leere kodierte Slots), Diff-Helfer, Suche des lokalen Saves (`XNU_REAL_SAVE` oder `Ryujinx/bis/user/save/0000000000000006/0/` aufwärts) |

`Xnu.Tests.EditMode.asmdef` brauchte keine Änderung (Verweise auf `Xnu.Save`, `Xnu.PokePara` vorhanden).

## 7. Offene Punkte
- Lauf der Tests im Unity-Editor; Lauf der neuen Dateien in der Unity-Kompilierung (nur gegen netstandard2.1 geprüft).
- Akzeptanz veränderter Saves durch das echte Spiel, Ryujinx und Switch-Hardware; Verhalten von Ryujinx mit der Kopie `1/`.
- Echte Layouts von yuzu, JKSV und Checkpoint gegen Installationen prüfen.
- Bedeutung von `sex` (0/1), `badge`, `region_code`, `rom_code`, Item-Index-Zuordnung über `ItemWork`; ob `MoneyWork`-Grenzen beim Laden erneut klemmen.
- Aufhebung der Einschränkung „nur 0x34“ (Aufwärtsmigration älterer Stände).
- iPadOS: Info.plist-Schlüssel für Dateizugriff, Verhalten von `File.Replace` unter Mono/iOS.
- Shining Pearl: gleiche Struktur? (Titel-ID nur aus öffentlichen Angaben).
