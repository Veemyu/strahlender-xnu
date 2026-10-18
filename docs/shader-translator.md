# Shader-Übersetzer Maxwell → MSL (Stand 2026-10-18, Teil 1: Übernahme und Abdeckungsmessung)

Der Übersetzer aus LASRecomp (MIT, Herkunft und Änderungen in `shader_translator/NOTICE.md`, Hinweise in `THIRD_PARTY_NOTICES.md`) liegt jetzt als eigenständiges Kommandozeilenwerkzeug `maxwell2msl` im Repo. Teil 1 beantwortet: Wie viele der Switch-Shader aus den Bundles kann er heute übersetzen, und was fehlt? Die Analyse und der Übernahmeplan stehen in `docs/referenz-las-shader.md`. Kernziel, Gamma/Built-in-Pipeline und Differenztests: `docs/kernziel.md`, `docs/render-treue.md`, `docs/shader-harness.md`.

Markierung: **belegt** = gemessen oder im Code gelesen, *vermutet* = Schluss ohne Test.

**Rahmen:** Das Repo enthält nur Code und Doku. Die Shader-Binärdaten entstehen lokal unter `work/shaders/` (gitignored) aus den eigenen Bundles.

## 1. Aufbau

| Datei (`shader_translator/`) | Herkunft | Inhalt |
|---|---|---|
| `translate.c`, `shader.h` | LASRecomp, von uns geändert | Übersetzer Maxwell-Maschinencode → MSL (und GLSL, ungenutzt). |
| `container.c`, `container.h` | eigen | Leser für Unity-Shaderprogramme (Magic `0x0C07513C`, Control `0x98761234`, Blob ab `0x12345678`). |
| `main.c` | eigen | Werkzeug `maxwell2msl`. |
| `survey_report.py` | eigen | Fasst Survey-Läufe zu einem Histogramm zusammen. |
| `Makefile`, `tests/` | eigen | Bauen (clang, `-O2`, Warnungen), `make test`, `make asan`. |
| `LICENSE-LASRecomp`, `NOTICE.md` | Original bzw. eigen | Lizenztext unverändert, Herkunft und Änderungsliste. |

Außerhalb: `scripts/shader_extract_blobs.py` (Extraktion aus den Bundles nach `work/shaders/blobs/`), `scripts/tests/test_shader_extract.py`.

Datenfluss: Bundles (Unity, Plattform 19) → `shader_extract_blobs.py` → `work/shaders/blobs/<hash>.bin` + `index.json` → `maxwell2msl --survey --batch` → `survey.jsonl` → `survey_report.py` → Histogramm.

## 2. Aufruf

```sh
make -C shader_translator            # baut build/maxwell2msl
make -C shader_translator test       # 47 C-Prüfungen, 12 CLI-Tests, 6 Report-Tests (synthetisch)
make -C shader_translator asan       # dieselbe CLI mit AddressSanitizer/UBSan

# Eine Datei übersetzen (Unity-Programm: Stufe kommt aus dem Container; rohe Blobs brauchen --stage)
shader_translator/build/maxwell2msl prog.bin -o prog.metal --info prog.json
shader_translator/build/maxwell2msl --stage fs blob.bin

# Abdeckung: ein Shader als JSON, oder viele per Listendatei ('vs|fs|cs <Pfad>' je Zeile), eine JSON-Zeile je Shader
shader_translator/build/maxwell2msl --survey --stage fs blob.bin
shader_translator/build/maxwell2msl --survey --batch list.txt -o survey.jsonl
```

Optionen: `--stage vs|fs|cs`, `-o`, `--info` (cbuf-Maske und -Größen, dynamisch indizierte cbufs, Texturen, Attribut- und Ausgabemasken), `--survey`, `--batch`, `--attr-kind N=f|i|u`, `--rt-kind N=f|i|u`, `--vs-out-mask`, `--flip-y`, `--depth-minus-one`, `--rscale`, `--glsl`, `--annotate`. Die Schlüsselwerte (`ShaderKey`) entsprechen dem Original.

Exit-Codes: 0 ok (Survey: keine Probleme), 1 Übersetzung fehlgeschlagen (Survey: Probleme gefunden), 2 falsche Bedienung, 3 Eingabe-/Ausgabefehler (Datei, unbekannter Container).

Eingabeformat: Maxwell-Blob (NVN-Kopf `0x12345678`, 0x30 Byte; SPH, 0x50 Byte; Code ab 0x80 in Vierergruppen aus einem Scheduling-Wort und drei Instruktionen; Compute: Code ab Dateianfang) oder ein komplettes Unity-Programm. Ein Konstantenpuffer wird nicht als Eingabe gelesen; die Konstantenpuffer-Informationen sind die **Ausgabe** (`--info`). Compiler-Konstanten hinter dem Code liest der Übersetzer in Teil 1 nicht.

Survey-JSON je Shader: `file`, `stage`, `bytes`, `insts`, `translatable`, `us`, `unknownOpcodes[]` (`name` = `op<obere 12 Bit>`, `bits`, `count`, `example`), `unsupportedForms[]` (`name`, `count`, `example`), optional `error`/`inputError`/`overflow`.

Extraktion:

```sh
PYTHONPATH=tools/pydeps python3 scripts/shader_extract_blobs.py            # work/shaders/blobs (Dpr/shaders + Effects/fxparticle)
PYTHONPATH=tools/pydeps python3 scripts/shader_extract_blobs.py --extra --out work/shaders/blobs_extra   # plus resources.assets, tmpshader
python3 shader_translator/survey_report.py work/shaders/blobs/index.json work/shaders/blobs/survey.jsonl --json work/shaders/blobs/report.json
```

## 3. Abweichungen vom Original (Kurzfassung, Details in `NOTICE.md`)

1. **Survey-Modus** (`maxwell_translate_ex`): sammelt alle unbekannten Opcodes und nicht unterstützten Formen statt beim ersten Fehler abzubrechen; meldet auch stille Platzhalter (`approx:`). Das Verhalten ohne Survey ist unverändert.
2. **Fehler im Codeende behoben:** Das Padding hinter EXIT ist bei Unity-Shadern ein Sprung auf das davorliegende Scheduling-Wort (Verschiebung −16). Das Original kannte nur −8 und las dann Compiler-Konstanten als Instruktionen (in der ersten Messung 67 falsche „unbekannte Opcodes“; `op000` und `opbf1` waren Fließkommakonstanten).
3. **Eingabeprüfung** auf Mindestgröße.
4. **LAS-Spezifika entfernt:** Debug-Haken `maxwell_dbg_*`, `getenv`-Schalter, Tint-Epilog (Puffer 19).
5. **`no_rscale`:** keine Auflösungsskalierung (Puffer 18); Standard im Werkzeug.
6. **Noch unverändert:** GLSL-Zweig, `flip_x`, Global-Memory-Globals, nicht threadsichere statische Puffer, `sprintf` ohne Grenzen (Aufgaben unten).

## 4. Messergebnis

Gemessen am 2026-10-18, Rechner M1 Pro, `clang` 23 (Homebrew), `-O2`. Alle Zahlen stammen aus `work/shaders/blobs/report.txt`.

### 4.1 Korpus

| Größe | Wert |
|---|---|
| Programme in `Dpr/shaders` + `Effects/fxparticle` | **13.710** (Vertex 6.878, Fragment 6.832); alle Container parsen |
| davon `shaders` / `fxparticle` | 5.734 / 7.976 |
| Eindeutige Maxwell-Blobs (ganzer Blob ab NVN-Kopf bis Programmende) | **4.276** (Vertex 683, Fragment 3.593) |
| Eindeutige Codes (SPH + Code ohne Konstanten und Folgedaten) | **2.859** |
| Blobgröße | Median 1.604 Byte, Maximum 9.352 Byte |
| Mit `--extra` (plus `resources.assets`, `tmpshader`) | 13.918 Programme, 4.336 Blobs, 2.919 Codes (`work/shaders/blobs_extra`, Ergebnis fast identisch) |

**Abweichung zu den bisher genannten 8.332 „eindeutigen Codes“ (belegt; Ursache *vermutet*):** Dieser Wert stammt aus dem Hash in `scripts/shader_map.py`, der den Code bis `dataOffset + dataSize` als absolute Position abschneidet. Schneide ich so ab, entstehen aus denselben Blobs 8.454 statt 4.276 verschiedene Werte. Vermutlich verschiebt sich der Bezugspunkt mit der Länge der Keyword-Liste, sodass gleiche Codes verschiedene Hashes bekommen. Außerdem bleibt bei diesem Schnitt in 254 Blobs weniger als eine Instruktionsgruppe übrig, obwohl der Code dahinter weitergeht. Deshalb schneidet `shader_extract_blobs.py` nicht ab, sondern exportiert bis zum Programmende, und der Übersetzer findet das Codeende selbst. `shader_map.py` wurde nicht geändert (gehört dem anderen Agenten). Das Ryujinx-Mapping über den Präfixvergleich ist nicht betroffen; nur die Zahl „eindeutige Codes“ ist dort zu hoch.

### 4.2 Abdeckung („übersetzbar“ = kein unbekannter Opcode, keine nicht unterstützte Form, kein stiller Platzhalter)

| Stufe | Blobs | übersetzbar | Codes | übersetzbar | Programme | übersetzbar |
|---|---|---|---|---|---|---|
| alle | 4.276 | **684 (16,0 %)** | 2.859 | 670 (23,4 %) | 13.710 | 6.876 (50,2 %) |
| Vertex | 683 | 675 (98,8 %) | 675 | 667 (98,8 %) | 6.878 | 6.842 (99,5 %) |
| Fragment | 3.593 | **9 (0,3 %)** | 2.184 | 3 (0,1 %) | 6.832 | 34 (0,5 %) |

Nach Bundle (Blobs): `shaders` 1.154, davon 322 übersetzbar (Vertex 315 von 323, Fragment 7 von 831); `fxparticle` 3.122, davon 362 übersetzbar (Vertex 360 von 360, Fragment 2 von 2.762). Die 50 % bei den Programmen täuschen: Sie entstehen fast nur durch die Vertex-Shader. **Fragment-Shader sind heute praktisch nicht übersetzbar.**

### 4.3 Fehlende Befehle (je Blob gezählt; es gibt nur diese drei Gruppen)

| Problem | Blobs | Codes | Programme | Vorkommen | Stufe |
|---|---|---|---|---|---|
| `TEX.B` (bindlose Textur, Meldung „bindless tex“) | 3.592 (84,0 %) | 2.189 | 6.834 | 13.613 | 3.584 Fragment, 8 Vertex |
| Opcode-Gruppe `0x7e8` = **HSETP2**, Konstantenpuffer-Form | 437 | 437 | 1.589 | 813 | Fragment |
| Opcode-Gruppe `0x7e0` = **HSETP2**, Immediate-Form | 179 | 179 | 566 | 181 | Fragment |

Die Namen der beiden Gruppen habe ich in der öffentlichen Dekodertabelle eines Emulators nachgeschlagen (`maxwell.inc` des Projekts citron-neo/emulator; GPL, nur gelesen, nichts kopiert). *Vermutet*, bis ein Test es bestätigt: Der Übersetzer kann HSETP2 nur in der Registerform.

Reihenfolge nach Nutzen (greedy): `TEX.B` allein macht 3.152 Blobs übersetzbar (89,7 % der Blobs, 88,4 % der Programme), dazu HSETP2-cbuf 261 (95,8 %), HSETP2-imm 179 (100 %). **Nach diesen drei Punkten bleibt im Korpus kein unbekannter Befehl.** Das ist eine Aussage über „erkannt“, nicht über „richtig“ (4.6).

Nicht gefunden (anders als in `referenz-las-shader.md` befürchtet): TLD4/TXD/TMML, Bildzugriffe, Atomics, indizierte IPA/LD, `mufu`-Varianten, PRMT-Modi, BFE.BREV, R2P.CC, CSET, TXQ-Typen. Entweder kommen sie in diesen Bundles nicht vor, oder ein anderes Muster erfasst sie fälschlich (4.6). Stille Platzhalter (`approx:`) traten nicht auf.

### 4.4 Laufzeit

Der Lauf über alle 4.276 Blobs dauert in einem Prozess **0,5 s** (kalt 1,3 s), 639.844 Instruktionen; je Shader Mittel 88 µs, Median 48 µs, P95 237 µs, Maximum 398 µs. Der Übersetzer ist als Build-Schritt unkritisch. Derselbe Lauf mit `make asan` liefert identische Ergebnisse und keine Sanitizer-Meldung.

### 4.5 Kompilierbarkeit der Ausgabe

Alle 684 übersetzbaren Blobs wurden mit `maxwell2msl` zu MSL übersetzt und mit dem Metal-Laufzeitcompiler (`scripts/shader_msl_check.swift`, Sprachversion 2.3, Apple M1 Pro) geprüft: **684 von 684** kompilieren (13 s). Das sagt nur etwas über die Syntax.

### 4.6 Grenzen der Messung

- **„Erkannt“ ist nicht „richtig“.** Der Decoder ist eine Kette von Maskenmustern ohne Gegenprobe. Ein zu lockeres Muster würde einen anderen Befehl still falsch übersetzen und nie als unbekannt auftauchen. Die Absicherung ist der numerische Vergleich in Teil 2.
- Die Instruktionsmischung (welche Befehle wie oft vorkommen) wurde nicht ausgewertet.
- Ob Kontrollfluss mit `switch (pc)` vorkommt und wie er sich auf Metal-Compilezeit und Ableitungen auswirkt, wurde nicht gemessen.
- Die 684 kompilierenden Shader sind fast alle Vertex-Shader.
- Die Gegenprobe mit dem Ryujinx-Cache als Zweitkorpus (`referenz-las-shader.md`, Abschnitt 11, Punkt 7) steht aus.

## 5. Befunde für Teil 2

- **TEX.B ist der Hauptblocker.** Der Übersetzer hat die Felder für bindlose Texturen vorbereitet (`ShaderTexture.bindless`, `bindless_cbuf`, `bindless_offset`), die Umsetzung fehlt aber. Die Annahme in `referenz-las-shader.md` („bindlos wahrscheinlich nicht relevant“) ist damit widerlegt: Unity-NVN-Shader sampeln fast alle über Handles.
- **Herkunft der Handles (belegt für 13.544 von 13.601 TEX.B in Fragment-Shadern):** Das Handle-Register wird unmittelbar vorher von einer Instruktion der Klasse `0x4c4x` (*vermutet*: logische Verknüpfung, Konstantenpuffer-Form) aus **cbuf 2** gesetzt. Die Offsets laufen in 8-Byte-Schritten von `0x568` bis `0x5c8` (13 Werte; `0x568` 3.822-mal, `0x570` 3.408-mal, abnehmend bis `0x5c8` 12-mal). *Vermutet:* cbuf 2 ist die Handle-Tabelle des Treibers, Textur k liegt bei `0x568 + 8k`. Die Zuordnung zu den Unity-Texturnamen kommt aus dem Parameter-Layout der Shaderdaten.
- **Vertex-Shader sind fast fertig** (98,8 %): die 8 Ausnahmen sind Vertex-Textur-Zugriffe (TEX.B).
- Pro Fragment-Blob kommen meist 2 bis 4 TEX.B vor (bis 20).

## 6. Aufgabenliste für Teil 2 (priorisiert)

1. **TEX.B umsetzen** (Abdeckung 16 % → 90 %). Handle aus Register, Feldlayout (Koordinaten ab `Ra`, Zusatzparameter hinter dem Handle-Register; Felder für Offset und LOD-Modus sind im Original schon als „bindless“-Zweig vorbereitet), Textur-Slot aus dem cbuf-2-Offset ableiten (`ShaderTexture.bindless_cbuf/offset`), Typ aus den Zielbits wie bei TEX. Unit-Tests aus den realen Beispielwörtern; danach gegebenenfalls weitere bindlose Formen (TLD.B, TLDS), die erst dann sichtbar werden.
2. **HSETP2 cbuf/imm** (ergibt 95,8 % bzw. 100 %). Feldlayout der Registerform übernehmen; Halb-Vergleich mit Konstantenpuffer- und Immediate-Operand. Prüfen, ob HSET2/HADD2/HMUL2/HFMA2 in diesen Formen fehlen (im Korpus nicht gesehen).
3. **Numerische Treue-Tests** gegen `scripts/shader_harness`: gleiche Vertex-, Konstanten- und Texturdaten durch (a) Ryujinx-SPIR-V → MSL (Referenz) und (b) `maxwell2msl`-MSL, Pixel- bzw. wertweise vergleichen. Zuerst die über `work/shaders/mapping.json` zuordenbaren Guest-Einträge (laut `shader_map.py` 1.315 mit Bundle-Gegenstück), dann Einzelbefehl-Mikrotests (MUFU RCP/RSQ/SIN/COS/EX2/LG2, F2I-Rundung, Halbpräzision, SHF/BFE/PRMT/XMAD). Dazu eine unabhängige Gegenprobe des Decoders (Musterüberdeckung), siehe 4.6.
4. **Fast-Math aus.** Das Original lässt Metals Fast-Math an. Für 1:1 prüfen: Compile-Optionen bzw. Unity-seitig `#pragma` und `precise`; FTZ- und Rundungsflags der Befehle auswerten; Verhalten bei Denormalen messen.
5. **`noperspective` und Interpolation.** `noperspective_mask` wird im Original nie gesetzt; Zentroid/Sample werden nicht ausgewertet. Aus den SPH-Interpolationsangaben und den IPA-Modi ableiten und gegen die Referenz absichern.
6. **Unity-Konstantenpuffer abbilden.** cbuf 0 = Treiber, cbuf 1 = Compiler-Konstanten, cbuf 2 = Handle-Tabelle (siehe oben), cbuf ≥ 3 = Unity-Blöcke (`UnityPerDraw`, `UnityPerCamera`, Material). Offsets und Namen aus dem Parameter-Layout der geparsten Shaderdaten (`scripts/shader_inventory.py`, `docs/shader-inventar.md`), Ausgabe als benannte Struktur statt `uint4`-Feld. Prüfen, ob `cbuf_base = 3` für Unity-glslc stimmt.
7. **Compiler-Konstanten (cbuf 1)** aus dem Blobende lesen (Format, Lage hinter dem Code, Control-Felder `+0x6FC`/`+0x700` im Unity-Container) und als `constant`-Array in die Ausgabe einbetten. Heute ignoriert.
8. **Keyword-Varianten.** `index.json` um die Zuordnung Programm → Blob-Hash (mit Shader, Pass, Keywords) ergänzen; Auswahl im Build nach Unity-Keyword-Sätzen; 13.710 Programme → 4.276 Blobs → 2.859 Codes, Deduplizierung im Build.
9. **Härtung.** `sprintf` durch Grenzen ersetzen, `cbuf_ref` ohne Obergrenze (Index ≥ 18), Registerindex-Prüfung, statische Puffer in `RSC2` thread-sicher machen, Fuzz-Test; danach parallele Übersetzung.
10. **Kontrollfluss.** Anteil der Shader mit `switch (pc)` messen; bei Bedarf strukturierten Kontrollfluss erzeugen (Compilezeit, Ableitungen im nicht-uniformen Fluss, HLSL-Tauglichkeit).
11. **Ausgabeform für Unity entscheiden** (`referenz-las-shader.md`, Abschnitt 9): HLSL-Backend für ShaderLab (i) oder MSL-Plugin (ii); Y- und Tiefen-Konventionen (`flip_y`, `depth_minus_one`) an Unity anpassen.
12. **Restliche LAS-Spezifika:** `flip_x`, Global-Memory-Globals; ungenutzten GLSL-Zweig entfernen oder behalten (Entscheidung).
13. **Erweiterte Messung:** Instruktionsmischung, Metal-Compilecheck nach jedem Schritt über alle übersetzbaren Blobs, Zweitkorpus aus dem Ryujinx-Cache, Kontrollfluss-Statistik; den Hash-Befund aus 4.1 an den Besitzer von `shader_map.py` weitergeben.

## 7. Reproduktion

```sh
make -C shader_translator test
PYTHONPATH=tools/pydeps python3 scripts/shader_extract_blobs.py
python3 - <<'EOF'   # Listendatei (Pfade relativ zum Repo-Root)
import json
d = "work/shaders/blobs"
with open(f"{d}/list.txt", "w") as f:
    for e in json.load(open(f"{d}/index.json"))["blobs"]:
        f.write(f"{e['stage']} {d}/{e['hash']}.bin\n")
EOF
shader_translator/build/maxwell2msl --survey --batch work/shaders/blobs/list.txt -o work/shaders/blobs/survey.jsonl
python3 shader_translator/survey_report.py work/shaders/blobs/index.json work/shaders/blobs/survey.jsonl
```

Testbestand: `shader_translator/tests/test_translate.c` (Kern und Container, Survey-Sammlung, Codeende), `tests/test_cli.py` (Exit-Codes, JSON, Batch, Schlüsseloptionen), `tests/test_report.py` (Histogramm), `scripts/tests/test_shader_extract.py` (Container-Parser, Codeende, Deduplizierung). Alle mit synthetischen Eingaben, ohne Spieldaten.
