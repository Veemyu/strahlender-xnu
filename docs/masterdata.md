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

## 7. Offene Fragen

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
