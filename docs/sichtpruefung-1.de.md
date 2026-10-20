# Sichtprüfung 1: erstes Bild der Zone 422 mit den erzeugten Shadern (Todo `ap-effects-fidelity`, Teil 3)

Stand: 2026-10-19, Unity 6000.3.26f1 (Haupt-Editor, Projekt `unity/`), macOS (M1 Pro), Built-in RP, Gamma, Metal. Szene `FieldTest2` im Spielmodus mit `XNU_GENERATED_SHADERS=1`:
„Umbau (Shader 61/61, 124 Materialeinträge)“, Spielwerte aus `EnvironmentSettings` (Stunde 12), **nur** unsere erzeugten Shader und der Ersatz-Shader der Figuren; kein Original-Shader geladen, **kein Ton**.
Die Bilder liegen nur unter `work/visual/` (gitignoriert); hier steht deshalb eine Beschreibung. Aufnahme per `Camera.Render` in eine `RenderTexture` (1280 × 720, Alpha = 255, Gamma), weil `ScreenCapture` Cyan liefern kann (`Field/Editor/FieldShot.cs`).

## 1. Was auf den Bildern zu sehen ist

**Zone 422 (Zwieblüh, Stunde 12, Kamera Gier 180, Neigung 45,0°, FOV 17,5°).** Das Bild ist als Zwieblüh erkennbar und stimmig: Das Spielerhaus mit grünem Schindeldach, Schornsteinen, Holzstämmen, Tür und drei Fenstern, davor der Briefkasten (orange), links das Nachbarhaus (Dach, Fenster), rechts Nadelbäume mit Alphatest-Laub, Wiese mit Blümchen und Gräsern, hellbrauner Weg, Wegweiser oben. Bildmittel **(101, 125, 72)**.
Kein schwarzer oder magentafarbener Bereich in der Karte, keine gespiegelte oder umgedrehte Geometrie (Dachschindeln, Fenster, Holz stimmen; Windung/Cull unauffällig), kein Durchscheinen hinter Laub. Texturen und Kachelung sind richtig zugeordnet. Farben: Gras mittelgrün mit leichtem Gelbstich, Boden ocker, Dach dunkelgrün – im Gamma-Projekt plausibel, nicht überbelichtet. Die Schattenfarbe (blau-violett, `_ShadowColor`) ist nur an Wandkanten zu ahnen.

**Tageszeit (derselbe Standort, `EnvironmentDriver`, Stunde über `XNU_ENV_HOUR`):**

| Stunde | Bildmittel | Beobachtung |
|---|---|---|
| 7 | (99, 120, 75) | leicht wärmer/grüner als Mittag |
| 12 | (101, 125, 72) | Tagesbild |
| 18,5 | (103, 121, 67) | Abend, wärmer |
| 22 | (57, 75, 49) | dunkel; **Fenster leuchten** gelb-orange (Emission über `_EmissionThreshold`) – genau das Verhalten eines Nachtbildes |

**Zone 425 (Spielerhaus, Stunde 12, Raumeinstellungen).** Wohnraum vollständig: Holzboden, gestreifte Tapete, Küchenzeile mit Spüle und Herd, Kühlschrank, Fernseher (Bildschirm schwarz), Teppich, Tisch mit Stühlen, Treppe, zwei Topfpflanzen, Fußmatte an der Tür unten. Der Raum steht freigestellt vor der einfarbigen blauen Kamerahintergrundfarbe (kein Himmel im Raum). Bildmittel (128, 144, 166), 85 Renderer.

**Zone 54 (Stadt mit Pokémon-Center, Neigung 40°, FOV 18°).** Fischgrätpflaster, Pokémon-Center mit rotem Dach und Pokéball-Zeichen, Nachbarhaus mit gelbem Dach und blauer Tür, Zaun links, Gitterdach rechts unten. Bildmittel (139, 126, 98).

**Zone 367 (Route 209, Tor zu Herzhofen).** Nach der Fehlerbehebung (Abschnitt 3) erscheint die Karte: Torgebäude mit blauem Wellblechdach, Fenster, Backsteinsockel, Zaun, Wegweiser, hohes Gras rechts oben, Laubbäume. Bildmittel (99, 122, 65).

**Spielerfigur.** Ausrichtung stimmt (Blick zur Kamera, wie beim Verlassen des Hauses), sie steht vor der Haustür. Höhe im Bild ≈ 1,35 Zellen (Ziel 1,4). Die Figur ist **weißlich/grau ohne richtige Texturfarben** (Ersatz-Shader, siehe offene Fehler). **NPC-Marker:** blaue Kapseln mit weißem Fleck (Zone 54 links, Zone 425 auf dem Teppich) – wie vorgesehen Platzhalter. Unter der Figur in Zone 422 liegt ein blau-braunes, unregelmäßiges Gebilde; es gehört zur Karte (Pfütze/Dekal), nicht zur Figur (nicht weiter geprüft).

**Himmel/Hintergrund.** Es gibt keinen Himmel: Die Kamera löscht mit einer einfarbigen Farbe (0,45 / 0,62 / 0,85). In Außenzonen füllt die Karte das Bild, am Kartenrand erschiene diese Farbe.

**Kamera.** 45° Neigung, FOV 17,5° (Zone 422) bzw. 20° (425, 367) bzw. 18° bei 40° (54): kommen aus den Stammdaten (`CameraTable`) und geben ein Bild mit kaum sichtbarer Perspektive wie in BDSP. Das Zellraster ist mit der Karte deckungsgleich (Haus 5 Zellen breit, Sperrzellen unter dem Haus, Tür in der Zelle (116, 885)).

## 2. Zahlen (Spielmodus im Editor, `get_performance_stats`, 3 Messungen, Spielfenster 1493 × 840)

| Zone | Renderer im Kartenbaum | Blöcke | Draw-Calls | SetPass | Dreiecke | Vertices |
|---|---|---|---|---|---|---|
| 422 | 1.484 (5 von 12 Containern) | 4 | 155 | 51 | 53.793 | 38.692 |
| 425 | 85 | – | 197 | 88 | 26.511 | 23.518 |
| 54 | 1.737 (kumulativ gebaut) | 6 | 291 | 153 | 224.673 | 251.916 |
| 367 | 1.910 (kumulativ gebaut) | 4 | 323 | 56 | 205.121 | 249.192 |

Frame-Zeit Zone 422: CPU-Frame 33,5 ms (30 Bilder/s, `targetFrameRate` 30, V-Sync-Stufe laut Projektvorgabe), Hauptthread 1,3 ms, GPU 25 bis 27 ms im Editor-Spielfenster (enthält Editor-Zeichnung; eine Messung 48 ms). Speicher Unity ≈ 620 MB reserviert 1,09 GB. Das Aufnehmen selbst (Render + Rücklesen, 1280 × 720) 44 bis 84 ms. Zonenwechsel: 422 → 425 375 ms, 425 → 54 908 ms (mit Karte neu laden, Überblendung).
Zonenspeicher laut `FieldMemoryLog` (Zone 54): Unity 569 MB, Grafik 270 MB, Texturen 91 MB.
Die Editor-Zahlen sind keine Player-Zahlen; im Player-Build gelten `docs/player-build-1.md`.

## 3. Gefundene und behobene Fehler

1. **Kamera-Gier im Freien (Bildfehler, behoben).** Mit Gier 0 (frühere Annahme) blickte die Kamera nach +Z: Die Haustür (Code 105 bei (116, 885), also auf der +Z-Seite des Hauses) lag *hinter* dem Haus, der Spieler stand hinter dem Dach (Bildmittel (83, 104, 63), unsichtbar), das Haus zeigte seinen fensterlosen Giebel. Mit Gier **180** (Zellraster: x nach rechts, y nach unten, Haus von vorn mit Tür und Fenstern, der Spieler verlässt das Haus mit Blick zur Kamera, wie im Spiel) stimmt das Bild; dazu passt auch, dass die Locator-Blickrichtung z = 0 „weg von der Tür“ bedeutet. Neu: `FieldController.fieldCameraYaw` (Standard 180; vorher fest 0, Raumgier unverändert 180). Die frühere Annahme aus `docs/feld-szene-1.md` (Gier 0 außer bei Systemflag `0x305`) bleibt als Befund der Dekompilierung stehen, ist aber für die Anfangszone widerlegt; die Bedeutung von `0x305` ist offen.
2. **Zone 367 zeigte nur den Hintergrund (behoben, mit Test).** Ursache: Das Streaming ordnete jeden Container (`R209`, `T05`, …) nur dem Block seines **Ursprungs** zu (`round(−x/32)`, `round(z/32)`). Container der Route reichen über mehrere Blöcke und liegen teils nicht auf dem 32er-Raster (`T04` bei x = −540, `C07` bei −678/574). Der Container `R209` hat den Ursprung bei z = 672 (Zeile 21), seine Meshes reichen bis Zeile 24, der Startpunkt (512, 726) liegt in Zeile 22: kein Block dort, der nächste lag 23 Zellen entfernt (Ladeabstand 20) → 0 Renderer. Neu: `FieldAreaStreamer` berechnet je Container das Weltrechteck aus den Mesh-Bounds (`BlockStreamingMath.BlocksCovering`, höchstens 16 Blöcke je Achse) und ordnet ihn allen berührten Blöcken zu; ein geteilter Container wird einmal gebaut und erst mit dem letzten Block abgebaut (Zähler). Zone 422 lädt dadurch 4 statt 1 Block mit 5 Containern.
3. **Spielerhöhe am Start in Zone 367 (behoben, mit Test).** Der Boden liegt dort bei y = 2; der Boden-Strahl begann bei 0 + 1,2 und traf nichts (Höhe 0 → Figur unter dem Boden). `RaycastGround.SpawnSearch` sucht beim Platzieren (Teleport) von oben (nur dann, normale Schritte unverändert).
4. **Spielerfigur und NPC-Marker magenta nach dem Zonenwechsel (behoben, mit Test).** `RemappedMaterials.Destroy` zerstörte den *gemeinsamen* Ersatzspeicher, den auch die Figur benutzt. Jetzt gibt es nur die selbst angelegten Ersatzmaterialien der Karte frei (`FallbackMaterials.Release`).
5. **Figurenhöhe aus falschen Bounds (behoben).** Die Höhe 5,07 ergab sich aus allen Renderern des Prefabs, auch aus ausgeschalteten (Reittiere, Fahrrad, Alternativmodelle); daraus folgte ein Maßstab 0,28. Jetzt zählen nur aktive, eingeschaltete Renderer: Höhe 1,41 → Maßstab 1,0. Im Bild blieb die Figur gleich groß (≈ 1,35 Zellen), die Animation setzt die Größe offenbar selbst; die 1,4-Annahme ist damit nicht mehr nötig, bleibt als Zielwert.
6. **Spielwerte statt Platzhalter, Licht (Auftrag 2).** `FieldController.EnsureRenderEnvironment` benutzt `SunLight.Ensure(transform, Soft)` statt des Eigenbaus und hängt einen `EnvironmentDriver` an die Sonne: Settings der Zone aus `work/masterdata/EnvironmentSettings.json` und `MapRenderSettings.json` (Standard `<GameData>/masterdata`), Stunde aus `XNU_ENV_HOUR`, sonst `environmentHour`, sonst lokale Uhr (`useGameEnvironment`, `environmentHour`). Zonen ohne Settings (2 von 658) oder ohne Katalog behalten die Platzhalter und die weiße Sonne. Zone 422: Sonne Intensität 1,15, Farbe (0,93, 0,93, 0,93), Drehung (75, 345, 0), Schattenentfernung 20; der Wert (101, 125, 72) gegenüber (37, 49, 28) mit Platzhaltern entspricht `docs/shader-globals.md` Abschnitt 10a.

Tests: Unity EditMode **645 von 645** grün (vorher 638; neu 7 in `FieldStreamerContainerTests`: Blockabdeckung, Begrenzung, Containerzuordnung 367, geteilter Container, Boden-Suche von oben, Ersatzmaterial-Freigabe), Python `scripts/tests` 268 OK, `make test` im Übersetzer grün. `shader_translator/` und `scripts/shader_wrap.py` blieben unverändert.

## 4. Offene Fehler und Lücken

1. **Figur und NPC-Marker tragen den Ersatz-Shader.** Charakter-Materialien sind nicht exportiert (`work/materials` enthält keine `Characters__…`), die Figur ist deshalb weißlich-grau ohne Texturfarben und ohne Licht; erzeugte Shader für Charaktervarianten sind nicht erzeugt. Nächster Schritt: `material_export.py` für `Characters/persons/field/fc0001_00` und Varianten dafür erzeugen.
2. **Nach einem Besuch von Zone 54 sind andere Zonen ≈ 19 % dunkler** (Zone 422 danach (82, 101, 59) statt (101, 125, 72), Zone 367 (86, 105, 57) statt (99, 122, 65)). Zone 54 und 422 teilen `FieldRenderSettings`. Ausgeschlossen: Sonnenwerte, die 36 Spiel-Globals (Ausgabe vor/nach identisch), Schatten an/aus, Stunde, Besuch von 367 oder 425. Reproduzierbar: 54 → 422. Ursache offen (Verdacht: Zustand außerhalb der Globals, z. B. Zonen mit `ReflectionCamera`).
3. **Dächer verdecken die Figur.** Am Start von Zone 367 steht die Figur in der Tür des Torgebäudes (`P_C_001_BarrierGate`, Dach bei y = 6), das Dach liegt zwischen Kamera und Figur: Die Figur ist im Bild nicht zu sehen. Ob das Original Dächer ausblendet, ist nicht untersucht.
4. **Kein Himmel, kein Hintergrund außer der Farbe**; Wolkenschatten und Wasser/Reflexion (`ReflectionCameraDriver`, `DepthCaptureDriver`) sind im Feld nicht angeschlossen; Szenenwerte des `EnvironmentController`, Nachbearbeitung (Bloom, Tiefenschärfe) fehlen weiter (`docs/shader-globals.md`, Abschnitt 10).
5. **Kein Vergleichsbild.** Der Ordner `Ryujinx/` enthält Konfiguration, Logs, Speicherstände und Shader-Caches, keine Bildschirmfotos; ein Pixelvergleich mit dem Original ist daher nicht möglich. Die Bewertung ist sachlich und aus Kenntnis des Spiels, nicht gemessen.
6. Die Gier 180 im Freien ist aus dem Bild und den Locator-Daten abgeleitet (Haustür/Blick), nicht aus dem Original-Code; ein Kamerafall mit Systemflag `0x305` ist ungeklärt.
7. Messung nur im Editor (Spielfenster, Gamma-RT-Bild 1280 × 720); Player-Zahlen und iPad stehen aus.

## 4a. Nachtrag (Teil 4, `docs/sichtpruefung-2.md`)

Zu den offenen Fehlern oben: (1) Figur und NPC tragen mit dem Materialumbau des Modellbundles jetzt erzeugte Shader (farbig; Aufruf im Feldcode steht noch aus). (2) **Ursache der 19 % Helligkeitsfehler gefunden und behoben:** `_ShadowMapTexture` blieb nach einer Zone mit Schattenkarte als freigegebener Verweis stehen (Schwarz = alles im Schatten); `ShadowMapGuard`. (4) Himmel: das Original hat kein Skybox-Material, die Kamera löscht mit Schwarz (Alpha 0), der Himmel ist eine Kugel mit `Delphis/Map/Sky`; Nachbearbeitung Bloom/Nebel/FXAA nachgebaut (`PostChain`), Tiefenschärfe und Farbkorrektur offen. Die Schatten in Zone 422 fehlten, weil die Schattenentfernung im Original aus der Szene kommt (45, Nahebene 15), nicht aus den Qualitätseinstellungen (20).

## 5. Reproduktion

```
# Editor: Szene FieldTest2 öffnen (ohne Spielmodus), dann per `unity command … eval`:
#   Xnu.Field.Editor.FieldShot.Prepare(12f);   // XNU_GAMEDATA=<Repo>/work, XNU_GENERATED_SHADERS=1, XNU_ENV_HOUR=12
# editor_play, ca. 20 s warten (Zone 422), dann:
#   Xnu.Field.Editor.FieldShot.Status();       // Zonenzustand als Text
#   Xnu.Field.Editor.FieldShot.Capture("…/work/visual/z422.png", 1280, 720);   // Bildmittel, PNG
# Zonenwechsel: var f = FieldShot.Find(); f.StartCoroutine(f.SwitchZone(367));
# vor run_tests immer editor_stop
```
Geänderte Dateien: `Field/Runtime/{FieldController,FieldAreaStreamer,PlayerAvatar,FallbackMaterials,RemappedMaterials}.cs`, `Field/Logic/BlockStreaming.cs`; neu `Field/Editor/FieldShot.cs`, `Tests/EditMode/FieldStreamerContainerTests.cs`.
