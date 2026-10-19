# Erste Feld-Szene (Todo `ap-field`, Scheibe 1)

Stand: 2026-10-19. Code: `unity/Assets/Scripts/Field` (Assemblies `Xnu.Field`, `Xnu.Field.Editor`), Tests: `unity/Assets/Tests/EditMode/FieldTests.cs`
(53 Tests, synthetische Daten), Szene: `unity/Assets/Scenes/FieldTest.unity` (nur Kamera, `DisplayController`, `GameInput`, `FieldController`; keine Spieldaten).
Alle Zahlen stammen aus dem Haupt-Editor 6000.3.26f1 (macOS, Metal, M1 Pro) mit dem lokalen Dump. Die Karten werden zur Laufzeit aus den Original-Bundles
gebaut, nichts davon liegt im Repo. Belege (Bildschirmfotos, Ghidra-Ausgaben) liegen nur unter `work/field/` und `work/decomp/field/`.

## 1. Ergebnis in Kürze
- Zone laden, Karte aus Bundle bauen, Spieler per Eingabe-Schicht (`Xnu.Input`) über das Attributraster bewegen: **läuft** für die Feldkarte
  (Zone 422, Twinleaf-Start) und einen Innenraum (Zone 425), mit echten Attributdaten, 30-Hz-Logik und Kamera nach den Stammdaten.
- **Kein Material und kein Shader des Dumps wird gerendert.** Das Shader-Bundle wird nicht geladen, jedes Material der Karte wird beim Bau durch ein
  eigenes Unlit-Material ersetzt; nach jedem Bau zählt `CountForeignMaterials` die Renderer mit fremdem Shader (gemessen: immer 0).
- Der Aufbau der Attributwerte (Code × 1000 + Stop; Zweitmatrix mit Höhenschwelle), das Koordinatensystem (X gespiegelt) und die Kollisionsregeln
  wurden aus der dekompilierten Spiellogik (Ghidra, `work/decomp/field/`) abgeleitet und gegen die Daten geprüft (Startzelle begehbar, Teich als Wasser,
  Treppe = Warp).
- Speicher: Karte nur für die Zone plus Nachbarblöcke bauen und das Bundle danach entladen spart ca. 85 % der Texturen gegenüber dem ganzen Prefab (Abschnitt 9).
- Lücken siehe Abschnitt 11; die wichtigsten: Bewegung ist ein Zellenschritt statt der freien Kreiskollision des Originals, Material-Texturen werden im Player
  noch nicht gelesen (nur Editor), keine Zonenwechsel (Warps), kein NPC/Objekt-Kollision.

## 2. Zonenwahl
Zone **422** (`フタバタウン`, Twinleaf Town). Begründung: erste Zone der Handlung, kleines Dorf (2 Rasterblöcke), enthält Gras, Teich, Häuser, Zäune und Bäume, der Innenraum 425 liegt direkt daneben:
- Ausgangsort der Handlung (Zonen 422–426 in `docs/masterdata.md` Abschnitt 16), Startpunkt im Locator 0 der Zone: Zelle (116, 886).
- Feldkarte im Bundle `Environments/fields/area001` (23,4 MB Datei, 1 Prefab): zeigt Außenbereich mit Gras, Bäumen, Häusern, Teich – der typische Feldaufbau.
- Dieselbe Karte trägt auch die Route 201 (Zone 354) und den See (346); der Blockfilter (Abschnitt 4) baut nur die Zone und ihre Nachbarn.
- Zusätzlich **425** (Spielerhaus 1. Stock, Bundle `prefab_map/t01r0201`, 2,8 MB, 94 Knoten) als kleiner Innenraum-Test mit Tür, Möbeln und Treppe.
Die Zone wird im Inspector (`FieldController.zoneId`) gewählt; `SwitchZone(id)` wechselt zur Laufzeit. Weitere geprüfte Zonen: 54 (`ハクタイシティ`, area003) und 367 (Route 209, area005) für die Speichermessung.

## 3. Aufbau des Codes
| Datei | Aufgabe |
|---|---|
| `Logic/FieldCoords` | Raster ↔ Welt (Abschnitt 5) |
| `Logic/AttributeCell`, `ExAttribute` | Zellwert zerlegen; Höhenentscheid der Zweitmatrix |
| `Logic/AttributeLayer` | Attributraster aus `AttributeMatrix` + `AttributeBlock` (32 × 32 je Block) |
| `Logic/AttributeCodeTable` | `MapAttributeTable` (Entry/Water/Encount je Code), Namen der Codes |
| `Logic/FieldCollision` | Betretbarkeit einer Zelle (Höhe, Fahrrad, Schwimmen) nach `FieldPlayerEntity.CanEntryAttribute` |
| `Logic/GridMover` | Rasterbewegung mit festem Zeitschritt, Geschwindigkeit in Zellen/s, Bodenhöhe über `IGroundHeight` |
| `Logic/MoveDir` | Richtungen (oben = +Z, rechts = +X) und Vier-Wege-Begrenzung der Eingabe |
| `Logic/FieldCameraMath` | Kamerapose aus Neigung, Abstand, Brennpunkt |
| `Runtime/FieldDataSet` | liest die Stammdaten-JSON (`XNU_MASTERDATA` oder `<GameData>/masterdata`), baut Zonen-, Raster- und Attributobjekte |
| `Runtime/FallbackMaterials` | Material-Ersatz, `OriginalMaterialInfo` (Editor) liest Haupttextur/Farbe/Queue aus den serialisierten Daten |
| `Runtime/FieldMapBuilder` | baut aus dem Prefab-Asset (ohne Instanziieren) eine eigene Hierarchie mit Mesh, Collidern, Ersatzmaterialien |
| `Runtime/FieldController` | Ablauf: Boot → Stammdaten → Bundle → Karte → Spieler/Kamera → 30-Hz-Schleife; Messprotokoll (`FieldMemoryLog`) |
| `Resources/XnuFieldFallbackUnlit.shader` | eigener Unlit-Shader (Haupttextur, Farbe, optionaler Alpha-Test) |
| `Editor/FieldSceneBuilder` | Menü `Xnu/Field/Create FieldTest Scene` |
Änderung außerhalb: `BundleProvider.DependencyFilter` (optional, Standard aus): Abhängigkeiten, für die der Filter `false` liefert, werden weder geladen noch gezählt.
Der Feldcode filtert damit alle Bundles mit `.shader`-Assets (Abschnitt 8).

## 4. Aufbau der Karten (Befunde aus den Bundles)
- Jedes Kartenbundle hat **ein Prefab** (Feld: `assets/bg/fields/areaNNN.prefab`, Innenraum: `assets/prefab_field/prefab_map/<karte>.prefab`). Meshes, Texturen und
  Materialien liegen im selben Bundle; die einzige Abhängigkeit ist das Shader-Bundle `Dpr/shaders` (Katalog: `allDependencies = [shaders]`).
- **Feldkarte `area001`:** 6697 Transforms, 6257 MeshFilter/-Renderer, 111 Meshes (258 574 Vertices), 124 Materialien, 1805 BoxCollider, 16 SphereCollider, 11 MeshCollider,
  38 Komponenten ohne Skript. Hierarchie: `Area001` → `Offset` → **Blockcontainer** (`T01` Twinleaf, `R201`, `T02`, `R202`, `C01`, `R203`, `L01` …). Jeder Container
  liegt bei `(-32 · Spalte, 0, 32 · Zeile)` des Zonenrasters (T01 bei (−96, 0, 864) = Raster (3, 27)) und enthält Boden (`P_T_001_Ground_01`), Architektur,
  Zäune, Bäume, Blumen, Gras-Objekte, Schilder. Zonen-ID → Blöcke kommt aus `ZoneTable` (Zone 422 = Zellen (3, 27) und (3, 28)).
- **Innenraum `t01r0201`:** 94 Knoten, 85 Renderer, 21 BoxCollider; Wände und Möbel auf Layer 9, Boden auf Layer 10, Schattenflächen (`RootShadow`) als einfache Quads.
  Der Raum liegt mit der Ecke bei (0, 0, 0) und erstreckt sich nach −X / +Z (also Raster (0..12, 3..12)).
- Layer: 9 = Wand-/Objektkollision, 10 = Boden (141 Collider im Feld, in jedem Innenraum der Boden), 12 = selten (10). Die Bedeutung ist aus der Verwendung erschlossen.
- Der Bau filtert die Blockcontainer: Zone plus `blockRadius` (Standard 1) Nachbarblöcke. Für Zone 422 sind das 1348 von 6697 Knoten (1284 Renderer, 34 verschiedene Meshes,
  42 171 Vertices, 216 Collider, 34 Ersatzmaterialien).

## 5. Koordinatensystem
Aus `FieldObjectEntity.get_gridPosition`/`set_gridPosition` (Dekompilat): `gx = (int)(0.5 − x)`, `gy = (int)(z + 0.5)`, rückwärts `x = −gx`, `z = gy`.
- Eine Zelle ist **1 Weltenheit**; Zellmitten liegen auf ganzen Koordinaten. Y ist die Höhe.
- **X ist gespiegelt:** größeres `gx` heißt weiter links auf dem Bildschirm. Die Kamera schaut mit Gier 0 nach +Z; oben = +Z = `gy + 1`, rechts = +X = `gx − 1`.
- Attributblöcke und Zonenraster sind 32 × 32 Zellen: Block = (`gx >> 5`, `gy >> 5`), Zelle im Block = (`gx & 31`, `gy & 31`); Zonenraster-Index = `Breite · (gy >> 5) + (gx >> 5)`
  (`GameManager.GetGridZoneID`). Locators und Warp-Positionen sind Rasterzellen (der Warp aus Zone 425 zur Zone 426 liegt bei (10, 3) – genau auf der Zelle mit Code 95).
- Bestätigt an den Daten: Locator 0 von Zone 422 = (116, 886) liegt im Block (3, 27) und die Container von Twinleaf liegen bei Welt-X −96…−133.

## 6. Attribute (Kollision, Begehbarkeit)
**Zellwert** (`GameManager.GetAttribute`): `roh < 1000` → nur *Stop* (Code 0); sonst Code = `roh / 1000`, Stop = `roh % 1000`.
- **Stop 128 sperrt** die Zelle (Wand, Tresen, Möbel). In allen Hauptmatrizen kommen nur Stop 0 (947 807 Zellen) und 128 (526 272 Zellen) vor, dazu 8 Zellen mit anderen Werten (8, 12, 100).
- **Code** verweist auf `MapAttributeTable` (Zeile = Code, 256 Zeilen): `Entry` (betretbar; 136 Codes ja, 120 nein), `Water` (18 Codes), `Encount` (24 Codes, Gras/Wasser),
  `Attribute` (Unterart, oft 255).
- Beispiele (aus dem Dump-Enum und der Daten): 0 Boden, 2/4–7/9/10 Gras (`IsGrass`), 3 Langgras, 16 Teich, 21 Meer, 22/23 Flachwasser/Sumpf (nicht `Water`), 94/95 Treppe
  rechts/links, 101 Türmatte unten, 105 Tür, 128 Tresen, 113–125 Brücken, 215/216 Absprungkante (`Entry` = 0, damit zu Fuß ohnehin gesperrt).
- **Zweitmatrix** (`AttributeEx`, Blocknamen auf `_Ex`; 1439 Blöcke): `roh = H · 1 000 000 + oben · 1000 + unten`. Ist `H ≤ (int)(Höhe + 100,5)` (Höhe 0 entspricht H = 100), gilt der mittlere Teil
  (Spieler steht auf der Brücke), sonst der untere (`HeightAttribute`/`IsHighAttribute`). Wird nur für Brückencodes ausgewertet.
- Außerhalb der Matrix oder ohne Block liefert das Original Code 0 / Stop 0 (begehbar). `FieldCollision.OutsideBlocked` (Standard an) sperrt diese Zellen – bewusste Abweichung.

**Betretbarkeit** (`FieldPlayerEntity.CanEntryAttribute`, Parameter Höhe, Zelle, Fahrrad, Schwimmen):
1. Stop = 128, kein Tabelleneintrag oder `Entry` = 0 → nein.
2. Brückencode (113–125): Spieler **unter** der Brücke und Wasserzelle und schwimmend → ja; **oben**: Wasserzelle und nicht schwimmend → ja; sonst, zu Fuß auf Land: senkrechte (118–121)
   oder waagerechte (122–125) Brücke → nein.
3. Fahrrad: `Attribute` ∈ {3, 0xA1–0xA8} (Langgras, Schnee, Sumpf) → nein; zu Fuß: `Attribute` ∈ {215, 216} → nein.
4. Ergebnis: Schwimmer nur auf Wasser, Läufer nur auf Land (`schwimmen == Water`).
Die Namen der Brückencodes folgen den dekompilierten `AttributeID.MATR_IsBridge*`; die Brückenzweige sind mit synthetischen Daten getestet, aber noch nicht an einer echten Brücke.

**Treppen und Höhen:** Innen-Treppen sind keine Höhen, sondern Zellen mit Code 94/95 (`MATR_IsRightStairs`/`IsLeftStairs`), auf denen ein Warp in den anderen Stock liegt
(`MapWarp_T01R0201`: Position (10, 3) → Zone 426). Die Zellen der Treppe selbst sind Stop 128. Die Höhe des Spielers kommt im Original aus Bodenstrahlen
(`CollisionUtility.CollideGround`); hier `IGroundHeight` (Szene: Raycast nach unten gegen Layer 10). Im Feld ergibt das Höhe 1,0 am Startpunkt, im Haus 0,0; Rampen-Collider werden nur
in der Nähe der Spielerhöhe getroffen (siehe Lücken).

## 7. Bewegung, Eingabe, Kamera
- **Eingabe:** `GameInput.Move` (Stick/D-Pad/WASD nach Totzone) → `FieldInputMath.LimitToFourWay` = `FieldPlayerEntity.LimitedCrossInput` (größere Achse gewinnt, bei Gleichstand die
  horizontale). `B` gedrückt = Laufen. Die Kamera/„oben“ ist +Z.
- **Geschwindigkeit** (`FieldPlayerEntity.GetMoveSpeed`, `FieldCommonParam`): zu Fuß 3,7, laufen 7,14 Zellen/s; Fahrrad 9,76/13,11 (Index 2/3, mit Beschleunigungswerten 0,3/0,15); Schnee/Sumpf/Langgras
  verlangsamen mit Faktoren aus Index 132–136 (0,75, 0,5, 0,25, 0,5, 0,5). Umgesetzt sind nur Gehen und Laufen.
- **Logik 30 Hz:** `FieldController` sammelt `Time.unscaledDeltaTime` und ruft feste 1/30-s-Schritte; `DisplayController` mit `Original30` setzt VSync-Zähler/Zielrate. Ein Zeitschritt kann mehrere
  Zellen weiterlaufen (Test: 1 s = 3 Zellen), die Schleife ist begrenzt.
- **Kollision im Original ist nicht zellweise:** `FieldGridCollision.CheckGriCollisionMoveEntity` bewegt einen Kreis (`entityRadius`) frei gegen die Zellkanten, mit Gleiten an Wänden
  und Typen None/NoEntry/Water/Npc. `GridMover` ist die **vereinfachte Zellenfassung** für diese Scheibe (ein Schritt = eine Zelle, Richtungswechsel nur an Zellgrenzen, Wand = nur drehen).
- **Kamera** (`FieldCamera.CameraUpdate`): Euler = (Neigung, 0 bzw. 180 bei Systemflag 0x305, 0) + Versatzwinkel, Sichtfeld = `Fov` + `fovOffset`, Brennpunkt = Ziel + Versatz + (0; 0,5; 0),
  Position = Brennpunkt − Blickrichtung · `TargetRange`. Die Werte kommen aus `MapInfo.Camera`: **eine Zeile je Zone** (658 Zeilen, Index = Zonen-ID; `ariaID` ist das Gebiet und wiederholt sich).
  Zone 422: Neigung 45°, Sichtfeld 17,5°, Abstand 30; Zone 425: 45°, 20°, 30; Route 201 (354): 35°, 15°, 30. Das Nachführen des Brennpunkts (`_cameraLerpRate`) ist im Original nicht ermittelt (Annahme 12 /s).
  Tiefenschärfe (`defocusStart/End`) und Wackeln sind nicht umgesetzt.

## 8. Rendering-Regel und Material-Ersatz
- **Shader-Bundle nie laden:** `BundleProvider.DependencyFilter` lässt `Dpr/shaders` (und jedes Bundle mit `.shader`/`.shadervariants`) aus. Materialien der Karte zeigen dann den Fehlershader, werden aber nie
  gezeichnet: `FieldMapBuilder` instanziiert das Prefab **nicht**, sondern liest nur Transform/Mesh/Collider aus dem Asset und weist eigene Ersatzmaterialien zu.
- **Befund (Absturz):** Mit geladenem Shader-Bundle brachte schon das Lesen der Material-/Shader-Eigenschaften (`Material.GetTexturePropertyNames`, `Shader.GetPropertyCount`) den Editor zum Absturz (SIGSEGV, zweimal beim
  Sondieren). `m.name`, `m.shader.name` waren unkritisch. Ohne geladenen Shader funktionieren Prefab- und Materialzugriff über `SerializedObject` (Editor) stabil.
  Deshalb liest `OriginalMaterialInfo` die Haupttextur (`_MainTex`), Skalierung/Versatz, `_Color` und `m_CustomRenderQueue` direkt aus `m_SavedProperties`. **Das gibt es nur im Editor**; im Player bleibt das Ersatzmaterial
  grau, bis ein eigener Materiallesepfad (Exporter oder Parser der Serialisierung) existiert.
- Ersatz-Shader `Xnu/FieldFallbackUnlit`: Haupttextur × Farbe, kein Licht, kein Nachbau des Originallooks (Alpha-Test mit 0,5 nur bei Queue ≥ 2450 und Textur mit Alphakanal). Bildschirmfotos
  (`work/field/shots/field1–4.png`) zeigen die Karte damit; Gamma-Farbraum und Built-in-Pipeline wie in `docs/render-treue.md`.
- Sicherung: nach jedem Bau muss `CountForeignMaterials` = 0 sein, sonst bricht das Laden ab.

## 9. Speicher (Streamen, Entladen, Spitze)
Messprotokoll: `FieldMemoryLog` je Ladestufe (Unity-Zähler, Grafiktreiber, Texturen, Prozess-Arbeitsspeicher). Der Editor selbst belegt ca. 300 MB (Unity) und 750–950 MB (Prozess); aussagekräftig sind die Differenzen.
Ablauf: `Acquire` (Bundle öffnen, ohne Shader) → Prefab laden (alle Texturen/Meshes des Prefabs) → nur die Zone plus Nachbarblöcke klonen → `Release` (Bundle entladen, `Unload(false)`) → `Resources.UnloadUnusedAssets`.

| Zone (Bundle, Datei) | Texturen vorher | nach Prefab-Laden (Spitze) | nach Entladen | Grafiktreiber vorher → Spitze | Ersatzmaterialien |
|---|---|---|---|---|---|
| 422 (`fields/area001`, 23,4 MB) | 30 MB | 76 MB (+46) | 33 MB (+3) | 139 → 197 MB | 34 |
| 54 (`fields/area003`, 33,2 MB) | 30 MB | 82 MB (+52) | 43 MB (+13) | 152 → 218 MB | 112 |
| 367 (`fields/area005`, 34,5 MB) | 30 MB | 89 MB (+59) | 38 MB (+8) | 166 → 242 MB | 73 |
| 425 (`prefab_map/t01r0201`, 2,8 MB) | 30 MB | 36 MB (+6) | 33 MB (+3) | 134 → 141 MB | 39 |

- Zeiten: Katalog 0,5 s, Stammdaten-JSON 1,0–1,1 s (die 20 MB `AttributeBlock.json` treiben den Prozess kurz um 150–170 MB hoch), Bundle öffnen 10 ms, Prefab laden 0,26–0,30 s (Feld), Bau 20–40 ms, Entladen/Aufräumen ca. 0,4 s.
  Ein Zonenwechsel (`SwitchZone`, Katalog und Stammdaten bleiben) dauert 0,3–0,4 s ohne Aufräumen.
- **Spitze** = Prefab-Laden: Das Prefab lädt alle Texturen des ganzen Gebiets (bis +59 MB Texturen, +76 MB Grafiktreiber). Nach Bau und Entladen bleiben nur +3 bis +13 MB Texturen; das Entladen gibt ca. 85 % wieder frei.
  Prozess-Spitze im Editor: 1,0–1,14 GB (davon ca. 0,75–0,95 GB Editor-Grundlast).
- Das sind Editor-Werte (Texturen teils dekomprimiert, Mac-Grafikspeicher); iPad/Switch-Werte sind nicht gemessen (`docs/ios-speicher-entitlements.md` nennt das Budget).
- Streaming im Spiel (Blöcke beim Laufen nachladen/entladen) gibt es noch nicht: gefiltert wird nur beim Laden. Eine saubere Lösung braucht die Bundle-Zerlegung je Block oder das Laden des
  Prefabs je Gebietswechsel.

## 10. Tests und Reproduktion
- `FieldTests.cs`: Koordinaten (Spiegelung, Zellgrenzen, Blöcke), Zellwert-Zerlegung, Höhenentscheid, Layer (Lücken, falsche Blockbreite), Regeln (Wand, Wasser, Absprungkante, Fahrrad, Brücken oben/unten,
  Außenbereich), Eingabe (Gleichstand horizontal), Kamera (Pose, Gier, Folgen), `GridMover` (Schrittdauer, Verkettung, Laufen, Wand, Wasser/Schwimmen, Richtungswechsel, großer Zeitschritt, Treppenhöhe, Brückenhöhe,
  Teleport), Stammdaten (Zonenblöcke, Kollision, Kamera je Zone) und Bundle-Filter (Attrappen-Quelle). Gesamtlauf `Xnu.Tests.EditMode`: grün (375 Tests, davon 53 Feld).
- Echte Daten: `XNU_GAMEDATA=<Repo>/work` setzen, Szene `FieldTest` öffnen und Play drücken (Eingabe nur mit fokussiertem Game-View; `simulate_key` wirkt wegen
  `backgroundBehavior` ohne Fokus nicht). Ohne Fokus lässt sich `FieldController.TickLogic(dt, richtung, laufen)` direkt aufrufen. Probelauf: Start (116, 886), nach unten gesperrt (Stop),
  nach rechts 11 Zellen in 3 s, an der Teichkante `Water`, Höhe 1,00.
- Szene neu erzeugen: Menü `Xnu/Field/Create FieldTest Scene` oder `Xnu.Field.Editor.FieldSceneBuilder.CreateScene()`.

## 11. Lücken und nächste Schritte
1. **Freie Bewegung mit Kreiskollision** (`CheckGriCollisionMoveEntity`, `entityRadius`, Seiten-/Vertikalrichtungen, Gleiten) statt Zellenschritt; die Dekompilate liegen in `work/decomp/field/b/Dpr_FieldGridCollision.c`.
2. **Zonenwechsel/Warps:** `MapWarp` je Karte (Position in Rasterzellen, `WarpZone`, Eingangsrichtung) modellieren und mit `SwitchZone` verbinden; damit funktionieren Türen und Treppen (Code 94/95/101/105).
3. **Höhen/Rampen:** Bodenhöhe per Strahl nur nahe der Spielerhöhe; Treppen im Freien (`P_OutStair`) und Klettern/Absprünge (Codes 56–59, 215/216, 75/76) fehlen. Einheitliche Bodenebene für Layer 10 prüfen.
4. **Material-Daten im Player:** Haupttextur/Farbe sind nur im Editor lesbar. Nötig: Exporter der Material-Eigenschaften oder ein eigener Leser der Serialisierung; später der Shader-Port (`docs/shader-translator.md`).
5. **Streaming nach Blöcken**, Wasser-/Gras-Effekte, Licht/Schatten, Nebel, Wetter, Tag/Nacht (`RenderSettings`-Objekt der Zone), Hintergrundmusik bleibt aus.
6. NPCs, Objekte (`PlaceData`), Trainer, Begegnungen (Code → `FieldEncountTable`), Fahrrad/Schwimmen als Zustände (Parameter sind da), Schnee-/Sumpfgeschwindigkeit.
7. Kamera: Nachführrate, Wackeln, Event-Kamera, Pan-Kamera (`RoomPanCamera`), Tiefenschärfe; Gier-Flag 0x305.
8. Brückencodes an echten Daten verifizieren; `AttributeID.MATR_*` vollständig als Enum ablegen (Zelle → Bedeutung, Debug-Anzeige).
9. Messung auf iPad (Speicher, 30 Hz) und mit freigegebenem Shader-Port.
