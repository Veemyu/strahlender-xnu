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
  (Pillow, LZ4, native Unicorn-Dateien). Danach ziehst du deine `.xci`, optional das Update `.nsp` und deine `prod.keys` in das Fenster,
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
| Unicorn-2.1.4-C-Header/Bibliothek in `tools/pydeps` oder `BDSP_UNICORN_ROOT` | Generator (Stufe `recomp`) | `ls tools/pydeps` |
| `git`, `make`, `cc` | Stufe `tools` (baut `hactool`) | `command -v git make cc` |

Homebrew- und Python-Pakete installieren:

```sh
brew install llvm sdl3 ffmpeg pkg-config
python3 -m pip install --target tools/pydeps unicorn==2.1.4
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

Installiere zusätzlich das Paket `time` (liefert `/usr/bin/time`) und die Asset-Abhängigkeit `lz4` und `unicorn==2.1.4` (liefert C-Header und native Bibliothek).
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

Am 23.10.2026 wurde ein frischer Fedora-Linux-x86_64-Checkout mit Basis-XCI und
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

## Windows-Vorbereitung (noch kein spielbares Release)

Mindestziel ist **Windows 10 22H2 amd64 (Build 19045)** sowie Windows 11.
ARM64 bekommt ein getrenntes Host-/Target-/ABI-Profil, aber keine Supportzusage.
Schon der erste spielbare Windows-Build muss im vorhandenen grafischen
Rust/iced-Installer bedienbar sein; die Entwickler-CLI ersetzt das nicht.

`installer/assets/windows-dependencies.json` ist der gemeinsame Requirements-Vertrag:
LLVM-MinGW **UCRT**, portable SIMD-C-Ausgabe, amd64-Baseline/CX16, ARM64-Baseline,
OS-Untergrenze und Releaseblocker. Die vorhandenen Locks für privates CPython
3.13.15 und Unicorn 2.1.4 werden referenziert; System-Python ist keine geplante
Nutzerpflicht. Die Windows-Prüfung liest kein `/etc/os-release`, bietet keine
Unix-Paketmanager an und startet keinen Linux-Build als Ersatz. Für ungeprüfte
Pakete zeigt die GUI die ausstehende Freigabe statt eines Download-/Installbuttons.

| Requirement | Noch erforderliche Qualifizierung |
|---|---|
| Portables LLVM-MinGW UCRT: Clang, LLD, PE-Werkzeuge, Header/Importlibs, compiler-rt, winpthreads | Archiv/Hash von 20261020 festgehalten und privat ausgeführt; komplette Host-DLL-Inventare, Notices und Windows-10-Ausführung noch erforderlich |
| Privates CPython und native Unicorn-2.1.4-Header/Library | Vorhandene amd64-Locks auf Windows 10 ausführen; natives ARM64-Unicorn ist nicht gelockt |
| Microsoft-VC-Runtime für das gelockte Unicorn-amd64-Wheel | App-lokales `vcruntime140.dll` für die Build-DLL erforderlich; autorisierte, versionierte Weiterverteilung qualifizieren, nicht aus System32 kopieren |
| SDL3 mit Nintendo-/Sony-HIDAPI und Xbox-Backends | ABI-passende UCRT-Header/Importlibs/DLL-Closure sowie echte USB-/Bluetooth-Abnahme |
| Vulkan-Headers, VMA und shaderc | Getrennte Pins/Quellennachweise, Toolchain-kompatible Libraries und GPU-Featureprüfung |
| FFmpeg avcodec/avformat/avutil | Configure-Flags, Codecs, passende Quellen/Lizenzpflichten und rekursive DLL-Inventare |
| Natives hactool und Asset-Helfer | Version/Hash, native Windows-Extraktion und Dependency-/Lizenzinventare |
| Grafisches Installerrelease | Releasehersteller brauchen Rust/Cargo >= 1.88; private Runtime mitliefern, Nutzer brauchen kein Rust/SDK |

Es gibt **keine in der GUI freigeschalteten Windows-Dependencydownloads**:
LLVM-MinGW-Archiv und -Hash sind festgehalten; Distributionsinventar und weitere
native Developmentpakete sind noch nicht qualifiziert. Für Entwicklerproben wurden
LLVM-MinGW und Unicorn nach Zustimmung privat und hashgeprüft vorbereitet. Später müssen Downloads
nach Zustimmung hashgeprüft in benutzereigene Verzeichnisse gelangen; derselbe
geprüfte Offlinecache bleibt möglich. Keine globale PATH-Änderung oder Adminpflicht.
Git, gh, Bash/MSYS2, Visual Studio, CMake, Make und Ninja sind keine geplanten
Buildvoraussetzungen für Endnutzer.

Die direkte Entwicklerkette `scripts/recomp/portable_build.py` bietet jetzt
Generatoraufrufe, optionale `subsdk1`-Entries, portables Vulkan-Source-Overlay,
zweipassige Images mit expliziter NVN-HLE-Bindung, RAM-begrenztes Kompilieren,
Hot-O2/O0-Ausreißerwahl und Link-/Pakethelfer mit expliziten Objektinventaren.
Windows-Compilerprozesse werden suspendiert erzeugt und vor ihrem Start einem
eigenen Job Object zugewiesen; Abbruch beendet auch Kindprozesse. Responsefiles
behandeln Unicode, Leerzeichen und Quoting. Caches trennen Host, Target, CRT/SIMD,
Compilerbytes/-triple, Header und Flags. Normale und Delay-PE-Imports werden nur
aus ausdrücklich inventarisierten DLLs aufgelöst; System-DLLs und der Vulkanloader
des GPU-Anbieters werden nicht kopiert. Der Pakethelfer schließt Buildwerkzeuge,
Python und Unicorn aus und fordert Notices, ersetzt aber weder Lizenzaudit noch
vollständige Spieldateninstallation.

Nur lesende Entwicklerprüfung in PowerShell im Checkout:

```powershell
python -B scripts\recomp\portable_build.py inspect --target x86_64
python -B scripts\install\driver.py preflight --root . --work work --tools-dir tools --target windows
```

Der zweite Aufruf meldet absichtlich die aktuellen Releaseblocker und schlägt fehl.
Mit ausdrücklich gewähltem LLVM-MinGW-UCRT-Compiler und privatem Unicorn können
Entwickler `generator`, `generate`, `images` und `compile` mit expliziten
`--host-cc`-/`--cc`-Pfaden und `--unicorn-root` aufrufen. Das ist noch kein
End-to-End-Spielbuild und darf nicht als solcher beworben werden.

Auf diesem Windows-Host mit privat vorbereitetem LLVM-MinGW UCRT 20261020 und
Unicorn 2.1.4 geprüft: native deterministische Generierung/Image-Relokationen,
amd64-Compile des erzeugten C-Codes, verschobener Generator samt DLL-Closure ohne
Entwickler-PATH, gepaartes Windows-setjmp/longjmp, Job-Object-Abbruch einschließlich
Kindprozessen sowie der SDL-Lebenszyklus mit künstlichen Geräten (zusätzlich mit
vorhandenem MSVC geprüft). Generiertes C und die Win32-Host-/Image-Loader-/
Entrypoint-Quellen werden getrennt nach ARM64 crosskompiliert; kein ARM64-Programm
wurde ausgeführt.

Der aktive Entrypoint reserviert jetzt ein Win32-Gastfenster. Datenpages werden
bei Zugriff committed. Explizites Commit, Schreib-/Zugriffsschutz, Decommit mit
Nullen bei Wiederverwendung, monotone Zeit, Speicherberichte und Unicode-/binäres
Image-Laden sind isoliert nativ geprüft. Guard-, schreibgeschützte und nicht
ausführbare Pages lösen weiterhin Faults aus. Datei-I/O-Zielpuffer werden
ausdrücklich committed statt auf Usermode-Faults zu vertrauen. Das ist noch kein
vollständiger Runtime-/GC-Port.

Der aktive Win32-Kernel verwendet monotone Zeit, Stack-/Working-Set-Abfragen und
kryptografischen Systemzufall. Seine native Probe emittiert eine synthetische
ARM64-Funktion mit dem echten C-Generator und führt vier Worker durch 32
Stop-the-world-Zyklen (128 Suspends/Resumes pro Build), jeweils mit `-O1`, `-O2`
und `-O3`. Geprüft werden alle exportierten GPRs, 32 aus Gaststacks geladene
SIMD-Registerpaare, Stackroots, wechselnde nur im Registersatz abgelegte
Rootkandidaten, wiederholt identische eingefrorene Kontexte, idempotentes
Pause/Resume und Threadende. Ein reproduzierter Exportfehler ist behoben:
NZCV, FPCR und FPSR stammen jetzt aus `Cpu`, statt null zu bleiben.
Das prüft die SVC-/Kontext-/Rootablagegrenze, keinen sammelnden Gast-GC.
Die `Cpu`-Felder sind gewöhnlicher C-Speicher; beliebige optimierte
Hosttemporäre werden nicht aus Windows-`CONTEXT` oder Hoststacks rekonstruiert.
Der gemeldete Gast-PC bleibt der gespeicherte Gast-LR, keine rückübersetzte
Hostinstruktionsadresse. Kein Whole-game-GC-/Rootvollständigkeits- oder
ARM64-Ausführungsnachweis.
Eine zusätzliche Compilerprüfung einer emittierten reinen EOR-/SUB-/CBNZ-Schleife
belegt diese Grenze: Clang 23.1.4 hält x19 mit `-O1` in einem Host-GPR und schreibt
erst nach der Schleife zurück; mit `-O2` kommen Host-SIMD-Temporäre hinzu.
Die erfolgreiche LDAR-basierte Probe belegt deshalb keine konsistenten
Gastregisterkontexte innerhalb beliebiger optimierter Rechenschleifen. Das ist
ein konkreter Nachweis verzögerten Zurückschreibens, kein Nachweis eines
fälschlich freigegebenen lebenden Objekts.

Die native Probe `test_optimized_sole_root_is_missing_from_guest_context`
reproduziert inzwischen auch eine Live-Root-Auslassung bei echtem Windows-Suspend
mit `-O1`/`-O2`, nicht nur anhand von Assembly. Die emittierte Gastfunktion lädt
einen kodierten Zeiger auf ein committed 16-Byte-Gastobjekt, löscht die Quelle,
dekodiert/kodiert ihn in einer endlichen Rechenschleife und verwendet ihn nach
Resume erneut. Drei Worker je Optimierung müssen je acht Hostkontext-Roots
liefern, während weder `Cpu`, exportierter SVC-Kontext noch Gaststack einen
Zeiger in dieses Objekt enthalten. Die Stichproben sind auf 256 Versuche je
Worker mit 1/2/3-ms-Pausen begrenzt. Kontext-/Stack-Positivkontrollen schließen
Innenzeiger ein. Das charakterisiert ausführbar die noch unbehobene
Rootexportlücke; es ist kein Collector-/Freigabetest, da der Gast-Boehm-Scanner
im quellbasierten synthetischen Fixture nicht vorliegt. Hoststackroots werden
ebenfalls nicht exportiert; diese Probe belegt den Hostkontextfall.

Ein korrekter Produktionsfix darf Gastregister nicht einfach mit fremden
Hostregisterwerten überschreiben. Zusätzliche konservative Hostrootbereiche
benötigen den tatsächlichen Scan-/Markierungsvertrag des Gast-Collectors;
kooperatives Anhalten oder Compiler-Rootmaps jeweils eigene Verträge und
Abdeckung. Nichts davon ist durch diese Probe implementiert oder qualifiziert.
Die direkte Integrationsprüfung im Checkout fand keinen registrierten
GC-Push-/Mark-Callback. `hle_register`, erzwungene Importslots und Generator-
`--hle` sind allgemeine Dispatch-/Ersetzungsmechanismen, kein Collector-Vertrag.
Upstreams `rt_unwind_point` verwirft Frames per longjmp beim Neustart; es kann
einen sammelnden Thread nicht parken und fortsetzen. Eine Collector-Brücke
benötigt einen identifizierten versionsgebundenen Gast-Hook samt Signatur,
bestätigte Scanbereichs-/Stop-/Markierungs-Lebensdauerregeln und nachgewiesene
Erreichbarkeit. Das liegt im erlaubten quellbasierten Fixture nicht vor;
alternativ muss ein neuer fortsetzbarer kooperativer Stopvertrag ausdrücklich
gewählt statt aus dem Neustartmechanismus abgeleitet werden.

Die vollständige **Diagnoseruntime ohne Grafik** kompiliert und linkt jetzt
direkt mit LLVM-MinGW auf amd64; für ARM64 wird sie crossgelinkt. Eine künstliche
Gastfunktionstabelle startet den aktiven Loader/Dispatcher/Kernel aus einem
verschobenen Unicode-Paket ohne Entwickler-PATH. Eine echte unbehandelte
Windows-Exception und ihr ursprünglicher Exitstatus werden geprüft. Das ist
weder ein Vulkan-Spiel-Link noch ein Spielstart. Der ausschließlich für iOS
vorgesehene Snapshot-Publisher wird nicht in diese Windowsdiagnose kompiliert.

Der Windows-`wmain` konvertiert Argumente und geerbte `BDSP_*`-Einstellungen strikt
nach UTF-8. Lesende Standardpfade (`img/`, `romfs/`, `exefs/main.npdm`) liegen neben
der EXE, unabhängig vom Startverzeichnis. Saves liegen standardmäßig unter
`%APPDATA%\StrahlenderXnu\save` (Windows-Known-Folder RoamingAppData).
Cache, Screenshots, Logs und Mods bleiben unter `%LOCALAPPDATA%\StrahlenderXnu`.
Explizites `BDSP_DATA_DIR` hält alle schreibbaren Standards einschließlich
Saves unter diesem Stamm für portable/isolierte Läufe; `BDSP_SAVE` hat Vorrang.
Vorhandene LocalAppData-Saves werden nicht automatisch gelesen, verschoben oder
zusammengeführt. Zum Fortsetzen `BDSP_SAVE` auf den alten Ordner setzen oder
erst bei geschlossenem Spiel manuell migrieren.
Runtime-Abbruchmeldungen und Code/PC/SP unbehandelter Host-Exceptions werden über
ein vorab geöffnetes natives Handle an `logs/crash.log` angehängt; vollständige
symbolisierte Crashberichte fehlen noch. Dateisystem-/Modlogik bleiben gemeinsam:
Nur die Windows-Dateigrenze konvertiert UTF-8 nach UTF-16 und ergänzt binäres
positioniertes 64-Bit-I/O. Native Proben prüfen Offsets über 4 GiB, unveränderte
Dateipositionen, frische Gastpages als Leseziel und atomaren Backupersatz.
Vulkan-Pipeline-/SPIR-V-Caches nutzen den gemeinsamen `BDSP_CACHE_DIR`-Helfer;
der vollständige Grafikbuild braucht weiterhin qualifizierte Dependencies.

Linux und Windows teilen den SDL3-PCM16-Ausgabepfad und den bestehenden
serialisierten Ausgabelebenszyklus; macOS behält AudioQueue. Die Eingangsqueue
ist auf 200 ms begrenzt. Künstliche Geräte prüfen Stop, App-Pause/Fortsetzen,
begrenzte Writes, fehlgeschlagenes Öffnen/Enqueue und ausgeglichene
Subsystem-Lebensdauer, nicht hörbare Wiedergabe. Die gezielt genehmigten Archive
für SDL 3.4.18 und das ausschließlich für Maintainer gedachte CMake 4.1.2 wurden
privat heruntergeladen und hashgeprüft. Das Offline-Rezept `sdl` baut getrennte
amd64-/ARM64-UCRT-Entwicklungspakete: Header, Importlibrary, DLL-Closure-Prüfung,
gesammelte Notices, generierte Konfiguration und SHA256-Inventare. C-/C++-/RC-Compiler
sind ausdrücklich targetgebunden; typisierte CMake-Pfade verhindern Escape-Fehler
mit Windows-Backslashes. Endnutzer brauchen weiterhin weder CMake noch Ninja.
Die Pakete sind nicht für öffentliche Installation qualifiziert; weitere Downloads
brauchen weiterhin Zustimmung.

Maintainer können das Rezept mit diesen bereits genehmigten privaten Archiven
und einem vorhandenen Ninja nachvollziehen. Es lädt nichts herunter und ersetzt
keine bestehenden Ausgabeverzeichnisse:

```powershell
$tools = Join-Path (Get-Location) 'work\windows-tools'
$llvm = Join-Path $tools 'llvm\llvm-mingw-20261020-ucrt-x86_64'
python scripts\recomp\portable_build.py sdl --host x86_64 --target x86_64 `
  --cc "$llvm\bin\x86_64-w64-mingw32-clang.exe" `
  --cmake "$tools\cmake\cmake-4.1.2-windows-x86_64\bin\cmake.exe" `
  --ninja (Get-Command ninja -ErrorAction Stop).Source `
  --sdl-archive "$tools\archives\SDL3-3.4.18.tar.gz" `
  --sdl-prefix "$tools\SDL3-3.4.18-x86_64"
```

Für das getrennte ARM64-Paket bleibt `--host x86_64`; wähle `--target aarch64`,
den Compiler `aarch64-w64-mingw32-clang.exe` und ein neues ARM64-Ausgabeverzeichnis.
Das ist ein Crossbuild, keine native ARM64-Ausführung. Mit der echten amd64-SDL-DLL
laufen jetzt der produktive UTF-8-Entrypoint, virtuelle Controller einschließlich
Hotplug/Tasten/Sticks/Fokus, Paar-/Einzelinitialisierung und Worker-Dummy-Audio ohne
Entwickler-PATH. Das prüft weder physische Controller noch hörbare Ausgabe oder Vulkan.
`BDSP_WINDOWS_SDL_ROOT` und optional `BDSP_WINDOWS_SDL_ARM64_ROOT` aktivieren diese
gezielten Tests zusätzlich zu den bestehenden nativen Compiler-Testvariablen.

Die acht privat genehmigten Quellarchive sind mit Revision, gemessenem SHA256 und
Größe in `installer/assets/windows-sources.json` festgehalten. Das Offline-Rezept
für Vulkan baut Vulkan-Headers/VMA/shaderc mit vorhandenem Maintainer-CMake/Ninja
und ausdrücklichen Target-C-/C++-Compilern. Die VCS-Versionsabfragen von shaderc
und SPIRV-Tools werden nur in temporären Quellen durch gelockte Revisionen ersetzt;
Patchhashes werden protokolliert. Dabei werden weder Git noch Downloads gestartet.

FFmpeg wird **nicht aus Quellen gebaut**. Nach eigener Zustimmung zum Binärdownload
wurde das BtbN-amd64-LGPL-Shared-Archiv `n8.1.3-24-g92611900bb` hashgeprüft.
Anders als eine reine CLI-Installation über winget enthält dieses tatsächliche
Archiv passende Header, GNU-/MSVC-Importlibraries und DLLs. Der Offline-Import
übernimmt Developmentdateien und Dokumentation, aber nur die gemessene Runtimeclosure:
`avcodec-62.dll`, `avformat-62.dll`, `avutil-60.dll` und `swresample-6.dll`.
`ffmpeg.exe` wird weder zum Spielbuild noch zum Spielen benötigt. Das genaue Archiv
im Offlinecache behalten: tägliche Producer-Releases sind nur begrenzt verfügbar;
das Rezept weicht niemals auf `latest` aus.

Maintainer-Vorbereitung nur mit vorhandenen genehmigten Archiven und Werkzeugen:

```powershell
python scripts\recomp\dependency_build.py vulkan `
  --archives "$tools\archives" --prefix "$tools\vulkan-x86_64" `
  --cc "$llvm\bin\x86_64-w64-mingw32-clang.exe" `
  --cmake "$tools\cmake\cmake-4.1.2-windows-x86_64\bin\cmake.exe" `
  --ninja (Get-Command ninja -ErrorAction Stop).Source --jobs 4
python scripts\recomp\dependency_build.py ffmpeg --target x86_64 `
  --archive "$tools\archives\ffmpeg-n8.1.3-24-g92611900bb-win64-lgpl-shared-8.1.zip" `
  --prefix "$tools\ffmpeg-x86_64"
python scripts\recomp\portable_build.py runtime --backend vulkan --frontend sdl `
  --cc "$llvm\bin\x86_64-w64-mingw32-clang.exe" `
  --sdl-prefix "$tools\SDL3-3.4.18-x86_64" `
  --vulkan-prefix "$tools\vulkan-x86_64" --ffmpeg-prefix "$tools\ffmpeg-x86_64"
```

Die gemeinsame Compile-/Cachequeue wählt jetzt je Quelle C17 oder Target-C++17,
berücksichtigt beide Compileridentitäten und quellbezogene Flags und bevorzugt
Overlayheader. Die gesamte aktive amd64-Vulkan-/VMA-/SDL-/Movieruntime kompiliert
und linkt mit künstlichen Gasttabellen. Sie startet aus einem verschobenen
Unicode-Paket ohne Entwickler-PATH und meldet Hostcrashes. Das ist **keine Spiel-
oder GPU-Abnahme**. Echtes shaderc erzeugt SPIR-V und Fehlerdiagnosen für ungültiges
GLSL. FFmpeg-Header und geladene C-ABI stimmen überein; VP8 wird encodiert, über
einen Unicode-WebM-Pfad gemuxt/demuxt und decodiert. VP8-/VP9-/H264-Decoder sind vorhanden.

`BDSP_WINDOWS_VULKAN_ROOT` und `BDSP_WINDOWS_FFMPEG_ROOT` aktivieren diese Proben
zusätzlich zu den bisherigen nativen/SDL-Variablen. Optional schreibt
`BDSP_WINDOWS_DEPENDENCY_REPORT` die genauen Configure-Flags, gemeldete Lizenz,
Compiler-, Paket-/Probehashes und Runtimeclosure als JSON.
Aufruf: `python -m unittest scripts.tests.test_dependency_build scripts.tests.test_windows_native_generator scripts.tests.test_windows_build scripts.tests.test_recomp_parallel_jobs`.
FFmpeg meldet **LGPL Version 3 oder neuer**; GPL/nonfree sind nicht aktiviert.
Das ist keine Weiterverteilungsfreigabe: passende FFmpeg-/Drittquellen,
Identität des Producer-Rezepts, Notices, CPU-Baseline und Windows-10-Ausführung
müssen noch qualifiziert werden. Die zuvor genehmigte FFmpeg-8.0.1-Quelle passt
nicht zu dieser 8.1-Binärdatei. ARM64-FFmpeg ist nicht gelockt; Make-Download,
FFmpeg-Quellbuild und globale winget-/PATH-Änderungen sind nicht erforderlich.

**Privater lokaler Installerpfad (experimentell, keine Releaseabnahme).** Der
GUI-Backendpfad verbindet ausgewählte XCI-/NSP-/NCA-Eingaben jetzt mit shellfreier
Extraktion, C-Generierung, vollständigem Vulkan-/Movie-Link, Daten-/DLL-Paket und
Benutzerinstallation. hactool wird aus der bereits genehmigten Quelle samt
gebündelter mbedTLS-Kryptobibliothek direkt ohne Make gebaut:

```powershell
python scripts\recomp\dependency_build.py hactool --target x86_64 `
  --archives "$tools\archives" --prefix "$tools\hactool-x86_64" `
  --cc "$llvm\bin\x86_64-w64-mingw32-clang.exe"
python -m scripts.install.windows_pipeline `
  --output "$tools\private-catalog.json" `
  --cc "$llvm\bin\x86_64-w64-mingw32-clang.exe" `
  --generator "work\native-generator\windows-x86_64\bdsp_codegen.exe" `
  --sdl "$tools\SDL3-3.4.18-x86_64" --vulkan "$tools\vulkan-x86_64" `
  --ffmpeg "$tools\ffmpeg-x86_64" --hactool "$tools\hactool-x86_64"
$env:BDSP_INSTALLER_DEV_CHECKOUT = "1"
$env:BDSP_WINDOWS_PRIVATE_CATALOG = (Resolve-Path "$tools\private-catalog.json").Path
```

Die beiden expliziten Variablen gelten **nur für den Debuginstaller im bestehenden
Checkout**. Releasebuilds behalten die Freigabesperre. Die Registrierung lädt nichts
herunter und ersetzt keinen bestehenden Katalog. Sie inventarisiert die gesamte
private Toolchain und Generator-DLL-Closure sowie geprüfte Targetpakete. Fehlende
oder veränderte Dateien führen zum Abbruch, nicht zu Systemtool-Fallbacks.
Der produktive Installer benötigt weiterhin qualifiziertes privates Python und
Werkzeuge; der Debugbuild darf vorhandenes Entwickler-Python verwenden.

Containerkopien prüfen Grenzen, Windows-sichere Namen, HFS0-Hashes und XCI-Rootheader.
hactool bekommt nur explizit ausgewählte Schlüsseldateien; die Standardsuche wird
in ein frisches temporäres Home isoliert. Rohe Extraktionsausgaben gelangen nicht
ins GUI-Protokoll. Metadaten-/Inhaltscache und Control-/Meta-Titelfamilienzuordnung
werden gemeinsam genutzt. Dateikopien, Inventarprüfung, rückrollbare Linux-/Windows-
Veröffentlichung und Generatorfortschritt sind gemeinsame Installerhelfer.
Generierung und Images werden ebenfalls transaktional veröffentlicht: entfernte
optionale Module hinterlassen keine alten C-Chunks/Images; fehlgeschlagene
Neubuilds bewahren das bisherige Inventar.
Gemeinsame Kopien verweigern außerdem bestehende Links/Reparsepunkte im Ziel und
ineinander verschachtelte Quell-/Zielbäume. Unlesbare Unterbäume führen zum Fehler
statt zu unvollständigen Kopien/Inventaren. Bei Ausgabeüberlauf oder fehlerhaftem
Fortschrittscallback beendet die begrenzte Prozessaufnahme das eigene Werkzeug,
statt unbegrenzt auf dessen Ende zu warten.

Das Paket enthält `BDSP.exe`, gemessene Runtime-DLLs, `img`, `romfs`,
`exefs/main.npdm` und Notices, aber kein Python, Unicorn oder Buildwerkzeug.
Standardziel ist `%LOCALAPPDATA%\StrahlenderXnu\app`; Saves und Caches liegen
außerhalb. Veränderte/fremde Pakete werden nicht überschrieben; scheitert die
Rücknahme einer Installation, bleiben die alten Dateien erhalten. Ein sauberer
Neubuild bewahrt bisherige Targetausgaben. Modpakete werden vorerst ausdrücklich
abgelehnt statt ignoriert.

Native synthetische Proben durchlaufen echte Generierung, Compile, Images, Runtime,
Link, Paket und Installation **nach ersetzter künstlicher Extraktion**. Das
verschobene Paket erreicht ohne Entwickler-PATH die beabsichtigte Diagnose eines
fehlenden Spieleinstiegs. Eine getrennte JSONL-Probe mit isoliertem Python ruft
den echten Extraktor auf einer ungültigen künstlichen NCA auf und prüft Fehler und
Redaktion. Das beweist weder echte NCA-Extraktion noch GUI-Klickabnahme mit Spieldaten
oder Gameplay. `BDSP_WINDOWS_HACTOOL_ROOT` und `BDSP_WINDOWS_PRIVATE_CATALOG`
aktivieren diese Proben. Gemeinsame Tests: `test_container_extract`,
`test_extract_game`, `test_windows_pipeline`, `test_installer_filesystem` und
`test_installer_driver`.

Die Windows-Vorbereitung zeigt ihre Abhängigkeits-/Freigabedetails zusätzlich in
einem lesbar getrennten Scrollbereich, ohne Download-/Installaktion. Gebündeltes
Windows-Python wird neben der EXE unter
`resources/runtime/<host>/python/python.exe` gesucht. Die Runtime-Assemblierung
erfasst alle Windows-Dateihashes einschließlich Extensions und Notices; veränderte,
zusätzliche, fehlende oder verlinkte Dateien verhindern die Backendauswahl. Dieses
Inventar prüft die Integrität innerhalb des vertrauenswürdigen Releasepakets und
ersetzt keine authentifizierte Downloadprüfung.

`python installer\scripts\release.py windows-readiness` liefert offline einen
JSON-Bericht und beendet sich mit **1**, solange Windows-Paketierung/Signierung
nicht freigegeben ist. Release-Sammlung und Veröffentlichung verweigern
`installer-windows-*` vor Staging oder externen Befehlen. Private Pakete werden
weder still übergangen noch als Freigabe behandelt. Passende FFmpeg-/Drittquellen,
Herstellerrezept und Notices, eine autorisierte VC-Runtime-Quelle und vollständige
Toolchain-Notices bleiben unabhängig von nativen Proben offen.
Der lokale Notice-Audit fand die targetspezifischen MinGW-`COPYING*` unter
`<LLVM>/<target>-w64-mingw32/share/mingw32`. Private Spielpakete bewahren jetzt
alle fünf Dateien einschließlich Runtime- und winpthreads-Notices. Das vollständige
Compilerarchiv enthält zusätzlich separat lizenzierte Hostwerkzeuge wie
Make/BusyBox, Python, gendef und widl; seine LLVM-Hauptlizenz deckt deren Audit
nicht ab. Der Offline-Audit hat alle **30** Notice-Dateien des Compilerarchivs
mit ihren entpackten Gegenstücken verglichen und unter
`work\windows-tools\license-audit\llvm-notices` gesichert. BusyBox enthält GPLv2,
Make/gendef GPLv3, widl gemischte Notices; Python/libffi haben eigene Bedingungen.
Passende Quellen-/Buildnachweise für die Copyleft-Hostwerkzeuge liegen lokal nicht
vor. Deren Vorhandensein im Maintainerarchiv ist weder eine Anforderung für den
direkten Endnutzer-Build noch eine Weiterverteilungsfreigabe.

Der gemeinsame Notice-Kopierer bewahrt jetzt vollständige `LICENSES`-Verzeichnisse
und Autorenlisten, ohne unbeteiligte Quellbäume zu übernehmen. hactool erhält zudem
die unveränderten cJSON-, Unicode-ConvertUTF- und LZ4-Quelldateien mit ihren
eingebetteten Bedingungen; ISC-Hauptlizenz und mbedTLS allein reichten dafür nicht.
Separate private `*-license-audit`-Bundles bewahren die bisherigen Binaries und
ergänzen 13 Vulkan-Notices, eine SDL-Autorenliste je Architektur, fünf hactool-
Notice-Träger und zwei allgemeine FFmpeg-Lizenztexte. Ihre Receipts bleiben
`qualified:false`; ursprüngliche Bundles und Katalog wurden nicht geändert.
`work\windows-tools\license-audit\audit.json` hält Hashes und Nachweislücken fest;
`private-catalog-license-audit.json` wählt die neuen amd64-Varianten ausschließlich
für private Debug-GUI-Tests.

Offline-Reproduktion in ein **noch nicht vorhandenes** Ausgabeverzeichnis:

```powershell
python scripts\recomp\dependency_build.py notices --bundle work\windows-tools\vulkan-x86_64 --archives work\windows-tools\archives --prefix work\windows-tools\vulkan-x86_64-new-notices
```

Dies unterstützt auch gepinnte quellgebaute SDL-/hactool-Bundles; für ARM64-SDL
`--target aarch64` ergänzen. Veränderte/zusätzliche Eingaben, unbekannte Herkunft,
fehlende oder abweichende Archive und vorhandene Ausgaben werden abgelehnt.
Beim Import der freigegebenen FFmpeg-Binärdatei ergänzt `--archives` die vollen
allgemeinen GPLv3-/LGPLv3-Texte aus dem gepinnten **8.0.1**-Quellarchiv. Es wird
kein FFmpeg gebaut; dieses Archiv wird ausdrücklich **nicht** als entsprechende
Quelle des **8.1**-Binaries ausgewiesen:

```powershell
python scripts\recomp\dependency_build.py ffmpeg --archive work\windows-tools\archives\ffmpeg-n8.1.3-24-g92611900bb-win64-lgpl-shared-8.1.zip --archives work\windows-tools\archives --prefix work\windows-tools\ffmpeg-x86_64-new-notices
```

Passende FFmpeg-/Drittquellen, Herstellerrezepte und komponentengenaue Lizenzprüfung
bleiben offen. Das lokale Unicorn-Wheel enthält **keine vollständigen Lizenz-/
Notice-Dateien**: Die Metadaten nennen BSD, das eingebettete README GPLv2.
Das Entfernen der Python-Bindings beseitigt keine Pflichten der nativen Engine.
Das gepinnte Installer-CPython **3.13.15** liegt lokal weder als Archiv noch
assemblierte Runtime vor; Python **3.14** aus der Toolchain ersetzt dessen Prüfung
nicht. Dies sind fehlende Artefakte/Nachweise, keine Behauptung eines bereits
erfolgten Lizenzverstoßes. Eine öffentliche Windows-Freigabe gibt es weiterhin nicht.

Die echte SDL-Probe hängt zusätzlich virtuelle einzelne linke/rechte Joy-Cons
mit explizitem SDL-Typ und horizontaler Zuordnung gemäß gepinntem SDL-Mini-Modus
an. Getrennt geprüft werden Gesichtstasten, Start, Stickklick, SL/SR-Schultern,
linke Stickrichtungen, Fokusreset/-rückkehr, Abziehen und Wiederanstecken. Das
emuliert keine Bluetooth-/HID-Pakete und beweist keine physische Paarung.
Controllerkonfiguration gehört ausschließlich in die **Spielruntime, nicht in den
Installer**. Dieser hat dafür weder Oberfläche noch Preferences oder Buildparameter;
das Spielpaket enthält keine ausgewählte Modusvorgabe. Die Windows-Runtime liest
`%LOCALAPPDATA%\StrahlenderXnu\controller-mode.txt` beziehungsweise
`BDSP_CONTROLLER_CONFIG` mit `pair` oder `single`. Fehlt die Datei, gilt Paarmodus;
`BDSP_JOYCONS=pair|single` überschreibt sie ausdrücklich. Ungültige/unlesbare
Konfiguration führt zu einer Diagnose. Eine Runtime-Einstellungsoberfläche fehlt noch.
**Gemeinsame Spieloberfläche:** Qt wurde unter Linux gerade wegen der geplanten
Windows-Portabilität gewählt. Ein vereinfachter Endnutzer-Build war kein Auftrag,
Qt durch eine neue SDL-Anwendungsoberfläche zu ersetzen. Der vorhandene
In-Process-Host `app/linux/qt_ui.cpp` ist jetzt die gemeinsame Quelle; der
Verzeichnisname ist historisch. Der separate X11-Einbettungsfallback
`bdsp_qt_host.cpp` mit seinem CMake-Build bleibt Linux-exklusiv. AppKit bleibt
unverändert, SDL liefert Controller/Audio, der iced-Installer bleibt separat.
Kein neues SDL-Einstellungsmenü wurde eingeführt.

Der Qt-Host verwendet zum Neustart nicht mehr `/proc`/`execv`: Die Runtime
übergibt die ursprünglichen UTF-8-Argumente; Qt startet dieselbe Anwendung mit
diesen Argumenten und Arbeitsverzeichnis. Startfehler werden vor dem Beenden
des alten Prozesses angezeigt. Cache-/Logaktionen nutzen initialisierte
Runtime-Nutzerpfade. Qt liefert die Vulkan-Surfaceextensions über das
Plattformplugin statt einer hartcodierten Plattformliste. Linux-Xauthority-/
KDE-/MangoHud-Initialisierung bleibt Linux-spezifisch. Windows-Controller nutzen
Initialisierung, 8-ms-Polling, Fokus und Shutdown der vorhandenen
SDL-Hauptthreadfunktionen; kein zweiter Pollingthread oder eigener HID-Backend.

Die direkte `runtime`-/`link`-CLI verwendet standardmäßig `--frontend qt` mit
explizitem `--qt-prefix`. `--frontend sdl` erhält den bisherigen synthetischen
Diagnosepfad; `--backend none` bleibt ohne Grafik. Qt-/SDL-Objektinventare sind
getrennt. Ein Qt-Bundle braucht das vorhandene exakte `build.json`-Inventar/Profil
und ein `qt`-Objekt mit exakter `version` (`6.x.y`), `linkage:"shared"`,
`cxx_runtime:"libc++"`, `minimum_windows_build` höchstens 19045 und zum tatsächlichen
Target-LLVM-MinGW-C++-Treiber passendem `cxx_compiler_sha256`. Geprüft werden
Core-/Gui-/Widgets-Header, MinGW-Importlibs/DLLs, `plugins/platforms/qwindows.dll`,
Notices sowie Architektur und transitive DLL-/Pluginclosure. Ein beliebiges
MSVC-/GCC-Qt-SDK ist kein Nachweis einer kompatiblen C++-ABI.

Private Katalogerzeugung akzeptiert optional `--qt <bundle>` und verdrahtet
diesen Host mit Compile/Link sowie Plugin-Abhängigkeiten, relativer `qt.conf`,
`plugins/platforms/qwindows.dll`, Menüübersetzungen und Qt-Notices. Alte Kataloge
sind ausdrücklich SDL-Diagnosekataloge, keine Qt-Abnahme. Fehlendes Qt wird vor
Runtime-Compile/Sourceoverlay diagnostiziert. Kein automatischer Download,
System-Qt-Fallback oder CMake als Endnutzerpflicht wurde hinzugefügt.
**Der lokale MVP verwendet jetzt die gezielt freigegebenen vorhandenen Archive**
isoliert unter `work/windows-tools/qt-mvp-6.12.0`, ohne vorhandenen Compilerersatz
oder Paketmanagerinstallation. Die echte gemeinsame Qt-Windowsruntime wurde mit
Qt 6.12.0 und passendem Clang 22.1.7 erfolgreich kompiliert (44 Objekte).
Das echte ausgewählte Spiel samt Update wurde außerdem gelinkt und über Qts
Windowsplugin/Vulkan auf einer RTX 2080 Ti gestartet; die Eröffnungsszene zeigt
jetzt Rowan. Das ist keine Whole-game- oder Windows-10-Abnahme; Linux wurde nicht
neu geprüft. Die Redistributionsprüfung bleibt getrennt.
Das Windows-Qt-Spielmenü bietet jetzt **Controller > Joy-Con-Paar / Einzelne
Joy-Cons (Mini-Modus)**; keine Installeroption. Die Auswahl initialisiert nur das
eigene SDL-Gamepadsubsystem im Qt-/SDL-Hauptthread neu, leert Controllerzustände,
öffnet Geräte über den vorhandenen Hotplugpfad und erhält Fokus- sowie
Audioownership. Dabei wird die Controllereingabe absichtlich kurz unterbrochen;
eine verlustfreie Umschaltung wird nicht versprochen. Ein weiterer SDL-
Joystickbesitzer verhindert die Änderung der Startup-Hints; der alte Modus wird
ohne Hintänderung wieder übernommen. Hint-/Initfehler versuchen Rollback;
scheitert auch dieser, bleiben Modusaktionen deaktiviert und Tastatureingabe
verfügbar. Nicht erreichbare Geräte werden beim normalen Polling erneut versucht.

Erfolgreiche Auswahl schreibt `pair` oder `single` atomar mit Flush vor Ersetzen
nach `%LOCALAPPDATA%\StrahlenderXnu\controller-mode.txt`. Schreib-/Publishfehler
stellen soweit möglich den vorherigen Laufzeitmodus wieder her und zeigen einen
Qt-Fehler. Explizites `BDSP_JOYCONS` oder abweichendes
`BDSP_CONTROLLER_CONFIG` deaktiviert die Aktionen, statt anderswo Einstellungen
zu speichern. Der isolierte laufende MVP bleibt daher unverändert. Linux behält
seinen bisherigen Poller; Laufzeitumschaltung ist nur unter Windows aktiviert.
Stick-Klick-Ebene, Steuerkreuz-Hysterese, Plus-zu-Minus, L/R-zu-ZL/ZR und
Loslass-/Zentrierunterdrückung bleiben erhalten; alle Pads bleiben Spieler1.
Die Mini-Belegung ist über vorhandene EN/DE/ES/PT-Tabellen erklärt. Synthetische
Fehlertests und echte SDL mit virtuellen Joy-Cons ersetzen keine USB-/BT-Hardwareabnahme.

Die nicht-invasive Folgeprüfung des bisherigen laufenden MVP bestätigte
`Responding=True`, ~60fps bei145s. Physische Tastaturbedienung in diesem laufenden Spiel bleibt unbestätigt;
keine Eingabe, Fokusänderung oder Saveinhalte wurden angefasst. RSS6544,54MiB,
Privatcommit2356,12MiB plus feste6400MiB Sectioncommit; deren Summe schätzt
zugerechneten Systemcommit, keinen direkt gemessenen Gesamtprozess-Commitpeak.

Die separate Windows-Offscreen-Qt-Fixture prüft jetzt synthetische `QKeyEvent`s
über den **echten KeyForwarder -> SDL-Eventadapter (`input_handle_event`) ->
`input.c`-Mixer -> COFF-registrierten `nn::hid::GetNpadState`**. Geprüft sind
alle20 belegten Tasten, kombinierte Buttons, Press/Release, Auto-Repeat und
verzögerte Release/Press-Repeatpaare, Modifier-/Unbekannt-Unterdrückung,
Popup-/Inaktiv-Gates, Fokusverlust sowie App-/Fensterdeaktivierung. Dabei wurde
ein echter Fehler mit hängenden Gastbuttons bei Qt-Fokusverlust behoben:
ausstehende Release-Timer und gehaltene Tasten werden sofort über den vorhandenen
SDL-Fokusverlusthandler geleert. Das Aktivfenster-Gate gilt nun auch für den
Textzweig der Bildschirmtastatur.
Synthetischer Unicode-Tastentext erreicht deren vorhandenen UTF-8-Callback ohne
HID-Buttons; beim offenen Prompt losgelassene Spieltasten werden ebenfalls
geleert. Der Textcallback ist in dieser Fixture ersetzt: natives Windows-
IME/Preedit, vollständiger Gast-Bildschirmtastaturdienst und physische
Tastaturzustellung sind damit nicht abgenommen.

Die Fixture nutzt echtes Qt6.12.0/SDL3 und produktiven C-Input/HID-Code, aber kein
Spiel, keine GPU-Surface/Controllerhardware, Save-/Dateimenüaktionen oder echten
Einstellungen. Alle45 gezielten Tests bestanden; der separate vollständige
`work\tests\qt-controller-mode\BDSP.exe` wurde mit Fokusfix neu gelinkt, **nicht
gestartet oder deployed**. Das detached Originalspiel behält seine ältere
Binärdatei. Der Nutzer bestätigte anschließend, dass Rowan rendert und
Tastatureingabe im Spiel funktioniert. Das ist Nutzer-Laufzeitbeleg ohne
unabhängig erfasste PID-/Build-/Layoutdetails, keine IME-/Controllerabnahme.
Der gemeinsame Hostfix betrifft auch Linux; Linux/natives Wayland
wurde hier nicht erneut ausgeführt. Windows10-Hardware, ARM64-Ausführung, GC
und Release-/Lizenzgates bleiben offen.

Die vorhandene Bildschirmtastatur ist im Windows-Vulkan-Build gelinkt, kein
Stub. Ihr Display-Gate benötigt Firmware-Schriften des Nutzers und den absoluten
Pfad `BDSP_FIRMWARE_DATA`; dieser fehlte im ersten MVP-Startaufruf. Die
bereitgestellten Firmware-Ressourcen liegen jetzt lokal unter
`work\windows-firmware-20.1.1`; der vorhandene private MVP-Starthelfer setzt
diese Variable. Keine neue Tastaturimplementierung, kein Deployment/Spielneustart.
Vorhandene Schriftatlas- und Layoutlesertests bestanden nativ mit diesen Daten;
der spätere isolierte Spiellauf erreichte das echte Applet, und der Nutzer
bestätigte die sichtbare Tastatur. Textcommit/Abschicken/Abbrechen im Spiel bleiben
ungeprüft. Der Test wurde normal geschlossen, keine BDSP-Testinstanz bleibt;
vor weiteren Starts muss eine andere laufende Instanz ausgeschlossen werden. Siehe
[`input.md`](input.md#windows-vulkan-build-configuration). Firmware nicht
ausliefern; automatische Skriptantworten ersetzen keine interaktive Eingabe.

Der native Test `test_real_swkbd_applet_submit_cancel` prüft jetzt die echten
vorhandenen UI-/Backendcallbacks ohne Spiel: UTF-8-/UTF-16-Ergebnisserialisierung,
Mindestlängenfehler, Abbrechen und interaktives Prüfer-Abweisen/Annehmen.
Kernel-/Storagetransport sind synthetisch; vollständiges Gast-IPC oder
Spiel-Textannahme sind damit nicht abgenommen. Drei gezielte Applet-/Qt-Input-/
SDL-Texttests bestanden. Exitcode0 des früheren echten Laufs bleibt getrennt
vom protokollierten `VK_ERROR_SURFACE_LOST_KHR`; Diagnosezeiten belegen nicht,
ob Surfaceverlust vor/nach Schließen auftrat. Der frühere Offscreen-Reproducer
belegte die fehlende Close-/Keepalivesperre, nicht diese GPU-Fehlerursache.

Der gemeinsame Windows-/Linux-Qt-Host ruft jetzt idempotentes
`vk_host_shutdown()` vor Close-Annahme und nach sonstigem Eventloop-Quit auf.
Ein nach Runtimeinitialisierung aktivierter Application-Eventfilter reagiert
außerdem **vor Objektfiltern** und damit vor Qt-Vulkan-Cleanup auf
`SurfaceAboutToBeDestroyed`. Nativer Qt-Surfaceabbau ist terminal; gewöhnlicher
Vulkan-Swapchainneubau schließt die Zulassung nicht. `host_shutdown.c` sperrt
neue Present-/Represent-/Cleararbeit, stoppt Keepalive ohne spätere Wakes,
joint ohne gehaltene Renderer-/Workerlocks, leert zugelassene CPU-Arbeit und
wartet auf GPU-Idle. Queue-Submit/Present/Device-Idle teilen externe
Queuesynchronisierung. Der joinbare Worker schläft bei unsichtbarer Tastatur
bis zum nächsten Wake oder terminalen Stop.

Acquire wartet höchstens eine Sekunde mit expliziter Diagnose statt
`UINT64_MAX`. Der gesamte Host-Stop-/Drain-/GPU-Wartepfad hat drei Sekunden
Deadline. Vulkan-Device-Idle ist nicht abbrechbar und läuft daher im Waiterthread.
Timeout sowie Treiber-/Stop-/Joinfehler werden protokolliert und beenden mit
Exit1 **vor Close-Annahme/Surfaceabbau**, ohne unsicheren Cleanup zu versuchen.
Ein hängender Treiber gilt nicht als wiederhergestellt. Surface-Loss bei
Capabilityabfrage/Acquire/Present bleibt außerhalb Shutdown fatal, ohne
Fenstergrößen-Fallback oder pauschale Fehlerunterdrückung. Gastthreads werden
nicht global gejoint; nach erfolgreichem Surface-Shutdown beendet bestehendes
`_Exit(0)` sie ohne Abbau gemeinsam genutzter Runtimeressourcen.

`test_real_qt_close_drains_keepalive` ersetzt den Lücken-Reproducer: echte
Qt-Host-/RenderWindowklassen sowie produktiver Shutdown-/Keepalive-C-Code,
barrierengesteuerter synthetischer Present- und GPU-Idlecallback. Geprüft werden
Close-Annahme und direkter nativer Surfaceabbau separat, Drain vor
Objekt-Surfacefiltern, Join/keine späteren Wakes und Idempotenz. Drei getrennte
Negativprozesse halten Keepalive, CPU-Owner oder GPU-Idle über die verkürzte
Testdeadline: jeweils Timeoutdiagnose und Exit1 vor Abbau erforderlich.
Das sind native Offscreen-Orderingtests, **keine GPU-/Spiel-/Hardwareabnahme**.
Physische Close-/Treiber-/Controller-/IME-Abnahme bleibt beim Nutzer; kein
weiterer Spielstart.

Gezielter Befehl nach Setzen der vorhandenen verifizierten Variablen
`BDSP_WINDOWS_NATIVE_BINARY`, `BDSP_WINDOWS_NATIVE_CC`, `BDSP_WINDOWS_SDL_ROOT`,
`BDSP_WINDOWS_QT_ROOT`, `BDSP_WINDOWS_VULKAN_ROOT`:

```powershell
$tests = @(
  'test_real_qt_close_drains_keepalive'
  'test_real_swkbd_applet_submit_cancel'
  'test_real_qt_keyboard_to_guest_hid'
  'test_real_qt_controller_menu_with_synthetic_backend'
  'test_nvn_coff_hle_registration_focus_reset_and_text'
)
python -X utf8 -m unittest -q ($tests | ForEach-Object {
  "scripts.tests.test_windows_native_generator.WindowsNativeGeneratorTests.$_"
})
```

Compile/Link nutzt `portable_build.compile_runtime(..., frontend="qt")` und
`link_executable` mit vorhandenen verifizierten Bundles/Gastobjektinventar nur
unter `work\tests\qt-controller-mode` (45 Runtimeobjekte); kein Start/Deploy.

Windows-Spielicons verwenden `scripts\recomp\app\game_icons.py` weiter:
`windows` erzeugt das vorhandene Qt-Sprachvariantenmanifest/PNGs sowie ein
Standard-ICO mit 16/24/32/48/64/128/256 Pixeln und RC-Datei.
`link_executable(..., icon=...)` bindet diese mit dem gepaarten LLVM-MinGW-windres
ein und erfasst Resourceinputs im Linkreceipt. Der Windows-Installer bereitet
die Icons mit dem vorhandenen autorisierten Control-NCA-Extraktor im Images-
Schritt vor und paketiert `icons/windows`. Qt findet dieses Verzeichnis
automatisch und nutzt bestehendes App-Symbol-Menü, Anwendungs-/Fenstericon und
Sprachpräferenzen; das eingebettete Explorer-EXE-Icon bleibt der Buildstandard.
Keine zweite Artworkpipeline, kein Icondownload. Originalgrafiken bleiben
lokal aus Nutzerdaten erzeugt, keine öffentlichen Releaseassets. Das private
MVP wurde mit sieben RT_ICON-Bildern und einer RT_GROUP_ICON-Resource neu
gelinkt. Offscreentests prüfen Suche und QWindow-Iconvererbung; Explorer-/
Taskleistenanzeige und Cache angehefteter Icons bleiben visuell vom Nutzer
abzunehmen, ohne weiteren vom Agenten gestarteten Spiellauf.

Die inzwischen erlaubte lokale GC-Metadatenprüfung der vier tatsächlichen
MVP-Module (an NSO-Build-IDs gebunden) identifizierte weder `GC_`-/`il2cpp_gc`-/
`GarbageCollect`-/`Boehm`-Einstieg noch benannten Rootcallback in generierten
Symbolinventaren. Das beweist nicht die Abwesenheit eines Collectors: interne/
gestrippte Funktionen müssen keine Exportnamen haben. SDK-SVC0x32/0x33 und
öffentliche Threadkontext-/Suspendwrapper sind vorhanden, aber kein belegter
Push-/Mark-Vertrag. Collectoradresse/Signatur, Rootbereich-/Scanphasen-/Lebensdauer-
regeln sowie Locks/native Reentrancy bleiben unbekannt. Kein produktiver
Root-Preservation-Pseudofix wurde angewandt.

Der wiederholte Offline-Lizenzaudit vorhandener lokaler Bundles steht unter
`work\windows-tools\license-audit-final-20261027\audit.json`; keine Downloads
oder Änderungen am Spielpaket. Inventare/Notices für SDL, Vulkan, FFmpeg,
hactool und ursprüngliche Toolchain sowie alle vier genehmigten Qt-Archivpins
und Qt-Receipt wurden erneut geprüft. Die38 obersten Qt-Lizenzdateien stimmen
mit dem Quellarchiv überein; dort liegen außerdem93 Drittanbieter-Notice-/
Attributionskandidaten zur Anwendbarkeitsprüfung, nicht93 nachgewiesen
ausgelieferte Abhängigkeiten. Die gepaarte Toolchain enthält34 Noticetexte;
libc++/libunwind stimmen mit der Runtime-Referenz überein. Das Receipt selbst
bindet weder Quell-/Toolchainarchivpins noch Herstellerrezept. Vollständige
anwendbare Qt-/Runtime-Attributionen und Quellkorrespondenz, FFmpeg8.1 samt
transitivem Build-/Quellnachweis, Copyleft-Hosttoolquellen und autorisierte
VC-Runtime-Provenienz bleiben Gates. Der alte Audit bleibt erhalten; Hashes und
kopierte generische Lizenztexte allein qualifizieren keinen Release.

Die anschließend erlaubte öffentliche Metadatenrecherche belegt einen echten
Fertigpaket-Kandidaten: Qt **6.12.0**, Kit `6.12.0-0-202609280346`, mit
**LLVM-MinGW 22.1.7**, nicht unserem vorhandenen Compiler 23.1.4. Der private
Qualifikationskandidat in `windows-dependencies.json` hält
Upstream-URL/SHA256/Bytegröße fest: QtBase 20.746.701, Compiler 104.242.456,
Runtime-Referenz des Kits 738.036 und passende QtBase-Quellen nur für
Notices-/Quellkorrespondenzaudit 51.220.268 Byte. Gesamt 176.947.461 Byte,
etwa 168,8 MiB. Nach gezielter Nutzerfreigabe wurden alle vier Archive nach
`work/windows-tools/archives/qt-6.12.0-candidate` geladen und Bytegrößen/SHA256
verifiziert. Eine anschließende ausdrückliche Freigabe erlaubt isoliertes
Entpacken/Ausführen für den lokalen MVP, keine öffentliche Weitergabe.
Native Archivlisten bestätigen
Core-/Gui-/Widgets-DLLs, offizielle `libQt6*.a`-Dateinamen, `qwindows.dll` und SBOMs.
Receiptprüfung und Linkeingaben verlangen jetzt passend zu diesen Listen
`libQt6Core.a`, `libQt6Gui.a` und `libQt6Widgets.a` statt der früheren
synthetischen `.dll.a`-Konvention. `.a` allein bedeutet hier nicht statisches
Qt: Shared-/Compileridentität, Runtime-DLLs, Plattformplugin und DLL-Closure
bleiben Pflicht. Synthetische Positiv-/Falschnamentests qualifizieren nicht
den tatsächlichen Archivinhalt.
Das ist kein Link-/GUI-Nachweis. Der Nutzer priorisiert den Spielstart-MVP
und stellt die Paketmanagerentscheidung zurück; keine eigene
Paketverwaltung oder Paketmanagerintegration wurde ergänzt. Das LLVM-Kit von Qt 6.11.3
nennt dagegen 17.0.6; die allgemeine Windows-Supporttabelle allein bezeichnet
nicht den Compiler eines konkreten Kits.
Die [Qt-6.12-Plattformangabe](https://doc.qt.io/qt-6.12/supported-platforms.html)
umfasst Windows 10 ab 1809 und nennt 6.12 als letzte Windows-10-Reihe.
Das ersetzt keine eigene Windows-10-Abnahme des LLVM-Kits. Der passende Compiler
soll getrennt privat qualifiziert werden, ohne vorhandene Werkzeuge/Runtimes
stillschweigend zu ersetzen. Bestehende C++-shaderc-/Runtimeartefakte benötigen
kompatiblen Neubau beziehungsweise Nachqualifizierung mit bereits erlaubten
Quellen. Die vorhandene shaderc-/FFmpeg-Compile-/Link-/Codec-/Relokationsprobe
besteht auch mit passendem Compiler/Runtime; vollständige ABI-Qualifikation ist
das nicht. Das private Qt-Receipt prüft echte Header/Importlibs, DLL-Closure,
Plattformplugin und Lizenztexte aus passenden Quellen. Die Runtime-Referenz-DLLs
sind byteidentisch mit denen des passenden Compilers; nur dessen Kopie wird
verwendet, um mehrdeutige Provider zu vermeiden. Windows-Systemabhängigkeiten
authz, mpr, netapi32, uxtheme, d3d9, mscms und shcore werden nicht aus dem SDK kopiert.
Passende Quellversion allein beweist weder binäre Buildoptionen noch vollständige
korrespondierende Quellen. Kein SDK-Sourcebuild, QtCreator/QML/WebEngine,
Dokumentations-/Beispielpaket oder öffentliche Weitergabe ist damit genehmigt.

Die native Extraktion behält begrenzten Metadaten-Capture bei, verwirft jedoch
ungenutzte ExeFS-/RomFS-/Control-Ausgaben während des Lesens, statt pro Datei
eine Zeile zu speichern. Große echte Spiele überschreiten damit nicht das
Metadatenlimit; Exitfehler bleiben Fehler und private Ausgabe landet nicht im Log.

Der erste echte Windowslauf zeigte einen unsichtbaren Rowan: Der GPU-Import des
Gast-Aliasheaps scheiterte, Shader-Globalzugriffe lieferten null. Die kontrollierte
64-MiB-Probe verwirft auf dem lokalen NVIDIA-Treiber `MEM_PRIVATE` und
`SEC_RESERVE` auch nach Commit/Befüllen, akzeptiert jedoch eine `SEC_COMMIT`-
Pagefile-Section. Die grafische Windowsruntime verwendet diese daher für den
Aliasbereich; andere Gastbereiche bleiben privat und demand-committed.
Das aktuelle amd64-Aliasfenster beansprucht **6,25 GiB System-Commit**, nicht
zwingend residenten RAM; unzureichender Commit führt zu einem expliziten Startfehler.
Discard nullt Sectionbereiche, ohne GPU-importiertes Backing zu decommitten.
Native Tests prüfen Guards, Privat-/Sectiongrenzen, Schutz, Nullsetzen und
Freigabe/erneutes Reservieren. Vulkan schneidet Host-/Buffer-Speichertypen,
verlangt kohärenten Speicher und prüft Allocate-/Bind-Ergebnisse. Der anschließende
echte 60-Sekunden-Lauf importierte 5.069 MiB erfolgreich; Screenshots zeigen
Rowans Modell und Dialog. Das ist eine lokale Renderregression, keine allgemeine
GPU- oder GC-Abnahme.

**Der Paketmanager ist noch nicht entschieden.** Der Nutzer lehnt MSYS2/pacman
ausdrücklich ab: nicht installieren oder hinter einem Bootstrap verstecken.
Conan 2 bietet native Abhängigkeitsgraphen, Compilerprofile, Revisions-Lockfiles,
Binärcache und `--build=never`, ohne unser Projektbuildsystem zu ersetzen.
Das beweist keine passenden ConanCenter-Binaries: Die reine Metadatenabfrage von
`qt/6.12.0#b0bc6faf97edf4e1e479f9169db772a0` fand zehn Pakete, davon vier
Windows-Varianten, alle MSVC 194 mit `with_vulkan=False`, keine für Windows
Clang/libc++. Die FFmpeg-8.1.2-Binärabfrage lieferte HTTP 403; deren Abdeckung
ist daher unbekannt. Das Quellrezept verlangt beim Windows-Bau Bash/MSYS2 und
Make. vcpkg bietet native Manifeste, Versions-Baselines und Binärcache, hat aber
nur Community-/ungetestete MinGW-Triplets, baut ohne passenden Cache überwiegend
aus Quellen und ruft im tatsächlichen Windows-FFmpeg-Port
`vcpkg_acquire_msys` auf. Kein automatischer Sourcebuild-Fallback ist damit
freigegeben. Conan könnte ausgewählte Herstellerbinaries mit kleinen normalen
Paketrezepten und privatem Cache verwalten statt eines eigenen Resolvers; diese
Integration ist weiterhin ein Vorschlag, nicht implementiert.
`aqtinstall` verwaltet offizielle fertige Qt-/LLVM-Kits ohne MSYS2, ersetzt aber
nicht die Verwaltung des gesamten SDL-/Vulkan-/FFmpeg-Graphen.
Bei diesem Vergleich wurde kein Paketmanager oder zusätzliches Paket installiert.

Die vom Nutzer bestätigte Zusatzebene hält **Stickklick** als Umschalter:
Start wird Gast-Minus, SL/SR werden ZL/ZR, Stickrichtungen werden Steuerkreuz.
Gesichtstasten behalten ihre Position. Loslassen beendet die Ebene sofort;
noch gehaltene umgeschaltete Tasten und Bewegungen bleiben bis zum Loslassen bzw.
Zentrieren gesperrt, statt eine normale Aktion auszulösen. Richtungsschwellen
verwenden Hysterese; es gibt keinen klebenden Toggle. Fokusverlust und Hotplug
löschen den temporären Zustand. Paar-/Standardcontroller und Tastaturbelegung
bleiben unverändert. Echte SDL-Proben mit synthetischen Devices prüfen beide
Hälften, wiederholte Polls, beide Loslassreihenfolgen, Richtungshysterese, Fokus
und Wiederanstecken. Rechter Stick und Gast-Stickklicks bleiben bei Einzelhälften
unerreichbar; die Tastatur bleibt nutzbar.

NVN behält den gemeinsamen HLE-Lookup und die Eingabelogik aller Plattformen; nur
die COFF-Linkergrenze unterscheidet sich von Mach-O/ELF. Optimierte HLE-Registrierung
über mehrere Objekte, UTF-8-Commit-Texte und Tastatur-Fokusreset haben native Proben;
derselbe Glue linkt ohne Ausführung gegen das ARM64-SDL-Paket. Fokusverlust löscht
gemeinsame Tastaturquelle und angesammelte Tastenmaske, damit keine Taste hängenbleibt.
Der SDL-Eventpfad gleicht Texteingabe jetzt bei jedem Event/Timeout am eigenen
Fenster ab, auch bei Fokuswechsel und Gast-Neustart. Start-/Stop-Fehler werden
gemeldet und beenden die Runtime, statt einen erfolgreichen Wechsel vorzutäuschen.
Texteingabe anderer Fenster wird nicht abgeschaltet. Moduswechsel und Neustart
warten nicht mehr auf eine leere Eventqueue; Fenster-Shortcuts greifen nicht,
solange die Gasttastatur die Eingabe besitzt. Fokusverlust bricht auch eine
gehaltene Touch-Taste ab. SDL-Preedit-/Kandidatenereignisse gelangen nicht in
bestätigten Gasttext; gemeldete Komposition behält Bearbeitungs-/Bestätigungstasten
bis Commit oder Abbruch. Native OS-IME-Oberfläche bleibt SDL-Standard, ohne neues
Overlay/Menü. Echte SDL-Dummyfenster prüfen Fokuszuordnung, Start/Stop/Neustart,
falschen Thread und synthetische Unicode-/Preedit-Ereignisse; ARM64 wird
crossgelinkt. Physische IME-/Vollbild-Kandidatenpositionierung und Texteingabe
im Spiel bleiben ausdrücklich unabgenommen.

Der Installer kompiliert und seine gezielten GUI-/Prerequisite-/Backendtests
laufen mit privat vorbereitetem Rust/Cargo 1.88.0 und Cargo.lock-gelockten Crates.
Vorhandenes Visual Studio wurde nur zum Linken dieses Maintainerbuilds verwendet,
nicht zur Endnutzerpflicht gemacht. Die echte Windows-GUI rendert auch ohne Vulkan
über tiny-skia auf Deutsch und Englisch. Die Vorbereitungsansicht zeigt
Werkzeuggruppen mit lesbaren Abständen; technische Freigabedetails bleiben im
aufklappbaren Protokoll statt die Hauptansicht zu füllen.
Vollständige GC-/Threadkontexte, komplette Crashberichte,
echte NCA-Extraktion, vollständige Vulkan-/Audio-/Movie-/Texteingabe-Hardwareintegration,
persistente Einzel-Joy-Con-Bedienung, GUI-End-to-End-Abnahme mit echten Dumps und
werkzeugfreies Gameplay fehlen noch. Windows 10/11, echte Controller und natives
ARM64 brauchen getrennte Hardwareabnahme. Kein Spiel wurde gestartet.

## 7. Überblick über die Bau-Stufen

Reihenfolge der Stufen: `tools extract recomp`. Mit `--only` oder
`--from`/`--to` läufst du einen Teil. Prüfe vorher mit `--dry-run`. Jede Stufe schreibt einen Marker
`work/.stages/<Stufe>.json` mit einem Eingabe-Hash. Passt der Hash, wird die Stufe übersprungen
(`--force` baut sie neu).

| Stufe | Zweck | Für die Apps nötig |
|---|---|---|
| `tools` | prüft Werkzeuge, baut `hactool` nach `tools/hactool` | ja (für `extract`) |
| `extract` | entschlüsselt `.xci`/`.nsp` nach `work/exefs`, `work/romfs`, `work/manifest.json` | ja |
| `recomp` | macOS-App aus der Rekompilation | nur für die macOS-App |

Die Unity-Stufen `il2cpp`, `masterdata`, `video`, `audio` und `shaders` wurden entfernt (sie liegen im Branch `unity`).

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

Der produktive Generator und Image-Bauer laufen als C17-Programm. Der Einstieg
für die CLI ist `bash scripts/recomp/codegen.sh gen ...` bzw. `image ...`.
`BDSP_GEN_JOBS=N` oder `--jobs N` steuert die nativen Threads. Unicorn wird über
seine C-API genutzt; der Generator braucht weder Capstone noch die Unicorn-Python-Bindings,
neue Installer-Laufzeiten enthalten sie nicht. Details: [Native generator](../scripts/recomp/native-generator/README.md).
