# Kampfablauf, Scheibe 4: Spezifikation

Stand: Zwischenstand Scheibe 4 (headless lauffähiger 1:1-Einzelkampf, Wild und Trainer, reine C#-Logik ohne UnityEngine, ohne Rendering, ohne Sound).
Die Umsetzung (`unity/Assets/Scripts/BattleFlow`, Assembly `Xnu.Battle.Flow`) baut auf Scheibe 1 (Rechner, `Xnu.Battle`), Scheibe 2/3
(Ereignissystem und Handler, `Xnu.Battle.Events`) und dem Pokémon-Modell (`Xnu.PokePara`) auf. Belegkonvention, Adressen (Ghidra-Adresse =
Il2CppDumper-RVA + 0x100000) und Prüfstufen **[O]**, **[OK]**, **[P]** wie in `docs/kampf-spezifikation-2.md` Abschnitt 0.

## 1. Ergebnis in Zahlen

| | |
|---|---|
| Spielbarer Umfang | Einzelkampf Wild und Trainer: Setup aus `PokemonParam`-Teams, Befehle Attacke / Item / Wechsel / Flucht als Daten, Runden bis `Finished` |
| Neue Orakel-Fälle (echte ARM64-Funktionen) | 5 900 Fälle in `Fixtures/BattleFlow.json` (2,7 MB, nur Zahlen) in 8 Gruppen (Abschnitt 9) |
| Neue Tests | 40 (10 Orakel-Vergleiche, 30 Ablauf-Tests); zusammen mit den 101 bestehenden Kampf-Tests 141 grün im dotnet-Projekt `work/dotnet-battleflow`, dazu 1 lokaler Test mit echten Stammdaten (60 echte Trainerteams durchgespielt) |
| Geänderter Altcode | keiner (`Xnu.Battle`, `Xnu.Battle.Events`, `Xnu.PokePara`, `Xnu.Data` unverändert); `Xnu.Tests.EditMode.asmdef` bekommt nur den Verweis auf `Xnu.Battle.Flow` |

## 2. Überblick: Zustandsmaschine

```
Setup (BattleSetup) ──Start()──> AwaitCommands ──Submit(Spielerbefehl[, Gegnerbefehl])──> Runde
                                      ^                                                    │
                                      │                       ┌────────────────────────────┤
                                      │                       v                            v
                              SubmitReplacement()       Finished (Win/Lose/Draw/Run)  AwaitReplacement
                                      ^                                                    │
                                      └────────────────────────────────────────────────────┘
```

Rundenablauf (Spiegel von `Section_Root_ProcessActions.Execute @0x22c9a10`) [P, Struktur aus dem Pseudocode; die Teilschritte siehe unten]:

1. **TurnStart** (`Section_TurnStart.Execute @0x2274fa0`): alle schlafenden Faktoren wecken (`WakeAllFactors`), Ereignis-Variablenstapel prüfen, Sonderprioritäten
   der Pokémon auf 1 zurücksetzen.
2. **Aktionen sammeln** (`Section_StoreActions`): je Seite eine Aktion; Reihenfolge im Container = Spieler zuerst, dann Gegner.
3. **Sortieren, Sonderprioritäten setzen, noch einmal sortieren** (`sortPokeActionOrder`, `setSpActPriority`, `sortPokeActionOrder`): jede Sortierung berechnet alle
   Schlüssel neu und zieht bei jedem Gleichstand einen Zufallswert (Abschnitt 3). Ein Gleichstand zieht also **zweimal**.
4. **Aktionen ausführen** (`ProcessAction`, Abschnitt 4–6) in Reihenfolge; Aktionen besiegter oder ausgewechselter Pokémon entfallen.
5. Ist eine Seite ausgelöscht (`CheckShowdown`), endet der Kampf sofort (Win, Lose oder Draw).
6. **TurnCheck** (`Section_TurnCheck.turnCheck @0x226fa20`): Schritt 1 Wetter (Dauer/Ende, sonst Wetterschaden in Initiative-Reihenfolge), Schritt 4 Freundschaftsheilung,
   Schritt 5 Ereignis 0x91, Schritt 8 Zustände (`TurnCheck_Sick`, Abschnitt 5), Schritt 0xb Seiteneffekte, 0xc Feld, 0xd Ereignis 0x92, 0x10 Ereignis 0x93.
   Zwischen den Gruppen prüft das Original Showdown und Wechselanforderungen. Umgesetzt sind Wetter und Zustände.
7. **CoverCheck** (`Section_CoverCheck`): besiegte Pokémon auf dem Feld werden ersetzt; der Gegner wählt per KI, beim Spieler wechselt die Phase zu
   `AwaitReplacement`. Der Ersatz kommt also **nach** den Rundenende-Effekten (Wetterschaden, Gift, …) [P: Reihenfolge aus `ProcessActions.Execute`; ob
   Wechselanforderungen innerhalb des TurnChecks (Schritte 3/7/10/15) schon früher auslösen, ist nur für Sonderfälle belegt, die nicht umgesetzt sind].
8. **TurnEnd** (`Section_TurnEnd.Execute @0x2273cb0`): Rundenflags löschen, Isolate-Faktoren entfernen (`RemoveIsolateFactors`), Zähler hoch.

## 3. Zugreihenfolge [O/OK]

### 3.1 Sortierschlüssel `ActPri` [O]

`ActPri.Make(dominant, operation, wazaPri, spPri, agility)` [`@0x1bbd360`] = `(dominant & 7) << 25 | (operation & 7) << 22 | (wazaPri & 0x3f) << 16 | (spPri & 7) << 13 | agility & 0x1fff`.
Größer = früher. Alle elf Hilfsfunktionen (`ChangeAgility`, `ChangeWazaPriority`, `Get*`, `Set*`, `ToHandlerPri`, `ToWazaOrgPri` = `wazaPri - 7`) sind per Orakel bestätigt
(500 Fälle, auch mit Werten jenseits der Masken).

Folgen: Die Initiative hat nur **13 Bit**. Werte ≥ 8192 laufen über (praktisch irrelevant); im Bereich der Ordnung wird `10000 - Initiative` gebildet und danach maskiert
(9900 → 1708): die Reihenfolge bleibt richtig, solange keine Initiative über 1808 liegt.

### 3.2 Schlüssel einer Aktion (`Section_CalcActionPriority.Execute @0x22ad570`) [P, Werte der Tabellen per Pseudocode]

- **Vorrang** (dominant): 0 (Unterbrechungsaktionen setzen ihn höher; nicht umgesetzt).
- **Aktionsart** (operation): Attacke 1, Item 4, Wechsel 5, Flucht 6 (die Flucht eines **wilden Pokémon** gilt als 1), G-Start 2, Anfeuern 3, Aufzeichnungs-Timeout 0.
  Flucht schlägt Wechsel schlägt Item schlägt Attacke, unabhängig von der Initiative.
- **Attackenprioritätsstufe** (`Event_GetWazaPriority @0x1e178a0`): `Attackenpriorität + 7` aus der WazaTable, danach Ereignis 17 (`GET_WAZA_PRI`, Variable `WAZA_PRI`); bei
  Nicht-Attacken 0. Wechsel/Item/Flucht haben also Stufe 0 und stehen in ihrer Aktionsart davor.
- **Sonderprioritäten** (`Event_CheckSpecialActPriority @0x1e1c7f0`, Ereignis 15, Variable `SP_PRIORITY`): 0 niedrig, 1 normal, 2 hoch (Vorlaeufer-/Nachzuegler-Effekte der Handler); gesetzt nur für Attacken-Aktionen, zwischen den zwei Sortierungen.
- **Initiative** (`Event_CalcAgility @0x1e179a0`, Ereignis 19) [OK]: Wert mit Stufen, Verhältnis aus den Handlern (Start 0x1000, Grenzen `[0x19a, 0x20000]`), `MulRatio`;
  Paralyse halbiert (`× 50 / 100`), solange die Ereignisvariable `GEN_FLAG` (Start 1) gesetzt bleibt (Handler wie Schnellfuß dürfen sie löschen); Deckel **10000**;
  mit gesetzter Variable `TRICK_FLAG` (Bereich der Ordnung) wird `10000 - Initiative`.

### 3.3 Sortierung (`Section_SortActionOrder.sort @0x22cd470`) [OK]

Auswahlsortierung mit zwei Schleifen `i < j`: tauschen, wenn `pri[i] < pri[j]`; bei **Gleichstand ein Zug `GetRand(2)`**, getauscht wird bei Ergebnis ≠ 0.
Es gibt keine weitere Regel (keine Rücksicht auf Seite, Level o. ä.). Das Orakel führt die echte Funktion mit einem Python-Container aus und vergleicht Reihenfolge **und**
den nächsten Zufallswert (also die Zahl der Züge) in 700 Fällen. Für die Rundenende-Reihenfolge (`Section_SortByAgility @0x22cd6a0`) gilt dieselbe Gleichstandsregel.

## 4. Aktionsausführung

### 4.1 Erste Fehlschlagprüfung `CheckFail_1st` (Statusprobleme) [P, Reihenfolge aus dem Pseudocode `@0x227ee20`; Zähler und Zufallsfunktionen [O]]

Reihenfolge und Zufallszüge, **vor** dem PP-Abzug:

1. Schlaf: Zähler `+1` (`+2` bei Frühaufsteher, Fähigkeit 48, wenn sie wirkt); ab Zähler ≥ Dauer Aufwachen (`CheckNemuriWakeUp`) [O]; sonst Fehlschlag Ursache 2. Kein Zug.
2. Frost: Attacke mit Flag 10 („taut auf“) oder ein Zug `IsOccurPer(20)` taut auf; sonst Fehlschlag Ursache 4.
3. Zurückschrecken (Zug-Flag 4) → Ursache 6. Kein Zug.
4. Verwirrung: Zähler `+1`, ab Zähler ≥ Dauer vorbei (`CheckKonranWakeUp`) [O]; sonst Zug `IsOccurPer(33)` für den Selbstangriff (Ursache 5).
   Selbstangriff (`Section_ConfDamage.calcDamage @0x22b56a0`) [OK]: erst Zug `GetRand(16)`, dann `DamageBase(40, Angriff, Stufe, Abwehr)` (beide mit Stufen),
   `(Basis & 0xffff) * (100 - Zug) / 100`, mindestens 1.
5. Paralyse: Zug `IsOccurPer(25)` → Ursache 3. 6. Bezauberung: Zug `IsOccurPer(50)` → Ursache 8.

Nicht umgesetzt: Sabotage (Ungehorsam), `Event_CheckWazaExecute` (Handler-Fehlschläge, Pech/Faulenzer), Kanashibari/Hohn/Heilsperre/Gravitation/Bann-Prüfungen, `Event_ExeFailThrew` (Schlafrede/Schnarchen).

### 4.2 PP und Ablauf einer erfolgreichen Prüfung (`Section_WazaExecStart.Execute @0x227b3d0`) [P]

`CheckFail_1st` → Ziele → **PP −1** (`decrementPP @0x227be60`; Druck über `Event_DecrementPPVolume` nicht angeschlossen) → zweite/dritte Fehlschlagprüfung → Ausführung.
Bei Fehlschlag in der ersten Prüfung werden **keine PP** verbraucht. Sind alle PP leer, benutzt das Pokémon **Verzweifler** (Attacke 165, Rückstoß ¼ der Max-KP, ohne Typenwirkung).
Waza-Handler der Attacke (`WazaHandlers.Add`, nur die in Scheibe 3 umgesetzten) werden für die Dauer der Attacke registriert.

### 4.3 Treffer, Immunität, Schaden (Reihenfolge der Zufallszüge)

Wirkungslosigkeit (Typenwirkung 0, auch Paralyse-Attacken gegen Elektro) wird **vor** der Genauigkeit geprüft (`CheckWazaInvalid` läuft vor der Kategorie) [P]. Zugfolge einer Treffer-Attacke:

1. Trefferzahl (`HitCountStd`, nur für „2–5 Treffer“, Typ 5) [O] — Lage relativ zur Genauigkeit [P];
2. Genauigkeit: `Event_CheckHit` über `BuildHitInput`/`AccuracyCalculator` (ein Zug `GetRand(100)`; Genauigkeit 0 oder > 100 trifft immer, kein Zug; Attacken auf den Anwender prüfen nicht) [OK];
3. je Treffer: Volltreffer (`CriticalHit.Check`, ein Zug) → Schaden (`DamageCalculator.Calc` über `BuildDamageInput`, ein Zug für den Zufallsfaktor);
   bei besiegtem Ziel bricht die Treffer-Schleife ab; Schaden ≤ aktuelle KP.
4. Zusatzwirkungen (`Section_WazaAdditionalEffect.Execute @0x2279760`: Zurückschrecken → Entzug → Zustand/Statuswert des Ziels → Statuswert des Anwenders) [P, Reihenfolge belegt]:
   - Entzug/Rückstoß: Prozent des **gesamten** Schadens (`damageRecoverRatio` > 0 Entzug, < 0 Rückstoß), mindestens 1;
   - Zustand (Kategorie 4): Wahrscheinlichkeit `sickPer`; Statuswert des Ziels (Kategorie 6) bzw. des Anwenders (7): je Eintrag `rankEffPer`; 0 und ≥ 100 gelten als sicher (kein Zug) [P];
   - Zurückschrecken nur, wenn das Ziel in dieser Runde noch nicht gehandelt hat (Zug-Flag 0); Zug nur bei `shrinkPer` < 100 [P].

Kategorien (`WazaCategory`): 0 Schaden, 1 Zustand, 2 Statuswerte, 3 Heilung, 4 Schaden+Zustand, 5 Statuswerte+Zustand, 6 Schaden+Statuswert, 7 Schaden+Statuswert des Anwenders,
8 Entzug, 9 K.-o.-Attacke (Treffer = Genauigkeit + Stufe Anwender − Stufe Ziel [P], Schaden = aktuelle KP), 10 Feld (Wetter), 11–13 Seiten-/Sonder-/Handler-Attacken (**nicht umgesetzt**: Protokoll `MoveFailed` mit `NotImplemented`).

### 4.4 Statuswerte, Heilung, Zustände

- Stufen 0..12 (6 neutral), `ChangeRank`: an der Grenze `StatChangeBlocked`. Werte 1 Angriff … 7 Fluchtwert; Volltreffer-Stufe (9) nicht umgesetzt.
- Heilung (Kategorie 3): `MaxKP × hpRecoverRatio / 100`, mindestens 1, bei vollen KP Fehlschlag [P].
- Zustand eintragen (`Section_AddSickCheckFail.checkFail_byBasicRules @0x21dc0a0`, Auszug) [P]: scheitert, wenn derselbe Zustand aktiv ist, wenn ein Hauptzustand (1–5) vorhanden
  ist, Paralyse bei Elektro, Frost bei Eis oder Sonne, Brand bei Feuer, Gift bei Gift/Stahl; Bezauberung nur bei gegensätzlichen Geschlechtern.
- Dauer eines Zustands (`calc.MakeDefaultPokeSickCont @0x2074d20`): Paralyse, Frost, Brand, Gift dauerhaft (Art 1); **Schlaf** Art 2 mit `RandRange(2, 4)` Runden (ein Zug);
  Verwirrung Art 2 mit `RandRange(min, max)` der Attackendaten; Bindung Art 4; **schwerer Gift** = Dauerzustand mit Zählmaximum 15 (`MakeMoudokuCont`; Attackendaten: `sickTurnMin = sickTurnMax = 15`).

### 4.5 Wetter (`Section_WazaExec_Category_FieldEffect`, `FieldStatus.TurnCheckWeather @0x19fa950`) [P/O]

Wetterattacken: Sonnentag 241, Regentanz 240, Sandsturm 201, Hagel 258 (die Typen der Stammdaten stimmen: Feuer, Wasser, Gestein, Eis [lokal geprüft]). Dauer = 5 + Verlängerung (Items über
`Event_WazaWeatherTurnUp`, nicht angeschlossen). Das gleiche Wetter schlägt fehl. Rundenende: Zähler `+1`; ab Zähler ≥ Dauer endet das Wetter **ohne** Schaden in dieser Runde (also 4 Schadensrunden
bei Dauer 5), sonst Wetterschaden `max(1, MaxKP/16)` (Sand: Gestein/Stahl/Boden immun, Hagel: Eis immun) in Initiative-Reihenfolge. Wetterfaktor auf den Schaden: Scheibe 1 [O].

## 5. Statusprobleme und Rundenende [O]

### 5.1 Dauer `BTL_SICKCONT` [O]

64-Bit-Wert je Zustand: Bits 0–2 Art (0 keine, 1 dauerhaft, 2 Runden, 3 Pokémon, 4 Pokémon+Runden), 3–7 Verursacher, 8–13 Rundenzahl / Zählmaximum / Pokémon-ID,
ab 14 Parameter (16 Bit; bei Art 4 Pokémon-ID auf 14–19, Parameter ab 20), Bit 30 Flag. `MakeNull` = `0x1f << 3`. Alle `Make*`/`Get*` der Klasse `SICKCONT` sind
über das Orakel bestätigt (600 Fälle, 11 Konstruktoren). Zu jedem Zustand gehört ein Byte-Zähler (`BTL_POKEPARAM` +0x50).

### 5.2 Zähler fortschreiben (`WazaSick_TurnCheck @0x20e10f0`) [O]

Gilt für alle Zustände **außer Schlaf (2) und Verwirrung (6)** (diese zählen bei der Aktion, Abschnitt 4.1): Zustand aktiv? Art 0 → nein. Rundenzahl 0 (dauerhaft): bei Zählmaximum ≠ 0 (schwerer Gift: 15)
und Zähler < Maximum Zähler `+1`; weiter aktiv. Mit Rundenzahl: Zähler `+1`; ist Zähler < Rundenzahl → weiter aktiv; sonst **abgelaufen** (Dauer auf Null, Zähler 0, Heilungsmeldung).
Danach (nur bei nicht abgelaufen) Schaden `CalcSickDamage @0x20de0c0` [O]: Brand `max(1, MaxKP/16)`, Gift `MaxKP/8` bzw. schwer `MaxKP/16 × Zähler`, Alptraum `MaxKP/4` nur bei Schlaf (oder Fähigkeit 213),
Fluch `MaxKP/4`; Bindung `MaxKP/8` (`cont_Bind`, Faktor 8 [P], Bindungsband = 6 nicht angeschlossen). Der Zähler des schweren Gifts steigt **vor** dem Schaden: 1/16, 2/16, 3/16 …

### 5.3 Reihenfolge der Zustände [O]

Die echte Tabelle `tables.GetTurnCheckWazaSickByOrder` (aus dem `.cctor`, 42 Einträge) beginnt `36, 21, 18, 5, 4, 9, 10, 8, 43, 11, 12, 23, …`: Aquaring, Wurzeln, Egelsamen, **Gift, Brand**, Alptraum, Fluch,
Bindung, Kraken, … Für jeden Zustand werden alle Pokémon in Initiative-Reihenfolge durchlaufen (`Section_TurnCheck_Sick.Execute @0x2270720`); die Reihenfolge der Pokémon wird einmal
sortiert (`SortByAgility`, Gleichstand: ein Zug).

## 6. Flucht, Wechsel, Items

### 6.1 Fluchtformel [OK]

`Section_Escape_Sub.checkEscapeEnableByAgi @0x22b73c0`, mit **Basis-Initiative ohne Stufen** (`GetValue_Base(AGILITY)` & 0xffff) des fliehenden und des gegnerischen Pokémon:

- ist die eigene Initiative **größer** als die des Gegners: Erfolg, **kein Zufallszug**;
- sonst ein Zug `GetRand(256)`; `ratio = gegner == 0 ? 0 : (eigen << 12) / gegner`; Erfolg, wenn `(Versuche & 0xff) * 0x50 + ((int)(ratio << 7) >> 12) > Zug`.

Der Zuschlag je Fehlversuch ist **0x50 = 80** (nicht die 30 der klassischen Formel); bei gleicher Initiative ist die Chance im ersten Versuch also (128 + 0) / 256 = 50 %, im zweiten (128 + 80) / 256 = 81 %.
Versuche = `ESCAPE_TRIED_COUNT`, wächst bei jedem Fehlversuch (`onEscapeFailed`: `IncBattleCount(1)`). Das Orakel prüft 900 Fälle samt Zugzahl.

Davor (`Section_Escape_Sub.checkForceSucceed @0x22b72a0`): Geist-Typ (Typ 7) und Handler-Ereignis `SKIP_NIGERU_CALC` (11) erzwingen den Erfolg ohne Rechnung (Fluchtband, Fluchtbereit: Handler noch nicht umgesetzt).
Danach (`Section_Escape_Core @0x22b6e80`): `Event_CheckNigeruForbid` (Zustand 22 „Fluchtverbot“ oder Bindung 8; Handler dürfen es erweitern, Ereignis 12) → Fehlschlag, **nach** dem Zufallszug.
Im Trainerkampf ist die Flucht nicht erlaubt (`EscapeMode` ≠ WILD): `Submit` verweigert den Befehl. Die Flucht-Aktion hat die höchste Aktionsart (6) und läuft vor allen anderen.

### 6.2 Wechsel und Ersatz

Wechsel (Aktionsart 5): Faktoren des alten Pokémon entfernen, dessen Stufen/Zustände (außer Hauptzuständen) löschen, Faktoren des neuen registrieren (`Tokusei.Add`, `Item.Add`),
Gegenüber-Eintragungen für die Erfahrung setzen (`Confronted`). Ersatz nach K.O. ebenso. Ereignis `MEMBER_IN` (108) und Eintrittseffekte (Bedroher, Fallen) sind nicht angeschlossen.

### 6.3 Items

Heil-Items über den Stammdaten-Wert `wk_prm_hp_rcv` (255 = volle KP); Verbrauch aus dem Beutel. Zustandsheilung, Beeren, PP-Items, Bälle (Fang) fehlen.

## 7. Besiegt-Verarbeitung, Erfahrung, Fleißpunkte

- **Faint**: Ereignis einmal je Pokémon, nicht-dauerhafte Zustände fallen; bei einem Gegner sofort Erfahrung/EV (`Section_CheckExpGet` läuft im Original nach Schaden, Wetter und Zuständen) [P].
- **Erfahrung** [O für die Formel, P für die Verteilung]: je kampffähigem Pokémon der Spielerseite `ExpCalculator.Calc` (Scheibe 1, `Exp.CalcExp @0x19f7d70`); Eingaben aus `calcExp_Poke @0x19f8c10`:
  `deadPokeExp = give_exp` der Art, Stufen, Freundschaft, `isMatch` = hat dem besiegten Pokémon gegenübergestanden (`CONFRONT_REC`), Erfahrungs-Teiler, Glücksei (Item 231 = 0xe7), fremdes Pokémon.
  **Der Trainerkampf-Bonus ×1,5 existiert in diesem Pfad nicht**: `competitor` wird in `Exp.CalcExp` nicht gelesen (Lücke 5 aus Spezifikation 1 ist damit beantwortet: kein Bonus).
- **Stufenanstieg**: aus der Wachstumstabelle, Werte neu gerechnet, KP steigen um die Differenz der Maximal-KP. Attacken-Lernen ist Aufgabe der Oberfläche (nicht im Ablauf).
- **Fleißpunkte** (`calcEffortExp_Poke @0x19f9060`) [P]: nur für Pokémon, die Erfahrung bekommen haben (`exp ≠ 0`). Ausbeute der besiegten Art steckt in `PersonalTable.exp_value`, je 2 Bit in der Reihenfolge
  KP, Angriff, Abwehr, Initiative, Sp.-Angriff, Sp.-Abwehr [lokal gegen echte Arten geprüft: Pikachu +2 Initiative, Mewtu +3 Sp.-Angriff, Garados +2 Angriff]. Machoband (Item 215 = 0xd7) verdoppelt. Grenzen 252 je Wert, 510 gesamt [P, Annahme].
  Nicht umgesetzt: Kraft-Items, Pokérus (die Tabelle steckt im `.cctor` von `ExpCalculator`, noch nicht ausgelesen).
- Ergebnis in die Quelldaten zurück (`BattleMon.WriteBack`): KP, Erfahrung, PP, Stufe, Werte.

## 8. Ereignisprotokoll

`BattleEngine.Log` ist eine Liste strukturierter `LogEvent` (Art `LogKind`, Runde, Pokémon-ID, Ziel, Id, zwei Werte). Pokémon-IDs: Spieler 0–5, Gegner 6–11.
Arten: `BattleStart, SendOut, TurnStart, ActionOrder, MoveUsed, MoveFailed, MoveMissed, NoEffect, Critical, Effectiveness, Damage, HitCount, Recover, Drain, Recoil, StatChange, StatChangeBlocked, SickAdded,
SickFailed, SickCured, SickDamage, ConfusionDamage, WeatherStart, WeatherEnd, WeatherDamage, Faint, ExpGained, LevelUp, EvGained, Switch, ItemUsed, RunAttempt, RunSuccess, RunFailed, TurnEnd, BattleEnd`;
Zurückschrecken erscheint als `MoveFailed` mit Ursache 6.
die Bedeutung der Felder steht an jedem Eintrag in `FlowTypes.cs`. Die Ausgabe ist mit gleichem Seed bitgleich reproduzierbar (Test `IdenticalSeedsGiveIdenticalLogsAndDifferentSeedsDiffer`).

## 9. Verifikation

### 9.1 Orakel (`scripts/battle_oracle_flow.py`, Fixture `unity/Assets/Tests/EditMode/Fixtures/BattleFlow.json`)

| Gruppe | echte Funktion(en) | Fälle | Stufe |
|---|---|---|---|
| `actpri` | `ActPri.Make/Change*/Get*/Set*/ToHandlerPri/ToWazaOrgPri` | 500 | [O] |
| `sickcont` | `SICKCONT.Make*` (11), `IsNull/IsMoudokuCont/GetPokeID/GetTurnMax/GetParam` | 600 | [O] |
| `sickturn` | `WazaSick_TurnCheck` (700), `CheckNemuriWakeUp`/`CheckKonranWakeUp` (300+300), `CalcSickDamage` (500) auf synthetischem Gast-Speicher (Zustands- und Zähler-Arrays) | 1 800 | [O] |
| `escape` | `Section_Escape_Sub.checkEscapeEnableByAgi` | 900 | [OK] |
| `sort` | `Section_SortActionOrder.sort` mit Python-Container | 700 | [OK] |
| `agility` | `Event_CalcAgility` (Handler-Ergebnisse als Eingaben) | 900 | [OK] |
| `confdmg` | `Section_ConfDamage.calcDamage` | 500 | [OK] |
| `tables` | `tables..cctor`: Rundenende-Reihenfolge der Zustände | 42 | [O] |

[OK]-Gruppen: die geprüfte Funktion läuft echt (samt echtem `Xoroshiro128+` und echtem `calc.GetRand/MulRatio/DamageBase`), Nachbarfunktionen (`BTL_POKEPARAM.GetValue*`, Ereignisfunktionen, Container) sind Stubs mit Testwerten.
Jeder Zufalls-Fall speichert auch den **nächsten** Zufallswert und prüft damit die Zahl der gezogenen Werte. Reproduktion:

```
PYTHONPATH=tools/pydeps python3 scripts/battle_oracle_flow.py            # BattleFlow.json neu erzeugen (ca. 1 Minute)
PYTHONPATH=tools/pydeps python3 scripts/battle_oracle_flow.py --out work/battleflow-oracle --only escape sort
cd work/dotnet-battleflow && dotnet test                                  # 142 Tests ohne Unity-Editor
```

### 9.2 Ablauf-Tests (`BattleFlowEngineTests`, 30)

Reihenfolge (Initiative, Priorität, Gleichstand mit den zwei Zügen), Schaden = Rechner mit der Zugfolge Treffer → Volltreffer → Zufallsfaktor, Typenwirkung/Immunität, Genauigkeitsquote,
Mehrfachtreffer 2–5 und Doppelkick, Entzug/Rückstoß/Heilung, Statuswertgrenzen, Brand/Gift/schweres Gift/Schlaf/Frost/Paralyse/Verwirrung (Häufigkeiten und exakte Dauer), Zustände mit Typregeln,
Wetterdauer und -schaden, Wetterfaktor, Wechsel (Priorität, Ziel), Flucht (Erfolg ohne Zug, Würfel, steigende Chance, Fluchtverbot, Trainerkampf), K.-o. mit Erfahrung/EV/Stufenanstieg,
Erfahrungs-Teiler und Machoband, Ersatzphase und Trainer-Ersatz, Items, Verzweifler, PP-Abzug nach der ersten Prüfung, Reproduzierbarkeit und 120 zufällige Kämpfe (Invarianten, Terminierung).

### 9.3 Lokale Prüfung mit echten Stammdaten (nicht im Repo)

`work/dotnet-battleflow/tests/BattleFlowRealDataLocal.cs` (ignoriert, wenn `work/masterdata` fehlt): Wettermoves/-typen, EV-Ausbeute, Mewtu/Garados, und 60 echte Trainerteams (aus `TrainerPoke`)
gegen ein Zweier-Team des Spielers bis zum Ende (59 Siege; kein Absturz, jeder Kampf endet). Der Test liest nur lokal, schreibt nichts und ist nicht Teil der Unity-Tests.

## 10. Prüfstufen im Überblick

| Aussage | Stufe |
|---|---|
| ActPri-Packung, SICKCONT-Packung, Zustandszähler, Schlaf-/Verwirrungs-Zähler, Zustandsschaden, Rundenende-Reihenfolge | [O] |
| Fluchtformel, Sortierung samt Gleichstandszügen, Initiative (Paralyse/Deckel/Ordnung), Verwirrungsschaden | [OK] |
| Aktionsarten-Tabelle, Attackenprioritäts-Stufe, Sonderpriorität, Ablaufstruktur der Runde, Reihenfolge der Fehlschlagprüfungen, PP erst nach der ersten Prüfung | [P] (Pseudocode, Strukturen mehrfach gegengelesen) |
| Reihenfolge Trefferzahl/Genauigkeit/Volltreffer/Schaden, Zusatzwirkungen (Zugfolge), Ersatz nach den Rundenende-Effekten | [P] (Teile belegt, Feinheiten Annahme) |
| Stammdaten-Auslegung (`sickPer 0` = sicher, `hitPer > 100` trifft immer, Wetterattacken-Nummern, EV-Bits, EV-Grenzen 252/510) | [P], teils lokal gegen echte Daten geprüft |

## 11. Lücken (ehrlich)

1. **Wirkungs-API und Handler mit Wirkung** (Bedroher, Wetterfähigkeiten, Beeren, Reste, Schärpe, Zurückschrecken-Fähigkeiten, Ereignisse 91–93, `MEMBER_IN` u. v. m.) sind nicht angeschlossen;
   die Handler der Scheibe 3 wirken nur dort, wo sie Ereignisvariablen ändern (Kraft, Angriff, Abwehr, Genauigkeit, Initiative, Priorität, Endschaden).
2. **Attacken**: nur Kategorien 0–10 aus der WazaTable. Attacken mit Handler-Logik (Kategorien 11–13: Schutz, Kraftreserve, Fluch, Spezialattacken, Festschaden, Zustands-Tabellen u. a.), Einschlafen-Sonderregeln,
   Doppelschaden-Bedingungen u. v. m. protokollieren `MoveFailed` (`NotImplemented`). Schadens-Ereignisse 87–89 (Festschaden) fehlen.
3. **Seiten-, Positions- und Feldeffekte** (Schutzwände, Fallen, Raum-Effekte, Gelände): keine; `Handler.Side/Pos/Field` sind in Scheibe 3 nicht umgesetzt. Ereignisse für „Bereich der Ordnung“ sind verdrahtet, aber ohne Handler.
4. **KI**: Gegner wählt eine zufällige Attacke mit PP (`RandomEnemyBrain`), Trainer setzen weder Items noch Wechsel ein; die Original-KI (`BtlAiExpert`, `AiBit`) ist nicht rekonstruiert.
5. **Fang** (Bälle, `Capture.checkCapureSuccessByRandom`), Preisgeld (`calc.CalcWinMoney`), Freundschaftseffekte, Attacken-Lernen, Entwicklung nach dem Kampf, Ungehorsam (Sabotage), Fänge-Bonus, Kraft-Items, Pokérus.
6. **Wildgenerierung** (Natur, Wertungen, Fähigkeit, Geschlecht) ist nicht die des Originals (`Pml.PokePara.InitialSpec`); `PokemonFactory.CreateWild` ist nur ein Hilfswerkzeug. Echte Begegnungstabellen liegen in `Xnu.Data`.
7. **Seed**: Der Live-Seed des Originals kommt aus `UnityEngine.Random`; hier ist er ein Parameter (Spezifikation 1, Abschnitt 4.2).
8. Nicht zugeordnet sind: Zufallszug-Reihenfolge bei Mehrfachtreffern (Trefferzahl vor oder nach der Genauigkeit), Zug bei `sickPer` = 100, Zurückschrecken-Zug, Reihenfolge Ersatz/Rundenende-Handler in Sonderfällen (Abschnitt 2, Schritt 7).

## 12. Aufwand für den Rest (Schätzung)

| Block | Umfang | Schätzung |
|---|---|---|
| **Doppelkämpfe** | Ziele (`PokePos`, 4 Plätze), Zielwahl (Attackenziele 0–13), Mehrfachziel-Schaden (`TargetRatio` ist vorbereitet), Reihenfolgen mit 4 Aktionen, Spread-Ereignisse, Ersatzwahl je Seite, Gegenüber-Zuordnung der Erfahrung, Befehlsphase mit zwei Befehlen je Seite | 3–4 Tage mit Orakel für Sortierung und Zielwahl (`Section_RegisterWazaTargets`) |
| **Trainer-KI** | `BtlAiExpert`, AI-Skript-Interpreter (`AiScriptCommandHandler`, `aiSeqNo` aus der WazaTable, `AiBit` aus `TrainerData`), Item-/Wechsel-Entscheidungen | 3–5 Tage (große, aber schematische Skript-VM; Orakel für einzelne Befehle möglich) |
| **Wirkungs-API** (`Common.*`, 56 `Section_FromEvent_*`) | Voraussetzung für fast alle Handler mit Wirkung | 2–3 Tage (Schätzung Scheibe 3), davon der Ablauf-Teil hier schon gelegt |
| **Seiten-/Feld-/Positionseffekte** | 37 Nummern, 40 Funktionen | 1 Tag nach der Wirkungs-API |
| **Fang, Preisgeld, Lernen, Entwicklung** | Bälle, `Capture`, `CalcWinMoney`, Lernlisten (`WazaOboeTable`), Entwicklungs-Prüfung | 2 Tage |
| **Dynamax/Zusatzmechanik** | **keine**: BDSP hat weder Dynamax noch Mega-Entwicklung noch Z-Attacken. Die „G-Modus“- und Raid-Reste im Code (`GMode`, `RaidBoss`, `Section_G_Start`) gehören zu Schwert/Schild und werden nicht gebraucht | 0 |
| Handler > 60 Zeilen, Beeren/Items | siehe `docs/kampf-spezifikation-3.md` | 3 Tage |

Zusammen bleiben für „alle Wild- und Trainerkämpfe der Haupthandlung wie im Original“ grob 2–3 Wochen, davon ein Drittel Orakel-Arbeit.
