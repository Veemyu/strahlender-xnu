# Pokémon-Parameter (Pml.PokePara) und Spielstand-Slots – Spezifikation

Strang B der Todos `ap-battle` / `ap-save-compat`. Alles in eigenen Worten; Grundlage sind ausschließlich die statische Analyse von
`work/elf/main.patched.elf` (Pseudocode-Export `work/decomp/battle_all/`, Dateien `Pml_PokePara_*.c`), die Typen und Feldoffsets in
`work/il2cpp/dump.cs` und Gegenproben am lokalen Spielstand (nur Zahlen, siehe Abschnitt 7). Fremdprojekte wurden nicht benutzt.

Adressen sind **Ghidra-Adressen** (Il2CppDumper-RVA + 0x100000), so wie in den kommentierten Kopfzeilen des Exports. Offsets ohne Zusatz sind
Byteoffsets. Kennzeichnung: **[O]** = durch Ausführen der echten Spielfunktion im Emulator bestätigt (Orakel, Abschnitt 7),
**[B]** = direkt im Pseudocode/dump.cs belegt, **[R]** = am echten Spielstand bestätigt, **[V]** = vermutet, **[offen]** = nicht geklärt.
Das Binärlayout ist so Teil der Save-Spezifikation (`docs/save-spec-entwurf.md`, Abschnitt „Pokémon-Slots“, dort offen markiert; hier geschlossen).

## 1. Typen und Größen

| Typ (Pml.PokePara) | Größe | Inhalt | Beleg |
|---|---|---|---|
| `CoreData` | 328 = 0x148 | Kopf (8 Byte) + 4 Blöcke zu je 80 Byte (`CORE_DATA_BLOCK_SIZE`) | dump.cs `CoreData.SIZE`; `Accessor$$Initialize` 0x25a39d0 legt 0x148 Byte an [B] |
| `CalcData` | 16 = 0x10 | berechnete Werte (Stufe, Statuswerte) | dump.cs `CalcData.SIZE` [B] |
| `SerializedPokemonCore` | `byte[0x148]` | nur `CoreData` | `SerializedPokemonCore$$CreateWorkIfNeed` 0x21559e0 [B] |
| `SerializedPokemonFull` | `byte[0x158]` = 344 | `CoreData` (0x148) + `CalcData` (0x10) | `SerializedPokemonFull$$CreateWorkIfNeed` 0x21558c0; `Accessor$$Serialize_FullData` 0x25a4410 kopiert Kern nach +0 und CalcData nach +0x148 [B] |
| `SavePokeParty` | 2066 | `members[6]` (je 344), dann `memberCount` (Byte), `markingIndex` (Byte) | dump.cs; `SavePokeParty$$Serialize_Full` 0x2155490; Größe stimmt mit der Tabelle in `save-spec-entwurf.md` überein [B][R] |
| `SaveBoxTrayData` | 10320 | `pokemonParam[30]` zu je 344 | dump.cs; `BoxPokemonWork.TRAY_POKE_MAX = 30`, 40 Ablagen (`TRAY_MAX`) [B][R] |

Im Spielstand liegen die Slots als **Marshal-Abbild** direkt hintereinander (kein Längenfeld, keine Lücken): Slot *i* der Party bei
`0x14098 + 344·i`, die Party-Anzahl bei `0x14098 + 2064`, der Markierungsindex bei `+2065`; Slot *p* der Ablage *t* bei
`0x14EF4 + 10320·t + 344·p` (`playerParty` bzw. `boxTray` in `SaveLayout`). Die Party serialisiert **immer alle sechs** Slots, auch leere
(`SavePokeParty$$Serialize_Full` kopiert members[0..5] unabhängig von `memberCount`, danach `memberCount = party+0x18`, `markingIndex = party+0x1c`) [B].

Am echten Spielstand: Gesamtzahl 6 + 1200 Slots, alle Prüfsummen stimmen [R].

## 2. Aufbau eines Slots (344 Byte)

```
0x000  CoreData (328)
         0x000  uint   personalRnd      Seed der Kodierung und der Blockmischung; bleibt im Klartext
         0x004  ushort headerFlags      Bit0 ppFastMode, Bit1 pppFastMode, Bit2 fuseiTamagoFlag („Bad Egg“)
         0x006  ushort checksum         16-Bit-Prüfsumme über die Klartext-Blöcke
         0x008  4 Blöcke zu 80 Byte     kodiert, in gemischter Reihenfolge (Abschnitt 3)
0x148  CalcData (16)                    kodiert mit demselben Seed, oder 16 × 0
```

Kopf: `CoreDataHeader` (dump.cs, `SIZE = 8`), Bitzugriffe `get/set_ppFastMode/pppFastMode/fuseiTamagoFlag` 0x2143400–0x2143460 [B].
Die ersten beiden Bits sind reine Laufzeitmodi des Accessors; gespeichert ist praktisch nur Bit 2.

## 3. Kodierung, Prüfsumme, Blockmischung

Alle Funktionen sind rein und wurden im Emulator gegen die Python-/C#-Umsetzung geprüft [O].

**Prüfsumme** `Encoder$$CalcChecksum` 0x2152460: Summe aller 16-Bit-Wörter (little endian) des Bereichs in einer 32-Bit-Zahl (ein ungerades Restbyte
bliebe unberücksichtigt). Im Slot steht das untere Halbwort. Der Bereich ist **Offset 8, Länge 0x140 (320 Byte), im Klartext** – also die vier
Blöcke, nicht der Kopf und nicht CalcData (`Accessor$$UpdateChecksumAndEncode` 0x25a3f20 ruft `CalcChecksum(core+8, 0x140)`) [B][O].

**Strom** `Encoder$$CalcNextRandCode` 0x2152500: LCG `z ← z · 0x41C64E6D + 0x6073 (mod 2³²)`, Ausgabe `z >> 16` (16 Bit).
`Encoder$$Encode` 0x21524d0 und `Encoder$$Decode` 0x2152520 sind identisch: jedes 16-Bit-Wort des Bereichs wird mit dem nächsten Ausgabewert per XOR
verknüpft; Startzustand ist der Seed [B][O]. Für jeden Bereich beginnt der Strom neu beim Seed.

**Kodieren** (`UpdateChecksumAndEncode`): Prüfsumme der Klartext-Blöcke berechnen und nach `+6` schreiben → Bereich `+8..+0x148` mit Seed `personalRnd`
(Offset 0 des Kerns) kodieren → CalcData (16 Byte) mit **demselben Seed**, Strom von vorn, kodieren. **Dekodieren** (`DecodeAndCheckIllegalWrite`
0x25a42f0): umgekehrt; stimmt die neu gerechnete Prüfsumme nicht mit `+6` überein, setzt das Spiel `fuseiTamagoFlag` (Kopf-Bit 2) – das Pokémon wird zum
„Bad Egg“, und die Getter liefern Ersatzdaten (Ersatzblöcke aus `Accessor$$Initialize`, u. a. Art 494). Bei jedem Zugriff dekodiert/kodiert der Accessor neu;
im Spielstand liegt immer der kodierte Zustand [B].

**Blockmischung** `Accessor$$GetCoreDataBlockPos(personalRnd, blockId)` 0x25a3e00: Zeile `(personalRnd >> 13) & 0x1F` einer 32×4-Tabelle
(`Accessor..cctor` 0x25ac480, jagged `byte[32][4]` als Initialisierer), Spalte = logischer Block (A=0, B=1, C=2, D=3; `CoreDataBlockId`), Ergebnis = physische Position
0..3. Byteoffset im Kern: `8 + Position · 80`. Die Tabelle (aus der echten `.cctor` gelesen [O]) sind die 24 Permutationen der klassischen Reihenfolge,
Zeilen 24..31 wiederholen die Zeilen 0..7:

```
 0: 0123   1: 0132   2: 0213   3: 0312   4: 0231   5: 0321   6: 1023   7: 1032
 8: 2013   9: 3012  10: 2031  11: 3021  12: 1203  13: 1302  14: 2103  15: 3102
16: 2301  17: 3201  18: 1230  19: 1320  20: 2130  21: 3120  22: 2310  23: 3210
24..31 = 0..7
```
(Ziffern = physische Positionen von A, B, C, D.)

**Leere Slots**: `personalRnd = 0`, Prüfsumme 0, vier Null-Blöcke, **kodiert** (die Nullen werden mit dem Strom von Seed 0 verknüpft, der Bereich ist also nicht
0). CalcData ist je nach Slot entweder 16 × 0 (nie berechnet; das schreibt `Serialize` bei fehlendem Calc-Array, 0x25a4680) oder kodierte Nullen. Am echten
Spielstand: 1060 leere Boxplätze ohne und 5 mit kodierter CalcData [R]. Ein 0-gefüllter Slot ohne gültige Kodierung wäre dagegen „defekt“, weil die Prüfsumme der entschlüsselten Zufallswerte nicht 0 ergibt.

**Seed ändern**: `Accessor$$SetPersonalRnd` 0x25a85a0 schreibt nur das Feld und kodiert neu; die Blöcke werden **nicht** umsortiert, mit neuer Zeile
ändert sich also die logische Zuordnung (eigentlich ein Programmierfehler, hier 1:1 übernommen: `CoreParam.PersonalRnd`). Für ein verlustfreies Umsetzen gibt es
`CoreParam.ReseedPreservingBlocks` (eigene Zutat, nicht im Original).

## 4. Felder

Offsets sind relativ zum **Blockanfang** (physische Position per Abschnitt 3). Beleg: Feldlisten in dump.cs (`CoreDataBlockA..D`) und die Getter/Setter von
`Accessor` (jeweils Adresse in Klammern nur bei Besonderheiten); alle Felder wurden mit den echten Gettern und Settern abgeglichen [O].

### Block A (logisch 0)

| Off | Größe | Feld (dump.cs / eigene Bezeichnung) | Hinweis |
|---|---|---|---|
| 0x00 | 2 | `monsno` / `SpeciesNo` | 0 = leerer Slot (`CoreParam$$IsNull` 0x214c9d0) [B] |
| 0x02 | 2 | `itemno` / `HeldItem` | |
| 0x04 | 4 | `id` / `TrainerId` | volle 32-Bit-Trainer-ID; Eingabe der Farbvariante |
| 0x08 | 4 | `exp` / `Exp` | |
| 0x0C | 2 | `tokuseino` / `Ability` | Fähigkeit direkt gespeichert |
| 0x0E | 2 | `_bitsA` | Bit0/1/2 Fähigkeit 1/2/3 (`tokusei1..3Flag`), Bit3 Favorit, Bit4 `special_g_flag`, Bit5 `debug_edit_flag` |
| 0x10 | 2 | `boxMark` / `BoxMark` | |
| 0x14 | 4 | `colorRnd` / `ColorRnd` | Zufall der Farbvariante |
| 0x18 | 1 | `seikaku` / `Nature` | Wesen (0..24) bei Erhalt |
| 0x19 | 1 | `seikakuHosei` / `NatureAdjust` | **Wesen für die Statuswerte** (Minzen ändern nur dieses Feld) |
| 0x1A | 1 | `_bitsB` | Bit0 `eventGetFlag`, Bit1 `officialBattleEnableFlag`, Bit2–3 `sex` (0 ♂, 1 ♀, 2 ohne; `Pml.Sex`) |
| 0x1C | 2 | `formNo` / `FormNo` | |
| 0x1E..0x23 | 6×1 | `effort*` / EV | Reihenfolge **KP, Angriff, Verteidigung, Initiative (0x21), Sp.-Angr. (0x22), Sp.-Vert. (0x23)** |
| 0x24..0x29 | 6×1 | Wettbewerbswerte | `style, beautiful, cute, clever, strong, fur` |
| 0x2A | 1 | `pokerus` | |
| 0x2C / 0x30 / 0x38 / 0x3C | 4 je | `ribbonA / B / C / D` | Band *n* = Bit *n* % 32 im Wort *n* / 32 (A, B, C, D); `HaveRibbon` 0x25a5b40 [B][O] |
| 0x34 / 0x35 | 1 je | `lumpingRibbonA/B` | Sammelband-Zähler |
| 0x40 | 1 | `_bitsC` → `camp_friendship` | der Accessor liest das ganze Wort, nutzbar ist das niedrigste Byte |
| 0x44 | 4 | `camp_reserved` | |
| 0x48 / 0x49 | 1 je | `talentHeight` / `talentWeight` | Größen-/Gewichts-Wert |
| 0x4A | 1 | `_bitsD` | Bit0 `dpr_illegal_flag` |
| 0x4B | 5 | Füllbytes | |

### Block B (logisch 1)

| Off | Größe | Feld | Hinweis |
|---|---|---|---|
| 0x00 | 26 | `nickname` | 13 UTF-16-Zeichen, NUL-terminiert, höchstens 12 sichtbar; Rest 0 (`SetNickName` 0x25aa1e0) [B][O] |
| 0x1A | 4×2 | `waza` | Attacken-IDs |
| 0x22 | 4×1 | `pp` | aktuelle PP |
| 0x26 | 4×1 | `pointupUsedCount` | PP-Plus je Attacke |
| 0x2A | 4×2 | `tamagoWaza` | Ei-Attacken |
| 0x32 | 2 | `hp` | aktuelle KP (Max-KP stehen in CalcData) |
| 0x34 | 4 | `_bitsA` | IV je 5 Bit: **KP 0, Angriff 5, Verteidigung 10, Initiative 15, Sp.-Angr. 20, Sp.-Vert. 25**; Bit 30 Ei (`tamagoFlag`), Bit 31 Spitzname (`nicknameFlag`) [B][O] |
| 0x38 | 1 | `effortG` | |
| 0x3C | 4 | `sick` | Zustandsbits |
| 0x40 | 4 | `palma` | |
| 0x44 | 12 | Füllbytes | |

### Block C (logisch 2)

| Off | Größe | Feld | Hinweis |
|---|---|---|---|
| 0x00 | 26 | `pastParentsName` | wie Spitzname |
| 0x1A / 0x1B | 1 je | `pastParentsSex`, `pastParentLangID` | |
| 0x1C | 1 | `ownedByOthers` | ≠ 0: Besitzer ≠ Erstbesitzer (Setter speichert 0/1) |
| 0x1E | 2 | `othersFriendshipTrainerId` | |
| 0x20 | 1 | `othersFriendship` | |
| 0x21 / 0x22 / 0x23 | 1 je | `othersMemoriesLevel / Code / Feel` | |
| 0x24 | 2 | `othersMemoriesData` | |
| 0x26 | 14 | `pokejob` | Bitfeld, Bit *i* = Byte *i*/8, Bit *i*%8, *i* < 0x70 |
| 0x34 / 0x35 | 1 je | `enjoy`, `nadeNadeValue` | |
| 0x36 | 1 | `getCassette` | Spielversion-Kennung („CassetteVersion“) |
| 0x37 | 1 | `battleRomMark` | |
| 0x3A | 1 | `langId` | Sprache (nicht 0x38/0x39 = `padding_1/2`) |
| 0x3C | 4 | `multiWork` | |
| 0x40 | 1 | `equipRibbon` | |

### Block D (logisch 3)

| Off | Größe | Feld | Hinweis |
|---|---|---|---|
| 0x00 | 26 | `parentsName` | Name des Erstbesitzers, wie Spitzname |
| 0x1A | 1 | `friendship` | Freundschaft zum Erstbesitzer (`GetOriginalFriendship`) |
| 0x1B / 0x1C / 0x20 | 1 je | `memories_level / code / feel` | |
| 0x1E | 2 | `memories_data` | |
| 0x21..0x23 | 3×1 | `eggGetYear/Month/Day` | Eiabgabe-Datum (Accessor `GetTamagoGet*`) |
| 0x24..0x26 | 3×1 | `firstContactYear/Month/Day` | Fang-/Schlupfdatum (Accessor `GetBirth*`) |
| 0x28 / 0x2A | 2 je | `getPlace`, `birthPlace` | Orte |
| 0x2C | 1 | `getBall` | Ball |
| 0x2D | 1 | `_bitsA` | Bit0–6 `getLevel` (Fangstufe), Bit7 `parentsSex` (Geschlecht des Trainers) |
| 0x2E | 1 | `trainingFlag` | Bit *i* (*i* = KP 0, Angr. 1, Vert. 2, Sp.-Angr. 3, Sp.-Vert. 4, Init. 5): IV zählt als 31 |
| 0x2F | 14 | `wazaRecordFlag` | Bitfeld < 0x70 |
| 0x3D | 8 | `bankUniqueID` | unausgerichtet |
| 0x45 | 11 | Füllbytes | |

**Freundschaft** (`Accessor$$GetFriendship` 0x25a5030, `SetFriendship` 0x25a8a30): ist `ownedByOthers == 0`, gilt `D.friendship`, sonst `C.othersFriendship`;
der Setter schreibt in dasselbe Feld [B][O].

**Zusammenfassung der Gleichheit zum Original**: Die C#-Setter wurden für 104 verschiedene Setter-Funktionen (je 3 Aufrufe mit zufälligen/maximalen Argumenten) und
die Namenssetter gegen die vom Spiel erzeugten Slots Byte für Byte verglichen, die Getter (101 Funktionen, 463 Werte je Slot) auf 32 Slots [O].

### CalcData (16 Byte, kodiert)

| Off | Größe | Feld |
|---|---|---|
| 0x0 | 1 | `level` |
| 0x2 | 2 | `maxHp` |
| 0x4 / 0x6 | 2 je | `atk`, `def` |
| 0x8 | 2 | `agi` (Initiative) |
| 0xA / 0xC | 2 je | `spatk`, `spdef` |
| 0xE | 1 | `gState` |

(`CalcData` in dump.cs; Accessor `GetLevel` 0x25a71a0, `GetMaxHp` 0x25a73e0 usw. [B][O].) Die Stufe wird **nicht** aus der Erfahrung abgeleitet, sondern hier gelesen;
fehlt CalcData, rechnet `CoreParam$$GetLevel` 0x2143e30 aus der Erfahrung (`CalcLevel`).

## 5. Berechnete Werte

Alle Formeln sind bereits in `unity/Assets/Scripts/Battle` umgesetzt und gegen das Orakel geprüft (`docs/kampf-spezifikation-1.md` Abschnitt 3); `PokemonParam` verdrahtet sie
mit den Slotfeldern wie `CoreParam$$CalcMaxHp_NotG` 0x2145460 und `CalcAtk_NotG` 0x2145570 [B]:

- **Eingaben je Wert**: Stufe (aus CalcData, sonst aus der Erfahrung), Basiswert der Art/Form (Stammdaten, `Pml_Personal_PersonalTableExtensions.GetParam`), **IV**
  (5 Bit aus Block B; ist das Trainingsflag des Werts gesetzt, **31**; `CoreParam$$GetTalentPower` 0x2144610), **EV** (Block A), **Wesen = `seikakuHosei`** (nicht `seikaku`).
- **KP** (`CalcTool$$CalcMaxHp` 0x25ad1b0): `((2·Basis + IV + (EV & 0xFFFC)/4) · Stufe) / 100 + Stufe + 10`, Art 292 immer 1.
- **Sonstige Werte** (`CalcTool$$CalcAtk` 0x25ad200 …): `(((2·Basis + IV + (EV & 0xFFFC)/4) · Stufe) / 100 + 5)`, danach die Wesenskorrektur ×1,1 bzw. ×0,9
  (`CalcCorrectedPowerBySeikaku`; Tabelle in `Nature.cs`).
- **Aktualisierung** (`CoreParam$$UpdateCalcDatas` 0x2144010): Stufe aus Erfahrung (`CalcLevel`), neue Max-KP; sind aktuelle KP ≠ 0 (oder wird Kampfunfähigkeit nicht
  erhalten), gilt `hp' = min(hp, neueMax)`, und wenn die Max-KP nicht sinken: `hp' = hp − alteMax + neueMax` (ohne Obergrenze, 16-Bit); danach Angriff, Verteidigung,
  Sp.-Angriff, Sp.-Verteidigung, Initiative. `PokemonParam.RecalculateCalcData`.
- **Stufe aus Erfahrung** (`CalcTool$$CalcLevel` 0x25ad0e0): größtes *L* ∈ 1..100 mit `exps[L] ≤ Erfahrung` (Wachstumszeile der Art, 101 Einträge) – `GrowthRate.LevelFromExp`.
- **Max-PP** einer Attacke (`CoreParam$$GetWazaMaxPP` 0x21480c0): `PP₀ + (((min(Plus,3) · PP₀ · 5) & 0x3FFF) << 2) / 100`, nur das untere Byte; `PP₀` = Basis-PP aus den Attacken-Stammdaten.
- **Farbvariante** (`CalcTool$$IsRareColor` 0x25ad790, am Orakel geprüft [O]): `((id & 0xFFF0) ^ (id >> 16) ^ (colorRnd >> 16) ^ (colorRnd & 0xFFF0)) < 0x10`.
- **Ei** (`CoreParam$$IsEgg` 0x2149370, Modus 0): `tamagoFlag && !fuseiTamagoFlag`.

## 6. Umsetzung (C#, Assembly `Xnu.PokePara`, ohne UnityEngine)

| Datei | Inhalt |
|---|---|
| `PokeLayout.cs` | Größen, Offsets der Blöcke, Party/Boxen-Konstanten |
| `PokeEncoder.cs` | Prüfsumme, LCG, `Encode/Decode`, Blockmischung (`BlockPosition`) |
| `CoreParam.cs` | 328-Byte-Kern im Klartext, alle Felder als Eigenschaften, `FromEncoded` / `EncodeTo` |
| `PokemonParam.cs` | Kern + CalcData = 344-Byte-Slot, Statuswerte, Stufe, Max-PP, Farbvariante |
| `PokeSaveSlots.cs` | Lesen/Schreiben von Party und Boxen in `SaveData.bin` (ändert den Dateihash nicht → danach `SaveWriter.FixHash`), `Verify`, `RewriteAll` |

Entwurfsentscheidungen: (1) Ein ungültiger Slot wird beim Lesen **nicht** automatisch zum Bad Egg (das Spiel setzt das Bit); `markBadEggOnMismatch` schaltet es ein.
(2) Beim Schreiben wird die Prüfsumme wie im Spiel stets neu berechnet; `recomputeChecksum: false` erhält die gespeicherte (verlustfreier Durchlauf defekter Slots).
(3) Ist CalcData im Spielstand 16 × 0, gilt `HasCalcData = false` und beim Schreiben wird wieder 0 geschrieben; sonst wird sie wie im Spiel entschlüsselt.
(4) Bad-Egg-Ersatzdaten des Spiels werden nicht nachgebildet [offen].

## 7. Verifikation

1. **Round-Trip am echten Spielstand** (Wegwerfprojekt `work/dotnet-pokepara`, nur Zahlen; `SaveData.bin` und `Backup.bin` liefern dieselben Zahlen): 1206 Slots (6 Party + 1200 Boxen),
   141 belegt (6 Party, 135 Boxen), **1206 von 1206 Prüfsummen gültig**, 1206 von 1206 Slots nach Entschlüsseln + Verschlüsseln byte-identisch, die gesamte Datei nach `RewriteAll`
   byte-identisch, nach `FixHash` auch der Dateihash identisch. Party-Anzahl 6, `trayMax` 18, keine Bad Eggs [R].
2. **Orakel** `scripts/pokepara_oracle.py` (Unicorn, Methode wie `scripts/battle_oracle.py`): führt die echten Funktionen aus – `Encoder.CalcChecksum/Encode/Decode/CalcNextRandCode`,
   `Accessor..cctor` und `GetCoreDataBlockPos`, `UpdateChecksumAndEncode` (damit das Spiel selbst die Test-Slots kodiert), 101 Getter, 104 Setter, drei String-Setter,
   `CalcTool.IsRareColor`. Die Ergebnisse stehen als reine Zahlen bzw. Hex-Strings **synthetischer Zufallsdaten** in
   `unity/Assets/Tests/EditMode/Fixtures/PokeParaCodec.json` (27 Prüfsummen, 32 Krypto-Fälle, 16 LCG-Schritte, 72 Blockpositionen, 32 Tabellenzeilen, 48 Farbvarianten),
   `PokeParaAccessor.json` (32 Slots, alle 32 Mischzeilen) und `PokeParaSetters.json` (312 Setter-Fälle, 18 String-Fälle). Keine echten Spielstanddaten.
   Grenze des Orakels: Funktionen mit `PersonalSystem`/Stammdatenzugriff (`CalcLevel`, `GetBasicPower`, `GetWazaMaxPP`) laufen nicht im Emulator; sie sind über den
   Pseudocode und die bereits orakelgeprüften Formeln in `Xnu.Battle` abgedeckt.
3. **NUnit-Tests** (`unity/Assets/Tests/EditMode/PokeParaCodecTests.cs`, `PokeParaAccessorTests.cs`, `PokeParaSlotTests.cs`, Assembly `Xnu.Tests.EditMode`) mit den Fixtures und mit im Test
   erzeugten synthetischen Slots/Spielständen. Entwickelt im Wegwerfprojekt `work/dotnet-pokepara` (44 Tests, einschließlich der nur dort liegenden Prüfung am lokalen Spielstand).
   Python-Hilfslogik: `scripts/tests/test_pokepara_oracle.py`.

Reproduktion der Fixtures: `PYTHONPATH=tools/pydeps python3 scripts/pokepara_oracle.py` (fester Seed, deterministisch).

## 8. Offene Punkte

- **Bad-Egg-Pfad**: Ersatzblöcke und Ersatz-CalcData aus `Accessor$$Initialize` (u. a. Art 494, Sprache aus `PlayerWork.msgLangID`) sind nicht nachgebildet; `IsBadEgg` wird nur als Bit geführt [offen].
- **Bedeutung** einzelner Felder (Ribbon-Indizes, `memories*`, `sick`-Bits, `palma`, `effortG`, `gState`, `camp_reserved`, `battleRomMark`) ist nur als Rohwert modelliert; Zuordnung zu Namen/Texten
  gehört in die Stammdaten-/UI-Schicht [offen].
- **Slot-Hilfsdaten der Boxen** (`SaveBoxData`, 1610 Byte bei 0x148AA): nur `trayMax` (45 Byte vor dem Ende; Wert 18 = `TRAY_NUM_1ST`) ist gesichert [R]. Die Strukturen davor (Ablagennamen, Teamnamen, Teamplätze,
  Hintergrund) enthalten im echten Save auffällig Zeigerwerte (8-Byte-Muster) und sind noch nicht entschlüsselt [offen]; die Anordnung der Endfelder aus den Fundlagen: `teamPos` (32 × 0xFFFF), `teamLock`, `trayMax`,
  `currentTray`, `isOpened` (1 Byte), `wallPaper[40]`, `statusPut` (ushort) [V].
- Das genaue Marshal-Layout von `SavePokeParty`/`SaveBoxTrayData` wurde nicht aus der Marshal-Routine (0x2b8e30 / 0x2b0780) gelesen, sondern aus den Größen der Tabelle und dem Round-Trip am echten Spielstand geschlossen [R].
