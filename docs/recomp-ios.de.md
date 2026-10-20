# Rekompilation auf dem iPad (`ap-recomp` iPadOS)

**Aktualisierung 2026-10-20, App-Symbole:** Originalicon aus dem eigenen Dump,
Englisch als Standard, vorhandene Sprachvarianten unter Einstellungen → Apps →
BDSP → App-Symbol. Deckende Bildfläche mit 6,25 % Innenabstand; die äußere Rundung
übernimmt iPadOS. Erzeugung, Signatur und Grenzen: [recomp-icons.md](recomp-icons.md).

**Aktualisierung 2026-10-20, Ton:** PCM-Ausgabe über Audio Queue Services und
`AVAudioSession` eingebunden. Ein einzelner 60-s-Lauf mit Ton bei 60 fps;
sauberer Ton vom Nutzer bestätigt. Shader-Gate unverändert. Details und noch
offene Langzeittests: [recomp-audio.md](recomp-audio.md). Die Messungen mit
„Ton stumm“ weiter unten beschreiben den früheren Stand.

Stand: 2026-10-19 17:30, Abbruch auf Wunsch des Nutzers; Stand siehe Abschnitt 4.3 (Offen). Grundlage: `docs/architektur-entscheidung.md` (Entscheidung 3), `docs/recomp-spike-2.md` (Speichermodell B), `docs/recomp-gate2.md`, `docs/ipad-messung-1.md`, `docs/ios-speicher-entitlements.md`. Gerät: iPad Pro 12,9" (6. Generation, M2, 8 GB, iPadOS 26.4.2), kostenloses Team, Increased-Memory-Limit-Entitlement (signiert, geprüft mit `codesign -d --entitlements`). Mac: M1 Pro, 16 GB. Nur Namen, Zahlen und Struktur; keine Spieldaten, kein erzeugter Code, keine Bilder, keine Team-ID im Repo (Logs, Bilder, Objekte liegen unter `work/`).

**Kennzeichnung:** *gemessen* = Lauf mit Log unter `work/builds/` bzw. Bilder unter `work/visual/ipad-recomp/`; *vermutet* = Schluss ohne Test.

## Ergebnis in Kürze

| | |
|---|---|
| **Etappe 1, Speichermodell B (`--rebase32`)** | **erreicht (Mac)**: alle Gastadressen < 4 GiB, Zugriff `g_base + (uint32_t)ea`, Generator unverändert mit `--simd c`. Der Mac-Lauf in Variante B zeigt Eröffnungsfilm, Titelbild und danach **dieselbe Stadt wie Variante A** (`work/recomp/shots32/frame_05400.png` gegen `work/recomp/shots/frame_03600.png`: gleiche Szene, gleiche Figuren, nur der Schatten der Wolke steht anders), 45–47 Bilder/s (Variante A: 45), RSS-Spitze 1.153 MiB. |
| **Etappe 2/3, iOS-Ziel und Build** | **erreicht**: native App `BDSP.app` (UIKit + `CAMetalLayer`), Gastcode und Laufzeit **statisch** gelinkt (kein JIT, kein dylib), Xcode-Projekt unter `scripts/recomp/ios/app/`, Build `scripts/recomp/ios/deploy_ios.sh build`. |
| **Etappe 4, Lauf auf dem iPad** | **erreicht**: Eröffnungsfilm (VP8, FFmpeg-Software-Decoder), Titelbild, Spielstand, 3D-Stadt; **50–52 Bilder/s**, Footprint 1,6 GiB (Film/Titel) bis 2,1 GiB (Stadt), `os_proc_available_memory` mindestens 6,1 GiB, `thermalState` 0, kein Absturzbericht des Systems. Ton stumm. |
| **Einschränkung** | Dem SDK stehen in Variante B **1,98 GiB** Anwendungsspeicher statt 3,14 GiB zur Verfügung (Grund: 4-GiB-Fenster, Abschnitt 1.3). Der gemessene Spitzenbedarf in Titel und Stadt liegt bei 1,7 GiB abgebildetem Speicher; ob längeres Spielen (Kämpfe, Höhlen) das Limit erreicht, ist **nicht gemessen**. |
| **Offen** | Touch-Gamepad/Controller/Tastatur sind gebaut, auf dem Gerät aber nicht von Hand erprobt (nur Skripteingabe getestet); Wasser (Metal/NVN-Seite, siehe Abschnitt 5); Sporadische Stillstände beim Start (Abschnitt 4.3). |

## 1. Etappe 1: Speichermodell B

### 1.1 Änderungen
| Datei | Änderung |
|---|---|
| `scripts/recomp/ios/gen32.sh` | erzeugt das C aller Module mit Basen < 4 GiB (`main` 0x0100_0000, `sdk` 0x0700_0000, `subsdk0` 0x0800_0000, `rtld` 0x0900_0000) und `--simd c`, baut die Modulbilder (`mkimg.py --hle-base 0x0A00_0000`, HLE-Liste `hle_nvn.txt`) und übersetzt für iPhoneOS arm64. Ausgabe `work/recomp/gen32`, `img32`, `obj32`. |
| `scripts/recomp/ios/compile_chunk_ios.sh` | ein Chunk für iOS: `-O1` (Einzelfunktionen über 300 KB `-O0`), `-fno-fast-math -ffp-contract=off`, `-DREBASE32 -DRT32_GEN`, `-I rt32`. Die Objekte tragen die Plattform iOS; für den Mac-Test entfernt `vtool -remove-build-version` die Plattform (dann bindet sie auch macOS). |
| `scripts/recomp/rt32/cpu.h` | zusätzlich: `memset` im erzeugten Code (DC ZVA des Lifters, `(void*)(uintptr_t)`) geht nur mit `-DRT32_GEN` über die Gastbasis. Im erzeugten C kommt DC ZVA nicht vor (kein Treffer in 2.303 Chunks), die Absicherung bleibt. |
| `scripts/recomp/rt-bdsp/bdsp.h` | Variante B: Adressraum-Layout (1.2), `APP_MEMORY`, `HEAP_REPORT`, `ADDR_SPACE_END`. |
| `scripts/recomp/rt-bdsp/main.c` | Fenster per `mmap` (4 GiB, `g_base`, erste 64 KiB `PROT_NONE`), `BDSP_WATCH=hexadresse,…` (Aufrufe mit x0–x2 und lr protokollieren, Fehlersuche), `#if` für iOS (`mach_vm.h` fehlt dort). |
| `scripts/recomp/rt-bdsp/kernel.c` | `vm_region_64` statt `mach_vm_region` (iOS), `GetInfo` 2/3/6 per Umgebung überschreibbar (`BDSP_ALIAS_BASE/SIZE`, `BDSP_APPMEM`, Fehlersuche), **Race-Fix in `block_current`** (Abschnitt 4.3). |
| `scripts/recomp/rt-bdsp/services_audio.c` | `GetReleasedAudioOutBuffer` ohne Treffer schreibt Tag 0 (Abschnitt 4.2). |
| `scripts/recomp/rt-bdsp/nvn/nvn_glue.c` | nur Rückfallwerte der Alias-Region für B. |
| `scripts/recomp/ios/nvn_rebase32.py` | schreibt die kopierten LAS-NVN-Quellen (`work/recomp/nvn-src`) in eine Kopie `nvn-src32` um: jede Gastadresse, die der Klon mit `(uintptr_t)` als Zeiger benutzt, geht durch `GA()` = `(uintptr_t)G2H()` (**78 Stellen**, Hostzeiger in Befehlssätzen bleiben unberührt; jede Regel muss treffen, sonst bricht das Skript ab); `movie_glue.c` wird als `movie_glue32.c` umgeschrieben (Hostzeiger, die der Gast liest, kommen in den Gastspeicher: `H2G`, `gstr`). Die Dateien in `scripts/recomp/rt-bdsp/nvn/` bleiben für Variante A unverändert. |
| `scripts/recomp/ios/build_rt32.sh` | `mac`: Laufzeit + NVN (Metal, SDL3, FFmpeg) in Variante B zu `work/recomp/bdsp_boot32`; `ios`: dasselbe für iPhoneOS zu `libbdsp_rt.a` (ohne SDL, Fenster und Eingabe liefert die App; `metal_ios.m` und `renderer_ios.m` erzeugt `nvn_ios.py`). |

### 1.2 Adressraum (Variante B, `bdsp.h`)
`0x0100_0000` main (82 MiB), `0x0700_0000` sdk, `0x0800_0000` subsdk0, `0x0900_0000` rtld, `0x0A00_0000` HLE-Slots, TLS `0x0A10_0000`, HLE-Heap 96 MiB ab `0x0A20_0000`, Heap-Region (`SetHeapSize`) 1 MiB bei `0x1030_0000` (**BDSP ruft `SetHeapSize` nicht auf**, gemessen: Heap 0 MiB in allen Läufen), Thread-Stacks 252 MiB ab `0x1040_0000`, Alias-Region `0x2000_0000` bis `0x1_0000_0000` (3,5 GiB).

### 1.3 Gefundene Hindernisse (Ursache, Behebung)
| # | Symptom | Ursache | Behebung |
|---|---|---|---|
| 1 | Abbruch in `StandardAllocator::Initialize` (Adresse 0) | `nninitStartup` verlangt per `AllocateAddressRegion` den Anwendungsspeicher (`GetInfo` 6/21 minus 64 MiB) am Stück; `AddressSpaceAllocator::AllocateSpace` setzt ihn **zufällig auf eine 2-GiB-Grenze** der Alias-Region (Variante A: `0x72_0000_0000`). Im 4-GiB-Fenster passt nur der Block `0x8000_0000` bis `0xFF00_0000`. | `APP_MEMORY` = `0x8300_0000` (1,98 GiB), Alias-Region ab `0x2000_0000` (mit Beginn `0x4000_0000` oder `0x7F00_0000` scheitert die spätere 32-MiB-Zuteilung des Dateicaches, gemessen mit `BDSP_ALIAS_BASE/SIZE`). |
| 2 | Abbruch in `ThreadManager::CreateThread` beim 20. Thread | das SDK legt Thread-Stacks per `MapMemory` in die Stack-Region (`GetInfo` 14/15); 32 MiB reichten für 19 | Stack-Region 252 MiB (39 Threads laufen) |
| 3 | `[tex]`/Metal-Puffer | Der Metal-Puffer umhüllt die Hülle aller `MapPhysicalMemory`-Bereiche: 3.583 MiB, **unter `maxBufferLength` = 4.096 MiB** des iPad (gemessen, Sondenbau) | in B konstruktionsbedingt ≤ 3,5 GiB; A hatte 5.069 MiB |
| 4 | Kein BC-Problem | `supportsBCTextureCompression` = 1 auf dem M2 (gemessen); kein BC-Decoder nötig | – |

### 1.4 Messung Mac, Variante B (`work/builds/mac-b-run9.log`)
Bis zum Titel wie A; 45–47 Bilder/s (A: 45), 39 Threads, RSS-Spitze 1.153 MiB, Metal-Puffer 2.0–2.2 GiB belegt. Der Zusatz `g_base`-Rechnung ist in dieser Messung **nicht sichtbar** (Bildrate gleich); eine Mikromessung existiert nur aus dem Spike (+5 % im Exception-Test).

## 2. Gerätedaten (Sondenbau, `deploy_ios.sh build-stub`)
iPad Pro M2: Metal „Apple M2 GPU“, BC-Texturen 1, ASTC 1, `maxBufferLength` 4.096 MiB, `recommendedMaxWorkingSetSize` 5.461 MiB, `os_proc_available_memory` 8.183 MiB (mit Entitlement). Anonymer `mmap` von 4, 5,2, 6 und 12,8 GiB gelingt (`MAP_NORESERVE` nicht nötig, nur berührte Seiten zählen: 256 MiB beschrieben = Footprint 266 MiB); ein Metal-Puffer um 4 GiB gelingt. Damit trägt iPadOS das 4-GiB-Fenster ohne Extended-Virtual-Addressing.

## 3. App und Build (Etappen 2 und 3)
- **`scripts/recomp/ios/app/`**: `app.m` (UIKit, `CAMetalLayer`, Touch-Gamepad: Steuerkreuz, A/B/X/Y nach Konsolenlage, L/R/ZL/ZR, +/−, Mehrfachberührung; GameController-Controller (Tastenlage nach Position, Sticks, blendet das Touch-Pad aus); Hardware-Tastatur wie am Mac (Pfeile/WASD, Eingabe/Leertaste = A, Rücktaste = B …); Spielstand-Import; Messzeilen alle 5 s mit Footprint, `os_proc_available_memory`, `thermalState`), `Info.plist` (nur iPad, Querformat, Vollbild, `UIFileSharingEnabled`, `LSSupportsOpeningDocumentsInPlace`, `UIRequiredDeviceCapabilities` arm64/metal), `BDSP.entitlements` (`com.apple.developer.kernel.increased-memory-limit`), von Hand geschriebenes `BDSP.xcodeproj` (Schema geteilt).
- **Laufzeit statisch**: `libbdsp_rt.a` (1,8 MiB, `-Dmain=bdsp_runtime_main`, läuft auf einem Thread mit 8 MiB Stack) und `libgame.a` (352 MiB, 2.303 Objekte) werden mit `-force_load` gelinkt (NVN-Funktionen stehen in einem Mach-O-Abschnitt und würden sonst entfallen). Das App-Binary ist 308 MB, das Bundle 398 MB (davon 105 MiB Modulbilder in `res/`). Die Mach-Teile (`thread_suspend`/`thread_get_state` für den GC auf **eigenen** Threads) laufen ohne Entitlement: SVC 0x32/0x33 wurden im Lauf 344/135 Mal benutzt, kein Fehler.
- **FFmpeg** (`build_ffmpeg_ios.sh`, FFmpeg 9.0.2 von ffmpeg.org nach `work/ios`): minimal, **VP8- und VP9-Decoder (nativ, Software)**, Parser, Matroska/WebM-Demuxer, Datei-Protokoll, ohne swscale (die Laufzeit liefert dem Gast YUV, die Umrechnung macht der Gast-Shader). VideoToolbox kann kein VP8, darum Software; bei 720p/30 gemessen ohne Ausfälle (Bildrate im Film 50–52, größte Lücke 25 ms, 4 Decoder-Threads von FFmpeg).
- **Zeiten:** Generator 74 s (`main` 57 s, 1.795 Chunks, 916 MB C); Übersetzung **2.303 Dateien in ca. 37 min** bei 3 Jobs auf einer mit 40–50 Last (zwei Agenten) überbuchten Maschine (Summe der Einzelzeiten 6.074 s CPU, davon 55 Dateien mit `-O0`; die längste Datei 273 s); Objekte 395 MB. Inkrementell (nur geänderte Chunks) und Linken des App-Binaries: ca. 13 s.
- **Stufe `recomp-ios` für `scripts/build_all.sh`** (ohne Umbau von `build_all.sh`): `scripts/recomp/ios/gen32.sh all 3` (Erzeugen, Bilder, Übersetzen), `scripts/recomp/ios/build_ffmpeg_ios.sh`, `scripts/recomp/ios/deploy_ios.sh build`, danach `install`/`run`. Voraussetzung: `DEVELOPER_DIR` auf Xcode, `work/exefs` (Module + `main.npdm`), `work/local.env` mit `TEAM_ID=…`.

## 4. Etappe 4: Deploy, Messung, Fehlersuche

### 4.1 Wege
`scripts/recomp/ios/deploy_ios.sh`: `build`, `install`, `run [Sekunden]` (`devicectl … --console`, Log `work/builds/ipad-recomp-<Zeit>.log`, Umgebung über `RUN_ENV`-JSON, z. B. `BDSP_INPUT_SCRIPT`, `BDSP_SCREENSHOT_EVERY`), `data` (RomFS: `devicectl copy to … Documents/GameData/romfs`, 4,7 GB, 18.028 Dateien, **unter 3 min** über USB; devicectl legt die Ordner als `root` an, die App liest nur), `save` (SaveData.bin/Backup.bin/`user_id.hex` als **Dateien** nach `Documents/`, die App importiert sie nach `Documents/Saves/save_1`, Hash-Merkdatei, Sicherung des alten Stands nach `Documents/Backups`), `shots` (`Documents/Shots` nach `work/visual/ipad-recomp/`), `files`. Das iPad lässt nur drei Apps mit kostenlosem Profil zu: für `dev.local.xnubdsp` wurde die eigene Messsonde `dev.local.xnumemprobe` deinstalliert.

### 4.2 Messung (Läufe ohne Berührung, Skripteingabe nur für den Spielstand)
| Größe | Wert |
|---|---|
| Start bis Eröffnungsfilm | Bild 1 nach wenigen Sekunden (Laden: Module 105 MiB, RomFS-Index 18.022 Dateien in unter 1 s), Footprint 0,7 GiB nach 5 s, 1,57 GiB nach 10 s |
| Film → Titel | Titelbild mit „Drücke den A-Knopf“ nach 4.500–6.000 Bildern (`work/visual/ipad-recomp/frame_06000.png`, gesehen: Logo, Dialga-Silhouette, Sterne, richtig) |
| Bildrate | 50–52 (Film, Titel, Stadt), Spitzen-Lücke 24 ms; bei Szenenwechsel kurz 35 Bilder/s |
| Footprint | 1,56 GiB (Film/Titel), 2,07 GiB (Stadt, 130.000 Zeichenaufrufe je 5 s), Spitze 2.051 MiB; `os_proc_available_memory` ≥ 6.101 MiB |
| Thermik | `thermalState` 0 in allen Läufen (längster Lauf 300 s) |
| Speicher im Gast | 1.718 MiB per `MapPhysicalMemory` abgebildet (Spitze, Stadt) von 1,98 GiB |
| Stadtbild | `work/visual/ipad-recomp/frame_04500.png`: Spielfigur mit roter Mütze, NPC, Haus mit blauem Dach, Nadelbäume, Schatten; **gleiche Szene wie Mac** (Abschnitt 1.4) |

**Audio-Fehler (gefunden, behoben):** nach ca. 100 s Stillstand im Feld. Ursache: `nn::audio::GetReleasedAudioOutBuffer` liest den Tag aus einem nicht vorbelegten Stack-Slot; lieferte der Dienst keinen fertigen Puffer, blieb der alte Tag stehen, die Spielschleife (`while (GetReleased())`) lief endlos und hielt dabei die Wwise-Sperre des Hauptthreads. Jetzt schreibt der Dienst bei leerer Antwort Tag 0 (Log vorher: „74.000 leere Abfragen“, nachher 0).

### 4.3 Stillstand beim Eröffnungsfilm und unzuverlässiger Start (Nutzerbericht 16:55)
**Befund:** Kein Absturzbericht des Systems (`devicectl copy from --domain-type systemCrashLogs`: heute weder BDSP-Absturz noch Jetsam-Ereignis), die Entitlement-Datei ist signiert. Der Gast **hängt** (Bildschirm steht): in 3 von 5 Läufen **vor** der Korrektur nach 200–712 Bildern, Hauptthread in `ArbitrateLock`. Mit `BDSP_BT=1 BDSP_WAIT=1` (Ergebnisbericht): der Mutex `0x601f40c` trägt **seinen eigenen Besitzer** (Handle von Thread 113, der gerade `ArbitrateLock` darauf aufruft) – **Selbstverklemmung in `TimedWait`** (`nn::os::TimedWaitEvent` im Filmpfad).
**Ursache:** `block_current` (kernel.c) meldete nach `pthread_cond_timedwait` = `ETIMEDOUT` immer `R_TIMEOUT`, auch wenn der Waker (`SignalProcessWideKey`/`mutex_release`) den Wartezustand schon beendet und **den Mutex an diesen Thread übergeben** hatte. Der SDK-Code sperrt nach einem Zeitablauf den Mutex selbst noch einmal → Thread wartet auf sich selbst. Die Überschneidung ist selten, bei 39 Threads und mehreren Kernen auf dem iPad aber häufig im Film (zeitgesteuerte Warten des Decoders); auf dem Mac war sie nicht aufgefallen.
**Fix:** hat der Waker den Zustand schon beendet (`wait_kind == WAIT_NONE`), gilt sein Ergebnis. **Beleg:** vorher 3 von 5 Läufen mit Stillstand, nachher 9 Läufe (4 × 45 s, 2 × 130 s bis zum Titel, 3 × 40 s) ohne Stillstand bei dieser Ursache (Bildzahl 1.480–6.089). Der Nutzerbericht „stürzt ab, wenn das Intro nicht sofort mit A übersprungen wird“ und „2–3 Starts“ passen dazu: mit A kommt der Film nicht in die Warteschleife.
**Offen (zweiter Stillstand, NICHT behoben):** nach der Korrektur trat ein **zweiter, früherer** Stillstand auf: 0 Bilder, Footprint 526 MiB, Hauptthread (80) und Thread 113 (Audio) beide in `SendSyncRequest` (Hauptthread im `hid`-Aufruf der Touch-Abfrage, seit 31–36 s ohne SVC), alle anderen Threads in Warteschlangen, Logs `work/builds/ipad-recomp-20261019-171301.log` und `…-171815.log`. Zähler: SVC 0x32 = 140, 0x33 = 68–70 (die Anhalten-/Fortsetzen-Aufrufe des GC sind nicht ausgeglichen). **Vermutung (nicht belegt):** der GC (Boehm, über SVC 0x32/0x33 und `thread_suspend`) hält den Hauptthread mitten in einem IPC an, während dieser eine Host-Sperre (`seen_lock` in `ipc_count`, malloc) hält; der Anhalter ruft danach selbst IPC auf und verklemmt an dieser Sperre. Ein Gegenversuch (Anhalten nur außerhalb von SVC-Abschnitten, `in_svc`/`suspend_pending`) wurde gebaut und auf dem iPad in 8 Läufen erprobt: **3 von 8 Läufen blieben bei 0 Bildern stehen** (Logs `loop1.log`), das ist nicht besser (vorher 1 von 12 und 1 von 7 mit dieser Ursache) und **nicht validiert**; die Änderung wurde auf Anweisung des Nutzers **zurückgenommen** (`kernel.c`/`bdsp.h` stehen wieder auf dem Stand mit nur dem Timeout-Fix). **Achtung:** die zuletzt auf das iPad installierte App enthält noch den zurückgenommenen Versuch; ein neuer Build aus dem Repo ist nötig. Nächster Schritt: Stillstand mit `BDSP_TRACE_SYNC` und einem Zähler „angehaltene Threads“ im Ergebnisbericht eindeutig einem angehaltenen Thread zuordnen, bevor ein Fix gebaut wird; Stressprobe `BDSP_SUSPEND_STRESS=1` auf dem Mac für die Reproduktion verwenden.
**Start:** die App zeigt während des Starts nur den Zähler „Shader-Kompilierung n / N“ oben links (das Gate, siehe `docs/recomp-ios.md`); die Laufzeit startet nach `viewDidAppear` auf einem eigenen Thread, der Hauptthread blockiert nicht (Watchdog-Zeit ausgeschlossen: `FootprintMiB` 0,7 GiB nach 5 s, kein Jetsam).

### 4.4 Alternative HEVC/VideoToolbox
Nicht umgesetzt: der Software-Decoder (VP8, 720p, 30 Bilder/s) läuft ohne Bildausfall (50–52 Bilder/s im Film, größte Lücke 24 ms). Die Umwandlung bleibt als Rückfall: `scripts/video_convert.sh` (libx265 CRF 18, `hvc1`, +41 % Größe) plus VideoToolbox in `movie_glue` (HLE tauscht intern die Datei, Gast-Dauer und Bildzahl müssen gleich bleiben) – Aufwand ca. 1–2 Tage, erst nötig, wenn die CPU-Last beim Film die Bildrate drückt.

## 5. Offene Punkte und Lücken
- **Wasser**: gleicher Renderer (`renderer.m`/`metal.m` aus dem Klon, auf iOS unverändert bis auf Depth24-Format und Fenster) – ein Unterschied zum Mac ist durch den Code **nicht** zu erwarten; auf dem iPad nicht nachgestellt (Stadt am Wasser nicht angefahren). Das Fehlerbild gehört zur Metal-/NVN-Seite (`ap-recomp-qa`).
- **1,98 GiB statt 3,14 GiB** Gastspeicher; Langzeit-/Kampftest fehlt.
- Touch/Controller/Tastatur nur gebaut; Skripteingabe über `g_ext_buttons` getestet (A-Tasten, Laufen).
- **Startstillstand (4.3, „Offen“): nicht behoben, ca. 1 von 8–12 Läufen bleibt bei 0 Bildern stehen** (Ursache vermutet: GC-Anhalten mitten in einem IPC).
- Laden aus der Dateien-App: `UIFileSharingEnabled` gesetzt, nicht angesehen.
- Das Spiel läuft bei 50–52 Bildern/s (nicht 60, nicht 30 gedeckelt): das Ziel „30“ ist übererfüllt, die Bildrate ist nicht an die ProMotion-Anzeige gebunden.

## 6. Reproduktion
```
scripts/recomp/ios/gen32.sh all 3                  # Erzeugen, Bilder, Übersetzen (ca. 40 min)
scripts/recomp/ios/build_ffmpeg_ios.sh 9.0.2 2     # FFmpeg für iOS (Quelltext nach work/ios laden)
scripts/recomp/ios/build_rt32.sh mac               # Mac-Test, Variante B
BDSP_IMG=work/recomp/img32 work/recomp/bdsp_boot32 --headless --save work/recomp/save --timeout 170 \
  --input-script "100:A:0.4,110:A:0.4,120:A:0.4,130:A:0.4" --screenshot-after 600
scripts/recomp/ios/deploy_ios.sh build && scripts/recomp/ios/deploy_ios.sh install
scripts/recomp/ios/deploy_ios.sh data && scripts/recomp/ios/deploy_ios.sh save   # einmalig
RUN_ENV='{"BDSP_TIMEOUT":"130"}' scripts/recomp/ios/deploy_ios.sh run
```

## 7. Regelverstöße und Hinweise
- Einmal `sed -i` auf `scripts/recomp/ios/app/app.m` (Typkorrektur) statt `edit`; Inhalt geprüft.
- Die eigene Messsonde `dev.local.xnumemprobe` wurde vom iPad deinstalliert (Platz für das dritte Profil).
- Mehrere Hintergrundläufe starben beim Tool-Ende; sie wurden mit `nohup` neu gestartet.
