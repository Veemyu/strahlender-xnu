# Handler-Liste (Kampf, Scheibe 3)

Priorisierte Liste der Fähigkeits-, Item- und Attacken-Handler des Kampfsystems. Alles in eigenen Worten; es stehen nur IDs, interne
Handler-Kürzel (Codebezeichner) und Zahlen darin, keine Texte oder Spielinhalte. Die Zahlen stammen aus `work/masterdata` und
`work/decomp/battle_all` (lokal, nicht im Repo) und lassen sich mit den Skripten in Abschnitt 5 neu erzeugen.

## 1. Vorgehen

1. **Nummer → Handler-Tabelle.** `scripts/battle_handler_map.py` führt die echten `.cctor` der Handler-Klassen im Orakel aus, liest
   `GET_FUNC_TABLE` (Nummer → `ADD_*`-Funktion), ruft jede `ADD_*`-Funktion auf und ordnet den zurückgegebenen Tabellenzeiger den
   statischen `HandlerTable_*`-Feldern zu. Ergebnis (`work/battleevents/handler_map.json`): Tokusei 241 Nummern → 222 Tabellen,
   Item 197 → 193 (eine Nummer ohne Tabelle), Waza 310 → 262, Seite 22, Feld 10 (8 mit Tabelle), Position 5, Default-Powerup 3, Raid-Boss 1.
   Mehrere Nummern teilen sich oft eine Tabelle (z. B. Tokusei 37 und 74, Item 298–313 mit je einer Typ-Konstante).
2. **Häufigkeit.** `scripts/battle_handler_priority.py` zählt aus den Stammdaten: Fähigkeiten je Art (`PersonalTable`, Slots 1–3, Arten-Zeilen)
   und je Trainer-Team-Platz (`TrainerTable.TrainerPoke`); Items als Wildtier-Item (Arten-Zeilen) und als Trainer-Item; Attacken als
   Lernlisten-Einträge (`WazaOboeTable`, je Art einmal) und als Trainer-Attacke. Spalte „Nutzung“ unten: `Arten/Trainer`.
3. **Einfachheit.** Der Pseudocode jeder Handler-Funktion (samt Hilfsfunktionen der Klasse) wird nach Fremdaufrufen durchsucht. **Rein** heißt: nur
   `Common.GetEventVar/MulEventVar/RewriteEventVar`, Lesezugriffe auf das Pokémon (`BTL_POKEPARAM.*`), Wetter-/Feld-/Freund-Abfragen und
   Rechenhilfen. Diese Handler laufen im Orakel mit nur gestubbten Abfragen. **Unrein** sind Handler mit Wirkungsebene (Meldungen
   `Common.Message`, `RankEffect`, `AddSick`, `Damage`, `UseItem`, `ConsumeItem`, `SetRecallEnable` …).

Ergebnis: Tokusei 64 von 241 Nummern rein, Item 80 von 197, Waza 57 von 310. Alle reinen mit ≤ 60 Zeilen und einige längere Waza-Handler
sind umgesetzt; offen bleiben vor allem die Handler mit Wirkungsebene (Abschnitt 3 und 4).

## 2. Umgesetzt (175 Nummern)

Prüfstufe **[OK]**: die echte ARM64-Funktion läuft im Orakel gegen die C#-Funktion, Pokémon-/Feldabfragen sind Stubs (Spezifikation 3, Abschnitt 3).
Zeilen = Zeilen Pseudocode des Handlers.

### 2.1 Fähigkeiten (54 Nummern, davon 4 aus Scheibe 2)

| Nr. | Handler | Ereignis | Zeilen | Nutzung |
|---|---|---|---|---|
| 1 | Akusyuu | 133 | 38 | 7/7 |
| 4, 75 | KabutoArmor | 67 | 29 | 8/6, 14/1 |
| 8, 81 | Sunagakure, Yukigakure | 64 (155 offen) | 56 | 17/9, 6/2 |
| 14 | Fukugan | 64 | 29 | 5/1 |
| 32 | TennoMegumi | 102, 125, 133, 205 | 59 | 9/9 |
| 33, 34 | Suisui, Youryokuso | 19 | 47, 55 | 32/71, 25/9 |
| 37, 74 | Tikaramoti | 74 | 38 | 3/4, 2/25 |
| 47 | AtuiSibou | 74 | 38 | 19/43 |
| 69 | Isiatama | 101 | 29 | 18/76 |
| 77 | Tidoriasi | 64 | 40 | 7/4 |
| 79 | Tousousin | 70 | 55 | 10/0 |
| 86, 126 | Tanjun, Amanojaku | 114 | 39 | 3/3, 2/0 |
| 89 | TetunoKobusi | 70 | 40 | 5/3 |
| 91 | Tekiouryoku | 84 | 38 | 5/2 |
| 92 | SkillLink | 66 | 29 | 4/0 |
| 97 | Sniper | 90 | 38 | 12/8 |
| 98 | MagicGuard | 156 | 29 | 6/9 |
| 101 | Technician | 70 | 37 | 12/11 |
| 105 | Kyouun | 67 | 31 | 6/3 |
| 132 | NakamaIsiki | 90 | 38 | 5/0 |
| 134, 135 | HeavyMetal, LightMetal | 151 | 29 | 5/0 |
| 136, 231 | MultiScale | 90 | 40 | 2/0 |
| 137, 138 | Dokubousou, Netubousou | 70 | 47 | 1/0, 2/3 |
| 146, 202 | Sunakaki (155 offen), Yukikaki | 19 | 56, 38 | 2/0 |
| 147 | MilacreSkin | 64 | 44 | 3/0 |
| 162 | GoodLuck | 64 | 31 | 0/0 |
| 169 | FurCoat | 75 | 38 | 0/0 |
| 177, 205 | HayateNoTsubasa, HealingShift | 17 | 48, 43 | 0/0 |
| 181 | KataiTume | 70 | 38 | 0/0 |
| 196 | Hitodenasi | 67 | 43 | 0/0 |
| 198 | Harikomi | 74 | 42 | 0/0 |
| 200 | Haganetukai | 74 | 39 | 0/0 |
| 203, 204 | Enkaku, UruoiVoice | 42 | 29, 40 | 0/0 |
| 212 | Husyoku | 217 | 32 | 0/0 |
| 217, 249, 252 | Battery, PowerSpot, HaganeNoSeisin | 70 | 45, 38, 40 | 0/0 |
| 218 | MohuMohu | 90 | 50 | 0/0 |
| 233, 246 | BrainPrism, KooriNoRinpun | 90 | 38 | 0/0 |
| 247 | Jukusei | 140 | 30 | 0/0 |
| 239, 242 | ScrewObire | 46, 225 | 58 | 0/0 |

Abdeckung: 21,3 % der Arten-Fähigkeiten-Einträge und 20,4 % der Trainer-Team-Plätze. Die meisten der häufigen Fähigkeiten haben eine Wirkung
(Nr. 22: 20/124, Nr. 39: 22/99, Nr. 26: 59/62 …, Abschnitt 3).

### 2.2 Items (73 Nummern, davon 4 aus Scheibe 2)

| Familie | Nummern | Ereignis | Handler |
|---|---|---|---|
| Typ-Verstärker (Kraftverhältnis nach Item-Wert, je eine Typ-Konstante) | 222, 233, 237–244, 246–251, 254, 298–315, 317, 318, 644 (38) | 70 | `common_PowerUpSpecificType` |
| Wetter-Steine (Wetterdauer = Item-Wert) | 282–285 | 152 | `common_WazaWeatherTurnUp` |
| Treffer-Verhältnisse | 213, 255 (Faktor 100 − Item-Wert), 265, 276 | 64 | HikarinoKona, NonkiNoOkou, KoukakuLens, FocusLens |
| Volltreffer-Stufe | 232, 326 (+1), 256, 259 (Art-gebunden, +2) | 67 | PintLens, LuckyPunch, Naganegi |
| Art-gebundene Verstärker | 226, 227 (Art 366), 258 (Art 104/105), 257, 274 (Art 132, nicht verwandelt), 225 (Art 380/381) | 74, 75, 19, 70 | SinkaiNoKiba … KokoroNoSizuku |
| Initiative/Gewicht ×0,5 | 215, 289–294 (19), 539 (151) | 19, 151 | KyouseiGipusu, PowerXXX, Karuisi |
| Sonstige | 266, 267, 268, 296, 543, 640, 1123, 879 | 70, 90, 174, 78, 75, 150, 210 | je ein Handler |

Abdeckung: 54,3 % der Wildtier-Item-Einträge, 29,7 % der Trainer-Items. Die häufigsten offenen Trainer-Items (158, 157, 150 Beeren; 275; 270 Rückstoß;
234; 217; 273 …) sind Wirkungs-Handler (Item-Verbrauch).

### 2.3 Attacken (48 Nummern)

Nur Sondereffekte; Standardwirkungen stehen in der `WazaTable` (Abschnitt 4).

| Nr. | Handler | Ereignis | Zeilen | Nutzung (Lernliste/Trainer) |
|---|---|---|---|---|
| 89 | Jisin | 189, 90 | 80 | 34/76 |
| 371, 372 | Sippegaesi, Dameosi (Kraft ×2) | 69 | 42 | 35/41, 27/10 |
| 474 | BenomShock | 70 | 42 | 12/28 |
| 74 | Seityou | 113 | 57 | 37/22 |
| 246, 702 | GensiNoTikara | 113 | 38 | 53/17 |
| 23, 34, 407 | Fumituke | 62, 90 | 84 | 23/19, 31/17, 10/6 |
| 86 | Denjiha | 77 | 29 | 34/17 |
| 16, 239 | Tatumaki | 189, 69 | 80 | 27/16, 12/10 |
| 473, 540, 548 | PsycoShock | 72 | 39 | 8/16 |
| 213 | Meromero | 54 | 46 | 12/14 |
| 234–236 | AsaNoHizasi (Heilwert je Wetter) | 177 | 47 | 6/5, 24/10, 12/13 |
| 46, 18 | Hoeru | 203 | 41 | 25/11, 17/4 |
| 57 | Naminori | 189, 90 | 80 | 17/11 |
| 59 | Fubuki | 62 | 38 | 21/9 |
| 101, 69 | TikyuuNage (Schaden = Level) | 88 | 34 | 20/8, 26/2 |
| 162, 717 | IkariNoMaeba (halbe KP des Ziels) | 88 | 44 | 5/6 |
| 512 | Acrobat | 69 | 40 | 8/5 |
| 492 | Ikasama | 71 | 31 | 8/3 |
| 206, 610 | Mineuti | 143 | 38 | 12/2 |
| 573 | FreezDry | 78, 79 | 38 | 3/2 |
| 776 | BodyPress | 73 | 29 | 2/1 |
| 329 | ZettaiReido | 65 | 40 | 11/0 |
| 599, 602, 674 | BenomTrap, ZibaSousa | 113 | 42 | 7/0, 5/0 |
| 744, 781, 782 | DaiMaxHou | 90 | 42 | 0/0 |
| 533, 663 | NasiKuzusi | 63, 72 | 58 | 0/0 |
| 659 | Sunaatume | 177 | 41 | 0/0 |
| 745 | NeraiUti | 46, 225 | 58 | 0/0 |
| 754, 755 | DengekiKutibasi | 69 | 42 | 0/0 |
| 788 | Newton | 70 | 40 | 0/0 |

Abdeckung: 13,9 % der Lernlisten-Einträge, 12,7 % der Trainer-Attacken.

## 3. Priorität der offenen Handler

| Rang | Gruppe | Umfang (Nummern) | Voraussetzung |
|---|---|---|---|
| 1 | Reine Handler mit > 60 Zeilen: Tokusei 96, 109, 244, 84, 159, 174, 178, 182, 184, 206; Item 112, 135, 136, 278; Waza 87, 167, 210, 283, 542, 560, 751, 783 | Tokusei 10, Item 4 (+ 4 Platzhalter), Waza 8 | keine (nur Abfragen) |
| 2 | Wirkungs-API: `Common.Message`, `TokuseiWindow_In/Out`, `RankEffect`, `AddSick`, `CureSick`, `Damage`, `RecoverHP` | 58 Tokusei-, 74 Waza-Handler mit Meldungen; 28 mit Stufenwirkung | Section-Ebene (nächste Scheibe) |
| 3 | Item-Verbrauch (`UseItem`, `ConsumeItem`, `SetRecallEnable`): Beeren, Schärpe, Reste | ca. 50 Items | Item-Verbrauch, Beeren-Daten |
| 4 | Seiten-, Feld- und Positionseffekte | 22 + 10 + 5 | Wetter-/Feld-Verwaltung |
| 5 | Attacken mit Raid-Boss-/G-Wall-Abfragen (`GetRaidBossParam`, `GWall.IsActive`) | ca. 40 | Raid-Boss, G-Modus |

Häufigste offene Fähigkeiten nach Trainer-Nutzung: 22 (124), 39 (99), 26 (62), 51 (48), 38 (43), 9 (40), 5 (37), 68 (37), 28 (33), 41 (27), 114 (27),
109 (27, rein, 103 Zeilen), 62 (25), 61 (25).

## 4. Warum viele Handler fehlen (Befund)

- Handler mit Wirkung rufen `Common.Message`/`StrParam` (Meldungen) und `Section_FromEvent_*`-Beschreibungen: 58 Tokusei-, 74 Waza- und etwa 70
  Item-Handler hängen daran. Ohne Section-Ebene lässt sich ihr Ergebnis nicht gegen das Orakel prüfen.
- Attacken ohne Handler (286 der 512 gültigen Attacken) laufen ausschließlich über die Tabelle (`WazaTable`): Kraft, Treffer, Priorität (35 Attacken mit
  Priorität ≠ 0), Statuswert-Änderungen und Zustände (195 Attacken) stehen dort und werden von den Rechnern aus Scheibe 1 und den Sections gelesen.
  Es gibt keinen „Prioritäts-Handler“ je Attacke; nur `GET_WAZA_PRI` (Ereignis 17, z. B. Fähigkeiten 177/205) verändert die Priorität im Handler.

## 5. Reproduktion

```
PYTHONPATH=tools/pydeps python3 scripts/battle_handler_map.py        # Nummer -> Tabelle -> Handler (work/battleevents/handler_map.json)
python3 scripts/battle_handler_priority.py                          # Häufigkeit x Einfachheit (work/battleevents/handler_priority.json)
python3 scripts/battle_pseudo_view.py Tokusei 0x1a3f7b0             # Pseudocode ohne IL2CPP-Rauschen (nur Ausgabe)
```
