# Sichtprüfung 3: Feldoptik mit erzeugten Shadern, Figur/NPCs, Pokémon, Stadt-Spielstand (Todo `ap-effects-fidelity`, Teil 5)

Stand: 2026-10-19, Unity 6000.3.26f1 (Labor `work/unity-shader-lab` und Haupteditor `unity/`), Built-in-Pipeline, Gamma, Metal, Apple M1 Pro. Es werden nur unsere erzeugten Shader gezeichnet (kein Original-Shader geladen), kein Ton. Bilder, Exporte und erzeugte Shader liegen unter `work/` (`work/visual/fieldrender/`, `…/stadt/`), nicht im Repo; hier stehen Zahlen und Beschreibungen. Aufnahme: Hauptkamera in eine `RenderTexture` 1280 × 720 am Bildende (`FieldShot.CaptureAtFrameEnd`, Haupteditor) bzw. `EffectsRunner` (Labor).

Markierung: **belegt** = gemessen/gesehen, *vermutet* = Schluss ohne Test.

## 1. Ergebnis in Kürze

| Frage | Ergebnis |
|---|---|
| Standard | Material-Umbau mit erzeugten Shadern ist **Standard** (`useGeneratedShaders = true`; `XNU_GENERATED_SHADERS=0` schaltet aus, `=1` erzwingt). Ohne `variants.json`, ohne auffindbare Shader oder ohne Materialexport sauberer Rückfall auf das Ersatzmaterial, `MaterialMode` nennt den Grund. |
| Kamera-Ausstattung | Neu `FieldRenderRig`: Tiefentexturen (`_OpaqueDepthTexture`, `_GlobalDepthTexture`), Reflexionskamera (`_ReflectionTex`), Nachbearbeitung (Bloom, Nebel, FXAA), Hintergrund Schwarz wie im Original. |
| Spielerfigur und NPCs | Figur und alle NPC-Modelle mit erzeugten Shadern (farbig). NPCs sind Charaktermodelle mit Ruhe-Animation, Marker nur als Rückfall. |
| NPC-Modelle auflösbar | Gesamt: von 4.197 Platzierungen 1.639 mit Figurenindex (alle 130 verschiedenen Modellbundles liegen vor), 1.365 mit Objekt-Index ≥ 142 (nicht aufgelöst), 1.193 unsichtbar. Zonen: 422: 5 von 5; 425: 2 von 2; 54: 14 Figuren, 12 Objekte; 367: 18 Figuren, 10 Objekte; Zone 24 (Stadt): 12 Figuren, 4 Objekte. |
| Vertexdaten | Unauffällig (Abschnitt 4). Das „Kaputte“ kam nicht von den Netzen. |
| Pokémon schwarz/Cyan | **Ursache gefunden und behoben**: Ganzzahl-Uniforms im Shader-Wrapper (Abschnitt 5). Kein NaN-Problem des Übersetzers. |
| Zone 167 (Nutzer-Screenshot) | weiße Quads, flaches Wasser, verschmierte Felswände: mit erzeugten Shadern und Kamera-Ausstattung behoben (Abschnitt 3). |
| Stadt-Spielstand (Zone 24) | Position aus `PLAYER_DATA` gelesen (57, 729); Bildschirmschatten fiel unter iOS-Ziel aus, behoben (Abschnitt 6). |
| Tests | Unity EditMode **763 von 763** (Haupteditor), Labor 63 von 63, `test_shader_wrap` 40 von 40. |

## 2. Prüfliste zum Nutzer-Screenshot (Zone 167, Mac-Vorschau)

| # | Beobachtung | Ursache | Fix | Beleg |
|---|---|---|---|---|
| 1 | weiße rechteckige Flächen am Pokécenter-Eingang | Standard war das Ersatzmaterial: die Glas/Fade-Flächen (`M_C_001_Grad_01`, `_ALPHABLEND_ON`, `_DEPTHDENSITY_ON`) wurden ohne Alpha-Mischung weiß gezeichnet (*vermutet*, aus dem Materialdump und dem Bildvergleich) | erzeugte Shader als Standard (Variante mit `_ALPHABLEND_ON`) | Labor, gleiche Zelle (840–846, 599): vorher weiße Quads, nachher Tür mit Glas |
| 2 | Wasser einfarbig blau | Ersatz-Shader kennt kein Wasser; mit erzeugtem `FlowmapWater` ohne Tiefentexturen zeichnete der Shader nur eine Flächenfarbe | `FieldRenderRig` (Tiefe, Reflexion); Wasser zeigt Wellen, Funkeln und Tiefenfarbe | Bilder `after_167`, `after2_167`, Stadt `z24_fix` |
| 3 | Felswände gestreckt, verschmiert, diagonales Dreiecksband | Ersatz-Shader mit nur einer Haupttextur statt der `_Cascade`-Mischung über zwei UV-Sätze (*vermutet*, nicht einzeln isoliert); keine Vertexdaten-Störung (Abschnitt 4) | erzeugte Shader (`_CASCADE_*`-Varianten) | `before_167` (Ersatz) gegen `after_167`: Felsstufen mit Steinstruktur, kein Band |
| 4 | Spielfigur weiß/grau | Ersatz-Shader der Figur | Materialumbau des Modellbundles (13 Materialien umgebaut, 8 Ersatz für ausgeschaltete Teile) | rote Mütze, Gesicht, Kleidung farbig |
| 5 | HUD-Text überdruckt | zwei `FieldController` bzw. zwei `OnGUI`-Zeichnungen übereinander; in der Spielszene zusätzlich der Debug-Text | nur eine Instanz zeichnet (`HudAllowed`), mit externer Spielschleife (`ExternalTick`) gar nicht; `showHud` | Quelltext, nicht am Bild gemessen |
| 6 | schwarze Balken links/rechts | Absicht: `DisplayController` begrenzt die Kamera auf 16:9 (`AspectMath.Fit`), Hintergrundkamera schwarz | keine Änderung (Zielverhältnis des Spiels) | Kamera-`rect` (0,09/0,83) im Fenster 1814 × 934 |

Die Prüfstelle (Zelle 840/599) gehört dem alten Spielstand. Der Nutzer-Screenshot zeigt Zone 167 bei (88x, 599).

## 3. Standard, Rig, Build

- `FieldController`: `GeneratedShadersWanted()`, `LoadShaderIndex()` (einmal, mit Zählung auffindbarer Shader), `CreateModelMaterials(bundle)` für Figur und NPCs (Katalog über `GeneratedShaderLibrary.FindMaterialFile`: Materialordner, sonst Nachbarordner `<…>_all`), `AttachRenderRig()`. Auf einer von außen übergebenen Kamera (`cameraOverride`, Spielszene mit Oberfläche) läuft die Nachbearbeitung nicht (`postOnSharedCamera`), weil Bloom/FXAA die Oberfläche mit verändern würden.
- `GeneratedShaderLibrary`: Suchreihenfolge der Shader `combined_all`, `combined`, Wurzel; `GeneratedShaderSync.FindSourceDirectory`, `GeneratedShaderBuildSync` (Vorbau-Schritt: kopiert die Shader vor jedem Player-Build nach `Assets/XnuGenerated/Resources`; fehlt die Quelle, nur Warnung).
- `scripts/build_all.sh`: Stufe `assets` kopiert zusätzlich die Charakter-Materialexporte (`work/materials_all/Characters__*.json`, 412 Dateien, 7,7 MB) nach `materials/`, damit der Player Figur und NPCs umbauen kann. Pokémon-Exporte (Statuen, Kampf) bleiben draußen.
- Debug-Haken `XNU_FIELD_START="Zone,gx,gy[,Blick]"` startet das Feld an einer Zelle (für Prüfläufe).

## 4. Vertexdaten (belegt, Labor und Haupteditor)

Scan über alle Netze der geladenen Karte und Modelle (`EffectsRunner.MeshScan`, Zone 54: 105 Netze, 20 Skinned; Zone 167: 96 Netze):

- **Kanäle:** Karte `Position Float32x3, Normal Float32x3 (oder Float16x4), Tangent Float32x4 (oder Float16x4), Color UNorm8x4, TexCoord0 Float32x2 (oder Float16x2), TexCoord1 Float32x2`; Wasser `Position, [Color], TexCoord0 Float16x2` ohne Normalen; Figuren/Pokémon Stream 0 `Position/Normal/Tangent`, Stream 1 `Color UNorm8x4, TexCoord0`, Stream 2 `BlendWeight Float32x2/x4, BlendIndices UInt32x2/x4`. Alle Layouts sind gültige Unity-Formate; Index 16 Bit (0 Netze mit 32 Bit), 203 Submeshes.
- **Werte:** 0 Netze mit NaN/Inf, 0 ohne Normalen, 0 ohne UV0, keine UV-Werte über 64, Tangenten-W ±1, Normalenlänge in Ordnung (nur die lesbaren Netze: 2 von 96, die übrigen sind nicht lesbar markiert, Netze liegen im GPU-Speicher; Auswertung über `isReadable` also begrenzt, *vermutet*: gleiche Güte).
- **Eingänge der Shader:** `POSITION, NORMAL, TANGENT, COLOR, TEXCOORD0, TEXCOORD1` (Karte) bzw. ohne COLOR (Mitake, Pokémon: `a0..a4 = POSITION, NORMAL, TANGENT, TEXCOORD0, TEXCOORD1`). Die Zuordnung der erzeugten Wrapper stimmt mit den Netzkanälen überein; fehlende Kanäle (Wasser ohne Normalen) liest Unity als 0.
- **Collider-Netze:** 10 `MeshCollider` hängen an sichtbaren Renderern (Himmel-Planes und `P_C_001_InOut_01`, Ebene 0); Bodenebene 10: 27 Renderer, alles Boden (Treppen, Boden), keine reinen Collider-Netze sichtbar. `FieldMapBuilder` baut Renderer nur mit `MeshFilter` + `MeshRenderer`; Collider-only-Objekte werden nicht gezeichnet.
- **Schluss:** Die „vertex collision“-Optik (gestreckte, diagonale Flächen) entstand durch den Ersatz-Shader (falsche Textur und Mischung), nicht durch Vertexdaten; mit erzeugten Shadern verschwinden sie.

## 5. Pokémon schwarz/Cyan: Ganzzahl-Uniforms im Wrapper

**Befund.** `Mitake/MitakeStandardBumpShader` zeichnete das Pokémon schwarz mit Cyan (Zone 54 bei Mittag: 3 Cyan-Pixel in der Textur-Schleife, sonst schwarze Silhouette). Eingrenzung: Texturen auf Weiß (je Slot), Globals (`_CloudShadowTex`, `_ShadowMapTexture`), Material-Floats, Kugel/Kapsel statt Modell, Bloom/FXAA ab: alles ohne Wirkung; die Ausgabe des Shaders war die Ursache.

**Ursache (belegt).** Das Original liest manche Material-Konstanten als Ganzzahl (`float(int(mx_cb3[2][1]))` für `_SpecularMaskEnable`, `_BaseColorAddEnable`, `_EmissionMaskUse`, `_SphereMaskEnable`, `_RimMaskEnable`, `_ColorMapUvIndex`, `_Layer1UvIndex`, …). Der Wrapper füllte den Konstantenpuffer mit den **Bits der Fließkommazahl** (`asuint(1.0)` = 1065353216); der Shader machte daraus `int` 1065353216, multiplizierte damit und erzeugte Inf/NaN. Betroffen: 55 von 119 erzeugten Shadern (Mitake-Pokémon, Charakter-Varianten und die Mehrzahl der `Delphis/Map/Standard`-Varianten, die `_Cascade` als Ganzzahl lesen; Aufteilung nicht einzeln gezählt).

**Fix.** `scripts/shader_wrap.py` (`build_stage_block`): Wörter, die der Shader als `int`/`uint` liest, werden als `asuint(int(<Eigenschaft>))` geschrieben (Erkennung aus dem HLSL, keine Namensliste). Test `test_int_uniform_words_are_converted`; 55 Dateien neu erzeugt (`work/shaders/combined_all`).

**Beleg.** Pokémon `pm0387_00_00` (Chelast) im Labor, Zone 54: vorher schwarze Silhouette (Bild `pk54_orig`), danach grün-braun mit Blatt (Bild `probe1`/`pkBF`). Pixel (805, 385): (35, 34, 34) → (163, 178, 117).

**Offen.** Die frühere Vermutung „fp16-Überlauf im Übersetzer“ (`docs/shader-translator.md`, Abschnitt 11.3, 15 `Map/Standard`-Paare) ist damit für die Mitake-Gruppe widerlegt; ob dieselbe Ursache auch die 15 Harness-Paare erklärt, ist nicht geprüft (der Harness setzt die Uniforms selbst).

## 6. Stadt-Spielstand (SaveData sha256 0396a4a62735)

**Position.** Im Stadt-Stand: `zoneID` (0x5634) = 24 (C02), `PLAYER_DATA` (0x79BF4/0x79BF8) = (57, 729), Höhe 1,0; `TownMapLocation` (0x8FB04+0x54) = Zone 416, (−789, 355) ist veraltet. Alter Stand: Zone 167, `PLAYER_DATA` (852, 599) mit Höhe 6,0, `TownMapLocation` (842, 597): die Höhe 6,00 der Zone 167 im Bild und die Zeile 599 sprechen für `PLAYER_DATA` *[A]*. `SavedPosition.Read` bevorzugt jetzt `PLAYER_DATA` + `zoneID`, `TownMapLocation` nur als Rückfall (Richtung nur, wenn deren Zone passt); `Write` schreibt beide Stellen. 6 neue Tests (`SavedPositionTests`), einer liest den lokalen Stand (ohne Datei ignoriert).

**Rendern (Haupteditor, Zone 24, Stunde 12).** Karte mit 4 bis 6 Blöcken (1.068 Renderer), Spawn (57, 729) funktioniert (das 0/6-Bild im Labor war die falsche Zelle 789/355). Zahlen: Draw-Calls 389, SetPass 201, 335.620 Dreiecke, 280.980 Vertices (Editor-Spielfenster). Bild: Wasser mit Wellen links, Pflaster violett-grau, blaues Dach mit türkiser Tür, Pokécenter oben, Nadelbäume rechts, NPC (braune Haare) und Figur farbig, Schatten klar.

**Fehler: Bildschirmschatten fiel aus (Ursache gefunden und behoben).** Im Haupteditor mit aktivem Build-Ziel **iOS** war das ganze Bild zu dunkel (Zone 24 Mittel 62/74/82, Zone 422 64/71/43 statt 87/102/111 bzw. 99/110/64 im Labor mit Ziel macOS). Alle Eingriffe (Qualität, Kaskaden, Bias, Nahebene, Rig, Post, Himmel, jeder Schattenwerfer) änderten nichts, nur „Schatten aus“ gab das helle Bild. Die Projektdateien unterscheiden sich in den **Graphics Tiers**: für iOS ist `cascadedShadowMaps` aus. Dann erzeugt Unity keinen Bildschirmschatten-Pass, die Shader lesen `_ShadowMapTexture` ohne Entsprechung und zeichnen alles im Schatten. Test: Labor auf iOS umgestellt: (62, 74, 82) wie im Haupteditor; mit `cascadedShadowMaps = true`: (87, 102, 110). Fix: `RenderProjectSettings` (Editor, beim Laden, idempotent) schaltet die Stufe für iOS und macOS ein (`ProjectSettings/GraphicsSettings.asset`), Test `IosStufenSchaltenCascadedShadowsFuerDenBildschirmschattenEin`. Das betrifft auch die iPad-App (*vermutet*, auf dem Gerät nicht geprüft) und erklärt, warum der Schatten in der Mac-Vorschau „zu dunkel“ wirkte.

## 7. Vergleich mit dem Ryujinx-Bild (`ref_01_feld_weiter`, Zone 24, Stunde 12,4)

Referenz geholt (`scripts/ryujinx_fetch_shots.sh fetch`, 2 neue Bilder), Vergleich `visual_compare.py ref compare`:

| Maß | vor dem Tier-Fix | nach dem Tier-Fix |
|---|---|---|
| Bildmittel RGB Referenz | 106,2 / 120,0 / 118,3 | – |
| Bildmittel RGB Unity | 62,4 / 75,0 / 82,7 | 87,1 / 102,2 / 110,6 |
| SSIM (angeglichen) | 0,408 | 0,394 (Versatz der Kamera/Figuren) |
| MAD roh → angeglichen | 34,9 → 26,8 | 35,2 → 27,1 |
| Helligkeit Unity/Referenz | 0,82 | 0,82 |

Beschreibung (links Referenz, Mitte Unity, rechts Heatmap): Aufbau gleich (Haus mit blauem Dach, Pflanzkübel, Baumreihe, Pflaster in zwei Violetttönen, Pokécenter oben). Größte Abweichungen: (1) **Wasser** links oben: Referenz türkis mit hellem Schaum, Unity blauer und dunkler mit Funkeln; (2) **Helligkeit/Kontrast**: Unity etwa 18 % dunkler, Pflaster bei Referenz (141/129/165), bei Unity (113/108/138): Schatten- und Lichtstärke (`_ShadowColor`, Lichtfarbe) sind nur abgeleitet *[A]*, Bloom und Farbkorrektur (LUT) fehlen; (3) **Bäume**: Referenz heller und gelbgrüner (52/105/37 gegen 46/88/36); (4) **Kameraversatz** (−68, −24) Pixel: Figuren stehen anders (Referenz: NPC rechts neben der Figur, bei uns weiter rechts), also andere Zelle/Animationsphase; der SSIM bleibt damit klein. Die Kamera (Neigung 40°, FOV 18°, Gier 180) entspricht dem Original nach Stammdaten, die Perspektive stimmt im Bild.

Nicht behoben: Farbkorrektur-LUT (`ColorGradingLookup`), Tiefenschärfe, HDR-Bloom (Abschnitt 5.4 in `docs/sichtpruefung-2.md`) und die Wasserfarbe (Reflexion/Umgebung `_EnvironmentMap` fehlt als Textur). Die Helligkeitslücke von 18 % ist damit das größte offene Maß dieser Stufe; *vermutet*: LUT und HDR-Bloom machen den größten Teil.

Das zweite Referenzbild (`ref_05_vor_pokecenter`, Pokécenter mit braunem Kupferdach, weißen Streben und Glasfront) zeigt ein **anderes Gebäude** als das Pokécenter unserer Zone 24 (rotes Dach mit Kuppel, `SM_C_001_PokeCen_01`). *Vermutet:* ein anderer Standort (anderes Gebäudemodell der Stadt); nicht geklärt, ob das Referenzbild im selben Gebiet entstand. Kein Vergleich möglich.

## 8. NPCs: Zahlen, Technik

- `CharacterGraphicsTable` (`dpr_masterdatas/CharacterGraphics.json`, 142 Einträge: `FieldGraphic`, `Scale`) löst `ObjectGraphicIndex` 0 bis 141 zum Bundle `Characters/persons/field/fcNNNN_00` auf; `NpcModels` baut je Platzierung ein Modell (Materialumbau je Modellbundle, `PlayerAvatar.Create` mit Namen und Skalierung). Animation: `idling_f`, sonst Clip mit „idl“/„wait“ im Namen, sonst der erste Clip; viele NPC-Bundles haben nur 1 von 3 Clips (Laufen/Gehen fehlen), Laufmuster werden nicht abgespielt.
- Lab-Läufe: Zone 422: 3 von 3 Platzierungen als Modell (3 Modelle); 54: 5 von 5; 367: 3 von 4 (1 nicht auflösbar: Objekt-Index 500 usw.). Zone 24: 12 Platzierungen mit Figurenindex, alle Modellbundles vorhanden (im Bild sichtbar: Figur mit NPC, Frau mit Haarschmuck als Modell, Kapsel für das Objekt); die Anzahl gleichzeitig gebauter Modelle wurde dort nicht gezählt.
- Nicht aufgelöst: Objekt-Indizes ≥ 142 (500 Item-Ball, 501 Fällbaum, 502/503 …, 556 Wand, 540000 Entenmodell, 4221100 …): 1.365 Platzierungen mit 132 verschiedenen Indizes; Zuordnung zu `Characters/objects/obNNNN` (128 Bundles) und zu den Pokémon-Modellen ist offen. Sie erscheinen weiter als Marker (blaue Kapsel, z. B. `C02_KODUCK` in der Stadt).

## 9. Zahlen (Labor, Ziel macOS, 1280 × 720, Mittag)

| Zone | Zustand | Draw-Calls | SetPass | Dreiecke | Bildmittel RGB | Frame-Zeit |
|---|---|---|---|---|---|---|
| 422 | vorher (Ersatz) | 98 | 29 | 32.351 | 96/104/63 | 1,5 ms (Editor ohne Vsync) |
| 422 | nachher (erzeugt, Rig) | 904 | 204 | 281.504 | 99/110/64 | 4,1 ms |
| 425 | vorher | 105 | 49 | 16.458 | 120/139/163 | 1,3 ms |
| 425 | nachher | 692 | 267 | 123.942 | 52/42/28 (Raum vor Schwarz) | 3,1 ms |
| 54 | vorher | 146 | 62 | 66.740 | 148/133/102 | 1,3 ms |
| 54 | nachher | 1.141 | 340 | 484.957 | 144/128/98 | 3,3 ms |
| 24 (Haupteditor) | nachher | 389 | 201 | 335.620 | 87/102/111 | Vsync-begrenzt 30 Bilder/s |

Die Frame-Zeit ist die reine Aufnahme (CPU und GPU auf M1 Pro im Editor, kein Player). Der Mehraufwand der erzeugten Shader (Faktor 3 bis 8 bei Draw-Calls, Schattenwerfer 244 bis 475) bleibt weit unter dem 30-Bilder/s-Ziel (33 ms). Messung am iPad steht aus.

## 10. Geänderte Dateien

`Field/Runtime/{FieldController,FieldNpcView,PlayerAvatar,FieldDataSet,NpcModels (neu)}.cs`, `Field/Logic/CharacterGraphicsTable.cs` (neu), `Field/Editor/FieldShot.cs` (`CaptureAtFrameEnd`), `Render/Runtime/{GeneratedShaderLibrary,FieldRenderRig (neu)}.cs`, `Render/Editor/{GeneratedShaderSync,GeneratedShaderBuildSync (neu),RenderProjectSettings (neu)}.cs`, `Game/Runtime/SaveSlotService.cs` (`SavedPosition`), `scripts/shader_wrap.py`, `scripts/build_all.sh`, `unity/ProjectSettings/GraphicsSettings.asset`, Tests `FieldFidelityTests`, `SavedPositionTests`, `test_shader_wrap.py`.

## 11. Lücken

1. Farbkorrektur-LUT, Tiefenschärfe, HDR-Bloom; Wasserfarbe gegen Referenz.
2. Objekt-Platzierungen (Index ≥ 142) und Pokémon-Begleiter bleiben Marker.
3. NPC-Animationen: nur Ruhe; Laufmuster, Blickrichtungs-Animation fehlen.
4. Player- und iPad-Messung der neuen Standardeinstellung (Shader in `Resources`, Tier-Fix) stehen aus; erster Mac-Player-Test durch den Hauptagenten.
5. Zweites Referenzbild (anderes Pokécenter) ungeklärt.
6. Die Nachbearbeitung läuft nur mit eigener Kamera; in der Spielszene (Kamera mit Oberfläche) ist sie aus (Compositor-Trennung fehlt).
