# Kampf-Ereignissystem, Scheibe 2: Spezifikation

Stand: Zwischenstand Scheibe 2 (Rückgrat des Kampfs: Ereignisse, Faktoren, Handler; ohne Rendering, ohne Sound).
Diese Datei ist die Spezifikation in eigenen Worten. Die C#-Umsetzung (`unity/Assets/Scripts/BattleEvents`, Assembly
`Xnu.Battle.Events`, reine Logik ohne UnityEngine) ist ausschließlich aus diesem Text entstanden, nicht aus dem Pseudocode
abgeschrieben. Sie baut auf Scheibe 1 auf (`docs/kampf-spezifikation-1.md`, Assembly `Xnu.Battle`), deren Rechner bisher die
Handler-Ergebnisse als Eingaben bekamen; jetzt liefert das Ereignissystem diese Eingaben selbst.

## 0. Vorgehen und Belegkonvention

- **Quellen (nur lesen):** Pseudocode-Export `work/decomp/battle_all/` (je Klasse eine Datei, Kopfzeile `// 0xADRESSE Name`),
  Typen/Felder/Offsets aus `work/il2cpp/dump.cs`, Binary `work/elf/main.patched.elf`. Kein neuer Ghidra-Lauf.
- **Beleg:** `[Klasse.Methode @0xADRESSE]`; die Adresse ist die Ghidra-Adresse (Il2CppDumper-RVA + 0x100000). Felder stehen als
  `Feld @Offset` (Hexadezimal, Objekt-Offset aus `dump.cs`; Objektkopf 0x10 Byte, Array-Länge bei +0x18, Elemente ab +0x20).
- **Prüfstufe je Aussage** (wie in Scheibe 1):
  - **[O]** durch das Emulations-Orakel bestätigt: die echte ARM64-Funktion lief in Unicorn auf synthetischem Gast-Speicher; die
    Zahlen stehen in `unity/Assets/Tests/EditMode/Fixtures/BattleEvents*.json` und werden im Unity-Test gegen die C#-Umsetzung
    geprüft (Abschnitt 9).
  - **[OK]** Orakel mit ersetzten Nachbarfunktionen (z. B. Pokémon-Abfragen durch Testwerte); die geprüfte Funktion selbst ist echt.
  - **[P]** nur aus dem Pseudocode gelesen und mit handgerechneten Beispielen getestet.
- Interne Namen der Originalklassen (japanische Kürzel wie `Tokusei` = Fähigkeit, `Waza` = Attacke, `Kodawari` = Wahl-Item,
  `Tikaramoti` = Kraftkoloss, `Fukugan` = Facettenauge) werden nur in Belegen genutzt.
- **Lehre aus dem Orakel:** Der Pseudocode verliert Stack-Argumente von Wrapper-Funktionen. `EventSystem.AddFactor` erscheint dort mit
  einem einzigen Argument; erst die Disassemblierung (`ldr w9,[x0,#0x58]; strh w9,[sp]`) zeigt, dass die aktuelle Aufruftiefe als
  neuntes Argument mitgegeben wird (Abschnitt 4.3). Das Orakel hat die zuerst falsche Annahme „Stufe 0“ aufgedeckt.

## 1. Überblick

```
  Spielablauf (Sections, EventLauncher)                Handler (Tokusei, Item, Waza, Seite, Feld, Pos, ...)
        |  Event_xyz(...)                                      ^  registriert beim Einwechseln, Item-Wechsel, Attackenstart
        |  1. EVENTVAR_Push  (neuer Variablenrahmen)           |
        |  2. EVENTVAR_Set*  (Eingaben als Variablen)     EventSystem.AddFactor  ->  EventFactorContainer
        |  3. CallEvent(id)  ------------------------->  Liste der Faktoren, nach Prioritaet sortiert
        |       fuer jeden Faktor: passt id? -> Handler(args, dependID)   (liest/aendert Variablen)
        |  4. EVENTVAR_GetValue (Ergebnis lesen)
        |  5. EVENTVAR_Pop
        v
   Rechner aus Scheibe 1 (Schaden, Treffer, Volltreffer, Erfahrung)
```

Kernidee: Der Kampfablauf kennt keine einzelnen Fähigkeiten oder Items. Er ruft an festen Stellen ein **Ereignis** (`EventID`, 229
Stück) auf. Alle **Faktoren** (registrierte Handler-Sätze) werden der Reihe nach angesehen; jeder, der für dieses Ereignis einen
Handler hat, darf **Ereignis-Variablen** lesen und ändern. Das Ergebnis liest der Aufrufer anschließend aus den Variablen.

## 2. Ereignis-Variablen (EventVar)

### 2.1 Bezeichner

- `EventID` [`dump.cs EventID`]: 229 Werte, 0 = ungültig. Auszug mit den Ereignissen der Scheibe: `ACTPROC_START` 1, `WAZA_HIT_RANK` 63,
  `WAZA_HIT_RATIO` 64, `WAZA_POWER_BASE` 69, `WAZA_POWER` 70, `ATTACKER_POWER_PREV` 71, `DEFENDER_GUARD_PREV` 72, `ATTACKER_POWER_VID` 73,
  `ATTACKER_POWER` 74, `DEFENDER_GUARD` 75, `TYPEMATCH_CHECK` 83, `TYPEMATCH_RATIO` 84, `WAZA_DMG_PROC1/2/3` 88/89/90, `USE_ITEM_TMP` 142,
  `MEMBER_IN` 108, `TURN_END` 223 (vollständige Liste in `EventIds.cs`).
- `EventVar.Label` [`dump.cs EventVar.Label`]: 124 Variablen plus `NUM`; 0 (`INVALID`) bedeutet „Slot frei“, 1 (`SYS_SEPARATE`) ist das
  Rahmen-Trennzeichen. Die in dieser Scheibe benutzten: `POKEID_ATK` 3, `POKEID_DEF` 4, `WAZAID` 18, `WAZA_TYPE` 22, `DAMAGE_TYPE` 27
  (0 keine, 1 physisch, 2 speziell), `HIT_RANK` 42, `AVOID_RANK` 43, `HIT_PER` 46, `WAZA_POWER` 51, `WAZA_POWER_RATIO` 52, `DAMAGE` 53,
  `POWER` 54, `GUARD` 55, `RATIO` 56, `TYPEAFF` 61, `SWAP_POKEID` 64, `VID` 65, `VID_SWAP_CNT` 66, `CRITICAL_FLAG` 76, `FLAT_FLAG` 82,
  `GEN_FLAG` 89, `WAZA_TOUCH_FLAG` 99.
- Jede Variable ist eine 32-Bit-Ganzzahl (`EventVar @0x14 m_value`), dazu Zustand (`@0x12`), Grenzen (`@0x18/0x1C`) und ein optionaler
  Objektverweis (`@0x20`).

### 2.2 Zustände und Operationen [O]

`EventVar.RewriteState` [`dump.cs`]: `FREE` 0, `ONCE` 1, `END` 2, `MUL` 3, `LOCK` 4. Jede Operation setzt Wert, Grenzen, Verweis und
Zustand vollständig neu (nur beim Freigeben bleibt der Inhalt stehen, siehe 2.3):

| Operation (EventSystem) | Wirkung | Beleg |
|---|---|---|
| `SetValue(l, v)` | Wert `v`, Grenzen 0, Verweis leer, Zustand FREE (beliebig oft umschreibbar) | `EVENTVAR_SetValue @0x19f5950`, `EventVar.SetValue @0x19f5a90` |
| `SetConstValue(l, v)` | wie oben, Zustand LOCK (nie änderbar) | `@0x19f5b60`, `EventVar.SetConstValue @0x19f5c20` |
| `SetRewriteOnceValue(l, v)` | Zustand ONCE: genau eine Umschreibung erlaubt | `@0x19f5c60`, `@0x19f5d20` |
| `SetMulValue(l, v, min, max)` | Zustand MUL mit Grenzen; nur per `MulValue` änderbar | `@0x19f5e10`, `@0x19f5ed0` |
| `RewriteValue(l, v)` | nur bei Zustand FREE oder ONCE (`state < 2`): Wert setzen, ONCE wird END; liefert Erfolg | `@0x19f5f10`, `EventVar.RewriteValue @0x19f5f90` |
| `RecoveryRewriteOncePermission(l)` | Zustand wieder ONCE (auch aus END/LOCK/MUL) | `@0x19f5d60`, `@0x19f5e00` |
| `MulValue(l, f)` | nur bei Zustand MUL: `v = (int)((long)v * f + 0x800 >> 12)`; danach, falls `min != 0` oder `max != 0`, auf `[min, max]` geklemmt | `@0x19f5fc0`, `EventVar.MulValue @0x19f6050` |
| `GetValue(l)` | Wert, fehlende Variable liefert 0 | `@0x19f60a0` |
| `GetValueIfExist(l, out v)` | Erfolg + Wert; sonst `false` und Wert 0 | `@0x19f6100` |
| `SetWorkAddress(l, obj)` / `GetWorkAddress(l)` | Variable mit Objektverweis statt Zahl (Wert 0) | `@0x19f6170`, `@0x19f6270`, `EventVar.SetAddress @0x19f6230` |

Rechenregel von `MulValue` [O]: Das 64-Bit-Zwischenergebnis wird **zuerst auf 32 Bit gekürzt**, erst dann geklemmt. Bei Überlauf
(z. B. `int.MaxValue` mal 4915) gewinnt deshalb die Untergrenze; Scheibe 1 (`BattleMath.EventVarMul`) klemmt dagegen vor dem Kürzen. Der
Unterschied betrifft nur Überlauf und ist in Scheibe 1 nicht verwendet; die neue Klasse `EventVar` folgt dem Original. Ein Handler-Verhältnis
(Festkomma x/4096) wird mit dieser Regel auf die Variable multipliziert; Startwert ist meist 0x1000 (= 1,0), Grenzen z. B. `[0x29, 0x20000]`.

### 2.3 Stapel und Rahmen [O]

- `EventVarStack` [`dump.cs`, `m_variables @0x10`, `m_sp @0x18`]: ein Vorrat von **96** Variablen (`EVENTVAL_STACK_DEPTH`). Slot mit
  Label 0 ist frei. `Push` [`@0x19f5590`]: ab `m_sp` die belegten Slots überspringen, in den ersten freien Slot das Trennzeichen
  (Label 1) schreiben, `m_sp` dahinter; der letzte Slot (95) wird nie Trennzeichen, ein voller Vorrat tut nichts. `Pop` [`@0x19f57b0`]:
  ab `m_sp` alle belegten Slots des Rahmens freigeben (nur das Label wird 0, Wert/Zustand bleiben stehen), dann das Trennzeichen davor
  freigeben und `m_sp` hinter das vorige Trennzeichen (bzw. 0) setzen. `GetNewPoint` [`@0x19f5a10`] liefert ab `m_sp` den ersten freien oder
  gleich benannten Slot; so überschreibt `SetValue` dieselbe Variable im selben Rahmen. `ToEmpty` [`@0x19f46d0`] gibt alles frei.
- `EventVarSet` [`@0x10 m_pVariables`, 124 Slots]: Variablen nach Label. `SetVariable` [`@0x19f5ad0`] legt die Variable ab (Label ≥ 124
  wird nicht eingetragen, belegt aber den Stapel-Slot); `GetVariable` [`@0x19f5db0`] liest.
- `EventVarSetStack` [`@0x10 m_varSets`, `@0x18 m_stackPointer`]: **32** Variablensätze, einer je Rahmen. `Push` [`@0x19f5630`] erhöht den
  Zeiger bis höchstens 31, `Pop` [`@0x19f5700`] leert den aktuellen Satz und senkt den Zeiger.
- `EventSystem.EVENTVAR_Push` [`@0x19f5510`]: Variablenstapel `Push`, Satzstapel `Push`, aktueller Satz = `m_varSets[m_stackPointer]`.
  `EVENTVAR_Pop` [`@0x19f56a0`]: Satzstapel `Pop`, aktueller Satz neu bestimmen, Variablenstapel `Pop`. `EVENTVAR_CheckStackCleared`
  [`@0x19f5880`]: ist der Stapel nicht leer, alles zurücksetzen.
- **Sichtbarkeit:** Lese-/Schreibzugriffe gehen immer auf den **aktuellen** Satz. Ein innerer Rahmen sieht die Variablen des äußeren
  nicht (er beginnt leer); nach dem `Pop` sind die äußeren wieder sichtbar. Ein Handler, der ein eigenes Ereignis aufruft, muss deshalb
  vorher selbst `Push` aufrufen und die benötigten Variablen neu setzen.
- Vor dem ersten `Push` gibt es keinen aktuellen Satz (`m_pCurrentEventVarSet @0x50` ist 0); das Original würde abstürzen, die
  C#-Umsetzung wirft eine `InvalidOperationException`.

## 3. Faktoren und ihre Verwaltung

### 3.1 Faktor (`EventFactor`, `EventFactor.Data`) [O]

Ein Faktor ist ein Handler-Satz mit Metadaten. `EventFactor` [`@0x10 m_instanceID`, `@0x18 m_prevFactor`, `@0x20 m_nextFactor`, `@0x28 m_data`],
`EventFactor.Data` (Offsets):

| Offset | Feld | Bedeutung |
|---|---|---|
| 0x10 | `handlerTable` | Tabelle `EventHandlerTable[]` (`eventID @0x10`, `eventHandler @0x18`) |
| 0x18 | `skipCheckHandler` | optionaler Überspring-Handler (Abschnitt 5.3) |
| 0x20 | `factorType` | `EventFactorType` (3.2) |
| 0x24 | `priority` | 32-Bit-Sortierschlüssel (3.3) |
| 0x28 | `subID` | Tokusei-Nr., Item-Nr., Attacken-Nr., Seiteneffekt-Nr. usw. |
| 0x2A | `dependID` | Pokémon-ID (Waza/Tokusei/Item), Seite oder Parameter |
| 0x2B | `pokeID` | Pokémon-ID für Schlaf/Wecken und Skip-Prüfung; 0x1F = keines |
| 0x2C | `eventLevel` | Aufruftiefe bei der Registrierung (4.3) |
| 0x30 | `numHandlers` | Anzahl der Tabelleneinträge (Byte) |
| 0x34–0x39 | `callingFlag`, `recallEnableFlag`, `rmReserveFlag`, `sleepFlag`, `tmpItemFlag`, `existFlag` | Laufzeit-Flags (Abschnitt 5) |
| 0x40 | `work` | `int[7]`, freie Arbeitswerte des Handlers (`EVENT_HANDLER_WORK_ELEMS = 7`) |

`Clear` [`EventFactor.Clear @0x1e124c0`] setzt alle Felder und Arbeitswerte auf 0. Zugriffe auf Arbeitswerte: `GetWorkValue @0x1e09d60`,
`SetWorkValue @0x1e09de0` (Index ≥ 7 wirft). Konventionen der Registrierer: Arbeitswert 6 ungleich 0 schützt Item- und Waza-Faktoren vor
dem Standard-Entfernen (`Item.Remove`, `Waza.Remove`), Arbeitswert 4 schützt Tokusei-Faktoren (`Tokusei.Remove`).

### 3.2 Typen und Hauptprioritäten [O]

`EventFactorType` [`dump.cs`]: `WAZA` 0, `POS` 1, `SIDE` 2, `FIELD` 3, `TOKUSEI` 4, `ITEM` 5, `DEFAULT_POWERUP` 6, `RAIDBOSS` 7, `ISOLATE` 8,
`NUM` 9 (beim Aufruf „alle Typen“). **Es gibt keinen eigenen Faktortyp für Statusprobleme („Sick“) und keinen für Wetter**: Wetter ist
ein `FIELD`-Faktor (`Handler.Field.ADD_Fld_Weather`), Statusprobleme leben im Sick-Container des Pokémon (Abschnitt 7) und werden
über die Ereignisse `ADD_SICK`, `WAZASICK_*`, `POKESICK_FIXED` usw. von den Tokusei-/Item-/Waza-Handlern beeinflusst.

`EventPriority` [`dump.cs`]: `DEFAULT_POWERUP` 0, `WAZA` 1, `POS` 2, `SIDE` 3, `FIELD` 4, `RAIDBOSS` 5, `TOKUSEI_dokusyu` 6, `TOKUSEI` 7, `ITEM` 8,
`TOKUSEI_atodasi` 9. **Kleiner = früher.** Nur drei Fähigkeiten weichen vom Standard 7 ab (`ref prio` ihrer `ADD_`-Funktion): `Dokusyu` und
`HorobiNoSango` mit 6 (vor allen anderen Fähigkeiten und Items, aber nach Attacke/Seite/Feld), `Atodasi` mit 9 (nach den Items).

### 3.3 Sortierschlüssel, Gleichstand, Einfügen [O]

- `EventFactorContainer.calcFactorPriority` [`@0x1e13230`]: `priority = ((9 - mainPri) << 24) | subPri` (32-Bit, die Unterpriorität
  belegt die unteren 24 Bit, `SUBPRI_MAX = 0xFFFFFF`). Eine **kleinere Hauptpriorität ergibt also einen größeren Schlüssel**.
- Die laufende Liste (`m_pRunningFactor @0x18`) ist **absteigend nach Schlüssel** sortiert. `addRunningFactor` [`@0x1e13860`]: ist der neue
  Schlüssel größer als der des Kopfes, kommt er an den Kopf; sonst wird weitergelaufen, solange `neu <= aktuell`, und **vor** den ersten
  Faktor mit kleinerem Schlüssel eingefügt (am Ende angehängt, wenn keiner kleiner ist). Bei **Gleichstand kommt der später Registrierte
  hinter den früher Registrierten** (Reihenfolge der Registrierung). **Es gibt keinen Zufall** bei Gleichstand.
- Die Unterpriorität ist bei Fähigkeiten, Items, Default-Powerups und Raid-Boss-Faktoren der **Basiswert Initiative des Pokémon**
  (`BTL_POKEPARAM.GetValue_Base(AGILITY)`, ohne Stufen; `Tokusei.Add @0x1a3e920`, `Item.addHandler @0x1a05870`), bei Seiten-, Positions-
  und Feldeffekten 0, bei Attacken ein vom Aufrufer gegebener Wert (`Waza.Add @0x18f9610`, aufgerufen aus `ServerCommandExecutor`/`-Putter`).
  Schnellere Pokémon sind also in jeder Gruppe früher dran. **Die Reihenfolge wird nur bei der Registrierung festgelegt**: `SetPriority`
  wird nirgends aufgerufen, spätere Initiative-Änderungen sortieren nichts um.
- Gesamtreihenfolge: Default-Powerup, Attacke, Position, Seite, Feld, Raid-Boss, Fähigkeiten mit Priorität 6, normale Fähigkeiten, Items,
  Fähigkeit mit Priorität 9 („atodasi“); innerhalb einer Gruppe nach Initiative absteigend, dann nach Registrierung.

### 3.4 Vorrat, Registrierung, Entfernen [O]

- `EventFactorContainer` [`m_factors @0x10`, `m_pRunningFactor @0x18`, `m_pStoredFactor @0x20`]: **172 Faktoren** (`FACTOR_REGISTER_MAX`;
  Konstanten: 12 je Pokémon = 72, 44 Seiteneffekte, 30 Positionseffekte, 10 Feld, 16 Reserve) werden im Konstruktor
  einmal angelegt [`@0x1e13270`, `createFactors @0x1e13390`] und der Reihe nach in die „gelagerte“ Liste gestellt (`storeFactor
  @0x1e13520`: Faktor aus seiner Liste lösen, `Clear`, an den **Kopf** der gelagerten Liste). Die Instanz-IDs werden daher **von oben
  nach unten** vergeben: der erste Faktor ist Nr. 171, der zweite 170, …; ein freigegebener Faktor wird als Nächster wiederverwendet.
- `AddFactor` [`@0x1e13ab0`, Parameter: Typ, subID, Hauptpriorität, Unterpriorität, dependID, Tabelle, Anzahl, Ereignisstufe]:
  nimmt den Kopf der gelagerten Liste (**leer: Rückgabe null, es wird nichts registriert**), setzt alle Felder, `existFlag = 1`,
  `pokeID = dependID` nur für Typ WAZA/TOKUSEI/ITEM (`isDependPokeFactorType @0x1e13240`), sonst 0x1F, und sortiert ein.
- `RemoveFactor` [`Container @0x1e13c40`]: Kopf der laufenden Liste nachziehen, `storeFactor`. `EventSystem.RemoveFactor` [`@0x19f4780`]
  entfernt **nur existierende** Faktoren; läuft der Faktor gerade (`callingFlag`), wird er nur zum Entfernen **vorgemerkt**
  (`rmReserveFlag`) und nach seinem Handler entfernt (Abschnitt 5.2). `RemoveIsolateFactors` [`@0x19f4800`] entfernt alle Faktoren vom Typ
  ISOLATE (`ConvertForIsolate @0x1e0a490` setzt den Typ; gerufen von Fähigkeits-/Attacken-Handlern; aufgeräumt in `Section_TurnEnd`).
- Suchen: `SeekFactor(typ)` [`@0x1e13c90`] / `SeekFactor(typ, dependID)` [`@0x1e13cd0`]: erster **existierender** Faktor ohne Löschvormerkung;
  `GetNextFactor(f, beliebigeDependID)` [`@0x1e13d20`]: nächster Faktor gleichen Typs ohne Löschvormerkung (mit gleicher dependID, wenn
  nicht „beliebig“). `SwapFactorsSideEffect` [`@0x1e13db0`] tauscht bei allen SIDE-Faktoren einer Seiteneffekt-Nr. die beiden Seiten.
  `Clear`/`CopyFrom`/`storeAllRunningFactor` (`@0x1e139f0/0x1e135f0/0x1e13a50`) kopieren den Zustand für Simulationen (`BattleEnv`); nicht umgesetzt.
- Schlafen: `SleepFactors(pokeID, typ)` [`@0x19f48c0`] setzt `sleepFlag` bei allen Faktoren des Pokémon und Typs, `WakeFactors` [`@0x19f4940`]
  hebt es auf, `WakeAllFactors` [`@0x19f49c0`] bei allen. Schlafende Faktoren werden nicht aufgerufen.

### 3.5 Wer registriert was [P, Tabelle der Parameter aus den `Add`-Funktionen]

| Handler-Klasse | Faktortyp | Hauptpriorität | subID | dependID | Besonderheiten | Beleg |
|---|---|---|---|---|---|---|
| `Handler.Tokusei` | TOKUSEI | 7 (6/9 für 3 Fähigkeiten) | Tokusei-Nr. | Pokémon-ID | `Remove`: solange Arbeitswert 4 = 0; `Swap` entfernt und registriert neu | `Add @0x1a3e920`, `Remove @0x1a3ea40`, `Swap @0x1a3eae0` |
| `Handler.Item` | ITEM | 8 | Item-Nr. | Pokémon-ID | direkter Container-Aufruf mit Ereignisstufe; `Remove`: Arbeitswert 6 = 0 | `addHandler @0x1a05870`, `Remove @0x1a05a10` |
| `Handler.Waza` | WAZA | 1 | Attacken-Nr. | Pokémon-ID | verweigert Doppelte; höchstens 8 Attacken-Faktoren je Pokémon geprüft | `Add @0x18f9610`, `Remove @0x18f9840` |
| `Handler.Side` | SIDE | 3 | Seiteneffekt-Nr. | Seite | keine Doppelten je Seite; Arbeitswerte 5/6 = Dauer (`SICKCONT.Split32bit`) | `Add @0x1a386c0`, `Remove @0x1a38a90` |
| `Handler.Pos` | POS | 2 | Positionseffekt-Nr. | Position | nur wenn `isRegistable`; Arbeitswerte aus Parameterfeld, Arbeitswert 6 = Parameter | `Add @0x1a35980`, `Remove @0x1a35d50` |
| `Handler.Field` | FIELD | 4 | Feldeffekt-Nr. (`EffectType`, auch Wetter) | Parameter | direkter Container-Aufruf mit Ereignisstufe | `Add @0x1a01e60`, `Remove @0x1a021e0` |
| `Handler.DefaultPowerUp` | DEFAULT_POWERUP | 0 | Grund der Verstärkung | Pokémon-ID | direkter Container-Aufruf mit Ereignisstufe; Unterpriorität = Initiative | `Add @0x1a01620`, `Remove @0x1a01970` |
| `Handler.RaidBoss` | RAIDBOSS | 5 | wie übergeben | Pokémon-ID | Unterpriorität = Initiative; `canAdd` prüft vorher | `Add @0x1a37a90`, `Remove @0x1a37f00` |

Jede dieser Klassen hat eine `GET_FUNC_TABLE` (Nr. → `HandlerGetFunc`) und je Handler-Satz eine statische Tabelle
`HandlerTable_*` (Ereignis → Handler-Methode). Die `ADD_*`-Funktionen liefern nur diese Tabelle (Tokusei/Waza dazu optional eine geänderte
Hauptpriorität).

## 4. Aufruf-Schleife

### 4.1 Aufrufarten [O]

- `CallEvent(id)` [`EventSystem.CallEvent @0x19f4a00`] ruft **alle** Typen mit Überspring-Prüfung. `CallEvent_Force(id)` [`@0x19f4ba0`]
  dasselbe **ohne** Überspring-Prüfung. `CallEvent_TargetType(id, typ)` [`@0x19f4c70`] nur Faktoren dieses Typs, mit Prüfung.
  `callEventCore @0x19f4ad0` und `notifyHandlers @0x19f4d40` sind Varianten derselben Schleife.
- Ablauf: Aufruftiefe `m_eventLevel @0x58` um 1 erhöhen, die laufende Liste vom Kopf an durchgehen (5.2), Tiefe um 1 senken; fällt sie auf 0,
  wird bei **allen** Faktoren die Ereignisstufe auf 0 zurückgesetzt (`SetEventLevel(0)`).
- Die Schleife merkt sich **vor** dem Handler den Nachfolger des Faktors. Ist dieser danach nicht mehr vorhanden (vom Handler entfernt), wird
  der **aktuelle** Nachfolger des Faktors genommen. Dadurch dürfen Handler beliebige Faktoren entfernen, ohne die Schleife zu zerstören.

### 4.2 Reihenfolge der Prüfungen je Faktor (`nofityHandler @0x19f4dd0`) [O]

Ein Faktor wird **übersprungen** (der Nachfolger wird zurückgegeben), wenn der erste der folgenden Punkte zutrifft:

1. er läuft gerade (`callingFlag`) und hat keine Wiedereintritts-Erlaubnis (`recallEnableFlag`);
2. er schläft (`sleepFlag`);
3. der Aufruf ist auf einen Typ beschränkt und der Faktor hat einen anderen;
4. seine Ereignisstufe ist ≠ 0 und die aktuelle Aufruftiefe ist **kleiner oder gleich** dieser Stufe (4.3);
5. er existiert nicht (`existFlag == 0`);
6. das Ereignis ist `USE_ITEM_TMP` (142) und der Faktor hat nicht das `tmpItemFlag` (`SetTmpItemFlag @0x1e12840`);
7. `numHandlers == 0`.

Danach wird die Tabelle durchsucht: **nur der erste Eintrag mit passender Ereignis-ID wird ausgeführt**; weitere Einträge derselben
ID im selben Faktor bleiben unbeachtet. Gibt es keinen, ist der Faktor erledigt. Bei Aufrufen mit Prüfung kommt jetzt `checkHandlerSkip` (5.3).

Dann: `callingFlag` setzen, `EventHandlerArgs` bauen (Referenz auf EventSystem, aktuellen Variablensatz `pEventVar`, eigenen Faktor,
dazu Kampfumgebung) und `handler(args, dependID)` aufrufen. **Nachlauf:** hatte der Handler `SetRecallEnable` gesetzt
(`@0x1e0a400`, wirkt nur während des Laufs), wird nur diese Erlaubnis zurückgenommen und `callingFlag` bleibt; sonst wird `callingFlag`
gelöscht. Ist `rmReserveFlag` gesetzt, wird – sofern der Faktor noch existiert und nicht mehr läuft – `RemoveFactor` ausgeführt (läuft er
noch, bleibt die Vormerkung). Der zurückgegebene Nachfolger wird dabei auf den nächsten **existierenden** Faktor vorgeschoben.

### 4.3 Rekursion und Ereignisstufe [O]

- **Rekursion:** Ruft ein Handler während seiner Ausführung wieder dasselbe Ereignis (oder ein anderes, das ihn betrifft), wird sein
  Faktor dabei übersprungen (Punkt 1) – außer er hat vorher `SetRecallEnable` gesetzt; dann läuft er einmal verschachtelt, und die Erlaubnis
  verfällt nach dem inneren Lauf.
- **Ereignisstufe:** `EventSystem.AddFactor` [`@0x19f4740`] gibt dem Container die **aktuelle Aufruftiefe** als Stufe des neuen Faktors mit (aus
  der Disassemblierung); der Container-Aufruf von `Handler.Item`/`Handler.Field` ebenso. Ein **während eines Aufrufs** der Tiefe *t*
  registrierter Faktor reagiert nicht auf diesen Aufruf und nicht auf verschachtelte Aufrufe bis zur Tiefe *t* (Punkt 4), wohl aber auf
  tiefere; sobald der äußerste Aufruf endet, gilt für alle wieder Stufe 0. Ausserhalb von Aufrufen (Tiefe 0) reagiert er sofort.

### 4.4 Überspringen (`checkHandlerSkip @0x19f5140`) [OK]

Berechnet vor jedem Handler, ob er unterdrückt wird (nur bei `CallEvent`/`CallEvent_TargetType`):

1. **Tokusei-Faktoren** (Pokémon vorhanden): überspringen, wenn das Pokémon den Zustand `WAZASICK_IEKI` (16, Fähigkeit ausser Kraft) hat,
   die Fähigkeit durch das Feld „Chemisches Gas“ wirkungslos ist (`IsTokuseiDisabledByKagakuHenkaGas`), oder (verwandelt und die
   Fähigkeit steht in der Auslassungstabelle `tables.CheckOmmitAfterHensin @0x2079980`) oder (im G-Modus und `CheckOmmitOnG @0x2079a30`).
2. **Item-Faktoren** (Ereignis ≠ `MEMBER_IN_EVO` 208): überspringen bei aktivem Feldeffekt 5 (Magieraum), beim Zustand `WAZASICK_SASIOSAE` (19,
   Item gesperrt) oder bei gesetztem Zug-Flag 9 (`TURNFLG_ITEM_CANT_USE`).
3. **Überspring-Handler anderer Faktoren:** jeder nicht schlafende Faktor mit `skipCheckHandler` (Fähigkeiten, die gerade ausser Kraft
   sind, zählen nicht) bekommt Ereignis, Typ, subID und dependID des geprüften Faktors; antwortet einer mit „ja“, wird übersprungen
   (so wirken Fähigkeiten, die Handler anderer ignorieren). `Attach/DetachSkipCheckHandler @0x1e0a0b0/0x1e0a0e0`.

## 5. Handler-Typen und Beispiele

Handler haben die Signatur `Handler(args, dependID)`. Über die Hilfsfunktionen der Klasse `Common` (188 Funktionen im Export) lesen sie Variablen
(`GetEventVar @0x1e09be0` = `EVENTVAR_GetValue`, `MulEventVar @0x1e09cc0`, `RewriteEventVar @0x1e09c90`), greifen auf Pokémon zu
(`GetPokeParam @0x1e09e40` über `BattleEnv.m_pokecon`) und lösen Wirkungen aus (`Damage`, `RankEffect`, `AddSick`, `ChangeWeather`, … über die
56 `Section_FromEvent_*`-Klassen). Die Wirkungsseite ist nicht Teil dieser Scheibe; hier zählt das Lesen/Ändern von Variablen.

| Handler-Typ (Faktortyp) | Zahl im Original (Abschnitt 10) | Typische Ereignisse (häufigste) |
|---|---|---|
| Fähigkeit (`Handler.Tokusei`) | 222 Tabellen / 383 Handler-Funktionen | 172 `CHANGE_TOKUSEI_AFTER`, 108 `MEMBER_IN`, 70 `WAZA_POWER`, 95 `WAZA_DMG_REACTION`, 74 `ATTACKER_POWER` |
| Item (`Handler.Item`) | 193 / 285 | 70 `WAZA_POWER`, 142 `USE_ITEM_TMP`, 141 `USE_ITEM`, 180 `CHECK_ITEM_REACTION`, 95, 108 |
| Attacke (`Handler.Waza`) | 262 / 412 | 34 `WAZA_EXECUTE_CHECK_3RD`, 196 `UNCATEGORIZE_WAZA`, 69 `WAZA_POWER_BASE`, 33, 197 |
| Seite (`Handler.Side`, Schutzwände, Fallen, Rückenwind) | 22 / 29 | 108 `MEMBER_IN`, 51, 90, 145 `TURNCHECK_BEGIN` |
| Feld (`Handler.Field`, Wetter, Räume, Gravitation) | 13 (davon 5 Platzhalter mit Ereignis 0) / 12 | 0, 33, 78, 79 |
| Position (`Handler.Pos`, Wunschtraum, Heilopfer, Vorhersage) | 5 / 5 | 108, 145, 200 |
| Default-Powerup / Raid-Boss | 1 / 1 und 1 / 2 | 106; 3, 4 |
| Status/Sick | kein Faktortyp (3.2) | Ereignisse 121–130 werden von Fähigkeiten/Items/Attacken bedient |

Beispiele aus dem Pseudocode (alle als Minimalsatz umgesetzt, Abschnitt 8):

- **Kraftkoloss** `handler_Tikaramoti @0x1a3f7b0` an Ereignis 74: Wenn `POKEID_ATK` der Besitzer ist und `DAMAGE_TYPE` = 1 (physisch), `RATIO *= 0x2000`.
- **Dickes Fell** `handler_AtuiSibou @0x1a3f640` an 74: Wenn `POKEID_DEF` der Besitzer ist und `WAZA_TYPE` Feuer (9) oder Eis (14), `RATIO *= 0x800`.
- **Facettenauge** `handler_Fukugan @0x1a40a00` an 64: Wenn `POKEID_ATK` der Besitzer ist, `RATIO *= 0x14CD`.
- **Techniker** `handler_Technician @0x1a43500` an 70: Wenn `POKEID_ATK` der Besitzer ist und `WAZA_POWER` < 0x3D (61), `WAZA_POWER_RATIO *= 0x1800`.
- **Items** nutzen den „Angriffswert“ des Items aus den Spieldaten: `Item.item_AttackValue_to_Ratio @0x1a05d30`: `ratio = (int)((float)(w + 100) * 4096 + 0,5) / 100`
  (bei `w + 100 < 1` mit −0,5), z. B. 10 → 4505 (0x1199), 30 → 5324 (0x14CC). Auf dieser Funktion beruhen `KoukakuLens` (Ereignis 64),
  `MonosiriMegane` (70, nur `DAMAGE_TYPE` 2, Variable `WAZA_POWER_RATIO`), `TatsujinNoObi` (90, nur `TYPEAFF` > 7) und `InochiNoTama_Damage` (90).
  `KodawariHachimaki_Pow @0x1a12600` an 74: Besitzer ist Angreifer, nicht G-Modus, physisch → `RATIO *= 0x1800`.

## 6. Das Pokémon im Kampf (BTL_POKEPARAM) [P, soweit das Ereignissystem es braucht]

`BTL_POKEPARAM` [`dump.cs`, 0x10-Köpfe]: `m_coreParam @0x10` (Kern), `m_baseParam @0x18`, `m_varyParam @0x20` (Stufen), `m_doryokuParam @0x28`,
`m_waza @0x30`, `m_tokusei @0x38`, `m_turnFlag @0x58`, `m_contFlag @0x60`, `m_permFlag @0x68`, `m_counter @0x70`, `m_migawariHP @0x92`, `m_fldSim @0xA0`
(Feldzustand für Wonder-Room-/Gas-Prüfungen).

- **Kern** (`CORE_PARAM`): `hpMax @0x24`, `hp @0x26`, `item @0x28`, `level @0x2E`, `myID @0x2F`, `sickCont @0x48` (Array `BTL_SICKCONT`, `CheckSick(id)`
  = `(sickCont[id] & 7) != 0` [`@0x20d8b30`]), `fHensin @0x3C` (verwandelt, `HENSIN_Check @0x20dd470`), `gParam @0x88` (G-Modus, `IsGMode @0x20db9a0`).
- **Basiswerte** (`BASE_PARAM`): `attack @0x14`, `defence @0x16`, `sp_attack @0x18`, `sp_defence @0x1A`, `agility @0x1C`; Typen `type1 @0x1E`, `type2 @0x1F`,
  `type_ex @0x20` (18 = kein Typ); `IsMatchType @0x20dfad0`: Typ 18 passt nie, sonst Typ 1, 2 oder Zusatztyp.
- **Stufen** (`VARIABLE_PARAM`, `sbyte`, tatsächlich im Bereich 0..12, 6 = neutral): Angriff, Abwehr, Sp.-Angriff, Sp.-Abwehr, Initiative, Genauigkeit,
  Fluchtwert (`@0x10..0x16`). `GetValue(id)` [`@0x20dd010`]: ID 1–7 liefert die Stufe selbst, 8–12 `calc.StatusRank(Basiswert, Stufe)` (Scheibe 1, Abschnitt 5.3);
  `GetValue_Base(id)` [`@0x20dd9e0`] den Wert ohne Stufen (Treffer/Flucht → 6); `GetValue_Critical` [`@0x20dfc50`]: bei Volltreffer zählt eine
  Angriffsstufe < 6 und eine Abwehrstufe > 6 nicht (Basiswert). Wonder-Room-Tausch der Abwehrwerte ist **nicht** umgesetzt (offen).
- **Flags:** `TURNFLAG_Get(f)` [`@0x20dfe70`] liest Bit `f & 7` im Byte `f >> 3` des Arrays `m_turnFlag` (27 Flags, z. B. 9 `ITEM_CANT_USE`, 14 `HITRATIO_UP`);
  Dauer-/Permanentflags entsprechend.
- **ValueID** (`BTL_POKEPARAM.ValueID`): 1–5 Stufen, 6/7 Treffer/Flucht, 8–12 Kampfwerte, 13 HP, 15 MaxHP, 17 Level, 18 Tokusei, 19 wirksames Tokusei (0, wenn
  durch `IEKI`/Gas ausser Kraft), 20 Geschlecht.

C#-Entsprechung: `BattlePoke` (Id, Level, Hp/MaxHp, Item, Tokusei, Typen, Basiswerte, sieben Stufen, Sick-Container (64 Dauer-Typen), Zug-Flags, G-Modus,
Verwandlung, Gas-Flag) mit `GetValue`, `GetValueBase`, `GetValueCritical`, `CheckSick`, `GetTurnFlag`, `IsMatchType`. Die Kampfumgebung
(`IEventBattleEnv`) liefert `GetPoke(id)`, `IsFieldEffectActive(effekt)`, die beiden Auslassungstabellen und den Item-Angriffswert.

## 7. Aufruf-Code des Kampfs (EventLauncher) und Anschluss an Scheibe 1 [P]

`EventLauncher` [176 Funktionen im Export] schnürt je Rechenschritt einen Rahmen: `Push`, Eingaben als Variablen, `CallEvent`, Ergebnis lesen, `Pop`.
Die Schritte, die die Rechner aus Scheibe 1 speisen:

| Schritt (Funktion) | Rahmen und Ereignisse | Ergebnis |
|---|---|---|
| Kraft (`Event_getWazaPower @0x1e14e20`) | konst. `POKEID_ATK/DEF`, `WAZAID`, `WAZA_TYPE`, `DAMAGE_TYPE`, `WAZA_TOUCH_FLAG`; einmal umschreibbar `WAZA_POWER` = Grundkraft; Ereignis 69; `WAZA_POWER_RATIO` (0x1000, `[0x29, 0x200000]`); Ereignis 70 | `MulRatio(Kraft, Verhältnis)` |
| Angriff (`Event_getAttackPower @0x1e15010`) | Rahmen 1: Ereignis 71 (darf `SWAP_POKEID` und `GEN_FLAG` = Stufen ignorieren setzen); innerer Rahmen: Ereignis 73 (darf Wertart `VID` ändern); weiter in Rahmen 1: `POWER` = Wert (bei Volltreffer: Stufe < 6 → Basiswert), `RATIO` (0x1000, `[0x19A, 0x20000]`), Ereignis 74 | `MulRatio(Wert, Verhältnis)` + Flag „Brand ignorieren“ |
| Abwehr (`Event_getDefenderGuard @0x1e153d0`) | Rahmen: `VID` = Standardwert, Ereignis 72 (Tausch der Wertart, Stufen ignorieren); `GUARD`, `RATIO`, Ereignis 75; Sandsturm: Gestein-Ziel ×0x1800 auf die Sp.-Abwehr | `MulRatio(Wert, Verhältnis)` |
| Gleichtyp-Bonus (`Event_CalcTypeMatchRatio @0x1e15740`) | `GEN_FLAG` = passt?, Ereignis 83, `RATIO` = 0x1800/0x1000, Ereignis 84 | Verhältnis |
| Trefferwahrscheinlichkeit (`Event_getHitPer @0x1e16a30`, aus `Event_CheckHit @0x1e19350` mit Ereignis 64) | `HIT_PER` einmal umschreibbar = Genauigkeit; `RATIO` (0x1000, `[0x19A, 0x20000]`) | `MulRatio(Genauigkeit, Verhältnis)` = `HitInput.HitPercent` |
| Trefferstufen (`Event_CheckHit`) | `FLAT_FLAG`, `HIT_RANK` = Stufe Angreifer, `AVOID_RANK` = Stufe Ziel, `RATIO` (0x1000, `[0x29, 0x20000]`); Ereignis 63 | Stufen, Flag, Verhältnis = `HitInput` |
| Endfaktor (`Event_CalcDamage @0x1e14710`, Ereignis 90) | `TYPEAFF`, `CRITICAL_FLAG`, `WAZA_TYPE`, …; `RATIO` (0x1000, `[0x29, 0x20000]`), `DAMAGE` = Schaden bisher; Ereignis 90 | Verhältnis = `DamageInput.FinalRatio` |

C#: `BattleEventLauncher` (`GetWazaPower`, `GetAttackPower`, `GetDefenderGuard`, `CalcTypeMatchRatio`, `GetHitPer`, `BuildHitInput`,
`GetFinalDamageRatio`, `BuildDamageInput`) setzt dasselbe in einem `EventSystem` um und liefert fertige `HitInput`/`DamageInput` für die Rechner aus
Scheibe 1. **Einzige Änderung am Scheibe-1-Code:** `DamageInput.FinalRatioFunc` (optional; hat Vorrang vor `FinalRatio`), weil der Endfaktor den
Schaden vor der letzten Stufe kennen muss (`DamageCalculator.Calc` ruft die Funktion mit dem Zwischenwert auf). Alle Scheibe-1-Tests bleiben grün.
Nicht umgesetzt: Festschaden-Ereignisse 87–89 und die G-Modus-/Raid-Ereignisse 91/92 innerhalb von `Event_CalcDamage`.

## 8. Minimalsatz echter Handler (Beweis des Konzepts)

| Handler | Nr. | Ereignis | Wirkung | Beleg | Stufe | Umfang |
|---|---|---|---|---|---|---|
| Kraftkoloss | Tokusei 37 | 74 | physischer Angriff ×2 | `handler_Tikaramoti @0x1a3f7b0` | [O] | vollständig |
| Dickes Fell | Tokusei 47 | 74 | Feuer/Eis gegen den Besitzer ×0,5 | `handler_AtuiSibou @0x1a3f640` | [O] | vollständig |
| Facettenauge | Tokusei 14 | 64 | Genauigkeit ×0x14CD | `handler_Fukugan @0x1a40a00` | [O] | vollständig |
| Techniker | Tokusei 101 | 70 | Kraft < 61 ×1,5 | `handler_Technician @0x1a43500` | [O] | vollständig |
| Wahlband | Item 220 | 74 | physischer Angriff ×1,5 (nicht im G-Modus) | `handler_KodawariHachimaki_Pow @0x1a12600` | [O] | nur Tabelleneintrag 74; die Sperr-Logik (36/192/222) fehlt |
| Weitwinkellinse | Item 265 | 64 | Genauigkeit gemäß Item-Wert | `handler_KoukakuLens @0x1a10d30` | [O] | vollständig |
| Schlauglas (Wise-Glasses-Item) | Item 267 | 70 | spezielle Kraft gemäß Item-Wert | `handler_MonosiriMegane @0x1a11a80` | [O] | vollständig |
| Expertengurt | Item 268 | 90 | Endschaden bei Wirkung > normal gemäß Item-Wert | `handler_TatsujinNoObi @0x1a13910` | [O] | vollständig |
| Lebensorb | Item 270 | 90 | Endschaden gemäß Item-Wert | `handler_InochiNoTama_Damage @0x1a13cf0` | [O] | nur Schadensteil; Rückstoß (Ereignis 164) fehlt |

Registrierung: `TokuseiHandlers.Add/Remove/Swap`, `ItemHandlers.Add/AddHandler/Remove` setzen `Tokusei.Add`/`Item.addHandler`/`Item.Remove` um (3.5).

## 9. Verifikation (Orakel)

### 9.1 Aufbau

`scripts/battle_oracle_heap.py` (Aufruf `PYTHONPATH=tools/pydeps python3 scripts/battle_oracle_heap.py`) erweitert das Orakel von Scheibe 1:

- **Gast-Heap-Helfer:** `DumpTypes`/`GuestHeap` lesen Feldnamen und Offsets aus `dump.cs` und legen Objekte (Container, `EventSystem`, `BattleEnv`,
  `FieldStatus`, Pokémon-Platzhalter, Handler-Tabellen) mit genullten Blöcken im Gastspeicher an; der Heap wird zwischen Szenarien zurückgesetzt.
- **IL2CPP-Stubs:** Klasseninitialisierung (`FUN_00364fe0`), Schreibbarrieren, Objekt-/Array-Allokation (`FUN_00366700`, `FUN_003afb00`), Typprüfung beim
  Array-Setzen; Ausnahmen (`FUN_0035c83c/0035cda0/003afbc0`) beenden die Emulation mit einem Fehler (kein stilles Weiterlaufen).
- **Delegat-Aufrufe:** `EventHandler.Invoke @0x1e12b80` und `SkipCheckHandler.Invoke @0x1e12f40` sind „yield“-Stubs: die Emulation hält an, der Handler läuft
  als Python-Funktion oder als **echte Gastfunktion** (verschachtelter Lauf auf eigenem Stack) und setzt danach fort. So können Handler Faktoren entfernen,
  hinzufügen, verschachtelt aufrufen – alles mit den echten `EventSystem`-Funktionen.
- **Pokémon-Abfragen** (`POKECON.GetPokeParam`, `CheckSick`, `TURNFLAG_Get`, `IsGMode`, `HENSIN_Check`, Auslassungstabellen, `ITEM_GetParam`) sind Stubs mit
  Testwerten (daher [OK] bei `checkHandlerSkip` und den Handlern, die Pokémon abfragen).
- **Methodenzeiger-Slots:** jeder Metadaten-Methoden-Slot (24020) zeigt auf einen Datensatz mit der Methodenadresse. Damit lassen sich die **echten `.cctor`
  der Handler-Klassen** ausführen, deren Pseudocode im Export fehlt (Decompiler-Timeout bei `Tokusei`/`Item`/`Waza`): die Tabellen Ereignis → Handler-Funktion
  werden aus dem Gastspeicher gelesen (`--tables`).

### 9.2 Fixtures (`unity/Assets/Tests/EditMode/Fixtures/`, nur Zahlen, seedbasiert)

| Datei | Inhalt | Umfang |
|---|---|---|
| `BattleEventsVar.json` | zufällige Operationsfolgen gegen die echten `EVENTVAR_*`-Funktionen: Rückgaben, beide Stapelzeiger, Slot-Inhalt am Ende | 70 Fälle, 3329 Operationen |
| `BattleEventsOrder.json` | `AddFactor`/`RemoveFactor` mit Prioritäten/Gleichstand, Instanz-IDs, Vorrat, `Seek`/`GetNext` | 61 Fälle, 1113 Faktoren, 240 Suchen, Pool-Erschöpfung (172) |
| `BattleEventsCall.json` | `CallEvent`/`Force`/`TargetType` mit Handlern, die sich/andere entfernen, Faktoren hinzufügen, rekursiv aufrufen, Variablen ändern, Wiedereintritt erlauben, schlafen lassen, Skip-Regeln; Protokoll aller Handleraufrufe (Ereignis, Instanz, dependID, Tiefe), Endzustand | 160 Fälle, 1729 Handleraufrufe |
| `BattleEventsHandlers.json` | die 9 echten Handler (Tabelle in Abschnitt 8) im echten Ereignissystem mit zufälligen Variablen; dazu `item_AttackValue_to_Ratio` (echter Gleitkomma-Code) | 720 Fälle (627 mit Aufruf), 1050 Verhältniswerte |

Die Unity-Tests (`BattleEvents*Tests.cs`) führen dieselben Szenarien gegen die C#-Umsetzung aus und prüfen jedes Protokoll, jede Faktorenliste,
jeden Slot und alle Stapelzeiger auf Gleichheit. Dazu kommen Handrechnungen (Prioritätsschlüssel, Reihenfolge, Rekursion/Recall, Ereignisstufe, Skip-Regeln,
Treffer-/Schadensverdrahtung). Python-Tests: `scripts/tests/test_battle_oracle_heap.py` (Parser, Heap, Zusammenfassung; mit Unicorn zusätzlich echte Emulationsproben).

### 9.3 Was nicht trägt (und wie getestet wird)

- **`EventLauncher`-Funktionen** (`Event_getHitPer`, `getWazaPower`, `getAttackPower`, `getDefenderGuard`, `CalcTypeMatchRatio`) und **`BTL_POKEPARAM.GetValue`**
  laufen nicht im Orakel: sie hängen an `BTL_POKEPARAM`, `WAZADATA`, `Section*` und `MainModule`, deren Objektgraphen sich nicht sinnvoll synthetisch
  aufbauen lassen, ohne weite Teile des Spiels zu stubben (die Ergebnisse wären dann nur Testeingaben). Stattdessen: Pseudocode-Analyse (Abschnitt 7) plus
  handgerechnete Beispiele im Test (z. B. Facettenauge: 70 × 0x14CD → 91; Weitwinkellinse (Wert 10) → 77; beide → 100; Kraftkoloss: Angriff 100 → 200;
  Stufen −3/+3 → 40/250; Sandsturm: Sp.-Abwehr 100 → 150).
- **`checkHandlerSkip`** ist [OK], nicht [O]: die Pokémon-Abfragen sind Stubs; die Entscheidungslogik ist echt.
- **Handler mit Wirkungen** (Schaden, Statuswerte, Meldungen) brauchen die `Section`-Ebene und liegen ausserhalb dieser Scheibe.

## 10. Offenes und Aufwand

### 10.1 Zählung der Handler-Klassen (aus den echten `.cctor`, `--tables`; Handler-Funktionen = verschiedene Funktionen in den Tabellen)

| Typ | Tabellen (≈ Fähigkeiten/Items/Attacken/Effekte) | Tabelleneinträge | Handler-Funktionen | Zeilen Pseudocode (Handler-Funktionen) | Funktionen ≤ 30 / 31–60 / 61–120 / > 120 Zeilen |
|---|---|---|---|---|---|
| Tokusei | 222 | 461 | 383 | 13 666 | 184 / 160 / 36 / 3 |
| Item | 193 | 437 | 285 | 9 139 | 156 / 92 / 37 / 0 |
| Waza | 262 | 542 | 412 | 18 278 | 124 / 206 / 75 / 7 |
| Side | 22 | 32 | 29 | 1 492 | 9 / 9 / 11 / 0 |
| Field | 13 | 18 | 12 | 282 | 8 / 4 / 0 / 0 |
| Pos | 5 | 7 | 5 | 366 | 0 / 3 / 2 / 0 |
| DefaultPowerUp | 1 | 1 | 1 | 4 | 1 / 0 / 0 / 0 |
| RaidBoss | 1 | 2 | 2 | 69 | 0 / 2 / 0 / 0 |
| **Summe** | **719** | **1 500** | **1 129** | **43 296** | |

Zahl der `ADD_*`-Funktionen im Export (= Tabellen mit Handler): Tokusei 222, Item 193, Waza 262, Side 22, Field 11, Pos 5. Insgesamt hat der Export 670 (Tokusei),
532 (Item), 744 (Waza), 62 (Side), 39 (Field), 21 (Pos), 7 (DefaultPowerUp), 8 (RaidBoss) Funktionen in den Handler-Klassen (Hilfsfunktionen eingeschlossen).
Verschiedene Ereignisse mit mindestens einem Handler: 194 von 229. Häufigste Ereignisse über alle Typen: 70 (98 Einträge), 34 (85), 196 (81), 108 (70),
142 (56), 95 (55), 141 (51), 172 (42), 90 (42), 180 (31).

**Umgesetzt:** 4 von 222 Fähigkeiten, 5 von 193 Items (davon 2 teilweise), 0 von 262 Attacken, 0 Seiten-/Feld-/Positionseffekte.

### 10.2 Aufwand für den Rest (Schätzung aus den Zahlen)

- Handler bis 60 Zeilen Pseudocode (Tokusei 344, Item 248, Waza 330, Seite 18, Feld 12) sind überwiegend „Variable lesen, vergleichen, `MulEventVar`/`RewriteEventVar`“
  und lassen sich nach dem Muster aus Abschnitt 5/8 je in Minuten umsetzen und mit dem Orakel prüfen (das Orakel führt dieselbe Funktion ohne Zusatzarbeit aus,
  solange sie nur `GetEventVar`/`MulEventVar`/`RewriteEventVar`/Pokémon-Lesezugriffe nutzt).
- Handler mit **Wirkung** (Schaden, Statuswerte, Zustände, Wetter, Item-Verbrauch, Meldungen) brauchen zusätzlich die `Common.*`-Wirkungs-API und die 56
  `Section_FromEvent_*`-Klassen – das ist der Hauptaufwand und gehört in die nächsten Scheiben (Ablauf/Sections).
- Größte Handler (> 120 Zeilen): Tokusei 3 (größter 339 Zeilen), Waza 7 (größter 171), Item 0, Side 0.

### 10.3 Reihenfolge-Priorität (Empfehlung)

1. **Wirkungs-API + Sections** (`Common.*`, `Section_FromEvent_*`) – ohne sie bleiben Handler wirkungslos.
2. **Schaden/Treffer-Handler** (Ereignisse 63/64/69/70/74/75/83/84/90): Fähigkeiten und Items mit direkter Wirkung auf Kraft, Angriff, Abwehr, Genauigkeit,
   Gleichtyp, Endschaden (≈ 98 Einträge für 70, 24 für 74 …); sie schließen den Rechenpfad aus Scheibe 1.
3. **Einwechsel-/Rundenende-Handler** (108 `MEMBER_IN`, 145 `TURNCHECK_BEGIN`, 223 `TURN_END`, 172 `CHANGE_TOKUSEI_AFTER`): Fähigkeiten wie Bedroher, Wetter-Fähigkeiten,
   Item-Heilungen; dazu Seiten-/Feld-/Positionseffekte (Wetter, Schutzwände, Fallen: zusammen nur 40 Funktionen).
4. **Items 141/142/180** (Verbrauch, Beeren): erst nach Item-Verbrauch/`UseItem`.
5. **Attacken-Handler** (262 Tabellen, die meisten an 34/196/69): zuletzt, größte Menge, abhängig von allem Obigen.

### 10.4 Weitere offene Punkte

- `BTL_POKEPARAM`: Wonder-Room-Tausch, Verwandlung, G-Modus-Werte, Fluchtwert/Treffer-Flags weiterer Zustände, Sick-Container mit Dauer/Zähler (nur der Dauer-Typ für `CheckSick`).
- `EventFactorContainer.CopyFrom/Clear` (Zustandskopie für KI-Simulation) und die Quelle der Attacken-Unterpriorität (`Waza.Add`-Parameter 4 aus den Server-Kommandos).
- Wirkung von `Handler.Pos.isRegistable`, Arbeitswert-Konventionen je Handler (Index 0–6) und die Rolle des Faktor-Typs ISOLATE im Rundenende-Ablauf.
- `EventSystem`-Rückgaben an `BattleEnv` (z. B. `Section`-Weitergabe über `EventHandlerArgs`): Die C#-Argumentklasse trägt nur Kampfumgebung, EventSystem, Variablensatz und Faktor.

## 11. Reproduktion

```
PYTHONPATH=tools/pydeps python3 scripts/battle_oracle_heap.py              # Fixtures neu erzeugen (ca. 2 Minuten)
PYTHONPATH=tools/pydeps python3 scripts/battle_oracle_heap.py --tables      # Handler-Tabellen (work/battleevents/handler_tables.json)
PYTHONPATH=tools/pydeps python3 -m unittest scripts.tests.test_battle_oracle_heap
cd work/dotnet-battleevents && dotnet test                                  # C#-Tests ohne Unity-Editor (Wegwerfprojekt)
```
