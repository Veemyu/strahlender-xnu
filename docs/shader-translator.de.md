# Shader-Übersetzer Maxwell → MSL (Stand 2026-10-18, Teil 1: Übernahme und Abdeckungsmessung; Teil 2: TEX.B, HSETP2, Ressourcenkarte, exakte Arithmetik, Treue-Test)

Der Übersetzer aus LASRecomp (MIT, Herkunft und Änderungen in `shader_translator/NOTICE.md`, Hinweise in `THIRD_PARTY_NOTICES.md`) liegt als eigenständiges Kommandozeilenwerkzeug `maxwell2msl` im Repo. Teil 1 (Abschnitte 1 bis 6) beantwortete: Wie viele der Switch-Shader aus den Bundles kann er übersetzen, und was fehlt? Teil 2 (ab Abschnitt 8) schließt die Lücken und prüft die Übersetzung numerisch gegen die Ryujinx-Referenz. **Kurzergebnis Teil 2:** 100 % der Blobs werden erkannt (4.276 von 4.276, Vertex und Fragment), alle 8.552 erzeugten MSL-Dateien kompilieren mit Metal, und im Treue-Test mit 500 Programmpaaren liegen 85,8 % der aussagekräftigen Paare (332 von 387) innerhalb von 1/255 je Kanal; 155 davon sind bitgleich. Die restlichen Abweichungen gehen fast ganz auf eine Näherung der Referenz bei fp16 zurück (Abschnitt 11); rechnet man diese heraus, sind es 95,1 % (368 von 387). Die Analyse und der Übernahmeplan stehen in `docs/referenz-las-shader.md`. Kernziel, Gamma/Built-in-Pipeline und Differenztests: `docs/kernziel.md`, `docs/render-treue.md`, `docs/shader-harness.md`.

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

Außerhalb: `scripts/shader_extract_blobs.py` (Extraktion aus den Bundles nach `work/shaders/blobs/`), `scripts/tests/test_shader_extract.py`, ab Teil 2 `scripts/shader_fidelity.py` (Treue-Test) mit `scripts/tests/test_shader_fidelity.py` (24 Tests, synthetisch).

Datenfluss: Bundles (Unity, Plattform 19) → `shader_extract_blobs.py` → `work/shaders/blobs/<hash>.bin` + `index.json` → `maxwell2msl --survey --batch` → `survey.jsonl` → `survey_report.py` → Histogramm.

## 2. Aufruf

```sh
make -C shader_translator            # baut build/maxwell2msl
make -C shader_translator test       # 72 C-Prüfungen, 14 CLI-Tests, 6 Report-Tests (synthetisch)
make -C shader_translator asan       # dieselbe CLI mit AddressSanitizer/UBSan

# Eine Datei übersetzen (Unity-Programm: Stufe kommt aus dem Container; rohe Blobs brauchen --stage)
shader_translator/build/maxwell2msl prog.bin -o prog.metal --info prog.json
shader_translator/build/maxwell2msl --stage fs blob.bin

# Abdeckung: ein Shader als JSON, oder viele per Listendatei ('vs|fs|cs <Pfad>' je Zeile), eine JSON-Zeile je Shader
shader_translator/build/maxwell2msl --survey --stage fs blob.bin
shader_translator/build/maxwell2msl --survey --batch list.txt -o survey.jsonl
```

Optionen: `--stage vs|fs|cs`, `-o`, `--info` (Ressourcenkarte, Abschnitt 9), `--cbuf1 <Datei>` (Compiler-Konstanten, Abschnitt 9), `--survey`, `--batch`, `--attr-kind N=f|i|u`, `--rt-kind N=f|i|u`, `--vs-out-mask`, `--flip-y`, `--depth-minus-one`, `--rscale`, `--glsl`, `--annotate`, `--fast-math` (Pragmas aus, Abschnitt 10), `--half-compat` (Testorakel, Abschnitt 11). Die Schlüsselwerte (`ShaderKey`) entsprechen dem Original.

Exit-Codes: 0 ok (Survey: keine Probleme), 1 Übersetzung fehlgeschlagen (Survey: Probleme gefunden), 2 falsche Bedienung, 3 Eingabe-/Ausgabefehler (Datei, unbekannter Container).

Eingabeformat: Maxwell-Blob (NVN-Kopf `0x12345678`, 0x30 Byte; SPH, 0x50 Byte; Code ab 0x80 in Vierergruppen aus einem Scheduling-Wort und drei Instruktionen; Compute: Code ab Dateianfang) oder ein komplettes Unity-Programm. Ein Konstantenpuffer wird nicht als Eingabe gelesen; die Konstantenpuffer-Informationen sind die **Ausgabe** (`--info`). Die Compiler-Konstanten hinter dem Code (Konstantenpuffer 1) liest der Übersetzer nicht selbst, `--cbuf1` schreibt sie aus (Abschnitt 9).

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
6. **Noch unverändert:** GLSL-Zweig (TEX.B und `half_compat` nur für MSL, GLSL nicht getestet), `flip_x`, Global-Memory-Globals, nicht threadsichere statische Puffer, `sprintf` ohne Grenzen (Aufgaben unten).
7. **Teil 2 (Abschnitte 8 bis 11):** TEX.B, HSETP2 (cbuf/imm), Ressourcenkarte, Pragmas gegen Fast-Math und FMA-Verschmelzung, `half_compat`. Jede Änderung ist im Quelltext mit `XNU:` und in `NOTICE.md` verzeichnet.

## 4. Messergebnis (Teil 1, Stand vor TEX.B und HSETP2; neue Zahlen in Abschnitt 8)

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

## 5. Befunde für Teil 2 (Teil 1; Auflösung in Abschnitt 8)

- **TEX.B ist der Hauptblocker.** Der Übersetzer hat die Felder für bindlose Texturen vorbereitet (`ShaderTexture.bindless`, `bindless_cbuf`, `bindless_offset`), die Umsetzung fehlt aber. Die Annahme in `referenz-las-shader.md` („bindlos wahrscheinlich nicht relevant“) ist damit widerlegt: Unity-NVN-Shader sampeln fast alle über Handles.
- **Herkunft der Handles (belegt für 13.544 von 13.601 TEX.B in Fragment-Shadern):** Das Handle-Register wird unmittelbar vorher von einer Instruktion der Klasse `0x4c4x` (*vermutet*: logische Verknüpfung, Konstantenpuffer-Form) aus **cbuf 2** gesetzt. Die Offsets laufen in 8-Byte-Schritten von `0x568` bis `0x5c8` (13 Werte; `0x568` 3.822-mal, `0x570` 3.408-mal, abnehmend bis `0x5c8` 12-mal). *Vermutet:* cbuf 2 ist die Handle-Tabelle des Treibers, Textur k liegt bei `0x568 + 8k`. Die Zuordnung zu den Unity-Texturnamen kommt aus dem Parameter-Layout der Shaderdaten. **Teil 2 präzisiert das:** vor der `0x4c4x`-Instruktion (LOP.OR) steht ein MOV aus demselben Puffer; das Handle ist die ODER-Verknüpfung zweier Wörter (Abschnitt 8).
- **Vertex-Shader sind fast fertig** (98,8 %): die 8 Ausnahmen sind Vertex-Textur-Zugriffe (TEX.B).
- Pro Fragment-Blob kommen meist 2 bis 4 TEX.B vor (bis 20).

## 6. Aufgabenliste für Teil 2 (aus Teil 1) und ihr Stand

| Nr. | Aufgabe | Stand nach Teil 2 |
|---|---|---|
| 1 | TEX.B | **erledigt** (Abschnitt 8) |
| 2 | HSETP2 cbuf/imm | **erledigt** (Abschnitt 8); HSET2 in diesen Formen kommt im Korpus nicht vor |
| 3 | Numerische Treue-Tests | **erledigt für Gesamtshader** (Abschnitt 11); Einzelbefehl-Mikrotests und Gegenprobe des Decoders offen (Teil 3) |
| 4 | Fast-Math aus | **erledigt** (Abschnitt 10); FTZ/Denormale offen |
| 5 | `noperspective`/Interpolation | **offen**: in den 500 getesteten Referenzen kommt kein `flat`, `noperspective` oder `centroid` vor, der Fall wurde also nicht geprüft |
| 6 | Unity-Konstantenpuffer abbilden | **teilweise**: Ressourcenkarte liefert Größen und Bereiche (Abschnitt 9); Namen aus dem Parameter-Layout offen (Teil 3) |
| 7 | Compiler-Konstanten (cbuf 1) | **erledigt**: Lage hinter dem Code gefunden, `--cbuf1` (Abschnitt 9); Einbetten als `constant`-Array offen |
| 8 | Keyword-Varianten | **offen** (Teil 3), Programm → Blob-Zuordnung liegt lokal in `work/shaders/prog_blob.json` |
| 9 | Härtung | **offen**; der Lauf über alle 8.552 Übersetzungen mit AddressSanitizer/UBSan blieb ohne Meldung |
| 10 | Kontrollfluss | **offen** |
| 11 | Ausgabeform für Unity | **offen** (Teil 3) |
| 12 | Restliche LAS-Spezifika | **offen** |
| 13 | Erweiterte Messung | **teilweise**: Zweitkorpus (Ryujinx) ist jetzt der Treue-Test; Instruktionsmischung und Kontrollfluss-Statistik offen |

Der ursprüngliche Wortlaut der Aufgaben steht im Git-Verlauf dieser Datei.

## 8. Teil 2: TEX.B, HSETP2 und Abdeckung

### 8.1 TEX.B (bindlose Textur)

**Wie das Handle entsteht (belegt an allen 13.613 TEX.B des Korpus).** Der Unity-Compiler baut das Handle-Register aus zwei Wörtern des Konstantenpuffers 2: erst `MOV Rh, c[2][s]`, dann `LOP.OR Rh, Rh, c[2][t]`. Ein NVN-Handle trägt die Textur-ID in den unteren 20 und die Sampler-ID in den oberen 12 Bit; das Wort `t` liegt im Bereich ab `0x568`, das Wort `s` im Bereich ab `0x168`, beide im 8-Byte-Raster. Die Textur ist damit zur Übersetzungszeit bekannt, ein Laufzeit-Handle braucht die MSL nicht. Der Übersetzer verfolgt dazu für jedes Register, ob sein Wert aus Konstantenpuffer-Wörtern aufgebaut wurde (`prov_track()`; MOV c[][], LOP.OR, LDC, Register-MOV; jeder andere Schreibzugriff setzt zurück, ein bedingter Schreibzugriff ebenfalls). Wer das Handle nicht auflösen kann, bekommt weiter einen Fehler.

Feldlage von TEX.B (wie `TEX`, nur anders angeordnet): Ziel Bit 0..7, Koordinaten ab `Ra` (Bit 8..15), Handle-Register `Rb` (Bit 20..27), Dimension Bit 28..30 (Array, Ziel), Schreibmaske Bit 31..34, Offset-Flag Bit 36, LOD-Modus Bit 37..39, Tiefenvergleich Bit 50. Die Register hinter dem Handle liefern der Reihe nach LOD, Offset und Tiefenvergleichswert. Alle Formen aus `TEX` (1D/2D/3D/Cube, Array, Shadow, LOD-Modi, Offset) sind damit ohne zusätzlichen Code auch für TEX.B nutzbar; im Korpus kommen davon 2D und Cube mit den LOD-Modi „implizit“, `LL` und `LZ` vor (Cube nur 4-mal, Shadow, Array und Offset nie).

**Messung über alle 4.276 Blobs (aus der Ressourcenkarte):** 3.592 Blobs haben Texturen, zusammen 13.134 verschiedene Texturslots (höchstens 13 je Blob), alle über cbuf 2, alle mit Samplerwort. 13.130 sind 2D, 4 Cube. Die Slots entstehen in der Reihenfolge der ersten Benutzung; zwei Slots sind gleich, wenn Wortpaar, Typ, Shadow- und Array-Flag gleich sind. Der Abstand Texturwort minus Samplerwort ist in 8.043 Fällen (61 %) genau `0x400`, sonst `0x3f8` (3.646), `0x408` (409), `0x410` (146) und weitere: Sampler und Textur sind also frei kombinierbar, der Sampler hat einen eigenen Tabellenindex. **Gegenprobe:** Der Ryujinx-Name einer bindlosen Textur kodiert dasselbe Wortpaar (`fp_tex_cb196610_1056805A` = Texturwort `0x568`, Samplerwort `0x168`). In allen 970 Stufen-Paaren des Treue-Tests (Vertex und Fragment von 500 Paaren) stimmt die Menge der (Textur, Sampler)-Schlüssel zwischen unserer Übersetzung und der Referenz überein.

### 8.2 HSETP2 mit cbuf- und Immediate-Operand

Die Registerform war vorhanden. Die beiden anderen Formen (Gruppe `0x7e80`/`0x7f80` und `0x7e00`/`0x7f00`) haben dieselben Felder an anderer Stelle, weil Bit 20..38 den Operanden tragen: Vergleich Bit 49..52 (Registerform: 35..38), HAND Bit 53 (49), bei der cbuf-Form Negation Bit 56 und Betrag Bit 54, Operand als ein f32 (cbuf) bzw. als zwei Halbwerte mit eigenen Vorzeichen (imm, dieselbe Kodierung wie bei HADD2). Die Lage habe ich aus den Feldpositionen der HADD2/HMUL2-Formen der gleichen Befehlsfamilie angesetzt und an den Wörtern des Korpus gegengeprüft (Quellwörter: `0x7e85038c0457ff07`, `0x7e0883bc0f071207`); entscheidend ist die numerische Prüfung: 128 Paare mit der cbuf-Form und 73 mit der imm-Form kamen in den Treue-Test, im Rahmen von Abschnitt 11 bestehen 117 bzw. 71 davon. HSET2 in diesen Formen (Gruppe `0x7c..`) kommt im Korpus nicht vor und ist nicht umgesetzt.

### 8.3 Abdeckung nach Teil 2

Erneut gemessen mit `--survey` über alle Blobs, Zahlen aus `survey_report.py`:

| Stufe | Blobs | erkannt | Codes | erkannt | Programme | erkannt |
|---|---|---|---|---|---|---|
| alle | 4.276 | **4.276 (100 %)** | 2.859 | 2.859 (100 %) | 13.710 | 13.710 (100 %) |
| Vertex | 683 | 683 (100 %) | 675 | 675 | 6.878 | 6.878 |
| Fragment | 3.593 | 3.593 (100 %) | 2.184 | 2.184 | 6.832 | 6.832 |

Der Zusatzkorpus (`--extra`, plus `resources.assets` und `tmpshader`) ergibt 4.336 von 4.336 Blobs und 13.918 von 13.918 Programmen. Es bleiben keine unbekannten Opcodes und keine nicht unterstützten Formen; weitere Befehle (TLD.B, TLDS, TXQ.B) tauchten nach TEX.B nicht auf. Der Lauf dauert 0,5 s. **Alle 4.276 Blobs lassen sich übersetzen (`maxwell2msl` ohne Survey), und alle 8.552 erzeugten MSL-Dateien (Standardmodus und `--half-compat`) kompilieren mit dem Metal-Laufzeitcompiler** (`scripts/shader_msl_check.swift`, 98 s, M1 Pro). Derselbe Lauf mit AddressSanitizer/UBSan blieb ohne Meldung.

„Erkannt“ heißt weiter nur „kein unbekannter Befehl“. Ob ein Befehl richtig übersetzt ist, zeigt erst Abschnitt 11.

## 9. Ressourcenkarte (`--info`)

`maxwell2msl --info <datei.json>` schreibt eine maschinenlesbare Karte, mit der ein Treiber (Harness, später Unity) die Daten richtig bindet. Neu in Teil 2 sind `metal`, `compilerConstants`, `constantBuffers`, die erweiterten `textures` sowie `inputs` und `outputs`; die älteren Schlüssel (`cbufMask`, `cbufSize`, `attrMask`, `outMask` und weitere) bleiben. Beispiel für einen synthetischen Fragment-Shader mit einer bindlosen Textur (ohne Spielinhalt, gekürzt):

```json
{
  "stage": "fs", "instructions": 4,
  "metal": {"entry": "main0", "constantBufferSlot": "cbuf k -> [[buffer(k)]], constant uint4*",
            "textureSlot": "texture i -> [[texture(i)]] and [[sampler(i)]]",
            "vertexAttribute": "location i -> [[attribute(i)]], float4",
            "stageInterface": "vertex out / fragment in: [[user(locn i)]], float4", "rscaleBuffer": null, "globalMemoryBuffer": null},
  "compilerConstants": {"cbuf": 1, "blobOffset": 256, "bytesAvailable": 16},
  "constantBuffers": [{"index": 2, "metalBuffer": 2, "size": 1536, "dynamic": false, "staticMinOffset": 360, "staticEndOffset": 1388}],
  "textures": [{"slot": 0, "metalTexture": 0, "metalSampler": 0, "type": 1, "typeName": "2d", "shadow": false, "array": false,
                "bindless": true, "handleCbuf": 2, "textureWordOffset": 1384, "textureTableIndex": 0,
                "hasSamplerWord": true, "samplerWordOffset": 360, "samplerTableIndex": 0}],
  "inputs": [], "outputs": []
}
```

Bedeutung:

- **`constantBuffers`:** je gelesenem Puffer der Index (= Metal-Pufferslot), die Größe (auf 256 Byte aufgerundet; bei Register-Index-Zugriff `dynamic: true`, dann den ganzen Puffer binden, bis 64 KB) und der Bereich der statisch adressierten Bytes (`staticMinOffset` bis `staticEndOffset`, ausschließlich). Daraus lässt sich ablesen, welche Teile eines Unity-Blocks der Shader wirklich liest.
- **`textures`:** `slot` ist zugleich Metal-Texturindex und Sampler-Index. `textureWordOffset`/`samplerWordOffset` sind die Byte-Offsets der beiden Handle-Wörter in cbuf `handleCbuf` (immer 2). Der Index in der Tabelle des Treibers ergibt sich als `(textureWordOffset − 0x568) / 8` bzw. `(samplerWordOffset − 0x168) / 8` (`textureTableIndex`/`samplerTableIndex`; die Basiswerte sind eine aus den Shadern abgeleitete Annahme, -1 bei Abweichung). Der Treiber muss die Textur dieses Tabelleneintrags an `texture(slot)` und den Sampler an `sampler(slot)` legen. Typ (`typeName`, `shadow`, `array`) bestimmt die MSL-Deklaration (`texture2d<float>`, `texturecube<float>`, `depth…`).
- **`inputs`/`outputs`:** Vertex: Eingabe-Locations mit gelesenen Komponenten (`[[attribute(i)]]`, alle als `float4` deklariert), Ausgaben mit geschriebenen Komponenten (`[[user(locn i)]]`). Fragment: Eingaben mit Interpolation (`flat`/`perspective`), Ausgaben als Farbziele mit Komponenten.
- **`compilerConstants` und `--cbuf1 <datei>`:** Der Konstantenpuffer 1 enthält die vom Compiler erzeugten Konstanten. Sie liegen im Blob hinter dem Code, auf 0x100 aufgerundet (`blobOffset`). Belegt für alle 934 Shader, die cbuf 1 statisch lesen: an dieser Stelle steht jeweils Nicht-Null-Daten; die Zahl der gelesenen Bytes passt in den geprüften Fällen zu den Fließkommakonstanten (z. B. `1.0, 0.8, 0.05, 0.1, 0.5` bei 20 gelesenen Bytes). `--cbuf1` schreibt höchstens 64 KB ab dieser Stelle (der Rest ist Reflexionsdaten und Füllbytes, die der Shader nie liest). Die Größe der Konstanten steht nicht im Blob; der Bedarf folgt aus `constantBuffers`.
- **Rollen der Puffer (Annahme, nicht von `maxwell2msl` ausgegeben):** cbuf 0 Treiber, 1 Compiler-Konstanten, 2 Handle-Tabellen, ab 3 Unity-Blöcke. Gelesene Puffer in den 4.276 Blobs: cbuf 0 in 180 Blobs, 1 in 934, 2 in 3.592, 3 in 3.615, 4 in 614, 5 in 118. Mit Register-Index (dynamisch) gelesen werden cbuf 5 in 118 und cbuf 4 in 7 Blobs (Instancing-Daten).

Hinweis: Die MSL liest die Handle-Wörter in cbuf 2 weiterhin (das MOV/LOP des Compilers wird mitübersetzt); der Wert wird nie benutzt, der Puffer muss aber gebunden sein, solange der Metal-Compiler den toten Zugriff nicht entfernt. In den 500 Paaren des Treue-Tests liest unsere Übersetzung deshalb in 473 von 970 Stufen einen Puffer mehr als die Referenz.

## 10. Exakte Arithmetik (Fast-Math aus)

**Was Metal standardmäßig tut:** Fast-Math (Umordnen, relaxierte NaN/Inf-Behandlung, schnelle Funktionen) und die Verschmelzung `a*b+c` zu einer FMA. Die Switch-GPU rundet jedes FMUL und jedes FADD einzeln. Beides ändert Ergebnisse in den letzten Bits und kann bei Schwellwerten und Rückkopplungen sichtbar werden.

**Was macOS 26 (Xcode 26.0.1, M1 Pro) akzeptiert (gemessen):**

- `MTLCompileOptions.mathMode = .safe` und `mathFloatingPointFunctions = .precise` werden auch mit Sprachversion 2.3 angenommen; vor macOS 15 bleibt `fastMathEnabled = false`.
- Die Pragmas `#pragma METAL fp math_mode(safe)` und `#pragma METAL fp contract(off)` werden mit Sprachversion 2.3 ohne Fehler übersetzt.
- **`mathMode = .safe` allein verhindert die FMA-Verschmelzung nicht:** Ein Test mit `a*b+c` (Operanden aus einem Puffer, so gewählt, dass einzeln gerundet 0, verschmolzen `2^-26` herauskommt) lieferte in beiden Modi das verschmolzene Ergebnis; erst `contract(off)` ergab das einzeln gerundete.
- Die Optionen wirken: ein bewusst chaotischer Test-Shader (sin, exp2, Division, log2, multipliziert und mit `fract` verstärkt) unterscheidet sich zwischen `safe` und `fast` um bis zu 253 Stufen (PSNR 16,7 dB).

**Umsetzung:** `maxwell2msl` schreibt die beiden Pragmas an den Anfang jeder MSL (`--fast-math` lässt sie weg). Das Harness (`scripts/shader_harness`, `Render.swift`/`main.swift`, kommentiert) kompiliert standardmäßig mit `mathMode = .safe`, genauen Funktionen und stellt Quellen ohne `fp contract`-Pragma (die spirv-cross-Referenz) `#pragma METAL fp contract(off)` voran, damit Referenz und Übersetzung gleich behandelt werden; `--fast-math` schaltet das ab. Die Ausgabe nennt den Modus (`math=safe`).

**Offen:** FTZ- und Rundungsflags der Befehle werden nicht ausgewertet; das Verhalten bei Denormalen ist nicht gemessen. Wie Unity die Pragmas oder Optionen in seiner eigenen Shader-Pipeline bekommt, ist Teil 3.

## 11. Numerischer Treue-Test (`scripts/shader_fidelity.py`)

### 11.1 Verfahren

Aus `work/shaders/mapping.json` kommen 2.901 Cache-Einträge (2.900 verschiedene Blobpaare) mit Vertex und Fragment in beiden Quellen: Bundle-Blob und Ryujinx-SPIR-V. `prog_blob.json` (Programm → Blob-Hash, `shader_fidelity.py index`) verbindet beide. Für die Stichprobe werden die Paare abwechselnd über die Shader gezogen (deterministisch), damit nicht `Delphis/Map/Standard` mit 2.570 Einträgen alles füllt.

Je Paar:

1. **Referenz:** SPIR-V → MSL mit `spirv-cross` (MSL 2.3, ohne Zusatzflags), danach die Schnittstelle aus dem MSL-Kopf gelesen: Vertexattribute, Puffer (`vp_c<k>`/`fp_c<k>` = Hardware-Cbuf k), Texturen und Sampler samt Slots. Der Ryujinx-Name einer bindlosen Textur liefert den (Textur, Sampler)-Schlüssel.
2. **Unsere Seite:** `maxwell2msl` für Vertex und Fragment (das Fragment mit `--vs-out-mask` des Vertex-Shaders), die Schnittstelle aus der Ressourcenkarte, die Compiler-Konstanten (cbuf 1) aus `--cbuf1`.
3. **Gleiche Eingaben:** Ein Gitter aus 12×12 Zellen (169 Vertices, 288 Dreiecke) mit allen Attributen der Vereinigung beider Seiten als `float4` (kleinste Location = Position in ±0,9, alle anderen Verläufe in [0, 1]); Konstantenpuffer als 64-KB-Dateien aus einem von 42 deterministischen Profilen (`identity`: Einheitsmatrizen im 64-Byte-Raster, ggf. um 1 bis 3 Vektoren verschoben, auch je Puffer verschieden; `dense`, `hash`, `signed`, `small`, `half`); Texturen 64×64 mit Mipmaps (Schachbrett mit wechselndem Alpha oder Verlauf, Farben aus dem Hash des Texturworts), Sampler linear/linear/mip-linear/wiederholend. Das erste Profil, bei dem das Referenzbild aussagekräftig ist (mindestens 2 % der Pixel bedeckt und mindestens zwei Farben), gewinnt. Cbuf 1 ist die Blob-Konstante, nicht synthetisch.
4. **Zustand:** 128×128, `rgba8Unorm`, keine Tiefe, kein Blending, kein Culling, eine Zeichnung, keine MSAA. Beide Seiten geben die Clip-Position des Gast-Shaders unverändert aus (`flip_y`/`depth_minus_one` bei uns aus, `--flip-vert-y`/`--fixup-clipspace` bei der Referenz aus); in den angesehenen Referenz-Modulen schreibt Ryujinx die Position unverändert, und 332 Paare stimmen ohne Raumkorrektur bis auf eine Stufe überein, der Zustand ist also gleich.
5. **Vergleich:** `scripts/shader_compare.py` (RGBA, größte und mittlere Abweichung, Pixel über Schwelle, PSNR). Bei Abweichung zusätzlich zwei Mischvarianten (Referenz-VS + unser FS, unser VS + Referenz-FS), die den Fehler einer Stufe zuordnen.

**Schwellen:** *bestanden* = größte Abweichung ≤ 1 Stufe je Kanal (1/255). Begründung: `rgba8Unorm` rundet; zwei Fließkommawerte, die sich nur in den letzten Bits unterscheiden, können an einer Rundungsgrenze um genau eine Stufe auseinanderfallen. Mehr als eine Stufe zeigt einen echten Rechenunterschied. *Knapp* = ≤ 3 Stufen (z. B. verschiedene Näherungen von Funktionen), *durchgefallen* darüber. Zusätzlich werden Pixelzahl über 1 Stufe, mittlere Abweichung und PSNR gespeichert.

**Nicht aussagekräftig** sind Paare, deren Referenzbild bei allen 42 Profilen fast leer (alles verworfen oder außerhalb) oder einfarbig ist; sie zählen nicht mit. **Nicht unterstützt** sind Paare mit Cube-Texturen (Harness kann nur 2D) oder Speicherpuffern (`vp_s0`, die Instanzdaten von `FxSystem/Particle`).

### 11.2 Ergebnis (500 Paare, 62 Shader, Apple M1 Pro, Metal Safe-Math, `shader_fidelity.py run --count 500`)

| Ergebnis | Paare |
|---|---|
| bestanden (≤ 1 Stufe) | **332** (davon 155 bitgleich, 177 mit höchstens 1 Stufe) |
| knapp (≤ 3) | 11 |
| durchgefallen | 44 |
| nicht aussagekräftig | 98 (64 einfarbig, 34 fast leer; 47 davon `Delphis/Map/Standard`, der Rest Alphatest-, Masken-, DepthOnly- und ähnliche Shader) |
| nicht unterstützt | 15 (11 Speicherpuffer, 4 Cube-Textur) |
| **aussagekräftig** | **387** |

**Quote (aussagekräftige Paare): 85,8 % bestanden im Standardmodus** (332 von 387, 88,6 % einschließlich „knapp“). Mit der Ryujinx-Näherung bei fp16 herausgerechnet (nächster Abschnitt): **95,1 %** (368 von 387). Die aussagekräftigen Paare stammen aus 55 der 62 Shader. Die mittlere Abweichung über alle Kanalwerte beträgt bei den bestandenen Paaren im Mittel 0,008 Stufen (höchstens 0,21). Teilmengen (Standardmodus bzw. kompatibel): Paare mit TEX.B 331 von 386 bzw. 367, mit HSETP2 cbuf 89 von 128 bzw. 117, mit HSETP2 imm 50 von 73 bzw. 71, mit TEX.B im LOD-Modus `LL` 76 von 103 bzw. 93. Paare ohne gepackte Halbpräzisions-Ergebnisse bestehen zu 100 % (159 von 159).

Beispielbilder (Referenz, Übersetzung, Differenz ×8) liegen unter `work/shaders/out/fidelity/` und gehören nicht ins Repo. Alle Zahlen stehen in `work/shaders/fidelity_report.json` (lokal).

### 11.3 Ursachen der Abweichungen

**1. Ryujinx rundet bei fp16 nicht (55 Paare, 52 davon nur im Fragment-Shader).** Unity-Shader nutzen auf der Switch `half`-Variablen; die Hardware rechnet HADD2/HMUL2/HFMA2 in fp16 und rundet jedes Ergebnis auf Halbpräzision. Der Ryujinx-Übersetzer entfernt das Pack/Unpack-Paar zwischen zwei Halb-Befehlen, die Referenz rechnet dort in fp32 ohne Rundung. Beleg:

- Am Paar 2801 (`UI/Blur`, einfach, eine Textur) steht in der Referenz `fma(_54, -9.0, _48)` in fp32, wo unsere Übersetzung nach fp16 rundet. Rundet man in einer Kopie der Referenz diese zehn Werte (`float(half(x))`), sinkt die größte Abweichung von 16 auf 1 Stufe.
- Der Schalter `--half-compat` bildet das Ryujinx-Verhalten nach (ein ungerundeter `float2`-Schatten je Register, das Halb-Befehle schreiben, `translate.c` `hstore()`). Damit bestehen 36 der 55 Paare, darunter bitgleiche.
- Alle 55 Paare mit Abweichung benutzen Halb-Befehle mit gepacktem Ergebnis (in Vertex oder Fragment); die 159 Paare ohne solche bestehen alle.

**Welche Seite ist „richtig“?** *Vermutet:* unsere (die Hardware rundet), aber es gibt keine Hardware-Referenz in diesem Test. Ryujinx ist eine Näherung, und auch `--half-compat` bildet sie nur grob nach (Ryujinx rundet an einigen Stellen doch, die Referenz enthält vereinzelt `half2(`). Für 1:1 gilt das Standardverhalten; der Treue-Test kann dafür keinen Beweis liefern. Ein Abgleich mit einem Referenzbild der Hardware oder eines Emulators mit fp16-Rundung steht aus (Teil 3).

**2. Reste nach `--half-compat` (19 Paare, 4,9 %).**

- 3 Paare (`Mitake/MitakeStandardBumpShader` 73 und 74, `Delphis/Character/Standard` 106): 5 bis 6 Pixel von 16.384 (0,04 %) springen zwischen 0 und 255 (chaotischer Pfad, Kantenpixel); der Rest des Bildes ist ≤ 1 Stufe.
- 15 Paare `Delphis/Map/Standard`: 61 oder 99 Pixel (0,4 bis 0,6 %) sind bei uns 0, in der Referenz farbig. **Per Bisektion** (Unterbrechen des Shaders nach Anweisung k und Ausgabe eines „irgendein Register ist NaN“-Flags) gilt am Paar 362: Die 61 abweichenden Pixel sind genau die Pixel, in denen unsere Übersetzung irgendwo NaN hat; das erste NaN entsteht in einer Kette aus Halb-Befehlen (`rsqrt` einer fp16-Summe, danach `inf * 0`). Das passt zu einem fp16-Überlauf bei den extremen synthetischen Werten, den die fp32-Referenz nicht hat. Nicht bewiesen, ob jede Instanz dieser Gruppe darauf beruht.
- Paar 2452 (`Map/Standard`): größte Abweichung 6, 43 Pixel; nicht analysiert.

**3. Nicht die Ursache:** Bindung, Registerbelegung, Interpolation und Clip-Raum. Die Texturschlüssel stimmen in 970 von 970 Stufen überein, die Mischvarianten zeigen keine Schnittstellenfehler, und alle 332 + 36 bestandenen Paare nutzen dieselben Bindungen. `noperspective`/`flat`/`centroid` kommen in den 500 Referenzen nicht vor und sind damit ungeprüft.

### 11.4 Grenzen des Tests

- Synthetische Eingaben: Extreme (NaN, Inf, Überlauf) treten häufiger auf als im Spiel. Ein bestandener Test belegt Gleichheit mit der Referenz für diese Eingaben, keine Fehlerfreiheit.
- Die Referenz ist Ryujinx (SPIR-V → spirv-cross → Metal), nicht die Hardware. Wo Ryujinx abweicht (fp16), kann sie nicht als Maß dienen.
- 98 von 500 Paaren sind nicht aussagekräftig; `Delphis/Map/Standard` (2.570 der 2.901 Einträge) ist in der Stichprobe mit 180 Paaren, davon 133 aussagekräftig, vertreten, die Verteilung seiner Varianten wurde nicht untersucht. Ein Lauf über alle 2.901 Paare dauert mit der Profilsuche mehrere Stunden und wurde nach etwa 290 Paaren abgebrochen (Zwischenstand dort: 160 bestanden von 186 aussagekräftigen bei `Map/Standard`).
- Eine Zeichnung, 2D-Texturen, `rgba8Unorm`, feste Sampler (kein Vergleichssampler, kein Rand), keine Tiefe/Stencil/Blend, keine Cube-/Array-/Shadow-Texturen, keine Speicherpuffer.
- Die Eingabeprofile sind geraten (welcher Cbuf-Bereich eine Matrix ist, kennt der Test nicht).

## 12. Offene Punkte

1. **fp16-Rundung gegen die Hardware prüfen** (11.3): Referenzbild vom Gerät oder aus einem Emulator, der in fp16 rundet; bis dahin Standardverhalten beibehalten.
2. **Reste der Gruppe 11.3 Nr. 2** auf Befehlsebene klären (Bisektion für die übrigen Paare, Mikrotest für HFMA2/HMUL2 mit Überlauf).
3. **Cube-, Array-, Shadow-Texturen und Speicherpuffer** im Harness ergänzen (vier Cube-Paare im Test, `FxSystem/Particle` braucht `vp_s0`).
4. **`noperspective`, `flat`, `centroid`** gegen die Referenz absichern (`noperspective_mask` wird im Übersetzer weiter nie gesetzt).
5. **Einzelbefehl-Mikrotests** (MUFU-Varianten, F2I-Rundung, SHF/BFE/PRMT/XMAD, FTZ/Denormale) und **Gegenprobe des Decoders**: Die Gesamtshader-Tests decken nur die Befehle ab, die im Korpus vorkommen und deren Ergebnis das Bild beeinflusst.
6. **Härtung** (Aufgabe 9 oben), **GLSL-Zweig** (TEX.B/`half_compat` nur MSL).
7. **Harness:** Ein Vertex-Shader ohne `[[stage_in]]` bringt den Renderer zum Absturz (`vertexAttributes!` ist `nil`); vorbestehend, nicht geändert.
8. **Dead-Code der Handle-Wörter** (Abschnitt 9) aus der MSL entfernen.

## 13. Reproduktion (Teil 2)

```sh
export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer
make -C shader_translator test                                   # 72 + 14 + 6 Prüfungen
swift build -c release --package-path scripts/shader_harness --scratch-path work/shaders/build
python3 -m unittest scripts/tests/test_shader_fidelity.py       # 24 Tests, synthetisch
PYTHONPATH=tools/pydeps python3 scripts/shader_fidelity.py index # einmalig: work/shaders/prog_blob.json
python3 scripts/shader_cache_extract.py                          # alle SPIR-V-Module nach work/shaders/spirv (203 MB)
python3 scripts/shader_fidelity.py run --count 500 --jobs 4      # ca. 10 Minuten, Bericht work/shaders/fidelity_report.json
python3 scripts/shader_fidelity.py run --only 2801 103           # einzelne Cache-Indizes
```

Der Lauf legt je Paar unter `work/shaders/fidelity/<index>/` Spezifikationen, MSL und die Eingaben des gewählten Profils ab (zusammen etwa 150 MB bei 500 Paaren) und Bilder unter `work/shaders/out/fidelity/` (etwa 6 MB).

## 14. Teil 3 (Vorschlag)

**Stand Teil 4 (2026-10-19):** HLSL-Pfad umgesetzt (`docs/shader-unity-integration.md`); das HLSL-Backend liest jetzt globalen Speicher über `ByteAddressBuffer mx_gmem` (180 Partikel-Blobs; 4.272 von 4.276 Blobs übersetzbar, offen: 4 Fragment-Blobs mit Subgroup-Shuffle) und macht registerindizierte cbuf-Zugriffe als `mx_cbr<k>` ersetzbar (Instancing). Der Texturindex der Maxwell-Tabelle entspricht dem Inventar-Feld `sampler`, nicht `index` (Abschnitt 4.1 dort). MSL-Option `--gmem-base`/`--gmem-size` für den Harness.

**Unity-Integration**

- Ausgabeform entscheiden (`referenz-las-shader.md`, Abschnitt 9): HLSL-Backend für ShaderLab oder MSL als natives Plugin. Die Ressourcenkarte ist so gebaut, dass beides sie nutzen kann.
- Konstantenpuffer benennen: cbuf 3 und höher gegen das Parameter-Layout der geparsten Shaderdaten (`UnityPerDraw`, `UnityPerCamera`, Material, Instancing) legen; Offsets in `staticMinOffset`/`staticEndOffset` zeigen, was gelesen wird. Compiler-Konstanten (cbuf 1) als `constant`-Array einbetten.
- Texturbindung: Tabelleneintrag `(textureWordOffset − 0x568) / 8` auf die Textur-Eigenschaft des Materials abbilden; Sampler aus den Unity-Sampler-Zuständen (Filter, Wrap, Anisotropie) statt der festen Test-Sampler.
- Y- und Tiefenkonventionen (`flip_y`, `depth_minus_one`) an Unity anpassen; die Pragmas oder Compile-Optionen aus Abschnitt 10 in Unitys Metal-Pipeline durchsetzen (oder die Wirkung prüfen).

**Varianten und Keywords**

- Zuordnung Programm → Blob-Hash (liegt lokal in `prog_blob.json`) in einen Build-Schritt übernehmen, Auswahl nach Unity-Keyword-Sätzen; 13.710 Programme → 4.276 Blobs → 2.859 Codes, Deduplizierung im Build. Der Test deckt je Cache-Eintrag eine Variante ab; die Verteilung innerhalb von `Delphis/Map/Standard` und `FxSystem/Particle` ist offen.

**Effekte**

- Partikel (`FxSystem/Particle`: Instanzdaten im Speicherpuffer), Cube-Texturen (Reflexion), Post-Effekte und GrabPass brauchen Harness-Erweiterungen und feste Zeitpunkte für den Bildvergleich.
- Treue-Test auf Zeitverläufe und mehrere Zeichnungen (Mehrpass, Tiefentest, Blending aus den geparsten Pass-Zuständen) ausdehnen.

**Absicherung**

- Offene Punkte 1 bis 8 aus Abschnitt 12.

## 15. Reproduktion (Teil 1)

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
