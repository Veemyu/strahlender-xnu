# Save-Spezifikation (Entwurf) – Brilliant Diamond, SaveData.bin

Quelle: eigene statische Analyse von `work/elf/main.patched.elf` (Ghidra-Projekt `work/ghidra/bdsp`) und
`work/il2cpp/dump.cs` / `global-metadata.dat`. Adressen sind Ghidra-Adressen (RVA + 0x100000).
Kennzeichnung: **[belegt]** = direkt im Pseudocode/Disassembly oder in den Metadaten zu sehen,
**[vermutet]** = Schluss aus Struktur/Benennung, **[offen]** = nicht geklärt.
Export der Pseudocodes: `work/decomp/` (PlayerWork.c, Dpr_NX_SaveSystem.c, …) und `work/decomp/save-spec/`.

## 1. Gesamtbild

- Der Spielstand ist **kein** Serialisierungsformat (kein MessagePack/JSON/BinaryFormatter), sondern das
  **Marshal-Abbild** (`Marshal.SizeOf` / StructureToPtr) der verwalteten Struktur `PlayerWork.SaveData`. Die Datei
  hat feste Offsets, keine Kompression, keine Verschlüsselung der Datei als Ganzes. [belegt: `PlayerWork$$ToBytes<PlayerWork.SaveData>` 0x1b8c2f0 ruft SizeOf, AllocHGlobal, StructureToPtr-artigen Aufruf, `Marshal.Copy`; Dateiinhalt wird unverändert geschrieben, siehe 2.]
  Dass der zweite Aufruf exakt `StructureToPtr<T>(T, IntPtr, bool)` ist, ist aus der Signatur (Struct, Zeiger, `1`) geschlossen. [vermutet]
- Pokémon-Slots sind zusätzlich einzeln mit dem bekannten LCG-XOR-Verfahren (Faktor `0x41C64E6D`, Inkrement `0x6073`,
  16-Bit-Prüfsumme) kodiert. [belegt: `Pml.PokePara.Encoder$$Encode` 0x21524d0, `$$CalcChecksum` 0x2152460, `$$CalcNextRandCode` 0x2152500]
- Version steht als `int` am Dateianfang; aktueller Wert `0x34` (`PlayerWork.SaveData.CURRENT_VERSION = 52`,
  `LAUNCH_VERSION = 37 (0x25)`). [belegt: dump.cs; `PlayerWork$$Initialization` 0x2deb000 setzt 0x34; OnPreSave 0x2decd90 hebt kleinere Versionen auf 0x34 an]

## 2. Ablauf Speichern

1. `PlayerWork$$SaveAsync(a,b)` 0x2ded680 → `PlayerWork$$DataSave(1,a,b)` 0x2ded1d0. [belegt]
2. `DataSave` setzt `_isMainSave` (+0x828) und `_isBackupSave` (+0x829), ruft u. a. `FieldWalkingManager.UpdatePartnerPokeIndex`,
   `PlayReportManager.SaveRecordDataEvent`, `SystemTimeWork.GetSaveTime/SetSaveTime`, `UgFieldManager.SAVE_POKE`, danach
   `PlayerPrefsProvider<PlayerWork>$$Save(isAsync)` 0x2424f60. [belegt]
3. `Save` ruft per vtable (Slot 11 = Offset 0x1e0) `OnPreSave`, dann Slot 7 (`CustomSaveOperation`, sync) bzw. Slot 9
   (`CustomSaveAsyncOperation`, async). [belegt: Slot→Methode aus dump.cs `PlayerPrefsProvider<T>`; Offsets 0x170+0x10·(Slot−4)]
4. `PlayerWork$$OnPreSave` 0x2decd90: serialisiert die Party (`Pml.PokeParty$$SerializeFull` 0x2157350, Ziel `_saveData.playerParty`),
   sichert Spielerposition (`SetPlayerPosData`), setzt `version = max(version, 0x34)`. [belegt]
5. `CustomSaveOperation` 0x2debf00 / `CustomSaveAsyncOperation` 0x2dec400: `ToBytes<SaveData>(_saveData)` → `byte[] _writeSrcBuffer`
   (+0x820), dann `PlayerWork$$makeSaveDataHash` 0x2debff0. [belegt]
6. **Prüfsumme** `makeSaveDataHash`: Bytes 0xE9818..0xE9827 auf 0 setzen, `MD5CryptoServiceProvider.ComputeHash(buf, 0, Marshal.SizeOf(SaveData))`
   (= ganze Datei, 0xEF0A4 Byte), Ergebnis (16 Byte) nach 0xE9818 kopieren. [belegt]
   Der Typ-Handle (`PTR_DAT_04cbfcf8`) ist derselbe wie in `Dpr.NX.SaveSystem$$_cctor`; dass es `PlayerWork.SaveData` ist, folgt aus der Größe 0xEF0A4. [vermutet]
7. `Dpr.NX.SaveSystem$$Save(data, writeMain, writeBackup)` 0x1edf3e0 (async: `SaveAsync` 0x1edf680 → Thread `StartThread` 0x1edf830 →
   `ThreadLoop` 0x1edfe50): mountet `SaveData` (`MountSaveData` 0x1edf5a0), dann für Hauptdatei und danach Backup jeweils
   `nn::fs::DeleteFile`, `CreateFile(size = data.Length)`, `OpenFile(Mode 2)`, `WriteFile(0, data, data.Length)`, `CloseFile`; zum Schluss
   `FileSystem.Commit`. Die Daten gehen 1:1 auf die Platte (keine Transformation). [belegt]
   Pfade: `SaveData:/SaveData.bin` und `SaveData:/Backup.bin` (dump.cs-Konstanten `SAVEDATA_PATH`, `BACKUP_PATH`). Zuordnung Hauptdatei = erster
   Schreibvorgang/`SaveDataExists`, Backup = zweiter/`BackupExists`. [vermutet, aus Funktionsnamen]

## 3. Ablauf Laden

1. `PlayerWork$$LoadAsync(fromBackup)` 0x2ded780 setzt `_isBackupSave` (+0x829) und ruft `PlayerPrefsProvider<PlayerWork>$$Load(false, true)` 0x2424ae0. [belegt]
2. Slot 8 `CustomLoadAsyncOperation` 0x2dec1e0 → `SaveSystem$$LoadAsync` 0x1edfba0 (Thread). `LoadCore` 0x1edf9b0: Puffer (`SAVELOAD_BUFFER_SIZE`
   = `Marshal.SizeOf` zur Klassenkonstruktion, `_cctor` 0x1ee01d0) mit 0 füllen, `nn::fs` Datei öffnen, `GetSize`, `ReadFile` mit `min(Dateigröße, Puffergröße)`
   (kürzere ältere Saves bleiben hinten 0-aufgefüllt). [belegt; min() aus dem Pseudocode gelesen]
3. Callback `PlayerWork$$OnPostLoadAsync` 0x2dec2a0 (sync-Variante: `CustomLoadOperation` 0x2deb850):
   - Datei fehlt → `LoadResult.NOT_EXIST (1)` (Prüfung `SaveDataExists`), Lesefehler bei vorhandener Datei → `FAILED (3)`,
   - `VerifySaveData` schlägt fehl → `CORRUPTED (2)`,
   - sonst `LoadBytes<PlayerWork.SaveData>` 0x1b8bf60 (`Marshal.PtrToStructure`-artig, siehe `ToBytes`) → `_saveData`, `SUCCESS (0)`. [belegt; Enum aus dump.cs]
   - Nur sync-Pfad: bei `version < 0x29` wird vor dem Einlesen `Array.Clear(buf, 0x9D03C, 0x31304)` ausgeführt (GMS-Bereich; dump.cs: `GMS_WORK_ADDR = 643132 = 0x9D03C`,
     `GMS_WORK_SIZE = 201476 = 0x31304`). [belegt]
4. **Prüfung** `PlayerWork$$VerifySaveData` 0x2deba00: `version` = LE-`int` an `buf[0]`; `version < 0x25` → gilt als gültig (keine Prüfung).
   Sonst: `N = BINARY_SIZE[version − 0x25]`; Puffer < 0xE9828 → ungültig; 16 Byte ab 0xE9818 merken, auf 0 setzen,
   `MD5.ComputeHash(buf, 0, N)`, Byte für Byte vergleichen, Hash zurückschreiben. [belegt]
   Version > 0x34 würde den Tabellenindex sprengen (IndexOutOfRange). [vermutet]
5. `PlayerWork$$OnPostLoad` 0x2dec500: `version < 0x20` → `Initialization` (vtable-Slot 5); `version < 0x34` → `TakeOverOldVersion` 0x2dec6e0
   (versionsabhängige Nachziehungen, z. B. `ZukanWork.CheckLangFlags`, `GMSWork.ResetGMSData`, `TvWork.Initialize`, `BallDecoWork.ResetBallDecoExtraData`); danach `OnPostLoad_NeedMD` 0x2dec8e0. [belegt]

### BINARY_SIZE (hasher-relevante Länge je Version, 0x25 … 0x34)
Statisches `int[16]` aus `PlayerWork.SaveData..cctor` 0x1c29610 (RuntimeHelpers.InitializeArray); Inhalt aus der Metadaten-Datenzeile (fieldDefaultValues):

| Version | 0x25 | 0x26 | 0x27 | 0x28 | 0x29 | 0x2A | 0x2B–0x31 | 0x32 | 0x33 | 0x34 |
|---|---|---|---|---|---|---|---|---|---|---|
| Größe | 0xE9828 | 0xE9BE8 | 0xED158 | 0xED188 | 0xED188 | 0xED680 | 0xEDC20 | 0xEED8C | 0xEED8C | **0xEF0A4** |

Die Werte entsprechen genau den Startoffsets neu hinzugekommener Blöcke (recodeAddData, mysteryGift, poketore, playReport/mt, dendouSaveAdd/tv, ballDecoExtra). [belegt; Zuordnung Version→Block vermutet]

## 4. Layout (Version 0x34, Gesamtgröße 0xEF0A4 = 979 108 Byte)

Herleitung: Die vom IL2CPP-Compiler erzeugte Marshal-Routine (verwaltet → nativ) liegt bei **0x2abf40–0x2acb64** (Gegenrichtung ab 0x2acb90). Ghidra hat sie nicht als Funktion
angelegt, sie wurde über `scripts/ghidra/ScanScalars.java` (Konstante 0x9818) gefunden und per `scripts/ghidra/DecompAt.java` im Speicher dekompiliert
(`work/decomp/save-spec/marshal_savedata.c`). Native Offsets je Top-Level-Feld mit `scripts/save_toplevel.py` abgeleitet; Gegenproben:
Hash-Offset 0xE9818 und GMS-Offset 0x9D03C stimmen mit den dump.cs-Konstanten überein, die Summe der Feldgrößen ergibt exakt 979 108 (0xEF0A4), Rivalenname bei 0x55F4 entspricht UTF-16 „Lutz“ im lokalen Save. [belegt]

Gelten für die Marshal-Abbildung: `bool[]` = 4 Byte je Element (Marshal-BOOL), `string` = festes UTF-16-Feld (rivalName 0x40 Byte), verschachtelte Strukturen inline.
Die Spalte „Größe“ ist Differenz zum nächsten Feld und enthält ggf. Padding. Die „mgd“-Offsets aus dump.cs sind **verwaltete** Offsets (nicht Dateioffsets).

| Datei-Offset | Größe | mgd | Feld | Typ | Marshal-Routine |
|---|---|---|---|---|---|
| 0x00000 | 4 | 0x000 | version | int | |
| 0x00004 | 2000 | 0x008 | intValues | int[500] | |
| 0x007D4 | 16000 | 0x010 | boolValues | bool[4000] (4 B/Elem) | |
| 0x04654 | 4000 | 0x018 | systemFlags | bool[1000] | |
| 0x055F4 | 64 | 0x020 | rivalName | string (32 UTF-16) | |
| 0x05634 | 4 | 0x028 | zoneID | ZoneID | |
| 0x05638 | 4 | 0x02C | timeScale | float | |
| 0x0563C | 48000 | 0x030 | saveItem | SaveItem[3000] à 16 | 0x2af6d0 |
| 0x111BC | 11988 | 0x038 | saveUgItem | SaveUgItem[999] à 12 | 0x2af780 |
| 0x14090 | 8 | 0x040 | saveItemShortcut | ushort[4] | |
| 0x14098 | 2066 | 0x048 | playerParty | SavePokeParty | 0x2b8e30 |
| 0x148AA | 1610 | 0x058 | boxData | SaveBoxData | 0x2afb90 |
| 0x14EF4 | 412800 | 0x088 | boxTray | SaveBoxTrayData[40] à 10320 (30 × 344) | 0x2b0780 |
| 0x79B74 | 1972 | 0x090 | playerData | PLAYER_DATA | 0x2e9050 |
| 0x7A328 | 12472 | 0x118 | zukanData | ZUKAN_WORK | 0x2a74a0 |
| 0x7D3E0 | 5656 | 0x220 | tr_battleData | TR_BATTLE_DATA[707] à 8 | 0x2a3c40 |
| 0x7E9F8 | 68 | 0x228 | topMenuData | TOPMENU_WORK | 0x2a3a20 |
| 0x7EA3C | 68000 | 0x238 | fieldObj_Save | _FIELDOBJ_SAVE | 0x2a9530 |
| 0x8F3DC | 1440 | 0x240 | record | RECORD_ARRAY | 0x2eb8e0 |
| 0x8F97C | 392 | 0x248 | enc_sv_data | ENC_SV_DATA | 0x2e4070 |
| 0x8FB04 | 128 | 0x298 | player_save_data | PLAYER_SAVE_DATA | 0x2e95a0 |
| 0x8FB84 | 17032 | 0x318 | ballDecoData | SaveBallDecoData | 0x2ab680 |
| 0x93E0C | 2400 | 0x328 | saveSeal | SaveSealData[200] à 12 | 0x2aba20 |
| 0x9476C | 1584 | 0x330 | randomGroup | _RANDOM_GROUP | 0x2aa2f0 |
| 0x94D9C | 12 | 0x338 | fieldGimmickSaveData | FieldGimmickSaveData | 0x2e48c0 |
| 0x94DA8 | 2056 | 0x340 | kinomiGrowSaveData | KinomiGrowSaveData | 0x2e5d30 |
| 0x955B0 | 1604 | 0x350 | poffinSaveData | PoffinSaveData | 0x2ea860 |
| 0x95BF4 | 440 | 0x360 | btlTowerSave | BTLTOWER_SAVEWORK | 0x2e1a50 |
| 0x95DAC | 308 | 0x388 | systemData | SYSTEMDATA | 0x2a3790 |
| 0x95EE0 | 416 | 0x3F8 | poketchData | POKETCH_DATA | 0x2e9760 |
| 0x96080 | 704 | 0x438 | azukariyaData | AzukariyaData | 0x2cae90 |
| 0x96340 | 14768 | 0x458 | dendoudata | _DENDOU_SAVEDATA | 0x2a9210 |
| 0x99CF0 | 8 | 0x468 | badgeSaveData | BadgeSaveData | 0x2e1ec0 |
| 0x99CF8 | 24 | 0x470 | boukenNote | BoukenNote | 0x2e2050 |
| 0x99D10 | 2956 | 0x478 | tvDataOld | byte[] | |
| 0x9A89C | 10144 | 0x480 | ugSaveData | UgSaveData | 0x2a5f80 |
| 0x9D03C | 201508 | 0x508 | gmsdata | GMS_DATA | 0x2e49d0 |
| 0xCE360 | 1712 | 0x518 | networkdata | PLAYER_NETWORK_DATA | 0x2e9380 |
| 0xCEA10 | 12 | 0x540 | unionSaveData | UnionSaveData | 0x2a6e10 |
| 0xCEA1C | 24 | 0x54C | contstPhotoLangData | CON_PHOTO_LANG_DATA | |
| 0xCEA34 | 100 | 0x568 | zukanPersonalRndData | ZUKAN_PERSONAL_RND_DATA | 0x2a7110 |
| 0xCEA98 | 160 | 0x580 | contestPhotoExtData | CON_PHOTO_EXT_DATA[] | 0x2e31b0 |
| 0xCEB38 | 104000 | 0x588 | gmsPointExtData | GMS_POINT_HISTORY_EXT_DATA[] | 0x2e51d0 |
| 0xE8178 | 32 | 0x590 | ugCountRecord | UgCountRecord | |
| 0xE8198 | 5760 | 0x5B0 | reBuffNameData | ReBuffnameData | 0x2a16a0 |
| **0xE9818** | 16 | 0x5B8 | **saveDataHash** | byte[16] (MD5) | |
| 0xE9828 | 960 | 0x5C0 | recodeAddData | RECORD_ADD_DATA | 0x2eb030 |
| 0xE9BE8 | 13680 | 0x5D0 | mysteryGiftSaveData | MysteryGiftSaveData | 0x2e8a40 |
| 0xED158 | 48 | 0x608 | poketoreCountArray | POKETCH_POKETORE_COUNT_ARRAY | 0x2ea060 |
| 0xED188 | 248 | 0x610 | playReportData | PLAYREPORT_DATA | |
| 0xED280 | 1024 | 0x708 | mtData | MT_DATA | 0x2abb10 |
| 0xED680 | 1440 | 0x710 | dendouSaveAdd | DENDOU_SAVE_ADD | 0x2e3ca0 |
| 0xEDC20 | 4460 | 0x718 | tvData | TV_DATA | 0x2a3ca0 |
| 0xEED8C | 792 | 0x7A8 | ballDecoExtraData | SaveBallDecoExtraData | 0x2ab830 |

Array-Längen `intValues`, `boolValues`, `systemFlags`, `saveItem`, `saveUgItem`, `saveItemShortcut`, `boxTray`, `tr_battleData` stammen zusätzlich aus
`PlayerWork$$Initialization` 0x2deb000 (500, 4000, 1000, 3000, 999, 4, 40, 0x2c3=707). [belegt]
Das verwaltete `PlayerWork.SaveData` ist 0x7B8 Byte groß (letztes Feld 0x7A8 + 16); `PlayerWork` selbst legt `_saveData` bei +0x18 ab, `_writeSrcBuffer` bei +0x820. Das ist nur der Wrapper mit Referenzen auf Arrays/Strukturen, nicht das Dateiabbild. [belegt: dump.cs, memcpy(…,0x7b8) in ToBytes/LoadBytes]

### Pokémon-Slots
- Ein Slot in Box/Party ist ein `byte[]` (`SerializedPokemonFull.buffer`); die Boxplatzgröße ergibt sich aus 10320 B je Tray / 30 Slots = **344 Byte** je Slot. [vermutet aus Tray-Größe; Slotzahl 30 nicht separat belegt]
- Kodierung: Gen-4/5-artig – 16-Bit-Wörter mit LCG-Keystream XOR (`Encoder$$Encode/Decode` 0x21524d0/0x2152520), Summe 16-Bit-Wörter als Prüfsumme (`CalcChecksum` 0x2152460).
  Die Keys/Seeds und welche Bereiche kodiert sind, steht in `Pml.PokePara.Accessor` (`UpdateChecksumAndEncode` 0x25a3f20, `DecodeAndCheckIllegalWrite` 0x25a42f0; Export `work/decomp/save-spec/Pml_PokePara_Accessor.c`). [offen: vollständige Beschreibung]

## 5. Prüfung am lokalen Save
`Ryujinx/bis/user/save/0000000000000006/0/SaveData.bin`: Größe 979 108, Version 52, MD5 über die Datei mit genulltem Feld bei 0xE9818 stimmt mit dem gespeicherten Hash überein. [belegt, selbst nachgerechnet]

## 6. Offene Fragen
- Interne Feldlayouts der Unterstrukturen (z. B. `PLAYER_DATA`, `ZUKAN_WORK`, `SaveBoxData`): Die jeweiligen Marshal-Routinen (Spalte „Marshal-Routine“) enthalten die Offsets; automatische Auswertung steht aus. Die verwalteten dump.cs-Offsets reichen dafür nicht, weil Arrays inline (feste Länge) und `bool` als 4 Byte abgelegt werden. [offen]
- Exakte Padding-/Alignment-Lücken innerhalb der in der Tabelle als Differenz berechneten Größen (z. B. `gmsdata` 201 508 vs. `GMS_WORK_SIZE` 201 476). [offen]
- Pokémon-Kodierung im Detail (Seed-Quelle, kodierte Bereiche, Slotgröße 344 Byte direkt belegen). [offen]
- Bestätigung, dass der zweite ToBytes/LoadBytes-Aufruf `StructureToPtr`/`PtrToStructure` ist, und der Typ-Handle `PTR_DAT_04cbfcf8` = `PlayerWork.SaveData`. [vermutet]
- Zuordnung Pfadkonstante ↔ Hauptdatei/Backup in `SaveSystem` (Literal-Zeiger `PTR_DAT_04cbfc68/70`). [vermutet]
- Zweck der `rp*.dat` im anderen Save-Ordner (`docs/save-format.md`) weiterhin unklar.

## 7. Eigene Werkzeuge (Hilfsmittel für die Analyse)
- `scripts/ghidra/ExportDecompiled.java` (Regex → .c je Klasse), `ScanScalars.java` (Skalar-Operanden suchen), `DumpRange.java` (Listing eines Bereichs),
  `DecompAt.java` (Funktion im Speicher anlegen und dekompilieren; mit `-readOnly` ändert es das Projekt nicht).
- `scripts/save_layout.py` (dump.cs ↔ Metadaten-Felder, 105 088 Felder stimmen überein), `scripts/save_toplevel.py` (native Top-Level-Offsets aus der dekompilierten Marshal-Routine).

## 8. Nachtrag: Pokémon-Slots
Slotlayout (344 Byte), Kodierung (LCG-XOR, 16-Bit-Prüfsumme, Blockmischung), alle Felder und die Berechnung der Statuswerte stehen in `docs/pokepara-spezifikation.md`
(C#: `unity/Assets/Scripts/PokePara`); damit sind die in Abschnitt 4 („Pokémon-Slots“) und 6 als offen markierten Punkte zur Pokémon-Kodierung geklärt. Am lokalen Save stimmen alle 1206 Slot-Prüfsummen.

## 9. Nachtrag: Spieler-Basisdaten, Items, Schreibpfad
Native Offsets in `PLAYER_DATA` (Name 0x79BB4, Trainer-ID 0x79BD0, Geld 0x79BD4, Spielzeit 0x79C04), das 16-Byte-Layout von `SaveItem` und der Schreibpfad (`SaveData`, atomares Schreiben, Ordnerkonventionen)
stehen mit Belegen in `docs/save-kompatibilitaet.md` (C#: `SavePlayerLayout`, `SaveData`).
