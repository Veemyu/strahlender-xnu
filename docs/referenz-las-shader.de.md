# Referenz: Shader-Pipeline von LASRecomp und Übernahmeplan (Stand 2026-10-18)

Eigene Analyse des lokalen Klons `research/LASRecomp` (gitignored, nur gelesen; Commit `09f8e5e`, einziger Commit, Autor „Peiikai“). Alle Aussagen sind in eigenen Worten; Zitate nur als Datei- und Funktionsnamen mit Zeilen. Nichts aus `research/` wurde ins Repo kopiert, nichts committet.
Markierung: **belegt** = im Code/Dokument/Messwert gelesen, *vermutet* = Schluss ohne Test.

**Stand der Freigabe:** Der Nutzer hat die Übernahme von LASRecomp-Code (MIT) ausdrücklich erlaubt. Dieses Dokument beschreibt deshalb zusätzlich einen Übernahmeplan (Abschnitt 8 bis 11). Das Kopieren und Committen erledigt der Hauptagent.

---

## 1. Wie kommen die Guest-Shader in die Runtime (belegt)

LASRecomp ist kein Emulator, sondern eine statische Rekompilation: Der Spielcode ruft NVN-Funktionen, die die Runtime selbst implementiert. Shader werden nicht aus Dateien gelesen, sondern aus dem Speicher des Spiels, sobald es sie an NVN übergibt.

| Schritt | Beleg | Befund |
|---|---|---|
| Programm setzen | `runtime/nvn/objects.c:565-599` (`set_shaders`, `nvnProgramSetShaders`, `…Ext`) | Eintrag je Stufe: 64-Bit-Adresse des Codes und Zeiger auf die Control-Section. Schrittweite 16 Byte (Ext: 24, mit Debug-Hash). |
| Stufe bestimmen | `objects.c:578-588` | Bits 10 bis 13 des ersten Worts des Programm-Headers (SPH, bei Code + 0x30): 1 Vertex, 5 Fragment, 4 Geometry, 2 Tess-Control, 3 Tess-Eval. Fehlt das Magic-Wort `0x12345678` am Codeanfang, gilt es als Compute. |
| Container | `translate.c:1927-1940`, `shader.h:97` | Blob = NVN-Kopf (0x30 Byte, beginnt mit `0x12345678`), SPH (0x50 Byte, Grafik), danach Maxwell-Code ab Offset 0x80. Compute: Code direkt am Blobanfang, kein SPH. Code in Vierergruppen zu 64 Bit: ein Scheduling-Wort, drei Instruktionen. |
| Control-Section | `objects.c:591-592`, `nvn.h:60-69`, `renderer.m:1346` | Dort liegen: Offset und Größe der „Compiler-Konstanten“ (`+0x700`, `+0x6FC`), bei Compute die Workgroup-Größe (`+0x748`). Die Compiler-Konstanten folgen dem Code im selben Blob und dienen zugleich als Obergrenze beim Instruktions-Scan. |
| Ausgabe-Register | `translate.c:1933-1936` | Aus dem SPH werden nur die Ausgabemasken gelesen (Farbziele `+0x48`, Tiefe `+0x4C` Bit 1). Interpolations- und Eingabemasken des SPH werden **nicht** gelesen; sie ergeben sich aus den Instruktionen (IPA) und aus `vs_out_mask` des Vertex-Shaders. |
| Konstantenpuffer | `renderer.m:610`, `renderer.m:1274-1313` (`bind_cbufs`) | Hardware-cbuf 0 = Treiberkonstanten (Storage-Buffer-Tabelle, Workgroup-Zahl), cbuf 1 = Compiler-Konstanten hinter dem Code, cbuf `k >= 3` = NVN-Uniform-Binding `k - 3` (`cbuf_base = 3`, per Umgebungsvariable änderbar). Puffer werden pro Draw in einen Ring kopiert (Snapshot). Maximal 18 cbufs (`shader.h:62-63`). |
| Texturen | `translate.c:451-480` (`tex_slot`), `renderer.m:1098-1103`, `1176-1180` | Der TEX-Befehl trägt einen 13-Bit-Index in die Handle-Tabelle; Byte-Offset `index*4`, Slot = `(Offset - 0x20) / 8`. Ein 64-Bit-Handle enthält 20 Bit Texturindex (TIC) und 12 Bit Sampler (TSC) und wird im Texturpool des Spiels nachgeschlagen. Maximal 31 Texturen je Shader. Der Typ (1D/2D/3D/Cube/Array/Shadow) ergibt sich aus dem Befehl (Zielbits), bei reinen Größenabfragen erst aus dem späteren Sample („weak“). |
| Attribute | `renderer.m:654-727`, `1613-1620`, `1830-1870` | Pro Vertex-Attribut wird nur die Art (Float/Int/UInt, `attr_kind`) in den Schlüssel übernommen; das Vertexformat selbst steckt im Metal-Vertex-Descriptor. Fragment-Eingänge: `vs_out_mask` des gerade verwendeten Vertex-Shaders. |
| Zustände | `renderer.m:1613-1620` | `ShaderKey` = Attributarten, Render-Target-Arten, `depth_minus_one`, `flip_y`, `flip_x`, `vs_out_mask`, `glsl`. Ein Programm wird je (Code-Adressen, Schlüssel) einmal übersetzt. |

**Folgerung (belegt):** Die Schnittstelle von `translate.c` ist schmal: Eingabe = Blobzeiger + Obergrenze + Stufe + `ShaderKey`, Ausgabe = `ShaderInfo` mit Quelltext und Metadaten. Sie ist von der restlichen Runtime unabhängig (siehe 8).

## 2. Der Übersetzer `runtime/nvn/maxwell/translate.c` (2165 Zeilen, 126 KB) und `shader.h` (103 Zeilen)

### 2.1 Struktur (belegt)

- **Decoder:** Eine lange `if/else`-Kette `emit_insn` (`translate.c:824-1624`), jede Instruktion über Muster `OPM(Wert, Maske)` auf das 64-Bit-Wort. Halbpräzisions-Befehle getrennt in `emit_half` (`:332`), Texturen in `emit_tex`/`emit_texs` (`:753`, `:672`). Keine Zwischendarstellung (kein SSA, keine Kontrollflussgraph-Analyse).
- **Registerabbildung:** Alle 255 Register als `uint rN`, Prädikate P0..P6 als `bool pN`, `PT` = true, RZ = `0u`. Fließkomma über `as_type<float>` (MSL) bzw. `as_f/as_u` (GLSL). Carry-/Zero-/Sign-Flags als `cc/ccz/ccs` (nur wenn benutzt).
- **Prädikate:** Jede Instruktion mit Guard wird in `if (pN) { … }` verpackt (`:824-840`).
- **Kontrollfluss:** Ohne Sprünge linearer Code in `do { } while(false)`. Mit Sprüngen eine Zustandsmaschine `switch (pc)` in einer Schleife (Wächter 100000 Durchläufe), mit expliziten Stapeln für SSY, PBK, PCNT (je 16 Einträge). Unterstützt: BRA, SSY, PBK, PCNT, SYNC, BRK, CONT, BRX (Sprungtabelle, dann jedes Wort ein Ziel), EXIT, KIL. Das ist robust, aber nicht strukturiert; es führt zu langem, langsam zu kompilierendem Zielcode.
- **Interpolation:** IPA-Modi pass/multiply/constant (`:874-900`). Konstant → `flat`. „pass“ liefert attr/w, „multiply“ multipliziert mit einem Register (`attr_load`, `:224-276`). Das Feld `noperspective_mask` ist deklariert, wird aber im Code **nie gesetzt** (nur gelesen, `:69`, `:1849`, `:2038`): `noperspective` wird also nie erzeugt. Zentroid-/Sample-Flags der IPA werden nicht ausgewertet. Für Unity ohne MSAA (render-treue.md) *vermutlich* unkritisch.
- **Ausgaben:** Vertex: `out.pos`, `out.v<i>`, Punktgröße. Fragment: Farbziele aus dem SPH (`omap_target`), je Ziel Float/Int/UInt, optional `depth`. Epilog im Vertex-Shader: `flip_y`, `flip_x`, `depth_minus_one` (z = (z+w)/2, NVN-Tiefe −1..1 → Metal 0..1) (MSL `:2113-2115`, GLSL `:1886-1888`).
- **Zielsprachen:** Zwei. MSL (Metal) ist die Primärausgabe. GLSL 460 für Vulkan entsteht aus demselben MSL-artigen Text durch ein token-basiertes Umschreiben (`glsl_rewrite`, `:1640`, Prelude `:1724`) plus eigene Zweige für Texturen, Speicher und Einstieg; die GLSL-Schnittstelle (Bindings, Locations) steht im Kopf von `shader.h:1-27`. SPIR-V entsteht erst zur Laufzeit per shaderc in `runtime/nvn/vulkan/shaders.c` (**nicht** im Übersetzer). HLSL gibt es nicht.
- **Laufzeit-Zusätze, spielspezifisch (belegt):** „Tint“-Epilog für das Farbziel 0 (`:1817`, `:2070`, für markierte Töpfe im Spiel), `flip_x` (Spiegelmodus), Auflösungsskalierung `rscale` (Puffer 18, beeinflusst Fragmentkoordinaten und Texel-Fetches), `maxwell_dbg_*`-Hooks, `getenv("BDSP_NO_DISCARD")` und `BDSP_SAVE_MSL` (`:847`, `:1984`). Eine IPA-Sonderbehandlung für den Nebel eines Spiel-Levels steht im Kommentar bei `:258-262`; der Code dazu ist allgemein.

### 2.2 Abdeckung

**Unterstützt (belegt, aus den Kommentaren/Mustern in `emit_insn`, `emit_half`):**

| Gruppe | Instruktionen |
|---|---|
| Fließkomma | FADD, FADD32I, FMUL, FMUL32I (mit Skalierung), FFMA, FFMA32I, FMNMX, FSET, FSETP, FCMP, MUFU (COS, SIN, EX2, LG2, RCP, RSQ, SQRT), RRO (als No-op), F2F, F2I, I2F, FSWZADD |
| Halb (SM53) | HADD2, HMUL2, HFMA2, HSET2, HSETP2 (Registerformen für SET/SETP, alle Formen für ADD/MUL/FMA), Merge-/Swizzle-Modi |
| Ganzzahl | IADD (+CC/X), IADD32I, IADD3 (+CC/X), ISCADD, ISCADD32I, ISET, ISETP, ICMP, IMNMX, SHL, SHR, SHF, LOP, LOP32I, LOP3, BFE, BFI, XMAD (alle vier Formen), IMUL, IMUL32I, FLO, POPC, I2I, PRMT, SEL, MOV, MOV32I |
| Prädikate/Flags | PSETP, PSET, R2P, P2R (inkl. CC), CSETP (nur Z/S) |
| Speicher | LD c[…] (LDC, auch mit Register-Index), LDL/STL (Local, 1 KB), LDG/STG (Global, über Guest-Heap-Puffer), IPA, LD/ST Attribut (nur konstante Adresse) |
| Textur | TEX (1D/2D/3D/Cube, Array, Shadow, LOD-Modi, Offset), TEXS, TLDS (Teilmenge der Info-Werte), TXQ (nur Dimension/Mip-Anzahl) |
| Sonstiges | S2R (Y-Richtung, Thread-/Block-Id), SHFL, BAR, KIL, DEPBAR/NOP/MEMBAR (ignoriert) |

**Nicht unterstützt (belegt: `fail(...)`-Stellen und fehlende Muster):**

| Lücke | Beleg | Für BDSP relevant? |
|---|---|---|
| TLD (volle Form), TLD4/TLD4S (Gather), TXD (explizite Ableitungen), TMML | kein Muster in `emit_insn`; Ergebnis „unknown instruction“ (`:1624`) | *vermutet*: einzeln möglich (Gather/Fetch in Post-Effekten), zu messen |
| Bildzugriffe SULD/SUST, Atomics ATOM/RED/ATOMS, Shared-Memory LDS/STS | kein Muster | gering (nur 5 Compute-Programme im Ryujinx-Cache) |
| TEX.B (bindless) | `:760` „bindless tex“ | *vermutet* nein (Unity bindet Texturen klassisch) |
| TXQ andere Typen als Dimension | `:954` | möglich |
| MUFU RCP64H/RSQ64H und weitere Funktionen | `:967` | gering |
| IPA mit Index, LD a[] mit Register-Index | `:878`, `:892`, `:226` | gering außerhalb Geometry/Tess |
| BFE.BREV, PRMT-Sondermodi, R2P.CC, CSET | `:1246`, `:1377`, `:1566`, `:1618` | PRMT-Modi *vermutet* selten, zu messen |
| TLDS/TEXS: nicht aufgeführte Info-Werte | `:645`, `:665`, `:726`, `:746` | möglich |
| Weitere Maxwell-Befehle ohne Muster (z. B. LEA, CS2R, PIXLD, VOTE, FCHK, DADD/DMUL/DFMA, VMAD, ISBERD) | nur aus dem Fehlen abgeleitet | *vermutet* teils selten; Messung nötig |
| Geometry-/Tessellation-Stufen | Stufen existieren als Konstanten (`shader.h:33`), `attr_load`/`attr_store` liefern dort Nullen/Kommentare (`:277-282`) | nach Ryujinx-Cache **nein** (nur Vertex+Fragment+5 Compute, `shader-audio-machbarkeit.md:44`) |
| Speicherfehler-Gefahr | `cbuf_ref` schreibt `cbuf_size[idx]` und `cbuf_need[idx]` ohne Obergrenzen-Prüfung (`:126`, `:909`); Arrays haben 18 Einträge | zu härten, falls Eingaben nicht vertrauenswürdig sind |

**Bekannte Abweichungen/Eigenheiten (belegt bzw. *vermutet*):**
- Das Metal-Fast-Math ist bei den Laufzeit-Optionen nicht abgeschaltet (`renderer.m:862`, `:834`: nur `preserveInvariance` für den Vertex-Shader, Fragment-Optionen leer). Für Treue 1:1 **müssen** wir `fastMathEnabled=NO` bzw. entsprechende Modi prüfen (*vermutet*, nicht getestet).
- FTZ- und Rundungsflags der Befehle werden nicht ausgewertet; Maxwell-Verhalten bei Denormalen kann abweichen (*vermutet*).
- RRO ist ein No-op und MUFU.SIN/COS rechnet im Bogenmaß; ob das mit dem Shadercode von glslc stimmt (Faktor 1/2π im Shader), ist **ein Testfall** (*vermutet* korrekt, weil das Spiel läuft).
- Die Halb-Zusammenführung musste umgeschrieben werden, weil der Metal-Compiler eine Maskenform auf M1 falsch übersetzte (Kommentar `:2014-2017`); GLSL rechnet Halbwerte absichtlich per Bitoperationen (Kommentar `:1758-1762`). Das zeigt: Compiler-Eigenheiten sind real und müssen mit Differenztests gefangen werden.
- Unsicher bei „unknown instruction“: Der Übersetzer bricht beim **ersten** Fehler ab (`fail`, `:84-91`); für ein Histogramm muss er „alle unbekannten“ sammeln (siehe 11).

### 2.3 Tests und Validierung (belegt)

| Werkzeug | Was es prüft | Was es **nicht** prüft |
|---|---|---|
| `tools/test_translate.c`/`.sh` | Fuzz: synthetisiert Programme aus allen Mustern in `translate.c`; (1) MSL muss byteidentisch zu einem Referenzstand des Übersetzers sein (Regression), (2) GLSL muss mit shaderc kompilieren und von SPIRV-Tools validiert werden. | Keine numerische Wahrheit gegen Hardware oder Ryujinx. |
| `tools/test_shaders.c`/`.m` | Zerlegt gedumpte Shader (`BDSP_DUMP_SHADERS`), übersetzt, kompiliert mit `xcrun metal` bzw. `newLibraryWithSource`. | Nur Kompilierbarkeit. |
| `tools/test_vk_pipelines.c`/`.sh` | Gefuzzte Programme → GLSL → echte Vulkan-Pipelines unter Validation-Layer. | Windows-/Vulkan-spezifisch; keine Bildprüfung. |
| `runtime/ui/shader_tour.mm` (70 Zeilen) | Kein Test: ein „Shader-Rundgang“. Warpt durch alle Warp-Punkte des Spiels, damit alle Shader beim Spieler einmal übersetzt und kompiliert werden und im Metal-Plattencache landen. | — |
| `tools/test_lift.py`, `test_simd.py` | Differenztests des **CPU**-Lifters gegen Unicorn, nicht der Shader. | — |

Treue wird bei LASRecomp also über das Spielen und Screenshots geprüft (`tools/shot.sh`, `tools/frames.sh`, Debug-Hook `BDSP_DBG_FS`, der ein Register an einer Programmstelle als Grauwert ausgibt). Einen Vergleich gegen ein Referenzergebnis (Ryujinx, Hardware) habe ich im Klon **nicht gefunden**.

### 2.4 Caching und Laufzeitkosten (belegt)

- Ein Programm wird beim ersten Draw übersetzt (`renderer.m:878-950`), MSL im Verzeichnis `cache/shaders/` abgelegt (`:814-826`). Beim Start werden alle dort liegenden Quellen im Hintergrund kompiliert (`shader_cache_warm`, `:827-856`), damit Metals eigener Plattencache gefüllt ist.
- Kompilierung läuft asynchron; Draws mit noch nicht bereitem Programm werden übersprungen (`:951-960`). Der Quelltext-Kommentar nennt etwa 40 ms je Erstkompilierung (`:807`, `:951`), danach etwa 0,1 ms. Das ist eine Angabe des Projekts, nicht von mir gemessen.
- Diese Laufzeitkompilierung ist für uns **keine Option**: Auf iPadOS ist `newLibraryWithSource` zwar verfügbar (Metal-Compiler im System), aber für uns ist Build-Zeit-Übersetzung vorgesehen (Kernziel, kein Spielcode in der App, reproduzierbar). Außerdem laufen wir in Unity, das seine Shader selbst kompiliert (siehe 9).

## 3. Metal-Renderer (`renderer.m` 2701 Zeilen/148 KB, `metal.m` 1191 Zeilen/67 KB)

| Thema | Befund (belegt) | Relevanz für uns |
|---|---|---|
| Pipeline-Zustand | Pro Draw Hash über Programm, Zielformate, Blend, Vertexformate/-streams, Kanalmaske, Alpha-to-Coverage (`renderer.m:1582-1605`, `:1767`), danach `MTLRenderPipelineState` asynchron (`:1784-1815`). | Gering: Unity erledigt das selbst. |
| Blend/Depth/Stencil | Tabellen NVN → Metal: `blend_factor` (`:729`), `blend_op`, `compare_fn` (`:768`), `stencil_op` (`:781`). Zustände kommen aus NVN-Befehlen, nicht aus ShaderLab. | Nützlich als Vergleichstabelle für die Zuordnung der im Bundle geparsten Render-States (Unity-Enum → Metal), sonst gering. |
| cbuf-Bindung | siehe 1 (cbuf 0/1/≥3, Ringpuffer-Snapshot). | Die cbuf-Nummern sind das Bindeglied zu Unity-Konstantenpuffern (siehe 9). |
| Sampler | `sampler_for` (`:959-1020`): Filter, Mip-Filter, Wrap-Modi inkl. Border/MirrorClamp, LOD-Grenzen, Anisotropie, Vergleichssampler. Der LOD-Bias der Switch-Sampler wird **nicht** übernommen. | Vergleichstabelle für Sampler-Treue. |
| Clip-Space/Y-Flip | `flip_y` bei unterem linken Fensterursprung, `depth_minus_one` bei NVN-Tiefenmodus −1..1; Front-Face-Winding wird bei `flip_y` gedreht (`renderer.m:1613-1616`, Cull `:1868`). Vulkan nutzt eine Viewport mit negativer Höhe (`shader.h:21-23`). | Unity verwaltet Projektion selbst; wir müssen Konventionen der **Original-Matrix** in Unity-Shadern wahren (siehe 10). |
| Gamma/sRGB | sRGB-Formate werden gemappt (`metal.m:78-140`). Die Bildschirmausgabe samplet sRGB-Ziele über einen Nicht-sRGB-View, „zeigt, was das Spiel geschrieben hat“ (`metal.m:650-661`). Kopien können roh erfolgen (`BDSP_COPY_RAW_SRGB`, `renderer.m:2223`). | Passt zu unserer Gamma-Vorgabe: Das Spiel rechnet in Gamma, ohne Zwischen-Linearisierung. In Unity 6.3 Farbraum Gamma + keine sRGB-Ziele erzwingen. |
| SMAA | SMAA 1x (MIT, `third_party/smaa`, 1,2 MB) über die SMAA-Portierungsmakros, Kompilierung je neuer Bildgröße (`metal.m:700-815`). | **Nicht relevant**: Das Original hat kein Anti-Aliasing (kein MSAA, render-treue.md). |
| MetalFX | Räumlicher Skalierer, „Perceptual“-Modus (`metal.m:663-698`). Dynamische Auflösung `output_scale.c` (93 Zeilen). | **Nicht relevant** für 1:1; optional später als Qualitätsoption, nicht Teil der Treue. |
| Rückkopplung | Wird eine Textur gelesen, die zugleich Ziel ist, wird eine Kopie angelegt (`resolve_feedback`, `:1113`). | Hinweis: Original-Shader lesen u. U. ihren Tiefenpuffer; in Unity über GrabPass/Kopie lösen (*vermutet*). |
| Spielspezifisch | Widescreen-Umbau, Spiegelmodus, Topf-Tint, Texturpatches (`texpatch.c`, 1043 Zeilen), Button-Prompts. | Nicht übernehmen. |

## 4. Link's Awakening vs. BDSP

| Aspekt | LAS (belegt aus Klon, README) | BDSP (belegt aus unseren Docs/Messungen) |
|---|---|---|
| Engine | Eigenengine von Grezzo (Sekundärquelle, `docs/recomp-referenzen.md`) | Unity 2019.4.27f1, IL2CPP (`docs/extraktion.md`) |
| Shader-Herkunft | Fertige NVN-Programme (glslc-Binärdaten) im Spiel selbst; Spielcode ruft `nvnProgramSetShaders` | Unity kompiliert ShaderLab zur Build-Zeit zu NVN-Programmen und legt sie in Bundle-Shader-Objekten ab (Plattform 19). Zur Laufzeit gibt es dort keinen Quelltext (`shader-audio-machbarkeit.md:21-28`). |
| Konstantenpuffer | Eigene Layouts des Spiels (per Reverse Engineering) | Unity-Layouts (`UnityPerDraw`, `UnityPerCamera`, …) mit Namen in den geparsten Shaderdaten (*vermutet* anhand der dort gefundenen Uniform-Namen wie `unity_MatrixVP`, `_MainTex_ST`, `shader-audio-machbarkeit.md:27`). |
| Varianten | Wenige, vom Spiel gewählt | Keyword-Varianten: In `work/shaders/mapping.json` (unser Skript `scripts/shader_map.py`): 13.710 Programme (6.878 Vertex, 6.832 Fragment), 8.332 verschiedene Code-Hashes, 0 bis 17 Keywords je Programm, Blobgröße 2.516 bis 12.300 Byte, Median 6.316 Byte. |
| Nvn-Laufzeit im Spiel | Spiel linkt NVN-Treiber des Systems; Runtime ersetzt ihn | `sdk`, `subsdk0` liegen im ExeFS (`docs/extraktion.md:17`). **Offen:** Ob dort ein Laufzeit-Shaderkompilierer (z. B. glslc-Bibliothek) liegt, ist **nicht untersucht**. *Vermutet:* nein, weil Unity die Shader offline als Binärcode liefert und nur über `nvnProgramSetShaders` bindet; `sdk` ist *vermutlich* die Nintendo-SDK-Bibliothek ohne Shader-Compiler. Prüfung: Zeichenketten/Symbole in `sdk`/`subsdk0` (nur Namen notieren). |
| letsgo-recomp | Baut auf LASRecomp auf (README: „built on the runtime and recompiler of LAS Recomp“), NVN auf **Vulkan**, Maxwell→SPIR-V zur Laufzeit, SMAA, Shader-Cache auf Platte (SPIR-V und Pipeline-Cache). Laut README Windows-only. | Unser früheres Doc `recomp-referenzen.md` nannte Let's Go „keine Unity-Spiele“; die Websuche stützt: Game-Freak-Eigenengine mit YEBIS-3-Middleware (Sekundärquelle, nicht direkt geprüft). Beide Zielspiele sind also Nicht-Unity; **BDSP wäre der erste Unity-Fall**. |

**Wichtigster Unterschied (belegt):** Unser Container ist bekannt. `scripts/shader_map.py` zeigt: Jedes Bundle-Programm beginnt mit dem Magic `0x0C07513C`, danach Version, Keyword-Liste (Anzahl bei `+0x18`), ein Control-Kopf mit Magic `0x98761234` (bei `Kopf+0x14`), dann der GLSLC-Datenteil mit `0x12345678` für den Programmstart; SPH = Position des Magics + 0x30 (`scripts/shader_map.py:parse_nvn`). Das ist exakt das Eingabeformat von `maxwell_translate` (Blob ab `0x12345678`, SPH bei `+0x30`, Code bei `+0x80`). Von den 1.388 Guest-Einträgen des Ryujinx-Caches (401 Vertex, 982 Fragment, 5 Compute) stimmen 1.288 byteweise mit Bundle-Programmen überein (`mapping.json`: `guestMatchedFull`). Das ist die Brücke für Treuetests. Ein separates `docs/shader-inventar.md` existiert noch nicht (nicht vorhanden, geprüft).

## 5. Übertragbarkeit (Antworten auf die Fragen 5a bis 5d)

**(a) Maxwell→MSL/SPIR-V als Build-Schritt:** *Technisch plausibel*, weil Eingabeformat und Stufen passen (V/F, kein Geometry/Tess). Offen ist die Abdeckung, siehe 11. Der Übersetzer erzeugt aber Registermaschinen-Code, keinen lesbaren ShaderLab-Quelltext (siehe 9 zu den Folgen).

**(b) Was wir selbst schreiben müssten:** Container-Parser (liegt als Python-Skript vor, in C/CLI nachzubauen), Zuordnung cbuf-Offsets/Texturslots ↔ Unity-Namen aus den geparsten Daten, ShaderLab-/HLSL-Hülle, Keyword-Auswahl, Fehlende Instruktionen, Differenztest-Anbindung, Entkopplung der Spielspezifika.

**(c) MIT-Lizenz (keine Rechtsberatung):** Die Lizenz erlaubt Nutzung, Änderung und Weitergabe, **wenn der Copyright-Hinweis „Copyright (c) 2026 Peiikai“ und der Lizenztext in allen Kopien oder wesentlichen Teilen erhalten bleiben**. Die Datei `LICENSE` nimmt Nintendo-Eigentum und die Drittkomponenten in `third_party/` ausdrücklich aus. Hinweise zu Qualität/Provenienz (nüchtern): Das README gibt an, dass der Code „fast ausschließlich“ mit einer KI (Claude über Claude Code) geschrieben und von einem Menschen gelenkt, getestet und geprüft wurde (`README.md:4-8`); der Klon hat nur einen Commit, eine Historie zur Entstehung gibt es also nicht. Der Übersetzer zitiert in Kommentaren Ryujinx (Feldlayouts HADD2/HMUL2/HFMA2/XMAD/LDC, `translate.c:355`, `386`, `900`, `1265`) und das README nennt envytools; Ryujinx wird im README **nicht** als Quelle aufgeführt (Suche ohne Treffer). Die Frage, ob und welche Teile aus Fremdwerken (Ryujinx, envytools) in Struktur oder Tabellen eingeflossen sind, lässt sich aus dem Klon nicht beantworten; wir sollten beim Weiterentwickeln Ryujinx und envytools in den Hinweisen mit nennen. Das ist eine Risikoeinschätzung, keine Wertung.

**(d) Treuprüfung 1:1:** Referenz = Ryujinx-SPIR-V (und der Guest-Code derselben Programme). Siehe 10.

## 6. Empfehlung (8 Sätze, Optionen A, B, C)

1. **Option B (LASRecomp-Übersetzer als Basis, MIT, mit Anpassungen)** ist mit der Freigabe die schnellste Route zu einem Build-Schritt, der ohne Ryujinx-Cache auskommt, weil die Eingabeformate exakt passen (Abschnitt 4).
2. **Option A (eigener Übersetzer)** wäre sauberer (SSA, strukturierter Kontrollfluss, direkt HLSL), kostet aber Monate und müsste dieselben Opcode-Details neu herleiten; sinnvoll erst, wenn B an Treue oder Laufzeit scheitert.
3. **Option C (Ryujinx-Referenz lokal, Shader händisch portieren)** bleibt für die Treueprüfung zwingend, taugt aber nicht als einziger Weg, weil der Cache nicht jedem Nutzer vorliegt und 13.710 Programme nicht von Hand zu portieren sind.
4. Empfohlen: **B als Kern plus C als Prüfstand**, A nur für gezielte Teile (z. B. strukturierter Kontrollfluss), falls nötig.
5. Zuerst die **Abdeckung messen** (Abschnitt 11), bevor Code übernommen wird; sie entscheidet, ob B überhaupt trägt.
6. Den Übersetzer als eigenständiges C-Werkzeug mit klarer Schnittstelle abtrennen, alle LAS-Spezifika entfernen und Lizenz/Hinweise mitführen (Abschnitt 8).
7. Die Ausgabe zunächst als MSL für den Prüfstand erzeugen und danach eine HLSL-/ShaderLab-Hülle für Unity bauen; ob Unity-Metal die erzeugte Struktur treu übersetzt, ist ein Risiko (Abschnitt 9).
8. Entscheidend bleiben Texturslot- und cbuf-Zuordnung zu Unity-Namen und die Differenztests gegen die Ryujinx-SPIR-V-Referenz; ohne sie kein 1:1-Nachweis.

---

## 7. Hinweis zu Repo-Regeln (belegt)

`.gitignore` schließt die Ordner `tools/`, `research/`, `work/`, `Ryujinx/`, `nsp/` aus. Ein Zielordner `tools/shader_translator/` wäre damit **nicht versioniert**. Entweder wird der Übersetzer außerhalb von `tools/` abgelegt (Vorschlag: `shader_translator/` im Repo-Wurzelverzeichnis) oder die Ignore-Regel wird gezielt aufgehoben (`!tools/shader_translator/`). Die Entscheidung liegt beim Hauptagenten.

## 8. Übernahmeplan: Was als Basis taugt und was nicht

Größen gemessen (Bytes, `wc -c`/`du`).

### 8.1 Geeignet (Basis)

| Datei | Größe | Verwendung |
|---|---|---|
| `runtime/nvn/maxwell/translate.c` | 126.050 B / 2.165 Z. | Kern. Nur libc (`math.h`, `stdio.h`, `stdlib.h`, `string.h`, `stdarg.h`; `malloc.h` nur Windows), **keine** Abhängigkeit zur Runtime (belegt: `#include`-Liste `:15-23`). |
| `runtime/nvn/maxwell/shader.h` | 6.765 B / 103 Z. | Öffentliche Schnittstelle (`ShaderKey`, `ShaderInfo`, `maxwell_translate`, `maxwell_free`). |
| `tools/test_translate.c` + `.sh` | 15.157 B + 1.941 B | Fuzz-/Regressionstest; Muster werden aus `translate.c` gelesen. Das Skript braucht einen Referenzstand (`git show $REF:…`) und shaderc/SPIRV-Tools; muss an unser Repo angepasst werden. |
| `tools/test_shaders.c` / `.m` | 1.230 B / 2.032 B | Dumps → MSL → Metal kompilieren; als Vorlage für unseren Abdeckungs-/Kompiliertest (Eingabeformat anpassen). |
| `tools/test_vk_pipelines.*` | 16.514 B + 891 B | Nur bei Vulkan-Ausgabe; auf macOS *vermutet* nicht benötigt. |
| `runtime/nvn/vulkan/shaders.c` | 24.622 B | Ideen für GLSL→SPIR-V und Reflexion, falls wir eine SPIR-V-Ausgabe brauchen; nicht übernehmen, nur lesen. |
| Ideen aus `renderer.m`/`metal.m` | 147.860 B / 66.506 B | **Nicht kopieren.** Lesen als Referenz: Tabellen für Blend/Compare/Stencil/Sampler, cbuf-Konventionen (`cbuf_base = 3`), Textur-Handle-Auflösung, Compile-Optionen. |

### 8.2 Nicht übernehmen

| Bereich | Größe | Grund |
|---|---|---|
| `third_party/LAS-Randomizer` | 864 KB | LAS-Randomizer, eigene Lizenz(en), Spielinhalt-nah |
| `third_party/imgui` | 7,2 MB | UI-Bibliothek, nicht nötig |
| `third_party/fonts`, `fonts/` | 660 KB / 4 KB | Schriften, Spielbezug |
| `third_party/smaa` + `runtime/nvn/smaa_data.c` | 1,2 MB | SMAA gibt es im Original nicht |
| `runtime/ui/` | 392 KB | Menüs, Cheats, Randomizer, Shader-Rundgang |
| `runtime/hle/`, `runtime/services/` | 356 KB / 120 KB | Switch-OS-Ersatz und Spielpatches |
| `runtime/*.c` (Kernel, Loader, Dispatch, …) | 2,1 MB gesamt `runtime/` | Rekompilations-Laufzeit |
| `tools/gen.py`, `lifter.py`, `passes.py`, `patches.py`, … | `tools/` 1,5 MB | ARM64→C-Rekompilierer, hier nicht relevant (BDSP-Weg ist Unity-Neuaufbau, `architektur-entscheidung.md`) |
| `runtime/nvn/{astc,texpatch,tegra,objects,cmdbuf,formats}.c` | 147.412 B zusammen | NVN-Objektmodell, Textur-Entschlüsselung (für Unity nicht nötig, Unity dekodiert Texturen selbst), Spielpatches |
| `docs/`, `docs/icon` | 1,6 MB | LAS-spezifisch |

## 9. Zielstruktur und Entkopplung

Vorschlag (Ort siehe Abschnitt 7):

```
shader_translator/
  LICENSE-LASRecomp          (Lizenztext unverändert, inkl. Copyright (c) 2026 Peiikai)
  THIRD_PARTY_NOTICES.md     (LASRecomp MIT; Hinweis auf Ryujinx, envytools als Quellen der Feldlayouts/Dokumentation)
  README.md                  (Herkunft, Änderungen gegenüber dem Original, KI-Hinweis des Originals)
  include/maxwell.h          (≙ shader.h, bereinigt)
  src/translate.c           (aus translate.c)
  src/container.c           (Unity-NVN-Container: Magic 0x0C07513C / 0x98761234 / 0x12345678)
  src/main.c                (CLI)
  tests/…                   (Fuzz, Abdeckung, Differenztest)
Makefile                    (clang, macOS)
```

**Schnittstelle:**
- Eingabe: Bundle-Programmblob (oder bereits ausgeschnittener Maxwell-Blob ab `0x12345678`), Stufe (aus Control-Kopf `Kopf+4`, in `shader_map.py` „stage“), optional `cbuf`-Info und `ShaderKey`.
- Ausgabe: Quelltext (MSL; optional HLSL/GLSL) plus Metadaten (benutzte cbufs und -Größen, Texturslots mit Typ/Shadow, Attribut-/Varyingmasken, Ausgabemaske, Flags).
- CLI-Beispiel: `shader_translator --stage vs --target msl --in prog.bin --out prog.metal --info prog.json`. Als Bibliothek derselbe Ablauf über `maxwell_translate`.

**Entkopplungs-Aufgaben (konkret):**
1. `translate.c` ist bereits frei von Runtime-Headern (siehe 8.1). Zu entfernen: Tint-Epilog (`:1817`, `:2070`) samt `uses_tint`, `flip_x`, `rscale`-Pfade (`uses_rscale`, `RSC2`, `rsc()`), `maxwell_dbg_*`-Variablen und -Hooks, `getenv`-Aufrufe (`:847`, `:1984`), globale `maxwell_gmem_base/size` (als Parameter oder entfernen, da V/F-Shader kein Global Memory brauchen sollten).
2. Globale statische Puffer (`RSC2` mit `static char bufs[4][1024]`, `:526`) und `alloca`-Makros thread-sicher machen (für parallele Übersetzung von 13.710 Programmen).
3. Eingabeprüfung: Obergrenzen für cbuf-Index (`cbuf_ref`), `reg_used` (Register > 255), Blobgröße.
4. Container-Parser aus `scripts/shader_map.py` nach C übertragen und Stufe/Keywords/Konstantenoffset liefern. **Zu prüfen:** ob `Control+0x700/0x6FC` (Offset/Größe der Compiler-Konstanten) im Unity-Container an gleicher Stelle stehen; sonst Obergrenze über „Ende des Codes“ (`:1964-1971`).
5. Ausgabe-Backends: MSL ist vorhanden. Für Unity eine **HLSL**-Ausgabe analog `glsl_rewrite` (Token-Umschreiber), aber mit `asuint/asfloat`, `mad`, `rsqrt`, `[loop]`-Schalter. **Risiko (*vermutet*):** implizite Ableitungen (`Sample`) innerhalb der `switch(pc)`-Zustandsmaschine; HLSL-/Metal-Compiler können sie als nicht-uniformen Kontrollfluss ablehnen oder falsch behandeln. Lösung: zuerst Kontrollfluss strukturieren (Dominatoren, if/else, Schleifen), oder LOD-Berechnung herausziehen.
6. Reproduzierbarkeit: Der Build-Schritt liest nur lokale Bundles (Kernziel Schritt 4 „Shader durch eigene ersetzen“) und erzeugt Ausgabe unter `work/` (nicht im Repo).

**Unity-spezifische Frage zur Ausgabeform (zu entscheiden):** (i) Übersetzte Programme als ShaderLab-`HLSLPROGRAM` einbinden: Unity kompiliert sie dann für Metal selbst (Fast-Math, Reihenfolge der Operationen und `precise` entscheiden über Treue); (ii) MSL direkt über ein natives Metal-Plugin: höchste Treue, aber Unity-Beleuchtung/Schatten/Pipeline müssten wir umgehen. Ich empfehle zunächst (i) für die Machbarkeit und (ii) nur als Prüfstand.

## 10. Weiterentwicklungsaufgaben für BDSP (grob priorisiert)

| Prio | Aufgabe | Begründung / Nachweis |
|---|---|---|
| 1 | **Abdeckung messen** (siehe 11) und alle unbekannten Opcodes sammeln statt beim ersten abzubrechen. | `fail` bricht beim ersten Fehler ab (`:89-95`). |
| 2 | Container-Parser in C, Programmextraktion für alle 13.710 Programme, Parallelisierung. | Aus `shader_map.py` bekannt. |
| 3 | Fehlende Instruktionen ergänzen, nach Häufigkeit: zuerst solche in Fragment-Shadern (TLD, TLD4, TXD, weitere TEXS/TLDS-Infos, PRMT-Modi, MUFU-Varianten). | Siehe 2.2. |
| 4 | **Treue-Test gegen Ryujinx-SPIR-V** im vorhandenen Harness `scripts/shader_harness`: gleiche Eingaben (Vertexdaten, cbuf, Texturen) in Referenz (SPIR-V→MSL) und unseren Übersetzer, pixel-/wertweise vergleichen. 1.288 Programme mit Gegenstück (Abschnitt 4). | Referenz laut `render-treue.md`. |
| 5 | Numerik: Fast-Math aus, FTZ/Denormale, MUFU-Genauigkeit (RCP, RSQ, SIN, COS), Rundung F2I/F2F, Halbpräzision; je ein Mikrotest pro Befehl gegen die Referenz. | Siehe 2.2 (Abweichungen). |
| 6 | **Unity-Konstantenpuffer:** Abbildung cbuf-Nr. und Offset auf Namen (`UnityPerDraw`, `UnityPerCamera`, Material-Properties) aus den geparsten Shaderdaten (`scripts/shader_inventory.py` liest die Parameter-Layouts). Texturslot → Property-Name. Prüfen, ob `cbuf_base = 3` auch für Unity-glslc gilt (*vermutet*, da derselbe Compiler). | Kernaufwand laut `render-treue.md` („Offen“). |
| 7 | **Keyword-Varianten:** Jedes Programm trägt seine Keywords (bis 17). Zuordnung Variante → Material-Keywords in Unity; Umgang mit 8.332 eindeutigen Codes statt 13.710 Programmen (Deduplikation per Hash). | `mapping.json`. |
| 8 | Strukturierter Kontrollfluss statt `switch(pc)` (Übersetzungszeit, Treue von Ableitungen, HLSL-Kompatibilität). | Siehe 9. |
| 9 | Compute (5 Programme, *vermutet* Skinning/Effekt) prüfen; Geometry/Tessellation nur wenn Messung welche zeigt (nach Cache: keine). | `shader-audio-machbarkeit.md:44`. |
| 10 | Absicherung: Fuzz gegen Abstürze, Eingabegrenzen, Tests in CI-ähnlichem Skript. | 2.2 „Speicherfehler-Gefahr“. |

## 11. Messung der Instruktionsabdeckung für BDSP

**Ziel:** Für jedes der 13.710 Bundle-Programme (8.332 eindeutige Codes) feststellen, welche Maxwell-Instruktionen vorkommen und welche `translate.c` nicht kennt.

Vorgehen (alles lokal, Ausgabe nur Zahlen/Namen unter `work/`, keine Binärdaten im Repo):
1. **Extrahieren:** Mit der bekannten Container-Struktur (Abschnitt 4) je Programm den Maxwell-Blob ab `0x12345678` ausschneiden (Skript `scripts/shader_map.py` liefert Programm-Id, Stufe, Keyword-Liste, `codeHash`). Nach `codeHash` deduplizieren.
2. **Histogramm A (Instruktion):** Für jede Instruktion (jedes Wort, dessen Index nicht durch 4 teilbar ist) die Opcode-Klasse über die Muster `OPM(Wert,Maske)` aus `translate.c` bestimmen (die Muster lassen sich wie in `test_translate.c:load_patterns` aus dem Quelltext lesen). Zählung getrennt nach Stufe: Wörter pro Opcode, Programme pro Opcode, Anteil Programme, die **vollständig** durch bekannte Opcodes abgedeckt sind.
3. **Histogramm B (Unbekannte):** Alle Wörter ohne Treffer nach den obersten 12 Bit (und Opcode-Familie) gruppieren, mit Beispiel-Programm-Id und Stelle; dann gegen die Maxwell-Opcode-Tabelle (envytools/Ryujinx-Dokumentation) benennen. Dazu `fail` im Übersetzer so erweitern, dass es sammelt statt abzubrechen.
4. **Histogramm C (Teilfunktionen):** `fail`-Meldungen (z. B. „mufu 6“, „prmt mode“, „texs info N“) je Meldung zählen; sie decken Opcodes ab, die erkannt, aber nur teilweise unterstützt sind.
5. **Kompilierbarkeit:** Alle übersetzbaren Programme per Metal-Laufzeitcompiler (`newLibraryWithSource`) prüfen (Vorlage `tools/test_shaders.m`) und Zeit/Quelltextgröße pro Programm messen.
6. **Gewichtung:** Ergebnis zusätzlich nach Shader-Namen (`perShader` in `mapping.json`) und danach, ob die Variante im Ryujinx-Cache vorkommt (gespielte Pfade zuerst).
7. **Zweitkorpus:** Die 1.388 Ryujinx-Guest-Programme (davon 1.288 mit Bundle-Gegenstück) als Kreuzprüfung, ob die Messung auf den Bundles dasselbe liefert.

**Messgrößen (Abnahmekriterium):** (a) Anteil Programme mit 0 unbekannten Opcodes, (b) Rangliste der fehlenden Opcodes nach Programmzahl, (c) Anteil kompilierbarer MSL-Ausgaben, (d) für die 1.288 abgestimmten Programme: Bildvergleich gegen die Ryujinx-SPIR-V-Referenz mit Toleranzvorgabe (zu definieren).

**Offene Punkte:** Layout und Offset der Compiler-Konstanten im Unity-Container; Bedeutung einzelner Felder des Control-Kopfes; ob `sdk`/`subsdk0` einen Shader-Compiler enthalten; ob Unity-Metal die erzeugte HLSL treu übersetzt; Messwerte zur Abdeckung (bisher keine).
