# Spielkern: Spielschleife, Ereignis-Host, Kampf- und Begegnungsanbindung (Todo `ap-game-flow`)

Stand: 2026-10-19. Nur Namen, Zahlen und Struktur; keine Spieltexte, keine Daten, keine echten Saves im Repo. Code: `unity/Assets/Scripts/Game` (Assembly `Xnu.Game`, reines C#, `noEngineReferences`),
Tests: `unity/Assets/Tests/EditMode/GameFlowTests.cs` und `GameFixture.cs`. Prüfstufen wie in `docs/evscript-spezifikation.md`: **[P]** Handler-Pseudocode gelesen, **[A]** Annahme (Name, Argumentform oder Teilbefund),
**[N]** nur Name und Aufrufliste, **[O]** Orakel (laufendes Original): **für nichts davon vorhanden**.
**Fortsetzung und Korrekturen: `docs/spielkern-2.md`** (alle 599 Host-Kennungen belegt; Befehl 523 ist `GET_POKE_COUNT2` = Zahl der Mitglieder ohne Ei, nicht die Teamgröße; Abschnitt 3 dort).

## 1. Ergebnis in Kürze

- Die Module sind zu einem **headless lauffähigen Kern** verbunden: `GameSession` (Spielstand + Variablen im `SaveData`-Puffer) → `GameEvHost` (konkreter `IEvHost`) → `GameLoop` (Zustandsmaschine `Field`, `Event`, `Battle`, `Menu`) → `BattleSession`
  (`BattleFlow`-Engine) und `IFieldHost` (Schnittstelle zur Feldschicht). Eingabe und Feldmeldungen sind reine Daten (`GameInput`, `FieldSignal`).
- **Host-Befehle:** von den 599 Host-Kennungen sind **168** (28 %) umgesetzt; sie decken **11 537 von 13 623 Host-Befehlen** der Daten ab (**84,7 %**). Davon **38 Kennungen mit Pseudocode belegt [P]** (5 977 Befehle, 43,9 %),
  31 [A] (2 068; 15,2 %), 99 [N] (3 492; 25,6 %). Wirkung auf Spielzustand 30, Delegation an die Feld-/Oberflächenschicht 117, Warten auf Eingabe/Feld 5, **Ton bewusst ohne Wirkung 16** (Regel „kein Sound“; 903 Befehle).
  Die 61 Kernbefehle des Interpreters (`docs/evscript-spezifikation.md`) kommen hinzu; 431 Host-Kennungen sind Lücken (Abschnitt 8).
- **Echtdatenlauf** (Abschnitt 6): Das Ereignis der Anfangssequenz (Datei `d27r0101`, Label `ev_d27r0101_rival`) läuft mit Mock-Eingaben und dem echten Skriptbuch, Text und Stammdaten **bis zum ersten Kampf** (233 Ticks, 15 Textfenster,
  Startwahl, `ADD_POKEMON`, `FIRST_BTL_SET`), der Kampf wird gespielt (Sieg in 2 Runden), das Ereignis endet ohne Fehler. Alle 13 139 Skripte laufen mit dem echten Host ohne Fehler (12 811 enden, 328 drehen sich in Mock-Schleifen).
- 28 neue Szenario-Tests (synthetische Daten), im Wegwerfprojekt `work/dotnet-game` zusammen mit den 38 EvScript-Tests **66 von 66 grün**. Im Unity-Test-Runner noch **nicht** gelaufen (Editor war tabu); `.meta`-Dateien erzeugt Unity beim ersten Import.

## 2. Architektur

```
Feldschicht (Unity)          Spielkern (Xnu.Game, ohne UnityEngine)                   bestehende Module
 FieldSignal  ───────────►  GameLoop ──► EvInterpreter ──► GameEvHost ──► GameSession ──► SaveData / EvSaveVariables
 GameInput    ───────────►     │                              │  │             │
 IFieldHost  ◄───────────────  │                              │  └► DialogModel/ChoiceModel (Xnu.Text: MessageBank, MessageComposer)
                               └──► BattleSession ──► BattleEngine (Xnu.Battle.Flow) ──► PokemonParam (Xnu.PokePara)
```

| Datei | Inhalt |
|---|---|
| `GameTypes.cs` | `GameState`, `GameInput`, `FieldSignal`, `EncounterKind`, `BattleRequest` |
| `GameData.cs` | `IGameData`/`GameData`: `IBattleData`, `MessageBank`, Trainer, Begegnungstabellen, Namensauflösung `TrainerID`/`ZoneID` (aus `dump.cs`, nicht im Repo) |
| `GameSession.cs` | Spielstand, Ereignisvariablen, Beutel (Obergrenze 999), Geld (0…999 999), Team, Heilung, neues Pokémon, Abzeichenzahl, Sitzungs-Zufall |
| `GameEvHost.cs` + `HostCommands.cs` | `IEvHost`; Tabelle der Host-Befehle mit Prüfstufe und Art; unbekannte Kennungen zählen als Lücke (`Gaps`) und gelten als fertig |
| `DialogModels.cs` | `DialogModel` (Seiten aus `ComposedMessage`, weiter mit Bestätigen), `ChoiceModel` (Ja/Nein, eigene Fenster) |
| `IFieldHost.cs` | Schnittstelle zur Feldschicht; `NullFieldHost` (sofort fertig, protokolliert) für Tests und lokale Läufe |
| `BattleSession.cs` | baut `BattleSetup` (Team aus dem Save, Gegner aus Trainerteam oder Wildgenerierung, Beutel, Abzeichen, Geld), nimmt Befehle als Daten, schreibt Team/Beutel/Geld zurück |
| `EncounterService.cs` | Wildbegegnung aus `FieldEncountTable` (Abschnitt 5) |
| `GameLoop.cs` | Zustandsmaschine; `AutoPlayer` spielt ohne Mensch (Texte bestätigen, Auswahl, Startwahl, erste brauchbare Attacke) |

### Zustandsmaschine

| Zustand | Tick-Verhalten | Übergänge |
|---|---|---|
| `Field` | `FieldSignal` auswerten: `Talk`/`Contact` → Ereignis (`StartEvent(label)`), `Warp` → `IFieldHost.ChangeZone`, `Step` → Wurf auf die Begegnungstabelle; `Menu`-Taste → `Menu` | → `Event`, → `Battle`, → `Menu` |
| `Event` | `GameEvHost.FeedInput` (Eingabe an offene Fenster), dann `EvInterpreter.Update`; ein Kampfwunsch (`TRAINER_BTL_SET`, `WILD_BTL_SET`, `FIRST_BTL_SET`, `SP_WILD_BTL_SET`) wird übernommen, das Skript pausiert | → `Battle`, bei Ende/Fehler → `Field` |
| `Battle` | `BattleSession.Step`: Spielerbefehl/Ersatz aus `GameInput`; bei Ende Ergebnis in den Save, Preisgeld oder Abzug | Sieg/Flucht → `Event` (Wunsch kam vom Skript, das weiterläuft) oder `Field`; **Niederlage → Rückkehr** |
| `Menu` | schließt mit Abbrechen/Menü | → `Field` (Menüinhalte sind Lücke) |

Ablauf wie im Original: Während eines Kampfs läuft der Interpreter nicht (`TRAINER_BTL_SET` wartet in `BattleIsDone`); nach dem Kampf macht das Skript mit dem nächsten Befehl weiter. Weitere Regeln:

- **Eingabe als Daten:** Tasten gelten pro Tick als „gerade gedrückt“; ein neu geöffnetes Fenster sieht die Taste des Öffnens nicht (Eingabe wird vor dem Interpreter verteilt). Kampf: `GameInput.Battle` (ein `BattleCommand`) in `AwaitCommands`,
  `Replacement` (Party-Index) in `AwaitReplacement`. Startwahl: `StarterChoice` (0–2).
- **Dialog:** `TALKMSG`/`TALK_KEYWAIT`/`EASY_*_MSG` → `MessageBank.TryGetLabel(datei, label, Sprache)` → `MessageComposer` mit den gesetzten Namenswörtern → Seiten. Seitenwechsel ist `ScrollPage` oder das Ende, `NewLine`/`ScrollLine` bleiben auf der Seite,
  `Wait`-Ereignisse zählen nicht **[A]**. Fehlt das Label, öffnet sich ein leeres Fenster (Zähler `MissingLabel`).
- **Ja/Nein:** Index 0 = „Ja“ **[A]**, Abbrechen wählt „Nein“ **[A]**. Eigenes Fenster: Cursor → Rückgabewert über `ADD_CUSTUM_WIN_LABEL`, Abbrechen wählt die letzte Zeile **[A]**.
- **Kartenwechsel:** `MAP_CHANGE(Zonenname, Locator)` → `IGameData.ResolveZoneName` → `IFieldHost.ChangeZone`; das Skript wartet, bis `ChangeZoneIsDone()` wahr ist. `BeforeZoneId` wird mitgeführt. Unbekannter Zonenname: Zone bleibt, Wechsel läuft trotzdem.

## 3. Schnittstellen

- `IFieldHost` (Feldschicht implementiert sie): `ChangeZone`/`ChangeZoneIsDone`, `SetEventMode`, `TurnToTalkPartner`, `SetObjectVisible`, `SetObjectGrid`, `GetPlayerGrid`, `Fade`/`FadeIsDone`, `AnimateObject`/`AnimationsDone`
  (Bewegungsskript `AC_*` aus demselben `EvData`-File), `RunVisual(EvCommandCall)` für alles Übrige (Kamera, Effekte, Türen, Läden, Listen, Speichern). `RunVisual` darf Ergebnis-Work über den Aufruf schreiben.
- `IGameData`: Stammdaten und Namensauflösung. Die echten Tabellen kommen aus `MasterDataReader`/`MasterData2Reader` (Beispiel: `work/dotnet-game/check/Program.cs`).
- Eingang: `GameLoop.Tick(dt, GameInput, FieldSignal?)`, `StartEvent(label)`. Ausgang: `GameLoop.State`, `Host.Dialog`/`Host.Choice` (Darstellung), `Battle.Engine` (Kampfdarstellung über `Engine.Log`), Zähler und `Trace`.
- Namenskonflikt: `Xnu.Game.GameInput` (Datenmomentaufnahme) und `Xnu.Input.GameInput` (MonoBehaviour der Eingabeschicht) liegen in verschiedenen Namensräumen; Dateien, die beide importieren, müssen qualifizieren oder die Datentypen umbenennen
  (Empfehlung beim Bau der Feldanbindung: `GameInputFrame`).

## 4. Host-Befehle: was belegt ist

Vollständige Tabelle: `HostCommands.Table` (Kennung, Name, Stufe, Art). Neu aus dem Pseudocode gelesen (Ghidra-Export `work/decomp/evscript2`, Hilfsskript `work/evscript/fn.py`) **[P]**:

| Kennung | Name | Befund |
|---|---|---|
| 479 | GET_MY_SEX | `Work[arg1] = playerStatus.sex ^ 1` (Byte bei +0x10). Im Save ist `SexRaw` das Byte; Zuordnung 0/1 ↔ Geschlecht bleibt offen |
| 448, 450 | SYS_FLAG_BADGE_GET/COUNT | GET: `Work[arg2] = Systemflag[arg1]`; COUNT: Summe der Systemflags 0x7C…0x83. **Am echten Save bestätigt:** alle acht gesetzt = 8 Abzeichen (Spielstand mit allen Abzeichen) |
| 290 | GET_NOW_ZONE_ID | `Work = PlayerWork.zoneID` |
| 554 | GET_TIME_ZONE | `Work = GameManager.currentPeriodOfDay`; Zahlenzuordnung **[A]**, die Uhr liefert die Feldschicht |
| 522 | GET_POKE_COUNT | `Work = Teamgröße` (`playerParty.count`) |
| 563 | TEMOTI_POKE_CHK | `Work[arg1] = 1`, wenn ein Teammitglied (nicht leer, kein Ei) die Art `arg2` hat, sonst 0 |
| 326 | FIRST_POKE_NO_GET | `Work = PlayerWork.defaultPokeNo` (Starter-Art); Ort im Save nicht belegt → Sitzungswert |
| 194 | GET_POCKET_NO | `Work[arg2] =` Tascheninformation des Items (Item-Parameter 0xE) = `ItemRecord.FieldPocket` **[A: Feldzuordnung]** |
| 480 | PC_KAIFUKU | `playerParty.RecoverAll()` und `BoxPokemonWork.RecoverAll()`: KP und PP voll, Zustände weg; Teammitglieder und Boxen |
| 218 | ADD_POKEMON | `InitialSpec{monsno = arg1, level = arg2, talentVNum = arg5}`, Item `arg3` wenn ≠ 0, Herkunft `SetFromCapture`, `playerParty.AddMember`, `Work[arg4] = Ergebnis & 1`, Zukan-Eintrag „gefangen“, Poketch-Verlauf. Zufallswerte der Erzeugung: **[A]** (Abschnitt 5) |
| 401, 403 | WILD_BTL_SET, FIRST_BTL_SET | `SetBattleReturn`, dann `FieldManager.EventWildBattle(arg1 = Art, arg2 = Stufe, …)`; `FIRST_BTL_SET` setzt zusätzlich Kampfstatusflag 0x100 und die Tutorial-Effektdaten |
| 402 | SP_WILD_BTL_SET | Kopf gelesen: Art `arg1`, Stufe `arg2`, weitere Argumente (Rare-Flag u. a.) werden nicht ausgewertet |
| 478 | SET_WARP_ID | `FieldManager.ZoneChangeSetZenmetu(zone)`: **Rücksetzzone nach Niederlage** („Zenmetsu“ = Auslöschung); gesetzt von den Pokécenter-Skripten |
| 259 | FIRST_POKE_SELECT_PROC | startet die Starter-Demo (`Demo_Gosanke`) und liefert 0, bis deren Rückruf den Zustand auf 2 setzt. Die Starter-Arten (387/390/393) stammen aus den Fallunterscheidungen des Skripts **[A]**; `FIRST_POKE_SELECT_SET_AND_DEL` (260) und `SET_MAP_PROC` (230) sind im Original ohne Wirkung |
| 453, 454, 455 | SYS_FLAG_PAIR_GET/SET/RESET | Systemflag 2 (Bedeutung „Partner läuft mit“ nur aus dem Namen und dem Aufruf von `NPCToPartner`); RESET ruft zusätzlich `FieldWalkingManager.NPCToPartner(…, false)` (Feldschicht) |
| 306, 307 | PLAYER_NAME, RIVAL_NAME | `MessageWordSetHelper.SetPlayerNickNameWord/SetRivalNickNameWord(slot = arg1)`; Name aus `SaveData.PlayerName`/`RivalName` |
| 310, 314 | ITEM_NAME, NUMBER_NAME | `SetItemWord(slot, item, x)` (dritter Wert ungeklärt, ignoriert) und `SetDigitWord(slot, zahl)`; Itemname aus `ss_itemname`, Label `ITEMNAME_nnn` (Index = Item-Nummer, `docs/masterdata.md`) |
| 155, 154, 151, 152, 153, 156, 157 | EVENT_START, TALK_START, TALK_OBJ_START(_TURN_NOT), TALK_OBJ_END, TALK_END, EVENT_END | laut `docs/evscript-spezifikation.md` [P]: Objekte anhalten/fortsetzen, Eingabe sperren/freigeben, Drehen zum Gesprächspartner |
| 146, 147, 158, 161, 283, 284, 836, 784 | OBJ_ADD/DEL, PLAYER_POS/DIR_GET, BLACK_OUT/IN, FADE_SPEED/WAIT | laut Spezifikation [P]; Argumente der Bewegungsbefehle 503/506/507 und `WHITE_*` sind **[A]** |

Weitere Befunde (nicht umgesetzt): `CMPWK` (19) steht in der Hosttabelle, schreibt aber den Vergleichsmerker `_cmp_flag` des Interpreters (`a<b → 0`, `a==b → 1`, sonst 2) – gehört in den Kern (1 Befehl in den Daten).
`TALK_OPEN` (80) setzt `Work[199] = 1` nur, wenn Zeilenzustand und beide Texte gesetzt sind (Fensterparameter des Originals); `TRAINER_MSG_SET` (337) öffnet einen Text aus `GetTrainerMsg(trainer, art)`;
`ZENKOKU_ZUKAN_FLAG` (651): Modus 1 = `ZukanWork.ZenkokuON`, Modus 2 = Zustand lesen (umgesetzt als Sitzungswert **[A]**).

Delegiert **[N]** (`HostKind.Field`, `RunVisual`): Kamera (`EVENT_CAMERA_INDEX/…`), Effekte, Türen, Blick/Blinzeln/Animationsgeschwindigkeit, Statisten (`DUMMY_*`), Objekt-Pause/-Skalierung/-Position, Läden (`DPR_SHOP_*`, `SHOP_OPEN_*`),
Listen/Beutel/Box/Dendou-Oberflächen, Speichern, Pokécenter-Animation, Sichttrainer-Bewegung, Fahrrad. Ergebnis-Work schreibt die Oberfläche; die Wirkung im Original ist nicht gelesen.
Tafeln (`EASY_BOARD_MSG`, `EASY_INFOBOARD_MSG`) öffnen ein Textfenster und warten auf Bestätigung **[N]**; `AB_KEYWAIT` wartet auf Bestätigen/Abbrechen.

Vom Interpreter nie an den Host gereichte Kennungen (im Original ohne Wirkung): 149 `VANISH_DUMMY_OBJ_DEL` und 825–828 (`EVENT_CAMERA_MODE/…`) sind **No-Ops** der Sprungtabelle; der Test `EveryCatalogEntryIsAHostCommandOfTheInterpreter`
prüft, dass jede Kennung der Tabelle wirklich als Host-Befehl eingeordnet ist (hat die fünf Fehlgriffe gefunden).

## 5. Begegnungen, Kampf, Niederlage

- **Trainerkampf** (`TRAINER_BTL_SET`): Name → `TrainerID` → `TrainerRecord` → Team über `PokemonFactory.FromTrainerPokemon`; `TrainerData.Gold` für das Preisgeld ([P], `docs/kampf-spezifikation-5.md`: `(Gold & 0xFF) × letzte Stufe × 4`);
  Kampfwunsch ohne Team (unbekannter Trainer) wird übersprungen (Zähler `BattlesSkipped`), damit das Skript nicht hängt. Das Sieg-Flag setzen die Skripte selbst (`TRAINER_FLAG_SET`); ob das Original es zusätzlich im Kampfrückkehrpfad setzt, ist nicht gelesen.
- **Wildkampf aus dem Skript:** Art und Stufe aus den Argumenten; die Erzeugung (Wesen, Werte, Fähigkeit, Geschlecht) nutzt `PokemonFactory.CreateWild` **[A]** – die echte Erzeugung (`Pml.PokePara.InitialSpec`, `EncountTools`) ist nicht dekompiliert.
- **Wildbegegnung im Feld** (`FieldSignal.Step`): `EncounterService.Roll` nimmt die Zone, Rate (`encRate_*`) und Slots der `FieldEncountTable` (belegt). **Nicht belegt [A]:** die Schrittprüfung (`Zufall(100) < Rate`) und die Slot-Gewichte
  (Gras 20/20/10/10/10/10/5/5/4/4/1/1, Wasser und Angeln aus den Vorgängerspielen). `EncounterService.*Weights` sind öffentlich und lassen sich ersetzen, sobald `Encount` gelesen ist. Zeit-/Wetter-/Mehrfachlisten (`Day`, `Night`, `Swarm`, GBA-Listen, `FormProb`) sind **Lücke**.
- **Rückkehr nach Niederlage:** Ereignis abbrechen (`EvInterpreter.Abort`), Abzug (`CalcPenaltyMoney` [P]; Tabelle **[A]**, `docs/kampf-spezifikation-5.md`), Team und Boxen heilen, Warp zur Zone aus `SET_WARP_ID` (`Session.WipeoutZone`; −1 = bleibt stehen),
  Zustand `Field`. Dass das Original den Wiederbelebungsort über genau diesen Wert wählt und wie es das Pokécenter-Gespräch abspielt, ist nur über den Befehlsnamen und die Aufrufstelle belegt **[A]**.
- **Heilung/Pokécenter:** `PC_KAIFUKU` [P] (Abschnitt 4); der Ablauf der Schwester (Ballanimation, Texte) steckt in den Skripten und in `POKECEN_*`/`PC_RECOVER_ANM` (delegiert).

## 6. Prüfung

**Synthetische Tests** (`GameFlowTests`, 28; erfundene Arten, Texte und Trainer aus `BattleFlowTestData`/`GameFixture`, leerer Save): Dialogseiten und Bestätigen; Namenswörter erreichen die Nachricht; Item-/Zahlwörter; Ja/Nein und eigenes Fenster;
Work/Flags/Systemflags/Beutel/Geld verändern die Save-Bytes und überleben `ToBytes`/Neuladen; Obergrenzen (999, 999 999); `ADD_POKEMON`, volles Team, `PC_KAIFUKU`, `GET_MY_SEX`; Trainerkampf im Ereignis mit Preisgeld und Fortsetzung;
Erfahrung wird in den Save geschrieben; Niederlage (Abzug, Heilung, Warp, Abbruch); fehlender Trainer; Startwahl und `FIRST_BTL_SET`; `WILD_BTL_SET`; `MAP_CHANGE` mit Wartezeit; Ereignisrahmen/Objekte/Überblendung/Ton; Lückenzähler;
Feldmeldungen (Talk, Warp); Gras-Begegnung aus der Tabelle; Rate 0/fehlende Tabelle; Slot-Gewichte; Menü; Ereignisstart im Kampf verweigert; Katalogkonsistenz.

**Lokaler Durchlauf** (`work/dotnet-game/check`, nur Zahlen; Save nur gelesen und im Speicher verändert, danach byte-gleich geprüft):

| Messgröße | Wert |
|---|---|
| Daten | 856 Skriptdateien, 12 985 Labels, 707 Trainer, 183 Zonen mit Begegnungen, 119 deutsche Textdateien, 709 `TrainerID`- und 659 `ZoneID`-Namen |
| Save-Variablen (echter Save) | Flags 4000/4000 sind 0/1 (573 gesetzt), Systemflags 1000/1000 sind 0/1 (411 gesetzt), Abzeichen 8; Trainer-Feld 0: 707/707 ∈ {0,1} (324 mit 1), Feld 1: 707/707 = 0. → 4-Byte-Schritt der Flags **belegt**; das Trainer-Layout (Sieg, Suche je 4 Byte) bleibt **[A]** (konsistent, aber „Suche“ nie gesetzt) |
| A1 Anfangssequenz `ev_d27r0101_rival` | bis zum ersten Kampf 233 Ticks (≈ 7,8 s bei 30 Hz), 130 Befehle (Kern 86, Host 39, ohne Wirkung 5), 15 Textfenster, Team 0 → 1, Starter-Art = Wahl 1 |
| A2 Kampf | Wildkampf, Tutorial gesetzt, Gegner Art 396 Stufe 2 gegen Starter Stufe 5 |
| A3 Kampfende | Sieg nach 2 Runden (2 Ticks), Zustand wieder `Event` |
| A4 Ereignisende | nach 51 weiteren Ticks, Status `Ended`, kein Fehler, 21 Feld-Aufrufe, **1 Lücke** (Kennung 324 `RIVAL_POKEMON_NAME`) |
| B alle 13 139 Skripte (Team Stufe 50, Mock-Eingaben, 4000 Ticks) | beendet 12 811, wartend 328 (822 `OPEN_CUSTUM_WIN` ×126, 70 `TALKMSG` ×122, 83 ×40, 4 `TIME_WAIT` ×37, 96 `YES_NO_WIN` ×3: Menü-/Gesprächsschleifen mit Dauerbestätigung), **Fehler 0** |
| B Kämpfe | 370 beendet (210 Niederlagen des Test-Teams, 5 übersprungen wegen fehlendem Trainerteam) |
| B Host-Aufrufe | umgesetzt 1 307 386 (168 Kennungen), Lücken 78 569 (406 Kennungen) → 94,3 % der Aufrufe (nach Schleifenwiederholungen gewichtet); statisch 84,7 % der Befehle |
| häufigste Lücken (Kennung × Aufrufe) | 527 `UG_SHOP_MENU_INIT` 22 551, 892 `CON_WAIT_CONTEST_MENU` 12 043, 995 `TEMOTI_BOX_MONSNO` 12 003, 1144 4 000, 711/710 `MONUMENT_NAME` je ≈ 3 300, 19 `CMPWK` 2 999, 1061 1 747, 334 `TRAINER_ID_GET` 1 726 |

Bewertung: „Läuft ohne Fehler“ heißt, dass jede Kennung Kern, No-Op, umgesetzt oder als Lücke gezählt ist und kein Skript abstürzt. Es heißt **nicht**, dass Reihenfolge, Dauer oder Darstellung dem Original entsprechen **[O fehlt]**.
Die Anfangssequenz wurde ohne Feldschicht gespielt (`NullFieldHost`): Bewegung, Kamera und Animationen sind nicht geprüft.

## 7. Prüfstufen im Überblick

| Bereich | Stufe |
|---|---|
| Interpreter-Kern, Variablen im Save (Flags, Systemflags, Work) | [P]; Flag-/Systemflag-Layout am echten Save bestätigt |
| 38 Host-Kennungen (Abschnitt 4) | [P] |
| 31 Host-Kennungen (Teilbefund, Argumentreihenfolge, Ton) | [A] |
| 99 Host-Kennungen (delegiert, Tafeln, Warten) | [N] |
| Kampfanbindung, Preisgeld, Niederlage-Abzug | [P] Formeln, Tabelle [A] |
| Begegnungsraten und -slots (Daten) | belegt; Schrittprüfung, Slot-Gewichte [A] |
| Wildgenerierung (Werte, Wesen, Geschlecht) | [A] |
| Dialogseiten, Ja/Nein-Zuordnung | [A] |
| Zeit- und Frameverhalten der Abläufe | [O] fehlt |

## 8. Lücken und Aufwand

| Lücke | Aufwand (Schätzung) |
|---|---|
| Feldanbindung: `IFieldHost` für `Xnu.Field` (Zonenwechsel mit `MapWarp`, Objekte aus `PlaceData`, `AC_*`-Bewegungsskripte, Kamera, Überblendung), Signale (Ansprechen, Kontaktfelder, Sichtfelder) | 4–6 Tage |
| Startlogik: welches Label wann startet (`PlaceData.TalkLabel`, `StopData.ContactLabel`, `MapWarp.ScriptLabel`, `SCENE_CHANGE_LABEL`/`INIT_CHANGE_LABEL` je Karte, Szenen-Work) | 2–3 Tage |
| Oberfläche: Textfenster, Menüs, Läden (Shop-Befehle sind nur delegiert), Team-/Beutelmenü (`Menu`-Zustand ist leer), Speichern | 5–8 Tage |
| restliche 431 Host-Kennungen: Pseudocode je Gruppe lesen (Pokémon/Team/PC/Zukan 99, Kampfturm, Wettbewerb, Untergrund, TV, Namenswörter 311–322) | 2–3 Tage je Hauptgruppe |
| Wildgenerierung und Begegnungslogik (`Encount`, `EncountTools`, `InitialSpec`): Schrittprüfung, Slot-Gewichte, Tageszeit/Wetter/Massenauftreten, Zufallsform | 2–3 Tage (Ghidra-Lauf für `Dpr.Encount.*`) |
| Trainer: Sichtkampf-Gruppen und Sichtfeld, Doppelkämpfe (`TRAINER_MULTI_BTL_SET`), Sieg-Flag im Kampfrückkehrpfad, Revanche | 3–4 Tage |
| Niederlage im Original (Texte, Pokécenter-Ablauf, Zielort), Geld-Tabelle des Abzugs | 1–2 Tage |
| `CMPWK`/`CMPVAL` in den Interpreter-Kern, `TALK_OPEN`, `TRAINER_MSG_SET`, `TRAINER_ID_GET` | 1 Tag |
| Gegner-KI (`docs/kampf-spezifikation-5.md`), Fang, Lernen, Entwicklung im Kampf | wie dort |
| Orakel [O] für Dialog-/Bewegungsabläufe | nicht möglich ohne laufendes Original |
| Test im Unity-Runner, `.meta`-Dateien, Umbenennung `GameInput` | 15–30 Minuten |

## 9. Reproduktion

- Tests: `dotnet test work/dotnet-game/Game.csproj` (Wegwerfprojekt, nicht im Repo; kompiliert die Unity-Quellen direkt, NUnit).
- Echtdatenlauf: `cd work/dotnet-game/check && dotnet run -c Release -- ../../..` (liest `work/masterdata`, `work/il2cpp/dump.cs` und den lokalen Save; schreibt nichts).
- Pseudocode: `python3 work/evscript/fn.py EvCmdName …` (Funktionen des Ghidra-Exports `work/decomp/evscript2`) und `bash work/evscript/show.sh <Kennung>` (Handler je Kennung); kein neuer Ghidra-Lauf war nötig.
