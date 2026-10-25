# Bauanleitung: BDSP-Rekompilation

**English version: [BUILD.md](BUILD.md)**

## 1. Überblick

BDSP ist eine Rekompilation des Originalcodes von *Pokémon Brilliant Diamond*. Der Bau wandelt den
Maschinencode des Spiels in C um, übersetzt ihn und bindet ihn mit einer Laufzeit, die die Konsolendienste
und ein Grafik-Backend bereitstellt (Metal auf macOS und iPadOS, Vulkan unter Linux).

- Das Repository enthält nur eigenen Code, Skripte und Dokumentation. Es enthält keine Spieldaten, keine
  Schlüssel, keine Speicherstände und keine Screenshots.
- Du brauchst einen eigenen Dump des Spiels: die Basis-`.xci` (optional das `.nsp`-Update) und deine
  `prod.keys` (plus `title.keys`). Lege sie außerhalb des Repositorys ab. Die Skripte lesen sie nur.
- Alles, was die Skripte erzeugen, landet in `work/`. Dieser Ordner ist von Git ignoriert. Committe ihn nie.
- Ziele: die macOS-App (am weitesten), die iPadOS-App, Linux mit Vulkan (in Arbeit, Abschnitt 6).

## Schnellstart (geführt)

Zwei geführte Installer erledigen alles aus dieser Anleitung für dich. Mit `--dry-run` zeigen sie vorab, was sie tun würden.

- **macOS:** Doppelklick auf `install.command` im Finder oder `./install.command`. Er prüft Xcode, Homebrew (und bietet den
  offiziellen Homebrew-Installer an, falls es fehlt), die Homebrew-Pakete, Python und eine private Python-Umgebung `work/venv`
  (Pillow, capstone, unicorn). Danach ziehst du deine `.xci`, optional das Update `.nsp` und deine `prod.keys` in das Fenster,
  und er führt die Stufen `tools`, `extract` und `recomp` von `scripts/build_all.sh` aus (Abschnitt 4). Plane mindestens 40 GB freien
  Platz ein; ein gemessener Lauf auf einem vorbereiteten Mac mit acht CPU-Threads dauerte etwa acht Minuten (Abschnitt 4.2).
- **Linux:** `./install-linux.sh` starten. Er erkennt `apt`, `dnf` oder `pacman`, listet die fehlenden Entwicklungspakete und
  installiert sie nach deiner Zustimmung (der Paketmanager fragt per `sudo` nach deinem Administrator-Passwort, das Skript sieht
  es nie). Der Vulkan Memory Allocator steckt auf Arch nicht in den offiziellen Paketen: Das Skript bittet dich, ihn selbst aus dem
  AUR zu installieren. Danach richtet es `work/venv` ein, fragt nach deinen Dateien und führt den Bau aus Abschnitt 6.2 aus.
  Mehrere Stunden; die Linux-Version ist in Arbeit (Abschnitt 6.4).

Beide Skripte sprechen Englisch, Deutsch, Spanisch und Portugiesisch (Systemsprache oder `BDSP_LANG=de|en|es|pt`). Die Texte
liegen in `scripts/install/lang/<Kürzel>.sh`; für eine neue Sprache `en.sh` kopieren, die Werte übersetzen und das Kürzel in
`scripts/install/common.sh` ergänzen. Bricht ein Skript ab, starte es erneut: fertige Stufen werden übersprungen. Die folgenden
Abschnitte beschreiben dieselben Schritte von Hand.

## 2. Gemeinsame Voraussetzungen

| Was | Wofür | Prüfen mit |
|---|---|---|
| Xcode 26 oder neuer (in `/Applications/Xcode.app`), einschließlich Icon Composer, Lizenz akzeptiert | macOS-/iPadOS-Bau und native Liquid-Glass-Icons | `xcodebuild -version` |
| Command Line Tools | Compiler, `codesign`, `otool`, `iconutil` | `xcode-select -p` |
| Python 3.9 oder neuer | `build_all.sh`, Hilfsskripte | `python3 --version` |
| Pillow | Originalicons konvertieren und deterministisch gestalten | `python3 -c 'from PIL import Image'` |
| Homebrew-Pakete `llvm`, `sdl3`, `ffmpeg`, `pkg-config` | macOS-App (Stufe `recomp`) | `pkg-config --exists sdl3 libavcodec libavformat libavutil` |
| Python-Pakete `capstone`, `unicorn` in `tools/pydeps` | Generator (Stufe `recomp`) | `ls tools/pydeps` |
| `git`, `make`, `cc` | Stufe `tools` (baut `hactool`) | `command -v git make cc` |

Homebrew- und Python-Pakete installieren:

```sh
brew install llvm sdl3 ffmpeg pkg-config
python3 -m pip install --target tools/pydeps capstone unicorn
```

Für die Stufe `recomp` muss das Homebrew-LLVM vor `/usr/bin` im `PATH` stehen:

```sh
export PATH="/opt/homebrew/opt/llvm/bin:$PATH"
```

Nichts wird mit `sudo` installiert. Schlägt eine Prüfung fehl, zeigt `scripts/build_all.sh preflight`,
was fehlt.

## 3. Lokale Konfiguration (`work/local.env`)

Lege die Datei `work/local.env` an. Sie ist von Git ignoriert. Trage diese Werte an keiner anderen Stelle
im Repository ein.

```sh
TEAM_ID=<TEAM_ID>
```

- `TEAM_ID`: deine Apple-Developer-Team-ID. Nur für den iPadOS-Bau (`deploy_ios.sh`). Sie wird per
  Kommandozeile an `xcodebuild` übergeben und nicht ins Projekt geschrieben.

Schreibe die Datei in Shell-Syntax: keine Leerzeichen um das `=`.

## 4. macOS-App (Stufe `recomp`, `--target macos`)

### 4.1 Spieldaten bereitstellen (Stufe `extract`)

Die Stufe `recomp` liest `work/exefs` und `work/romfs`. Erzeuge sie zuerst:

```sh
scripts/build_all.sh --only tools,extract --xci <Pfad/zum/Spiel.xci> --keys <Ordner/mit/prod.keys>
```

Liegen die Schlüssel in getrennten Dateien, verwende `--prod-keys <Datei>` und `--title-keys <Datei>`
statt `--keys`. Hast du das Update, ergänze `--nsp <update.nsp>`.

### 4.2 App bauen

```sh
scripts/build_all.sh --dry-run --only recomp --target macos   # nur Plan, ändert nichts
scripts/build_all.sh --only recomp --target macos
```

Ergebnis: `work/builds/macos-recomp/BDSP.app` (arm64, Metal, ad hoc signiert).

Am 23.10.2026 benötigten die Stufen `tools,extract,recomp` aus einem frischen GitHub-Clone mit den aktuellen lokalen Quelländerungen **7 Minuten 42 Sekunden** bis zur signierten `BDSP.app`. Gemessen wurde auf einem Apple-Silicon-Mac mit 8 CPU-Threads und 16 GiB RAM, mit einer Basis-XCI ohne Update-NSP und leeren Projekt-Builddaten. Davon entfielen 5 Sekunden auf Hactool, 23 Sekunden auf die Extraktion, 68 Sekunden auf die C-Generierung und etwa 5 Minuten 25 Sekunden auf den C-Compile mit acht Jobs. Danach folgten Modulbilder, Runtime/Metal, Bundle, Signatur und RomFS. Die 361 MiB große arm64-App bestand `codesign --verify --deep --strict`. Der GitHub-Clone dauerte zusätzlich etwa eine Sekunde; Python-Venv und vier Pakete etwa drei Sekunden mit vorhandenem Pip-Downloadcache. Xcode 27.1 und Homebrew-Bibliotheken waren bereits installiert. Historische langsamere Messungen unter Last stehen in `docs/recomp-macapp.md`. Spätere Bauten nutzen die Marker wieder und sind deutlich schneller (Abschnitt 7).

Nützliche Optionen:

| Option | Bedeutung |
|---|---|
| `--recomp-jobs N` | überschreibt die aus CPU und RAM berechnete Anzahl paralleler Compiler |
| `--recomp-o0-kb N` | Funktionen ab N KB werden mit `-O0` übersetzt (Standard 300) |
| `--force` | Stufe neu bauen, auch wenn der Marker passt |
| `--hardened` | mit Hardened Runtime signieren (Standard: nur ad hoc) |
| `--no-install-data` | RomFS nicht unter Application Support ablegen |

### 4.3 App starten und Optionen setzen

Starte die App im Finder (`open work/builds/macos-recomp/BDSP.app`) oder im Terminal. Umgebungsvariablen
werden nur übergeben, wenn du das Programm direkt startest:

```sh
BDSP_FPS=60 work/builds/macos-recomp/BDSP.app/Contents/MacOS/BDSP
```

| Variable | Werte | Wirkung |
|---|---|---|
| `BDSP_FPS` | `30`, `60`, `120` | Bildrate. Andere Werte werden ignoriert. Überschreibt die gespeicherte Menü-Einstellung. |
| `BDSP_PRESENT_AT` | `off`, `min`, `grid`, `lock` | Zeitsteuerung der Bildpräsentation. Standard auf dem Mac: `lock`. `off` stellt das alte Verhalten wieder her. |
| `BDSP_EXEC_WORKER` | `0` | `0` schaltet den Übersetzungs-Worker ab und nutzt den synchronen Pfad. Standard: an. |
| `BDSP_FPS_INTERVAL` | Sekunden | Abstand der `fps`-Logzeile (Standard 2). |

Aus dem Terminal bleibt das Protokoll auf dem Bildschirm. Aus dem Finder geht es in den Log-Ordner
(`BDSP_LOG_STDOUT=1` erzwingt die Ausgabe im Terminal). Pfade für Konfigurationsdatei, Spielstand und
Cache: `docs/recomp-macapp.md`.

Einschränkungen: kein Netz. Beim ersten Start ggf. Rechtsklick → Öffnen (Gatekeeper, ad hoc
Signatur).

## 5. iPadOS-App (`scripts/recomp/ios/deploy_ios.sh`)

### 5.1 Voraussetzungen

- `TEAM_ID` in `work/local.env` (Abschnitt 3).
- Ein gekoppeltes iPad, entsperrt, als Gerät vertraut und verbunden. Das Skript wählt das erste verbundene iPad.
- Die iOS-Bauteile `work/recomp/obj32` und `work/recomp/img32`. Erzeuge sie mit
  `scripts/recomp/ios/gen32.sh` (siehe `docs/recomp-ios.md`).
- `work/exefs` mit `main.npdm` aus der Stufe `extract`.

### 5.2 Befehle

```sh
scripts/recomp/ios/deploy_ios.sh build          # Laufzeit, libgame.a, Ressourcen und App (xcodebuild)
scripts/recomp/ios/deploy_ios.sh install        # App auf das iPad installieren
scripts/recomp/ios/deploy_ios.sh data           # work/romfs in den App-Container kopieren (einmalig, rund 4,7 GB)
scripts/recomp/ios/deploy_ios.sh save           # optional: Speicherstand aus work/recomp/save kopieren
scripts/recomp/ios/deploy_ios.sh run 120        # 120 Sekunden starten; ohne Zahl bis Strg+C
scripts/recomp/ios/deploy_ios.sh shots          # Screenshots nach work/visual/ipad-recomp/ holen
scripts/recomp/ios/deploy_ios.sh files [Pfad]   # Dateiliste des App-Containers
```

Umgebungsvariablen des Skripts:

- `DEVICE_NAME`: Teil des Gerätenamens, wenn mehrere iPads verbunden sind.
- `BUNDLE_ID`: Standard `dev.local.xnubdsp`.
- `RUN_ENV`: JSON mit Umgebungsvariablen für `run`, zum Beispiel `{"BDSP_TIMEOUT":"130"}`.

Das Protokoll jedes `run` landet in `work/builds/logs/ipad-recomp-<Zeit>.log`. Das Bau-Protokoll steht in
`work/builds/logs/ios-recomp-xcodebuild.log`.

### 5.3 Signierung

Die Signierung machst du selbst. Wähle bei einem fehlgeschlagenen Bau Team und Provisioning in Xcode.
Das Skript übergibt `TEAM_ID` und `-allowProvisioningUpdates` an `xcodebuild`. Ändere
`project.pbxproj` im Repository nicht, um das Team einzustellen.

## 6. Linux mit Vulkan und Qt6

Die vollständige, gepflegte Paketliste steht in [BUILD.md](BUILD.md), Abschnitt 6.
Der Linux-Build läuft direkt auf dem Linux-Rechner, vom Repo-Hauptverzeichnis aus; seine Skripte liegen unter `scripts/recomp/linux/local/` (die Abhängigkeitsprüfung unter `scripts/recomp/linux/deps.sh`).

Installiere auf dem Linux-Rechner die Entwicklungsdateien für Qt6 Widgets, SDL3,
Vulkan-Header und -Loader, shaderc, Vulkan Memory Allocator und FFmpeg.
Laufzeitpakete allein reichen nicht. Fedora benötigt insbesondere
`qt6-qtbase-devel`, `vulkan-loader-devel`, `vulkan-headers`, `SDL3-devel`,
`libshaderc-devel` und `VulkanMemoryAllocator-devel`. Dazu kommen passende
FFmpeg-Devel-Pakete desselben Anbieters wie die vorhandenen Laufzeitbibliotheken.

Die Skripte installieren nichts und kopieren keine Homebrew-Header. Der reguläre
Build verwendet Systempakete über pkg-config; alte include-vk- oder deps/include-
Verzeichnisse werden nicht automatisch bevorzugt. Es werden keine zusätzlichen
Qt-/SDL-/Vulkan-/FFmpeg-Bibliotheken ins Repository aufgenommen.

Installiere zusätzlich das Paket `time` (liefert `/usr/bin/time`) und die Python-Abhängigkeiten `lz4`, `capstone` und `unicorn`.
Die installierten Pakete prüfst du ohne Kopieren, Download oder Installation mit
`bash -c 'source scripts/recomp/linux/deps.sh && linux_require_runtime && linux_require_qt'`
(ohne `linux_require_qt`, wenn du die Qt-Hülle nicht baust).
Stelle die Eingaben `work/exefs/`, `work/romfs/` und `work/recomp/icons/source/` bereit. Extrahiere dazu einen selbst rechtmäßig erstellten Spieledump auf diesem Rechner mit dem Befehl aus Abschnitt 4.1 (die Stufe `extract` schreibt auch die Icon-Quelle), oder kopiere vorhandene Ordner im selben Aufbau hierher. Die Linux-Build-Skripte lesen keine Schlüssel und keine `.xci`.
Optional vergleicht `scripts/recomp/linux/local/setup.sh` die Eingaben mit `work/exefs.sha256`, wenn diese Datei existiert; sonst gibt das Skript nur einen Hinweis. Die Datei erzeugst du im Repo-Hauptverzeichnis mit `sha256sum work/exefs/rtld work/exefs/main work/exefs/sdk work/exefs/subsdk0 > work/exefs.sha256`.

Erzeuge und übersetze die Gastmodule mit
`bash scripts/recomp/linux/local/build_all.sh`. Baue Vulkan-Laufzeit und Qt-Hülle
im selben Prozess mit `bash scripts/recomp/linux/local/vk_build.sh --qt`; das
Ergebnis liegt unter `work/recomp/bdsp_boot_vk_qt`. Extrahierte Icon-Varianten
werden während des Builds deterministisch in Linux-Assets unter
`work/recomp/icons/` umgewandelt. Starten lässt sich die App lokal mit
`bash scripts/recomp/linux/local/vk_qt.sh`. Diese Variante unterstützt natives
Wayland und X11. Die getrennte X11-Hülle bleibt mit `BDSP_QT_PROCESS=1` verfügbar.
Modulbilder für `vk_qt.sh` und `vk_run.sh` liegen unter `work/recomp/img_gfx`. Einmal erzeugen: `IMG=work/recomp/img_gfx HLE_LIST=scripts/recomp/rt-bdsp/hle_nvn.txt bash scripts/recomp/rt-bdsp/mkimages.sh` (wie bei der macOS-App, `scripts/recomp/app/recomp_build.sh`).
Konkrete Sitzungs-IDs und Authentifizierungspfade committe nie.

Am 23.10.2026 wurde ein frischer Nobara-44-x86_64-Checkout mit Basis-XCI und
Update-NSP als einzigen Spieldaten und den installierten Fedora-Entwicklungspaketen
gebaut. `eh_gen` dauerte 52,9 s; zwölf parallele Clang-Prozesse übersetzten
2.369 C-Dateien in 351,3 s (57 mit `-O0`, 2.312 mit `-O1`). Beim ersten
geführten Lauf zeigten sich macOS-spezifische Includes und ein QoS-Aufruf in
der Runtime; nach Plattform-Guards lief `install-linux.sh` bis zum Ergebnis.
Ein zehnsekündiger Start der Qt-/Vulkan-App unter nativem Wayland zeigte 306
Frames. Der erneute geführte Lauf erzeugte C und linkte die Bibliothek in 68 s;
keine C-Objekte mussten erneut kompiliert werden. Die Binärdatei nutzt dynamisch
die installierten Systembibliotheken. Die vollständigen Optimierungslisten
stehen in [clang-optimierungsstufen.md](../todo/clang-optimierungsstufen.md).
Linux-Ton und längere Spiel-/Darstellungstests bleiben offen.
Messungen und Vulkan-Stand: [recomp-linux.md](recomp-linux.md) (englisch).

## 7. Überblick über die Bau-Stufen

Reihenfolge der Stufen: `tools extract recomp shaders`. Mit `--only` oder
`--from`/`--to` läufst du einen Teil. Prüfe vorher mit `--dry-run`. Jede Stufe schreibt einen Marker
`work/.stages/<Stufe>.json` mit einem Eingabe-Hash. Passt der Hash, wird die Stufe übersprungen
(`--force` baut sie neu).

| Stufe | Zweck | Für die Apps nötig |
|---|---|---|
| `tools` | prüft Werkzeuge, baut `hactool` nach `tools/hactool` | ja (für `extract`) |
| `extract` | entschlüsselt `.xci`/`.nsp` nach `work/exefs`, `work/romfs`, `work/manifest.json` | ja |
| `recomp` | macOS-App aus der Rekompilation | nur für die macOS-App |
| `shaders` | wandelt zwischengespeicherte Spiel-Shader für die Unity-Shader-Werkzeuge um (braucht UnityPy in `tools/pydeps`) | nein: `recomp_build.sh` liest nur `work/exefs` und `work/romfs` |

Die Unity-Stufen `il2cpp`, `masterdata`, `video` und `audio` wurden entfernt (sie liegen im Branch `unity`).

### 7.1 Die Stufe `recomp`

`scripts/recomp/app/recomp_build.sh` führt sechs Schritte aus:

1. **Generator:** Module aus `work/exefs` → C in `work/recomp/gen4` (rund 1 GB). Marker `recomp-gen`.
2. **Übersetzen:** C → Objekte in `work/recomp/obj4`. Die Zahl paralleler Clang-Prozesse wird aus verfügbaren CPUs und RAM bestimmt (2 GiB Systemreserve, etwa 1,5 GiB pro Compiler); `--recomp-jobs N` überschreibt sie. Funktionen ab `--recomp-o0-kb` werden mit `-O0` übersetzt. Marker `recomp-obj`.
3. **Modulbilder:** `mkimages.sh` mit `hle_nvn.txt` → `work/recomp/img_app`.
4. **Laufzeit:** `rt-bdsp/build.sh` mit `BDSP_APP=1` → `work/recomp/bdsp_app`.
5. **App:** Bundle, `Info.plist`, Symbol, Bibliotheken, ad hoc Signatur.
6. **Daten:** APFS-Klon von `work/romfs` nach Application Support.

### 7.2 Der NVN-Stempel (`prepare.sh`)

`scripts/recomp/rt-bdsp/nvn/prepare.sh` bereitet die Metal-Fassung der NVN-Schicht in `work/recomp/nvn-src` vor.

- Der Stempel ist ein SHA-256 über `scripts/recomp/rt-bdsp/nvn/src` (alle Dateien, sortiert),
  `shader_translator/translate.c`, `shader_translator/shader.h` und `prepare.sh` selbst. Der Hash steht in
  `work/recomp/nvn-src/.stamp`.
- Das Skript kopiert die Quellen nur, wenn der Stempel abweicht. Es verändert sie nicht.
- `prepare.sh --check` kopiert nichts und endet mit 0, wenn der Stempel passt, sonst mit 1.
- `prepare.sh --print` gibt den Quell-Hash aus. Die Stufe `recomp` nutzt ihn in ihrem eigenen Hash.
- Die normalen Bauten (`build_nvn.sh`, `build.sh`) rufen `prepare.sh` selbst auf. Sie überspringen es nur, wenn `NVN_KEEP=1` gesetzt ist.

### 7.3 Compiler-Flags (`flags.inc.sh`)

`scripts/recomp/rt-bdsp/nvn/flags.inc.sh` legt die gemeinsamen Flags der NVN-Bauten fest:
`BDSP_OPT="-O1 -g"`, `BDSP_NOWARN="-w"`, `BDSP_WARN_GLUE="-Wall -Wextra -Wno-unused-parameter"`.
Die Skripte `build_nvn.sh`, `vulkan/build_vk.sh` und `ios/build_rt32.sh` binden sie ein.
Plattformspezifische Defines stehen weiterhin im jeweiligen Skript.

## 8. Fehlersuche

| Symptom | Ursache und Lösung |
|---|---|
| `NVN-Stempel passt nicht` (von `prepare.sh --check`) | Die Kopie in `work/recomp/nvn-src` ist veraltet. Führe `scripts/recomp/rt-bdsp/nvn/prepare.sh` aus. Normale Bauten tun das automatisch. |
| Bau nutzt alten NVN-Code | `NVN_KEEP=1` ist gesetzt, daher wurde `prepare.sh` übersprungen. Entferne die Variable oder führe `prepare.sh` aus. |
| `Marker passt, übersprungen` | Eingaben haben sich nicht geändert. Mit `--force` neu bauen. |
| `work/exefs/main fehlt` (Exit 10) | Stufe `extract` zuerst ausführen. |
| Zu wenig Platz (Exit 8) | Platz freimachen oder mit `--min-free-gb N` die Anforderung senken. Der macOS-Bau braucht mehrere zehn GB. |
| Übersetzen schlägt fehl (Exit 4), Speicherfehler | `--recomp-jobs 2` verwenden. Log: `work/logs/recomp-compile.log`. |
| `Kein verbundenes, entsperrtes iPad gefunden.` | iPad verbinden, entsperren und dem Mac vertrauen. Prüfen mit `xcrun devicectl list devices`. |
| `xcodebuild` bricht ab (Signierung) | Log `work/builds/logs/ios-recomp-xcodebuild.log` lesen. `TEAM_ID` setzen und in Xcode mit deinem Konto signieren. |
| macOS-App wird beim ersten Start blockiert | Rechtsklick auf die App, dann Öffnen. |

## 9. Weitere Dokumentation

- `docs/architecture.md`: wie die Rekompilation arbeitet.
- `docs/development.md`: Arbeitsregeln, Befehle, Tests, was in `work/` liegt.
- `docs/recomp-macapp.md`: macOS-App, Datenpfade, Spielstand-Import, Messwerte.
- `docs/recomp-ios.md`: Schritte für die iPadOS-App, Speichermodell und Entitlements.
- `docs/recomp-linux.md`: Linux-Bau und Vulkan-Backend.
- `docs/rendering.md`: Metal-Renderer: Fehlersuche, Leistung, Bildrate, Wasser.
- `docs/shaders.md`: Shader-Übersetzer und Harness.
- `docs/saves.md`: Save-Format, Prüfskript, Ablageorte.

(Die Dokumente außer `README` und `BUILD` gibt es nur auf Englisch.)
