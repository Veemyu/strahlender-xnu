# Ereignisskripte (EvData): Befehle und Interpreter (Todo `ap-evscript`)

Stand: 2026-10-19. Nur Namen, Zahlen und Struktur; keine Spieltexte, keine Daten im Repo. Die Pseudocodes liegen lokal unter `work/decomp/evscript*`
(Ghidra, `-readOnly`), die Auswertung unter `work/evscript/` (nicht im Repo).

**Die Story-Reihenfolge der ersten Strecke ist nicht bestätigt.** Stellen, die davon abhängen, sind mit **[A]** (Annahme) markiert.

## 1. Ergebnis in Kürze

- Format und Laufzeitmodell des Originals (`EvDataManager.UpdateEvdata`, `RunEvCmd`, `CallLabel`, `ReturnEvData`) sind aus dem Pseudocode geklärt.
- Die Sprungtabelle von `RunEvCmd` (1234 Einträge) wurde aus der ELF gelesen und je Kennung dem Handler zugeordnet. Ergebnis: **484 Kennungen sind im Original ohne
  Wirkung** (Rücksprung mit 1), darunter 206 der in den Daten benutzten Kennungen (8 739 Befehle, 13,5 %).
- Neues C#-Modul `Xnu.EvScript` (`unity/Assets/Scripts/EvScript`, reines C#, ohne UnityEngine): Skriptbuch, Zustandsmaschine, Host-Schnittstelle, Variablen
  (Speicher und `SaveData`). **61 Kernbefehle** sind mit Semantik umgesetzt (65,5 % aller 64 741 Befehle), 599 weitere Kennungen (21,0 %) gehen an den Host.
- 38 synthetische Tests (`unity/Assets/Tests/EditMode/EvScriptTests.cs`), außerhalb von Unity per `dotnet test` grün (Wegwerfprojekt `work/dotnet-evscript`);
  im Unity-Test-Runner noch nicht gelaufen (Editor war nicht benutzbar; `.meta`-Dateien erzeugt Unity beim ersten Import).
- Echtdatenlauf (Abschnitt 6): alle 13 139 Skripte laufen mit einem Mock-Host ohne unbekannten Befehl und ohne Fehler; 8 095 davon brauchen keinen einzigen
  Host-Befehl.

## 2. Format und Ausführungsmodell

### Daten
`EvData { Scripts[Label, Commands[Arg[argType, data]]], StrList }` (siehe `docs/masterdata.md` Abschnitt 13). Das erste Argument ist die Kennung
(`EvCmdID.NAME`, `argType` 0). Argumentarten: `Float` 1, `Work` 2, `Flag` 3, `SysFlag` 4, `String` 5. [P]

### Wertauflösung eines Arguments (`val`)
`Work` → aktueller Arbeitswert; `Float` → die **Bits** von `data` als `float`, dann auf `int` abgeschnitten (`fcvtzs`, also Richtung 0); alles andere → 0. Ganzzahlen stehen in den
Skripten als Float (z. B. 7 = `0x40E00000`). Ziel-Argumente (zu schreibender Work-Index, Flag-Index) werden **roh** aus `data` genommen, ohne Typprüfung. [P]
Ein String-Argument ist ein Index in `StrList` der Datei, in der das laufende Skript steht; ein Nicht-String-Argument liefert `""`. [P]

### Variablen (`FlagWork` → `PlayerWork`)
| Art | Speicher im Save | Größe | Bemerkung |
|---|---|---|---|
| Work | `intValues` | 500 × int | `GetInt/SetInt`, Index außerhalb → Ausnahme |
| Flag | `boolValues` | 4000 × bool | Index −1 oder 4000 gilt in den Flag-Befehlen als „nicht gesetzt“/wird ignoriert |
| Systemflag | `systemFlags` | 1000 × bool | Indizes 0x326–0x329 liefern immer wahr (`GetSytemFlag`) |
| Trainer-Siegflag | `tr_battleData` | 707 Einträge | je Trainer ein `ushort`: niedriges Byte Sieg, hohes Byte „sucht noch“ (`TrainerWork.SetWinFlag`/`GetBattleSearcher`) |

Im Marshal-Abbild der Datei sind es laut `docs/save-spec-entwurf.md` 4 Byte je bool und 8 Byte je Trainer; `EvSaveVariables` nimmt dort Sieg an Offset 0 und Suche an Offset 4 **[A]**.
Arbeitswerte mit besonderer Rolle: 199 (TALK_CLOSE setzt 0), 0xF2/0xF3 (FLD_ITEM_EVENT), 0xF8 (CASE_CANCEL). `EvWork.WORK_INDEX` benennt 441 Werte (`LOCALWORK0…`, `OBJCHRWORK0…`,
`WK_SCENE_T01…` für Szenen-Fortschritt je Ort), `INDEX_NUM` die Flag-Bereiche (FH 0–63, FE 63–314, FV 314–603, FT 603–859, FV_FLD 859–1115, TMFLG ab 1115). [P]

### Ablauf (`UpdateEvdata`)
- Zustand: Ereignisliste (geladene `EvData`-Dateien, je Datei `LabelIndex`/`CommandIndex`), aktueller Listenindex (−1 = kein Ereignis), Aufrufstapel `EvCallData(Liste, Label, Befehl)`. [P]
- Je Aufruf: Befehl lesen, `RunEvCmd(Kennung)` ausführen. Liefert der Handler 0, wird der Befehl im nächsten Frame wiederholt. Liefert er 1, rückt `CommandIndex` um 1 vor,
  **außer** der Befehl hat Liste oder Label gewechselt (Sprung, Aufruf, Rückkehr). Danach `VariableReset` (setzt u. a. `_talkStart`, `_procCmd`, `_timeWait` auf 0). [P]
- Schleifenlimit 5000 Befehle je Frame (`MUGEN_LOOP`); danach wird das Ereignis beendet. [P]
- Ende: `END` (und `NOP`, `SP_EVENT_DATA_END`, `SCENE_CHANGE_END`) setzt den Listenindex auf −1. Läuft `CommandIndex` hinter den letzten Befehl, wird `EventEnd()` aufgerufen und der Aufrufstapel geleert. [P]
- Labels: globales Wörterbuch `_findAllLabel: Label → [Listenindex, Skriptindex]`. `JUMP` springt (Befehl 0 des Skripts), `CALL` legt `(Liste, Label, Befehl+1)` auf den Stapel und springt,
  `RET` holt zurück. Ein unbekanntes oder leeres Label ist **kein Fehler**, der Befehl endet mit 1 ohne Sprung. `RET` bei leerem Stapel fällt in den END-Pfad (beendet das Ereignis). [P]
- Vergleichsart-Strings (`EQ NE GT GE LT LE`): `IFVAL_*` vergleicht zwei `val`-Werte (`GT`: `a > b`). `IF_JUMP/IF_CALL` und die Flag-Makros lesen `_cmp_flag` (0 kleiner, 1 gleich, 2 größer; EQ = 1, NE ≠ 1, GT = 2, GE ≥ 1, LT = 0, LE ≤ 1). [P]
  Die Alias-Zeichenketten von `ReEQType` (`==`, `ON`, `OFF` usw.) sind nicht einzeln aufgelöst **[A]**; in den Daten kommen nur die sechs Kürzel vor.

### Sprungtabelle (`RunEvCmd`)
`RunEvCmd(id)`: ist `id − 1 ≥ 0x4D2` (also `id ≤ 0` oder `id > 1234`, auch der Platzhalter −1, 88 × in den Daten), kommt sofort 1 zurück. Sonst springt eine `ushort`-Tabelle bei `0x3EDAB7C` (Ghidra-Adresse)
auf den Fall. Ausgewertet mit `llvm-objdump` auf `work/elf/main.patched.elf`:

| Fälle | Anzahl | Bedeutung |
|---|---|---|
| Rücksprung mit 1 ohne Aufruf (`0x2D60154`) | 484 | im Original ohne Wirkung (z. B. `LAST_KEYWAIT`, `AC_*`, `ACMD_END`, `TRAINER_LOSE*`, `BOARD_*`-Reste, VM-Register 5–18) |
| gleiche Handler | – | `22=28` (CALL), `23=29` (RET), `32=34`, `33=35`, `70=83` (TALKMSG), `81=82`, `1=3` (END), `168=171=3`-Pfad, `169=172=173=174` (Sprung auf Label), `285=286`, `555=556` |
| übrige | 750 | echter Handler (Kernbefehl oder Host) |

Die `AC_*`-Befehle sind deshalb keine eigenen Befehle: sie stehen als Daten in Bewegungsskripten, die `OBJ_ANIME` an das Objekt übergibt (`EvEntityCommand.SetScriptMoveData`); der Interpreter reicht die Befehlsliste unverändert an den Host.

## 3. Prüfstufen

- **[P]** Handler-Pseudocode gelesen (Ghidra `-readOnly`, Funktionen `Dpr_EvScript_EvDataManager$$…`, `FlagWork`, `TrainerWork`, `MoneyWork`).
- **[T]** nur aus der Sprungtabelle (kein Aufruf = No-Op; gleiche Adresse = gleicher Handler).
- **[N]** nur Name und Argumentform (`scripts/evscript_stats.py`, Aufrufliste des Handlers); Wirkung vermutet.
- **[O]** Orakel (laufendes Original oder Emulator): **für keinen Befehl vorhanden**; deshalb sind alle Aussagen über Anzeige, Dauer und Reihenfolge im Spiel ungeprüft.
- **[A]** Annahme.

## 4. Kernbefehle (im Interpreter umgesetzt)

Argumente ab 1 gezählt. `v` = `val` (Work/Float), `W` = Ziel-Work (roh), `L` = String-Label.

| Kennung | Name | Anz. | Stufe | Wirkung / Argumente |
|---|---|---|---|---|
| 3, 1, 168, 171 | END, NOP, SP_EVENT_DATA_END, SCENE_CHANGE_END | 7 389 | [P] | Ereignis beenden |
| 24 | JUMP | 5 059 | [P] | `L` |
| 28, 22 | CALL, CHG_COMMON_SCR | 1 404 | [P] | `L`; Stapel push |
| 29, 23 | RET, CHG_LOCAL_SCR | 1 992 | [P] | Stapel pop; leer → Ereignis endet |
| 32, 34 | IFVAL_JUMP, IFWK_JUMP | 3 096 | [P] | `v1, "EQ…", v2, L` |
| 33, 35 | IFVAL_CALL, IFWK_CALL | 1 532 | [P] | wie oben, mit Aufruf |
| 36, 37 | SWITCH, CASE_JUMP | 966 | [P] | SWITCH merkt Work-Index; CASE_JUMP `v, L`: springt, wenn `Work[merk] == v` |
| 30, 31 | IF_JUMP, IF_CALL | 1 | [P] | `"EQ…", L` gegen `_cmp_flag` |
| 60, 61, 62 | LDVAL, LDWK, LDWKVAL | 2 958 | [P] | `W = v` |
| 58, 59 | ADD_WK, SUB_WK | 173 | [P] | `Work[a] = Work[a] ± v(b)` |
| 4 | TIME_WAIT | 756 | [P] | `v` Frames (÷30 s), `W`: 1 solange gewartet, danach 0 |
| 41, 43, 50 | FLAG_SET, FLAG_RESET, FLAG_SET_WK | 1 937 | [P] | Flag roh bzw. über Work; −1 ignoriert |
| 42, 873, 874 | ARRIVE_FLAG_SET, SET_SYS_FLAG, RESET_SYS_FLAG | 259 | [P] | Systemflag roh (auch bei String-Argument wird `data` als Index benutzt, 12 Fälle); danach Abzeichenzahl = Summe der Flags 0x7C–0x83 |
| 45–48 | IF_FLAGON/OFF_JUMP/CALL | 1 159 | [P] | Flag/Systemflag, `L`; Index −1/4000 zählt als „aus“ |
| 51–53 | TRAINER_FLAG_SET/RESET/CHECK | 149 | [P] | Trainer als Float, Work oder `TrainerID`-Name (String → `ResolveTrainerId`); CHECK setzt `_cmp_flag = Sieg && !sucht` |
| 54–57 | IF_TR_FLAGON/OFF_JUMP/CALL | 27 | [P] | `_cmp_flag = Sieg`, dann Sprung/Aufruf |
| 70, 83 | TALKMSG, TALK_KEYWAIT | 4 842 | [P] | `"datei%label"` (Trennung an `%`), optional `v` (== 1 → Flag). Host öffnet Fenster, Befehl wartet bis fertig |
| 81, 82 | TALK_CLOSE, TALK_CLOSE_NO_CLEAR | 2 525 | [P] | `Work[199] = 0`, Fenster schließen |
| 84, 85 | EASY_OBJ_MSG, EASY_MSG | 544 | [P] | Makro: (TALK_OBJ_START,) TALKMSG, Fenster schließen, (TALK_OBJ_END); jede Stufe kostet einen Frame |
| 96 | YES_NO_WIN | 265 | [P] | `W`, optional `v` (== 1: „Ja“ vorgewählt); Ergebnis = Index im Menü → `Work[W]`; Zuordnung 0 = Ja ist **[A]** |
| 821, 822 | ADD_CUSTUM_WIN_LABEL, OPEN_CUSTUM_WIN | 639 | [P] | Zeile `"datei%label"` mit Rückgabewert `v` (Standard: laufende Nummer); OPEN `W`: `Work[W] = Rückgabewert[Auswahl]` |
| 136, 140 | OBJ_ANIME, OBJ_ANIME_WAIT | 3 587 | [P] | `Objekt(String oder Index), Label[, v Tempo]`; Skript im selben File; WAIT optional Objektname, leer = alle |
| 169, 172–174 | SCENE_/FLAG_/OBJ_/INIT_CHANGE_LABEL | 59 | [P] | Sprung auf `L` |
| 170 | SCENE_CHANGE_DATA | 154 | [P] | `v1, v2, L`: bei Gleichheit **CALL** |
| 175, 176, 177, 1207 | ADD_GOLD, SUB_GOLD, COMP_GOLD, GET_GOLD | 55 | [P] | `MoneyWork.Add(±v)` (0…999 999); COMP: `W = (v ≤ Geld)`; GET: `W = Geld` |
| 189–192 | ADD_ITEM, SUB_ITEM, ADD_ITEM_CHK, ITEM_CHK | 223 | [P] | `Item, Anzahl, W`; ADD/SUB schreiben 1; CHK: `W = IsAddItem`; ITEM_CHK: `W = (Anzahl ≤ vorhanden)` |
| 187 | FLD_ITEM_EVENT | 308 | [P], Label [A] | `Work[0xF2] = v1`, `Work[0xF3] = v2`, Sprung auf eine feste Label-Konstante; in den Daten passt nur `ev_fld_item2` |
| 285, 286 | MAP_CHANGE, MAP_CHANGE_NONE_FADE | 109 | [P] teilweise | `ZoneName(String), Locator`; gleicher Handler. Ablauf nach dem Setzen der Felder nur im Kopf gelesen; Host wartet bis Kartenwechsel fertig |
| 335 | TRAINER_BTL_SET | 131 | [P] | Trainer1 (`TrainerID`-Name), Trainer2 optional; Original: Rückkehrposition merken, Ereignis beenden, nach dem Kampf dort fortsetzen. Interpreter: wartet bis `BattleIsDone` (gleiche Wirkung für den Host) |
| 555, 556 | GET_RND, GET_RND_NEXT | 81 | [P] | `W = Random.Range(0, v)` |

## 5. Wichtige Host-Befehle (Auswahl der häufigsten; 599 Kennungen insgesamt)

Diese Befehle gehen an `IEvHost.ExecuteCommand(call)` (`true` = fertig, sonst Wiederholung mit wachsendem `Phase`). Stufe [N], außer wo [P] steht (Aufrufliste des Handlers gelesen, Verhalten daraus abgeleitet).

| Kennung | Name | Anz. | Stufe | Erwartetes Host-Verhalten |
|---|---|---|---|---|
| 153, 156, 157 | TALK_OBJ_END, TALK_END, EVENT_END | 2 276 | [P] | `Cmd_ObjPauseClearAll`: Objekte fortsetzen (`MVCodeRestart`), Eingabe aktiv |
| 151, 152, 154 | TALK_OBJ_START(_TURN_NOT), TALK_START | 697 | [P] | Spieler und Gesprächspartner zueinander drehen (Hals), alle Objekte anhalten, Auswahl-Ton |
| 155 | EVENT_START | 396 | [P] | Poketch ausblenden, Objekte anhalten |
| 942, 943 | EVENT_CAMERA_INDEX, EVENT_CAMERA_END_WAIT | 1 127 | [N] | Ereigniskamera (`EventCameraTable`); `943` wartet auf Ende |
| 507, 503, 506, 505 | SXY_EXIT_POS_CHANGE, SXY_POS_CHANGE, SXY_DIR_CHANGE, SXY_MV_CHANGE | 937 | [P] | Objekt (Name) auf Gitterposition/Richtung setzen (`gridPositionDirect`, `SetYawAngleDirect`) |
| 146, 147 | OBJ_ADD, OBJ_DEL | 606 | [P] | Objekt (Name/Index) ein-/ausblenden; DEL setzt zusätzlich ein Flag |
| 1062 | OBJ_POS_CHANGE_WORLD | 150 | [N] | Objekt auf Weltposition |
| 158, 159, 161, 813 | PLAYER_POS_GET, OBJ_POS_GET, PLAYER_DIR_GET, GET_REL_POS_HERO | 233 | [P] | Gitterposition → zwei Work-Werte |
| 283, 284, 784, 836 | BLACK_OUT, BLACK_IN, FADE_WAIT, FADE_SPEED | 584 | [P] | Überblendung schwarz (`Fader.FadeOut/FadeIn`); FADE_WAIT wartet |
| 306, 307, 308, 310, 314, 318 | PLAYER_NAME, RIVAL_NAME, SUPPORT_NAME, ITEM_NAME, NUMBER_NAME, NICK_NAME | 898 | [P] | Platzhalterwort `slot` für den nächsten Text setzen (`MessageWordSetHelper`) |
| 479, 448 | GET_MY_SEX, SYS_FLAG_BADGE_GET | 152 | [P]/[N] | Work-Wert aus Spielerdaten/Systemflag |
| 92, 93 | EASY_BOARD_MSG, EASY_INFOBOARD_MSG | 181 | [N] | Tafeltext (Schild/Infotafel) |
| 109, 111, 112–116, 118… | SE_*, ME_*, VOICE_*, BGM_* | 963 | [N] | **Ton: wird nicht umgesetzt** (Regel „kein Sound“); Host liefert sofort `true` |
| 829, 830, 831 | HIT_DOOR_ANIME(_WAIT), SET_DOOR_OBJ | 213 | [N] | Türanimation |
| 981, 982, 1102, 1143, 881, 880 | CHARA_LOOK_*, OBJ_ANIME_SPEED, SET_FORCE_BLINK, AC_ANIM_* | 497 | [N] | Blick/Tempo/Animation von Objekten |
| 1052, 1053, 1054, 1161 | CALL_EFFECT, STOP_EFFECT, RELEASE_EFFECT, EFF_SCALE | 326 | [N] | Effekte (`EffectDatabase`) |
| 563, 216, 194 | TEMOTI_POKE_CHK, CB_ITEM_NUM_ADD, GET_POCKET_NO | 139 | [N] | Team-/Beutelabfragen mit Work-Ergebnis |

Familienübersicht aller 599 benutzten Host-Kennungen (Kennungen / Befehle): Objekte, Bewegung, Türen 65 / 6 916; Kamera 15 / 1 319; Ton 16 / 963; Namenswörter 51 / 829; Überblendung 9 / 615;
Menüs, Fenster, Tafeln 42 / 539; Pokémon, Team, PC, Zukan 99 / 548; Effekte 5 / 330; Kampf, Trainer 46 / 262; Beutel 22 / 157; Karte, Zone, Fortbewegung 34 / 139;
Untergrund, Union, Netz, Wettbewerb, TV 23 / 124; übrige 172 / 882.

## 6. Zahlen (echte Daten, nur Zähler)

Quelle: `scripts/evscript_stats.py` (Befehlshäufigkeit) und der lokale Lauf `work/dotnet-evscript/check` (`dotnet run`).

| Messgröße | Wert |
|---|---|
| Dateien / Skripte / Befehle (ohne 4 leere) | 856 / 13 139 / 64 741 |
| verschiedene Kennungen in den Daten | 866 (+ Platzhalter −1) |
| davon Kern / ohne Wirkung / Host | 61 / 206 / 599 |
| Befehle: Kern / ohne Wirkung (inkl. 88 × −1) / Host | 42 379 (65,5 %) / 8 739 (13,5 %) / 13 623 (21,0 %) |
| Skripte ohne jeden Host-Befehl (statisch) | 8 095 von 13 139 (61,6 %) |
| Labels / doppelte Labels | 12 985 / 154 |
| Häufigste 10 Kennungen decken | 46,8 % aller Befehle (END, JUMP, TALKMSG, IFVAL_JUMP, LDVAL, TALK_CLOSE, OBJ_ANIME, RET, ACMD_END, TALK_KEYWAIT) |
| Lauf mit Mock-Host (alle Variablen 0, jede Host-Abfrage einmal „noch nicht“): beendet | 12 778 |
| nach 2 000 Updates noch wartend (Dialogschleifen mit konstanten Mock-Antworten: TALKMSG, TIME_WAIT, Kamera, Menüs) | 361 |
| Fehler / unbekannte Befehle | 0 / 0 |
| Skripte mit mindestens einem fehlenden Sprungziel (trotz aller geladenen Dateien) | 54 (59 Stellen); das Original ignoriert sie ebenfalls |
| ausgeführte Befehle im Lauf | 1 713 776 (Kern 1 174 715, ohne Wirkung 152 438, Host 386 623); 61 von 61 benutzten Kernkennungen ausgeführt |

„Läuft ohne unbekannten Befehl“ heißt hier: jede Kennung ist Kern, ohne Wirkung (Tabelle) oder an den Host delegiert. Es sagt nichts darüber, ob der Host die 599 delegierten Befehle richtig ausführt.

## 7. Aufbau in C# (`Xnu.EvScript`)

| Datei | Inhalt |
|---|---|
| `EvCmdId.cs` | Kennungen der Kernbefehle, Sonder-Work-Indizes |
| `EvCommandTable.cs` | Einordnung `Core / NoOp / Host` (NoOp-Menge aus der Sprungtabelle), `Classify(id)` |
| `EvScriptBook.cs` | geladene `EventScriptFile`s (aus `Xnu.Data.MasterData2Reader.LoadEventScripts`), globales Label-Verzeichnis (ohne Groß-/Kleinschreibung, erste Datei gewinnt **[A]**) |
| `EvInterpreter.cs` | Zustandsmaschine: `Start(label)`, `Update(dt)` → `Idle/Waiting/Ended/Error`, `Abort()`, Statistik (`EvRunStats`) |
| `IEvHost.cs` | Host: Text, Auswahl, Kampf, Kartenwechsel, Objektbewegung, Beutel/Geld, Hilfen, generischer `ExecuteCommand`, `EventEnded` |
| `EvVariables.cs` | `IEvVariables`; `EvMemoryVariables` (Tests) und `EvSaveVariables` (liest/schreibt den `SaveData.Buffer`) |
| `EvMockHost.cs` | Host ohne Spielwelt (für Tests und Massenläufe) |

Abweichungen vom Original, bewusst: Fehler (fehlendes Argument, Index außerhalb) führen zu `EvStatus.Error` statt zu einer Ausnahme; `TRAINER_BTL_SET` beendet das Ereignis nicht, sondern wartet (Host startet den Kampf und
meldet das Ende); `MAP_CHANGE` wartet analog. Wer den Zustand über einen Szenenwechsel speichern muss, kann den Interpreter im Speicher behalten (Position und Stapel sind darin).

## 8. Annahmen

- **[A] Story-Reihenfolge der ersten Strecke:** nicht bestätigt. Die Skripte der Strecke (Kartenkürzel `t01*`, `d27*`, `sp_*`, Szenen-Work `WK_SCENE_T01R0101…`) wurden nicht der Reihe nach ausgeführt; welche Skripte beim Start laufen
  (`SCENE_CHANGE_LABEL`, `INIT_CHANGE_LABEL` je Karte) und in welcher Reihenfolge Work-Werte entstehen, ist nicht belegt.
- **[A]** Auswahlindex im Ja/Nein-Menü: 0 = „Ja“. Die Rückrufe (`DisplayClass460/461`) schreiben den Menüindex unverändert in den Work.
- **[A]** `FLD_ITEM_EVENT` springt auf `ev_fld_item2` (Label-Konstante nicht aufgelöst).
- **[A]** Doppelte Labels, Groß-/Kleinschreibung, Alias-Zeichenketten der Vergleichsarten, Trainer-Layout im Save (Abschnitt 2).
- **[A]** Trainer-Namen (`TrainerID`-Enum, 709 Werte im Dump) entsprechen den String-Argumenten (`LEADER3_01` usw.): die Suche im Original vergleicht den Enum-Namen; `ResolveTrainerId` muss diese Tabelle liefern (Quelle `dump.cs`, nicht im Repo).
- Auffälligkeiten im Original: `TALKMSG` ohne `%` im Namen (43 + 21 + 14 + 2 Fälle) würde im Original beim Aufteilen scheitern; der Interpreter nimmt dann den ganzen String als Dateinamen und Label `""`.
  `FLAG_CHECK_WK` (49, ungenutzt) liefert verkehrt herum (1 = Flag nicht gesetzt).

## 9. Lücken und Aufwand

| Lücke | Aufwand (Schätzung) |
|---|---|
| Host für die Strecke bis zum ersten Kampf: Text (`Xnu.Text`), Objekte, Kartenwechsel, Kamera, Überblendung, Namenswörter, Gitterbewegung aus `AC_*` | 3–5 Tage (größter Posten: Anbindung an Feld und Text) |
| restliche 599 Host-Kennungen prüfen (Wirkung je Gruppe aus dem Pseudocode lesen; Ghidra-Export ist für alle `EvCmd*` vorhanden) | 2–3 Tage je Hauptgruppe, die ersten 60 Kennungen decken 77 % der Host-Befehle ab |
| Kampf: Trainer-ID aus Namen, `BattleTrainer`-Vorbereitung (Sichtkampf-Gruppen, `Btl_TrainerType1/2`), Rückkehr nach Niederlage (`TRAINER_LOSE*` sind im Original ohne Wirkung, der Verlust läuft über `BattleReturn`) | 2 Tage |
| `MAP_CHANGE`-Ablauf im Detail (Pseudocode nur bis zum Setzen der Felder gelesen), Zonen-/Locator-Auflösung mit `MapWarp` | 1 Tag |
| Startlogik: wann das Spiel welches Label startet (`PlaceData.TalkLabel`, `StopData.ContactLabel`, `MapWarp.ScriptLabel`, `ScriptStartCheck`, `SpLabel_*`, `CheckSceneChangeLabel`) | 2–3 Tage |
| Orakel [O] für Dialog- und Bewegungsabläufe (Zeitverhalten, Frame-Genauigkeit) | nicht möglich ohne laufendes Original |
| Multi-Trainer (`TRAINER_MULTI_BTL_SET`), Beutelvarianten (`ADD_GOODS` usw.), Shops, Untergrund, Union, Wettbewerb | später, nicht für die erste Strecke nötig |
| Test im Unity-Runner, `.meta`-Dateien | 15 Minuten, sobald der Editor frei ist |

## 10. Reproduktion

- Statistik: `python3 scripts/evscript_stats.py 70` (schreibt `work/evscript/stats.json`).
- Pseudocode: `ExportDecompiled.java` (Regex `^Dpr_EvScript_EvDataManager\$\$` usw.) und `DecompAt.java` für die Fälle der Sprungtabelle (Ghidra `-readOnly`, `-noanalysis`, Heap ≤ 6 GB, Sperre `work/ghidra.lock`).
- Sprungtabelle: `llvm-objdump -d` auf `work/elf/main.patched.elf`, Bereich `0x2C5B290–0x2C60250`; Tabelle `0x3DDAB7C` (Datei-Offset über die Programmköpfe).
- Tests: `dotnet test work/dotnet-evscript/EvScript.csproj` (Wegwerfprojekt, nicht im Repo; Kopie gegen die Unity-Quellen: `UnityCheck.csproj`).
- Echtdatenlauf: `cd work/dotnet-evscript/check && dotnet run`.
