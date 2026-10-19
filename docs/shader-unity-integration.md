# Übersetzte Shader in Unity 6.3: HLSL-Wrapper (Pfad A) gegen natives Metal-Plugin (Pfad B)

Stand 2026-10-19, Todo `ap-shader-unity` (Machbarkeit und Prototyp). Frage: Wie kommen die mit `maxwell2msl` übersetzten Switch-Shader (`docs/shader-translator.md`) so nach Unity 6.3 (Built-in-Pipeline, Gamma, Metal, arm64), dass das Bild dem Referenzrender entspricht (Hartvorgabe aus `docs/render-treue.md`)?

Markierung: **belegt** = gemessen oder im Quelltext gelesen, *Schätzung/vermutet* = Schluss ohne Test. Alle Testdaten sind synthetisch (Schachbrett, Verlauf, Eckpunkte aus dem Code); gerendert wurden nur von uns erzeugte Shader, nie ein Original-Bundle-Shader.

## 1. Ergebnis in Zahlen

| Frage | Ergebnis |
|---|---|
| Lässt sich HLSL aus dem Übersetzer erzeugen? | **Ja.** `maxwell2msl --lang hlsl` übersetzt 4.092 von 4.276 Blobs (95,7 %: 503 von 683 Vertex, 3.589 von 3.593 Fragment) in 18 s. Die 184 Ausfälle: 180 Vertex-Blobs mit globalem Speicher (Partikel), 4 Fragment-Blobs mit Subgroup-Shuffle. |
| Nimmt Unity die Ausgabe an? | **Ja.** Zwei überlappende Stichproben (183 und 272 Varianten aus den 6.820, alle 64 Shader) kompilierten in Unity 6.3 für Metal ohne Fehler (Mittel 260 bis 340 ms je Shader). |
| Stimmt das Bild? | **Ja, bitgleich.** 7 Fälle, Unity gegen Harness (unsere MSL, Metal Safe-Math): größte Abweichung **0 von 255** in 13 von 13 Vergleichen (7 × `array`, 6 × `named`), auch mit Perspektiv-Matrix, mit und ohne die Pragmas für exakte Arithmetik. Ziel war ≤ 1/255. |
| Verändert Unitys Pfad die Rechengenauigkeit? | **Ja, wenn man ihn lässt.** Mikrotests: Standardeinstellung stimmt nur in 11 von 16 Fällen mit Metal Safe-Math überein (FMA-Verschmelzung, Division, `sin`/`cos`, `isnan`). Mit `#pragma disable_fastmath` und `#pragma skip_optimizations metal` sind es **16 von 16**. Der Wrapper schreibt beide Pragmas standardmäßig. |
| Wie viel der 6.820 Varianten verpackt der Wrapper heute? | **6.804 (99,8 %)** (vorher 3.521 = 51,6 %): Instancing (1.288) und Partikel/Speicherpuffer (1.994) sind jetzt verpackbar; offen bleiben 16 Varianten mit Subgroup-Shuffle (`Mitake/MitakeStandardPetrify`). Abschnitt 13. |
| Empfehlung | **Pfad A (HLSL/ShaderLab).** Pfad B (Metal-Plugin) nur als Reserve für Dinge, die HLSL nicht ausdrücken kann; bisher ist keine gefunden. Abschnitt 8. |

## 2. Aufbau der Lösung

```
Switch-Blob ──maxwell2msl --lang hlsl──▶ HLSL-Snippet (mx_vs / mx_fs, ohne Semantik)
Inventar (Properties, Tags, Zustand, Block-Layouts) ──┐
                                                      ├─ scripts/shader_wrap.py ─▶ .shader + .wrap.json ──▶ Unity (FXC → HLSLcc → MSL)
Ressourcenkarte (--info), Compiler-Konstanten (--cbuf1)┘
```

| Teil | Datei | Aufgabe |
|---|---|---|
| HLSL-Backend | `shader_translator/translate.c` (`hlsl_rewrite`, `hlsl_prelude`, `hlsl_finish`, `hlsl_sample`), `shader.h` | Befehlsrumpf in HLSL, Vertrag (Strukturen, Namen) im Kopfkommentar von `shader.h` |
| Wrapper-Generator | `scripts/shader_wrap.py` (eigener Code) | setzt Properties, Tags, Zustand, Block-Layouts und das Snippet in eine `.shader`-Datei ein |
| Tests | `scripts/tests/test_shader_wrap.py` (29), `shader_translator/tests/` (88 C-Prüfungen, 15 CLI-Tests) | synthetisch, ohne Spielinhalt und ohne Unity |
| Labor | `work/unity-shader-lab/` (Wegwerf-Projekt), `work/shaders/unity-lab/*.py` | Messung; nicht im Repo (`work/` ist ignoriert) |

## 3. HLSL-Backend: Aufwand und Umsetzung

**Bewertung vorab (aus dem Quelltext):** Der Übersetzer erzeugt den Befehlsrumpf in einer festen MSL-Schreibweise (Register als `uint`, Gleitkommawerte über `as_type<float>`) und der GLSL-Zweig stellt schon vor, wie man daraus per Token-Umschreibung einen zweiten Dialekt gewinnt. Ein dritter Dialekt kostet daher keine neue Befehlsübersetzung, sondern: eine Umschreibtabelle, ein Prelude, die Stellen mit anderer Struktur (Texturen, 16-Bit-Gleitkomma, 64-Bit-Ganzzahlen, Größenabfragen, Kopf und Einstiegspunkt) und die Prüfung. Umgesetzt: 429 geänderte Zeilen in `translate.c`, davon etwa 250 für den neuen Zweig; die MSL- und GLSL-Ausgabe ist byteidentisch geblieben (500 Blobs × 3 Optionssätze gegen die Vorversion verglichen).

| Konstrukt | Lösung in HLSL (Shader Model 5) | Status |
|---|---|---|
| Typen | Register `uint`, `asfloat`/`asuint`/`asint`; `float2/3/4`, `int*`, `uint*` unverändert; **kein** `half`/`min16float`, sondern `f16tof32`/`f32tof16` | belegt (Unity setzt beide Funktionen in dieselben `as_type<half2>`-Befehle um wie unsere MSL) |
| Vektoren, Swizzles, `float4(...)`-Konstruktoren | unverändert | belegt |
| Textur lesen | `Sample`, `SampleLevel`, `SampleBias`, `SampleCmp`/`SampleCmpLevelZero`, `Load`; Offsets aus Registern über Koordinatenverschiebung (HLSL erlaubt nur Literale) | 2D belegt (Unity-Render); Cube, Array, 3D, Vergleichssampler nur übersetzt, nicht in Unity gerendert |
| Größenabfrage (TXQ) | `GetDimensions` in `tsize<i>()`/`tlevels<i>()` | übersetzt, in Unity nicht gerendert |
| Ableitungen | implizit über `Sample`; FSWZADD mit Lane aus der Pixelposition; **SHFL fehlt** (kein Quad-Austausch in SM5) | 4 Blobs scheitern |
| `discard` | `discard;` | belegt (Fall `p2757`, Alphatest) |
| Interpolation | `nointerpolation` im Wrapper aus `--info`; `noperspective` wird vom Übersetzer nie gesetzt | `flat` nur im Testtext geprüft |
| Ganzzahl/Bits | Bitfelder, `mulhi`, `clz`, `prmt`, Trichterverschiebung und Übertrag (IADD mit CC) ohne 64-Bit-Typ im Prelude | Übertrag und SHF nur im Testtext geprüft |
| Prädikate | `bool p0..p6` | belegt |
| Sprünge/Schleifen | `switch (pc)` scheitert in FXC (`continue` im `switch`; „l-value expected“ bei Zuweisung an die Schaltvariable): jetzt Kette `if (pc == N)`, Durchfall setzt `pc` | belegt (Fall `p2804`, Schleife mit 6 Durchläufen bitgleich) |
| `isnan` | als Bittest (`mx_isnan`): FXC faltet `isnan(x)` und `x != x` sonst weg | belegt (Mikrotest) |
| Globaler Speicher (LDG/STG) | `ByteAddressBuffer mx_gmem` (Lesen; Speichern und mehrere Puffer abgelehnt), Abschnitt 13.2 | 180 Blobs übersetzt, in Unity kompiliert, Bild nicht verglichen |
| Compute, `half_compat`, Auflösungsskalierung, Punktkoordinate | abgelehnt | – |

**Vertrag** (Kopfkommentar `shader.h`): Strukturen ohne Semantik (`MxVIn`, `MxVOut`, `MxFIn`, `MxFOut`), Funktionen `mx_vs(MxVIn, vid, iid)` und `mx_fs(MxFIn, front_facing)`; Konstantenpuffer k als `mx_cb<k>[Zeile][Komponente]` (uint4-Feld), Texturen `mx_t<i>`/`mx_s<i>`. Ohne `#define MX_EXTERNAL_RESOURCES` deklariert das Snippet alles selbst (`cbuffer`, `register`), mit dem Schalter stellt der Wrapper die Namen. Fragment-Position: `pos.w` ist **1/w** (wie Maxwell und Metal).

## 4. Der ShaderLab-Wrapper (`scripts/shader_wrap.py`)

```sh
python3 scripts/shader_wrap.py 'Custom/ProceduralPlane/Footprint' --bundle shaders --out work/unity-shader-lab/Assets/XnuGen/foot.shader
python3 scripts/shader_wrap.py 'UI/Custom' --bundle shaders --keywords UNITY_UI_ALPHACLIP --out .../ui.shader --mode array
```

Eine Datei = ein SubShader, ein Pass, **eine feste Keyword-Variante** (die Keyword-Menge wählt die Programme von Vertex und Fragment aus dem Inventar). Aus dem Inventar kommen `Properties` (Typ, Standardwert, Flags, Attribute), SubShader-Tags, Pass-Name und -Tags sowie der Zustand: `Blend`/`BlendOp` (auch je Ziel und mit Material-Eigenschaften wie `[_SrcBlend]`), `ColorMask`, `ZTest` (`Disabled` → `Always`), `ZWrite`, `Cull`, `Offset`, `AlphaToMask`, `ZClip`, `Stencil` (Ref, Masken, Vergleich/Operationen, getrennt nach Vorder- und Rückseite). Ausgabe daneben: `.wrap.json` (Zuordnung für Tests und Massenfertigung, Warnungen).

### 4.1 Abbildung der Konstantenpuffer

Die Hardware-Puffer der Switch heißen im Maxwell-Code `c[k][Byte-Offset]`; der Übersetzer macht daraus `cb<k>[Offset/16][(Offset/4) % 4]`.

| Hardware-cbuf | Inhalt | Abbildung im Wrapper |
|---|---|---|
| 0 | Treiberdaten (gelesen in 180 Blobs, Inhalt unbekannt) | `static uint4`-Feld mit Nullen, Warnung im Manifest |
| 1 | Compiler-Konstanten: die Bytes hinter dem Code des Blobs (auf 0x100 aufgerundet, `--cbuf1`) | `static const uint4 mxf_cb1[n] = {…}` als Literal (Zahl der Zeilen aus dem Blob, höchstens 64 KB) |
| 2 | Handle-Tabellen der bindlosen Texturen: Texturwort `0x568 + 8·i`, Samplerwort `0x168 + 8·i` | Nullen (der Shader liest die Wörter, benutzt sie aber nicht); die Textur kommt über den Namen: Tabellenindex `i` ↔ `textures[].sampler` des Inventars (nicht `index`, siehe unten) ↔ Material-Eigenschaft |
| **3 + k** | Unity-Block mit Bindungsnummer `k` (`cbBindings`): `VGlobals` (Vertex, meist `k = 1`), `PGlobals` (Fragment, `k = 0`), `UnityInstancing_PerDraw*` | Modus `named`: je Wort der Wert des Unity-Uniforms, das dort liegt (Name, Offset, Komponenten aus `constantBuffers` des Inventars). Modus `array`: ein `float4`-Feld `mxav_cb<n>` (Vertex) / `mxaf_cb<n>` (Fragment), das ein Test exakt füllt |

Regeln (**belegt** an der Vertex-Arithmetik von `Mitake/MitakeDepthOnlyShader` und durch bitgleiche Bilder):

- Wort = Byte-Offset / 4. Füllbytes im Block (Packregeln) sind 0.
- **Matrizen liegen spaltenweise:** Zeile `r` des Blocks ist Spalte `r` der HLSL-Matrix, also Wort `4·c + r` = `M[r][c]` (`unity_ObjectToWorld` bei Offset 0: Zeilen 0 bis 3, Verschiebung in Zeile 3).
- Arrays: jedes Element beginnt auf 16 Byte (`float x[4]` belegt 16 Wörter, `float3x3` drei Zeilen).
- Namen, die nicht in den `Properties` stehen, sind Spiel-Globals (`_CloudParam`, `_PokeLightColor`, …): Unity bindet sie nach Namen aus `Shader.SetGlobalVector/Float`, der Wrapper deklariert sie nur. Engine-Werte (`unity_*`, `_Time`, `_WorldSpaceCameraPos`, `_ProjectionParams`, …) setzt Unity selbst; `<Textur>_TexelSize` setzt Unity ebenfalls selbst, auch für global gesetzte Texturen (belegt: Fall `p2801`).
- Vertex- und Fragmentstufe haben getrennte Puffer gleicher Nummer. Der Wrapper trennt sie mit stufenbezogenen Makros (`#define mx_cb3 mxv_cb3` … `#undef`), ebenso `mx_t<i>`, `mx_s<i>`, `tsize<i>`.
- Puffer, die der Shader liest, aber das Inventar nicht kennt (z. B. Vertex-Bindung 0, wenn `VGlobals` auf 1 liegt), werden mit Nullen belegt und als Warnung gemeldet. Puffer mit Register-Index (Instancing, cbuf 4/5): Abschnitt 13.1.
- **Textur-Tabellenindex (Korrektur 2026-10-19):** Der Texturwort-Index `i` im Maxwell-Code gehört zum Inventar-Eintrag mit `sampler == i` (Feld `m_SamplerIndex`), das Samplerwort zum Feld `index`. Bis dahin las der Wrapper `textures[].index`; bei 18.451 von 31.319 Texturabrufen der 14.342 Programme (Eintrag mit `index ≠ sampler`) wäre damit die falsche Textur gebunden worden (Dimensionen fielen nur bei `POINT_COOKIE` auf). Gegenprobe über alle Programme: die Zuordnung über `sampler` ist in 31.319 von 31.319 Fällen auch in der Gegenrichtung (Samplerwort = `index`) stimmig (`work/shaders/unity-lab/texmap_check.py`; Test `test_texture_table_uses_sampler_field`). Die Treue-Fälle der Abschnitte 6 und 13 verwenden Texturen mit gleichem Inhalt je Slot und hätten den Fehler nicht gezeigt.

### 4.2 Eingaben, Ausgaben, Texturen

- **Vertexeingaben:** `inputChannels[].source` ist Unitys `VertexAttribute` (0 Position, 1 Normal, 2 Tangent, 3 Color, 4+i TexCoord i), `target` der Attribut-Ort `a<target>` des Snippets. Der Wrapper schreibt `float4 a<ort> : <Semantik>`.
- **Varyings:** Vertex-Ausgabe `v<i>` ↔ `TEXCOORD<i>`; nur Orte, die der Fragment-Shader liest (Maske `--vs-out-mask` aus der Vertex-Ausgabe). `flat` → `nointerpolation`.
- **Fragmentausgabe:** `SV_Target<rt>`, optional `SV_Depth`. `SV_IsFrontFace` → `front_facing`.
- **`SV_Position.w`:** Unitys HLSLcc kehrt Metals `1/w` um, Unity liefert also `w`. Der Wrapper übergibt `1.0 / pos.w` an das Snippet (belegt: Sonde mit `w = 2`: Metal 0,5, Unity 2,0). In den Testfällen kürzt sich der Wert wegen IPA-Multiplikation und Kehrwert weg; Shader, die `pos.w` direkt nutzen, brauchen die Korrektur.
- **Texturen:** `Texture2D<float4> _MainTex; SamplerState sampler_MainTex;` (Name = Material-Eigenschaft; Unity nimmt Filter, Wiederholung und Anisotropie aus der Textur). Vergleichssampler: `SamplerComparisonState` (nicht gerendert).

## 5. Labor

Wegwerf-Projekt `work/unity-shader-lab` (Template 3D, Built-in, Unity 6000.3.26f1 arm64, Metal, **Gamma**, Editor stumm geschaltet). Zweiter Editor: ungefähr 1,1 GB Hauptspeicher plus 0,2 GB Shader-Compiler. Gesteuert nur über `unity command … --project-path work/unity-shader-lab` (Haupteditor `unity/` nicht berührt).

Aufbau eines Falls: 6 Eckpunkte (zwei Dreiecke), synthetische Konstantenpuffer, 64×64-Textur (Schachbrett mit Alpha oder Verlauf, linear, ohne Mips, `clamp`) → 256×256-`ARGB32`-RenderTexture (`CommandBuffer.DrawMesh`, Matrizen auf Identität gesetzt) → PNG; dieselben Eingaben im Harness (`scripts/shader_harness`, Quelle = unsere MSL, `mathMode = .safe`) → `scripts/shader_compare.py`. Konstantenpuffer-Bytes und Eckpunkte sind in beiden Läufen dieselben Float-Werte.

**Befunde zu Unitys Konventionen** (alle belegt; wichtig beim Einsatz mit echten Kameras):

| Befund | Folge |
|---|---|
| `SetViewProjectionMatrices(I, I)` ergibt `unity_MatrixVP` = Y gespiegelt, Z → (w − z)/2, `_ProjectionParams.x = −1` (Rendern in eine Textur, umgekehrtes Z) | Im Modus `named` stimmen Matrizen nur, wenn die Gegenseite dieselbe Matrix bekommt (so gemessen). Ob die Switch-Shader dieselbe Konvention erwarten wie Unitys Metal-Matrizen, entscheidet erst ein Vergleich mit einem echten Referenzbild (Abschnitt 10). |
| Zeichnet man Dreiecke, die in NDC (y oben) gegen den Uhrzeigersinn laufen, in eine RenderTexture, gelten sie in Unity als Vorderseite (Unity kehrt die Orientierung für Texturen um); im Harness (Metal, `frontFace cw`) wären sie Rückseite | Test mit `Cull Back` braucht `frontFace ccw` im Harness |
| Unity legt `[[position, invariant]]` für die Vertexposition selbst fest (aus dem erzeugten MSL gelesen) | Tiefen-Vorpass mit EQUAL-Test bleibt konsistent |
| Unity erzeugt für `f32tof16`/`f16tof32` `as_type<uint>(half2(x, 0.0))` / `as_type<half2>(u).x`, dieselben Befehle wie unsere MSL | fp16-Rundung (Rundung auf nächsten Gleichstand) wie im Übersetzer |

Das von Unity erzeugte MSL liegt im Klartext in `Library/ShaderCache/shader/<name>/…/*.bin` und lässt sich mit `strings` lesen (so wurden FMA, Pragmas und fp16 geprüft).

## 6. Treue-Messung

### 6.1 Fälle (Unity gegen Harness, 256×256, RGBA8)

Die Pair-Nummern sind Cache-Indizes (`work/shaders/mapping.json`). Das dritte Beispiel des Harness (Index 136) ließ sich nicht verwenden: für ihn gibt es im Bundle nur die Vertex-Stufe (`nur_eine_stufe`); ersetzt durch Fälle mit `discard` und mit Schleifen.

| Fall | Shader, Pass | Prüft | `array` | `named` |
|---|---|---|---|---|
| `p68` | `Custom/ProceduralPlane/Footprint` | Beispiel des Harness; Rotation, `min`, Textur, Material- und Global-Uniforms | 0 | 0 |
| `p2741` | `Mitake/MitakeDepthOnlyShader` (mit `ColorMask RGBA` überschrieben) | Beispiel des Harness; zwei 4×4-Matrizen, `Cull Back` | 0 | 0 |
| `p2803` | `Custom/EffectCopyTexture` | Textur kopieren, IPA mit `pos.w` | 0 | 0 |
| `p3` | `Delphis/Map/Additive` | zwei Texturen (eine global: `_CameraDepthTexture`), Blend `SrcAlpha One` | 0 | übersprungen (Engine-Werte `_ProjectionParams`, `_ZBufferParams`, `unity_MatrixV`) |
| `p2801` | `UI/Blur` (Pass 3) | Halbpräzision (HFMA2/HMUL2), globale Textur, `_TexelSize` | 0 | 0 |
| `p2757` | `UI/Custom`, `UNITY_UI_ALPHACLIP` | `discard`, Alpha 0,5/1,0 im Schachbrett | 0 | 0 |
| `p2804` | `Dpr/PostEffect/RadualBlur` | Schleife (`pc`-Kette), `_RadialBlurNumSamples` = 6 | 0 | 0 |

Spalten: größte Abweichung je Kanal (von 255). Zusätzlich im Modus `array`: Perspektiv-Matrix (`w = 1,5 + 0,4·y`) → 0 in allen 7; Shader **ohne** die Pragmas für exakte Arithmetik → 0 in allen 7 (die Fälle sind auf 8 Bit unempfindlich, die Mikrotests unten zeigen die Unterschiede). Voraussetzung der Gleichheit: gleiche GPU (Apple M1 Pro) und gleiche Metal-Compiler-Version; andere GPUs können bei Funktionen wie `sin` im letzten Bit abweichen (Abschnitt 10).

### 6.2 Steuerung der Rechengenauigkeit in Unity

16 Mikrotests (`work/shaders/unity-lab/run_math.py`), Eingaben über ein Uniform-Feld, Ausgabe als vier Bytes der Float-Bits. Referenz: Metal mit `math_mode(safe)` und `fp contract(off)` (so übersetzt unser MSL) und Metal mit Fast-Math (Standard). Vergleich ist bitweise.

| Variante | gleich wie Metal safe | gleich wie Metal fast | Auffälligkeiten |
|---|---|---|---|
| Standard | 11 | 16 | `a*b+c` verschmolzen (`b2800000` statt 0), `7/3` = `40155556` (angenähert), `sin(1000)`, `cos(1000)` angenähert |
| `#pragma disable_fastmath` | 14 | 13 | Division und `sin`/`cos` exakt, **FMA-Verschmelzung bleibt** (FXC bildet `a*b+c` als `mad`, HLSLcc setzt `fma`) |
| `#pragma skip_optimizations metal` | 11 | 16 | wie Standard (Metal verschmilzt weiter) |
| **beide Pragmas** | **16** | 11 | exakt wie unser MSL |
| `precise` auf den Zwischenwerten | 11 | 16 | verhindert nur das `mad` |
| `disable_fastmath` + `precise` | 16 | 11 | gleichwertig, bei eingeschalteter FXC-Optimierung |

Bedeutung: `mad(a,b,c)` bleibt in allen Varianten eine echte FMA (`b2800000`); so soll der Maxwell-Befehl FFMA wirken. Das Pragma `disable_fastmath` ist laut Unity-Handbuch für Metal gedacht („Enable precise IEEE 754 rules involving NaN handling. This currently only affects the Metal platform.“); gemessen schaltet es auch Divisions- und Funktionsnäherungen ab. Einen Spieler- oder Grafikeinstellungs-Schalter dafür haben wir nicht gefunden (*vermutet:* es gibt keinen); das Pragma gilt je Shader. **Standard des Wrappers:** beide Pragmas (`--fast-math` lässt sie weg). Offener Preis: `skip_optimizations` schaltet FXC aus (größerer Zwischencode; die Kosten zur Laufzeit wurden nicht gemessen). Verfeinerung: FADD/FMUL als `precise float`-Zwischenwerte erzeugen und nur `disable_fastmath` setzen (im Mikrotest gleichwertig).

## 7. Pfad B: Metal-Plugin (nur Analyse)

Idee: Unity liefert nur Meshes, Texturen und Konstanten; ein natives Plugin zeichnet mit eigenen Metal-Pipelines aus unserer MSL.

| Baustein | Was Unity bietet | Quelle |
|---|---|---|
| Plugin-Haken | `UnityRenderingExtEvent`; über `GL.IssuePluginEvent` oder `CommandBuffer.IssuePluginEventAndData` im Rendering-Thread; Plugin-Name muss mit `GfxPlugin` beginnen, um vor dem Gerät geladen zu werden | Handbuch „Native plug-in API for graphics and rendering“, `docs.unity3d.com/6000.3/Documentation/Manual/low-level-native-plugin-rendering-extensions.html` |
| Metal-Zugriff | `IUnityGraphicsMetalV2`: `MetalDevice`, `CommandQueue`, `CurrentCommandBuffer`, `CurrentCommandEncoder`, `EndCurrentCommandEncoder` (eigenen Encoder anlegen, Unitys vorher beenden und eigenen vor der Rückgabe beenden), `CurrentRenderPassDescriptor`, `TextureFromRenderBuffer` | `PluginAPI/IUnityGraphicsMetal.h` der Editor-Installation (gelesen) |
| Mesh, Textur | `Mesh.GetNativeVertexBufferPtr` (`id<MTLBuffer>`, Layout abhängig von Kompression, Aufruf synchronisiert den Rendering-Thread), `GetNativeIndexBufferPtr`, `Texture.GetNativeTexturePtr` | `docs.unity3d.com/6000.3/Documentation/ScriptReference/Mesh.GetNativeVertexBufferPtr.html` |
| Vor dem Zeichnen | `kUnityRenderingExtEventBeforeDrawCall` liefert nur die gebundenen Shader als `void*` (plattformabhängig), **kein** Austauschen | `PluginAPI/IUnityRenderingExtensions.h` (gelesen) |
| Shader-Compiler-Zugriff | `IUnityShaderCompilerAccess`: **nur D3D11** | Handbuch „Native plug-in API for shader compiler“ |

| Aspekt | Einschätzung für Pfad B |
|---|---|
| Aufwand | Eigenes Objective-C++-Plugin (MTLLibrary aus unserer MSL, Pipelinezustände aus dem Inventar), Übergabe von Matrizen, Material- und Global-Werten aus C# je Zeichnung, Mesh- und Texturzeiger, Kamera-/Ziel-Zustand. *Schätzung:* ein Mehrfaches von Pfad A (Wochen statt Tage), dazu ein Betriebsmittel-Kreis (Lebensdauer von Buffern/Texturen, Neuaufbau bei Gerätewechsel). |
| Schatten, Lichtpässe | Unitys eigene Pässe (ShadowCaster, ForwardAdd, Tiefenvorpass, Schattenmaske) kennen unsere Pipelines nicht; jeder Pass müsste im Plugin nachgebildet werden, inklusive Schattenkarten und Lichtschleifen. In Pfad A übernimmt Unity das über Tags und Keywords. |
| Instancing | Instanzdaten müsste das Plugin selbst bereitstellen (Unity-Arrays gibt es nur in Unitys Pipelines). |
| Stereo, Post-Effekte, Grab | Eigene Behandlung für Stereo-Ziele und `_GrabTexture`/Kameratiefe; Unity-Befehlspuffer-Reihenfolge muss stimmen (eigener Encoder). |
| Editor-Vorschau | Das Plugin läuft im macOS-Editor nur mit Metal; Szenenansicht, Materialvorschau und Prefab-Vorschau zeichnen Unity-Shader, nicht das Plugin. |
| iOS | Plugin statisch gelinkt (`__Internal`). Offline kompilierte `.metallib` sind für iOS der übliche Weg; Kompilierung aus MSL-Quelltext zur Laufzeit ist über die Metal-API möglich (*vermutet:* Apple-Richtlinien erlauben das, nicht geprüft). Ein JIT im Sinn von erzeugtem CPU-Code ist nicht beteiligt. |
| Vorteil | Metal-Compileroptionen (`mathMode`, `fp contract`) sind direkt wählbar; keine FXC-/HLSLcc-Stufe. In Pfad A erreicht man dasselbe Ergebnis per Pragma (Abschnitt 6.2). |

**Schluss:** Pfad A scheitert nicht (Abschnitt 6), daher kein Prototyp für B.

## 8. Empfehlung

**Pfad A, mit ShaderLab-Wrappern aus dem Wrapper-Generator, Pragmas für exakte Arithmetik als Standard.** Begründung in Zahlen:

| Kriterium | Pfad A (gemessen) | Pfad B (Analyse) |
|---|---|---|
| Treue | 13 von 13 Vergleichen bitgleich; 16 von 16 Mikrotests mit Pragmas | prinzipiell gleich (dieselbe MSL), nicht erprobt |
| Abdeckung heute | 95,7 % der Blobs, 51,6 % der Varianten verpackt, zwei Stichproben (183 und 272 Varianten) in Unity kompiliert, 0 Fehler | 100 % der MSL, aber jede Unity-Funktion (Licht, Schatten, Instancing) nachzubauen |
| Unity-Funktionen | Tags, Keywords, Instancing-Makros, Lichter, Schatten, Editor-Vorschau, Builds laufen über Unity | müssen im Plugin nachgebaut werden |
| Restaufwand | drei benannte Lücken (Abschnitt 9), *Schätzung:* je einige Arbeitstage; danach Massenfertigung und Messung am echten Referenzbild | *Schätzung:* ≥ 6 Wochen und danach dauerhafte Pflege |

**Hybrid** nur, falls ein Baustein sich in HLSL nicht abbilden lässt. Kandidat wäre die Partikel-Gruppe (globaler Speicher), doch `ByteAddressBuffer` reicht dafür voraussichtlich (Unity unterstützt Puffer in Vertex-Shadern auf Metal; *vermutet*, nicht getestet).

## 9. Schritte für die Massenfertigung (4.276 Blobs, 64 Shader)

Zahlen: 14.342 Programme → 4.276 eindeutige Blobs → 6.820 Varianten (SubShader 0, Normal-Pässe, gleiche Keyword-Menge in Vertex und Fragment) in 74 Pässen. 58 % der Varianten sind `FxSystem/Particle` (3.988, 102 Keywords), 38 % `Delphis/Map/Standard` (2.570, 17 Keywords); die übrigen 62 Shader haben zusammen 262 Varianten.

1. **Variantentabelle:** (Shader, Pass, Keyword-Menge) → Blob-Hashes (`prog_blob.json`, `mapping.json`); Wrapper je Variante (rund 60 Varianten je Sekunde in einem Prozess: alle 6.820 in unter zwei Minuten gemessen).
2. **Keywords:** Unitys Engine setzt Keywords je Zeichnung (Lichtart, Lightprobes, Instancing …). Die Einzelvariante eines Passes ist deshalb nur der Baustein; für den Einsatz entsteht je Pass **ein** Pass-Block mit `#pragma multi_compile`/`multi_compile_local` (Gruppen aus den Keyword-Mengen abgeleitet: Keywords, die nie zusammen vorkommen, bilden eine Gruppe) und einer `#if`-Kette, die den Rumpf der passenden Variante wählt. Fallstrick: Unity erlaubt höchstens 64 lokale Keywords je Shader; `FxSystem/Particle` hat 102, dort bleibt es bei einem Shader je Keyword-Menge (oder einer Aufteilung nach Gruppen). Gestrichen werden nur Kombinationen, die das Original nie erzeugt hat (`#pragma skip_variants`, Variantensammlungen aus den Bundles).
3. **Ausschuss in drei Gruppen beheben:** (a) Instancing und (b) globaler Speicher: erledigt, Abschnitt 13.1/13.2; (c) FSWZADD/SHFL-Ableitungen durch `ddx`/`ddy` ersetzen (16 Varianten): offen, Abschnitt 13.4.
4. **Material-Zuordnung:** Material-Keywords und Eigenschaften aus den Bundles der Spielmaterialien lesen (nicht Teil dieses Auftrags).
5. **Prüfung in Stufen:** (i) Kompilierung aller erzeugten Shader in Unity (Mittel 260 bis 340 ms je Shader: 6.820 Varianten ≈ 30 bis 40 Minuten, *Schätzung* linear); (ii) Treue-Test aus `docs/shader-translator.md` Abschnitt 11 auf Unity-Seite ausdehnen: dieselben 500 Paare, Harness-Bild gegen Unity-Bild (Modus `array`), Schwelle ≤ 1/255; (iii) Pixelvergleich an echten Szenen gegen Referenzbilder.
6. **Pragmas:** `disable_fastmath` und `skip_optimizations metal` bleiben Standard; Verfeinerung auf `precise`-Zwischenwerte nach Laufzeitmessung.

## 10. Offene Punkte und Grenzen

1. **Clip-Raum, Y-Richtung und Windungsrichtung gegenüber der Switch.** Die Tests geben die Bytes der Konstantenpuffer vor (Modus `array`) und beweisen damit nur, dass der HLSL-Pfad dasselbe rechnet wie unsere MSL. Ob Unitys Metal-Matrizen zu den Erwartungen der Switch-Shader passen (Abschnitt 5, erste Zeile), zeigt nur ein Referenzbild einer echten Szene (Ryujinx oder Gerät).
2. **Instancing-Puffer, globaler Speicher:** Wrapper und Kompilierung fertig (Abschnitt 13), **Bildvergleich offen** (13.1, 13.2). Shuffle: Abschnitt 13.4.
3. **Nicht in Unity gerendert:** Array-, 3D-Texturen, Vergleichssampler (Schatten), `TXQ`, mehrere Farbziele, `SV_Depth`, `nointerpolation`. **Diese Typen kommen in keinem der 6.804 verpackbaren Varianten vor** (Zählung über die `.wrap.json` aller Varianten: 30.863 Abrufe `2D`, 4 `Cube`, keiner `3D`/Array/Schatten); die Schatten sind Bildschirmraum-Schatten (`_ShadowMapTexture` als `2D`). Der Wrapper erzeugt sie trotzdem, die Bilder wurden nicht verglichen; Cube-Abruf: 4 Varianten nur kompiliert (13.3).
4. **Metal-Bibliothek:** Die Stichprobenvarianten wurden bis zum MSL-Text kompiliert; nur die 7 Fälle liefen bis zur GPU. Ein Lauf, der jede Variante zeichnet, steht aus.
5. **Andere GPU/Player:** Alle Messungen laufen im macOS-Editor auf einem Apple M1 Pro. Bitgleichheit mit dem Harness gilt für diese Kombination; ein iOS- oder Player-Build wurde nicht gemessen. Die Spielgerät-Abweichungen bei Funktionen wie `sin` sind offen.
6. **cbuf 0** (Treiberdaten, 180 Blobs) und die Belegung der Vertex-Bindung 0 sind unbekannt (Nullen mit Warnung).
7. **fp16 gegen die Hardware** (`docs/shader-translator.md` Abschnitt 11.3) bleibt offen; Unitys Pfad entspricht dem Übersetzer.
8. **Laufzeitkosten** von `skip_optimizations`, Größe der erzeugten Shader und Startzeit sind nicht gemessen.
9. Die Prüfung nutzt als Referenz unsere MSL im Harness; die Treue der MSL gegen die Ryujinx-SPIR-V-Referenz (95 %) steht in `docs/shader-translator.md`.

## 11. Reproduktion

```sh
export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer
make -C shader_translator test                                   # 93 + 15 + 6 Prüfungen
python3 -m unittest scripts/tests/test_shader_wrap.py            # 34 Tests
shader_translator/build/maxwell2msl --lang hlsl --stage fs work/shaders/blobs/<hash>.bin --info x.json --cbuf1 c1.bin -o x.hlsl
python3 scripts/shader_wrap.py '<Shader>' --bundle shaders --pass 0 --out work/unity-shader-lab/Assets/XnuGen/x.shader [--mode array] [--keywords K ...]

# Labor (Wegwerf-Projekt, zweiter Editor; nur Werkzeuge unter work/)
zsh -ic 'unity projects new unity-shader-lab --path <repo>/work --editor-version 6000.3.26f1 --architecture arm64 --template com.unity.template.3d'
(cd work/unity-shader-lab && zsh -ic 'unity pipeline install' && zsh -ic 'unity open')
python3 work/shaders/unity-lab/run_cases.py [fall ...] [--modes array named] [--persp] [--fast]   # Bilder: work/shaders/unity-out/
python3 work/shaders/unity-lab/run_math.py                                                       # Mikrotests
python3 work/shaders/unity-lab/mass2.py --per-shader 10 --check                                   # Massenprobe
```

Die Labor-Skripte und der Editor-Code (`Assets/Editor/XnuLab.cs`: `Check`, `RenderCase`, `StartMany`) liegen unter `work/` und sind nicht eingecheckt; die Messzahlen stehen in `work/shaders/unity-lab/results*.json`, `math_results.json`, `mass2_check.txt`.

## 12. Quellen

- Unity-Handbuch (6000.3): Pragma-Referenz (`disable_fastmath`, `skip_optimizations`, `hlslcc_bytecode_disassembly`) `https://docs.unity3d.com/6000.3/Documentation/Manual/SL-PragmaDirectives.html`; Pragmas an Compiler übergeben `…/writing-shader-programs-pragma-directives.html`.
- Native Plugins: `…/Manual/native-plugin-interface-introduction.html`, `…/Manual/low-level-native-plugin-rendering-extensions.html`, `…/Manual/low-level-native-plugin-shader-compiler-access.html` (nur D3D11); Header `IUnityGraphicsMetal.h`, `IUnityRenderingExtensions.h` im Ordner `Contents/PluginAPI` der Editor-Installation.
- Mesh-Zeiger: `https://docs.unity3d.com/6000.3/Documentation/ScriptReference/Mesh.GetNativeVertexBufferPtr.html`.
- Apple: `MTLCompileOptions` (`fastMathEnabled`, `mathMode`) `https://developer.apple.com/documentation/metal/mtlcompileoptions`.

## 13. Vollständige Abdeckung: Instancing, Speicherpuffer, Massenlauf, Build-Stufe (Stand 2026-10-19)

Alle Zahlen: Apple M1 Pro, Unity 6000.3.26f1, Lab-Editor im Hintergrund. Das Labor (`work/unity-shader-lab`, `work/shaders/unity-lab/`) liegt unter `work/` und ist nicht eingecheckt.

### 13.1 Instancing (1.288 Varianten, `Delphis/Map/Standard`, `Custom/StencilMask`, `UI/UI-Multiply`, `TextMeshPro/…`)

**Konvention (belegt aus den Bundle-Daten, nicht geraten):** `m_ConstantBuffers[].m_StructParams` des Inventars (neu: `constantBuffers[].structs`, `scripts/shader_inventory.py`) enthält Unitys `UNITY_INSTANCING_BUFFER`: Block `UnityInstancing_PerDraw0` = Array `unity_Builtins0Array` von Strukturen mit `unity_ObjectToWorldArray` (Offset 0) und `unity_WorldToObjectArray` (Offset 64), Schrittweite 128 Byte; `…PerDraw2` (`unity_Builtins2Array`, 112 Byte: `unity_SHAr…SHC`) und `…PerDrawSprite` (`PerDrawSpriteArray`, 32 Byte: `unity_SpriteRendererColorArray`, `unity_SpriteFlipArray`). Der Maxwell-Code liest `c[k][r27 + Offset]` mit `r27 = (iid + unity_BaseInstanceID) · 128` (belegt am Code von Blob `01e04f372b4f3067`: Multiplikation mit `0x60`/Verschiebung um 7); `unity_BaseInstanceID` liegt in `VGlobals` und ist eine Ganzzahl.

**Umsetzung:** Der Übersetzer erzeugt registerindizierte Zugriffe als `mx_cbr<k>(Offset)` (ersetzbare Makros, `NOTICE.md` Punkt 17). Der Wrapper (Modus `named`) deklariert den Unity-Block unverändert (`cbuffer UnityInstancing_PerDraw0 { struct { … } unity_Builtins0Array[500]; }`, Lücken der Struktur mit `float4 mx_pad…` aufgefüllt, 500 = `UNITY_INSTANCED_ARRAY_SIZE`) und liefert `mxv_cbr<k>(off)`, das aus `Offset / Schrittweite` und dem Wort den Ausdruck `unity_Builtins0Array[e].<Mitglied>[Zeile][Spalte]` wählt (Matrizen spaltenweise wie in 4.1). `unity_BaseInstanceID` wird als `uint` deklariert und ohne `asuint` gelesen. Bei Varianten mit `INSTANCING_ON` schreibt der Wrapper `#pragma multi_compile_instancing`, bei `PROCEDURAL_INSTANCING_ON` zusätzlich `#pragma instancing_options procedural:mx_proc_setup` und eine leere Funktion dieses Namens. Der Modus `array` bleibt für Tests (Harness füllt das Feld selbst).

**Ergebnis:** alle 1.288 Varianten werden verpackt (vorher 0); Unity übersetzt Stichproben (12 Varianten aller Gruppen) und die Varianten des Massenlaufs (13.5) ohne Fehler. **Bildvergleich: nicht bestanden / offen.** Der Instancing-Test (`Custom/StencilMask`, `DIRECTIONAL INSTANCING_ON`, zwei Instanzen mit verschiedenen Matrizen über `CommandBuffer.DrawMeshInstanced`) zeigt in Unity beide Instanzen mit **Einheitsmatrix** (Fläche wie ohne Instancing: x 26…228 statt 38…206 im Harness): Unity füllt `unity_Builtins0Array` mit den übergebenen Matrizen nicht so, wie unser Block es erwartet, oder wählt für diesen Aufruf nicht die `INSTANCING_ON`-Variante. Ursache nicht geklärt (Kandidaten: Zeichenaufruf im Lab; Name/Layout des Blocks in Unity 6 anders als in der Switch-Übersetzung von 2019.4; Matrizen im Block nach `unity_ObjectToWorldArray` + `unity_WorldToObjectArray` + `unity_LODFadeArray`). Bis das geklärt ist, gilt für Instancing **nur „kompiliert“**, nicht „bildgleich“.

### 13.2 Partikel und globaler Speicher (180 Vertex-Blobs, 1.994 Varianten `FxSystem/Particle`, Keyword `PROCEDURAL_INSTANCING_ON`)

**Konvention (belegt):** Das Inventar führt je Variante genau einen Speicherpuffer: `m_BufferParams` = `unity_ParticleInstanceData` (Index 512), also Unitys `StructuredBuffer` für Partikel-GPU-Instancing. Der Maxwell-Code liest Treiber-cbuf 0 Zeile 17 (Byte 0x110, 64-Bit-Adresse des Speicherpuffers 0 = NVN-Treiberkonvention), rechnet `Adresse = Basis + Instanz · 0x60 + Feldoffset` (Schrittweite 96 Byte) und lädt per LDG 32 Bit. **Umsetzung:** `ByteAddressBuffer`; da der Wrapper cbuf 0 auf Null lässt, ist die Gast-Adresse gleich dem Byte-Offset (`mx_gmem.Load(ga)`, hohes Wort ≠ 0 liest 0). Der Wrapper prüft, dass cbuf 0 nur Zeile 17 (Bytes 0x110 bis 0x118) liest und das Inventar genau einen Puffer führt, sonst Abbruch („mehr als ein Speicherpuffer“); `ByteAddressBuffer unity_ParticleInstanceData;` bindet Unity über den Namen (`Material.SetBuffer`/Partikelsystem, Raw-Puffer). STG (Schreiben) bleibt abgelehnt; in den 180 Blobs kommt es nicht vor.

**Ergebnis:** 1.994 von 1.994 Varianten verpackt (vorher 0); Stichproben (zwei Partikel-Varianten) kompilieren in Unity. **Bildvergleich offen:** der Fall `part` (zwei Partikel aus synthetischen Instanzdaten, Schrittweite 96 Byte, ungefähre Struktur) liefert im Harness kein sichtbares Bild (`nonclear_pixels = 0`), ist also nicht aussagekräftig; die genaue Struktur von `ParticleInstanceData` (Offset von Transform, Farbe, Animationsbild) ist nicht bewiesen, nur die Schrittweite. Der Bildtest braucht Daten, die das Vertex-Programm in sichtbare Geometrie umsetzt.

### 13.3 Textur-Dimensionen

Über alle 6.804 verpackbaren Varianten: 30.863 `2D`-Abrufe, 4 `Cube` (`Mitake/MitakeStandardShader1st` u. a., Punktlicht mit Cookie), **keine** `3D`-, Array- oder Vergleichssampler-Abrufe (Abschnitt 10, Punkt 3). Das HLSL-Backend erzeugt sie (C-Tests), ein Unity-Rendertest mit synthetischen Würfel-/Array-Texturen ist deshalb nur für `Cube` sinnvoll und steht aus; die 4 Cube-Varianten kompilieren in Unity. Dabei fiel der Fehler der Texturzuordnung auf (4.1, „Korrektur“).

### 13.4 Subgroup-Shuffle (16 Varianten, 4 Fragment-Blobs `Mitake/MitakeStandardPetrify`)

Nicht umgesetzt. SM5 hat keinen Quad-/Lane-Austausch; `SHFL` im Fragment-Shader dient *vermutlich* (nicht am Code geprüft) der Ableitungsbildung innerhalb des 2×2-Quads und ließe sich durch `ddx`/`ddy` ersetzen, aber nicht **bitgleich** (Ableitungen in Unity/Metal rechnen anders als der Austausch plus Subtraktion). Ohne Referenzbild entschieden wir uns gegen eine ungenaue Ersetzung. Folge: 16 von 6.820 Varianten (0,2 %) bleiben ohne HLSL; Alternative Pfad B (MSL-Plugin) nur für sie wäre unverhältnismäßig.

### 13.5 Massenlauf in Unity (Import, Kompilierung, Zeit, Speicher)

Messung: `work/shaders/unity-lab/mass_unity.py` (jede 3. erzeugte Variante, in Blöcken nach `Assets/XnuMass/c<N>/` im Lab-Projekt, Import mit `ForceSynchronousImport`, Fehler aus `ShaderUtil.GetShaderMessages`).

| Messgröße | Wert |
|---|---|
| Erzeugen aller 6.804 Varianten (Python, ein Prozess) | etwa 110 s; Quelltext 381 MB (Ø 56 KB je Variante; `Delphis/Map/Standard` Ø 60 bis 80 KB) |
| Blöcke 0 und 1 (1.520 Varianten = jede 3. der erzeugten Dateien; `Custom/…` und `Delphis/Map/Standard`, davon **720 mit Instancing-Block**) | **1.520 von 1.520 ohne Fehler**; Block 0: 760 in 415 s (Ø 547 ms, Maximum 2,8 s), Block 1: 760 in 526 s (Ø 692 ms) |
| Kompilierzeit | Ø 0,3 s (kleine Shader) bis 2,5 s (`Delphis/Map/Standard`, 60 bis 80 KB Quelltext) je Variante |
| Hochrechnung alle 6.804 | Größenordnung 1,5 bis 2,5 Stunden Editor-Zeit (`Delphis/Map/Standard` 2.570 × ~0,7 bis 2,5 s allein 0,5 bis 1,8 h): *Schätzung*, nicht gemessen |
| Editor-Hauptspeicher (RSS) | 790 MB nach 760, 817 MB nach 1.520 Varianten (Start ≈ 0,75 GB); Shader-Cache 164 MB auf der Platte nach rund 1.000 Varianten |
| Treue-Stichprobe (Unity gegen Harness) | die 7 Fälle aus 6.1 (alle 0/255); **neu: Instancing- und Partikelfälle ohne gültigen Vergleich** (13.1, 13.2) |

Nicht importiert (Zeitrahmen): die Partikel-Varianten (`FxSystem/Particle`, alphabetisch hinter den Blöcken 0 und 1) bis auf zwei Stichproben, und die übrigen Shader ab `Delphis/Map/Standard`-Ende. Die Bilanz für diese Varianten ist **nicht gemessen**.

**Folgerung für das iPad-Budget (Schätzung, nicht gemessen):** Alle 6.804 Varianten in den Player zu nehmen ist weder in der Kompilierzeit (Stunden je Plattform) noch in der Größe sinnvoll; die Varianten sind nach den Keywords der echten Materialien zu **strippen**. `scripts/shader_wrap_all.py --used used.json` erzeugt nur die gelisteten (Shader, Keyword-Menge)-Paare; `used.json` entsteht aus den Materialien der Bundles (nicht Teil dieses Auftrags: `m_ShaderKeywords` der Material-Objekte lesen; **jetzt vorhanden:** `scripts/material_export.py` + `scripts/material_variants.py`, `docs/material-remap.md`). Danach: je Pass ein Block mit `multi_compile` (Abschnitt 9, Punkt 2) statt einer Datei je Variante.

### 13.6 Build-Stufe `shaders` (`scripts/shader_build.sh`)

```sh
scripts/shader_build.sh [--out DIR] [--used FILE] [--shader NAME] [--force]
```

Kette: `make shader_translator` → `shader_extract_blobs.py --extra` (Blobs aus den eigenen Bundles) → `shader_inventory.py` (Inventar, jetzt mit `structs`/`buffers`) → `shader_fidelity.py index` (Programm → Blob-Hash) → `shader_wrap_all.py` (je Variante `maxwell2msl --lang hlsl` + `shader_wrap.py`, Ausgabe `.shader`, `.wrap.json`, `variants.json`). Programm-Ids zählt `shader_wrap.py` jetzt selbst aus dem Inventar auf (an allen 14.342 Programmen identisch zu `mapping.json`); der **Ryujinx-Cache wird nicht gelesen** (`shader_map.py` ist nur noch Messbank). Deterministisch: Dateinamen aus SHA-1 der Keyword-Menge (statt `hash()`), sortierte Aufzählung; zwei Läufe über `Delphis/Map/Standard` (2.570 Dateien) ergeben denselben Gesamt-MD5. Ausgabeordner: `work/build/shaders` (Standard) oder ein gitignorierter Ordner, z. B. `unity/Assets/GameData/Shaders` (`.gitignore`); `shader_wrap_all.py` bricht sonst ab (Spieldaten gehören nicht ins Repo). Exit-Codes: 0 ok, 2 Aufruf, 3 Bundle fehlt, 4 Werkzeug, 9 nicht alle Varianten verpackbar (derzeit 16).

**Integration in `scripts/build_all.sh` (umgesetzt, `docs/build-pipeline.md`):** Die Stufe `shaders` (nach `masterdata`) ruft `shader_build.sh` mit `--out work/build/shaders` (Standard) bzw. mit `--shaders-into-unity` `unity/Assets/GameData/Shaders`, reicht `SHADER_USED` als `--used`, `--force` und für Tests `--shader-only NAME` weiter und behandelt Exit 9 als Warnung („16 Varianten ohne HLSL, weiter“). Bei einem anderen `--work` verknüpft sie `work/romfs` dorthin, weil die Hilfsskripte den Pfad fest lesen. Voraussetzung: Stufe `extract` hat `work/romfs` erzeugt, `tools/pydeps` (UnityPy, lz4) ist vorhanden (Preflight prüft das). Stichprobenlauf (`Custom/EffectCopyTexture`) in 1,3 s. Das Unity-Projekt importiert die Dateien beim nächsten Öffnen; ohne `--used` entstehen Tausende Dateien, deshalb liegt die Standardausgabe außerhalb des Projekts (Strippen anhand der Materialdaten fehlt noch, 13.7 Punkt 4).

### 13.7 Offene Lücken (Stand dieses Abschnitts)

1. Instancing-Bild: Unity zeichnete im Lab Einheitsmatrizen (13.1) — **Nachtrag 2026-10-19 (`docs/material-remap.md`, Abschnitt 8): im aktuellen Stand nicht mehr reproduzierbar** (Fall `inst` 0/255 gegen Harness, Kontrollshader gleich); Ursache der früheren Messung nicht bewiesen, Instancing über Renderer-Batching ungemessen.
2. Partikel-Bild: kein gültiger Vergleichsfall (13.2).
3. Subgroup-Shuffle: 16 Varianten (13.4).
4. Massenlauf: nur ein Teil importiert (13.5); Kompilierzeit der großen Shader hoch; Strippen nach Materialdaten fehlt (`used.json`).
5. Cube-Rendertest, `TXQ`, mehrere Farbziele, `SV_Depth`, `nointerpolation`: weiterhin ohne Bildvergleich.
6. cbuf 0 (außer Speicherpuffer-Adresse) und Vertex-Bindung 0 bleiben unbekannt (Nullen mit Warnung).

### 13.8 Nachtrag 2026-10-19: Mehrpass-Shader, GrabPass, Schatten

`shader_wrap.py` erzeugt jetzt auch **mehrere Pässe in einem SubShader** (`--also PASS[:KW,KW]`, typisch der Schattenwurf) sowie **GrabPass** vor und **UsePass** hinter dem Hauptpass (Originalreihenfolge, `--no-aux` schaltet ab); `shader_wrap_all.py --combine-shadow` setzt zu jeder Forward-Variante den passenden `SHADOWCASTER`-Pass dazu (`variants.json`: `shadow`, `aux`). Im Lab gemessen: Schattenwurf und Bildschirmschatten laufen, GrabPass-Wasser zeigt den Hintergrund, 61 von 61 kombinierten benutzten Varianten kompilieren. Einzelheiten, Messaufbau und Zahlen: `docs/shader-globals.md`, Abschnitte 6 und 7.
