# iPad-Messung 1: Speicher, Bildrate, Thermik (Todo `ap-ipad-perf`)

> **Historisch (Stand 2026-10-20):** Unity-Messung. `scripts/ios_deploy.sh` ist auf `main` entfernt (nur Branch `unity`). Für die Rekompilation gilt `scripts/recomp/ios/deploy_ios.sh`.

Stand: 2026-10-19. Gemessen auf dem iPad Pro 12,9" (6. Generation, `iPad14,6`, M2, 8 GB, iPadOS 26.4.2) mit der Mess-App **MemoryProbe** (Unity 6000.3.26f1, IL2CPP, nur Metal, Release-Build, kostenloses Team, per `scripts/ios_deploy.sh` installiert). Die App enthält keine Spielinhalte, nur eine leere Szene, einen eigenen Lastshader und Allokationen. Ton blieb aus (`AudioSafety` aktiv, in jedem Lauf `audioListenerVolume=0`, `audioPause=1`); die Gerätelautstärke wurde nicht angefasst.
Rohlogs (Gerätekonsole, jede Zeile `XNUPROBE|...`) liegen nur lokal unter `work/measurement/` (gitignoriert).

## 1. Ergebnis in Kürze
| Frage | Ergebnis |
|---|---|
| Speicherlimit **ohne** Entitlement | **5120 MiB (5 GiB)**, in 3 Läufen und allen Phasen identisch (Summe aus `os_proc_available_memory` und `phys_footprint`). |
| Speicherlimit **mit** Increased Memory Limit | **8192 MiB (8 GiB)**, bereits beim Start sichtbar. Das liegt über dem Arbeitsspeicher des Geräts (7518 MiB sichtbar), ist also eine Obergrenze und keine Garantie. |
| Entitlement mit dem kostenlosen Team | Wird akzeptiert, signiert und wirkt (`codesign -d --entitlements` zeigt es, die App läuft, das Limit steigt um 3 GiB). |
| Systemwarnung (`Application.lowMemory`) | ohne Entitlement bei **ca. 4,0 bis 4,2 GB** Footprint, mit Entitlement erst bei **ca. 5,9 GB** (nur der native Test). |
| Footprint einer leeren Unity-Szene (Metal) | **ca. 180 MiB** nach dem Start, ca. 193 MiB nach 8 Minuten Last. |
| Bildrate | **120 FPS erreichbar** (119,9 gemessen), 60 und 30 ebenso, sofern `Application.targetFrameRate` gesetzt ist. Ohne gesetztes Ziel liefert Unity 30 FPS. |
| ProMotion-Schlüssel `CADisableMinimumFrameDurationOnPhone` | Für das iPad **ohne Wirkung** (120 FPS auch bei `false`; mit `true` unverändert). |
| Thermik | `thermalState` blieb in allen Läufen **nominal (0)**, auch bei 150 s GPU-Last und 300 s GPU- plus CPU-Last. Kein Aussagewert für längere Spielsitzungen. |
| Budget fürs Spiel | Richtwert **2,5 GB**, harte Obergrenze **4 GB** Footprint, Entitlement an lassen (Abschnitt 6). |

## 2. Aufbau der Messung
- **Code:** `unity/Assets/Scripts/Probe/` (`MemoryProbe.cs`, `NativeProbe.cs`, `ProbeMath.cs`, Shader `ProbeLoad`), natives Plugin `unity/Assets/Plugins/iOS/XnuMemoryProbe.m` (`os_proc_available_memory`, `task_info(TASK_VM_INFO)` mit `phys_footprint`, `internal`, `compressed`, `limit_bytes_remaining`, `NSProcessInfo.thermalState`, `physicalMemory`, `UIScreen.maximumFramesPerSecond`, Info.plist-Schlüssel, Metal-`currentAllocatedSize`). Tests der Rechenlogik: `ProbeTests.cs` (5 Tests, in der Suite grün).
- **Szene und Build:** `unity/Assets/Scenes/MemoryProbe.unity`, gebaut über `Xnu/Probe/...` im Editor (`MemoryProbeBuild.cs`) mit **eigener Szenenliste**; die Build-Settings des Projekts bleiben leer und unverändert. Bundle-ID `dev.local.xnumemprobe` und Produktname gelten nur während des Builds und werden danach zurückgesetzt. Ausgabe nach `work/builds/ios/memprobe-*`.
- **Entitlement-Schalter:** `IosPostBuild` trägt das Entitlement standardmäßig ein (Standard bleibt an). Ausschalten per Compile-Symbol `XNU_NO_INCREASED_MEMORY` oder per `SessionState`-Schlüssel `Xnu.Build.NoIncreasedMemoryLimit` (setzt `MemoryProbeBuild`). Die Messung ohne Entitlement wurde zusätzlich geprüft: das gebaute Xcode-Projekt hat dann kein `CODE_SIGN_ENTITLEMENTS`, `codesign` zeigt das Entitlement nicht.
- **Ablauf je Start (ca. 9 Minuten, mit Modus `fps` ca. 3):** Schnappschüsse bei Awake, erstem Bild und alle 5 s; Basis (8 s mit Projektvorgabe); Bildraten-Matrix (idle und mit leichter GPU-Last, je 5 s, die ersten 1,5 s verworfen); Dauerlast 150 s (GPU voll ausgelastet, Vollbild-Shader, ca. 44 FPS) und 300 s (zusätzlich 6 CPU-Threads); dann drei Speicherrampen in 128-MiB-Schritten: **nativ** (`AllocHGlobal`, mit Zufallsdaten gefüllt, damit nichts als Nullseite oder durch Wiederholung verschwindet), **Render** (RenderTexture 4096 × 4096 ARGBHalf = 128 MiB, einmal beschrieben) und **managed** (`byte[]`, Obergrenze 3 GB). Vor jedem Schritt Stopp, wenn `available - 128 MiB < 300 MiB` oder Footprint über 6 GiB läge; danach alles freigeben und 3 s warten. Jede Zeile wird sofort auf Platte geschrieben (`Documents/memprobe_*.log`), so wäre auch ein Kill nachvollziehbar gewesen.
- **Wiederholung:** `Xnu/Probe/Build iPad (Entitlement an|aus)` im Editor, dann
  `DERIVED_DATA=work/builds/ios-derived-memprobe BUNDLE_ID=dev.local.xnumemprobe scripts/ios_deploy.sh work/builds/ios/memprobe-ent --no-launch` und
  `xcrun devicectl device process launch --device <ID> --terminate-existing --console dev.local.xnumemprobe > work/measurement/console_....log` (`DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer`). `ios_deploy.sh` kennt dafür jetzt `DERIVED_DATA` und `DEPLOY_LOG`. Die Datei in `Documents` lässt sich mit `devicectl device copy from --domain-type appDataContainer` holen (getestet).
- **Läufe:** mit Entitlement 2 vollständige (davon einer mit gesetztem ProMotion-Schlüssel) plus 1 Bildraten-Lauf; ohne Entitlement 3 vollständige. Kein Lauf endete durch Jetsam; kein Neustart oder Absturz.

## 3. Speicher mit und ohne Entitlement
Alle Werte in MiB. „Limit“ = `os_proc_available_memory` + `phys_footprint` zum selben Zeitpunkt (Summe war stets 5120,0 bzw. 8192,0 ± 0,5, auch während der Rampen).

| | ohne Entitlement | mit Increased Memory Limit |
|---|---|---|
| `os_proc_available_memory` im ersten Bild | 4941,9 (3 Läufe: 4941 bis 4963) | 8013,8 (2 Läufe: 8014) |
| Limit (Summe) | **5120** | **8192** |
| nativ: gehalten bis Stopp | 4480 (Grund: Reserve, 402,7 verfügbar) | 5888 (Grund: 6-GiB-Obergrenze, 2108,8 verfügbar) |
| Render: gehalten bis Stopp | 4480 bis 4608 (Reserve, 289,6 bis 420,4 verfügbar) | 5888 (Obergrenze, 2076 verfügbar) |
| managed: gehalten bis Stopp | 2816 (Obergrenze 3 GiB) | 2816 |
| `lowMemory` | ab Footprint 4035 bis 4205 (nativ) und 4057 bis 4164 (Render), in allen 3 Läufen | nativ bei 6083, Render **keine** Warnung bis 6116 |
| Jetsam | nicht ausgelöst (Stopp mit Reserve) | nicht ausgelöst |

Beobachtungen:
- Das Limit lässt sich zur Laufzeit exakt berechnen: `Limit = os_proc_available_memory() + phys_footprint`. Das Spiel kann so sein Budget selbst bestimmen, statt Zahlen fest zu verdrahten.
- **GPU-Speicher zählt voll in den Footprint:** pro 128-MiB-RenderTexture stieg der Footprint um ca. 128 MiB (`mtlAllocMiB` erreichte 6028 MiB, also mehr als `recommendedMaxWorkingSetSize` mit 5461 MiB, ohne Folgen). Unified Memory heißt: Texturen und Render-Ziele gehen vom selben Budget ab wie der Rest. `SystemInfo.graphicsMemorySize` meldet nur 2048 MB und ist als Budget unbrauchbar.
- **Native Seiten werden auf diesem iPad stark komprimiert oder ausgelagert** (mit Entitlement `compressed` 5326 bei `internal` 626 MiB, ohne 4324 bei 220 MiB), obwohl die Daten zufällig sind. Der Footprint zählt sie dennoch voll. Nach `FreeHGlobal` fiel der Footprint von 6083 auf 832 (3 s später; `compressed` 320 bis 484 blieben zunächst stehen). Zugriffe auf ausgelagerte Seiten kosten Zeit; das ist nicht gemessen.
- **Der Managed-Heap (Mono/Boehm) gibt Speicher nicht zurück:** nach dem Freigeben der `byte[]` blieb der Footprint bei ca. 3025 MiB (`internal` 2851), bis die App endete. Große kurzlebige Managed-Spitzen sind teuer; native Puffer und RenderTextures werden sauber freigegeben.
- Einmaliger kleiner Mehrverbrauch beim Render-Schritt: Der Footprint wächst pro Schritt etwas mehr als 128 MiB (ohne Entitlement unterschritt die Reserve bei zwei Läufen mit 289,6 MiB den Wert 300, ohne Folgen).

## 4. Footprint der leeren Unity-Szene (Metal, Release)
| Zeitpunkt | Footprint | davon `internal` | Resident | Unity-Allokator | Metal `currentAllocatedSize` |
|---|---|---|---|---|---|
| `Awake` (ca. 2,1 s) | 156,4 bis 177,9 | 52 | 141 | 48 | 97 bis 119 |
| erstes Bild | 178,1 bis 178,5 | 52 | 142 | 48 | 119 |
| nach 8 s (Basis) | 179,4 bis 179,6 | 53 | 143 | 48 | 117 |
| während der Dauerlast | 190,7 bis 192,9 | 64 | 154 | 48 | 117 |

**Basis: ca. 180 MiB** (ohne Spielinhalte, mit Metal-Gerät, Layer, Backbuffer in 2732 × 2048 und Unity-Kern). Das sind 7 % des 2,5-GB-Richtwerts. Die `Profiler`-Zähler liefern auch im Release-Build Werte (`unityAllocMiB`, `monoHeapMiB`). Hinweis: Das Spiel bringt IL2CPP-Metadaten, Assemblies und Shader-Variantenspeicher dazu, die hier fehlen.

## 5. Bildrate, ProMotion, Thermik
Anzeige: `Screen.currentResolution` 120 Hz, `UIScreen.maximumFramesPerSecond` 120, Auflösung 2732 × 2048 bei 264 dpi. Mittelwerte aus je 3 bis 4 Läufen, alle Läufe stimmen auf ±0,1 FPS überein. „idle“ = leere Szene, „leicht“ = Vollbild-Shader mit 24 Iterationen.

| `vSyncCount` | `targetFrameRate` | gemessen idle | gemessen leicht | p99-Bilddauer |
|---|---|---|---|---|
| 0 | -1 (Standard) | **30,0** | – | 33,4 ms |
| 1 | -1 | **30,0** | – | 33,4 ms |
| 2 | -1 | **30,0** | – | 33,4 ms |
| 0 | 120 | **119,9** (min 107 bis 117) | 119,9 | 8,5 ms |
| 1 | 120 | 119,9 | 119,9 | 8,5 ms |
| 2 | 120 | 119,9 | – | 8,5 ms |
| 0 | 60 | 60,0 | 60,0 | 16,8 ms |
| 1 | 60 | 60,0 | – | 16,8 ms |
| 2 | 60 | 60,0 | 60,0 | 16,8 ms |
| 0 | 30 | 30,0 | 30,0 | 33,4 ms |
| 4 | 30 | 30,0 | 30,0 | 33,4 ms |

- **Unity unter iOS richtet sich nach `Application.targetFrameRate`; `vSyncCount` allein ändert nichts** (alle Werte mit Ziel -1 ergaben 30 FPS, alle Werte mit Ziel 60 ergaben 60 FPS). Das Projekt muss das Ziel immer setzen. `DisplayController` setzt beides (`FrameRatePlanner`: 120 Hz, 60 FPS → vSync 2, Ziel 60; 30 FPS → vSync 4, Ziel 30) und liegt damit richtig; alle drei Kombinationen wurden gemessen. Die Projektvorgabe im Probe-Build (iOS-Qualitätsstufe des Projekts, gemessen `vSyncCount` 1, Ziel -1) ergab ohne Ziel ebenfalls 30 FPS. Auffällig: `ProjectSettings/QualitySettings.asset` enthält sechs Standardstufen (vSync 0 bis 2), nicht die eine Original-Stufe mit vSync 2 aus `docs/render-treue.md`; das wurde hier nicht weiter verfolgt.
- **ProMotion-Schlüssel:** `CADisableMinimumFrameDurationOnPhone` ist laut Apple nur für iPhone nötig. Auf dem iPad waren 120 FPS mit `false` (Unity-Standard, `appleEnableProMotion: 0`) und mit `true` (separater Build) gleich. Die Info.plist enthielt in beiden Fällen auch `CADisableMinimumFrameDuration` (Unity setzt beide gleich). Der Schalter bleibt aus.
- Ob das System die Rate im variablen ProMotion-Betrieb zeitweise unter das Ziel senkt, zeigten die 5-s-Fenster nicht (kleinster Wert der Einzelbilder ca. 107 FPS in einem Fenster, sonst 113 bis 117). `FrameRateMode.Variable120` ist damit nur mit dem Ziel 120 und vSync 0 geprüft, nicht der Lastwechsel.
- **Dauerlast:** Fenster zu 10 s, 150 s, Vollbild-Shader (160 Iterationen), GPU voll ausgelastet: konstant **44,5 bis 44,7 FPS**, kleinste Einzelbildrate ca. 27 bis 30 FPS, `thermalState` 0 in allen 15 Fenstern, kein Abfall. Danach 300 s mit zusätzlich 6 Hintergrund-Threads (Rechenschleife): FPS fiel sofort auf **31,2** (erstes Fenster 33,9) und blieb 15 Fenster lang gleich, `thermalState` weiter 0. Der Abfall kam daher von der CPU-Konkurrenz, nicht von Wärme; die Ursache wurde nicht weiter zerlegt.
- Footprint während der Dauerlast stabil (190 bis 193 MiB, kein Leck).

## 6. Abgeleitetes Speicherbudget
Grundlage: Limit ohne Entitlement 5120 MiB, mit 8192 MiB; Warnschwelle ohne Entitlement ab ca. 4,1 GB, mit ca. 5,9 GB; Basis 0,18 GB.
- **Harte Obergrenze 4 GB Footprint** (Nutzervorgabe, Switch-Niveau): Mit Entitlement liegt das 1,9 GB unter der ersten Warnung und 4,1 GB unter dem Limit. **Ohne** Entitlement liegt 4 GB genau an der Warnschwelle und 1 GiB unter dem Limit, also zu knapp. Deshalb: **Entitlement bleibt an** (Standard in `IosPostBuild`).
- **Richtwert 2,5 GB** Footprint im Dauerbetrieb: lässt auch ohne Entitlement 2,6 GB bis zum Limit und 1,6 GB bis zur Warnung. Abzüglich Basis bleiben ca. **2,3 GB für Inhalte**.
- **Vorschlag zur Aufteilung** (nicht gemessen, nur Planungswert, bei Messung des echten Spiels anpassen): Texturen und Render-Ziele ca. 1,2 GB, Meshes, Animation und Material ca. 0,4 GB, native Puffer und geladene Bundles ca. 0,4 GB, Managed-Heap höchstens 0,3 GB (wegen fehlender Rückgabe klein halten), Rest Reserve.
- **Folgerungen für den Code:**
  1. Beim Start und vor jedem Zonenwechsel `Limit = available + footprint` lesen und das Budget daran messen (nicht fest verdrahten, andere iPads mit 4 oder 6 GB werden abweichen).
  2. `Application.lowMemory` behandeln (Caches leeren, Bundles entladen): ohne Entitlement kam die Warnung 1 GiB vor dem Limit.
  3. Große Texturen und Bundles nur zonenweise halten (siehe `docs/feld-szene-1.md`, Abschnitt 9) und danach entladen; Managed-Allokationen im Ladepfad vermeiden.
  4. Unified Memory: Render-Ziele (z. B. Schatten, Nachbearbeitung in 2732 × 2048) zählen voll mit.
  5. `Application.targetFrameRate` immer setzen (Abschnitt 5).

## 7. Messunsicherheiten und Lücken
- **Ein Gerät, eine iPadOS-Version (26.4.2), eine App ohne Spielinhalte.** 8-GB-Modell; die Zahlen gelten nicht für iPads mit 4 oder 6 GB oder den 16-GB-Modellen (1 und 2 TB).
- Der Wert **8192 MiB mit Entitlement** wurde nur bis 6116 MiB Footprint belegt; wir stoppten absichtlich (Vorgabe: ca. 6 GB). Wo der echte Kill durch Systemdruck bei 7,5 GB Arbeitsspeicher einsetzt, ist **nicht gemessen**. Das Limit ist eine Obergrenze, nicht verfügbarer Speicher: andere Apps im Hintergrund drücken das praktische Maximum, und dazu hat keine Messung stattgefunden (Hintergrund-Apps während der Läufe nicht kontrolliert).
- Die Entwicklungs-Signatur (`get-task-allow`, 7-Tage-Profil, kostenloses Team) kann sich von einer anderen Verteilung unterscheiden. Beobachtet wurde nur dieser Fall; zudem lief die App unter `devicectl --console` (ohne Debugger, aber mit Konsolenanbindung).
- Die Rampen füllen Speicher mit Zufallsdaten. Echte Spielzustände (Texturen, die sich komprimieren lassen; Streaming) verhalten sich bei Kompression und Auslagerung anders. Der Einfluss der Auslagerung auf die Bildzeit wurde nicht gemessen.
- `os_proc_available_memory` und `phys_footprint` sind Systemzähler mit Rundung; Differenzen unter 1 MiB zwischen Läufen sind Rauschen. Der Footprint-Anstieg pro Render-Schritt (> 128 MiB) enthält Treiberhilfsspeicher.
- Die Bildraten-Fenster dauern je 3,5 bis 6,5 s; das reicht für Mittelwerte, nicht für seltene Aussetzer. Last war synthetisch (ein Vollbild-Shader), nicht das Spiel. Ein **echter** Hitzetest (30 Minuten Spielbetrieb, Gehäuse, Raumtemperatur) fehlt: `thermalState` blieb nach rund 8 Minuten nominal, das sagt nichts über Dauerbetrieb aus. Die Raumtemperatur und der Ladezustand des iPads wurden nicht erfasst.
- Während der Läufe war das Display an (App hält `Screen.sleepTimeout = NeverSleep`, gilt nur solange sie läuft); die Messung hängt davon ab, dass das iPad entsperrt blieb.
- Ablaufnebenwirkung: Beim Lauf der Probe mit gesetztem ProMotion-Schlüssel wurde zuerst irrtümlich die Bundle-ID `dev.local.xnum0` überschrieben (Fehler im Build-Skript: veraltetes SerializedObject). Das Skript wurde korrigiert, `xnu-m0` auf dem iPad danach neu installiert. Die Projekteinstellungen wurden jedes Mal zurückgesetzt (`git status` auf `ProjectSettings` blieb leer).
