# NOTICE: Entwurf und einzelne Teile nach LASRecomp

Die Laufzeit in diesem Ordner ist **Eigenbau**, folgt aber im Entwurf der Laufzeit des Projekts LASRecomp und enthält an einigen Stellen dessen Logik in eigener Schreibweise (keine Datei wurde kopiert; der Klon `research/LASRecomp` bleibt unverändert).

| | |
|---|---|
| Projekt | LASRecomp |
| Repository | https://github.com/peiikai/LASRecomp |
| Stand | Commit `09f8e5ebf28aeefd6daa1456c73ae1b7a51efec5` (einziger Commit des Klons) |
| Urheber | Peiikai |
| Lizenz | MIT, „Copyright (c) 2026 Peiikai“. Lizenztext unverändert in [`LICENSE-LASRecomp`](LICENSE-LASRecomp). |
| Nicht übernommen | Renderer (NVN/Metal/Vulkan), UI, Randomizer, `third_party/`, Spiel-Hooks (`runtime/hle/*`) |

Die Lizenz des Originals nimmt Nintendo-Eigentum und die Drittkomponenten aus. Davon ist hier nichts enthalten. Der Nutzer des Repositories hat die Nutzung und Weiterentwicklung ausdrücklich freigegeben.

## Woher was stammt

| Datei hier | Vorbild (LASRecomp `runtime/`) | Art der Übernahme |
|---|---|---|
| `kernel.c` | `kernel.c` | Semantik von Mutex/Condvar/Address-Arbiter (`ArbitrateLock`, `WaitProcessWideKeyAtomic`, `WaitForAddress`), Handle-Tabelle, Struktur von `KThread`/`KObject`; neu: Mach-Anhalten, SVCs `0x20/0x23/0x28/0x2F/0x30/0x31/0x32/0x33/0x36/0x37/0x5F`, Host-Stack-Größe, Zähler, Speicherkarte mit `G2H` |
| `ipc.c`, `bdsp.h` (IPC-Typen) | `ipc.c`, `ipc.h` | Nachrichtenkodierung HIPC/CMIF, Domain-Verwaltung; neu: Mitschrift, Registry als Tabellen, Fehlerstub, `G2H` |
| `services.c` | `services/am.c`, `acc.c`, `hid_set.c`, `time.c`, `misc.c` | Aufbau der Antworten (Zeitdienst-Gemeinsamspeicher, Sprachlisten, Profilstruktur, Anwendungsproxy); neu: vollständige Befehlstabellen, Ereignisse, Mitschrift |
| `services_fs.c` | `romfs_build.c`, `services/fs.c` | Aufbau des RomFS-Abbilds (Kopf 0x50, Daten ab 0x200, Tabellen danach), IFileSystem/IFile/IDirectory-Befehlssatz; neu: virtuelles Abbild ohne 5-GB-Datei |
| `dispatch.c`, `loader.c`, `main.c` | `dispatch.c`, `loader.c`, `main.c` | Idee des Verteilers mit Cache und HLE-Slots, Start über `nn::init::Start`; neu: vier Tabellen, Wiedereinstieg, Überwachung |

Der Generator (`../eh_gen.py`) importiert die Werkzeuge des Klons (`research/LASRecomp/tools`) wie bisher nur zur Laufzeit.
