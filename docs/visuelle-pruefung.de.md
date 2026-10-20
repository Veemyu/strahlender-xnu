# Automatische Sichtprüfung (Screenshots, Vergleich, Ryujinx-Referenz)

Stand: 2026-10-19, 14:40. Ziel: Bilder der Unity-Szenen entstehen und werden **automatisch** verglichen, nicht mehr von Hand. Ein Befehl:

```
scripts/visual_auto.sh run            # Aufnahme -> Vergleich mit der Baseline -> Bericht + Kontaktbögen
```

Bilder, Berichte und Referenzen liegen nur unter `work/` (gitignoriert); im Repo stehen Skripte, Szenarioliste, Routen und diese Beschreibung. Kein Ton: nichts spielt etwas ab (Tests und Skripte nur mit synthetischen Bildern).

**Stand der Lieferung (ehrlich, 15:30):** Vergleich, Anomalie-Detektor, Berichte, Kontaktbögen, Szenarioliste, Orchestrierung, Referenzimport (Ryujinx und Rekompilation) und Tasten-Spieler sind fertig und getestet (Python-Tests, Trockenläufe, echter F8-Test auf dem Ryzen). Der **Aufnahmecode im Unity-Editor** (`Xnu.Visual.Capture`) läuft im **Labor-Editor** (`work/unity-shader-lab`, Kopie unter `Assets/XnuSrc/Visual/Editor/`): `XNU_UNITY_PROJECT=$PWD/work/unity-shader-lab scripts/visual_auto.sh run …` nahm 11 Feldszenarien in 30 s auf (Zonen 24, 27, 422, 425, 54, 367, 167, 168), verglich und schrieb Berichte und Referenzvergleiche. Die Quelle bleibt `work/visual/phaseB/`; in `unity/Assets` kommt sie erst nach Freigabe (Abschnitt 7). Bis dahin endet `visual_auto.sh run` im Haupteditor mit Exit-Code 4.

## 1. Befehle

| Befehl | Wirkung |
|---|---|
| `scripts/visual_auto.sh run [--quick] [--only a,b] [--mode editor\|player\|ipad] [--strict] [--ref]` | Aufnahme, Vergleich, Bericht `work/visual/auto/run-<Zeit>/report.md`. `--quick`: nur Szenarien mit Tag `quick` (4 Feldbilder, ca. 1–2 Minuten). Exit 0 = keine Regression, 1 = Regression, 2 = Fehler, 4 = Aufnahmecode fehlt |
| `scripts/visual_auto.sh compare [--run LAUF\|latest] [--ref [ryujinx\|recomp\|both]]` | nur Vergleich eines vorhandenen Laufs; `--ref` ergänzt den Referenzvergleich (Ryujinx-F8-Bilder, Rekompilation, beide) |
| `scripts/visual_auto.sh accept [LAUF]` | Lauf als **neue Baseline** übernehmen (`work/visual/auto/baseline/`, alte nach `baseline.alt/`). **Erst nach Sichtung** der Kontaktbögen durch den Hauptagenten/Nutzer |
| `scripts/visual_auto.sh watch [--interval MIN] [--once]` | alle N Minuten (Standard 10) laufen, wenn sich `unity/Assets/Scripts/{Field,Render}` oder `scripts/shader_*` geändert haben |
| `scripts/visual_auto.sh ref [--fetch] [--run LAUF] [--ref ryujinx\|recomp\|both]` | Referenzen holen (`--fetch`, Ryujinx) und gegen den Lauf vergleichen (Abschnitt 8); Labor-Editor: `XNU_UNITY_PROJECT=$PWD/work/unity-shader-lab` vor `run` |
| `scripts/visual_auto.sh scenarios \| test \| status` | Szenarioliste prüfen, Python-Tests, Zustand |
| `python3 scripts/visual_compare.py analyze BILD… [--kind field\|room\|ui]` | nur Anomalie-Detektor für einzelne Bilder |
| `scripts/ryujinx_fetch_shots.sh [fetch\|status\|cache\|reset]` | F8-Screenshots vom Ryzen holen (Abschnitt 8) |
| `scripts/ryujinx_record.sh ROUTE [--dry-run]` | Tastenfolge in Ryujinx abspielen und Bilder holen (Abschnitt 9) |

Aufnahmearten: **editor** (Standard: Feldszenarien über `Xnu.Visual.Capture` in `FieldTest2`, danach die Folgen der Szene `Game` im Editor-Spielmodus), **player** (macOS-Build `work/builds/macos/xnu.app`, nur Spielszene-Folgen), **ipad** (`devicectl`, nur Spielszene-Folgen; bisher nicht ausgeführt). Der Editor wird über `scripts/unity_safe.sh` (Status/Öffnen) und `unity command … eval` gesteuert; `visual_auto.sh` startet ihn nur, wenn er aus ist.

## 2. Dateien

| Datei | Aufgabe |
|---|---|
| `scripts/visual/scenarios.json` | Aufnahmeliste: 13 Feldszenarien (Standard-Testspielstand: Zone 24 zu zwei Stunden, Zone 27 Pokécenter innen; dazu 422 zu vier Stunden, 425, 54, 367 und die älteren 167 zu zwei Stunden, 168), 14 Spielszene-Bilder in zwei Folgen (`durchlauf`: Titel, Feld, Innen, Text, Auswahl, Kampf; `menue`: Menü, Team, Beutel, Bericht); 1280×720, stabile Namen, Wartezeit in Bildern (`settle_frames`), Typ (`kind`), erlaubte Flags, Schwellen je Szenario |
| `scripts/visual_scenarios.py` | prüft/exportiert die Liste (`validate`, `list`, `script FOLGE`, `export-field`, `mark-requested`) |
| `scripts/visual_compare.py` | Vergleich, Anomalie-Detektor, Bericht, Kontaktbögen, `accept`, Modus `ref` |
| `scripts/visual_ref.py` | Ryujinx-Referenz: Import/Normalisierung, Vergleich mit Heatmap, Shader-Cache-Zahlen |
| `scripts/visual_auto.sh` | Orchestrierung |
| `scripts/visual/ref_map.json` | Referenzansichten, Zuordnung zu Szenarien, Masken, Ryzen-Pfade |
| `scripts/visual/routes/*.keys` | Tastenfolgen für Ryujinx |
| `scripts/ryzen_keys.py`, `scripts/ryujinx_fetch_shots.sh`, `scripts/ryujinx_record.sh` | Tasten-Spieler (läuft auf dem Ryzen), Abholen, Aufnahme-Treiber |
| `scripts/tests/test_visual_*.py`, `test_ryzen_keys.py` | 49 Tests mit synthetischen Bildern (`scripts/visual_auto.sh test`) |
| `work/visual/phaseB/Capture.cs`, `Xnu.Visual.Editor.asmdef` | Aufnahmecode für den Editor (noch nicht in `unity/`) |

Ordner eines Laufs: `shots/<name>.png`, `capture.json` (Aufnahme, `requested` = erwartete Namen), `report.md/json`, `diff/<name>.png` (Differenz ×4), `contact/uebersicht_NN.png`, `contact/vergleich_NN.png`, bei `--ref` zusätzlich `ref_report.md`, `ref/*_heatmap.png`, `contact/ref_NN.png`.

## 3. Vergleich mit der Baseline (je Bild)

Kennzahlen: Mittel RGB (alt/neu), mittlere absolute Abweichung (MAD), Anteil geänderter Pixel (Kanalabweichung > 16), **SSIM** (eigene Implementierung, 8×8-Fenster auf der Luminanz), Laplace-Varianz (Kantenschärfe/Texturdetail) und ihr Verhältnis, Histogrammabstand, Histogramme (Luma 16, RGB je 8 Klassen) im JSON, dazu Größe geändert.

**Regression** (Exit 1), wenn eine Schwelle verletzt ist: SSIM < 0,80, MAD > 12, geändert > 25 %, Detail-Verhältnis < 0,5, Mittelwert-Verschiebung > 25, Zunahme „gerichteter Strukturen“ > 0,03 oder der größten flachen Region > 0,08, **neue** Fehlerflags gegenüber der Baseline, eine erwartete Aufnahme fehlt. Flags, die schon in der Baseline stehen, sind „bekannt“ und lösen nichts aus (so bleiben bekannte Fehler wie die weiße Figur bis zur Behebung unter Beobachtung, blockieren aber nicht). `--strict`: auch Fehlerflags von Bildern ohne Baseline sind Regressionen. Schwellen je Szenario: `thresholds` in `scenarios.json`.

## 4. Anomalie-Detektor (ohne Referenz, „heuristische Fehlerbilder“)

Bildtypen (`kind`): **field** (alle Detektoren), **room** (ohne „flach_gross“, weil Räume vor einer einfarbigen Kamerafarbe stehen), **ui** (nur leer, Mittel, Farben; Menüs haben legitime weiße Kästen).

| Flag | Erkennung | Schwelle |
|---|---|---|
| `balken` | schwarze Randspalten/-zeilen (≥ 93 % der Pixel ≤ 10) | ≥ 1,5 % der Breite/Höhe |
| `leer_konstant` | Luma-Streuung oder 5-Bit-Farbzahl | Streuung < 1,5 oder ≤ 4 Farben |
| `mittel_ausserhalb` | Luma-Mittel des Inhalts | < 10 oder > 245 |
| `magenta`, `cyan` | Pixelanteil (R,B ≥ 180 und G ≤ ⅓; bzw. G,B ≥ 180 und R ≤ ⅓) | ≥ 0,2 % |
| `weisse_flaeche` | zusammenhängende Stücke mit allen Kanälen ≥ 250, Größe ≥ 0,5 % (mind. 3000 px) und Rechteckigkeit ≥ 0,40 | Summe ≥ 0,5 % der Fläche |
| `schwarze_flaeche` | zusammenhängend, alle Kanäle ≤ 8 | Summe ≥ 4 % |
| `flach_gross` | 8×8-Blöcke mit Kanalspanne ≤ 3; größte zusammenhängende Region | ≥ 10 % der Fläche |
| `gestreckt` | Strukturtensor je 16×16-Kachel: kohärent (≥ 0,93), schräg (≥ 22° von den Achsen) | ≥ 15 % (siehe Lücken) |
| `hud_text` | helle Textglyphen-Komponenten in der linken oberen Ecke (Hinweis, kein Fehler) | ≥ 20 Stücke und ≥ 3 % hell |

Jedes Flag liefert Wert, Schwelle und Rechtecke; im Kontaktbogen sind die Fehlerflächen rot umrandet.

### Kalibrierung an den vorhandenen Bildern (`scripts/visual_compare.py analyze`)

| Bild | Flags |
|---|---|
| **Nutzer-Screenshot** `user/mac-preview-zone167.png` (bekannte Fehler) | **`balken`** (16,5 %), **`weisse_flaeche`** (2,5 %, Hüllrechteck 449–709 × 258–438, Füllgrad 0,67), **`flach_gross`** (28 % Wasser und flacher Boden), **`hud_text`** (33 Glyphen); 4 Flags |
| `z422_h12_final.png` (gut), `v3_z422_h12`, `z422_h22`, `v3_z54_h12`, `v3_z367_h12`, `v3_z425_h12` (Raum), `fieldrender/w1.png` | **keine** |
| `fieldrender/before_167.png`, `before_54.png` (vor der Korrektur) | `weisse_flaeche` (25.975 bzw. 23.771 px) + `flach_gross` |
| `fieldrender/before_422.png`, `before_425.png` | `flach_gross` (35 %), bzw. `schwarze_flaeche` (4,6 %) |
| `fieldrender/gen_167b.png` (aktuelle Korrektur) | nur `flach_gross` (13 %: das Wasser ist dunkelbraun und noch flach) |
| `fieldrender/gen_167.png` | `cyan` |
| `z425_h12.png` (alt) | `magenta` (0,34 %, Spielerfigur nach Zonenwechsel) |
| `ipad/run4/g1_innen.png` | `leer_konstant` (leeres Bild während der Überblendung) |
| Spiel-UI-Bilder (`vslice`, `ui2`, iPad) als `ui` | keine (außer `g1_innen`) |

Eingestellt wurde so, dass legitime weiße Stücke (Pokéball-Emblem 3.700 px, Füllgrad 0,22) nicht auslösen, die Fehler-Quads (24.000–31.000 px, Füllgrad > 0,65) aber sicher.

### Lücken des Detektors (ehrlich)

* **Gestreckte/verschmierte Felswände und das schräge Dreiecksband** des Nutzer-Screenshots erkennt der Detektor **ohne Referenz nicht**: Kachelkohärenz und Kantenzüge unterscheiden sie nicht von legitimen Mustern (Fischgrätpflaster in Zone 54: 8 % „gerichtete Kacheln“, Felswand im Nutzer-Bild 0,8 %). Ein Diagonalband-Detektor wurde versucht und wieder verworfen (Zaun in Zone 367 hat längere schräge Kanten). Diese Fehler werden **im Vergleich** sichtbar (SSIM, Detail-Verhältnis, Zunahme gerichteter Strukturen, Differenzbild) und im Referenzvergleich mit Ryujinx (Abschnitt 8); bleibt Aufgabe der Sichtung des Kontaktbogens.
* **Weiße Figur:** die Figur ist grauweiß, kaum von Fensterscheiben zu unterscheiden; kein Flag. Sie steht in jedem Feldbild und ist als „bekannt“ Teil der Baseline.
* Animierte Elemente (Wasser, Figur) erzeugen kleine Bildabweichungen; die Schwellen sind darauf ausgelegt.

## 5. Bericht und Agent-in-the-loop

`report.md` enthält: Zusammenfassung, Tabelle (Bild, Status, SSIM, MAD, geändert, Laplace alt→neu, Mittel RGB, Flags; fett = Fehlerflag, `*` = neu), Regressionen, Flag-Details mit Flächen und am Ende den Abschnitt **„Zur manuellen/Agenten-Sichtung“** mit den absoluten Pfaden der Kontaktbögen. Der Hauptagent öffnet sie mit dem view-Tool:

* `contact/uebersicht_NN.png`: Raster aller Bilder des Laufs (5 Reihen × 4), Fehlerflächen rot.
* `contact/vergleich_NN.png`: je Bild **Baseline | Lauf | Differenz ×4**, nach Veränderung sortiert, vier Bilder je Bogen (1248 px breit).

Ablauf: `run` → Bericht lesen → Kontaktbögen ansehen → bei Fehlern beheben, neu laufen lassen → bei Zustimmung `accept`. Die Baseline akzeptiert nur der Hauptagent nach Sichtung.

## 6. Szenarien (Auszug)

Feld (Editor, `FieldTest2`): **`field_z24_h12|h18`** (Standard-Testspielstand: Mio-Stadt/Fleetburg, Zelle 57/729, Blick oben), **`field_z27_h12`** (Pokécenter dort innen, Typ `room`), `field_z422_h07|h12|h18|h22` (Zelle 116/886, Blick oben; Tageszeit über `XNU_ENV_HOUR`), `field_z425_h12` (Spielerhaus innen, Typ `room`), `field_z54_h12` (Locator 0), `field_z367_h12` (Zelle 512/726), ältere Prüfstellen des alten Spielstands `field_z167_h12|h18` (Zelle 840/599, Pokécenter-Eingang vor Wasser und Felswand; bekannte Fehler des Nutzer-Screenshots) und `field_z168_h12`. Spielszene (`Game`, Eingabeskript wie `work/vslice/run4.txt` und `work/ui2/run1b.txt`): `game_titel`, `game_feld_z24`, `game_innen_z27`, `game_text`, `game_auswahl`, `game_nach_ereignis`, `game_kampf_befehl|attacken|meldung`, `game_menue`, `game_menue_rechts`, `game_team`, `game_beutel`, `game_bericht_frage`. Die Spielszene-Bilder entstehen mit dem Skriptbefehl `shot` (`-xnuShotDir`); die Folge endet mit `quit` (Editor: `visual_auto.sh` beendet den Spielmodus nach dem letzten Bild).

### 6.1 Standard-Testspielstand ab 14:50 (Ort aus SaveData bestimmt)

SaveData sha256 `0396a4a62735…`, Backup.bin `7a324b865ea9…`, Spielzeit 69:08:16, Mio-Stadt (japanischer Name ミオシティ; deutsche Fassung Fleetburg/Eisenach-artig). Ablageort **nicht mehr** aus `TownMapLocation` annehmen. Befund (Python-Lesen der 979.108 Byte, Vergleich mit dem Stand 69:05 und dem alten Stand der Siegesstraße):

| Feld (Offset) | alter Stand (Zone 167) | Stand 69:05 | **neuer Stand** |
|---|---|---|---|
| `zoneID` (0x5634) | 167 | 416 | **24** (`C02`, Bundle `fields/area010`) |
| `TownMapLocation` (0x8FB04 + 0x54: Zone, x, y, z) | 167, −842 / 6 / 597 | 416, −789 / 1 / 355 | 416, −789 / 1 / 355 (**veraltet**: Zone ≠ `zoneID`) |
| **PLAYER_DATA Zelle** (0x79BF4: int gx, int gy, float Höhe) | **852, 599**, 6,0 | 789, 357, 1,0 | **57, 729**, 1,0 |

Der neue Stand steht also in **Zone 24, Zelle (57, 729)**; `TownMapLocation` zeigt auf die Zone des vorherigen Aufenthalts (416) und wird in Städten nicht nachgeführt. Belege: (a) die Zelle (57, 729) liegt im Gebiet der Zone 24 (Locatoren 37–63 / 714–755), sieben Zellen unter dem Pokécenter-Locator (58, 723) – genau das zeigt der Ryujinx-Screenshot (Pokécenter oben im Bild, Spieler darunter, Hafenkran links); (b) in den beiden älteren Ständen stimmt die PLAYER_DATA-Zelle mit der Zone-Locator-Nähe überein (789/357 ≈ Locator 2 (789, 357) der Zone 416). Die Blickrichtung steht nicht im gefundenen Block (**[A]** Annahme „oben“). **Folge für den Spielkern (nicht von mir geändert):** `SavedPosition.Read` in `Game/Runtime/SaveSlotService.cs` verwirft die Position, wenn `TownMapLocation`-Zone ≠ `zoneID`; der Treiber startet dann am Locator 0 der Zone (58, 723) statt in (57, 729). Besser: Zelle aus PLAYER_DATA 0x79BF4/0x79BF8 lesen (gültig, wenn x/y in der Zone liegen), `TownMapLocation` nur als Rückfall.

Auf diesen Stand umgestellt: Szenarien `field_z24_h12|h18`, `field_z27_h12`, `game_feld_z24`, `game_innen_z27`; Eingabefolge `durchlauf` (Tür bei Locator (58, 723), Innenraum Zone 27); Referenzansichten `ref_01_feld_weiter` (Unity: `game_feld_z24`, `field_z24_h12`) und `ref_03_innen_eintritt` (`game_innen_z27`, `field_z27_h12`); Routen `boot_weiter`, `tuer_innenraum` (eine Zelle rechts, sieben nach oben). Baselines gab es noch nicht (nichts zu verwerfen).

## 7. Übernahme des Aufnahmecodes (Phase B)

Erst nach Freigabe durch den Hauptagenten (der Haupteditor gehört zurzeit `ap-field-render`; `scripts/visual_auto.sh status`, `scripts/unity_safe.sh status`; keine Tests und kein Spielmodus laufen):

0. **Erprobt im Labor-Editor (15:12–15:25):** `Capture.cs` und `Xnu.Visual.Editor.asmdef` nach `work/unity-shader-lab/Assets/XnuSrc/Visual/Editor/` kopiert, `recompile` (0 Fehler), Menü `Xnu/Field/Create FieldTest2 Scene` (die Lab-Szene gab es noch nicht), dann `unity command … eval 'Xnu.Visual.Capture.CaptureAll("<Liste>", "<Ausgabe>");'` (**das Semikolon am Ende ist Pflicht**, sonst „; expected“). Ergebnis: 8 Szenarien in 30 s, 11 in ca. 40 s (je Bild 50–75 ms Aufnahme, der Rest ist Zonenwechsel), `capture.json` mit `state: fertig`. Danach lief `visual_auto.sh run --name lab-full --only … --ref both` im Labor-Editor von der Aufnahme bis zum Bericht ohne Handarbeit (`XNU_UNITY_PROJECT` zeigt auf das Labor).
1. `work/visual/phaseB/Capture.cs` nach `unity/Assets/Scripts/Visual/Editor/Capture.cs`, `Xnu.Visual.Editor.asmdef` daneben kopieren (Referenzen `Xnu.Field`, `Xnu.Field.Editor`, `Xnu.Core`; Editor-only). Unity legt die `.meta`-Dateien an.
2. Übersetzen lassen (`unity command … recompile`), Konsole auf Fehler prüfen (Labor: 0 Fehler).
3. `scripts/visual_auto.sh run --quick`: erste Aufnahme (4 Bilder), Bericht und Kontaktbögen ansehen.
4. `scripts/visual_auto.sh run`: alles inklusive Spielszene-Folgen (im Labor nicht erprobt: dort gibt es keine Szene `Game`); nach der Sichtung `accept`.

Funktionsweise von `Xnu.Visual.Capture.CaptureAll(scenariosPath, outDir)`: liest die exportierte Liste (`visual_scenarios.py export-field`), öffnet `FieldTest2`, setzt `XNU_GAMEDATA`, `XNU_GENERATED_SHADERS=1`, `XNU_ENV_HOUR` und geht in den Spielmodus (Zustand in `SessionState`, überlebt den Domain-Reload). Je Szenario: Stunde setzen, `FieldController.BeginSwitchZone(zone, locator)`, auf Ende der Überblendung warten, bei Zellenangabe `Mover.Teleport` + `ForceStream`, `settle_frames` Bilder warten, `FieldShot.Capture` (RenderTexture, Alpha 255). Schreibt `<outDir>/shots/<name>.png` und `capture.json` (`state` laeuft/fertig/fehler, Zeiten, Zeile je Bild mit Status und Zonenzustand). Ein ungespeicherter Zustand einer anderen Szene führt zum Abbruch statt zu einem Dialog; Menü `Xnu/Visual/Capture All` liest `work/visual/auto/current-job.json`.

## 8. Ryujinx-Referenz

Ryujinx 1.2.78 (Vulkan, `res_scale` 1, `Fixed16x9`) auf dem Ryzen liefert Referenzbilder des Originalspiels. Screenshot-Taste **F8**, Ausgabe `~/.config/Ryujinx/screenshots/` auf dem Ryzen (Dateiname `Pokémon Brilliant Diamond_<Datum>_<hh-mm-ss>.png`, 1280×720).

### 8.1 Abholen und Zuordnen

`scripts/ryujinx_fetch_shots.sh fetch [--since "2026-10-19 14:40"]` holt nur **neue** Dateien (`rsync -rt --ignore-existing`, Dateizeit bleibt) nach `work/visual/ref/ryujinx/raw/`, ordnet sie den Ansichten aus `scripts/visual/ref_map.json` zu und schreibt normalisierte 1280×720-Bilder nach `views/<Ansicht>.png` (schwarze Ränder weg, mittig auf 16:9, skaliert) und `assignments.json` (Datei, Zeit, **Spielstunde**). Idempotent. Fehlerfälle: Ryzen aus → Exit 2 mit Hinweis, Screenshot-Ordner fehlt noch → Exit 3. `status` zeigt den Stand, `cache` die Shader-Cache-Zahlen, `reset` archiviert die Zuordnung (nichts wird gelöscht). `--since` blendet ältere Testbilder aus.

Zuordnung: der Reihe nach (Dateizeit) auf die freien Ansichten, **oder** per Umbenennen: eine Datei, deren Name mit dem Ansichtsnamen beginnt (`ref_03_innen_eintritt….png`), belegt genau diese Ansicht; Dateien mit Präfix `free_` bleiben freie Bilder.

### 8.2 Anleitung für den Nutzer (die zwei exakt reproduzierbaren Zustände)

Reproduzierbar ist der Moment nach „Weiter“ am gespeicherten Ort (Standard-Testspielstand: Zone 24 Mio-Stadt/Fleetburg, Zelle 57/729, Abschnitt 6.1) und die Route Tür → Innenraum des Pokécenters (Zone 27). Vorher `scripts/ryujinx_sync_save.sh status` (Hash des Standes `0396a4a62735` muss auf Mac und Ryzen stehen).

1. Ryujinx starten, Spiel bis zum **Titelbild** („Weiter“). Fenster im Vordergrund lassen.
2. **Weiter** wählen (A = Taste `Z`), warten bis das Feld steht. **Nichts bewegen. F8** → `ref_01_feld_weiter`.
3. Hauptmenü öffnen (Switch-X = Taste `C`), **F8** → `ref_02_menue`; Menü mit B (`X`) schließen.
4. Geradeaus nach oben in die Tür des Pokécenters laufen (Pfeil hoch halten), nach dem Laden **F8** direkt nach dem Eintreten, nichts weiter drücken → `ref_03_innen_eintritt`.
5. Optional: am Tresen A drücken, erstes Textfenster der Schwester, **F8** → `ref_04_text_schwester`.
6. `scripts/ryujinx_fetch_shots.sh fetch --since "<Uhrzeit vor Schritt 1>"` auf dem Mac.

**Uhrzeit:** muss nicht notiert werden. Der Vergleich nimmt die Dateizeit des Screenshots und rechnet die Spielstunde: `((Epoche + system_time_offset) mod 86400) / 3600` in UTC (Config: `system_time_offset` −1388 s, `system_time_zone` UTC). Beispiel: Screenshot um 14:32 Ortszeit (12:32 UTC) → Spielstunde 12,2. Das ist eine **Annahme [A]** (Host-Uhr + Offset, Zeitzone UTC); im Zweifel `game_hour` in `assignments.json` von Hand überschreiben. `visual_auto.sh run` rendert die Unity-Szenarien der Referenzansichten mit genau dieser Stunde (`export-field --ref-hours`; für den Editor-Weg `XNU_ENV_HOUR`). Weicht das Bild trotzdem in der Helligkeit ab, gleicht der Vergleich per Histogramm an.

**Stand der Referenzen (14:47):** das erste echte Referenzbild liegt vor, `Pokémon Brilliant Diamond_2026-10-19_14-47-54.png` (Spielstunde ≈ 12,4 nach Formel): Stadtplatz in Mio-Stadt/Fleetburg, blaues Dach links, Pokécenter oben, rote Spielerfigur (farbig, bei uns noch weiß), Nachbar-NPC rechts, Tannen, Hafenkran. Es ist als `ref_01_feld_weiter` zugeordnet (`fetch --since "2026-10-19 14:45"`); die früheren Bilder (14:19–14:35) zeigten die Sprachauswahl und sind mit `--since` ausgeblendet. Ob dieses Bild exakt „Weiter, nichts bewegt“ war, ist nicht belegt (Spieler steht in der Mitte des Platzes).

### 8.3 Referenzvergleich

`python3 scripts/visual_compare.py ref compare --run work/visual/auto/<lauf>` (auch `visual_auto.sh ref`, `run --ref`). Je Ansicht (Unity-Bild laut `ref_map.json`, z. B. `game_feld_z24` oder `field_z24_h12`):

* beide auf 1280×720, HUD-/Debugbereich per **Maske** ausgeschlossen (`mask`, Bruchteile der Bildgröße; Spielszene: links oben),
* Bildversatz per Kreuzkorrelation ausgeglichen (±48 px),
* **SSIM** roh und nach **Histogramm-Angleichung** (Helligkeit/Tageszeit-Offset entfernt), mittlere Abweichung roh/angeglichen, **Detail-Verhältnis** (Laplace Unity/Referenz), **Farbstich** (Kanalmittel Unity/Referenz, helligkeitsbereinigt), Helligkeitsverhältnis,
* **8×8-Rasterkarte** der Abweichung (Zellen A1–H8), Anteil schlechter Zellen (> 28 mittlere Abweichung) und Liste der **schlechtesten Zellen**,
* Kontaktbogen `contact/ref_NN.png`: **Referenz | Unity | Differenz-Heatmap** (Zellen rot umrandet und beschriftet), Bericht `ref_report.md` mit „Zur manuellen/Agenten-Sichtung“.

Schwellen (`ref_map.json`, `gates`) binden nur mit `--gate` (Exit 1); Unity und Ryujinx werden nie pixelgleich sein, die Zahlen dienen als Trend und zum Lokalisieren von Fehlern (z. B. Zelle E7 = Wasser).

### 8.4 Shader-Cache-Vergleich (nur Zahlen)

`scripts/ryujinx_fetch_shots.sh cache` liest auf dem Ryzen (`games/0100000011d90000/cache/shader`) nur Dateigröße, Kopfzähler und einen Hash-Anfang der `.toc`-Dateien (Format: 32 Byte Kopf, 16 Byte je Eintrag) und stellt sie neben unsere genutzten Varianten (`work/materials_all/used_final.json`):

| Cache | `.toc` | Einträge |
|---|---|---|
| `guest` (Gast-Shader) | 19.584 Byte | **1.222** (Kopfzähler stimmt) |
| `shared` | 22.704 Byte | 1.417 |
| `vulkan_nvidia` (Host-Programme) | 45.376 Byte | **2.834** |
| unsere genutzten Varianten (`used_final.json`) | – | **120** (119 übersetzbar) |

Verhältnisse 10,2 (guest) bzw. 23,6 (Host) je genutzter Variante; sie sind **nicht 1:1 vergleichbar**: der Cache zählt Programme je Stufenkombination und Pipeline-/Spezialisierungszustand, wir zählen Shader × Schlüsselwortvariante. Brauchbar ist die Größenordnung (ein Shader-Variantenraum von ~120 gegenüber ~1.200 Gast-Programmen: wir decken die Materialvarianten ab, nicht die Zustandsvarianten) und die Veränderung über die Zeit (der Cache wächst während des Spielens; ca. 3.500 im Vollausbau laut Nutzer).

### 8.5 Rekompilation als zweite Referenzquelle (Phase C, `--ref recomp`)

Die rekompilierte Original-Engine (Mac-Metal-Runtime, Ryzen-Vulkan) ist die zweite Referenz neben Ryujinx: sie rechnet den Originalcode ohne Emulator. Quellen: `work/recomp/shots/*.png` (Mac) und `work/visual/recomp/*.png` (Ryzen). `python3 scripts/visual_ref.py import --source recomp` ordnet **nur per Name** zu (Ansichtsname als Präfix, `aliases` in `ref_map.json`, Präfix `free_`; die vielen `frame_NNNNN.png` werden übergangen, `--all-free` führt sie als `free_…`) und schreibt normalisierte Bilder nach `work/visual/ref/recomp/views/`; geänderte Dateien werden erneut importiert. Aliase: `gate2_titel*` → `ref_00_titel`, `gate2_sprachauswahl*` → `ref_00b_sprachauswahl`. Wer ein Rekompilationsbild für eine Ansicht liefert, nennt es `ref_01_feld_weiter_metal.png` (oder trägt einen Alias ein).

* **Unity gegen Rekompilation:** `visual_compare.py ref compare --run LAUF --source recomp` (auch `visual_auto.sh run --ref recomp`, `--ref both` für beide Quellen); Bericht `LAUF/recomp/ref_report.md`, Kontaktbögen `LAUF/recomp/contact/`.
* **Rekompilation gegen Ryujinx:** `visual_ref.py refs` (Standard `--a recomp --b ryujinx`): gleiche Ansichten beider Quellen, Ryujinx ist die Referenz. Bericht `work/visual/ref/recomp_vs_ryujinx/ref_report.md`. Damit lassen sich Fehler der Rekompilation von Emulator-Eigenheiten trennen.
* Erster Wert: Sprachauswahl (`ref_00b_sprachauswahl`, Rekompilation Metal 1920×1080 auf 1280×720 skaliert gegen Ryujinx 1280×720): **SSIM 0,999, mittlere Abweichung 0,1** – die Rekompilation gibt diesen Bildschirm praktisch pixelgleich wieder.
* Das Titelbild der Rekompilation (`gate2_titel_metal.png`) hat einen **dunkelgrünen Hintergrund** (Mittel 33/88/37) und rote Beschriftung „Drücke den A-Knopf“. Ein Ryujinx-Titelbild zum Gegenprüfen fehlt noch: bitte im Spiel zum Titel zurückgehen und F8 drücken (Name `ref_00_titel….png`), dann sagt `refs`, ob Farbe und Beschriftung stimmen.

## 9. Tasten-Spieler für Ryujinx (`scripts/ryzen_keys.py`)

Läuft **auf dem Ryzen** (KDE Plasma Wayland + Xwayland; `/dev/uinput` per ACL für den Benutzer, python-evdev vorhanden), Ablage `~/xnu-recomp/tools/ryzen_keys.py`, Routen `~/xnu-recomp/routes/`, Logs `~/xnu-recomp/logs/ryzen_keys-*.log`. Nichts außerhalb `~/xnu-recomp` wird geschrieben; Ryujinx und das Spiel startet der Nutzer (der Spieler startet **nichts**).

Es legt per `evdev.UInput` die virtuelle Tastatur **`xnu-virtual-keyboard`** an, wartet 0,7 s, bis der Compositor sie kennt, und spielt eine `.keys`-Datei ab.

### 9.1 Tastenbelegung (aus `~/.config/Ryujinx/Config.json`, `input_config[0]` WindowKeyboard, Pro Controller, Player1; nicht geraten)

| Switch | Taste | | Switch | Taste |
|---|---|---|---|---|
| **A** | `Z` | | Steuerkreuz hoch/runter/links/rechts | Pfeiltasten |
| **B** | `X` | | linker Stick hoch/runter/links/rechts | `W` `S` `A` `D` (Klick `F`) |
| **X** | `C` | | rechter Stick | `I` `K` `J` `L` (Klick `H`) |
| **Y** | `V` | | Minus | `Minus` |
| L / ZL | `E` / `Q` | | Plus | `Plus` |
| R / ZR | `U` / `O` | | Hotkeys | F8 Screenshot, F5 Pause, F4 UI, F2 Stumm, F1 VSync |

`ryzen_keys.py --list` zeigt die Belegung samt evdev-Code. Das Layout des Ryzen ist `us`: `Plus` wird als `KEY_EQUAL`, `Minus` als `KEY_MINUS` gesendet (**[A]**, nicht im Spiel erprobt; bei Abweichung `map PLUS KEY_KPPLUS` in der Route). In BDSP öffnet **X** (Taste `C`) das Hauptmenü, **A** bestätigt, **B** bricht ab.

### 9.2 Befehle einer `.keys`-Datei

`key NAME [ms]`, `hold NAME ms`, `down/up NAME`, `combo A+B [ms]`, `type TEXT`, `wait MS`, `shot [timeout]` (F8, dann auf die **neue Datei im Screenshot-Ordner warten** statt blind zu warten), `shot_as ANSICHT [timeout]`, `wait_shot`, `require_focus`, `repeat N … end`, `map NAME KEY_XXX`, `note TEXT`; Namen = Switch-Knöpfe, `KEY_…` oder Ryujinx-Tastennamen. Optionen: `--dry-run`, `--focus`, `--time-limit`, `--speed`, `--hold-ms`, `--check`, `--list`. Letzte Ausgabezeile `RESULT {json}` mit den neuen Screenshots.

### 9.3 Sicherheit (Eingaben dürfen nie in Fenster des Nutzers geraten)

* **Vor jeder einzelnen Taste** wird das aktive Fenster geprüft: `xprop -root _NET_ACTIVE_WINDOW` des Xwayland-Servers (Umgebung `DISPLAY`/`XAUTHORITY` aus dem Ryujinx-Prozess), dann Titel (`_NET_WM_NAME` beginnt mit „Ryujinx“) **und** `WM_CLASS` „Ryujinx“. KWin meldet für Wayland-native Fenster (Konsole, Browser) kein X11-Fenster als aktiv; das zählt als „kein Fokus“. Nur bei „ok“ wird gesendet, sonst **Abbruch (Exit 5)**, alle gedrückten Tasten werden losgelassen.
* Datei `~/xnu-recomp/STOP` anlegen bricht jederzeit ab (Exit 3; vom Mac: `scripts/ryujinx_record.sh --stop`), Zeitlimit (Standard 300 s, Exit 4), nur eine Instanz (Exit 8), `--dry-run` sendet nichts (kein uinput).
* `--focus` versucht `wmctrl -i -a` (unter Wayland für Xwayland-Fenster oft möglich, sonst Fokus von Hand).
* Getestet (Python-Tests mit simuliertem Fokus): fremdes Fenster → keine Taste, Wayland-Fenster → kein Fokus, Fokusverlust mitten in der Folge → Taste losgelassen und Abbruch, STOP, Zeitlimit, Trockenlauf.

### 9.4 Routen (`scripts/visual/routes/`) und Aufnahme-Treiber

| Route | Inhalt | Status |
|---|---|---|
| `f8_only` | nur Fokus prüfen und F8 | **echt ausgeführt** (2×, harmlos): Taste kam an, neues Bild nach 0,36 s |
| `boot_weiter` | Titelbild → A → Weiter (A) → 12 s Laden → F8 `ref_01_feld_weiter` → X Menü → F8 `ref_02_menue` → B | nur **Trockenlauf** |
| `tuer_innenraum` | F8 vor der Tür → Pfeil hoch 1,6 s → 4,5 s Laden → F8 `ref_03_innen_eintritt` | nur **Trockenlauf** |

`scripts/ryujinx_record.sh ROUTE [--dry-run] [--focus] [--no-compare]` (Mac): zeigt den Spielstand-Abgleich (`ryujinx_sync_save.sh status`, nur lesen), kopiert `ryzen_keys.py` und die Route auf den Ryzen, prüft den Fokus (sonst Exit 5, keine Taste gesendet), spielt ab, holt die neuen Bilder nach `work/visual/ref/ryujinx/<route>/` und `raw/<Ansicht>__<Original>.png`, ordnet zu und ruft den Referenzvergleich gegen den letzten Unity-Lauf.

**Zeiten sind Annahmen [A]** (12 s Laden, 1,6 s Laufzeit zur Tür, 4,5 s Überblendung). Beobachtet ist nur: uinput-Start 0,7 s, F8 → Datei 0,36 s. Kalibrierung: erste echte Läufe, danach Zeitstempel der Screenshots und der `wait`-Zeilen vergleichen (Log `~/xnu-recomp/logs/`), Zeiten in den `.keys` anpassen. Statt blind zu warten synchronisiert `shot` auf die neue Datei; für das Laden gibt es keinen Marker (kein Zugriff auf Spielzustand), deshalb Wartezeiten.

### 9.5 Freigabe vor Bewegungs- und Menütasten

**Es wurden NUR F8-Tasten wirklich gesendet** (zwei Läufe `f8_only`, bei geprüft aktivem Ryujinx-Fenster). Bewegungs- und Menütasten (`boot_weiter`, `tuer_innenraum`) sind nur im Trockenlauf geprüft. Vor dem ersten echten Lauf braucht es die Zustimmung des Nutzers (Hauptagent fragt): das Spiel muss am Titelbild stehen (Stand 14:47: das Spiel läuft bereits in der Stadt; dann zuerst im Spiel zum Titel zurückgehen oder die Route erst ab dem Feld verwenden, sonst würde A im Spiel etwas bestätigen), das Ryujinx-Fenster angeklickt sein. Befehl danach:

```
scripts/ryujinx_record.sh boot_weiter            # Titel -> Feld -> Menü, 2 Referenzbilder
scripts/ryujinx_record.sh tuer_innenraum         # Tür -> Innenraum, 1 Referenzbild
```

## 10. Bekannte Grenzen und nächste Schritte

* Aufnahmecode im Editor: im **Labor-Editor** erprobt, **nicht** in `unity/` (Abschnitt 7). `player` und `ipad` sind nur geschrieben, nicht ausgeführt; sie liefern nur Spielszene-Folgen, keine Feldszenarien. Die Spielszene-Folgen (`game_*`) sind weder im Labor noch im Haupteditor gelaufen.
* Die Spielszene-Folgen nutzen den Spielstand-Import der Szene `Game` (Quelle Ryujinx-Ordner im Repo); ohne ihn bleibt `game_feld_z24` aus und der Lauf meldet die Aufnahme als fehlend.
* Zone 54, 27 und 168 laufen mit Locator 0 (Zellen unbekannt); Zone 24 an Zelle 57/729 stammt aus dem Spielstand (6.1), die Blickrichtung ist Annahme. Der Spielkern liest die Position noch aus `TownMapLocation` (6.1): `game_feld_z24` zeigt deshalb vorerst den Locator (58, 723) statt (57, 729), bis `SavedPosition.Read` angepasst ist.
* Detektor: gestreckte Texturen, Diagonalband und weiße Figur ohne Referenz nicht erkennbar (Abschnitt 4); Ryujinx-Referenz und Differenzbild decken sie ab.
* Ryujinx-Spieluhr und Zeitzone sind Annahmen; Referenz-Zeitpunkt `ref_04` ist nicht exakt reproduzierbar (Tresenposition).

## 11. Erste Referenzvergleiche (Stand 15:30, Labor-Editor gegen Ryujinx)

Grundlage: zwei echte Ryujinx-Bilder des Nutzers in Mio-Stadt/Fleetburg (`14-47-54` = `ref_01_feld_weiter`, Spielstunde ≈ 12,4; `15-03-21` = `ref_05_vor_pokecenter`, ≈ 12,7) und Aufnahmen des Labor-Editors (`work/visual/auto/run-lab-z24`, `run-lab-full`, Stunden aus den Referenzen). Der Lauf `lab1` (Zelle 57/729) und `lab-cells` (12 Kandidatenzellen) gehören dazu. Die Bilder der Spielszene `Game` (UI, Menü, Kampf) gibt es noch ohne Referenz; zu **UI/Menü** gibt es deshalb noch keinen Befund (`ref_02_menue` fehlt).

### 11.1 Position: gespeicherte Zelle ≠ Unity-Zelle (neuer Befund)

Mit den zwölf Kandidatenzellen um (57, 729) (`lab-cells`, SSIM nach Histogramm-Angleichung, Restversatz nach Kreuzkorrelation):

| Unity-Zelle | SSIM angeglichen | Restversatz (x, y) px |
|---|---|---|
| **(58, 729)** | **0,414** | **(8, −24)** |
| (57, 729) | 0,408 | (−68, −24) |
| (59, 730) | 0,406 | (92, 24) |
| (57, 730) | 0,406 | (−60, 24) |
| (58, 728) | 0,355 | (0, −84) |
| (56, 729) | 0,346 | (−100, −20) |

Das Referenzbild gehört zur Unity-Zelle **(58, 729)** (Restversatz 8 px waagerecht), nicht zur gespeicherten Zelle (57, 729): Spielstand-Zelle und Unity-Zelle unterscheiden sich um **+1 in x** (und etwa +0,4 Zellen in y, dort ist der Versatz von 24 px unabhängig von der Zelle, also eher Kamera). **[A]** Erklärung: die Originalwelt hat Zellmitten bei halben Zahlen (Weltposition −(gx + 1) bzw. gy + 0,5), `FieldCoords` rechnet mit ganzen Zahlen; sicher ist nur der Bildabgleich an diesem einen Bild. `field_z24_h12|h18` nutzen deshalb (58, 729). Für den Spielkern (`SavedPosition`) heißt das: gespeicherte Zelle (57, 729) → Spawn bei Unity-Zelle (58, 729) prüfen, sobald ein zweites Referenzbild mit bekannter Zelle vorliegt.

### 11.2 `ref_01_feld_weiter` ↔ `field_z24_h12` (Unity-Zelle 58/729, Stunde 12,4)

| Kennzahl | Wert |
|---|---|
| SSIM roh / nach Histogramm-Angleichung | **0,449 / 0,416** |
| mittlere Abweichung roh → angeglichen | 32,8 → 25,1 |
| Detail-Verhältnis (Laplace Unity/Referenz) | **×1,37** (Unity schärfer/unruhiger) |
| Farbstich R/G/B (helligkeitsbereinigt) | 0,98 / 1,00 / 1,05 (leicht bläulich) |
| Helligkeit Unity/Referenz | **×0,83** (Unity 17 % dunkler) |
| schlechte Zellen (> 28) | 17 von 62; schlechteste A2 (86), A3 (86), A4 (69) |

Mittelwerte nach Farbmasken (Bild bei Zelle 57/729, Referenz → Unity):

| Fläche | Referenz RGB | Unity RGB |
|---|---|---|
| Pflaster (grau-violett) | 141 / 137 / 161 | 118 / 117 / 138 (**−16 %**) |
| Baumgrün | 50 / 106 / 32 | 57 / 111 / 40 (heller, gelbstichiger) |
| blaues Dach | 57 / 120 / 185 | 58 / 116 / 166 (weniger blau, dunkler) |
| Wasser | 55 / 119 / 186 | 59 / 117 / 168 |
| gesamt | 106 / 120 / 118 | 88 / 103 / 111 |
| Pixel mit Luma > 200 | 1,8 % | **0,1 %** |
| Luma-Streuung | 42,9 | **33,3** |

Befunde (nach Kontaktbogen `contact/ref_01.png` und Kennzahlen):

* **Helligkeit/Kontrast:** Unity ist insgesamt etwa 17 % dunkler, vor allem Pflaster und Hauswände (Hauswand beim blauen Haus: Referenz weißgrau, Unity dunkles Blaugrau, die Differenz-Heatmap leuchtet dort). Es fehlen helle Spitzen (1,8 % → 0,1 % der Pixel über Luma 200) und damit Kontrast (Streuung 33 statt 43): das Original hat vermutlich Bloom/Tonwert-Nachbearbeitung und hellere Umgebungsbeleuchtung der senkrechten Flächen. Das zieht auch die Detail-Kennzahl hoch (Unity ×1,37 schärfer: die Referenz ist weicher/geglättet, wahrscheinlich Kantenglättung/Bloom).
* **Farbe:** insgesamt gut getroffen (Stich unter 6 %); Dachblau etwas matter, Baumgrün gelbstichiger und heller, Schatten in Unity bläulicher (29/47/35 gegen 25/49/24 in der Referenz).
* **Spielerfigur:** im Labor **farbig** (rotes Käppi, dunkles Oberteil), Pose und Größe wie im Original; nur die Kleidung ist dunkler als in der Referenz (gleiches Beleuchtungsthema). Der NPC mit braunen Haaren steht wie in der Referenz neben dem Spieler (kleine Abweichung der Position, Animation).
* **Wasser:** Unity zeigt am linken Rand ein Hafenbecken mit blauem, funkelndem Wasser; im Referenzbild liegen dort oben links ein **hölzerner Hafenkran/Steg** (dunkles Metall, Holz) und darunter türkises Wasser. **Der Kran fehlt in Unity** (Zellen A2–A4 sind mit MAD 69–86 die schlechtesten). Wasserpixel per Farbmaske: Referenz 55/119/186, Unity 59/117/168 (Unity weniger blau und dunkler; die Masken erfassen verschiedene Bildstellen, Wert nur als Hinweis).
* **Schatten:** Richtung und Form der Hausschatten stimmen; in Unity sind Schattenflächen etwas dunkler und kälter.
* **UI/Menü:** nicht verglichen (kein Referenzbild).

### 11.3 `ref_05_vor_pokecenter` ↔ `field_z24_vor_pc` (nicht aussagekräftig)

SSIM 0,37 / 0,31 (angeglichen), 56 von 64 Zellen schlecht: das Referenzbild zeigt einen **anderen Ort** als die geschätzte Unity-Zelle (54, 722): links eine Tannenwand, rechts ein **orangebraunes Gebäude mit weißen Dachrinnen und Poké-Ball-Zeichen** (kein rotes Pokécenter wie in Unity), davor ein Schild mit Poké-Ball; Unity zeigt dort Wasser links und das rote Pokécenter. Es ist vermutlich ein anderes Gebäude (Beschriftung/Form ähnlich einem Markt) an anderer Stelle der Stadt; die Zelle ist unbekannt. Bis die Zelle bekannt ist, taugt das Bild nur zur Ansicht. Für eine Suche der Zelle reicht `lab-cells`-artiges Rastern (12 Zellen = 35 s; ein Raster 40×50 Zellen mit Schritt 3 etwa 10 Minuten).

### 11.4 Rekompilation (Phase C)

* Sprachauswahl Mac-Metal ↔ Ryujinx: **SSIM 0,999**, mittlere Abweichung 0,1: praktisch pixelgleich (Abschnitt 8.5).
* Titelbild Mac-Metal: grüner Hintergrund und rote Beschriftung; Gegenstück aus Ryujinx fehlt (Bitte um ein F8 am Titelbild).
* Weitere Ansichten (Stadt, Menü) gibt es in der Rekompilation noch nicht.

### 11.5 Was daraus für Unity folgt (Reihenfolge nach Gewicht)

1. **Gesamthelligkeit und Kontrast** (−17 %, fehlende Lichter): Umgebungslicht/Boden-Aufhellung der senkrechten Flächen und Nachbearbeitung (Bloom, Tonwert) prüfen; größter Hebel auf allen Stadtbildern.
2. **Fehlende Objekte** (Hafenkran/Steg in Zone 24): Containerzuordnung/Streaming (`Blöcke 4`) oder Kategorien, die der Karten-Aufbau auslässt.
3. **Koordinatenversatz** Spielstand ↔ Unity-Zelle (11.1).
4. Wasserfarbe (Referenz blauer/türkiser); Baumgrün weniger gelb.
