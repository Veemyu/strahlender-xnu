# Kampfablauf, Scheibe 6: Gegner-KI der Trainer (BtlAi*, AIBit, Wertung, Item, Wechsel)

Stand: Scheibe 6, aufbauend auf `docs/kampf-spezifikation-5.md` (Abschnitt 5 kündigte die KI als Lücke an). Code: `unity/Assets/Scripts/BattleFlow/Ai/`
(`TrainerAi.cs`, `AiWorld.cs`, `AiScriptBase.cs`, `AiScriptBasic.cs`, `AiScriptsOther.cs`), Schnittstelle in `BattleEngine.cs` (`BattleSetup.EnemyAi`, `EnemyItems`).
Orakel: `scripts/battle_oracle_ai.py` (Unicorn, echte ARM64-Funktionen aus `work/elf/main.patched.elf`), Fixtures `unity/Assets/Tests/EditMode/Fixtures/BattleAi*.json` (nur Zahlen).

Prüfstufen wie in Spezifikation 2/5, hier mit einer zusätzlichen Stufe für die Skriptebene:

- **[O]** Die C#-Funktion ruft bei gleichem Zustand dieselben `AI_CMD`-Befehle mit denselben Argumenten in derselben Reihenfolge auf und ändert die Wertung genauso wie die **echte ARM64-Funktion** (Orakel, siehe Abschnitt 6).
- **[P]** Aus dem Ghidra-Pseudocode gelesen und nachgebaut, vom Orakel nicht bestätigt.
- **[A]** Annahme ohne Beleg. **[N]** nicht modelliert (liefert 0 bzw. keine Wirkung).

## 1. Ergebnis in Zahlen

| | |
|---|---|
| KI-Klassen im Original | 7 (`BtlAiBasic`, `Strong`, `Expert`, `Double`, `Allowance`, `Item`, `PokeChange`) + `BattleAi`/`AiWazaJudge`/`AiItemJudge`/`AiPokeChangeJudge`/`BattleAiCommand` (130 Befehle) |
| Umfang der Skripte (Pseudocode) | Basic 541 KB (168 Funktionen), Expert 996 KB (256), Double 306 KB (65), Strong 31 KB (3), PokeChange 30 KB (11), Item 20 KB (6), Allowance 5 KB (1) |
| Per Orakel bestätigte Skriptfunktionen | **66** (Basic 48, Strong 3, Allowance 1, Item 6, PokeChange 8), **4220 verglichene Fälle** (je 64 Pseudo-Welten, 4 weitere Basic-Fälle übersprungen) – 0 Abweichungen |
| Basic: Attacken-Slots der 706 Teams, die vollständig abgedeckt sind | **5623 von 6085 (92,4 %)**: 3990 Slots haben keine eigene Seq-Funktion (nur die gemeinsamen Prüfungen), 1633 haben eine umgesetzte; 462 Slots (7,6 %) laufen in eine noch fehlende Seq-Funktion |
| Basic: umgesetzte Seq-Funktionen | 33 von 148 erreichbaren (`BaciAI_Seq_001, 007, 010–013, 016, 018–020, 028, 032, 033, 035, 037, 047, 049, 065, 084, 092, 106, 109, 115, 132, 136, 148, 158, 160, 188, 211, 212, 225, 251`) |
| Tests (dotnet-Wegwerfprojekt `work/dotnet-battleai`, inkl. aller Battle*-Tests der Unity-Suite) | **169 grün** (davon neu: 6 Orakel-Tests, 8 Ablauf-Tests) |
| Lauf über die ersten 60 Teams (Spiegelteam, gieriger Spieler) | Zufallsgegner: Gegner siegt 8, Spieler 51, unentschieden 1, Runden Ø 22,3, NotImplemented 2. **Trainer-KI:** Gegner siegt 13, Spieler 46, unentschieden 1, **Runden Ø 18,9** (1136 gesamt), **NotImplemented 8**, nicht beendet 0 |
| Lauf über alle 706 Teams mit Trainer-KI | Gegner siegt 143, Spieler 558, unentschieden 5, nicht beendet 0, Runden Ø 15,2, NotImplemented 101, Heil-Items eingesetzt 66, freiwillige Wechsel 49 |

(Messungen lokal: `work/battleai-playthrough.txt`, Test `BattleAiPlaythroughLocal` im Wegwerfprojekt; nicht im Repo, weil `work/masterdata` gebraucht wird.
Das Spiegelteam und der gierige Spieler sind eine Messhilfe, kein Original-Verhalten. Die ersten 60 Teams haben nur Basic+Double (59×) bzw. Basic+Double+Allowance (1×); Items und Wechsel kommen dort nicht vor.)

## 2. Struktur: AIBit und Skriptklassen

Die Trainer-KI ist **kein Bytecode**, sondern aus einer Skriptsprache in C# übersetzter Code. `AiScript.CreateScriptBase` (0x1bc08d0) erzeugt je Skriptnummer eine Klasse;
`TrainerData.AIBit` ist eine Bitmaske über diese Nummern **[P]** (`BtlAiscriptBit` im Dump):

| Bit | Wert | Klasse | Aufgabe | Trainer (von 707, davon 706 mit Team) |
|---|---|---|---|---|
| 0 | 1 | `BtlAiBasic` | Grundskript der Attackenwertung | 706 |
| 1 | 2 | `BtlAiStrong` | Zusatzwertung (Wirkung, Beeren, Zuschläge) | 92 |
| 2 | 4 | `BtlAiExpert` | umfangreiche Attackenwertung | 83 |
| 3 | 8 | `BtlAiDouble` | Partner-/Doppelkampf-Wertung | **707** |
| 4 | 16 | `BtlAiAllowance` | kleine Zusatzwertung | 1 |
| 5 | 32 | `BtlAiItem` | Item-Verwendung | 89 |
| 6 | 64 | `BtlAiPokeChange` | Wechsel-Entscheidung | 89 |

Verteilung der AIBit-Werte (707 Trainer): `9` (Basic+Double) 613; `111` (Basic, Strong, Expert, Double, Item, PokeChange) 83; `107` (ohne Expert) 6; `11` (Basic, Strong, Double) 3; `8` (nur Double; Trainer ohne Team) 1; `25` (Basic, Double, Allowance) 1.
Das Double-Bit ist bei **allen** Trainern gesetzt; die Double-Skripte laufen auch im Einzelkampf (`AISide` 2/3 werden dort auf dieselben Pokémon wie 0/1 abgebildet **[P]**, `AiScriptCommandHandler.AISideToPokePos`).
Das ist die größte offene Lücke (Abschnitt 8): `DoubleAI_Enemy_Main` (30 KB) und 36 Enemy-Seq-Funktionen sind nicht umgesetzt.

Eigene Trainer-Items: 46 Trainer tragen `UseItem1..4` (Top-Genesung 23 bei 40 von ihnen, Hypertrank 25, Supertrank 26, Trank 17); davon haben 33 das Item-Bit, 13 nicht; 56 Trainer haben das Item-Bit ohne Items. `HpRecoverFlag` ist bei allen 707 Trainern 0.

### Skript-Schnittstelle

Ein Skript kennt den Kampf nur über `BattleAiCommand.AI_CMD(clientId, cmd, long[] args)` (130 Befehle, `AICmd`-Enum) und verändert sein Feld `p_Score` (+0x14) per `ScoreCtrl`; `SetPokeChangeEnable` setzt `p_PokeChangeEnable`.
Die Befehle sind überwiegend Abfragen (Typ, Fähigkeit, KP-Anteil, Zustand, Seiteneffekt, Wetter, Wirkung einer Attacke auf den Gegner). **AI-Seite** (`ai_side`) [P]: 0 Verteidiger (das Gegenüber), 1 Angreifer (das eigene Pokémon), 2/3 deren Partner, 4 Ersatzpokémon (nur Wechsel-/Bank-Befehle).
Die Attacken-Nummer des Skriptablaufs ist `WAZADATA.AISeqNo` (`MoveRecord.AiSeqNo`, 252 verschiedene Werte bei den Trainer-Attacken); `Calc_BasicAll` bzw. `Expert.main_proc` verteilen darüber auf `BaciAI_Seq_NNN` / `ExpertAI_Seq_NNN`.
Die Tabelle KI-Nummer → Funktion wurde mit dem Orakel gemessen (Basic 196 Nummern → 148 Funktionen, Expert 294 → 223) und ist in `AiScriptBasic.SeqDispatch` eingebettet; ein Test vergleicht sie mit `BattleAiDispatch.json`.

## 3. Entscheidungsablauf (BattleAi, AiWazaJudge) — [P]

`BattleAi.StartActionSelect/UpdateActionSelect` (0x20eb8a0/0x20ebaf0) wählt aus fünf Aktionen: **Attacke, Item, Wechsel, Flucht, Verzweiflung** (`AiAction`). Jede hat Bewertungsart (SCORE / PROHIBIT / FORCE) und Wertung, Start: PROHIBIT, **100**.

1. `CheckSpecialAction`: nur bei Setup-Flags 0x100/0x400 (Sonderkämpfe) → Flucht erzwungen; bei Trainern nicht gesetzt.
2. **Item** (nur wenn `AIItem_CheckUse` ein Item anbietet): `AiItemJudge` → Wertung **100 + Skriptergebnis** des Item-Skripts (Bit 5; ohne Bit bleibt es 100).
3. **Wechsel** (nur Nicht-Wildkampf, Wechsel erlaubt, einsatzbereites Ersatzpokémon, Gegner vorhanden): `AiPokeChangeJudge` → Wertung des besten freigegebenen Ersatzpokémons.
4. **Attacke**: `AiWazaJudge`: Matrix Ziel × Attacke, Start **100**, Status DISABLE. Für jedes gesetzte Waza-Skript (Bit 0..4, in dieser Reihenfolge), jede wählbare Attacke und jedes Ziel läuft das Skript mit `p_Score = 0`; das Ergebnis wird **addiert** und der Status wird NORMAL (`wazaScore_Add`).
   Ohne wählbare Attacke: Verzweiflung (Wertung 100). `wazaScore_DecideBest`: höchste Wertung unter NORMAL-Einträgen, **Zufall (`Random.GetValue(n)`) unter den Gleichen**; Freundes-Ziele mit Wertung < 100 werden verworfen (Doppelkampf).
5. `DecideAction`: erst `GetForcedAction` (Priorität Attacke, Flucht, Item, Wechsel, Verzweiflung = Tabelle `{0,3,1,2,4}` aus `.cctor`, aus der ELF gelesen; nur Flucht kann FORCE sein), sonst `storeBestScoredActions` → **zufällig unter den Aktionen mit der höchsten Wertung**.

Wichtige Folgen: Das Basic-Skript vergibt fast nur **Abzüge** (−1 bis −12) auf 100; eine unbeeinträchtigte Attacke bleibt bei 100, bei Gleichstand entscheidet der Zufall. Ein Item oder ein Wechsel mit Wertung 100 steht gleichauf mit einer Attacke (Item ohne Item-Bit: Gleichstand → Zufall, falls das Item überhaupt angeboten wird).
Der Ersatz nach einem besiegten Pokémon ist das erste kampffähige **[A]** (`BTL_CLIENT` wählt ohne Skript).
Die Zufallsfolge der KI (`Random` mit `randSeed` aus dem Kampf) stammt im Original aus dem Kampf-Setup; hier hat die KI einen eigenen Generator aus dem Kampf-Seed **[A]** — dieselben Entscheidungen, aber nicht dieselben Würfe wie das Original.

### Item-Angebot (`BTL_CLIENT.AIItem_CheckUse`, 0x2050060) — [P] (Priorität [A])

Je Trainer-Item (bis 4 Plätze): kein Angebot bei Zustand 0x13 (Item-Sperre, WAZASICK 19). Platz *i* zählt nur, wenn die Zahl lebender Pokémon ≤ `{6,4,2,1}[i]` ist (Blob aus der ELF). Heil-Items (`wk_prm_hp_rcv > 0`) nur bei KP ≤ ¼ der Maximal-KP (`QuotMaxHP_Zero(poke, 4)`); Zustands-/Statuswert-Items über `check_cure_sick_item`/`check_status_up_item` (**nicht umgesetzt**).
Bei mehreren Kandidaten gewinnt die höchste `tables.GetAIItemPriority` (Position in einer statischen Tabelle, nicht ausgelesen) — hier ersatzweise die Heilmenge **[A]**. Das gewählte Item wird verbraucht.

## 4. Die Skripte im Einzelnen

### Basic (Bit 0) — [O] für 48 Funktionen

Ablauf `main_proc` (0x198b240): (1) Doppelkampf und Mitspieler-Ziel → Ende. (2) Fünf Sonderprüfungen, die bei Treffer −10 setzen und beenden: `Basic_ConaHoushi` (Pulver gegen Pflanzen/Hitzeschutz 142), `Basic_Itazuragokoro` (Prankster 158 gegen Unlicht), `Basic_Sensei` (Vorrang-Attacken), `Basic_Hayatenotubasa` (Gale Wings 177), `Basic_DaimaxNG` (G-Attacken; in BDSP wirkungslos, `IF_G` = 0).
(3) Bei Schadensattacken `Calc_BasicDamage`: ist die Attacke **typ-wirkungslos** (`CHECK_WAZA_AISYOU` = Faktor 0) → −10 und Ende (Ausnahme: Boden gegen Schwebe mit Mold-Breaker-Gruppe, KI-Nummern 0x87/0xad/0xde); sonst Abwehr-Fähigkeiten des Gegners: Volt-Absorb/Blitzableiter/Motor-Antrieb (−12 bei Elektro), Wasserschlucker/Dürre-Haut/Sturmsog (−12 bei Wasser), Feuerfänger (Feuer), Wunderwache 25 (−10 außer bei sehr effektiven Attacken), Schwebe 26 (−10 bei Boden ohne Schwerkraft), Saftsauger 157 (Pflanze).
(4) `Calc_BasicAll`: `Bouon_Check` (Lärmschutz 43 gegen Schall-Attacken, −10), `Boudan_Check` (Kugelsicher 171, −10), dann Verteiler nach `AISeqNo`.
Die Seq-Funktionen sind Wirkungs-Prüfungen der einzelnen Attackentypen: Statuswert-Senker/-Heber (Seq 10–13, 16, 18–20, 211, 212: Abzug, wenn der Wert schon am Anschlag ist oder eine Schutzfähigkeit/Nebel/Delegator wirkt), Statusattacken (001, 033, 049, 084, 106, 109: schon ein Zustand, Heiligtum, Pflanzen-Typ gegen Puder, Insomnia/Blattschutz, Gift-/Stahl-Typ), Wetter (115, 136), Explosion (007: Abzug, wenn Ersatzpokémon fehlen) u. a.

### Strong (Bit 1) — [O] für den Einzelkampf ohne G-Modus (3 Funktionen)

`main_proc` (0x1e05e60), `Strong_exception`, `Strong_KinomiCheck`. Bei Attacken, die als „tödlich“ gelten (`IF_WAZA_HINSHI`), Zuschläge nach KI-Nummer (+3 bei Zufallswurf 0x80/0xe6, +5/+4 für die Nummern 0x168/0x67/0x155); Abzug −1, wenn eine andere eigene Attacke mehr Schaden macht (`COMP_POWER`) und keine Ausnahme/Beere vorliegt; Resistenzbeere des Gegners (18 Typen → Item-Tabelle) macht die Attacke „unwirksam“; Boden gegen Schwebe −3; **sehr effektive Attacken (Wirkungs-ID > 8, also ≥ 4×) bekommen +2 bei Zufallswurf 0xb4**.
Nicht umgesetzt: der Doppelkampf-Zweig (`CHECK_BTL_RULE = 1`) und der G-Zweig (`IF_GWAZA_USE_TURN`). Der Orakel-Test legt für `main_proc` genau diese beiden Befehlsantworten fest (Fixture-Feld `override`).

### Allowance (Bit 4) — [O]: Schadensattacke; Gegner ohne `CHECK_NEKODAMASI` +1, sonst −1 bei niedrigen KP des Gegners (<20 % / <40 %) und Zufallswurf (220/150 von 256).

### Item (Bit 5) — [O] für `main` und `itemAI_001/023/027/057/059`
Dispatch nach Item-Nr. (`GET_CURRENT_ITEMNO`): Tränke 17/24/25/26 → `itemAI_001`, Top-Genesung 23, Vollheilung 27, X-Items 57/58/61/62/59. Beispiel Trank: eigene KP < 20 % → +10 (mit Bank-Pokémon zunächst Zufallswürfe 0x80/0xaa: +10 / +2); < 40 % → Zufallswürfe 0x80/0x46: +10 bzw. +1; sonst **−20**.

### PokeChange (Bit 6) — [O] für 8 Funktionen (+ `IsAisyou0Bai` indirekt)
Für jedes einsatzbereite Ersatzpokémon (Seite 4) prüft `main` der Reihe nach: Abschiedslied-Ende, Wunderwache des Gegners, Typen-Ohnmacht, Wahl-Item mit schlechter Typenlage (Wertung `Basis + 20`), Gegner ohne Wirkung durch Fähigkeit, Natur-Kur, bessere Typenlage. Treffer setzen `PokeChangeEnable` und die Wertung `CalcBaseScore + 1` oder `+ 20` (Zufallswurf 220 bzw. 180). `CalcBaseScore`: 0 bzw. −30 (Szenario-Trainer, Wechsel nicht erlaubt) plus Staffel nach der stärksten Attacke des Ersatzes (+0/+2/+3/ `|4`).
Gewählt wird unter den freigegebenen Ersatzpokémon das mit der höchsten Wertung (Zufall bei Gleichstand), Wertung = 100 + Skript.

### Double (Bit 3) und Expert (Bit 2) — nicht umgesetzt (Abschnitt 8)
`BtlAiDouble.main` verzweigt über `IF_MIKATA_ATTACK` in `DoubleAI_Enemy_Main`/`DoubleAI_Friend_Main`; `Enemy_Main` prüft u. a. Blitzableiter 31 / Sturmsog 114 / Magiespiegel 156 beim „Partner“ des Gegners (im Einzelkampf = Gegner selbst) und ruft 36 Enemy-Seq-Funktionen. `Expert.main_proc` hat einen langen Vorspann (Item-, Fähigkeits- und Zustandsprüfungen) und verteilt über 294 KI-Nummern auf 223 Funktionen; für die 1427 Attacken-Slots der Expert-Trainer haben 654 (46 %) keine eigene Funktion, die häufigste (`ExpertAI_Seq_043`) deckt 61 Slots (4 %).

## 5. Spielzustand für die Skripte (`AiWorld`, AI_CMD-Befehle)

`AiWorld` setzt die Befehle auf der `BattleEngine` um (Einzelkampf). **Beleg [P]** (aus `CMDFUNC_*` gelesen) u. a.: Typ-Befehl (`CHECK_TYPE`: Selektor 0/1 Typ 1 von Gegner/Eigen, 2/3 Typ 2, 4 Typ der Attacke), `CHECK_WAZA_AISYOU` (Wirkungs-ID der Attacke gegen das Ziel; Erwartung 9 = „≥ 2×“, 5 = „≤ ½“, 0xe = nicht anwendbar), `IF_HP_*` (KP-Anteil in 1/4096, `IF_HP_EQUAL` aufgerundet), Seiteneffekte, Wetter, `IF_PARA_*` (Rang-/Statuswerte), Ersatzpokémon-Zählung.
**Wichtig:** `CHECK_TOKUSEI` für das Gegenüber verrät die Fähigkeit **nicht**: nur Fangfähigkeiten (23, 42, 71) oder bereits offenbarte Fähigkeiten (`BattleAiSystem.IsTokuseiOpened`) werden gemeldet; sonst wählt die KI zufällig unter den möglichen Fähigkeiten der Art (`PERSONAL`-Fähigkeiten 1–3) — die vier aufeinanderfolgenden Abfragen in `Strong_exception` erkennen so, ob die Fähigkeit feststeht **[P]**. Offenbarung wird hier aus den `AbilityActivated`-Logeinträgen abgeleitet **[A]**.
**[A]/[N]**: Schaden für `COMP_POWER`/`GET_MAX_WAZA_POWER` ist eine Näherung (Stufe, Basiskraft, Angriff/Verteidigung, STAB, Wirkungs-ID; ohne Stufenwandler/Wetter/Fähigkeiten) statt `BattleSimulator.CalcDamage`; nicht modelliert (liefern 0): Delegator, Fluch-/Abschiedslied-Zähler, Gelände-Effekte, Zustandsprüfung der Ersatzpokémon, G-Modus (in BDSP nicht vorhanden), Mega-Entwicklung.
Die Befehls-Seite der Welt ist **nicht** per Orakel geprüft (nur die Skriptlogik darüber); sie ist die größte Fehlerquelle für die Treue.

## 6. Orakel (Skriptebene)

`scripts/battle_oracle_ai.py` lädt `work/elf/main.patched.elf` in Unicorn und führt die echten Funktionen (`main_proc`, `Basic_*`, `BaciAI_Seq_*`, Strong, Item, PokeChange, …) aus. `AI_CMD` (0x20ecdb0) wird durch eine **deterministische Pseudo-Welt** ersetzt:
Antwort = `f(seed, Aufrufnummer, Befehl)` mit SplitMix64; 62,5 % kleine Zahl 0..13, 18,75 % eine Konstante aus der Liste aller Zahlen ≤ 1000 im Funktionstext (damit auch Fähigkeits-/Attackenlisten getroffen werden), 9,4 % 1, 9,4 % 0.
Gemessen und verglichen werden: Aufruffolge (Befehl, Argument-Array mit Länge und Inhalt; FNV-Hash), Rückgabewert, Endwertung `p_Score`, `p_PokeChangeEnable`. Für Dispatch-Funktionen wird zusätzlich festgehalten, in welche Seq-Funktion der echte Ablauf lief; Fälle, die in eine nicht umgesetzte Funktion laufen, werden übersprungen (4 von 3072 bei Basic).
Statische Felder (Seitenliste in `BtlAiPokeChange`) füllt der echte `.cctor`. Aufruf: `PYTHONPATH=tools/pydeps python3 scripts/battle_oracle_ai.py --cases 64 --include scripts/battle_oracle_ai_functions.json` (die Include-Liste benennt die umgesetzten Funktionen; `name@57=0,128=0` legt Befehlsantworten fest; `--trace Klasse.Funktion:Seed` zeigt die Aufruffolge der echten Funktion).
Fixtures: `BattleAiScripts.json` (163 KB, 66 Funktionen × 64 Fälle: Seed, Rückgabe, Wertung, Aufrufzahl, Hash), `BattleAiDispatch.json` (KI-Nummer → Seq-Funktion für Basic und Expert), `BattleAiCmdUsage.json` (Befehlshäufigkeit je Klasse in den Pseudo-Läufen: Basic nutzt 47 Befehle, Expert 53, Double 28, PokeChange 14, Strong 15, Item 4, Allowance 5).
Während der Arbeit fanden die Orakel-Läufe u. a.: leere statische Argument-Arrays (`CHECK_WORKWAZA_*` nutzen `Empty`), eine doppelt gelesene `CurrentWazaNo`, unterschiedliche Seiten in `IF_PARA_EQUAL` (Seite 0 bei Seq 18, Seite 1 bei Seq 19/20) und einen Befehl, der trotz Kurzschluss immer aufgerufen wird (`Type(2)` in der Pflanzen-Prüfung) — das Lesen des Pseudocodes allein hatte das nicht zuverlässig gezeigt.

## 7. Integration (abwärtskompatibel)

```
BattleSetup.EnemyAi   : IBattleAi   (optional; null = bisheriger Zufallsgegner RandomEnemyBrain)
BattleSetup.EnemyItems: int[]       (TrainerData.UseItem1..4; nur die KI benutzt sie)
IBattleAi.Decide(engine, side) -> AiResult {Action, MoveSlot, ItemId, ChangeIndex, Scores[]}
BattleAiBrain : IEnemyBrain          (Brücke; die Engine baut sie bei EnemyAi != null selbst)
TrainerAi(aiBits, seed, useItems)    (Standard-Implementierung; TrainerAi.ForTrainer(0, …) = null)
```
`EnemyBrain` hat weiter Vorrang vor `EnemyAi`. In der Engine ist der Gegner-Befehl `Item` jetzt erlaubt (nur Heil-Items aus `EnemyItems`; der Befehl `Run` bleibt verboten); `Change` war bereits erlaubt. Alle vorhandenen Battle-Tests laufen unverändert (169 grün im dotnet-Projekt; die 645 Unity-Tests selbst wurden nicht im Editor gefahren).

## 8. Lücken und Aufwand

| Block | Stand | Aufwand (Schätzung) |
|---|---|---|
| `BtlAiDouble` (Bit 3, bei **allen** Trainern gesetzt; wirkt auch im Einzelkampf) | nicht umgesetzt | 2 Tage: `DoubleAI_Enemy_Main` (30 KB) + 36 Enemy-Seq-Funktionen, mit Orakel |
| `BtlAiExpert` (83 Trainer, 256 Funktionen, 996 KB) | nicht umgesetzt | 4–5 Tage; mit halbautomatischer Übersetzung (Ghidra-C → C#, Orakel als Prüfer) ca. 2–3 Tage |
| Basic: 115 weitere Seq-Funktionen (7,6 % der Attacken-Slots; größte: 067, 175, 023, 266, 167, 090, 242) | teilweise | 1–1,5 Tage |
| Strong: Doppelkampf- und G-Zweig | nicht umgesetzt | 0,5 Tage (im Einzelkampf irrelevant) |
| AI_CMD-Befehle: exakte Schadensrechnung (`BattleSimulator.CalcDamage`), Delegator, Abschiedslied, Gelände, Zustandsprüfung der Bank, Beerenprüfung, `GetAIItemPriority`-Tabelle | Näherung/[N] | 1–2 Tage; zusätzlich ein Orakel für die Befehle (nicht nur die Skripte) |
| KI-Zufallsfolge wie im Original (`randSeed`, `Random` je Judge) | [A] | 0,5 Tage, braucht das echte Kampf-Setup |
| Wild-/Safari-KI, Raid-Boss (`wazaScore_DecideRaidBoss`), Doppelkampf-Ziele | nicht umgesetzt | außerhalb des Einzelkampf-Umfangs |

## 9. Prüfung

- `BattleAiScriptOracleTests` (6): Basic, Strong, Allowance, Item, PokeChange gegen das Orakel; Verteilertabelle = Fixture; jede umgesetzte Seq-Funktion ist erreichbar.
- `BattleAiFlowTests` (8): Typ-Immunität wird gemieden (Wertung 90 gegen 100), Zufall bei Gleichstand, Reproduzierbarkeit, Heil-Item bei niedrigen KP, kein Item bei vollen KP, ganzer Kampf mit KI, Trainer ohne Bits → keine KI, ohne `EnemyAi` bleibt der Zufallsgegner Standard.
- Lokal: `BattleAiPlaythroughLocal` (60 Teams × Zufallsgegner/Trainer-KI, alle 706 Teams mit KI).
