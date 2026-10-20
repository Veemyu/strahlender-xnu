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
- Ziele: die macOS-App (am weitesten), die iPadOS-App (ohne Ton), Linux mit Vulkan (in Arbeit, Abschnitt 6).

## 2. Gemeinsame Voraussetzungen

| Was | Wofür | Prüfen mit |
|---|---|---|
| Xcode (in `/Applications/Xcode.app`), Lizenz akzeptiert | macOS- und iPadOS-Bau | `xcodebuild -version` |
| Command Line Tools | Compiler, `codesign`, `otool`, `iconutil` | `xcode-select -p` |
| Python 3.9 oder neuer | `build_all.sh`, Hilfsskripte | `python3 --version` |
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

Einschränkungen: kein Ton, kein Netz. Beim ersten Start ggf. Rechtsklick → Öffnen (Gatekeeper, ad hoc
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

## 6. Linux mit Vulkan (in Arbeit)

Arbeitsstand. Noch nicht spielbar. Die bekannten Einschränkungen stehen in Abschnitt 6.4.

### 6.1 Voraussetzungen

Du führst die Befehle auf dem Mac aus. Ein Linux-Rechner (x86-64) baut und startet das Spiel im Ordner
`~/xnu-recomp`. Trage `RZ_HOST` in `work/local.env` (Abschnitt 3) als ssh-Alias dieses Rechners ein.

**Linux-Rechner**

- x86-64-Prozessor mit der Stufe `x86-64-v3` (AVX2), weil der Bau `-march=x86-64-v3` verwendet.
- Vulkan-Loader und Vulkan-Treiber. Getestete GPU: NVIDIA GeForce RTX 2080 Ti mit Vulkan 1.4.
- `clang`.
- Laufzeitbibliotheken (zum Ausführen nötig; die Build-Abhängigkeiten unten sind davon getrennt): `/usr/lib64/libvulkan.so.1`, `/usr/lib64/libSDL3.so.0`,
  `/usr/lib64/libshaderc_shared.so.1`.
- Für die Filmwiedergabe: `libavformat.so.62`, `libavcodec.so.62`, `libavutil.so.60`. Optional: ohne sie
  baue mit `BDSP_NO_MOVIE=1`.

**Mac**

- ssh mit Schlüssel-Authentifizierung (ohne Passwortabfrage), `rsync`, `curl`.
- Homebrew-Pakete `vulkan-headers`, `sdl3`, `shaderc` (nur Header).
- Optional: Homebrew-Paket `ffmpeg` für die FFmpeg-Header (siehe Schritt 2 in Abschnitt 6.2).

#### Build-Abhängigkeiten

Die Qt-Hülle (Menüleiste und Fenster) braucht diese Pakete auf dem Linux-Rechner. Installiere sie selbst.
Die Skripte installieren nichts.

| Element | Debian/Ubuntu (apt) | Fedora (dnf) | Arch Linux (pacman) |
|---|---|---|---|
| Qt-6-Entwicklungsdateien (Widgets) | `qt6-base-dev` | `qt6-qtbase-devel` | `qt6-base` |
| CMake | `cmake` | `cmake` | `cmake` |
| pkg-config | `pkg-config` | `pkgconf` | `pkgconf` |
| Vulkan-Header | `libvulkan-dev` | `vulkan-headers` | `vulkan-headers` |
| SDL3-Entwicklungsdateien | `libsdl3-dev` | `SDL3-devel` | `sdl3` |
| shaderc-Entwicklungsdateien | `libshaderc-dev` | `shaderc-devel` | `shaderc` |

Installationsbefehl je Distribution:

```sh
# Debian/Ubuntu
sudo apt install qt6-base-dev cmake pkg-config libvulkan-dev libsdl3-dev libshaderc-dev
```

```sh
# Fedora
sudo dnf install qt6-qtbase-devel cmake pkgconf vulkan-headers SDL3-devel shaderc-devel
```

```sh
# Arch Linux
sudo pacman -S qt6-base cmake pkgconf vulkan-headers sdl3 shaderc
```

Prüfstatus: Die Arch-Namen (`qt6-base`, `sdl3`, `shaderc`, `vulkan-headers`, `cmake`) sind im offiziellen
Repository `extra` bestätigt. Die Debian-Namen (`qt6-base-dev`, `libsdl3-dev`, `libshaderc-dev`, `libvulkan-dev`)
sind auf packages.debian.org (stable) bestätigt. Der Fedora-Name `qt6-qtbase-devel` ist im Fedora-Paketindex
bestätigt; `SDL3-devel`, `shaderc-devel` und `vulkan-headers` sind die Namen, die auf dem Fedora-Build-Host
verwendet werden (`docs/recomp-ryzen.md`, Abschnitt 11). Ubuntu verwendet die Debian-Namen; ob `libsdl3-dev`
existiert, hängt von der Version ab (nicht für jede Ubuntu-Version verifiziert).
PySide6 steht nicht in der Tabelle. Ob die oben genannten Qt-6-Pakete für PySide6 ausreichen, ist nicht
verifiziert.

Die Qt-Hülle läuft als X11-Client (`QT_QPA_PLATFORM=xcb`). Unter Wayland läuft sie über Xwayland. Das
Spielfenster wird über X11 eingebettet: die Hülle startet das Spiel mit `SDL_VIDEODRIVER=x11`.

### 6.2 Bauen und starten

Führe diese Schritte auf dem Mac in dieser Reihenfolge aus:

1. Header einmalig auf den Linux-Rechner kopieren: `scripts/recomp/ryzen/vk_sync_deps.sh`
   - Beim ersten Lauf lädt das Skript `vk_mem_alloc.h` von GitHub, sofern die Datei nicht bereits in
     `work/recomp/deps-vk/` liegt.
2. Quellen und eigene Daten (RomFS, `main.npdm`) kopieren: `scripts/recomp/ryzen/vk_sync.sh --daten`
   - Fehlt `work/recomp/img_gfx`, nennt das Skript den Befehl zum Erzeugen (`mkimages.sh`).
   - Optional, für die Filmwiedergabe: `scripts/recomp/ryzen/sync_deps.sh` kopiert die FFmpeg-Header und die
     SDL3-Header aus Homebrew nach `~/xnu-recomp/deps/include`. Setze `FFMPEG_PREFIX`, wenn ffmpeg nicht unter
     `/opt/homebrew/opt/ffmpeg` liegt.
3. Die vier Module auf dem Linux-Rechner nach `~/xnu-recomp/work/recomp/obj4-c` übersetzen:
   `scripts/recomp/ryzen/build.sh` (Voraussetzungen auf dem Rechner: `docs/recomp-ryzen.md`).
4. Vulkan-Laufzeit bauen: `scripts/recomp/ryzen/vk_build.sh` (Ergebnis: `work/recomp/bdsp_boot_vk` auf dem Linux-Rechner).
5. Ohne Fenster starten (Standard): `scripts/recomp/ryzen/vk_run.sh --tag=t1 --headless --timeout 40 --screenshot-after 300`
6. Screenshots und Logs nach `work/recomp/ryzen/` auf dem Mac holen: `scripts/recomp/ryzen/vk_fetch.sh`

`--headless` braucht kein Display. Es rendert in Bilder außerhalb des Bildschirms. Die Screenshots landen
auf dem Linux-Rechner in `work/recomp/shots/frame_NNNNN.png`; Schritt 6 holt sie.

### 6.3 Mit Fenster starten (Wayland)

Das Fenster öffnet sich auf dem Desktop des Linux-Rechners. Übergib die Sitzungsvariablen des
Desktop-Benutzers beim Aufruf. Die Benutzer-ID ermittelst du mit `id -u` auf dem Linux-Rechner. Ohne diese
Variablen kann kein Fenster öffnen.

```sh
scripts/recomp/ryzen/vk_run.sh --tag=win XDG_RUNTIME_DIR=/run/user/<UID> WAYLAND_DISPLAY=wayland-0 \
  SDL_VIDEODRIVER=wayland BDSP_NO_USER_INPUT=1 --window 1280x720 --timeout 22
```

`BDSP_NO_USER_INPUT=1` verhindert, dass das Fenster beim Öffnen den Tastaturfokus übernimmt. Ob es auch die
unten genannten Tasten blockiert, ist nicht geprüft. Für das interaktive Spielen lässt du es weg.

Einstellungen nur für Fensterläufe (ohne Wirkung mit `--headless`):

- Startgröße: `--window 1280x720` oder `BDSP_WINDOW=1920x1080` (Standard 1280×720).
- Bildrate: `BDSP_FPS=30`, `BDSP_FPS=60` oder `BDSP_FPS=120`. Übergib sie nach dem Skriptnamen, zum Beispiel
  `scripts/recomp/ryzen/vk_run.sh BDSP_FPS=60 --tag=win ...`.
- MangoHud-Anzeige (fps, Frame-Zeit, CPU- und GPU-Werte): `BDSP_MANGOHUD=1`. Benötigt das Paket `mangohud` auf
  dem Linux-Rechner. Es wird nur zur Laufzeit gebraucht, nicht zum Bauen. Standard: aus.
- Laufzeit: `--timeout N` in Sekunden (Standard 120).

Tasten im Fenster:

- F1 bis F4: Fenstergröße 960×540, 1280×720, 1920×1080, 2560×1440 (nicht im Vollbild).
- F5, F6, F7: Bildrate 30, 60, 120.
- F11: Vollbild ein- und ausschalten. Nicht geprüft.

X11 ist nicht geprüft.

### 6.3a Menüleiste (in Arbeit, Qt-Hülle)

Eine Menüleiste mit Datei, Bearbeiten, Ansicht, Fenster und Hilfe ist in Arbeit, als Teil einer Qt-Hülle.
Sie ist noch nicht geliefert, und die Qt-Hülle liegt nicht im Repository. Bis dahin nutzt du die Tasten aus
Abschnitt 6.3.

### 6.4 Bekannte Einschränkungen

- **Spielfigur fehlt, Vertex-Explosionen, Fenster-Füllung:** im letzten Testlauf behoben (Feldszene mit
  Spielfigur, NPCs und Wasser; Fenster vollständig gefüllt). Noch nicht über mehrere Sitzungen geprüft.
- **Textur außerhalb des Gastfensters:** die Laufzeit meldet `[vk] Textur außerhalb des Gastfensters` und
  überspringt den Upload (Schutz in `textures.c`). Wirkung auf das Bild nicht geprüft. Offen.
- **Seltene Hänger am Ladebildschirm:** offen. Ursache nicht bekannt.
- **FFmpeg-Header-Version:** noch nicht auf die Laufzeitbibliotheken abgestimmt. Schlägt die
  Filmwiedergabe fehl, baue mit `BDSP_NO_MOVIE=1`.
- **Bildrate:** `BDSP_FPS` begrenzt die Bildrate (30, 60, 120). Nur im Fenster gemessen; nicht über mehrere Sitzungen geprüft.
- Kein Ton. Der Eingabezustand wird nicht gemeldet. Compute-Arbeitslasten werden nicht unterstützt.
- Windows wird nicht unterstützt. X11 und Vollbild (F11) sind nicht geprüft.

Details: `docs/recomp-vulkan.md`.

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
