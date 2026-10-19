# macOS-App aus der Rekompilation (`BDSP.app`)

Stand: 2026-10-19 (`ap-recomp` macOS-App). Grundlage: `docs/recomp-gate2.md` (bdsp_boot läuft headless bis in die 3D-Stadt), `docs/architektur-entscheidung.md` (Entscheidung 3: Rekompilation ist Hauptweg), `docs/kernziel.md`. Auftrag: aus dem Testprogramm `bdsp_boot` eine richtige macOS-App machen (arm64, Metal, **ohne Ton**, ohne Netz) und die Build-Stufe `recomp` in `scripts/build_all.sh` einrichten.

**Kennzeichnung:** *gemessen* = mit den Läufen unter `work/` ermittelt (M1 Pro, 16 GB, **Last 25 bis 50** durch andere Prozesse, daher sind Bauzeiten und Bildraten pessimistisch). *vermutet* = Schluss ohne Test. Im Repo liegen nur Skripte, Laufzeit-Quellen und Doku; erzeugter Code, Spielstände, Bildschirmfotos und das RomFS liegen nie im Repo.

## Ergebnis in Kürze

| | |
|---|---|
| **App** | `work/builds/macos-recomp/BDSP.app`, Bundle-ID `dev.local.xnubdsp`, arm64, Metal, hochauflösend, ad hoc signiert. Fenster mit 16:9-Letterbox, Vollbild (Cmd+F), vier Fenstergrößen (Cmd+1 bis 4), deutsches Menü *Spiel / Ansicht / Fenster / Hilfe*. |
| **Eingabe** | Tastatur nach dem Ryujinx-Standard (Z = A, X = B, C = X, V = Y, WASD = linker Stick, Pfeile = Steuerkreuz, …), Controller über GameController.framework (Xbox, PlayStation, Switch Pro; **ohne Hardware nicht getestet**). Belegung: Abschnitt „Bedienung“ und Menü *Hilfe → Tastenbelegung*. |
| **Spielstand** | `~/Library/Application Support/dev.local.xnubdsp/save/save_1/SaveData.bin` + `Backup.bin` (Format unverändert, wie Ryujinx/Switch), Sicherung bei jedem Start, Import per Menü, Ablegen auf das Fenster oder `--import-save` (Größe und MD5 wie `scripts/bdsp_save.py`), Zurücksetzen mit Sicherung. |
| **Ablage** | RomFS unter Application Support (APFS-Klon von `work/romfs`, kein zusätzlicher Platz), Shader-Cache und Bildschirmfotos unter `~/Library/Caches/dev.local.xnubdsp`, Logs unter `~/Library/Logs/dev.local.xnubdsp`. Pfade über `config.ini` oder `BDSP_*`-Umgebung. |
| **Build-Stufe** | `scripts/build_all.sh --only recomp` (nach `extract`/`il2cpp`): Generator → C → Übersetzen → Modulbilder → Laufzeit/NVN-Metal → App → Daten. Marker, `--dry-run`, Preflight (≥ 25 GB), deutsche Fehlermeldungen. Zahlen: Abschnitt „Bauzeit und Größen“. |
| **Test** | Eingabeskript Titel → Weiter → Feld → Pokécenter-Tür → **Innenraum erreicht** (Schwester Joy am Tresen), Screenshots gesehen. Innenraum zeigt Darstellungsfehler (Abschnitt „Lücken“). |
| **Nicht umgesetzt** | MetalFX (optional, siehe Lücken), Controller-Hardwaretest, Drag & Drop mit echter Maus (Ereignis vorhanden, nur über die Funktion getestet). |

## Aufbau des Bundles

```
BDSP.app/Contents/
  Info.plist          dev.local.xnubdsp, NSHighResolutionCapable, Dateitypen (SaveData.bin/Ordner ablegen)
  MacOS/BDSP          Laufzeit (rt-bdsp) + libgame (übersetzte Gastmodule, rund 220 MB) + NVN/Metal-Schicht + App-Hülle
  Resources/img/      Modulbilder (Relokationen angewandt, aus dem eigenen Dump; hle.txt = HLE-Slots)
  Resources/main.npdm Programm-Metadaten des Dumps
  Resources/BDSP.icns Platzhalter-Symbol (blaue Raute auf Verlauf, keine Spielgrafik)
  Frameworks/         SDL3, FFmpeg (libavcodec/-format/-util) und deren Abhängigkeiten, 16 Bibliotheken
```

Die App enthält damit Inhalte aus deinem Dump (Spielcode); sie ist nur für den persönlichen Gebrauch. Das RomFS (4,7 GB) liegt bewusst **nicht** im Bundle, sondern unter Application Support.

**Ton:** keiner. `audren`/`audout`/`hwopus` bleiben stumme Stummel (`services_audio.c`), es gibt keinen CoreAudio-Ausgang und kein Audio-Framework im Bundle. **Netz:** keines; die Laufzeit enthält keinen Netzcode (`services_net.c` meldet nur Erfolg), die App hat weder Netzrechte noch Sandbox (Hardened-Runtime-Variante: nur das Entitlement `disable-library-validation`).

## Bedienung

**Menü** (Cmd+Tasten wirken, wenn das Fenster den Fokus hat):

| Menü | Eintrag | Wirkung |
|---|---|---|
| Spiel | Spielstand-Ordner öffnen (Cmd+O) | Finder zeigt `…/save/save_1` |
| Spiel | Spielstand importieren … (Cmd+I) | Dateiauswahl für `SaveData.bin` oder einen Ordner (Ryujinx: `bis/user/save/<ID>/0`), Prüfung, Sicherung des bisherigen Stands, danach Neustart |
| Spiel | Pause (Cmd+P) | hält das Vsync-Ereignis an: das Spiel steht, bis es fortgesetzt wird |
| Spiel | Neustart (Cmd+R) | Rückfrage, dann startet die App neu (`open -n`); der Spielstand bleibt |
| Spiel | Spiel zurücksetzen … (Cmd+Umschalt+R) | Rückfrage; der aktuelle Stand wandert nach `backups/reset-<Zeit>/`, das Spiel beginnt neu (Sprachauswahl) |
| Ansicht | Vollbild (Cmd+F) | Vollbild des Schreibtischs (Esc beendet es) |
| Ansicht | Fenstergröße 960×540 / 1280×720 / 1920×1080 / 2560×1440 (Cmd+1 bis 4) | Größe in Punkten; das Bild bleibt 16:9, bei anderen Fensterformen mit schwarzen Balken (Letterbox) |
| Hilfe | Tastenbelegung, Konfigurationsdatei zeigen, Cache-Ordner öffnen, Log-Ordner öffnen | |

Pause bei Fokusverlust ist **optional** (`pause_on_focus_loss = 1` in `config.ini`, Standard aus).

**Tastatur** (Standard von Ryujinx; zusätzlich Return/Leertaste = A und Rücktaste = B):

| Switch | Taste | | Switch | Taste |
|---|---|---|---|---|
| A / B / X / Y | Z / X / C / V (alternativ Return, Leertaste = A; Rücktaste = B) | | L / R | E / U |
| ZL / ZR | Q / O | | + / − | `=` oder Tab / Minus |
| Steuerkreuz | Pfeiltasten | | Linker Stick | W A S D |
| Linker/rechter Stick drücken | F / H | | Rechter Stick | I J K L |

**Controller:** GameController.framework (Xbox, PlayStation, Switch Pro u. a.). Standard `pad_layout = nintendo`: Tastenposition wie bei der Switch (rechte Taste = A), `xbox`: nach Beschriftung. Menü/Start = +, Ansicht/Optionen = −, Schultertasten L/R, Trigger ZL/ZR, Sticks mit Totzone 12 %. Mehrere Controller wirken gemeinsam auf Spieler 1.

**Fenster:** Standard 1280×720 (`window = BxH`), Hochauflösung (Retina), Größe frei änderbar (Mindestgröße 640×360). Das Spiel rendert 1280×720 und wird auf die Fenstergröße gespannt; bei Seitenverhältnissen ≠ 16:9 entstehen Balken. MetalFX ist **nicht** eingebaut (Lücken).

## Daten und Ablage

| Was | Standardort | Änderbar über |
|---|---|---|
| Hauptordner | `~/Library/Application Support/dev.local.xnubdsp` | `BDSP_HOME` |
| Konfigurationsdatei | `<Hauptordner>/config.ini` (Menü *Hilfe → Konfigurationsdatei zeigen* legt eine kommentierte Vorlage an) | `BDSP_CONFIG` |
| RomFS | `<Hauptordner>/romfs` (enthält `Data/`) | `romfs =` / `BDSP_ROMFS` |
| Spielstand | `<Hauptordner>/save` (`save_1/SaveData.bin`, `Backup.bin`, `user_id.hex`, `backups/`) | `save =` / `BDSP_SAVE` / `--save` |
| Shader-Cache, Bilder | `~/Library/Caches/dev.local.xnubdsp` (`shaders/`, `shots/`) | `cache =` / `BDSP_CACHE` |
| Logs | `~/Library/Logs/dev.local.xnubdsp/bdsp.log` (letzter Lauf: `bdsp.prev.log`) | `logs =` / `BDSP_LOG_DIR` |

Die Reihenfolge ist: Umgebungsvariable vor `config.ini` vor Standard. Weitere Schlüssel in `config.ini`: `language` (z. B. `de`, `en-US`; die Sprache, die das Spiel von der Konsole erfragt), `window`, `fullscreen`, `pause_on_focus_loss`, `pad_layout`, `backups` (Zahl der Startsicherungen, Standard 10). Relative Pfade (Umgebung und Kommandozeile) werden vor dem Start gegen das aufrufende Verzeichnis aufgelöst. Aus Finder/Dock gestartet schreibt die App ihr Protokoll in die Logdatei (stdout ist dort `/dev/null`); aus dem Terminal bleibt es auf dem Bildschirm (`BDSP_LOG_STDOUT=1` erzwingt das).

**Shader-Cache:** Die NVN-Schicht schreibt relativ nach `work/recomp/cache/shaders`. Die App wechselt deshalb in `<Cache>/cwd` und legt dort `work/recomp/cache` als Verweis auf den Cache-Ordner an; die übersetzten Shader (MSL) landen so in `~/Library/Caches/dev.local.xnubdsp/shaders`, ohne die NVN-Quellen zu ändern. Der Cache lässt sich jederzeit löschen.

## Spielstand

**Format:** unverändert. Das Spiel öffnet `SaveData.bin` (und legt `Backup.bin` an) in `save_1/`; beide Dateien sind 979.108 Byte (Version 0x34, MD5 bei 0xE9818), also **dieselben Dateien wie bei Ryujinx** (`bis/user/save/<ID>/0/`) und beim Switch-Export. Zurück zu Ryujinx: beide Dateien aus `save_1/` dorthin kopieren.

**Sicherung beim Start:** vor jedem Start kopiert die App `SaveData.bin`/`Backup.bin` nach `save/backups/start-<Datum>-<Zeit>/`, wenn sich der Stand seit der letzten Sicherung geändert hat; es bleiben die letzten 10 (`backups`). Importe und das Zurücksetzen sichern zusätzlich nach `backups/import-…` bzw. `reset-…`.

**Import** (Menü, Ablegen auf Fenster oder Dock-Symbol, `BDSP --import-save <Pfad>`): akzeptiert `SaveData.bin` oder einen Ordner (direkt, `0/`, `save_1/`); geprüft werden Version (0x25 bis 0x34), exakte Größe je Version und die MD5-Prüfsumme (C-Umsetzung von `scripts/bdsp_save.py`; Test `scripts/recomp/rt-bdsp/test/run_save_test.sh` mit synthetischen Ständen). Ungültige Dateien werden mit Grund abgelehnt (`bdsp_save.py check/fix-hash` hilft bei kaputter Prüfsumme). Ein `Backup.bin` daneben wird mitgenommen, wenn es gültig ist; liegt `ExtraData0` bei (Ryujinx), liest die App daraus die Benutzer-ID (Byte 8 bis 23, wie `install_save.sh`). Schreiben geschieht atomar (`.tmp`, `fsync`, `rename`).

**Wichtig:** Importieren oder Zurücksetzen verlangt einen Neustart, weil das laufende Spiel seinen Stand im Speicher hält; die App führt ihn selbst aus. Beenden mitten im Speichern (Cmd+Q) ist nicht abgesichert.

## Build-Stufe `recomp`

Aufruf und Optionen: `docs/bauen.md`. Ablauf (`scripts/recomp/app/recomp_build.sh`, von `build_all.sh` aufgerufen):

| Schritt | Werkzeug | Inkrementell durch |
|---|---|---|
| 1 Generator | `scripts/recomp/gen_all.sh` (`eh_gen.py`) → `work/recomp/gen4` (rund 1 GB C, 2.495 Dateien) | Teilmarker `recomp-gen` (Hash aus den vier Modulen, Generatorskripten, Klon-Werkzeugen); bei vorhandenem C wird neu erzeugt und nur **Inhaltsänderungen** übertragen (`rsync -c`), Zeitstempel bleiben |
| 2 Übersetzen | `scripts/recomp/build_all.sh` (`clang -O1`, `-O0` für Einzelfunktionen ≥ 300 KB), höchstens 4 Jobs → `work/recomp/obj4` | Zeitstempel je Chunk (`compile_chunk.sh`), Teilmarker `recomp-obj`, geänderte `-O0`-Schwelle verwirft nur betroffene Objekte |
| 3 Modulbilder | `mkimages.sh` mit `hle_nvn.txt` → `work/recomp/img_app` | schnell (2 s), immer |
| 4 Laufzeit | `rt-bdsp/build.sh` mit `BDSP_APP=1` (+ `prepare.sh`/`build_nvn.sh`, Apple-clang für Objective-C), bindet libgame → `work/recomp/bdsp_app` | Zeitstempel je Quelldatei |
| 5 App | `scripts/recomp/app/make_app.sh`: Bundle, Info.plist, Symbol (`make_icon.py`), `bundle_dylibs.py`, `codesign` ad hoc, `codesign --verify --deep --strict`, Prüfung auf Homebrew-Pfade | immer (rund 20 s) |
| 6 Daten | APFS-Klon von `work/romfs` nach `<Hauptordner>/romfs` (`--no-install-data` überspringt) | Kennung `romfs.stamp` (main-Hash + Dateizahl) |

Der Stufenmarker `work/.stages/recomp.json` fasst alles zusammen (Eingaben: Module des Dumps, Generator, `rt-bdsp/`, NVN-Quellen des Klons, `shader_translator/`, `scripts/recomp/app/`, Optionen); ein zweiter Aufruf meldet „Marker passt, übersprungen“.

**Eingriffe in bestehende Dateien (klein gehalten, weil `ap-recomp-ios` parallel an `rt-bdsp/` arbeitet):** `main.c` (Aufruf `bdsp_app_init` unter `#ifdef BDSP_APP`), `nvn/nvn_glue.c` (Tasten/Sticks der Hülle `g_ext_buttons`/`g_ext_stick` in `buttons_now`/`npad_fill`, zwei schwache Stummel `menu_handle_event`/`menu_apply_window_requests`), `services_gfx.c` (`g_bdsp_paused` hält das Vsync-Ereignis an), `build.sh` (Schalter `BDSP_APP=1`, `NVN_RT`), `recomp/build_all.sh` (`O0_BYTES`). Neu: `rt-bdsp/app/` (`app.h`, `app_config.c`, `app_save.c`, `app_ui.m`) und `scripts/recomp/app/`.

### Signatur, Hardened Runtime, Gatekeeper

- Standard: **ad hoc** (`codesign -s -`). Die App startet lokal ohne Entwicklerkonto; aus dem Finder beim ersten Mal ggf. *Rechtsklick → Öffnen*. Das Quarantäne-Attribut (`com.apple.quarantine`) entsteht nur bei Downloads, nicht beim lokalen Bauen.
- `--hardened`: Signatur mit `--options runtime`. **Gemessen:** läuft ohne weitere Ausnahmen (Metal, FFmpeg-Film, Gastcode: 40 s Lauf); nötig ist nur das Entitlement `com.apple.security.cs.disable-library-validation`, weil die gebündelten Bibliotheken ad hoc statt mit derselben Team-ID signiert sind. Das Entitlement in `scripts/recomp/app/BDSP.entitlements` darf **keine XML-Kommentare** enthalten (AMFI weist sie ab).
- **JIT wird nicht gebraucht:** der Gastcode ist vorab nach C übersetzt und als normaler Maschinencode im Programm; es gibt kein `MAP_JIT`, kein Entitlement `allow-jit`/`allow-unsigned-executable-memory`. Das Gastfenster wird mit `mach_vm_allocate` (Daten, lesen/schreiben) reserviert.
- Keine App-Sandbox (die Pfade unter Application Support/Caches/Logs sind frei zugänglich, `~/…/romfs` ist ein Klon). Eine Sandbox bräuchte Entitlements für Dateizugriff und wurde nicht versucht.
- Für die Weitergabe an andere Macs (Notarisierung) fehlt ein Entwicklerkonto; das ist ausdrücklich nicht Ziel (die App enthält Spielcode des Nutzers).

## Tests

Standard bleibt der Lauf ohne sichtbares Fenster (`--headless --screenshot-after N`, Bilder nach `BDSP_SHOT_DIR`). Zusätzliche Testhaken der Hülle (nur Umgebungsvariablen, wirkungslos ohne sie):

| Variable | Wirkung |
|---|---|
| `BDSP_KEY_SCRIPT="Sekunde:TASTE:Dauer,…"` (oder `@Datei`) | echte SDL-Tastenereignisse durch die normale Belegung (z. B. `62:Z:0.4,108:W:2.5`); Tastennamen wie `SDL_GetScancodeFromName` |
| `BDSP_UI_SELFTEST="Sekunde:Aktion,…"` | Menüaktionen ohne Rückfrage: `fs`, `w960`…`w2560`, `pause`, `restart` (Tastenkürzel lassen sich von außen nicht senden: Bedienungshilfen sind nicht erlaubt) |
| `BDSP_PAUSE_SELFTEST="ab:Dauer"` | Pause per Zeitplan |
| `BDSP_MENU_DUMP=1` | gibt die Menüstruktur im Log aus |
| `BDSP_LOG_STDOUT=1`, `BDSP_NO_ALERT=1` | Log auf dem Bildschirm bzw. keine Meldungsfenster |

(`--input-script` aus `docs/recomp-gate2.md` wirkt weiter; es setzt die Tasten direkt auf Npad-Ebene.)

**Ergebnisse (gemessen, Last 25 bis 50):**

- **Spielablauf per Tastatur:** `BDSP_KEY_SCRIPT="62:Z:0.4,72:Z:0.4,82:Z:0.4,92:Z:0.4,106:D:0.5,108:W:2.5"`, Fenster versteckt, Bilder alle 300 Bilder. Z (= A) führt vom Titel über „Weiter“ in das Feld (Stadt, Bild 2.400: gepflasterte Straße, Haus mit blauem Dach, Spielfigur mit roter Mütze, NPC, Nadelbäume; Beschreibung wie `docs/recomp-gate2.md`); danach D und W (linker Stick nach rechts und oben) bis zur Pokécenter-Tür und hinein. **Bild 2.700 bis 4.200 (Innenraum):** Schwester Joy mit rosa Haar und Haube hinter dem roten Tresen, links und rechts je ein Blumenkorb, links eine Frau mit grünlichem Haar und ein Mülleimer, rechts zeitweise eine Frau mit braunem Zopf und rosa Oberteil, unten die Spielfigur mit rotem Hut und gelbem Lichtkreis. **Abweichungen (Darstellungsfehler, Gate 2 Punkt „Wasser/Texturen“ verwandt):** Boden und Wände sind einfarbig (blau, dazu ein brauner Keil statt des gekachelten Bodens), am rechten Rand zieht sich ein Streifen dunkler senkrechter Striche; Figuren, Tresen und Möbel sind korrekt. Die Ursache ist nicht untersucht (*vermutet:* fehlende Textur-/Lightmap-Bindung im Innenraum-Shader).
- **Pause:** `BDSP_PAUSE_SELFTEST=40:6`: 40,3 s Bild 385, Pause 40 bis 46 s, Bild 405 bei 46,9 s (Lücke 5.996 ms laut Metal-Zähler), danach wieder 39 Bilder/s.
- **Menü:** Struktur und Kürzel per `BDSP_MENU_DUMP` geprüft (App-Menü plus Spiel, Ansicht, Fenster, Hilfe, 20 Einträge). **Sichtbarer Lauf** (aus dem Finder gestartet mit `open -n`, Standardpfade, ohne Spielstand): Fenster mit Menüleiste *BDSP Spiel Ansicht Fenster Hilfe*, Titel „BDSP“, Dock-Symbol (blaue Raute), das **Spiel erscheint im Fenster** (Sprachauswahl mit zwei Spalten, hellblauer Kristallhintergrund, Text „Select the language you would like to play in.“); die Logdatei `~/Library/Logs/dev.local.xnubdsp/bdsp.log` wurde angelegt. Fenstergröße 960×540 per Selbsttest gesehen. Vollbild per Selbsttest ausgelöst, aber der Screenshot wurde von einem fremden Systemdialog (Bildschirmaufnahme-Anfrage eines anderen Programms) verdeckt: Vollbild-Ansicht **nicht gesehen**.
- **Neustart:** `BDSP_UI_SELFTEST=12:restart`: das alte Exemplar endet, nach einer Sekunde startet `open -n` ein neues (neue PID, Standardpfade). **Befund:** die Umgebung des Aufrufers wandert über `open` zum neuen Exemplar; dadurch startete sich das neue Exemplar mit demselben Testzeitplan immer wieder neu (Schleife, mit dem Verschieben des Bundles beendet). Behoben: `bdsp_app_restart` entfernt die Testhaken (`BDSP_UI_SELFTEST`, `BDSP_KEY_SCRIPT`, `BDSP_PAUSE_SELFTEST`, `BDSP_INPUT_SCRIPT`, `LARECOMP_SCREENSHOT_*`) aus der Umgebung; der Neustart danach lief genau einmal.
- **Spielstand:** `--import-save work/recomp/save/save_1` installiert `SaveData.bin` (979.108 Byte, sha256 `0396a4a62735…` wie der Teststand) und `Backup.bin`; eine Kopie mit einem verfälschten Byte wird wegen der Prüfsumme abgelehnt (Exit 1, nichts geschrieben). C-Test mit synthetischen Ständen: gültig/ungültig/falsche Größe/Version, Ryujinx-Layout mit `ExtraData0` (Benutzer-ID), Datei statt Ordner, Sicherung beim Start (neu, unverändert, auf 3 beschnitten), Zurücksetzen: **alle Prüfungen bestanden**.
- **Hardened Runtime:** Signatur `flags=0x10002(adhoc,runtime)`, 40 s Lauf ohne Fehler.
- **Python-Tests:** `python3 -m unittest scripts.tests.test_build_stages scripts.tests.test_build_all` (57 Tests, grün; neu: Stufenreihenfolge, Preflight-Grenzen, Hash-Abhängigkeiten, Dry-run).

## Bauzeit und Größen

**Kaltbau aus dem eigenen Dump** (gemessen 2026-10-19 in einem frischen Ordner, ohne vorhandenes C/Objekte, Last 25 bis 50 durch andere Prozesse, 4 Compiler):

| Schritt | Zeit | Größe / Anmerkung |
|---|---|---|
| 1 Generator (4 Module) | **7,2 min** (main 357 s, sdk 46 s, subsdk0 26 s; CPU-Summe nur rund 1,5 min, der Rest ist Warten auf die Last; unbelastet rund 75 s laut `docs/recomp-gate1.md`), bis 2,6 GB RSS | 2.495 C-Dateien, **995 MB**; **byte-identisch** zum zuvor erzeugten C (`diff -rq`: keine Abweichung, also deterministisch) |
| 2 Übersetzen | **19,8 min** (1.186 s), 2.430 Dateien `-O1`, 65 Dateien `-O0` (Einzelfunktionen ab 300 KB) | Objekte **303 MB**; größte Datei 95 s/1,7 GB RSS (`-O1`), unbelastet früher 11,7 min (`docs/recomp-gate1.md`) |
| 3 Modulbilder | 1 s | 104 MB |
| 4 Laufzeit + NVN/Metal + Link | 7 s | `bdsp_app` **225 MB** |
| 5 App (Bundle, Bibliotheken, Signatur) | 10 s | **361 bis 363 MB** (MacOS 223, Resources 104, Frameworks 35) |
| **Gesamt kalt** | **rund 27,5 min** | Platzbedarf der Stufe selbst rund 1,7 GB (kurzzeitig bis 2,7 GB mit der Zwischenablage `gen4.new` bei Wiederholung) |

**Folgeläufe (gemessen):** unveränderte Eingaben: **0,4 s** („Marker passt, übersprungen“); nur Laufzeit/App geändert: rund **13 bis 50 s** (Marker für Generator und Objekte passen, Bau + Bündel); Generator erneut: 1 bis 7 min je nach Last, danach übersetzt der Compiler nur Dateien mit geändertem Inhalt. Der Preflight (≥ 25 GB) wurde auf dieser Maschine mit 14 GB freiem Platz bewusst mit `--min-free-gb 10` umgangen und lehnte ohne die Option mit Exit-Code 8 ab. Zum Vergleich der Frist: Gesamtziel „unter 30 Minuten“ (`docs/recomp-spike-2.md`) ist auch unter Last erfüllt.

Der Test des Kaltbaus lief mit der Stufenlogik von `recomp_build.sh` (eigener Arbeitsordner, `--no-install-data`); die fertige App aus diesem Lauf startete (70 s, kein Absturz).

## Absturzsuche

1. **Log:** `~/Library/Logs/dev.local.xnubdsp/bdsp.log` (App aus dem Finder) bzw. der Terminalauftrag. Ein Absturz im Gastcode meldet `*** Signal N bei Hostadresse …`, einen Host-Rückverfolgungsauszug (`f_70xxxxxxxx` = übersetzte Gastfunktion) und die Ringe der letzten Gastfunktionen je Thread; Abbrüche der Laufzeit stehen als `FATAL: …` im Log.
2. **Gastnamen:** `python3 -I scripts/recomp/il2sym.py` erzeugt einmalig `work/recomp/il2sym.tsv` (68.183 IL2CPP-Methoden, nur Namen); `scripts/recomp/app/crashsym.sh <log>` ergänzt Gastadressen im Bericht (`f_70xxxxxxxx`, Ring) um die Methodennamen (`symres.py`). Mit `BDSP_IL2SYM=work/recomp/il2sym.tsv` meldet die Laufzeit zusätzlich jede Spielmethode beim ersten Aufruf.
3. **Host-Adressen:** `scripts/recomp/app/crashsym.sh --atos <Ladeadresse> <Adresse>…` ruft `atos -o BDSP -arch arm64 -l <Ladeadresse>` auf (Ladeadresse aus dem Systembericht `~/Library/Logs/DiagnosticReports/BDSP-*.ips`, „usedImages“). Die Binärdatei enthält Symbole und Debug-Informationen der Laufzeit (`-g`).
4. **Beispiel:** ein früherer Fehlstart (fehlende `hle.txt` im Bundle) endete nach 0,1 s mit `Signal 11` in `f_70002c1d90`; der Bericht enthielt Rückverfolgung und Ring, die Ursache war damit eingrenzbar (HLE-Slots der Modulbilder).

## Lücken

- **MetalFX** (optional) ist nicht eingebaut: `output_scale` ist fest (1:1 mit Letterbox); die Hooks `g_settings.upscaler` bestehen, aber `renderer.m` wird nicht mit einem Skalierer gespeist.
- **Controller** nur durch Code und Abbildung geprüft, nicht mit Hardware; die Zuordnung der GameController-Tasten für Switch-Pro-Controller (`buttonA` unten/rechts) ist *vermutet* positional.
- **Drag & Drop** auf das Fenster/Dock-Symbol löst `SDL_EVENT_DROP_FILE` aus und ruft denselben Import wie das Menü; mit echter Maus nicht ausprobiert.
- **Neustart** per `open -n` (Bundle) bzw. `exec` (ohne Bundle): Bundle-Variante gemessen (siehe Ergebnisse), `exec`-Variante nicht getestet; Fenstergröße/Vollbild kommen nach dem Neustart wieder aus `config.ini`.
- **Vollbild-Ansicht** nicht gesehen (Screenshot verdeckt), nur der Aufruf per Selbsttest.
- **`-O0`-Schwelle im Dauerordner:** das bereits vorhandene `work/recomp/obj4` stammt aus der Zeit mit der Schwelle 1 MB; Dateien zwischen 300 KB und 1 MB blieben dort `-O1` (der Kaltbau oben nutzt 300 KB). Wirkung auf Leistung nicht gemessen.
- **Innenraum-Darstellung** (Boden/Wände einfarbig, Streifen am rechten Rand) und die bekannten Gate-2-Abweichungen (Wasser, Titeltext rot) sind Sache der NVN-/Shader-Schicht, nicht der App-Hülle.
- **Pause bei Fokusverlust** (optional) ist wie die Menü-Pause umgesetzt (Vsync-Ereignis); nur die Menü-/Zeitplanvariante wurde gemessen.
- **Beenden** per Cmd+Q beendet den Prozess sofort; ein gerade laufender Schreibvorgang des Spiels ist nicht geschützt (der Spielstand wird atomar nur von der App-Hülle geschrieben, nicht vom Gast).
- **Sprache:** Standard `en-US` (Wert der Laufzeit), per `language` änderbar; nicht gemessen mit anderen Sprachen.
