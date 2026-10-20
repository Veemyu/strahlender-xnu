# Kampfablauf, Scheibe 7: Gegner-KI vollständig (Double, Expert, Basic-Rest, Strong-Doppelzweig)

Stand: Scheibe 7, aufbauend auf `docs/kampf-spezifikation-6.md` (dort: Basic/Strong/Allowance/Item/PokeChange; offen waren Double, Expert, 115 Basic-Seq-Funktionen und der Strong-Doppelzweig).
Code: `unity/Assets/Scripts/BattleFlow/Ai/` (von Hand: `TrainerAi.cs`, `AiWorld.cs`, `AiScriptBase.cs`, `AiScriptBasic.cs`, `AiScriptsOther.cs`; **erzeugt**: `Generated/AiScriptDouble.cs`, `AiScriptExpert.cs`, `AiScriptBasicGen.cs`, `AiScriptStrongFull.cs`).
Werkzeug: `scripts/ai_translate/` (Pseudocode → C#), Orakel: `scripts/battle_oracle_ai.py` (Unicorn, echte ARM64-Funktionen). Prüfstufen wie in Spezifikation 6 (**[O]** vom Orakel bestätigt, **[P]** aus Pseudocode gelesen, **[A]** Annahme, **[N]** nicht modelliert).

**Repo-Regel (Entscheidung des Nutzers: eigene Formulierung, kein übersetzter Spielcode im Repo):** `Generated/` ist maschinell aus dem Pseudocode übersetzt und deshalb gitignoriert; es entsteht beim Bauen aus dem eigenen Dump (vorgesehene Build-Stufe `ai_translate`, Ghidra-Pseudocode-Export vorausgesetzt). Im Repo liegen nur der Übersetzer, das Orakel, Zahlen-Fixtures und die von Hand geschriebenen Teile. `AiGenerated.Create` lädt die erzeugten Klassen per Reflection (`link.xml` behält `Assembly-CSharp`; die Battle-Assembly ist Projektcode); fehlen sie, baut das Spiel weiter, die Orakeltests werden übersprungen und Trainer mit Expert/Double-Bits bekommen diese KI-Stufe nicht.

## 1. Ergebnis in Zahlen

| | Spezifikation 6 | Scheibe 7 |
|---|---|---|
| Skriptklassen umgesetzt (Bits der 706 Trainerteams) | Basic, Strong (nur Einzelkampf), Allowance, Item, PokeChange | **alle sieben**: zusätzlich **Double (706 Trainer)**, **Expert (83)**, Strong mit Doppel- und G-Zweig |
| Per Orakel bestätigte Funktionen (Einträge) | 66 | **505 Funktionen**: Basic 167 (alle erreichbaren 148 Seq-Funktionen + 15 Hilfsfunktionen + `main_proc`), Double 65, Expert 255, Strong 3, Allowance 1, Item 6, PokeChange 8 |
| Verglichene Orakel-Fälle (Pseudo-Welten) | 4220 | **11 300**, 0 Abweichungen, 0 übersprungene |
| Basic: umgesetzte Seq-Funktionen | 33 von 148 (7,6 % der Attacken-Slots liefen ins Leere) | **148 von 148**: 119 erzeugt, 33 von Hand; Slots ohne Wirkung: 0 |
| Skriptumfang als C# | ca. 60 KB von Hand | + 137 KB Double, 361 KB Expert, 92 KB Basic-Rest, 15 KB Strong (erzeugt) |
| `UnimplementedScriptBits` (gesetzte, nicht umgesetzte KI-Skripte) | 2 (Expert, Double) | **0** |
| Tests im dotnet-Wegwerfprojekt (alle Battle-Tests der Unity-Suite) | 169 | **174 grün** (neu: 4 Orakel-Tests Double/Expert/Strong/Basic-Seq, 1 Ablauf-Test mit allen Skripten) |

Lauf über alle 706 Teams (Spiegelteam, gieriger Spieler; Messhilfe `BattleAiPlaythroughLocal`, nicht im Repo, weil `work/masterdata` gebraucht wird):

| | Gegner siegt | Spieler siegt | unentschieden | nicht beendet | Runden Ø | NotImplemented | Items | Wechsel |
|---|---|---|---|---|---|---|---|---|
| Zufallsgegner | 111 | 587 | 8 | 0 | 15,7 | 91 | – | – |
| Trainer-KI Scheibe 6 | 143 | 558 | 5 | 0 | 15,2 | 101 | 66 | 49 |
| **Trainer-KI Scheibe 7** | **163** | 537 | 6 | **0** | 15,0 | **83** | 69 | 46 |

Erste 60 Teams: Zufallsgegner 8 Siege / Ø 22,3 Runden; Trainer-KI Scheibe 6: 13 Siege / Ø 18,9; **Scheibe 7: 16 Siege / Ø 18,8**, NotImplemented 4 (vorher 8).

**NotImplemented** ist ein Zähler der Kampf-**Engine** (`FailCause.NotImplemented`: die gewählte Attacke braucht Handler/Sections, die es noch nicht gibt), nicht der KI-Skripte; die KI-Skripte selbst haben seit dieser Scheibe keine Lücke mehr. Der Zähler ist beim Zufallsgegner mit 91 praktisch gleich hoch (die KI wählt nicht häufiger Unfertiges). Es sind nur **11 verschiedene Attacken** (Nummern, gezählt über alle 706 Teams mit Trainer-KI): 214 (30×), 272 (12×), 118 (10×), 164 (8×), 102 (6×), 286 (6×), 580 (4×), 604 (3×), 277 (2×), 494 (1×), 668 (1×). Sie zu beheben ist Sache der Engine-Seite (`BattleEngine.SpecialMoves`), nicht der KI.

## 2. Methode: Pseudocode → C# (statt 440 Funktionen von Hand)

Handübersetzung ist für 440 weitere Funktionen (Double 65, Basic 115, Expert 256) nicht zu leisten und nicht prüfbar. Die Skripte sind aber selbst in C# geschriebener Code, der als IL2CPP-Pseudocode vorliegt; deshalb übersetzt ein Werkzeug (`scripts/ai_translate/`: `ghc_parse.py` Parser und Rauschentfernung, `ghc_emit.py` Ausgabe, `ai_translate.py` Klassen) den Pseudocode, und das **Orakel prüft jede Funktion einzeln gegen die echte ARM64-Funktion**. Das Werkzeug liest nur `work/decomp/battle_all` (Pseudocode, nicht im Repo) und das Orakel (statische Zahlenfelder aus dem ELF); die erzeugten Dateien enthalten Befehlsfolgen, Konstanten und Kontrollfluss der Skripte, keine Daten oder Texte des Spiels.

Was das Werkzeug tut:

- **Parser** für die verwendete C-Teilmenge (Ausdrücke mit Casts, Zeigerzugriffen, Komma-Operator; `if/else`, `goto`, Marken, `switch`).
- **Rauschen entfernen**: Klassen-Initialisierung (`DAT_… & 1`, `FUN_00359b58`, Zugriffe auf +0x12e/+0xe0), Debug-Ausgabe (`PRINTF`, `String.Format`, Boxing) – ausgenommen `CurrentWazaNo`-Aufrufe in der Debug-Ausgabe, die als echter `AI_CMD` mitlaufen (ohne sie weicht die Aufruffolge von `BtlAiDouble.main` ab, vom Orakel gefunden); Grenzprüfungen der Argument-Arrays (`if (len < 3 || (arr[2] = x, len == 3)) goto FEHLER`) werden zu den enthaltenen Zuweisungen; Fehler-Tails (`thunk_FUN_0035c83c; FUN_003afbc0`) fallen weg.
- **Arrays verschmelzen**: `a = new long[n]; a[0] = x; …; r = Call(cmd, a)` → `r = C(cmd, n, x, …)` (die Länge `n` zählt in der Aufruffolge mit); ist das nicht eindeutig möglich (Array über Marken hinweg wiederverwendet), bleibt ein echtes Array `aA`. Statische Zahlenfelder (`InitializeArray`) liest das Orakel aus dem ELF und setzt sie als Konstanten ein; ebenso die Wertungstabellen der Expert-Typprüfung (11 Tabellen mit Werten −1/+1).
- **Typtreue**: Ghidra-Variablentypen (int/uint/long/ulong) bleiben erhalten; `x - 0x68U < 0x3d` bleibt vorzeichenlos; Bitmasken-Idiome `(1L << (x & 0x3f)) & M` werden zu `Bit(x, M)`.
- **Kontrollfluss goto-treu**: C# erlaubt `goto` nur in umschließende Blöcke; ein `if`-Block bleibt strukturiert, wenn alle in ihm sichtbaren Marken nur von innen angesprungen werden, sonst wird er zu `if (!c) goto …` abgeflacht. `switch` (Sprungtabellen des Originals) wird zu `switch … goto` mit zusammengelegten Fällen.
- Einsprungstellen (`Run(name)`) und Namensliste (`Functions`) sind erzeugt, keine Reflexion (wegen IL2CPP-Stripping).

Der Aufruf `PYTHONPATH=tools/pydeps python3 scripts/ai_translate/ai_translate.py` schreibt nach `unity/Assets/Scripts/BattleFlow/Ai/Generated/`. Eine einzige Stelle ließ sich nicht automatisch lesen: `DoubleAI_Friend_Main` ruft für die KI-Nummern 0x181–0x189 über eine Sprungtabelle (Ghidra: „indirect jump“); die Zuordnung (385, 386→309, 388, 391, 393→309) hat das Orakel gemessen und ist im Werkzeug festgehalten.

## 3. Double (Bit 3, alle 706 Trainer) — [O]

`BtlAiDouble.main` (0x1d0b560): `IF_MIKATA_ATTACK` (Ziel ist der Partner) → `DoubleAI_Friend_Main`, sonst `DoubleAI_Enemy_Main`. Im **Einzelkampf** ist `IF_MIKATA_ATTACK` immer 0, es läuft also nur der Enemy-Zweig; der Friend-Zweig ist trotzdem umgesetzt und geprüft (für Doppelkämpfe).

- `DoubleAI_Enemy_Main`: Vorspann mit Fähigkeitsprüfungen des Gegenübers (Blitzableiter 31, Sturmsog 114, Magiespiegel 156 u. a.: −10 bei passenden Attackentypen und KI-Nummern, mehrere Zufallswürfe), dann Verteiler über die KI-Nummer (`switch` über Bereiche) auf die Enemy-Seq-Funktionen. 42 KI-Nummern verteilen auf 41 Enemy-Funktionen (`BattleAiDispatchDouble.json`, Schlüssel `BtlAiDouble.Enemy`, vom Orakel gemessen); größte: 111 (18 KB), 195 (22 KB mit Unterfunktion), 147, 172, 378.
- `DoubleAI_Friend_Main`: 21 KI-Nummern auf 20 Friend-Funktionen (Partner-Unterstützung, z. B. Heilattacken auf den Partner, Windattacken).
- Das Orakel läuft jede der 66 Funktionen mit je 16 Pseudo-Welten; für beide Verteiler zusätzlich mit **festgelegter KI-Nummer** (`DoubleAI_Enemy_Main@62=k` für 44, `DoubleAI_Friend_Main@62=k` für 22 Nummern), damit jede Verzweigung des Verteilers wirklich läuft: 131 Einträge, **2096 Fälle, 0 Abweichungen**.

## 4. Basic-Rest und Strong-Doppelzweig — [O]

Die 115 fehlenden Basic-Seq-Funktionen sind erzeugt (`AiScriptBasicGen.cs`, 119 Funktionen inkl. Hilfsfunktionen, registriert über `partial void RegisterGenerated()`); die 33 von Hand geschriebenen bleiben und werden von den erzeugten aufgerufen (`Seq0NN`). Fixture `BattleAiScriptsBasicSeq.json` (152 Seq-Funktionen, 1824 Fälle) und die alte `BattleAiScripts.json` (48 Funktionen, jetzt **ohne** übersprungene Fälle statt vorher 4) stimmen. Die größten bisher fehlenden Funktionen (067, 175, 023, 266, 167, 090, 242) sind enthalten.

`BtlAiStrong` ist jetzt vollständig (`AiScriptStrongFull`, 3 Funktionen, 192 Fälle ohne festgelegte Befehlsantworten, also **mit** Doppelkampf-Zweig `CHECK_BTL_RULE = 1` und G-Zweig). Die handgeschriebene `AiScriptStrong` (nur Einzelkampf) bleibt als Referenz mit ihrem alten Test; `TrainerAi` nutzt `AiScriptStrongFull`.

## 5. Expert (Bit 2, 83 Trainer) — [O]

`ExpertAI.main_proc` (0x1d1ab60): langer Vorspann (Item-, Fähigkeits- und Zustandsprüfungen), Verteiler über 294 KI-Nummern auf 223 Funktionen; `ExpertAI_TypeCheck(param)` (25 Aufrufe) wertet je Wetter/Typ-Gruppe mit 11 Wertungstabellen. **Alle 257 Funktionen** sind umgesetzt (Seq-Funktionen, Unterfunktionen, `…Pokemon`-Hilfsfunktionen wie `CopyPokemonTokusei`, `MegaShinkaPokemon`); Orakel: 255 Funktionen, 3060 Fälle, 0 Abweichungen (`TypeCheck` wird über seine Aufrufer mitgeprüft). Damit ist die in Spezifikation 6 geschätzte Lückenliste (46 % der Expert-Attacken-Slots ohne Funktion) gegenstandslos. Gefundene Fehler während der Entwicklung (alle vom Orakel): `break` in verschachtelten `if` im `switch`, Argument-Typ `byte` von `TypeCheck` (Abschneiden von 0x50e0a09 auf 9), Längenvariable, die zugleich als Attackennummer dient (`iVar2 = *(int*)(arr+0x18)` → Konstante).

## 6. AiWorld (Abfragebefehle) und Schaden

**Schaden [P]:** `COMP_POWER`, `GET_MAX_WAZA_POWER` und das neue `IF_WAZA_HINSHI` rechnen mit dem echten `DamageCalculator` (`BattleEngine.EstimateDamageForAi`: `Launcher.BuildDamageInput` mit Wetter, Stufen, STAB, Typenwirkung, Brand; **fester Zufallsfaktor 85, kein Volltreffer**, `DamageInput.FixedRoll` – im Original setzt nur der KI-Simulator das Flag). Die frühere Näherung entfällt. Nicht enthalten sind Fähigkeits-/Item-Handler außerhalb der Wirkungs-ID, soweit der Launcher sie nicht berücksichtigt **[A]**.

**Neue Befehle:** `IF_WAZA_HINSHI`/`IFN_` (Schaden ≥ KP des Gegners) [P], `IF_HINSHI`, `IF_HAVE_WAZA`/`IF_HAVE_WAZA_SEQNO` (eigene Seite: alle Attacken, Gegenüber nur bereits eingesetzte – `CheckWazaStored`, aus dem Kampfprotokoll) [P], `IF_COMMONRND_*` (gemeinsamer Zufallswert der Runde) [P/A], `CHECK_AGI_RANK`, `CHECK_MAMORU_COUNT`, `CHECK_LAST_WAZA_KIND`, `CHECK_STATUS`, `IF_DMG_PHYSIC_*` (Angriff gegen Sp.-Angriff mit Stufen) [P], `IF_DOKUDOKU` (Gift mit Moudoku-Zähler), `IF_BENCH_PPDEC`. Von den 100 Befehlen, die die Skripte tatsächlich aufrufen, hat jetzt jeder einen `case` (vorher fehlten mehrere). Insgesamt 110 von 130 Befehlsnummern haben einen `case` (die 20 ohne `case` ruft kein Skript auf; sie liefern 0); **[N]** (bewusst 0, 16 Befehle): `IF_CONTFLG`, 18/19 (Abgesang), `IF_BENCH_DAMAGE_MAX`, `CHECK_SLOWSTART_TURN`, `GET_MEZAME_TYPE`, `IF_WAZAHIDE`, `IF_ALREADY_MORAIBI`, `COMP_POWER_WITH_PARTNER`, `CHECK_NEKODAMASI`, `CHECK_RECYCLE_ITEM`, `IF_TOTTEOKI`, `IF_MIGAWARI`, `IF_EXIST_GROUND`, `CHECK_WAZA_NO_EFFECT_BY_TOKUSEI`, `IF_ZIDANDA_POWERUP`.

**Orakel für die Befehle: nicht umgesetzt.** Die `CMDFUNC_*` greifen über `GetBppByAISide` auf `BTL_POKEPARAM` (Kernparameter +0x10 mit KP bei +0x26, Zustandsarray +0x48, Attackenliste +0x30, Rangwerte +0x18/+0x20 …) und das `BattleSimulator` zu. Im Emulator liefen sie nur mit einem im Gastspeicher aufgebauten Pokémon samt Kampfumgebung (`GuestHeap` aus `battle_oracle_heap.py` kann Objekte nach dem Dump anlegen; für `BTL_POKEPARAM` fehlt die Konsistenz der verschachtelten Felder). Aufwand grob 1–2 Tage für etwa 40 reine Lesebefehle (Typ, Fähigkeit, KP, Rang, Zustand, Attackenliste); Schaden/Reihenfolge brauchen zusätzlich `BattleSimulator`. Bis dahin ist die Befehls-Seite weiter die größte Fehlerquelle der Treue (unverändert aus Spezifikation 6).

## 7. Zufall

Der Zufallsgenerator der KI ist der Xoroshiro128+ des Originals (`Dpr.Battle.Logic.Random`, bereits `BattleRandom`). **[P]** `BattleAi.ctor` (0x20eb…) erzeugt ein **eigenes** `Random` und initialisiert es mit dem `randSeed` des Kampf-Setups (`Random.Initialize(setup+0x28)`), kein Mischen mit einer Konstante; `TrainerAi` seedet jetzt mit `BattleSetup.Seed` (bisher `Seed ^ 0xA1A1A1A1`). Der gemeinsame Wert für `IF_COMMONRND_*` kommt im Original aus dem Zufall von `BTL_CLIENT` (+0x90, `GetValue(0x100)`); dessen Seed und die genaue Abfolge der Würfe je Attacke/Skript (Reihenfolge von `wazaScore_DecideBest`, Skript-Würfen, Tokusei-Raten) sind **[A]**: gleiche Entscheidungen, aber nicht Wurf für Wurf wie im Original. Das ableiten zu können, bräuchte das Kampf-Setup des Originals (Reihenfolge der Judge-Aufrufe, `BTL_CLIENT`-Seed).

## 8. Lücken

| Block | Stand |
|---|---|
| Orakel für die 130 `CMDFUNC_*` (Befehls-Seite von `AiWorld`) | nicht umgesetzt (Abschnitt 6); 16 Befehle bewusst [N] (liefern 0) |
| KI-Zufallsfolge Wurf für Wurf | Generator und Seed [P], Reihenfolge der Würfe und `BTL_CLIENT`-Zufall [A] |
| Schaden: Fähigkeits-/Item-Handler im `BattleSimulator.CalcDamage` | nur was `Launcher.BuildDamageInput` berücksichtigt |
| Doppelkampf in `TrainerAi` (Zielwahl, `IF_MIKATA_ATTACK`) | die Skripte sind umgesetzt und geprüft; `AiWorld`/`TrainerAi` bilden nur den Einzelkampf ab |
| Engine-NotImplemented (11 Attacken, Abschnitt 1) | Engine, nicht KI |
| Wild-/Safari-KI, Raid-Boss | wie Spezifikation 6, außerhalb des Umfangs |

## 9. Prüfung

- `BattleAiScriptOracleTests`: Basic (48 Funktionen, 3072 Fälle), Basic-Rest/Seq (152, 1824), Double (131, 2096), Expert (255, 3060), Strong (3, 96) und Strong voll (3, 192), Allowance, Item, PokeChange; Verteilertabelle; jede Verteilerzahl führt auf eine umgesetzte Funktion.
- `BattleAiFlowTests`: zusätzlich ein ganzer Kampf mit allen sieben Skripten (reproduzierbar, `UnimplementedScriptBits == 0`).
- Fixtures (nur Zahlen): `BattleAiScriptsDouble/Expert/StrongFull/BasicSeq.json`, `BattleAiDispatchDouble.json`. Erzeugung siehe Kopf von `scripts/battle_oracle_ai.py` (Aufrufe je Klasse mit `--suffix`; Einträge der Include-Dateien dürfen Muster enthalten, `name@62=k` legt die KI-Nummer fest). Erneutes Erzeugen liefert bytegleiche Dateien.
- Lokal: `BattleAiPlaythroughLocal` (60 Teams, alle 706 Teams, Zufallsgegner und Trainer-KI, NotImplemented je Attacke).
