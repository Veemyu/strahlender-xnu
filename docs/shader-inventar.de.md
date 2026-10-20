# Shader-Inventar, Zuordnung zum Ryujinx-Cache und Schnittstellen (Stand: 2026-10-18)

Teil 1 von `ap-shaders`: nur Lesen und Messen. Es wurde nichts gerendert und kein Ton erzeugt. Kein Dump-Shader lief in Unity.
Die Datei enthält nur Namen, Zahlen und Render-States. Binärdaten (Shadercode, Texturen) stehen nicht im Repo.
Markierung: **belegt** = selbst gemessen, *vermutet* = Schluss ohne Gegenprobe, **offen** = nicht geklärt.
Eingebettet in den Zusammenhang: `render-treue.md` (Vorgabe 1:1), `shader-audio-machbarkeit.md` (Cache-Format, 5937 SPIR-V-Module).

## Werkzeuge und Ausgaben

| Skript (Repo) | Aufgabe | Ausgabe (lokal, `work/shaders/`, nicht im Repo) |
|---|---|---|
| `scripts/shader_inventory.py` | Shader-Objekte per UnityPy-TypeTree lesen: Eigenschaften, SubShader, Pässe, Render-State, Programme, Blobgrößen | `inventory.json` |
| `scripts/shader_map.py` | NVN-Blobs zerlegen, Maxwell-Code mit `guest.data` vergleichen, `shared.toc` auflösen | `mapping.json` |
| `scripts/shader_reflect.py` | SPIR-V der zugeordneten Cache-Einträge mit `spirv-cross --reflect` und `--msl` auswerten | `reflect.json` |
| `scripts/shader_report.py` | Tabellen und Kennzahlen für dieses Dokument | `tables.md` |

Aufruf aus dem Repo-Wurzelverzeichnis, zum Beispiel `PYTHONPATH=tools/pydeps python3 scripts/shader_inventory.py`. Spitzenverbrauch rund 600 MB RAM, Laufzeit je Skript unter zwei Minuten.

## 1. Inventar

### Quellen

- **belegt:** Die 64 Shader aus der Aufgabe: 63 in `AssetAssistant/Dpr/shaders` und 1 in `AssetAssistant/Effects/fxparticle` (`FxSystem/Particle`). Alle: Plattform-ID 19 (= `kShaderCompPlatformSwitch` in der UnityPy-Enumeration), Unity 2019.4.27f1, Programmtyp `ConsoleVS`/`ConsoleFS`, Hardware-Tier 3.
- **belegt (zusätzlich):** Ein Lauf über alle 14.056 Dateien unter `AssetAssistant` (nur Objekttypen gezählt) fand weitere Shader-Objekte. Das sind 26 Stück in 8 weiteren Quellen: `Data/resources.assets` (9: u. a. `Hidden/ModelViewReflection`, `TextMeshPro/Sprite`, Duplikate von `UI/Custom`, `Custom/Fxaa`, Bloom, TMP), `Dpr/tmpshader` (11 TextMeshPro-Varianten), und je ein Shader in `FureaiHiroba/poffin/prefabs`, `Environments/prefab_map/c10r0101`, `Environments/underground/ugspace03`, `Environments/bg/arenas/ground/g070` (alle vier: Unity `Standard`), `Dpr/scenes/digfossil` (`Skybox/Procedural`), `Dpr/fieldui/gymseq` (`Hidden/encseqpanelshader`). Im Katalog (`work/dpr_catalog.json`) stehen nur die beiden Bundles. Die Zusatz-Shader sind in `inventory.json` unter `extraShaders` und fließen in die Zuordnung (Abschnitt 3) ein, die Tabellen unten betreffen nur die 64.
- `fxparticle` enthält außerdem 400 `ShaderVariantCollection`-Objekte mit zusammen 2000 Varianten (Keyword-Text und Pass-Typ). Der Shader selbst hat 3988 Vertex/Fragment-Paare. 1994 der 2000 Keyword-Mengen existieren im Shader.
- Die `shaders`-Datei enthält zusätzlich 1 `Material` (nicht ausgewertet).
- Hinweis zur Struktur: Das Feld `m_Name` des Shader-Objekts ist leer. Der Name steht in `m_ParsedForm.m_Name`.

### Kennzahlen der 64 Shader

- Programme gesamt: 6878 Vertex, 6832 Fragment, **0** Geometry, **0** Hull, **0** Domain, 0 Raytracing. **Keine Tessellation, keine Geometry-Shader, kein Compute** im Bundle.
- Pässe je Shader: 1 Pass bei 45, 2 bei 16, 3 bei 2, 4 bei 1 (`UI/Blur`). Alle 64 haben genau einen SubShader mit LOD 0. Insgesamt 74 normale Pässe, 9 GrabPass, 4 UsePass (alle `Legacy Shaders/VertexLit/SHADOWCASTER`).
- Keywords: 155 verschiedene Namen. Lokale Keywords (`shader_feature_local`/`multi_compile_local`) nur in 5 Shadern (`UI/Custom`, `UI/UI-SoundWave`, `UI/UI-Multiply`, `Custom/Contest/ColorAdditve`, `Delphis/Dig/DigColorGain`).
- Instancing: 4 Shader haben eine Instancing-Variante (`Delphis/Map/Standard`, `Custom/StencilMask`, `UI/UI-Multiply`, `FxSystem/Particle`). Nur `FxSystem/Particle` hat zusätzlich eine prozedurale Instancing-Variante (`PROCEDURAL_INSTANCING_ON`).
- Render-State der 87 Pässe (einschließlich Grab- und UsePass, bei denen er unbelegt ist): Blend `One Zero` (= aus) 56, `SrcAlpha OneMinusSrcAlpha` 13, aus Material-Eigenschaften gesteuert (`_SrcBlend`/`_DstBlend` oder `_SrcColor`/`_DestColor`) 11, `SrcAlpha One` 2, `One One` 2, `One OneMinusSrcAlpha` 2, `DstColor OneMinusSrcAlpha` 1. Stencil aktiv in 12 Pässen. ZWrite aus Eigenschaft (`_ZWrite`) in 12 Pässen. ZTest aus Eigenschaft (`_ZTest`, `unity_GUIZTestMode`) in 20. Cull aus Eigenschaft (`_Cull`, `_CullMode`) in 15.
- Queue-Tags: Transparent 23 (+1 `Transparent-1`), Overlay 2, Background 1, Geometry±n 6; die übrigen 31 Shader ohne Queue. Im Original steht fünfmal der Tippfehler `RenderType=Opeque` (`Dpr/PostEffect/*`). Er ist irrelevant für die Funktion, aber beim Nachbau als Eigenheit zu bewahren, falls Shader-Ersatz per RenderType gesucht wird.
- Eigenschaften: 964 insgesamt: 394 Float, 262 Range, 145 Texture (143 2D, 2 Cube), 116 Color, 47 Vector. Attribute in den Eigenschaften: `PowerSlider` 94, `Header` 63, `Enum` 45, `Toggle` 44, `KeywordEnum` 40, `Space` 19, `MaterialToggle` 13, `ValueOffset` 3. Flags: `HideInInspector` 56, `NoScaleOffset` 29, `PerRendererData` 10, `HDR` 2.
- Standardtexturen: `white` 88, `black` 37, `bump` 16, `gray` 3, `green` 1. Häufigster Texturname: `_MainTex` (47 Shader).
- Custom-Editor-Klassen (Namen aus dem Spielcode, nicht im Bundle enthalten): `TMPro.EditorUtilities.TMP_SDFShaderGUI` (2), `DelphisMapStandardShaderGUI`, `DelphisCharacterStandardShaderGUI` (2), `PokeDefaultGUI` (2), `FireCoreShaderGUI`, `FireMaskShaderGUI`, `SmokeMaskShaderGUI`, `InspectorFxParticle`. Fallback gesetzt bei `TextMeshPro/Distance Field` (auf die Mobile-Variante) und `Custom/StencilMask` (`Diffuse`).
- Programm-Blobs: 11.974.198 B komprimiert, 84.758.224 B entpackt (alle 64). 62 Shader haben ein Segment, `Delphis/Map/Standard` und `FxSystem/Particle` je drei (je rund 16 MB).
- Vertex-Eingänge (Unity-Kanal → Shader-Eingang): häufigste Belegung sind die 6 Kanäle 0–5 (Position, Normal, Tangente, Farbe, UV0, UV1) bei 2560 Programmen, alle in `Delphis/Map/Standard`. Dann nur Kanäle 0, 3, 4 (Position, Farbe, UV0) bei 1808 Programmen in 16 Shadern (UI, Blend/Additive/Wasser, Post). Dann die Kanäle 0, 3, 4, 5, 6, 7 (zusätzlich UV1–UV3) bei 1670 Programmen, alle in `FxSystem/Particle`.

### Familien (Zuordnung nach Namen, von mir festgelegt)

Charakter/Pokémon-Modelle 8, Umgebung 18, UI/Text/Video 10, Partikel/Effekte 13, Post-Processing 15. Zusammen 64.
Spalten der Tabelle A: Pässe; Programme Vertex/Fragment; Keyword-Kombinationen (Summe über die Pässe: eindeutige Keyword-Mengen der Programme); Anzahl verschiedener Keywords; Eigenschaften gesamt/davon Texturen; Instancing-Variante; Cache-Einträge (Zahl der Ryujinx-Programme, die laut Abschnitt 3 diesem Shader zugeordnet sind).
„Kombi“ gleich „V/F“ heißt: jede Keyword-Menge hat ein eigenes Programm je Stufe. Bei `Mitake/*` und `UI/Custom` haben Vertex- und Fragmentstufe verschieden viele Programme (Keywords, die nur eine Stufe betreffen).

#### Charakter / Pokémon-Modelle

| Shader | Pässe | V/F | Kombi | Kw | Prop/Tex | Inst | Cache |
|---|---|---|---|---|---|---|---|
| `Delphis/Character/DepthOnly` | 2 | 6/6 | 6 | 3 | 39/4 | nein | 6 |
| `Delphis/Character/Standard` | 2 | 28/28 | 28 | 8 | 45/4 | nein | 28 |
| `Delphis/Poffin` | 2 | 28/28 | 28 | 8 | 49/7 | nein | 28 |
| `Mitake/MitakeDepthOnlyShader` | 1 | 1/1 | 1 | 0 | 0/0 | nein | 1 |
| `Mitake/MitakeStandardBumpShader` | 2 | 32/16 | 32 | 6 | 59/6 | nein | 4 |
| `Mitake/MitakeStandardPetrify` | 2 | 32/16 | 32 | 6 | 63/9 | nein | 4 |
| `Mitake/MitakeStandardPetrifyFire` | 1 | 1/1 | 1 | 0 | 35/7 | nein | 1 |
| `Mitake/MitakeStandardShader1st` | 3 | 42/26 | 42 | 10 | 56/4 | nein | 14 |

#### Umgebung

| Shader | Pässe | V/F | Kombi | Kw | Prop/Tex | Inst | Cache |
|---|---|---|---|---|---|---|---|
| `Custom/StencilMask` | 2 | 11/9 | 11 | 8 | 0/0 | ja | 9 |
| `Custom/WaterInteration/DynamicNormalMap` | 1 | 1/1 | 1 | 0 | 1/1 | nein | 1 |
| `Custom/WaterInteration/WaterSimulation` | 1 | 1/1 | 1 | 0 | 4/1 | nein | 1 |
| `Delphis/Map/Blend` | 1 | 1/1 | 1 | 0 | 1/1 | nein | 1 |
| `Delphis/Map/FlowMap` | 2 | 1/1 | 1 | 0 | 5/2 | nein | 1 |
| `Delphis/Map/FlowmapBumpWater` | 1 | 1/1 | 1 | 0 | 27/4 | nein | 1 |
| `Delphis/Map/FlowmapWater` | 1 | 1/1 | 1 | 0 | 20/3 | nein | 1 |
| `Delphis/Map/Fog` | 2 | 1/1 | 1 | 0 | 1/1 | nein | 1 |
| `Delphis/Map/LineUVScroll` | 1 | 1/1 | 1 | 0 | 11/1 | nein | 1 |
| `Delphis/Map/Mask` | 1 | 1/1 | 1 | 0 | 1/0 | nein | 1 |
| `Delphis/Map/PhotoFrame` | 1 | 1/1 | 1 | 0 | 8/1 | nein | 1 |
| `Delphis/Map/Sky` | 2 | 4/4 | 4 | 4 | 14/6 | nein | 3 |
| `Delphis/Map/Standard` | 2 | 2570/2570 | 2570 | 18 | 71/9 | ja | 2570 |
| `Delphis/Map/Water` | 2 | 1/1 | 1 | 0 | 15/3 | nein | 1 |
| `Delphis/Map/Wave` | 2 | 1/1 | 1 | 0 | 6/2 | nein | 1 |
| `Delphis/Snowfield/Snowfield` | 2 | 4/4 | 4 | 4 | 4/4 | nein | 4 |
| `Delphis/WaterSimulation/WaterSurface` | 2 | 1/1 | 1 | 0 | 11/3 | nein | 1 |
| `Dpr/Objects/ShadowCast` | 1 | 2/2 | 2 | 1 | 1/1 | nein | 2 |

#### UI / Text / Video

| Shader | Pässe | V/F | Kombi | Kw | Prop/Tex | Inst | Cache |
|---|---|---|---|---|---|---|---|
| `Delphis/UI/FrostedGlass` | 1 | 1/1 | 1 | 0 | 12/3 | nein | 1 |
| `MovieTexture` | 1 | 1/1 | 1 | 0 | 2/2 | nein | 2 |
| `TextMeshPro/Distance Field` | 1 | 8/8 | 8 | 3 | 65/5 | nein | 8 |
| `TextMeshPro/Mobile/Distance Field` | 1 | 8/8 | 8 | 3 | 35/1 | nein | 8 |
| `UI/Blur` | 4 | 2/2 | 2 | 0 | 7/1 | nein | 2 |
| `UI/Custom` | 1 | 4/16 | 16 | 4 | 19/1 | nein | 16 |
| `UI/UI-Gray` | 1 | 2/2 | 2 | 1 | 10/1 | nein | 2 |
| `UI/UI-Multiply` | 1 | 4/4 | 4 | 2 | 7/2 | ja | 4 |
| `UI/UI-SolidColor` | 1 | 2/2 | 2 | 1 | 6/1 | nein | 2 |
| `UI/UI-SoundWave` | 1 | 4/4 | 4 | 2 | 9/1 | nein | 1 |

#### Partikel / Effekte

| Shader | Pässe | V/F | Kombi | Kw | Prop/Tex | Inst | Cache |
|---|---|---|---|---|---|---|---|
| `Custom/AfterImage` | 1 | 1/1 | 1 | 0 | 5/2 | nein | 1 |
| `Custom/Contest/ColorAdditve` | 1 | 4/4 | 4 | 2 | 1/1 | nein | 1 |
| `Custom/ProceduralPlane/Footprint` | 1 | 1/1 | 1 | 0 | 9/1 | nein | 1 |
| `Custom/ProceduralPlane/FrameFade` | 1 | 1/1 | 1 | 0 | 2/1 | nein | 1 |
| `Delphis/Battle/Encount01` | 2 | 1/1 | 1 | 0 | 2/1 | nein | 1 |
| `Delphis/Battle/Encount02` | 2 | 1/1 | 1 | 0 | 2/1 | nein | 1 |
| `Delphis/Dig/DigColorGain` | 1 | 4/4 | 4 | 2 | 1/1 | nein | 1 |
| `Delphis/Map/Additive` | 1 | 1/1 | 1 | 0 | 1/1 | nein | 1 |
| `FxSystem/Particle` | 1 | 3988/3988 | 3988 | 102 | 77/3 | ja | 138 |
| `Mitake/FireCore1st` | 1 | 1/1 | 1 | 0 | 21/3 | nein | 1 |
| `Mitake/FireMask1st` | 1 | 18/18 | 18 | 8 | 18/2 | nein | 6 |
| `Mitake/MitakeGroundEffectShader1st` | 3 | 21/13 | 21 | 9 | 46/4 | nein | 7 |
| `Mitake/SmokeMask_MT` | 1 | 3/3 | 3 | 3 | 10/2 | nein | 1 |

#### Post-Processing

| Shader | Pässe | V/F | Kombi | Kw | Prop/Tex | Inst | Cache |
|---|---|---|---|---|---|---|---|
| `Custom/Bloom Finalize` | 1 | 4/4 | 4 | 4 | 6/2 | nein | 4 |
| `Custom/Bloom Setup` | 1 | 1/1 | 1 | 0 | 1/1 | nein | 1 |
| `Custom/CaptureFocus` | 1 | 1/1 | 1 | 0 | 1/1 | nein | 1 |
| `Custom/DepthOfField` | 1 | 1/1 | 1 | 0 | 4/4 | nein | 1 |
| `Custom/Downsample2x2Focus` | 1 | 1/1 | 1 | 0 | 1/1 | nein | 1 |
| `Custom/EffectCopyTexture` | 1 | 1/1 | 1 | 0 | 1/1 | nein | 1 |
| `Custom/ExpandFocus` | 1 | 1/1 | 1 | 0 | 1/1 | nein | 1 |
| `Custom/Fxaa` | 1 | 3/3 | 3 | 3 | 6/3 | nein | 3 |
| `Custom/Gaussian7x7` | 1 | 1/1 | 1 | 0 | 1/1 | nein | 1 |
| `Custom/ResolveFocus` | 1 | 1/1 | 1 | 0 | 1/1 | nein | 1 |
| `Dpr/PostEffect/BtlvPfxShader` | 1 | 4/4 | 4 | 2 | 11/1 | nein | 4 |
| `Dpr/PostEffect/ChromaticAberration` | 1 | 1/1 | 1 | 0 | 2/1 | nein | 1 |
| `Dpr/PostEffect/ColorFiler` | 1 | 1/1 | 1 | 0 | 2/1 | nein | 1 |
| `Dpr/PostEffect/FeedbackBlur` | 1 | 1/1 | 1 | 0 | 8/0 | nein | 1 |
| `Dpr/PostEffect/RadualBlur` | 1 | 1/1 | 1 | 0 | 4/1 | nein | 1 |

Die benötigten Texturen und Eigenschaften je Shader stehen vollständig in `inventory.json` (`properties`: Name, Anzeigename, Typ, Standardwert, Texturdimension, Standardtextur; `stages.*.textures`: Textur-Einheit, Name, Dimension). Die meistverwendeten Texturen sind Material-Eigenschaften (`_MainTex`, `_BumpTex`, `_Col0Tex`, `_EmissionMaskTex`, `_ComplexTex`, `_FlowMap`, `_NoiseTex` …). Zusätzlich lesen die Shader **globale Texturen**, die nicht in den Eigenschaften stehen und vom Spiel gesetzt werden müssen:

| Globale Textur | Shader (Zahl) | Beispiele |
|---|---|---|
| `_ShadowMapTexture` | 8 | Character/Standard, Map/Standard, Poffin |
| `_CloudShadowTex` | 7 | Character/Standard, Map/Standard, Poffin |
| `_BackgroundTexture` (GrabPass) | 5 + `g_BackgroundTexture` bei Particle | Encount01/02, Map/Water |
| `_CameraDepthTexture` | 5 | Map/Additive, Map/Blend, Map/Fog |
| `_OpaqueDepthTexture` | 5 | FlowmapWater, FlowmapBumpWater, Map/Standard |
| `_EnvironmentMap` | 5 | Character/Standard, Map/Standard |
| `_GlobalDepthTexture` | 2 | Bloom Finalize, CaptureFocus |
| `_ReflectionTex` | 2 | Map/FlowMap, Map/Standard |
| `_LightTexture0`, `_LightTextureB0` | je 2 | Mitake Standard/GroundEffect (Licht-Cookie, Abschwächung) |
| `_SnowTex`, `_SnowNormalTex`, `_FocusTex`, `_SubTex0`–`4`, `_DelayFrameTexture`, `_GrabTexture` | je 1 | Map/Standard, Downsample2x2Focus, Bloom Finalize, FeedbackBlur, UI/Blur |

### Render-State je Pass (aus `m_State`, Tabelle B)

`[_Name]` heißt: Wert kommt aus der Material-Eigenschaft. Bei Grab- und UsePass-Pässen sind die State-Felder unbelegt (Platzhalter `ZTest Disabled`, `Cull Off`, `ZWrite Off`); die Werte sind dort bedeutungslos. Stencil-Zeilen nennen nur Ref, Vergleich und Pass-Operation (Lese-/Schreibmasken, Fail/ZFail in `inventory.json`). Tags: `Lightmode` ist die Pass-Tag-Angabe, `QUEUE`/`RenderType` kommen vom SubShader.

#### Charakter / Pokémon-Modelle

| Shader | Pass | Tags | State |
|---|---|---|---|
| `Delphis/Character/DepthOnly` | #0 | Lightmode=FORWARDBASE, RenderType=Opaque | Blend [_SrcBlend] [_DstBlend]; ZWrite [_ZWrite]; ZTest LEqual; Cull Back; ColorMask 0; Stencil Ref 0 Comp GEqual Pass Keep |
| `Delphis/Character/DepthOnly` | #1 | Lightmode=SHADOWCASTER, RenderType=Opaque | ZWrite On; ZTest LEqual; Cull Back; ColorMask 0 |
| `Delphis/Character/Standard` | #0 | Lightmode=FORWARDBASE, RenderType=Opaque | Blend [_SrcBlend] [_DstBlend]; ZWrite [_ZWrite]; ZTest LEqual; Cull Back; Stencil Ref 0 Comp GEqual Pass Keep |
| `Delphis/Character/Standard` | #1 | Lightmode=SHADOWCASTER, RenderType=Opaque | ZWrite On; ZTest LEqual; Cull [_Cull] |
| `Delphis/Poffin` | #0 | Lightmode=FORWARDBASE, RenderType=Opaque | Blend [_SrcBlend] [_DstBlend]; ZWrite [_ZWrite]; ZTest LEqual; Cull Back; Stencil Ref 0 Comp GEqual Pass Keep |
| `Delphis/Poffin` | #1 | Lightmode=SHADOWCASTER, RenderType=Opaque | ZWrite On; ZTest LEqual; Cull [_Cull] |
| `Mitake/MitakeDepthOnlyShader` | #0 | Lightmode=FORWARDBASE | ZWrite On; ZTest LEqual; Cull Back; ColorMask 0 |
| `Mitake/MitakeStandardBumpShader` | #0 | Lightmode=FORWARDBASE | Blend [_SrcBlend] [_DstBlend]; ZWrite [_ZWrite]; ZTest [_ZTest]; Cull [_CullMode] |
| `Mitake/MitakeStandardBumpShader` | UsePass `Legacy Shaders/VertexLit/SHADOWCASTER` | – | (unbelegt) |
| `Mitake/MitakeStandardPetrify` | #0 | Lightmode=FORWARDBASE | Blend [_SrcBlend] [_DstBlend]; ZWrite [_ZWrite]; ZTest [_ZTest]; Cull [_CullMode] |
| `Mitake/MitakeStandardPetrify` | UsePass `Legacy Shaders/VertexLit/SHADOWCASTER` | – | (unbelegt) |
| `Mitake/MitakeStandardPetrifyFire` | #0 | QUEUE=Geometry+2, RenderType=Opaque | ZWrite On; ZTest [_ZTest]; Cull Back; Stencil Ref 0 Comp Equal Pass Keep |
| `Mitake/MitakeStandardShader1st` | #0 | Lightmode=FORWARDBASE | Blend [_SrcBlend] [_DstBlend]; ZWrite [_ZWrite]; ZTest [_ZTest]; Cull [_CullMode] |
| `Mitake/MitakeStandardShader1st` | #1 | Lightmode=FORWARDADD | Blend One One; ZWrite Off; ZTest [_ZTest]; Cull [_CullMode] |
| `Mitake/MitakeStandardShader1st` | UsePass `Legacy Shaders/VertexLit/SHADOWCASTER` | – | (unbelegt) |

#### Umgebung

| Shader | Pass | Tags | State |
|---|---|---|---|
| `Custom/StencilMask` | #0 | Lightmode=FORWARDBASE, RenderType=Opaque | Blend SrcAlpha OneMinusSrcAlpha; ZWrite Off; ZTest LEqual; Cull Back; ColorMask 14; Stencil Ref 1 Comp Always Pass Replace |
| `Custom/StencilMask` | #1 | Lightmode=FORWARDADD, RenderType=Opaque | Blend SrcAlpha One; ZWrite Off; ZTest LEqual; Cull Back; ColorMask 14; Stencil Ref 1 Comp Always Pass Replace |
| `Custom/WaterInteration/DynamicNormalMap` | #0 | – | ZWrite Off; ZTest LEqual; Cull Off |
| `Custom/WaterInteration/WaterSimulation` | #0 | – | ZWrite Off; ZTest LEqual; Cull Off |
| `Delphis/Map/Blend` | #0 | Lightmode=FORWARDBASE, QUEUE=Transparent, RenderType=Transparent | Blend SrcAlpha OneMinusSrcAlpha; ZWrite Off; ZTest LEqual; Cull Off |
| `Delphis/Map/FlowMap` | #0 Grab | QUEUE=Transparent | (unbelegt) |
| `Delphis/Map/FlowMap` | #1 | Lightmode=FORWARDBASE, QUEUE=Transparent, RenderType=Transparent | ZWrite Off; ZTest LEqual; Cull Back |
| `Delphis/Map/FlowmapBumpWater` | #0 | Lightmode=FORWARDBASE, QUEUE=Transparent, RenderType=Transparent | Blend SrcAlpha OneMinusSrcAlpha; ZWrite Off; ZTest LEqual; Cull Back |
| `Delphis/Map/FlowmapWater` | #0 | Lightmode=FORWARDBASE, QUEUE=Transparent, RenderType=Transparent | Blend SrcAlpha OneMinusSrcAlpha; ZWrite Off; ZTest LEqual; Cull Back |
| `Delphis/Map/Fog` | #0 Grab | QUEUE=Transparent | (unbelegt) |
| `Delphis/Map/Fog` | #1 | Lightmode=FORWARDBASE, QUEUE=Transparent, RenderType=Transparent | Blend SrcAlpha OneMinusSrcAlpha; ZWrite Off; ZTest LEqual; Cull Off |
| `Delphis/Map/LineUVScroll` | #0 | Lightmode=FORWARDBASE, QUEUE=Transparent, RenderType=Opaque | Blend SrcAlpha OneMinusSrcAlpha; ZWrite On; ZTest LEqual; Cull Back |
| `Delphis/Map/Mask` | #0 | QUEUE=Geometry-1, RenderType=Opaque | ZWrite Off; ZTest LEqual; Cull Back; ColorMask 0; Stencil Ref 0 Comp Always Pass Replace |
| `Delphis/Map/PhotoFrame` | #0 | Lightmode=FORWARDBASE, RenderType=Opaque | ZWrite On; ZTest LEqual; Cull Back |
| `Delphis/Map/Sky` | #0 | Lightmode=FORWARDBASE, QUEUE=Geometry, RenderType=Opaque | ZWrite On; ZTest LEqual; Cull Back |
| `Delphis/Map/Sky` | #1 | Lightmode=SHADOWCASTER, QUEUE=Geometry, RenderType=Opaque | ZWrite On; ZTest LEqual; Cull Back |
| `Delphis/Map/Standard` | #0 | Lightmode=FORWARDBASE, RenderType=Opaque | Blend [_SrcBlend] [_DstBlend]; ZWrite [_ZWrite]; ZTest LEqual; Cull [_Cull]; ColorMask [_ColorMask] |
| `Delphis/Map/Standard` | #1 | Lightmode=SHADOWCASTER, RenderType=Opaque | ZWrite On; ZTest LEqual; Cull [_Cull] |
| `Delphis/Map/Water` | #0 Grab | QUEUE=Transparent | (unbelegt) |
| `Delphis/Map/Water` | #1 | Lightmode=FORWARDBASE, QUEUE=Transparent, RenderType=Opaque | ZWrite Off; ZTest LEqual; Cull Back |
| `Delphis/Map/Wave` | #0 Grab | QUEUE=Transparent | (unbelegt) |
| `Delphis/Map/Wave` | #1 | Lightmode=FORWARDBASE, QUEUE=Transparent, RenderType=Opaque | ZWrite Off; ZTest LEqual; Cull Back |
| `Delphis/Snowfield/Snowfield` | #0 | Lightmode=FORWARDBASE, QUEUE=Background, RenderType=Opaque | ZWrite On; ZTest LEqual; Cull Back; Stencil Ref 1 Comp Always Pass Replace |
| `Delphis/Snowfield/Snowfield` | #1 | Lightmode=SHADOWCASTER, QUEUE=Background, RenderType=Opaque | ZWrite On; ZTest LEqual; Cull [_Cull] |
| `Delphis/WaterSimulation/WaterSurface` | #0 Grab | QUEUE=Transparent | (unbelegt) |
| `Delphis/WaterSimulation/WaterSurface` | #1 | Lightmode=FORWARDBASE, QUEUE=Transparent, RenderType=Opaque | ZWrite Off; ZTest LEqual; Cull Back; Stencil Ref 2 Comp NotEqual Pass Keep |
| `Dpr/Objects/ShadowCast` | #0 | Lightmode=SHADOWCASTER, QUEUE=Transparent-1 | ZWrite On; ZTest LEqual; Cull Back |

#### UI / Text / Video

| Shader | Pass | Tags | State |
|---|---|---|---|
| `Delphis/UI/FrostedGlass` | #0 | QUEUE=Transparent, RenderType=Transparent | Blend SrcAlpha OneMinusSrcAlpha; ZWrite Off; ZTest [unity_GUIZTestMode]; Cull Off; ColorMask [_ColorMask] |
| `MovieTexture` | #0 | – | ZWrite On; ZTest LEqual; Cull Back |
| `TextMeshPro/Distance Field` | #0 | QUEUE=Transparent, RenderType=Transparent | Blend One OneMinusSrcAlpha; ZWrite Off; ZTest [unity_GUIZTestMode]; Cull [_CullMode]; ColorMask [_ColorMask] |
| `TextMeshPro/Mobile/Distance Field` | #0 | QUEUE=Transparent, RenderType=Transparent | Blend One OneMinusSrcAlpha; ZWrite Off; ZTest [unity_GUIZTestMode]; Cull [_CullMode]; ColorMask [_ColorMask] |
| `UI/Blur` | #0 Grab, #2 Grab | QUEUE=Transparent, RenderType=Opaque | (unbelegt) |
| `UI/Blur` | #1, #3 | QUEUE=Transparent, RenderType=Opaque | ZWrite On; ZTest LEqual; Cull Off |
| `UI/Custom` | #0 | QUEUE=Transparent, RenderType=Transparent | Blend [_SrcColor] [_DestColor]; ZWrite Off; ZTest [unity_GUIZTestMode]; Cull Off; ColorMask [_ColorMask] |
| `UI/UI-Gray` | #0 | QUEUE=Transparent, RenderType=Transparent | Blend SrcAlpha OneMinusSrcAlpha; ZWrite Off; ZTest [unity_GUIZTestMode]; Cull Off; ColorMask [_ColorMask] |
| `UI/UI-Multiply` | #0 | QUEUE=Transparent, RenderType=Transparent | Blend DstColor OneMinusSrcAlpha; ZWrite Off; ZTest LEqual; Cull Off |
| `UI/UI-SolidColor` | #0 | QUEUE=Transparent, RenderType=Transparent | Blend SrcAlpha OneMinusSrcAlpha; ZWrite Off; ZTest [unity_GUIZTestMode]; Cull Off; ColorMask [_ColorMask] |
| `UI/UI-SoundWave` | #0 | QUEUE=Transparent, RenderType=Transparent | Blend SrcAlpha OneMinusSrcAlpha; ZWrite Off; ZTest [unity_GUIZTestMode]; Cull Off; ColorMask [_ColorMask] |

#### Partikel / Effekte

| Shader | Pass | Tags | State |
|---|---|---|---|
| `Custom/AfterImage` | #0 | RenderType=Opaque | ZWrite Off; ZTest Always; Cull Off |
| `Custom/Contest/ColorAdditve` | #0 | QUEUE=Transparent, RenderType=Transparent | Blend SrcAlpha OneMinusSrcAlpha; ZWrite Off; ZTest [unity_GUIZTestMode]; Cull Off |
| `Custom/ProceduralPlane/Footprint` | #0 | QUEUE=Transparent, RenderType=Transparent | Blend [_SrcBlend] [_DstBlend]; ZWrite Off; ZTest LEqual; Cull Off |
| `Custom/ProceduralPlane/FrameFade` | #0 | – | ZWrite Off; ZTest LEqual; Cull Off |
| `Delphis/Battle/Encount01`, `Encount02` | #0 Grab | QUEUE=Overlay | (unbelegt) |
| `Delphis/Battle/Encount01`, `Encount02` | #1 | QUEUE=Overlay | ZWrite Off; ZTest Always; Cull Off |
| `Delphis/Dig/DigColorGain` | #0 | QUEUE=Transparent, RenderType=Transparent | Blend SrcAlpha OneMinusSrcAlpha; ZWrite Off; ZTest [unity_GUIZTestMode]; Cull Off |
| `Delphis/Map/Additive` | #0 | Lightmode=FORWARDBASE, QUEUE=Transparent, RenderType=Transparent | Blend SrcAlpha One; ZWrite Off; ZTest LEqual; Cull Off |
| `FxSystem/Particle` | #0 | QUEUE=Transparent, RenderType=Transparent | Blend [_SrcColor] [_DestColor]; ZWrite [_ZWrite]; ZTest [_ZTest]; Cull [_Cull] |
| `Mitake/FireCore1st` | #0 | QUEUE=Geometry+2, RenderType=Opaque | ZWrite [_ZWrite]; ZTest [_ZTest]; Cull Back; Stencil Ref 0 Comp Equal Pass Keep |
| `Mitake/FireMask1st` | #0 | QUEUE=Geometry+1, RenderType=Opaque | ZWrite [_ZWrite]; ZTest [_ZTest]; Cull [_CullMode]; ColorMask 0; Stencil Ref 0 Comp NotEqual Pass Replace |
| `Mitake/MitakeGroundEffectShader1st` | #0 | Lightmode=FORWARDBASE | Blend [_SrcBlend] [_DstBlend]; ZWrite [_ZWrite]; ZTest [_ZTest]; Cull [_CullMode] |
| `Mitake/MitakeGroundEffectShader1st` | #1 | Lightmode=FORWARDADD | Blend One One; ZWrite Off; ZTest [_ZTest]; Cull [_CullMode] |
| `Mitake/MitakeGroundEffectShader1st` | UsePass `Legacy Shaders/VertexLit/SHADOWCASTER` | – | (unbelegt) |
| `Mitake/SmokeMask_MT` | #0 | QUEUE=Geometry+1, RenderType=Opaque | ZWrite [_ZWrite]; ZTest [_ZTest]; Cull Off; ColorMask 0; Stencil Ref 0 Comp NotEqual Pass Replace |

#### Post-Processing

Alle Pässe laufen mit `ZWrite Off; ZTest Always; Cull Off` (Vollbild-Dreiecke), ohne Blend, außer:
`Dpr/PostEffect/FeedbackBlur` mit `Blend SrcAlpha OneMinusSrcAlpha`. Das gilt für `Custom/Bloom Finalize`, `Bloom Setup`, `CaptureFocus`, `DepthOfField`, `Downsample2x2Focus`, `EffectCopyTexture`, `ExpandFocus`, `Fxaa`, `Gaussian7x7`, `ResolveFocus` und `Dpr/PostEffect/BtlvPfxShader`, `ChromaticAberration`, `ColorFiler`, `FeedbackBlur`, `RadualBlur` (jeweils 1 Pass).

### Besonderheiten (Zusammenfassung)

- **Tessellation: nein. Geometry-Shader: nein. Compute: nein** (im Bundle). Der Cache enthält 5 Compute-Programme, die zu keinem Bundle-Shader passen (siehe Abschnitt 3).
- **Beleuchtung:** Die Umgebung/Charakter-Shader sind Unity-Forward-Shader mit `FORWARDBASE`, `SHADOWCASTER` (und bei `Mitake/*` `FORWARDADD`). Die Keywords zeigen im Wesentlichen ein einziges Richtungslicht (`DIRECTIONAL`) mit Schatten (`SHADOWS_SCREEN`, `SHADOWS_DEPTH`, `SHADOWS_CUBE`). Nur `Mitake/*` kennt Punkt- und Spotlicht (`POINT`, `SPOT`, `*_COOKIE`, `VERTEXLIGHT_ON`, `LIGHTPROBE_SH`). Lightmap-Keywords fehlen in allen 155.
- `Delphis/Map/Standard` ist der große Shader: 18 Keywords, 2570 Varianten, 71 Eigenschaften, Instancing (`INSTANCING_ON`). Er hat 2562 Varianten im FORWARDBASE-Pass und 8 im SHADOWCASTER-Pass.
- `FxSystem/Particle`: 102 Keywords, 3988 Varianten, ein Pass, Instancing und prozedurales Instancing. Die Keywords beschreiben ein Kombinierer-System (`_COLORTEXTUREEXPRESSION_*`, `_ALPHAEXPRESSION_*`, `_MULTITEXTUREMODE_*`).
- GrabPass (9) nutzt `_BackgroundTexture` (7 Pässe) bzw. die Standard-Grab-Textur (`UI/Blur`).
- Stencil: `Custom/StencilMask`, `Snowfield`, `WaterSurface`, `Map/Mask`, `Mitake/Fire*`/`SmokeMask`, `Delphis/Character/*` (GEqual) – die Stencil-Maske ist für das Aussehen wichtig und kommt aus den Pass-Daten.
- Unity-Quelltext ist in den Bundles nicht vorhanden. Die Spalten im Inventar sind Metadaten der Programme.

## 2. ShaderLab-Gerüst aus ParsedForm

Ergebnis: **Ein ShaderLab-Gerüst lässt sich aus `m_ParsedForm` vollständig bis auf den Programmcode rekonstruieren**. Das ist eine Analyse der Datenlage. Ich habe keinen Rekonstruktionsversuch im Unity-Editor gemacht (Editor darf nicht angefasst werden) und kein Skript geschrieben, das `.shader`-Text erzeugt. *Vermutet:* Ein Generator (Python, nach `inventory.json`) ist eine überschaubare Aufgabe. AssetRipper erzeugt bereits für 9 Shader Platzhalter-Dateien (`//DummyShaderTextExporter`, nur Name und Properties); das ist weniger als das, was ParsedForm hergibt.

| Teil | Vorhanden in ParsedForm? | Bemerkung |
|---|---|---|
| Shader-Name, `CustomEditor`, `Fallback`, Abhängigkeiten | ja | Name nur in `m_ParsedForm.m_Name` |
| Properties: Name, Anzeigename, Typ, Standardwert, Range-Grenzen, Standardtextur, Texturdimension | ja | Range als [Wert, min, max] |
| Property-Attribute (`[Toggle]`, `[KeywordEnum(...)]`, `[Enum(...)]`, `[PowerSlider(n)]`, `[Header]`, `[Space]` …) und Flags (`HideInInspector`, `NoScaleOffset`, `PerRendererData`, `HDR`) | ja | Attribute als Text je Eigenschaft (z. B. 94 `PowerSlider`, 44 `Toggle`) |
| SubShader: Tags, LOD | ja | LOD ist immer 0 |
| Pass: Typ (Normal, UsePass, GrabPass), Name, Tags (`LightMode` …), Textur-Name beim GrabPass | ja | |
| Render-State: Blend (inkl. Alpha, Op, MRT-Blend), ZWrite, ZTest, Cull, ColorMask, Offset, AlphaToMask, Stencil (Ref, Masken, Comp/Pass/Fail/ZFail, Front/Back), Fog-Zustand | ja | Werte können auf Material-Eigenschaften verweisen (`[_SrcBlend]`); der Name der Eigenschaft ist mitgespeichert |
| Keywords je Programm (global und lokal) und welche Kombinationen kompiliert wurden | ja | **Nicht** erkennbar: ob `multi_compile` oder `shader_feature`, und die Gruppierung (welche Keywords zu einer Auswahlgruppe gehören). Daraus lassen sich Kombinationslisten, aber nicht die originalen `#pragma`-Zeilen zurückgewinnen |
| Instancing-Flag je Pass, prozedurales Instancing | ja | Die Pragmas (`multi_compile_instancing`, `instancing_options`) fehlen |
| Parameter-Layout je Programm: Konstanten-Puffer-Namen, Größen, Member mit Offset und Komponenten, Texturen (Einheit, Dimension), Eingabekanäle | ja | Das ist die Schnittstelle des Programms (Abschnitt 4) |
| Anforderungen (`m_ShaderRequirements`), Hardware-Tier | ja | Nur als Bitmaske |
| **HLSL-/CG-Programmcode** | **nein** | Nur NVN-Binärcode (Maxwell). Der Code kann nur aus SPIR-V/Maxwell zurückgewonnen werden, nicht aus ParsedForm |
| `#include`/Hilfsfunktionen, Struct-Namen, Variablennamen, Kommentare | nein | |
| Eigene `UsePass`-Ziele | nur Name | `Legacy Shaders/VertexLit/SHADOWCASTER` setzt Unitys eingebaute Legacy-Shader voraus |

Konsequenz: Das Gerüst (Properties, Tags, States, Keyword-Liste) ist rein mechanisch erzeugbar. Der Programmteil muss je Shader aus dem Cache-SPIR-V (oder direkt aus Maxwell) entstehen. Für 1:1-Treue ist das der eigentliche Aufwand (`render-treue.md`).

## 3. Zuordnung Bundle-Programme ↔ Ryujinx-Cache

### Was in den Bundle-Blobs steht (belegt)

Je Programm (Eintrag der Blob-Tabelle, 12 Byte: Offset, Länge, Segment) gilt, alle Zahlen little-endian:

| Offset | Inhalt | Beobachtung |
|---|---|---|
| 0x00 | Magic `0x0C07513C` | in allen 14.342 Blobs; im 80-MB-`main.elf` kommt die Folge nicht vor, die NVN-Shader liegen also nur in den Datendateien |
| 0x04 | Versionswort 26 (`0x1A`) | in allen Blobs; deckt sich mit dem Programmtyp 26 (`ConsoleVS`) im ParsedForm, die Bedeutung ist *vermutet* |
| 0x18 | Zahl der globalen Keywords, danach je Keyword `[Länge][Text, auf 4 Byte aufgefüllt]`, dann Zahl der lokalen Keywords und deren Liste | die Keyword-Listen stimmen bei **14.342 von 14.342** Programmen mit den Listen aus ParsedForm überein (Prüfung über sortierte Namen) |
| danach | Kopf: Gesamtgröße, Stufe (0 Vertex, 1 Fragment), 0, Offset des Datenabschnitts (immer `0x880`, relativ zum Kopf), Größe des Datenabschnitts, Magic `0x98761234` | Abschnitt „GLSLC“-Kopf, danach Wörter 1, 0x10, 0x120, 0x0B, 0x878 (in allen Blobs gleich) |
| Kopf + 0x8C4 | **SPH**: 0x50 Byte Shader-Programm-Header der Maxwell-GPU | Wort 0: Vertex `0x02060461`/`0x04060461`/`0x00060461`/`0x06060461`, Fragment `0x00065462`/`0x0006D462`/`0x0406D462`. Erste 5 Bit = Typ (1 VTG, 2 Pixel), Bits 5–9 = Version 3 |
| danach | Maxwell-Maschinencode, je 32 Byte: ein Scheduling-Wort plus 3 Befehle, am Ende `EXIT` und Schleifen-Padding | Beginn des Codes = Kopf + 0x914 |
| Datenabschnitt-Ende | Konstantenpool (Float-Konstanten, z. B. Grauwerte in `UI/UI-Gray`) | *vermutet*: wird zur Laufzeit als Konstantenpuffer 1 gebunden (Abschnitt 4) |
| nach dem Datenabschnitt | Reflexionstabelle: Block-Namen (`VGlobals`, `PGlobals`), Größe, Mitglieder (Name, Typ, Offset) | deckt sich inhaltlich mit den Parametern aus ParsedForm |

Die Segmentierung der Blobs: `Delphis/Map/Standard` und `FxSystem/Particle` liegen in je 3 LZ4-Segmenten (Tabelle in Segment 0, Programme in Segment 0–2), alle anderen in einem Segment.
**offen:** Die genaue Bedeutung der Kopfwörter (außer Größe, Stufe, Datenoffset), der Konstantenpool-Offset und die Skalierung der Scratch-/Lokalspeicher-Felder im SPH.

### Was im Ryujinx-Cache steht (belegt)

- `guest.toc` hat 1388 Einträge: 401 Vertex-, 982 Fragment- und 5 Compute-Codeblöcke. Jeder Eintrag enthält bei Grafikstufen **SPH (0x50 B) + Code** (Compute: nur Code), Cb1-Größe überall 0.
- `shared.toc` hat 2971 Einträge. Maske `0x22` (Vertex + Fragment) bei 2966, Maske 0 (Compute) bei 5. Bit 1 = Vertex, Bit 5 = Fragment (Ryujinx-Stufenzählung mit Compute = 0). Der Eintrag nennt je Stufe den Index in `guest.toc`.

### Methode (belegt)

1. Je Bundle-Programm: SPH-Position bestimmen (Kopf + 0x8C4, verifiziert durch Typ/Version-Bits). Ab dort liegt SPH + Code.
2. Je Guest-Eintrag: Schlüssel = die 32 Bytes Code direkt hinter dem SPH. Über den Schlüssel wird ein Wörterbuch auf Guest-Indizes gebaut.
3. Treffer, wenn der gesamte Guest-Eintrag (SPH + Code, Länge laut Cache) **Byte für Byte** dem Anfang des Blob-Codes ab SPH entspricht. Der Guest-Eintrag ist ein Präfix des Blob-Codes (*vermutet:* Ryujinx speichert nur die erreichbare Codelänge, das Schleifen-Padding am Ende fehlt).
4. Guest-Einträge ohne Treffer: zusätzlich Teilstring-Suche (48 Byte ab dem 17. Codebyte) im Rohblob aller Shader. Sie ergab 4 Treffer. Ich habe sie nicht weiter untersucht und nicht als Zuordnung gewertet.
5. Cache-Eintrag (shared) → Guest-Indizes Vertex/Fragment → Bundle-Programme → gemeinsame (Shader, SubShader, Pass). Eine Variante gilt als bestimmt, wenn es genau eine Keyword-Menge gibt, bei der Vertex- und Fragmentprogramm dieselben Keywords haben.

Es sind **keine Relokationen** nötig: Alle Treffer sind bitgleich inklusive SPH. Ein Vergleich nur des Codes ohne SPH brachte keinen zusätzlichen Treffer.

### Ergebnis (belegt, Zahlen aus `mapping.json`)

| Messgröße | Wert |
|---|---|
| Bundle-Programme (Vertex + Fragment) in den 64 Shadern | 13.710 (6878 + 6832); davon 8361 mit unterschiedlichem Code |
| … zusätzlich 26 Zusatz-Shader (resources.assets, tmpshader, Szenen-Bundles) | +632, zusammen 14.342 |
| Guest-Codeblöcke im Cache | 1388 (1383 Grafik, 5 Compute) |
| **Guest-Blöcke, die zu einem Bundle-Programm der 64 Shader passen** | **1302 von 1383** Grafikblöcken (94,1 %) |
| … mit den Zusatz-Shadern | **1316 von 1383** (95,2 %); +14 (TextMeshPro-Mobile, `Standard`, `Hidden/ModelViewReflection`, `TextMeshPro/Sprite`) |
| **Cache-Einträge (shared) mit vollständiger Zuordnung** (Vertex und Fragment) zu einem der 64 Shader | **2901 von 2966** Grafikeinträgen (97,8 %) |
| … mit den Zusatz-Shadern | **2915 von 2966** (98,3 %), 3 nur eine Stufe, 48 keine Stufe; 5 Compute-Einträge ohne Bundle-Entsprechung |
| **Bundle-Programme, die im Cache vorkommen** (64 Shader) | **8613 von 13.710** (62,8 %); davon 5221 mit unterschiedlichem Code |
| … alle Programme der Bundles (mit Zusatz-Shadern) | 8797 von 14.342; 5241 verschiedene Codes |

Verteilung der 2915 voll zugeordneten Einträge:
- 2900 auf genau einen Shadernamen (die übrigen 15 auf mehrere, z. B. `TextMeshPro/Distance Field` und `… Overlay`, die gleichen Code teilen).
- 2899 auf genau einen Pass.
- **2815 auf genau eine Keyword-Variante** (Shader + Pass + Keyword-Menge, wenn Vertex- und Fragment-Keywords gleich sind). Für 14 Einträge (12 aus `UI/Custom`, 2 aus `Custom/StencilMask`) existiert keine Paarung mit gleicher Keyword-Menge, weil die Stufen verschieden viele Programme haben. Der Rest ist wirklich mehrdeutig, weil mehrere Keyword-Mengen denselben Maschinencode erzeugen.
- Nur 43 Einträge sind schon auf Programmebene eindeutig (genau ein Vertex- und ein Fragmentprogramm).

Abdeckung der Keyword-Varianten (Keyword-Mengen, die in Vertex- und Fragmentliste desselben Passes vorkommen): 3181 von 6820 in den 64 Shadern.

Je Shader (Auszug, belegt; vollständig in `mapping.json` unter `stats.perShader`):

| Shader | Bundle-Programme | davon im Cache | Cache-Einträge |
|---|---|---|---|
| `Delphis/Map/Standard` | 5140 | **5140 (alle)** | 2570 |
| `FxSystem/Particle` | 7976 | 2879 | 138 |
| alle übrigen 62 Shader | 594 | **alle** | je 1 bis 28 |

- Für 63 der 64 Shader ist der Cache also vollständig: jede Variante, die das Bundle enthält, wurde einmal kompiliert (*vermutet:* Spielstart-Vorwärmung über Varianten-Sammlungen). **Nur `FxSystem/Particle` ist lückenhaft:** von 3988 Keyword-Mengen sind 343 mit gleicher Menge im Cache, 304 davon stehen in den 2000 Varianten der `ShaderVariantCollection`. Das ist die Menge, die der Nutzer tatsächlich gespielt hat. Die übrigen Partikelvarianten haben wir nur als Binärcode aus dem Bundle, ohne SPIR-V.
- Das heißt für die Rekonstruktion: Für alle 63 anderen Shader liegt für jede Variante ein SPIR-V-Modul vor (Duplikate eingerechnet). Für Partikel nur für den gespielten Teil.

### Was nicht zugeordnet werden konnte (offen)

- **72 Guest-Blöcke** (37 Vertex, 30 Fragment, 5 Compute) stimmen mit keinem Bundle-Programm überein. Sie betreffen 48 Cache-Einträge ohne jede Stufe und 3 mit nur einer Stufe. Der Code der Blöcke hat 0 bis 48 Byte gemeinsamen Anfang (nur SPH), also keine nahe Verwandtschaft zu einem Bundle-Programm.
- Ihre SPIR-V-Schnittstellen ähneln den Unity-Shadern (Blöcke `VGlobals`/`PGlobals`, 0–3 Texturen). *Vermutet:* Unity-eigene Shader (`Hidden/…`, interne Blit- oder Bildschirm-Shader), die in keinem der durchsuchten Dateien liegen, oder eine andere Spielversion im Cache (Cache vom 2023-07-07, Dump-Version nicht verglichen).
- Ein Abgleich mit dem ELF (`work/elf/main.elf`) fand keinen der 72 Blöcke.
- Die 5 Compute-Programme haben keine Entsprechung in den Shader-Bundles.

## 4. Schnittstelle: Konstanten, Puffer, Texturen

Quellen: Parameter-Layouts aus ParsedForm (`m_ConstantBuffers`) und SPIR-V-Reflexion der zugeordneten Cache-Module (`spirv-cross --reflect`, 5830 Module, null Fehler; `--msl` zum Ablesen der Zugriffe). `spirv-dis` ist nicht installiert.

### Constant-Buffer-Aufbau (belegt)

- Alle Switch-Shader (64) verwenden **zwei Sammelblöcke**: `VGlobals` (in allen 6878 Vertexprogrammen) und `PGlobals` (in 6678 der 6832 Fragmentprogramme). Zusätzlich kommen bei Instancing `UnityInstancing_PerDraw0` (1289 Vertexprogramme), `UnityInstancing_PerDraw2` (2) und `UnityInstancing_PerDrawSprite` (2) vor. Die klassischen Unity-Blöcke `UnityPerDraw`, `UnityPerCamera`, `UnityLighting` gibt es **nicht**; ihre Inhalte stehen als gewöhnliche Mitglieder in `VGlobals`/`PGlobals`.
- **Bindung:** Unity-Bindungsindex n entspricht im SPIR-V dem Hardware-Konstantenpuffer n + 3. Beispiele: `VGlobals` Bindung 1 → `vp_c4` (2874 Module), `PGlobals` Bindung 0 → `fp_c3` (2874), `VGlobals` Bindung 0 → `vp_c3` (41), `UnityInstancing_PerDraw0` Bindung 2 → `vp_c5` (1282). Die Regel hielt bei allen 5830 ausgewerteten Modulen; es traten nur zusätzlich auf: **c1** (siehe unten) und bei 47 Fragmentmodulen **c2**.
- Die Puffer erscheinen im SPIR-V als `float4[4096]` (65.536 B), sie sind eine Ryujinx-Eigenheit. Die tatsächliche Größe ist die aus ParsedForm (zum Beispiel `VGlobals` 416 B bei `TextMeshPro/Mobile/Distance Field`). Der Ryujinx-Block `support_buffer` (1344 B, Bindung 0) steht in allen 5830 Modulen und trägt keinen Unity-Namen. *Vermutet:* Er gehört dem Emulator (Zusatzdaten für Alpha-Test, Viewport u. Ä.) und ist beim Nachbau irrelevant.
- **Instancing:** `vp_c5` (die Instanzdaten, 1286 Module) wird dynamisch indiziert. *Vermutet:* Das entspricht Unitys Instanz-Arrays (`UNITY_INSTANCING_BUFFER`).
- **c1 (Konstantenpool):** 2705 Fragment- und 1330 Vertexmodule lesen aus Puffer 1. Beispiel `UI/UI-Gray`: Fragment liest `c1[0].xyz` und multipliziert damit Farbkanäle; im Datenabschnitt des Blobs stehen dort Gleitkommawerte (0,59 und 0,11). **vermutet:** c1 ist der vom Shader-Compiler angelegte Konstantenpool, dessen Inhalt im Blob liegt. Der Cache speichert ihn nicht (Cb1-Größe 0 überall). Für einen treuen Nachbau muss er aus dem Blob gelesen werden. Der genaue Offset ist **offen**.
- **Texturen:** Fragmenttexturen liegen im SPIR-V bei Satz 2, Bindung 128 + Textur-Einheit; die Einheit stimmt mit `m_TextureParams.m_Index` aus ParsedForm überein (59 von 61 Shadern konsistent; die zwei Ausnahmen, `Snowfield` und `MitakeStandardPetrify`, lesen Texturen im Vertexshader mit anderen Bindungen). In den 64 Shadern sind es 31.483 2D- und 4 Cube-Parameter. Im SPIR-V der zugeordneten Module erscheinen `sampler2D` (180 Bindungen über alle Shader) und `samplerCube` (3). Maximal 13 Texturen in einem Programm (`Delphis/Map/Standard`, Bindungen 128 bis 140).
- **Vertex-Eingänge:** Die Eingänge sind Attribute 0 bis 7 (je vec4). Die Zuordnung Unity-Kanal → Eingang steht in `inputChannels` (häufigste Belegungen siehe Abschnitt 1).

### Von den Shadern erwartete Unity-Built-in-Konstanten (belegt)

Aufgeführt sind die Namen in `VGlobals`/`PGlobals`/`UnityInstancing_*`. Die Zahl hinter dem Namen ist die Zahl der Shadernamen, in denen er vorkommt (77 verschiedene Namen aus den Bundles und den Zusatzquellen); „genutzt“ heißt: laut SPIR-V-Zugriffen im Maschinencode tatsächlich gelesen.

- **Matrizen:** `unity_ObjectToWorld` (76; genutzt in 63 Shadern), `unity_MatrixVP` (76; 64), `unity_WorldToObject` (25; 18), `unity_MatrixV` (13; 11), `glstate_matrix_projection` (10; 4), `unity_MatrixInvV` (1), `unity_CameraInvProjection` (1).
- **Kamera/Bildschirm:** `_WorldSpaceCameraPos` (26; 21), `_ProjectionParams` (19; 17), `_ScreenParams` (12; 5), `_ZBufferParams` (12; 11), `_Time` (15; 12), `unity_WorldTransformParams` (10; 8).
- **Licht:** `_WorldSpaceLightPos0` (22; 17), `_LightColor0` (11; 7), `unity_LightShadowBias` (10; 4), `unity_WorldToLight` (5; 3), `_LightShadowData`, `unity_ShadowFadeCenterAndType`, `unity_WorldToShadow`, `_LightPositionRange`, `_LightProjectionParams` (je 1), vier Punktlichter (`unity_4LightPosX0`/`Y0`/`Z0`, `unity_4LightAtten0`, `unity_LightColor`; 4; genutzt in 1).
- **Sphärische Harmonische (Lichtsonden):** `unity_SHAr/g/b`, `unity_SHBr/g/b`, `unity_SHC` (je 6; genutzt in 3).
- **Sonden-Volumen, Reflexionssonden:** `unity_ProbeVolume*` (3), `unity_OcclusionMaskSelector` (3), `unity_SpecCube0_*`, `unity_SpecCube1_*` (1: das ist `Standard`, nicht der Spiel-Shader).
- **Instancing/Partikel:** `unity_BaseInstanceID` (7; 5), `unity_ParticleUseMeshColors`, `unity_ParticleUVShiftData` (1).
- **Abgeleitete Konstanten** (`_ST`, `_TexelSize`, `_HDR`, `_ProjS` zu einer Eigenschaft): 41 Namen. Unity setzt `_ST`/`_TexelSize` selbst, `_ProjS` ist eigenes Material-Handling (siehe nächster Punkt).
- **Globale Werte, die das Spiel setzen muss** (kein Material-Eigenschaftsname, kein Unity-Name), 40 Namen: `_CloudParam`, `_CloudShadowBase`, `_CloudShadowScale`, `_ShadowColor` (je 7 Shader), `_ReflectorColor` (5), `_GlobalLightPower`, `_PokeLightColor`, `_PokeReflectorColor`, `_EnvMatrix`, `_ClipRect` (je 4), `_ReflectionVP` (3), `_CharacterLightColor`, `_CharacterReflectorColor`, `_FocalCoefficient`, `_RcpGridSize` (je 2) und weitere Einzelwerte (u. a. `_BloomThreshold`, `_BlurOffsetX/Y`). Von den 40 Namen stehen 32 als Zeichenketten im Spielcode (`work/il2cpp/stringliteral.json`); dort liegt die Quelle der Werte. Die übrigen 8 sind vom Unity-System/TMP automatisch gesetzte Größen (`_TextureSampleAdd`, `_UIMaskSoftnessX/Y`, `*_TexelSize`).

### Was für Unity 6 geliefert werden muss

Zuerst das, was die Built-in-Pipeline selbst setzt (nur dann, wenn wir sie mit denselben Einstellungen wie das Original fahren: Forward, Gamma, ein Richtungslicht, Schattenkaskaden wie in `render-treue.md`):

1. **Matrizen und Kamera** (`unity_ObjectToWorld`, `unity_WorldToObject`, `unity_MatrixVP`, `unity_MatrixV`, `_WorldSpaceCameraPos`, `_ProjectionParams`, `_ScreenParams`, `_ZBufferParams`, `_Time`, `unity_WorldTransformParams`): liefert Unity 6 Built-in. Die Namen müssen in den neuen HLSL-Shadern gleich heißen, die Pufferstruktur ist egal (Unity bildet `UnityPerDraw`/`UnityPerCamera` selbst ab).
2. **Licht** (`_WorldSpaceLightPos0`, `_LightColor0`, `unity_LightShadowBias`, `unity_WorldToLight`, Punktlicht-Felder, `unity_SH*`): liefert Unity im FORWARDBASE/FORWARDADD-Durchlauf, wenn `LightMode`-Tags und Pragmas (`multi_compile_fwdbase`, `multi_compile_fwdadd_fullshadows`) richtig gesetzt sind. Die Keyword-Listen aus Abschnitt 1 sind dafür die Referenz. **Offen:** ob `unity_SH*` und die Vertexlichter bei Unity 6 dieselben Werte wie bei 2019.4 ergeben (Gamma/Linear-Pfad, Sonden-Daten).
3. **Schatten:** `_ShadowMapTexture` (Bildschirm-Schatten) und `SHADOWS_DEPTH`/`SHADOWS_CUBE`: erzeugt Unity im Forward-Pfad. Das setzt `Shadows` in Qualitätsstufe und Kaskaden wie im Original (Distanz 20, Stufe 2).
4. **Instancing:** `UnityInstancing_PerDraw0` entspricht Unitys `UNITY_INSTANCING_BUFFER`; der Instanz-Pfad muss per Pragma wieder aktiviert werden.
5. **GrabPass:** `_BackgroundTexture` (GrabPass in `Delphis/Map/*`) ist in Unity 6 Built-in weiterhin möglich.

Dann das, was **das Spiel (unser Nachbau) setzen muss**:

6. **Globale Werte** aus der Liste oben (Wolkenparameter, Licht-/Reflektorfarben `_PokeLightColor`…, `_EnvMatrix`, `_ReflectionVP`, `_FocalCoefficient`). Die Zeichenketten im Spielcode zeigen, wo sie im Original gesetzt werden; die Werte kommen aus dem Spiel-Zustand.
7. **Globale Texturen:** `_CloudShadowTex`, `_EnvironmentMap`, `_OpaqueDepthTexture`, `_GlobalDepthTexture`, `_CameraDepthTexture`, `_ReflectionTex`, `_BackgroundTexture` (Tabelle in Abschnitt 1). Die Tiefen-Texturen (`_OpaqueDepthTexture`, `_GlobalDepthTexture`) sind spielinterne Render-Ziele, die das Spiel selbst erzeugt.
8. **Konstantenpool (c1):** nicht von Unity gesetzt. Entweder die Konstanten aus dem Blob in den neuen Shader als Literale übernehmen, oder die Shader aus SPIR-V neu erzeugen (dort liegt c1 als Uniform-Block).
9. **Material-Eigenschaften:** 964 Eigenschaften der 64 Shader stehen im Inventar; die Materialwerte selbst stehen in den Material-Objekten der Szenen-Bundles (nicht Teil dieser Analyse).

### Offene Punkte

- **c1-Konstantenpool:** Lage im Blob, Layout, und ob er bei allen Programmen identisch zum zur Laufzeit gebundenen Puffer ist.
- Die Bedeutung der Kopfwörter im NVN-Blob außerhalb der benannten Felder.
- Ob die 72 nicht zuordenbaren Guest-Blöcke (67 Grafik, 5 Compute) aus anderen Shadern oder einer anderen Spielversion stammen.
- Welche der Varianten, die nur im Bundle (ohne SPIR-V) liegen (rund 3.700 Partikel-Keyword-Mengen), das Spiel tatsächlich verwendet.
- Ob die Zuordnung für Varianten, die identischen Code teilen (z. B. 3 Keyword-Mengen → 1 Programm), eine Rolle für das Aussehen spielt (der Maschinencode ist gleich; nur der Keyword-Name unterscheidet sich).
- Werte der Unity-Built-ins in Unity 6 vs. 2019.4 (Gamma-Pfad, `unity_SH*`, Schattenkaskaden).
- Spielversion von Dump und Cache nicht verglichen (Cache 2023-07-07).
- Die Rekonstruktion von `#pragma`-Zeilen (multi_compile vs. shader_feature).

## Dateien

- `scripts/shader_inventory.py`, `shader_map.py`, `shader_reflect.py`, `shader_report.py` (Repo).
- Lokal: `work/shaders/inventory.json` (alle Shader inkl. Zusatzquellen, Eigenschaften, Pässe, Programm-Listen, Parameter-Layouts), `mapping.json` (Programme, Guest-Treffer, Cache-Einträge mit Kandidaten, Statistik), `reflect.json` (SPIR-V-Schnittstelle je zugeordnetem Eintrag, Zusammenfassung je Shader), `tables.md` (Tabellen).
