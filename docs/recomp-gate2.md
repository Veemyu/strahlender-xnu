# Rekompilation, Gate 2 „Grafik“ (`ap-recomp` Gate 2)

Stand: 2026-10-19, Zwischenstand (wird je Etappe fortgeschrieben). Grundlage: `docs/recomp-gate1.md` (Gate 1 erreicht), `docs/recomp-machbarkeit.md`, `docs/shader-translator.md`, `docs/referenz-las-shader.md`. Auftrag: Das Spiel soll im rekompilierten Betrieb ein erstes Bild über Metal zeichnen (macOS arm64, **ohne Ton**); Kriterium: ein nicht-schwarzes, erkennbares Bild des Startbildschirms im Screenshot.

**Kennzeichnung:** **gemessen** = mit den Läufen unter `work/recomp/` ermittelt (M1 Pro, 16 GB, Last 11 bis 19 durch andere Prozesse, Fenster versteckt). *vermutet* = Schluss ohne Test. Keine Spielbytes, kein erzeugter Code, keine Shader und keine Bilder im Repo (Screenshots, Shader-Cache und Abzüge liegen unter `work/recomp/`).

## Ergebnis in Kürze

| | |
|---|---|
| **Gate 2** | **noch nicht erreicht** (Kriterium: erkennbares Titelbild). Erreicht ist: der rekompilierte Gast läuft **dauerhaft** (getestet bis 280 s, 35 Threads) und **zeichnet über Metal**: **46 Bilder/s** (45 bis 47, Fenster versteckt, 1920x1080-Zielbild), **2.788 Bilder in 60 s**, 5.959 NVN-Programme angelegt, übersetzt und kompiliert, 1.616 RomFS-Lesezugriffe (148 MiB), **echte Spielinhalte werden geladen und gesampelt** (ASTC-Atlas der Charakterauswahl, korrekt entpackt, siehe unten). Das ausgegebene Bild ist **schwarz**: alle 7 Zeichenaufrufe je Bild sind UI-Elemente mit Farbfaktor 0 (Überblendung). |
| Blocker | Der Gast bleibt in einer Ladephase mit Überblendung auf Schwarz; warum er nicht weiter in Titel/Logo schaltet, ist **offen** (Abschnitt „Offene Punkte“). |
| RSS | 400 bis 1.100 MiB (Spitze 1.103 MiB nach 60 s), Metal-Puffer 5.069 MiB (aufgeteilt/nur Adressraum, Seiten werden lazy belegt) |
| Fehlende NVN-Funktionen | 495 von 524 vorhanden; von den 29 fehlenden sind 22 in der LAS-Schicht doch vorhanden (Zählfehler der Namensliste), 2 liefert die Glue-Schicht (`nvnBootstrapLoader`, `nvnDeviceGetProcAddress`), 7 Debug-Prüfpunkte sind wirkungslose Stummel. **Aus dem Lauf: 0 aufgerufene Funktionen ohne Host-Umsetzung.** |
| Shader | LAS-Übersetzer: **2.977 von 2.977** BDSP-Programmen scheitern mit „bindless tex“ (100 %). Unser Übersetzer (`shader_translator/`): **0 Fehler** in 5.959 angelegten Programmen, alle Metal-Kompilierungen erfolgreich. Gewählt: unser Übersetzer. |
| Gefunden und behoben (Kernel) | **zwei Fehler des Kernels aus Gate 1, die den echten Unity-Lauf nach Sekunden zum Stillstand brachten** (verlorener Weckruf, Selbstverklemmung nach Zeitablauf), siehe Abschnitt Kernel |

## Aufbau der Grafikschicht (`scripts/recomp/rt-bdsp/nvn/`)

| Datei | Inhalt |
|---|---|
| `prepare.sh` | **Kopiert** die LAS-Quellen `research/LASRecomp/runtime/nvn` (MIT, `research/` bleibt unverändert) nach `work/recomp/nvn-src` (nichts davon liegt im Repo), legt die Ersatz-Header aus `shim/` daneben, ersetzt `maxwell/translate.c` und `shader.h` durch `shader_translator/` und wendet `las-nvn.patch` an. Nicht übernommen: Vulkan-Teil, `texpatch.c` (Zelda-Texturtabellen), `output_scale.c`, `smaa_data.c`, alle Spiel-Hooks. |
| `las-nvn.patch` | unsere Änderungen an den LAS-Quellen (14 Abschnitte, Liste unten) |
| `shim/` | Ersatz für `rt.h`, `hle.h`, `platform.h`, `kernel.h`, `paths.h`, `settings.h`, `ui/menu.h`, `texpatch.h` des Klons: nur das, was `objects.c`, `cmdbuf.c`, `renderer.m`, `metal.m` brauchen; Adressraum und Heap kommen aus der BDSP-Laufzeit |
| `nvn_glue.c` | `nvnBootstrapLoader`/`nvnDeviceGetProcAddress` (Funktionstabelle nach Namen), 9 gebundene Importe von `main` (nn::vi 5, nv 3), Hülle des Anwendungsspeichers für den Metal-Puffer, Ausgabegröße, 7 Prüfpunkt-Stummel, wirkungslose Stummel für die Spiel-Hooks des Klons (Breitbild, Zelda-Effekte, Menü, Eingabe, Neustart) |
| `build_nvn.sh` | baut die Objekte inkrementell (Apple-Clang für Objective-C: der Homebrew-LLVM erzeugt Klassen-Stubs, die der Apple-Linker nicht auflöst); `NVN_KEEP=1` verhindert das Neuanlegen der Kopie (Entwicklung) |

**Backend-Auswahl (`build.sh`, Umgebung `NVN_BACKEND`):** `metal` (macOS, Standard), `vulkan` (noch nicht umgesetzt, bricht mit Hinweis ab), `none` (keine Grafik, `-DBDSP_NVN_NONE`: der NVN-Treiber des SDK bleibt, Verhalten wie Gate 1; Standard unter Linux, Objekte unter `work/recomp/rt-bdsp-none`). Unter Linux nimmt `build.sh` automatisch `scripts/recomp/ryzen/compat` (Mach-Ersatz) dazu; die ELF-Abschnittstabelle für `HLE_FUNC` (`__start_hle_impls`) ist in `shim/hle.h`/`nvn_glue.c` vorbereitet. **Nicht auf dem Ryzen getestet.**

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

**Bild:** Erste Bilder (Zeit 6 s) schwarz, dann magenta (Fehler-Shader, Schritt 8), seit Schritt 8 bis 10 schwarz. Debug-Abzug eines Bildes (Bild 1500, `LARECOMP_DEBUG_FRAME`): ein Rendertarget 1280x720 (das Spiel rendert in 1280x720 in ein 1920x1080-Fensterbild), 7 Zeichenaufrufe: ein Vollbild-Viereck (Modus 7, 4 Indizes) und 6 Netze (1.086, 48, 96, 54, 6 und 384 Indizes), die **einen 2048x2048-ASTC-Atlas** (Format `0x7d`, 1,4 bis 1,6 Mio. Byte ungleich null) und einen 1024x1024-Atlas samplen. Der Atlas ist nach dem Abzug **erkennbar** (Charakterauswahl-Bilder, Wolken- und Kristallhintergrund, UI-Felder); die Pipeline ASTC → Block-Linear → Metal → bindloses Sampling funktioniert also. Der Farbfaktor der Fragment-Konstanten (`fubo0`) ist bei diesen Aufrufen `[0 0 0 0]`: das Bild steht in einer Überblendung auf Schwarz.

## Shader-Wahl: Messung

| | LAS-Übersetzer (`runtime/nvn/maxwell/translate.c`) | unser Übersetzer (`shader_translator/translate.c`) |
|---|---|---|
| Programme im Lauf (mit `nvnDeviceGetInteger(0x5e)` = 16) | 2.977 angefordert, **2.977 Fehler** („bindless tex“: 2.941 Fragment, 36 Vertex) | 5.959 angelegt, **0 Fehler** bei Übersetzung und bei der Metal-Kompilierung (kein „pipeline failed“) |
| Abdeckung am Korpus (`docs/shader-translator.md`) | nicht gemessen (scheitert am ersten TEX.B) | 13.710 von 13.710 Programmen erkannt (100 %), Treue-Test 500 Paare |
| Fehlende Opcodes/Features laut Korpusmessung | TEX.B, HSETP2 (cbuf/imm) | keine; offen: STG/zweiter Storage-Puffer, 64-Bit-Ganzzahlen, Subgroup-Befehle, Compute (nicht gebraucht bis jetzt) |

Ein Schalter für den LAS-Übersetzer ist nicht vorgesehen: seine Spezialisierung auf Zelda (feste Texturbindungen) passt nicht zu Unity. Gemessen ist der Weg zum Bild, **nicht die Pixeltreue gegen unsere Referenzen im Gastlauf** (Treue-Test: `scripts/shader_fidelity.py`, offline).

**Compute-Skinning (5 Programme), Instancing, MRT, Partikel-Speicherpuffer:** im bisherigen Lauf **nicht erreicht** (0 `nvnCommandBufferDispatchCompute`, kein MRT-Durchgang): offen, erst mit weiterem Spielfortschritt messbar.

## Offene Punkte (Reihenfolge)

1. **Warum bleibt die Überblendung bei Schwarz?** Hypothesen: (a) Zeit: Unity berechnet `deltaTime` aus `GetSystemTick`/`cntvct`; wenn die Übersetzung des Zählers oder die Frequenz falsch ist, laufen Überblendungen nicht ab *(zu prüfen)*; (b) Eingabe: `hid` meldet keinen Zustand (kein Controller), der Gast wartet evtl. auf eine Taste *(vermutet)*; (c) Wwise wartet auf den Audiopfad (Bank geladen, `audout` in Echtzeit bedient, `audren:u` nie angefragt) *(vermutet)*. Je Hypothese ein Experiment (je ≤ 10 Minuten) steht im nächsten Zwischenstand.
2. `audren:u`-Abnahme (Rechenzeit/Antworten) erst, wenn der Gast es anfragt.
3. Frame-Pacing: bisher 60-Hz-Vsync-Ereignis aus einem Host-Thread (`services_gfx.c`), `PresentInterval` des Fensters wird nicht ausgewertet; echte Kopplung an das Metal-Display fehlt.
4. Eingabe (`hid`): der Dienst meldet nur Verbindungen, kein Eingabezustand.
5. Speicherabbild B (iPad, 4 GiB): offen (siehe Gate 1); der Metal-Puffer deckt den gesamten Bereich der `MapPhysicalMemory`-Abbildungen (5,07 GiB Adressraum) ab, das ist unter Variante B **nicht** möglich.

## Vulkan-Pfad (Linux/Windows), Stand der Vorbereitung

| Punkt | Stand |
|---|---|
| Quellen | LAS: `runtime/nvn/vulkan` (6.019 Zeilen: `device.c` 709, `exec.c` 3.789, `shaders.c` 454, `textures.c` 858, `vma.cpp`, `vk.h`, `imgui_glue.cpp`), `runtime/platform/linux.c`, `docs/linux.md` (x86-64, Vulkan 1.3, AVX2; clang, SDL3, FFmpeg, shaderc, VMA) |
| Gemeinsame Schicht | `objects.c`, `cmdbuf.c`, `tegra.c`, `astc.c`, `formats.c` sind backend-frei und wären für Vulkan unverändert wiederverwendbar; `renderer.m`/`metal.m` sind Metal-spezifisch und müssten durch `vulkan/*.c` ersetzt werden |
| Shader-Weg | **Unterschied:** Der LAS-Vulkan-Weg übersetzt Maxwell **über denselben Übersetzer in GLSL** (`key->glsl`, Beiwerk `glsl_rewrite()` formt den MSL-Rumpf zu GLSL um) und kompiliert mit **shaderc zu SPIR-V zur Laufzeit** (Plattenpuffer `cache/spirv`). Unser Übersetzer hat den GLSL-Zweig **ungetestet und für TEX.B nicht umgesetzt** (`docs/shader-translator.md` Abschnitt 3.6); stattdessen hat er einen HLSL-Zweig (`key->hlsl`, für den Unity-Wrapper, ohne Compute). Für Vulkan gibt es drei Wege: (A) GLSL-Zweig um TEX.B ergänzen, shaderc wie LAS; (B) HLSL-Zweig → DXC/glslang → SPIR-V (offline möglich: 13.710 Programme, 2.859 Codes); (C) MSL → SPIRV-Cross (nicht verfügbar). **Empfehlung (A)**, weil die Zeichenschicht von LAS GLSL-Bindungen erwartet (Vertrag in `shader.h`); Aufwand *vermutet* 1 bis 2 Wochen (TEX.B/bindlos in GLSL: Textur-Array oder Descriptor-Indexing, Treue-Test auf Vulkan). |
| Build | `NVN_BACKEND=vulkan` ist angelegt, aber nicht umgesetzt; `prepare.sh` kopiert den Vulkan-Teil bewusst noch nicht |
| Fehlt | Fensterschleife (SDL3, Vulkan-Surface), `renderer`-Entsprechung für die Befehle `CMD_BIND_SAMPLERS`/getrennte Texturen und trennbare Programme (beides stand in `renderer.m`, nicht in `exec.c`), 16-KiB/4-KiB-Seitengröße (macOS 16 KiB: `plat_*`), Linux-Mach-Ersatz in `kernel.c` (Anhalten per Signal; vorhanden unter `scripts/recomp/ryzen/compat`) |

**Pakete auf dem Ryzen (`nobara`), vom Nutzer zu installieren (kein sudo für den Agenten):** `vulkan-headers`, `SDL3-devel`, `ffmpeg-free-devel` (nur LAS-Video; für BDSP nicht nötig), `shaderc-devel`, `VulkanMemoryAllocator-devel`. Vorhanden laut Auftrag: Vulkan-Loader, `vulkan-tools`, RTX 2080 Ti. Ohne diese Pakete ist `NVN_BACKEND=none` baubar (Gate-1-Verhalten).

## Änderungen an den LAS-Quellen (`las-nvn.patch`)

`cmdbuf.c`: NULL-Programm, getrennte Sampler aufzeichnen · `metal.m`: Speicherbereich aus der Kernelschicht, Screenshot-Ordner, Fenstertitel · `nvn.h`: Pool-Zeiger der Textur, Befehl `CMD_BIND_SAMPLERS` · `objects.c`: `nvnDeviceGetInteger(0x5e)`, `nvnTextureGetMemoryPool`, `nvnTextureWriteTexels` (Stufe/Schicht aus der Sicht, Ausschnitte) · `renderer.m`: trennbare Programme, bindlose Texturen (`shader_handle`), Sampler-Zustand, Debug-Haken des Übersetzers, Shader-Cache nach `work/recomp/cache/shaders` (LAS schrieb nach `cache/` im Arbeitsordner: **nie im Repo ablegen**), Tint des Klons deaktiviert, `no_rscale`. Der Patch lässt sich aus dem Klon frisch anwenden und ergibt dieselbe Kopie wie der Arbeitsstand (geprüft mit `diff -r`).

## Reproduktion

```
scripts/recomp/rt-bdsp/nvn/prepare.sh                         # LAS-Quellen + Patch + Übersetzer nach work/recomp/nvn-src
IMG=work/recomp/img_gfx HLE_LIST=scripts/recomp/rt-bdsp/hle_nvn.txt scripts/recomp/rt-bdsp/mkimages.sh
scripts/recomp/rt-bdsp/build.sh                               # Backend metal (macOS); NVN_BACKEND=none für Gate-1-Verhalten
BDSP_IMG=work/recomp/img_gfx work/recomp/bdsp_boot --headless --timeout 120 --screenshot-after 600
# Diagnose: BDSP_NVN_STATS=1 BDSP_BT=1 BDSP_TRACE_SYNC=3000 BDSP_TRACE_HLE=5000 BDSP_TRACE_IPC=1 BDSP_LOG_FILES=1 BDSP_DEV94=16
```

Lizenz: `scripts/recomp/rt-bdsp/NOTICE.md` (Abschnitt „NVN-Schicht“), Lizenztext `LICENSE-LASRecomp`.
