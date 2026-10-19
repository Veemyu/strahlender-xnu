# Material-Umbau: Bundle-Material → erzeugter Shader (Todo `ap-material-remap`)

Stand 2026-10-19. Fragen: Wie kommt ein Material aus einem Original-Bundle zu einem unserer erzeugten Shader (`docs/shader-unity-integration.md`), ohne dass je ein Original-Shader in Unity geladen oder gezeichnet wird? Welche Variante wird je Material gewählt? Was fehlt bis zum Bild?

Markierung: **belegt** = gemessen oder im Quelltext gelesen, *vermutet* = Schluss ohne Test. Alle Messungen: Apple M1 Pro, Unity 6000.3.26f1 (Lab-Editor `work/unity-shader-lab`, Built-in-Pipeline, Gamma, Metal). Spieldaten, Bilder und erzeugte Shader liegen nur unter `work/` (gitignoriert); im Repo stehen Code, Tests mit synthetischen Daten und diese Datei.

## 1. Ergebnis in Zahlen

| Frage | Ergebnis |
|---|---|
| Behält Unity die Eigenschaften eines Bundle-Materials ohne geladenen Shader? | **Ja.** Das Material lädt mit `Hidden/InternalErrorShader`; Floats, Farben, Texturverweise (mit Kachelung/Versatz), Keywords und Render-Queue bleiben erhalten (Abschnitt 2). Der **Shadername geht verloren** (der PPtr bleibt ungelöst, Instanz-ID 43032 bei allen). |
| Wie kommt der Name zurück? | Offline aus den Bundles per UnityPy (`scripts/material_export.py`): Shader-PPtr → CAB → Inventar. **640 Bundles unter `Environments/` in rund 15 s: 10.011 Materialien**, 3 ohne auflösbaren Shader, 22 Namensgruppen mit doppeltem Namen im selben Bundle (4 inhaltsgleich, 5 mit anderen Keywords, 13 nur mit anderen Werten). |
| Welche Variante? | `ShaderVariantResolver` (C#) / `scripts/material_variants.py` (Referenz): **10.008 von 10.008** Materialien mit exakter Forward-Variante, Schatten-Pass 9.813 von 9.813 exakt; 0 „nächstliegend“ im Forward-Pass, 0 „nicht verfügbar“ (einzige Ausnahme: der `FORWARDADD`-Pass des einen `Custom/StencilMask`-Materials, „nächstliegend“). 137 verschiedene (Shader, Keyword-Menge) → **60 benutzte Varianten** statt 6.820. |
| Kompilieren die benutzten Varianten? | **61 von 61** ohne Fehler in Unity (32,6 s, Ø 0,53 s je Datei). |
| Umbau der Zone 422 (Blöcke T01, R201, L01 der Karte `area001`) | **34 Materialien, 1.357 Material-Slots, 34 von 34 vollständig, 0 Abweichungen** beim Vergleich Material ↔ Export (beide Pfade), **0 Textur-Fehlgriffe**; Umbau 18 bis 58 ms (68 Material-Objekte inkl. Schatten-Material). |
| Bild gegen Harness mit echten Materialwerten | **5 von 5 Fällen bitgleich** (0 von 255, 41.616 Pixel gezeichnet): `Delphis/Map/Standard` mit Float- und Farbwerten echter Materialien, Variante vom Resolver gewählt (Abschnitt 7.2). |
| Tests | 11 reine C#-Tests (dotnet, `work/dotnet-render`) und 7 Unity-Tests, zusammen **18 grün im Lab**; 5 Python-Tests neu (`scripts/tests/test_material_variants.py`), `shader_wrap`-Tests (34) unverändert grün. |
| Instancing „Einheitsmatrix“ | **Im aktuellen Stand nicht reproduzierbar** (Abschnitt 8): Unity zeichnet zwei Instanzen mit verschiedenen Matrizen, bitgleich zum Harness (Fall `inst`, 0/255) und deckungsgleich zu einem handgeschriebenen Kontrollshader. Ursache der früheren Messung nicht bewiesen. |
| Größte Lücken | Schattenpfad (`SHADOWS_SCREEN`/`_ShadowMapTexture`), Mehrpass-Shader in einem Material, Grab-Pässe, Spielwerte der Globals, Texturen aus Nachbar-Bundles, Player-Einbindung der Shader (Abschnitt 10). |

## 2. Befund: Bundle-Material ohne Shader-Bundle (belegt, Lab)

Sonde `Assets/Editor/MatProbe.cs` (nicht im Repo): Bundle `Environments/fields/area001` mit `AssetBundle.LoadFromFile`, Prefab laden, Materialien der Renderer lesen. **Das Shader-Bundle wird nicht geladen.**

| Beobachtung | Wert |
|---|---|
| `material.shader` | nicht `null`, sondern `Hidden/InternalErrorShader` |
| `shaderKeywords`, `renderQueue` | erhalten (z. B. `_ALPHABLEND_ON,_CASCADE_SINGLE`, 2000) |
| `HasProperty("_MainTex")` | `false` (der Fehlershader kennt sie nicht) |
| `SerializedObject`: `m_SavedProperties` | erhalten: 9 Texturumgebungen, 66 Floats, 11 Farben; `m_ShaderKeywords` leer (Unity 6 führt Keywords in anderen Feldern), `stringTagMap` mit 1 Eintrag |
| `m_Shader` | ungelöster PPtr, Instanz-ID bei allen Materialien gleich (43032) |
| **Danach `material.shader = <unser Shader>`** | Eigenschaften greifen sofort nach Namen: `_MainTex`, `_ComplexTex`, `_BlendTex` als echte Texturen mit Namen und Größe (512 × 512), Kachelung (`-0,13`), `_Cascade`, `_Cutoff`, `_Cull`, Farben, `_SpecularColor`; Keywords und Queue bleiben |

Folgerungen: (1) Ein **Export der Werte ist für den Umbau nicht nötig**, solange das Material geladen ist: Kopie des Materials + Shadertausch genügt (Pfad „Übernahme“). (2) Der **Shadername muss offline kommen**, weil der PPtr ihn nicht trägt. (3) Der Export bleibt als zweiter Pfad („Eintrag“) für Fälle, in denen das Material nicht geladen ist oder geprüft werden soll; beide Pfade ergeben im Zonentest dasselbe (Abschnitt 7.1). (4) Der Editor ändert beim Zuweisen eines Shaders mit `[KeywordEnum]` die Keywords des Materials selbst (beobachtet: `_CASCADE_BLENDUV0` fiel weg, `_ENVIRONMENTMAPENABLE_SPECULAR` kam hinzu); das ist für uns bedeutungslos, weil die Variante aus den **exportierten** Keywords bestimmt wird und die erzeugten Shader feste Keyword-Mengen haben.

## 3. Datenweg und Dateien

```
Bundles ──material_export.py──▶ work/materials/<Bundle>.json   (je Material: Shader, Keywords, Queue, Tags, Floats, Farben, Texturen)
                                        │
Inventar ─ shader_wrap_all.py ─▶ variants.json (alle Varianten; Dateiname = Shadername)
                                        │
        material_variants.py (Referenz der Regeln) ─▶ used_variants.json ─▶ shader_wrap_all.py --used ─▶ nur diese .shader (Abschnitt 11)

Laufzeit:  MaterialCatalog (Export) + ShaderVariantIndex (variants.json) ─▶ ShaderVariantResolver ─▶ MaterialRemapper ─▶ Material[]
```

| Datei | Aufgabe |
|---|---|
| `scripts/material_export.py` | liest Material-Objekte per UnityPy-TypeTree; Shader-PPtr → Shadername (Dateiverweis → CAB der Shader-Bundles → Inventar `bundle`/`pathId`); Texturverweis → Name, Breite, Höhe, Format; schreibt je Bundle eine JSON-Datei und optional `--used`. Bricht ab, wenn der Zielordner nicht gitignoriert ist. |
| `scripts/material_variants.py` | Referenzumsetzung der Variantenwahl (Python), Massenauswertung über alle Exporte, Bericht mit Lücken, `--used-out` für `shader_wrap_all.py --used`. |
| `unity/Assets/Scripts/Render/ShaderVariantIndex.cs` | liest `variants.json` (nur SubShader 0, nur Status `ok`); je Shader/Pass: Varianten, Keyword-Menge des Passes, `LightMode`. |
| `…/ShaderVariantResolver.cs` | Regeln aus Abschnitt 4; `RenderEnvironment` (Umgebungs-Keywords). |
| `…/MaterialCatalog.cs` | liest die Exporte (`MaterialRecord`); Suche nach (Bundle, Name[, Keywords]). |
| `…/GameGlobals.cs` | die 35 Spiel-Globals (Abschnitt 6), Senke `IGlobalSink`. |
| `…/Runtime/MaterialRemapper.cs` | Umbau (Abschnitt 5), `Verify` (Material gegen Export). |
| `…/Runtime/LoadedTextureIndex.cs` | Textur zum Exportverweis über Name + Größe. |
| `…/Runtime/UnityGlobalSink.cs` | `Shader.SetGlobalFloat/Vector/Matrix/Texture`. |
| `unity/Assets/Tests/EditMode/RenderRemapTests.cs`, `RenderRemapUnityTests.cs`, `Fixtures/variant_resolution_cases.json` | Tests; dieselbe Fallliste prüft Python und C# (Abschnitt 9). |

Die Assembly `Xnu.Render` hängt nur von `Xnu.Core` und `Xnu.Data` (MiniJson) ab; alles außer `Runtime/` ist frei von `UnityEngine` und lässt sich mit `dotnet` testen.

## 4. Variantenwahl (Regeln und Rückfall)

Jede erzeugte Datei ist **ein Pass mit fester Keyword-Menge** (`docs/shader-unity-integration.md`, Abschnitt 4). Ein Material kann daher mehrere Shader brauchen: je Pass einen.

**Rolle eines Passes** (`PassRole`): aus dem `LIGHTMODE`-Tag des Passes (`FORWARDBASE` → Forward, `SHADOWCASTER` → Schattenwurf, `FORWARDADD` → zusätzliche Lichter); ohne Tag aus den Keywords (`SHADOWS_DEPTH`/`SHADOWS_CUBE` → Schattenwurf, sonst Forward). Grab-Pässe und `UsePass` werden nicht erzeugt (Abschnitt 10).

**Wahl** je (Shader, Pass), Eingabe: Material-Keywords `M` (aus `m_ShaderKeywords`), Umgebung `E`:

1. **Angefordert** `R = (M ∪ E) ∩ U`, `U` = alle Keywords, die der Pass in irgendeiner Variante kennt. Fremde Material-Keywords (z. B. `_ALPHABLEND_ON` beim `Delphis/Map/Standard`) haben im Original keine Wirkung und werden gemeldet, nicht verlangt.
2. **Exakt:** Variante mit Keyword-Menge `== R` → `Exact`.
3. **Umgebung lockern:** `E` besteht aus `DIRECTIONAL`, `SHADOWS_SCREEN` (Forward) bzw. `SHADOWS_DEPTH` (Schattenwurf) und optional `INSTANCING_ON`. Fehlt eine exakte Variante, werden der Reihe nach `INSTANCING_ON`, dann `SHADOWS_SCREEN` weggelassen (kumulativ), jeweils wieder exakt gesucht → `EnvironmentRelaxed`. Gemeldet wird gegen die volle Anforderung (`MissingKeywords`).
4. **Nächstliegend:** sonst die Variante mit (a) wenigsten fehlenden Material-Keywords, (b) wenigsten fehlenden Umgebungs-Keywords, (c) wenigsten überzähligen Keywords, (d) kleinster Keyword-Menge, (e) Name (ordinal) → `Nearest`; das Ergebnis gilt als **nicht vollständig** (`RemapResult.Complete = false`).
5. **Nichts:** Shader/Pass ohne erzeugte Variante (nicht verpackbar, gestrichen) → `Unavailable`; der Aufrufer nimmt das Ersatzmaterial (`FallbackMaterials` des Feldcodes).

Warum die Umgebung ein Parameter ist: Die Keywords `DIRECTIONAL`, `SHADOWS_SCREEN`, `INSTANCING_ON` kommen im Original vom Zeichenaufruf (Licht, Schatten, Instancing), nicht vom Material. Unsere Varianten haben diese Keywords fest einkompiliert; Unity wählt sie nicht mehr selbst (kein `multi_compile`). Die Voreinstellung entspricht dem Karten-Rendering mit einem Richtungslicht und Bildschirmschatten; `Instancing` ist aus (Abschnitt 8).

**Messung (belegt, alle 640 Bundles `Environments/`):**

| Shader | Materialien | Forward-Pass exakt | Schatten-Pass exakt |
|---|---|---|---|
| `Delphis/Map/Standard` | 9.795 | 9.795 | 9.795 |
| `Delphis/Map/Water` (nur ein Normal-Pass, der Grab-Pass fehlt) | 96 | 96 | – |
| `Delphis/Map/FlowmapBumpWater` / `FlowmapWater` | 42 / 25 | 42 / 25 | – |
| `Delphis/Map/PhotoFrame` | 29 | 29 | – |
| `Delphis/Map/Sky` | 18 | 18 | 18 |
| `Custom/StencilMask` (zusätzlich `FORWARDADD`-Pass: nächstliegend) | 1 | 1 | – |
| `Delphis/Map/LineUVScroll`, `Delphis/Map/Mask` | je 1 | je 1 | – |
| ohne Shadername (m_FileID 0: eingebauter Standard-Shader) | 3 | Ersatzmaterial | – |

Mit `INSTANCING_ON` in der Umgebung sind ebenfalls alle Forward-Pässe exakt (geprüft mit `--instancing`).

**Rückfall-Regeln im Betrieb:** (1) kein Exporteintrag → Ersatzmaterial; (2) Shader nicht aufgelöst → Ersatzmaterial; (3) `Nearest` → Material wird gebaut, `Complete = false` (Aufrufer protokolliert); (4) doppelter Materialname im Bundle → Wahl über die Keyword-Menge, sonst erster Eintrag.

## 5. MaterialRemapper

`Remap(Material source, MaterialRecord rec, RenderEnvironment env)` → `RemapResult` (`Forward`, `ShadowCaster`, `Additional`, `Passes`, `Notes`, `Complete`). Je gefundenem Pass entsteht ein neues Material:

1. **Übernahme (Quelle geladen):** `new Material(source)` (behält die gespeicherten Eigenschaften), dann `shader = <erzeugter Shader>`. **Die gespeicherten Werte der Quelle gelten**, der Export überschreibt nichts (Queue und Werte): er unterscheidet doppelte Materialnamen nicht sicher (13 Gruppen unterscheiden sich nur in Werten). Ohne `source` (nicht geladen): `new Material(shader)`.
2. **Eintrag (ohne Quelle):** Floats und Farben aus dem Export werden gesetzt, und zwar nach dem **Typ, den der Zielshader deklariert** (der Export führt manchmal denselben Namen als Float *und* als Farbe, ein veralteter Eintrag eines früheren Shaders, z. B. `_Reflectivity`; Farben als `SetVector`, ohne Farbraumumrechnung), Kachelung und Versatz je Textur, Texturen über einen `LoadedTextureIndex` (Name + Größe), `renderQueue` aus `m_CustomRenderQueue` (falls ≥ 0).
3. In beiden Pfaden: `enableInstancing` genau dann, wenn die Variante `INSTANCING_ON` hat, Override-Tags (`stringTagMap`).
4. **Forward-Pässe** gehen in `Forward` (sichtbar zuweisen), der **Schattenpass** in `ShadowCaster` (nie sichtbar zuweisen: ohne `LightMode`-Trennung würde er Farbe zeichnen), `FORWARDADD` in `Additional`.

`MaterialRemapper.Verify(Material, MaterialRecord)` vergleicht Floats, Farben (jeweils nur Eigenschaften mit passendem Typ), Texturnamen und Kachelung; in der Zone 422 ergaben beide Pfade **0 Abweichungen**. (Ohne die Typprüfung meldete `Verify` zunächst 30 Scheinabweichungen durch die veralteten Float-Einträge neben Farben; bei dem Wassermaterial `FlowmapBumpWater` ist `_Reflectivity` ein Float 0, der Export enthält daneben eine veraltete Farbe (1, 1, 1, 1).)

## 6. Spiel-Globals (`GameGlobals`)

Namen in `VGlobals`/`PGlobals` der Bundle-Shader (`work/shaders/inventory.json`), die weder Material-Eigenschaft des eigenen Shaders noch von Unity gesetzt sind und (für die Zahlenwerte) als Zeichenkette im Spielcode vorkommen (`work/il2cpp/stringliteral.json`). **35 Namen** (die ältere Angabe „32 von 40“ in `docs/shader-inventar.md` zählte zusätzlich die Shader aus `extraShaders` und schloss die Texturen aus; hier stehen Zahlen und Texturen zusammen, `_Color`, `_Cutoff`, `_ClipRect` und die von Unity/UI gesetzten `*_TexelSize`, `_TextureSampleAdd`, `_UIMaskSoftness*` nicht):

| Art | Namen |
|---|---|
| Float (10) | `_CloudShadowBase`, `_CloudShadowScale`, `_GlobalLightPower`, `_GlobalBumpScale`, `_EmissionScale`, `_EmissionThreshold`, `_VertexColorScale`, `_AdditionalBlurry`, `_BloomThreshold`, `_RcpGridSize` |
| Vektor (12) | `_CloudParam`, `_ShadowColor`, `_ReflectorColor`, `_CharacterLightColor`, `_CharacterReflectorColor`, `_PokeLightColor`, `_PokeReflectorColor`, `_UVOffset`, `_FocalCoefficient`, `_BlurOffsetX`, `_BlurOffsetY`, `_Corner` |
| Matrix (2) | `_ReflectionVP`, `_EnvMatrix` |
| Textur (11) | `_CloudShadowTex`, `_EnvironmentMap`, `_ReflectionTex`, `_SnowTex`, `_SnowNormalTex`, `_NoiseTex`, `_OpaqueDepthTexture`, `_GlobalDepthTexture`, `_DelayFrameTexture`, `_FocusTex`, `g_BackgroundTexture` |

`GameGlobals` prüft Name und Art (falscher Name oder falsche Art → `ArgumentException`), reicht an eine `IGlobalSink` weiter (Unity: `UnityGlobalSink` mit `Shader.SetGlobal*`), führt Buch (`CountSet`, `Unset`) und kann `SetDefaults()` (Platzhalter: Multiplikatoren 1, Matrizen Einheit, sonst 0; Texturen bleiben ungesetzt, Unity bindet dann seine Standardtextur).

**Das sind keine Originalwerte.** Die Werte kommen im Original aus dem Spielzustand (Wetter, Tageszeit, Kartenlicht); sie sind noch nicht ermittelt. Wie stark das ins Bild geht, zeigt Abschnitt 7.1: allein `_ShadowColor` = Weiß statt Schwarz hebt den Bildmittelwert von (29, 38, 22) auf (69, 85, 51).
Nicht in der Liste, weil Unity sie setzt: `_Time`, `_WorldSpaceCameraPos`, `_ProjectionParams`, `_ScreenParams`, `_ZBufferParams`, `_WorldSpaceLightPos0`, `_LightColor0`, `unity_*`, `glstate_matrix_projection`, `_ShadowMapTexture`, `_CameraDepthTexture`, `_LightTexture0/B0`, `_GrabTexture`.

## 7. Rendertest und Treue (Lab)

### 7.1 Zone 422 mit umgebauten Materialien

Aufbau (`Assets/Editor/MatRender.cs`, nur im Lab): Prefab `area001` instanziieren (Materialien haben den Fehlershader, nichts Originales wird gezeichnet), Blockfilter wie in `FieldMapBuilder` (Zone 422 = Blöcke (3, 27) und (3, 28), Radius 1 → Container T01, R201, L01; 9 Container verworfen), alle Renderer-Slots über `MaterialRemapper` umbauen, `GameGlobals.SetDefaults()`, ein weißes Richtungslicht (Euler 50/−30/0, weiche Schatten), Kamera nach den Stammdaten der Zone (Neigung 45°, Sichtfeld 17,5°, Abstand 30, Brennpunkt Zelle (116, 886) = Welt (−116, 1,5, 886)), 1280 × 720, Gamma.

| Messgröße | Wert |
|---|---|
| Renderer-Slots / verschiedene Materialien | 1.357 / 34 |
| vollständig / nächstliegend / ohne Variante | 34 / 0 / 0 |
| Abweichungen Material ↔ Export (`Verify`) | 0 (Pfad „Übernahme“ und Pfad „Eintrag“) |
| Textur-Fehlgriffe (Pfad „Eintrag“) | 0 |
| Umbauzeit | 18 bis 58 ms (Schatten-Materialien: 33) |
| Magenta (Ersatz) im Bild | 0,0 % |
| Bildmittelwert RGB, Voreinstellung (`_ShadowColor` 0) | (29, 38, 22) |
| Bildmittelwert RGB, `_ShadowColor` = Weiß | (69, 85, 51) |
| Bildmittelwert, zusätzlich `_ShadowMapTexture` = Weiß | unverändert |
| Unterschied „Übernahme“ gegen „Eintrag“ (letzter Stand, `_ShadowColor` Weiß) | 62.393 von 921.600 Pixeln (Maximum 164, Mittel 0,10 von 255); zwei Läufe **desselben** Pfads unterscheiden sich um 80.275 Pixel (Maximum 167, Mittel 0,18): die Differenz ist Rauschen durch zeitabhängige Shader (`_Time`, Wind-Schwingen `_SWING_ON`), kein Pfadunterschied |

Das Bild (`work/matremap/shots/zone422_*.png`, nicht im Repo) zeigt das Haus von Twinleaf mit Dach, Schornstein, Wald, Wiese und Pfad, Texturen und Kachelung der Bundles; mit schwarzer `_ShadowColor` bleibt es fast ganz im „Schatten“ (dunkel).

**Referenz:** Es gibt keine Ryujinx-Bildschirmfotos der Zone (die PNG-Dateien unter `Ryujinx/` sind Speicherstand-Symbole). Ein Pixelvergleich mit der Switch-Wiedergabe ist deshalb **nicht möglich**; die Beleuchtung (Lichtfarbe, Schattenpfad, Spielwerte der Globals) ist ohnehin noch nicht original. Das Bild belegt, dass Material → Shader → Texturen funktioniert, nicht, dass es dem Original gleicht.

### 7.2 Echte Materialwerte, Unity gegen Harness (belegt)

Fälle `mat1`…`mat5` in `work/shaders/unity-lab/run_cases.py`: `Delphis/Map/Standard`, Float- und Farbwerte aus dem Export eines echten Materials in die Konstantenpuffer (Modus `array`: Unity und Harness bekommen **dieselben** Wörter), Variante vom Resolver gewählt, synthetische Texturen (Schachbrett/Verlauf), 256 × 256. Die Textur-Globals (`_ShadowMapTexture`, `_CloudShadowTex`, …) werden auf beiden Seiten gleich gefüllt; Unity-Zustand `_Cull = 0` wie der Harness.

| Fall | Material (Art) | gewählte Keywords | größte Abweichung |
|---|---|---|---|
| `mat1` | Haus (`_CASCADE_SINGLE`) | `DIRECTIONAL SHADOWS_SCREEN _CASCADE_SINGLE` | **0** von 255 |
| `mat2` | Blume (`_ALPHATEST_ON _CASCADE_SINGLE _SWING_ON`) | + `_ALPHATEST_ON`, `_SWING_ON` | **0** |
| `mat3` | Innenraum (`_CASCADE_EMISSION`) | `… _CASCADE_EMISSION` | **0** |
| `mat4` | Boden (`_CASCADE_MULTI`) | `… _CASCADE_MULTI` | **0** |
| `mat5` | Tür (`_CASCADE_SINGLE`, Umgebungsabbild) | `… _ENVIRONMENTMAPENABLE_ENVIRONMENTMAP` | **0** |

Das belegt, dass der Wrapper mit echten Materialwerten **dieselben Pixel wie unsere MSL** liefert (mit den Pragmas für exakte Arithmetik). Die Treue unserer MSL gegen die Switch-Wiedergabe steht in `docs/shader-translator.md` (Ryujinx-SPIR-V-Referenz), nicht hier. Der Modus `named` (Unity bestimmt Matrizen, Zeit, Licht selbst) ist für `Delphis/Map/Standard` nicht vergleichbar: die Harness-Seite kann `_Time`, `_WorldSpaceLightPos0` u. a. nicht gleich setzen.

## 8. Instancing: „Einheitsmatrix“ (Untersuchung)

Frühere Messung (`docs/shader-unity-integration.md`, 13.1): zwei Instanzen erschienen in Unity mit Einheitsmatrix. Heute:

| Prüfung | Ergebnis |
|---|---|
| Fall `inst` (`Custom/StencilMask`, `DIRECTIONAL INSTANCING_ON`, zwei Instanzen, `CommandBuffer.DrawMeshInstanced`) Unity ↔ Harness, Modus `named` | **0 von 255**, Fläche x 38…206, 16.270 Pixel in beiden Bildern |
| derselbe Fall mit Inventar ohne `LIGHTMODE`-Tags (alter Stand) | ebenfalls 0 von 255 |
| Kontrollshader von Hand (`UnityCG.cginc`, `UNITY_SETUP_INSTANCE_ID`, `multi_compile_instancing`) und erzeugter `Delphis/Map/Standard`-Shader (`INSTANCING_ON`) mit denselben zwei Matrizen, Kamera, `CommandBuffer.DrawMeshInstanced` | beide: 16.256 Pixel, x 13…229, y 64…178, getrennte Quadrate (Lücke in der Mitte) |
| Material **ohne** `enableInstancing` | `DrawMeshInstanced` wirft „Material needs to enable instancing“ (kein stilles Einheitsmatrix-Bild) |

Schluss: Der erzeugte Instancing-Block (`UnityInstancing_PerDraw0`, `unity_Builtins0Array`, 128 Byte Schrittweite, `unity_BaseInstanceID`) ist für Unity 6.3 richtig; die Matrizen kommen an. **Warum die frühere Messung Einheitsmatrizen zeigte, ist nicht bewiesen.** Hinweis: `XnuLab.cs` (Zeichenfall des Labors) wurde nach der Messung noch geändert und enthält jetzt `mat.enableInstancing = true` vor dem Zeichnen; *vermutet* ist, dass dieser Schalter damals fehlte und Unity eine nicht-instanzierte Variante zeichnete. **Nicht gemessen:** Instancing über das automatische Batching von MeshRenderern (statt `DrawMeshInstanced`); daher steht `RenderEnvironment.Instancing` standardmäßig auf `false`. Der Fall `inst2` (`Delphis/Map/Standard`) ist als Bildtest nutzlos: beide Bilder sind leer (0 Pixel), die Gleichheit ist leer.

## 9. Tests

| Gruppe | Anzahl | Inhalt |
|---|---|---|
| `RenderRemapTests` (rein, auch per dotnet) | 11 | gemeinsame Fallliste (14 Fälle: exakt, fremdes Keyword, Instancing exakt/gelockert, Bildschirmschatten gelockert, nächstliegend mit Gleichstand, Schattenpass, Unlit, Pass/Shader ohne Variante, SubShader 1, ForwardAdd, LightMode gegen Keywords), Index (fehlerhafte und SubShader-1-Einträge fehlen), Reihenfolge-Unabhängigkeit, Katalog-Parser, doppelte Namen, Globals (Vollständigkeit, Art-Prüfung, Standardwerte, Senke), Umgebung |
| `RenderRemapUnityTests` | 7 | Umbau ohne Quelle (Export setzt Float, Farbe nach Shadertyp trotz veraltetem Float gleichen Namens, Textur, Kachelung, Queue, Tag), mit Quelle (gespeicherte Werte und Queue bleiben, auch gegen den Export), Instancing-Schalter, fehlender Shader/Eintrag, nächstliegende Variante nicht vollständig, Texturindex, Globals gegen `Shader.GetGlobal*` (Stellvertreter-Shader `Sprites/Default`) |
| `scripts/tests/test_material_variants.py` | 5 | dieselbe Fallliste gegen die Python-Referenz, Rollen, Export-Umwandlung mit synthetischem TypeTree, unbekannter Shader, lokaler Shader-Verweis |

Die Fallliste `unity/Assets/Tests/EditMode/Fixtures/variant_resolution_cases.json` hält beide Umsetzungen gleich (Python und C# lesen dieselbe Datei). Gelaufen: Lab-Editor (18 von 18), `dotnet test work/dotnet-render` (11), `python3 -m unittest discover -s scripts/tests` (OK). Der Gesamtlauf `Xnu.Tests.EditMode` im Haupt-Editor steht aus (375 + 18 erwartet).

## 10. Lücken (Stand)

1. **Schatten.** (a) Unser Forward-Pass trägt jetzt `LightMode=ForwardBase`; `_ShadowMapTexture` (Bildschirmschatten) erzeugt Unity aber nur für Pässe mit `multi_compile_fwdbase`, *vermutet*; ein weißer Ersatz ändert das Bild nicht (7.1). (b) Der **Schattenwurf** steckt in einem eigenen Shader (`SHADOWCASTER`); als zweiter Material-Slot änderte er das Bild nicht (Mittelwert gleich, kein Schattenbild geprüft). Eine saubere Lösung: ein Material = ein Shader mit mehreren Pässen (`UsePass` auf die erzeugten Pässe oder ein Wrapper, der Pässe gruppiert). Ungeprüft.
2. **Mehrpass-Shader.** `Delphis/Map/Water`, `FlowmapWater` u. a. haben Grab-Pässe (`_BackgroundTexture`); der Wrapper erzeugt nur Normal-Pässe. Wasser braucht eine eigene Aufnahme des Hintergrunds (`CommandBuffer`) und die Globals `_OpaqueDepthTexture`, `_ReflectionTex`.
3. **Umgebungs-Keywords fest.** Licht (`DIRECTIONAL`, Punktlichter, Lichtkarten) wählt im Original Unity je Zeichenaufruf; bei uns die Voreinstellung (Abschnitt 4). Szenen mit mehreren Lichtern, Lichtkarten oder Lichtsonden brauchen weitere Varianten (`FORWARDADD`-Pass: Rolle erkannt, aber nicht angebunden).
4. **Spielwerte der Globals** fehlen (Abschnitt 6): Licht-/Reflektorfarben, Wolkenparameter, Schattenfarbe. Ohne sie ist die Karte zu dunkel oder zu hell.
5. **Texturen aus anderen Bundles.** 52 von 30.609 Texturverweisen der Materialien (`FileID ≠ 0`) haben im Export keinen Namen; sie liegen in einem Nachbar-Bundle (Abhängigkeit des Katalogs). Auflösung über die externe Dateiliste + Katalog fehlt. Namensgleiche Texturen gleicher Größe könnten verwechselt werden (in den geprüften Bundles kein Fall: 0 Fehlgriffe).
6. **Player-Einbindung der Shader.** Im Player findet `Shader.Find` nur Shader, die im Build enthalten sind (Verweis aus einem Asset, `Resources`, Always Included). Die erzeugten Shader liegen in `unity/Assets/GameData/Shaders` (gitignoriert, Stufe `shaders`); ein Build-Schritt, der sie einschließt (z. B. in einen `Resources`-Ordner oder ein Shader-Bundle), und die zugehörige `variants.json` fehlen. Nicht gebaut/geprüft.
7. **Strippen.** `--used` von `shader_wrap_all.py` schlüsselt nach (Shader, Keywords) **ohne Pass**; die benutzte Menge erzeugt deshalb gelegentlich zusätzliche Pässe mit gleicher Keyword-Menge (61 statt 60 Dateien). Harmlos, aber ungenau. Die Menge für das ganze Spiel steht aus: nur `Environments/` ist exportiert (60 Varianten); Charaktere, Kampf, UI, Effekte fehlen (Exporter ist allgemein, nur nicht ausgeführt).
8. **Materialien ohne Shadernamen** (3, eingebauter Standard-Shader) und **nicht verpackbare Varianten** (16, `Mitake/MitakeStandardPetrify`) → Ersatzmaterial.
9. **Doppelte Materialnamen** (22 Gruppen im selben Bundle: 4 inhaltsgleich, 5 mit anderen Keywords, 13 nur mit anderen Werten): der Export-Eintrag wird über Namen + Keywords gewählt, sonst der erste. Für Shader und Variante genügt das (gleicher Shader in allen 22 Gruppen), die Werte kommen im Pfad „Übernahme“ aus dem geladenen Material. Im Pfad „Eintrag“ (ohne Quelle) könnte der falsche Wert gewählt werden; besser wäre ein Schlüssel über die PathID, die zur Laufzeit nicht verfügbar ist.
10. **Instancing-Bild über Renderer-Batching** nicht gemessen (Abschnitt 8); Partikelbild (`FxSystem/Particle`) weiterhin offen (`docs/shader-unity-integration.md`, 13.2).
11. **Zeitabhängigkeit:** Bildvergleiche der Karte sind wegen `_Time` nicht deterministisch; der Harness-Vergleich (7.2) friert die Konstanten ein.

### 10a. Nachtrag 2026-10-19 (`ap-effects-fidelity`, Teil 1): Stand der Lücken 1, 2, 4, 5

Ausführlich in `docs/shader-globals.md`.

| Lücke | Neuer Stand |
|---|---|
| 1 Schatten | **Geschlossen** (Lab gemessen). Der erzeugte `SHADOWCASTER`-Pass wirft Schatten, Unitys Bildschirmschatten erreicht unseren Forward-Pass ohne `multi_compile_fwdbase`. Die Annahme „ein weißer Ersatz ändert das Bild nicht“ (7.1) hatte eine andere Ursache: der Platzhalter `_CloudShadowBase` = 0 setzt den Wolkenterm im Shader auf 0, und `min(Schatten, Wolkenterm)` ist dann immer 0 — die ganze Karte lag „im Schatten“, egal was in `_ShadowMapTexture` stand. Mit `_CloudShadowBase` = 1 − Szenenwert erscheint der Würfelschatten. **Ein Material = ein Shader mit mehreren Pässen:** `shader_wrap.py --also`, `shader_wrap_all.py --combine-shadow` (61 benutzte Varianten, 48 mit Schattenpass, 61 von 61 kompilieren); `RemapResult.ShadowEmbedded` ersetzt das getrennte Schattenmaterial; `UsePass` der Mitake-Shader wird übernommen. |
| 2 Mehrpass-Shader / Grab | **Geschlossen für GrabPass.** Das Original benutzt Unitys `GrabPass` (kein eigener CommandBuffer); der Wrapper schreibt ihn jetzt vor den Pass (`Delphis/Map/Water` im Lab: Hintergrund scheint durch). `FlowmapWater` hat keinen Grab-Pass, sondern liest `_OpaqueDepthTexture`/`_ReflectionTex`/`_ReflectionVP`: `DepthCaptureDriver`, `ReflectionCameraDriver`. |
| 4 Spielwerte der Globals | **Quellen geklärt**, 26 von 35 umgesetzt (`EnvironmentState`): Werte aus `EnvironmentSettings` (175 Assets, je Zone über `MapInfo.RenderSettings`) und aus dem Szenenobjekt `EnvironmentController`. Offen: Szenenobjekt-Werte nicht ausgelesen, Nachbearbeitungs-Globals. Zone 422 mit den abgeleiteten Globals: Bildmittel (83, 104, 62) am Tag statt (26, 34, 20) mit Platzhaltern. `_GlobalLightPower` im Ruhezustand ist 0, nicht 1 (Platzhalter korrigiert). |
| 5 Texturen aus Nachbar-Bundles | **Geschlossen:** `material_export.py --resolve-external` löst alle 52 Verweise auf (5 Bundles, alle `Dpr/common_resources`), `MaterialTextureRef.ExternalBundle`. |

Neu bei den Dateien: `scripts/environment_export.py`, `scripts/ghidra/{StringXrefs,CallersOf}.java`, `scripts/ghidra/run_headless.sh`; geändert: `shader_wrap.py` (`--also`, `--no-aux`, GrabPass/UsePass), `shader_wrap_all.py` (`--combine-shadow`), `material_export.py` (`--resolve-external`, `export_bundle` liefert `(Materialien, externe Pfade)`), `GameGlobals.cs` (`_GlobalLightPower`-Platzhalter 0), `MaterialCatalog.cs`, `ShaderVariantIndex.cs`, `Runtime/MaterialRemapper.cs`, `Runtime/UnityGlobalSink.cs` (Textur-Platzhalter).

### 10b. Nachtrag 2026-10-19 (`ap-effects-fidelity`, Teil 2): Ursachen von „Bild schwarz“ und „Editor hing“

Fragen aus `docs/feld-szene-2.md`, Kapitel 6: Warum war das Bild mit dem Umbau schwarz, und warum reagierte der Haupt-Editor im Spielmodus nicht mehr (> 8 Minuten, 175 % CPU, Hauptthread in der IMGUI-Zeichnung, Pipeline-Befehle in Zeitüberschreitung)? Alles im Lab (`work/unity-shader-lab`, eigener Editor, nur unsere 61 erzeugten Shader, kein Original-Shader geladen) nachgebaut: (a) Zone 422 aus Prefab + Materialumbau, (b) der echte `FieldController` (Quellen aus dem Repo ins Lab kopiert, `XNU_GENERATED_SHADERS=1`: „Umbau (Shader 61/61, 124 Materialeinträge)“, mit Spielerfigur, NPC-Markern, `DisplayController`, Streaming). Die Bilder entstehen per `RenderTexture` (1280 × 720, Alpha ignoriert); Hilfsklassen `Assets/Lab/ReproRunner.cs` und `Assets/Editor/{CompileBench,FirstDraw}.cs`, Konfiguration, Logs, Proben und Bilder unter `work/matremap/` (nicht im Repo).

**Befund 1 – schwarz = kein Richtungslicht (belegt).** Matrix für Zone 422 (34 Materialien, 3 Blöcke, Kamera nach den Stammdaten, Gamma, Bildmittel RGB):

| Licht | Globals | Bildmittel |
|---|---|---|
| keines | Platzhalter (`SetDefaults`) | **(0, 0, 0)** |
| keines | alle null (Unity-Standard) | **(0, 0, 0)** |
| Richtungslicht (weiß, 50/−30/0, ohne Schatten) | alle null | (31, 39, 23) |
| Richtungslicht | Platzhalter | (37, 49, 28) |
| Richtungslicht | Spielwerte Zone 422, Stunde 12 | (83, 104, 63) |
| dasselbe mit weichen Schatten (4 Kaskaden, Distanz 20) | Spielwerte, Stunde 12 | (83, 104, 63), im Mittel unverändert |

Ohne Licht sind **alle** Pixel schwarz (auch Himmel und Alphatest-Laub): `_LightColor0` ist 0, das Original-Shaderprogramm multipliziert damit. Das erklärt den ersten Lauf im Haupt-Editor (damals gab es noch keine `FieldSun`). Der echte `FieldController` im Lab liefert mit Licht (37, 49, 29) – dasselbe Bild wie der Nachbau (a); ohne Licht (0, 0, 0). Die **Platzhalter-Globals machen das Bild nur dunkler, nie schwarz** (Abstand (31, 39, 23) → (83, 104, 63) mit den Spielwerten aus `EnvironmentDriver`, siehe `docs/shader-globals.md`, Abschnitt 6.4).
Falle im Lab selbst: `FindObjectsByType<Light>` liefert auch Objekte, die am Frame-Ende mit `Destroy` zerstört werden. Zerstörte ich das Szenenlicht (`Destroy`) und startete danach den `FieldController` im selben Frame, wählte dieser das sterbende Licht als `_sun` – Ergebnis (0, 0, 0) mit „vorhandenem“ Licht. Mit `DestroyImmediate` stimmt das Bild. (Die Szene `FieldTest2` hat kein Licht, dort legt `EnsureRenderEnvironment` die `FieldSun` an; wer ein Szenenlicht hinzufügt oder zerstört, sollte `SunLight.Ensure` benutzen.)
Prüfreihenfolge aus dem Auftrag (Konstanten-/cbuf-Bindung, Globals, Textur-Bindung, Lichtfarbe/`_GlobalLightPower`, Blend/ZWrite/Cull, Gamma, Clip/Y-Flip/Windung): Mit Licht ist das Bild der Zone 422 (Haus von Twinleaf, Dach, Schornsteine, Wald mit Alphatest-Laub, Wiese, Weg, Briefkasten; `work/matremap/shots/mx_env12.png`) in allen diesen Punkten unauffällig – Texturen und Kachelung richtig zugeordnet, Haus nicht gespiegelt und nicht von innen gezeichnet (Windung/Cull), kein Durchscheinen hinter Laub (Blend/ZWrite), Helligkeit plausibel im Gamma-Projekt; die Konstantenbindung ist durch den Harness-Vergleich (7.2, 5 von 5 bitgleich) belegt. Es blieb also **ein** Fehler, und der war die fehlende Lichtquelle.
Weitere Beobachtung: `ScreenCapture.CaptureScreenshotAsTexture`/`capture_game_view` lieferten in den ersten Sekunden einfarbig Cyan (0, 255, 255) und bei verkleinertem Kamera-Rechteck (`DisplayController`, 16:9) einen Rand mit Alpha 0; derselbe Zustand per `RenderTexture` war richtig (37, 49, 28). Für Bildmessungen deshalb `Camera.Render` in eine `RenderTexture` benutzen, nicht den Bildschirm abgreifen.

**Befund 2 – der „Hänger“ ist kein Shader-Problem, sondern `run_tests` im Spielmodus (reproduziert).**
- Das Editor-Log der Sitzung (`work/main-editor.prev.log`, 114.101 Zeilen) enthält **kein** `Compiling shader "XNU/Generated/…"` (0 von 245 Kompilierzeilen, alles Unity-Eigenes), keine Compiler-Schleife, keine Metal-Fehler. Nach dem Laden der Zone („Karte gebaut … Umbau (Shader 61/61 …): 1.991 ms“, „Spielerfigur … 2.047 ms“) steht als nächstes: `[PipelineTestRunner] Running 623 tests`, danach `InvalidOperationException: This cannot be used during play mode`, `Test tree is not available for PostbuildCleanupTask`, `Test execution timed out, cancelling...`. Der Editor stand also **im Spielmodus**, als der Testlauf angestoßen wurde.
- Reproduktion im Lab: Feldszene im Spielmodus (60 Bilder/s, Hauptthread zeichnet das Game-Fenster), dann `run_tests` → `Pipeline command 'run_tests' timed out after 100000ms`; **alle weiteren Pipeline-Befehle** (`editor_status`, `editor_stop`) laufen ebenfalls in die Zeitüberschreitung (der Testlauf blockiert die Befehlsschlange), der Editor selbst läuft weiter (185 % CPU, Probe `sample`: Hauptthread in `GUIView::DoPaint` → `GameView.OnGUI` → `RenderPlayModeViewCameras`, wie in der Haupt-Sitzung beschrieben). Probe: `work/matremap/samples/lab_testsinplay.txt`.
- **175 bis 200 % CPU und „Hauptthread in der IMGUI-Zeichnung“ sind der normale Spielmodus** (Lab, Feldszene mit erzeugten Shadern, 60 Bilder/s: Editor 190 bis 215 % CPU; Probe ohne Hänger `samples/lab_cold1.txt` zeigt dieselbe Hauptthread-Kette). Das Merkmal taugt nicht als Hängerbeleg.
- **Regel:** Vor `run_tests` immer `editor_stop` und warten, bis `editor_status` `playMode: stopped` meldet; Pipeline-Testläufe nie bei laufendem Spielmodus starten.
- Nebenbefund im selben Log: Nach einem Skript-Neuladen **im** Spielmodus (`ForceDomainReload` während des Spiels) warf `FieldController` 3.129 `NullReferenceException` (1.043 in `TickLogic`, 2.086 in `OnGUI`; Zustand der Komponente nach dem Neuladen weg). Das kostet Zeit pro Bild, ist aber nach rund 1.043 Bildern (≈ 17 s) vorbei und nicht die Ursache des Hängers.

**Befund 3 – Kompilierung und Varianten sind kein Faktor (gemessen).**
- Wrapper: `shader_wrap.py` schreibt **kein** `multi_compile`/`shader_feature`; die 61 kombinierten Shader enthalten 0 `#pragma multi_compile*` und 0 `shader_feature` (nur `multi_compile_instancing`, wenn die Variante `INSTANCING_ON` trägt – keine der 61 tut es). Je Shader und Pass genau **ein** Keyword-Satz, keine Variantenexplosion. Eine Änderung am Wrapper war deshalb nicht nötig.
- Zeit der ersten Zeichnung eines großen Shaders (`Delphis/Map/Standard`, `skip_optimizations`, `disable_fastmath`): Unity-Kompilierung per `ShaderVariantCollection.WarmUp` beider Pässe bei leerem `ShaderCache` 0,36 s, danach erste Zeichnung (Metal-Pipeline) 0,33 s; ein Quelltext ohne `disable_fastmath` (neuer Metal-Quelltext, leerer Cache) 0,04 s bis zur ersten Zeichnung. Die „2,8 s je Variante“ aus dem Übersetzertest betreffen das Übersetzen der Rohquelle, nicht Unitys Erstzeichnung. Fünf Zonen nacheinander (425, 54, 367, 422, 354) mit geleertem `ShaderCache`: Ladezeit 0,35 bis 1,0 s je Wechsel, nie ein Stillstand; Bildrate 60/s.
- Grafiklast: Zonen bei 3456 × 1944 (Vollbild eines 16-Zoll-MacBooks) 37 bis 58 ms je Bild einschließlich Rücklesen (422: 58, 54: 49, 425: 37 ms, je 10 Aufrufe in 372 bis 581 ms) – weit von einem Hang entfernt.

**Änderungen aus Teil 2:** `Render/RenderChecks.cs` (Unity-freie Regeln „kein Licht / Licht ohne Intensität / Globals ungesetzt / mehrere Lichter“, 7 Tests in `RenderChecksTests`, `dotnet test work/dotnet-render` 36 von 36 grün), `Render/Runtime/SunLight.cs` (`SunLight.FindActive/Ensure/Collect`; sieht auch `DontSave`-Lichter wie die `FieldSun`, die `FindObjectsByType` auslässt; `RenderHealthWatch` meldet jedes Problem einmal als Warnung) und 3 Unity-Tests (`RenderSunTests`). Lab-Gesamtlauf: **47 von 47** grün (37 vorher + 10). Lab-Probe: ohne Licht meldet `RenderHealthWatch` `[NoSun | GlobalsUnset]` bei Bildmittel (0, 0, 0); mit `SunLight.Ensure` und Platzhaltern keine Meldung, Bildmittel (37, 49, 28). Der Feldcode (`Scripts/Field`, gehört einem anderen Auftrag) ruft sie noch nicht auf: `FieldController.EnsureRenderEnvironment` sollte `SunLight.Ensure(transform)` benutzen und `RenderHealthWatch` anhängen. `shader_wrap.py` und `shader_translator/` blieben unverändert (kein Fächer, keine Ursache dort). Die 624 bestehenden Tests sind nicht angefasst (im Haupt-Editor nicht gelaufen; dort 631 erwartet).

**Lab-Betrieb (Erfahrung):** Der Hänger trat im Lab **zweimal** auf (einmal bewusst, einmal versehentlich nach einem Probelauf, der den Spielmodus offen ließ); beide Male blockierte `run_tests` die Befehlsschlange > 17 Minuten ohne Erholung und der Editor musste mit `kill <PID>` beendet werden. Nach dem `kill` bleibt `Temp/__Backupscenes` zurück; der neue Editor wartet dann ohne Fenster-Rückmeldung auf einen Wiederherstellungsdialog (Pipeline „No Pipeline instance“): `Temp/` des Projekts löschen, dann `unity open`.

**Lücken (ehrlich):** (1) Die Haupt-Sitzung selbst ist nicht wiederholbar; der Mechanismus (Testlauf im Spielmodus → Befehlsschlange blockiert) ist im Lab nachgestellt und passt zu Log und Probe, einen Zeitgeber der Haupt-Sitzung („> 8 Minuten“) gibt es nur aus dem Bericht. (2) Es gibt weiter keine Switch-Referenz; das Bild ist plausibel, nicht bewiesen original. (3) Zone 367 liefert im `FieldController`-Lab nur Hintergrundfarbe (Bildmittel (115, 157, 217)) und die Spielerfigur: die Karte erscheint nicht (Spawn/Streaming, nicht Render; dem Feldcode melden). (4) Weiche Schatten verändern das Bildmittel nicht messbar (Würfeltest in `docs/shader-globals.md`, Abschnitt 6, zeigt sie); ein Schattenbild der Zone 422 mit eigener Auswertung steht aus. (5) Spielwerte der Szenenobjekte (`EnvironmentController`) fehlen weiter (siehe `shader-globals.md`).

## 11. Änderungen an bestehenden Dateien

- `scripts/shader_inventory.py`: Pass-Tags aus `m_State.m_Tags` übernehmen (`LIGHTMODE`). Vorher stand dort immer `{}` (der Pass-eigene `m_Tags` ist leer), die erzeugten Shader hatten kein `LightMode`. Im Inventar jetzt: 23 × `FORWARDBASE`, 7 × `SHADOWCASTER`, 3 × `FORWARDADD`; sonst bleibt das Inventar gleich (geprüft: alle anderen Felder identisch). `work/shaders/inventory.json` wurde neu erzeugt (2 s).
- `scripts/shader_wrap_all.py`: `variants.json` enthält je Eintrag `lightMode`.
- `unity/Assets/Tests/EditMode/Xnu.Tests.EditMode.asmdef`: Verweis auf `Xnu.Render` (der Verweis auf `Xnu.Probe` stammt von einer anderen, noch offenen Änderung).

## 12. Reproduktion

```sh
export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer
# 1. Materialien exportieren (Beispiel: alle Karten-Bundles)
PYTHONPATH=tools/pydeps python3 scripts/material_export.py --out work/materials --dir Environments
# 2. benutzte Varianten bestimmen und nur diese erzeugen
python3 scripts/material_variants.py --materials work/materials --used-out work/materials/used_variants.json --report work/materials/variants_report.json
python3 scripts/shader_wrap_all.py --out unity/Assets/GameData/Shaders --used work/materials/used_variants.json
# 3. Laufzeit (Beispiel)
#   var idx = ShaderVariantIndex.FromJson(File.ReadAllText(".../variants.json"));
#   var catalog = new MaterialCatalog(); catalog.LoadJson(File.ReadAllText(".../<Bundle>.json"));
#   var tex = new LoadedTextureIndex(); tex.AddAllLoaded();
#   var remap = new MaterialRemapper(new ShaderVariantResolver(idx), null, tex.Find);
#   var rec = catalog.Find(bundleName, material.name, material.shaderKeywords);
#   var result = remap.Remap(material, rec);   // result.Forward[0] statt des Originalmaterials zuweisen
#   new GameGlobals(new UnityGlobalSink()).SetDefaults();   // dann die Spielwerte setzen
# Tests
python3 -m unittest scripts/tests/test_material_variants.py
dotnet test work/dotnet-render        # Wegwerfprojekt, kompiliert Render/*.cs + Tests ohne Unity
```

`material.shaderKeywords` eines Bundle-Materials ist die Menge, die Unity beim Laden behält (Abschnitt 2); die Suche im Katalog nutzt sie nur zur Auswahl bei doppelten Namen. Zeichen nie das Original-Material selbst zu (Fehlershader), und nie das Shader-Bundle laden (`BundleProvider.DependencyFilter`, `docs/feld-szene-1.md`, Abschnitt 8).
