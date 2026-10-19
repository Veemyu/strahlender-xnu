# Feld-Szene, Scheibe 2: Zonenwechsel, Streaming, Spielerfigur, NPCs (Todo `ap-field`)

Stand: 2026-10-19. Code: `unity/Assets/Scripts/Field` (Assemblies `Xnu.Field`, `Xnu.Field.Editor`, neu `Xnu.Render.Editor`), Tests: `unity/Assets/Tests/EditMode/FieldWorldTests.cs`
(58 neue Tests, synthetische Daten), Szene `unity/Assets/Scenes/FieldTest2.unity` (nur Kamera, `DisplayController`, `GameInput`, `FieldController`).
Alle Zahlen: Unity 6000.3.26f1, macOS (M1 Pro), lokaler Dump. **Die Prüfläufe mit echten Daten liefen im Batchmodus (`-nographics`, ohne Spielmodus und ohne Bild)**, siehe Kapitel 9;
Speicherwerte sind dort Editor-Werte ohne Grafiktreiber. Keine Spieldaten, Bilder oder erzeugten Shader im Repo (Belege unter `work/field2/`). Kein Ton: nichts wird abgespielt.
Markierung: **belegt** = an den Daten oder im Dekompilat geprüft, *Annahme* = begründet, aber nicht belegt.

## 1. Ergebnis in Kürze

| Punkt | Stand |
|---|---|
| Warps | **1.931 Warps** gelesen: 1.899 einer Zone zugeordnet, 18 ohne Ziel (`WarpZone = -1`), 14 ungelöst (Karten `D10R0102`, `C10R0116`, `Safari`); Ziel-Locator bei allen 1.899 gültig. Außentüren: **245** abgeleitet. |
| Zonenwechsel | Warp-Rechteck (Treppen, Raumausgang, Höhlen), Außentür (Hineinlaufen in die gesperrte Türzelle), Zonengrenze im Zonenraster; Überblendung; Spawn mit Blickrichtung. Mit echten Daten durchgespielt: Tür 422 → 425 (49 ms), Raumausgang 425 → 422 (268 ms), Gebietswechsel 422 → 54 (257 ms). |
| Streaming | Block-Streaming der Feldkarte (Blöcke 32 × 32 Zellen), Ladeabstand aus der Kamera (19 Zellen in Zone 422), Hysterese, Speicherbudget 2,5 GB als Regelkreis. Zone 422: höchstens **2 Blöcke** gleichzeitig. |
| Spielerfigur | Modell `fc0001_00` aus dem Bundle, 3 von 3 Clips (Stehen, Gehen, Laufen) über `PlayableGraph`; Material: Ersatzmaterial. Fahrrad nicht umgesetzt. |
| NPCs/Objekte | 4.197 Platzierungen (`PlaceData`) als Daten; sichtbare NPCs als Marker; Ansprechen/Berühren als Ereignis über `IFieldInteractionHandler` (nicht von EvScript abhängig). |
| Kollision | Absprungkanten (4 Richtungen, Dekompilat), NPC-Sperre; Wasser, Brücken, Höhenstufen unverändert aus Scheibe 1 (Abschnitt 8). |
| Material-Umbau | Im Haupt-Editor: 61 von 61 erzeugten Shadern gefunden, Umbau lief ohne Absturz, **aber Bild schwarz; ein zweiter Lauf mit Licht blockierte den Editor** → Standard **aus** (Kapitel 6). |
| Tests | Gesamtlauf `Xnu.Tests.EditMode` im Batchmodus: **624 von 624 grün** (vorher 481 laut Auftrag, andere Agenten haben Tests ergänzt; 58 davon neu aus dieser Scheibe). |

## 2. Zonenwechsel

### 2.1 Datenbefunde (belegt, Stammdaten)
- **Locator** (`MapInfo.ZoneData[z].Locators[i]`): `x`, `y` = Rasterzelle, **`z` = Blickrichtung in Vierteln (0 oben, 1 rechts, 2 unten, 3 links)**. Prüfung: Für 569 Raum-Locators mit `z` 1 oder 3 ist die Zelle in Blickrichtung bei 562 frei und nur bei 7 gesperrt
  (die gespiegelte Deutung ergab 484 gesperrt). Beispiele: Zone 425 Locator 0 (6, 10, 2) steht in der Tür und schaut in den Raum; Zone 422 Locator 0 (116, 886, 0) steht vor der Haustür (Tür bei (116, 885)) und schaut von ihr weg.
  Die Folie aus Scheibe 1 („`z` nicht ausgewertet“) ist damit überholt. Locators mit (0, 0) sind unbelegt.
- **MapWarp** (`MapWarp_<Name>`): Position (x = `gx`, z = `gy`), Größe in Zellen, `WarpZone`, **`WarpIndex` = Index des Locators in der Zielzone**, `InputDir` (0 oben, 1 rechts, 2 unten, 3 links; Treppe links 94 → 3, Treppe rechts 95 → 1, Türmatte unten 101 → 2, oben 110 → 0 laut Häufigkeiten über alle Warps).
  Der **Instanzname ist der Name im Spiel-Enum `ZoneID`** (`T01R0201` = 425; Kartenbundles sind teils geteilt, deshalb genügt der Bundle-Name nicht: 211 von 552 Namen passen nicht zum Bundle der Zone). Feldgebiete heißen `A01`…`A14`, `Safari`; ihre Warps liegen in absoluten Zellen.
  Der Enum steht nur im Dump: `scripts/field_zone_names.py` schreibt `work/masterdata/field/ZoneNames.json` (659 Namen). Ohne die Datei sucht `WarpTable` nach dem Bundle-Namen (eindeutige Treffer) und lässt den Rest ungelöst (Test).
- **Außentüren stehen nicht in `MapWarp`.** Die Haustüren von Zwieblüh sind Zellen mit Attribut **105 und Stop 128** ((116, 885), (105, 875), (106, 885), (116, 875)); das Skript spricht sie über den Objektnamen `T01R0201_D01` an. Ableitung: Der Raumausgang trägt `ConnectionName = T01R0201_D01`
  und führt auf einen Feld-Locator; die Tür liegt **eine Zelle hinter dem Locator** (Gegenrichtung des Blicks), der Spieler läuft in Gegenrichtung des Locator-Blicks hinein. Für Zwieblüh ergibt das genau die vier Türzellen mit Code 105. Eintritts-Locator im Raum = der Raum-Locator, dessen Zelle im Ausgangsrechteck liegt.

### 2.2 Logik (`Xnu.Field/Logic`, ohne Unity)
| Datei | Aufgabe |
|---|---|
| `Facing` | Viertel/Grad ↔ `MoveDir`; Gegenrichtung |
| `WarpTable` | alle Warps je Zone, Auflösung der Zone (Enum-Name → Bundle-Name → Zonenraster der Warp-Zelle), Außentüren (`DoorLink`) |
| `FieldZoneRouter` | `OnArrived` (Warp-Rechteck, Türzelle ohne Sperre), `OnBump` (Außentür nur beim Hineinlaufen), `OnZoneGridChange` (Rand-Übergang), `TryResolveSpawn`, `SameMap` |
| `ScreenFade` | Aus → schwarz halten (Laden) → Ein; Dauern 0,25 s je Richtung (*Annahme*, Originalwerte nicht ermittelt) |
| `ZoneNames` | liest `ZoneNames.json` |

Regeln: Warp-Zelle = Zelle, deren Mitte in `[Mitte − Größe/2, Mitte + Größe/2)` liegt (Größen unter 1 zählen als 1; z. B. Position (5,75; 10), Größe (1,5; 1) deckt (5, 10) und (6, 10)). Ein Warp löst bei **Schrittende** aus; der Spawn nach einem Wechsel ist ein Teleport
und löst nichts aus (Spawn auf der Ausgangstür des Raumes). `InputDir` wird **nicht** als Auslöserbedingung geprüft (Treppen werden von der Nachbarzelle betreten, ihre `InputDir` folgt dem Treppentyp, nicht der Laufrichtung) – *Annahme*.
Ein Wechsel braucht eine neue Karte (`NeedsMapLoad`), wenn das Bundle der Zielzone anders ist; Zonen desselben Gebiets (Zwieblüh 422 ↔ Route 201 354 in `area001`) wechseln ohne Laden und ohne Überblendung.

### 2.3 Ablauf (`FieldController.RunTransition`)
1. Eingabe stoppt (`InTransition`), `ScreenFade` blendet aus.
2. Bei neuem Bundle: Karte abbauen (Blöcke, NPC-Marker, Materialien, Bundle `Release`), `Resources.UnloadUnusedAssets`, Zone setzen, `Load()` (Prefab laden, Gerüst bauen, Spawn-Blöcke streamen, Mover und Spieler platzieren). Sonst: Zonendaten (Kollision, Kamera) tauschen, Mover neu setzen, Blöcke nachziehen.
3. Einblenden; Bericht (Dauer, letzte Speichermessung) in `TransitionReports`.
Der Spieler (Figur, Animation) bleibt über Wechsel erhalten. Karte wird **vor** dem Laden der neuen entladen (keine zwei Gebiete gleichzeitig).

## 3. Außenwelt-Streaming
- **Aufbau:** Das Prefab wird nicht instanziiert; `FieldAreaStreamer` baut das Gerüst (alles außer den Blockcontainern unter `Offset`) und je Block die Container (`-32·Spalte, 0, 32·Zeile`) mit `FieldMapBuilder.CloneBranch`. Blöcke werden gebaut und zerstört; Meshes und Texturen gehören dem geladenen Bundle (bleibt für das Gebiet geladen).
  Zone 422 (`area001`): 12 Blockcontainer in 12 Blöcken. Innenräume haben kein `Offset` und werden als Ganzes gebaut.
- **Reichweite:** Im Spielcode ist die Streaming-Reichweite nicht gefunden (im `FieldManager` steht nur die Konstante `MapSize = 64`, Bedeutung nicht belegt; Ghidra-Suche nach Block-/Sichtbarkeitsklassen ohne Treffer). **Ableitung aus den Kameradaten** (`BlockStreamingMath.VisibleRadius`): Strahlen durch die Bildränder gegen die Bodenebene, aus Neigung, Sichtfeld und Abstand der Zone;
  Zone 422 (45°, 17,5°, 30): vorn 7,7, hinten 5,7, seitlich (16:9, mit 25 % Zuschlag) 10,3 → **sichtbarer Radius ≈ 10,3 Zellen**; Ladeabstand = ⌈Radius⌉ + 8 Zellen Vorlauf = **19**. Route 201 (35°, 15°, 30): 8,8. Entladen erst jenseits von Ladeabstand + 8 (Hysterese).
  Der Abstand ist Chebyshev-Abstand der Spielerzelle zum Blockrechteck. Die Werte 8 (Vorlauf) und 8 (Hysterese) sind *Annahmen*.
- **Speicherbudget** (`MemoryBudget`, Standard 2.500 MB gesamt für das iPad): Unity-Zähler (nativ + Grafiktreiber) werden alle 30 Logikschritte bewertet; ab 75 % schrumpft der Ladeabstand auf 3/4 (mindestens 12), ab 92 % auf 1/2 (mindestens 8). Die Zahlen sind Stellschrauben, nicht gemessen auf dem Gerät.
- **Messung** (Zone 422, Teleport entlang x = 116 von y = 886 bis 770 und zurück): Blöcke gleichzeitig 1 → 2 → 2 → 1 → 0 → 1 → 1, insgesamt 4 Ladevorgänge und 3 Entladevorgänge, **Spitze 2 Blöcke**; Zeit je Blockwechsel 0 bis 16 ms; Unity-Speicher 209 → 213 MB (Schwankung durch Blöcke ≈ 2 MB).
  Das Prefab liegt dabei vollständig im Speicher (Texturen +46 MB gegenüber dem Start, Prefab-Laden 0,22 s); die 85 % Einsparung aus Scheibe 1 (Bundle nach dem Bau entladen) gibt es nur mit `streaming = false`. Auf dem iPad ist das Gebiet in komprimierten Formaten kleiner (nicht gemessen).
- **Nicht gelöst:** Wasserflächen/Himmel/Wetter hängen nicht an Blöcken; Texturen verlassen den Speicher erst mit dem Gebietswechsel (Bundle-Entladung), nicht beim Block-Entladen.

## 4. Spielerfigur und Animation
- `PlayerAvatar`: Bundle `Characters/persons/field/fc0001_00` (Junge; `fc0002_00` = Mädchen; 15 Skinned-Renderer, 56 Clips) holen, Prefab instanziieren, **sofort** alle Materialien durch Ersatzmaterial ersetzen (die Originalmaterialien tragen nur den Fehlershader und werden nie gezeichnet), Clips `idling_f`, `walk_f`, `run_f` in einem `AnimationMixerPlayable` überblenden (0,15 s). Das Bundle enthält keinen Animator-Controller.
  Das Shader-Bundle bleibt gefiltert. Prüfung im Batchmodus: Instanziieren, 15 Renderer, 3/3 Clips, Modellhöhe 5,07 Einheiten → **auf 1,4 Zellen skaliert** (*Annahme*, Originalmaß nicht ermittelt).
- Ersatzmaterial heißt: Haupttextur/Farbe über `SerializedObject` (nur Editor); im Player grau. Ob die Charakter-Shader zu den erzeugten gehören, ist offen (Export der Materialien nur für `Environments/`).
- **Nicht umgesetzt:** Fahrrad, Schwimmen, Angeln und die übrigen 53 Clips; die Bundles `fc0001_10…22` (Varianten mit 3 bis 56 Clips) sind nicht untersucht. Bildkontrolle (Ausrichtung, Skalierung, Animationsausgabe) steht aus, weil der Haupt-Editor nach dem Absturz nicht wieder startbar war (Kapitel 6).

## 5. NPCs, Objekte, Interaktion
- **Daten:** `PlaceData` (484 Instanzen, 4.197 Einträge, 36 mit ungültiger Zone). `PlacementParser` → `PlacementRecord`. Befunde: `Position` ist die Rasterzelle; ältere Raumobjekte tragen die Weltposition (x negativ) → Betrag. Prüfung: 2.858 von 2.955 sichtbaren NPCs stehen auf begehbaren Zellen, 695 von 1.093 Objekten mit positivem x auf gesperrten (Schilder, Möbel).
  `ObjectGraphicIndex ≥ 0` = sichtbarer NPC, `−1` = unsichtbare Fläche (Schild, Fernseher, Auslöser) mit `Size` in Zellen; `Rotation` in Grad (0, 90, 180, 270 wie die Viertel); `TalkLabel`/`ContactLabel` = Skriptlabels.
- **Flags:** `DoNotLoad` ≠ 4000 verbirgt bei gesetztem Flag; `Work` ≠ 4000 macht die Figur nur bei gesetztem Flag sichtbar (*Annahme*: die Rivalen-Mutter steht sonst auf der Türzelle des Spielerhauses und sperrte den Ausgang; im ersten Prüflauf tat sie es). Flags liefert später der Interpreter (`IFieldFlags`); ohne Quelle gilt nichts als gesetzt.
- **Darstellung:** `FieldNpcView`: Kapsel mit Blickmarke (Trainer orange, sonst blau) im Umkreis des Ladeabstands; keine Laufmuster (`MoveCode` nicht ausgewertet), keine Modelle (`CharacterGraphics` nicht gelesen). Sichtbare NPCs sperren ihre Zelle (`GridMover.IsOccupied`).
- **Interaktion** (`Interaction.cs`): `IFieldInteractionHandler { bool Busy; bool Handle(InteractionRequest) }` – der spätere Event-Interpreter implementiert das Interface (`FieldController.InteractionHandler`); bis dahin protokolliert `LoggingInteractionHandler`.
  `InteractionRequest` trägt Art (`Talk`/`Contact`), Zone, Platzierung (Labels, Trainer-ID), Spielerzelle und Blick. A-Taste: Zelle in Blickrichtung (Reichweite 1,25 deckt die Nachbarzelle; Objekte mit `TalkToRange ≥ 2` auch die zweite, z. B. Tresen). Berührung: Betreten einer Fläche mit `ContactLabel`.
  Solange `Busy`, ruht Eingabe und Spieler. `TalkBit` (Bitmaske, meist 15) ist gelesen, aber **nicht ausgewertet** (Bedeutung der Bits nicht belegt).

## 6. Material-Umbau und erzeugte Shader im Projekt
**Einbindung (neu, gitignoriert):** `Xnu/Render/Sync Generated Shaders` (`Xnu.Render.Editor.GeneratedShaderSync`) kopiert die in `variants.json` mit Status `ok` gelisteten `.shader`-Dateien nach `unity/Assets/XnuGenerated/Resources/Shaders` und `variants.json` nach `…/Resources/XnuGeneratedVariants.json`.
Quelle: `XNU_SHADERS` oder `<XNU_GAMEDATA>/shaders/combined` (61 Varianten). `.gitignore` führt `unity/Assets/XnuGenerated/` (und `.meta`). Dateien in `Resources` sind im Build enthalten, `Shader.Find` findet sie im Player (**Player nicht gebaut/geprüft**). `GeneratedShaderLibrary` (Laufzeit) liest die Tabelle aus `Resources` oder dem Ordner.
Der Materialexport (`work/materials/<Bundle mit __>.json`, `scripts/material_export.py`) wird über `XNU_MATERIALS` oder `<GameData>/materials` gefunden; im Player müsste er nach `StreamingAssets/GameData/materials`.

**Ergebnis im Haupt-Editor (belegt):** Import der 61 Shader ohne Fehlermeldung; Zone 422: „Umbau (Shader 61/61, 124 Materialeinträge)“, 433 Renderer mit 443 ersetzten Slots, **0 fremde Materialien**, kein Absturz (`RemappedMaterials`: Name + Keywords lesen, `MaterialRemapper.Remap`, sonst Ersatzmaterial).
- **Bild schwarz:** auch der Himmelhintergrund; Ursache vermutlich fehlendes Licht (Forward ohne Richtungslicht). Zweiter Lauf mit `FieldSun` (Richtungslicht) und `GameGlobals.SetDefaults()` (Platzhalter) in `FieldController.EnsureRenderEnvironment`: **der Haupt-Editor reagierte nicht mehr** (> 8 Minuten, 175 % CPU, Hauptthread in der IMGUI-Zeichnung, Pipeline-Befehle liefen in Zeitüberschreitung);
  Ursache nicht bestimmt (Verdacht: Shaderkompilierung/GPU-Zeit der erzeugten Shader im Spielmodus, nicht nachgewiesen). Ich beendete den Editor (`kill`), danach ließ er sich aus der Shell nicht mehr starten (Lizenz/Anmeldung ohne Hub-Token, Dialog vermutet); Batchmodus (`-batchmode -nographics`) funktioniert. Kein `mono_crash`, keine Datei zu löschen.
- **Folgerung:** `useGeneratedShaders` ist **aus** (Inspector), Umgebungsvariable `XNU_GENERATED_SHADERS=1` schaltet ein. Ohne den Umbau bleibt es beim Ersatzmaterial (Scheibe 1). Offen: Lichtumgebung (Licht, Schatten, Globals mit Spielwerten, Himmel) und Ursache des Hangs; ein Lauf in einem frischen Editor mit Bild (nicht möglich in dieser Sitzung).

## 7. Szenen und Werkzeuge
- `FieldTest2.unity` (Menü `Xnu/Field/Create FieldTest2 Scene`): Streaming, Spielerfigur, NPCs an; Umbau aus. `FieldTest.unity` bleibt wie in Scheibe 1, nutzt aber den neuen `FieldController` (Streaming ist Standard).
- Steuerung: Richtung = Bewegung (Innenräume: Kamera um 180° gedreht, Eingabe entsprechend gedreht – *Annahme* `roomCameraYaw = 180`, belegt nur durch die Lage von Tür/Locator-Blick; nicht im Bild geprüft), B = Laufen, A = Ansprechen.
- `Xnu/Field/Verify (Zonenwechsel, Streaming)` (`FieldVerify`), headless: `Unity -batchmode -nographics -projectpath unity -executeMethod Xnu.Field.Editor.FieldVerify.RunBatch` mit `XNU_GAMEDATA=<Repo>/work`, Bericht nach `XNU_FIELD_REPORT` (Standard `<GameData>/field-verify.txt`).
  Hilfen dafür: `FieldController.CoroutineRunner`, `headlessUnload`, `ForceStream`, `FieldDestroy`.

## 8. Kollision: Wasser, Höhen, Brücken, Sprünge
- Unverändert aus Scheibe 1 (`FieldCollision`): Wasser/Land, Brückencodes 113–125 mit Zweitmatrix, Fahrrad-Sperren, Zellen ohne Block.
- **Absprungkanten (neu, belegt):** `AttributeID.MATR_IsJump*` im Dekompilat: 56 = rechts, 57 = links, 58 = oben, 59 = unten (Richtungen im Viertelsystem; die Zellen haben `Entry = 0` und Stop 128). Läuft der Spieler in Kantenrichtung in die Kante, springt er auf die Zelle dahinter (zwei Zellen, Gehgeschwindigkeit, Bogen 0,6 – *Annahme*); ein gesperrtes/belegtes/falsches Landefeld oder die falsche Seite gilt als Wand.
  Anzahl im Dump: Code 59 550 Zellen, 56 23, 57 41, 58 – (0 gefunden); die Richtungsrichtigkeit der Kantenzuordnung ist am Gelände nur plausibel (Ränder liegen zwischen Zonen), nicht belegt.
- 215/216 (`TakeOff`) bleiben Fahrrad-Absprungstellen (`CanEntryAttributeBycJump` im Dekompilat), 75/76 Kletterfelsen (Entry 0), 89 `WaterNoIn` (Entry 1, Bedeutung nicht ausgewertet).
- Höhen: weiterhin Bodenstrahl gegen Layer 10; NPC-Höhe per Strahl; Treppen im Freien nicht untersucht.

## 9. Prüfläufe und Zahlen (Batchmodus, echte Daten)
`work/field2/verify.txt` (Bericht), `work/field2/results.xml` (624 Tests):
- Laden Zone 422: 1,6 s gesamt (Katalog 0,3 s, Stammdaten 1,0 s mit 1.899 Warps und 4.197 Platzierungen, Bundle 0,02 s, Prefab 0,22 s, Gerüst 5 ms, Block 17 ms, Figur 46 ms).
- Tür (116, 886) → hinein: Zone 425, Spawn (6, 10), Blick unten, 49 ms; Raum verlassen (Zelle (6, 10) betreten): Zone 422, Spawn (116, 886), Blick oben, 268 ms (Karte entladen + neu laden); Gebietswechsel 422 → 54 (`area003`): 257 ms; Wechsel 54 → 425: 54 ms.
- Speicher (Editor, ohne Grafiktreiber; Stufen aus `FieldMemoryLog`): Unity 160 MB (Start) → 199 MB (Prefab area001, Texturen 16 → 62 MB) → 209 MB (mit Figur) → 204 MB nach Kartenabbau. **Bundle-Entladung:** vor dem Gebietswechsel 70 → 26 MB Texturen (`Release` + `UnloadUnusedAssets`), danach Prefab `area003`: Texturen 69 → 121 MB (+52 MB, **Spitze**), Unity 225 → 229 MB, Prozess 892 MB (davon ca. 600 MB Editor-Grundlast; Stichproben-Spitze Unity 230 MB).
  **Weit unter 2,5 GB**; Gerätewerte fehlen. Beim Abbau bleiben einzelne Texturen bis zum nächsten `UnloadUnusedAssets` (z. B. 64 MB nach dem ersten Abbau).
- Datenprüfung: 1.615 auflösbare Spawn-Locators, davon 64 auf einer Stop-128-Zelle (meist Türzellen); Ziel-Locator aller Warps gültig; Zwieblüh: 4 Außentüren, passend zu den Attributen.
- Tests (neu): Facing/Kamera-Drehung (2), Warp-Rechteck und Auflösung (6), Router (10), Überblendung (3), Streaming und Budget (11), Platzierungen/Interaktion (16), Sprünge/NPC-Sperre/Wasser (10).

## 10. Lücken und nächste Schritte
1. **Bildkontrolle fehlt:** Es gibt kein Bild dieser Scheibe (Haupt-Editor nach Hang nicht wieder startbar). Offen: Figur (Ausrichtung/Skalierung/Animationsausgabe), Innenraumkamera 180°, NPC-Marker, Überblendung, Übergang an Zonengrenzen.
2. **Material-Umbau im Bild:** Licht, Schatten, Globals mit Spielwerten, Himmel; Ursache des Editor-Hangs (siehe 6). Player-Build mit `Resources`-Shadern ungeprüft.
3. Außentüren nur für Raumausgänge mit Feld-Ziel; Türen in Höhlen/Untergrund (`UGSPACE*`) und die 14 ungelösten Warps nicht. Treppen/Türen anderer Gebiete ungetestet am Bild. `InputDir` als Auslöser nicht ausgewertet.
4. Interaktion: Blickkontakt von Trainern (Sichtweite aus `MoveParam`), `TalkBit`, Laufmuster (`MoveCode`), NPC-Modelle (`CharacterGraphics`), Flags aus dem Interpreter.
5. Streaming: Abstände sind abgeleitet, nicht aus dem Original; Texturspeicher fällt erst mit dem Gebietswechsel; Wasser/Himmel/Wetter nicht blockweise.
6. Fahrrad, Schwimmen, Angeln, Klettern; Kantensprung-Dauer/Bogen; Brücken weiter nur synthetisch geprüft (Scheibe 1, Punkt 8).
7. Messung auf dem iPad (Speicher, 30 Hz) steht aus.
