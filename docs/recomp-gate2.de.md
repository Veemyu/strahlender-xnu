# Rekompilation, Gate 2 „Grafik“ (`ap-recomp` Gate 2)

Stand: 2026-10-19, Zwischenstand (wird je Etappe fortgeschrieben). Grundlage: `docs/recomp-gate1.md` (Gate 1 erreicht), `docs/recomp-machbarkeit.md`, `docs/shader-translator.md`, `docs/referenz-las-shader.md`. Auftrag: Das Spiel soll im rekompilierten Betrieb ein erstes Bild über Metal zeichnen (macOS arm64, **ohne Ton**); Kriterium: ein nicht-schwarzes, erkennbares Bild des Startbildschirms im Screenshot.

**Kennzeichnung:** **gemessen** = mit den Läufen unter `work/recomp/` ermittelt (M1 Pro, 16 GB, Last 11 bis 19 durch andere Prozesse, Fenster versteckt). *vermutet* = Schluss ohne Test. Keine Spielbytes, kein erzeugter Code, keine Shader und keine Bilder im Repo (Screenshots, Shader-Cache und Abzüge liegen unter `work/recomp/`).

## Ergebnis in Kürze

| | |
|---|---|
| **Gate 2** | **erreicht und übertroffen (Metal)**: Der Lauf mit Spielstand zeigt der Reihe nach (Screenshots, gesehen) den **Eröffnungsfilm** (VP8-WebM, „Pokémon Strahlender Diamant“-Logo auf blauem Funkelhintergrund), das **Titelbild** („Pokémon Strahlender Diamant“, „Drücke den A-Knopf“) und nach A die **3D-Stadt des Spielstands** (Spielfigur mit roter Mütze, NPC, Haus mit blauem Dach, Bäume, Schatten) – siehe Etappe 3. Ohne Spielstand erscheint die Sprachauswahl (Etappe 2). Bilder: `work/recomp/shots/gate2_film_metal.png`, `gate2_titel_metal.png`, `gate2_stadt_metal.png`, `gate2_sprachauswahl_metal.png` (nie im Repo). 40 bis 51 Bilder/s. |
| Blocker | keine für Gate 2. Offen: Wasser links im Stadtbild fehlt (weiß statt blau), Kamera 28 Pixel versetzt gegenüber Ryujinx (Zeitpunkt), Titeltext „Drücke den A-Knopf“ rot statt weiß *(vermutet: Farbanimation oder Fehler im Übersetzer)*, Speicherpuffer/Compute über den umhüllten Gastspeicher (Etappe 2). |
| RSS | 400 bis 1.100 MiB (Spitze 1.103 MiB nach 60 s), Metal-Puffer 5.069 MiB (aufgeteilt/nur Adressraum, Seiten werden lazy belegt) |
| Fehlende NVN-Funktionen | 495 von 524 vorhanden; von den 29 fehlenden sind 22 in der LAS-Schicht doch vorhanden (Zählfehler der Namensliste), 2 liefert die Glue-Schicht (`nvnBootstrapLoader`, `nvnDeviceGetProcAddress`), 7 Debug-Prüfpunkte sind wirkungslose Stummel. **Aus dem Lauf: 0 aufgerufene Funktionen ohne Host-Umsetzung.** |
| Shader | LAS-Übersetzer: **2.977 von 2.977** BDSP-Programmen scheitern mit „bindless tex“ (100 %). Unser Übersetzer (`shader_translator/`): **0 Fehler** in 5.959 angelegten Programmen, alle Metal-Kompilierungen erfolgreich. Gewählt: unser Übersetzer. |
| Gefunden und behoben (Kernel) | **zwei Fehler des Kernels aus Gate 1, die den echten Unity-Lauf nach Sekunden zum Stillstand brachten** (verlorener Weckruf, Selbstverklemmung nach Zeitablauf), siehe Abschnitt Kernel |

## Aufbau der Grafikschicht (`scripts/recomp/rt-bdsp/nvn/`)

| Datei | Inhalt |
|---|---|
| `prepare.sh` | **Kopiert** die LAS-Quellen `scripts/recomp/upstream/runtime/nvn` (MIT, vendort, unverändert) nach `work/recomp/nvn-src` (nichts davon liegt im Repo), legt die Ersatz-Header aus `shim/` daneben, ersetzt `maxwell/translate.c` und `shader.h` durch `shader_translator/` und wendet `las-nvn.patch` an. Nicht übernommen: Vulkan-Teil, `texpatch.c` (Zelda-Texturtabellen), `output_scale.c`, `smaa_data.c`, alle Spiel-Hooks. || `las-nvn.patch` | unsere Änderungen an den LAS-Quellen (14 Abschnitte, Liste unten) |
| `shim/` | Ersatz für `rt.h`, `hle.h`, `platform.h`, `kernel.h`, `paths.h`, `settings.h`, `ui/menu.h`, `texpatch.h` des Klons: nur das, was `objects.c`, `cmdbuf.c`, `renderer.m`, `metal.m` brauchen; Adressraum und Heap kommen aus der BDSP-Laufzeit |
| `nvn_glue.c` | `nvnBootstrapLoader`/`nvnDeviceGetProcAddress` (Funktionstabelle nach Namen), 9 gebundene Importe von `main` (nn::vi 5, nv 3), Hülle des Anwendungsspeichers für den Metal-Puffer, Ausgabegröße, 7 Prüfpunkt-Stummel, wirkungslose Stummel für die Spiel-Hooks des Klons (Breitbild, Zelda-Effekte, Menü, Eingabe, Neustart) |
| `build_nvn.sh` | baut die Objekte inkrementell (Apple-Clang für Objective-C: der Homebrew-LLVM erzeugt Klassen-Stubs, die der Apple-Linker nicht auflöst); `NVN_KEEP=1` verhindert das Neuanlegen der Kopie (Entwicklung) |

**Backend-Auswahl (`build.sh`, Umgebung `NVN_BACKEND`):** `metal` (macOS, Standard), `vulkan` (noch nicht umgesetzt, bricht mit Hinweis ab), `none` (keine Grafik, `-DBDSP_NVN_NONE`: der NVN-Treiber des SDK bleibt, Verhalten wie Gate 1; Standard unter Linux, Objekte unter `work/recomp/rt-bdsp-none`). Unter Linux nimmt `build.sh` automatisch `scripts/recomp/linux/compat` (Mach-Ersatz) dazu; die ELF-Abschnittstabelle für `HLE_FUNC` (`__start_hle_impls`) ist in `shim/hle.h`/`nvn_glue.c` vorbereitet. **Nicht auf dem Linux-Rechner getestet.**

Gemeinsame Schicht (backend-unabhängig im Entwurf): `objects.c` (Objekte, Builder, Pools), `cmdbuf.c` (Befehlsaufzeichnung im Gastspeicher), `tegra.c`/`formats.c`/`astc.c` (Block-Linear-Layout, Formate, ASTC-Decoder). Metal-spezifisch: `renderer.m` (Ausführung der Befehle, Pipelines, Rendertargets) und `metal.m` (Fenster, Texturen, Präsentation). Die Vulkan-Entsprechungen im Klon sind `vulkan/*.c` (siehe Abschnitt Vulkan-Pfad).

## Änderungen an der Laufzeit (`rt-bdsp/*.c`)

| Datei | Änderung |
|---|---|
| `main.c` | **Hauptthread gehört dem Fenster** (`ui_run`, SDL3/AppKit); die Überwachung (`monitor_loop`) läuft in einem Thread. Optionen: `--screenshot-after N` (Bild N und danach alle N Bilder nach `work/recomp/shots`, `BDSP_SHOT_DIR` ändert den Ordner), `--exit-after-shot`, `--headless` (Fenster nie sichtbar), `--window BxH`, `--no-window`, `--timeout S`. Gate-1-Stopp nur noch mit `BDSP_STOP_AT_GATE=1`. |
| `kernel.c` | **Fehler 1:** `WaitProcessWideKeyAtomic` setzte den Schlüssel *nach* dem Freigeben des Mutex; der SDK-Code ruft `Signal` nur bei Schlüssel ≠ 0 und liest ihn ohne Kernelsperre → verlorener Weckruf (Unity-Semaphoren, Hauptthread und Renderthread warten gegenseitig, 100 % der Läufe nach 1 bis 5 s). Jetzt Schlüssel zuerst. **Fehler 2:** nach **Zeitablauf** nahm der Kernel den Mutex zurück, der SDK-Code sperrt ihn aber selbst erneut → Selbstverklemmung beim ersten `TimedWait` (5 ms). Jetzt wie bei echtem Horizon: kein Zurücknehmen. Dazu: `kernel_phys_range` (Hülle der `MapPhysicalMemory`-Bereiche), Mitschrift der Synchronisations-SVCs (`BDSP_TRACE_SYNC=n`), Rückverfolgung je Thread (`BDSP_BT=1`). |
| `dispatch.c` | Aufrufzähler je Host-Funktion (`BDSP_NVN_STATS=1`), Ablauf der ersten n Aufrufe (`BDSP_TRACE_HLE=n`), Liste der Importe ohne Host-Umsetzung im Ergebnis, Funktionsring je Thread (`BDSP_FNPROF=1 BDSP_RINGDUMP=n`) |
| `services_audio.c` (neu) | **stumme** Audiodienste: `audout:u` (IAudioOut: Puffer werden in Echtzeit „abgespielt“ und zurückgegeben), `audren:u` (IAudioRenderer/IAudioDevice, leere Antworten), `hwopus` (Arbeitspuffergrößen, 0 Samples), `audin:u` (Fehler). Kein Ton. |
| `services.c` | `acc:u0` 131 (offene Nutzer), `ITimeZoneService` 202 |
| `services_net.c` | `bcat:u` meldet Erfolg (sonst bricht `nn::bcat::Initialize` ab) |
| `services_gfx.c` | `vi_vsync_handle` für die gebundene `GetDisplayVsyncEvent` (60 Hz) |

## Etappen

### Etappe 1: NVN-Schicht eingebunden, erstes Bild, Messung

Reihenfolge der gefundenen Hindernisse (jeweils mit Ursache):

| # | Symptom | Ursache | Behebung |
|---|---|---|---|
| 1 | `nvnBootstrapLoader` ohne Wirkung | HLE-Slots aus `mkimages.sh --hle-list` hatten keine Funktion | `nvn_glue_init` bindet die `HLE_FUNC`-Einträge an die Slots; Liste `hle_nvn.txt` jetzt mit 9 Namen (nvnBootstrapLoader, nn::vi::Initialize/OpenDefaultDisplay/CreateLayer/GetNativeWindow/GetDisplayVsyncEvent, nv::InitializeGraphics/SetGraphicsAllocator/SetGraphicsDevtoolsAllocator) |
| 2 | Abbruch `nn::audio::ListAudioOuts` | `audout:u` war Fehlerstub | stumme Audiodienste |
| 3 | Absturz `nvnCommandBufferBindProgram` (Programm `NULL`) | Unity löst mit NULL | `cmdbuf.c`: NULL erlaubt |
| 4 | Stillstand nach Sekunden | Kernel-Fehler 1 und 2 (oben) | `kernel.c` |
| 5 | Absturz `nvnMemoryPoolMap(0)` | `nvnTextureGetMemoryPool` lieferte 0 | Zeiger der Pool merken |
| 6 | Abbruch `nn::bcat`, Dauerschleife `GetReleasedAudioOutBuffer` (17 Mio. IPC) | Dienst-Stubs | `bcat:u`; Abfragen werden gebremst |
| 7 | alle Zeichenaufrufe übersprungen | Unity bindet **trennbare Programme** (ein `NVNprogram` je Stufe, Stufenmaske in `nvnCommandBufferBindProgram`), LAS bindet ein Programm mit allen Stufen | `renderer.m`: Stufenprogramme zu einem Programm zusammenführen |
| 8 | alles magenta (Fehler-Shader) | `nvnDeviceGetInteger(0x5e)` lieferte 0: Unity hält dann die meisten Shader für nicht unterstützt (2.654 statt 5.959 Programme, Rest „unsupported“, Fehler-Shader). Der Wert ist vermutlich die **GPU-Code-Version**; die Kontrollabschnitte der Shader tragen `1, 0x10` | Wert **16** (`BDSP_DEV94` ändert ihn): Unity legt nun 5.959 Programme an. 1 und 288 verhalten sich wie 16. |
| 9 | LAS-Übersetzer: „bindless tex“ für alle | Unity-Shader lesen Texturhandles bindlos (`TEX.B`) aus Konstantenpuffer 2 (Textur ab `0x568`, Sampler ab `0x168`, je 8 Byte) | **unser Übersetzer** statt des LAS-Übersetzers (hat TEX.B); `renderer.m`: Handle aus `nvnCommandBufferBindSeparateTexture` (Textur) und `BindSeparateSampler` (Sampler, neuer Befehl `CMD_BIND_SAMPLERS`), `no_rscale` gesetzt |
| 10 | Texturen schwarz („partial WriteTexels“, 1.232 Meldungen) | `nvnTextureWriteTexels` schrieb nur Stufe 0 ganzer Texturen | Stufe und Schicht aus der Sicht (`view`), beliebiger Ausschnitt per Lesen-Ändern-Schreiben |

**Messung, Lauf bis 280 s (`--headless`):** 35 Threads, 25 verschiedene SVCs, 1,1 Mio. SVCs je 60 s (Mehrheit Mutex/Condvar der Unity-Jobs), 30.855 IPC je 60 s (100 verschiedene (Dienst, Befehl), 4 mit Standardantwort: `IParentalControlService` 1, `ICommonStateGetter` 66, `acc:u0` 130, `IAudioController` 0), 0 Ausnahmen, 0 abgewickelte Rahmen, Gast-Logzeilen 0 (Release-Fassung). Bildrate 45 bis 47 fps, GPU-Zeit 40 bis 75 ms je 2 s (Metal: 7 Zeichenaufrufe, 3 bis 4 Durchgänge je Bild). Speicher: **RSS 400 MiB bis 1,1 GiB**, MapPhysicalMemory 1,2 GiB belegt von 3,14 GB.

**Letzte Gast-Zugriffe auf das RomFS (Reihenfolge):** `globalgamemanagers`, `resources.assets(.resS)`, `unity default resources`, `Dpr.bin`, `Dpr/masterdatas`, `Dpr/shaders`, Wwise-Bank `Delphis_Main.bnk` (+ `.wem`), `Dpr/scenes/title`, Schriften (`efigs`, `jpn`, `sch`, `kor`), `scriptableobjects/gamesettings`, `fieldui/main`, `Pokemon Database/pokemons/*pm0446*` (Munchlax). Danach keine neuen Zugriffe mehr.

**Bild:** Erste Bilder (Zeit 6 s) schwarz, dann magenta (Fehler-Shader, Schritt 8), seit Schritt 8 bis 10 schwarz. Debug-Abzug eines Bildes (Bild 1500, `BDSP_DEBUG_FRAME`): ein Rendertarget 1280x720 (das Spiel rendert in 1280x720 in ein 1920x1080-Fensterbild), 7 Zeichenaufrufe: ein Vollbild-Viereck (Modus 7, 4 Indizes) und 6 Netze (1.086, 48, 96, 54, 6 und 384 Indizes), die **einen 2048x2048-ASTC-Atlas** (Format `0x7d`, 1,4 bis 1,6 Mio. Byte ungleich null) und einen 1024x1024-Atlas samplen. Der Atlas ist nach dem Abzug **erkennbar** (Charakterauswahl-Bilder, Wolken- und Kristallhintergrund, UI-Felder); die Pipeline ASTC → Block-Linear → Metal → bindloses Sampling funktioniert also. Der Farbfaktor der Fragment-Konstanten (`fubo0`) ist bei diesen Aufrufen `[0 0 0 0]`: das Bild steht in einer Überblendung auf Schwarz.

### Etappe 2: Spielablauf sichtbar gemacht, Schwarzbild behoben, Spielstand, Eingabe

**Werkzeug: IL2CPP-Namen im Lauf.** `scripts/recomp/il2sym.py` liest `global-metadata.dat` (Version 24) und das Speicherbild des Hauptmoduls und schreibt `work/recomp/il2sym.tsv` (68.183 Methoden: Adresse, Name; nur Namen, keine Spielbytes im Repo). Mit `BDSP_IL2SYM=work/recomp/il2sym.tsv` meldet die Laufzeit **jede Spielmethode beim ersten Aufruf** (`[il2] <ms> t<Thread> <Name>`; erzwingt den Funktionseintrittshaken, daher etwas langsamer); `scripts/recomp/symres.py` versieht Gastadressen in Berichten (Absturz, `BDSP_RINGDUMP`) mit Namen. Damit ist der Spielablauf lesbar (gemessen, erster Start ohne Spielstand): `GameController..cctor` 0,7 s · `SaveSystem.Load/MountSaveData` 1,2 s · Asset-Manifest 1,3 bis 4,6 s · Wwise-Initialisierung und `LoadInitBank` 6,7 s · Stammdaten (`XLSXContent.*`) 7 bis 10,7 s · `nn.oe.Language.GetDesired` 10,75 s · Szenenwechsel 18,6 s · **`OpeningController.OpenSelectLanguage` 22,0 s**. Das Spiel hing also **nicht**: es wartete in der Sprachauswahl auf Eingabe (frühere Hypothesen Zeit/`audren`/Fence/Vsync sind damit erledigt; `GetSystemTick` und `cntvct` laufen mit 19,2 MHz).

**Schwarzbild (gemessen, Ursache gefunden).** Der Vulkan-Strang zeichnete dieselben 7 Zeichenaufrufe sichtbar, also lag der Fehler in der Metal-Ausführung, nicht in Gastlogik oder Konstantenpuffern. Die Zeichenaufrufe hatten gültige Vertices (weiße Vertexfarbe, 1280x720-Hintergrundviereck), Matrizen, Indizes und Viewport. Der „Farbfaktor 0“ aus Etappe 1 war ein Fehlschluss: `f0=[0 0 0 0]` ist `_TextureSampleAdd` des UI-Programms. Entscheidende Tests: (a) jeder Fragment-Ausgang auf Festfarbe (`BDSP_FS_RED`) → nur der erste Zeichenaufruf (ohne Indexpuffer) wurde sichtbar; (b) zusätzlich die Vertexposition aus `vertex_id` (`BDSP_VS_TEST`) → weiterhin nichts, also sahen die indizierten Zeichenaufrufe **keine gültigen Index-/Vertexdaten**; (c) Daten über den Ring kopieren (`BDSP_NO_GUEST_BUF`, jetzt Standard) → die Sprachauswahl erscheint vollständig. Ursache: der Gastspeicher ist als ein Metal-Puffer (5.069 MiB, `newBufferWithBytesNoCopy`) umhüllt, die Seiten sind beim Umhüllen noch nie beschrieben; die GPU sah dort nie die später vom Gast beschriebenen Seiten (*vermutet:* geteilte Nullseite, die beim ersten Schreiben per Copy-on-Write ersetzt wird; `UnmapPhysicalMemory` kommt im Lauf **nicht** vor, 0 Aufrufe in 30 s, es ist also nicht das Verwerfen von Seiten). Behoben in `fixes.patch`: Vertex- und Indexdaten gehen über den Ring; `BDSP_GUEST_BUF=1` schaltet den alten Pfad zurück. **Offen:** Speicherpuffer/Compute (`uses_gmem`, Compute-Skinning, Partikel) lesen weiter den umhüllten Puffer; dafür braucht es entweder vorab beschriebene Seiten oder einen Ringabzug mit Rückschreiben. Kosten des Ringpfads: RSS 1,5 GiB in der Sprachauswahl (vorher 0,4 bis 1,1 GiB); Bildrate 51 Bilder/s (gemessen, vorher 46).

**Bindlose Texturen.** `fixes.patch` tauscht Textur- und Sampler-Tabelle (Texturen ab `0x168`, Sampler ab `0x568`; Fund des Vulkan-Strangs, 847 von 3.592 Fragment-Programmen betroffen). Im Metal-Bild ist der Text der Sprachauswahl danach sauber („Select the language you would like to play in.“; vorher beim Vulkan-Strang zerhackte Glyphen).

**Bildbeschreibung (Screenshot, Frame 2.600, 1920x1080-Zielbild, gesehen):** oben links ein 1280x720-Ausschnitt (der Rest ist schwarz: `nvnWindowSetCrop` des Spiels erreicht die Präsentation nicht, Änderungswunsch 2 des Vulkan-Strangs, noch offen), darin hellblauer Kristallhintergrund, zwei Spalten mit je fünf Schaltflächen (links English [hervorgehoben, roter Rand], Español, Français, Deutsch, Italiano; rechts にほんご, 日本語, 한국어, 简体中文, 繁體中文), unten das Textfenster mit dem englischen Satz. Die Systemschrift (`nn::pl`) wird nicht gebraucht: Der Text kommt aus Schrift-Assets des Spiels (TextMeshPro-SDF-Atlas).

**Spielstand.** `scripts/recomp/rt-bdsp/install_save.sh` kopiert einen Ryujinx-Stand (Quelle: `BDSP_SAVE_SRC` = Ordner mit `SaveData.bin`/`Backup.bin`, optional `BDSP_SAVE_EXTRA` = Ordner mit `ExtraData0`; oder gleichnamige Zeilen in `work/local.env`) nach `work/recomp/save/save_1` (Kontotyp 1, wie das Attribut der Gast-Anfrage; Vorgänger wandert nach `backup-<Zeit>/`, nur Größen und Hashes werden ausgegeben) und schreibt die Benutzer-ID aus `ExtraData0` (Byte 8 bis 23) nach `work/recomp/save/user_id.hex`; `acc:u0` meldet diese ID (`user_id_load`). Option `--save <Ordner>` (Standard `work/recomp/save`). Das Spiel fragt `main2` und `SaveData.bin` ab (`[fs-save]`-Protokoll, `fsp-srv` 51/53, `IFileSystem` 7/8) und öffnet `SaveData.bin`. Erwarteter Hash des aktuellen Teststands: `SaveData.bin` 979.108 Byte, sha256 `0396a4a62735…` (geprüft: stimmt), `Backup.bin` `7a324b865ea9…`. **Ergebnis:** mit Spielstand entfällt `OpenSelectLanguage`, der Ablauf geht nach `Title.Start` (23,5 s). **Linux-Rechner:** dort kann dasselbe Skript laufen, mit `BDSP_SAVE_SRC` und `BDSP_SAVE_EXTRA` auf die Ordner einer Kopie des Ryujinx-Stands (Aufbau `Ryujinx/bis/user/save/0000000000000006/0/` und `Ryujinx/bis/user/save/0000000000000006/`), die der Nutzer dort bereitstellt; einen Übertragungsschritt gibt es nicht. Es braucht `shasum` und `xxd`; geschrieben wird nur nach `work/recomp/save`, nie in den Repo-Baum.

**Titelszene und Video.** `Title.PlayOpeningSequence` startet den Eröffnungsfilm (`Movie/<Sprache>/Opening/movie_*_op.webm`, VP9) über `SwitchVideoPlayer` (Stagefright/OMX des SDK, Hardwaredecoder über `nvdec`). Befund: Absturz (Signal 11) in `strcasecmp(…, NULL)` in `android::OMXCodec::findMatchingCodecs`, weil die Codec-Liste leer ist (kein OMX-Komponentenregister). Behelf: ein NULL-sicheres `strcasecmp` als HLE (`nvn_glue.c`, `hle_nvn.txt`): die Suche endet leer, der Lauf bleibt stabil (getestet 100 s). Danach ruft das Spiel jedes Bild `GetCurrentTime`/`GetVideoLength` und wartet auf das Filmende; das Bild bleibt schwarz. **Nächster Schritt dafür:** entweder die Zeitsteuerung des Videospielers durch den Host ersetzen (Filmende melden; die Unity-Funktionen haben keine Symbole, die Auflösung über die `icall`-Tabelle ist offen) oder einen Decoder bereitstellen (`mm:u`/`nvdec`-Ioctls, VP9 über FFmpeg/libvpx, nur Bild, kein Ton).

**Eingabe (`hid`).** Die SDK-Funktionen `nn::hid::GetNpadState`/`GetNpadStates` (je fünf Zustandstypen) und `GetNpadStyleSet` sind als HLE ersetzt (`nvn_glue.c`, Muster `runtime/hle/input.c` des Klons): Spieler 1 ist ein verbundener Pro Controller; Tastatur aus dem Fenster (Eingabe/Leertaste/K = A, Rücktaste/J = B, X, Y, Pfeile und WASD = Steuerkreuz, Q/E = L/R, P = Plus, O = Minus) und das Testskript `--input-script "Sekunde:TASTE[+TASTE]:Dauer,…"` (ab Prozessstart, z. B. `26:A:0.4,32:A+DOWN:0.2`; `BDSP_TRACE_INPUT=1` protokolliert). Gemessen: das Spiel liest die Taste (`Tasten 0x1`), in der Titelszene schaltet sie aber nicht weiter, solange der Film läuft.

**Debug-Haken und Patches.** `nvn/fixes.patch` (Ring statt umhülltem Gastspeicher, Textur-/Sampler-Tabelle; immer angewandt) und `nvn/debug.patch` (nur mit `NVN_DEBUG=1 prepare.sh`): `BDSP_FS_RED` (Festfarbe je Fragmentprogramm; UI grün, sonst rot), `BDSP_VS_TEST` (Position aus `vertex_id`), `BDSP_DUMP_VUBO` (mit `BDSP_DEBUG_FRAME=N`: Rendertarget, Viewport, Konstantenpuffer je Aufruf), `BDSP_DUMP_IDX` (erste Indizes). Laufzeit: `BDSP_IL2SYM`, `BDSP_TRACE_UNMAP`, `BDSP_TRACE_INPUT`, `[fs-save]`.

**Messung (M1 Pro, 16 GB, Fenster versteckt):** Sprachauswahl (ohne Spielstand): Ladezeit bis zum Bild etwa 22 s, 2.791 Bilder in 58 s, 51 Bilder/s, 7 Zeichenaufrufe und 309 Durchgänge je 2 s, RSS 1.500 MiB (Spitze 1.537), 37.362 IPC-Anfragen, 1.612 RomFS-Lesezugriffe (148 MiB), 0 NVN-Funktionen ohne Host-Umsetzung. Titelszene (mit Spielstand): Titel nach 23,5 s, 4.337 Bilder in 100 s, 51 Bilder/s, RSS-Spitze 793 MiB, 1.668 RomFS-Lesezugriffe (160 MiB).

**Hinweis:** Der Abschnitt „Titelszene und Video“ oben beschreibt den Stand vor Etappe 3 (Behelf `strcasecmp`); der Film läuft jetzt über `movie_glue.c`.

### Etappe 3: Film, Titel, Spielstand laden, Stadt

**Film (`nvn/movie_glue.c`, neu).** Der Unity-`SwitchVideoPlayer` benutzt die Android-artige Schnittstelle `movie::` (nnMedia: `Extractor`, `Decoder`, `MediaData`, `Buffer`; 23 Importe, die das SDK mit Stagefright/OMX und dem Hardware-Decoder bedient). `movie_glue.c` ersetzt sie durch FFmpeg (Entwurf und Teile nach `runtime/hle/movie.c` des LAS-Klons, MIT, für BDSP angepasst, NOTICE.md gilt): `Extractor` öffnet `rom:/Data/StreamingAssets/Movie/<Sprache>/Opening/*.webm` aus dem RomFS-Ordner, bietet **nur die Videospur** an (kein Ton), `Decoder` liefert NV12 (VP8, 1280x720, 30 Bilder/s; Eröffnungsfilm `movie_*_op.webm` und Titelschleife `movie_*_op_loop.webm`). Befunde dabei (gemessen): (a) Das Spiel ruft `SetDataSource` **auch über Vtable-Slot 2** (Pfad in x1), nicht nur direkt; (b) der Spieler stellt die Ausgabepuffer selbst bereit (`Buffer::SetDataAndCapacity`, Speicher im Gastpool) und liest das Bild **von dort** (`nvnCommandBufferCopyBufferToTexture`, R8 1280x720 und RG8 640x360): `GetOutputBuffer` muss also **in den Puffer des Spielers schreiben**, nicht einen eigenen Puffer zurückgeben (zuerst: grüne Fläche, weil alles null war). `hle_nvn.txt` bindet die 23 `movie::`-Namen an die Host-Funktionen (`mkimages.sh` mit `HLE_LIST`). Bau: FFmpeg über `pkg-config` (Homebrew; `BDSP_NO_MOVIE=1` baut ohne). Linux/Vulkan: dieselbe Datei, FFmpeg-Entwicklungspakete (`ffmpeg-free-devel`) nötig *(noch nicht gebaut)*. Der frühere Behelf `strcasecmp` bleibt eingetragen, wird aber nicht mehr erreicht.

**Ablauf (Lauf mit Spielstand, Eingabeskript `--input-script "75:A:0.4,85:A:0.4,95:A:0.4,105:A:0.4"`, gemessen):** Titelszene nach 20 bis 23 s, Eröffnungsfilm, Titelbild („Drücke den A-Knopf“) nach dem Film (Frame 2.400 im Lauf ohne Skript), mit A **Spielstand laden** (`PlayerWork`/`FieldPlayerEntity`, `EvDataManager`, `KinomiResources` im Protokoll) und Feldszene mit der **Stadt des Spielstands** nach etwa 100 s. Lauf bis 150 s stabil (kein Absturz, 39 Threads, 4.306 Bilder, RSS-Spitze 1.041 MiB, 2.695 RomFS-Lesezugriffe/229 MiB, 1,7 Mio. SVC-Aufrufe, per `MapPhysicalMemory` 1.704 MiB, 44 Bilder/s in der Stadt, 40.320 Zeichenaufrufe und 720 Compute-Dispatches je 2 s ⇒ **Compute-Skinning/Partikel laufen jetzt**, 0 Zeichenaufrufe übersprungen).

**Wiederholung mit sauberem Bau (Lauf 12, ohne `NVN_KEEP`, Skript `62:A:0.4,72:A:0.4,82:A:0.4,92:A:0.4`, gemessen):** `SaveSystem.Load` 1,1 s · `Title.Start`/`PlayOpeningSequence` 21,9 s · erster A-Druck 62 s · `EvDataManager.EnvironmentControllerCallBack` (Feldaufbau) 75,0 s · `FieldPlayerEntity.CheckSwim` (Spieler im Feld) 91,1 s · gleiches Stadtbild (Frame 3.600, 45 Bilder/s, 45.864 Zeichenaufrufe und 819 Dispatches je 2 s). Ladezeit bis zum Titel also etwa 22 s, bis zur Stadt etwa 29 s nach dem A-Druck.

**Bildbeschreibung Stadt (Screenshot Frame 4.200, 1280x720, gesehen):** Aufsicht auf eine gepflasterte Straße in Lila-/Graublau mit Fischgrätmuster und weichen Schatten; links ein kleines Haus mit blauem Dach und türkisfarbener Tür, davor drei Büsche in weißen Kübeln; in der Mitte die Spielfigur (rote Mütze) und rechts daneben ein Mann mit braunem Haar; rechts Reihen von Nadelbäumen; oben mittig ein Gebäude mit rotem Dach (Pokécenter-artig); links oben Holzgerüst. **Vergleich mit der Ryujinx-Referenz** (`work/visual/ref/ryujinx/views/ref_01_feld_weiter.png`, gleiche Szene, F8-Bild des Nutzers; eigene Rechnung mit numpy, kein `visual_compare`-Lauf, da dessen `ref compare` Unity-Bilder erwartet): Kamera **28 Pixel nach rechts versetzt** (Zeitpunkt der Kamerafahrt); mittlerer Farbwert recomp (109,7 / 122,1 / 120,0) gegen Referenz (106,2 / 120,0 / 118,3), nach Verschiebung mittlere absolute Abweichung 16,5 / 17,1 / 15,2 je Kanal (R, G, B) und 19,8 % der Pixel mit Abweichung über 40 (Kanten, Schatten, Verschiebung ungenau); Farben, Schatten, Figuren und Modelle stimmen sonst überein. **Abweichungen:** das **Wasser links** (blau in der Referenz) ist im Recomp-Bild weiß; der rote Text „Drücke den A-Knopf“ im Titelbild ist in der Referenz nicht geprüft.

**FPU-Umgebung (`ap-recomp-diff`):** `rt_fp_guest_mode()` (`scripts/recomp/c_exact/fp_env.h`) am Anfang jedes Gast-Threads (`kernel.c`, `thread_main`) und nach jedem SVC (`rt_svc`): auf arm64 FPCR = 0 (RN, FZ = 0, DN = 0).

**Plattformübergreifend:** die vier `#include`-Zeilen (`SDL3/SDL.h`, `stdatomic.h`, `string.h`, `strings.h`) stehen in `nvn_glue.c` nicht mehr im `__APPLE__`-Block (Wunsch aus `docs/recomp-vulkan.md`). `nvnWindowSetCrop` erreicht die Metal-Präsentation (`fixes.patch`: Screenshot jetzt 1280x720 statt 1920x1080 mit schwarzem Rand); `nvn_window_crop()` in `objects.c` steht auch dem Vulkan-Pfad zur Verfügung.

## Shader-Wahl: Messung

| | LAS-Übersetzer (`runtime/nvn/maxwell/translate.c`) | unser Übersetzer (`shader_translator/translate.c`) |
|---|---|---|
| Programme im Lauf (mit `nvnDeviceGetInteger(0x5e)` = 16) | 2.977 angefordert, **2.977 Fehler** („bindless tex“: 2.941 Fragment, 36 Vertex) | 5.959 angelegt, **0 Fehler** bei Übersetzung und bei der Metal-Kompilierung (kein „pipeline failed“) |
| Abdeckung am Korpus (`docs/shader-translator.md`) | nicht gemessen (scheitert am ersten TEX.B) | 13.710 von 13.710 Programmen erkannt (100 %), Treue-Test 500 Paare |
| Fehlende Opcodes/Features laut Korpusmessung | TEX.B, HSETP2 (cbuf/imm) | keine; offen: STG/zweiter Storage-Puffer, 64-Bit-Ganzzahlen, Subgroup-Befehle, Compute (nicht gebraucht bis jetzt) |

Ein Schalter für den LAS-Übersetzer ist nicht vorgesehen: seine Spezialisierung auf Zelda (feste Texturbindungen) passt nicht zu Unity. Gemessen ist der Weg zum Bild, **nicht die Pixeltreue gegen unsere Referenzen im Gastlauf** (Treue-Test: `scripts/shader_fidelity.py`, offline).

**Compute-Skinning (5 Programme), Instancing, MRT, Partikel-Speicherpuffer:** im bisherigen Lauf **nicht erreicht** (0 `nvnCommandBufferDispatchCompute`, kein MRT-Durchgang): offen, erst mit weiterem Spielfortschritt messbar.

## Offene Punkte (Reihenfolge)

1. **Titelfilm** (siehe Etappe 2): Videospieler durch den Host ersetzen (Filmende/Zeit) oder Decoder; danach Titelbild („Drücke A“) und Weiterschalten per A.
1b. **Ausschnitt/Zielgröße:** das Spiel rendert 1280x720 in ein 1920x1080-Fensterbild und ruft `nvnWindowSetCrop`; der Ausschnitt erreicht die Präsentation nicht (Bild oben links, Rest schwarz). In beiden Backends aus `WIN->crop` in die Präsentation einspeisen.
1c. **Umhüllter Gastspeicher** für Speicherpuffer/Compute (siehe Etappe 2).
1d. `rt_fp_guest_mode()` (`scripts/recomp/c_exact/fp_env.h`, Hinweis von `ap-recomp-diff`: FTZ/DAZ aus, Rundung RN, FPCR 0) am Anfang jedes Gast-Threads und nach Host-Aufrufen *(noch nicht eingebaut)*.
2. `audren:u`-Abnahme (Rechenzeit/Antworten) erst, wenn der Gast es anfragt (bisher: nur `audout:u` wird bedient, 0 Tonausgabe).
3. Frame-Pacing: bisher 60-Hz-Vsync-Ereignis aus einem Host-Thread (`services_gfx.c`), `PresentInterval` des Fensters wird nicht ausgewertet; echte Kopplung an das Metal-Display fehlt.
4. Eingabe: Tastatur/Skript vorhanden (Etappe 2); Controller über GameController/SDL und Sticks fehlen.
5. Speicherabbild B (iPad, 4 GiB): offen (siehe Gate 1); der Metal-Puffer deckt den gesamten Bereich der `MapPhysicalMemory`-Abbildungen (5,07 GiB Adressraum) ab, das ist unter Variante B **nicht** möglich.

## Vulkan-Pfad (Linux/Windows), Stand der Vorbereitung

| Punkt | Stand |
|---|---|
| Quellen | LAS: `runtime/nvn/vulkan` (6.019 Zeilen: `device.c` 709, `exec.c` 3.789, `shaders.c` 454, `textures.c` 858, `vma.cpp`, `vk.h`, `imgui_glue.cpp`), `runtime/platform/linux.c`, `docs/linux.md` (x86-64, Vulkan 1.3, AVX2; clang, SDL3, FFmpeg, shaderc, VMA) |
| Gemeinsame Schicht | `objects.c`, `cmdbuf.c`, `tegra.c`, `astc.c`, `formats.c` sind backend-frei und wären für Vulkan unverändert wiederverwendbar; `renderer.m`/`metal.m` sind Metal-spezifisch und müssten durch `vulkan/*.c` ersetzt werden |
| Shader-Weg | **Unterschied:** Der LAS-Vulkan-Weg übersetzt Maxwell **über denselben Übersetzer in GLSL** (`key->glsl`, Beiwerk `glsl_rewrite()` formt den MSL-Rumpf zu GLSL um) und kompiliert mit **shaderc zu SPIR-V zur Laufzeit** (Plattenpuffer `cache/spirv`). Unser Übersetzer hat den GLSL-Zweig **ungetestet und für TEX.B nicht umgesetzt** (`docs/shader-translator.md` Abschnitt 3.6); stattdessen hat er einen HLSL-Zweig (`key->hlsl`, für den Unity-Wrapper, ohne Compute). Für Vulkan gibt es drei Wege: (A) GLSL-Zweig um TEX.B ergänzen, shaderc wie LAS; (B) HLSL-Zweig → DXC/glslang → SPIR-V (offline möglich: 13.710 Programme, 2.859 Codes); (C) MSL → SPIRV-Cross (nicht verfügbar). **Empfehlung (A)**, weil die Zeichenschicht von LAS GLSL-Bindungen erwartet (Vertrag in `shader.h`); Aufwand *vermutet* 1 bis 2 Wochen (TEX.B/bindlos in GLSL: Textur-Array oder Descriptor-Indexing, Treue-Test auf Vulkan). |
| Build | `NVN_BACKEND=vulkan` ist angelegt, aber nicht umgesetzt; `prepare.sh` kopiert den Vulkan-Teil bewusst noch nicht |
| Fehlt | Fensterschleife (SDL3, Vulkan-Surface), `renderer`-Entsprechung für die Befehle `CMD_BIND_SAMPLERS`/getrennte Texturen und trennbare Programme (beides stand in `renderer.m`, nicht in `exec.c`), 16-KiB/4-KiB-Seitengröße (macOS 16 KiB: `plat_*`), Linux-Mach-Ersatz in `kernel.c` (Anhalten per Signal; vorhanden unter `scripts/recomp/linux/compat`) |

**Pakete für den Linux-Rechner, vom Nutzer zu installieren (kein sudo für den Agenten):** `vulkan-headers`, `SDL3-devel`, `ffmpeg-free-devel` (nur LAS-Video; für BDSP nicht nötig), `shaderc-devel`, `VulkanMemoryAllocator-devel`. Vorhanden laut Auftrag: Vulkan-Loader, `vulkan-tools`, RTX 2080 Ti. Ohne diese Pakete ist `NVN_BACKEND=none` baubar (Gate-1-Verhalten).

## Änderungen an den LAS-Quellen (`las-nvn.patch`, `fixes.patch`, `debug.patch`)

`fixes.patch` (nach `las-nvn.patch`): Vertex-/Indexdaten über den Ring, Textur-/Sampler-Tabelle der bindlosen Handles; `debug.patch`: Debug-Haken (nur mit `NVN_DEBUG=1`). `las-nvn.patch` enthält:
`cmdbuf.c`: NULL-Programm, getrennte Sampler aufzeichnen · `metal.m`: Speicherbereich aus der Kernelschicht, Screenshot-Ordner, Fenstertitel · `nvn.h`: Pool-Zeiger der Textur, Befehl `CMD_BIND_SAMPLERS` · `objects.c`: `nvnDeviceGetInteger(0x5e)`, `nvnTextureGetMemoryPool`, `nvnTextureWriteTexels` (Stufe/Schicht aus der Sicht, Ausschnitte) · `renderer.m`: trennbare Programme, bindlose Texturen (`shader_handle`), Sampler-Zustand, Debug-Haken des Übersetzers, Shader-Cache nach `work/recomp/cache/shaders` (LAS schrieb nach `cache/` im Arbeitsordner: **nie im Repo ablegen**), Tint des Klons deaktiviert, `no_rscale`. Der Patch lässt sich aus dem Klon frisch anwenden und ergibt dieselbe Kopie wie der Arbeitsstand (geprüft mit `diff -r`).

## Reproduktion

```
scripts/recomp/rt-bdsp/nvn/prepare.sh                         # LAS-Quellen + Patch + Übersetzer nach work/recomp/nvn-src
IMG=work/recomp/img_gfx HLE_LIST=scripts/recomp/rt-bdsp/hle_nvn.txt scripts/recomp/rt-bdsp/mkimages.sh
scripts/recomp/rt-bdsp/build.sh                               # Backend metal (macOS); NVN_BACKEND=none für Gate-1-Verhalten
BDSP_IMG=work/recomp/img_gfx work/recomp/bdsp_boot --headless --timeout 120 --screenshot-after 600
# Etappe 2: Bilder mit Namen, Spielstand, Eingabe (Bilder nach work/recomp/shots)
python3 -I scripts/recomp/il2sym.py                                                       # work/recomp/il2sym.tsv
BDSP_SAVE_SRC=<Ryujinx>/bis/user/save/<id>/0 BDSP_SAVE_EXTRA=<Ryujinx>/bis/user/save/<id> scripts/recomp/rt-bdsp/install_save.sh
IMG=work/recomp/img_gfx2 HLE_LIST=scripts/recomp/rt-bdsp/hle_nvn.txt scripts/recomp/rt-bdsp/mkimages.sh
BDSP_IL2SYM=work/recomp/il2sym.tsv BDSP_IMG=work/recomp/img_gfx2 work/recomp/bdsp_boot --headless --timeout 100 --save work/recomp/save --input-script "26:A:0.4" --screenshot-after 1500
# NVN_DEBUG=1 scripts/recomp/rt-bdsp/nvn/prepare.sh  (Debug-Haken aus debug.patch)
# Diagnose: BDSP_NVN_STATS=1 BDSP_BT=1 BDSP_TRACE_SYNC=3000 BDSP_TRACE_HLE=5000 BDSP_TRACE_IPC=1 BDSP_LOG_FILES=1 BDSP_DEV94=16
```

Lizenz: `scripts/recomp/rt-bdsp/NOTICE.md` (Abschnitt „NVN-Schicht“), Lizenztext `LICENSE-LASRecomp`.
