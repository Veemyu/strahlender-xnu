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
RZ_HOST=<RZ_HOST>
```

- `TEAM_ID`: deine Apple-Developer-Team-ID. Nur für den iPadOS-Bau (`deploy_ios.sh`). Sie wird per
  Kommandozeile an `xcodebuild` übergeben und nicht ins Projekt geschrieben.
- `RZ_HOST`: der ssh-Alias deines Linux-Build-Rechners. Nur für die Linux-/Vulkan-Skripte (Abschnitt 6).
  Verwende einen Alias aus `~/.ssh/config`, keine IP-Adresse.

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

Der erste Bau dauert unter Last rund 28 Minuten (gemessen, siehe `docs/recomp-macapp.md`). Spätere Bauten
nutzen die Marker wieder und sind deutlich schneller (Abschnitt 7).

Nützliche Optionen:

| Option | Bedeutung |
|---|---|
| `--recomp-jobs N` | Anzahl der Compiler-Jobs, 1 bis 4 (Standard 4) |
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

Das Protokoll jedes `run` landet in `work/builds/ipad-recomp-<Zeit>.log`. Das Bau-Protokoll steht in
`work/builds/ios-recomp-xcodebuild.log`.

### 5.3 Signierung

Die Signierung machst du selbst. Wähle bei einem fehlgeschlagenen Bau Team und Provisioning in Xcode.
Das Skript übergibt `TEAM_ID` und `-allowProvisioningUpdates` an `xcodebuild`. Ändere
`project.pbxproj` im Repository nicht, um das Team einzustellen.

## 6. Linux mit Vulkan und Qt6

Die vollständige, gepflegte Paketliste und alle Befehle stehen in
[BUILD.md](BUILD.md), Abschnitt 6. Die Host-Skripte liegen jetzt unter
`scripts/recomp/linux/`; lokale Ergebnisse unter `work/recomp/linux/`.
SSH-Alias und Arbeitsordner werden weiterhin lokal über RZ_HOST/RZ_DIR festgelegt.

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

Nach der Quellübertragung prüft `scripts/recomp/linux/check_deps.sh --qt`
die Voraussetzungen. `scripts/recomp/linux/vk_build.sh --qt` baut die Qt-Hülle
im Prozess der Laufzeit; `scripts/recomp/linux/vk_qt.sh` startet sie. Diese Variante
unterstützt natives Wayland und X11. Die getrennte X11-Hülle bleibt mit
BDSP_QT_PROCESS=1 verfügbar. Konkrete Sitzungs-, Benutzer- und Hostdaten bleiben lokal.

Die frühere Variante mit kopierten Headern wurde gebaut und kurz gestartet.
Ein neuer vollständiger Paket-Build muss nach Installation der noch fehlenden
Devel-Pakete geprüft werden. Linux-Ton und längere Spiel-/Darstellungstests bleiben offen.
Historische Messungen: [recomp-linux.de.md](recomp-linux.de.md).

## 7. Überblick über die Bau-Stufen

Reihenfolge der Stufen: `tools extract il2cpp recomp masterdata shaders video audio`. Mit `--only` oder
`--from`/`--to` läufst du einen Teil. Prüfe vorher mit `--dry-run`. Jede Stufe schreibt einen Marker
`work/.stages/<Stufe>.json` mit einem Eingabe-Hash. Passt der Hash, wird die Stufe übersprungen
(`--force` baut sie neu).

| Stufe | Zweck | Für die Apps nötig |
|---|---|---|
| `tools` | prüft Werkzeuge, baut `hactool` nach `tools/hactool` | ja (für `extract`) |
| `extract` | entschlüsselt `.xci`/`.nsp` nach `work/exefs`, `work/romfs`, `work/manifest.json` | ja |
| `il2cpp`, `masterdata`, `shaders`, `video`, `audio` | Unity-bezogene Stufen | nein: `recomp_build.sh` liest nur `work/exefs` und `work/romfs` |
| `recomp` | macOS-App aus der Rekompilation | nur für die macOS-App |

### 7.1 Die Stufe `recomp`

`scripts/recomp/app/recomp_build.sh` führt sechs Schritte aus:

1. **Generator:** Module aus `work/exefs` → C in `work/recomp/gen4` (rund 1 GB). Marker `recomp-gen`.
2. **Übersetzen:** C → Objekte in `work/recomp/obj4`, höchstens 4 Jobs. Funktionen ab `--recomp-o0-kb` werden mit `-O0` übersetzt. Marker `recomp-obj`.
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
| `RZ_HOST fehlt` | `RZ_HOST=<RZ_HOST>` in `work/local.env` eintragen oder exportieren. |
| `… ssh-Alias … nicht erreichbar` | Mit `ssh <RZ_HOST> true` prüfen. Der Rechner muss laufen, Schlüssel-Authentifizierung muss funktionieren. |
| `Kein verbundenes, entsperrtes iPad gefunden.` | iPad verbinden, entsperren und dem Mac vertrauen. Prüfen mit `xcrun devicectl list devices`. |
| `xcodebuild` bricht ab (Signierung) | Log `work/builds/ios-recomp-xcodebuild.log` lesen. `TEAM_ID` setzen und in Xcode mit deinem Konto signieren. |
| macOS-App wird beim ersten Start blockiert | Rechtsklick auf die App, dann Öffnen. |

## 9. Weitere Dokumentation

- `docs/recomp-macapp.md`: macOS-App, Datenpfade, Spielstand-Import, Messwerte.
- `docs/recomp-ios.md`: Schritte für die iPadOS-App.
- `docs/recomp-vulkan.md`: Vulkan-Pfad und Stand.
- `docs/build-pipeline.md`: Stufen, Marker, Preflight.
