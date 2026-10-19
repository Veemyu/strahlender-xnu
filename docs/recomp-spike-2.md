# Rekompilations-Spike Phase 2 (`ap-recomp-spike-2`): Gegenprobe zur Frage „statische Rekompilation als Hauptweg?“

Stand: 2026-10-19 (Endstand des Spikes, die Zwischenmeldung nach Schritt 1 steht unverändert am Anfang). Grundlage: `docs/recomp-machbarkeit.md` (Phase 1), `docs/architektur-entscheidung.md` (Entscheidung 2, revidierbar), `docs/referenz-las-shader.md`, `docs/ipad-messung-1.md`.
**Auftrag:** nur messen und kleinste Prototypen, mit Abbruchkriterien. Keine Rechtsberatung. Aus `research/LASRecomp` (MIT, ausdrückliche Freigabe des Nutzers) wurde **nichts kopiert**: die Skripte unter `scripts/recomp/` importieren Lifter und Generator des Klons zur Laufzeit (wie `scripts/recomp_survey.py`) und ergänzen sie. Keine Spielbytes, kein erzeugter Code und keine Spieladressen im Repo; alles Erzeugte liegt unter `work/recomp/` (gitignoriert).

**Kennzeichnung:** **gemessen** = mit den Skripten unter `scripts/recomp/` am lokalen Dump ermittelt. **belegt** = im Klon oder in einer genannten Quelle gelesen. *vermutet* = Schluss ohne Test. **nicht verifiziert** = nicht prüfbar.

## Zwischenstand nach Schritt 1 (Exception-Test, Ausschlusskriterium)

**Ergebnis: bestanden. C++-Exceptions sind im LAS-Modell lösbar (Variante a), mit dem unveränderten Gast-Unwinder des Spiels.** Das Ausschlusskriterium aus `docs/recomp-machbarkeit.md` (Abschnitt 5, Zeile „C++-Exceptions“) entfällt damit als Blocker. Aufwand für die Produktionsreife: **grob 1 bis 2 Wochen** (Abschnitt 1.6), keine Forschungsfrage mehr.

| Frage | Ergebnis | Status |
|---|---|---|
| Läuft der echte Unwinder des SDK (`_Unwind_RaiseException`, `unw_*`, `__gxx_personality_v0`, `__cxa_*`) rekompiliert unverändert? | **Ja.** Er läuft als erzeugtes C auf dem Gast-Stack, liest die Gast-Rahmen über `.eh_frame`/`.eh_frame_hdr` und ruft die Personality als rekompilierten Gastcode. | gemessen (Test T1 bis T5) |
| Throw → Catch über ≥ 2 rekompilierte Rahmen mit korrektem Zustand | **Ja:** 3 Gastrahmen dazwischen (Aufräumen in 2 Rahmen, Fang im 4.), callee-saved Register und Reihenfolge der Destruktoren stimmen; Rethrow (`catch (...)` + `throw;`) ok; **200 Rahmen** mit Landing-Pads ok; Wurf aus **echtem SDK-Code** (`operator new` → `std::bad_alloc`) ok. Gegenprobe unter Unicorn (echte ARM64-Semantik) liefert dieselben Werte. | gemessen |
| Zusätzliche Mechanik nötig | Rahmeneintrag + `_setjmp` je Gastfunktion mit Wiedereinstiegspunkt, Wiedereinstieg im `rt_dispatch`-Fehlpfad, `ret` nach `mov sp` als indirekter Sprung (3 Stellen im SDK: libunwind-`jumpto`, `longjmp`). Zusammen ca. 350 Zeilen Python (Generator-Erweiterung) und 30 Zeilen C (Laufzeit). | gemessen |
| Gefunden und behoben | Der Standardgenerator zerschneidet Funktionen an `adr`-Sprungtabellenbasen (610 Stellen im SDK); Folge: Switch-Tabellen der libunwind nicht aufgelöst, Absturz im Unwinder. Mit Korrektur 515 statt 41 aufgelöste Tabellen. **Betrifft jede Funktion mit kompakter Sprungtabelle, nicht nur Exceptions.** | gemessen |
| Kosten | 44,8 µs je Wurf+Fang über 4 Rahmen (`-O1`, ein Thread, Dispatch ohne Cache) = ca. 22.000 Würfe/s; Rahmeneintrag nur in den 3.447 Funktionen mit Wiedereinstiegspunkt (von 270.299 erzeugten). | gemessen |
| Beweis an echten BDSP-Funktionen | 180 echte LSDA-Funktionen aus `main` ausgewählt (je 60 nur Aufräumen / typisierter Catch / `catch (...)`; ein erster Lauf mit 45 zeigte dasselbe): bei **100** erreichte der Lauf einen Aufruf mit Landing-Pad und **in allen 100** wählte der echte Gast-Unwinder exakt das Landing-Pad, das ein unabhängiger LSDA-Parser vorhersagt; Aufräumcode und `_Unwind_Resume` liefen, die Ausnahme erreichte den Fänger darüber (bei 6 `catch (...)`-Funktionen fing die Funktion selbst). Die übrigen 80 scheiterten an der synthetischen Umgebung (25 erreichten keinen gedeckten Aufruf, 55 stürzten durch Nullzeiger-Daten ab oder liefen in eine Endlosschleife), nicht am Unwinder; 0 Abweichungen. | gemessen (Abschnitt 1.5) |
| Urteil | **Lösbar**, ca. 1 bis 2 Wochen Produktionsarbeit (Abschnitt 1.6). | |

### Zwischenstand der übrigen Schritte (Details in den Abschnitten 2 bis 6)

| Schritt | Ergebnis | Urteil |
|---|---|---|
| 2 GC/Thread-Anhalten | `thread_suspend` + `thread_get_state` auf eigenen Threads: 8 µs je Thread bei 1 bis 4 Threads (16 bis 64 Threads auf der ausgelasteten Maschine 0,07 bis 0,09 ms je Thread). Boehm selbst nutzt genau diese Aufrufe auf Apple-Plattformen. An rekompiliertem Gastcode fand ein asynchrones Anhalten das Objekt in 19.293 von 19.293 kritischen Fenstern allein im `Cpu`-Speicher (jeder Gast-Speicherzugriff und Aufruf erzwingt die Rückschrift); die Mach-Register bleiben als zusätzliche Absicherung. Alternative kooperative Sicherheitspunkte: bis 12 % im Extremfall, vermutlich 1 bis 4 % real. | lösbar, 2 bis 4 Tage |
| 3 Speichermodell | `--rebase32` als Header-Schalter (ca. 90 Zeilen): der komplette Exception-Test mit dem echten SDK läuft mit **allen Gastadressen < 4 GiB** und Zugriff `g_base + (uint32_t)ea` unverändert grün (47,0 statt 44,8 µs je Wurf). Zeiger-Tags/39-Bit-Annahmen: im Code von `main` keine gefunden (nur 4 Masken mit 48 Bit, 1 mit 40 Bit; 0 verdächtige Tag-Befehle in 11,8 Mio. Wörtern). | tragfähig; ca. 1,5 bis 3 Wochen (statt 3 bis 6) |
| 4 Teilbau | Alle vier Module erzeugt: 270.299 Funktionen, 992 MB C in 74 s; übersetzt in **15,6 min Wanddauer** (3 parallele Compiler, ausgelastete Maschine; CPU-Summe 45 min); Bibliothek **224 MiB** (`__text` 210 MB); größter Compiler-Spitzenwert 1,7 GB (nicht 3,3 GB); langsamste Datei 214 s. | tragfähig |
| 5 Kleinstes lauffähiges Stück | `main`+`sdk`+`subsdk0` rekompiliert laden (RSS 101 MiB), `nn::init::Start` laufen lassen: `nnosInitialize` und alle 115 Konstruktoren des SDK laufen durch, dann **erster harter Blocker: IPC** (`sm:`, `lm`, CMIF-Domain, danach `apm`, `appletOE`, `aoc:u`, `ectx:aw`, `pctl*`). Bis dahin 8 verschiedene SVCs, 29 Aufrufe, 0 Threads, 105 MiB RSS. | kein CPU-/Exception-/Speicherblocker; Blocker = erwartete Dienstschicht |

**Zusatz Leistung (Abschnitt 4a):** Mikro-Benchmarks desselben C-Codes rekompiliert gegen nativ auf dem Mac: **Faktor 1,4 bis 4,3** (Ganzzahl ca. 2, Aufrufe/FP 3 bis 4).

**Vorläufige Empfehlung (Abschnitt 6):** Hybrid. R wird von „zurückgestellt“ auf „parallel verfolgter Hauptkandidat mit Entscheidungspunkt“ gehoben (Phase 3, 4 bis 6 Wochen auf dem Mac), D läuft unverändert weiter, startet aber keine neuen großen Rekonstruktionsblöcke bis zum Entscheidungspunkt.

---

## 1. Exception-Test (Ausschlusskriterium)

### 1.1 Befund: was im Spiel vorkommt (gemessen, `scripts/recomp/eh_lsda.py survey|cfa`)

| | main | sdk | subsdk0 | rtld |
|---|---:|---:|---:|---:|
| FDEs (`.eh_frame`) | 216.168 | 29.434 | 9.844 | 26 |
| FDEs mit LSDA (Landing-Pads) | **2.917** | 508 | 0 | 0 |
| Call-Sites in den LSDA-Tabellen | 26.631 | 2.802 | | |
| Landing-Pads (verschiedene Adressen) | 14.887 | 1.601 | | |
| Landing-Pads je Funktion (Median / Maximum) | 3 / 162 | 2 / 32 | | |
| Call-Sites ohne Handler / nur Aufräumen | 9.257 / 3.866 | 937 / 1.087 | | |
| Aktionsketten: typisierter Catch / `catch (...)` / Aufräumen in der Kette | 11.851 / 1.658 / 11.844 | 0 / 761 / 0 | | |
| `setjmp`-Rückkehrstellen (Wiedereinstieg bei `longjmp`) | 17 | 10 | 0 | 0 |

- **CFA-Befehle:** in keinem Modul kommen `DW_CFA_remember_state`/`restore_state`, Ausdrucksbefehle (`def_cfa_expression`, `expression`, `val_expression`), PAC-Befehle oder unbekannte Opcodes vor. Die Nintendo-Toolchain schreibt reine Sync-Unwind-Tabellen. Die libunwind des SDK **lehnt `remember_state` ab** (beim Test gefunden: ein FDE mit Opcode `0x0a` lässt die FDE-Auswertung scheitern). Das betrifft nur unsere mit neuerem Clang gebauten Testprogramme (übersetzt mit `-fno-asynchronous-unwind-tables`), nicht das Spiel.
- Funktionen mit Landing-Pads sind im Mittel 720 Byte (180 Anweisungen) groß, zusammen 2,1 MB Code in den 2.917 Funktionen von `main`.
- Personality ist überall `__gxx_personality_v0`. Die SDK-libunwind ist eine LLVM-libunwind (`unw_*`, `_Unwind_RaiseException` mit `unw_getcontext`, `unw_init_local`, `unw_step`). Der Wiedereinstieg erfolgt in `__libunwind_Registers_arm64_jumpto`: lädt alle Register aus dem Kontext, setzt `sp` und springt per `ret` (x30 = Landing-Pad) mitten in eine Gastfunktion.

### 1.2 Warum das LAS-Modell bricht (belegt, Lifter/Generator gelesen)

1. Ein Gast-`RET` wird zu einem Host-`return`; `ret` nach `mov sp, xN` (`jumpto`) wäre damit ein Rücksprung zum **Host-Aufrufer**, nicht zum Landing-Pad. Ebenso `longjmp` (`br x30`).
2. `rt_dispatch` kennt nur Funktionsanfänge; ein Landing-Pad liegt mitten in einer Funktion → „no function at …“.
3. Der Host-Stack enthält zwischen Wurfstelle und Fänger noch die Rahmen der übersprungenen Gastfunktionen; sie müssen verschwinden.

### 1.3 Entwurf der drei Varianten

| Variante | Idee | Bewertung |
|---|---|---|
| **(a) Gast-Unwinder unverändert + Wiedereinstieg über Rahmeneinträge (gewählt, prototypisiert)** | Jede Gastfunktion mit Wiedereinstiegspunkt (Landing-Pad aus der LSDA, Stelle hinter `bl setjmp`) legt beim Eintritt einen `EhRec {prev, lo, hi, sp, jmp_buf}` auf den Host-Stack, hängt ihn an `Cpu` (Offset 336, bislang freier Füllbereich) und ruft `_setjmp`. Jeder Austritt (Return, Tail-Call, Dispatch) hängt ihn aus. Der echte Unwinder (rekompiliert) arbeitet auf den **echten Gast-Rahmen**: Die Gast-Stackrahmen sind faithful, weil die rekompilierten Prologe `stp x29,x30` auf den Gast-Stack schreiben und das Gast-LR vor jedem Aufruf gesetzt wird. Am Ende ruft `jumpto` per `br x30` den `rt_dispatch` mit der Landing-Pad-Adresse; ein Fehlgriff dort ruft `rt_nle_enter`: innerster Eintrag, dessen Bereich die Adresse enthält und dessen Eintritts-SP **über** dem Ziel-SP liegt (rekursive Aufrufe derselben Funktion liegen tiefer), `_longjmp` dorthin; die Funktion verteilt per `switch (c->pc)` auf das Label. Gast-Register stimmen, weil sie ohnehin nur in `Cpu` und auf dem Gast-Stack liegen (der Unwinder stellt x19 bis x28, fp, sp aus den Rahmen wieder her, `_Unwind_SetGR` setzt x0/x1). | funktioniert (1.4, 1.5); Kosten nur in 3.447 von 270.299 Funktionen |
| (b) Eigener Unwinder auf `.eh_frame` mit Host-`longjmp` | `_Unwind_RaiseException`/`_Resume` als Host-Funktionen (HLE): CFI selbst auswerten (reicht: nur `def_cfa`, `offset`, `advance_loc`, `def_cfa_register/offset`, siehe 1.1), Personality weiterhin als Gastcode. Vorteil: schneller, kein SDK-Modulinfo (`GetExceptionInfo`) nötig. Nachteil: eigener DWARF-Interpreter (ca. 300 bis 400 Zeilen C), eine zweite Wahrheit neben dem SDK-Unwinder. | als Optimierung/Fallback möglich, nicht nötig |
| (c) Fehlerrückgabe-Konvention | Jede Funktion gibt einen Ausnahmezustand zurück, jeder Aufruf prüft. | **nicht tragbar:** 216.168 Funktionen, auch ohne LSDA-Rahmen, Aufrufe durch Funktionszeiger und HLE; Laufzeit- und Größenkosten überall |

### 1.4 Der Prototyp (`scripts/recomp/`, alles Eigenbau, LAS-Generator nur zur Laufzeit importiert)

| Baustein | Datei | Inhalt |
|---|---|---|
| LSDA-/CFA-Parser | `eh_lsda.py` | `.eh_frame_hdr`, FDE/CIE, LSDA-Call-Sites, Aktionstabellen, Typtabelle; Zahlen aus 1.1 |
| Generator-Erweiterung | `eh_gen.py` | `EhModule(gen.Module)`: Wiedereinstiegspunkte, Rahmeneintrag (`EH_ENTER/EH_POP/EH_SETJMP`), `ret`-Sonderfälle, Korrektur der Sprungtabellen-Zerschneidung (siehe unten), Teilbau (`--only`), Gesamterzeugung (`generate`, eine Kopie der Partitionsschleife von `gen.main` mit der Korrektur) |
| Laufzeit-Header | `rt/cpu.h` | `EhRec`, Makros, `#include_next` der Original-`cpu.h` |
| Mini-Linker | `mini_link.py` | ELF64-Relocatable (aarch64) → NSO + Bild + `.eh_frame_hdr` (kein aarch64-Linker auf dem Mac) |
| Bildbau | `mkimg.py` | NSO → Speicherbild mit Relokationen, Importe → Modulexporte oder HLE-Slots, schwache Importe → 0, `.mod`-Datei |
| Test | `test/eh_guest.cpp`, `test/eh_harness.c`, `test/run_eh_test.sh`, `test/uc_ref.py` | synthetisches Gastprogramm (aarch64-Clang), Host-Laufzeit, Referenzlauf unter Unicorn |

**Gefundene Randbedingungen des SDK-Unwinders** (im Test entdeckt, für das Produkt als Anforderungen an den Loader/die Laufzeit zu übernehmen):

1. FDE-Suche über `nn::ro::detail::GetExceptionInfo(info, pc)`. Im SDK implementiert über **SVC `QueryMemory`** auf dem Segmentbild (Typ 3 bzw. 8 und Recht 5 für Code, dann `MOD0` und `eh_frame_hdr`); im Test durch eine Host-Funktion ersetzt, im Produkt: `QueryMemory` mit Segmenttabelle der Module (der Probelauf in Schritt 5 liefert sie bereits).
2. `nn::os`-Mutex des FDE-Caches (Thread-Objekt, Arbitration): Host-Mutex.
3. `__cxa_get_globals` (TLS über `nn::os`): im Test Host-Block; im Produkt läuft das über den echten SDK-Start (Schritt 5).
4. `malloc/free/calloc/aligned_alloc` sind Importe des SDK und kommen aus der Anwendung (`nninitStartup`).
5. EH-Kodierungen: die libunwind der Switch-Toolchain arbeitet mit `sdata4`; der lokale Clang schreibt `sdata8` (Test wandelt im Assembler um, `test/eh_sdata4.py`).

**Gefundene Generatorlücke (betrifft jede Funktion mit kompakter Sprungtabelle):** `gen.py` macht jedes `adr`-Ziel im Text zum Funktionsanfang. Bei clang-Tabellen der Form `adr xA, T; ldrb w, [tab, idx]; add xA, xA, w, lsl #2; br xA` ist `T` die Tabellenbasis **innerhalb** der Funktion; die Funktion wurde zerschnitten, die Tabelle konnte nicht aufgelöst werden, und der Sprung ging in die Mitte einer anderen „Funktion“. Korrektur in `eh_gen.py` (`is_jumptable_base_adr`): SDK 610 Stellen, aufgelöste Tabellen **41 → 515**, Funktionen 44.718 → 38.342; `main`: 2.219 Stellen, 2.277 Tabellen aufgelöst, 284 Rückfälle auf „alle Anweisungen sind Label“. Das ist ein allgemeiner Fehler des Standardgenerators und ohne die Korrektur würde auch Spielcode falsch laufen.

### 1.5 Messung (`test/run_eh_test.sh`, `test/run_eh_real.sh`)

| Test | Inhalt | Ergebnis |
|---|---|---|
| T0 | `_Unwind_Backtrace` ohne Wurf | 2 Rahmen mit LSDA/Funktionsanfang richtig |
| T1 | `leaf` wirft `int` → Aufräumen in `mid` und `mid2` (Landing-Pads) → Fang in `test_basic`; Callee-saved-Werte und Log-Reihenfolge prüfen | Rückgabe 60/60, Log 1234/1234 |
| T2 | kein Wurf, Rahmenkette danach leer | ok |
| T3 | `catch (...)` mit `throw;` (Rethrow), Fang mit Typ weiter oben | ok |
| T4 | 200 Rahmen mit Landing-Pads | ok |
| T5 | Wurf aus echtem SDK-Code: `operator new(0x7fffffffffff)` → `std::bad_alloc` | ok (ein echter SDK-Rahmen dazwischen) |
| T6 | 20.000 Würfe, je 4 Rahmen | 44,8 µs je Wurf+Fang (`-O1`) |
| Gegenprobe | dieselben Tests unter Unicorn (echte ARM64-Semantik, gleiche Bilder und HLE-Semantik) | alle bestanden |
| Echte Funktionen (`run_eh_real.sh`, `PER_KIND=60`) | 180 echte LSDA-Funktionen aus `main` (reproduzierbar per Seed, Teilbau mit direkten Aufrufen als Dispatch-Stubs; Standard 45 Funktionen). Der erste Aufruf mit Landing-Pad **wirft** eine Ausnahme (echtes `__cxa_allocate_exception`/`__cxa_throw` des SDK, Rücksprungadresse = Aufrufstelle in der Funktion); alle Importe der Funktion laufen danach über den echten SDK-Code (PLT-Auflösung). Ein unabhängiger Parser (`eh_lsda.py`) sagt das Landing-Pad voraus. | **100 von 100** erreichten Fälle (nur Aufräumen 40, typisierter Catch 25, `catch (...)` 35): Landing-Pad stimmt, Aufräumcode läuft, `_Unwind_Resume` setzt die Abwicklung fort, der Fänger oberhalb bekommt die Ausnahme (6-mal fing die `catch (...)`-Funktion selbst). 25 ohne erreichten gedeckten Aufruf, 55 Abstürze/Zeitüberschreitungen durch die synthetische Umgebung (Argumente zeigen auf einen Seitenpuffer, der mit Selbstzeigern gefüllt ist). **0 Abweichungen, 0 Laufzeitfehler.** (Lauf mit 45 Funktionen: 25 von 25.) |

Grenzen: Der Wurf-Test belegt Auswahl des Landing-Pads und Abwicklung an echten Funktionen, **nicht** das Spielverhalten (Zustand der Funktion ist synthetisch). Bei den 25 erreichten Funktionen mit typisiertem Catch war das geworfene Typobjekt nicht das der Catch-Klausel (die Ausnahme lief weiter zum Wrapper); der Fang selbst ist durch T1/T3 (eigene Typen) belegt. Zeitlimit/Absturz bei 55 von 180 liegt an der Umgebung, nicht am Unwinder.

### 1.6 Urteil und Aufwand

**Lösbar.** Fehlend für die Produktion (Schätzung, Einzelentwickler): (1) `QueryMemory`/Modulsegmente im Lader und Mehrthread-Mutex für den FDE-Cache (1 bis 2 Tage), (2) Host-HLE-Funktionen dürfen beim Abwickeln keine Sperren halten; Thread-Beendigung/`ExitThread` mit offenen Rahmen (2 Tage), (3) Tests gegen mehr echte Funktionen und die Variante `longjmp` (17 Stellen in `main`) (2 bis 3 Tage), (4) Leistung: Dispatch-Cache und -O1-Optimierung (1 Tag). Summe **1 bis 2 Wochen**. Risiko: niedrig bis mittel (keine bekannten offenen Probleme; Unity-Code ist der größere Prüfstand: Managed-Exceptions kommen von IL2CPP über `__cxa_throw` mit `Il2CppExceptionWrapper`).

---

## 2. GC / Thread-Anhalten

**Befund (belegt):** `main` importiert `nn::os::SuspendThread`, `ResumeThread`, `GetThreadContext`; ein Boehm-GC (13 Warnstrings, `GC_general_register_disappearing_link` in `main`, siehe Phase 1) hält alle Threads an und scannt Stack und Register. LAS setzt SVC `0x32` (`SetThreadActivity`) und `0x33` (`GetThreadContext3`) nicht um.

**Prototyp** (`scripts/recomp/test/gc_suspend.c`, macOS, ohne Entitlement):

| Messung | Wert |
|---|---|
| `thread_suspend` + `thread_get_state(ARM_THREAD_STATE64)` + `thread_resume`, 1 Thread | 8,0 µs im Mittel |
| 4 Threads | 34,5 µs (8,6 µs je Thread) |
| 16 Threads | 1,45 ms (Maschine mit 14 anderen Prozessen ausgelastet; schlechtester 25 ms) |
| 64 Threads | 4,3 ms (67 µs je Thread) |
| Gastwert nur im Host-Register, **künstlicher Fall** (Inline-asm hält ihn dort) | im Mach-Registerzustand 1 von 1, im `Cpu`-Speicher 0: die API liefert den Registerzustand |
| **Rekompilierter Gastcode** (`gc_guest.c` über `eh_gen.py`, `run_gc_proof.sh`): Zeiger aus Slot nehmen, Slot leeren, 60 Rechenschritte, zurücklegen; 20.000 zufällige Anhaltepunkte | 19.293 im Fenster (Slot leer, Zeiger nur noch „im Register“): gefunden mit **`Cpu` + Gast-Stack allein in 19.293 von 19.293 (100 %)**, Host-Register/-Stack zusätzlich nötig: 0 |
| Kooperativer Sicherheitspunkt (Poll am Funktionseintritt), Worst Case: 5 winzige Funktionen je Durchlauf | +12,1 % (23,5 → 26,4 ns); reale Funktionen sind größer, *vermutet* 1 bis 4 % |

**Auswertung:**

- **Warum der Host-Zustand trotzdem in Betracht kommt:** Erzeugtes C hält Gastregister in `Cpu` im Speicher; LLVM darf Werte innerhalb einer Funktion aber in Host-Registern halten, solange kein Aufruf und kein Gast-Speicherzugriff dazwischen liegt. Der Test oben zeigt, dass das in dem Muster „Zeiger nur im Register“ **nichts verändert**: Jeder Gast-Speicherzugriff ist `may_alias` und zwingt den Compiler, `Cpu` vorher zu schreiben, jeder Aufruf `f_G(c)` ebenso (`c` entkommt). Übrig bleiben nur abgeleitete Werte, die in einer Strecke ohne Speicherzugriff berechnet werden (typisch Innenzeiger, die auf dasselbe Objekt zeigen); der Boehm-GC wertet Innenzeiger aus, und veraltete `Cpu`-Werte halten das Objekt ohnehin am Leben. Ein Fall, in dem **kein** Verweis in `Cpu`, Stack oder Heap bleibt, ist nach dem Test nicht ausgeschlossen, aber nicht erzeugt worden.
- **Lösung A (asynchron, kein Laufzeitaufschlag, empfohlen):** `SetThreadActivity(pause)` → `thread_suspend`; `GetThreadContext3` liefert den Gast-Kontext aus `Cpu` (x0 bis x30, sp, pc, Vektorregister) und spiegelt zur Sicherheit zusätzlich die 29 Host-Register und die oberen 512 Byte des Host-Stacks unterhalb des gemeldeten Gast-SP (der Boehm scannt bis dorthin; der Gast-SP selbst bleibt unverändert). Kosten: Mikrosekunden je Thread. **Rest-Risiko:** siehe oben; es braucht einen Allokations-/GC-Stresstest des echten Spiels, der hier nicht möglich war.
- **Lösung B (kooperativ):** Poll am Funktionseintritt und an Rücksprüngen im erzeugten C (`c->gc_pending`), Threads in HLE/Kernel-Warten gelten als sicher. Deterministisch, aber Laufzeitaufschlag und Generatoränderung an 218.195 Funktionen.
- **iOS/iPadOS:** `thread_suspend` und `thread_get_state` auf **eigenen** Threads sind erlaubt (kein Entitlement); belegt durch den Quelltext von Boehm `darwin_stop_world.c` (öffentlich, abgerufen 2026-10-19: `thread_suspend`, `thread_get_state`, `task_threads(mach_task_self())`, ARM-Zweige), der auf iOS genau so läuft (Unity-Mono/IL2CPP-Boehm auf iOS). Auf dem iPad **nicht selbst gemessen**.
- **Aufwand:** 2 bis 4 Tage (SVC `0x32/0x33`, `nn::os::GetThreadContext`, Test mit zwei Allokationsthreads), plus 2 bis 3 Tage Stresstest. Urteil: **lösbar**.

---

## 3. Speichermodell (32-Bit-Gastadressen)

**Schalter:** `scripts/recomp/rt32/cpu.h` und `rt32/simd.h` (zusammen ca. 90 Zeilen, `-DREBASE32 -I scripts/recomp/rt32` vor `rt`): überschreiben `LD8..LD64/ST8..ST64`, `LD128/ST128` und die Exklusiv-/Acquire-Hilfen mit `*(T*)(g_base + (uint32_t)ea)`. Der Generator bleibt **unverändert**, FP/SIMD muss im C-Modus (`--simd c`) erzeugt werden, weil die Inline-asm-Blöcke Gastadressen direkt als Hostadressen benutzen.

**Test:** derselbe Exception-Test mit dem **echten SDK-Modul** (38.342 Funktionen, `--simd c`) und **allen Gastadressen unter 4 GiB** (SDK `0x1000000`, Testmodul `0x2000000`, Stack `0x3000000`, HLE `0x8000000`, Heap `0x20000000`; Fenster per `mmap(NORESERVE)`): T0 bis T5 **bestanden**, T6 47,0 µs je Wurf (asm-Modus ohne Rebase: 44,8 µs, also +5 %). Der Host (HLE) rechnet mit `H()`/`GA()` um (Gast- nach Hostadresse und zurück); das sind im Test 20 Zeilen in einer 422 Zeilen großen Harness (Allokator, TLS, Stack, `GetExceptionInfo`). Objektgröße der SDK-Chunks 35,8 MB statt 30,3 MB (+18 %, überwiegend C-SIMD statt Inline-asm). **`main` im C-SIMD-Modus** (`--simd c`): 917 Chunks, 781 MB C (Inline-asm-Modus 828 MB); im erzeugten C steht **kein einziges `(uintptr_t)`** außerhalb der Makros, also laufen alle Speicherzugriffe über `LD*/ST*` und `ldx/stx`; 24 gleichmäßig gewählte `main`-Chunks (je ca. 1,5 MB C, 18 s mit 3 Jobs) übersetzen fehlerfrei mit `-DREBASE32`.

**Stichprobe nach Zeiger-Tags und 39-Bit-Annahmen** (`scripts/recomp/ptr_scan.py`, 11.786.892 Wörter in `main`):

| Muster | main | sdk | subsdk0 |
|---|---:|---:|---:|
| `AND` mit Maske 2^k−1, k = 39..63 (Zeigerbreite abschneiden) | 118 (davon 106 mit k = 62/63: Vorzeichen/`fabs`; **4 mit k = 48, 1 mit k = 40**) | 134 | 11 |
| `AND` mit 0xFFFFFFFF (auf 32 Bit abschneiden) | 4.681 | 9.311 | 120 |
| `ORR` mit Bit ≥ 40 gesetzt | 2.418 (die häufigsten: Bitmuster `0xAAAA…`, `0xCCCC…`, `0xFFFFFFFF00000000`, Gleitkomma-Konstanten) | 423 | 307 |
| `LSR/UBFX` ab Bit ≥ 40, `LSL` ≥ 40 | 1.605 / 23 | 859 / 36 | 428 / 6 |
| `MOVK/MOVZ/MOVN` mit hohen Halbworten | 7.424 | 7.565 | 2.477 |

Ergebnis: **kein Hinweis auf Zeiger-Tags im Anwendungscode** (die 5 Zeigerbreiten-Masken sind klein genug für eine Einzelprüfung); die Häufungen sind Bitmuster- und Gleitkommakonstanten. Kein Beweis (Daten, die als 64-Bit-Zeiger mit Flags in hohen Bits gespeichert werden, tauchen so nicht auf), aber ein günstiger Befund. Die Gast-Zeiger sind in Rebase-Modus ohnehin Werte < 4 GiB; gefährlich wären nur gespeicherte Zeiger mit Tags in den oberen 32 Bit.

**Budgetrechnung gegen iPad (gemessene Limits 5 GiB ohne, 8 GiB mit Increased Memory Limit; Warnschwellen 4,1 / 5,9 GiB; `docs/ipad-messung-1.md`):**

| Posten | MiB | Status |
|---|---:|---|
| Module (Text, ro, data, bss; Bild im Gast) | 100 | gemessen (RSS 101 MiB nach Laden von main+sdk+subsdk0) |
| rekompilierter Code (`__text` 210 MB, 224 MiB Bibliothek), nur berührte Seiten resident (sauber, ablösbar) | 50 bis 200 | *vermutet* |
| Gast-Heap (Switch-Anwendungsbereich; `SetHeapSize` von BDSP ungemessen) | bis 3.328 | Obergrenze (LAS `HEAP_MAX` 3,25 GiB) |
| Gast-Stacks und TLS | 20 bis 60 | *vermutet* |
| Host-Seite: Texturkopien (Tegra-Swizzle → Metal), Puffer als No-Copy-Wrapper um den Gast-Heap (LAS-Ansatz) | 300 bis 1.000 | *vermutet* |
| Metal/UIKit/Laufzeit | 200 | gemessen (leere Unity-Szene 180 MiB) |
| **Summe** | **ca. 3,9 bis 5,0 GiB** | |

Ohne Entitlement (5 GiB, Warnung bei 4,1 GiB) ist das **zu knapp**; mit Increased Memory Limit (8 GiB, funktioniert mit kostenlosem Team) **passt es mit 3 GiB Reserve**. Das 4-GiB-Fenster ist reserviert, nicht belegt (`NORESERVE`); die Adressraumgrenze iOS (7,4 GiB nutzbar laut Phase 1, **nicht verifiziert auf aktuellem iPadOS**) lässt 3,4 GiB für alles andere; Host-Thread-Stacks müssen deutlich unter LAS' 256 MiB liegen (Gaststack 1 MiB, Hoststack genügt in der Größenordnung 1 bis 2 MiB: ein Host-Rahmen je Gast-Aufruf, ca. 50 bis 200 Byte).

**Aufwand (Schätzung, statt 3 bis 6 Wochen in Phase 1):** Header-Schalter fertig; offen: HLE/Kernel/Dienste auf `H()`/`GA()` umstellen (Phase 1: ca. 456 `(uintptr_t)`-Umwandlungen in HLE/Services/NVN), `DC ZVA` (5 Stellen im SDK, `memset`), Asm-SIMD mit Rebase (289.000 Zugriffe in `main`: entweder Basisregister vor dem Befehl auf Hostadresse und danach zurückrechnen oder C-SIMD akzeptieren), Test mit dem laufenden Spiel. **1,5 bis 3 Wochen.** Urteil: **tragfähig.**

---

## 4. Teilbau: Generierung und Übersetzung aller vier Module

**Erzeugung** (`scripts/recomp/gen_all.sh`; Ausgabe `work/recomp/gen4`, gitignoriert; Python-Generator, Einzelkern):

| Modul | Funktionen | Chunks | C-Größe | Zeit | Spitzen-RAM Generator |
|---|---:|---:|---:|---:|---:|
| main | 218.195 | 1.046 | 828 MB | 62 s | 4,8 GB |
| sdk | 38.342 | 189 | 103 MB | 7,7 s | 0,7 GB |
| subsdk0 | 13.719 | 160 | 61 MB | 4,2 s | 0,4 GB |
| rtld | 43 | 1 | 0,1 MB | 0,2 s | |
| **Summe** | **270.299** | **1.396** | **992 MB** | **74 s** | |

`main` hat 2.929 Funktionen mit Rahmeneintrag, 14.887 Landing-Pad-Labels, 17 `setjmp`-Rückkehrstellen; 58 Wörter werden als `rt_udf` (nicht unterstützte Exklusiv-Paare) erzeugt.

**Übersetzung** (`scripts/recomp/build_all.sh 3`; `clang -O1 -fno-strict-aliasing -fvisibility=hidden`; Einzelfunktionen über 1 MB C mit `-O0`; 3 parallele Compiler, die Maschine war durch andere Prozesse ausgelastet, Last 8 bis 14):

| Messwert | Ergebnis |
|---|---|
| Dateien | 1.400 (1.390 mit `-O1`, 10 mit `-O0`; 1.396 Chunks plus 4 Tabellendateien) |
| Wanddauer gesamt | **937 s = 15,6 min** |
| Summe der Einzelzeiten | 2.711 s (45 min CPU) |
| Median je Datei | 1 s |
| Dateien über 10 s / über 60 s | 21 / 4 |
| langsamste Dateien | 214 s (729 MB), 187 s (727 MB), 87 s (**1.681 MB**, größter Speicherbedarf), 72 s, 44 s |
| größter Speicherbedarf | **1,7 GB** (870-KB-Einzelfunktion; Phase 1 hatte in einer Stichprobe 3,3 GB gemessen, diese Datei kam bei der jetzigen Chunk-Einteilung nicht vor oder wurde anders zugeschnitten) |
| Link (`clang -dynamiclib`) | 0,5 s |
| Objektdateien | 266 MiB |
| Bibliothek `libgame.dylib` | **224 MiB** (`__text` 209,6 MB, `__const` 12,2 MB, `__unwind_info` 0,4 MB) |

Ausreißer-Experiment (je eine Einzelfunktionsdatei, `-O1` / `-O0`, Spitzenspeicher): 134 KB C: 3,3 s / 0,08 s; 379 KB: 1,6 s / 0,11 s; 756 KB: 8,6 s (312 MB) / 0,24 s; 1,36 MB: **72 s** (604 MB) / 0,39 s; **8,0 MB** (größte Funktion): **153 s** (867 MB) / 4,0 s (999 MB, Objekt 4,3 MB). `-O0` löst die Ausreißer vollständig (Faktor 35 bis 185 schneller), kostet aber Laufzeit in diesen Funktionen; es sind 337 Einzelfunktionsdateien über 100 KB (284 zwischen 100 und 300 KB, 32 bis 600 KB, 9 bis 1 MB, 8 bis 2 MB, 2 darüber), also 10 von 1.400 Dateien im Sonderpfad. Die drei langsamsten Dateien (214 s, 187 s, 87 s) sind **Einzelfunktionen von 373 KB, 488 KB und 870 KB C**, also unter der 1-MB-Schwelle; die Übersetzungszeit hängt stark vom Kontrollfluss ab, nicht nur von der Größe (die 8-MB-Funktion braucht 153 s, die 373-KB-Funktion 214 s). Mit einer Schwelle von 300 KB für `-O0` wären sie alle in den Sonderpfad gefallen.

**Bewertung:** Gesamtbau **unter der Bedingung (c) aus Phase 1 (30 Minuten)**: 15,6 min mit 3 Jobs auf der ausgelasteten Maschine, *vermutet* 6 bis 8 min mit 8 freien Kernen. Gesamt-Ressourcen: 1 GB C + 0,27 GB Objekte + 0,22 GB Bibliothek, Platz < 2 GB; Generator braucht 5 GB RAM für `main`. Urteil: **tragfähig**. Offen: iOS-Ziel (arm64, gleiche Bibliothek, in das App-Bundle eingebettet; Xcode-Übersetzung statt Skript), Link-Verhalten mit LTO nicht gemessen.

---

## 4a. Leistung: Mikro-Benchmarks rekompiliert gegen nativ

`scripts/recomp/test/run_bench.sh`: dieselbe C-Quelle (`bench_guest.c`) wird für aarch64-linux mit `-O2` übersetzt und durch die Pipeline rekompiliert (`-O1` wie im Gesamtbau, Gleitkomma als Inline-asm-Blöcke, Dispatch wie LAS mit 4096er-Cache), und als Vergleich nativ auf dem Mac (M1 Pro, `-O2`) übersetzt. Ergebnisse stimmen in allen vier Fällen überein.

| Benchmark | rekompiliert | nativ | Faktor (`-O1`) | Faktor (`-O2`) |
|---|---:|---:|---:|---:|
| Ganzzahl + Speicher (Xorshift, 32 KiB) | 0,41 s | 0,21 s | 1,9 | 2,0 |
| Aufrufe + Stack (`fib(35)`) | 0,12 s | 0,03 s | 4,3 | 3,2 |
| Gleitkomma (FMA-Schleife, Inline-asm) | 0,61 s | 0,15 s | 4,0 | 4,0 |
| indirekte Aufrufe (8er-Tabelle, `rt_dispatch`) | 0,17 s | 0,11 s | 1,5 | 1,4 |

**Aussage:** auf Mikro-Ebene **1,4- bis 4,3-mal langsamer** als nativer Code derselben Quelle (Ganzzahlcode ca. 2×, aufrufintensiv und FP-lastig 3 bis 4×). Das bestätigt die Phase-1-Schätzung „2× bis 5×“ von unten. Grenzen: kleine Schleifen, ein Thread, kein Cache-Druck; die Switch-CPU (Cortex-A57, ca. 1 GHz) ist laut Schätzung 6- bis 10-mal langsamer als ein M1/M2-Kern, was den Faktor mehr als aufwiegen würde (*vermutet*); das Spiel selbst wurde nicht gemessen. Der Rebase-Schalter kostet in der Exception-Messung +5 %.

---

## 5. Kleinstes lauffähiges Stück: `main` + `sdk` + `subsdk0` bis `nnMain`

Die Bedingung „Schritte 1 bis 3 positiv“ ist erfüllt. Aufbau (`scripts/recomp/test/boot_probe.c`, `run_boot_probe.sh`): alle drei Module (aus den 1.400 Objekten, nicht der Test-Teilbau) an ihrer Basis laden (`main` `0x70_0000_0000`, `sdk` `0x70_0600_0000`, `subsdk0` `0x70_0700_0000`; das `main`-Image ist 84,3 MB groß, der LAS-Slot 64 MiB, daher geänderte Basen), Relokationen und Querverweise anwenden (`main` → `sdk`: 3.854, `subsdk0` → `main`/`sdk`: 6.551), schwache Importe 0, `nn::init::Start(thread_handle, args, init_sdk, init_main, fini)` auf dem Hauptthread starten (rtld-Ersatz wie LAS: erste Rückruffunktion = Initialisierung des SDK-Moduls nach `nnosInitialize`, zweite = `main` vor `nnMain`). Mini-Kernel nur für den Befund: 25 SVCs mit Standardantworten, ein Thread, einfache CMIF-Antworten.

**Ergebnis (gemessen):**

| | |
|---|---|
| Start-RSS nach Laden der drei Module | **101 MiB** (alle Module berührt, 99 MB entpackt) |
| `nn::init::Start` → `nnosInitialize` | läuft: `GetInfo` ×12, `QueryMemory` ×2, `GetThreadPriority`, `GetThreadId` (alle Werte plausibel) |
| SDK-Konstruktoren (DT_INIT, **115 `init_array`-Einträge**) | **laufen durch**, ohne Absturz oder Ausnahme |
| Erster harter Blocker | **IPC / Dienstschicht**: `ConnectToNamedPort("sm:")` → `SendSyncRequest` (HIPC-Typ 6). Mit einer Mini-CMIF-Schicht (Antworten, Domain, 120 Zeilen) beantwortet der Test `sm:` Initialize, `lm` (Steuerbefehle QueryPointerBufferSize und ConvertCurrentObjectToDomain, `OpenLogger` als Domain-Objekt) und `MapPhysicalMemory`. **Fragefolge des SDK danach (`sm:` GetService):** `apm`, `appletOE`, `aoc:u`, **`ectx:aw`** (fehlt er, ruft das SDK `svcBreak`), danach `pctl`, `pctl:s`, `pctl:a`, `pctl:r`. Fehlerantworten für `apm`/`appletOE`/`aoc:u` nimmt das SDK hin; fehlt `pctl` samt Varianten, läuft es in seine Abbruchbehandlung (`nn::diag::detail::InvokeSdkAbortObserver`), die ein `nn::am`-Objekt (aus `appletOE`) braucht, und der Test stürzt mit Nullzugriff ab (Ursache gelesen aus dem Funktionsring, kein Fehler des erzeugten Codes). Echte Dienste mit gültigen Objekten sind nötig. Pflicht bis hier: `ectx:aw` und ein `pctl*` (sonst Abbruch), `appletOE` (für die Abbruchbehandlung); `apm` und `aoc:u` überstanden den Fehler; `lm` wurde umgesetzt. |
| SVCs bis dahin (Lauf ohne `ectx:aw`) | 8 verschiedene (`0x06`, `0x0c`, `0x1f`, `0x21`, `0x25`, `0x26`, `0x29`, `0x2c`), 29 Aufrufe (`GetInfo` 13, `SendSyncRequest` 9); zwei `GetInfo`-Anfragen mit IDs, die der Mini-Kernel nicht kennt |
| Threads, Heap | 0 Threads angelegt, `SetHeapSize` noch nicht aufgerufen (das macht `nninitStartup` in `main` nach den Konstruktoren) |
| Spitzen-RSS bei Abbruch | 105 MiB |
| Zeit bis zum Blocker | Lauf selbst < 1 s |

**Was dem Start (laut Phase 1 und diesem Lauf) fehlt:** (1) die CMIF-/Domain-Schicht und die 47 Dienste laut NPDM (`sm:`, `lm`, `fsp-srv`, `appletOE`, `apm`, `hid`, `time:u`, `set:sys`, `acc:u0`, `pctl`, `aoc:u`, `audren:u`, `nvdrv` …; LAS bringt 20 Namen mit, siehe Phase 1) – dies ist der nächste harte Blocker und erwartete Arbeit, kein Forschungsrisiko; (2) Thread- und Synchronisations-SVCs mit echten Host-Threads (`CreateThread`, `StartThread`, `WaitSynchronization`, `ArbitrateLock`, `WaitProcessWideKey`, `WaitForAddress`: Mini-Kernel hat sie nur als Platzhalter), SVC `0x32/0x33` (Schritt 2), `0x20, 0x23, 0x28, 0x2F, 0x36, 0x5F`; (3) `QueryMemory`-Segmenttypen (im Probelauf nachgebaut), (4) `nninitStartup`/`SetHeapSize` (kommt nach den Konstruktoren), (5) Grafik- und Medienschicht (nicht Teil dieses Laufs). Die **Zahl der Unity-Threads** bleibt ungemessen (Strings: `UnityGfxDeviceWorker`, `Loading.*`, `Background Job`, `AK::IOThread`, vermutlich 20 bis 40).

**Erweiterung (kurzer Zusatzlauf, `run_boot_probe_las.sh`):** Die IPC-/Dienstschicht von LASRecomp (`ipc.c`, `services/am|misc|acc|hid_set|time.c`, gelinkt, nicht kopiert; dazu ein 40-Zeilen-Handle-Shim) ersetzt die Mini-CMIF-Schicht des Tests. Ergebnis: `sm:` → `lm` → `apm` → `appletOE` werden beantwortet, zwei `am`-Befehle (`ICommonStateGetter` 900, `ISelfController` 91) sind in LAS nicht behandelt, danach `svcBreak` (Grund 0) des SDK, noch vor `aoc:u`/`ectx:aw`/`pctl`. 9 verschiedene SVCs, 557 Aufrufe (`GetInfo` 14, `QueryMemory` 514 durch den EH-Unwinder-Pfad des SDK, `SendSyncRequest` 22), 0 Threads, Spitzen-RSS 105 MiB. Befund unverändert: nächster Blocker sind fehlende bzw. unvollständige Dienste (Wochenarbeit laut Aufwandsschätzung), kein Fehler in den rekompilierten Modulen.

**Abbruch** wie vorgegeben beim ersten harten Blocker (fehlende Dienstschicht). Erste Log-Zeilen des Unity-/IL2CPP-Starts wurden **nicht** erreicht: dafür fehlen RomFS (`fsp-srv`), Threads und Grafikdienste. CPU-Seite: **kein Hinweis auf Fehler** in den rekompilierten Modulen bis hierher (SDK-Konstruktoren, TLS, `nn::os`).

---

## 6. Entscheidungsvorlage

### 6.1 Zahlen D gegen R

| Kriterium | D: Unity-6-Rebuild mit handrekonstruierter Logik | R: Rekompilation des gesamten NSO (gemessen in Phase 1 und 2) |
|---|---|---|
| Stand | 194 C#-Dateien (28.620 Zeilen) plus 12.802 Zeilen Tests, 645 Tests grün; Feld-, Kampf-, Event-, UI-Teile (Slices); **ca. 39.100 Methoden Spiellogik** insgesamt zu rekonstruieren | CPU-Seite vollständig gemessen: 270.299 Funktionen, 14,1 Mio. Wörter, **58 nicht abgedeckt**, 1.400 Dateien in 15,6 min, 224 MiB Bibliothek, SDK-Initialisierung läuft |
| Feature-Parität (Logik, Engine, UI, Events) | nur so weit rekonstruiert; Differenzen in Zufall, Timing, Reihenfolge, Unity 6 statt 2019.4 bleiben | **1:1 automatisch**, solange CPU, Kernel/Dienste und GPU stimmen; Savegame-Kompatibilität bleibt, weil der Gast-Code unverändert schreibt |
| Treue-Prüfung | gegen das Original nur über Orakel/Messung (`scripts/battle_oracle*.py`) | das Original **ist** der Code; Vergleich mit D möglich (Referenz) |
| GPU | Unity-Pfad mit unserem Maxwell→MSL-Übersetzer (99,8 % der Varianten, Treue gemessen) | NVN→Metal-Schicht aus LAS (9,5 kZeilen, 495 von 524 NVN-Namen, `docs/referenz-las-shader.md`) plus derselbe Maxwell→MSL-Übersetzer (Stufe `shader_translator`): **GPU-Seite im Wesentlichen vorhanden**, Unity-spezifische Nutzung (MRT, Instancing, Compute-Skinning, 5 Compute-Programme) ungeprüft |
| Exceptions | n. a. | **gelöst** (Abschnitt 1) |
| GC-Thread-Anhalten | n. a. (Unity-IL2CPP) | **lösbar**, 2 bis 4 Tage (Abschnitt 2) |
| iPad-Adressraum/-Speicher | Unity normal, Budget 2,5 GB Richtwert / 4 GB Grenze (`ipad-messung-1.md`) | 32-Bit-Fenster **funktioniert** (Abschnitt 3); Summe 3,9 bis 5,0 GiB: **nur mit Increased Memory Limit** (8 GiB, mit kostenlosem Team gemessen) sicher, ohne zu knapp |
| Leistung | Unity-nativ | Spiel **ungemessen**; Mikro-Benchmarks (Abschnitt 4a): **1,4- bis 4,3-mal langsamer** als nativer Code derselben Quelle (Ganzzahl ca. 2×, Aufrufe/FP 3 bis 4×), Rebase +5 %, Sicherheitspunkt-Poll bis 12 % (Worst Case); Zielgeräte M1/M2 rechnen ca. 6- bis 10-mal so schnell wie der Cortex-A57 der Switch (*vermutet*) |
| Build | Unity + Xcode wie bisher | 15,6 min auf dem Mac (3 Jobs), 5 GB RAM Generator, < 2 GB Platz; Bibliothek 224 MiB im App-Bundle |
| Fehlt noch | alles außerhalb der Slices: laut Schätzung 90 % der Logik | Dienstschicht (47 Dienste), echte Threads, Speicherumbau der Laufzeit, Medien (Video 8 von 23 `movie::` fehlen), Audio (`hwopus`), Eingabe/Touch, Plattform-Integration |
| Aufwand bis Feature-Parität (Einzelentwickler mit KI, **Schätzung**) | **40 bis 80 Wochen** (39.100 Methoden bei 100 bis 200 Methoden je Arbeitstag mit Werkzeugen; die Rate ist eine Annahme, nicht gemessen; Referenz nur der heutige Stand: 645 Tests, 28,6 kLOC); Unsicherheit ± 50 % | **Mac: 10 bis 18 Wochen, iPad stabil: weitere 10 bis 18 Wochen** (Aufstellung unten); Unsicherheit ± 50 %, größte Unbekannte: Unity-Start auf dem Gast, Leistung |
| Hauptrisiken | Umfang, stille Abweichungen, Unity-6-Unterschiede | Leistung (60 FPS auf dem iPad), Unity-Mehrthreading/GC im Zusammenspiel mit dem Kernel-Nachbau, Speicher auf dem iPad, Rechtslage, Wartung (Generator/Runtime = Compilerprojekt, LAS-Quelle laut README fast ganz KI-generiert) |
| Rechtslage (keine Rechtsberatung) | Nachbau aus Decompiler-Ausgabe; Weitergabe des Repos ohne Spielinhalte | **Repo enthält nur Recompiler + Runtime** (`scripts/recomp`, Klon-Code mit MIT-Hinweis), erzeugtes C und Binary entstehen **lokal** und werden nicht weitergegeben (Muster „Repo + eigener Dump“); das Binary ist eine mechanische Übersetzung von Nintendo-Code (klarer abgeleitetes Werk als D), die App nur für den persönlichen Gebrauch; vor öffentlicher Weitergabe rechtlich klären |
| Ressourcen | Mac 16 GB reicht (Unity Editor + Tests) | Mac 16 GB reicht (Generator 5 GB, Compiler je 1,7 GB); iPad M2 8 GB mit Entitlement, 5 GiB ohne: knapp |

**Aufwand R in Wochen (Schätzung, Einzelentwickler):**

| Paket | Wochen |
|---|---:|
| Exceptions produktiv, `QueryMemory`, Loader, `longjmp` | 1 bis 2 |
| GC-Thread-Anhalten, Thread-/Sync-SVCs mit Host-Threads | 1,5 bis 2,5 |
| CMIF/Domain, 47 Dienste (Stubs/Echtes: `sm:`, `lm`, `fsp-srv`, `appletOE`, `apm`, `hid`, `time`, `set`, `acc`, `pctl`, `aoc`, `nvdrv`); LAS-Runtime als Vorbild | 3 bis 5 |
| Speichermodell B in Laufzeit/HLE (Abschnitt 3) | 1,5 bis 3 |
| Grafik: NVN→Metal übernehmen und an Unity anpassen, Maxwell-Programme prüfen | 3 bis 6 |
| Audio (`audren`, `hwopus`, Wwise), Video (`movie::`) | 2 bis 4 |
| Eingabe/Touch/iPad, Pfade/Save, Plattform-Integration, Xcode-Bundle | 2 bis 3 |
| Fehlersuche und Leistung (60 FPS) | 4 bis 10 |
| **Summe** | **18 bis 35.5** (Mac ca. die Hälfte) |

### 6.2 Empfehlung: **Hybrid, R vorrangig weiterverfolgen mit Entscheidungspunkt**

1. **Jetzt (Phase 3, nur Mac, keine neue Unity-Rekonstruktion), zwei Stufen:**
   **Stufe 1 (4 bis 6 Wochen):** CMIF/Domain und die Dienste bis zum Unity-/IL2CPP-Start auf dem Gast ausbauen (LAS-Runtime `ipc.c`/`kernel.c`/`services` als Vorbild, ohne UI/Rando; nächste Pflicht laut Schritt 5: `ectx:aw`, `pctl*`, `appletOE`, danach `fsp-srv`/RomFS), echte Host-Threads, SVC `0x32/0x33`, GC-Stresstest; **Messung von `SetHeapSize`, Gast-RSS, Zahl der Threads und Dienste, erste Logzeilen des Unity-Starts**.
   **Stufe 2 (weitere 4 bis 6 Wochen):** Grafik (NVN→Metal, Maxwell→MSL) bis zum Titelbild und ins Feld, **Bildzeit** auf dem Mac und ein Probe-Build der Mini-Szene auf dem iPad.
2. **D läuft weiter wie bisher** (die Shader-/Textur-/Save-/Daten-Werkzeuge sind für beide Wege gleich), startet aber **keine neuen großen Logikblöcke**, bis der Entscheidungspunkt erreicht ist. Die schon rekonstruierten Teile (Kampf, EvScript) werden **gegen R als Orakel** geprüft (gleiche Eingaben, Zustandsvergleich), das senkt auch das D-Risiko.
3. **Entscheidungspunkte.** Nach Stufe 1: weiter nur, wenn (a) der Unity-Start auf dem Gast bis zu einer stabilen Hauptschleife läuft (Exceptions und GC in einem Dauertest von 1 Stunde ohne Fehler) und (c) der Gast-RSS dort ≤ 4,5 GiB liegt (mit Entitlement < 5,9 GiB). Nach Stufe 2 wird R Hauptweg (Mac **und** iPad), wenn zusätzlich (b) die Bildzeit im Feld ≤ 16,7 ms auf dem Mac liegt und die Hochrechnung auf das iPad (Faktor aus Mac M1 Pro gegen iPad M2 mit dem Probe-Build) das Ziel hält, (e) der Gesamtbau ≤ 30 min auf dem Mac braucht und (f) die Rechtslage für den persönlichen Gebrauch akzeptiert ist. **Sonst**: D bleibt Hauptweg, R bleibt als Orakel und Vergleichsbasis (Entscheidung 2 bleibt gültig).
4. **Warum nicht sofort R als alleiniger Hauptweg:** Unity-Engine, Dienste, Audio, Grafik des Gasts sind in diesem Spike nicht gelaufen; die Leistung auf dem iPad und der Speicher im Spiel sind ungemessen; das Arbeitspaket ist als Wochenfolge geschätzt, aber noch kein Unity-Frame ist erreicht. **Warum nicht bei D allein:** die drei Hauptblocker der Phase 1 (Exceptions, GC, Speichermodell) sind weg; R liefert Feature-Parität und Treue für ein Drittel bis die Hälfte des D-Aufwands, falls die offenen Punkte (b), (c) halten.
5. **Abbruchkriterium des Hybrids:** Schlägt in Phase 3 ein harter Blocker auf (Unity-Boot scheitert an Threads/GC/Diensten, die Bildzeit liegt mehr als 3-fach über dem Ziel oder der Speicher überschreitet 5,9 GiB), werden die Ergebnisse dokumentiert und D wird wieder alleiniger Hauptweg; die Kosten sind begrenzt auf 4 bis 6 Wochen (Stufe 1) bzw. 8 bis 12 Wochen (beide Stufen).

---

## 7. Abbruchkriterien und was sie ergeben haben

| Schritt | Abbruchkriterium | Ergebnis |
|---|---|---|
| 1 Exceptions | throw → catch über ≥ 2 rekompilierte Rahmen mit korrektem Zustand nicht erreichbar | **erreicht** (Test T1 bis T5, 100 von 100 erreichten echten Funktionen) |
| 2 GC | Thread-Anhalten ohne Entitlement unmöglich | **nicht eingetreten** (Mach-API, Boehm nutzt sie) |
| 3 Speicher | 32-Bit-Offsets nicht ohne Änderung der Semantik machbar | **nicht eingetreten** (Header-Schalter läuft grün) |
| 4 Teilbau | Gesamtbau > 30 min oder Speicher > 3,3 GB je Compiler | **nicht eingetreten** (15,6 min, 1,7 GB) |
| 5 Kleinstes Stück | erster harter Blocker | **eingetreten** nach `nnosInitialize` und 115 SDK-Konstruktoren: IPC (`sm:`/`lm`) |

## 8. Lücken und nicht Verifiziertes

- **Leistung** der rekompilierten Spiele (Bildzeit, Anteil `Cpu`-Speicher, Dispatch): nur Mikro-Benchmarks (Abschnitt 4a: Faktor 1,4 bis 4,3 gegen nativ, `fib`, FP, indirekte Aufrufe, Ganzzahl); es gibt kein lauffähiges Spiel. Die Annahme „M-Kern 6- bis 10-mal schneller als Cortex-A57“ ist nicht gemessen.
- **Unity-Start auf dem Gast** (IL2CPP-Initialisierung, Threads, Wwise, Videopfad): nicht erreicht.
- Der echte `SetHeapSize`-Wert, die Zahl der Threads und der Gast-RSS im Feld: ungemessen.
- **iPad**: weder 4-GiB-Reservierung noch `thread_suspend` auf dem Gerät gemessen; Adressraumgrenzen aktueller iPadOS-Versionen nicht verifiziert.
- Wurf-Test mit echten Funktionen: nur 100 von 180 erreichten die Prüfung (Rest: synthetische Umgebung); typisierte Catches mit dem **tatsächlich passenden** Typobjekt nicht an echten Funktionen geprüft; `longjmp`-Wiedereinstieg (17 Stellen in `main`) nur über denselben Mechanismus, nicht getestet.
- GC-Anhalten (Abschnitt 2): Mach-Messungen und ein synthetischer Test an rekompiliertem Gastcode, **kein Lauf mit einem echten Boehm-GC**; die Spiegelung des Host-Zustands ist Entwurf.
- Rebase32: nur mit dem SDK-Test (Exceptions, Allokationen), nicht mit `main`; Asm-SIMD-Pfad mit Rebase nicht umgesetzt.
- Aufwandszahlen in Wochen sind Schätzungen mit ± 50 % Unsicherheit; die D-Spanne beruht auf einer Annahme über Methoden je Tag, die nicht gemessen ist.
- Kompilierzeit: Messung unter fremder Last; keine LTO-/Release-Optimierung gemessen; Startzeit der Bibliothek (Seitenfehler beim Laden der 224 MiB) nicht gemessen.

## 9. Reproduktion

Alles lokal; Ausgaben unter `work/recomp/` (gitignoriert). Voraussetzung: `work/exefs`, `research/LASRecomp`, `tools/pydeps` (capstone, unicorn, lz4), Homebrew-LLVM.

```
python3 scripts/recomp/eh_lsda.py survey ; python3 scripts/recomp/eh_lsda.py cfa ; python3 scripts/recomp/eh_lsda.py sample
scripts/recomp/test/run_eh_test.sh               # Schritt 1: Gast-Test mit dem echten SDK (Generator, Compiler, Lauf)
python3 scripts/recomp/test/uc_ref.py            # Gegenprobe unter Unicorn
scripts/recomp/test/run_eh_real.sh               # 45 echte LSDA-Funktionen aus main (PER_KIND=60: 180)
clang -O1 -o work/recomp/spike2/gc_suspend scripts/recomp/test/gc_suspend.c && work/recomp/spike2/gc_suspend     # Schritt 2 (Mach-Latenzen, Poll-Kosten)
scripts/recomp/test/run_gc_proof.sh              # Schritt 2: asynchrones Anhalten an rekompiliertem Gastcode
scripts/recomp/test/run_eh_rebase32.sh           # Schritt 3: 32-Bit-Gastadressen
python3 scripts/recomp/ptr_scan.py               # Schritt 3: Tag-/39-Bit-Stichprobe
scripts/recomp/gen_all.sh ; scripts/recomp/build_all.sh 3     # Schritt 4
scripts/recomp/test/run_bench.sh -O1             # Abschnitt 4a: Leistung rekompiliert gegen nativ
scripts/recomp/test/run_boot_probe.sh            # Schritt 5
scripts/recomp/test/run_boot_probe_las.sh        # Schritt 5, Erweiterung mit LAS-IPC-/Dienstschicht
```

Herkunft und Lizenz: `research/LASRecomp` (MIT, Copyright (c) 2026 Peiikai; Nintendo-Eigentum und `third_party/` ausgenommen) wird nur zur Laufzeit von den Skripten importiert; es wurde nichts kopiert. Falls der Generator später übernommen wird, gelten die Hinweise aus `shader_translator/NOTICE.md` (Lizenztext unverändert, Commit `09f8e5e`, Änderungen kennzeichnen); `tools/patches.py` des Originals enthält Spieladressen und ist nicht übernehmbar.
