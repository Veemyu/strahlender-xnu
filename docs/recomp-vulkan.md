# Rekompilation: Vulkan-Pfad für Linux (und später Windows) (`ap-recomp` Vulkan)

Stand: 2026-10-19, Zwischenstand nach Etappe 3 (wird je Etappe fortgeschrieben). Grundlage: `docs/recomp-gate2.md` (NVN/Metal-Schicht, Backend-Abstraktion), `docs/recomp-ryzen.md` (Linux-Rechner „Ryzen“, ssh-Alias `nobara`), `docs/shader-translator.md`, `research/LASRecomp/docs/linux.md`. Auftrag: das rekompilierte BDSP soll unter Linux x86-64 mit Vulkan zeichnen (ohne Ton), Fenster über SDL3, für Tests Offscreen mit PNG-Ausgabe.

**Kennzeichnung:** **gemessen** = mit den Skripten unter `scripts/recomp/ryzen/vk_*.sh` auf dem Ryzen (Ryzen 5 7500F, RTX 2080 Ti, Treiber mit Vulkan 1.4.329, Fedora/Nobara 44) bzw. auf dem Mac ermittelt; Rohlogs unter `~/xnu-recomp/logs/vk-*.log` (per `vk_fetch.sh logs` nach `work/recomp/ryzen/logs/`). *vermutet* = Schluss ohne Test. Im Repo liegen weder Spielbytes noch erzeugter Code, Shader, Zwischenspeicher oder Bilder (alles unter `work/` bzw. `~/xnu-recomp/work/`).

## Ergebnis in Kürze

| | |
|---|---|
| **Vulkan-Pfad** | **läuft** auf dem Ryzen: Gast bootet durch, `nnMain`, NVN-Initialisierung, Spieldaten aus dem RomFS, Shader, Zeichenaufrufe. **Gerät: NVIDIA GeForce RTX 2080 Ti** (Vulkan 1.4.329) erkannt und benutzt. Kein Absturz in allen Läufen (bis 40 s Offscreen, 22 s im Wayland-Fenster). |
| **Bild** | **erkennbares, vollständiges Bild**: der Gast zeichnet die **Sprachauswahl** (erster Start: English, Español, Français, Deutsch, Italiano, にほんご, 日本語, 한국어, 简体中文, 繁體中文 auf dem Kristallhintergrund, darunter „Select the language you would like to play in.“) mit **7 Zeichenaufrufen je Bild**, 59,8 Bilder/s, GPU-Zeit etwa 0,1 ms je Bild (gemessen, `BDSP_VK_PROF=1`). Das Bild entsteht im 1920x1080-Zielbild oben links als 1280x720-Ausschnitt (der Rest ist schwarz, siehe Änderungswünsche). Der Metal-Pfad liefert im selben Stand ein schwarzes Bild (Abschnitt „Vergleich mit Metal“). |
| Shader | Unser Übersetzer (`shader_translator/`, `--glsl`) übersetzt **4.276 von 4.276** eindeutigen Spielprogrammen (3.593 Fragment, 683 Vertex) und `glslc --target-env=vulkan1.3` kompiliert **4.276 von 4.276** (Mac, 95 s mit 8 Threads, gemessen). Im Lauf werden 3.025 Programme (Paare mit Schlüssel) in etwa 3 s zu SPIR-V; **1.206** verschiedene SPIR-V-Module, 115 MB. Kalt (leerer Zwischenspeicher) und warm (gefüllt) unterscheiden sich kaum (kalt: erste Zeichenaufrufe nach 3,6 s, warm: 3,3 s). |
| Determinismus | Zwei Läufe mit leerem Zwischenspeicher liefern **dieselben 1.206 Dateinamen und denselben Inhalt** (Prüfsumme über alle Dateien identisch). Schlüssel = FNV-1a-Hash über Stufe und GLSL-Quelltext; der Quelltext entsteht allein aus den Maxwell-Programmdaten des eigenen Dumps und dem `ShaderKey`. **Kein Ryujinx-Cache** wird benutzt. |
| Build | `NVN_BACKEND=vulkan scripts/recomp/rt-bdsp/build.sh` (Ryzen: `scripts/recomp/ryzen/vk_build.sh`): Vulkan-Teil in **5 s** (15 Dateien, `clang -O2`), Link 353 MB. Auf dem Mac dient `VK_SYNTAX=1 …/nvn/vulkan/build_vk.sh` als Syntaxprüfung mit Homebrew-Headern (alle 12 Quellen ok). |
| Offscreen | `--headless` rendert in Bilder eigener Größe (1920x1080, B8G8R8A8), **ohne Fenster und ohne Anzeigeverbindung** (läuft per ssh); `--screenshot-after N` schreibt `work/recomp/shots/frame_NNNNN.png` (1920x1080). |
| Fenster | SDL3 + Wayland: 22 s im Fenster 1280x720 (Swapchain 2176x1224 durch Skalierung des Desktops), 1.060 Bilder, 59,8 Bilder/s, ohne Fokusraub (`BDSP_NO_USER_INPUT=1`). |
| Nicht gelöst | keine Schreibverfolgung der Gastseiten (Vertex-Zwischenspeicher aus, Texturen werden neu geprüft); Compute-Skinning/Partikel/MRT noch nicht erreicht (0 Dispatches); Pipeline-Zwischenspeicher wird beim Beenden nicht geschrieben; Windows nicht angefasst. |
| **Fund (gilt auch für Metal)** | **Textur- und Sampler-Tabelle des bindlosen Zugriffs waren vertauscht**: bei Handles aus zwei Wörtern liegen die **Texturen** in der Tabelle ab `0x168` und die **Sampler** in der ab `0x568` (nicht umgekehrt; Unity bindet Textur und Sampler einer Einheit mit demselben Index). Bei Programmen, deren Compiler Textur- und Sampler-Index verschieden vergeben hat, wurden falsche Texturen gebunden. Das sind **847 von 3.592** eindeutigen Fragment-Programmen mit bindlosen Texturen (**23,6 %**, Messung an den Blobs mit `maxwell2msl --info`); die übrigen 2.745 haben gleiche Indizes (dort war die alte Annahme wirkungslos). Sichtbar wurde es am TextMeshPro-Text (Schriftatlas als „Gesichts-Textur“ gebunden: zerhackte, schmale Glyphen); nach der Korrektur ist der Text **pixelgleich** mit dem Ergebnis einer zweiten, unabhängigen Zuordnung (Umkehrung innerhalb der Texturzahl). `renderer.m` der Metal-Fassung (`shader_handle`, `las-nvn.patch`) macht dieselbe Annahme wie vorher der Vulkan-Pfad: dort ebenso tauschen (Änderungswunsch 1). |

## Aufbau (`scripts/recomp/rt-bdsp/nvn/vulkan/`, alles neu)

| Datei | Inhalt |
|---|---|
| `prepare_vk.sh` | ruft `../prepare.sh` mit `NVN_SRC=work/recomp/nvn-src-vk` auf (gemeinsamer Teil: `objects.c`, `cmdbuf.c`, `formats.c`, `tegra.c`, `astc.c`, unser Übersetzer, `las-nvn.patch` – das Patchen der gemeinsamen Dateien bleibt damit beim anderen Agenten), kopiert danach den Vulkan-Teil des Klons (`device.c`, `exec.c`, `shaders.c`, `shaders.h`, `textures.c`, `vk.h`, `vma.cpp`), legt `shim/` darüber und wendet `las-vk.patch` an |
| `las-vk.patch` | unsere Änderungen am Vulkan-Teil (Liste unten, 287 Zeilen) |
| `shim/` | `platform.h`, `kernel.h`, `settings.h`, `ui/menu.h`: Ersatz für die Kopfdateien des Klons, überlagert `nvn/shim/` |
| `vk_glue.c` | `plat_written_pages` (immer „keine Verfolgung“), `plat_terminate`, `g_blocked_ns`, Standardwert `BDSP_PACE=0` |
| `build_vk.sh` | baut die Objekte nach `work/recomp/rt-bdsp-vk/nvnvk/`; `VK_INC` (Kopfdateiordner, Standard `./include-vk` oder Homebrew), `VK_SYNTAX=1` |
| `NOTICE.md` | Herkunft (LASRecomp, MIT) und Drittkomponenten (Vulkan-Header, VMA, SDL3, shaderc), nichts davon im Repo |

Geändert in der gemeinsamen Datei `rt-bdsp/build.sh` (nach erneutem Lesen, minimal): der Zweig `vulkan)` ruft `build_vk.sh` auf, setzt `RT=…-vk`, `OUT=…_vk` und die Bibliotheken `-l:libvulkan.so.1 -l:libSDL3.so.0 -l:libshaderc_shared.so.1 -lstdc++`. Außerdem ein Satz in `rt-bdsp/NOTICE.md`.

`scripts/recomp/ryzen/` (neu, Präfix `vk_`): `vk_sync_deps.sh` (Header), `vk_sync.sh` (Arbeitsstand, `--daten` für RomFS/NPDM), `vk_build.sh`, `vk_run.sh`, `vk_fetch.sh` (Bilder und Logs), dazu `remote/vk_build.sh`, `remote/vk_run.sh`. Alles läuft wie die bestehenden Skripte entkoppelt über `job.sh` (Bahnen a/b), schreibt nur unter `~/xnu-recomp` und braucht kein sudo.

### Änderungen an den Quellen des Klons (`las-vk.patch`)

| Datei | Änderung |
|---|---|
| `exec.c` | **Trennbare Programme** (`CMD_BIND_PROGRAM` mit Stufenmaske, Stufen werden zu einem Programm zusammengeführt), **getrennte Sampler** (`CMD_BIND_SAMPLERS`, `st.smp`), **bindlose Texturen** (`shader_handle`: Texturwort ab `0x568`, Samplerwort ab `0x168`, je 8 Byte, aus Konstantenpuffer 2 – dieselbe Regel wie `renderer.m`), `no_rscale`, Wegfall des Tint-Pfads (`uses_tint` gibt es im Übersetzer nicht mehr), Programmtabelle 16.384 Einträge |
| `device.c` | **`--headless`** (`BDSP_HIDDEN`): Instanz ohne Oberflächenerweiterungen, Gerätewahl ohne Present-Prüfung, drei Offscreen-Bilder statt Swapchain, kein Present; Bilder nach `BDSP_SHOT_DIR` bzw. `work/recomp/shots`; Pipeline-Cache unter `work/recomp/cache`; Speicherbereich der Pools über `nvn_glue_mem_range()`; Fenstertitel |
| `shaders.c` | SPIR-V-Zwischenspeicher unter `work/recomp/cache/spirv` (LAS schrieb nach `cache/` im Arbeitsordner) |

Nicht geändert: `textures.c`, `vk.h`, `vma.cpp`, `shaders.h`. Der Patch lässt sich aus dem Klon frisch anwenden und ergibt dieselbe Kopie wie der Arbeitsstand (`diff -r` geprüft).

## Etappe 1: Header und Bibliotheken ohne sudo (gemessen)

Der Ryzen hat die Laufzeitbibliotheken, aber keine `-devel`-Pakete und kein Internet. Vorhanden und per **Vollpfad gelinkt** (ohne `-dev`-Symlinks): `/usr/lib64/libvulkan.so.1`, `/usr/lib64/libSDL3.so.0` (3.4.16), `/usr/lib64/libshaderc_shared.so.1` (Paket `libshaderc-2026.1`). **Korrektur der Annahme „shaderc fehlt“:** die Laufzeitbibliothek ist da (als Abhängigkeit anderer Pakete); es fehlt nur der Header. Damit entfällt der geplante Umweg über Vorab-Übersetzung mit `glslc` auf dem Mac: der Klon kompiliert GLSL zur Laufzeit wie vorgesehen, der Zwischenspeicher macht es deterministisch und billig.

`vk_sync_deps.sh` überträgt **nur Header** nach `~/xnu-recomp/include-vk/` (27 MB): `vulkan/`, `vk_video/` (Homebrew `vulkan-headers` 1.4.363), `SDL3/` (Homebrew `sdl3` 3.4.18), `shaderc/` (Homebrew `shaderc` 2026.4, nur die C-Schnittstelle genutzt), `vk_mem_alloc.h` (VMA, MIT, von GitHub nach `work/recomp/deps-vk/` geladen, weil es als Homebrew-Formel fehlt). Lizenztext von VMA liegt daneben (`LICENSE-VMA.txt`).

**Optionale Installationsliste für den Nutzer** (nur wenn man statt `include-vk/` die Systempakete will; Namen nach Fedora, nicht geprüft; ich führe kein sudo aus):

```
sudo dnf install vulkan-headers vulkan-loader-devel SDL3-devel libshaderc-devel VulkanMemoryAllocator-devel
sudo dnf install vulkan-validation-layers     # nur für Diagnose (BDSP_VK_VALIDATION=1)
```

Danach `VK_INC=/usr/include` setzen (oder `include-vk/` löschen); `build.sh` bleibt gleich. Nötig ist nichts davon.

## Etappe 2: Backend eingehängt (gemessen)

Befunde beim ersten Bau auf dem Ryzen (alles behoben, ohne gemeinsame Dateien anzufassen): `g_debug_frame` wird von `nvn_glue.c` und `exec.c` definiert → `nvn_glue.c` wird für Vulkan mit `-Dg_debug_frame=bdsp_glue_debug_frame` übersetzt; `kernel_heap_size` gibt es schon in `kernel.c` (die Vulkan-Fassung nutzt sie); `g_blocked_ns` (Zeit in Warteaufrufen, Bildtakt-Erkennung des Klons) fehlt → `vk_glue.c`, Bildtakt-Erkennung aus (`BDSP_PACE=0`), das Spiel taktet über das Vsync-Ereignis aus `services_gfx.c`. Fehlende Kopfdateien (`plat_written_pages`, `menu_render` in C, `UPSCALE_FSR1`) liefern die Shims. Sonst übersetzte `exec.c` (3.790 Zeilen) ohne Änderung der Logik.

## Etappe 3: Lauf auf dem Ryzen (gemessen)

Voraussetzung: RomFS und `main.npdm` des **eigenen** Dumps liegen unter `~/xnu-recomp/work/` (`vk_sync.sh --daten`, 4,7 GB in 44 s; nie im Repo). Frühere Läufe der Farm endeten bewusst vor dem RomFS; für Zeichenaufrufe ist es nötig.

Ablauf des Laufs (`vk_run.sh --tag=t1 --headless --timeout 40`): `[vk] gpu 0: NVIDIA GeForce RTX 2080 Ti (api 1.4.329)` → Gerät, Swapchain/Offscreen 1920x1080 → `nvnBootstrapLoader`, Gerät, Fenster mit 3 Texturen → 3.025 Programme in ~3 s → ab t=4 s 7 Zeichenaufrufe je Bild, 240 Durchgänge/2 s. 40 s, RSS 2,4 GB (Offscreen, einschließlich 650 MiB per MapPhysicalMemory, Vulkan-Speicher und Shader-Zwischenspeicher), 0 NVN-Funktionen ohne Host-Umsetzung.

Dieselben 7 Zeichenaufrufe wie im Metal-Pfad (Vollbild-Viereck, Netze mit 1.086/48/96/54/6 Indizes aus dem 2048x2048-ASTC-Atlas, dann das Textnetz mit 384 Indizes, das den 1024x1024-R8-Schriftatlas samplet).

## Vergleich mit Metal und Befund für die gemeinsame Runtime

Der Metal-Pfad auf dem Mac (Kopie von `work/recomp/bdsp_boot` 14:01, gleiche Abbilder `img_gfx`, `--headless --screenshot-after 300`) liefert in Bild 300, 600, 900, 1.200 **durchgehend schwarze** Bilder (Mittelwert 0). Die Vulkan-Fassung zeigt in **demselben Spielzustand** (gleiche Aufrufzahlen: 7 Zeichenaufrufe je Bild) die Sprachauswahl. Eine Pixelabweichung lässt sich daher **nicht** berechnen (Metal hat kein Bild); sobald Metal ein Bild liefert, vergleicht `scripts/visual_compare.py` (vorhanden, vom anderen Agenten) beide Ausgaben; die Vulkan-Bilder holt `vk_fetch.sh shots` nach `work/recomp/ryzen/shots/`.

**Wichtiger Hinweis zur Suche nach dem schwarzen Bild (Metal), gemessen:** Beide Pfade sehen im Bild 300 **dieselbe Eingabe**: gleiche Programmadressen (`vs=72c0fcbd00 fs=72c0fcc000` …), gleiche Konstantenpuffer-Adressen (`f0(72beb71600,16)`, `f0(72beb71d00,112)`, `v1(72beb71700,480)`), gleiche Werte (Fragment-Konstantenpuffer 3: `[1 1 1 1]` beim Vollbild-Viereck, `[0 0 0 0]` bei den Atlas-Netzen, Zeit-Vektor `[0.26 5.1 10.3 15.4]` beim Textnetz; Vulkan-Log mit `BDSP_DEBUG_FRAME=300`, Metal-Log mit `BDSP_DEBUG_FRAME=300 BDSP_DEBUG_DATA=1`) und dieselben 7 Zeichenaufrufe mit denselben Texturen (1280x720 `0x3f`, 2048x2048 ASTC `0x7d`, 1024x1024 R8, 4x4 `0x25`). Der Farbfaktor `[0 0 0 0]` der Atlas-Netze ist demnach **nicht** die Ursache (Vulkan zeigt dieselben Netze sichtbar; die Faktoren gehören offenbar nicht zu dem, was der Shader liest). **Der Spielablauf ist also in Ordnung und der Fehler liegt in der Metal-Ausführung** (`renderer.m`/`metal.m`: Rendertarget/Blend/Präsentation), nicht in Gastlogik, Zeit oder Konstantenpuffern. Auch der Tausch der Textur-/Sampler-Tabelle in `renderer.m` allein (Kopie unter `work/recomp/nvn-src-mtest`, Metal-Lauf 40 s) ändert das Bild nicht (Werte ≤ 2 von 255). Nächster Schritt für Metal: die Durchgänge des Bildes 300 als Einzelbilder abziehen (`BDSP_DEBUG_FRAMES`) und mit den Vulkan-Durchgängen vergleichen (`vk` kann dasselbe mit `build/pass_*.png`, Ordner `build/` vorher anlegen).

## Lauf mit dem neuen Spielstand (14:58, gemessen)

Bau: `nvn_glue.c` (neue Eingabeschicht von gate2) bindet `SDL3/SDL.h`, `stdatomic.h`, `string.h` nur unter `__APPLE__` ein; unter Linux fehlten daher alle `SDL_SCANCODE_*` und `atomic_fetch_*` (20 Fehler, **kein** Header-Problem: `include-vk/SDL3/SDL_scancode.h` war da). Lösung im vk-Bau: `build_vk.sh` übersetzt `nvn_glue.c` mit `-include SDL3/SDL.h -include stdatomic.h -include string.h -include strings.h`. Änderungswunsch an `nvn_glue.c`: die vier `#include` aus dem `#ifdef __APPLE__`-Block herausnehmen (nur `mach-o/*` gehört hinein); dann entfällt der Behelf.

Lauf `vk_run.sh --tag=save3 --headless --timeout 60 --screenshot-after 4 --save work/recomp/save` (Spielstand SHA-256 `0396a4a62735` auf dem Ryzen, `user_id.hex` vorhanden):
- `[acc] Benutzer-ID aus work/recomp/save/user_id.hex`, `[fs-save] cmd 7 …/main2`, `cmd 7` und `cmd 8` auf `…/SaveData.bin`: **der Spielstand wird geöffnet und gelesen**.
- Die Sprachauswahl erscheint nicht mehr im Lauf (bis zum Absturz bei Bild ~120 zeichnet der Vulkan-Pfad nur Schwarz; die ersten Zeichenaufrufe kommen sonst erst nach ~3 s Shader-Kompilierung).
- **Absturz im Gastcode nach 6,5 s (SIGSEGV, Adresse 0)** in `android::OMXCodec::findMatchingCodecs` ← `android::ACodec::UninitializedState::onAllocateComponent` ← `onMessageReceived`: der Gast legt einen Video-Decoder an (MIME-Kette `vnd.on2…`, VP8: Titelfilm), die OMX-/Codec-Anbindung (nvdrv/nvdec o. ä.) fehlt. **Derselbe Absturz mit identischem Gast-Stapel im Metal-Lauf auf dem Mac** (Kopie von `bdsp_boot` 14:53, nach 16,9 s): kein Linux-/Vulkan-Problem, sondern fehlender Video-Dienst der gemeinsamen Runtime.
- Eingabe (`hid`) wurde nicht gebraucht, der Lauf kommt nicht so weit.

Bilder: `work/visual/recomp/vk_save/` (30 PNG, alle schwarz bis auf Bild 120 mit Mittelwert 0,3).

## Offene Punkte (Reihenfolge)

1. **Gelöst (Fund oben):** TextMeshPro-Text im Dialog der Sprachauswahl. Weg dorthin (gemessen): Schriftatlas selbst korrekt (R8 1024x1024 als PGM abgezogen), Vertexdaten und Konstantenpuffer plausibel (Projektion 1/640, 1/360), Swizzle `0,0,0,R` stimmt; im Fragment-Shader tastet `t0` mit den Atlas-UV (`uv0`) ab, die Bindung lieferte aber eine 4x4-Weißtextur dafür → Tabellenvertauschung. Nicht mehr offen; **offen** bleibt, die GLSL-Ausgabe des Übersetzers insgesamt gegen die Ryujinx-Referenz zu prüfen (MSL: 332 von 387 Paaren ≤ 1/255; GLSL nie gemessen).
2. Schreibverfolgung der Gastseiten (`plat_written_pages`): heute immer „unbekannt“ → Vertex-Zwischenspeicher aus (`vcache`), Textur-Neuprüfung per Hash (4 volle + 56 Stichproben je 60 Bilder, 19,8 MB Upload je 2 s). Linux bietet Soft-Dirty (`/proc/self/clear_refs`, `pagemap`) oder `userfaultfd`; bei steigender Last nötig.
3. Pipeline-Zwischenspeicher (`work/recomp/cache/vk_pipelines.bin`) wird nicht geschrieben: der Prozess endet über `_exit` der Überwachung; `quick_exit_handler` läuft dabei nicht. Optional.
4. Compute (Skinning, Partikel, `LDG/STG`): im Titelzustand 0 Dispatches; die Anbindung des Gastspeichers als Vulkan-Puffer (`VK_EXT_external_memory_host`) ist im Klon vorhanden, aber ungetestet und pinnt bis zu 5 GB; **nicht aktiviert**-Pfad: `BDSP_VK_NO_GMEM=1` wäre nötig, falls die Importgröße scheitert.
5. Frame-Pacing (gleiche Lücke wie Metal), Eingabe (`hid` meldet keinen Zustand): gemeinsame Runtime.
6. Fenster: kurzer Test unter Wayland erfolgreich, X11 (`SDL_VIDEODRIVER=x11`) und Vollbild nicht getestet.

## Änderungswünsche an die gemeinsame Runtime

(Ich habe die Dateien nicht angefasst, bis auf `build.sh`, siehe oben.)

1. **`renderer.m` (Metal), `shader_handle` in `las-nvn.patch`:** Textur- und Sampler-Tabelle tauschen (siehe „Fund“): bei `bindless_has_sampler` den **Texturindex aus `bindless_sampler_offset` (ab `0x168`)** und den **Samplerindex aus `bindless_offset` (ab `0x568`)** bilden. Betrifft 23,6 % der Fragment-Programme; kann das Metal-Bild ändern.
2. **Zielgröße/Ausschnitt:** das Spiel rendert 1280x720 in das 1920x1080-Fensterbild und ruft `nvnWindowSetCrop` (in `objects.c` im Fensterobjekt `crop[4]` gespeichert, aber nie an `backend_present` weitergereicht). `widescreen_present_crop` in `nvn_glue.c` liefert immer das volle Bild; Bildschirm und Screenshots zeigen daher unten/rechts Schwarz. Den Ausschnitt aus `WIN->crop` für beide Backends in die Präsentation einspeisen.
3. **`nvn/nvn_glue.c`**: `bool g_debug_frame;` hinter `#ifndef BDSP_NVN_VULKAN` oder in einen eigenen Abschnitt legen (die Vulkan-Fassung definiert es selbst; heute behelfsweise `-Dg_debug_frame=…` in `build_vk.sh`). Die Logzeile `[nvn] Metal-Puffer über …` neutral nennen („Speicherbereich der NVN-Pools“).
4. **`kernel.c`**: `__thread uint64_t g_blocked_ns` (Zeit des Threads in Warte-/Schlafaufrufen) führen, sobald der Bildtakt des Klons gebraucht wird; heute liefert `nvn/vulkan/vk_glue.c` eine Null-Definition (dann dort entfernen).
5. **`build.sh`**: unter Linux Standard `NVN_BACKEND=vulkan`, wenn `include-vk/vulkan` oder `pkg-config vulkan` vorhanden ist (heute `none`).
6. **`kernel.c`/`main.c`**: die vier Mach-Stellen hinter eine kleine Plattformschicht (Zeit, Thread-Anhalten, Stack, Speicherbericht), damit `scripts/recomp/ryzen/compat` entfällt (steht schon in `docs/recomp-ryzen.md`, Abschnitt 7); gleiche Schicht ist die Voraussetzung für Windows.
7. **Metal (`renderer.m`/`metal.m`) prüfen:** das schwarze Bild entsteht in der Ausführung, nicht in der Gastlogik (siehe „Vergleich mit Metal“); Einzeldurchgänge von Bild 300 gegen die Vulkan-Durchgänge halten.
8. `--headless` in `main.c` sagt „Rendern bleibt Metal“; für Vulkan bedeutet es zusätzlich „ohne Anzeigeverbindung“ – Kommentar anpassen.

## Windows-Ausblick (nicht angefasst, *vermutet*)

Der Vulkan-Teil des Klons ist für Windows gebaut (MSYS2 `clang64`: `mingw-w64-clang-x86_64-{clang,SDL3,vulkan-headers,vulkan-loader,vulkan-memory-allocator,shaderc}`; Visual Studio geht mit `clang-cl` nur umständlich, weil die Laufzeit GNU-Inline-Assembler und `__attribute__` nutzt). Offen bleibt die Laufzeit selbst: **Mach-Ersatz → Win32**: `mach_absolute_time` → `QueryPerformanceCounter`; `thread_suspend/resume/get_state` (Boehm-GC-Anhalten) → `SuspendThread`/`GetThreadContext`; `mach_vm_allocate` an festen Adressen (`0x7000000000`, 12,5 GB Fenster) → `VirtualAlloc(MEM_RESERVE)` an der Wunschadresse (unter Windows bis 128 TB möglich); `mach_vm_region`/`task_info` → `VirtualQuery`/`GetProcessMemoryInfo`; Signale → strukturierte Ausnahmen; die ELF-/Mach-O-Abschnitte für `HLE_FUNC` (`__start_hle_impls`) → PE-Abschnitte mit `.hle$a`/`.hle$z`-Markern. Als Vorlage dient `research/LASRecomp/runtime/platform/windows.c`. Aufwand *vermutet* 3 bis 5 Tage nach der Plattformschicht aus Wunsch 4.

## Reproduktion

```
scripts/recomp/ryzen/vk_sync_deps.sh              # Header (einmalig, ~27 MB)
scripts/recomp/ryzen/vk_sync.sh --daten           # Arbeitsstand + img_gfx (+ RomFS/NPDM des eigenen Dumps)
scripts/recomp/ryzen/vk_build.sh                  # NVN_BACKEND=vulkan auf dem Ryzen → work/recomp/bdsp_boot_vk
scripts/recomp/ryzen/vk_run.sh --tag=t1 --headless --timeout 40 --screenshot-after 300
scripts/recomp/ryzen/vk_fetch.sh alles            # Bilder und Logs nach work/recomp/ryzen/{shots,logs}
# Fenster (kurz, ohne Fokusraub; Wayland-Sitzung des Desktops):
scripts/recomp/ryzen/vk_run.sh --tag=win XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-0 SDL_VIDEODRIVER=wayland BDSP_NO_USER_INPUT=1 --window 1280x720 --timeout 22
# Mac-Syntaxprüfung mit Homebrew-Headern:
VK_SYNTAX=1 scripts/recomp/rt-bdsp/nvn/vulkan/build_vk.sh
```

Diagnose-Schalter des Klons (Umgebung): `BDSP_VK_PROF=1` (CPU-/GPU-Zeit je Kategorie), `BDSP_DEBUG_FRAME=N` (Zeichenaufrufe von Bild N im Log), `BDSP_SAVE_MSL=1` (GLSL nach `build/glsl/`, Ordner `build/` vorher anlegen), `BDSP_VK_VALIDATION=1`, `BDSP_VK_NO_SPIRV_CACHE=1`.
