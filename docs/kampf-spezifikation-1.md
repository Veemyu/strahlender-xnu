# Kampfmathematik, Scheibe 1: Spezifikation

Stand: Zwischenstand Scheibe 1 (nur reine Kampfmathematik, ohne Rendering, ohne Sound).
Diese Datei ist die Spezifikation in eigenen Worten. Die C#-Umsetzung (`unity/Assets/Scripts/Battle`, Assembly
`Xnu.Battle`) ist ausschließlich aus diesem Text entstanden, nicht aus dem Pseudocode abgeschrieben.

## 0. Vorgehen und Belegkonvention

- **Quelle:** dekompilierte Funktionen des Spiel-Binaries (`work/elf/main.patched.elf`, Ghidra-Projekt `work/ghidra/bdsp`,
  Export nach `work/decomp/battle1*`), Typen und Feldoffsets aus `work/il2cpp/dump.cs`.
- **Beleg:** `[Klasse.Methode @0xADRESSE]`; die Adresse ist die Ghidra-Adresse (Il2CppDumper-RVA + 0x100000).
  Reihenfolge-Aussagen beziehen sich auf die Aufrufreihenfolge in der genannten Funktion.
- **Prüfstufe je Aussage:**
  - **[O]** durch das Emulations-Orakel bestätigt: die echte ARM64-Funktion lief in Unicorn, Eingaben und Ergebnisse stehen
    als Zahlen in `unity/Assets/Tests/EditMode/Fixtures/*.json` und werden im Unity-Test gegen die C#-Umsetzung geprüft
    (Abschnitt 9).
  - **[OK]** Orakel mit ersetzten Zustandsfunktionen (Verbund-Orakel): die echte Rumpffunktion lief, aber Spielzustand und
    Handler (Fähigkeiten, Items, Attacken) wurden durch Testeingaben ersetzt.
  - **[P]** nur aus dem Pseudocode gelesen und mit handgerechneten Beispielen getestet.
- Interne Namen der Originalklassen (japanische Kürzel wie `Seikaku` = Wesen, `Sakasa` = umgekehrt/Inverse Battle,
  `Koraeru` = Durchhalten, `Migawari` = Delegator) werden nur in Belegen genutzt.

## 1. Zahlenkonventionen des Originals

- Alle Kampfrechnungen laufen in **32-Bit-Ganzzahlen** (IL2CPP, ARM64). Wo eine Funktion `ushort`/`byte` zurückgibt oder
  Parameter mit `& 0xffff` maskiert, steht das unten ausdrücklich. Überläufe wickeln modulo 2^32 um (keine Prüfung).
- **Division rundet immer ab** (Ganzzahlteilung auf vorzeichenlosen Werten, wo es im Original `uint` ist).
- **Festkomma „x/4096“** (Verhältnisse): 0x1000 = 1,0; 0x1800 = 1,5; 0x2000 = 2,0; 0x0800 = 0,5; 0x0C00 = 0,75; 0x1333 ≈ 1,2.
  Die Funktion `MulRatio` multipliziert und teilt durch 4096 **mit Rundung „halb nach unten“**:
  `p = (a*b) mod 2^32; r = p >> 12; wenn (p & 0xfff) > 0x800: r += 1` [O, `calc.MulRatio @0x2074b00`]. Genau 0x800 rundet also ab.
  `MulRatio_OverZero @0x2074b20` ist dasselbe, liefert aber mindestens 1 [O].
  `MulRatioInt @0x2074bb0`: `p = (a*b) mod 2^32; r = p / 100; wenn p % 100 > 49: r += 1` (Prozent, „halb nach oben“) [O].
- **Ereignis-Variablen** (Handler-Verhältnisse, Abschnitt 5) werden anders gerundet: `EVENTVAR_MulValue` rechnet mit 64 Bit
  `v = (v * f + 0x800) >> 12` (**halb nach oben**) und klemmt das Ergebnis auf `[min, max]`, falls einer der beiden Grenzwerte
  ungleich 0 ist [P+OK, `EventSystem.EVENTVAR_MulValue @0x19f5fc0`; die Treffer-Fixtures nutzen diese Regel].
- **Typ-IDs** (`PokeType`): 0 Normal, 1 Kampf, 2 Flug, 3 Gift, 4 Boden, 5 Gestein, 6 Käfer, 7 Geist, 8 Stahl, 9 Feuer,
  10 Wasser, 11 Pflanze, 12 Elektro, 13 Psycho, 14 Eis, 15 Drache, 16 Unlicht, 17 Fee, 18 = „kein Typ“ (`NULL`) [dump.cs `PokeType`].

## 2. Typentabelle und Typenwirkung

### 2.1 Tabelle (liegt im Code, nicht im Bundle)

`Pml.Battle.TypeAffinity.TYPE_AFF_TBL` ist ein `byte[18][18]`, aufgebaut im Klassenkonstruktor
[`TypeAffinity..cctor @0x1c29e00`]. Jede Zeile kommt als Initialisierer-Blob aus den Metadaten; ich habe den echten `.cctor` in
Unicorn ausgeführt und die 18 Zeilen ausgelesen (Fixture `BattleTables.json`, `typeChart`) [O]. Zeile = Angriffstyp, Spalte =
Verteidigertyp, Werte: `0` = wirkt nicht, `2` = halber Schaden, `4` = normal, `8` = doppelter Schaden (Konstanten `x0/xH/x1/x2`).
Die Tabelle entspricht der bekannten Typentabelle ab Generation 6 (mit Fee; Geist und Unlicht sind gegen Stahl neutral).

Kodierung der 18 Zeilen (Spalten in Typ-ID-Reihenfolge 0..17):

```
Normal : 4 4 4 4 4 2 4 0 2 4 4 4 4 4 4 4 4 4
Kampf  : 8 4 2 2 4 8 2 0 8 4 4 4 4 2 8 4 8 2
Flug   : 4 8 4 4 4 2 8 4 2 4 4 8 2 4 4 4 4 4
Gift   : 4 4 4 2 2 2 4 2 0 4 4 8 4 4 4 4 4 8
Boden  : 4 4 0 8 4 8 2 4 8 8 4 2 8 4 4 4 4 4
Gestein: 4 2 8 4 2 4 8 4 2 8 4 4 4 4 8 4 4 4
Käfer  : 4 2 2 2 4 4 4 2 2 2 4 8 4 8 4 4 8 2
Geist  : 0 4 4 4 4 4 4 8 4 4 4 4 4 8 4 4 2 4
Stahl  : 4 4 4 4 4 8 4 4 2 2 2 4 2 4 8 4 4 8
Feuer  : 4 4 4 4 4 2 8 4 8 2 2 8 4 4 8 2 4 4
Wasser : 4 4 4 4 8 8 4 4 4 8 2 2 4 4 4 2 4 4
Pflanze: 4 4 2 2 8 8 2 4 2 2 8 2 4 4 4 2 4 4
Elektro: 4 4 8 4 0 4 4 4 4 4 8 2 2 4 4 2 4 4
Psycho : 4 8 4 8 4 4 4 4 2 4 4 4 4 2 4 4 0 4
Eis    : 4 4 8 4 8 4 4 4 2 2 2 8 4 4 2 8 4 4
Drache : 4 4 4 4 4 4 4 4 2 4 4 4 4 4 4 8 4 0
Unlicht: 4 2 4 4 4 4 4 8 4 4 4 4 4 8 4 4 2 2
Fee    : 4 8 4 2 4 4 4 4 2 2 4 4 4 4 4 8 8 4
```

(Die Zeilen sind direkt aus dem Binary ausgelesen; Gegenprobe: Normal→Geist 0, Geist→Normal 0, Boden→Flug 0,
Elektro→Boden 0, Psycho→Unlicht 0, Drache→Fee 0, Gift→Stahl 0.)

### 2.2 Einzelner Verteidigertyp: `CalcAffinity(wazaTyp, pokeTyp, umgekehrt)` [O, `@0x1c296c0`]

1. Ist einer der beiden Typen 18 (kein Typ), ist das Ergebnis **ID 7** (= neutral), ohne Tabellenzugriff.
2. Sonst Tabellenwert `t = TYPE_AFF_TBL[wazaTyp][pokeTyp]`:
   - normaler Kampf: `0 → ID 0`, `2 → ID 6`, `4 → ID 7`, `8 → ID 8`;
   - umgekehrter Kampf (`isSakasaBattle`, „Inverse Battle“): `0 → ID 8`, `2 → ID 8`, `4 → ID 7`, `8 → ID 6`.
3. Typen außerhalb 0..17 (außer 18) lösen im Original eine Ausnahme aus (nicht abgebildet).

**Affinitäts-IDs** (`TypeAffinity.AffinityID`): `0` = ×0, `1` = ×1/64, `2` = ×1/32, `3` = ×1/16, `4` = ×1/8, `5` = ×1/4, `6` = ×1/2,
`7` = ×1, `8` = ×2, `9` = ×4, `10` = ×8, `11` = ×16, `12` = ×32, `13` = ×64, `14` = „kein Wert“ (`TYPEAFF_NULL`).
Es gibt eine interne Wertetabelle `VALUE_TABLE = {0,1,2,4,8,16,32,64,128,256,512,1024,2048,4096}` (ID → 64·Faktor) [O, aus dem .cctor].

### 2.3 Zwei Typen: `MulAffinity(a, b)` [O, `@0x1c298c0`]

`MulAffinity` multipliziert zwei IDs: `p = VALUE_TABLE[a] * VALUE_TABLE[b]`.
- `p < 0x40040`: `v = p >> 6`; ist `v == 0` obwohl beide IDs ≠ 0 (Faktor kleiner 1/64), wird `v = 1` gesetzt (das Original ruft hier
  eine Assert-Meldung auf, rechnet aber weiter).
- sonst `v = 0x1000` (Sättigung bei ×64).
- Ergebnis: ist `a == 0` oder `b == 0` → **ID 0**. Sonst die Position `k` des niedrigsten gesetzten Bits von `v` (0-basiert) plus 1,
  also `v = 64 → ID 7`, `v = 128 → ID 8`, `v = 1 → ID 1`; `v = 0x1000 → ID 13`.
- Eingaben ≥ 14 lösen im Original eine Ausnahme aus (nicht abgebildet).

Die Pml-Variante `CalcAffinity(wazaTyp, typ1, typ2, umgekehrt)` [`@0x1c29810`] multipliziert **beide** Einzelwerte ohne Duplikatprüfung.
Der Kampf selbst benutzt aber `calc.TypeAffPair` (nächster Punkt).

### 2.4 Kampf-Variante: `calc.TypeAffPair(wazaTyp, PokeTypePair)` [P, `@0x2074300`]

`PokeTypePair` ist eine 16-Bit-Packung: Bits 0–4 Typ 1, Bits 5–9 Typ 2, Bits 10–14 Zusatztyp (z. B. durch Attacken wie Halloween,
`PokeTypePair.Split @0x21ce620`). Ablauf:
1. `aff = CalcAffinity(waza, typ1, umgekehrt)`.
2. Ist `typ2 ≠ 18` **und** `typ2 ≠ typ1`: `aff = MulAffinity(aff, CalcAffinity(waza, typ2))`.
3. Ist `zusatz ≠ 18` **und** `zusatz ≠ typ1` **und** `zusatz ≠ typ2`: `aff = MulAffinity(aff, CalcAffinity(waza, zusatz))`.
Das Flag „umgekehrt“ steht in `calc.g_SakasaBtlFlag`, gesetzt durch `calc.InitSys(zufall, sakasa)` [`@0x2073f40`].
Ein Einzeltyp-Pokémon trägt Typ 2 = Typ 1 (bzw. 18) und wird so nicht doppelt gezählt.

`ConvAboutAffinity(id)` [`@0x1c29b60`] grobe Einstufung für die Anzeige: `id > 7 → 2` (wirksam), `id == 7 → 1`, `id == 0 → 0`,
sonst `3` (nicht sehr effektiv). `calc.GetResistTypes` [`@0x2074660`] liefert alle Angriffstypen, deren ID gegen den Einzeltyp 0 oder 6 ist.

### 2.5 Anwendung auf den Schaden: `calc.AffDamage(roh, id)` [O, `@0x2074820`]

- `id = 0 → 0`; `id = 1..6 → roh >> (7 - id)` (Rechtsschieben, also abrunden: 1 → >>6, 6 → >>1);
- `id = 8..13 → roh << (id - 7)` (32-Bit, Überlauf wickelt um);
- jede andere ID (7, ≥ 14) → `roh` unverändert.

## 3. Statuswerte, Wesen

### 3.1 Wesenstabelle [O]

25 Wesen (`Seikaku`-ID 0..24; Enum-Namen GANBARIYA, SAMISHIGARI, YUUKAN, IJIPPARI, YANTYA, ZUBUTOI, SUNAO, NONKI, WANPAKU, NOUTENKI,
OKUBYOU, SEKKATI, MAJIME, YOUKI, MUJYAKI, HIKAEME, OTTORI, REISEI, TEREYA, UKKARIYA, ODAYAKA, OTONASHII, NAMAIKI, SINTYOU, KIMAGURE;
das ist die übliche Reihenfolge Robust, Solo, Mutig, … Kauzig). Die Tabelle
`Pml.PokePara.CalcTool` hat 25 Zeilen zu je 5 `sbyte` (Spalten: Angriff, Verteidigung, Spezial-Angriff, Spezial-Verteidigung,
Initiative). `+1` = Wert wird erhöht, `-1` = gesenkt, `0` = unverändert [`CalcTool..cctor @0x25aec40`, aus dem echten .cctor ausgelesen,
Fixture `BattleTables.json`, `natureTable`]. Neutrale Wesen: IDs 0, 6, 12, 18, 24 (alle Einträge 0). Jedes andere Wesen erhöht genau einen und
senkt genau einen Wert, je Zeile ein `+1` und ein `-1`; die Zeilen stehen vollständig in `BattleTables.json`.
Mapping „Kraft-ID“ (`powerId`) → Spalte: `1 → Angriff`, `2 → Verteidigung`, `3 → Sp.-Angriff`, `4 → Sp.-Verteidigung`, `5 → Initiative`
(Spalte = `powerId - 1`); `powerId` außerhalb 1..5 bedeutet „keine Wesenswirkung“ [O, `GetPowerTransformBySeikaku @0x25ad6c0`].

### 3.2 Wesenskorrektur [O, `CalcCorrectedPowerBySeikaku @0x25ad2c0`]

`wert` (32 Bit), Wesen `n`, `powerId`:
- `powerId` nicht in 1..5 oder Tabelleneintrag 0 → `wert` unverändert;
- Eintrag `-1`: `((wert * 90) & 0xfffe) / 100`; Eintrag `+1`: `((wert * 110) & 0xfffe) / 100`.
Auffällig: das Produkt wird mit `0xfffe` **maskiert** (16 Bit, Bit 0 gelöscht), bevor durch 100 geteilt wird. Für echte Statuswerte (< 596) ändert die
Maske nichts, außer dass sie ein ungerades Produkt abrundet; ab Wert 596 (Produkt ≥ 65 536, +10 %) wickelt es um. Das
Verhalten wird 1:1 nachgebildet; die Fixtures testen Werte bis 65 535. Das Ergebnis der Statusfunktionen ist `ushort`.

### 3.3 HP und übrige Werte [O]

Alle Eingaben werden maskiert: Basiswert und IV mit `& 0xffff`, Level mit `& 0xff`, EV als `(ev & 0xfffc) >> 2` (also `floor(ev/4)` mit
16-Bit-Eingang).
- **HP** `CalcMaxHp(monsno, level, basis, iv, ev)` [`@0x25ad1b0`]: ist `monsno == 292` (Nationaldex 292 = Shedinja, Pokémon mit fester 1 HP), Ergebnis **1**. Sonst
  `((2*basis + iv + ev/4) * level) / 100 + level + 10`.
- **Angriff / Verteidigung / Sp.-Angriff / Sp.-Verteidigung / Initiative** [`CalcAtk @0x25ad200`, `CalcDef @0x25ad3c0`, `CalcSpAtk @0x25ad480`,
  `CalcSpDef @0x25ad540`, `CalcAgi @0x25ad600`]: `roh = ((2*basis + iv + ev/4) * level) / 100 + 5`, dann Wesenskorrektur (3.2) mit
  `powerId` 1, 2, 3, 4, 5. Rückgabe `ushort` (untere 16 Bit).
- **Level aus Erfahrung** `CalcLevel(monsno, form, exp)` [`@0x25ad0e0`]: gesucht ist das größte `L` in 1..100 mit `exps[L] ≤ exp`, wobei `exps` die Zeile der
  Wachstumsrate der Art ist (Tabelle `GrowTable`, 101 Einträge, Index = Level); `exps[1] = 0`. Ergebnis mindestens 1, höchstens 100.
  `GrowTable.GetMinExp(level)` [`@0x25a0880`] = `exps[min(level, 100)]` (Level > 100 löst im Original eine Assert-Meldung aus und wird auf 100 gesetzt).

### 3.4 Wachstumsraten [O für das Datenmaterial, P für die Formel]

`work/masterdata/pml_personal/GrowTable.json` enthält 8 Zeilen zu je 101 Einträgen. Ich habe sie gegen die klassischen Formeln geprüft
(Prüfung lokal in `scripts/battle_oracle.py --verify-growth`, nur lesend gegen die Masterdata):
Zeile 0 = mittel-schnell `n³`; Zeile 1 = unregelmäßig (erratic); Zeile 2 = schwankend (fluctuating); Zeile 3 = mittel-langsam
`6/5·n³ − 15·n² + 100·n − 140`; Zeile 4 = schnell `4/5·n³`; Zeile 5 = langsam `5/4·n³`; Zeilen 6 und 7 = wie 0. Alle Zeilen stimmen für
Level 2..100 exakt (Ganzzahldivision), Level 1 = 0, Zeile 3 ist dort negativ und wird auf 0 gesetzt. Details (Bereichsgrenzen
50/68/98 und 15/35) stehen im C#-Code `GrowthRate`; maßgeblich bleibt die Tabelle aus dem Bundle, die Formeln sind eine Hilfe für
Tests ohne Spieldaten.

## 4. Zufall

### 4.1 Generator [O]

Alle Zufallswerte im Kampf kommen aus **Xoroshiro128+** (`Xoroshiro128Plus.Xoroshiro128Plus`), Zustand 2 × 64 Bit.
- **Seed → Zustand** [`Xoroshiro128Plus..ctor(ulong) @0x18d84e0`]: `mix(x)`: `z = x; z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9; z = (z ^ (z >> 27)) * 0x94D049BB133111EB; z ^ (z >> 31)`.
  `s0 = mix(seed + 0x9E3779B97F4A7C15)`, `s1 = mix(seed + 0x3C6EF372FE94F82A)` (alles mod 2^64). Sind beide 0, wird `s0 = 1`.
- **Schritt** [`next @0x18d8fd0`, `NextULong @0x18d8ff0`]: `ergebnis = s0 + s1`; `t = s1 ^ s0`; `s0' = rotl(s0, 24) ^ t ^ (t << 16)`; `s1' = rotl(t, 37)`.
  `NextULong` gibt `ergebnis` zurück, `NextUInt` [`@0x18d9010`] `ergebnis >> 32`.
- **Begrenzter Wert** `Random.GetValue(max)` [`Dpr.Battle.Logic.Random.GetValue @0x21d3290`]: `r = NextULong(); max == 0 ? r : r % max` (64-Bit-Modulo,
  `[0, max)`). `GetValue()` ohne Argument [`@0x21d4090`] = `NextULong`.
- Hilfen: `calc.GetRand(n)` [`@0x2074990`] = `GetValue(n)` auf dem Kampf-Generator `calc.g_RandSys`; `calc.RandRange(a, b)` [`@0x2074a10`]: Grenzen werden
  geordnet, Ergebnis `min + GetValue(max - min + 1)` [O]; `calc.IsOccurPer(p)` [`@0x2075e20`] = `GetValue(100) < p` [O].
- `calc.GetPublicRand(n)` [`@0x20748b0`] nutzt einen **zweiten** Generator `g_PublicRand` (oder `UnityEngine.Random`, wenn dieser fehlt) und ist nur für
  nicht reproduzierbare Darstellungsdinge gedacht.

### 4.2 Seed und Reproduzierbarkeit [P]

- `calc.InitSys(zufall, sakasa)` [`@0x2073f40`] merkt den Kampf-Generator, legt einen zweiten, öffentlichen an und setzt das Inverse-Flag.
  `calc.ResetSys(seed)` [`@0x2074040`] setzt den Kampf-Generator neu (`Random.Initialize(seed)` [`@0x21d4000`]).
- `MainModule.SetUpRandSystem` [`@0x213a1b0`]: Ist im Setup (`BattleSetupParam`, Byte bei +0x3b) das Wiedergabe-Flag `== 1`, wird der Seed aus dem Setup-Feld
  `recRandSeed` (+0xF8) genommen; sonst `Random.Initialize()` [`@0x21d3f40`] mit einem **Unity-Zufallswert** `UnityEngine.Random.Range(int.MinValue, int.MaxValue)`, vorzeichenerweitert
  auf 64 Bit (`(ulong)(long)int`), und dieser Seed wird als `recRandSeed` gespeichert. Der Kampfausgang ist also bei bekanntem Seed vollständig reproduzierbar;
  der Originalseed eines Live-Kampfes kommt aus dem (nicht deterministischen) Unity-Zufall. Der Rebuild nimmt den Seed als Parameter.
- **Ziehreihenfolge im Schaden** (wichtig für Reproduzierbarkeit): Trefferprüfung (genau 1 Zug, nur wenn nicht automatisch getroffen) → Volltrefferprüfung (genau 1 Zug, wenn
  die Attacke Volltreffer prüfen darf) → Zufallsfaktor des Schadens (genau 1 Zug, entfällt bei festem Faktor 85). Mehrfachtreffer-Anzahl
  `calc.HitCountStd` [`@0x2075ae0`] (1 Zug nur wenn die Attacke „2–5 Treffer“ hat, Typ 5) [O].

## 5. Schaden

Der Schaden einer Attacke auf ein Ziel entsteht in `Section_CalcDamage.getCalcDamage` [`@0x22addc0`] → `EventLauncher.Event_CalcDamage` [`@0x1e14710`] [OK].
Vor der eigentlichen Formel liest `getCalcDamage` das Wetter (`Section_FromEvent_GetWeather`) und übergibt es. Die Volltreffer-Entscheidung fällt
**vorher** in `Section_CalcDamage.Execute` [`@0x22ad8d0`] (`Event_CheckCritical`, Abschnitt 7) und die Typenwirkung vorher in `Section_CheckWazaDamageAffinity`.

### 5.1 Eingaben von Event_CalcDamage

Typenwirkung `aff` (ID, Abschnitt 2), `zielFaktor` (Festkomma; 0x1000 bei einem Ziel, bei Mehrfachzielen kleiner), Volltreffer-Flag, „fester Faktor“-Flag
(nur der KI-Simulator setzt es; `getCalcDamage` übergibt 0), Delegator-Flag, Wetter und die Attacke (Typ, Schadenskategorie 1 = physisch, 2 = speziell).
Aus dem Zustand/Handlern kommen (siehe 5.3): `kraft`, `angriff`, `abwehr`, Level des Angreifers, STAB-Verhältnis, Endfaktor, Brand-Ignorieren-Flag.

### 5.2 Ablauf (Reihenfolge ist verbindlich) [OK]

0. **Vorab-Ereignisse** (0x58, 0x59) dürfen Festschaden liefern (z. B. Fixschadensattacken); gelingt das, werden alle folgenden Schritte übersprungen. Nicht Teil
   der Scheibe 1.
1. `kraft`, `angriff`, `abwehr` bestimmen (5.3), Level = Level des Angreifers.
2. **Grundschaden** `DamageBase(kraft, angriff, level, abwehr)` [O, `calc.DamageBase @0x20747e0`]:
   `u = (angriff * kraft * ((level*2)/5 + 2)) / abwehr` (32-Bit, vorzeichenlose Division; ist `abwehr == 0`, ist `u = 0`), Ergebnis `u/50 + 2`.
3. Ist `zielFaktor ≠ 0x1000`: `s = MulRatio(s, zielFaktor)`.
4. **Wetterfaktor** `GetWeatherDmgRatio(wetter, attackenTyp)` [O, `@0x2075830`]: Sonne (1) oder Extremsonne (6): Feuer ×1,5 (0x1800), Wasser ×0,5 (0x800),
   sonst 0x1000; Regen (2) oder Starkregen (5): Wasser 0x1800, Feuer 0x800, sonst 0x1000; alle anderen Wetter (0, 3 Schnee/Hagel, 4 Sand, 7, …) 0x1000.
   Ist der Faktor ≠ 0x1000: `s = MulRatio(s, faktor)`.
5. **Volltreffer** (falls gesetzt): `s = (s * 15) / 10` (32-Bit, abrunden; **nicht** über MulRatio).
6. **Zufallsfaktor** `roll`: bei „fester Faktor“ **85**, sonst `100 - GetRand(16)` (also 85..100, ein Zug aus dem Kampf-Generator).
   `s = (roll * s) / 100` (32-Bit-Produkt, das bei Überlauf umwickelt, danach abrundende Division). Der Faktor kommt **nach** Wetter und Volltreffer.
7. **STAB**: ist der Attackentyp ≠ 18: `s = MulRatio(s, stab)`, wobei `stab` aus `Event_CalcTypeMatchRatio` [`@0x1e15740`] kommt: 0x1800 (×1,5), wenn der Angreifer den Typ
   hat (Typ 1, Typ 2 oder Zusatztyp, `BTL_POKEPARAM.IsMatchType @0x20dfad0`, Typ 18 passt nie), sonst 0x1000; ein Handler kann das Verhältnis noch ändern
   (Fähigkeit Anpassung/„Tekiouryoku“ schreibt 0x2000, `Handler.Tokusei.handler_Tekiouryoku @0x1a41650`).
8. **Typenwirkung**: `s = AffDamage(s, aff)` (2.5).
9. **Brand**: ist die Attacke physisch (Kategorie 1) **und** der Angreifer verbrannt (`GetPokeSick == 4`) **und** das „Brand ignorieren“-Flag (kommt aus
   `Event_getAttackPower`, Ereignis 0x4A, Variable 0x5A, z. B. durch eine Fähigkeit mit Brand-Ausnahme) nicht gesetzt: `s = (s * 50) / 100` (32-Bit, abrunden).
10. **Endfaktor** (Ereignis 0x5A: Handler der letzten Schadensstufe multiplizieren hier): Variable 0x38 startet bei 0x1000 mit den Grenzen
    `[0x29, 0x20000]`, Handler multiplizieren (Regel „halb nach oben“, Abschnitt 1); dann `s = MulRatio(s, endfaktor)`.
11. (G-Modus, Raid-Boss-Wand: Scheibe 2.)
12. **Mindestschaden**: ist `s == 0` und kein Festschaden aktiv: `s = 1`. Ergebnis wird auf 16 Bit gekürzt (`ushort`).
    Wichtig: der Mindestschaden gilt auch bei Typenwirkung 0 — die Immunität wird davor (`Section_CheckTypeAffinity`/`CheckWazaDamageAffinity`) abgefangen.

Anschließend begrenzt `Section_CalcDamage.Execute` [`@0x22ad8d0`]: `roundDamage` [`@0x22adf50`]: `min(schaden, aktuelleHP)`; bei Delegator
(`roundDamage_byMigawari @0x22adf90`): `min(schaden, Delegator-HP)` (HP-Feld +0x92). Durchhalten (`Event_CheckKoraeru`) darf die gedeckelte HP weiter
verändern [P].

### 5.3 Teilwerte aus dem Ereignissystem [P, OK-ersetzt]

- `kraft` = `Event_getWazaPower` [`@0x1e14e20`]: Basis aus den Attackendaten; Ereignis 0x45 darf sie umschreiben, danach Ereignis 0x46 mit Verhältnis
  (Start 0x1000, Grenzen `[0x29, 0x200000]`), Ergebnis `MulRatio(kraft, verhältnis)`.
- `angriff` = `Event_getAttackPower` [`@0x1e15010`]: Quelle ist physisch der Angriffswert (ValueID 8), speziell der Sp.-Angriff (10); ein Ereignis (0x49) darf die
  Wertart ändern (Variable 0x41), Ereignis 0x47 darf das Pokémon wechseln, dessen Wert zählt (Variable 0x40, z. B. Ziel statt Angreifer). Wert = `BTL_POKEPARAM.GetValue` (mit Stufen) **oder** `GetValue_Base` (ohne
  Stufen), Regel: bei Volltreffer wird ein **negativer Stufenwert des Angreifers ignoriert** (Stufe < 6 im 0..12-System → Basiswert); sonst Stufenwert.
  Danach Ereignis 0x4A mit Verhältnis (Start 0x1000, Grenzen `[0x19a, 0x20000]`), Ergebnis `MulRatio(wert, verhältnis)`.
- `abwehr` = `Event_getDefenderGuard` [`@0x1e153d0`]: physisch Verteidigung (ValueID 9), speziell Sp.-Verteidigung (11); Ereignis 0x48 darf die Art vertauschen (Variable 0x42) und das Ignorieren der Stufen erzwingen (Variable 0x59); bei Volltreffer
  `GetValue_Critical` (ignoriert **positive** Verteidigungsstufen des Ziels, wenn die Stufe ≥ 7 wäre: Regel `stufe > 6 → Basiswert`); bei Sandsturm und
  Gestein-Ziel zusätzlich ×1,5 auf Sp.-Verteidigung (`MulRatio(wert, 0x1800)`); danach Ereignis 0x4B mit Verhältnis `[0x19a, 0x20000]`.
- **Stufenwert** `BTL_POKEPARAM.GetValue(8..12)` [`@0x20dd010`] = `calc.StatusRank(basis, stufenIndex)` [O]: Stufenindex 0..12 (6 = neutral):
  `((zähler * basis) & 0xffff) / nenner` mit der Tabelle (zähler/nenner) `{2/8, 2/7, 2/6, 2/5, 2/4, 2/3, 2/2, 3/2, 4/2, 5/2, 6/2, 7/2, 8/2}`
  (aus dem .cctor, [O]); Index ≥ 13 liefert `basis` unverändert.
- Genauigkeits- und Fluchtstufe liegen im selben 0..12-System (6 = neutral) [P].

### 5.4 Wetterschaden nach dem Zug [P]

`calc.RecvWeatherDamage(poke, wetter)` [`@0x2075770`]: Wetter 3 (Hagel/Schnee): Typ Eis ist immun; Wetter 4 (Sand): Gestein, Stahl, Boden sind immun; sonst
Schaden `max(1, maxHP / 16)` (HP über `ValueID 16`, MAX_HP_BEFORE_G; Original rechnet `(x + 15)` bei negativem x, praktisch `x >> 4`). Wetter außerhalb 3/4: 0.

## 6. Treffer

`EventLauncher.Event_CheckHit(angreifer, ziel, attacke)` [`@0x1e19350`] [OK], liefert `trifft` und ein Flag „Zuneigungsausweichen“:
1. Flag := 0. Trifft automatisch (**kein Zufallszug**), wenn eines gilt: `CheckMustHit` (Ziel/Angreifer in bestimmter Lage, z. B. Lock-On-Effekte), Kampfart
   „Demo-Fang“ (`GetCompetitor == 4`), `Event_IsCalcHitCancel` (Attacke trifft immer oder Handler hebt die Prüfung auf), das Ziel hat den Zustand 0x21 (`WAZASICK_TELEKINESIS`).
2. `p0` = `Event_getHitPer` [`@0x1e16a30`] = `MulRatio(genauigkeit, verhältnis)` (Genauigkeit aus den Attackendaten, Verhältnis aus Ereignissen, Start 0x1000,
   Grenzen `[0x19a, 0x20000]`).
3. Ereignis 0x3F darf die Genauigkeitsstufe `acc` (Angreifer, 0..12), die Fluchtstufe `eva` (Ziel, 0..12), das Flag „Flucht ignorieren“ und ein Verhältnis ändern
   (Variable 0x38, Start 0x1000, Grenzen `[0x29, 0x20000]`). Hat der Angreifer das Zug-Flag 0xE, wird das Verhältnis zusätzlich mit 0x1333 multipliziert (≈ ×1,2,
   `EVENTVAR_MulValue`-Regel).
4. Stufenindex: Wenn „Flucht ignorieren“ gesetzt ist **oder** (das Ziel hat den Zustand 0x11 (`WAZASICK_MIYABURU`, Foresight-/Odor-Sleuth-Art) **und** `eva > 6`), ist der Fluchtterm `-6`, sonst `-eva`.
   `idx = clamp(fluchtterm + acc + 6, 0, 12)`.
5. `p1 = HitPer(p0, idx)` [O, `calc.HitPer @0x20750b0`]: Tabelle (zähler/nenner) `{6/18, 6/16, 6/14, 6/12, 6/10, 6/8, 6/6, 8/6, 10/6, 12/6, 14/6, 16/6, 18/6}`; `p1 = (zähler * (p0 & 0xff)) / nenner`,
   `≥ 100 → 100`; Index ≥ 13 liefert `p0` unverändert. (Gegenüber den klassischen 3/9 … 9/3-Brüchen identisch.)
6. `p2 = MulRatio(p1, verhältnis)`; `≥ 100 → 100`.
7. Zuneigung: Ist die Freundschaft des **Ziels** über `SectionUtil.GetFriendship` (nur aktiv für Spieler-Pokémon in Wild-/Trainerkämpfen, nicht im G-Modus, `IsFriendshipActive @0x21378d0`)
   gleich **255**: `p2 = p2 > 10 ? p2 - 10 : 0` und Flag := 1.
8. Zug `x = GetRand(100)`; **trifft, wenn `(x & 0xff) < (p2 & 0xff)`**.
Hinweise: `p0 == 0` (Attacken ohne Genauigkeit) führen hier zu `p1 = 0`, also Fehlschlag; sie müssen vorher über `IsAlwaysHit`/`IsCalcHitCancel` abgefangen
werden [P]. Reihenfolge der Zufallszüge: nur Schritt 8.

## 7. Volltreffer

`EventLauncher.Event_CheckCritical(angreifer, ziel, attacke)` [`@0x1e144d0`] [OK]:
1. `stufeAttacke` = `WAZADATA.GetCriticalRank` (0..2, **6 = immer Volltreffer**). `stufe = stufeAttacke == 6 ? 6 : GetCriticalRank(Angreifer) + stufeAttacke`
   (`BTL_POKEPARAM.GetCriticalRank @0x20e0c10` [P]: gespeicherte Stufe (Byte +0x3f) plus Zuschläge durch Zustandsflags: +2 bei gesetztem Bit 1 des zweiten Zustandsfeldes, +3 bei einem Flag in +0x168 des Zustandsblocks; Ergebnis ab 3 auf 3 gedeckelt).
2. Ereignis 0x43 darf `stufe` ändern oder Volltreffer **verbieten**. Danach `stufe = min(stufe, 3)`.
3. Verboten → kein Volltreffer (kein Zufallszug).
4. `stufeAttacke == 6` → Volltreffer, außer Kampfart „Demo-Fang“ (= 4) (kein Zufallszug).
5. Demo-Fang → kein Volltreffer. Sonst: `zuneigung = (GetFriendship(Angreifer) == 255)`; `teiler = zuneigung ? 2 : 1`.
6. `CheckCritical(stufe, teiler)` [O, `calc.CheckCritical @0x2075170`]: `n = CheckCriticalTable[stufe] / teiler`, mindestens 1 (Ergebnis 0 → 1);
   Volltreffer, wenn `GetValue(n) == 0`. Tabelle `{24, 8, 2, 1}` (aus dem .cctor) = 1/24, 1/8, 1/2, 1/1.
7. Bei Volltreffer schreibt die Funktion das Flag „Zuneigungsbonus“ := `zuneigung`.
Die Stufe 6 der Attackendaten steht also nicht in der Tabelle; die gedeckelte Stufe indexiert sie.

## 8. Erfahrungspunkte

Berechnung je Empfänger: `Exp.CalcExp(param, ergebnis)` [`Dpr.Battle.Logic.Exp.CalcExp @0x19f7d70`] [O (echte Funktion mit Speicher-Eingaben)].
Eingaben (`Exp.CalcParam`): `levelCap` (Level-Deckel), `deadPokeExp` (Basis-Erfahrung der besiegten Art, `PersonalTable.give_exp`), `deadPokeLevel`,
`getPokeLevel` (Level des Empfängers), `getPokeFriendship`, `playerLanguageId`, `getPokeLanguageId`, Flags `isMatch` (hat gekämpft), `isGakusyusoutiOn`
(Erfahrungs-Teiler vorhanden), `haveSiawasetamago` (Glücks-Ei), `isEvoCanceledPoke` (Entwicklung per Level gestoppt/Entwicklungsstein), `isMyPoke` (eigenes Pokémon, nicht
getauscht), `competitor` (wird nicht benutzt).
Ablauf:
1. Hat der Empfänger weder gekämpft noch einen Teiler: Ergebnis 0 (`exp = 0`, Flags 0).
2. `L = min(deadPokeLevel, levelCap)`. `basis = L * deadPokeExp`; `basis = basis < 5 ? 1 : basis / 5` (`CalcBaseExp @0x19f8000`, 32-Bit).
3. Hat der Empfänger **gekämpft**: `e = basis`. Sonst (nur Teiler): `e = max(1, basis >> 1)` (`CalcGakusyusoutiExp @0x19f8030`), Flag „durch Teiler“ = 1.
4. **Stufenausgleich** (`getexp_calc_adjust_level @0x19f8040`, **Gleitkomma einfacher Genauigkeit**):
   `x = 2*L + 10` (float), `y = L + level_empfänger + 10` (float), `f(z) = z*z*sqrt(z)` (float, Reihenfolge `(z*z)*sqrtf(z)`),
   `e = (int)( (f(x) / f(y)) * (float)e + 1.0f )` (Abschneiden zur 0, `int`). Das entspricht `((2L+10)/(L+Lr+10))^2,5 · e + 1`.
5. Ist das Pokémon **nicht** eigen (`!isMyPoke`): `e = MulRatio(e, sprache gleich ? 0x1800 : 0x1b33)` (×1,5 bzw. ≈ ×1,7), Flag „Bonus“ := 1.
6. Glücks-Ei: `e = MulRatio(e, 0x1800)`, Bonus := 1.
7. Entwicklungs-Bonus: `e = MulRatio(e, 0x1333)`, Bonus := 1.
8. Freundschaft `> 219` (`0xDB`): `e = MulRatio(e, 0x1333)`, Bonus := 1.
Rückgabe `exp` (32 Bit), `durchTeiler`, `hatBonus` (Reihenfolge der Multiplikationen: 5 → 6 → 7 → 8; jede Stufe rundet einzeln).
Der Trainerkampf-Bonus (×1,5) kommt **nicht** in dieser Funktion vor (`competitor` bleibt unbenutzt); wo er sonst steckt, ist offen (Abschnitt 10).
Die Verteilung auf die Gruppe (`ExpCalculator.CalcExp @0x19f8460` ruft `calcExp_Party`, `calcEffortExp_Party`, `calcGEffort_Party`) und die EV-Vergabe sind Scheibe 2.

## 9. Orakel-Methodik und Ergebnisse

- Werkzeug: `scripts/battle_oracle.py` (Python 3 + Paket `unicorn`, installiert unter `tools/pydeps`). Es lädt die LOAD-Segmente des ELF an ihre
  vaddr, wendet die 551 315 relativen Relokationen an (nötig, weil IL2CPP seine Tabellenzeiger über sie auflöst) und führt die Funktionen ab
  ihrem Einstieg bis zum Rücksprung aus. IL2CPP-Laufzeit: Array-Anlage, Typprüfung, Barrieren und Klasseninitialisierung sind Stubs; statische
  Felder werden nicht nachgebaut, sondern durch **Ausführen der echten `.cctor`** (`TypeAffinity`, `CalcTool`, `calc`) befüllt. Statische Initialisierer-Arrays
  (`RuntimeHelpers.InitializeArray`) lesen die Rohbytes aus `global-metadata.dat` anhand der Feld-Hashes aus `dump.cs`.
- Verbund-Orakel (`damage`, `hit`, `crit`): Die Funktionen `Event_CalcDamage`, `Event_CheckHit`, `Event_CheckCritical` laufen als Original; das Ereignissystem
  (`EVENTVAR_*`, `CallEvent`), `BTL_POKEPARAM`-Zugriffe und die Handler-Funktionen (Kraft, Angriff, Abwehr, STAB) sind Python-Stubs, deren Rückgaben
  Teil der Fixture-Eingaben sind. Der Zufall kommt aus dem echten Xoroshiro; jede Fixture enthält deshalb auch den **nächsten Zufallswert nach dem Aufruf**
  (`nextRand`) und prüft damit die Anzahl der gezogenen Werte.
- Fixtures (`unity/Assets/Tests/EditMode/Fixtures`, nur Zahlen, feste Seeds, mit `PYTHONPATH=tools/pydeps python3 scripts/battle_oracle.py` neu erzeugbar);
  jede Funktion hat ≥ 50 Eingaben.

| Fixture | Funktionen (echt, Unicorn) | Fälle |
|---|---|---|
| `BattleTables.json` | .cctor von `TypeAffinity`, `CalcTool`, `calc` (Tabellen) | 101 Einträge |
| `BattleStats.json` | `CalcMaxHp`, `CalcAtk/Def/SpAtk/SpDef/Agi`, `CalcCorrectedPowerBySeikaku`, `GetPowerTransformBySeikaku` | 1635 |
| `BattleTypes.json` | `TypeAffinity.CalcAffinity`, `MulAffinity` | 918 |
| `BattleCalc.json` | `DamageBase`, `AffDamage`, `MulRatio`, `MulRatio_OverZero`, `MulRatioInt`, `GetWeatherDmgRatio`, `StatusRank`, `HitPer`, `RoundValue` | 1855 |
| `BattleExp.json` | `Exp.CalcExp`, `getexp_calc_adjust_level`, `CalcBaseExp`, `CalcGakusyusoutiExp` | 740 |
| `BattleRng.json` | `Xoroshiro128Plus..ctor`, `NextULong`, `NextUInt`, `Random.GetValue(max)` | 70 Ströme |
| `BattleRngUse.json` | `IsOccurPer`, `RandRange`, `HitCountStd`, `CheckCritical` mit echtem RNG | 640 |
| `BattleDamage.json` | `Event_CalcDamage` (Verbund) | 500 |
| `BattleHit.json` | `Event_CheckHit` (Verbund) | 600 |
| `BattleCrit.json` | `Event_CheckCritical` (Verbund) | 400 |

## 10. Offenes

1. **Handler (Fähigkeiten, Items, Attacken-Spezialfälle):** Kraft-, Angriffs-, Abwehr-, STAB- und Endfaktor-Anpassungen kommen aus ~2000 Handler-Methoden
   (`Dpr.Battle.Logic.Handler.Tokusei/Item/Waza`). Scheibe 1 behandelt sie als Eingaben (Verhältnisse). Beispiel bestätigt: Anpassung = STAB 0x2000.
2. **Ereignis-IDs** (0x3E, 0x3F, 0x40, 0x43, 0x45–0x4B, 0x53, 0x54, 0x58–0x5C, 0x95 …) sind hier nur nach Wirkung benannt; ein Katalog gegen die Handler fehlt.
3. **Festschaden/Vorab-Ereignisse** 0x58/0x59 (Variablen 0x3A–0x3C) und der Schaden-Deckel durch Durchhalten/Delegator/Raid-Boss sind nur grob beschrieben.
4. **Typenwirkung im Kampf:** `Section_CheckWazaDamageAffinity`, schwebende Ziele (Boden-Immunität), Fähigkeiten (Schwebe, Absorber), Zustände
   (Verwandlungs-Typen) und das Umschreiben der Wirkung per `rewriteWazaAffinityBy...` sind nicht rekonstruiert; die Immunität (ID 0) setzt sich nur durch,
   wenn diese Abschnitte sie vor `Event_CalcDamage` abfangen.
5. **Trainerkampf-Erfahrung ×1,5**: kommt nicht in `Exp.CalcExp` vor; vermutlich in `Section_*Exp*`/`BTL_CLIENT`. Erfahrungsverteilung, EV-Vergabe und
   Level-Aufstiege (Scheibe 2).
6. **Sprach-/`isMyPoke`-Bedeutung:** `playerLanguageId` und `getPokeLanguageId` sind Sprach-IDs; ob der 0x1b33-Zweig im Spiel (nur eine Sprache pro Installation) je auftritt,
   ist ungeklärt, bleibt aber nachgebildet.
7. **Zuneigungseffekte** (Freundschaft 255): Nur Treffer (−10), Volltreffer (Teiler 2) bestätigt; weitere (Statusheilung, Überleben) sind Scheibe 2.
8. **Wachstumsrate-Index im Pokémon**: Ob das Feld `grow` der Art direkt die Zeile der `GrowTable` ist, ist angenommen (Zeile 0–5; 6/7 ungenutzt).
9. **Seed im Live-Kampf:** stammt aus `UnityEngine.Random`; der Rebuild kann deshalb nur *ab* einem gegebenen Seed deterministisch sein. Ob der Online-/Wiedergabe-Pfad
   (`recRandSeed`, `commMode`) weitere Zufallsquellen hat, ist ungeklärt. `g_PublicRand` ist bewusst nicht reproduzierbar.
10. **Nicht abgedeckt:** `BattleSimulator.CalcDamage` (KI-Vorschau), Fänge (`Capture.checkCapureSuccessByRandom`), Geldpreise (`calc.CalcWinMoney`), Wirkungs-Prozente
    (`calc.IsOccurPer` ist da, die Verwendung nicht), Mehrfachtreffer-Ablauf, Fluchtformel, Initiative/Prioritäten, Statusschäden (Gift, Verwirrung), Wetterdauer.
11. **Orakel-Grenzen:** Der Emulator stubt Klassenkonstruktoren; Funktionen mit Zugriff auf `PersonalSystem`/Masterdaten (`CalcLevel`, `GetGrowTable`) laufen nicht
    ohne Engine-Zustand und sind nur per Pseudocode + Formelprüfung gegen `GrowTable.json` gedeckt [P]. `RecvWeatherDamage` ist nur [P].
