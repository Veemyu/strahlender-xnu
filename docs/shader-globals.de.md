# Spiel-Globals, Schatten, Wasser und Nachbar-Texturen (Todo `ap-effects-fidelity`, Teil 1)

> **Historisch (Stand 2026-10-20):** Unity-Weg, eingestellt. Auf `main` entfernt (nur Branch `unity`): `scripts/environment_export.py`, `scripts/material_export.py` und ihre Tests. Die Befehle unten laufen auf `main` nicht mehr.

Stand 2026-10-19. Fragen: Wer setzt die 35 Spiel-Globals der Original-Shader (`_ShadowColor`, `_CloudParam`, `_PokeLightColor` …) und woher kommen die Werte? Wie erzeugt das Original Schatten, und läuft das mit unseren Shadern? Was macht das Original beim Wasser (Grab-Pass)? Wie lösen wir Texturverweise in Nachbar-Bundles auf?

Markierung: **belegt** = im dekompilierten Spielcode gelesen oder in Unity gemessen, *vermutet* = Schluss ohne Test. Quellen: `work/il2cpp/dump.cs` und `script.json` (Il2CppDumper), Ghidra-Projekt `work/ghidra/bdsp` (headless, `-readOnly`, Skripte `scripts/ghidra/`: `StringXrefs.java`, `CallersOf.java`, `ExportDecompiled.java`, Starter `run_headless.sh` mit Sperrdatei `work/ghidra.lock`), Pseudocode unter `work/decomp/effects*` (nicht im Repo). Adressen unten sind Il2CppDumper-RVAs (Ghidra = RVA + 0x100000). Im Repo stehen nur Code, Formeln und Zahlen, keine Spielwerte.

## 1. Ergebnis in Zahlen

| Frage | Ergebnis |
|---|---|
| Globals mit geklärtem Setter | **35 von 35** (Tabelle in Abschnitt 2); die Ghidra-Verweissuche über die Zeichenketten-Slots fand für jeden Namen die Klasse, die ihn in `PropertyToID` benutzt (`work/ghidra/globals_xrefs.txt`) |
| Davon aus Daten (Asset oder Szenenobjekt) | 18: `EnvironmentSettings` 10, Szenenobjekt 8; dazu 3 aus Spielzustand/Konstanten, 4 aus Kamera-Aufbauten (Reflexion, Tiefe), 6 aus Nachbearbeitung (CommandBuffer), 3 je Objekt (`MaterialPropertyBlock`), 1 aus dem TextMeshPro-Paket (Summe 35) |
| Per Code umgesetzt (`EnvironmentState`, `DepthOfFieldMath`, `Runtime/*`) | **26 von 35**; offen (9): `_UVOffset`, `_Corner`, `_RcpGridSize` (je Objekt), `_EnvMatrix` (Paket), `_FocusTex`, `_BlurOffsetX/Y`, `_DelayFrameTexture`, `g_BackgroundTexture` (Nachbearbeitung, Teil 2) |
| Lichtdaten im Spiel | **175** `EnvironmentSettings`-Assets (Bundle `Dpr/scriptableobjects/gamesettings`, je 5 Tagesabschnitte); **656 von 658** Zonen verweisen darauf (`MapInfo.ZoneData[].RenderSettings`), 97 verschiedene Assets werden benutzt; 556 Zonen haben `FixedTime` |
| Schatten mit unseren Shadern | **läuft** (Lab, Unity 6.3, Built-in, Gamma, Metal): Werfer-Pass im erzeugten Shader wirft sichtbaren Schatten, Empfänger-Pass bekommt den Bildschirmschatten von Unity; kein Eingriff in `shader_translator/` nötig (Abschnitt 6) |
| Kombinierte Shader (Forward + Schattenwurf im selben `.shader`) | `shader_wrap_all.py --combine-shadow`: 61 benutzte Varianten, 48 mit Schattenpass, **61 von 61 kompilieren** (37 s); im Zonentest 0 getrennte Schattenmaterialien nötig |
| Wasser/Grab | `GrabPass { "_BackgroundTexture" }` wird jetzt übernommen (7 Shader benannt + 2 unbenannt in `UI/Blur`); im Lab gemessen: Hintergrundfarben im Wasser mit Grab, konstanter Farbton ohne (Abschnitt 7) |
| Texturen in Nachbar-Bundles | **52 von 52** aufgelöst, alle in `Dpr/common_resources` (5 Bundles, 0 offen) |
| Tests | 18 neue C#-Tests (`RenderEnvironmentTests`) + 1 Unity-Test + 9 Python-Tests (`test_environment_export` 2, `test_material_export_external` 2, `test_shader_wrap` +5, ohne Spieldaten); Lab 37 von 37, `dotnet test` 29 von 29, Python 247 OK, `make test` im Übersetzer unverändert grün |

## 2. Tabelle: Global → setzende Klasse/Methode → Datenquelle

Setter-Kürzel: **EC.OU** = `EnvironmentController.OnUpdate` (RVA 0x1F0EB60, läuft jedes Bild, Abschnitt 3), **EC.SL** = `EnvironmentController.SetLight` (0x1F0FA10). Die Kennungen der Eigenschaften stehen als `static readonly int` im `EnvironmentController` und werden in dessen `.cctor` (0x1F109C0) per `Shader.PropertyToID` angelegt.

| Global | Art | Setter | Datenquelle | umgesetzt |
|---|---|---|---|---|
| `_ShadowColor` | Vektor | EC.OU | `Parameters.ShadowColor` des Tagesabschnitts (EC.SL kopiert sie), **× 0,5** (auch Alpha); bei Wetter „Schnee“ stattdessen `_SnowShadowColor` (Szenenobjekt) × 0,5 | ja |
| `_CloudParam` | Vektor | EC.OU | (Uhrzeit in Stunden · 60 · `_CloudSpeed.x`, dito y, `_CloudTiling.x`, `.y`); ist die Kachelung ≠ 0, wird x/y vorher `fmodf` 1/Kachelung genommen | ja |
| `_CloudShadowBase` | Float | EC.OU | **1 − `_CloudShadowBase`** (Szenenobjekt) | ja |
| `_CloudShadowScale` | Float | EC.OU (Wert aus EC.SL) | `Parameters.CloudShadowScale` | ja |
| `_CloudShadowTex` | Textur | EC.OU | `_CloudShadowTex` (Szenenobjekt), wenn die Wolkenschatten aktiv sind (`EnvironmentSettings.CloudShadowEnable`), sonst `Texture2D.blackTexture` | ja |
| `_GlobalLightPower` | Float | EC.OU | **statisches `globalLightPower` − 1** (Standard 1, also **0**); bei `_throughGlobal` 0 | ja |
| `_GlobalBumpScale` | Float | EC.OU | statisches `globalBumpScale` (Standard 1) | ja |
| `_EmissionScale` | Float | EC.OU | `_EmissionScale` (Szenenobjekt) | ja |
| `_EmissionThreshold` | Float | EC.SL und `SceneConnector.OnUpdate` | **(Tagesabschnitt + Fortschritt) · 0,2**, `Abschnitt` 0 Morgen … 4 Mitternacht; EC.OU reicht den Wert nur weiter | ja |
| `_VertexColorScale` | Float | EC.OU | `Parameters.VertexColorScale` | ja |
| `_ReflectorColor` | Vektor | EC.OU | `Parameters.ReflectorColor` | ja |
| `_CharacterLightColor` | Vektor | EC.OU | `Parameters.CharacterLightColor` · (I, I, I, 1), I = `CharacterLightIntensity` + `AddCharacterLightIntensity` | ja |
| `_CharacterReflectorColor` | Vektor | EC.OU | `Parameters.CharacterReflectorColor` | ja |
| `_PokeLightColor` | Vektor | EC.OU | `Parameters.PokeLightColor` · (I, I, I, 1), I = `PokeLightIntensity` + `AddPokeLightIntensity` | ja |
| `_PokeReflectorColor` | Vektor | EC.OU | `Parameters.PokeReflectorColor`; `SetPokemonLight` (0x1F10520) überschreibt die drei Pokémon-Werte aus einem anderen Abschnitt (Kampf, Pokémon-Ansicht) | ja |
| `_AdditionalBlurry` | Float | EC.OU | `Parameters.Blurry` (EC.OU setzt zusätzlich das statische `DepthOfField.blurry`) | ja |
| `_BloomThreshold` | Float | EC.OU | `Parameters.BloomThreshold` | ja |
| `_EnvironmentMap` | Textur | EC.OU | `_EnvironmentMap` (Szenenobjekt), sonst Weiß | ja |
| `_SnowTex`, `_SnowNormalTex` | Textur | EC.OU | `_SnowTex`, `_SnowNormalTex` (Szenenobjekt); Normalen sonst `Texture2D.normalTexture` | ja |
| `_NoiseTex` | Textur | EC.OU | `_NoiseTex` (Szenenobjekt), sonst Grau | ja |
| `_ReflectionTex`, `_ReflectionVP` | Textur, Matrix | `ReflectionCameraFollower.OnEnable` (0x19A5C10) / `.LateUpdate` (0x19A5F30) | Abschnitt 4.1 | ja (`ReflectionCameraDriver`) |
| `_OpaqueDepthTexture`, `_GlobalDepthTexture` | Textur | `MultipleCameraCompositor.OnReset` (0x1F7D4C0, CommandBuffer) | Abschnitt 4.2 | ja (`DepthCaptureDriver`, vereinfacht) |
| `_FocalCoefficient` | Vektor | `SmartPoint.Rendering.DepthOfField.Update` (0x2CA8EA0) | (d, f, 1/f, 1/max(d + f, 0,001)), d = Abstand Kamerafokus, f = Tiefenschärfe (Abschnitt 5) | ja (`DepthOfFieldMath`) |
| `_FocusTex`, `_BlurOffsetX/Y` | Textur, Vektor | `DepthOfField.Build` (0x2CA77F0), `Bloom.Build` (0x20A5050): CommandBuffer-`SetGlobal*` je Durchgang | Weichzeichner-Kern und Fokuskarte; Teil 2 | nein |
| `_DelayFrameTexture` | Textur | `Dpr.Rendering.FeedbackBlur.Build` (0x1BCFDB0) | Vorbild der Rückkopplung, Teil 2 | nein |
| `g_BackgroundTexture` | Textur | `Effect.EffectManager.SetupBackgroundTexture` (0x1F00310) | `DepthOfField.renderTexture` (heruntergerechnetes Szenenbild), je Bild nach `UpdateDistortionCamera` | nein |
| `_UVOffset` | Vektor | `FieldCharacterEntity.OnUpdate` (0x17885E0) | **je Renderer** als `MaterialPropertyBlock` (Augen- und Mundmuster, Blinzelkurve); kein Global | nein |
| `_Corner` | Vektor | `Snowfield.OnUpdate` (0x2CAAE70) | **je Fußabdruck** als `MaterialPropertyBlock` | nein |
| `_RcpGridSize` | Float | nur `ProceduralPlane.cctor` (Property-ID); kein `SetFloat` im Code | Materialeigenschaft des Footprint-Materials (*vermutet*) | nein |
| `_EnvMatrix` | Matrix | TextMeshPro-Paket (`TMPro.ShaderUtilities.GetShaderPropertyIDs`) | Materialeigenschaft des TMP-Shaders (Drehung der Umgebungsabbildung); Standard Einheitsmatrix | nein |

Andere Eigenschaften, die `EC.OU` zusätzlich setzt (nicht in unserer 35er-Liste, weil kein Bundle-Shader sie braucht): `_Wetness` (`_Wetness` des Szenenobjekts), `_MipTex` (Debug-Textur).

Folgerung für die Platzhalter: `GameGlobals.SetDefaults` setzte `_GlobalLightPower` auf 1; der Originalwert im Ruhezustand ist **0** (statisch 1 − 1). Das ist korrigiert (und im bestehenden Test nachgezogen). Zusätzlich: der Platzhalter `_CloudShadowBase` = 0 macht im Original-Shader **alles zu Schatten** (Abschnitt 6.3); der Originalwert ist `1 − Szenenwert`, bei Szenenwert 0 also 1 (Platzhalter ebenfalls korrigiert).

## 3. Ablauf: wer ruft wen

```
GameManager.OnUpdate            nowTime = DateTime.Now (Systemuhr) jedes Bild, solange nicht pausiert/ladend
SceneConnector.OnUpdate         (Feldszene, 0x19A7720)
  ├─ (Periode, Fortschritt, Gewicht) = GameManager.currentPeriodOfDayEx       (Abschnitt 3.1)
  ├─ Settings = MapInfo.ZoneData[PlayerWork.zoneID].RenderSettings            (Ausnahmen: Waza-Cut-In, Nebel)
  ├─ Zone mit FixedTime:  SetLight(Settings, Tag, 0, 0); _EmissionThreshold = (Fortschritt + Periode) · 0,2
  └─ sonst:               SetLight(Settings, Periode, Fortschritt, Gewicht)
EnvironmentController.SetLight  (nur der aktive Controller; Parameters = Settings.GetTransition(Periode, Gewicht))
EnvironmentController.OnUpdate  (Tick-Callback jedes Bild)  → alle SetGlobal* aus Abschnitt 2, Light, QualitySettings
```

Weitere Aufrufer von `SetLight`: 24 Stellen (Kampf-Sequenz `SpecialSetTimeZone`, Wettbewerb, Demos, GMS, Fossilien-Spiel, UI-Modellansichten, Timeline `TimeLineBinder`, Siegelvorschau …); sie bestimmen Settings und Periode selbst. `OnUpdate` stellt außerdem ein: `Light.intensity` = `Parameters.LightIntensity` + `AddLightIntensity`, `Light.color`, `Light.transform.eulerAngles` = (`PitchYaw.x`, `PitchYaw.y`, 0) (Settings liefert Pitch und Yaw), `Light.shadowNormalBias` = `_ShadowNormalBias`, `QualitySettings.shadowDistance` = `_ShadowDistance` und `shadowNearPlaneOffset` = `_ShadowNearPlaneOffset` (beide aus dem Szenenobjekt).

### 3.1 Tageszeit (`GameManager`, **belegt**)

`elapsedTimeOfDay` (0x2CD0A50) = `((tickOffset + timeScale · (nowTime.Ticks mod Tag)) mod Tag) / Tag · 24` in Stunden (Tag = 864 · 10⁹ Ticks; `nowTime` ist die Systemzeit, `tickOffset`/`timeScale` sind statische Felder für Debug und Zeitraffer, ohne direkte Aufrufer).

| Stunde | Periode | Länge (Minuten) |
|---|---|---|
| 4 bis 10 | 0 Morgen | 360 |
| 10 bis 17 | 1 Tag | 420 |
| 17 bis 20 | 2 Abend | 180 |
| 20 bis 2 | 3 Nacht | 360 |
| 2 bis 4 | 4 Mitternacht | 120 |

`currentPeriodOfDayEx` liefert zusätzlich Fortschritt p (0..1 im Abschnitt) und Gewicht **max((p · Länge − (Länge − 10)) · 0,1; 0)**: das Gewicht der Überblendung zum nächsten Abschnitt (Reihenfolge Morgen → Tag → Abend → Nacht → Mitternacht → Morgen) steigt **nur in den letzten 10 Minuten** von 0 auf 1. `EnvironmentSettings.GetTransition(Periode, Gewicht)`: Gewicht < 0,0001 → Werte des Abschnitts, > 0,9999 → Werte des nächsten, sonst Mischung: Farben `Color.Lerp`, Intensitäten `Mathf.Lerp`, Licht-Winkel auf dem kürzesten Weg (d − rund(d / 360) · 360), Nebel (Ein-/Ausblenden über den Alphakanal der Nebelfarben, sonst linear) und Farbkorrektur (Einfluss) sinngemäß. Alles in `TimeOfDay` und `EnvironmentSettingsData` umgesetzt und getestet.

## 4. Kamera-Aufbauten

### 4.1 Reflexion (`ReflectionCameraFollower`, **belegt**)

Eine zweite Kamera auf demselben Objekt, `targetTexture` = `RenderTexture(Bildschirmbreite, -höhe, Tiefe 24)` mit Mips und automatischer Mip-Erzeugung (neu angelegt bei geänderter Größe, sonst `SetCustomResolution`). Je Bild (`LateUpdate`): Position (x, **−y**, z), Drehung `Euler(−x, y, −z)` der Hauptkamera, **Sichtfeld = Hauptkamera · `_fovScale`**; `_ReflectionVP` = `GL.GetGPUProjectionMatrix(projectionMatrix, false)` · `worldToCameraMatrix`; `_ReflectionTex` = Zieltextur. Gespiegelt wird an der Ebene y = 0, die Wasserhöhe liegt also im Original bei 0.

### 4.2 Tiefe (`MultipleCameraCompositor`, **belegt**)

Alle Ebenenkameras (Haupt- und Layer-Kameras) rendern in **eine gemeinsame Farbtextur und eine gemeinsame Tiefentextur** (`SetTargetBuffers`); zwei `CommandBuffer`:

- `CameraEvent.BeforeForwardOpaque` (10) an der Compositor-Kamera: `_GlobalDepthTexture` = gemeinsame Tiefentextur, Blit der Farbtextur auf den Schirm;
- `CameraEvent.AfterForwardOpaque` (11) an der Hauptkamera: `_OpaqueDepthTexture` = `BuiltinRenderTextureType.Depth`.

Unsere `DepthCaptureDriver` setzt beide Texturen über dieselben Ereignisse mit `_CameraDepthTexture` (für **eine** Kamera gleichwertig; die gemeinsame Zieltextur mit mehreren Ebenenkameras ist nicht nachgebaut, Lücke 3).

## 5. Nachbearbeitung (nur soweit sie Globals betrifft)

`DepthOfField.Update`: `Abstand d` = |Ziel + `targetOffset` − Kameraposition|; ohne physikalische Kamera Brennweite aus Sichtfeld und Sensorhöhe `sensorScale · 24 mm`, `k = 0,024`, sonst `k = Sensorhöhe · 0,001`; **Tiefenschärfe f = (sensorScale · k · d · 0,5) / (Brennweite · 0,001)²**; `_FocalCoefficient` = (d, f, 1/f, 1/max(d + f, 0,001)). Die Weichzeichner-Versätze `_BlurOffsetX/Y` sind feste Kernkonstanten des Gauß-Durchgangs (vier Gleitkommazahlen in `get_blurOffset`, 0x2CA7790), je Durchgang als `CommandBuffer.SetGlobalVector` gesetzt. Fokuskarte, Weichzeichner, Bloom, FXAA/Farbkorrektur und Rückkopplung sind **CommandBuffer-Ketten** an der Hauptkamera (`GetTemporaryRT`, `Blit`, `SetGlobalTexture`); sie gehören zum Teil 2 (Effekte), die Struktur ist in Built-in unverändert übernehmbar.

## 6. Schatten

### 6.1 Das Original (**belegt**)

- **QualitySettings** (`globalgamemanagers`, Stufe „Ultra“, einzige Stufe): Schatten *All* (2), Auflösung High (2), Projektion StableFit (1), **eine Kaskade**, Entfernung 20, Nahebenen-Versatz 3, kein MSAA, 4 Pixellichter. Die letzte Stufe unserer `ProjectSettings` stimmt überein (`RenderSettingsTests`); `OriginalQuality.Apply()` setzt sie zusätzlich zur Laufzeit. `EnvironmentController` überschreibt je Bild Entfernung und Nahebenen-Versatz mit den Szenenwerten.
- **Licht**: ein Richtungslicht pro Szene, geführt vom `EnvironmentController` (Farbe, Intensität, Drehung, `shadowNormalBias` aus Szenenwert), Schatten im Szenen-/Prefab-Asset (Typ und Stärke dort, nicht aus dem Code ablesbar).
- **Shader**: Kein eigener Bildschirmschatten-Sammler im Code. Die Map-Shader sind Vorwärts-Shader mit `LightMode=ForwardBase` und Variante `SHADOWS_SCREEN` (sie lesen `_ShadowMapTexture` — Unitys eingebauter `Internal-ScreenSpaceShadows`-Durchgang erzeugt sie) und, wo vorhanden, einem **eigenen `ShadowCaster`-Pass** (7 Shader: `Delphis/Map/Standard`, `Map/Sky`, `Character/Standard`, `Character/DepthOnly`, `Poffin`, `Snowfield`, `Dpr/Objects/ShadowCast`). Die vier `Mitake/…`-Shader (`BumpShader`, `Petrify`, `Shader1st`, `GroundEffect1st`) benutzen `UsePass "Legacy Shaders/VertexLit/SHADOWCASTER"` (Unitys eingebauter Schattenwurf).

### 6.2 Unsere Lösung (**im Lab gemessen**)

Unity wählt den Schattenwurf aus dem **Shader des Materials**; ein Material = ein Shader. Darum erzeugt `scripts/shader_wrap.py` jetzt Shader mit mehreren Pässen:

| Option | Wirkung |
|---|---|
| (Standard) | **GrabPass** unmittelbar vor und **UsePass** unmittelbar hinter dem Hauptpass aus dem Inventar werden in Originalreihenfolge übernommen (`--no-aux` schaltet das ab) |
| `--also PASS[:KW,KW]` | weiterer Normal-Pass (typisch der `SHADOWCASTER`-Pass mit `SHADOWS_DEPTH`) im selben SubShader; Eigenschaften einmal im Kopf, jeder Pass mit eigenem `HLSLPROGRAM` |
| `shader_wrap_all.py --combine-shadow` | je Forward-Variante den passenden Schattenwurf-Pass wählen (Regel wie `ShaderVariantResolver`: Keywords des Materials geschnitten mit denen des Wurf-Passes plus `SHADOWS_DEPTH`; sonst ohne `INSTANCING_ON`); `variants.json` bekommt `shadow` (Pass, Keywords) und `aux`; lässt sich der Schattenwurf nicht übersetzen, entsteht die Variante ohne ihn (`shadowError`) |

C#: `VariantEntry.EmbeddedShadowKeywords` liest `shadow`; `MaterialRemapper` baut dann **kein** getrenntes `ShadowCaster`-Material mehr (`RemapResult.ShadowEmbedded`).

Messaufbau (`work/unity-shader-lab/Assets/Editor/ShadowTest.cs`, nicht im Repo): Ebene (Empfänger) und Würfel (Werfer), beide mit `Delphis/Map/Standard` (Forward `DIRECTIONAL SHADOWS_SCREEN _CASCADE_SINGLE` + Wurf `SHADOWS_DEPTH`), Richtungslicht Euler (50, 40, 0), weiche Schatten, QualitySettings wie im Original (eine Kaskade, StableFit, Entfernung 20), Kamera Forward.

| Fall | Ergebnis |
|---|---|
| Kontrollshader von Hand (`multi_compile_fwdbase`, `SHADOW_ATTENUATION`) | Schatten sichtbar, Unitys Bildschirmschatten läuft in diesem Lab |
| Unser Werfer-Pass (Würfel) + Kontroll-Empfänger | **Schatten sichtbar**: der erzeugte `SHADOWCASTER`-Pass mit Tag `LIGHTMODE=SHADOWCASTER` (Großschreibung wie im Inventar) wird von Unity gefunden |
| Unser Empfänger + unser Werfer, Platzhalter `_CloudShadowBase` = 0 | Fläche **komplett im Schatten** (Mittel (100, 100, 100)), kein Würfelschatten sichtbar; Ursache nicht der Schattenpfad, sondern der Platzhalter: der Shader nimmt `min(Schattentextur, Wolkenterm)`, der Wolkenterm ist mit `_CloudShadowBase` = 0 immer 0 |
| Unser Empfänger + Werfer, `_CloudShadowBase` = 1 | **Würfelschatten sichtbar** (Schattenzone/freie Fläche = 181 / 198, Würfeldach 203); das Bild ist mit und ohne `#pragma multi_compile_fwdbase` pixelgleich, der Pragma ist also nicht nötig: Unity liefert den Bildschirmschatten auch an einen Shader ohne Keyword-Varianten |
| Werfer per `UsePass` (Mitake) | Schatten sichtbar (Würfel aus `MitakeStandardBumpShader`, Variante `DIRECTIONAL LIGHTPROBE_SH SHADOWS_SCREEN`) |
| eine Kaskade statt vier | gleiches Bild |
| Zone 422, `--combine-shadow`-Varianten | 34 von 34 Materialien vollständig, **0** getrennte Schatten-Materialien, Bild plausibel (Abschnitt 6.4) |

**Treue:** Eine Referenz (Switch-Bild) gibt es nicht; geprüft ist, dass die **Pässe und Unitys Pfade wie im Original arbeiten** (Werfer, Bildschirmschatten, Kaskade 1, Entfernung 20) und der Schatten an der richtigen Stelle erscheint. Pixelgleichheit gegen die Switch ist nicht messbar. Die Schattenform hängt von Unitys Schattenerzeugung ab; sie ist in Unity 2019.4 (Original) und 6.3 (hier) im Built-in-Pfad gleich aufgebaut, **bitgleich** gilt das nicht belegt.

### 6.3 Befund: Platzhalter-Globals verfälschen den Schatten

Der Forward-Shader mischt (aus dem erzeugten HLSL gelesen: Schattenprobe, Wolkenterm, `_ShadowColor`, Licht) Bildschirmschatten, Wolkenschatten (`_CloudShadowTex`, `_CloudShadowScale`, `_CloudShadowBase`, `_CloudParam`), `_ShadowColor` und Licht (`_GlobalLightPower`). Mit den bisherigen Platzhaltern (Basis 0, Farbe 0) wirkte die ganze Karte wie im Schatten (Mittel (29, 38, 22) in Zone 422). Mit den abgeleiteten Werten (Abschnitt 6.4) ändert sich das Bild stark.

### 6.4 Zone 422 mit abgeleiteten Globals (Lab, `MatRender`, 960 × 540)

`EnvironmentDriver` mit den echten Daten der Zone (`FieldRenderSettings`, keine `FixedTime`), kombinierte Varianten (`--combine-shadow`), Szenenfelder des Controllers auf Standardwerten (Lücke 1):

| Zustand | Bildmittel RGB | Anmerkung |
|---|---|---|
| Platzhalter (`SetDefaults`, alter Stand) | (26, 34, 20) | Karte „im Schatten“ |
| Stunde 12 (Tag) | (83, 104, 62) | Haus, Wald, Wiese erkennbar hell; Bild unter `work/matremap/shots/ap_env12.png` |
| Stunde 22 (Nacht) | (65, 79, 43) | dunkler, kühleres Licht |

Das Bild zeigt, dass die Datenkette (Zone → Settings → Periode → Globals → Shader) funktioniert; ein Pixelvergleich mit der Switch bleibt unmöglich (keine Referenzbilder).

## 7. Wasser und Grab-Pass

**Original (belegt):** Die Wasser-Shader benutzen Unitys eigenen `GrabPass`: Inventar-Pässe vom Typ *Grab* mit Textur `_BackgroundTexture` bei `Delphis/Map/Water`, `Wave`, `Fog`, `FlowMap`, `WaterSurface`, `Delphis/Battle/Encount01/02`, ein unbenannter in `UI/Blur` (zweimal, Standardtextur `_GrabTexture`). Das Spiel selbst legt **keinen** eigenen CommandBuffer für den Hintergrund an (der Code kennt `_BackgroundTexture` nicht, nur `g_BackgroundTexture` aus der Tiefenschärfe-Textur für die Partikel). `FlowmapWater`/`FlowmapBumpWater` haben **keinen** Grab-Pass: sie lesen `_OpaqueDepthTexture`, `_ReflectionTex`, `_ReflectionVP` (Abschnitt 4).

**Entsprechung in Built-in:** `GrabPass { "_BackgroundTexture" }` ist dasselbe Verfahren. Der Wrapper schrieb bisher nur Normal-Pässe; jetzt steht der GrabPass vor dem Pass des erzeugten Shaders (`aux_blocks`). Test (`GrabTest.cs` im Lab): zwei Flächen (rot/blau) unter einer Wasserfläche mit `Delphis/Map/Water`, Kamera mit `DepthTextureMode.Depth`:

| Shader | `_BackgroundTexture` nach dem Rendern | Wasser über rotem / blauem Grund |
|---|---|---|
| mit GrabPass | 256 × 256 Textur gebunden | (209, 95, 96) / (65, 115, 245) |
| ohne (`--no-aux`) | keine | (136, 168, 169) / (139, 171, 172) |

Der Hintergrund scheint durchs Wasser, wie es der Grab-Pass soll; `isSupported` bei beiden Shadern wahr. Offen: Vergleich mit dem Switch-Bild (nicht möglich) und das Strömungsbild mit echten `_FlowMap`/`_NormalMap` aus den Bundles (Teil 2).

## 8. Texturen aus Nachbar-Bundles

`scripts/material_export.py --resolve-external` löst Texturverweise mit `FileID ≠ 0` auf: CAB-Name aus der externen Dateiliste des Bundles, Kandidaten sind die Abhängigkeiten laut Katalog (`work/dpr_catalog.json`, Feld `deps`; die Namen tragen keinen Ordner, jeder Ordner von `AssetAssistant` kommt in Frage, entscheidend ist der CAB-Name im Bundle), Texturtabelle (Name, Größe, Format) des gefundenen Bundles. Der Eintrag bekommt `texName`, `width`, `height`, `format` und `extBundle`.

| Messgröße | Wert |
|---|---|
| Texturverweise aller Materialien (640 Bundles `Environments/`) | 30.609 |
| davon in Nachbar-Bundles | **52** in 5 Bundles (`prefab_map/d29r0101`, `d29r0102`, `d05r0104`, `d05r0105`, `fields/area009`) |
| aufgelöst / offen | **52 / 0**, alle in `Dpr/common_resources` |

C#: `MaterialTextureRef.ExternalBundle` trägt das Bundle; `LoadedTextureIndex` findet die Textur wie bisher über Name und Größe, **wenn `Dpr/common_resources` geladen ist** (Abhängigkeit des Katalogs, `BundleProvider` lädt sie ohnehin mit). Namensgleiche Texturen gleicher Größe bleiben ein theoretisches Risiko (bisher 0 Fehlgriffe).

## 9. C#-Umsetzung

| Datei | Inhalt |
|---|---|
| `Scripts/Render/TimeOfDay.cs` | `PeriodOfDay`, Uhrzeit aus Ticks, Periode, (Periode, Fortschritt, Gewicht) |
| `Scripts/Render/EnvironmentData.cs` | `Rgba`, `EnvironmentParameters`, `EnvironmentSettingsData` (`GetTransition`), `EnvironmentSettingsCatalog` (liest `EnvironmentSettings.json` und `MapRenderSettings.json` von `scripts/environment_export.py`) |
| `Scripts/Render/EnvironmentState.cs` | Port von `SetLight`, `SetPokemonLight`, `OnUpdate` (`Apply` setzt 21 Globals über `GameGlobals`), `FieldLighting` (SceneConnector), `DepthOfFieldMath`, `DefaultTextures` |
| `Scripts/Render/GameGlobalSources.cs` | Tabelle des Abschnitts 2 als Daten (`GameGlobalSources.All`, ein Eintrag je `GameGlobals.Specs`) |
| `Scripts/Render/Runtime/EnvironmentDriver.cs` | `EnvironmentDriver` (setzt Licht, Qualität, Globals je Bild), `OriginalQuality` |
| `Scripts/Render/Runtime/CameraRigs.cs` | `ReflectionCameraDriver`, `DepthCaptureDriver` |
| `Scripts/Render/Runtime/UnityGlobalSink.cs` | Textur-Platzhalter `black`/`white`/`gray`/`bump` → Unity-Standardtexturen |
| `Scripts/Render/RenderChecks.cs`, `Runtime/SunLight.cs` | Regeln gegen schwarzes Bild (kein Licht, Licht ohne Intensität, Globals ungesetzt, mehrere Lichter), `SunLight.Ensure/FindActive/Collect`, `RenderHealthWatch` (Abschnitt 10a) |
| `scripts/environment_export.py` | exportiert die Settings und die Zonenzuordnung nach `work/masterdata/` |

Konstanten (Faktor 0,5, 1 − Basis, −1, 0,2, 60, 0,0001/0,9999, 10 Minuten, `k` = 0,024) sind im Test festgelegt (`RenderEnvironmentTests`, 18 Tests: Abschnittsgrenzen, Gewicht, Ticks, Überblendung inklusive Winkel und Nebel, alle Formeln von `Apply`, Schnee, Wolkenschatten, FixedTime, Katalog, Quellentabelle). Die Konstruktor-Vorgaben der Szenenfelder (Wolkengeschwindigkeit, -kachelung, Schattenfarben) stehen **nicht** im Repo: serialisierte Werte überschreiben sie ohnehin.

## 10. Lücken (Stand)

1. **Szenenwerte des `EnvironmentController`** (`_CloudSpeed`, `_CloudTiling`, `_EmissionScale`, `_CloudShadowBase`, Texturen, Schattenentfernung/-versatz/-bias, `_WeatherMode`, `_SnowShadowColor`) stehen im Szenenobjekt (Prefab) der Karte, nicht in den Tabellen. Der Export liest sie noch nicht; `EnvironmentSceneParams` hat die Felder, ihre Quelle (Prefab-Komponente im Bundle) ist nicht angebunden. Zone 422 lief deshalb mit Standardwerten dieser Felder.
2. **Wetter:** `MapInfo.Weather` (`SYS_WEATHER`) und der Kalender (`CalenderEncTable.weather`) steuern Regen/Schnee und `SkyColorSettings`; die Verbindung zu `_WeatherMode` ist nicht verfolgt.
3. **Mehrere Ebenenkameras** (Compositor mit gemeinsamer Farb-/Tiefentextur) nur für eine Kamera nachgebaut.
4. **Nachbearbeitung** (Weichzeichner-Kern, Fokuskarte, Bloom, Farbkorrektur, Rückkopplung, `g_BackgroundTexture`) und die drei je-Objekt-Eigenschaften (`_UVOffset`, `_Corner`, `_RcpGridSize`) fehlen (Teil 2).
5. **`GameManager.nowTime`** ist die Systemzeit; ob das Spiel sie bei Bedarf anders setzt (Debug, Ereignisse), ist nicht verfolgt.
6. **Schatten-Treue** nur strukturell geprüft (kein Referenzbild); Spiel-Licht (Schattenstärke, Auflösung je Szene) liegt im Prefab.
7. **`UsePass "Legacy Shaders/VertexLit/SHADOWCASTER"`** setzt voraus, dass Unitys eingebauter Shader im Player enthalten ist (Build-Schritt für `Always Included Shaders`, nicht geprüft).
8. **`multi_compile_fwdbase`** ist nicht nötig (gemessen), alle Lab-Ergebnisse mit Unity 6000.3.26f1 auf Apple M1 Pro; andere GPUs nicht geprüft.

### 10a. Nachtrag 2026-10-19 (`ap-effects-fidelity`, Teil 2): Globals gegen Licht, Bild schwarz, „Hänger“

Ausführlich mit Methode und Logbelegen: `docs/material-remap.md`, Abschnitt 10b. Was für die Globals daraus folgt (Lab, Zone 422, 34 Materialien, Gamma, Bildmittel RGB aus `RenderTexture`; `FieldController` echt: „Umbau (Shader 61/61, 124 Materialeinträge)“):

| Zustand | Bildmittel | Lehre |
|---|---|---|
| kein Richtungslicht, Globals egal (Platzhalter oder null) | **(0, 0, 0)** | Die Forward-Shader multiplizieren mit `_LightColor0`; ohne Licht ist alles schwarz, auch wenn alle 35 Globals gesetzt sind. `SunLight.Ensure` (Render/Runtime) stellt ein Licht sicher, `EnvironmentDriver` setzt danach Farbe/Intensität/Drehung aus den Spielwerten. |
| Richtungslicht, alle Globals null | (31, 39, 23) | Nicht schwarz: ohne Globals nur dunkler (`_ShadowColor`, `_GlobalLightPower`, Wolkenterm 0). |
| Richtungslicht, Platzhalter (`SetDefaults`) | (37, 49, 28) | Der Platzhalter ändert gegenüber „alle null“ nur wenig (+6, +10, +5). |
| Richtungslicht, Spielwerte Zone 422, Stunde 12 | (83, 104, 63) | wie Abschnitt 6.4; derselbe Wert mit weichen Schatten (4 Kaskaden, Distanz 20): im Mittel unverändert. |

Folgerungen: (1) „Globals ungesetzt“ erklärt nie ein schwarzes Bild, sondern ein zu dunkles; ein **schwarzes** Bild ist in dieser Kette immer „kein/dunkles Licht“ (Regeln in `Render/RenderChecks.cs`, geprüft von `RenderChecksTests`). (2) Die Platzhalter taugen für Sichttests nur grob; Bildmessungen immer mit `EnvironmentDriver` und den Zonenwerten (Stunde wählbar). (3) Zeitbedarf der Globals: ein `Tick` ist reine Rechnung plus 21 `Shader.SetGlobal*`; keine Kompilierung, keine Variantenwahl – der Editor-Hänger der Haupt-Sitzung hatte mit Globals und Shadern nichts zu tun (Ursache: `run_tests` im Spielmodus).
Lücken (unverändert): Szenenwerte des `EnvironmentController`, Nachbearbeitungs-Globals (9 offen), Switch-Referenzbild.

### 10b. Nachtrag 2026-10-19 (`ap-effects-fidelity`, Teil 4): Szenenwerte, `_ShadowMapTexture`, Nachbearbeitung

Ausführlich: `sichtpruefung-2` (Git-Verlauf; Abschnitte 5, 7, 8, 9).

| Thema | Ergebnis |
|---|---|
| Szenenwerte des `EnvironmentController` (Lücke 1 aus Abschnitt 10) | **Gelesen** aus `Dpr/scenes/field` (`scripts/environment_export.py` → `EnvironmentScene.json`): Schattenentfernung **45**, Nahebene **15**, Normal-Bias 0, Wolken `_CloudSpeed` (0,5; 0,5), `_CloudTiling` (0,03; 0,03), `_CloudShadowBase` 0, `_EmissionScale` 1, `_WeatherMode` 0, Schattenfarbe (0,41; 0,46; 0,53); andere Szenen (`battle`, `gms`, …) 20 und 3. Texturen `_NoiseTex`, `_SnowTex`, `_SnowNormalTex`, `_EnvironmentMap` benannt, `_CloudShadowTex` nicht aufgelöst. `EnvironmentDriver` lädt die Datei selbst (`EnvironmentSceneData`). |
| Schattenentfernung | Das Original überschreibt die Qualitätsstufe (20) je Bild mit dem Szenenwert 45; damit erscheinen die Schatten in Zone 422 (22,06 % der Pixel dunkler, Bildmittel (101,8 / 125,0 / 72,5) → (94,2 / 116,8 / 67,2)); mit 20 liegt die Bildmitte außerhalb (0 Pixel Unterschied). |
| `_ShadowMapTexture` (neues, 36.) Global | Wird nur in Bildern mit Schattenkarte gesetzt; ohne Karte bleibt ein freigegebener Verweis stehen und bindet Schwarz („alles im Schatten“). Ursache der „19 % dunkler nach Zone 54“. `ShadowMapGuard` setzt vor jedem Kamerabild Weiß; Zone 422 nach 54 wieder (101, 124, 72). |
| Offene Nachbearbeitungs-Globals (Teil 1: 9 offen) | `_BlurOffsetX/Y` **belegt** (Vektor (−2,2186; 2,2186; −0,6075; 0,6075), je Durchgang X oder Y, Bitmuster `0xC00DF8DF, 0x400DF8DF, 0xBF1B9852, 0x3F1B9852`) und im Bloom (`PostChain`) gesetzt; `_SubTex0..4` (Bloom-Ebenen) ebenfalls; weiter offen: `_FocusTex`, `_DelayFrameTexture`, `g_BackgroundTexture` (Tiefenschärfe, Rückkopplung, Partikel), `_UVOffset`, `_Corner`, `_RcpGridSize`, `_EnvMatrix`. |

## 11. Reproduktion

```sh
export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer
PYTHONPATH=tools/pydeps python3 scripts/environment_export.py                              # work/masterdata/EnvironmentSettings.json, MapRenderSettings.json
PYTHONPATH=tools/pydeps python3 scripts/material_export.py --out work/materials --resolve-external --dir Environments
python3 scripts/shader_wrap_all.py --out work/shaders/combined --used work/materials/used_variants.json --combine-shadow
python3 scripts/shader_wrap.py 'Delphis/Map/Standard' --pass 0 --keywords DIRECTIONAL SHADOWS_SCREEN _CASCADE_SINGLE --also 1:SHADOWS_DEPTH --out work/unity-shader-lab/Assets/XnuGen/x.shader
python3 scripts/shader_wrap.py 'Delphis/Map/Water' --pass 1 --out work/unity-shader-lab/Assets/XnuGen/water.shader   # mit GrabPass
# Ghidra (nur eine Instanz zugleich; Sperrdatei work/ghidra.lock, wartet bis 20 Minuten)
scripts/ghidra/run_headless.sh <Name> work/ghidra/x.log -postScript StringXrefs.java work/ghidra/out.txt _ShadowColor=0x4CAB640
scripts/ghidra/run_headless.sh <Name> work/ghidra/x.log -postScript ExportDecompiled.java '^EnvironmentController\$\$' work/decomp/effects
scripts/ghidra/run_headless.sh <Name> work/ghidra/x.log -postScript CallersOf.java work/ghidra/callers.txt 'EnvironmentController\$\$SetLight'
python3 -m unittest discover -s scripts/tests
```
