# Machbarkeitsspike `ap-recomp-feasibility`: LAS-artige Rekompilation des BDSP-NSO (Stand 2026-10-18)

**Auftrag:** nur messen und analysieren, keine Entscheidung. Eigene Worte, keine Rechtsberatung. Aus `research/LASRecomp` (MIT, nur gelesen) wurde nichts ins Repo kopiert; es stehen nur Dateipfade, Zeilennummern, Zahlen und Namen im Dokument. Keine Binärdaten, kein erzeugter Code, keine Disassembly.

**Nachtrag 2026-10-19:** Die Spike-Phase 2 aus Abschnitt 7 ist durchgeführt: `docs/recomp-spike-2.md`. Der „Kernblocker“ C++-Exceptions ist gelöst (Variante a, getestet am echten SDK-Unwinder und an 180 echten Funktionen), Thread-Anhalten und 32-Bit-Speichermodell sind prototypisiert, der Gesamtbau ist gemessen (15,6 min, 224 MiB). Aussagen unten, die diese Punkte als offen oder „Wochen bis Monate“ führen, sind dadurch überholt.

**Kennzeichnung:** **gemessen** = mit `scripts/recomp_survey.py` oder per Kommando an den lokalen Dateien ermittelt. **belegt** = im Klon, in einer genannten Quelle oder in unseren Docs gelesen. *vermutet* = Schluss ohne Test. **nicht verifiziert** = Zahl oder Aussage aus Sekundärquelle bzw. nicht prüfbar.

**Reproduktion** (alles lokal; Ausgaben landen in `work/recomp/`, gitignoriert):

```
pip install --target tools/pydeps capstone unicorn            # lz4 war schon da
python3 scripts/recomp_survey.py nso | hist | imports | svc | npdm | eh
python3 scripts/recomp_survey.py lifter    --lifter-dir scripts/recomp/upstream/generator --module main --simd asm
python3 scripts/recomp_survey.py gensample --lifter-dir scripts/recomp/upstream/generator --module main --functions 0
```

`lifter` und `gensample` importieren Lifter und Generator aus dem Klon nur zur Laufzeit (ohne `.pyc`-Dateien dort zu schreiben, ohne die LAS-spezifischen Patch-Tabellen) und erzeugen nur Zahlen. Das Ziel-Binary wird nie verändert.

## Kurzfassung (die wichtigsten Zahlen)

| Frage | Ergebnis | Status |
|---|---|---|
| CPU-Abdeckung des LAS-Lifters für BDSP | 14.105.420 Wörter in vier Modulen. Abgelehnt werden **58 Wörter** (`LDXP/STXP/LDAXP/STLXP`, alle in `main`), 4 von 332 verschiedenen Mnemonics. Kein LSE, kein PAC, kein Crypto/CRC in `main`. | gemessen |
| Größe des erzeugten C (ARM64-Modus, inline asm) | **1,01 GB** (main 846 MB, sdk 105 MB, subsdk0 63 MB), 71,8 Byte je Instruktion, rund 1,25 C-Zeilen je Instruktion | gemessen (volle Generierung ohne Schreiben der Dateien) |
| Funktionen | main 217.858, sdk 37.267, subsdk0 13.343 (Grenzen aus eh_frame, Symbolen, Relokationen, BL-Zielen) | gemessen |
| Compile-Zeit | normaler Chunk (1,5 MB C) 1 bis 4 s; **lange Ausreißer**: einzelne Funktionen mit 1,1 bis 1,4 MB C brauchen 13 bis 200 s und bis 3,3 GB RAM; die größte (8,0 MB C) wurde nicht kompiliert | gemessen (Stichprobe) |
| Schnittstelle | `main` importiert 1.040 Symbole: 1.013 aus `sdk`, 23 aus `subsdk0` (Movie), 4 offen. NVN kommt nur über `nvnBootstrapLoader` | gemessen |
| SVC-Lücke in LAS | BDSP-Maske hat 50 SVCs, LAS setzt 43 um; **8 fehlen**, darunter `SetThreadActivity`/`GetThreadContext3` (Thread-Anhalten) | gemessen/belegt |
| Dienste (IPC) | NPDM erlaubt 47 Dienste, LAS bringt 12 davon mit (20 Dienstnamen insgesamt) | gemessen/belegt |
| **Kernblocker** | BDSP nutzt C++-Exceptions (IL2CPP): 2.917 Funktionen mit Landing-Pads. LAS hat dafür keinen Mechanismus. | gemessen/belegt |
| Speicher/iPadOS | festes Fenster 12,5 GiB bei `0x70_0000_0000` verträgt sich ohne Entitlement **nicht** mit iOS; das passende Entitlement gibt es für das kostenlose Team nicht (Abschnitt 4a) | belegt (XNU-Quelle, Apple-Doku) |

---

## 1. Architektur der CPU-Rekompilation in LASRecomp

### 1.1 Pipeline (belegt)

| Stufe | Datei (Zeilen) | Aufgabe |
|---|---|---|
| NSO lesen | `tools/nso.py` (98) | LZ4-Segmente entpacken, MOD0, Dynamic, Dynsym, Relokationen |
| Funktionsgrenzen | `tools/analyze.py` (105), `tools/gen.py:boundaries/main` | Anfänge aus `.eh_frame_hdr`, Funktionssymbolen, `R_AARCH64_RELATIVE`-Zeigern auf Text, BL-Zielen, ADR/ADRP-Paaren; Fixpunkt-Iteration, bis jedes Sprungziel außerhalb einer Funktion selbst Funktionsanfang ist |
| Sprungtabellen | `tools/gen.py` (630) | `br xN` über Bounds-Check-Tabellen: **Unicorn** führt das Adressmuster für jeden Index aus; bei Misserfolg Rückfall auf „alle Instruktionen der Funktion sind Label“ (`switch(c->pc)`) |
| Lifter | `tools/lifter.py` (728) | Ganzzahl, Speicher, Sprünge, System-Instruktionen nach C; FP/SIMD je nach Modus |
| FP/SIMD | `tools/lifter.py:emit_asm_batch`, `tools/simd_c.py` (1.156), `runtime/simd.h` (818), `simd_fp.h` (340) | Modus `asm` (arm64-Host): die Original-Encodings werden als `.inst` in Inline-asm-Blöcke (bis 24 Stück) gepackt, V-Register werden vor/nach jedem Block aus `Cpu` geladen und zurückgeschrieben, bit-genau durch Konstruktion. Modus `c`: portable C-Nachbildung (x86-Hosts). |
| Ausgabe | `gen.py` | je Funktion `void f_<adresse>(Cpu *c)`, Chunks mit höchstens 1500 Funktionen bzw. 1,5 MB, Funktionen über 100 KB bekommen eine eigene Datei; zusätzlich `*_table.c` mit sortierter Adress- und Funktionszeiger-Tabelle |
| Build | `Makefile` | `clang -O1 -fno-strict-aliasing -fvisibility=hidden` je Chunk; Ergebnis ist **eine eigene Bibliothek** (`lasgame.dylib`), die die Runtime per `dlopen` lädt (`runtime/gamelib.c`) |

Wichtig für uns: Die Gast-Register liegen in einer Struktur `Cpu` im Speicher (`runtime/cpu.h`, `x[32]`, `sp`, `nzcv`, `tpidr`, `excl_addr`, `v[32]`). Jede Instruktion liest und schreibt `c->x[n]`; Flags sind ein gepacktes Wort (`adds64`, `COND_EQ` usw. als Inline-Funktionen). Das ist einfach und korrekt, verschenkt aber Register-Allokation über Funktionsgrenzen (*vermutet*: deutlich langsamer als natives ARM64; **nicht gemessen**, es gibt weder ein lauffähiges BDSP noch ein lauffähiges LAS hier).

### 1.2 Speicherzugriffe (belegt)

- **Gastadresse = Hostadresse.** `LD8..LD64`/`ST8..ST64` sind reine Zeiger-Dereferenzierungen (`runtime/cpu.h:62-72`, unaligned-sicher, `may_alias`). Keine Übersetzung, keine Bereichsprüfung, ein Zugriff außerhalb stürzt per SIGSEGV ab.
- **Festes Fenster:** `runtime/rt.h:14-30`. `GUEST_LO=0x70_0000_0000`, `GUEST_HI=0x73_2000_0000` = **12,5 GiB**. Begründung im Kommentar (`rt.h:14-15`): macOS belegt `0x2_0000_0000-0x70_0000_0000`, Gastadressen müssen in 39 Bit passen. Aufteilung: Main bei `0x70_0000_0000`, SDK bei `0x70_0400_0000` (nur 64 MiB Abstand), HLE-Stubs `0x70_8000_0000`, TLS `0x70_9000_0000` (1 MiB), HLE-Heap 224 MiB, Alias-Bereich 4 GiB ab `0x71_0000_0000`, Stack-Fenster 1 GiB ab `0x72_0000_0000` (`runtime/kernel.h:7-8`), Heap ab `0x72_4000_0000`, **maximal 3,25 GiB** (`HEAP_MAX`).
- **macOS:** `plat_reserve_guest` = `mach_vm_allocate(..., VM_FLAGS_FIXED)` über das ganze Fenster, alles lesbar/schreibbar, Seiten werden erst beim ersten Zugriff angelegt (`runtime/platform/macos.c:24-37`). `plat_commit` ist ein No-op. Die Seitengröße ist 16 KiB (`platform.h:32`), der Gast arbeitet in 4-KiB-Schritten, weil nie Rechte gesetzt werden: `SetMemoryPermission`/`SetMemoryAttribute` geben nur OK zurück (`kernel.c:579`). Es gibt also keine Guard-Pages und keinen Schreibschutz im Gast.
- **Linux:** gleiches Prinzip mit `MAP_NORESERVE | MAP_FIXED_NOREPLACE` (`platform/linux.c:29-44`). **Windows:** `VirtualAlloc(MEM_RESERVE)` für das Fenster, Commit je Region (`plat_commit`) und lazy per Exception-Handler in 64-KiB-Stücken (`platform/windows.c:14-27`).
- **Kollision:** Wenn macOS an der Wunschadresse schon etwas abgelegt hat, startet der Prozess sich bis zu 20 Mal neu (`main.c:37-52`, `plat_exec`/`execv`).
- **Exklusive Zugriffe** (`LDXR/STXR`): über `excl_addr`/`excl_val` und Compare-and-Swap nachgebildet (`cpu.h:74-95`). Das ist nicht identisch zur Hardware (ABA-Fälle), für übliche Spinlocks und Zähler genügt es. `CLREX` setzt den Monitor zurück. `LDAR/STLR` sind echte Acquire/Release-Zugriffe. Barrieren sind `__atomic_thread_fence`.

### 1.3 Indirekte Aufrufe, vtables, Funktionszeiger (belegt)

- Direkte `BL`/`B` zwischen Funktionen sind direkte C-Aufrufe bzw. Tail-Calls (`musttail`). Ein Gast-`RET` ist ein Host-`return`: **der Host-Stack spiegelt den Gast-Aufrufstack**, das Gast-LR (`x30`) wird nur gesetzt, nicht zum Zurückspringen benutzt.
- `BLR`/`BR` mit Registerziel: `c->pc = ziel; rt_dispatch(c)` (`runtime/dispatch.c:157-164`): Cache mit 4.096 Einträgen je Thread (direkt abgebildet, Index aus `pc>>2`), bei Fehlgriff **Binärsuche** in der sortierten Adresstabelle, danach HLE-Stubs (Adressen ab `HLE_BASE`) und Overrides. Unbekanntes Ziel: `FATAL "no function at …"`.
- Es gibt **zwei** Tabellen (main, sdk; `dispatch.c:12, 116, 187`) und `g_modules[4]` (`rt.h:40`). BDSP hat drei Code-Module (`main`, `sdk`, `subsdk0`); eine dritte Tabelle wäre nötig.
- Jede Gastfunktion, die per Zeiger erreichbar sein kann, muss eine eigene C-Funktion sein: Der Generator nimmt dafür Code-Zeiger aus Relokationen, `ADR/ADRP+ADD` und BL-Ziele als Funktionsanfänge. In `main` gibt es rund **554.000 Relokationen** (Größe von `.rela.dyn` / 24). IL2CPP-Methodentabellen und vtables sind dort enthalten (*vermutet*, der Anteil mit Text-Ziel wurde nicht einzeln gezählt).
- **Nicht vorhanden: C++-Exceptions und `setjmp/longjmp` des Gastes.** Es gibt im Klon keinen Treffer für `_Unwind`, `__cxa_throw` oder Personality (`grep` über `runtime/` und `tools/`). `longjmp` benutzt die Runtime selbst nur, um Gast-Threads beim Beenden/Neustart abzuwickeln (`kernel.c:184-192, 611`). Folge für BDSP: Abschnitt 5.

### 1.4 Threads, TLS, Atomics, Exclusives (belegt)

- Jeder Gast-Thread ist ein Host-`pthread` mit **256 MiB** Host-Stack (`kernel.c:226`, Kommentar: „guest recursion runs on the host stack“) plus eigenem Gast-Stack (aus dem Gast-Speicher). Zwei Stacks je Thread. Gast-Threads laufen echt parallel; Prioritäten werden aufgenommen, Kern-Masken ignoriert (`SetThreadCoreMask` = OK).
- TLS: `MRS TPIDR_EL0/EL0RO` liefern `c->tpidr`/`c->tpidrro` (`lifter.py:system`), je Thread ein 0x200-Byte-Bereich im TLS-Fenster (`kernel.c:209-214`). Zählerregister (`CNTVCT`, `CNTFRQ`=19,2 MHz) per `rt_ticks()`.
- Synchronisation (`ArbitrateLock`, `WaitProcessWideKey`, `WaitForAddress` …) ist in `kernel.c` mit einer globalen Mutex plus Bedingungsvariablen umgesetzt.
- **Thread anhalten/Kontext lesen** (`SetThreadActivity`, `GetThreadContext3`): nicht umgesetzt (Abschnitt 3.3).
- README (`README.md` ca. Z. 183): Beitrag #107 von hjqcan, „Windows game thread stacks reserved instead of committed, about 9 GB less memory committed“. Der zugehörige Code-Commit ist im Klon nicht isolierbar (Commit `9f26e4c` und `ece84d7` ändern nur die README). Im Stand des Klons steht in `kernel.c:226` weiterhin die 256-MiB-Reservierung. Die Lehre (Stacks nur reservieren, nicht committen) ist plausibel; wo genau LAS sie umsetzt, ist **nicht verifiziert**.

### 1.5 SVC- und IPC-Umsetzung

**SVC (belegt, `runtime/kernel.c:569-780`):** 43 Nummern: `0x01-0x1F` (Heap, Speicher, Threads, Events, Shared/Transfer-Memory, `CloseHandle`, `WaitSynchronization`, Arbitrate-Lock/Unlock, ProcessWideKey, `GetSystemTick`, `ConnectToNamedPort`), `0x21` SendSyncRequest, `0x22` mit User-Buffer, `0x24-0x27`, `0x29` GetInfo, `0x2C/0x2D` MapPhysicalMemory, `0x34/0x35` WaitForAddress/SignalToAddress, `0x45` CreateEvent. Alles andere ist `FATAL "unimplemented svc"`. `MapMemory` wird als Kopie umgesetzt (die Quelle ist laut Kommentar ohnehin unzugänglich).

**IPC (belegt, `runtime/ipc.c` 246 Zeilen, `ipc.h`):** HIPC/CMIF mit Domains, X/A/B/C-Puffern; Dienste sind Host-Funktionen mit `SERVICE("name", handler)`. Umgesetzt sind **20 Namen**: `sm:`, `acc:u0`, `aoc:u`, `apm`, `appletOE`, `audout:u`, `audren:u`, `fsp-srv`, `hid`, `hid:sys`, `lm`, `pctl` (+ `:a :r :s`), `set`, `set:sys`, `time:u/:a/:s`. Dazu kommen **68 `HLE_FUNC`-Überschreibungen** einzelner Gast-Symbole (u. a. `nvnBootstrapLoader`, `nn::vi`, `nv::`, `nn::pl`, `nn::swkbd`, `movie::`).

### 1.6 Größe und Zeiten bei LASRecomp und Let's Go

- **Let's Go: 123.612 Funktionen, ca. 550 MB C: nicht verifiziert.** Weder diese Zahlen noch „letsgo“ kommen im Klon vor (`grep -ri` über den gesamten Klon ohne Treffer). Daher lässt sich aus den Notizen **kein** Let's-Go-Verhältnis „C-Zeilen je Instruktion“ ableiten. Stattdessen wurde das Verhältnis direkt an BDSP gemessen (Abschnitt 2.4). Zum Vergleich nur als Rechenbeispiel: 550 MB / 123.612 wären 4,4 KB je Funktion; BDSP-`main` liegt bei 3,9 KB (gemessen).
- Compile-Zeit bei LAS: nur der Hinweis „a few minutes“ (`runtime/ui/launcher.mm:282`, Aufbau der Spielbibliothek beim ersten Start). Eine Messung steht nicht im Klon.

### 1.7 Größe der Runtime (gemessen, `wc -l`, Klon-Stand 77 Commits)

| Verzeichnis | Zeilen | Anmerkung |
|---|---:|---|
| `runtime/*.c, *.h` (Kern) | 5.351 | Kernel 868, IPC 246, Dispatch 289, Loader 185, main 188, `cpu.h` 197, `simd.h` 818, `simd_fp.h` 340, Gamebuild/Settings/Paths u. a. |
| `runtime/hle/` | 6.462 | davon allgemein nutzbar nur rund 2.000 (Input 515, Movie 796, Heaps 163, Bindings 228, `pl`, `vi`, `swkbd`, `nvn_boot`, `framepace`); der Rest (rund 4.400) ist Zelda-/Randomizer-spezifisch (Warp, Digs, Miniboss, Pets, …) |
| `runtime/services/` | 2.452 | Audio 1.251, FS 618, AM 236, Time 139, HID/Set 103, ACC 57, Misc 48 |
| `runtime/nvn/` (Metal-Pfad: `*.c`, `*.m`, `maxwell/`) | 9.534 | `renderer.m` 2.701, `translate.c` 2.165, `metal.m` 1.191, `texpatch.c` 1.043 (LAS-spezifisch), `objects.c` 806, `astc.c` 524, `cmdbuf.c` 451 |
| `runtime/nvn/vulkan/` | 6.019 | für uns unnötig |
| `runtime/platform/` | 943 | macOS 167 |
| `runtime/ui/` | 6.479 | Randomizer-/Start-UI, nicht übernehmen |
| `tools/*.py` | 4.659 | Lifter 728, `simd_c.py` 1.156, Generator 630, `patches.py` 687 (LAS-Adressen), Tests |

Ohne UI, Vulkan und Spielspezifika bleibt ein **übernehmbarer Kern von grob 18.000 bis 20.000 Zeilen** (Kernel, IPC, Dispatch, Loader, SIMD, allgemeine Dienste, Maxwell-Übersetzer, Metal-Renderer) plus 3.000 Zeilen Generator. *Schätzung* aus den obigen Zählungen.

---

## 2. Messung am BDSP-NSO

### 2.1 Module und Segmente (gemessen, `recomp_survey.py nso`)

| Modul | Datei | text | ro | data | bss | Image | Instr. (4 B) | Dynsym: Imp. / Exp. |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| rtld | 7.187 | 6.240 | 3.384 | 600 | 3.496 | 16.384 | 1.560 | 19 / 0 |
| main | 37.895.896 | 47.147.568 | 27.143.648 | 5.735.456 | 4.258.784 | 84.287.488 | 11.786.892 | 1.040 / 49 |
| sdk | 5.755.393 | 5.822.768 | 6.840.808 | 416.248 | 759.304 | 13.844.480 | 1.455.692 | 13 / 26.570 |
| subsdk0 | 3.409.290 | 3.445.104 | 2.161.836 | 197.496 | 1.162.376 | 6.971.392 | 861.276 | 657 / 10.895 |
| **Summe** | 47.067.766 | 56.421.680 | 36.149.676 | 6.349.800 | 6.183.960 | **105.119.744** | **14.105.420** | |

Der Text von `main` (`0x2cf6a30` = 47,1 MB) entspricht der Ghidra-Angabe „`.text` bis `0x2df6a30`“ bei Image Base `0x100000`. Die `.plt`-Sektion der nx2elf-Konvertierung (22 MB) ist in Wahrheit der IL2CPP-Spielcode.

**Korrektur zu `docs/extraktion.md`:** „6630 .dynsym-Einträge“ ist die *Hex*-Größe der Sektion (`0x6630` Byte = 26.160 B = **1.090 Einträge**, `llvm-readelf --dyn-syms` bestätigt 1.090).

### 2.2 Histogramm der Instruktionsklassen (gemessen, `hist`, capstone 5.0.7, linear über den Text)

Klassen nach Wort-Encoding plus Mnemonic. Aliase wie `mov`, `cmp` stehen unter „Integer“. Anteile in % der Wörter des Moduls.

| Klasse | main | % | sdk | % | subsdk0 | % | Summe 4 Module |
|---|---:|---:|---:|---:|---:|---:|---:|
| Integer ALU/Move/Bitfeld | 3.673.845 | 31,2 | 600.116 | 41,2 | 360.125 | 41,8 | 4.634.626 |
| Integer Mul/Div | 50.825 | 0,4 | 13.278 | 0,9 | 11.713 | 1,4 | 75.843 |
| Integer bedingt (CSEL/CCMP) | 64.582 | 0,6 | 17.596 | 1,2 | 12.681 | 1,5 | 94.869 |
| ADR/ADRP | 436.790 | 3,7 | 36.143 | 2,5 | 17.829 | 2,1 | 490.837 |
| Load/Store GPR einzeln | 3.062.698 | 26,0 | 307.226 | 21,1 | 215.134 | 25,0 | 3.585.423 |
| Load/Store Paare GPR | 916.290 | 7,8 | 130.006 | 8,9 | 52.715 | 6,1 | 1.099.152 |
| LDAR/STLR (Acquire/Release) | 2.028 | 0,02 | 2.067 | 0,14 | 64 | 0,01 | 4.159 |
| Prefetch | 1.313 | 0,01 | 109 | 0 | 77 | 0 | 1.499 |
| **Exklusive** (LDXR/STXR/LDAXR/STLXR, CLREX) | 8.768 | 0,07 | 1.521 | 0,10 | 22 | 0 | 10.315 |
| **Atomics/LSE** (CAS, SWP, LDADD …) | **0** | 0 | **0** | 0 | **0** | 0 | **0** |
| FP/NEON/SIMD Rechnen | 557.608 | 4,7 | 19.321 | 1,3 | 5.927 | 0,7 | 582.856 |
| FP/NEON/SIMD Load/Store | 288.804 | 2,5 | 11.957 | 0,8 | 1.624 | 0,2 | 302.393 |
| **Crypto** (AES/SHA/PMULL) | 0 | 0 | 1.038 | 0,07 | 0 | 0 | 1.038 |
| CRC32 | 0 | 0 | 18 | 0 | 0 | 0 | 18 |
| System: MRS/MSR | 0 | 0 | 120 | 0,01 | 0 | 0 | 120 |
| System: Barrieren (DMB/DSB/ISB) | 858 | 0,01 | 133 | 0,01 | 51 | 0,01 | 1.042 |
| System: DC/IC/SYS/TLBI | 0 | 0 | 5 | 0 | 0 | 0 | 5 |
| System: SVC | **0** | 0 | 77 | 0,01 | 0 | 0 | 81 (inkl. rtld 4) |
| System: UDF/BRK (Trap-Füllwörter) | 99.955 | 0,85 | 19.197 | 1,3 | 5.303 | 0,6 | 124.504 |
| System: NOP/Hints | 160.556 | 1,4 | 138 | 0,01 | 61 | 0,01 | 160.758 |
| **PAC/BTI** | **0** | 0 | 2 (nur `AUTIA1716/AUTIB1716`) | 0 | 0 | 0 | 2 |
| Sprung direkt | 2.204.659 | 18,7 | 241.547 | 16,6 | 159.495 | 18,5 | 2.605.987 |
| Sprung indirekt (`BR`/`BLR`) | 99.451 (`BLR` 83.726, `BR` 15.725) | 0,84 | 22.950 | 1,6 | 8.285 | 1,0 | 130.697 |
| `RET` | 157.607 | 1,3 | 30.848 | 2,1 | 9.856 | 1,1 | 198.347 |
| nicht dekodierbar | 255 | 0 | 279 | 0,02 | 314 | 0,04 | 849 |
| **Summe Wörter** | **11.786.892** | | 1.455.692 | | 861.276 | | 14.105.420 |

Beobachtungen (gemessen): Speicherzugriffe (GPR, Paare, Acquire/Release, Exklusive, FP) sind **36,3 %** aller Instruktionen in `main`, d. h. 4,28 Mio. Stellen mit Adressumrechnung, falls man je Zugriff rebasen wollte (Abschnitt 4c). FP/NEON ist mit 7,2 % in `main` klein. Es gibt keine Atomics der ARMv8.1-Erweiterung und keine Pointer-Authentifizierung: der Code ist reines ARMv8.0 (Cortex-A57). Alle 77 SVC-Aufrufstellen liegen in `sdk` (und 4 in `rtld`), **`main` ruft nie direkt in den Kernel**.

### 2.3 Abgleich mit dem Lifter (gemessen, `lifter`; Nachvollzug an jedem Wort, nicht nur an einer Mnemonic-Liste)

Eine statische Mnemonic-Liste lässt sich aus `lifter.py`/`simd_c.py` nicht sauber ziehen, weil der Lifter nach Bitmustern dekodiert und nicht nach Namen. Deshalb wurde jedes Wort von `rtld`, `main`, `sdk` und `subsdk0` durch den Lifter geschickt und die Ablehnungen (`Unsupported`) gezählt, beide FP-Modi.

| Modul / Modus | Wörter | abgelehnt | Grund | Mnemonics |
|---|---:|---:|---|---|
| main, `asm` | 11.786.892 | **58** | „exclusive pair / CAS“ | `ldxp` 20, `stxp` 23, `ldaxp` 9, `stlxp` 6 |
| main, `c` | 11.786.892 | 58 | wie oben | wie oben |
| sdk, subsdk0 (beide Modi) | 2.316.968 | 0 | | |
| rtld, `c` | 1.560 | 1 | ein nicht dekodierbares FP-Wort (Datenwort) | |

- **Nicht abgedeckt: 58 Wörter = 29 Exklusiv-Paare in `main`**, 0,0005 % der Instruktionen; 4 von 332 verschiedenen Mnemonics. Sie sind 128-Bit-Lock-freie Operationen (typisch: Boehm-GC/Allocator oder Unity-Atomics). Eine Ergänzung ist klein (Paar laden/speichern mit 128-Bit-CAS), aber zwingend, sonst endet die Ausführung mit `rt_udf`.
- „Abgedeckt“ heißt hier: der Lifter erzeugt C. **Korrektheit ist nicht gemessen.** LAS bringt `tools/test_lift.py` (244) und `test_simd.py` (460) mit, die wir nicht ausgeführt haben.
- 100.211 Wörter in `main` werden als `trap` gelifted (UDF-Füllwörter und Datenwörter im Text). Sie dürfen nie ausgeführt werden.

### 2.4 Größe des erzeugten C (gemessen, `gensample --functions 0`: der echte Generator über alle Funktionen, nur gezählt)

| Modul | Funktionen | Instruktionen | C-Bytes (`asm`) | B/Instr. | B/Funktion | Funktionen > 100 KB (Anteil C) | größte Funktion |
|---|---:|---:|---:|---:|---:|---|---:|
| main | 217.858 | 11.786.892 | 846.020.435 | 71,8 | 3.883 | 336 (84,4 MB = 10 %) | 8,0 MB |
| sdk | 37.267 | 1.455.692 | 104.737.617 | 72,0 | 2.810 | 76 | 0,61 MB |
| subsdk0 | 13.343 | 861.276 | 62.834.635 | 73,0 | 4.709 | 74 | 0,58 MB |
| rtld | 42 | 1.553 | 109.798 | 70,7 | | 0 | |
| **Summe** | **268.510** | **14.105.420** | **1.013.702.485 ≈ 1,01 GB** | | | | |

- Modus `c` (portables SIMD): `main` 797.415.923 Byte, 67,7 B/Instr.
- Zeilen: 198.987 Zeilen für 12,3 MB Stichprobe (Stichprobe 3.000 Funktionen) = **1,25 C-Zeilen je Instruktion** (inkl. Deklarationen); Inline-asm-Blöcke fassen FP-Folgen zu einer Zeile zusammen.
- Grenzen: Die Funktionszahl ist die Zahl der Anfänge vor dem Fixpunkt (Gen-Schritt „Grenzen“), die Endzahl liegt etwas höher. Ghidra nennt 166.095 Funktionen (andere Zählweise: nur erkannte Funktionen ohne eh_frame-Splits). `main` hat 216.168 FDEs.
- **Spanne ohne Let's-Go-Verhältnis:** Mit 60 bis 90 B/Instr. (um den gemessenen Wert) und 14,1 Mio. Instruktionen ergäben sich 0,85 bis 1,27 GB. Der gemessene Wert (1,01 GB) liegt mittig. Die frühere Schätzung „0,7–1 GB“ (`docs/recomp-referenzen.md`) war leicht zu niedrig angesetzt.
- Objektcode-Größe (Stichprobe, 8 Chunks, 12,3 MB C): 3,8 MB Objektdatei, Faktor **0,31**. Auf 1,01 GB C hochgerechnet: grob **300 bis 330 MB Maschinencode** in der Bibliothek (rund das 5- bis 6-fache der 56 MB Gast-Text). *Schätzung*, nicht gelinkt.

### 2.5 Compile-Zeit (gemessen an Stichproben, Apple clang 17, `-O1` wie im Makefile, M1 Pro)

| Probe | C-Größe | Zeit | Spitzen-RAM |
|---|---:|---:|---:|
| 8 Chunks mit je 1,3 bis 1,7 MB, 3.000 zufällige Funktionen (7 von 8) | je ca. 1,5 MB | 1 bis 4 s je Chunk | ca. 200 MB (2 Messungen: 227 und 203 MB) |
| derselbe Satz, ein Chunk mit einer großen Funktion | 1,5 MB | **89 s** | |
| 9 der 10 größten Einzelfunktionen (je 1,1 bis 2,8 MB) | je 1,1 bis 2,8 MB | 13 / 39 / 49 / 1,4 / 1,0 / 1,1 / 75 / **200** / 3,2 s | bis **3,3 GB** (ein Fall mit 1,2 MB) |
| größte Funktion (8,0 MB) | 8,0 MB | **nicht kompiliert** (RAM-Grenze dieser Messung 3 GB) | unbekannt |

- Normalfall ca. 0,7 bis 0,8 MB C/s je Kern. Für 1,01 GB ergibt das rund **25 CPU-Minuten**; dazu die lange Spitze: allein die 9 gemessenen Ausreißer kosten rund 6,5 CPU-Minuten, die 8-MB-Funktion fehlt. *Vermutet:* 30 bis 60 CPU-Minuten, auf 6 Performance-Kernen eines M1 Pro **10 bis 20 Minuten Wand-Zeit**, sofern der Speicher der Ausreißer (bis 3,3 GB je Job) die Parallelität begrenzt. Das ist kein iPad-Thema (Build auf dem Mac), aber ein Build-Pipeline-Thema.
- Ursache der Ausreißer *(vermutet)*: Funktionen mit riesigem `switch`/vielen Labels (264 Funktionen in `main` fielen auf „alle Instruktionen sind Label“ zurück). Gegenmittel: weniger Optimierung für diese Funktionen, Aufteilen, bessere Sprungtabellen-Auflösung.
- Der Link-Schritt einer rund 300-MB-Bibliothek wurde nicht gemessen. Direkte `BL` reichen auf ARM64 nur ±128 MB; ld64 setzt dafür selbst Thunks (*vermutet*, nicht geprüft).

---

## 3. Schnittstelle zum Switch-System

### 3.1 Importe von `main` (gemessen, `imports`; Dynsym des NSO)

`main` hat 1.090 Dynsym-Einträge, davon **1.040 Importe** (1.026 Funktionen, 10 Objekte, 4 weak-Marker) und 49 Exporte. Anbieter (Name gegen die Exporte der übrigen Module aufgelöst): **sdk 1.013**, **subsdk0 23** (alle im Namensraum `movie`), 4 offen (`__rel_*`).

| Namensraum | Importe | Bemerkung |
|---|---:|---|
| `nn::*` (C++, `_ZN2nn`) | **733** | zweite Ebene unten |
| libc/libm (`memcpy`, `malloc`, `printf` …) | 125 | aus `sdk` (enthält nnmusl) |
| C++-ABI/Unwind/libc++ (`__cxa_*`, `_Unwind_Resume`, `std::`) | 80 | inkl. `__cxa_throw`, `__gxx_personality_v0` |
| `nnos*`/`nnsocket*`/`nnssl*`/`nnResult*` (C-API) | 20 / 21 / 21 / 4 | |
| `movie::*` (Nintendo-Multimedia) | 23 | aus `subsdk0` |
| `nv::` (Grafiktreiber-Init) | 3 | `InitializeGraphics`, `SetGraphicsAllocator`, `…DevtoolsAllocator` |
| `nvn*` | **1** | nur `nvnBootstrapLoader`; alle weiteren NVN-Funktionen holt Unity über diesen Lader per Name |
| pthread-Familie | 5 | |
| AK/Wwise, Unity-Nativsymbole | **0** | beides ist statisch in `main` gelinkt (nur Zeichenketten, z. B. `AK::…`, `UnityGfxDeviceWorker`) |

`nn::*` nach Unter-Namensraum (zweite Ebene): `hid` 102, `os` 91, `friends` 75, `socket` 60, `audio` 50, `swkbd` 43, `fs` 40, `account` 36, `ldn` 26, `irsensor` 24, `oe` 22, `bcat` 22, `ec` 21, `err` 20, `crypto` 17, `nifm` 12, `time` 10, `mem` 10, `web` 8, `ngc` 7, `prepo` 6, `util` 5, `vi` 5, `ssl` 4, `aoc` 4, `diag` 3, `pl` 3, `settings` 3, `cstd` 2, `nsd` 1, `codec` 1. Online-/Netz-Anteil (friends, socket, ldn, bcat, ec, nifm, ssl, web, prepo, ngc, nsd) ist **242 der 733** `nn::`-Importe, dazu 42 C-API-Importe (`nnsocket*`, `nnssl*`).

### 3.2 Was `sdk` und `subsdk0` sind (gemessen, soweit aus Symbolnamen lesbar)

| Modul | Größe (Text/Image) | Inhalt (aus Exportnamen) | Zweck |
|---|---|---|---|
| `rtld` | 6 KB / 16 KB | 19 Importe, 4 SVCs (`QueryMemory`, `Break`, `OutputDebugString`, `ReturnFromException`) | Laufzeit-Linker; LAS ersetzt ihn durch `module_init` in `main.c` (Initialisierungsreihenfolge) |
| `sdk` | 5,8 MB / 13,8 MB | 26.570 Exporte: 16.900 `nn::*`, 4.220 C++-ABI, 1.807 libc, 148 `nv*`, 102 pthread; enthält **die NVN-Treiberbibliothek** (exportiert `nvnBootstrapLoader`, `nvnBootstrapLoaderInternal`, `nvnDevtoolsBootstrap`) | Nintendo-SDK (`nnSdk`): Betriebssystem-Schicht, IPC-Clients, libc (nnmusl), libc++, libunwind, libpng (`nndetailImagePng…`) und die NVN-Treiber |
| `subsdk0` | 3,4 MB / 7,0 MB | 10.895 Exporte: `android` 5.249, `movie` 825, `mkvparser` 360, `mkvmuxer` 225, `mm_internal` 61, `nnAudioSink` 32 | Nintendo-Multimedia-Bibliothek (laut `NEEDED`-Eintrag von `main`; Dateiname nur als Namensvergleich): WebM/Matroska-Parser und Decoder-Hülle für den Videoplayer (VP8-WebM-Videos, `docs/daten-inventar.md`) |

- **glslc:** `sdk` enthält nur die fünf Allokator-Hooks `glslc_Alloc`, `…Realloc`, `…AllocAlign`, `…Free`, `…GetAllocator`; `main` importiert keine glslc-Funktion. Ein Shader-Compiler zur Laufzeit ist damit **unwahrscheinlich**, ein Beweis (Aufrufgraph) fehlt. Das schließt die offene Frage aus `docs/referenz-las-shader.md` (Abschnitt 4) vorläufig: *vermutlich nein*.
- NVN-Namen: In `main` stehen 524 `nvn…`-Namenszeichenketten (Zeichenketten-Scan). LAS implementiert 495 `NVN(...)`-Funktionen; **495 der 524 BDSP-Namen** haben eine Entsprechung, 29 nicht (7 davon Checkpoint-Debug, außerdem u. a. `ClearBuffer`, `DispatchCompute(Indirect)`, `Draw*Indirect`, `ReportCounter`, `SetSampleMask`, `Wait/SignalEvent/Sync`). Ob BDSP diese tatsächlich *aufruft*, ist offen; Namen im Text sind keine Aufrufe. Laut `docs/shader-audio-machbarkeit.md` kommen 5 Compute-Programme vor.

### 3.3 Umfang der nötigen HLE im Vergleich zu LAS

| Bereich | BDSP braucht | LAS bringt | Lücke |
|---|---|---|---|
| SVC | 50 laut NPDM-Maske (davon 46 im `sdk`-Text aufgerufen) | 43 | **0x20, 0x23, 0x28, 0x2F, 0x32, 0x33, 0x36, 0x5F** fehlen. `SetThreadActivity`/`GetThreadContext3` (0x32/0x33) sind das Fundament von `nn::os::SuspendThread/ResumeThread/GetThreadContext`; `main` importiert alle drei, ein Stop-the-World-GC nutzt sie typischerweise (*vermutet*, nicht im Code nachgewiesen) |
| IPC-Dienste | 47 laut NPDM | 20 Namen (12 der 47) | 35 fehlen: `audin:u`, `bcat:u`, `bsd:u`, `bsdcfg`, `caps:u/su`, `csrng`, `friend:u`, `hwopus`, `irs`, `ldn:u`, `ldr:ro`, `mii:u`, `mm:u`, `nfc:*`, `nfp:user`, `nifm:u`, `nim:eca`, `notif:a`, `nsd:u`, `ntc`, `nvdrv`, `pcm`, `pl:u`, `prepo:u`, `sfdnsres`, `ssl`, `vi:u`, `htc*`, `banana`, `ectx:aw`, `ngct:u`. Drei davon deckt LAS anders ab: `vi`/`nv` (HLE per Symbol, `hle/vi.c`), `pl` (`hle/pl.c`), `nvdrv` (NVN-HLE). Der Rest ist Netz/Online/Sensoren: *stubbar* (Rückgabe Fehler), wenn die sdk-Initialisierung dabei nicht hängt (ungeprüft). **Wirklich nötig:** `hwopus` (Opus-Dekodierung, vermutlich von Wwise genutzt; *vermutet*), `csrng`, `mm:u`/`nvdrv` (Video-Decoder), `ssl`/`bsd` nur als Fehlerstubs |
| Grafik | NVN über Loader, 524 Namen, Unity-Maxwell-Shader (13.710 Programme) | NVN-Metal-Backend (9,5 kZeilen), Maxwell→MSL (`translate.c`, 2.165 Zeilen) | Abdeckung der Shader-Opcodes ungemessen (`docs/referenz-las-shader.md` §11); Unity-spezifische Nutzung (Instancing, MRT, Compute-Skinning) ungeprüft |
| Video | 23 `movie::`-Importe | `hle/movie.c` (796 Zeilen, FFmpeg): 15 der 23 Namen vorhanden | 8 Namen fehlen (u. a. `Extractor::SetDataSource/GetTrackCount/GetTrackConfiguration`, `MediaData::FindRect/FindInt64`, `SetCoreMask`); VP8 über FFmpeg muss geprüft werden |
| Audio | Wwise über `audren` (Renderer) und `hwopus` | `audren` (1.251 Zeilen) | Opus-Dienst fehlt; Wwise-Nutzungsmuster ungeprüft |
| Dateisystem | 40 `nn::fs`-Importe, RomFS-Mount, Save, AddOn-Content | `fsp-srv` (618 Zeilen) | Save-Mount (`MountSaveData`, `EnsureSaveData`), AddOn-Content (`MountAddOnContent`) mit Unity-Datenlayout prüfen |
| HID | 102 `nn::hid`-Importe (Npad, Touch, Gyro, Vibration, IR-Sensor 24) | `hid` + `hle/input.c` (SDL) | Touch/Gyro/IR (nur teilweise nötig) |
| Account/Online | 36 `account`, 75 `friends`, 60 `socket` … | `acc:u0` | stubben |

Zusammen *vermutet*: **8.000 bis 12.000 Zeilen neue oder stark angepasste HLE/Services** zusätzlich zum übernommenen Kern (LAS: HLE 6.462 + Services 2.452 + IPC 246 = 9,2 kZeilen, davon rund die Hälfte spielspezifisch). Der Hauptaufwand liegt nicht in den Zeilen, sondern im Test gegen ein Unity-Spiel.

---

## 4. Speichermodell

### 4.1 `main.npdm` (gemessen, `npdm`, ohne Schlüssel; Aufbau nach <https://switchbrew.org/wiki/NPDM>, Felder dort gelesen)

| Feld | Wert | Anmerkung |
|---|---|---|
| Magic / Größe | `META`, 1.620 Byte | |
| Flags0 | `0x37`: 64-Bit-Anweisungen, **AddressSpace64Bit (39 Bit)**, OptimizeMemoryAllocation, DisableDeviceAddressSpaceMerge | Bit 5 war im Skript nicht ausgewiesen; Wert aus dem Rohbyte abgelesen |
| Haupt-Thread | Priorität 44, Kern 0 | Kernel-Capability `ThreadInfo`: Prioritäten 28 bis 59, Kerne 0 bis 2 |
| **Main-Thread-Stack** | **1 MiB** (`0x100000`) | LAS liest dieses Feld (`main.c:141-148`) |
| **SystemResourceSize** | **16 MiB** (`0x1000000`) | Kernel reserviert das für Seitentabellen; nötig für `MapPhysicalMemory` |
| Version | 0 | |
| Prozess-Kategorie | **kein eigenes Feld** im NPDM-Header; `MiscParams.ProgramType = 1` (Application), ACID-Flags: MemoryRegion **0 = Application**, Production, UnqualifiedApproval | |
| Kernel-Capabilities | KernelVersion 9.1, HandleTableSize **512**, MiscFlags `EnableDebug` | |
| SVC-Maske | **50 SVCs** (ACI0 und ACID gleich), Liste in `work/recomp/npdm.json` | |
| Dienste (SAC) | **47** Zugriffsnamen, keine Host-Dienste | |
| Heap-Limit | **nicht im NPDM**. Der Heap kommt aus der Application-Region und wird vom Spiel mit `SetHeapSize` bzw. `nn::os::SetMemoryHeapSize` angefragt. | |

Application-Region auf der Retail-Switch: grob 3,2 bis 3,3 GiB (*nicht verifiziert*, Sekundärquelle zu Switchbrew); LAS rechnet mit `HEAP_MAX` = 3,25 GiB (`rt.h:29`). Welchen Wert BDSP wirklich anfordert, ist **ungemessen** (kein Lauf).

### 4.2 Gast-Adressraumbedarf von BDSP (Schätzung aus Messwerten)

| Teil | Größe | Status |
|---|---|---|
| Module (text+ro+data, entpackt, 16-KiB-gerundet) | main 80,0 MB, sdk 13,1 MB, subsdk0 5,8 MB, rtld 0,01 MB = **98,9 MB** (94,3 MiB) | gemessen |
| bss | 6,2 MB (main 4,3, sdk 0,8, subsdk0 1,2) | gemessen |
| `main`-Image gegen LAS-Slot | **84,3 MB > 64 MiB** (`SDK_BASE - MAIN_BASE`, `rt.h:18-19`) | gemessen: Layout muss geändert werden |
| Heap | bis ca. 3,25 GiB (Switch-Limit) | Obergrenze |
| Main-Stack | 1 MiB; weitere Gast-Stacks legt das Spiel selbst im Heap an | belegt |
| TLS | 0x200 B je Thread (LAS-Fenster 1 MiB) | belegt |
| HLE-Heap der Runtime | LAS 224 MiB | belegt (`rt.h:25`) |
| NVN-Pools, Alias/Mapped Memory | liegen im Heap bzw. Alias-Bereich; Größe unbekannt | ungemessen |
| Host-Seite zusätzlich | Metal-Texturen/Puffer (Kopien aus Tegra-Swizzle), Host-Stacks | *vermutet*, ungemessen |

Ein **kompakter** Gast-Adressraum käme auf rund 3,6 bis 4,0 GiB (Heap voll ausgereizt) und passt knapp in 4 GiB. Das 12,5-GiB-Fenster ist also mehr als dreimal so groß wie der tatsächliche Bedarf; der Überschuss kommt aus dem 4-GiB-Alias-Bereich, dem 1-GiB-Stack-Fenster und den Lücken zwischen den Regionen.

### 4a. Virtueller Speicher: festes Fenster, iPadOS und die Vorgabe „no high virtual memory requirements“

**Was ist beim Start tatsächlich resident, was nur reserviert?** (aus dem Code abgeleitet; ein Lauf von LAS oder BDSP war nicht möglich, also **nicht gemessen**)

| Posten | reserviert | resident beim Start |
|---|---|---|
| Gastfenster | 12,5 GiB (`mach_vm_allocate` FIXED, `macos.c:24-28`) | nur berührte Seiten. Auf macOS bleibt alles nullgefüllt-bei-Zugriff (kein Commit, keine Überbuchung). |
| Module | im Fenster | **alles, was der Loader beschreibt**: LZ4 entpackt Text, ro und data in das Fenster (`loader.c:57-75`) → BDSP ca. **99 MB** (bss unberührt), plus kurzzeitig die gelesene NSO-Datei (ca. 47 MB, wird freigegeben) |
| HLE-Heap | 224 MiB | nur beschriebene Teile (`hle_alloc` nullt die zugeteilte Länge) |
| Host-Thread-Stacks | **256 MiB je Gast-Thread** | nur berührte Seiten; Zahl der Threads in BDSP ungemessen (*vermutet*: Dutzende: Unity-Worker, Wwise, Loader, GfxDevice, Video); 30 Threads wären 7,5 GiB nur an Host-Stacks |
| Heap (SetHeapSize) | bis 3,25 GiB | nur, was das Spiel anfasst; Unity/IL2CPP beschreibt seinen Heap schrittweise |

Auf Windows wurde das Muster „erst alles committen“ als Problem erkannt (README-Credit #107: rund 9 GB weniger committed). Auf Apple-Systemen gilt dieses Problem nicht für den **Speicherverbrauch** (Jetsam zählt berührten, „dirty“ Speicher), wohl aber für den **Adressraum**.

**Was funktioniert auf iOS/iPadOS nicht ohne Entitlement?** (Quellen unten)

| Baustein von LAS | Problem auf iOS/iPadOS | Beleg |
|---|---|---|
| Feste Adresse `0x70_0000_0000` (448 GiB) | Die höchste gültige Nutzeradresse auf arm64 außerhalb von macOS ist in den öffentlichen XNU-Headern `0xFC0000000` (ca. 63 GiB). Eine Variante bis 47 Bit steht dort nur unter `EXTENDED_USER_VA_SUPPORT` im Kernel (kernel-privat). `0x70_0000_0000` liegt über der öffentlichen Grenze: ohne Entitlement schlägt `VM_FLAGS_FIXED` dort fehl. Mit *Extended Virtual Addressing* gilt laut XNU-Code „jumbo“ = 64 GB (Blog); ob iPadOS-Kernel das 47-Bit-Fenster aktivieren, ist **nicht verifiziert** | XNU `osfmk/mach/arm/vm_param.h` (Z. 135-153), `osfmk/arm/pmap.c` laut Blog |
| Fenstergröße 12,5 GiB | Ein normaler iOS-Prozess hat laut Analyse des XNU-Codes **15,375 GiB Adressraum auf Geräten mit mehr als 3 GiB RAM, davon nutzbar 7,375 GiB** (4 GiB `__PAGEZERO` und 4 GiB Shared Region abgezogen). 12,5 GiB passen dort nicht neben Binary, Frameworks, Metal und Heap. Stand der Analyse: iOS 12 bis 15; ob das auf aktuellen iPadOS-Versionen und M-Chips noch gilt, ist **nicht verifiziert** | <https://alwaysprocessing.blog/2022/02/20/size-matters> (liest XNU-Quellcode) |
| 256-MiB-Host-Stack je Thread | zählt als Adressraum; 20 Threads = 5 GiB | `kernel.c:226` + obige Grenze |
| Re-exec bei Adresskollision | `execv` ist unter iOS nicht verfügbar (*vermutet*, nicht geprüft); außerdem hat iOS keine macOS-artige Kollision | `main.c:37-52` |
| Gast-Adresse = Host-Adresse, Konstanten im Code | zwingt zu einer *festen* Basis zur Bauzeit (Immediates aus `ADRP/ADR`, Sprungtabellen, Adress-Tabelle); eine zur Laufzeit gewählte Basis ginge so nicht | `lifter.py` (`hx(val)`), `gen.py` |
| `dlopen` der Spiel-Bibliothek | als in das App-Bundle eingebettete, signierte Bibliothek erlaubt; Erzeugen/Kompilieren auf dem Gerät nicht (das ist der „vorgepackte“ Weg) | Architekturvorgabe, nicht geprüft |
| Kein JIT nötig | Gast-Code ist AOT-kompiliert, FP/NEON als `.inst`-Inline-asm: unproblematisch (*vermutet*) | |

**Entitlements (Apple-Doku, abgerufen 2026-10-18):**

- *Extended Virtual Addressing* (`com.apple.developer.kernel.extended-virtual-addressing`, iOS/iPadOS ab 14.0): „larger addressable space“, gedacht u. a. für Spiele mit gemappten Assets <https://developer.apple.com/documentation/bundleresources/entitlements/com.apple.developer.kernel.extended-virtual-addressing>. Er **ändert nur den Adressraum, nicht das Speicherlimit**.
- *Increased Memory Limit* (`com.apple.developer.kernel.increased-memory-limit`, ab 15.0): erlaubt, das Standardlimit „on supported devices“ zu überschreiten; die App muss auch ohne zusätzlichen Speicher funktionieren, verfügbare Menge über `os_proc_available_memory` <https://developer.apple.com/documentation/bundleresources/entitlements/com.apple.developer.kernel.increased-memory-limit>. Ein Praxisbericht (iPhone 17 Pro, 8 GB) zeigt, dass es die Residenzgrenze hebt und auf Geräten mit 4 GB RAM nichts ändert <https://zenn.dev/mtfum/articles/ios_memory_entitlements>. Konkrete Jetsam-Limits je iPad-Modell veröffentlicht Apple nicht; Foren-Zahlen (z. B. „ca. 6 GB bei 8 GB, ca. 12 GB bei 16 GB“) sind **nicht verifiziert**. Messen mit `os_proc_available_memory` auf dem Zielgerät.
- **Kostenloses Personal Team:** Apples Tabelle „Supported capabilities (iOS)“ führt *Extended Virtual Addressing* nur für ADP und ADEP (bezahlt), **nicht** für „Apple Developer“ (kostenlose Konten) <https://developer.apple.com/help/account/reference/supported-capabilities-ios> (HTML-Tabelle gelesen). Gleiches gilt für „Increased Debugging Memory Limit“. *Increased Memory Limit* steht in dieser Tabelle **gar nicht**; ob Xcode es mit einem Personal Team zulässt, ist **nicht verifiziert** (*vermutet*: nein; vorab mit einem leeren Testprojekt prüfen).

**Widerspricht ein festes 12,5-GiB-Fenster der Vorgabe „no high virtual memory requirements for ios compatibility“ (`goal.md`)?** Ja, in dreifacher Hinsicht (belegt aus den Quellen oben): (1) die Fenstergröße übersteigt den Standard-Adressraum, (2) die feste Adresse liegt außerhalb der öffentlichen Grenze und wäre höchstens mit Entitlement plus passendem Kernel erreichbar, (3) der Ausweg über Extended Virtual Addressing steht dem kostenlosen Team nicht zur Verfügung. Das Modell „Gast = Host-Adresse, fest verankert“ ist **für iPadOS ungeeignet**, auch wenn es auf macOS trägt. Der Speicherverbrauch (Jetsam) wäre nicht das Hauptproblem, sondern der Adressraum.

### 4b. Alternative: Pointer-Rebasing / 32-Bit-Offsets im erzeugten C

| Variante | Idee | Aufwand (Schätzung) | Risiko |
|---|---|---|---|
| **A: Basis zur Laufzeit** | Gastadressen bleiben 64-Bit-Werte, aber alle eingebackenen Konstanten (`ADRP/ADR`, Literal-Loads, Sprungtabellen-`case`, Adresstabellen) werden `g_base + off` | Lifter und Generator: ca. 437.000 ADR/ADRP-Stellen in `main` plus Tabellen; Runtime unverändert (Gast=Host bleibt, nur die Basis wandert) | Das Fenster muss trotzdem an einer vom System gewählten Stelle liegen und alle Gast-Zeiger (z. B. gespeicherte vtable-Zeiger, Relokationen) müssen zur Laufzeit korrekt gesetzt werden; 12,5 GiB bleiben zu groß, also müsste das Fenster auf ≤ 4 GiB schrumpfen. Mittel |
| **B: 32-Bit-Offsets** | Gastzeiger sind Werte < 4 GiB. Jeder Zugriff wird `*(T*)(g_base + (uint32_t)ea)`; konstante Gastadressen bleiben unverändert (Basis 0 zur Bauzeit). Die Runtime liefert dem Gast nur Adressen < 4 GiB (Heap, Stacks, TLS, Module selbst platziert) | Lifter: Speicher-Emission an rund 11 Stellen in `lifter.py` (`LD*/ST*`, Paare, Exklusive, `DC ZVA`, Literal), plus Inline-asm-Pfad für FP/NEON (289.000 Zugriffe in `main`: Basisregister vor dem Befehl auf Hostadresse setzen, nach Write-back zurückrechnen) oder FP im `c`-Modus; Runtime: **ca. 456 `(uintptr_t)`-Umwandlungen und 209 getypte Zeiger-Casts** in HLE/Services/NVN/Kernel (`g2h()` einführen), `G()`-Makro in `nvn.h`. Grob **3 bis 6 Wochen** für Generator+Runtime-Umbau, danach lange Fehlersuche | Stille Abschneide-Fehler (Gast speichert Zeiger mit Tag-Bits oder 39-Bit-Annahmen; LAS selbst nennt die 39-Bit-Grenze, `rt.h:14`), Boehm-GC und Unity packen eventuell Zeiger; zusätzlicher Add je Speicherzugriff (ARM64 hat `ldr x, [base, w, uxtw]`, daher *vermutet* kaum Mehrkosten); Debugging schwerer (Absturz statt Zugriff auf falsche Adresse) |
| **C: Fenster verkleinern, feste niedrige Adresse** | Basis zur Bauzeit z. B. unter 7 GiB | wenig Aufwand (Konstanten in `rt.h`) | auf iOS nicht garantiert frei (ASLR, Frameworks); nur als Experiment auf dem Gerät testbar |

Einschätzung: **B ist der belastbare Weg für iPadOS**, weil er den Adressraum auf ≤ 4 GiB bindet, unabhängig von der Plattform-Basis ist und ohne Entitlement auskommt. Er macht aus dem Lifter ein anderes Produkt (kein 1:1-Port von LAS mehr) und kostet die Einfachheit „Gast=Host“. Auf **macOS** reicht das feste Fenster.

---

## 5. Unity-spezifische Risiken und Aufwandsliste

| Bereich | Befund | Ersatz/Aufwand | Status |
|---|---|---|---|
| **C++-Exceptions (IL2CPP)** | `main` importiert `__cxa_throw`, `__cxa_allocate_exception`, `__cxa_begin/end_catch`, `__cxa_rethrow`, `_Unwind_Resume`, `__gxx_personality_v0`; `sdk` enthält libunwind (`_Unwind_RaiseException`); **2.917 Funktionen mit LSDA** (Landing-Pads) von 216.168 FDEs; zusätzlich `setjmp`/`longjmp` in `main` | Landing-Pads liegen mitten in Funktionen, ein Sprung des Unwinders dorthin ist per `rt_dispatch` unmöglich (Funktionsanfänge nur), und `RET` kehrt zum Host-Aufrufer zurück, nicht zum Gast-Aufrufer. **Das Modell „Host-Stack = Gast-Stack“ bricht bei jedem gefangenen Managed-Exception.** Lösungen: Landing-Pads als Einsprungpunkte erzeugen und Stack-Abwicklung ersetzen (Host-`setjmp` je Funktion mit LSDA, eigener Unwinder auf `.eh_frame`, oder Fehlerrückgabe-Konvention). Forschungs- und Generator-Aufwand. | gemessen/belegt; Aufwand *vermutet* hoch (Wochen bis Monate) |
| **Boehm-GC (libil2cpp)** | `GC Warning …`-Zeichenketten (13) und `GC_general_register_disappearing_link` in `main`: Boehm. Er scannt Stacks, Register und Datensegmente konservativ und hält Threads an (`SuspendThread`/`GetThreadContext`, im Import vorhanden) | Gast-Register stehen in `Cpu` (gut: scannbar), aber ein beliebig angehaltener Host-Thread kann Gast-Werte in Host-Registern halten. Nötig: kooperative Sicherheitspunkte (Poll an Funktionseintritt und Schleifenrücksprung, das kostet) oder `thread_suspend` + `thread_get_state` (Mach, unter iOS für eigene Threads *vermutet* erlaubt, nicht geprüft). SVC 0x32/0x33 fehlen in LAS. | belegt/vermutet |
| Engine-Threads | Strings: `UnityGfxDeviceWorker`, `Loading.PreloadManager`, `Loading.AsyncRead`, `Background Job`, `AK::IOThread` | laufen als Host-Threads wie bei LAS; Zahl und Stackbedarf ungemessen; Host-Stack je Thread kleiner wählen (256 MiB zu groß für iOS) | belegt/offen |
| Job-System/Worker | Unity-Jobs über `nn::os`-Threads, Kern-Masken, Events | Threads und `WaitForAddress` sind da | vermutet |
| Wwise | statisch in `main` (AK::-Strings), Ausgabe über `audren`, Dekodierung vermutlich `hwopus`; Streaming-I/O-Thread | `audren` übernehmen (1.251 Zeilen), `hwopus` neu (libopus), Wwise-Soundbanks laufen unverändert (1:1) | vermutet |
| VideoPlayer | 23 `movie::`-Importe aus `subsdk0` | `hle/movie.c` (15/23) ergänzen, VP8-Dekodierung über FFmpeg/VideoToolbox prüfen; VP8 auf iOS ungeprüft (`docs/kernziel.md`) | belegt |
| `nn::fs` | 40 Importe, RomFS-Mount (aus unserem `work/romfs` oder Paket), SaveData, AddOn | `fsp-srv` ausbauen; Save-Layout ist durch `docs/save-format.md` bekannt (Nutzervorgabe: Savegame-Kompatibilität bleibt erhalten, weil der Gast-Code unverändert schreibt) | belegt |
| `nn::hid` | 102 Importe, Npad, Touch, Gyro, Vibration | `hle/input.c` (SDL) als Muster; Touch/Gyro für iPad nativ ergänzen | belegt |
| `nn::audio` | 50 Importe | `audren`/`audout` vorhanden, `audin` fehlt (Mikrofon, *vermutet* ungenutzt) | belegt |
| `nn::account` | 36 Importe (Benutzerwahl, UID für SaveData) | `acc:u0` vorhanden, muss die Unity-Aufrufe tragen | vermutet |
| Online/Pia/NEX | `friends`, `ldn`, `bcat`, `ec`, `nifm`, `ssl`, `socket`: 242 `nn::`-Importe plus 42 C-API-Importe | Stubs mit Fehlercodes; Game-Logik soll offline laufen (`docs/spielcode-inventar.md`: Online stubbar) | vermutet |
| Grafik | Unity-NVN-Pfade, 13.710 Shader-Programme | Maxwell→MSL aus LAS (siehe `docs/referenz-las-shader.md`); Unity nutzt mehr Features als LAS (MRT, Instancing, Compute, Tessellation nicht) | offen |

**Vergleich mit LAS (Eigenengine):** Für LAS spricht, dass kein Managed-Runtime-Unterbau (GC, Exceptions, Reflection-Metadaten, Threads in großer Zahl) beteiligt ist; das Spiel ruft vergleichsweise einfach in nn/NVN. Bei BDSP kommt die gesamte Unity-Engine samt IL2CPP-Laufzeit, Wwise und Videopfad **mit**, die ohnehin mit dem Gast-Code mitgezogen werden müssen. Dafür spricht bei BDSP, dass die Rekompilation alles auf einmal liefert (1:1 inklusive Engine-Verhalten und Spiellogik) und dass die Instruktionsabdeckung außergewöhnlich gut ist (58 von 14,1 Mio. Wörtern). Dagegen sprechen Exceptions, GC-Thread-Anhalten, der 3,3-GB-Compiler-Ausreißer, die iPadOS-Adressraumfrage und die Größe (1 GB C, rund 300 MB Maschinencode).

---

## 6. Optionsvergleich

**(D)** Unity-6-Rebuild mit handrekonstruierter Logik (aktuell ca. 39.100 Methoden Spiellogik, `docs/spielcode-inventar.md`) gegen **(R)** LAS-artige Rekompilation des gesamten NSO inklusive Unity-Engine.

| Kriterium | (D) Unity-6-Rebuild | (R) Rekompilation des gesamten NSO |
|---|---|---|
| Treue 1:1 | Nur so gut wie die Rekonstruktion: Logik von Hand (39.100 Methoden), Engine-Verhalten (Unity 6 statt 2019.4.27), Shader ersetzt/übersetzt. Differenzen in Zufall, Timing, Reihenfolge sind möglich und müssen gegen das Original geprüft werden. | **Logik und Engine-Verhalten automatisch gleich**, solange CPU-Lifter, Kernel/IPC-Nachbildung und GPU-Pfad stimmen. Abweichungen kommen aus den Nachbauten (Zeit, Threads, GC-Timing, Float-Details), nicht aus Handarbeit. |
| Aufwand | sehr hoch, wächst mit Spielumfang (Kampf 12.575 Methoden, UI 7.723, Feld/Entities 6.613, …); gut parallelisierbar und inkrementell | hoher Anfangsaufwand (Kern übernehmen, Generator für 3 Module, Exceptions, GC-Anhalten, ~35 Dienste, Speichermodell B), dann *vermutet* kleinere Restmenge; Vorhersage schwer, weil ein Fehler überall wirkt. Zeitbedarf: **nicht schätzbar ohne Phase-2-Spike** |
| Hauptrisiken | Umfang; stille Abweichungen; Unity-6-Unterschiede (2019 → 6) bei Physik, Animation, Timeline, Shader | C++-Exceptions des IL2CPP-Runtimes (Kernblocker), Boehm-GC/Thread-Suspend, Speichermodell iPadOS, Build-Größe/-Zeit, Maxwell-Shader-Abdeckung, Leistung (Register im Speicher) |
| Kernziel (Repo ohne abgeleiteten Code) | erfüllt: eigener Code, Daten kommen aus dem Dump | **erfüllbar, aber mit Pipeline-Pflicht:** Repo enthält nur Recompiler und Runtime; das erzeugte C (1 GB) und die Bibliothek entstehen lokal beim Bauen (`work/`, gitignoriert) und stecken nur im lokalen, nicht weitergegebenen Binary. Der Bau muss auf dem Entwicklungsrechner laufen (Xcode kompiliert das C). Wichtig: Der Generator darf keine Adressen/Spielbytes in Quelltexten einchecken (die LAS-eigenen `patches.py` mit Spieladressen wären daher nicht übernehmbar). |
| iPad-Speicher/Performance | Unity 6 auf iPad: bekannte Größenordnung; Speicher steuerbar | Adressraum nur mit Variante B (≤ 4 GiB) möglich; Gast-Heap bis ca. 3,25 GiB plus Host-Kopien der GPU-Daten könnten bei 8 GB-Geräten ohne Increased Memory Limit eng werden (ungemessen); Leistung *vermutet* 2× bis 5× unter nativ wegen `Cpu`-Struktur und Dispatch (**nicht gemessen**); Binary 300 MB+ |
| Wartbarkeit | normaler C#-/Unity-Code, lesbar, testbar | Generator + Runtime sind eigenes Compilerprojekt; LAS-Quelle ist laut README „fast ausschließlich“ KI-generiert (Qualität unklar); Updates des Spiels (anderer Build) erzwingen Neu-Lift und Adressanpassungen; Debugging nur über Host-Backtrace `f_<adresse>` |
| Rechtslage (keine Rechtsberatung) | Nachbau der Logik in eigenen Worten/Code; die Nähe zur Original-Logik (Nachprogrammieren aus Decompiler-Ausgabe) bleibt eine offene Frage | Das erzeugte Artefakt ist eine mechanische Übersetzung des Nintendo-Codes. Es wird nicht weitergegeben, bleibt aber ein abgeleitetes Werk des Nutzers; das Muster „Repo + eigener Dump“ bleibt gleich. LASRecomp ist MIT mit Ausschluss von Spieldateien, Beitragende sind teils KI-generiert. Vor einer öffentlichen Weitergabe rechtlich klären. |

---

## 7. Empfehlung als Optionen mit Bedingungen (keine Entscheidung)

**Option 1: Bei (D) bleiben.** Sinnvoll, wenn Phase 2 unten an einem Blocker scheitert oder die Zeitvorgabe für die Rekompilation zu knapp ist. Keine neuen Abhängigkeiten.

**Option 2: Spike-Phase 2 für (R) („kleinstes lauffähiges Stück“)**, in dieser Reihenfolge und jeweils mit Abbruchkriterium:

1. **Exception-Test (Ausschlusskriterium).** Ein Minimalbeispiel: `rtld`+`main`+`sdk` bis zum ersten gefangenen Managed-Exception-Pfad; die Lösung (Landing-Pad-Einsprung plus Stack-Abwicklung) in einem Tag-Spike entwerfen und an 3 realen Funktionen mit LSDA prüfen. Scheitert das, ist (R) für BDSP nicht tragbar.
2. **Lifter-Ergänzungen:** `LDXP/STXP/LDAXP/STLXP` (58 Wörter), dritte Dispatch-Tabelle für `subsdk0`, Modul-Layout mit größerem `main`-Slot; SVC 0x32/0x33/0x36/0x28/0x2F/0x23/0x20/0x5F.
3. **Nur `rtld`+`sdk`+`subsdk0`+`main` bis `nnMain`** auf dem Mac: Ziel „erste Zeile Log aus dem Unity-Start“ (ohne Grafik). Messen: Start-RAM resident gegen reserviert, Zahl der Threads, `SetHeapSize`-Wert, Anzahl nötiger Dienste.
4. **Compile-Zeiten:** vollständige Generierung auf Platte (1 GB), Build mit `-O1`; Ausreißer isolieren (Funktionen > 1 MB mit `-O0`/`optnone`).
5. **Speichermodell B** zuerst im Generator mit Schalter (`--rebase32`) für eine kleine Teilmenge testen, bevor die Runtime umgebaut wird. Auf einem iPad: Testprojekt mit 4-GiB-Reservierung ohne Entitlement (Personal Team) und `os_proc_available_memory` ausgeben.
6. **Grafik zuletzt:** Unity-Maxwell-Programme gegen `translate.c` (Instruktionsabdeckung, `docs/referenz-las-shader.md` §11).

**Bedingungen, unter denen (R) tragfähig bleibt:** (a) Exceptions und GC-Thread-Anhalten sind lösbar, (b) 32-Bit-Offsets laufen mit BDSP (keine Pointer-Tags), (c) Gesamtbau unter ca. 30 Minuten auf dem Mac, (d) Leistung auf iPad (M-Chip) reicht für 60 FPS (Messung am Spike), (e) die Rechtslage ist für den persönlichen Gebrauch akzeptiert.

**Hybrid (*vermutet* sinnvoll):** (R) als **Referenzimplementierung** zum Treuevergleich für (D) (gleiche Eingaben, Zustandsvergleich), auch wenn (R) nicht auf dem iPad ausgeliefert wird.

---

## 8. Offene Punkte und nicht Verifiziertes

- Let's-Go-Zahlen (123.612 Funktionen, 550 MB C): **nicht verifiziert** (nicht im Klon).
- Keine Laufzeitmessung: Speicher resident, Threads, Leistung, Heap-Wert von BDSP.
- Korrektheit des Lifters und Gleichheit der Float/NEON-Semantik: nicht geprüft, nur Abdeckung.
- Zahl der Funktionen vor/nach Fixpunkt, Zahl der Code-Zeiger-Relokationen: nur teilweise gemessen.
- Jetsam-Limits je iPad-Modell, Adressraum auf aktuellen iPadOS-Versionen: nicht verifiziert; Xcode-Verhalten von *Increased Memory Limit* mit Personal Team: nicht verifiziert.
- Die 8-MB-Funktion (größte, 8.010.651 Byte C) wurde nicht kompiliert; Link-Zeit und -Verhalten der 300-MB-Bibliothek ungemessen.
- Frühere Aussagen in `docs/recomp-referenzen.md` („Spielcode wird beim Nutzer kompiliert, das geht auf iPadOS nicht“) gelten für LAS' Start-Setup, nicht für den vorgepackten Weg; „0,7–1 GB C“ ist jetzt gemessen (1,01 GB).
