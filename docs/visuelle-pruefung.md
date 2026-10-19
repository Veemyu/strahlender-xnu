# Automatische Sichtprüfung (Screenshots, Vergleich, Ryujinx-Referenz)

Stand: 2026-10-19, 14:40. Ziel: Bilder der Unity-Szenen entstehen und werden **automatisch** verglichen, nicht mehr von Hand. Ein Befehl:

```
scripts/visual_auto.sh run            # Aufnahme -> Vergleich mit der Baseline -> Bericht + Kontaktbögen
```

Bilder, Berichte und Referenzen liegen nur unter `work/` (gitignoriert); im Repo stehen Skripte, Szenarioliste, Routen und diese Beschreibung. Kein Ton: nichts spielt etwas ab (Tests und Skripte nur mit synthetischen Bildern).

**Stand der Lieferung (ehrlich):** Vergleich, Anomalie-Detektor, Berichte, Kontaktbögen, Szenarioliste, Orchestrierung, Referenzimport und Tasten-Spieler sind fertig und getestet (Python-Tests, Trockenläufe, echter F8-Test auf dem Ryzen). Der **Aufnahmecode im Unity-Editor** (`Xnu.Visual.Capture`) liegt fertig und gegen die Unity-DLLs übersetzungsgeprüft unter `work/visual/phaseB/`, ist aber **noch nicht in `unity/Assets`** (der Haupteditor gehörte bis ca. 15:30 einem anderen Agenten); Übernahme siehe Abschnitt 7. Bis dahin geht `visual_auto.sh run` mit Exit-Code 4, `compare`/`accept`/`ref` funktionieren auf vorhandenen Bildern.

## 1. Befehle

| Befehl | Wirkung |
|---|---|
| `scripts/visual_auto.sh run [--quick] [--only a,b] [--mode editor\|player\|ipad] [--strict] [--ref]` | Aufnahme, Vergleich, Bericht `work/visual/auto/run-<Zeit>/report.md`. `--quick`: nur Szenarien mit Tag `quick` (4 Feldbilder, ca. 1–2 Minuten). Exit 0 = keine Regression, 1 = Regression, 2 = Fehler, 4 = Aufnahmecode fehlt |
| `scripts/visual_auto.sh compare [--run LAUF\|latest] [--ref]` | nur Vergleich eines vorhandenen Laufs |
| `scripts/visual_auto.sh accept [LAUF]` | Lauf als **neue Baseline** übernehmen (`work/visual/auto/baseline/`, alte nach `baseline.alt/`). **Erst nach Sichtung** der Kontaktbögen durch den Hauptagenten/Nutzer |
| `scripts/visual_auto.sh watch [--interval MIN] [--once]` | alle N Minuten (Standard 10) laufen, wenn sich `unity/Assets/Scripts/{Field,Render}` oder `scripts/shader_*` geändert haben |
| `scripts/visual_auto.sh ref [--fetch] [--run LAUF]` | Ryujinx-Referenzen holen und gegen den Lauf vergleichen (Abschnitt 8) |
| `scripts/visual_auto.sh scenarios \| test \| status` | Szenarioliste prüfen, Python-Tests, Zustand |
| `python3 scripts/visual_compare.py analyze BILD… [--kind field\|room\|ui]` | nur Anomalie-Detektor für einzelne Bilder |
| `scripts/ryujinx_fetch_shots.sh [fetch\|status\|cache\|reset]` | F8-Screenshots vom Ryzen holen (Abschnitt 8) |
| `scripts/ryujinx_record.sh ROUTE [--dry-run]` | Tastenfolge in Ryujinx abspielen und Bilder holen (Abschnitt 9) |

Aufnahmearten: **editor** (Standard: Feldszenarien über `Xnu.Visual.Capture` in `FieldTest2`, danach die Folgen der Szene `Game` im Editor-Spielmodus), **player** (macOS-Build `work/builds/macos/xnu.app`, nur Spielszene-Folgen), **ipad** (`devicectl`, nur Spielszene-Folgen; bisher nicht ausgeführt). Der Editor wird über `scripts/unity_safe.sh` (Status/Öffnen) und `unity command … eval` gesteuert; `visual_auto.sh` startet ihn nur, wenn er aus ist.

## 2. Dateien

| Datei | Aufgabe |
|---|---|
| `scripts/visual/scenarios.json` | Aufnahmeliste: 10 Feldszenarien (Zonen 422 zu vier Stunden, 425, 54, 367, 167 zu zwei Stunden, 168), 14 Spielszene-Bilder in zwei Folgen (`durchlauf`: Titel, Feld, Innen, Text, Auswahl, Kampf; `menue`: Menü, Team, Beutel, Bericht); 1280×720, stabile Namen, Wartezeit in Bildern (`settle_frames`), Typ (`kind`), erlaubte Flags, Schwellen je Szenario |
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

Feld (Editor, `FieldTest2`): `field_z422_h07|h12|h18|h22` (Zelle 116/886, Blick oben; Tageszeit über `XNU_ENV_HOUR`), `field_z425_h12` (Spielerhaus innen, Typ `room`), `field_z54_h12` (Locator 0), `field_z367_h12` (Zelle 512/726), `field_z167_h12|h18` (Zelle 840/599, Pokécenter-Eingang vor Wasser und Felswand), `field_z168_h12` (Pokécenter innen). Spielszene (`Game`, Eingabeskript wie `work/vslice/run4.txt` und `work/ui2/run1b.txt`): `game_titel`, `game_feld_z167`, `game_innen_z168`, `game_text`, `game_auswahl`, `game_nach_ereignis`, `game_kampf_befehl|attacken|meldung`, `game_menue`, `game_menue_rechts`, `game_team`, `game_beutel`, `game_bericht_frage`. Die Spielszene-Bilder entstehen mit dem Skriptbefehl `shot` (`-xnuShotDir`); die Folge endet mit `quit` (Editor: `visual_auto.sh` beendet den Spielmodus nach dem letzten Bild).

## 7. Übernahme des Aufnahmecodes (Phase B)

Erst wenn der Haupteditor frei ist (`scripts/visual_auto.sh status`, `scripts/unity_safe.sh status`; keine Tests und kein Spielmodus laufen):

1. `work/visual/phaseB/Capture.cs` nach `unity/Assets/Scripts/Visual/Editor/Capture.cs`, `Xnu.Visual.Editor.asmdef` daneben kopieren (Referenzen `Xnu.Field`, `Xnu.Field.Editor`, `Xnu.Core`; Editor-only). Unity legt die `.meta`-Dateien an.
2. Übersetzen lassen (`unity command … recompile`), Konsole auf Fehler prüfen. Die Datei ist vorher mit `dotnet build work/visual/phaseB/check` gegen die Unity-DLLs und die vorhandenen `Xnu.*`-Assemblies übersetzt worden (0 Fehler); im Editor selbst noch **nicht** ausgeführt.
3. `scripts/visual_auto.sh run --quick`: erste Aufnahme (4 Bilder), Bericht und Kontaktbögen ansehen.
4. `scripts/visual_auto.sh run`: alles inklusive Spielszene-Folgen; nach der Sichtung `accept`.

Funktionsweise von `Xnu.Visual.Capture.CaptureAll(scenariosPath, outDir)`: liest die exportierte Liste (`visual_scenarios.py export-field`), öffnet `FieldTest2`, setzt `XNU_GAMEDATA`, `XNU_GENERATED_SHADERS=1`, `XNU_ENV_HOUR` und geht in den Spielmodus (Zustand in `SessionState`, überlebt den Domain-Reload). Je Szenario: Stunde setzen, `FieldController.BeginSwitchZone(zone, locator)`, auf Ende der Überblendung warten, bei Zellenangabe `Mover.Teleport` + `ForceStream`, `settle_frames` Bilder warten, `FieldShot.Capture` (RenderTexture, Alpha 255). Schreibt `<outDir>/shots/<name>.png` und `capture.json` (`state` laeuft/fertig/fehler, Zeiten, Zeile je Bild mit Status und Zonenzustand). Ein ungespeicherter Zustand einer anderen Szene führt zum Abbruch statt zu einem Dialog; Menü `Xnu/Visual/Capture All` liest `work/visual/auto/current-job.json`.

## 8. Ryujinx-Referenz

Ryujinx 1.2.78 (Vulkan, `res_scale` 1, `Fixed16x9`) auf dem Ryzen liefert Referenzbilder des Originalspiels. Screenshot-Taste **F8**, Ausgabe `~/.config/Ryujinx/screenshots/` auf dem Ryzen (Dateiname `Pokémon Brilliant Diamond_<Datum>_<hh-mm-ss>.png`, 1280×720).

### 8.1 Abholen und Zuordnen

`scripts/ryujinx_fetch_shots.sh fetch [--since "2026-10-19 14:40"]` holt nur **neue** Dateien (`rsync -rt --ignore-existing`, Dateizeit bleibt) nach `work/visual/ref/ryujinx/raw/`, ordnet sie den Ansichten aus `scripts/visual/ref_map.json` zu und schreibt normalisierte 1280×720-Bilder nach `views/<Ansicht>.png` (schwarze Ränder weg, mittig auf 16:9, skaliert) und `assignments.json` (Datei, Zeit, **Spielstunde**). Idempotent. Fehlerfälle: Ryzen aus → Exit 2 mit Hinweis, Screenshot-Ordner fehlt noch → Exit 3. `status` zeigt den Stand, `cache` die Shader-Cache-Zahlen, `reset` archiviert die Zuordnung (nichts wird gelöscht). `--since` blendet ältere Testbilder aus.

Zuordnung: der Reihe nach (Dateizeit) auf die freien Ansichten, **oder** per Umbenennen: eine Datei, deren Name mit dem Ansichtsnamen beginnt (`ref_03_innen_eintritt….png`), belegt genau diese Ansicht; Dateien mit Präfix `free_` bleiben freie Bilder.

### 8.2 Anleitung für den Nutzer (die zwei exakt reproduzierbaren Zustände)

Reproduzierbar ist der Moment nach „Weiter“ am gespeicherten Ort und die Route Tür → Innenraum (Kamera, Zelle und Blick liegen im Spielstand). Vorher `scripts/ryujinx_sync_save.sh status` (Hash des Mac-Stands `8dd552b1287c` muss auf dem Ryzen stehen).

1. Ryujinx starten, Spiel bis zum **Titelbild** („Weiter“). Fenster im Vordergrund lassen.
2. **Weiter** wählen (A = Taste `Z`), warten bis das Feld steht. **Nichts bewegen. F8** → `ref_01_feld_weiter`.
3. Hauptmenü öffnen (Switch-X = Taste `C`), **F8** → `ref_02_menue`; Menü mit B (`X`) schließen.
4. Geradeaus nach oben in die Tür des Pokécenters laufen (Pfeil hoch halten), nach dem Laden **F8** direkt nach dem Eintreten, nichts weiter drücken → `ref_03_innen_eintritt`.
5. Optional: am Tresen A drücken, erstes Textfenster der Schwester, **F8** → `ref_04_text_schwester`.
6. `scripts/ryujinx_fetch_shots.sh fetch --since "<Uhrzeit vor Schritt 1>"` auf dem Mac.

**Uhrzeit:** muss nicht notiert werden. Der Vergleich nimmt die Dateizeit des Screenshots und rechnet die Spielstunde: `((Epoche + system_time_offset) mod 86400) / 3600` in UTC (Config: `system_time_offset` −1388 s, `system_time_zone` UTC). Beispiel: Screenshot um 14:32 Ortszeit (12:32 UTC) → Spielstunde 12,2. Das ist eine **Annahme [A]** (Host-Uhr + Offset, Zeitzone UTC); im Zweifel `game_hour` in `assignments.json` von Hand überschreiben. `visual_auto.sh run` rendert die Unity-Szenarien der Referenzansichten mit genau dieser Stunde (`export-field --ref-hours`; für den Editor-Weg `XNU_ENV_HOUR`). Weicht das Bild trotzdem in der Helligkeit ab, gleicht der Vergleich per Histogramm an.

**Beobachtung zum Spielzustand:** die ersten Screenshots des Nutzers (14:19) und der F8-Test (14:32, 14:35) zeigen die **Sprachauswahl** („Select the language you would like to play“, Cursor auf English), nicht das Titelbild. Solange das Spiel dort steht, sind es keine Referenzen; erst nach der Sprachauswahl/Titelbild beginnt Schritt 1. Ob der abgeglichene Spielstand (Slot des Benutzers in Ryujinx) von der Sprachauswahl nicht erkannt wird oder die Auswahl nur beim ersten Start erscheint, ist offen.

### 8.3 Referenzvergleich

`python3 scripts/visual_compare.py ref compare --run work/visual/auto/<lauf>` (auch `visual_auto.sh ref`, `run --ref`). Je Ansicht (Unity-Bild laut `ref_map.json`, z. B. `game_feld_z167` oder `field_z167_h12`):

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

**Es wurden NUR F8-Tasten wirklich gesendet** (zwei Läufe `f8_only`, bei geprüft aktivem Ryujinx-Fenster). Bewegungs- und Menütasten (`boot_weiter`, `tuer_innenraum`) sind nur im Trockenlauf geprüft. Vor dem ersten echten Lauf braucht es die Zustimmung des Nutzers (Hauptagent fragt): das Spiel muss am Titelbild stehen (aktuell steht es in der Sprachauswahl, dort würde A „English“ wählen), das Ryujinx-Fenster angeklickt sein. Befehl danach:

```
scripts/ryujinx_record.sh boot_weiter            # Titel -> Feld -> Menü, 2 Referenzbilder
scripts/ryujinx_record.sh tuer_innenraum         # Tür -> Innenraum, 1 Referenzbild
```

## 10. Bekannte Grenzen und nächste Schritte

* Aufnahmecode im Editor ist **nicht** in `unity/` und nicht im Editor ausgeführt (Übersetzungsprüfung gegen die Unity-DLLs bestanden). `player` und `ipad` sind nur geschrieben, nicht ausgeführt; sie liefern nur Spielszene-Folgen, keine Feldszenarien.
* Die Spielszene-Folgen nutzen den Spielstand-Import der Szene `Game` (Quelle Ryujinx-Ordner im Repo); ohne ihn bleibt `game_feld_z167` aus und der Lauf meldet die Aufnahme als fehlend.
* Zone 54 und 168 laufen mit Locator 0 (Zellen unbekannt); Zone 167 an Zelle 840/599 ist eine Annahme aus dem vertikalen Durchstich.
* Detektor: gestreckte Texturen, Diagonalband und weiße Figur ohne Referenz nicht erkennbar (Abschnitt 4); Ryujinx-Referenz und Differenzbild decken sie ab.
* Ryujinx-Spieluhr und Zeitzone sind Annahmen; Referenz-Zeitpunkt `ref_04` ist nicht exakt reproduzierbar (Tresenposition).
