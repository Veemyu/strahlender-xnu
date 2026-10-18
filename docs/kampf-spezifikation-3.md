# Kampf-Ereignissystem, Scheibe 3: Handler-Abdeckung

Stand: Zwischenstand Scheibe 3 (Fähigkeiten, Items und Attacken-Handler auf dem Ereignissystem aus Scheibe 2; ohne Rendering, ohne Sound).
Die C#-Umsetzung (`unity/Assets/Scripts/BattleEvents`, Assembly `Xnu.Battle.Events`, reine Logik ohne UnityEngine) ist aus den hier
beschriebenen Regeln entstanden; die Orakel-Fixtures belegen sie gegen die echten ARM64-Funktionen. Die Priorisierung steht in
`docs/kampf-handler-liste.md`. Belegkonvention und Prüfstufen wie in `docs/kampf-spezifikation-2.md` Abschnitt 0 (Adressen = Ghidra-Adressen).

## 1. Ergebnis in Zahlen

| | Scheibe 2 | Scheibe 3 (neu) | gesamt | Ziel |
|---|---|---|---|---|
| Fähigkeiten (Nummern) | 4 | 50 | 54 | ≥ 40 |
| Items (Nummern) | 5 (2 teilweise) | 69 | 73 (270 nicht in Scheibe 3 geprüft) | ≥ 40 |
| Attacken (Nummern) | 0 | 48 | 48 | ca. 60 |
| Orakel-Fälle | 720 | 1 755 (1 728 mit C#-Handler verglichen) | | |
| Unity-/dotnet-Tests | 93 | 8 neue | 101 grün | |

Die Nummern teilen sich Tabellen; verschiedene Handler-Tabellen unter den umgesetzten Nummern: Fähigkeiten 50, Items 72, Attacken 31. Die Attacken-Zahl bleibt unter dem Ziel,
weil nur 57 von 310 Attacken-Nummern reine Handler sind (Abschnitt 5) und etwa die Hälfte der gültigen Attacken gar keinen Handler hat.

## 2. Befunde

### 2.1 Nummer → Handler (Handler-Karte) [O]

`GET_FUNC_TABLE` der Klassen `Tokusei`, `Item`, `Waza`, `Side`, `Field`, `Pos`, `DefaultPowerUp`, `RaidBoss` ist ein Struct-Array
(Nummer `@0x0`, Delegat `@0x8`, 16 Byte je Element). Die Nummern sind die gewohnten der Reihe (Fähigkeit 22 = Bedroher, Item 220 = Wahlband,
Attacke 33 = Tackle ohne Handler). `scripts/battle_handler_map.py` führt dafür die echten `.cctor` aus und ordnet über die `ADD_*`-Funktionen die
Tabellen zu: 241 / 197 / 310 / 22 / 10 / 5 / 3 / 1 Nummern (Tokusei / Item / Waza / Seite / Feld / Position / Default-Powerup / Raid-Boss);
Item 0 (kein Item) und zwei Feld-Nummern haben keine Tabelle; bei Waza erreichen 259 der 262 Tabellen aus Scheibe 2 eine Nummer.

**Lehre aus dem Orakel:** Struct-Arrays belegen 16 statt 8 Byte je Element; der Standard-Stub für `il2cpp_array_new_specific` legt nur 8 Byte an und
`Oracle.make_class` nur 0x100 Byte Statics. Bei 222 Tabellen (ca. 1 800 Byte Statics) überlappten die Objekte. Die Handler-Karte legt daher selbst
0x2000 Byte Statics an und überschreibt den Array-Stub (32 Byte je Element). Die Ergebnisse von `--tables` aus Scheibe 2 sind davon nicht betroffen:
Tabellennamen und Einträge (Ereignis, Funktion) der neuen Karte sind für alle Tabellen identisch mit `handler_tables.json`.

### 2.2 `char`-Variablen im Pseudocode [O]

Handler, die `GetEventVar` in einer `char`-Variablen halten und `+ 1` schreiben (Volltreffer-Stufe, Dauer des Bodens), rechnen auf **8 Bit ohne Vorzeichen**:
`RewriteEventVar(l, (byte)(v + d))`. Beispiel aus dem Orakel: Eingabe 254 liefert 255, Eingabe 255 liefert 0 (nicht 256 und nicht −1). Gleichheitsvergleiche
mit Konstanten (`== '\t'`) sind davon unabhängig. Das Orakel hat die erst angenommene Vorzeichen-Variante widerlegt.

### 2.3 Handler-Muster [OK]

Fast alle reinen Handler haben eine feste Form (`HandlerKit.When`):

1. Besitzer-Variable (`POKEID`, `POKEID_ATK` oder `POKEID_DEF`) muss gleich der eigenen Pokémon-ID sein; manche prüfen stattdessen „nicht ich, aber Freund“
   (`IsFriendPokeID`) oder gar nichts (Items, die nur den Besitzer-Faktor tragen).
2. Optionale Bedingung: Schadensart (`DAMAGE_TYPE`), Attackentyp (`WAZA_TYPE`), Wetter, Zustand (`CheckSick`), Zug- oder Dauerflag des Ziels, KP voll, Art, Item.
3. Wirkung: `MulEventVar` (Festkomma-Verhältnis x/4096, z. B. 0x2000 = ×2, 0x1800 = ×1,5, 0x800 = ×0,5, 0x14CD = ×1,3), `RewriteEventVar` (Flag, Wert)
   oder `MulWazaBasePower` (Grundkraft `WAZA_POWER` ×n, ganzzahlig).

Besonderheiten: `Common.GetWeather` (Feld) gegenüber `GetLocalWeather(pokeId)` (mit Wetter-Aufhebern); Wettercodes 0 keins, 1 Sonne, 2 Regen, 3 Schnee, 4 Sand,
5 Starkregen, 6 Extremsonne, 7 Turbulenz; `calc.IsShineWeather` = 1 oder 6, `calc.IsRainWeather` = 2 oder 5 (aus dem echten Code). Die Heil-Attacken mit Wetter
(234–236) lesen eine Tabelle `{0xAAC, 0x400, 0x400, 0x400, 0x400, 0xAAC}` (Wetter 1–6, sonst 0x800; aus dem Datenabschnitt der Binärdatei gelesen);
Sunaatume (659) verwendet 0xAAC bei Sand, sonst 0x800.

### 2.4 Waza-Handler vs. Tabelle [P]

Von 827 Zeilen der `WazaTable` sind 512 gültig; 286 davon haben keinen Handler (nur 226 stehen in `GET_FUNC_TABLE`). Prioritäten (35 gültige Attacken mit
Priorität ≠ 0), Statuswert-Änderungen (`rankEffType1..3`) und Zustände (`sickID`) liegen in der Tabelle (195 Attacken mit mindestens einem von beiden) und
werden von den Rechnern/Sections gelesen, nicht von Handlern. Handler greifen ein, wenn eine Attacke Sonderregeln hat (Kraft ×2 unter Bedingung,
Festschaden, Wetterabhängigkeit, Schutzphasen-Ausnahmen, Typ-Überschreibung). Die Aufgaben „Status-Effekte, Stat-Changes, Prioritäten“ sind daher keine Handler-
Aufgaben; die Handler-Umsetzung deckt sie nur dort ab, wo ein Handler sie verändert (Priorität: Fähigkeiten 177/205 über Ereignis 17).

## 3. Verifikation

### 3.1 Aufbau (`scripts/battle_oracle_handlers.py`)

Je Handler-Eintrag (Nummer, Ereignis) führt das Orakel die **echte Handler-Funktion** in der echten Ereignis-Maschine aus (`EventSystem`, `EventVar*`, `Common.GetEventVar/
MulEventVar/RewriteEventVar/GetPokeParam`). Zufallsszenarien (seedbasiert, je Eintrag 9): Variablen des Handlers (aus Pseudocode und Hilfsfunktionen ermittelt)
mit Zustand FREE, ONCE oder MUL (mit Grenzen) und Wertebereichen je Variable (Pokémon-IDs 0–3 mit 50 % Besitzer, Typen, Schadensart, Wetter, Flags …), vier
Pokémon mit zufälligen Werten (KP, Stufe, Geschlecht, Art, Item, Typen, Zustände, Zug-/Dauerflags, G-Modus/Verwandlung), Wetter, Attackenflags (7, 8, 12), Feldeffekt 2,
Item-Wert. Aufruf von `CallEvent`, danach alle Variablen. Gespeichert: Aufrufprotokoll, belegter Variablenstapel (Wert, Zustand, Grenzen) und Faktorenliste.

Stubs (Pokémon-/Feldabfragen): `BTL_POKEPARAM.GetValue/IsHPFull/GetMonsNo/GetItem/IsMatchType/CONTFLAG_Get` (und die aus Scheibe 2: `CheckSick`, `TURNFLAG_Get`,
`IsGMode`, `HENSIN_Check`), `Common.GetWeather/GetLocalWeather/IsFriendPokeID/CheckFieldEffect`, `WAZADATA.GetFlag`, `calc.ITEM_GetParam`. „Freund“ = gleiche Parität der ID.
Daher Prüfstufe **[OK]** (Handler echt, Abfragen Testwerte).

Fixture: `unity/Assets/Tests/EditMode/Fixtures/BattleHandlers.json` (2,3 MB, nur Zahlen): 1 755 Fälle, davon 1 451 mit Handler-Aufruf; zwei Einträge übersprungen
(Item 220: Ereignisse 36 und 192 haben Wirkungsebene).

### 3.2 C#-Test (`BattleEventsSlice3Tests`)

- `HandlersAgreeWithTheRealFunctionsForEveryOracleCase`: jeder Fall wird mit der C#-Tabelle ausgeführt und auf Gleichheit geprüft (Aufrufprotokoll, jede Variable,
  Zustand, Grenzen). 1 728 verglichene Fälle; Fälle ohne C#-Handler (155 der Wetter-Reaktion) werden gezählt und nicht verglichen. Abdeckung: 54 Fähigkeiten, 73 Items, 48 Attacken.
- `ImplementedNumbersAreCoveredByTheOracle`: jede umgesetzte Nummer hat mindestens einen Orakel-Fall (außer Item 270 aus Scheibe 2).
- Handrechnungen [P]: Rivalität (Geschlechter), Tafeln/Räucherwerk, Attacken-Registrierung (Priorität), Akrobat, Morgensonne je Wetter, Zorn-Fang-Schaden.

### 3.3 Reproduktion

```
PYTHONPATH=tools/pydeps python3 scripts/battle_handler_map.py                     # work/battleevents/handler_map.json (2 Sekunden)
python3 scripts/battle_handler_priority.py                                        # Priorisierung
PYTHONPATH=tools/pydeps python3 scripts/battle_oracle_handlers.py [--cases 9]     # BattleHandlers.json (ca. 3 Minuten)
cd work/dotnet-battlehandlers && dotnet test                                      # 101 Tests, ohne Unity-Editor
```

## 4. Änderungen am Code aus Scheibe 2

- `IEventBattleEnv` bekommt `GetWeather`, `GetLocalWeather(pokeId)`, `WazaHasFlag(waza, flag)`, `IsFriend(a, b)` (neue Implementierer müssen sie liefern; die Test-Umgebung tut es).
- `BattlePoke` bekommt `MonsNo`, `Sex` (Wert-ID 20), `IsHpFull`, Dauerflags (`GetContFlag/SetContFlag`, 32 Stück).
- `TokuseiHandlers`/`ItemHandlers` sind `partial`; die Tabellen der Scheibe 3 stehen in `HandlersSlice3.cs`, Attacken in `WazaHandlers.cs`
  (`GetTable`, `IsImplemented`, `Add` = `Waza.Add`: Faktor WAZA, Hauptpriorität 1, Unterpriorität vom Aufrufer).
- Ein Test aus Scheibe 2 (`TokuseiWithoutHandlerRegistersNothing`) nutzt jetzt Fähigkeit 22 (Bedroher, ohne Handler) statt 1 (jetzt umgesetzt).

## 5. Lücken (ehrlich)

- **Unvollständige Tabellen:** Sunagakure/Yukigakure/Sunakaki (8, 81, 146) ohne Wetter-Reaktion (Ereignis 155, `common_weather_guard`); Item 220 (Wahlband) ohne Sperr-Logik;
  Item 270 ohne Rückstoß; Fumituke/Jisin/Tatumaki/Naminori sind vollständig (beide Einträge).
- **Nicht umgesetzt (Wirkungsebene):** Bedroher (22), Seelenkraft (39), Schwebe (26), Statik (9), Giftdorn (38), Wasserhülle (41), Robustheit (5) u. a. (Meldungen, Stufenänderungen,
  Zustände); alle Beeren, Schärpe, Reste, Lebensorb-Rückstoß. Handler mit > 60 Zeilen reiner Logik (Tokusei 109/96/244/84/159/…, Waza 87/167/210/283/542/560/751/783,
  Item 112/135/136/278) sind noch offen; sie wären als Nächstes dran (ca. 1–2 Stunden mit Orakel).
- **Attacken-Ziel (ca. 60) nicht erreicht:** 48; bei nur 57 reinen Attacken-Nummern (Tabelle in `docs/kampf-handler-liste.md`) ist das Ziel ohne Wirkungsebene nicht erreichbar.
- **Orakel-Grenzen:** Pokémon-/Feldabfragen sind Stubs (Prüfstufe [OK], nicht [O]); Nummern-Gleichheit von Abfrage-Zahlenwerten (z. B. Sick-IDs 4/5/6 = Brand/Gift/Verwirrung,
  Zugflags 1/2/0x12, Dauerflags 3/4/5/8) ist durch den Pseudocode, nicht durch das Orakel belegt; die Zuordnung zu Spielbegriffen steht nicht in den Fixtures.
- **Python-Test** für `battle_handler_map.py`/`battle_oracle_handlers.py`/`battle_handler_priority.py` fehlt; die Skripte sind nur durch ihren Lauf belegt.
- **Nicht im Unity-Editor getestet** (zwei Editoren offen); neue Dateien ohne `.meta` (`HandlersSlice3.cs`, `WazaHandlers.cs`, `BattleEventsSlice3Tests.cs`, `Fixtures/BattleHandlers.json`).
  `Xnu.Tests.EditMode.asmdef` wurde nicht angefasst; die neuen Tests liegen im bestehenden Verzeichnis.

## 6. Aufwand für den Rest (Schätzung aus den Zahlen)

| Block | Umfang | Schätzung |
|---|---|---|
| Reine Handler > 60 Zeilen | Tokusei 10, Item 4, Waza 8 | 2 Stunden mit dem vorhandenen Orakel |
| Wirkungs-API (`Common.Message/RankEffect/AddSick/Damage/RecoverHP`, `StrParam`, `Section_FromEvent_*`) | 56 Section-Klassen; trägt ca. 130 Tokusei-, 74 Waza-, 70 Item-Handler | 2–3 Tage für die Section-Ebene, danach je Handler ca. 10–20 Minuten; Orakel braucht dort Effekt-Aufzeichnung (Stub schreibt Beschreibungsobjekte in ein Protokoll) |
| Item-Verbrauch/Beeren | ca. 50 Items (`UseItem`, `ConsumeItem`, `SetRecallEnable`) | 1 Tag nach der Section-Ebene |
| Seiten-/Feld-/Positionseffekte | 37 Nummern, 40 Funktionen | 1 Tag (Wetter-Verwaltung, Schutzwände, Fallen) |
| Raid-Boss-/G-Modus-Abfragen | ca. 40 Waza | zusammen mit dem G-Modus |

Der Rest ist Pseudocode-Menge (Tokusei 16 682, Item 13 752, Waza 31 425 Zeilen in offenen Nummern) – ohne Wirkungs-Ebene wirkungslos, mit ihr überwiegend schematisch.
