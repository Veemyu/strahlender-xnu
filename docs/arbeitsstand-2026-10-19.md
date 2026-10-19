# Arbeitsstand 2026-10-19 (17:10)

Zweck: ein Dokument, das ohne Vorwissen erklärt, wo wir stehen, was belegt ist, was fehlt und wo man nachliest. Zahlen sind gemessen oder als Annahme gekennzeichnet. Index aller Dokumente: `docs/README.md`.

## 1. Ziel und Regeln

- **Ziel (Nutzer):** Mit diesem Repo und einer eigenen NSP/XCI von Pokémon Brilliant Diamond (BDSP) lässt sich ein natives, getestetes Spiel für **macOS, iPadOS** (später Linux/Windows mit Vulkan) bauen. Das Repo enthält **keine** Spieldaten, Keys, Dumps, erzeugten Code, Saves oder Screenshots. Gebaute Apps sind nur für den persönlichen Gebrauch.
- **Kein Ton**, nie: Audio ist stumm, keine Lautstärkeänderungen an Mac oder iPad.
- **Saves** bleiben kompatibel mit Ryujinx/Switch (`SaveData.bin` 979.108 Byte, Version 0x34, MD5 bei 0xE9818).
- **Arbeitsregeln:** kein sudo, keine Scans der ganzen Platte, Commits nur mit der Identität des Nutzers (kein Co-Author-Trailer), Repo-Dateien nur mit `edit`/`create`, vor jedem Commit läuft `scripts/repo_check.py` (Hook).

## 2. Strategie (Entscheidungen in `docs/architektur-entscheidung.md`)

| Nr. | Datum | Entscheidung |
|---|---|---|
| 1 | 2026-10-18 | Nutzer: Weg D (Unity-Rebuild), vollständig spielbar, später öffentlich (nur Code). |
| 2 | 2026-10-18 | Autopilot: Rekompilation (LAS-Methode) zurückgestellt (Exceptions, GC, 12,5-GiB-Fenster). |
| 3 | 2026-10-19 15:30 | Rekompilation wird Hauptweg (Exceptions lösbar, c-Modus bitgenau, Spiel läuft bis in die Stadt). |
| 4 | 2026-10-19 16:57 | **Nutzer: Unity-Rebuild ist deprecated, nicht mehr weiterentwickeln** (`unity/DEPRECATED.md`). |

Es gibt heute **einen** Entwicklungsstrang: die Rekompilation.

## 3. Rekompilation (Hauptweg)

**Prinzip:** Der originale ARM64-Code des Spiels (NSO `main`, `sdk`, `subsdk0`, `rtld`) wird statisch nach C übersetzt (Lifter aus LASRecomp, MIT). Eigene Laufzeit `scripts/recomp/rt-bdsp/` ersetzt das Switch-Betriebssystem: Kernel-SVCs, IPC-Dienste (HIPC/CMIF), RomFS aus dem Dump, Speicherstand, NVN-Grafik über Metal (macOS/iPadOS) bzw. Vulkan (Linux), Film über FFmpeg. Logik, UI, Events, Kampf und KI sind damit 1:1 das Original.

### 3.1 Gemessen (Quellen: `recomp-gate1.md`, `-gate2.md`, `-spike-2.md`, `-diff.md`, `-ryzen.md`, `-macapp.md`)
- **Umfang:** 270.299 Funktionen, 985,6 MB (c) bzw. 1.037 MB (asm) C, 14,1 Mio. Befehlswörter. Nur 58 Wörter (LDXP/STXP-Familie) waren anfangs nicht abgedeckt, jetzt 116 erzeugt.
- **Bauzeit:** Generator 51–74 s; Übersetzen auf dem Mac 937 s (3 Jobs), Kaltbau der Stufe `recomp` ca. 27,5 min inklusive allem; Ryzen 310–388 s (10–12 Jobs, `-O0` ab 300 KB Einzelfunktion). Inkrementell: Sekunden bis 1 min (feste 32-KiB-Chunk-Fenster).
- **Exceptions (Ausschlusskriterium):** Der echte libunwind des SDKs läuft rekompiliert; 100 von 180 echten LSDA-Funktionen im Test ohne Abweichung beim Landing-Pad, 55 stürzten in der synthetischen Umgebung ab (nicht im Spiel).
- **GC:** Thread-Anhalten über Mach `thread_suspend`/`thread_get_state` (SVC 0x32/0x33), ca. 8 µs je Thread.
- **Bitgenauigkeit (`recomp-diff.md`):** x86-`c`-Modus gegen ARM64: 0 Abweichungen (93,5 Mio. Fälle je Variante, 44 Befehle erschöpfend über 2^32 Eingaben). Pflicht: `rt_fp_guest_mode()` im Gast-Thread (sonst weichen FTZ/DAZ-Fälle ab), Flags `-O1 -ffp-contract=off -fno-fast-math`.
- **Lauf auf dem Mac (Metal):** rtld → Eröffnungsfilm (VP8, FFmpeg) → Titel nach 21,9 s → „Weiter“ → Spielstand → 3D-Stadt (Zone 24) bei 45 Bildern/s, RSS 1,0–1,5 GiB, 24–37 Threads, 135 s ohne Absturz.
- **Lauf unter Linux (Vulkan, RTX 2080 Ti):** Sprachauswahl mit korrektem Text bei 60 Bildern/s; alle 4.276 eindeutigen Spielprogramme gehen durch Übersetzer + `glslc`, deterministisch (1.206 SPIR-V-Dateien byte-identisch).
- **iPad (App `dev.local.xnubdsp`):** läuft, ca. 41 FPS, Footprint 1,5–2,1 GiB (Limit 8 GiB mit Increased-Memory-Limit), 37 Threads. Details in `ipad-durchstich-1.md` (Save-Weg) und `recomp-ios.md` (entsteht).
- **Referenzvergleich:** Sprachauswahl Rekompilation gegen Ryujinx pixelgleich (SSIM 0,999). Stadtbild: Farben nah (Abweichung 15–17 je Kanal), Wasser fehlt (weiß statt blau).

### 3.2 Komponenten (wo liegt was)
| Pfad | Inhalt |
|---|---|
| `scripts/recomp/*.py,sh` | Generator-Pipeline (`gen_all.sh`, `regen_inc.sh`, `build_all.sh`, `mkimg.py` Modulabbilder, `eh_*` Exception-Mechanik, `il2sym.py` IL2CPP-Symbole, `symres.py`) |
| `scripts/recomp/rt-bdsp/` | Laufzeit: `kernel.c`, `ipc.c`, `services*.c`, `loader.c`, `dispatch.c`, `main.c`, `guestmem.h` (G2H/H2G), `install_save.sh`, `app/` (macOS-Hülle) |
| `scripts/recomp/rt-bdsp/nvn/` | NVN→Metal: `prepare.sh` kopiert LAS-Quellen nach `work/` und wendet `fixes.patch` an; `nvn_glue.c`, `movie_glue.c` (FFmpeg-Film), `debug.patch`; `vulkan/` Linux-Pfad (`prepare_vk.sh`, `las-vk.patch`, `vk_glue.c`) |
| `scripts/recomp/rt`, `rt32/` | Header-Erweiterungen der LAS-Laufzeit (Exceptions, 32-Bit-Rebasing) |
| `scripts/recomp/app/` | `BDSP.app`-Hülle (Info.plist, Menü, Import, Eingabe) |
| `scripts/recomp/ios/` | iPad-Bau (rebase32, FFmpeg-iOS, Xcode, Deploy), in Arbeit |
| `scripts/recomp/ryzen/` | Ryzen-Farm (`sync.sh`, `build.sh`, `run_probe.sh`, `vk_*.sh`) |
| `scripts/recomp/qa/` | Testharness (`qa_run.sh`, Szenarien), in Arbeit |
| `scripts/recomp/diff/`, `c_exact/` | Differenzialtest c-Modus gegen ARM64, FP-Umgebung |

### 3.3 Offene Fehler (Priorität)
1. **Wasser** (`Delphis/Map/FlowmapWater`, Transparenz, ohne GrabPass; Eingänge `_OpaqueDepthTexture`, `_ReflectionTex`): Referenz `work/visual/ref/ryujinx/views/free_wasser_a/b.png` (Zielwerte in `docs/wasser.md`). Verdacht: Render-Target-Texturen werden im Metal-Pfad falsch gelesen. Besitzer: `ap-recomp-qa`.
2. **Pokécenter-Innenraum** einfarbig blau, dunkle Striche rechts (NVN/Shader-Schicht).
3. **iPad:** Absturz, wenn das Intro-Video nicht sofort übersprungen wird (nicht reproduziert); Start brauchte 2–3 Versuche. Software-Decoder VP8 (FFmpeg) läuft; Alternative H.265 per VideoToolbox. Besitzer: `ap-recomp-ios`.
4. Kameraversatz 28 px gegen Ryujinx (Zeitpunkt der Kamerafahrt, vermutlich nur Timing).
5. Titelbild: Ryujinx-Referenz fehlt (F8 am Titel nötig).
6. Speicherpuffer/Compute lesen den umhüllten Gastspeicher; 32-Bit-Modell (`rebase32`) auf dem Gerät noch nicht belegt; SDK verlangt 3,14 GB am Stück.
7. Nicht umgesetzt: MetalFX, Controller-Test mit Hardware, Touch-Steuerung auf dem iPad, Vulkan unter Windows, Ton (bleibt aus).

## 4. Gemeinsame Werkzeuge (bleiben in Betrieb)
- **Extraktion:** hactool-Bau, XCI/NSP → `work/exefs`, `work/romfs` (`scripts/build_all.sh` Stufen `tools`, `extract`); Il2CppDumper → `work/il2cpp`; Ghidra-Projekt `work/ghidra/bdsp` (166.095 Funktionen).
- **Shader:** Maxwell→MSL/GLSL-Übersetzer `shader_translator/` (LASRecomp-MIT-Basis, `NOTICE.md`, 4.276/4.276 Blobs erkannt, 0 Fehler bei 5.959 Programmen, Treue gemessen).
- **Umwandlungen:** VP8→H.265 (`video_convert.sh`, CRF 18, +41 % Größe), BC→ASTC (`texture_transcode.py`, 6×6: Median 46,2 dB PSNR), Bundle-Zielplattform Switch→Player (`bundle_retarget.py`).
- **Saves:** `bdsp_save.py` (prüfen, Hash fixen), `ryujinx_sync_save.sh` (Mac ↔ Ryujinx auf dem Ryzen, findet Profilordner über `ExtraData0`), `ios_push_save.sh` (iPad), `install_save.sh` (Rekompilation). **Standard-Testspielstand:** Stadt (Zone 24), 69:08:16 Spielzeit, SaveData sha256 `0396a4a62735…`.
- **Bildprüfung:** `visual_compare.py`, `visual_ref.py`, `visual_scenarios.py`, `visual_auto.sh`; Referenzen aus Ryujinx (F8, Ryzen) per `ryujinx_fetch_shots.sh`; Tasten-Spieler `ryzen_keys.py` (uinput, nur bei Fokus auf Ryujinx). Phase B (Unity-Aufnahme) ist stillgelegt.
- **Analyse-Material (Unity-Zeit, weiter als Referenz nützlich):** Orakel `battle_oracle*.py`, `pokepara_oracle.py` (Unicorn führt echte ARM64-Funktionen aus), Spezifikationen `kampf-spezifikation-1…7`, `pokepara-spezifikation`, `evscript-spezifikation`, `masterdata`, `bundle-katalog`, `ui-spezifikation-1…3`.

## 5. Unity-Rebuild (deprecated, eingefroren)
Stand beim Stilllegen: 763 EditMode-Tests grün; Kampf (Handler, Ablauf, KI vollständig), Event-Interpreter (597 von 599 Host-Befehle), Spielkern, Feld, UI-Fenster über Stubs, Render-Umbau mit erzeugten Shadern (99,8 % der Varianten). Wird nicht mehr gebaut oder gepflegt; Zweck jetzt nur noch Referenz und Gegenprobe. Beide Unity-Editoren sind geschlossen.

## 6. Umgebung
| Gerät | Rolle |
|---|---|
| MacBook Pro M1 Pro, 16 GB | Hauptrechner; Generator, Mac-App, iOS-Build (Xcode 26.0.1 über `DEVELOPER_DIR`), ca. 36 GB Platz |
| Ryzen 5 7500F, 30 GB, RTX 2080 Ti, Fedora (`ssh nobara`) | Build-/Testfarm, Vulkan-Lauf, Ryujinx 1.2.78 für Referenzbilder; nur unter `~/xnu-recomp` (+ Ryujinx-Screenshots) |
| iPad Pro 12.9" (M2), iPadOS 26 | Zielgerät; Increased Memory Limit: 8 GiB statt 5 GiB (kostenloses Team, Signatur 7 Tage) |

Lokal und nie im Repo: `work/`, `tools/`, `research/`, `nsp/`, `Ryujinx/`, `Ryujinx_July23/`, `unity/Assets/XnuStubs|XnuGenerated`, `cache/`.

## 7. Offene Entscheidungen und Risiken
- **Rechtslage** vor öffentlicher Weitergabe klären (Repo enthält nur Recompiler/Runtime/Doku; erzeugtes C und Binary bleiben lokal).
- **iPad-Gerätespeicher:** volles RomFS (ca. 4–5 GB) auf dem Gerät; Strategie (voll vs. Teilmenge) in Arbeit.
- **Build-Zeit des Generats in Xcode** für iOS (ca. 1 GB C) ungemessen.
- **Free-Team-Signatur** läuft nach 7 Tagen ab.

## 8. Nächste Schritte (Reihenfolge)
1. Wasser und Innenraum in Metal beheben, dann Bildvergleich mit Ryujinx erneut.
2. iPad: Video-Absturz reproduzieren und beheben, Start zuverlässig machen, `recomp-ios.md` fertigstellen.
3. QA-Szenarien durchlaufen (Menü, Pokécenter, Kampf, Speichern/Laden, Dauerlauf), Fehlerliste in `recomp-qa.md`.
4. Touch-Steuerung und Controller auf dem iPad testen.
5. Linux-Vulkan-Lauf mit Film und Spielstand wiederholen (Mac-Fixes auf Vulkan übertragen).
6. Build-Pipeline `build_all.sh` um die Stufe `recomp-ios` ergänzen; Unity-Stufen aus dem Standardlauf nehmen.

## 9. Arbeitsweise mit Subagenten
- Große Modelle (Sonnet) für Fehlersuche und Code in Kernel/NVN/Codec; kleine (Haiku/Luna) für Läufe, Messungen, Sichtung, Doku. Höchstens zwei große Agenten gleichzeitig.
- Agenten committen nie; Tests und Commit macht der Hauptagent. Lange Läufe mit `nohup`/`setsid` + Logdatei.
