# NOTICE: Entwurf und einzelne Teile nach LASRecomp

Die Laufzeit in diesem Ordner folgt dem Entwurf von LASRecomp und enthält **Teile des Originals wörtlich**. Ein Abgleich (Stand 2026-10-19; Zeilen mit mindestens 25 Zeichen, Leerraum normalisiert) ergibt identische Zeilen: `kernel.c` 45 %, `ipc.c` 47 %, `services.c` 42 %, `services_fs.c` 37 %, `dispatch.c` 17 %, `bdsp.h` 19 %, `main.c` 10 %, `loader.c` 8 %. Ein Teil davon sind Konstanten und Standardmuster, der Rest ist übernommener Code. Er steht unter der MIT-Lizenz des Originals (Lizenztext in `LICENSE-LASRecomp`, bei jeder Kopie mitführen). Der Klon `research/LASRecomp` bleibt unverändert. Die Header `cpu.h`, `simd.h`, `simd_fp.h` liegen unverändert in `scripts/recomp/upstream/runtime/` (Lizenz `scripts/recomp/upstream/LICENSE`).

| | |
|---|---|
| Projekt | LASRecomp |
| Repository | https://github.com/peiikai/LASRecomp |
| Stand | Commit `09f8e5ebf28aeefd6daa1456c73ae1b7a51efec5` (einziger Commit des Klons) |
| Urheber | Peiikai |
| Lizenz | MIT, „Copyright (c) 2026 Peiikai“. Lizenztext unverändert in [`LICENSE-LASRecomp`](LICENSE-LASRecomp). |
| Nicht übernommen | `third_party/` des Originals, `fonts/`, Klon-Metadaten (`.git`, Makefile, README, `docs/`). Bis zum 29.10.2026 waren Laufzeit und Generator vollständig unter `scripts/recomp/upstream/` vendort; seitdem bleiben dort nur `LICENSE`, `runtime/{cpu,simd,simd_fp}.h`, der Rest (auch die zehn `runtime/nvn`-Dateien, die zu den lokalen Kopien byte-identisch waren) steht in der Git-Historie (Commits `e43b466`, `2d01ade`, `d1c40e7`). Siehe „Woher was stammt“ und „NVN-Schicht“ |

Die Lizenz des Originals nimmt Nintendo-Eigentum und die Drittkomponenten aus. Davon ist hier nichts enthalten. Der Nutzer des Repositories hat die Nutzung und Weiterentwicklung ausdrücklich freigegeben.

## Woher was stammt

| Datei hier | Vorbild (LASRecomp `runtime/`) | Art der Übernahme |
|---|---|---|
| `kernel.c` | `kernel.c` | Semantik von Mutex/Condvar/Address-Arbiter (`ArbitrateLock`, `WaitProcessWideKeyAtomic`, `WaitForAddress`), Handle-Tabelle, Struktur von `KThread`/`KObject`; neu: Mach-Anhalten, SVCs `0x20/0x23/0x28/0x2F/0x30/0x31/0x32/0x33/0x36/0x37/0x5F`, Host-Stack-Größe, Zähler, Speicherkarte mit `G2H` |
| `ipc.c`, `bdsp.h` (IPC-Typen) | `ipc.c`, `ipc.h` | Nachrichtenkodierung HIPC/CMIF, Domain-Verwaltung; neu: Mitschrift, Registry als Tabellen, Fehlerstub, `G2H` |
| `services.c` | `services/am.c`, `acc.c`, `hid_set.c`, `time.c`, `misc.c` | Aufbau der Antworten (Zeitdienst-Gemeinsamspeicher, Sprachlisten, Profilstruktur, Anwendungsproxy); neu: vollständige Befehlstabellen, Ereignisse, Mitschrift |
| `services_fs.c` | `romfs_build.c`, `services/fs.c` | Aufbau des RomFS-Abbilds (Kopf 0x50, Daten ab 0x200, Tabellen danach), IFileSystem/IFile/IDirectory-Befehlssatz; neu: virtuelles Abbild ohne 5-GB-Datei |
| `dispatch.c`, `loader.c`, `main.c` | `dispatch.c`, `loader.c`, `main.c` | Idee des Verteilers mit Cache und HLE-Slots, Start über `nn::init::Start`; neu: vier Tabellen, Wiedereinstieg, Überwachung |

Der native Generator (`../native-generator/`) adaptiert Analyse, Lifter und Emitter aus den vendorten Werkzeugen in `scripts/recomp/upstream/generator/` (gen.py, lifter.py, analyze.py, nso.py, patches.py, simd_c.py; vollständiger Stand von `tools/`, ohne `__pycache__`, Lizenz `scripts/recomp/upstream/LICENSE`). `patches.py` enthält spielspezifische Hooks.

## NVN-Schicht (Gate 2, `nvn/`)

Anders als der Rest dieses Ordners **übernimmt** die Grafikschicht Quelltext des Klons, mit ausdrücklicher Freigabe des Nutzers und unter dessen MIT-Lizenz (Copyright (c) 2026 Peiikai, Lizenztext in [`../upstream/LICENSE`](../upstream/LICENSE)). Die Quellen liegen in `nvn/src/` (Metal) und `nvn/vulkan/src/` (Vulkan-Abweichungen), **geändert** gegenüber dem Klon (Commit `09f8e5ebf28aeefd6daa1456c73ae1b7a51efec5`). Änderungen sind direkt in den Dateien, Patches gibt es nicht mehr. Der unveränderte Stand bleibt als Vergleichsbasis in `scripts/recomp/upstream/runtime/`. Der Übersetzer kommt aus `shader_translator/`. `nvn/prepare.sh` kopiert sie nach `work/recomp/nvn-src` und wendet die Patches `nvn/las-nvn.patch` und `fixes.patch` an; Änderungen stehen nur in den Patches, nicht in den vendorten Dateien.| Übernommen (unverändert, mit Patch zur Bauzeit) | Nicht übernommen |
|---|---|
| alles unter `scripts/recomp/upstream/runtime/` (Metal, Vulkan, `hle/`, `services/`, `platform/`, `ui/`) und `scripts/recomp/upstream/generator/` (inkl. `rando/`) | `third_party/` des Originals, `fonts/`, Klon-Metadaten |
| `maxwell/translate.c` und `maxwell/shader.h` werden **ersetzt** durch `shader_translator/` (selbst von LASRecomp abgeleitet, siehe `../../../../shader_translator/NOTICE.md`) | |

Eigen sind `nvn/shim/*`, `nvn/nvn_glue.c`, `nvn/build_nvn.sh`, `nvn/prepare.sh` und die Patches (`las-nvn.patch`, `fixes.patch`, `debug.patch`). Die Lizenz des Originals nimmt Nintendo-Eigentum und die Drittkomponenten aus; davon ist nichts enthalten.

**Filmschicht (`nvn/movie_glue.c`):** in eigener Schreibweise nach `runtime/hle/movie.c` des Klons (Aufbau von `MediaData`, Extractor, Decoder, Ausgabeschlange und Ereignisse als Vorbild; Anpassungen für BDSP: Vtable-Slot 2, direkt importierte Aufrufe, Videospur allein, Schreiben in den Puffer des Spielers). Linkt FFmpeg (LGPL/GPL je nach Bauart, wird nicht mitgeliefert).

**Vulkan-Fassung (Linux/Windows):** übernimmt zusätzlich `runtime/nvn/vulkan/*` des Klons, ebenfalls nur zur Bauzeit und mit eigenem Patch; Einzelheiten, Drittkomponenten und Lizenzen in [`nvn/vulkan/NOTICE.md`](nvn/vulkan/NOTICE.md).

## Weiterer Fremdcode

`third_party/stb_truetype.h` ist stb_truetype v1.26 (Sean Barrett, gemeinfrei oder MIT nach Wahl; der Lizenztext steht am Ende der Datei) in der leicht geänderten Fassung, die Dear ImGui ausliefert. Die Bildschirmtastatur nutzt sie, um die Schriften der eigenen Firmware des Nutzers zu rastern (`swkbd_text.c`). Die Bibliothek ist nicht für fremde, unvertrauenswürdige Schriftdateien gedacht; sie liest nur die Schriften der Firmware.

