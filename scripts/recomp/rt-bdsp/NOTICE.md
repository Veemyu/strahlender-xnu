# NOTICE: Entwurf und einzelne Teile nach LASRecomp

Die Laufzeit in diesem Ordner folgt dem Entwurf von LASRecomp und enthält **Teile des Originals wörtlich**. Ein Abgleich (Stand 2026-10-19; Zeilen mit mindestens 25 Zeichen, Leerraum normalisiert) ergibt identische Zeilen: `kernel.c` 45 %, `ipc.c` 47 %, `services.c` 42 %, `services_fs.c` 37 %, `dispatch.c` 17 %, `bdsp.h` 19 %, `main.c` 10 %, `loader.c` 8 %. Ein Teil davon sind Konstanten und Standardmuster, der Rest ist übernommener Code. Er steht unter der MIT-Lizenz des Originals (Lizenztext in `LICENSE-LASRecomp`, bei jeder Kopie mitführen). Der Klon `research/LASRecomp` bleibt unverändert. Die Header `cpu.h`, `simd.h`, `simd_fp.h` liegen unverändert in `scripts/recomp/upstream/runtime/` (Lizenz `scripts/recomp/upstream/LICENSE`).

| | |
|---|---|
| Projekt | LASRecomp |
| Repository | https://github.com/peiikai/LASRecomp |
| Stand | Commit `09f8e5ebf28aeefd6daa1456c73ae1b7a51efec5` (einziger Commit des Klons) |
| Urheber | Peiikai |
| Lizenz | MIT, „Copyright (c) 2026 Peiikai“. Lizenztext unverändert in [`LICENSE-LASRecomp`](LICENSE-LASRecomp). |
| Nicht übernommen | UI, Randomizer, `third_party/`, Spiel-Hooks (`runtime/hle/*`); der Renderer (NVN/Metal) ab Gate 2 doch, siehe Abschnitt „NVN-Schicht“ am Ende |

Die Lizenz des Originals nimmt Nintendo-Eigentum und die Drittkomponenten aus. Davon ist hier nichts enthalten. Der Nutzer des Repositories hat die Nutzung und Weiterentwicklung ausdrücklich freigegeben.

## Woher was stammt

| Datei hier | Vorbild (LASRecomp `runtime/`) | Art der Übernahme |
|---|---|---|
| `kernel.c` | `kernel.c` | Semantik von Mutex/Condvar/Address-Arbiter (`ArbitrateLock`, `WaitProcessWideKeyAtomic`, `WaitForAddress`), Handle-Tabelle, Struktur von `KThread`/`KObject`; neu: Mach-Anhalten, SVCs `0x20/0x23/0x28/0x2F/0x30/0x31/0x32/0x33/0x36/0x37/0x5F`, Host-Stack-Größe, Zähler, Speicherkarte mit `G2H` |
| `ipc.c`, `bdsp.h` (IPC-Typen) | `ipc.c`, `ipc.h` | Nachrichtenkodierung HIPC/CMIF, Domain-Verwaltung; neu: Mitschrift, Registry als Tabellen, Fehlerstub, `G2H` |
| `services.c` | `services/am.c`, `acc.c`, `hid_set.c`, `time.c`, `misc.c` | Aufbau der Antworten (Zeitdienst-Gemeinsamspeicher, Sprachlisten, Profilstruktur, Anwendungsproxy); neu: vollständige Befehlstabellen, Ereignisse, Mitschrift |
| `services_fs.c` | `romfs_build.c`, `services/fs.c` | Aufbau des RomFS-Abbilds (Kopf 0x50, Daten ab 0x200, Tabellen danach), IFileSystem/IFile/IDirectory-Befehlssatz; neu: virtuelles Abbild ohne 5-GB-Datei |
| `dispatch.c`, `loader.c`, `main.c` | `dispatch.c`, `loader.c`, `main.c` | Idee des Verteilers mit Cache und HLE-Slots, Start über `nn::init::Start`; neu: vier Tabellen, Wiedereinstieg, Überwachung |

Der Generator (`../eh_gen.py`) nutzt die vendorten Werkzeuge in `scripts/recomp/upstream/generator/` (`gen.py`, `lifter.py`, `analyze.py`, `nso.py`, `patches.py`, `simd_c.py`; unverändert, Lizenz `scripts/recomp/upstream/LICENSE`). Nicht übernommen: der Randomizer-Anteil (`tools/rando/`), den `gen.py` nur optional lädt. `patches.py` enthält spielspezifische Hooks.

## NVN-Schicht (Gate 2, `nvn/`)

Anders als der Rest dieses Ordners **übernimmt** die Grafikschicht Quelltext des Klons, mit ausdrücklicher Freigabe des Nutzers und unter dessen MIT-Lizenz (Copyright (c) 2026 Peiikai, Lizenztext in [`nvn/upstream/LICENSE`](nvn/upstream/LICENSE)). Die Dateien liegen **unverändert** in `nvn/upstream/` (Commit `09f8e5ebf28aeefd6daa1456c73ae1b7a51efec5`, byte-identisch mit dem Klon). `nvn/prepare.sh` kopiert sie nach `work/recomp/nvn-src` und wendet die Patches `nvn/las-nvn.patch` und `fixes.patch` an; Änderungen stehen nur in den Patches, nicht in den vendorten Dateien.

| Übernommen (zur Bauzeit, mit Patch) | Nicht übernommen |
|---|---|
| `objects.c`, `cmdbuf.c`, `formats.c`, `tegra.c`, `tegra.h`, `astc.c`, `astc.h`, `nvn.h`, `renderer.m`, `renderer.h`, `metal.m`, `output_scale.h` | Vulkan-Teil (`vulkan/`), `texpatch.c` (Textur-Änderungen für ein bestimmtes Spiel), `output_scale.c`, `smaa_data.c`, alle `runtime/hle/*` (Spiel-Hooks), `ui/` (Menü), Randomizer, `third_party/` |
| `maxwell/translate.c` und `maxwell/shader.h` werden **ersetzt** durch `shader_translator/` (selbst von LASRecomp abgeleitet, siehe `../../../../shader_translator/NOTICE.md`) | |

Eigen sind `nvn/shim/*`, `nvn/nvn_glue.c`, `nvn/build_nvn.sh`, `nvn/prepare.sh` und die Patches (`las-nvn.patch`, `fixes.patch`, `debug.patch`). Die Lizenz des Originals nimmt Nintendo-Eigentum und die Drittkomponenten aus; davon ist nichts enthalten.

**Filmschicht (`nvn/movie_glue.c`):** in eigener Schreibweise nach `runtime/hle/movie.c` des Klons (Aufbau von `MediaData`, Extractor, Decoder, Ausgabeschlange und Ereignisse als Vorbild; Anpassungen für BDSP: Vtable-Slot 2, direkt importierte Aufrufe, Videospur allein, Schreiben in den Puffer des Spielers). Linkt FFmpeg (LGPL/GPL je nach Bauart, wird nicht mitgeliefert).

**Vulkan-Fassung (Linux/Windows):** übernimmt zusätzlich `runtime/nvn/vulkan/*` des Klons, ebenfalls nur zur Bauzeit und mit eigenem Patch; Einzelheiten, Drittkomponenten und Lizenzen in [`nvn/vulkan/NOTICE.md`](nvn/vulkan/NOTICE.md). (Die Zeile „Vulkan-Teil“ in der Tabelle oben gilt nur für den Metal-Weg.)
