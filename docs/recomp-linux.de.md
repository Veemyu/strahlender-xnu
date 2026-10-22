# Historischer Linux-Build-Bericht

**English version: [recomp-linux.md](recomp-linux.md)**

> **Status:** Der Linux-Rechner und der SSH-/rsync-Ablauf der Messungen existieren nicht mehr. Linux-Builds laufen nur noch lokal vom Repo-Hauptverzeichnis aus, mit den Skripten in `scripts/recomp/linux/local/` (siehe [BUILD.md](BUILD.md), Abschnitt 6). Die Zahlen unten sind historische Referenzwerte vom 2026-10-19.

# Linux als Build- und Testrechner für die Rekompilation

Messungen vom 2026-10-19, von 10:48 bis 12:20 Uhr; der Generatorstand je Lauf steht in den Abschnitten 4 und 5. Grundlage: `docs/recomp-spike-2.md` (Phase 2, Mac-Zahlen), `docs/recomp-gate1.md` (Arbeitsstand `ap-recomp-3`), `research/LASRecomp` (MIT, nur gelesen/zur Laufzeit importiert).

**Kennzeichnung:** **gemessen** = mit den Skripten unter `scripts/recomp/linux/` auf dem Linux-Rechner ermittelt (Rohzahlen in den Protokollen `*.stats` und `*.times`). *vermutet* = Schluss ohne Test. Im Repo steht **kein** Spielinhalt: erzeugtes C, Objekte, Bibliotheken und NSOs liegen nur unter `work/` (gitignoriert); hier stehen nur Hashes (Kurzform) und Größen.

## 1. Ergebnis in Kürze

| | Mac (Spike 2) | Linux-Rechner (diese Messung) |
|---|---|---|
| Rechner | M1 Pro, geteilt, Last 8 bis 14 | x86-64-CPU, 6 Kerne / 12 Threads, 30 GB RAM, exklusiv |
| SIMD-/FP-Modus des erzeugten C | `asm` (Inline-asm, arm64) | `c` (portables C, `-march=x86-64-v3`) |
| Generieren, 4 Module, ein Kern | 74 s | **51 s** (c) / 57 s (asm, nur Vergleich) |
| Übersetzen, alles (Schwelle des Spikes: Einzelfunktion > 1 MB → `-O0`) | **937 s** mit 3 Jobs | **986 s** mit 3 Jobs (gleiche Jobzahl: praktisch gleich), **692 s** mit 10 Jobs |
| Übersetzen mit `-O0` ab 300 KB Einzelfunktion | nicht gemessen | **310 s** (12 Jobs), 384 s (6 Jobs), 388 s (10 Jobs) |
| Summe CPU-Zeit der Compiler (3 Jobs) | 2.711 s | 2.868 s user (+6 %); mit 10 Jobs 4.584 s (SMT: 10 Jobs auf 6 Kernen) |
| Zielbibliothek | 224 MiB (`libgame.dylib`) | 327 MiB (`libgame.so`), mit 300-KB-Regel 341 MiB |
| größter Compiler-Spitzenwert | 1,7 GB | 1,6 GB (Einzelfunktion, 790 KB C) |
| Boot-Probe (SDK-Konstruktoren bis `svcBreak`) | siehe Spike 2, Abschnitt 5 | **identisch**: gleiche SVC-Zähler, gleiche Dienstfolge |

**Bewertung:** Je Kern ist der Linux-Rechner **nicht schneller** als der M1 Pro (986 s gegen 937 s bei 3 Jobs, jeweils mit demselben Compiler-Aufwand je Datei; der Mac war dabei ausgelastet). Sein Vorteil kommt aus **Parallelität und exklusiver Nutzung**: 6 Kerne / 12 Threads, 30 GB RAM, kein anderer Prozess, dazu die `-O0`-Regel für Ausreißer ab 300 KB; damit sinkt der Vollbau von 15,6 min auf **5 bis 6,5 min**, ein inkrementeller Bau auf etwa eine Minute (Abschnitt 9). Der Linux-Rechner ist **kein Ersatz** für den Mac-Bau: SIMD-/Float-Bitgenauigkeit und der Endbau für macOS/iPad (asm-Modus, Xcode) bleiben auf dem Mac.

## 2. Aufbau

### 2.1 Skripte (`scripts/recomp/linux/local/`)

Die Skripte laufen aus dem Repo-Hauptverzeichnis. `common.sh` wird von den anderen eingebunden und nicht direkt gestartet.

| Datei | Aufgabe |
|---|---|
| `setup.sh` | prüft Werkzeuge und Python-Pakete (`lz4`, `capstone`, `unicorn`), vergleicht die Eingaben mit `work/exefs.sha256`, falls die Datei existiert, und installiert nichts |
| `gen.sh [c\|asm] [modul ...]` | erzeugt das C der vier Module (`rtld`, `main`, `sdk`, `subsdk0`) mit dem LAS-Lifter (`eh_gen.py`) und misst Zeit, RAM und Größe; Vorgabe `c`, `asm` nur zum Vergleich auf x86 |
| `compile.sh [c] [--neu]` | übersetzt das erzeugte C parallel (`JOBS`, Vorgabe 10) mit `-O1`; Einzelfunktionsdateien über `THRESH_O0` (Vorgabe 300 KB) bekommen `-O0`; bindet `libgame.so` |
| `build_all.sh [--neu] [--nur-gen] [--nur-compile]` | führt `gen.sh c` und `compile.sh c` mit Gesamtzeit aus; zusätzlich `--tag=`, `--jobs=` und `--schwelle=` (Schwelle für `-O0` in Byte) |
| `las_runtime.sh` | Übersetzungstest des Linux-Pfads der LAS-Laufzeit ohne Grafik; meldet ok oder Fehler je Quelldatei |
| `probe.sh <test>` | Linux-Gegenstücke der Spike-Proben: `eh`, `eh-real` (nach `eh`), `rebase32`, `gc`, `bench`, `boot`, `boot-las` (nach `boot`) und `bdsp` (Gate-1-Laufzeit, Abschnitt 7); `alle` führt alles außer `bdsp` aus |
| `incr_test.sh` | misst inkrementelle Neubauten auf einer Kopie eines fertigen Builds (Szenarien A, B, C) |
| `vk_build.sh [--qt]` | baut rt-bdsp mit dem Vulkan-Backend (nach `build_all.sh`); `--qt` baut zusätzlich das Qt-Frontend im selben Prozess |
| `vk_run.sh` | startet den Vulkan-Build `work/recomp/bdsp_boot_vk` standardmäßig ohne Fenster; braucht `work/romfs` |
| `vk_qt_build.sh` | baut den Qt-Host als eigenen Prozess (CMake) nach `work/recomp/qt-host` |
| `vk_qt.sh` | startet das Qt-Frontend mit dem Vulkan-Spiel: im selben Prozess, wenn `vk_build.sh --qt` lief, sonst als eigener Prozess (`BDSP_QT_PROCESS=1` wählt ihn) |

Weitere Dateien: `gc_prove_linux.c` ist die Linux-Fassung des GC-Beweises (Signal statt Mach) und wird von `probe.sh gc` benutzt. `compat/mach/*.h` ist eine Mach-Kompatibilitätsschicht (Zeit, Thread anhalten per Signal, `task_info`, `mach_vm_*`), damit `rt-bdsp` unverändert unter Linux übersetzt (Abschnitt 7).

Die Arbeitskopie änderte sich während der Messungen: `ap-recomp-3` arbeitete parallel an `eh_gen.py` und `rt/cpu.h` (Abschnitt 8).


## 3. Einrichtung (gemessen)

Linux-Rechner: Fedora 44, Linux 7.2, clang 22.1.8, gcc 16.2.1, GNU make 4.4.1, Python 3.14.7 (wie `tools/pydeps` auf dem Mac, cpython-314), x86_64 mit AVX2/FMA/BMI2, 174 GB frei auf `/home`. Der clang kennt das Ziel `aarch64-linux-gnu` (für die synthetischen Gastprogramme der Proben). `pip install --user lz4==4.4.5 capstone==5.0.9 unicorn==2.1.4`, Versionen wie auf dem Mac, Import geprüft. Die Messungen nutzten kein sudo, keinen Ton, keine Grafik und keinen Plattenscan.

Eingaben (mit `sha256sum -c` gegen die auf dem Mac erstellte Liste geprüft, alle vier **OK**; Kurz-Hash = erste 16 Hex-Stellen):

| Datei | Größe (Byte) | sha256 (Kurzform) |
|---|---:|---|
| `rtld` | 7.187 | `bc175ad9865adb48` |
| `main` | 37.895.896 | `9c6b1d847d8fb3a1` |
| `sdk` | 5.755.393 | `1c9f198a91c0bcfe` |
| `subsdk0` | 3.409.290 | `67a38fcf89cd13e0` |

Nicht Teil der Messungen: `main.npdm`, Schlüssel, NCA/XCI/NSP, RomFS, Saves, `third_party` von LASRecomp. Speicherbedarf auf dem Linux-Rechner: etwa 4 GB (je 1 GB erzeugtes C für `c` und `asm`, 0,8 GB Objekte je Variante, Bibliothek 0,35 GB).

## 4. Generator (gemessen)

`eh_gen.py gen` (LAS-Lifter plus die Erweiterungen aus Phase 2), ein Kern, die vier Module nacheinander (`gen.sh`). Stand: Generator wie im Spike (Stand des Repos um 10:48 Uhr, Fensterwahl nach Größe).

| Modul | Funktionen | Dateien `c` | C-Größe `c` | Zeit `c` | Spitzen-RAM `c` | Dateien `asm` | C-Größe `asm` | Zeit `asm` |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| main | 218.195 | 918 | 817,3 MB | 41,3 s | 4,3 GB | 1.047 | 865,6 MB | 47,5 s |
| sdk | 38.342 | 180 | 105,0 MB | 5,6 s | 0,6 GB | 190 | 107,6 MB | 5,8 s |
| subsdk0 | 13.719 | 158 | 63,2 MB | 3,2 s | 0,35 GB | 161 | 63,9 MB | 3,2 s |
| rtld | 43 | 2 | 0,11 MB | 0,1 s | | 2 | 0,11 MB | 0,07 s |
| **Summe** | **270.299** | **1.258** | **985,6 MB** | **50,6 s** | | **1.400** | **1.037,2 MB** | **56,9 s** |

- Die Zahl der Funktionen ist in beiden Modi gleich (der Lifter entscheidet nicht anhand des SIMD-Modus über Funktionsgrenzen). Der `c`-Modus erzeugt etwa 5 % weniger C-Text (Float/SIMD als kurze Aufrufe aus `simd.h` statt langer Inline-asm-Blöcke), dafür mehr Maschinencode (Abschnitt 5).
- **Der Generator ist plattformunabhängig und deterministisch:** der `asm`-Lauf auf dem Linux-Rechner liefert **Byte für Byte dieselben 1.400 Dateien** wie `work/recomp/gen4` auf dem Mac (Vergleich der Datei-Hashes aller Chunks, Summe 1.037.185.555 Byte). Der `asm`-Modus lässt sich auf dem x86-Host erzeugen, aber nicht übersetzen (arm64-Inline-asm). Damit ist die Erzeugung auf dem Linux-Rechner ein vollwertiger Ersatz für den Mac, nur der Übersetzungsmodus unterscheidet sich.
- Python 3.14 auf dem Linux-Rechner ist für den Generator schneller als auf dem M1 Pro unter Last (50,6 s gegen 74 s); `main` braucht 4,3 GB (Mac: 4,8 GB).

## 5. Vollständiger Build der vier Module (gemessen)

`compile.sh`: `clang -O1 -fno-strict-aliasing -fvisibility=hidden -w -fPIC -march=x86-64-v3` (die Flags von `LASRecomp/Makefile` für Linux/x86-64), `xargs -P 10`, große Dateien zuerst; Einzelfunktionsdateien über einer Schwelle mit `-O0`; Zeit/RAM je Datei über `/usr/bin/time`, Gesamt-Spitzen-RAM über einen Sampler auf `/proc/meminfo`; Link `clang -shared`.

| Lauf (Generatorstand) | Dateien (`-O1`/`-O0`) | Wanduhr Übersetzen | + Link | Σ Wanduhr / Σ user | Median | > 10 s / > 60 s | größter Compiler | Spitzen-RAM gesamt | Bibliothek |
|---|---|---:|---:|---|---:|---|---:|---:|---:|
| Schwelle 1 MB (wie Spike), alter Stand | 1.248 / 10 | **688,5 s** | 1,2 s | 4.658 s / 4.584 s | 1,66 s | 44 / 9 | 1,6 GB | 1,96 GB | 341.792.872 Byte (`__text` 329,4 MB) |
| Schwelle 300 KB, alter Stand | 1.201 / 57 | **388,0 s** | 1,3 s | 3.097 s / 3.035 s | 1,61 s | 26 / 3 | 0,84 GB | 2,06 GB | 356.531.656 Byte (`__text` 344,2 MB) |
| Schwelle 300 KB, neuer Stand (feste 32-KiB-Fenster, `ap-recomp-3`, 2.369 Dateien), 10 Jobs | 2.312 / 57 | **387,8 s** | 1,4 s | 3.038 s / 2.963 s | 0,74 s | 27 / 2 | 0,84 GB | 1,98 GB | 357.485.784 Byte (`__text` 345,0 MB) |
| dito, **6 Jobs** | 2.312 / 57 | 384,0 s | | 2.071 s / 2.014 s | | | 0,84 GB | 2,03 GB | |
| dito, **12 Jobs** | 2.312 / 57 | **309,9 s** | 1,4 s | 3.291 s / 3.189 s | | | 0,84 GB | 1,73 GB | 357.485.784 Byte |
| Schwelle 1 MB, neuer Stand, **3 Jobs** (Vergleich mit dem Mac-Spike) | 2.359 / 10 | **986,4 s** | 1,4 s | 2.934 s / 2.868 s | 0,51 s | 27 / 7 | 1,62 GB | 1,64 GB | 342.747.000 Byte (`__text` 330,3 MB) |

**Ausreißer** (alter Stand, 1-MB-Schwelle): die drei langsamsten Dateien sind dieselben Einzelfunktionen wie im Mac-Spike, im `c`-Modus aber deutlich teurer:

| Datei | C-Größe | `-O1` Linux-Rechner (`c`) | Mac (`asm`) | Spitzen-RAM Linux-Rechner |
|---|---:|---:|---:|---:|
| `main_357` (eine Funktion) | 372 KB | **497 s** | 214 s | 0,48 GB |
| `main_694` (eine Funktion) | 791 KB | 292 s | 87 s (870 KB) | **1,6 GB** |
| `sdk_048` (eine Funktion) | 488 KB | 204 s | 187 s | 0,68 GB |
| Funktion `main_639`, 8 MB C, `-O0` | 8,0 MB | 3,3 s | 4,0 s | 0,84 GB |

- **Der Gesamtbau wird vom längsten Einzelstück bestimmt:** mit der 1-MB-Regel liegt der kritische Pfad bei 497 s (eine 372-KB-Funktion bei 10 Jobs; 242 s bei 3 Jobs), die Summe aller Dateien durch 10 Jobs wäre nur etwa 466 s; die Wanduhr war 688 s. Mit `-O0` ab **300 KB** (57 statt 10 Dateien) fällt sie auf 310 bis 388 s je nach Jobzahl; die längste Datei ist dann 216 s (260 KB). Die Streuung zwischen 6, 10 und 12 Jobs (384, 388, 310 s) liegt innerhalb dessen, was SMT-Zeitscheiben und die Reihenfolge der Ausreißer ausmachen; eine saubere Jobzahl-Kurve wurde nicht gemessen. Empfehlung: 10 bis 12 Jobs. Die Laufzeitkosten der 47 zusätzlichen `-O0`-Dateien sind **nicht gemessen**; die Bibliothek wird um 14,7 MB größer.
- Der größte RAM-Verbrauch einer Datei liegt bei 1,6 GB (nicht 3,3 GB). Bei 10 Jobs lag der Spitzen-RAM des ganzen Rechners bei **2 GB** (Sampler, Unterschied zum Ruhestand): RAM ist beim Bau kein Engpass, die Kerne sind es.
- **Median 0,5 bis 1,6 s je Datei; 2.868 s CPU (3 Jobs) gegen 2.711 s auf dem Mac:** je Datei kostet der x86-`c`-Modus etwa so viel wie der arm64-`asm`-Modus, obwohl er mehr Maschinencode erzeugt; mit 10 Jobs auf 6 Kernen (SMT) steigt die Summe auf 4.584 s, weil sich zwei Compiler einen Kern teilen (Einzelzeiten bis 60 % länger). Der 8-MB-Ausreißer (`main`, eine Funktion) braucht mit `-O1` **108 s** und 0,83 GB (Mac: 153 s, 867 MB), mit `-O0` 3,3 s.
- Bibliothek: 327 MiB gegen 224 MiB (`asm`, Mac): der `c`-Modus erzeugt etwa 57 % mehr Maschinencode. Das Binärformat ist ELF statt Mach-O; Größen sind nur grob vergleichbar.

## 6. Linux-Pfad der LAS-Laufzeit und Proben (gemessen)

### 6.1 LAS-Laufzeit (`las_runtime.sh`, ohne Grafik)

`runtime/platform/linux.c`, Kern (`dispatch`, `kernel`, `ipc`, `loader`, …), `services/*`, `hle/*`, `nvn/*` (ohne Vulkan-Backend) werden einzeln übersetzt: **53 von 55 Quellen ok, 2 scheitern an fehlenden Dateien aus `third_party`** (`AreaTex.h`, `imstb_truetype.h`, bewusst nicht vorhanden). `platform/linux.c` übersetzt. Auf dem Linux-Rechner fehlten die `-devel`-Pakete für SDL3, FFmpeg, Vulkan und shaderc, und es gab kein Internet; die Header für diesen Übersetzungstest stammen aus Homebrew. **Nicht möglich** ist das Linken und Starten des LAS-Programms selbst (braucht Bibliotheken, Vulkan-Treiber, Grafik): dafür fehlen die Pakete aus Abschnitt 10; nicht Teil dieser Aufgabe.

### 6.2 Proben aus dem Spike auf x86 (`probe.sh`, c-Modus; Ergebnisse im Stand 11:30 Uhr)

| Probe | Mac (Spike 2) | Linux x86 `c` |
|---|---|---|
| `eh`: Exception-Test T0 bis T6 mit dem echten SDK-Unwinder | bestanden, 44,8 µs je Wurf+Fang | **bestanden**, 26,8 µs je Wurf+Fang (4 Rahmen) |
| `eh-real`: 180 echte LSDA-Funktionen aus `main` | 100 erreicht, 100 richtig, 25 ohne Aufruf, 55 Umgebung, 0 Abweichung | **identisch** (100 / 100 / 25 / 55 / 0) |
| `rebase32`: 32-Bit-Gastadressen | bestanden, 47,0 µs | **bestanden**, 29,8 µs |
| `gc`: Anhalten an beliebiger Stelle, Zeiger nur in Registern | 19.293 von 19.293 im Fenster allein in `Cpu` + Gast-Stack | **19.565 von 19.565** (Linux: Signal-Stopp statt Mach, x86-Registersatz) |
| `bench`: rekompiliert gegen nativ | Faktor 1,9 / 4,3 / 4,0 / 1,5, alle Ergebnisse gleich | Ganzzahl **1,5**, `fib` **3,9**, indirekt **1,6**, Float **12,0** (Ergebnis **abweichend**) |
| `boot`: eigene Mini-Dienste | `sm:` → `lm` → `apm` → `appletOE` → `aoc:u` → `ectx:aw`, dann `svcBreak` | **identisch**: 8 verschiedene SVCs (`0x06 0x0c 0x1f 0x21 0x25 0x26 0x29 0x2c`), 29 Aufrufe (`GetInfo` 13, `SendSyncRequest` 9) plus 2 interne Zähler (`0xff`), `svcBreak`, 115 SDK-Konstruktoren, Spitzen-RSS 115 MB |
| `boot-las`: LAS-IPC-/Dienstschicht | `am`-Befehle 900/91 unbehandelt, dann `svcBreak`; 557 SVCs, `QueryMemory` 514 | **identisch** (557 SVCs, 9 verschiedene, `QueryMemory` 514, gleiche Dienstfolge) |
| `bdsp`: Gate-1-Laufzeit `rt-bdsp` (Stand 11:46, Abschnitt 7) | | baut und startet unter Linux (Mach-Ersatz in `compat/`): 115 SDK- und 417 `main`-Konstruktoren laufen, ein Gast-Thread wird angelegt, der Gast erreicht **`nnMain`** und hält in `nn::fs::QueryMountRomCacheSize` am RomFS (bewusst nicht auf dem Linux-Rechner). Stand 12:18+ (NVN/Metal/UI, Gate 2): linkt unter Linux nicht mehr |

**Boot-Probe auf x86 `c`: wie weit kommt der Gast?** Genau so weit wie auf dem Mac mit `asm`: `nn::init::Start`, `nnosInitialize` (12 `GetInfo`, `QueryMemory`, Thread-ID/Priorität), alle **115 SDK-Konstruktoren**, `sm:`-Initialisierung, `lm` (Domain-Umwandlung, `OpenLogger`), `apm`, `appletOE`, dann bricht das SDK (`svcBreak`, Grund 0), weil `ectx:aw` fehlt bzw. in der LAS-Schicht die `am`-Befehle 900 (`ICommonStateGetter`) und 91 (`ISelfController`) unbehandelt sind. Das ist der Befund aus Phase 2 und der Anlass für Gate 1. **Kein Unterschied zwischen arm64-`asm` und x86-`c` im Verhalten des CPU-Teils bis dorthin.**

**Befunde der Proben:**

1. **Float-Ergebnis weicht ab (`bench`, FMA-Schleife):** **Korrektur (`docs/recomp-diff.md`, Abschnitt 6):** die Abweichung ist das NaN-Vorzeichen (ARM-Standard-NaN `0x7FF8…` im Rekompilat und unter Unicorn, x86-Standard-NaN `0xFFF8…` in der nativen Referenz), keine FMA-Fusion des Rekompilats; mit Unicorn als Referenz stimmt das Rekompilat in allen Läufen überein. Ursprüngliche (überholte) Vermutung: der Vergleichswert ist die *nativ für x86 übersetzte* Referenz; clang wählt dort für `b * a + v * 0.25` eine andere Fusion (welcher der beiden Multiplikationen zu `fma` verschmolzen wird) als der aarch64-Compiler für den Gastcode. Der Unterschied liegt also in der **Referenz**, nicht belegt im Rekompilat. Er zeigt aber, dass auf dem Linux-Rechner kein Bit-Vergleich mit echter arm64-Semantik möglich ist (siehe Abschnitt 8). Der FP-Faktor 12 (Mac 4) zeigt den Preis des `c`-Modus: Gastregister und SIMD-Operationen laufen über die `Cpu`-Registerdatei im Speicher.
2. **T7 (`setjmp`/`longjmp`, neu von `ap-recomp-3`) schlägt auf dem Linux-Rechner fehl:** `rt_nle_enter: kein Rahmen für pc=…514`; im Test-Gastmodul meldet der Generator `setjmp_returns: 0`. Die Funktion `_find_setjmp_returns` sucht `setjmp` in den Symbolen des NSO (`n.syms`), das der Mini-Linker (`mini_link.py`) für Testmodule nicht schreibt; ob der Test auf dem Mac gerade grün ist, wurde nicht geprüft (Arbeitsstand). Die Probe wiederholt in diesem Fall ohne T7, damit T0 bis T6 und der Durchsatz gemessen werden.
3. `rt/cpu.h`/`rt32/cpu.h` ändern sich laufend; die Proben bauen deshalb ihre Objekte bei jedem Lauf neu (keine Altlasten bei anderer Chunk-Einteilung), und `compile.sh` baut bei geänderten Headern/Flags vollständig neu.

## 7. Gate-1-Laufzeit (`rt-bdsp`) auf dem Linux-Rechner

Von den neun Quelldateien der Laufzeit von `ap-recomp-3` (Stand 11:46) übersetzen **sieben unverändert** unter Linux; `kernel.c` und `main.c` brauchen Mach-Aufrufe an vier Stellen: Zeit (`mach_absolute_time`), Anhalten fremder Threads (`thread_suspend`/`resume`, Boehm-GC), Stackgröße (`pthread_get_stacksize_np`) und Speichermessung (`mach_vm_region`, `task_info`, `mach_vm_allocate` für die Fensterreservierung). `scripts/recomp/linux/compat/mach/*.h` ersetzt sie (nur für den Linux-Build; kein Ersatz für die Semantik auf dem Mac), die Dateien selbst blieben unberührt (`-I scripts/recomp/linux/compat`). Ergebnis (Stand 11:46, `bdsp_boot` aus Laufzeit und den `c`-Objekten, 351 MB, `mkimages.sh` für die Bilder): die Laufzeit lädt `main`/`sdk`/`subsdk0`, führt die 115 SDK-Konstruktoren aus, legt den ersten Gast-Thread an (`CreateThread`), beantwortet `IParentalControlService` mit der Standardantwort, führt die 417 `init_array`-Einträge von `main` aus, der Gast erreicht **`nnMain`** (Rückverfolgung `nnMain+164` → `nn::fs::QueryMountRomCacheSize` → `CanMountRomForDebug` → `SendSyncRequest`) und die Laufzeit bricht dann mit `FATAL: RomFS-Ordner work/romfs nicht lesbar` ab (Lauf 11 s, 172 MB RSS; danach meldet der Absturzhandler ein SIGSEGV an Hostadresse 0x39 beim Beenden, Ursache nicht untersucht, vermutlich Aufräumpfad). **Das RomFS-Ende war gewollt:** RomFS und `main.npdm` gehörten nicht zu den Eingaben (Auftrag: keine Spielinhalte außer den NSOs). Weiter als bis zum ersten RomFS-Zugriff ließ sich Gate 1 auf dem Linux-Rechner also nicht fahren, solange der Nutzer nicht ausdrücklich Daten freigibt.

**Stand 12:18 und später:** `ap-recomp-3` hat `rt-bdsp/nvn/` (NVN-Schicht, Metal, SDL, `ui_run`, `nvn_glue_init`) für Gate 2 ergänzt. Das ist macOS-spezifisch und linkt unter Linux nicht; `probe.sh bdsp` bricht dann mit einer klaren Meldung ab (das Protokoll des Laufs von 11:46 blieb auf dem inzwischen entfernten Rechner). Der Linux-Rechner bleibt für Generator, Bau und die Proben des CPU-Teils nützlich; ab Gate 2 braucht die Laufzeit die macOS-spezifische NVN-/Metal-Schicht und läuft unter Linux nicht mehr. Die vier Mach-Stellen (Zeit, Thread-Anhalten, Stack, Speicherbericht) hinter eine kleine Plattformschicht zu legen, wäre die Voraussetzung, den Boot-Teil weiter auf dem Linux-Rechner laufen zu lassen.

## 8. Grenzen

- **x86-`c`-Modus ≠ arm64-`asm`-Modus.** **Stand `docs/recomp-diff.md`: der `c`-Modus ist gegen Unicorn (Cortex-A57) und den M1 über 93,5 Mio. Fälle je Variante (plus 560 Mio. und 259,8 Mrd. erschöpfend) bitgenau, ohne FPSR-Sammelflags; die folgende Aussage gilt nur noch für diese Flags und für den Compiler-/MXCSR-Zustand.** Der `c`-Modus lowert FP/SIMD in portables C (`simd.h`, `simd_fp.h`), der `asm`-Modus führt arm64-Inline-asm auf Apple-Silicon aus. Bitgenaue Float-/SIMD-Semantik (NaN-Behandlung, Rundung, FPCR/FPSR-Flags, `fmadd`-Fusion, Denormale) ist **nur auf dem Mac gegen echte arm64-Befehle verifiziert**; ein erfolgreicher Lauf auf dem Linux-Rechner sagt darüber nichts. Das gilt auch für den Leistungsvergleich: der dort gemessene Faktor (Float 12) ist nicht der Mac-/iPad-Faktor.
- **Der finale Build für macOS/iPad entsteht immer auf dem Mac/Xcode** (Mach-O, arm64, `asm`-Modus, Codesignatur, Entitlements, Metal). Die auf dem Linux-Rechner gebaute Bibliothek ist ein ELF-x86-64-Objekt und nur für Proben nutzbar.
- Funktions-Proben (Exceptions, Speichermodell, Boot, Dienstschicht, Dispatch, GC-Fenster) sind plattformunabhängig und liefen identisch; Thread-/Anhalte-Mechanik ist es nicht (Linux: Signale; auf dem Mac/iPad Mach-`thread_suspend`).
- Die Messungen bauten den **Stand der Arbeitskopie zum Zeitpunkt der Messung** (laufende Änderungen von `ap-recomp-3` sind darin enthalten); Zahlen daher nur mit Läufen aus demselben Stand vergleichen.
- Nicht verfolgt: Header-Abhängigkeiten im Detail (nur Gesamt-Stempel), `ccache`/`lld` (nicht installiert, siehe Abschnitt 10), LTO, Link-Zeit mit `ld.bfd` (1,2 bis 3,2 s, unkritisch), Start-Zeit der 340-MB-Bibliothek, Last-Kopplung bei parallelen Probe- und Bauläufen.

## 9. Zeiten Mac gegen Linux-Rechner und inkrementelle Neubauten

**Vergleich mit dem Spike (3 Jobs, Schwelle 1 MB, neuer Generatorstand, 2.369 Dateien):**

| | Mac (Spike 2, asm, ausgelastet) | Linux-Rechner (c, exklusiv) |
|---|---:|---:|
| Generieren | 74 s | 53 s |
| Übersetzen, Wanduhr | 937 s | 986 s |
| Summe CPU der Compiler | 2.711 s | 2.868 s |
| langsamste Datei | 214 s | 242 s |
| größter Compiler-RAM | 1,7 GB | 1,6 GB |
| Bibliothek | 224 MiB | 327 MiB |

Bei gleicher Jobzahl liegen beide gleichauf; der Vorteil des Linux-Rechners entsteht erst durch mehr Jobs und die 300-KB-Regel (Abschnitt 5: 310 bis 692 s). Zum Vergleich der Mac-Zahl ist zu beachten, dass die Mac-Maschine damals mit Last 8 bis 14 lief; auf einem freien M1 Pro wären 3 Jobs vermutlich schneller (nicht gemessen).

**Inkrementell** (gemessen an einer Kopie des fertigen Builds mit `incr_test.sh`, neuer Stand mit festen 32-KiB-Chunkfenstern):

| Szenario | Dateien neu übersetzt | Wanduhr Übersetzen | Link |
|---|---:|---:|---:|
| A: keine Änderung | 0 | 0,7 s | 3,2 s |
| B: fünf Chunks geändert (mittelgroße, `main`) | 5 | 1,4 s | 1,4 s |
| C: sieben SDK-Funktionen werden HLE-Stubs (echte Generatoränderung) | **3 von 298 SDK-Chunks** | 1,2 s | 1,4 s |

Mit dem **alten** Chunkzuschnitt (nach Größe fortlaufend) änderten sieben HLE-Funktionen 14 von 180 SDK-Chunks (8 %); der Zuschnitt mit festen Adressfenstern von `ap-recomp-3` ist deutlich stabiler. Die Neuerzeugung selbst ist **nicht inkrementell** (53 s für alles, davon `main` 43 s); `write_if_changed` lässt unveränderte Chunks unberührt, damit nur geänderte übersetzt werden. Ein vollständiger Wiederholungsbau nach einer kleinen Änderung am Generator kostet also rund **1 Minute** (Erzeugen + 1 bis 5 Chunks + Link) statt 7,5 Minuten. Das schlimmste Einzelstück (ein langsamer Chunk, 220 s) bleibt der Ausreißer, wenn gerade er geändert wird.

## 10. Installationsliste für den Nutzer (fehlende Pakete, kein sudo benutzt)

Für die Messungen fehlte **nichts** (alles vorhanden; `pip --user` genügte). Optional, nur um die LAS-Laufzeit selbst bauen zu können oder schneller zu linken:

- `lld` (liefert `ld.lld`; das LAS-Makefile nutzt `-fuse-ld=lld`),
- `ccache` (Wiederholungsbauten),
- für das LAS-Programm: `SDL3-devel` (3.2 oder neuer), `ffmpeg-devel` (oder `ffmpeg-free-devel`), `vulkan-loader-devel`, `vulkan-headers`, `shaderc-devel`, `glslc`, `vulkan-validation-layers`, `VulkanMemoryAllocator-devel`, `mesa-vulkan-drivers` (RADV); und `third_party` des LAS-Klons (imgui, `AreaTex.h`) für `nvn/smaa_data.c` und `nvn/texpatch.c`,
- `gdb` (Absturzanalyse; fehlt, die Proben brauchen es nicht),
- für die Messungen war kein Netz-Zugang nötig; der Linux-Rechner hatte keinen (Download von SDL3-Quellen schlug fehl).

## 11. Reproduktion

Die Befehle unten sind die lokalen Gegenstücke zu den Messläufen. Sie laufen aus dem Repo-Hauptverzeichnis auf einem Linux-Rechner; für den unterstützten Nutzerablauf siehe [BUILD.md](BUILD.md), Abschnitt 6.

```
sha256sum work/exefs/rtld work/exefs/main work/exefs/sdk work/exefs/subsdk0 > work/exefs.sha256   # optionales Eingabe-Manifest
bash scripts/recomp/linux/local/setup.sh                                  # Werkzeuge, Python-Pakete, Eingabe-Prüfsummen
bash scripts/recomp/linux/local/build_all.sh                              # Generator (c) + Übersetzen (10 Jobs) + Link
bash scripts/recomp/linux/local/build_all.sh --nur-compile --tag=j3 --jobs=3 --schwelle=1000000   # Vergleich mit dem Mac-Spike
bash scripts/recomp/linux/local/incr_test.sh                              # Neubau-Messung (braucht einen fertigen Build und rsync)
bash scripts/recomp/linux/local/las_runtime.sh                            # Linux-Pfad der LAS-Laufzeit (Übersetzungstest)
bash scripts/recomp/linux/local/probe.sh alle                             # eh, eh-real, rebase32, gc, bench, boot, boot-las
bash scripts/recomp/linux/local/probe.sh bdsp                             # Gate-1-Laufzeit (Abschnitt 7; die NVN-Schicht linkt unter Linux nicht)
```

Die Messdateien (`*.stats`, `*.times`) schreiben die Skripte nach `logs/` im Repo-Hauptverzeichnis.
