# Sichtprüfung 2: Charaktere, Himmel, Nachbearbeitung, Helligkeitsfehler, Schatten (Todo `ap-effects-fidelity`, Teil 4)

Stand: 2026-10-19, Unity 6000.3.26f1 (Lab-Editor `work/unity-shader-lab`, nicht der Haupteditor), Built-in-Pipeline, Gamma, Metal, Apple M1 Pro. Es werden **nur** unsere erzeugten Shader gezeichnet (119 von 120 benutzten Varianten übersetzbar), kein Original-Shader geladen, **kein Ton**. Bilder, Exporte, erzeugte Shader und Logs liegen unter `work/` (`work/effects/shots/`, `work/materials_all/`, `work/shaders/combined_all/`), nicht im Repo; hier stehen Zahlen und Beschreibungen. Bildmessungen: `Camera.Render` in eine `RenderTexture` (1280 × 720), Bildmittel RGB, Zone 422, Stunde 12, Zeit eingefroren (`Time.timeScale = 0`), sofern nicht anders genannt.

Markierung: **belegt** = gemessen oder im Quelltext/Pseudocode gelesen, *vermutet* = Schluss ohne Test.

## 1. Ergebnis in Zahlen

| Frage | Ergebnis |
|---|---|
| Material-Export über `Environments/` hinaus | **Alle** Katalog-Gruppen exportiert (`material_export.py --resolve-external`, rund 20 s gesamt): Charaktere **412 Bundles, 2.105 Materialien**; Pokémon **3.038 Bundles, 17.963 Materialien**; Effekte 2.716 Bundles, 13.629 Materialien; UI 25 Bundles, 119 Materialien; Rest (Dpr, Contest, Fureai, …) 35 Bundles, 225 Materialien. 72.198 externe Texturverweise der Pokémon-Materialien und 14.335 der Effekte: **0 offen**. 0 Material ohne Shadername in Charakteren und Pokémon (UI/Dpr/GMS: 49 Materialien mit eingebautem Standard-Shader). |
| Deckung durch Varianten/Wrapper | Charaktere **2.105 von 2.105**, Pokémon-Feld/Kampf **15.232 von 15.232** (beide Ordner je 7.616), Pokémon-Statuen **148 von 2.731** (2.583 brauchen `Mitake/MitakeStandardPetrify`, Übersetzer meldet `hlsl: subgroup shuffle`, Abschnitt 6). Effekte: 13.482 Materialien mit `FxSystem/Particle` (**1.993 Varianten**) nicht erzeugt (nur gezählt, Abschnitt 6), 147 andere abgedeckt. |
| Benutzte Varianten (`used.json`) | Charaktere **13**, Pokémon **10**, UI 19, Dpr 29, Effekte ohne Partikel 15; Umgebung 60; zusammen mit den Laufzeit-Schlüsselwörtern (Abschnitt 2.3) **120 Varianten, 119 erzeugt**, 119 kompilieren im Lab (`Shader 119/119`). |
| Figur und Gegner im Lab | Spielerfigur `fc0001_00` **13 Materialien mit `Delphis/Character/Standard`** (2 Varianten), NPC `fc2039_00` 5 von 5, Pokémon `pm0387_00_00` 7 von 7 (`Mitake/MitakeStandardBumpShader`, 2 Varianten). Abschnitt 3. |
| Himmel | Original: **kein Skybox-Material**, Kamera löscht mit Schwarz (Alpha 0); der Himmel ist eine Kugel mit `Delphis/Map/Sky` (22 Bundles `Environments/bg/arenas/sky/…`). Im Lab gezeichnet: 3 von 3 Kugeln. Abschnitt 4. |
| Nachbearbeitung | Kette im Original: **Bloom → Tiefenschärfe → FXAA**. Nachgebaut: Bloom (5 Ebenen, 17 Durchgänge je Bild), Nebel im Bloom-Abschluss, FXAA; **nicht** nachgebaut: Tiefenschärfe, Farbkorrektur-LUT, Rückkopplung. Abschnitt 5. |
| Helligkeitsfehler nach Zone 54 | **Ursache gefunden und behoben:** `_ShadowMapTexture` blieb als freigegebener Verweis (null) stehen, Unity band Schwarz = „alles im Schatten“. Zone 422 nach 54: (82, 101, 59) → mit Fix **(101, 124, 72)**, identisch zu frisch. Abschnitt 7. |
| Schatten Zone 422 | Mit den Originalwerten der Szene (Entfernung **45**, Nahebene **15**, eine Kaskade, weich): **22,1 % der Pixel dunkler** (> 5 Stufen), Bildmittel (101,8 / 125,0 / 72,5) → (94,2 / 116,8 / 67,2). Mit Entfernung 20: **0 Pixel** Unterschied. Abschnitt 8. |
| Tests | Unity (Lab) **57 von 57** (vorher 47; neu 5 Szenenwerte, 5 Wächter/Szene/Nachbearbeitung), `dotnet test work/dotnet-render` **41 von 41**, Python `test_environment_export` 3, `test_material_variants` 7 grün, `make test` im Übersetzer grün. Zwei Python-Tests anderer Arbeit (`test_build_all`, `test_build_stages`: Stufe `stubs`) schlagen fehl, nicht von dieser Arbeit. |

## 2. Material-Export, Varianten und Strippen

### 2.1 Export

`scripts/material_export.py` war schon allgemein; ausgeführt wurde er bisher nur für `Environments/`. Läufe (je Gruppe, `--resolve-external --used … --dir <Gruppe>`, Ausgabe `work/materials_all/`):

| Gruppe | Bundles mit Material | Materialien | doppelte Namen | ohne Shadername |
|---|---|---|---|---|
| `Characters` (objects 128, persons/field 160, persons/battle 124) | 412 | 2.105 | 3 | 0 |
| `Pokemon Database` (field 1.304, battle 1.304, statue 430; `common` nur Texturen) | 3.038 | 17.963 | 0 | 0 |
| `Effects` | 2.716 | 13.629 | 0 | 0 |
| `UIs` | 25 | 119 | 20 | 22 |
| `Dpr`, `Contest`, `FureaiHiroba`, `GMS`, `DigFossil`, `Union`, `UnderGround`, `StatuePlacementEdit` | 35 | 225 | 5 | 27 |
| `Battle` (1.411), `Pml`, `UgFather`, `LightStone` | 0 | – | – | – |

`Battle/btlv` enthält nur Szenen und Daten, keine Materialien. Die Pokémon-Modelle liegen unter `Pokemon Database/pokemons/{field,battle,statue}`, die Texturen in `pokemons/common` (Abhängigkeiten, über `--resolve-external` aufgelöst).

### 2.2 Deckung

`material_variants.py` (Referenz der Variantenwahl) über 33.992 Materialien: **33.895 exakt** im Forward-Pass, 96 „nächstliegend“ (19 × `Custom/Bloom Finalize`, 77 × `FxSystem/Particle`), 0 Shader ohne Variante. Je Teilgruppe (Material → Variante vorhanden **und** übersetzbar):

| Teilgruppe | Materialien | abgedeckt | Anmerkung |
|---|---|---|---|
| `Characters/objects` | 222 | 222 | `Delphis/Character/Standard` 221, `Delphis/Poffin` 1 |
| `Characters/persons/field` | 966 | 966 | |
| `Characters/persons/battle` | 917 | 917 | |
| `Pokemon/field` | 7.616 | 7.616 | `Mitake/MitakeStandardBumpShader` |
| `Pokemon/battle` | 7.616 | 7.616 | |
| `Pokemon/statue` | 2.731 | **148** | **2.583** mit `MitakeStandardPetrify`: Variante nicht übersetzbar |
| `Effects` | 13.629 | 147 | 13.482 mit `FxSystem/Particle`: nicht erzeugt (1.993 Varianten) |
| UI, Dpr, Contest, Fureai, Statue-Editor, GMS, Union, Untergrund, Fossilien | 344 | 294 | 49 ohne Shadername (eingebauter Standard-Shader), 1 ohne Variante |

Die Zahl der benutzten Varianten je Gruppe ist klein, weil die Materialien Konstantenwerte statt Schlüsselwörtern tragen: der Mitake-Shader wählt Spiegelung, Rand und Maske mit **Float-Konstanten** (`_SpecularMaskEnable`, `_RimMaskEnable`, `_BaseColorAddEnable` im Konstantenpuffer 3), nicht mit Schlüsselwörtern; deshalb gibt es für alle 15.232 Pokémon-Materialien nur 2 Varianten (`DIRECTIONAL SHADOWS_SCREEN` mit und ohne `USE_LAYER1`).

### 2.3 Neu: zur Laufzeit gesetzte Schlüsselwörter fehlen in `used.json`

Die Nachbearbeitung schaltet Schlüsselwörter **im Code** (`Material.EnableKeyword`: Nebel `_FOGMODE_*` im Bloom-Abschluss, `_GRADING_*` im FXAA); die Material-Exporte tragen sie nicht. Das „Strippen“ über `used.json` hätte sie deshalb verworfen (nur `_FOGMODE_NONE` und `_GRADING_NONE` blieben als „nächstliegend“). Neu: `scripts/runtime_variants.json` (7 Einträge: 4 Nebelarten, 3 Farbkorrekturarten) und `material_variants.py --extra-used scripts/runtime_variants.json --exclude-shader FxSystem/Particle` (Funktion `merge_used`, 2 Tests). Weitere Laufzeit-Schlüsselwörter (Tiefenschärfe, Kampf-Effekte) sind **nicht** erfasst; sie ergeben sich erst, wenn deren Aufrufe bekannt sind (Lücke 3).

## 3. Figur, NPC und Pokémon mit erzeugten Shadern (Lab)

Aufbau (`work/unity-shader-lab/Assets/Lab/EffectsRunner.cs`, nur Lab): der echte `FieldController` (Quellen aus dem Repo, `XNU_GENERATED_SHADERS=1`, Zone 422) und zusätzlich `PlayerAvatar.Create(provider, new RemappedMaterials(fallback, Katalog des Modellbundles, Variantentabelle, Bundlename), …)`: dieselbe Klasse wie im Spiel, aber mit dem **Materialumbau des Modellbundles** statt des Ersatzspeichers.

| Modell | Bundle | Materialien umgebaut / Ersatz | Shader (erzeugte Varianten) | Bild |
|---|---|---|---|---|
| Spielerfigur | `Characters/persons/field/fc0001_00` | 13 / 8 | `Delphis/Character/Standard` (`…69ddfc07`, `…bf366d46` für Haare) | **farbig**: rote Mütze, Gesicht, Kleidung mit den Bundle-Texturen; vorher (Ersatz-Shader) weißlich-grau |
| NPC | `Characters/persons/field/fc2039_00` | 5 / 0 | dieselben zwei Varianten | farbig, Haare und Kleidung |
| Pokémon (Feld) | `Pokemon Database/pokemons/field/pm0387_00_00` | 7 / 0 | `Mitake/MitakeStandardBumpShader` (`…69ddfc07`, `…51727159`) | siehe unten: Fehler |

Die 8 Ersatzmaterialien der Spielerfigur gehören zu Teilen im selben Prefab, die ausgeschaltet sind (Fahrrad `bicycle`/`light`, Angelruten, Gießkanne, Reittiere `mcl`/`mh`): ihre Materialien stammen aus Nachbarbundles (`Characters/objects/…`), nicht aus dem Bundle der Figur; der Katalog sucht nur im eigenen Bundle (Lücke 2). Alle Netze der Figur haben Tangenten, Vertexfarbe und Skinning-Gewichte.

**Offener Fehler Pokémon:** Mit den echten Texturen zeichnet das Pokémon **schwarz mit Cyan** (an der Sonne einfarbig Cyan (0, 255, 255), im Hausschatten schwarz mit Cyan-Flecken). Eingrenzung (Lab): Setzt man `_Col0Tex` auf Weiß, verschwindet das Cyan sofort (22 → 0 Pixel); setzt man zusätzlich Ambient-, Emissions- und Normalen-Textur auf Weiß, erscheint ein plausibel beleuchtetes graues Modell; Keywords, Floats und `_BaseColorAddEnable`/`_RimMaskEnable`/`_SpecularMaskEnable` ändern nichts. Texturformat der Farbtextur: ASTC 6×6 (UNorm), dasselbe wie bei der Figur, die richtig aussieht. *Vermutet:* der Shader erzeugt bei den echten Texturwerten NaN/Inf (Cyan = (0, 1, 1) nach der Begrenzung; derselbe Cyan-Fleck erscheint im Kugelhimmel-Bild an einer Wasserfläche), wie bei den 15 NaN-Paaren in `docs/shader-translator.md`; nicht bewiesen. Nächster Schritt: Harness-Vergleich `Mitake/MitakeStandardBumpShader` mit der Textur `pm0387_00_00_Body_col` (Übersetzer, `shader_harness`).

NPC-Marker (Kapseln) bleiben Platzhalter des Feldcodes mit dem Ersatz-Shader (`FieldNpcView`); die Modelle der NPCs (`Characters/persons/field/fcNNNN_00`) sind mit dem Umbau darstellbar (Zeile NPC).

## 4. Himmel (Original)

Aus der Szene `Dpr/scenes/field` (`scripts/environment_export.py` → `work/masterdata/EnvironmentScene.json`, belegt):

- **RenderSettings:** kein Skybox-Material (`m_SkyboxMaterial` leer), Umgebungslicht-Modus „Skybox“ mit Nullwerten (Sonde 0, Himmel/Äquator/Boden nur als Dreifarben-Vorgabe gespeichert), Nebel aus, Reflexion „Skybox“ (also schwarz), `subtractiveShadowColor` (0,42 / 0,48 / 0,63). Unser Projekt hatte Unitys Standard-Skybox (Umgebungslicht ≠ 0); die erzeugten Forward-Shader lesen kein Umgebungslicht (Bildmittel mit und ohne Szenenwerte gleich (101,8 / 125 / 72,5)), das Bild ändert sich dadurch nicht.
- **Kameras (6):** `Compositor` (löscht nichts, Ebenenmaske 0, HDR, Tiefe 4, trägt `MultipleCameraCompositor`, `PostProcessFilter`, `AfterImage`), **`Main Camera`** (**löscht mit Volle Farbe Schwarz, Alpha 0**, HDR an, MSAA erlaubt, Nah 0,1, Fern 1500, Ebenenmaske 4.456.247, Tiefe 0; `FieldCamera`, `FieldPanCamera`), `ReflectionCamera` (weiß, Tiefe −10), `EncountEffectCamera`, `AnimaitonCamera`, `PokemonCamera` (aus). Die Vordergrundfarbe unseres Feldes (0,45 / 0,62 / 0,85) ist **erfunden**; im Original erscheint am Kartenrand Schwarz (Alpha 0 im Compositor).
- **Himmel selbst:** Kugelnetze mit dem Shader `Delphis/Map/Sky` in den Bundles `Environments/bg/arenas/sky/s001 … s081` und `eventsky001` sowie in `Environments/fields/battle001` (22 Bundles mit 22 Material-Einträgen); Texturen: Farbverlauf (`SkyGrad`), Nah- und Fernwolken, Szenerie/Tiefe (Berge), Sternenhimmel (`StarlightTex`). Die Tageszeit wirkt über Spiel-Globals (`_CloudParam`, `_EmissionThreshold`) und `SkyColorSettings` (Klasse im Dump, Werte aus Prefab/ScriptableObject, nicht ausgewertet).

Im Lab (Kugel am Kamerastandort, Kamera Neigung −8°, Sichtfeld 60°, erzeugter `Delphis/Map/Sky`-Shader, 1 Material je Kugel, 0 Ersatz): `s008` 89,8 % Pixel nicht schwarz (Bildmittel (7, 211, 204)), `s032` 99,8 % ((43, 46, 49), mit Sternen), `s081` 100 % ((68, 123, 152): Verlauf, Wolkenbänder, Sterne, Horizont); die Kugel mit Gelände („arena“) wird mitgezeichnet. In der Feldkamera (Neigung 40° bis 45°, Sichtfeld 17° bis 20°) ist am Himmel nie etwas zu sehen. Offen: welche Kugel zu welcher Zone und Stunde gehört (`SkyColorSettings`, Wetter) und die Sternenstärke am Tag (im Bild `s081` sichtbar zu hell).

## 5. Nachbearbeitung

### 5.1 Original (belegt aus `Dpr/scenes/field` und dem dekompilierten `Bloom.Build`)

`PostProcessFilter` (auf dem Compositor) führt die Effekte in der Reihenfolge **`Bloom`, `DepthOfField`, `FXAA`** (ScriptableObjects mit je einer Liste von Materialien) und baut daraus je Bild `CommandBuffer` (`GetTemporaryRT`, `Blit`, `SetGlobalVector/Texture`). Materialien und Shader (alle im Inventar, erzeugt):

| Effekt | Material → Shader | Schlüsselwörter im Material |
|---|---|---|
| Bloom | `BloomSetup` → `Custom/Bloom Setup`; `Gaussian7x7` → `Custom/Gaussian7x7`; `BloomFinalize` → `Custom/Bloom Finalize` | `_SRGB_ON` |
| Tiefenschärfe | `CaptureFocus`, `Downsample2x2Focus`, `ExpandFocus`, `ResolveFocus`, `DepthOfField`, `Gaussian7x7` | `_GAMMA_ON`, `_BLUR_ON`, `_SRGB_ON` |
| FXAA | `FXAA` → `Custom/Fxaa` | `_GRADINGMODE_NONE`, `_GRADING_NONE` (Laufzeit: Farbkorrektur-LUT) |

**Bloom-Aufbau** (aus `Bloom.Build`, 0x20A5050; Zahlen stammen aus dem Pseudocode): 5 Ebenen (`MaxLayerCount`), Ebene i hat Breite und Höhe `>> (i + 2)` (Viertel bis 1/64), Format ARGBHalf, je ein Puffer-Paar A/B; Ebene 0: Quelle → A0 mit **Bloom Setup** (Schwelle `_BloomThreshold`, Global aus `EnvironmentSettings`, 0,95 am Tag), Ebene i > 0: A(i−1) → A(i) einfach verkleinert; je Ebene: `_BlurOffsetX` = (−2,2186; 2,2186; −0,6075; 0,6075) (Bitmuster `0xC00DF8DF, 0x400DF8DF, 0xBF1B9852, 0x3F1B9852`, ein 7-Tap-Gauß mit bilinearen Abtastungen), `_BlurOffsetY` = 0, A → B mit **Gaussian7x7**, dann X = 0, Y = Versatz, B → A; zuletzt Quelle → Ziel mit **Bloom Finalize**, der die fünf Ebenen als globale Texturen `_SubTex0..4` liest (Gewichte im Shader eingebrannt) und **den Entfernungsnebel** aus `_GlobalDepthTexture` zeichnet (`Bloom.SetFogParameters`: Schlüsselwort `_FOGMODE_LINEAR/EXP/EXP2`, `_FogParam` = (Ende bzw. Anfang, 1/max(Ende − Anfang; 0,1) [· Dichte bei Exp], 0, Fernebene), `_Color` = Nahfarbe, `_FarColor` = Fernfarbe aus den `EnvironmentSettings`). Die Nebelart der Zone 422 ist „Exp“ (Morgen, Abend, Mitternacht an; Tag und Nacht aus).

### 5.2 Umsetzung

`Scripts/Render/Runtime/PostChain.cs` (neu; Komponente auf der Kamera, `OnRenderImage`, Built-in-Pipeline): Bloom wie oben (17 Blits je Bild: 5 × (Verkleinern/Setup + 2 × Gauß) + Abschluss), Nebel über die Variante `_FOGMODE_*` des erzeugten Shaders (Werte aus `EnvironmentDriver.State.Current`), danach FXAA (`_GRADING_NONE`). Hängt `DepthCaptureDriver` für `_GlobalDepthTexture` selbst an. Die Varianten je Laufzeit-Schlüsselwort werden bei Bedarf über `ShaderVariantResolver` gesucht (deshalb `scripts/runtime_variants.json`, Abschnitt 2.3).

### 5.3 Messung (Lab, Zone 422, 921.600 Pixel, Referenz = ohne `PostChain`)

| Zustand | Bildmittel RGB | Pixel verändert | davon > 8 Stufen | größte Änderung |
|---|---|---|---|---|
| ohne Kette | (94,2 / 116,8 / 67,2) | – | – | – |
| `PostChain` ohne Effekt (Durchreichen) | identisch | 0 | 0 | 0 |
| nur FXAA | (94,2 / 116,8 / 67,2) | 239.793 (26 %) | 17.680 | 188 (Kanten) |
| nur Bloom (Tag, Schwelle 0,95) | (94,1 / 116,8 / 67,2) | 145.752 (15,8 %) | 0 | 3 (schwacher Schein) |
| Bloom + FXAA | (94,1 / 116,8 / 67,2) | 308.488 | 17.752 | 188 |
| Morgen (Stunde 6), ohne Nebel | (92,4 / 112,2 / 70,1) | – | – | – |
| Morgen, **mit Nebel** (Exp, Start 15, Ende 65, Dichte 0,45) | **(104,4 / 126,2 / 88,2)** | 921.600 (alle) | – | 80 |

Die Kette ist eingeschaltet kein Hänger im Lab (alle Messbilder dieses Abschnitts je Bild unter 0,2 s einschließlich Rücklesen); eine Zeitmessung gegen die Kette in Bildern je Sekunde steht aus.

### 5.4 Nicht umgesetzt / Lücken der Nachbearbeitung

1. **Tiefenschärfe** (6 Materialien, 5 Shader, `DepthOfField.Build` 0x2DA77F0, Pseudocode 1.479 Zeilen unter `work/decomp/effects/`): nicht nachgebaut; `_FocalCoefficient` wird bereits geliefert (`DepthOfFieldMath`), `_FocusTex`, `g_BackgroundTexture`, `_AdditionalBlurry` aus `EnvironmentSettings.Blurry`.
2. **Farbkorrektur:** `ColorGradingEnable` ist in den Zonensettings an (Zone 422, alle Abschnitte); das Original ruft `Fxaa.SetColorGrading(lut0, Einfluss, lut1, Gewicht)` und wählt `_GRADING_SINGLE/MULTI` mit den LUT-Texturen aus den `EnvironmentSettings` (`ColorGradingLookup`). Die LUTs liegen in Bundles (Verweis nicht aufgelöst); `PostChain` benutzt `_GRADING_NONE`. Das Original-Bild ist damit leicht anders getönt (nicht gemessen).
3. **Rückkopplung** (`FeedbackBlur`), `ColorFilter`, `ChromaticAberration`, `RadualBlur` (Kampf/Ereignisse), `AfterImage` und `g_BackgroundTexture` (Partikel-Verzerrung): nicht nachgebaut.
4. **HDR:** Die Main Camera des Originals ist HDR; im Lab läuft die Feldkamera LDR (`allowHDR` falsch), Bloom-Puffer sind ARGBHalf. Im Original fließen Werte über 1 in den Bloom; hier nicht gemessen, *vermutet*: stärkerer Schein.
5. Kein Vergleichsbild des Originals (Ryujinx liefert keine Bilder): Bloom, Nebel und FXAA sind als **Aufbau** belegt (Pseudocode, Szene, Shader-Eigenschaften), die Bildähnlichkeit ist nicht gemessen.

## 6. Lücken bei Varianten und Shadern

1. **`MitakeStandardPetrify`** (Statuen): 2 Varianten nicht übersetzbar (`hlsl: subgroup shuffle`), 2.583 Materialien der Statuen-Bundles fallen auf das Ersatzmaterial. Die Änderung am Übersetzer (Subgruppen-Shuffle) wurde **nicht** begonnen (kein unbedingtes Muss für Figur/NPC/Pokémon).
2. **`FxSystem/Particle`:** 13.482 Materialien, **1.993 Varianten** nicht erzeugt (Erzeugung wurde nicht angestoßen: rund 2 s je Variante für den Übersetzer, dazu Unity-Kompilierung); 77 Materialien verlangen ein Schlüsselwort ohne Variante („nächstliegend“). Für die Effekte-Gruppe ist `--exclude-shader FxSystem/Particle` vorgesehen, bis die Partikel gebraucht werden.
3. **Laufzeit-Schlüsselwörter** nur für Bloom-Abschluss und FXAA erfasst (Abschnitt 2.3).
4. **Katalogsuche nur im eigenen Bundle** (`MaterialCatalog.Find(Bundle, Name, Keywords)`): Teile eines Prefabs mit Materialien aus Nachbarbundles (Fahrrad, Angelruten) fallen auf den Ersatz; Abhilfe: Suche über Abhängigkeiten laut Katalog.
5. **Pokémon-Shader:** schwarz/Cyan (Abschnitt 3).

## 7. Helligkeitsfehler nach Zone 54

Beschreibung aus `docs/sichtpruefung-1.md`, Abschnitt 4.2: Nach einem Besuch von Zone 54 sind andere Zonen rund 19 % dunkler (Zone 422: (82, 101, 59) statt (101, 125, 72)).

**Reproduktion im Lab** (`FieldController` echt, Stunde 12): 422 (101, 124, 72) → 422 neu laden (101, 124, 72) → **54 (137, 123, 95) → 422: (82, 101, 59)**; 367 oder 425 dazwischen ändern nichts. Das Verhältnis ist **nicht gleichmäßig**: Wiese 0,785, Dach 0,83, Bäume 0,89 (Kachelraster 160 × 120 Pixel: 0,79 bis 0,92).

**Eingrenzung (Lab, Bildmittel nach 54 → 422 = (82, 101, 59) in jedem Fall):**

| Eingriff nach dem Besuch von 54 | Ergebnis |
|---|---|
| Sonne aus/an, `UnloadUnusedAssets`, `QualitySettings` wie im Original neu setzen, `DynamicGI.UpdateEnvironment`, neue Kamera | unverändert dunkel |
| `FieldController` zerstören und neu erzeugen (neue Sonne, neuer Treiber, neue Materialien), `AssetBundle.UnloadAllAssetBundles(true)` | unverändert dunkel |
| Zustandsabgleich (131 Größen: alle Lichter, `RenderSettings`, Qualität, Kamera, 35 Spiel-Globals, 13 Textur-Globals, `unity_*`, Schlüsselwörter) | **einziger Unterschied außer der Zeit: `_ShadowMapTexture`** (vorher `UnityWhite` 4×4, nachher `null`) |
| Alle Eigenschaften aller Materialien der Karte vor/nach (Fließkomma, Farben, Texturnamen, Keywords, Queue) | identisch |
| `_ShadowMapTexture` per Hand auf Weiß setzen | **(101, 124, 72)**, auch mit Schatten an oder aus |

**Ursache (belegt):** Unitys Bildschirmschatten-Pass setzt das Global `_ShadowMapTexture` nur in Bildern, in denen eine Schattenkarte entsteht (mindestens ein Schattenwerfer innerhalb der Schattenentfernung). In Zone 54 passiert das (Schattenkarte `Shadowmap` 4096 × 4096). Wechselt man in eine Zone **ohne** Schattenwerfer im Bereich (Zone 422 mit Entfernung 20: der Fokuspunkt liegt 30 Einheiten vor der Kamera, Abschnitt 8), bleibt der Wert des letzten Bildes stehen – nach dem Abbau der Zone ein freigegebener Verweis (`null`). Die erzeugten Forward-Shader lesen `_ShadowMapTexture` immer (`min(Schatten, Wolkenterm)`), null bindet Schwarz = **alles liegt im Schatten** (Wiese 21 % dunkler: die Schattenfarbe `_ShadowColor` ersetzt das Licht). Das erklärt auch, warum Sonne, Globals und Schatten an/aus nichts änderten: der Fehler sitzt im Bildschirmschatten-Zustand, nicht in den Globals. In frischem Zustand war der Wert `UnityWhite` (Unitys Standard), deshalb war die erste Zone immer hell.

**Behebung (nur `Scripts/Render`):** `Render/Runtime/ShadowMapGuard.cs` (neu): `Camera.onPreRender` setzt `_ShadowMapTexture` vor **jedem** Kamerabild auf `Texture2D.whiteTexture`; erzeugt Unity im Bild eine Schattenkarte, überschreibt der Schattenpass den Wert danach (belegt: Zone 54 weiter mit Schattenkarte, Bild unverändert (137, 123, 95)). Installiert sich selbst über `SunLight.Ensure` und `EnvironmentDriver.OnEnable`; der Feldcode braucht keine Änderung. Messung nach der Behebung (Reihenfolge 422 → 54 → 422 → 54 → 367 → 422): 422 jedes Mal **(101, 124, 72)**, 54 (137, 123, 95), 367 (99, 122, 65). Tests: `RenderShadowGuardTests` (Zurücksetzen, Installation idempotent und vor dem Kamerabild, Szenenwerte, Konstanten).

## 8. Schatten-Treue (Zone 422)

**Befund zu den Originalwerten:** Die Schattenentfernung kommt im Original **nicht** aus den Qualitätseinstellungen (20), sondern der `EnvironmentController` überschreibt sie je Bild mit dem Szenenwert (`_ShadowDistance`, `_ShadowNearPlaneOffset`, `_ShadowNormalBias`). Gelesen aus den Szenen-Bundles (`scripts/environment_export.py`):

| Szene | Entfernung | Nahebene | Normal-Bias |
|---|---|---|---|
| **`field`** | **45** | **15** | 0 |
| `battle`, `gms`, `contest`, `evolvedemo`, `sealpreview` | 20 | 3 | 0 |

Das Licht der Szene (`EnvironmentController`-Objekt): Richtungslicht, Intensität 1,5, **weiche Schatten**, Bias 0,05, Normal-Bias 0,4 (`EnvironmentController` setzt Intensität, Farbe, Drehung und Normal-Bias je Bild aus den Zonenwerten; Zone 422: 1,15, (0,93, …), Drehung (75, 345, 0)). Die Qualitätsstufe liefert Schatten „alle“, Auflösung hoch, StableFit, **eine Kaskade**.

**Messung** (Lab, `EnvironmentDriver` mit `EnvironmentScene.json`, eine Kaskade, StableFit, hoch, weich; Zeit eingefroren, gleiche Kamera; Bilder `work/effects/shots/s45_on|off.png`, `s20_on|off.png`, Unterschiedsbild `shadow_diff45.png`):

| Einstellung | Bildmittel an | Bildmittel aus | Pixel dunkler (> 5) | davon > 20 | größte Abnahme | Pixel heller |
|---|---|---|---|---|---|---|
| **Entfernung 45, Nahebene 15** (Szenenwert) | (94,2 / 116,8 / 67,2) | (101,8 / 125,0 / 72,5) | **203.302 (22,06 %)** | 143.155 | 96 | 0 |
| Entfernung 20, Nahebene 3 (Qualitätswert) | (101,8 / 125,0 / 72,5) | (101,8 / 125,0 / 72,5) | **0** | 0 | 0 | 0 |

Das Bild mit Schatten zeigt klare weiche Schlagschatten: Haus (Dach, Wand) auf Boden und Weg nach rechts unten, Briefkasten, Wegweiser oben, Nadelbäume rechts, Nachbarhaus links; die Figur wirft keinen (Ersatz-Shader ohne Schattenpass). Bei Entfernung 20 gibt es keinen Schatten im Bild, weil der Fokuspunkt (Zelle 116, 886) rund 30 Einheiten von der Kamera entfernt liegt; die Bildmitte liegt damit **außerhalb** der Schattenentfernung. Zone 54 (näher an der Kamera) wirft auch mit 20 Schatten – das war der Auslöser des Fehlers aus Abschnitt 7. Die Schatten mit Morgenlicht (Stunde 6) sind länger und blauer (`po_m_nofog.png`).

**Treue:** Die Form entspricht dem Verfahren des Originals (Unity-Schattenkarte, ein Cascade, StableFit, weich, Bias 0,05/0,4/0). Ein Pixelvergleich mit der Switch ist nicht möglich (keine Referenzbilder). Offene Unschärfe: Der Original-Wert `shadowNormalBias` des Lichts ist 0 (Controller) bzw. 0,4 (Prefab); `EnvironmentDriver` setzt 0 wie der Controller.

## 9. Szenenwerte des `EnvironmentController` (Nebenergebnis, schließt Lücke 1 aus `docs/shader-globals.md`)

`scripts/environment_export.py` schreibt jetzt `work/masterdata/EnvironmentScene.json` aus `Dpr/scenes/field`: `_ShadowDistance` 45, `_ShadowNearPlaneOffset` 15, `_ShadowNormalBias` 0, `_CloudSpeed` (0,5; 0,5), `_CloudTiling` (0,03; 0,03), `_CloudShadowBase` 0, `_CloudShadowScale` 1, `_EmissionScale` 1, `_Wetness` 1, `_WeatherMode` 0 (sonnig), Schattenfarbe (0,41; 0,46; 0,53), Schneeschattenfarbe (0,47; 0,52; 0,80); Texturen `_NoiseTex` = `noise_repeat`, `_SnowTex` = `snow`, `_SnowNormalTex` = `snowNormal`, `_EnvironmentMap` = `Reflection` (alle in `Dpr/common_resources`), `_CloudShadowTex` **nicht aufgelöst** (Name „extern“; Verweis führt in ein Bundle außerhalb der Abhängigkeitsliste, offen). C#: `EnvironmentSceneData.FromJson` (rein, 5 Tests), `EnvironmentDriver` lädt die Datei selbst (`AutoLoadScene`) und setzt `State.Scene` und die `RenderSettings` (`SceneRenderApply.Apply`). Die Wolkenschatten-Textur ist die größte verbleibende Lücke der Spiel-Globals: ohne sie ist `_CloudShadowTex` schwarz, `_CloudShadowBase` 1.

## 10. Hinweisliste für den Feldcode (nicht geändert; gehört `ap-vertical-slice`)

1. **Figur mit Materialumbau:** `FieldController.CreatePlayer` ruft `PlayerAvatar.Create(_provider, _fallback, …)`. Statt `_fallback` ein `RemappedMaterials(_fallback, katalogDesModelbundles, variantenIndex, playerModelBundle)` übergeben (Katalog: `GeneratedShaderLibrary.MaterialFileFor(playerModelBundle)`, Export liegt unter `<Materialordner>/Characters__persons__field__fc0001_00.json`; der Materialordner muss die Dateien aus `work/materials_all/` enthalten, z. B. `XNU_MATERIALS`). Gleiches für NPC- und Pokémon-Modelle. Ein Materialumbau-Objekt je Modell; `Destroy()` beim Abbau.
2. **Kamera:** `SetupCamera` nimmt `_camera.backgroundColor = (0,45 / 0,62 / 0,85)`. Original: `SceneRenderApply.ApplyCamera(_camera, scene.Camera("Main Camera"), clipPlanes: false)` (Volle Farbe schwarz, Alpha 0, HDR, MSAA erlaubt). `scene` = `EnvironmentDriver.SceneData`.
3. **Nachbearbeitung:** nach `EnsureRenderEnvironment` `var pc = _camera.gameObject.AddComponent<PostChain>(); pc.Driver = _envDriver;` (einmalig).
4. **Szenenexport:** die Stufe `masterdata` von `build_all.sh` soll `scripts/environment_export.py` ausführen (schreibt jetzt auch `EnvironmentScene.json`); ohne Datei bleiben die Platzhalter (Entfernung 20, Standardwerte).
5. **Strippen:** `material_variants.py … --extra-used scripts/runtime_variants.json` beim Erzeugen der benutzten Menge; `shader_wrap_all.py --used … --combine-shadow`.
6. **Karten-Materialkatalog:** `FieldController.CreateMaterials` lädt nur den Export des Kartenbundles; für Charaktere wie unter 1. ein eigener Katalog.

## 11. Reproduktion

```
export PYTHONPATH=tools/pydeps
python3 scripts/environment_export.py                                    # + work/masterdata/EnvironmentScene.json
for g in Characters "Pokemon Database" Effects UIs Dpr Contest FureaiHiroba GMS UnderGround Union DigFossil StatuePlacementEdit; do
  python3 scripts/material_export.py --out work/materials_all --resolve-external --used "work/materials_all/used_$g.json" --dir "$g"; done
python3 scripts/material_variants.py --materials work/materials_all --extra-used scripts/runtime_variants.json \
    --exclude-shader FxSystem/Particle --used-out work/materials_all/used_game_nopart.json --report work/materials_all/variants_report.json
python3 scripts/shader_wrap_all.py --out work/shaders/combined_all --used <benutzte Menge> --combine-shadow     # 119 von 120
# Lab: Spielmodus per work/effects/run.cfg (steps=call:chars:…, snap:…, call:post:bf, call:sky:s081, shadows:off, call:dist:45 …),
#      Start work/effects/run.sh; XNU_SHADERS=work/shaders/combined_all; vor run_tests editor_stop
```

Geändert/neu: `scripts/environment_export.py` (+`scene_document`, `read_scene`), `scripts/material_variants.py` (`--extra-used`, `--exclude-shader`, `merge_used`), `scripts/runtime_variants.json`, Tests `scripts/tests/test_environment_export.py`, `test_material_variants.py`; Unity `Scripts/Render/EnvironmentScene.cs`, `Runtime/{ShadowMapGuard,SceneRenderApply,PostChain}.cs`, `Runtime/{EnvironmentDriver,SunLight}.cs` (geändert), `Tests/EditMode/{RenderSceneTests,RenderShadowGuardTests}.cs`. `shader_translator/` und `scripts/shader_wrap*.py` unverändert.
