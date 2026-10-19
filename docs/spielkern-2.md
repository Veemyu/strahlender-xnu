# Spielkern, Scheibe 2: Host-Befehle, Pokécenter-Ablauf, Massenlauf und Story-Lauf (Todo `ap-game-flow-2`)

Stand: 2026-10-19. Nur Namen, Zahlen und Struktur; keine Spieltexte, keine Daten, keine echten Saves im Repo. Code: `unity/Assets/Scripts/Game` (Assembly `Xnu.Game`, reines C#),
Tests: `unity/Assets/Tests/EditMode/GameSlice2Tests.cs`. Prüfstufen wie in `docs/evscript-spezifikation.md` und `docs/spielkern-1.md`: **[P]** Handler-Pseudocode gelesen (Ghidra-Export, `-readOnly`),
**[A]** Annahme (Argumentform, Label-Namen, Zuordnung), **[N]** nur Name, Signatur und Aufrufliste; die Wirkung läuft dann über `IFieldHost.RunVisual` an die Feldschicht, **[O]** Orakel (laufendes Original): **weiterhin für nichts vorhanden**.

## 1. Ergebnis in Kürze

- **Alle 599 Host-Kennungen sind belegt** (vorher 168 = 28 %): 597 stehen in `HostCommands.Table`, zwei (`CMPWK` 19, `CASE_CANCEL` 38) sind jetzt **Kernbefehle** des Interpreters (63 statt 61). Es gibt keine Lücke mehr; der Zähler `GameEvHost.Gaps` bleibt für künftige Kennungen erhalten.
- **Prüfstufen der 597 Tabelleneinträge** (Kennungen / Befehle in den Daten): **P 173 / 10 241 (75,2 %)**, A 69 / 1 719 (12,6 %), N 355 / 1 661 (12,2 %) von 13 621 Host-Befehlen. Scheibe 1 lag bei P 38 / 5 977 (43,9 %).
  „Umgesetzt“ heißt hier: eine Kennung ist entweder mit Wirkung auf den Spielzustand ausgeführt (State: 138 Kennungen), an die Feldschicht/Oberfläche delegiert und im Ereignisprotokoll mit Dauer sichtbar (Field 414, Wait 29) oder stumm (Ton 16, 903 Befehle).
  **N-Einträge sind Delegation, keine nachgebaute Wirkung**; ob die Feld-/UI-Schicht sie richtig ausführt, ist eine eigene Aufgabe (Abschnitt 8).
- **Korrektur aus Scheibe 1:** Befehl **523 ist `GET_POKE_COUNT2` = Zahl der Teammitglieder ohne Ei, nicht die Teamgröße** (Abschnitt 3). Außerdem: `SXY_EXIT_POS_CHANGE` (507) hat keinen Objektnamen (Abschnitt 6), `TEMOTI_MONSNO` (543) liefert für Eier 0.
- **Massenlauf** (alle 13 139 Skripte, echter Host, `NullFieldHost`, Zufallsantworten bei Dauerbestätigung): **0 unbekannte Befehle, 0 Fehler, 13 106 enden** (davon 263 erst mit Zufallsantworten), **33 hängen** (Abschnitt 7; vorher 12 811 / 328).
- **Story-Lauf** (Abschnitt 7): ab dem Startskript der Anfangssequenz bis zum **ersten Kampf** (Tutorialkampf, 20 von 20 Läufen) und danach bis zum **ersten Pokécenter-Besuch mit Heilung** (20 von 20, 4 bis 6 Zonenbetritte, 13–14 Ereignisse ohne Fehler und ohne Hänger).
- **Tests:** 92 von 92 grün im Wegwerfprojekt `work/dotnet-game` (38 EvScript + 28 Spielkern aus Scheibe 1 + 26 neu); die 38 EvScript-Tests laufen auch in `work/dotnet-evscript` grün. Andere Wegwerfprojekte: BattleEvents 101, BattleHandlers 101, PokePara 44, MasterData2 23, Text 35, Save 21, SaveWrite 56, Effects 17 grün;
  `work/dotnet-battleflow` kompiliert nicht (Fremdänderung: neue KI-Tests `IAiHost`/`AiScriptBase`, Projektdatei veraltet) und `work/dotnet-battleai` hat 1 fehlschlagenden Test aus derselben laufenden Fremdarbeit; beides berührt `Xnu.Game` nicht. Im Unity-Test-Runner nicht gelaufen (Editor tabu).

## 2. Aufbau und Änderungen

**Herkunft des Codes:** Alle C#-Dateien sind von Hand nach dem gelesenen Pseudocode formuliert und durch Tests geprüft; es gibt keinen maschinell übersetzten Code im Repo. Die `Vis("id:NAME …")`-Listen sind reine Kennungs-/Namenstabellen (aus `scripts/evscript_stats.py`), keine Logik.

| Datei | Inhalt |
|---|---|
| `HostCommandsMore.cs` (neu) | Befehle mit Wirkung auf den Spielzustand: Team/Box, Beutel, Flags/Zeit, Namenswörter, Fortbewegung/Objekte/Warp, Trainer, Dialog/Eingabe |
| `HostCommandsVisual.cs` (neu) | delegierte Befehle (`Vis`, Stufe N), Läden, Kamera, Pokécenter-Animation, TV-Werte, Speicheranfragen, `Promote` (Stufe nach Lesen des Pseudocodes anheben) |
| `WorldState.cs` (neu) | Sitzungszustand der Welt (Fahrrad/Surfen, Poketch-Apps, Sichttrainer, Objektsichtbarkeit/-position, Rekorde, Ballkapsel-Sticker, BP, Kamera, Pokécenter-Bälle, letzte Heilzone …) und `HostEvent` |
| `GameSessionWorld.cs` (neu) | `GameSession.World`, Zugriff auf Team/Box nach Skriptart (`GetMon(pos, tray)`), Zählungen, Uhr → Arbeitswert 0x1A2, Tageszeit |
| `ShopModel.cs` (neu) | Laden-Anfrage (`ShopRequest`), Angebot aus `ShopTables`, `Buy`/`Sell` mit Geld, BP und Beutelgrenze |
| `GameEvHostEvents.cs` (neu) | Ereignisprotokoll `GameEvHost.Events` (nur mit `Record`), Namenswörter aus Textlabels |
| `HostCommands.cs`, `GameSession.cs`, `GameEvHost.cs`, `GameTypes.cs`, `GameData.cs`, `GameLoop.cs` | kleine, abwärtskompatible Haken: `partial`, `InstallMore`, `GameInput.Text`, `GameData.Shops`, Dauer/Protokoll in `ExecuteCommand`, Niederlage (Abschnitt 3) |
| `EvInterpreter.cs`, `EvCmdId.cs`, `EvCommandTable.cs` | Kernbefehle `CMPWK` (19) und `CASE_CANCEL` (38) |

`IFieldHost` blieb **unverändert** (die Feldschicht des UI-Agenten implementiert sie bereits in `FieldHostAdapter`); alle neuen Anfragen laufen über `RunVisual(EvCommandCall)`.
Die Feldschicht kann das Ereignisprotokoll (`Events`: Kennung, Name, Argumente, Dauer in Frames) statt der Einzelaufrufe auswerten. **Dauer** = Zahl der Aufrufe bis der Befehl fertig meldet (30 Hz, wie `TIME_WAIT`); sie entsteht aus dem Warten auf die Feldschicht, nicht aus einer Tabelle. Zeitwerte im Skript (`TIME_WAIT`) bleiben im Interpreter.
Neue Eingabe: `GameInput.Text` (Namenseingabe; `null` = nichts eingegeben, Bestätigen ohne Text behält den Namen **[A]**).

## 3. Pokécenter, Heilung, Niederlage (belegt, Korrektur)

Ablauf der Schwester (Skript `common_scr`, Beschriftungen nur als Namen): `TEMOTI_BALL_LOAD_WAIT` → `GET_POKE_COUNT2` (523) → Schleife `POKECEN_PUT_BALL n` (979) + Ton + `TIME_WAIT 15` bis `n == Zahl` →
viermal `PC_RECOVER_ANM` (663) mit `TIME_WAIT 15` → `POKECEN_CLEAR_BALL` (980) → Kamera → Text → `PC_KAIFUKU` (480).

| Kennung | Name | Befund (Pseudocode `EvCmdGetPokeCount*`, `EvCmdPokecenPutBall`) |
|---|---|---|
| 522 | GET_POKE_COUNT | `Work = playerParty.count` (Teamgröße) **[P]** |
| **523** | **GET_POKE_COUNT2** | **Schleife über das Team, zählt `!IsEgg`**: Zahl der Mitglieder ohne Ei **[P]**. Scheibe 1 hatte „Teamgröße“ angenommen; mit einem Ei im Team hätte die Ballschleife dann einen Ball zu viel gesetzt |
| 524 | GET_POKE_COUNT3 | nicht leer, kein Ei, KP ≠ 0 **[P]**; 525, 1213 gleiche Zählung **[A]** |
| 979 | POKECEN_PUT_BALL | n-tes Mitglied **ohne Ei** (Zähler läuft nur über Nicht-Eier), Ball = `GetGetBall` → Ball im Kern gemerkt (`World.PokecenterBalls`), Modell/Platz in der Feldschicht **[P]** |
| 980, 663 | POKECEN_CLEAR_BALL, PC_RECOVER_ANM | `FieldPokemonCenterEntity.DestroyAllBall` / `PlayHealEffect` **[P]** (Feldschicht) |
| 480 | PC_KAIFUKU | Team und Boxen heilen **[P]**; Scheibe 2 merkt zusätzlich die Zone als Rücksetzzone (`World.LastHealZone`) **[A]** |

**Niederlage** (neu per Ghidra-Export `work/decomp/zenmetu`, zwei Läufe mit Sperre `work/ghidra.lock`, `-readOnly`, Heap 5 G): `FieldConnector.ZenmetuProc` setzt die Warp-Art „Zenmetsu“, **Systemflag 2 (Partner) aus**, entfernt den Begleiter und setzt den Spieler laut Tabelle
`ZenmetuZone` (19 Einträge: Pokécenter-Zonen `T02PC0101` … `C11PC0101`, Gitter 8/6, Ausgang 0, `townMapZoneID`) **[P]**; gewählt wird der Eintrag mit `zoneID == PlayerWork.transitionZoneID`; `SET_WARP_ID` (478, nur 3 × in den Daten) setzt diese Zone über `ZoneChangeSetZenmetu`.
`transitionZoneID` wird in `FieldConnector.SwitchingOperation/PrepareOperation/SetupOperation` gelesen und am Ende auf −1 gesetzt (Übergabewert, kein Dauerzustand) **[P]**. Der Dauerort „letztes Pokécenter“ steht im Save (`PlayerSaveData.zenmetu`/`ReturnZenmetsu_Ground`, `LOCATION_WORK`, Layout **[offen]**).
Der Kern nimmt deshalb ersatzweise die Zone des zuletzt benutzten Pokécenters (`PC_KAIFUKU`) **[A]**; Partnerflag-Reset ist **[P]**. Die `TRAINER_LOSE*`-Befehle bleiben, wie in Scheibe 1 belegt, im Original ohne Wirkung.

## 4. Befehlsgruppen

Zahlen aus `HostCommands.Table` (Kennungen) und `scripts/evscript_stats.py` (Befehle in den Daten); Gruppenzuordnung nach Namen.

| Gruppe | Kennungen | Befehle | P / A / N (Kennungen) | P / A / N (Befehle) |
|---|---|---|---|---|
| NPC, Objekte, Bewegung, Türen, Effekte | 82 | 3 528 | 42 / 1 / 39 | 3 001 / 203 / 324 |
| Dialog, Menü, Eingabe | 44 | 2 909 | 11 / 1 / 32 | 2 539 / 5 / 365 |
| Kamera | 24 | 1 376 | 8 / 0 / 16 | 1 316 / 0 / 60 |
| Sonstige (Hilfen, Zufall, Karten-/Gymmechanik) | 41 | 1 179 | 4 / 3 / 34 | 1 068 / 10 / 101 |
| Namenswörter | 37 | 1 142 | 13 / 18 / 6 | 853 / 252 / 37 |
| Ton (stumm als Ereignis) | 16 | 903 | 0 / 16 / 0 | 0 / 903 / 0 |
| Netz, Untergrund, Union, Wettbewerb, Kampfturm, TV, Safari, Pension, Naturpark, Begleiter, Pferd | 143 | 654 | 0 / 6 / 137 | 0 / 155 / 499 |
| Überblendung | 9 | 615 | 6 / 0 / 3 | 609 / 0 / 6 |
| Pokémon, Team, Zukan | 86 | 495 | 31 / 11 / 44 | 264 / 74 / 157 |
| Beutel, Geld, Läden | 23 | 283 | 12 / 2 / 9 | 204 / 66 / 13 |
| Flags, Works, Systemflags | 17 | 173 | 15 / 2 / 0 | 158 / 15 / 0 |
| Trainer, Kampf | 20 | 134 | 8 / 4 / 8 | 65 / 13 / 56 |
| Pokécenter, Box | 13 | 65 | 7 / 0 / 6 | 56 / 0 / 9 |
| Fahrrad, Surf, Hidenwaza | 24 | 62 | 8 / 3 / 13 | 17 / 21 / 24 |
| Zeit, Zufall | 7 | 52 | 4 / 1 / 2 | 49 / 1 / 2 |
| Warp, Karte, Zone | 11 | 51 | 4 / 1 / 6 | 42 / 1 / 8 |
| **Summe** | **597** | **13 621** | **173 / 69 / 355** | **10 241 / 1 719 / 1 661** |

### 4.1 Mit Pseudocode belegt und mit Wirkung umgesetzt (Auswahl, alle [P])

| Bereich | Kennungen (Argumente ab 1) |
|---|---|
| Team zählen/prüfen | 522–524 Zählungen; 696 `PARTY_MONSNO_CHECK(Art, W)`; 1041 `TEMOTI_POKE_CHK_NUM(W, Art)` (Art 0: Doppelte?), 1141 `…GET_POS` (erster Platz oder −1); 543 `TEMOTI_MONSNO(Pos, W)` (Ei → 0); 683 `COUNT_MONSBOX_SPACE(W)` (1 = Boxen voll) |
| Party-/Boxzugriff (`GetPokemonParam(tray, pos)`: tray ≥ 0 Box, sonst Team) | 221 `CHK_POKE_WAZA`, 571 `WAZA_COUNT`, 572 `WAZA_DEL` (Lücken schließen), 557/558 Freundschaft (0–255), 654/655 Bänder, 657 Fleißpunkte-Summe, 717/1197 Stufe, 625 Wesen, 995 Art aus Box, 994 Art in Team oder Box, 1216 alle Talentwerte 31, 1230 Persönlichkeitswert, 653 Zahl der Bänder im Team, 1172 Spitzname |
| Namenswörter | 313 Attacke, 315 Zahl (Text mit führenden Nullen oder Zahlenwort), 322 Art, 324/325 Art von Rivale/Begleiter, 328 Wesen, 574 Attacke eines Teammitglieds |
| Flags, Systemflags | 417–420 Poketch (Flag 0xCB, Apps), 445 (Flag 0x69 + Zukan an), 447 (Flag 0x4A), 449 Abzeichen setzen, 452, 456, 459, 461/463, 464, 467; 510 → Work 0xCD; 840 `LDVAL_VERSION` → Work 0xEE; 19 `CMPWK` (Work-von-Work); 38 `CASE_CANCEL` (Work 0xF2 gegen 0xF8) |
| Zeit | 658 `CHK_WEEK`, 702 `GET_NOW_HOUR` lesen **Work 0x1A2** (`USE_COMMAND_TIME`): Woche = Wert / 10⁸ − 1, Stunde = (Wert mod 10⁴) / 100; der Kern schreibt den Wert aus `WorldState.Clock` (Aufbau des Mittelteils **[A]**) |
| Beutel, Läden | 195 `CHECK_POCKET`, 215/216 Ballkapsel-Sticker, 747 (Item-Bereich 0x12A + 16), 612 Rekord +1, 236; Läden 912 (Zonenname), 921 (Nr.), 926 (Verkauf) mit `ShopRequest` |
| Fortbewegung | 293 Fahrrad abfragen, 1171 Form (1 Rad, 2 Surfen), 292 `NAMINORI` (Surfen an, Rad ab), 302/303 Blitz/Nebel, 1093 Farbe |
| NPC, Objekte | 165 Partner-Objekt, 505 Bewegungscode, 503 Position (`set_gridPosition` + Direct), 507 Ausgangsposition (Abschnitt 6), 813 Lage des Spielers zum Objekt im Zehnerblock (7 8 9 / 4 5 6 / 1 2 3, 0 = nicht benachbart), 549/550 sichtbar/unsichtbar |
| Trainer | 334/276 Sichttrainer (`EyeTrainerIds`), 338 `TRAINER_TALK_TYPE_GET` (Einzel 0/2/0, sonst 3/5/6), 337 `TRAINER_MSG_SET` (Art 0/3/7 vor dem Kampf, 2/5/9 danach, 6 ein Pokémon, 17–19 Revanche), 404 Fangvorführung (Art 399, Stufe 2) |
| Kamera | 942 `EVENT_CAMERA_INDEX(Index)` = `EventCamera.SetCameraData`, 943 wartet auf das Kameraende-Flag; Dauer aus der Feldschicht |
| Dialog | 114 `EASY_VOICE_MSG` (wie `EASY_MSG` mit Objektrahmen, Stimme entfällt), 77 `AB_KEY_TIME_WAIT`, 80 `TALK_OPEN` (Work 199 = 1) |
| Sonstige | 734 `GET_RANDOM_HIT(%, W)`, 1186 `SET_TELEPORT_ID`, 914 Türübergang, 1088 `AUTO_SAVE` (zählt Speicheranfragen, Schreiben macht die Oberfläche) |

Zusätzlich auf [P] angehoben, weil ihr zentraler Aufruf gelesen wurde (Wirkung bleibt Feldschicht): Überblendung weiß (281/282), Türanimation (829/830), Blick/Animationstempo (981/982/1102/880/881), Effekte (1052–1054, 1161), Pause/Position/Richtung/Größe/Sichtbarkeit (142–145, 163, 504, 509, 1062, 1191, 1103, 1035, 1192),
Statisten (816–819), 3D-Warten (487, 973), Kamerafahrten (1038/1069/972/814/815), Geldfenster (948/949), Verbeugung (1218), Wazen-Cutin (304), Suchrufe (1050/1051), 983, 1162, 323, 289.

### 4.2 Annahmen [A] (Kennung: was geraten ist)

Label-Namen der Namenswörter (311 Beutel-Fach, 319 Poketch, 327 Beeren, 656 Bänder, 759 Sticker, 970 Sprecher, 1095/1114 Park-/Untergrund-Items, 1180 Typen, 1181 Pofin, 1182 Kleidung: Datei und `NNN`-Nummerierung folgen den Dateinamen, der Aufruf ist gelesen); 320 Trainerart-Label;
217/545/599/626/671/672/762 (Argumentreihenfolge bei Team-Abfragen); 219 `ADD_TAMAGO` (Ei Stufe 1, Ball 4); 278/710 Namenseingabe über `GameInput.Text`; 316 Geburtstagsprüfung; 336 Doppelkampf-Anfrage; 348 `2VS2_BATTLE_CHECK`; 275 Sichttrainer-Typ;
670/1055 Kassette (10 = Diamant, nur durch `LDVAL_VERSION` gestützt); 722/731/765/1189 Zähler im Weltzustand; 935 `TELEPORT`; 1105 UG-Items; 1145–1147/1211 TV-Themenwerte (leer); Laden-Zuordnung Zone/Abzeichen (Freundschaftsladen) und Verkaufspreis = halber Preis; 923 BP-Laden.

## 5. Läden, Namenseingabe, Menüs

- **Läden:** `SHOP_OPEN_FIXED(Nr.)` (921) lädt aus `ShopTables.FixedShop` die Waren der Nummer, `DPR_SHOP_OPEN(Zone)` (912) den Freundschaftsladen (Zone, Abzeichenzahl ≥ `BadgeNum`), `SHOP_OPEN_BATTLE` den BP-Laden.
  Preis = `ItemRecord.Price` (BP-Laden `BpPrice`) **[A]**. `GameSession.Buy`/`Sell` prüfen Geld bzw. BP, Beutelgrenze 999 und das Angebot; Verkauf zum halben Preis **[A]**. Die Oberfläche zeigt `Session.Shop.Items` und ruft `Buy`/`Sell`; `DPR_SHOP_OPEN_WAIT` (913) schließt, sobald die Feldschicht fertig meldet. Seal-, Blumen-, Wetter-, Boutique-, Palpark-Läden sind nur Anfragen (Stufe N).
- **Namenseingabe:** `NAMEIN_POKE(Pos, Box, W)` setzt den Spitznamen aus `GameInput.Text` und schreibt Team/Box zurück; Ergebnis 1 = geändert. Bestätigen ohne Text lässt alles unverändert, Abbrechen ebenfalls.
- **Auswahl:** unverändert aus Scheibe 1 (Ja/Nein, eigenes Fenster). `TALKMSG_SP` (71, 31 ×) liest Datei/Label nicht aus einem Argument-String, sondern aus dem laufenden Skript; Auflösung **offen** (an die Oberfläche delegiert, öffnet keinen Text).

## 6. Fehler, die der Lauf gefunden hat und die behoben sind

| Befund | Behebung |
|---|---|
| 523 als Teamgröße angenommen (Abschnitt 3) | 523 zählt Nicht-Eier [P]; Test mit Ei im Team |
| `CMPWK` fehlte (2 999 Wiederholungen im Massenlauf von Scheibe 1) | Kernbefehl, Work-von-Work-Vergleich [P] |
| `SXY_EXIT_POS_CHANGE` (507, 470 ×) wurde wie `SXY_POS_CHANGE` mit Objektnamen behandelt; die Daten haben drei Zahlen (Ausgang, x, z) | eigener Handler: Ausgang → Position im Weltzustand, Feldschicht per `RunVisual` [P] |
| `TEMOTI_MONSNO` (543) gab für Eier die Art zurück | Ei/leer → 0 [P] |
| Artennamen fehlten im lokalen Lauf (`ss_monsname` liegt in `msg_common`, nicht in `msg_german`) | Lauf lädt die deutschen Dateien aus `msg_common`; **Hinweis an die UI-Schicht:** `GameDataLoader.Load` liest nur `msg_german`, dort fehlen `POKEMON_NAME`, `FIRST_POKEMON_NAME`, `RIVAL_POKEMON_NAME` usw. |
| Niederlage: Partnerflag und Rücksetzzone nur über `SET_WARP_ID` | Partnerflag aus [P]; ohne `SET_WARP_ID` letzte Heilzone [A] |
| Platzhalter im Test `UnknownHostCommandsAreCountedAsGapsAndDoNotBlock` (Kennung 1234 war nun belegt) | Test sucht eine freie Host-Kennung (bei null Lücken `Assert.Ignore`) |

## 7. Lauf mit echten Daten (nur Zahlen)

Quelle: `work/dotnet-game/check` (`dotnet run -c Release -- ../../..`, lokal, Save nur gelesen und im Speicher verändert, danach byte-gleich geprüft). Daten: 856 Skriptdateien, 12 985 Labels, 707 Trainer, 119 + 9 deutsche Textdateien, 659 `ZoneID`-Namen.

### 7.1 Alle 13 139 Skripte (Mock-Host, Team Stufe 50, 4 000 Ticks, Dauerbestätigung, danach bis zu 6 Läufe mit Zufallsantworten)

| Messgröße | Scheibe 1 | Scheibe 2 |
|---|---|---|
| unbekannte Befehle / Skripte mit Lücken-Aufruf | 406 Kennungen / viele | **0 / 0** |
| Fehler | 0 | **0** |
| beendet | 12 811 | **13 106** (davon 263 erst mit Zufallsantworten) |
| hängend nach 4 000 Ticks | 328 | **33** (`TALKMSG` 19, `TALK_KEYWAIT` 8, `TIME_WAIT` 4, `YES_NO_WIN` 2) |
| Kämpfe im Lauf | 370 (210 Niederlagen) | 368 (209 Niederlagen, 5 übersprungen: Trainerteam fehlt) |
| Host-Aufrufe | 1 307 386 umgesetzt, 78 569 Lücken | 1 335 736, Lücken 0; nach Stufe P 1 021 343 / A 205 693 / N 108 700 |

Die 33 Hänger sind Einstiegspunkte mitten in Abläufen, die ohne ihre Vorgänger nicht enden können: Heilanimationsschleife mit nicht belegtem Zähler (`pcwoman_pc_kaihuku_anim_common_loop*`, im Story-Lauf läuft dieselbe Animation ohne Hänger), Netz-/Union-Führer, Denkmal-Namenseingabe (verlangt echten Text),
Bibliotheksmenü, Move-Reminder-Auswahl, Ball-Anzeige der Ruhmeshalle. Keiner davon ist ein Kernfehler.

### 7.2 Story-Lauf (`Story.cs`; 20 Läufe mit Zufallsantworten, Starterwahl zufällig)

Aufbau (soweit aus den Daten ableitbar): Neues Spiel = alle Arbeitswerte/Flags 0, dann `ev_init_script` (init_scr). Startzone ist die der Anfangssequenz (`D27R0101`: ihr Szenenskript `SP_D27R0101_SCENE` ruft bei `WK_SCENE_D27R0101 == 0` das Rivalen-Ereignis auf, es endet mit `MAP_CHANGE "L01"`).
Je Zonenbetritt laufen `SP_<ZONE>_INIT`, `_FLAG`, `_SCENE`, danach die Kontaktfelder (`StopData`: `Work == Param`). Der Weg zwischen Zonen ist die kürzeste Strecke im Graphen aus `MapWarp` (Innenräume) und benachbarten Zellen des Zonenrasters `ZoneTable` (Außenwelt); Ziel ist das nächste Pokécenter
(Läufe mit geradem Startwert: ausdrücklich `C01PC0101`), dort Gespräch mit der Schwester (`PlaceData`-Label `…pcwoman…`).

| Messgröße (20 Läufe) | Wert |
|---|---|
| erster Kampf erreicht (Tutorial-Wildkampf der Anfangssequenz, Gegner Stufe 2) | 20 / 20 |
| Pokécenter erreicht, Schwester-Gespräch beendet, `PC_KAIFUKU` ausgeführt | 20 / 20 |
| Zonenbetritte je Lauf | 4–6 (z. B. `D27R0101 > L01 > C02 > C02PC0101`, mit Ziel `C01PC0101`: `… > C02 > R218 > C01 > C01PC0101`) |
| Ereignisse je Lauf / beendet / hängend / Fehler / unbekannter Befehl | 13–14 / alle / 0 / 0 / 0 |
| ausgeführte Host-Kennungen im Lauf | 61 (127 Aufrufe) |

**Grenzen:** Die Strecke ist eine Graphensuche, nicht der Spielweg. Kontaktfelder lösten nicht aus (ihre Arbeitswerte stehen am Anfang nicht auf dem Sollwert; die Spielstände dazwischen entstehen im echten Spiel durch Gespräche, die hier nicht geführt werden),
Sichtkämpfe und Gespräche mit Personen fehlen, Positionen und Sperren (Flaggen an Warps) sind nicht modelliert. Der Lauf zeigt, dass die Skripte der Anfangszonen samt Szenenskripten, Rivalenereignis, Kampf, Zonenwechsel und Pokécenter-Ablauf mit dem Host durchlaufen; er sagt nichts über Dauer, Reihenfolge oder Darstellung **[O fehlt]**.

## 8. Lücken und Aufwand

| Lücke | Aufwand (Schätzung) |
|---|---|
| 355 Kennungen nur [N] (Kampfturm, Wettbewerb, Netz/Union/Untergrund, Pension, Safari, Naturpark, Begleiter, Pferd, Ballkapsel, TV-Erzeugung, Arenenmechanik, Beerenbeete, Honigbäume): je Gruppe Pseudocode lesen und Zustand im Kern bauen | 1–2 Tage je Gruppe (Pension, Beerenbeete, Honigbäume zuerst; Kampfturm 3 Tage) |
| Feld- und UI-Schicht: `RunVisual` für die 414 Feld- und 29 Warte-Kennungen, Ereignisprotokoll mit Dauern auswerten, Läden/Teamliste/Beutel/Box-Oberfläche, Namenstastatur | 5–8 Tage (Feldschicht: 3–4, Oberfläche: 3–4) |
| Zustand ohne Ort im Save (`WorldState`: Poketch-Apps, Rekorde, Ballkapsel-Sticker, UG-Items, BP, TV-Werte, Rücksetzort `zenmetu`, Zukan): Offsets aus `docs/save-spec-entwurf.md` ergänzen, sonst gehen sie beim Speichern verloren | 2–3 Tage |
| Wildgenerierung, Begegnungsschritt, Tageszeit/Wetter (Scheibe 1, unverändert) | 2–3 Tage |
| `TALKMSG_SP`, `SEACRET_POKE_RETRY_CHECK`, `GROUP_EXIST_CHECK`, `WAZA_ITEM_CHK`/`ITEM_WAZA_NAME` (Maschinentabelle in `IBattleData`), `GET_TAG_PATNER_ID` | 1 Tag |
| Story-Lauf mit echten Gesprächen/Kontaktfeldern (Positionen, Sperrflaggen der Warps, Sichtkämpfe) | 3–4 Tage, braucht die Feldschicht |
| Orakel [O] für Dialog-/Bewegungs-/Kameraabläufe | nicht möglich ohne laufendes Original |
| Unity-Test-Runner, `.meta`-Dateien der neuen Dateien (Unity erzeugt sie beim ersten Import) | 15–30 Minuten, sobald der Editor frei ist |

## 9. Reproduktion

- Tests: `dotnet test work/dotnet-game/Game.csproj` (Wegwerfprojekt, kompiliert die Unity-Quellen direkt; `GameUnityTests.cs` ist ausgenommen, weil es Unity braucht).
- Massenlauf und Story-Lauf: `cd work/dotnet-game/check && dotnet run -c Release -- ../../..` (alles), `… -- ../../.. story 20` (nur Story-Lauf mit 20 Seeds), `… -- ../../.. table` (Tabelle Kennung, Name, Stufe, Art).
- Pseudocode: `python3 work/evscript/fn2.py <Kennung> …` (kompakte Ansicht des Handlers, folgt einem Aufruf eine Ebene tief), `python3 work/evscript/listscr.py <Datei> [Label-Regex]` (Skript als Befehlsliste).
  Neuer Ghidra-Lauf nur für die Niederlage: `scripts/ghidra/run_headless.sh … -postScript ExportDecompiled.java 'ZenmetuProc|ZoneChangeSetZenmetu|…' work/decomp/zenmetu` und `CallersOf.java` (Sperre `work/ghidra.lock`).
