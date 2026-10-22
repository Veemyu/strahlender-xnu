# Wasser im Original: Befund für die Rekompilation

Stand: 2026-10-19, 16:58. Der Auftrag „Wasser im Unity-Rebuild“ wurde **zurückgezogen**: Gemeint ist die rekompilierte BDSP-App (`dev.local.xnubdsp`, Stränge `ap-recomp-qa`/`ap-recomp-ios`), nicht das Unity-Projekt. Am Unity-Projekt wurde **nichts geändert**. Hier steht nur, was aus der Material-Analyse und dem Referenzbild für die Rekompilation nützlich ist. Es gibt hier **keine** Unity-Messungen und keine iPad-Startanalyse (nicht begonnen).

Markierung: **belegt** = aus unseren Exporten oder dem Referenzbild gemessen, *vermutet* = Schluss ohne Test.

## 1. Referenz (Ryujinx, echtes Original)

`work/visual/ref/ryujinx/views/free_wasser_a.png` und `free_wasser_b.png` (nur lokal, nicht im Repo), 2 s Abstand, Spielstand sha 0396a4a62735, Fleetburg (Zone 24), Becken rechts neben dem Pokécenter, Spielstunde ≈ 14,4 (Dateizeit 14:49:59 UTC minus Offset 1388 s, Annahme [A]).

Beschreibung: tiefes, gesättigtes Blau; darauf helle, scharfe **Caustics** (weiße, netzartige Lichtlinien und Glanzpunkte, im Bild a und b an anderen Stellen); schwach erkennbare **Spiegelung/Brechung** von Brücke und Planken am oberen Beckenrand und als dunkle Schlagschatten im Wasser; orange Uferkante (Holz/Kupfer) links und rechts, helle Steinmauern.

Zahlen (Wasserregion x 790–1180, y 170–650 des 1280×720-Bildes, **belegt**):

| Maß | Bild a | Bild b |
|---|---|---|
| Mittel RGB | 87,2 / 126,7 / 209,6 | 88,1 / 127,5 / 210,6 |
| Standardabweichung RGB | 25,8 / 17,1 / 24,7 | 26,2 / 17,8 / 25,1 |
| 99-%-Perzentil der Helligkeit | 191 | 195 |
| Anteil sehr heller Pixel (alle Kanäle > 200) | 0,27 % | 0,33 % |

Animation: mittlere Abweichung zwischen a und b in der Region **8,7** (Anteil Pixel mit Abweichung > 24: 5 %). Das Mittel bleibt gleich, nur die Caustics-Struktur wandert: **belegt**, dass das Wasser über `_Time` animiert wird und die Gesamtfarbe zeitlich stabil ist. Ein Rekompilationsbild muss also Mittel ≈ (87 / 127 / 210) ± 10 % und zwei Bilder mit MAD ≈ 9 in der Region zeigen.

## 2. Shader und Material der Zone 24

Das Wasser der Zone 24 steckt im Bundle `Environments/fields/area010` (Bereich C02), Material **`M_C_001_SeaWater_03`** (aus `work/materials/Environments__fields__area010.json`, **belegt**; die Pokécenter-Prefabs `c02r*` enthalten kein Wassermaterial):

| Eigenschaft | Wert |
|---|---|
| Shader | `Delphis/Map/FlowmapWater` (ein Pass, `Lightmode=FORWARDBASE`) |
| Zustand | `QUEUE=Transparent`, `Blend SrcAlpha OneMinusSrcAlpha`, `ZWrite Off`, `ZTest LEqual`, `Cull Back` (Inventar); `renderQueue` im Material −1 (Shader-Standard) |
| Keywords | `_ALPHABLEND_ON`, `_CASCADE_SINGLE`, `_ENVIRONMENTMAPENABLE_SPECULAR` |
| Instancing | nein |
| Grab-Pass | **keiner** (nur `Map/Water`, `Wave`, `Fog`, `WaterSurface`, `Encount01/02` haben `_BackgroundTexture`) |
| Texturen (Bindung über Eigenschaftsname) | `_CausticsTex` „Caustics“ 256×256 (Format 10 = DXT1/BC1), Kachelung 4×4; `_FlowMap` „Flow“ 256×256 (Format 27 = RGBA/BC7-Klasse laut Exporttabelle), 1×1; `_TimeOffsetMap` „TimeOffset“ 256×256 (Format 1 = Alpha8), Kachelung 5×5, Versatz 0,3 |
| Farben | `_WaterColor` (0,012 / 0,205 / 0,620, Alpha 0,698), `_Color` (0 / 0,626 / 1), `_SkyColor` (0,099 / 0,718 / 1), `_SpecularColor` (0,35 / 1 / 0,751), `_WaveColor` (0,344 / 1 / 1, Alpha 0,25), `_Reflectivity` (1,1,1) |
| Zahlen | `_CausticsIntensity` 6, `_CausticsExponential` 3, `_FlowSpeed` 0,1 (Vektor (1, 0, 1, 0)), `_FlowStrength` 0,015, `_TimeScale` 0,5, `_BumpScale` 0,67, `_FresnelPower` 3, `_RefractionScale` 3, `_ReflectionBias` 5, `_ReflectionOffsetScale` 1, `_DensityExponential` 2, `_MaxDensity` 1, `_TransDistance` 0,6, `_SpecularIntensity` 0,5, `_SpecularCosinePower` 18, `_Cull` 0 (Material), `_SrcBlend` 1, `_DstBlend` 0 |

Das Bild passt dazu: `_WaterColor` im Gamma-Raum ergibt tiefes Blau, `_CausticsIntensity` 6 mit Exponent 3 erzeugt wenige, sehr helle Linien (0,3 % der Pixel über 200). *Vermutet:* die Caustics-Textur wird mit zwei gegenläufig verschobenen UV-Sätzen (Zeit × `_TimeScale`, Versatz aus `_TimeOffsetMap`) gelesen, das erklärt das wandernde Netz; nicht am Shadercode überprüft.

## 3. Eingänge, die die Rekompilation liefern muss

Aus dem Inventar (`docs/shader-inventar.md`, Abschnitt Globals) und `docs/shader-globals.md`:

1. **`_OpaqueDepthTexture`** (`FlowmapWater`, `FlowmapBumpWater`): Tiefe nach dem undurchsichtigen Durchgang (`CameraEvent.AfterForwardOpaque`, `MultipleCameraCompositor`). Ohne sie rechnet der Shader mit Tiefe 0/1 und zeichnet in Unity eine einfarbige, braune Fläche (Beobachtung aus `sichtpruefung-3` im Git-Verlauf, **belegt** im Unity-Rebuild). Das Wasser darf nicht in diese Tiefentextur schreiben (`ZWrite Off`).
2. **`_ReflectionTex` und `_ReflectionVP`**: Reflexionskamera (`ReflectionCameraFollower`), an y = 0 gespiegelt, Position (x, −y, z), Drehung Euler(−x, y, −z), Sichtfeld = Hauptkamera · `_fovScale`, Textur Bildschirmgröße mit Mips. **Widerspruch im Inventar:** die Tabelle nennt `_ReflectionTex` nur bei `Map/FlowMap` und `Map/Standard`, `docs/shader-globals.md` Abschnitt 7 nennt sie auch für `FlowmapWater`; für Zone 24 ungeklärt, ob der Shader sie liest. Die Spiegelung der Brücke im Referenzbild spricht dafür (*vermutet*).
3. **`_Time`** aus der Spielzeit (Animation, siehe Abschnitt 1), plus die Spiel-Globals der Umgebung (`_SkyColor`-artige Werte kommen aus dem Material, Licht und `_ShadowColor` aus `EnvironmentController`).
4. **Blendzustand** aus dem Pass (`SrcAlpha OneMinusSrcAlpha`, `ZWrite Off`) und **Zeichenreihenfolge Transparent (Queue 3000)** nach allen undurchsichtigen Flächen; Cull Back. Das Netz hat keine Normalen (nur Position, Farbe, UV0 als Float16×2, `sichtpruefung-3` im Git-Verlauf): fehlende Normalen sind 0, die Normalen des Wassers kommen aus der Bump-Berechnung.
5. **Bindung der Texturen** erfolgt im Original über die Eigenschaftsnamen des Materials (`_CausticsTex`, `_FlowMap`, `_TimeOffsetMap`). In der Rekompilation kommen sie als Bindless-Handles in `cbuf 2` (ab 0x568, Schritt 8, `docs/render-treue.md`); sind die Handles falsch oder die Textur nicht geladen, erscheint eine einfarbige Fläche.

## 4. Grab-Pass (für die übrigen Wasser-Shader)

`Delphis/Map/Water`, `Wave`, `Fog`, `WaterSurface` besitzen einen Grab-Pass `_BackgroundTexture` vor dem Hauptpass. Das Spiel legt dafür **keinen** eigenen Puffer an; es ist Unitys `GrabPass` (Kopie des Bildes bis dahin). In der Rekompilation ist das ein Kopieren des aktuellen Farbziels in eine Textur zwischen undurchsichtigem und transparentem Durchgang. Für die Zone 24 spielt das keine Rolle (`FlowmapWater` hat keinen Grab-Pass). Messung im Unity-Lab: mit Grab-Pass scheint der Hintergrund durch das Wasser (Rot (209, 95, 96), Blau (65, 115, 245)), ohne bleibt ein konstanter Farbton (`docs/shader-globals.md`, Abschnitt 7).

## 5. Prüfen in der Rekompilation

- Region und Zahlen aus Abschnitt 1 verwenden: Mittel (87 / 127 / 210) ± 10 %, Standardabweichung ≈ (26 / 17 / 25), Anteil sehr heller Pixel ≈ 0,3 %.
- Zwei Aufnahmen im Abstand von 2 s: MAD in der Region ≈ 9, Mittel unverändert. Zeigt sich keine Bewegung, fehlt `_Time` (oder die Zeitkonstanten); zeigt sich Bewegung ohne Caustics-Netz, fehlt `_CausticsTex`.
- Vergleich mit `scripts/visual_compare.py ref compare` (Heatmap, Bildmittel). Dazu muss in `scripts/visual/ref_map.json` noch eine Ansicht für `free_wasser_a`/`b` ergänzt werden (nicht erledigt; ein manueller Vergleich beider Bilder reicht für die Zahlen oben).

## 6. Nicht geklärt

- Ob `FlowmapWater` in Zone 24 `_ReflectionTex` tatsächlich liest (Abschnitt 3, Punkt 2).
- Der Texturformat-Code 27 ist aus der Exporttabelle übernommen, nicht gegengeprüft.
- iPad-Start (2–3 Versuche bis zum Hochfahren): nicht untersucht, gehört zu `ap-recomp-ios`.
