# Rekompilation, Gate 1 „Unity-Boot“ (`ap-recomp` Gate 1)

Stand: 2026-10-19. Arbeitsprotokoll mit Zwischenstand je Etappe. Grundlage: `docs/recomp-spike-2.md` (Phase 2), `docs/recomp-machbarkeit.md`, `docs/architektur-entscheidung.md`. Auftrag: Der rekompilierte BDSP-Code (`rtld`, `sdk`, `subsdk0`, `main`) soll auf dem Mac (ohne Grafik, **ohne Ton**) bis zu den ersten Logzeilen des Unity-/IL2CPP-Starts laufen, besser bis in die Spielinitialisierung (Player-Loop beginnt, Gast ruft `nvnBootstrapLoader`). Die Rekompilation läuft als eigener, paralleler Strang; der Unity-Rebuild (`unity/`, `shader_translator/`, `scripts/shader_*`) wurde nicht angefasst.

**Kennzeichnung:** **gemessen** = mit den Skripten unter `scripts/recomp/` am lokalen Dump ermittelt. *vermutet* = Schluss ohne Test. Keine Spielbytes, kein erzeugter Code und keine Spieladressen im Repo; alle Zahlen stammen aus Läufen mit dem lokalen Dump (`work/`, gitignoriert). Die Spieladressen in diesem Protokoll sind Offsets in Modulen und dienen nur der Nachvollziehbarkeit der Fehlersuche (wie in `docs/recomp-machbarkeit.md`).

## Ergebnis in Kürze

| | |
|---|---|
| **Gate 1** | **erreicht**: der rekompilierte BDSP-Code (`rtld`, `sdk`, `subsdk0`, `main`) läuft auf dem Mac ohne Grafik und ohne Ton durch `nninitStartup` und `nnMain` bis zum ersten Aufruf von `nvnBootstrapLoader` (Kriterium des Auftrags), in **0,3 bis 0,7 s**, **100 von 100 Läufen**, auch unter Anhalte-Stress (40 von 40) und mit 1 MiB Host-Stack |
| Beim Gate | 24 Threads (20 Arbeiter), 649 SVCs (23 verschiedene), 141 IPC-Anfragen (74 verschiedene (Dienst, Befehl), 19 Dienste), RomFS gemountet (11 Lesezugriffe, 12 MiB), RSS 258 MiB (davon 219 MiB per `MapPhysicalMemory`), Host-Stack 16 KiB je Thread, 0 Ausnahmen, keine Gast-Logzeile |
| Vollbau | Erzeugung 74 s, Übersetzung 699 s (4 Jobs, 2.495 Dateien, größter Compiler 1,7 GB), Link 0,6 s; inkrementell nur geänderte Chunks (feste 32-KiB-Adressfenster) |
| Gefunden und behoben | zu kleine Alias-Region, LDXP/STXP (116 Wörter), Sprungtabellen-Erkennungsfenster, **fehlende Symbol-Interposition** (`operator new/delete`), `bsd:u`-Anmeldung, Fehler in `GetEntryCount` und im Absturzbericht |
| Nächster Blocker | **NVN/Grafik** (Gate 2): der SDK-eigene NVN-Treiber stürzt nach dem ersten `nvdrv`-Ioctl ab; Weg: `nvnBootstrapLoader` und NVN-Funktionen durch Host-Funktionen ersetzen (LAS-Schicht) |

## Aufbau der eigenen Laufzeitschicht `scripts/recomp/rt-bdsp/`

Die Laufzeit des Klons (`research/LASRecomp/runtime`, MIT) bleibt unverändert und wird **nicht** gelinkt, sondern in ihrem Entwurf nachgebaut (Lizenz: `scripts/recomp/rt-bdsp/NOTICE.md`, Lizenztext `LICENSE-LASRecomp`). Wiederverwendet wird nur `cpu.h`/`simd.h` per `#include_next` (Zustandsstruktur `Cpu`, Speicher-/Flaggen-Makros). Grund: Der Klon-Kernel hat 256-MiB-Host-Stacks, kennt SVC `0x32/0x33/0x36/…` nicht, ruft Gastzeiger ohne Adressabstraktion auf und ist mit Renderer, UI und Randomizer verflochten.

| Datei | Inhalt |
|---|---|
| `bdsp.h`, `guestmem.h` | gemeinsamer Kopf, Adresslayout (Variante A/B), **`G2H()`/`H2G()`** als einzige Stelle der Adressumrechnung |
| `kernel.c` | Horizon-Kernel: Handle-Tabelle (16.384), echte Host-Threads, Mutex/Condvar/Arbiter, Speicherkarte, 36 SVCs, SVC-Zähler je Thread, Mach-Anhalten für den Boehm-GC |
| `ipc.c` | HIPC/CMIF (Domains, Steuerbefehle, Pufferdeskriptoren), Mitschrift aller (Dienst, Befehl)-Paare, Fehlerstub für unbekannte Dienste |
| `services.c` | `lm`, `apm`, `appletOE` (vollständig), `acc:u0`, `aoc:u`, `pctl*`, `ectx:aw`, `set`, `set:sys`, `time:*`, `hid` |
| `services_fs.c` | `fsp-srv`: RomFS als **virtuelles** Abbild (Tabellen im Speicher, Dateidaten per `pread` aus `work/romfs`), Speicherstände unter `work/recomp/save` |
| `services_net.c` | Fehlerstubs für Netz/Online (`nifm:u`, `bsd:u`, `bsdcfg`, `ssl`, `friend:u`, `ldn:u`, `bcat:u`, `nim:eca`, `notif:a`, `nsd:u`, `sfdnsres`, …) und Peripherie; `prepo:u`, `ldr:ro` „Erfolg ohne Daten“; `csrng` |
| `services_gfx.c` | `vi:u/s/m` und `nvdrv` als protokollierende Stubs (keine Grafikausgabe), 60-Hz-Vsync-Ereignis, „Null-GPU“-Antworten für einige `nvgpu`-Ioctls |
| `nvn_null.c`, `hle_nvn.txt` | Vorversuch für Gate 2: `nvnBootstrapLoader` und die NVN-Funktionen als wirkungslose Host-Stubs (nur mit Bildern aus `mkimages.sh` mit `HLE_LIST`) |
| `test/` | synthetische Tests: `kernel_test.c`, `romfs_test.c` (RomFS und Speicherstand-Ordner), `excl_pair_test.c`, je mit `run_*_test.sh` |
| `dispatch.c` | 4 Dispatch-Tabellen (`main`, `sdk`, `subsdk0`, `rtld`), HLE-Slots, Wiedereinstieg für Landing-Pads/`setjmp` (`rt_nle_enter`), Gate-Beobachtung, Absturzbericht |
| `loader.c`, `mkimages.sh` | lädt die mit `mkimg.py` gebauten Modulbilder (Relokationen und Modulquerverweise angewandt) |
| `main.c` | Fensterreservierung, Start von `nn::init::Start`, Überwachung, Ergebnisprotokoll |
| `build.sh` | baut die Laufzeit inkrementell und bindet sie mit den Modulobjekten zu `work/recomp/bdsp_boot` |

**Audio:** kein Ton, keine Ausgabe. `audren:u`, `audout:u`, `audin:u`, `hwopus` liefern Fehlerstubs (der Dienst `audren:u` wird erst bei Bedarf als stummer Stub ausgebaut, siehe Etappe 6).

## Etappe 1: Abbruch aus Phase 2 beheben

**Befund Phase 2** (`run_boot_probe_las.sh`, LAS-IPC-Schicht gelinkt): `svcBreak` nach den nicht behandelten `am`-Befehlen. Aus dem Lauf:

| Dienst/Objekt | Befehl | Bedeutung | Folge ohne Antwort |
|---|---:|---|---|
| `ISelfController` | 91 | `GetAccumulatedSuspendedTickChangedEvent` | das SDK erwartet ein Ereignis-Handle in der Antwort; ohne Handle bricht `nn::os::AttachReadableHandleToSystemEvent` ab (`svcBreak`, Grund 0) |
| `ICommonStateGetter` | 900 | `SetCpuBoostRequestPriority` | harmlos, aber unbehandelt |

Die eigene Schicht beantwortet **alle** `ICommonStateGetter`-, `ISelfController`-, `IApplicationFunctions`-, `IWindowController`-Befehle, die das SDK in Phase 2 und in diesem Lauf stellt; Befehle mit Ereignis-Ausgabe (`0, 13, 61`, `9, 91`, `130, 140, 150, 160`) liefern echte Kernel-Ereignisse. Danach läuft das SDK durch `sm:` → `lm` → `apm` → `appletOE` → `pctl`, `pctl:s/a/r` → `aoc:u` → `ectx:aw`.

**Weitere Hindernisse, nacheinander gefunden und behoben** (jeweils mit Ursache; Details in den Etappen 2 und 3):

| # | Symptom | Ursache | Behebung |
|---|---|---|---|
| 1 | `nn::diag::Abort` in `StandardAllocator::Initialize` (aus `nninitStartup`) | BDSP verlangt in `nninitStartup` fast den gesamten Anwendungsspeicher (Ergebnis aus `GetInfo`: 3,14 GB) als **einen** Bereich und holt ihn per `MapPhysicalMemory` aus der **Alias-Region**; die Alias-Region der ersten Laufzeitfassung (4 GiB nach dem LAS-Vorbild) war zu klein: abzüglich Module/Heap/Stack blieb kein 3,14-GB-Loch | Alias-Region 6,25 GiB, Heap-Region 3,25 GiB, Stack-Region 512 MiB, Module/HLE/TLS unten (Layout in `bdsp.h`) |
| 2 | `rt_udf` in `main` (`ldxp x10, x11, [x0]`) | LDXP/STXP/LDAXP/STLXP nicht im Lifter (58 Schleifen, 116 Wörter) | Lifter-Erweiterung `excl_pair()` in `eh_gen.py` + Hilfen `ldxp64/stxp64/ldxp32/stxp32` in `rt/cpu.h`, Test `rt-bdsp/test/excl_pair_test.c` |
| 3 | „kein Gastcode bei …“ in `main` (Sprung mitten in eine Hash-Funktion) | Byte-Offset-Sprungtabelle `adr xD, <erster Fall>; ldrb w,[tab,idx]; add xD,xD,w,lsl #2; br xD` mit 11 Wörtern Abstand zwischen `adr` und `br`; das Erkennungsfenster der Korrektur aus Phase 2 war 8 Wörter | Fenster 24 Wörter (`is_jumptable_base_adr`); 12 weitere Tabellen in `main` richtig geschnitten (2.231 statt 2.219) |
| 4 | `nn::socket::Initialize` bricht ab (Abbruch in `InitializeCommon`) | `bsd:u` meldete beim Anmelden (`RegisterClient`) einen Fehler | `bsd:u`: Anmeldung gelingt, jeder Socket-Aufruf liefert `-1`/`ENETDOWN` |
| 5 | Heap-Prüfung `nnmem_nlib_debug_break` beim Freigeben einer `std::string` des Spiels (`TlsHeapCentral::UncacheSmallMemory_`) | **Symbol-Interposition fehlte im Lader:** `operator new/delete` kommen in `main` **und** im SDK vor; die ausführbare Datei gewinnt beim echten rtld (ELF-Interposition), `mkimg.py` band die SDK-Verweise an die eigene Definition. Das SDK-`std::string` gab so mit dem SDK-`delete` einen Zeiger frei, den das Spiel mit seinem Allokator (16-Byte-Kopf) angelegt hatte | `mkimg.py --interpose-from main.syms.json`: `operator new/delete/new[]/delete[]` (und `typeinfo`) der anderen Module gehen an die Definition von `main` (39 Bezüge im SDK, 6 in `subsdk0`) |
| 6 | Absturzbericht endete mit `SIGTRAP` | Eigener Fehler: `rt_fatal_trace` war als `noreturn` deklariert, kehrt aber zurück (Compiler setzte `brk`) | Attribut entfernt; Bericht wird aus dem Hauptthread in normalem Kontext erstellt |

**Ergebnis Etappe 1: bestanden.** Der Gast durchläuft `nninitStartup`, alle 115 Konstruktoren des SDK und 417 des Spiels, erreicht `nnMain`, mountet das RomFS und ruft `nvnBootstrapLoader` auf (siehe Ergebnisprotokoll, Gate-Status).

## Etappe 2: SVCs, Threads, Heap, Tabellen, LDXP, RomFS/SaveData

| Punkt | Stand | Beleg |
|---|---|---|
| SVC `0x32` SetThreadActivity / `0x33` GetThreadContext3 | umgesetzt mit Mach `thread_suspend/resume` auf dem Host-Thread; der Kontext (x0..x30, sp, Vektorregister, tpidr) kommt aus `Cpu` (Spike: 100 % der Anhaltefenster allein dort). Im Gate-Lauf kam dieselbe Folge **zweimal vom Spiel selbst**: Anhalten, Kontext lesen, Fortsetzen, einmal vom Thread 82 (Priorität 59) auf den Hauptthread und einmal vom Hauptthread auf Thread 82, jeweils Ergebnis 0, beide Threads liefen danach weiter | `test/kernel_test.c`: Thread startet, Zähler steht nach dem Anhalten still (30 ms), Kontext liefert `x19` und den Zählerstand, Fortsetzen funktioniert |
| SVC `0x36` SynchronizePreemptionState, `0x28` ReturnFromException, `0x2F`, `0x23`, `0x20`, `0x5F`, `0x2A/0x2B`, `0x30/0x31/0x37` | `0x36`, `0x5F`, `0x2A/B`, `0x30/31/37`: Leerlauf mit Erfolg; `0x28`: `FATAL` (im Spiel nur in `rtld`); `0x2F`, `0x23`, `0x20`: Fehlercode `0xDC01` (nicht implementiert) mit Meldung. **Im Gate-Lauf wurden `0x23`, `0x28`, `0x2F`, `0x20`, `0x36` nicht aufgerufen** (23 verschiedene SVCs, 654 Aufrufe) | SVC-Zähler im Ergebnisprotokoll |
| SVC `0x2C/0x2D` (`MapPhysicalMemory`) | ohne Nullen des Speichers (die Fensterseiten sind frisch und werden erst beim Zugriff belegt); `0x2D` verwirft per `mmap(MAP_FIXED)`. Vorher löste ein `memset` von 3,14 GB sofort 3 GB RSS aus (vermieden) | 157 Aufrufe, **219 MiB** abgebildet, RSS 258 MiB am Gate |
| Boehm-GC-Suspend-Pfad | Mechanik wie im Spike (Abschnitt 2 von `docs/recomp-spike-2.md`). **Anhalte-Stresstest gegen den Boot** (`BDSP_SUSPEND_STRESS=1`: ein Host-Thread hält alle Gastthreads reihum an, liest den Kontext und setzt sie fort, alle 200 µs): 2.300 bis 4.000 Zyklen je Lauf, auch mitten in IPC/SDK-Code und am Hauptthread, **40 von 40 Läufen** erreichen das Gate (ohne Stress 100 von 100). Ein Allokations-/GC-Stresstest des Spiels selbst ist erst möglich, wenn der Player-Loop läuft | `main.c` (`suspend_stress`), Ergebniszeile „Anhalte-Stresstest“ |
| Threads und Stack-Größen | Host-Stack je Gastthread **1 bis 16 MiB** (Umgebung `BDSP_HOST_STACK_MB`, Standard 16; Läufe mit 1 und 2 MiB erreichen das Gate unverändert). **Gemessen belegt: 16 KiB je Thread** (`mach_vm_region`, `pages_resident`) bei 24 Threads. Gast-Stack: 1 MiB Hauptthread (NPDM), Stacks der übrigen Threads vergibt das SDK | `kernel_report` im Ergebnis |
| TLS | je Thread ein Block `tpidrro` zu 0x200 Byte ab `TLS_BASE` (2 MiB = 4.096 Threads); `tpidr` bleibt 0 bis der Gast ihn setzt | 24 Threads laufen |
| Heap-Wert (`SetHeapSize`) | **`SetHeapSize` wird von BDSP bis zum Gate nie aufgerufen.** Der Anwendungsspeicher kommt vollständig über `MapPhysicalMemory` (Alias-Region). `GetInfo(TotalMemorySize)` = 3,14 GB (Wert wie auf der Konsole); `nninitStartup` verlangt `Total − Used` = **3,14 GB** als einen Bereich | Layout-Befund in Etappe 1/4 |
| 3 Dispatch-Tabellen (+ `rtld`) | `main` 218.098, `sdk` 38.289, `subsdk0` 13.689, `rtld` 43 Funktionen (nach der Sprungtabellen-Korrektur) | `dispatch.c` |
| LDXP/STXP/LDAXP/STLXP | im Lifter (`eh_gen.py`, 116 Wörter in `main`) und in `rt/cpu.h` (Hilfen), `rt32/cpu.h` über `GPTR`; 128-Bit-Zählschleife mit 4 Threads x 50.000 Schritten stimmt | `test/excl_pair_test.c` |
| RomFS | **virtuelles Abbild:** Tabellen im Speicher (879 KiB für 18.022 Dateien und 145 Ordner), Dateidaten per `pread` aus `work/romfs` (4.826 MiB Daten), kein 5-GB-Abbild; Zugriffe vom Spiel bis zum Gate: 11 Lesezugriffe, 12 MiB (3 Dateien, Unity-Standarddateien der Ebene 0) | `test/romfs_test.c`: 8 erfundene Dateien, Suche wie im Spiel über Hash-Tabellen, Inhalte und Größen, Lesen über Dateigrenzen |
| SaveData | `fsp-srv` 51/52/53 hängt Host-Ordner `work/recomp/save/save_<typ>` ein (nie im Repo); vom Spiel bis zum Gate nicht angefordert | synthetisch getestet (`test/romfs_test.c`, nach dem RomFS-Teil: Datei anlegen, doppeltes Anlegen = Fehler, schreiben, lesen, Größe, `SetSize`, Typ, umbenennen, Verzeichnis zählen und lesen, löschen). Der Test fand einen Fehler (GetEntryCount verstellte die Leseposition des Verzeichnisstroms auf macOS), behoben |
| NCA-Mount | entfällt: das Spiel liest das RomFS über `OpenDataStorageByCurrentProcess` (Befehl 200) als Speicherabbild; `OpenDataStorageByDataId`/Patch liefern „nicht vorhanden“ | IPC-Mitschrift |

## Etappe 3: Exception-Mechanik produktiv

| Punkt | Stand |
|---|---|
| Landing-Pad-Einsprünge | `rt_nle_enter` in `dispatch.c` (innerster Rahmeneintrag, dessen Bereich die Adresse enthält und dessen Eintritts-SP über dem Ziel-SP liegt; `_longjmp`), mit Zählern für Wiedereinstiege und abgewickelte Host-Rahmen. Im Gate-Lauf kein Wiedereinstieg (0), also auch keine Ausnahme des Spiels bis dahin |
| `QueryMemory` mit Modulsegmenten | Der Lader trägt Text (Typ 3, Recht 5), Rodata (3, 1) und Daten (4, 3) jedes Moduls in die Speicherkarte ein; `GetExceptionInfo` des SDK findet damit `MOD0`/`eh_frame_hdr` |
| Mehrthread-Mutex des FDE-Caches | echter SDK-Code über die Arbiter-SVCs des Kernels; Test: zwei Threads, 4.000 Sperrungen, kein Verlust (`kernel_test.c`) |
| `ExitThread` mit offenen Rahmen | `longjmp` auf den Sprungpunkt von `thread_main`; Test: nach `ExitThread` läuft nichts mehr, Thread-Objekt wird signalisiert |
| 17 Wiedereinstiegsstellen hinter `bl setjmp` (`main`; 10 im SDK) | Der Generator findet sie (`setjmp_returns: 17` in `main`, 10 in `sdk`). **Test der Mechanik synthetisch** (`test/eh_guest.cpp`, Test T7: eigene `setjmp`/`longjmp` nach AAPCS64, `longjmp` aus 3 + 20 Rahmen, zweimal hintereinander, Destruktoren laufen nicht, Rahmenkette danach leer, Rückgabe und Callee-Saved-Register stimmen). **Die 17 echten Stellen wurden im Gate-Lauf nicht erreicht** (0 Wiedereinstiege); sie werden erst vom laufenden Spiel getestet |
| Regression | T0 bis T6 des Exception-Tests aus Phase 2 bestehen unverändert mit der neuen Chunk-Einteilung und der verbreiterten Sprungtabellenerkennung (T6: 45,8 µs je Wurf und Fang) |


## Etappe 4 (vorgezogen): Speichermodell, Entscheidung und Abstraktion

**Entscheidung:** Für Gate 1 gilt **Variante A**: ein festes 12,5-GiB-Fenster bei `0x70_0000_0000` (`mach_vm_allocate`, `VM_FLAGS_FIXED`, früh in einem Konstruktor, bevor der Host-Allokator das Fenster belegt), **Gastadresse = Hostadresse**. **Variante B** (`--rebase32`, alle Gastadressen < 4 GiB, Zugriff `g_base + (uint32_t)ea`) bleibt der iPad-Weg und gehört zu Gate 2.

**Wie die Laufzeit beide trägt (jetzt umgesetzt):**

| Ebene | Variante A | Variante B |
|---|---|---|
| erzeugter Code | `LD8..ST64`, `ldx*/stx*`, `ldxp*/stxp*` aus `cpu.h` mit `(uintptr_t)` | gleicher Code, aber `-I scripts/recomp/rt32` vor `rt/`: `rt32/cpu.h` ersetzt die Makros durch `*(T*)(g_base + (uint32_t)ea)`, `GPTR(a)` für die Exklusiv-Paare; FP/SIMD im C-Modus (`--simd c`) |
| Host (Kernel, IPC, Dienste, Lader) | **ausschließlich** `G2H(a)`/`H2G(p)` aus `rt-bdsp/guestmem.h`: A = Identität, B = `g_base + (uint32_t)a` (Schalter `-DBDSP_REBASE32`, `build.sh -DBDSP_REBASE32`) | dasselbe; alle Laufzeitdateien bestehen die Syntaxprüfung mit `-DBDSP_REBASE32 -I scripts/recomp/rt32` (nur Übersetzung geprüft). **Offen für Gate 2:** Reservierung des 4-GiB-Fensters und Setzen von `g_base` in `main.c` (heute nur Variante A), Lauf mit Variante-B-Modulen |
| Adresslayout | `bdsp.h`, Block A (12,5 GiB) | `bdsp.h`, Block B: Module, HLE, Stacks, Alias und Heap unterhalb von 4 GiB (nur als Layout festgehalten, **ungetestet**) |
| Module | `mkimages.sh` mit den Basen von `gen_all.sh` | Neuerzeugung mit Basen < 4 GiB (`gen_all.sh`/`mkimages.sh` über `base_of`) |

Regel für alle Host-Quellen: **keine** Umwandlung nach `uintptr_t` außerhalb von `guestmem.h`; jede Gastadresse (Register, IPC-Puffer, Tabellen im Gastspeicher) geht durch `G2H`, jeder Zeiger in den Gastspeicher, der an den Gast zurückgeht, durch `H2G`. `grep -n "uintptr_t" scripts/recomp/rt-bdsp/*.c` zeigt nur noch Ausrichtungsrechnungen auf IPC-Nachrichten (relativ zum Nachrichtenanfang, daher modellneutral).

**Befund aus Gate 1, der Variante B betrifft:** Das SDK von BDSP holt in `nninitStartup` den gesamten Anwendungsspeicher (3,14 GB) als **zusammenhängenden** Bereich per `MapPhysicalMemory` aus der Alias-Region (siehe Etappe 1, Hindernis 1). In einem 4-GiB-Fenster (Variante B) ist das nicht darstellbar, **ohne dass `GetInfo(TotalMemorySize/UsedMemorySize)` der Kernelschicht kleinere Werte meldet**. Gate 2 muss deshalb den Anwendungsspeicher, den die Kernelschicht dem Gast meldet (Info-IDs 6/7/21/22), auf einen Wert begrenzen, der samt Modulen, Stacks und Host-Seite in 4 GiB passt (Zielbereich *vermutet* 2,0 bis 2,5 GB; der Unity-Heap von BDSP hängt vom gemeldeten Wert ab, das ist **nicht verifiziert**). Das ist ein Parameter der Kernelschicht, kein Umbau; ob Unity mit weniger Speicher startet, zeigt erst Gate 2. Gemessen ist nur: bis zum Gate sind 219 MiB der 3,14 GB belegt.

## Etappe 5: Volle Erzeugung und Übersetzung der vier Module

**Neu gegenüber Phase 2** (`scripts/recomp/`):

| Änderung | Zweck |
|---|---|
| `eh_gen.py --window 0x8000` (Standard) | Chunk-Grenzen alle 32 KiB Gastcode statt nach laufender Nummer; Dateinamen `<modul>_<fenster>_<n>.c`. Ändert sich eine Funktion, bleiben **alle anderen Chunks unverändert** (vorher verschob sich die Nummerierung, die Korrektur der Sprungtabellenerkennung hatte 823 von 1.046 Dateien verändert) |
| `regen_inc.sh` | erzeugt nach `gen4.new`, überträgt per `rsync --checksum` nur Dateien mit geändertem Inhalt nach `gen4`, entfernt veraltete Chunks |
| `build_all.sh` | entfernt Objekte ohne Quelldatei (sonst doppelte Symbole nach geänderter Einteilung), sonst unverändert (nur Chunks, deren Objekt älter als die Quelle ist) |
| `rt-bdsp/build.sh` | baut die Laufzeit (alle `rt-bdsp/*.c`, nur bei Änderung) und linkt mit `obj4/*.o` zu `work/recomp/bdsp_boot` |
| `mkimages.sh` | Bilder der Module (`mkimg.py`, jetzt mit Interposition von `operator new/delete`) |

**Messung** (4 parallele Compiler, geteilte Maschine mit Last 12 bis 19, 16 GB RAM, `clang -O1`, Einzelfunktionen über 1 MB C mit `-O0`):

| Messwert | Ergebnis |
|---|---|
| Erzeugung (Python, ein Kern) | **74 bis 90 s** gesamt: `main` 62 s (Spitze 3,7 GB RAM), `sdk` 7,4 s, `subsdk0` 4,1 s, `rtld` 0,1 s |
| Chunks (Dateien) | `main` 1.956, `sdk` 305, `subsdk0` 229, `rtld` 1, dazu 4 Tabellendateien: **2.495 Dateien** (2.485 mit `-O1`, 10 mit `-O0`), 995 MB C |
| Übersetzung, vollständig | **699 s = 11,7 min** Wanddauer, Summe der Einzelzeiten 2.707 s (45 min CPU); die längste Datei 201 s (674 MB RSS), größter Speicherbedarf **1.676 MB** (Datei mit 1,6 GB: eine Einzelfunktion), nie mehr als vier Compiler gleichzeitig |
| Objekte | 277 MiB, Programm `bdsp_boot` mit Laufzeit 224 MiB (Datei) |
| Link | **0,6 s** inklusive Laufzeitübersetzung |
| Inkrementell: Neuerzeugung ohne Änderung | **0 geänderte Dateien** in allen vier Modulen (Erzeugung deterministisch), danach `build_all.sh` ohne Übersetzung (10 s nur zum Durchsehen der Dateiliste) |
| Inkrementell: Erweiterung des Lifters (LDXP/STXP) | 2 geänderte Chunks in `main`, **8 s** Übersetzung (gemessen vor der Fenstereinteilung; die Erzeugung selbst bleibt bei 74 s) |
| Plattenplatz | `df` vor/nach: 27 GB → 35 bis 36 GB frei (gelöscht: `work/recomp/gen`, `gen32`, `libgame_probe.dylib`, `boot_probe*`; Zwischenartefakte `gen4.new` nach jedem Lauf); ≥ 15 GB zu jedem Zeitpunkt |

Das **Dauerziel „Bauzeit unter 30 min“** aus Phase 1 gilt weiter erfüllt (11,7 min bei 4 Jobs auf stark ausgelasteter Maschine). Eine neue Erzeugung kostet jedes Mal mindestens 74 s (Generator ist nicht inkrementell), die Übersetzung danach nur die geänderten Chunks.

**Hinweise für andere Hosts und Nutzer von `eh_gen.py`:** (1) `--window 0` schaltet die Fenstereinteilung ab (Chunks nur nach Größe, Namen `<modul>_00000_<n>.c`). (2) Die Exklusiv-Paar-Hilfen in `rt/cpu.h` nutzen 128-Bit-Atomics (`unsigned __int128`): auf arm64 inline, auf x86-64 braucht der Compiler `-mcx16` (sonst Aufruf von `__atomic_*_16` aus libatomic) und der Test `excl_pair_test.c` ist nur auf arm64 geprüft. (3) Der Rechner-Lauf auf dem Ryzen (`docs/recomp-ryzen.md`, anderer Strang) ist von diesen Änderungen nicht gemessen worden.

## Etappe 6: Ergebnisprotokoll

Lauf: `BDSP_TIMEOUT=60 work/recomp/bdsp_boot` (Standard `BDSP_STOP_AT_GATE=1`; Ausgabe des Ergebnisprotokolls durch `main.c`; Mehrfachläufe 0,3 bis 0,7 s bis zum Gate, 3 Läufe mit 1, 2 und 16 MiB Host-Stack gleich).

| Messwert | Ergebnis |
|---|---|
| **Gate-Status** | **Gate 1 erreicht**: der Gast ruft `nvnBootstrapLoader` auf (erste Beobachtung durch den Verteiler, `lr` in `main`; Argument ein Zeiger auf einen Namen der NVN-Funktionsliste), nach **0,3 bis 0,7 s** |
| Weg dorthin | `nn::init::Start` → `nnosInitialize` → 115 SDK-Konstruktoren → `nninitStartup` (Allokator) → 417 Konstruktoren des Spiels → `nnMain` → `nn::vi::Initialize`, Zeit-/Dateisystem-/HID-Dienste, **RomFS gemountet und gelesen** (Unity-Standarddateien der Ebene 0), `nn::socket::Initialize`/`nn::nifm`/`ssl` (Fehlerstubs), 22 weitere Threads → `nvnBootstrapLoader` |
| Letzte Logzeile des Gastes | **keine**: es gab bis dahin keine `lm`-Zeile und keinen `OutputDebugString` (die Release-Fassung von Unity schreibt nichts). Die Logzeilenkanäle sind angeschlossen (`lm:ILogger` und SVC `0x27`, Zähler im Protokoll) |
| Letzter SVC | Hauptthread am Gate: `MapPhysicalMemory` (570 SVCs, 141 IPC bis dahin); nach dem Gate (Lauf ohne Gate-Stopp) `SendSyncRequest` auf `nvdrv` (erste Anfragen des NVN-Treibers, siehe unten) |
| SVCs | 23 verschiedene, 649 Aufrufe: `MapPhysicalMemory` 157, `SendSyncRequest` 141, `QueryMemory` 111, `StartThread/CreateThread` je 23, `MapMemory` 23, `WaitProcessWideKeyAtomic` 24 (22 Arbeiter warten), `SetThreadCoreMask` 42, `SetThreadPriority` 17, `GetInfo` 22 |
| Threads | **24** angelegt und lebend: Hauptthread (Priorität 44, Kern 0), 1 SDK-Thread (Priorität 28, Kern 3), 1 Thread Priorität 59, 1 Thread Priorität 29 (Kern „beliebig“), **20 Arbeiter mit Priorität 44** (Kern 0). 22 davon warten auf Bedingungsvariablen (Arbeitsschlange der Job-Threads von Unity) |
| Handles | 72 (Spitze 72) |
| RSS | **257 bis 263 MiB** (davon 219 MiB per `MapPhysicalMemory` abgebildet und belegt; Module 101 MiB) |
| Host-Stack | 16 KiB je Thread belegt (24 Threads) |
| IPC | 141 Anfragen, **74 verschiedene (Dienst, Befehl)**; nicht umgesetzt (Standardantwort): nur `IParentalControlService` 1 und `ICommonStateGetter` 66 (beide folgenlos) |
| Angefragte Dienste (in Reihenfolge) | `lm`, `apm`, `appletOE`, `aoc:u`, `ectx:aw`, `pctl`, `pctl:s`, `pctl:a`, `pctl:r`, `time:u`, `fsp-srv`, `nvdrv`, `vi:m`, `vi:s`, `vi:u`, `nifm:u`, `bsd:u`, `ssl`, `hid` (19 der 47 NPDM-Dienste) |
| Fehlerstubs, die der Gast hinnahm | `nifm:u` (Befehl 5), `ssl` (Befehl 5); `bsd:u` meldet `RegisterClient` als Erfolg und verwirft alles weitere |
| Wiedereinstiege (Exceptions/`longjmp`) | 0: das Spiel warf bis dahin keine Ausnahme und keinen `longjmp` |
| RomFS | 11 Lesezugriffe, 12 MiB |
| Exception-/Kernel-/Dienst-Tests | `run_excl_test.sh`, `run_kernel_test.sh`, `run_romfs_test.sh`, `run_eh_test.sh` (T0 bis T7): alle bestanden |

**Befund zum „Unity-Start“:** Bis zu `nvnBootstrapLoader` laufen Unitys Plattformschicht, der 24-Thread-Pool und der Dateizugriff (`globalgamemanagers`, `globalgamemanagers.assets`, `resources.assets.resS`). Dass der Player-Loop beginnt, ist **nicht** gemessen: Unity initialisiert die Grafik vor dem ersten Frame, der Gast bleibt an der Grafik hängen. Das Gate-Kriterium „erste `nvnBootstrapLoader`-Aufrufe“ ist erfüllt. IL2CPP-Metadaten (`global-metadata`) wurden bis dahin nicht gelesen.

### Was nach dem Gate passiert (`BDSP_STOP_AT_GATE=0`)

Der Gast öffnet `/dev/nvhost-ctrl-gpu` über `nvdrv` und stellt als ersten Ioctl `0xC0B04705` (176 Byte, `GET_CHARACTERISTICS`); danach bricht die NVN-Initialisierung durch einen Nullzeiger im SDK-eigenen NVN-Treiber ab (`SIGSEGV` bei Adresse 0, Gast im NVN-Teil des SDK, Aufrufer `nnMain`). Der Absturz bleibt **unverändert**, wenn der Stub den Ioctl mit plausiblen Kennwerten beantwortet (`services_gfx.c`, „Null-GPU“: `GET_CHARACTERISTICS` mit GM20B-Werten, `nvmap` CREATE/FROM_ID/GET_ID/PARAM, `as-gpu` ALLOC_SPACE/MAP_BUFFER_EX/GET_VA_REGIONS; alle anderen Ioctls: Eingabe zurückgeben, Erfolg, **ungeprüfte Layouts aus dem Gedächtnis**). Der Zeiger kommt aus einer Struktur im Gast-Heap (`[x4+8]` in einer Funktion des NVN-Treibers), nicht aus der Ioctl-Antwort. Das ist erwartet: der echte NVN-Treiber im SDK braucht entweder einen vollständigen Emulator für die `nvhost-*`-Ioctls (Umfang eines GPU-Treibers, nicht empfohlen) oder (Weg von LAS und Gate 2) den Austausch von `nvnBootstrapLoader` und der NVN-Funktionen durch Host-Funktionen. Der erste Aufruf war `nvnBootstrapLoader("nvnDeviceGetProcAddress")`: Unity holt sich die NVN-Funktionen wie bei LAS über diesen Namen.

### Vorversuch: NVN-Funktionen als Host-Stubs (`nvn_null.c`, `hle_nvn.txt`)

Zur Einordnung des nächsten Blockers wurde `nvnBootstrapLoader` per `mkimages.sh` (`IMG=work/recomp/img_nvn HLE_LIST=scripts/recomp/rt-bdsp/hle_nvn.txt`) an einen Host-Slot gebunden (der Mechanismus `mkimg.py --hle-list` funktioniert; Lauf mit `BDSP_IMG=work/recomp/img_nvn BDSP_STOP_AT_GATE=0 BDSP_TRACE_NVN=1`). Jede NVN-Funktion, die Unity über `nvnBootstrapLoader("nvnDeviceGetProcAddress")` und `nvnDeviceGetProcAddress` holt, ist ein Stub ohne Wirkung mit Rückgabe 0. Befund:

| | |
|---|---|
| Aufrufe vor dem Absturz | 16: `nvnDeviceGetInteger` (Enum 0 und 1, Versionsabfrage; der Stub schreibt nichts), `nvnDeviceBuilderSetDefaults/SetFlags`, `nvnDeviceInitialize` (Rückgabe 0 = „gescheitert“), `nvnDeviceSetWindowOriginMode`, `nvnDeviceSetDepthMode`, 5 x `nvnQueueBuilder*`, `nvnQueueInitialize`, `nvnQueueSetDebugLabel` mit Warteschlange `NULL` |
| Verhalten von Unity | **prüft die Rückgabewerte nicht** und macht mit unbrauchbaren Objekten weiter; zusätzlich fragt es `ISelfController` Befehl 44 (`CreateManagedDisplaySeparableLayer`, vom Stub nicht umgesetzt). Danach `SIGSEGV` (Adresse 0x18) im Fensterteil des SDK (`nn::vi`/Native Window) |
| Schluss | Es gibt **keine Fehlermeldung** von Unity, die ein Log erzeugt, und der Player-Loop wird ohne ein echtes NVN (Rückgaben, Ausgabeparameter, Objektzustand) nicht erreicht. Gate 2 braucht deshalb eine funktionierende NVN-Schicht mit den Werten der Konsole (`nvnDeviceGetInteger` für alle Enums, `nvnDeviceInitialize` = wahr, Fenster/Texturen/Queue); die LAS-Schicht liefert das Vorbild |

## Nächste Blocker (Reihenfolge, Aufwand als Schätzung)

| # | Blocker | Wirkung | Aufwand (Schätzung, Einzelentwickler) |
|---|---|---|---|
| 1 | **NVN/Grafik**: `nvnBootstrapLoader` und die ca. 495 NVN-Funktionen durch Host-Funktionen ersetzen (LAS-Schicht `runtime/nvn`, 9,5 kZeilen, Gate 2) oder `nvhost-*`-Ioctls emulieren | Voraussetzung für jeden Frame und für den Player-Loop | 3 bis 6 Wochen (Phase-2-Schätzung; Unity-spezifische Nutzung ungeprüft) |
| 2 | **`--hle-list` für die NVN-Namen** | Mechanismus erprobt (Vorversuch oben); für Gate 2 fehlt die Namensliste der NVN-Funktionen (Quelle: `work/recomp/nvn_names.json`, 524 Namen) und die Host-Implementierung | 1 Tag für die Liste |
| 3 | **Audio** (`audren:u`, `hwopus`, Wwise): bisher nicht angefragt; stummer Stub ist Pflicht, sobald der Gast `audren:u` öffnet (`RequestUpdate` braucht gültige Antwortstruktur) | Wwise-Initialisierung | 2 bis 4 Tage (stumm), nur Stub |
| 4 | **Speichermodell B** (iPad): Kernelschicht muss weniger Anwendungsspeicher melden (Info-IDs 6/7/21/22); ob Unity damit läuft, ist offen | iPad-Weg | 1,5 bis 3 Wochen (Phase-2-Schätzung) |
| 5 | **Exceptions/GC im laufenden Spiel**: die 17 `setjmp`-Stellen und die Landing-Pads wurden noch nicht vom Spiel erreicht; Boehm-GC-Stresstest und Dauertest (1 Stunde) | Entscheidungskriterium aus `docs/recomp-spike-2.md` Abschnitt 6.2 | 3 bis 5 Tage nach Blocker 1 |
| 6 | **Bildzeit** (Ziel 16,7 ms), Leistung der rekompilierten Funktionen | Entscheidungskriterium (b) | offen, erst mit Grafik messbar |
| 7 | restliche Dienste der NPDM-Liste (28 von 47 noch nicht angefragt): `hid` mit Eingabestatus im Gemeinsamspeicher, `acc:u0`-Profile, `set`, `mm:u`, `caps:*`, `nfc/nfp`, … | je nach Aufruf des Spiels | je Dienst Stunden bis 1 Tag |

## Reproduktion

```
scripts/recomp/gen_all.sh            # oder regen_inc.sh: erzeugt/aktualisiert work/recomp/gen4
scripts/recomp/build_all.sh 4        # Module übersetzen (inkrementell), höchstens 4 Compiler
scripts/recomp/rt-bdsp/mkimages.sh   # Modulbilder (Relokationen, Interposition) nach work/recomp/img
scripts/recomp/rt-bdsp/build.sh      # Laufzeit bauen und zu work/recomp/bdsp_boot linken
work/recomp/bdsp_boot                # Lauf: BDSP_TIMEOUT, BDSP_STOP_AT_GATE, BDSP_TRACE_SVC, BDSP_TRACE_IPC, BDSP_FNPROF, BDSP_RING,
                                     # BDSP_DUMP, BDSP_LOG_FILES, BDSP_HOST_STACK_MB, BDSP_ROMFS, BDSP_SAVE, BDSP_LANG
scripts/recomp/rt-bdsp/test/run_{excl,kernel,romfs}_test.sh ; scripts/recomp/test/run_eh_test.sh
```

Lizenzhinweis zur Laufzeit: `scripts/recomp/rt-bdsp/NOTICE.md`, Lizenztext `scripts/recomp/rt-bdsp/LICENSE-LASRecomp`. Der Klon `research/LASRecomp` wurde nicht verändert.

