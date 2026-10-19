# Player-Build 1: erste echte Builds für macOS und iPad (Todo `ap-packaging` / `ap-build-all`)

Stand: 2026-10-19. Erstmals wurden mit der Build-Pipeline echte Player-Builds (IL2CPP, arm64, nur Metal) mit den echten Bundles erzeugt, gestartet und ausgewertet: macOS (M1 Pro, 16 GB) und iPad Pro 12,9" (6. Generation, `iPad14,6`, M2, 7518 MB sichtbar, 128 GB, iPadOS 26.4.2). Alle Zahlen stammen aus diesen Läufen (Logs nur lokal unter `work/builds/`, gitignoriert). **Ton blieb aus** (`AudioSafety`, jeder Lauf meldete „Ton: aus“); die Lautstärke von Mac und iPad wurde nicht angefasst. Keine Spieldaten, Bilder oder Builds im Repo, die Team-ID steht nur in `work/local.env`.

## 1. Ergebnis in Kürze

| Frage | Ergebnis |
|---|---|
| macOS-Build mit Pipeline-Skript | **läuft**: IL2CPP, arm64, Metal; erster Build 202 s, danach 44 s (inkrementell), nach Zielwechsel 92 s; App 4,1 GB (Ausgabeordner mit Symbolen 5,0 GB). |
| macOS-App startet mit den Spieldaten im Paket | **ja**: Boot-Szene, `-xnuScene`/`XNU_START_SCENE` startet `FieldTest2`; Zone 422 (Zwieblüh) lädt in 1,2 s, 30 FPS, kein Absturz in 60 s. |
| **Größter Fund: Switch-Bundles lädt kein Player** | Die Bundles tragen die Zielplattform 38 (Switch). Der Editor lädt sie trotzdem, der **Player lehnt sie ab** („The file can not be loaded because it was created for another build target…“). Lösung: `scripts/bundle_retarget.py` setzt die Plattformkennung (4 Bytes je Bundle) in der Stufe `assets`. |
| iOS-Build, Installation, Start auf dem iPad | **läuft**: Unity-Build 19 s (inkrementell, 247 s mit erstem Zielwechsel), `scripts/ios_deploy.sh` 2 min 40 s (Xcode Release plus Installation), Start mit `devicectl --console`, Zone 422 lädt in 1,1 s, 30 FPS, thermisch nominal. |
| **Offen und kritisch für iOS: Texturformate** | Die Karten-Bundles enthalten BC1/BC3/BC7 (DXT). Apple-GPUs unterstützen sie nicht, Unity kann sie nicht entpacken: auf dem iPad schlagen **1.884 Texturen** der Zone 422 fehl (Abschnitt 6). Ohne Umwandlung nach ASTC (oder RGBA) bleibt die Karte auf iOS ohne Texturen. |
| Stripping | Ein Fund: iOS strippte `SkinnedMeshRenderer` („Could not produce class with ID 137“, 30-mal). `unity/Assets/link.xml` behebt es; danach 0 Fehler dieser Art. |
| Generierte Shader im Player | **gelöst und belegt**: `Shader.Find` findet 61 von 61 Shadern im macOS-Player (Resources-Mechanismus). Der Build gleicht sie vorher automatisch ab. |
| Tests | Unity EditMode **635 von 635 grün** (624 Bestand plus 4 neue Boot-Tests und 7 von anderen Agenten), Python-Suite 258 grün (8 neue Tests für den Retarget). |

## 2. Was gebaut und geändert wurde

| Datei | Inhalt |
|---|---|
| `unity/Assets/Scripts/Boot/BootMenu.cs`, `BootOptions.cs` | Startszene **Boot**: zeigt Spieldaten-Zustand (Pfad, Bundles, Stammdaten, Ton), Gerät, Speicher und eine Auswahlliste der übrigen Build-Szenen (IMGUI, nur eigene Objekte). `-xnuScene <Name>` oder `XNU_START_SCENE=<Name>` startet eine Szene ohne Eingabe (Messläufe, iPad per `devicectl`). Nach dem Wechsel bleibt oben rechts eine Schaltfläche „Menü“. Alle 10 s eine Logzeile mit Szene, FPS, Speicher. |
| `unity/Assets/Scenes/Boot.unity` | Kamera, `DisplayController`, `BootMenu`. Erzeugt von `BootSceneBuilder` (Menü `Xnu/Build/Boot-Szene erzeugen`, und automatisch, wenn der Build sie braucht und sie fehlt). |
| `unity/Assets/Scripts/Build/Editor/BuildScript.cs` | Standard-Szenenliste: Boot, FieldTest2, FieldTest, UiTest, InputTest (Build Settings des Projekts bleiben leer). Vor jedem Build: **Abgleich der erzeugten Shader** nach `Assets/XnuGenerated/Resources` (Quelle `-xnuShaders`, `XNU_SHADERS`, `work/build/shaders`, `work/shaders/combined`, jeweils mit `variants.json`). Meldet Größe der Spieldaten im Paket. Assembly referenziert jetzt `Xnu.Boot`, `Xnu.Render.Editor`. |
| `unity/Assets/Scripts/Boot/BundleSource.cs` | Eine Logzeile je geladenem Bundle (`[Boot] Bundle geladen: …`); damit lässt sich die Bundle-Menge einer Szene messen. |
| `unity/Assets/link.xml` | Behält Core-, Animation-, Physik- und Partikelmodul (Abschnitt 5). Kein Audio-Modul. |
| `scripts/bundle_retarget.py` | Setzt die Zielplattform in UnityFS-Bundles (`info`, `patch`, `tree`, `subset`). |
| `scripts/build_all.sh`, `scripts/build_stages.py` | Stufe `assets`: `--bundle-platform macos|ios|keep` (Standard aus `--target`), `--bundle-subset DATEI`, kopiert zusätzlich `work/materials`; Marker-Hash berücksichtigt Plattform, Teilmenge und Materialien. |
| `scripts/subsets/ipad-start.txt` | Bundle-Teilmenge für den iPad-Start (5 Bundles). |
| `scripts/tests/test_bundle_retarget.py`, `unity/Assets/Tests/EditMode/BootOptionsTests.cs` | 8 Python-Tests mit synthetischen Bundles, 4 Unity-Tests. |
| `.gitignore` | `unity/Assets/StreamingAssets.meta`. |

## 3. macOS

### 3.1 Daten ablegen (Stufe `assets`)
| Schritt | Zeit | Größe |
|---|---|---|
| nur Klonen der Bundles, 14.187 Dateien (erster Lauf, Plattform unverändert) | 4 s | 3,9 GB, ohne zusätzlichen Platz (APFS-Klon) |
| Klonen und Plattform setzen (14.052 Bundles werden neu geschrieben, damit kein Klon mehr) | **24 s** mit unkomprimiertem Block, **42 s** mit LZ4HC-Neukompression | 4,8 GB bzw. **4,0 GB** (14.833 Dateien inkl. 646 Materialexporte und 104 MB Stammdaten) |

### 3.2 Build
| Lauf | Dauer | Größe laut Bericht | Warnungen |
|---|---|---|---|
| erster Build (kalt, Bundles unverändert) | **202 s** | 4.827 MB | 237 (alle aus den erzeugten Shadern: „loop only executes for 1 iteration“, „unary negate of unsigned value“) |
| zweiter Build (inkrementell, Plattform gesetzt, Block 0 unkomprimiert) | **44 s** | 5.728 MB | 4 |
| letzter Build (nach Zielwechsel von iOS zurück, Stufe `assets` mit LZ4HC) | **92 s** | 5.052 MB (App 4,1 GB, Ausgabeordner 5,0 GB) | 237 |

Fehler: 0. Das Skript meldet vorher die Spieldaten im Paket und den Shader-Abgleich („61 Varianten (ok), kopiert/unverändert“). Der Build schreibt außerdem in `ProjectSettings.asset` (Scripting-Backend IL2CPP für Standalone, nur Metal für macOS und iOS, Eintrag für Input-System-Einstellungen); das ist gewollt und gehört ins Repo.

### 3.3 Lauf (Direktaufruf, `-logFile`, kein Ton, nach 60 s per `kill <PID>` beendet)
- **Fehler 1 (ohne Retarget):** „The file can not be loaded because it was created for another build target … File's Build target is: 38“, danach `AssetBundle.LoadFromFile lieferte null`. Ursache: Bundles für die Switch. Lösung wie oben.
- **Danach:** Boot: „Xnu 0.1, Unity 6000.3.26f1, OSXPlayer“, `MacBookPro18,3`, 16.384 MB, Grafik Apple M1 Pro (Metal); Spieldaten „im Paket (StreamingAssets)“; Bundles und Stammdaten vorhanden; Ton aus.
- `FieldTest2`: Katalog 214 ms, Stammdaten 917 ms, Bundle `area001` geöffnet 930 ms, Prefab 1.144 ms, Zone 422 komplett nach **1,2 s** (433 Renderer, 12.465 Vertices, 75 Collider, Spielerfigur `fc0001_00` mit 3 von 3 Clips). **30,0 FPS** (Original-Vorgabe vSync 2 → 30), Unity-Speicher 102 MB (davon Texturen 47 MB), Prozess-RSS 470 bis 570 MB, in 60 s konstant, keine Ausnahme.
- Es werden genau vier Bundles geladen: `Environments/fields/area001` (23,4 MB), `Characters/persons/field/fc0001_00` (2,7 MB), `fc0001_11` (1,9 MB), `pc_parts` (0,5 MB).
- Warnungen im Log: „The referenced script (…) on this Behaviour is missing!“ (`FieldEventDoorEntity`, `EmissionColorChanger`, `AudioAmbient`, `FieldEffect`, `FieldPlayerEntity`): erwartet, die Originalskripte gibt es nicht (im Editor identisch). Keine Shader- oder Texturfehler auf macOS (BC wird von der Mac-GPU unterstützt).
- **Generierte Shader im Player:** mit `XNU_GENERATED_SHADERS=1` und `XNU_MATERIALS=…`: „Umbau (Shader **61/61**, 124 Materialeinträge)“, 29,5 bis 29,9 FPS, kein Absturz (im Editor hatte derselbe Umbau das Bild schwarz gemacht bzw. den Editor blockiert, `docs/feld-szene-2.md`, Kapitel 6; im Player trat das nicht auf; ob das Bild richtig aussieht, wurde **nicht** geprüft, siehe Lücken).
- `UiTest` 30,0 FPS, `InputTest` 59,6 FPS, Boot-Szene 59,4 FPS, jeweils ohne Fehler.
- Ein Bildschirmfoto war nicht möglich (`screencapture`: „could not create image from display“, keine Berechtigung bzw. kein Display); die Sichtprüfung fehlt deshalb.

### 3.4 Endlauf
Der letzte Build (mit `assets` und LZ4HC-Neukompression) wurde erneut gestartet: `FieldTest2` lädt dieselben vier Bundles, Zone 422 komplett, 30,0 FPS, Unity-Speicher 104 MB, keine Fehler. Danach wurden App und `StreamingAssets` gelöscht (Platz); alles ist mit den Befehlen aus Abschnitt 7 in rund 2 bis 5 Minuten reproduzierbar.

## 4. iOS / iPad

### 4.1 Teilmenge der Bundles
Die gesamten Bundles (4,0 GB) wurden **nicht** auf das iPad gelegt. Gründe:
1. Die Karten-Texturen sind auf iOS ohnehin unbrauchbar, bis die Umwandlung existiert (Abschnitt 6); 4 GB Daten mit 1.884 fehlerhaften Texturen belegen nichts Brauchbares.
2. Die Installation per Xcode kopiert das ganze Paket; die Zeit für 4,9 GB über USB wurde nicht gemessen und stünde bei jedem Testlauf im Weg.
3. Gerätespeicher: 128 GB laut `devicectl` (`internalStorageCapacity`). Der **freie** Platz ist weder über `devicectl` noch über `DriveInfo` in der App abfragbar (Boot-Zeile „Freier Speicher: unbekannt“ auf Mac und iPad). Der Platz ist also nicht belegt; eine Installation von 4,9 GB wurde nicht versucht.

Auswahl: die Bundles, die der Start der Szene `FieldTest2` **tatsächlich lädt**, gemessen mit dem macOS-Player (vier Bundles, 28,5 MB, Abschnitt 3.3), plus der Textbox-Skin der UI-Szene. Das steht in `scripts/subsets/ipad-start.txt`; `scripts/build_all.sh --only assets --target ios --bundle-subset scripts/subsets/ipad-start.txt` legt sie samt Katalog (`Dpr.bin` u. a., immer mitkopiert) ab. Ergebnis: 9 Dateien, 34,6 MB Bundles, mit Stammdaten (104 MB) und Materialexporten (47 MB) **179 MB** im Paket. Nicht enthalten: weitere Zonen (Türen und Zonenwechsel in `FieldTest2` führen auf Bundles, die fehlen), Kampf, UI-Bundles, Videos, Audio.

### 4.2 Build und Deploy
| Schritt | Dauer / Größe |
|---|---|
| Unity-Build (iOS) | 19 s inkrementell, 247 s beim ersten Zielwechsel (neuer Import für iOS); Xcode-Projekt 967 bis 1.055 MB (mit `link.xml`) |
| `scripts/ios_deploy.sh --no-launch` (Xcode Release, signieren, installieren) | **2 min 40 s** (erster Lauf), ca. 2 min 25 s (zweiter) |
| Entitlement „Increased Memory Limit“ | `Xnu.entitlements` im Projekt, `CODE_SIGN_ENTITLEMENTS` gesetzt |
| Start | `xcrun devicectl device process launch --device <iPad> --terminate-existing --console --environment-variables '{"XNU_START_SCENE":"FieldTest2"}' dev.local.xnum0` |

**Fehler 2 (Postbuild):** Der erste Build aus dem offenen Editor (aktives Ziel macOS) lieferte **kein** `Xnu.entitlements`: `IosPostBuild.cs` ist mit `#if UNITY_IOS` umschlossen und existiert nur, wenn beim Kompilieren das Ziel iOS aktiv ist. Beim Zielwechsel in `BuildPlayer` gilt das nicht sofort. Der Batchaufruf der Pipeline (`-buildTarget iOS`) ist davon nicht betroffen; im offenen Editor erst nach dem Wechsel (zweiter Aufruf) und nach einer neuen Kompilierung. Die Stufe prüft `Xnu.entitlements` nach dem Bau und bricht sonst ab (unverändert).

### 4.3 Lauf auf dem iPad (60 s, danach beendet)
- Boot: `IPhonePlayer`, `iPad14,6`, 7518 MB RAM, Grafik **Apple M2 GPU (Metal)**, Spieldaten im App-Paket (`…/xnu.app/Data/Raw/GameData`), Ton aus.
- Zone 422: Katalog 349 ms, Stammdaten 881 ms, **komplett nach 1,1 s**; 30,0 FPS konstant (Zielwert der Szene), `thermalState` nominal; Unity-Speicher 92 MB, Mono 73 bis 76 MB (Profiler-Zähler; „Grafik 0 MB“ ist auf Metal kein brauchbarer Zähler, der echte Footprint wurde in dieser App nicht gemessen).
- Keine Abstürze, keine Ausnahmen. Fehler im Log: nur die Texturumwandlung (Abschnitt 6) und die erwarteten „script missing“-Meldungen.

## 5. Stripping und Reflection
- **Reflection:** Die Suche nach `Activator`, `System.Reflection`, `GetType`, `JsonUtility` im Laufzeitcode ergab keine echte Reflection-Nutzung (Treffer waren Methodennamen wie `TryGetField`). Die Datenleser nutzen den eigenen `MiniJson`. Eine `link.xml` für Projektklassen war deshalb **nicht** nötig.
- **Engine-Stripping:** Der iOS-Player (nicht der macOS-Player) strippte `SkinnedMeshRenderer` (Klassen-ID 137), weil nur Bundle-Inhalt, keine Szene ihn referenziert; Folge: Spielerfigur ohne Mesh-Komponente. `unity/Assets/link.xml` behält die Module Core, Animation, Physik und Partikel. Das ist breiter als nötig, aber sicher für fremde Bundle-Inhalte (Collider, Animator, Partikel). Kosten: Xcode-Projekt +88 MB. Danach 0 Meldungen „Could not produce class“. Audio ist bewusst nicht enthalten.

## 6. Offene Lücken (mit Reihenfolge)
1. **Texturen für iOS (Nachtrag 2026-10-19: Umwandlung umgesetzt, siehe `docs/ios-texturen.md`; auf dem iPad noch nicht gelaufen).** Die Karten-Bundles enthalten DXT1 (BC1), DXT5 (BC3), BC7 (und BC5/BC6H). iOS meldet je Textur „format is not supported, decompressing texture“, danach „Failed to decompress“ (Zone 422: 1.884 Meldungen; Figuren und UI nutzen ASTC 6×6 und sind unproblematisch). **Nächster Schritt:** BC → ASTC beim Bauen für iOS (Entwurf: pro Bundle die Texturen mit `texture2ddecoder`/`astc_encoder` aus `tools/pydeps` umschreiben, dabei `m_TextureFormat` und Datenblöcke tauschen; Speicherziel 2,5 GB beachten) oder zur Laufzeit beim Laden dekodieren (teurer, mehr Speicher). Auf macOS ist das nicht nötig.
2. **Sichtprüfung.** Weder auf dem Mac (kein Bildschirmfoto möglich) noch auf dem iPad wurde das Bild gesehen; belegt sind Logs, FPS und Ladezeiten, nicht das Aussehen. Ebenso unverifiziert: Bedienung des Boot-Menüs per Maus/Touch (IMGUI mit dem Input System „nur neu“; Start per Argument funktioniert, das Anklicken wurde nicht getestet).
3. **Volle Bundle-Menge auf dem iPad.** Installation von rund 4,9 GB, Ladezeit und Platz sind nicht gemessen (Abschnitt 4.1). Der Plan für „fertig gepacktes Binary“ (`docs/kernziel.md`): die volle Menge in das Paket, **nachdem** die Texturumwandlung läuft; bis dahin Teilmengen je Testszene aus den Logzeilen `[Boot] Bundle geladen`. Der Mechanismus (`--bundle-subset`) ist da; eine automatische Hülle aus dem Katalog (`Dpr.bin`) steht aus.
4. **`--target all`** legt nur einen Satz `StreamingAssets/GameData` an (Plattform `macos`); für iOS die Stufe `assets` mit `--target ios` erneut laufen lassen und dann bauen.
5. Generierte Shader im Player: geladen und gefunden (61/61), das Bild wurde nicht geprüft; auf iOS ohne Texturumwandlung nicht sinnvoll.
6. Video und Audio nicht Teil dieses Laufs (Stufe `video` nicht gelaufen, `audio` nicht umgesetzt).
7. Der Unity-Batch-Treiber der Pipeline (Editor geschlossen) wurde **nicht** ausgeführt, weil der Haupteditor lief; gebaut wurde über die Menüeinträge `Xnu/Build/…` im offenen Editor. Die Stufe `unity-build` bleibt damit nur per Dry-run geprüft.

## 7. Wiederholung
```sh
# macOS (Editor geschlossen: Stufe unity-build, sonst Menü Xnu/Build/macOS im offenen Editor)
scripts/build_all.sh --only assets,unity-build --target macos --min-free-gb 20
work/builds/macos/xnu.app/Contents/MacOS/xnu -logFile $PWD/work/builds/player.log     # -xnuScene FieldTest2 oder XNU_START_SCENE
# iPad: Teilmenge, dann bauen und installieren
scripts/build_all.sh --only assets --target ios --bundle-subset scripts/subsets/ipad-start.txt --min-free-gb 20
#   Unity: Menü Xnu/Build/iOS und iPadOS (Xcode-Projekt)   (im offenen Editor zweimal, falls Xnu.entitlements fehlt)
DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer scripts/ios_deploy.sh work/builds/ios/xnu --no-launch
xcrun devicectl device process launch --device <iPad> --terminate-existing --console --environment-variables '{"XNU_START_SCENE":"FieldTest2"}' dev.local.xnum0
```
Hinweis zu `-logFile`: Unity braucht einen **absoluten** Pfad; mit einem relativen Pfad entsteht keine Logdatei.
