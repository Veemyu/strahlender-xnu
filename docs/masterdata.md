# Stammdaten (Masterdata) aus den Bundles

Stand: Todo `ap-masterdata`. Alle Aussagen stammen aus dem eigenen Dump (UnityFS v7, Unity 2019.4.27f1) und aus
`work/il2cpp/dump.cs`. Es stehen hier nur Klassen-/Feldnamen und Zahlen, keine Spielinhalte.

## 1. Ergebnis in Kürze

- Die Stammdaten-Bundles enthalten **vollständige TypeTrees**. Sie lassen sich ohne Unity und ohne die Skript-DLL
  lesen; es genügt das Python-Paket UnityPy (MIT), installiert nur unter `tools/pydeps`
  (`pip install --target tools/pydeps UnityPy`).
- Jede Tabelle ist ein `MonoBehaviour` (ScriptableObject, Assembly `Assembly-CSharp.dll`) mit einer oder mehreren
  Listen („Sheets“), deren Zeilen flache Strukturen mit Zahlen, Strings und Zahlenlisten sind.
- Für alle 88 Datenklassen und alle verschachtelten Zeilenklassen (eine Ebene tief) stimmen Feldnamen und
  Reihenfolge mit `dump.cs` überein (0 Abweichungen). Damit sind auch die Speicher-Offsets bekannt.
- Der Grund für „`LoadAllAssets` liefert 0 Objekte“ in Unity 6: Die Klassen (`XLSXContent.*`) existieren im neuen
  Projekt nicht. Das ist kein Defekt der Bundles. Wir lesen deshalb JSON statt Unity-Objekte.

## 2. Werkzeug und Datenfluss

```
Bundle (UnityFS) --UnityPy/TypeTree--> scripts/masterdata_export.py --> work/masterdata/<bundle>/<Klasse>.json
                                                                    --> Xnu.Data.MasterDataReader (C#, POCOs)
```

`scripts/masterdata_export.py`:

| Befehl | Wirkung |
|---|---|
| `survey [--messages]` | listet je Bundle Objekte/Klassen/Zeilen, gleicht mit `dump.cs` ab, schreibt `work/masterdata/_survey.json` (Feldschema je Klasse inkl. Dump-Offsets) |
| `export [--messages]` | schreibt je Klasse eine JSON-Datei nach `work/masterdata/<kurzname>/<Klasse>.json` |

Es werden nur `MonoScript` und `MonoBehaviour` angefasst; Audio-, Textur- und Mesh-Objekte werden nie gelesen.
`work/` ist gitignored. Laufzeit des gesamten Exports: wenige Sekunden, rund 72 MB mit Texten.

### JSON-Format

```json
{"class":"<Skriptklasse>","namespace":"XLSXContent","assembly":"Assembly-CSharp.dll","bundle":"<Pfad relativ zu AssetAssistant>",
 "instances":[{"name":"<m_Name>","data":{"<Sheetname>":[{<Zeile>}, ...]}}]}
```

- `data` enthält alle serialisierten Felder außer Unity-Boilerplate (`m_GameObject`, `m_Enabled`, `m_Script`, `m_Name`).
- Zeilen sind Objekte mit den Originalfeldnamen; Zahlenlisten sind JSON-Arrays; verschachtelte Structs (z. B.
  `Vector3f`) sind Objekte.
- Klassen mit mehreren Instanzen (z. B. `MapWarp`, `PlaceData`, `MsbtData`) haben mehrere Einträge in `instances`.
- Ausgabeordner je Bundle: `dpr_masterdatas`, `pml_personal`, `battle_masterdatas`, `ui_masterdatas`, `effect_database`,
  `contest_masterdatas`, `gms_masterdatas`, `fureai_masterdata`, `underground_masterdata`, `union_masterdata`;
  mit `--messages`: `msg_english`, `msg_german`, `msg_common`.

## 3. Befund je Bundle

„Objekte“ = MonoBehaviour-Instanzen (ohne MonoScript/AssetBundle). `Dpr/masterdatas` hat 1118 Container-Einträge,
aber 1141 MonoBehaviours; die Differenz ist nicht weiter untersucht.

| Bundle | Objekte | Klassen | Klassen (Zeilen je Haupt-Sheet) |
|---|---:|---:|---|
| `Pml/personal_masterdatas` | 16 | 16 | `PersonalTable` (560), `WazaTable` (827), `ItemTable` (1823 + 201 Maschinen), `EvolveTable` (560), `WazaOboeTable` (560), `TamagoWazaTable` (560), `AddPersonalTable` (651), `GrowTable` (8), `TamaTable`, `PedestalTable`, `SealTable`, `StoneStatuEeffect`, `UgItemTable`, `UgFather{Expansion,Pos,ShopTable}` |
| `Dpr/masterdatas` | 1141 | 34 | `TrainerTable` (6 Sheets, 707 Trainer), `PlaceData` (484 Instanzen), `MapWarp` (552 Inst.), `StopData` (53 Inst.), `ShopTable` (10 Shops), `PokemonInfo` (1959), `FieldCommonParam`, `MsgWindowData`, `Tower*`, `Kinomi*`, `HoneyTree`, `TvDataTable`, `TvSchedule`, `ZenmetuZone`, `UgJumpPos`, `CharcterAnime{Event,Table}`, `CharacterGraphics`, `GimmickGraphics`, … |
| `Battle/battle_masterdatas` | 4 | 4 | `BattleDataTable` (19 Sheets, u. a. 828 Zeilen Waza-Daten, 1013 Nachrichtenrahmen), `BattleDefaultPlacementData`, `BattleSetupEffectLots`, `BattleWaitCameraData` |
| `UIs/masterdatas/uimasterdatas` | 6 | 6 | `UIDatabase` (32 Sheets), `PlaceNameTable` (774), `TownMapTable` (218), `TownMapGuideTable` (135), `DistributionTable`, `InputLimitTable` |
| `Effects/masterdatas/effectdatabase` | 1 | 1 | `EffectDatabase` (4 Sheets, 2168 Kampfeffekte) |
| `Contest/md/contest_masterdatas` | 2 | 2 | `ContestMasterDatas` (12 Sheets), `ContestConfigDatas` (9) |
| `GMS/md/gms_masterdatas` | 1 | 1 | `GMSMasterData` (10 Sheets) |
| `FureaiHiroba/fureai/masterdata` | 20 | 20 | `FreeSanpo*`, `Poffin*`, `PokeWalking*`, `Monohiroi*`, `HirobaPokeTalk`, … (je ein Sheet) |
| `UnderGround/masterdata` | 36 | 2 | `UnderGroundFossilNum`, `UnderGroundFossilPos` (35 Inst.) |
| `Union/unionroom/masterdata` | 2 | 2 | `UnionCharacterTable`, `UnionNpcColorTable` |
| `Message/<sprache>` | 119 | 1 | `MsbtData` (`Dpr.Message`), pro Textdatei ein Objekt; `Message/common_msbt`: 90 Objekte |

Alle Klassen liegen im Namespace `XLSXContent` (Ausnahme: `TagPlaceData` ohne Namespace, `MsbtData` in `Dpr.Message`).
Die Zeilenklassen heißen im TypeTree `Sheet<Name>` (oder `Sheet1`) und im Dump `Tabelle.Sheet<Name>`.

## 4. Zuordnung zu dump.cs

- Tabellenklasse: `public class WazaTable : ScriptableObject` im Namespace `XLSXContent`; ihre Felder sind Arrays
  der Zeilenklasse, erstes Feld bei Offset `0x18` (nach dem 0x18 großen ScriptableObject-Kopf).
- Zeilenklasse: verschachtelt als `WazaTable.SheetWaza` (leerer Namespace); Felder beginnen bei `0x10`
  (il2cpp-Objektkopf). Einige Sheets erben Felder von einer Basisklasse (`SheetBuyBase`, `SheetDistributionTable`);
  der Abgleich löst die Vererbung auf.
- Feldnamen im TypeTree entsprechen exakt den Dump-Feldnamen (Groß-/Kleinschreibung, Tippfehler des Originals
  wie `StoneStatuEeffect` inklusive). Typabbildung: `byte/sbyte/ushort/short/int/uint/float/string` 1:1, Arrays als
  JSON-Listen. Zahlen sind im Dump `byte`, auch wenn sie Flags oder Enums sind.
- Wichtige Offsets (Auszug, Zeilenklassen): `SheetPersonal.monsno` 0x14, `.basic_hp` 0x1C, `.tokusei1` 0x34;
  `SheetWaza.wazaNo` 0x10, `.power` 0x18, `.flags` 0x34; `SheetItem.no` 0x10, `.price` 0x18. Alle weiteren stehen
  in `work/masterdata/_survey.json` (`dump.nested.<Sheet>.offsets`).

## 5. Gewählte Kerntypen und C#-Modelle

Code: `unity/Assets/Scripts/Data` (Assembly `Xnu.Data`, keine Unity-Abhängigkeit).

| Gebiet | Original (Bundle) | Eigenes Modell | Anmerkung |
|---|---|---|---|
| Pokémon-Grunddaten | `PersonalTable.SheetPersonal` (Pml) | `SpeciesRecord` | 43 Felder; 560 Zeilen (Arten + Formen) |
| Attacken | `WazaTable.SheetWaza` (Pml) | `MoveRecord` | 33 Felder; die je drei Stufenfelder `rankEff*1..3` sind Arrays |
| Items | `ItemTable.SheetItem` / `SheetWazaMachine` | `ItemRecord`, `MachineRecord` | `wk_*`-Wirkungsbytes als `Effects`-Wörterbuch |
| Entwicklung | `EvolveTable.SheetEvolve` | `EvolutionRecord` | `ar` ist ein flaches Zahlenfeld, Bedeutung der Gruppen noch zu klären |
| Texte | `Dpr.Message.MsbtData` (Message/*) | `MessageFile`, `MessageLabel`, `MessageWord` | Style-/Tag-Daten noch nicht abgebildet |

`MasterDataReader` (`LoadSpecies/Moves/Items/Machines/Evolutions/Messages`) liest die JSON-Dateien und prüft
Klassenname und Instanzzahl; `Parse*`-Methoden arbeiten auf Strings (testbar ohne Dateien). `MiniJson` ist ein kleiner
eigener Parser (Unity bringt kein System.Text.Json mit); er versteht auch `NaN`/`Infinity` aus Pythons JSON-Ausgabe.
Die Property-Namen sind eigene, aus den japanischen Kürzeln abgeleitete Bezeichnungen. Unsichere Deutungen:
`ExpValue`/`GiveExp` (`exp_value`/`give_exp`), `EggBirth`, `Rank`, `EggFormHeldStone*` (`…kawarazunoishi`),
`HoldEffect`/`HoldPower`/`ThrowPower` (`eqp`/`atc`/`nage_atc`). Sie sind durch die Feldnamen gedeckt, aber nicht
durch Verhalten verifiziert.

Verifikation gegen die echte Extraktion (nur Zähler): 560 Arten, 827 Attacken, 1823 Items, 201 Maschinen,
560 Entwicklungszeilen, 119 Textdateien mit 42 557 Labels (Englisch) werden fehlerfrei geladen.

## 6. Tests

- Python: `python3 -m unittest scripts/tests/test_masterdata.py` (synthetische TypeTree-Knoten, Dump-Auszug, Export).
- C# EditMode: `unity/Assets/Tests/EditMode/DataMasterDataTests.cs` (synthetisches JSON; MiniJson, alle Parser,
  Fehlerfälle, Verzeichnisleser). Die Datei wurde zusätzlich außerhalb von Unity mit .NET und NUnit gebaut und ausgeführt
  (9 Tests grün); im Unity-Test-Runner ist sie noch nicht gelaufen.

## 7. Offene Fragen (Stand Teil 1; Aktualisierung in Abschnitt 14)

1. **Typentabelle**: Es gibt keine Tabelle im Bundle. `Pml.Battle.TypeAffinity.TYPE_AFF_TBL` ist ein statisches
   `byte[][]`, das im Klassen-Konstruktor (`.cctor`) aufgebaut wird (Werte x0/xH/x1/x2 = 0/2/4/8). Auslesen erfordert
   Ghidra-Analyse des `.cctor` oder Nachbau nach bekannter Wirkungsmatrix.
2. **Tokusei/Fähigkeiten**: Es gibt keine Datentabelle, nur das Enum `TokuseiNo` und Verhalten im Code; Namen und
   Beschreibungen stehen in den Message-Dateien (`*_ss_tokusei`, `*_ss_tokuseiinfo`). Die Zuordnung Enum-Wert ↔
   Text-Label ist noch zu prüfen.
3. **Namen**: Pokémon-, Attacken-, Item- und Typnamen liegen nur in Message-Dateien (`*_ss_monsname`,
   `*_ss_wazaname`, `*_ss_itemname`, `*_ss_typename`; Pokémon-Texte in `Message/common_msbt`). Das Label-zu-ID-Schema
   (`labelIndex` gegen Label-Namen) ist zu bestätigen.
4. **Karten/Zonen**: Hier liegen Platzierungsdaten (`PlaceData`, `MapWarp`, `StopData`, `ZenmetuZone`,
   `PlaceNameTable`), aber keine Kartengeometrie und keine Zonen-Metatabelle. `ZoneID` ist ein Enum im Code; die
   eigentlichen Zonendaten und die Begegnungstabellen stehen vermutlich in `Dpr/scriptableobjects`, `Dpr/field` oder
   `ev_script` und sind nicht untersucht.
5. `EvolveTable.ar`: Gruppierung der Zahlen (Methode/Parameter/Ziel) fehlt; vermutlich Dreiergruppen.
6. Ob Pml-Tabellen (`ItemTable`, `WazaTable`) dieselben Zeilen wie die Kampf-Tabelle `BattleDataTable.BattleWazaData`
   (828 Zeilen) erweitern, ist ungeklärt.
7. Der Abgleich prüft nur eine Verschachtelungsebene; tiefere Strukturen (z. B. `StyleInfo`, `TagData`) sind
   per TypeTree vorhanden, aber nicht gegen `dump.cs` verglichen.
8. Nicht im Unity-Editor getestet (Vorgabe: Editor nicht über Tools verändern); der Test-Runner und die automatisch
   erzeugten `.meta`-Dateien stehen noch aus.

## 8. Aufwandsschätzung für die restlichen Typen

- Bis zu 88 Datenklassen mit etwa 215 Sheets sind bereits fehlerfrei exportiert; es fehlen nur C#-Modelle und Leser.
- Handgeschriebene Modelle wie die fünf oben: je Sheet etwa 0,5 bis 1 Stunde inklusive Test. Für Trainer
  (`TrainerTable`, 157-Felder-Sheet `TrainerPoke`), Shops, Wildbegegnungen und Kampfdaten (`BattleDataTable`) rechne ich
  mit 1 bis 2 Tagen.
- Zeitsparender Weg: ein Generator, der aus `_survey.json` POCOs und Reader erzeugt (ca. 1 Tag), danach nur noch
  Feintuning der Namen. Für UI-, Effekt-, Kontest-, GTS- und Freizeitdaten reicht diese automatische Variante
  voraussichtlich aus; sie werden meist erst später gebraucht.
- Größere Lücken sind nicht die Bundles, sondern die Code-seitigen Tabellen (Typentabelle, Fähigkeiten-Verhalten,
  Entwicklungsregeln): je 1 bis 3 Tage Ghidra-/Dump-Arbeit.

---

# Teil 2: Trainer, Begegnungen, Karten, Skripte (Todo `ap-masterdata`, Fortsetzung)

Auch hier nur Namen, Zahlen und Struktur; keine Spieltexte, keine Daten im Repo (alles unter `work/`).
Die in Abschnitt 7 offenen Punkte 2, 4 und 5 sind in Teil 2 beantwortet (siehe 14).

## 9. Wo die weiteren Tabellen liegen

Der neue Befehl `scan` öffnet alle Bundles unter `AssetAssistant` außer `Environments` (2,2 GB Karten-/Objektmodelle)
und `Pokemon Database` (Modelle) und liest dort nur die `MonoScript`-Objekte. Ergebnis (`work/masterdata/_scan.json`):
71 Bundles enthalten Tabellenklassen (`XLSXContent.*`, `Dpr.Message.MsbtData`, `EvData`, `TagPlaceData`). Neu gegenüber
Teil 1 sind folgende Bundles (Option `--set extra`, Ausgabe unter `work/masterdata/<kurzname>/`):

| Bundle | Kurzname | Klassen (Instanzen → Zeilen) |
|---|---|---|
| `Dpr/scriptableobjects/gamesettings` | `gamesettings` | `FieldEncountTable` (2 Inst.: je 183 Zonen), `MapInfo` (658 Zonen + 658 Kameras), `ZoneTable` (2 Raster), `AttributeBlock` (2878), `AttributeMatrix` (614), `MapAttributeTable` (256 Codes), `MapAttributeExTable` (114), `CalenderEncTable` (69 Tage, 366 Wettertage), `ArenaInfo` (106), `WaterSettings` (5) |
| `Dpr/ev_script` | `ev_script` | `EvData` (856 Dateien, 13 139 Skripte, 64 745 Befehle) |
| `UnderGround/data/ugdata` | `ug_data` | `UgEncount` (12 Inst., 491 Zeilen), `UgPokemonData` (493), `UgSpecialPokemon` (77), `UgRandMark` (20), `UgEncountLevel` (9), `UgMiniMap`, `UgNpc{List,Pos,Talk}` (50/42/73), `UgPokemonPos` (75), `UgTamagoWazaIgnoreTable` (113) |
| `LightStone/uglightstonedata`, `UnderGround/lightstone/prefabs/lightstonemanager` | `lightstone`, `lightstone_ug` | `LightStonePosTable` (35), `LightStoneTable` (6); zwei Fassungen, nur `lightstone_ug` passt zum Dump (siehe 10) |
| `Dpr/spfishing` | `spfishing` | `RareFishTable` (531 Rasterpunkte) |
| `Dpr/statueeffectdata`, `StatuePlacementEdit/sb/sbcontroller`, `DigFossil/dig/digfossilcontroller` | `statueeffect`, `secretbase`, `digfossil` | `StatueEffectRawData` (430), `Pedestal` (35), `SecretbaseUpgrade` (3), `HardStoneRawData`, `DepositItemRawData`, `StoneBoxRawData` |
| `FureaiHiroba/fieldwalking` | `fieldwalking` | `FieldWalkingKinomiTable`, `…KinomiSeikakuTable` (25), `FieldWalkingPokeTalk` (235) |
| `Dpr/scenes/title` | `title` | `TitleSettings` (9); die Abspannliste `StaffrollList` (Textdaten) wird bewusst nicht exportiert |

Nicht in `AssetAssistant` gefunden: `CharacterTable`, `EffectTable`, `EvMsgList`, `Resources`,
`ArenaInfoExtensionMethods` (vermutlich in anderen Ressourcen oder im Code). Die Audio-Klassen `AudioTable`, `BgmInfo`,
`DebugAudioDatabase` liegen in keinem gescannten Bundle; Audio wird ohnehin nie angefasst. `Contest/music/*` enthält
nur `NotesInfo` (Wettbewerb) und `UIs/searchdatas/*` nur `SearchIndexData` (Text, 9 Sprachen); beide bewusst nicht exportiert.
Nicht exportiert sind auch Nicht-Tabellenklassen im selben Bundle (`EnvironmentSettings` 175, `GameSettings`,
`EventCameraData` 526, `EventCameraTable`); Verweise auf sie werden nur namentlich aufgelöst.

Insgesamt gibt es jetzt 125 JSON-Dateien (88 Teil 1 + 37 Teil 2), `work/masterdata` ist rund 102 MB groß.

## 10. Exporter-Erweiterung (nur additiv)

`scripts/masterdata_export.py` verhält sich ohne neue Optionen wie zuvor (alle Teil-1-Tests unverändert grün).

| Neu | Wirkung |
|---|---|
| `--set base\|extra\|all` | `base` (Standard) = Teil 1; `extra` = Bundles aus `EXTRA_BUNDLES`; `all` = beides. Gilt für `survey` und `export`. `survey --set extra` schreibt `_survey_extra.json` (Teil 1 bleibt in `_survey.json`). |
| `counts` | schreibt Instanz- und Zeilenzahlen aller JSON-Dateien nach `_counts.json` (nur Zahlen) |
| `scan` | listet je Bundle die Tabellenklassen → `_scan.json` (nur MonoScript, ca. 5 Minuten) |

Zusätze im Extra-Export:
- Instanzen tragen `path_id` (Objekt-ID im Bundle). PPtr-Verweise auf Objekte desselben Bundles (`{m_FileID:0, m_PathID}`)
  bekommen `target_class` und `target_name`; so zeigt z. B. `MapInfo…Attribute` auf den Namen der `AttributeMatrix`.
  Aufgelöst wird vor dem Klassenfilter, also auch auf nicht exportierte Klassen (z. B. `EnvironmentSettings`).
- Klassenfilter je Bundle (`EXTRA_BUNDLES`): Standard nur Namespace `XLSXContent`, bei `ev_script` nur `EvData`, bei `title` nur `TitleSettings`.
- Neue Hilfsfunktionen mit Tests: `want_class`, `filter_records`, `resolve_pptr_names`, `table_counts`, `ev_stats`, `scan_wanted`.

Abgleich mit `dump.cs` (Klassenname, Feldnamen, Reihenfolge, Offsets): 37 Klassen, 47 Zeilenklassen, 0 Abweichungen bei
Feldnamen und Reihenfolge – mit einer Ausnahme: In `LightStone/uglightstonedata` weichen `LightStonePosTable.SheetData`
(Bundle: `ZoneID, Digda, Dugtrio`; Dump: `ZoneID, MinNum, MaxNum, MinProbability, MaxProbability, Diglettrate, Dugtriorate, Locator`) und
`LightStoneTable.SheetData` (Bundle: `ZoneID, LightStoneNum, EventTime, BonusTime`; Dump: `ZoneID, LightStone, BonusTime`) ab.
Das Bundle `UnderGround/lightstone/prefabs/lightstonemanager` hat dagegen genau das Dump-Schema. Das ist ein Hinweis, dass
das romfs-Bundle `LightStone/uglightstonedata` neuer ist als der Dump. Der Dump gilt also nicht für jede Tabelle als
Wahrheit; wichtig fürs Untergrund-Kapitel, nicht für die erste Strecke.
Zusätzlich wurde geprüft, dass der C#-Leser jedes Dump-Feld der 33 abgedeckten Zeilenklassen liest (0 ungelesene Felder).

## 11. Neue C#-Modelle und Leser (`Xnu.Data`)

Dateien: `MasterDataModels2.cs` (POCOs), `MasterData2Reader.cs` (Leser; eigene JSON-Helfer, `MiniJson` und der
Teil-1-Leser bleiben unverändert). Ohne UnityEngine. Die Reader-Konstanten nennen die erwarteten Dateipfade unter `work/masterdata`.

| Gebiet | Quelle (Klasse.Sheet) | Modell / Leser | Gelesene Zahlen (echte Daten) |
|---|---|---|---|
| Trainer | `TrainerTable.{TrainerType,TrainerData,TrainerPoke,TrainerRematch}` | `TrainerTables` → `TrainerTypeRecord`, `TrainerRecord` (+ `Party`), `TrainerPokemonRecord`, `TrainerRematchRecord`; `LoadTrainers` | 108 Klassen, 707 Trainer, 706 mit Team, 1563 Teamplätze (max. 6), 238 Rematch |
| Wildbegegnungen | `FieldEncountTable.{table,urayama,mistu,honeytree,safari,mvpoke,legendpoke,zui}` | `FieldEncounterTables` → `ZoneEncounterRecord`, `EncounterSlot` u. a.; `LoadFieldEncounters(instanz)` | 183 Zonen (171 mit Graslisten, 53 mit Wasser/Angeln), 6 Honig, 4 Honigbaum, 64 Safari, 29 Wanderzonen, 37 feste Begegnungen, 18 `zui`, 16 `urayama` |
| Honigbäume | `HoneyTree.{HoneyTreeIndex,HoneyTreeShake}` | `HoneyTreeTables`; `LoadHoneyTrees` | 21 Standorte, 4 Schüttelergebnisse |
| Kalender | `CalenderEncTable.{data,weather}` | `CalendarEncounterTables`; `LoadCalendar` | 69 Tage, 366 Wettertage |
| Zonen | `MapInfo.{ZoneData,Camera}` | `MapInfoTables` → `ZoneInfoRecord`, `ZoneCameraRecord`; `LoadMapInfo` | 658 Zonen, 658 Kameras, 67 Feldzonen, 648 mit Kartenbundle (377 verschiedene) |
| Zonenraster | `ZoneTable` | `ZoneGridRecord`; `LoadZoneGrids` | 2 Raster (30 × 30 mit 196 belegten Zonen, 4 × 5 mit 6) |
| Karten-Attribute | `AttributeBlock`, `AttributeMatrix`, `MapAttributeTable` | `AttributeBlockRecord`, `AttributeMatrixRecord`, `MapAttributeCodeRecord` | 2878 Blöcke (2863 × 1024, 15 × 1056 Werte, Breite 32), 614 Matrizen, 256 Codes |
| Warps | `MapWarp` | `MapWarpSet` → `MapWarpRecord`; `LoadMapWarps` | 552 Karten, 1931 Warps |
| Shops | `ShopTable.{FS,FixedShop,BPShop}` | `ShopTables`; `LoadShops` | 59 / 75 / 90 Einträge (weitere Shop-Sheets nicht modelliert) |
| Lernlisten | `EvolveTable.ar`, `WazaOboeTable.ar`, `TamagoWazaTable`, `GrowTable` | `EvolutionListRecord`/`EvolutionStepRecord`, `LearnsetRecord`, `EggMoveRecord`, `GrowthCurveRecord` | 560 Listen, 254 Entwicklungsschritte, 8 384 Lernstufen-Paare, 560 Eiattacken-Zeilen, 8 Kurven à 101 Werte |
| Event-Skripte | `EvData` | `EventScriptFile` → `EventScript` → `EventCommand` → `EventArgument` | 856 Dateien, 13 139 Skripte, 64 745 Befehle, 17 328 Strings |

Verifikation: alle Tabellen laden fehlerfrei; Spitzenverbrauch beim Lesen aller (inkl. 20-MB-Attributdatei und Skripten)
rund 410 MB. Querprüfungen (echte Daten, nur Zähler): Trainer-Typ-IDs 0 unbekannt; Team-ID = Zeilenindex bei allen 707;
alle 707 `NameLabel` und alle 658 `PokePlaceName` existieren als Label in den passenden Message-Dateien;
`Attribute`-Verweise der Zonen → Matrizen → Blöcke: 0 offene Verweise; Zonen aus dem Raster ↔ `MapInfo`: 0 fehlende;
die 25 „Zonen“ ohne `MapInfo`-Eintrag in `FieldEncountTable` und die 18 Warps ohne Ziel sind alle `-1` (Platzhalter).

Hinweise zur Deutung (aus Feldnamen/Zahlen, nicht aus Verhalten bestätigt):
- `TrainerData` hat kein ID-Feld; die Trainer-ID ist der Zeilenindex (durch `TrainerPoke.ID` bestätigt).
- `FightType` kommt in 681 × 0 und 26 × 1 vor (vermutlich Einzel/Doppel). `AIBit` ist eine Bitmaske mit 6 verschiedenen
  Werten (9 bei 613 Trainern, 111 bei 83, 107 bei 6, 11 bei 3, 8 und ein sechster bei je 1). Die Bedeutung der Bits liegt im Kampfcode.
- Slotzahlen je Zone sind fest: Gras 12, Zeit (Tag/Nacht) je 2, Massenauftreten 2, wiegendes Gras 4, Wasser und die drei
  Angelstufen je 5, GBA-Listen je 2. Die Tabelle enthält nur die Gesamtrate je Art (`encRate_*`), **keine Slot-Wahrscheinlichkeiten**;
  die müssen aus dem Code (Klasse `Encount`/`FieldEncount`) oder Nachbau kommen.
- Die zwei Instanzen `FieldEncountTable_d` und `_p` sind zwei Editionen (in 11 Zonen unterscheidet sich die Grasliste).
  Der Leser nimmt standardmäßig `_d` (Brilliant Diamond).
- `zui` hat je Zone 28 Bool-Werte (passt zur Formenzahl von Icognito/Unown; Vermutung).
- Zonenraster: Index = Zeile × Breite + Spalte, `-1` = leer. Attributblöcke: 32 Werte pro Zeile; Matrizen setzen Blöcke
  zeilenweise zusammen (Name des Blocks, leer = kein Block). Die Bedeutung der Attributwerte (z. B. 128) steht in
  `MapAttributeTable`/`MapAttributeExTable` (Letztere enthält auch Soundlabel-Namen; nicht modelliert).
- `MapWarp.GruopID` ist ein Tippfehler im Original und bleibt als `GroupId` erhalten.

## 12. Karten-, Szenen- und Bundlezuordnung

- `MapInfo.ZoneData.AssetBundleName` verweist relativ auf `Environments/`: 377 verschiedene Namen (249 `prefab_map/*`,
  114 `underground/*`, 14 `fields/*`); 375 existieren als Datei, zwei fehlen (`prefab_map/c08r0501`, `c08r0601`).
  Mehrere Zonen teilen sich ein Bundle (z. B. gleiche Hausinnenräume). 10 Zonen haben kein Kartenbundle. Im Ordner liegen
  384 Kartenbundles (`fields` 15, `prefab_map` 255, `underground` 114), 9 davon sind von keiner Zone benannt.
- Die Feldkarten (`fields/areaNNN`) tragen mehrere Zonen (Stadt + Routen); `AreaID` gruppiert sie (14 Feldbundles + `safari`).
- Platzierungstabellen heißen nach der Karte: `PlaceData_<KARTE>` (484 Instanzen, 4197 Zeilen), `MapWarp_<KARTE>` (552 / 1931),
  `StopData_<KARTE>` (53 / 116). Die Instanzen passen nur teilweise namentlich auf Kartenbundles (277 / 326 / 38 Treffer);
  `PlaceData.zoneID` und `MapWarp.WarpZone` verweisen direkt auf Zonen-IDs und sind der verlässlichere Schlüssel.
- Szenen (`Dpr/scenes/*`, jeweils ein Bundle): `battle`, `contest`, `digfossil`, `evolvedemo`, `field`, `gms`, `opening`,
  `sealpreview`, `title`. Die Feldszene lädt Karten über `AssetBundleName`; Kampfhintergründe über `ArenaInfo`
  (106 Einträge mit Boden-/Himmelsbundle unter `Environments/bg/arenas/{ground,sky}`: 104 + 19 Dateien).
- `ZoneID` hat 658 Werte (0–657, Enum mit 659 Einträgen inkl. `-1`) und entspricht 1:1 den `MapInfo`-Zeilen.

## 13. Event-Skripte (`EvData`) – nur Struktur

Format (Dump und TypeTree stimmen überein): `EvData { List<Script> Scripts; List<string> StrList }`,
`Script { string Label; List<Command> Commands }`, `Command { List<Aregment> Arg }`, `Aregment { ArgType argType; int data }`
(Originalschreibweise „Aregment“). Es ist also **kein Byte-Code-Blob**, sondern strukturierte Zahlenlisten.

- `ArgType` (Enum im Dump): `Command` 0, `Float` 1, `Work` 2, `Flag` 3, `SysFlag` 4, `String` 5.
  Häufigkeit in den echten Daten: 64 741 / 26 305 / 13 255 / 2 959 / 458 / 33 054 (zusammen 140 772 Argumente).
- Das erste Argument eines Befehls hat `argType` 0 und ist die Befehlskennung (`EvCmdID.NAME`, 1236 Werte 0–1235).
  In den Daten kommen 867 verschiedene Kennungen vor, dazu 88 × `-1` (Platzhalter) und 4 leere Befehle.
- `Float`-Argumente speichern die Bits eines `float` in `data` (z. B. 1 065 353 216 = 1,0f); `String` ist ein Index in `StrList`;
  `Work`/`Flag`/`SysFlag` sind Indizes in die Ereignis-Variablen.
- 856 Dateien, 13 139 Skripte (1 bis 952 je Datei), 64 745 Befehle, 17 328 Stringtabellen-Einträge, rund 5,4 MB JSON.
  Dateinamen sind Kartenkürzel (238 passen auf Kartenbundle-Namen) und `sp_*` (300; Sonderereignisse).
- Nicht interpretiert: die Bedeutung der Befehle und das Variablenmodell. Das ist Aufgabe des Skriptinterpreters (Dump: `EvDataManager`, `EvCmdID`); Stand siehe `docs/evscript-spezifikation.md`.
- Verknüpfungen aus anderen Tabellen: `PlaceData.TalkLabel` (3868 gesetzt, 3849 treffen ein `Script.Label`, groß/klein ignoriert)
  und `StopData.ContactLabel` (106 von 106) sind Skript-Labels; `PlaceData.ContactLabel` ist überall leer.
  `MapWarp.ScriptLabel`/`ExitLabel` sind Zahlen (Label-/Ausgangsindex). Es gibt 12 985 verschiedene Labels.

## 14. Offene Fragen aus Abschnitt 7: neuer Stand

- **Fähigkeiten, Wesen, Typen (Punkt 2, teilweise 1):** Es gibt weiterhin keine Datentabelle für Fähigkeitenverhalten oder
  Typenwirkung. Aber die Namenstabellen stehen als Message-Dateien in jeder Sprache: `ss_tokusei` und `ss_tokuseiinfo` (je 268 Labels,
  `TOKUSEI_000…`), `ss_seikaku` (25, `SEIKAKU_nnn`), `ss_typename` (18, `TYPENAME_nnn`), `ss_wazaname` (827), `ss_itemname*` (1823,
  sechs Fassungen). Der Labelindex entspricht der ID (`TokuseiNo` hat 270 Enum-Werte mit Rand, `Seikaku` 26, `PokeType` 21,
  `TypeAffinity.AffinityID` 16). Höchste in `PersonalTable` benutzte Fähigkeit: 256. Die Typenmatrix selbst bleibt Code-Arbeit.
- **Namen (Punkt 3) bestätigt:** Label-Schema `<PREFIX>_<nnn>` mit `labelIndex == arrayIndex == ID`; Trainer- und Ortsnamen
  werden über die Labeltexte der Tabellen (`NameLabel`, `PokePlaceName`) gefunden (707 / 658 Treffer, siehe 11).
- **Zonen/Begegnungen (Punkt 4) gelöst:** Zonenmetadaten, Raster, Attribute, Kameras in `gamesettings` (Abschnitt 9);
  Begegnungstabellen in `FieldEncountTable`; Szenen/Karten über `AssetBundleName` (Abschnitt 12).
- **Entwicklung (Punkt 5) gelöst:** `EvolveTable.ar` besteht aus Fünfergruppen `(Methode, Parameter, Zielart, Zielform, Stufe)`;
  alle 560 Listen haben eine durch 5 teilbare Länge (254 Gruppen insgesamt). Bei Art 1 ergibt die Gruppe `(4, 0, 2, 0, 16)`
  plausibel „Stufenaufstieg zu Art 2 auf Stufe 16“. 25 Methodenwerte kommen vor (4 = 163 ×, 8 = 28 ×). Ihre Bedeutung ist nicht
  einzeln bestätigt. `WazaOboeTable.ar` besteht aus Paaren `(Stufe, Attacke)` (Stufen 0–100, Attacken 1–791, 8 384 Paare).
- **Lernlisten (Punkt 6, Wahrscheinlichkeiten, `Encount`):** offen (siehe 11).
- Zusätzlich offen: `EnvironmentSettings` (Licht je Karte und Tageszeit) sowie `EventCameraData` sind nicht exportiert;
  `PlaceData`-Zeilenfelder (`EventType`, `MoveCode`, `TalkBit` usw.) sind modellierbar, aber noch ohne Modell.

## 15. Texte (nur Zahlen)

Hinweis: Die Label-Zahlen unten schließen Auffüll-Einträge ein (je Sprache 4.261 leere Labels, `common_msbt` 9.940); echte Labels: 38.296 je Sprache, 46.500 in `common_msbt`. Format, Tags und Leser (`Xnu.Text`): `docs/lokalisierung.md`.

Alle Sprachen haben dieselbe Struktur: 119 Textdateien mit insgesamt 42 557 Labels (außer `common_msbt`: 90 Dateien, 56 440 Labels).
Wortzahl je Sprache: Englisch 71 411, Deutsch 75 508, Französisch 76 495, Italienisch 76 727, Spanisch 74 546,
Japanisch 79 900 (Kanji 79 880), Koreanisch 81 549, Vereinfachtes Chinesisch 77 970, Traditionelles Chinesisch 81 633;
`common_msbt` 64 775 Wörter. Der Export (`--messages`) umfasst Englisch, Deutsch und `common`; die anderen Sprachen
lassen sich durch Ergänzen von `MESSAGE_BUNDLES` exportieren. Dateinamen tragen das Sprachpräfix (`german_…`). Label→Tabelle:
`TrainerData.NameLabel` → `dp_trainers_name` (1045 Labels), `MapInfo.PokePlaceName` → `dp_fld_areaname` (218), `…MSLabel` → `dp_fld_areaname_display` (142),
Trainertexte → `dp_trainer_msg` (3014) und `…_sub` (245), Trainerklassen → `dp_trainers_type` (101).

## 16. Tabellen für die erste spielbare Strecke (Start bis erster Kampf)

Strecke nach den internen Zonennamen: Zonen 422–426 (Startort mit Rivalen- und Spielerhaus, Innen- und Außenbereich),
354 (erste Route), 346 und 323–325 (See mit Uferzone). Dort liegen `PlaceData` 68 Zeilen in 8 Karten, die Routenzone
hat Trainer 1–3, die Seekarte (324) die Trainer 322, 323, 328, 329; die Wildlisten der Zonen 323, 324 und 354 sind gleich
gefüllt (Grasrate 30), Zone 422 hat keine. Die Reihenfolge der Story habe ich nicht aus Daten bestätigt; die Menge ist
bewusst etwas großzügig.

| Priorität | Tabelle | Umfang gesamt (für die Strecke gebraucht) |
|---|---|---|
| Kern | `PersonalTable` 560, `WazaTable` 827, `ItemTable` 1823, `GrowTable` 8×101, `EvolveTable` 560, `WazaOboeTable` 560 | alle (Kampf braucht Arten, Attacken, Lernlisten, Erfahrungskurven) |
| Kern | `TrainerTable` (Type 108, Data 707, Poke 707) | Trainer 1–3 und die Seetrainer; Typklassen dazu |
| Kern | `FieldEncountTable` (183 Zonen, Instanz `_d`) | 3–4 Zonen; Zeit-/Wasserlisten leer bis auf Gras |
| Kern | `MapInfo` 658/658 | 10 Zonen; `ZoneTable` Raster 30×30; `MapAttributeTable` 256; `AttributeMatrix` 614 / `AttributeBlock` 2878 (nur die Blöcke der Zonen) |
| Kern | `MapWarp` 552 Karten/1931 Warps, `PlaceData` 484/4197, `StopData` 53/116 | ca. 8–12 Karten je Tabelle |
| Kern | `EvData` 856 Dateien/13 139 Skripte | die Dateien der beteiligten Karten (Kartenkürzel `t01*`, `d27*`, Feldbereich, `sp_*`) |
| Kern | `MsbtData` (Deutsch 119 Dateien/42 557 Labels, `common_msbt` 90/56 440) | Dialoge, Namen, Attackentexte |
| Kampf | `BattleDataTable` (19 Sheets), `ArenaInfo` 106, `BattleSetupEffectLots`, `BattleDefaultPlacementData`, `EffectDatabase` (2168 Einträge) | Kampfdarstellung; ohne Ton |
| Darstellung | `PokemonInfo` 1959, `CharacterGraphics`, `FieldCommonParam` 281, `MsgWindowData` (2380 Sprechernamen u. a.), `PlaceNameTable` 774 | Modelle/UI; Rest später |
| Später | Shops (`ShopTable`: FS 59, Fest 75, BP 90), `HoneyTree` 21, `CalenderEncTable`, Untergrund (`ug_data`), Fureai, Wettbewerb, GTS, Turm | nicht für den ersten Kampf nötig |

## 17. Tests, Lücken, nächste Schritte

- Python: `python3 -m unittest scripts/tests/test_masterdata.py` (22 Tests, davon 11 neu für Teil 2).
- C#: `unity/Assets/Tests/EditMode/DataMasterData2Tests.cs` mit synthetischen Beispieldaten (14 Tests: Trainer, Begegnungen, Zonen,
  Raster/Attribute, Warps, Shops, Entwicklung/Lernlisten, Event-Skripte, Fehlerfälle, Verzeichnisleser). Außerhalb von Unity per
  `dotnet test` (Wegwerfprojekt `work/dotnet-masterdata2/`, NUnit 3.14): 23 Tests grün (9 Teil 1 + 14 Teil 2); im Unity-Test-Runner noch
  nicht gelaufen (`.meta`-Dateien der neuen Dateien erzeugt Unity beim ersten Import). Der Echtdatenlauf liegt unter
  `work/dotnet-masterdata2/check/` (nicht im Repo).
- Lücken: Slot-Wahrscheinlichkeiten der Begegnungen, Bedeutung von `AIBit`/`FightType`/Evolutionsmethoden, Typenmatrix und
  Fähigkeitenverhalten (Code), `PlaceData`-Modell, Skriptinterpreter (Befehlssemantik), `EnvironmentSettings`, nicht modellierte
  Shop-Sheets, Untergrund-/Fureai-Modelle.
- Nächster sinnvoller Schritt: `PlaceData`/`StopData` modellieren und mit `MapWarp` zu einem Kartenladeplan je Zone verbinden;
  danach die Wahrscheinlichkeiten aus `Encount` (Dump/Ghidra) übernehmen.
