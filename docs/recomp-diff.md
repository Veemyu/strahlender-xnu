# Differenzialtest: erzeugtes C (c-Modus) gegen echte ARM64-Semantik (`ap-recomp-diff`)

Stand: 2026-10-19 (Messungen 13:45 bis 15:10 Uhr). Grundlage: `docs/recomp-ryzen.md` (Abschnitt 8, Grenzen), `docs/recomp-spike-2.md`, `docs/recomp-machbarkeit.md` (Abschnitt 1.1, Lifter-Modi), `research/LASRecomp` (MIT, Freigabe des Nutzers; nur gelesen und zur Laufzeit importiert, nichts verändert).

**Kennzeichnung:** **gemessen** = mit den Skripten unter `scripts/recomp/diff/` erzeugt (Zahlen aus den Berichten unter `work/recomp/diff/`, lokal, nicht im Repo); **abgeleitet** = Schluss aus Messwerten; **nicht geprüft** = Lücke (Abschnitt 9).

## 0. Ergebnis in Kürze

1. **Der portable `c`-Modus ist für alles, was das Spiel ausführt, bitgenau zur ARM64-Semantik – gemessen, mit den richtigen Compilerflags und einem sauberen Host-FPU-Zustand.** Rund **93,5 Mio. Fälle je Variante** (9.134 Tests, 306 Befehle, je Test 10.240 Fälle) und **561 Mio. Fälle** (je Test 61.440) ergaben bei fünf x86-Varianten **0 Abweichungen** in V0 (128 Bit), X0, NZCV, Speicher und Basisregister. Dazu **259,8 Milliarden** Fälle im erschöpfenden Einzelbefehlstest (Abschnitt 4).
2. **Die Abweichung des Float-Benchmarks (`recomp-ryzen.md`, Abschnitt 6/8) war kein Fehler des Rekompilats und auch keine FMA-Fusion des Rekompilats:** das Ergebnis ist `NaN` (die Schleife läuft in `inf - inf`); die native x86-Referenz liefert das x86-Standard-NaN **`0xFFF8…` (Vorzeichen gesetzt)**, ARM (und das Rekompilat, und Unicorn) das ARM-Standard-NaN **`0x7FF8…`**. Alle endlichen Läufe stimmen überein (Abschnitt 6).
3. **Gefunden und behoben bzw. abgesichert:** (a) das Rekompilat hängt vom **Host-MXCSR** ab (FTZ/DAZ oder Rundung ≠ nächste gerade Zahl aus Treibern/Audio-Bibliotheken → 1.560 bzw. 386 von 9.126 Tests weichen ab); `scripts/recomp/c_exact/fp_env.h` stellt den Zustand her, danach 0 Abweichungen. (b) Mit `-ffp-contract=fast` und ohne `FENV_ACCESS`-Pragma weichen 45 Tests ab (nur bei Rundungsmodus ≠ RN); die Laufzeit **lässt `-ffast-math`/`fast` ohnehin nicht übersetzen** (Pragma-Fehler). (c) Auf einem **arm64-Host mit `-O2`** erzeugt clang 23 für `sqdmulh v.4h` falschen Code (Vektorisierer; mit `-fno-vectorize` korrekt, auf x86 und mit `-O1` unauffällig; das Spiel nutzt nur `.4s`/skalar).
4. **Nicht modelliert (dokumentierte Restliste):** FPSR-Sammelflags (IOC/DZC/OFC/UFC/IXC/IDC) und QC; das Spiel (`main`) liest sie nie (0 `mrs fpsr`), das SDK nur in libm-`fenv`-Funktionen. ARMv8.2-FP16-Arithmetik u. a. (1.632 Befehlsformen) fehlt im Lifter; kein Spielvorkommen.
5. **Empfehlung Linux/Windows:** `clang -O1 -march=x86-64-v3 -ffp-contract=off -fno-fast-math` (kein gcc/MSVC, kein x87), `rt_fp_guest_mode()` an jedem Gast-Thread-Anfang und nach Fremdaufrufen; der Differenzialtest als Regressionstest je Compilerversion (Abschnitt 8).

## 1. Welche FP-/SIMD-Befehle führt das Spiel aus? (gemessen)

`scripts/recomp/diff/hist.py` zerlegt jedes 32-Bit-Wort des Textsegments von `main`, `sdk`, `subsdk0`, `rtld` (lokal, `work/exefs`) mit Capstone 5.0.7: **14.105.420 Wörter** (`main` 11.786.892, `sdk` 1.455.692, `subsdk0` 861.276, `rtld` 1.560), davon 849 nicht zerlegbar (Daten im Text).

| Klasse | Wörter | Anteil | Befehlsformen |
|---|---:|---:|---:|
| FP-/SIMD-Datenverarbeitung (Bits 27:25 = 111) | 583.894 (`main` 557.608, `sdk` 20.359, `subsdk0` 5.927) | 4,14 % | 576 |
| FP-/SIMD-Laden/Speichern (`ldr q`, `ldp`, `ld1` …) | 302.393 | 2,14 % | 254 |
| zusammen | 886.287 | 6,28 % | 830 |

Häufigste FP-/SIMD-Befehle (Datenverarbeitung; „Form“ = Mnemonic + Registerbreite/Anordnung, Registernummern und Konstanten herausgerechnet):

| Befehl | Wörter | Anteil an der Datenverarbeitung (kumulativ) |
|---|---:|---:|
| `fmul` | 133.331 | 22,8 % |
| `mov` (Alias `orr`/`ins`) | 83.570 | 37,1 % |
| `fadd` | 74.814 | 50,0 % |
| `fmov` | 42.991 | 57,3 % |
| `fsub` | 39.224 | 64,0 % |
| `dup` | 27.769 | 68,8 % |
| `fcmp` | 27.080 | 73,4 % |
| `ext` 14.903, `movi` 9.027, `fdiv` 8.476, `fcsel` 8.232, `faddp` 7.806, `and` 7.567, `scvtf` 7.543 | | 84,3 % |

Die ersten 50 Mnemonics decken 98,0 % der Datenverarbeitung ab, darunter `eor`, `fneg` 5.129, `bsl`, `frecps` 4.343, `fcvtzs` 3.931, `fcmgt`, `ucvtf` 3.680, `fmin`, `frsqrts` 2.749, `fcvt` 2.700, `fmax`, `fabs`, `fsqrt` 1.733, `fmadd` 1.614, `fcvtzu` 1.565, `frsqrte` 1.328, `frecpe` 1.248.

Weitere Familien: **Fused Multiply-Add** zusammen nur 3.009 Wörter (`fmadd` 1.614, `fmla` 934, `fmsub` 187, `fnmsub` 238, `fmls` 34, `fnmadd` 2; 0,02 % aller Wörter); Konvertierungen `fcvt{n,m,p,a,z}{s,u}` ≈ 5.800, `frint*` ≈ 670 (`frintm` 447, `frintp` 158, `frintz` 35, `frinta` 16, `frintx` 9, `frinti` 2); gesättigte/gerundete NEON-Ganzzahlbefehle ≈ 450 (`sqadd` 148, `sqrshrn` 141, `sqdmulh` 39, `uqadd` 21 …); Verschlüsselung/CRC: `aese/aesd/aesmc/aesimc` 532, `sha1*/sha256*` 464, `pmull` 42, `crc32*` 18 (alle im SDK).

**FPCR/FPSR im Spielcode (gemessen):** `main`, `rtld`, `subsdk0`: **kein einziges** `mrs/msr fpcr/fpsr`. Im SDK 5× `mrs fpcr`, 6× `mrs fpsr`, 3× `msr fpcr`, 4× `msr fpsr`; die Stellen sind die libm-`fenv`-Funktionen (`fegetround`/`fesetround`: FPCR-Bits 22..23 lesen/setzen, `fetestexcept`/`feclearexcept`/`feraiseexcept`: FPSR-Bits 0..4, `fegetenv`/`fesetenv`: beide; Standardumgebung = 0) und die Kontextsicherung (`mrs x0, fpcr; mrs x1, fpsr`). **Der Gast läuft also im FPCR-Standardzustand 0** (Rundung auf nächste gerade Zahl, FZ = 0, DN = 0), solange er nicht `fesetround` aufruft. Standardwert unter Unicorn (`UC_CPU_ARM64_A57`) und unter Linux ist ebenfalls 0; Horizon setzt für Anwendungs-Threads nach allem, was unsere Quellen zeigen, keine anderen Bits (**nicht geprüft** gegen echte Hardware). Die Tests laufen trotzdem zu 60 % mit den übrigen 15 Kombinationen aus RMode (RN/RP/RM/RZ) × FZ × DN, damit auch seltene Pfade stimmen.

## 2. Testaufbau (`scripts/recomp/diff/`)

**Eingaben** (`cases.c`, splitmix64, fester Startwert je Test, auf Mac und Ryzen identisch; keine Spielbytes): je Register nach Typ (F16/F32/F64, I8..I64, Bits) – 22 % Spezialwerte (±0, ±Inf, qNaN/sNaN mit Nutzlasten, größte/kleinste Denormale, kleinste/größte Normale, 2^24, 2^31, 2^63, 2^64 …), 18 % reine Zufallsbits, 22 % mittlere Exponenten, 10 % Nachbarn (±3 ulp) der Spezialwerte, 10 % kleine exakte Zahlen (Rundungsgrenzen), 9 % Denormale/kleinste Normale, 5 % Überlaufnähe, 4 % Exponenten um 1; Operanden mit 14 % Wahrscheinlichkeit gleich/negiert/±1 ulp des Vorgängers (Auslöschung, Gleichheit), bei FMA in 8 % `c = -(a*b)`. FPCR wie oben, NZCV zufällig, GPR-Quellen aus Ganzzahl-/Float-Spezialwerten.

**Referenzen** (`tmpl.S`, eine Schleife, dieselben Maschinencode-Bytes überall):
- **Unicorn 2.1.4, Cortex-A57-Modell** (der Kern der Switch), je Test ein `emu_start` über alle Fälle.
- **Apple M1 Pro nativ** (`native.c`: JIT-Seite, `MAP_JIT`; die echten Befehle, im `asm`-Modus des Lifters bitgenau per Konstruktion).
- Ergebnis: **M1 und Unicorn-A57 stimmen in allen 9.134 Tests × 10.240 Fällen exakt überein, auch in FPSR** (0 Abweichungen). Damit ist Unicorn als Referenz auf dem Ryzen belegt (stichprobenhafte Prüfung gegen echte ARM-Semantik ersetzt durch die Vollprüfung gegen den M1); Unterschiede M1 ↔ Cortex-A57 in NaN-Behandlung, FPCR-Verhalten, Rundung oder FPSR traten **nicht** auf (nur FPSR-Details wie IDC bei FZ könnten abweichen, kamen aber in den Fällen nicht vor).

**Testobjekt:** der `c`-Modus-Output des Lifters (`Lifter(base, 'c').lift(...)`, danach `simd_c.py`/`simd.h`/`simd_fp.h`), eine Gastfunktion `void t_<id>(Cpu *)` je Test (1 bis 4 Befehle), in `ctest.c` mit einer frischen `Cpu` je Fall ausgeführt (V8..V31 = 0 wie in der Referenz). Speicherbefehle laufen gegen einen 192-Byte-Puffer (Gastadresse = Hostadresse).

**Testliste** (`mktests.py`): der gesamte FP-/SIMD-Kodierungsraum (Bits 27:25 = 111, plus Laden/Speichern mit V = 1) wird mit Capstone durchlaufen, je Form 3 bis 6 Vertreter (die 576 Spielformen mit mehr Vertretern bei Konstanten/Lane-Index) → **9.134 Tests: 6.016 Datenverarbeitung, 2.270 Speicher, 800 Zufallsketten (2 bis 4 abhängige FP-Befehle), 48 Sonderfälle** (FMUL+FADD/FSUB-Folgen als Fusionsprüfung, `fcmp #0.0`, `fccmpe`, `xzr`-Formen, CRC32). 306 verschiedene Mnemonics. **Abdeckung des Spiels:** 566 von 576 Datenverarbeitungsformen im Raster gefunden, die 10 übrigen (`fcmp #0.0`, `xzr`-Quellen) als Sonderfälle ergänzt; von den 254 Speicherformen sind 174 abgedeckt, 80 fehlen (Formen mit `sp` als Basis und Registeroffset `[xN, xN]`; reine Adressrechnung der Ganzzahlseite, **nicht geprüft**).
- **Nicht im c-Modus unterstützt:** 1.632 Befehlsformen (ARMv8.1+ `sqrdmlah`, Dot-Product, `fcmla`, FP16-Arithmetik, `fmlal`, `frint32/64`, …), **Spielvorkommen 0**.

**Compilervarianten (Ryzen, clang 22.1.8):** `-O1 -march=x86-64-v3` mit Standardvertrag (clang: `-ffp-contract=on`) und mit `-ffp-contract=off`; `-O2` ebenso; `-O1` für das x86-64-Grundprofil (ohne FMA-Hardware; `fma` über libm) mit `off`. Dazu auf dem Mac (arm64, clang 23): `-O1 -ffp-contract=off`, `-O2`.

## 3. Ergebnis der Hauptläufe (gemessen)

| Quelle (gegen Referenz) | Tests | Fälle | Abweichungen |
|---|---:|---:|---:|
| Unicorn-A57 gegen M1 nativ | 9.134 | 93.532.160 | **0** (inkl. FPSR) |
| c, `-O1 -march=x86-64-v3`, Vertrag `on` (Standard) | 9.134 | 93.532.160 | **0** |
| c, `-O1 -march=x86-64-v3 -ffp-contract=off` | 9.134 | 93.532.160 | **0** |
| c, `-O2 -march=x86-64-v3 -ffp-contract=off` | 9.134 | 93.532.160 | **0** |
| c, `-O2 -march=x86-64-v3` (Standard) | 9.134 | 93.532.160 | **0** |
| c, `-O1 -ffp-contract=off` (x86-64-Grundprofil, kein FMA) | 9.134 | 93.532.160 | **0** |
| c, `-O1 -march=x86-64-v3 -ffp-contract=off`, 61.440 Fälle/Test | 9.126 | 560.701.440 | **0** |
| c, `-O2 -march=x86-64-v3` (Standard), 61.440 Fälle/Test | 9.126 | 560.701.440 | **0** |
| c auf arm64-Host, `-O1 -ffp-contract=off`, gegen M1 | 9.134 | 93.532.160 | **0** |
| c auf arm64-Host, `-O2` (Standard), gegen M1 | 9.134 | 93.532.160 | **25.706** (nur `sqdmulh v.4h`, Abschnitt 6.1) |

FPSR: der c-Modus liefert immer 0; die Referenz setzt in 18.725.436 Fällen Sammelflags (meist IXC, Bit 4). Diese Fälle sind **nicht** als Abweichung gezählt (Abschnitt 9). Nach Familien (Auszug; Spalte „Vorkommen“ = FP-/SIMD-Wörter im Spiel, „Fälle“ = Testfälle je Variante; **alle 0 Abweichungen**):

| Befehl | Vorkommen | Tests | Fälle |
|---|---:|---:|---:|
| `fmul` | 133.331 | 108 | 1.105.920 |
| `ldr` (SIMD) | 114.925 | 77 | 788.480 |
| `mov` (SIMD) | 83.570 | 540 | 5.529.600 |
| `fadd` | 74.814 | 15 | 153.600 |
| `str` / `ldp` / `stp` (SIMD) | 74.038 / 43.217 / 33.185 | 71 / 66 / 66 | 727.040 / 675.840 / 675.840 |
| `fmov` | 42.991 | 38 | 389.120 |
| `fsub` / `fdiv` | 39.224 / 8.476 | 15 / 15 | 153.600 / 153.600 |
| `dup` | 27.769 | 78 | 798.720 |
| `fcmp` / `fcsel` | 27.080 / 8.232 | 6 / 96 | 61.440 / 983.040 |
| `ext` / `movi` / `faddp` | 14.903 / 9.027 / 7.806 | 12 / 84 / 11 | 122.880 / 860.160 / 112.640 |
| `scvtf` / `ucvtf` | 7.543 / 3.680 | 36 / 36 | 368.640 / 368.640 |
| `frecps` / `frsqrts` | 4.343 / 2.749 | 15 / 15 | 153.600 / 153.600 |
| `fcvtzs` / `fcvt` / `fmin` / `fmax` / `fabs` / `fsqrt` | 3.931 / 2.700 / 3.629 / 2.696 / 2.542 / 1.733 | 54 / 6 / 15 / 15 / 5 / 5 | 552.960 / 61.440 / 153.600 / 153.600 / 51.200 / 51.200 |
| `fmadd` / `fmla` / `frecpe` / `frsqrte` | 1.614 / 934 / 1.248 / 1.328 | in Familien- und Kettentests | – |
| übrige 258 Befehle/Gruppen (inkl. AES, SHA, PMULL, CRC32, Konvertierungen, Gesättigte) | 34.225 | 7.089 | 72.591.360 |

(Die vollständige Tabelle liefert `report.py <bericht.json>`.)

## 4. Erschöpfender Einzelbefehlstest (gemessen)

`exh.c` (`exh_gen.py` erzeugt die Befehlsliste, `exh_run.sh` fährt sie, `exh_cmp.py` vergleicht): 44 Einzelbefehle (`fsqrt`, `frecpe`, `frsqrte`, `frecpx`, `fcvt{zs,zu,ns,as,ps,mu}` nach 32/64 Bit, fest­kommaartig `#8`, `fcvt` S↔D↔H, `frint{n,a,x,i,z,m,p}`, `fabs`, `fneg`, `scvtf`/`ucvtf` aus 32/64 Bit mit und ohne Festkomma, jeweils S und D) werden über **alle 2^32 Eingaben** (32-Bit-Formate vollständig; 64-Bit-Formate: obere 32 Bit vollständig, untere aus einem Mischer) ausgeführt und zu einem Hash zusammengefasst: **nativ auf dem M1** (Inline-asm, echte Befehle, Referenz) gegen **erzeugtes C** auf dem Ryzen (`-O1 -march=x86-64-v3 -ffp-contract=off`). FPCR = 0 vollständig (je 4,29 Mrd. Eingaben), dazu RP, RM, RZ, FZ, DN, FZ+DN+RZ mit jedem 16. Wert. **Ergebnis: 308 Läufe (44 Befehle × 7 FPCR-Werte), 259.845.521.408 Fälle, 0 abweichende Läufe.** (Ein erster Lauf zeigte 13 Abweichungen bei Float→Ganzzahl-Befehlen; Ursache war der Prüfstand, nicht das Rekompilat: der Inline-asm-Block ließ D0 unbelegt, das C hatte V0 = 0 – nach `fmov d0, xzr` vor dem Befehl 0 Abweichungen.) Laufzeit: M1 ≈ 12 s je Befehl und 4,29 Mrd. Fälle, Ryzen (erzeugtes C, 4 Prozesse) etwa 13 Minuten für alles.

## 5. Störversuche und Negativkontrollen (gemessen)

### 5.1 Der Test erkennt Fehler

Negativkontrolle (Ryzen): Laufzeit **ohne** `#pragma STDC FENV_ACCESS ON` (Kopie unter `work/`, Original unberührt) und `-ffp-contract=fast`: **45 von 9.134 Tests weichen ab** (51.901 Fälle), alle **nur bei FPCR-Rundungsmodus ≠ RN** und nur in `fnmul` (6), `ucvtf` (12) und Zufallsketten, die `fnmul` enthalten (27). Mit RN/FZ/DN allein: 0. Der Compiler faltet im langsamen Pfad vermutlich `-(a*b)` bzw. die Ganzzahlumwandlung ohne Rücksicht auf den eingestellten Rundungsmodus (Ursache nicht weiter untersucht). Mit dem unveränderten Original (Pragma vorhanden) lässt sich `-ffp-contract=fast` und `-ffast-math` **gar nicht übersetzen** (`'#pragma STDC FENV_ACCESS ON' is illegal when precise is disabled`): ein eingebauter Schutz. **Kein x86-Fusionseffekt im Schnellpfad:** die Folgen `fmul`+`fadd` usw. werden auch mit `fast` nicht verschmolzen, weil jede Operation ihr Ergebnis auf NaN prüft (`FBAD`) und das Zwischenergebnis in `Cpu` ablegt.

### 5.2 Host-MXCSR (Fund 1)

Das Rekompilat rechnet im Schnellpfad (FPCR = 0) mit der Host-FPU und setzt „Rundung nächste gerade Zahl, Denormale an“ voraus (so im Kopf von `simd.h` dokumentiert). Setzt fremder Code im selben Thread MXCSR um (üblich in Audio-/Treiber-/Grafikbibliotheken; erben neue Threads), stimmt das Ergebnis nicht mehr:

| Host-MXCSR während des Laufs | Tests mit Abweichung (von 9.126) | Fälle |
|---|---:|---:|
| `0x1F80` (Standard) | 0 | 0 |
| `0x9FC0` (FTZ + DAZ) | **1.560** | 737.630 |
| `0x7F80` (Rundung zur Null) | **386** | 79.119 |

**Fix:** `scripts/recomp/c_exact/fp_env.h` (`rt_fp_guest_mode()`: MXCSR auf `0x1F80` bzw. auf arm64-Hosts FPCR auf 0), eingebaut als `-DCEXACT_GUARD` in `ctest.c`: mit dem Schutz bei **gleichen Störwerten 0 Abweichungen** (beide Modi). **Einbauort in der Laufzeit** (nicht von mir geändert, `rt-bdsp` gehört einem anderen Agenten): am Anfang jedes Gast-Threads und nach jedem Aufruf in Fremdcode (HLE-Dienste, Vulkan-/Audio-Callbacks); der Aufruf kostet einen `stmxcsr` und einen Vergleich.

## 6. Der Float-Benchmark (`recomp-ryzen.md`, Abschnitt 6/8) – Ursache und Behebung (gemessen)

`bench_fp.sh` baut die Schleife aus `scripts/recomp/test/bench_guest.c` (`b = b*a + v*0.25; buf[...] = b - v`) vierfach (Gastcode und native Referenz mit Standard- bzw. `-ffp-contract=off`), erzeugt das C im c-Modus und führt aus: erzeugtes C (`REC`), nativ x86 (`NAT`), und **dieselben aarch64-Bytes unter Unicorn** (`UNI`, echte ARM-Semantik). Ergebnis (D0-Bits, Hash des Puffers):

| Lauf | n | `REC` (Rekompilat) | `UNI` (Unicorn) | `NAT` (x86 nativ) |
|---|---:|---|---|---|
| Standard (beide fusioniert: Gast `fmul`+`fmadd`, x86 `vfmadd`) | 1.000 | `411028b2b7d8b9f1` | `…b9f1` | `…b9f1` (**gleich**) |
| Standard | 20.000 | `57432c81da143979` | gleich | gleich |
| Standard | ≥ 200.000 | `7ff8000000000000` | `7ff8…` | **`fff8000000000000`** |
| alles `-ffp-contract=off` | 1.000 | `…b9ee` | `…b9ee` | `…b9ee` (gleich) |
| alles `-ffp-contract=off` | ≥ 200.000 | `7ff8…` | `7ff8…` | `fff8…` |
| Gast `off`, nativ Standard | 1.000 | `…b9ee` | `…b9ee` | `…b9f1` (**andere Fusion**) |
| Gast Standard, nativ `off` | 1.000 | `…b9f1` | `…b9f1` | `…b9ee` |

**Ursache:** (1) Bei 100 Mio. Schritten läuft `b` über (`b` und `v` wachsen gegenseitig), am Ende steht `inf - inf` → NaN. ARM erzeugt dafür das Standard-NaN **`0x7FF8000000000000`**, x86 das „Real Indefinite“ **`0xFFF8000000000000`**. Das Rekompilat (`FPCR.DN`-Pfad, `DNAN`) und Unicorn liefern ARM, die native Referenz x86; deshalb „abweichend“. Der Puffer-Hash ist in allen Läufen gleich. (2) Die in `recomp-ryzen.md` vermutete FMA-Fusion ist **nicht** die Ursache des gemeldeten Unterschieds; sie würde aber bei endlichen Ergebnissen zu Abweichungen führen, **wenn die native Referenz anders fusioniert als der Gast-Compiler** (letzte zwei Zeilen). In keinem Fall weicht das Rekompilat vom Unicorn-Referenzlauf ab.

**Behebung:** keine am Rekompilat nötig; als Vergleichsmaßstab dient künftig die Unicorn-/M1-Referenz, nicht die x86-native Übersetzung derselben Quelle. Die Doku-Aussage in `recomp-ryzen.md` ist entsprechend ergänzt.

### 6.1 Compiler-Fund auf arm64 (Fund 3)

`c`-Modus auf einem arm64-Host mit clang 23 und `-O2`: `sqdmulh v0.4h, …` (3 Tests, 25.706 Fälle, immer RN/ohne Sonderwerte) liefert falsche Lanes; `-O2 -ffp-contract=off` ändert nichts, **`-O2 -fno-vectorize -fno-slp-vectorize` behebt es** → Autovektorisierer (die Lane-Funktion rechnet über `__int128`). Auf x86 (clang 22, -O1/-O2) und mit `-O1` auf arm64: 0 Abweichungen. Das Spiel nutzt `sqdmulh` nur als `.4s`/skalar (39 Wörter), die dort 0 Abweichungen zeigen. Folge: der Test gehört in die Build-Pipeline **je Compilerversion**.

## 7. Kosten der exakten Varianten (gemessen, Ryzen 5 7500F, ns je erzeugter Gastfunktion)

`perf_c.py` (`bench_c` in `ctest.c`, 5 Mio. Aufrufe, beste von 3, Rechner nebenbei durch `ap-recomp-vulkan` belastet; Aufruf der Funktion über Zeiger eingeschlossen). FPCR = 0 (Schnellpfad) gegen FZ/RZ (langsamer Pfad):

| Befehl | `-O1 v3 off` RN | `-O1 v3` Standard RN | `-O2 v3 off` RN | `-O1` ohne FMA RN | FZ / RZ (`-O1 v3 off`) |
|---|---:|---:|---:|---:|---:|
| `fmul s` | 1,22 | 1,22 | 1,26 | 1,23 | 21,3 / 21,2 |
| `fadd s` | 1,34 | 1,91 | 1,75 | 1,92 | 21,5 / 21,4 |
| `fdiv s` | 1,91 | 1,92 | 1,75 | 1,92 | 21,3 / 21,1 |
| `fmul v.4s` | 1,91 | 1,92 | 1,74 | 1,91 | 89,3 / 88,9 |
| `fmla v.4s` | 2,58 | 2,62 | 2,55 | **8,44** | 91,2 / 91,3 |
| `fsqrt s` | 1,92 | 1,92 | 1,55 | 1,94 | 21,3 / 21,1 |
| `frecpe s` | 2,68 | 2,71 | 2,32 | 2,73 | 3,1 / 2,7 |
| `frecps s` | 1,91 | 1,94 | 1,94 | 3,11 | 21,7 / 21,5 |
| `fcvtzs w,s` | 1,92 | 1,96 | 1,73 | 2,88 | 2,1 / 1,9 |
| `scvtf s,w` | 1,92 | 1,96 | 1,73 | 1,72 | 1,8 / 20,8 |
| `faddp v.4s` | 1,92 | 1,95 | 1,76 | 1,93 | 90,6 / 91,4 |
| `mov v.16b` | 1,72 | 1,74 | 1,54 | 1,75 | 1,7 / 1,7 |
| `fmul`+`fadd` s (Folge) | 2,11 | 2,11 | 1,94 | 2,13 | 43,4 / 42,8 |
| `fmul`+`fadd` v.4s (Folge) | 1,92 | 1,92 | 1,94 | 2,13 | 179 / 179 |

**Folgerungen (abgeleitet):** (1) **`-ffp-contract=off` kostet nichts** (Unterschiede im Rauschen). (2) `-O2` bringt nichts gegenüber `-O1`. (3) Auf dem Schnellpfad kostet ein FP-/SIMD-Befehl 1 bis 3 ns (≈ 5 bis 13 Zyklen). (4) **FPCR ≠ 0 (FZ, RP/RM/RZ) ist 17-mal (skalar) bis 47-mal (4 Lanes) langsamer**; im Spiel kommt das nicht vor, solange kein `fesetround` aufgerufen wird. (5) **Ohne FMA-Hardware (`x86-64` Grundprofil) ist `fmla` 3,3-mal langsamer** (korrekte Software-`fma`, aber teuer) – x86-64-v3 (ab Haswell/Zen) ist Pflicht.

## 8. Empfehlung für Linux-/Windows-x86-64-Builds

**Compilerflags für das erzeugte C:** `clang -O1 -march=x86-64-v3 -ffp-contract=off -fno-fast-math -fno-strict-aliasing -fvisibility=hidden` (`-O2` gleichwertig; kein `-Ofast`, kein `-ffast-math`, `-ffp-contract=fast` verboten; **nur clang** – gcc kennt `__builtin_elementwise_*` nicht, MSVC `cl` auch nicht; Windows: clang-cl oder MinGW-clang, **auf Windows nicht getestet**). Kein x87 (x86-64 rechnet mit SSE; 32-Bit-Hosts nicht unterstützt).

**Laufzeit:** `rt_fp_guest_mode()` (`scripts/recomp/c_exact/fp_env.h`) am Anfang jedes Gast-Threads und nach Aufrufen in Fremdcode; Gast-FPCR nur in `Cpu` (wie bisher). `-march=x86-64-v3` (FMA!) statt Grundprofil.

**Regressionstest:** `scripts/recomp/diff/run_ryzen.sh base` (70 s für 93 Mio. Fälle × 5 Varianten auf 4 Kernen) bei jeder Änderung an Lifter, `simd*.h` oder Compilerversion; Erwartung 0 Abweichungen. `mktests.py --ncases 61440` für die große Variante (6 Minuten). Mit dem M1 als zweite Referenz (`difftest.py --src m1,uc,c:...`).

## 9. Grenzen und Restliste

- **FPSR-Sammelflags (IOC, DZC, OFC, UFC, IXC, IDC) und QC werden im c-Modus nicht gesetzt** (so im Kopf von `simd.h` dokumentiert). Im Spiel nur über libm-`fenv`-Funktionen im SDK lesbar (`fetestexcept` …): `main`, `subsdk0`, `rtld` lesen FPSR nie. Das Risiko liegt bei Aufrufen von `fetestexcept`/`feclearexcept` aus `main` in das SDK (nicht gezählt). Aufwand für eine Nachbildung: mittel (je Operation Flag-Logik im Schnellpfad, der dann nicht mehr „billig“ ist) – nicht empfohlen, solange kein Spielpfad sie liest.
- **FPCR-Trapbits (IOE …), FP16-Arithmetik, ARMv8.1+-Befehle** nicht modelliert; Switch-Kern A57 kennt sie nicht, Spielvorkommen 0.
- **Nicht geprüft:** `sp`-relative und Registeroffset-Speicherbefehle (Adressrechnung der Ganzzahlseite); Zweioperanden-Befehle erschöpfend (nur Zufall + Randfälle, 10.240 bis 61.440 Fälle je Test); Windows/MSVC/clang-cl; gcc; echte Switch-Hardware (der Referenzkern ist Unicorn-A57 und M1, beide untereinander gleich); tatsächlicher FPCR-Startwert von Horizon-Threads (0 angenommen, Quelle: libm-Standardumgebung und Linux).
- Die Unterschiede zwischen M1 und Cortex-A57 bei NaN/FPCR/FPSR-Details sind in den Tests **nicht aufgetreten**; Unterschiede nur in nicht gemessenen FPSR-Feinheiten möglich.
- **x86-native Berechnungen sind keine Referenz** (NaN-Vorzeichen `0xFFF8…`, andere Fusion): nur Unicorn/M1 verwenden.

## 10. Auswirkung auf die Rekompilationsstrategie

1. **Linux/Windows x86-64 (Vulkan) mit dem `c`-Modus ist machbar, ohne dass Spiele-Arithmetik (Schaden, Zufall, Animation, Physik) durch Float-Abweichungen leidet:** für alle gemessenen Befehle mit allen Flag-Varianten 0 Abweichungen, 259,8 Mrd. erschöpfende plus 560 Mio. Zufallsfälle je Variante. Die Sorge aus `recomp-ryzen.md` („kein Bit-Vergleich mit echter arm64-Semantik möglich“) ist ausgeräumt: der Vergleich geht über Unicorn (A57) und den M1, nicht über x86-native Übersetzung.
2. **Der `asm`-Modus bleibt der Standard für macOS/iPadOS (bitgenau per Konstruktion, am schnellsten),** der `c`-Modus ist die gleichwertige portable Variante; beide lassen sich in der Pipeline gegeneinander prüfen (`difftest.py --src m1,uc,c:...`).
3. **Die Kosten der Exaktheit sind klein:** Schnellpfad 1 bis 3 ns je Befehl; teuer ist nur FPCR ≠ 0 (nie im Spiel gesehen). Eine zusätzliche Absicherung ist nötig: Host-FPU-Zustand (`fp_env.h`), Compilerflags und Compilerversion (Fund 3: Test je Version).
4. **Risikoliste für die Laufzeit:** FPSR-Flags (siehe oben), Host-Threads/Treiber, die MXCSR ändern, Standard-NaN der Host-Mathematik (z. B. HLE-Funktionen, die `sinf` o. Ä. im Host rechnen, liefern x86-NaN-Vorzeichen; im Gast gerechnete NaNs sind ARM-konform) – HLE-Math nur nutzen, wenn das Gast-libm-Ergebnis nicht benötigt wird.

## 11. Dateien und Reproduktion

| Datei | Zweck |
|---|---|
| `scripts/recomp/diff/hist.py` | Histogramm (Mnemonics, Formen, FPCR/FPSR-Zugriffe) über die NSO-Texte |
| `scripts/recomp/diff/mktests.py` | Testliste (`tests.json`) und erzeugtes C (`lifted.c`) |
| `scripts/recomp/diff/cases.c`, `difftest.h`, `tmpl.S`, `native.c`, `ctest.c`, `common.py` | Eingaben, Referenzschleife, M1-Lauf, C-Harness |
| `scripts/recomp/diff/difftest.py`, `report.py` | Treiber (Unicorn/M1/c gegeneinander), Auswertung |
| `scripts/recomp/diff/build_c.sh`, `run_ryzen.sh` | Bibliotheken bauen; Variantenläufe auf dem Ryzen (`base`, `neg`) |
| `scripts/recomp/diff/exh.c`, `exh_gen.py`, `exh_run.sh`, `exh_cmp.py` | erschöpfender Einzelbefehlstest |
| `scripts/recomp/diff/bench_fp.c`, `bench_fp.sh`, `bench_fp_uc.py` | Float-Benchmark-Beweis |
| `scripts/recomp/diff/perf_c.py` | Kostenmessung |
| `scripts/recomp/c_exact/fp_env.h`, `NOTICE` | Host-FPU-Schutz, Lizenzhinweis |

```bash
python3 scripts/recomp/diff/hist.py                       # Mac, 3 min
python3 scripts/recomp/diff/mktests.py                    # Mac, 40 s
bash scripts/recomp/diff/build_c.sh base && bash scripts/recomp/diff/build_c.sh c mac_o1 -O1 -ffp-contract=off
python3 scripts/recomp/diff/difftest.py --src m1,uc,c:mac_o1=work/recomp/diff/lib_mac_o1.so --jobs 2 --out work/recomp/diff/rep_mac.json
# Ryzen: rsync scripts/recomp/diff, c_exact und work/recomp/diff/{tests.json,lifted.c} nach ~/xnu-recomp, dann
ssh <RZ_HOST> 'cd ~/xnu-recomp && bash scripts/recomp/diff/run_ryzen.sh base'     # Varianten; `neg`: Negativkontrolle
bash scripts/recomp/diff/exh_run.sh m1                                        # Mac; Ryzen: exh_run.sh c "-O1 -march=x86-64-v3 -ffp-contract=off" 4
```
