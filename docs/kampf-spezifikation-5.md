# Kampfablauf, Scheibe 5: Handler-Wirkungen, Seiten-/Feldeffekte, Sonderattacken, Preisgeld

Stand: Scheibe 5, aufbauend auf `docs/kampf-spezifikation-4.md` (Ablauf-Zustandsmaschine). Code: `unity/Assets/Scripts/BattleFlow`
(`BattleEngine.Effects.cs`, `BattleEngine.SpecialMoves.cs`, `PrizeFormula.cs` neu; `BattleEngine*.cs`, `BattleMon.cs`, `FlowTypes.cs` erweitert).
Prüfstufen **[O]**, **[OK]**, **[P]** wie in Spezifikation 2 (Abschnitt 0): **[P]** = aus Ghidra-Pseudocode gelesen, nicht vom Orakel bestätigt; **[A]** = Annahme ohne Beleg.
Wichtig: Die Handler-Tabellen der Scheibe 3 wirken nur über Ereignisvariablen; die hier ergänzte **Section-Ebene** (Meldungen, Zustandsänderungen, Ereignisaufrufe) ist in C# nachgebaut und deshalb überwiegend **[P]**.

## 1. Ergebnis in Zahlen

| | |
|---|---|
| Tests (dotnet-Wegwerfprojekt, inkl. 101 bestehender Battle-Tests der Unity-Suite) | 157 grün (144 → 157; neu: 13 in `BattleFlowEffectTests`) |
| Echte Trainerteams (lokal, `work/masterdata`) | **706** vorhanden; 694 ohne `NotImplemented` durchgespielt (98,3 %); die **ersten 60** Teams: **60/60** ohne `NotImplemented` |
| Teams, deren Attacken alle unterstützt sind (statisch) | 667/706 (94,5 %); erste 60: 58/60 |
| Sonderattacken der Kategorien 10–13 | ca. 57 Attackennummern in `ResolveSpecialMove` |
| Neue Orakel-Fixtures | keine (siehe Abschnitt 6) |

Fehlend in Trainerteams (Nummer: Zahl Vorkommen in Teams): 164 Delegator (6), 102 Imitator (5), 214 Schlafrede (5), 580 Gras-Feld (5), 272 Rollentausch (4), 668 (4), 501 Schnellschutz (4), 277 Magiemantel (2), 494 (2), 356 Schwerkraft, 513, 118 Metronom, 286 Bann, 469 Rundumschutz, 472, 604 (je 1).

## 2. Handler-Wirkungen (Section-Ebene)

Die Engine mischt die Tabellen der Scheibe 3 (`TokuseiHandlers`, `ItemHandlers`) mit eigenen Wirkungs-Handlern (`RegisterAbility`/`RegisterItem`; es läuft pro Faktor nur der erste Eintrag je Ereignis, daher `Merge` ohne Doppelungen).

| Bereich | Umsetzung | Stufe |
|---|---|---|
| Eintritt (Ereignis `MEMBER_IN`) | Wird bei Spielstart (nur wenn ein Anführer einen Eintritts-Effekt hat, damit die Zufallsfolge der Scheibe 4 unverändert bleibt), bei Wechsel und beim Ersatz aufgerufen. Bedroher 22 (Angriff −1 des Gegners), Wetterfähigkeiten 2/45/70/117 (Niesel, Sandsturm, Sonnenschein, Schneewarnung), Beeren 155/158 bei Eintritt | [P] |
| Rundenende (Reihenfolge) | Wetter → Ereignis 145 (0x91) → Zustände → Seiten → Feld → Ereignis 146 (0x92) → Ereignis 147 (0x93); `Section_TurnCheck_Event` ruft erst global (ID 0x1f), dann je Pokémon in Initiativ-Reihenfolge | [P] |
| Ereignis 145 | Resteessen 234 (1/16), Schlammbrühe 281 (Gift-Typ heilt 1/16, sonst Schaden 1/8), Wunsch (Positionseffekt), Zukunftsvorhersage (Positionseffekt, 3 Zählschritte) | [P] |
| Ereignis 146 | Toxik-Orb 272 und Heiß-Orb 273 (Selbstvergiftung/Brand), Abstreifen 61 | [P] |
| Ereignis 147 | Rundenende-Prüfung für Wirkungen nach 146 (Reihenfolge verdrahtet, keine eigenen Handler) | [P] |
| Wetter-Reaktion (Ereignis 155) | Wetterschaden läuft über `Event_CheckWeatherReaction`: Variablen POKEID, WEATHER, `FAIL_FLAG` (Rewrite-Once), VOLUME; Fähigkeiten 8/159/81/142/98 (Schutz vor Sandsturm/Hagel) setzen `FAIL_FLAG`; Wetter-Heilung/-Schaden 115/44/87/94 | [P] |
| Wetter-Initiative | 33/34/146/202 verdoppeln die Initiative bei passendem Wetter (Ereignis `CALC_AGILITY`) | [P] |
| Schwebe | `IsFloating` (Levitation 26, Magnetflug): Boden-Attacken wirken nicht, Fallen (Stacheln usw.) treffen nicht | [P] |
| Beeren | Sitrus 158 (25 % der KP), Orangebeere 155 (10 KP) nach Schaden/bei Eintritt; Verbrauch (`ConsumeItem`, Log `ItemConsumed`) | [P] |
| Wahlitems | Wahlband/Wahlschal/Wahlglas (220/297/287): Sperre auf die erste Attacke (`ChoiceLock`), Sperre fällt beim Wechsel | [P] |
| Lebensorb 270 | Rückstoß 1/10 der max. KP nach Schaden (Magieschutz 98 blockt) | [P]; der Teiler 1/10 ist aus dem Item-Handler gelesen |
| Überlebens-Effekte | Ausdauer, Robustheit 5 (nur bei vollen KP), Fokusschärpe 275 (verbraucht), Fokusband 230 (Chance = `HoldPower`) | [P] |
| Kontakt-Fähigkeiten | 9/38/49 (30 % Status beim Berührer), Steinhaupt 69 (kein Rückstoß) | [P] |
| Weitere | Synchro 28, Aqua-Ring (Zustand 36, 1/16), Schutz vor Statussenkung durch 29/73/51/52, Immunitäts-Fähigkeiten 15/72/7/17/41/40/20, Heiligtum, Weißer Nebel, Lock-On (Zustand 29) und Tiefschlaf-/Treffsicherheits-Fähigkeit 99 | [P] |

## 3. Seiten-, Feld- und Sonderattacken

Seiteneffekt-Nummern des Originals (`work/battleevents/handler_map.json`): 0 Reflektor, 1 Lichtschild, 2 Heiligtum, 3 Weißer Nebel, 4 Rückenwind, 5 Zauberschild (nicht umgesetzt), 6 Stachler, 7 Giftspitzen, 8 Tarnsteine, 14 Klebenetz, 17 Aurorawall.

| Effekt | Dauer / Regel | Stufe |
|---|---|---|
| Reflektor, Lichtschild, Aurorawall | 5 Runden; Ereignis 90 mit Faktor 0x800 (Einzelkampf), nur bei passender Schadensart und ohne Volltreffer; einmal je Treffer (Hilfsvariablen 100/101) | [P] |
| Heiligtum, Weißer Nebel | 5 Runden; Heiligtum blockt Hauptzustände und Verwirrung der Gegenseite, Nebel Statussenkungen | [P] |
| Rückenwind | `MakeTurn(…,4)`, Initiative ×2 (Faktor 0x2000, Ereignis 19) | [P] |
| Stachler | Schichten 1–3: 1/8, 1/6, 1/4 der max. KP beim Eintritt, nicht für Schwebende | [P] |
| Giftspitzen | 1 Schicht Gift, 2 Schichten schweres Gift (`MakeMoudokuCont`); Gift-Typen nehmen sie auf | [P] |
| Tarnsteine | Teiler aus der Tabelle `{256,256,128,64,32,16,8,4,2,1,1,1,1}` (Typ-Effektivität, aus der ELF `DAT_03e59d2c` gelesen) | [OK] (Tabelle gelesen), Anwendung [P] |
| Klebenetz | Initiative −1 beim Eintritt | [P] |
| Raum-Effekte | Bereich der Ordnung (433): FIELD-Faktor auf Ereignis 19 setzt `TRICK_FLAG`; Dauer 5 Runden; erneutes Einsetzen beendet ihn **[A]** | [P] |

Sonderattacken (`BattleEngine.SpecialMoves.cs`): Schutz 197/182/596/673 (Wiederholung: Erfolg 1/3ⁿ, **[A]**; scheitert als Letzter der Runde), Ausdauer 203, Fluch 174 (Geist/Nicht-Geist), Verhöhner 269 (3 bzw. 4 Runden, Zug **[P]**),
Fokusenergie 116, Erholung/Rest 156, Wasserring 392, Dunkelnebel 114, Fluchtverbot 212/335, Brüller/Wirbelwind 46/18 (Wildkampf: Kampfende `RunEnemy`), Zukunftsvorhersage 248, Stafette 226; Zugzwang (Zustand 23, 3 Runden **[A]**) und Aussetzer (Zustand 13, 4 Runden **[A]**) sperren in `ExecuteFight`/`CheckFirstFail`,
sowie weitere Attacken der Nummern 194, 487, 100, 199, 170, 244, 384, 187, 504, 220, 273, 215, 432, 367, 180, 271, 415, 393, 262, 150 (Plätscher), 227, 50, 383, 254, 502/270/266 (ohne Partner: `NoTarget`).
Die Zählung der Kategorien: Anteil der Attacken-Slots in Kategorien 10–13 in den 706 Teams ca. 11 %.

## 4. Preisgeld und Wild-Begegnung

**Preisgeld (`calc.CalcWinMoney`, 0x2076980 / `calcWinMoney_Sub` 0x2076900) [P]:** nur bei Gegner-Typ Trainer (`competitor == 1`):
`(Gold & 0xFF) × Stufe des LETZTEN Mitglieds der Gegner-Party × 4`; im Doppelkampf (Partys mit ≥ 4 Plätzen) wird der Betrag des zweiten Gegners addiert. `Gold` ist `TrainerData.Gold`.
Berechnet wird er beim Kampfstart (`MainModule.InitializeCoroutine`), hier beim Sieg (`BattleEngine.PrizeMoney`, Log `PrizeMoney`). Nicht abgebildet: Verdopplungs-Items (Münzamulett) und die Auszahlung — die liegen außerhalb des Kampf-Moduls und konnten nicht belegt werden.

**Niederlage (`CalcLoseMoney` → `CalcPenaltyMoney`, 0x2076c60) [P]:** höchste Stufe der Spieler-Party × `Tabelle[Orden]` × 4, begrenzt auf das vorhandene Geld; Orden außerhalb der Tabelle (Länge 9) wirft im Original einen Fehler.
Die Tabelle ist ein statisch initialisiertes Byte-Feld (`RuntimeHelpers.InitializeArray`, Datenblock nicht ausgelesen). **[A]:** `{2,4,6,9,12,16,20,24,36}` aus den Vorgängerspielen — `BattleSetup.PenaltyTable` überschreibt sie, sobald die echten Werte gelesen sind.

**Wild-Begegnung (Lücke):** Die Generierung (Natur, Wertungen, Fähigkeit, Geschlecht, Begegnungsplatz-Zufall, Stufe) steckt in `EncountTool`/`Pml.PokePara.InitialSpec`, nicht im ausgewerteten Pseudocode (`work/decomp/battle_all` enthält nur `Dpr.Battle.*`).
`PokemonFactory.CreateWild` bleibt Hilfswerkzeug **[A]**. Der Aufrufer muss Art, Form und Stufe vorgeben. Aufwand: ca. 1–2 Tage (Dekompilat der Begegnungsklassen, Orakel für `InitialSpec`).

## 5. Gegner-KI (Lücke, mit Befund)

Die Trainer-KI ist **kein Bytecode**, sondern kompilierter C#-Code: `AiScript.CreateScriptBase` (0x1bc08d0) erzeugt je nach Bit eine der Klassen `BtlAiBasic`, `BtlAiStrong`, `BtlAiExpert`, `BtlAiDouble`, `BtlAiAllowance`, `BtlAiItem`, `BtlAiPokeChange`.
Umfang des Pseudocodes: Basic 541 KB, Expert 996 KB, Double 306 KB, Strong/Item/PokeChange je 20–31 KB; dazu `BattleAiCommand` (310 KB) und `AiWazaJudge` (47 KB).
Ableitbar ist damit prinzipiell alles, aber nicht „klar und klein“: Es ist ein Punktesystem (Skript-Befehle erhöhen/senken die Wertung je Attacke, Auswahl nach Höchstwert mit Zufall bei Gleichstand) mit rund einhundert Befehlen und Dutzenden Abfragen (Typen-Effektivität, Schaden aus `BattleSimulator`, Wetter, Zustände).
Das ist hier **nicht umgesetzt**; `RandomEnemyBrain` bleibt der Standard, `IEnemyBrain` ist die Schnittstelle. Schätzung: Basic/Strong ca. 2 Tage, Expert + Double ca. 3–4 Tage, Item-/Wechsel-KI (`AiItemJudge`, `AiPokeChangeJudge`) ca. 1 Tag; Orakel nur für einzelne Rechenbefehle sinnvoll.

## 6. Prüfung

- Orakel: für diese Scheibe **keine** neuen Fixtures — Section-Ebene und Preisgeld sind nur im Pseudocode belegt; die rein arithmetischen Teile (Tarnstein-Tabelle, 1/8·1/6·1/4, Preisgeld-Formel) sind einfache Ganzzahlformeln, getestet in `BattleFlowEffectTests`. Das Orakel (`scripts/battle_oracle_flow.py`, 5900 Fälle) bleibt unverändert grün.
- Neue Tests (`BattleFlowEffectTests`, 13): Reflektor halbiert (Zufallsfolge gleich), Reflektor endet nach 5 Runden, Tarnsteine bei Eintritt, Stachler-Schichten, Schutz, Bereich der Ordnung, Bedroher, Niesel, Resteessen, Wahlitem-Sperre, Preisgeld (Trainer und Wild), Niederlage-Abzug.
- Lokal (nicht im Repo-Test, weil `work/masterdata` gebraucht wird): `BattleFlowPlaythroughLocal` spielt alle 706 Teams, Ausgabe in `work/battleflow-playthrough.txt`.

## 7. Verbleibende Lücken und Aufwand

| Block | Stand | Schätzung |
|---|---|---|
| Delegator 164, Imitator 102, Schlafrede 214, Rollentausch 272, Magiemantel 277, Bann 286, Metronom 118, Schnell-/Rundumschutz 501/469, Gelände 580/604/472, Schwerkraft 356 | nicht umgesetzt | 1–2 Tage |
| Restliche Items/Fähigkeiten (siehe `work/battleflow-coverage.txt`: u. a. Beeren mit Statuswirkung, Statuswert-Beeren, Trainer-Items) | teilweise | 2 Tage |
| Gegner-KI | Abschnitt 5 | 6–8 Tage |
| Wildgenerierung | Abschnitt 4 | 1–2 Tage |
| Doppelkämpfe, Fang, Lernen, Entwicklung | wie Spezifikation 4, Abschnitt 12 | unverändert |
