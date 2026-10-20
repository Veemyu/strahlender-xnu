# iPad-Durchstich 1: Titel → Weiter → Feld → Tür → Schwester → Wildkampf → Speichern auf dem iPad (Todo `ap-ipad-slice`)

> **Historisch (Stand 2026-10-20):** Unity-Weg, eingestellt. Die Stufe `assets` und `scripts/bundle_retarget.py` sind auf `main` entfernt (nur Branch `unity`); die Befehle unten laufen dort nicht mehr.

Stand: 2026-10-19, iPad Pro 12,9" (6. Generation, `iPad14,6`, M2, 8 GB, iPadOS 26), Unity 6000.3.26f1, IL2CPP, Metal, Built-in RP, Release-Build, Teilmenge `scripts/subsets/ipad-start.txt` (789 Dateien, 229 MB, ASTC 6×6). Nur Namen, Zahlen und Struktur; keine Spieltexte, keine echten Saves, keine Bilder im Repo (Logs und Bilder unter `work/`, gitignoriert). **Ton blieb aus** (`AudioSafety`, Lautstärke des Geräts nicht angefasst; das Gerät wurde nur gestartet und beendet). Prüfstufen wie in `docs/spielkern-1.md`: **[A]** Annahme, **[P]** belegt.

## 1. Ergebnis in Kürze

| Frage | Ergebnis |
|---|---|
| Durchlauf ohne Hand-Eingabe | **Läuft auf dem iPad bis zum Ende** (Eingabeskript per Datei im Container, 3 vollständige Durchläufe und 3 Kurzläufe, jeweils `quit`, Exit-Code 0): Titel → „Weiter“ → Zone 167 → Tür (Zonenwechsel 167 → 168) → Schwester (4 Textfenster, 1 Auswahl, Ereignis 1/1) → Wildkampf (9 Protokollschritte, 1 Befehl, Kämpfe 1/1) → Speichern (979.108 Byte). |
| Ursache „Slot keiner“ | **Pfad verdoppelt** (App suchte `Documents/Saves/Saves/main`, die Datei lag in `Documents/Saves/main`) **und** ein von `devicectl` angelegter Ordner gehört `root`, die App durfte dort nichts anlegen (Abschnitt 2). Beides behoben. |
| Texturfehler der Zone | **0** (vorher 1.884 BC-Fehlschläge); 0 Fehlermeldungen in allen Läufen. Die Bilder zeigen die Texturen richtig (Abschnitt 5). |
| Ladezeit | Stammdaten 1,3 s; Zone 167 steht **2,4 s** (Ersatzmaterial) bzw. **3,2 bis 3,4 s** (mit erzeugten Shadern, Umbau 61/61) nach „Weiter“; Tür 167 → 168 rund 4,2 bis 4,6 s bis die Innenkarte steht. |
| Bildrate | Ziel 30: **30,0 FPS**; Ziel 60: **60,0**; Ziel 120: **119,9** (auch mit der Außenkarte, 2.431 Renderer). Ohne gesetztes Ziel liefert Unity 30 (wie in `docs/ipad-messung-1.md`). |
| Speicher | Footprint **736 bis 861 MiB** (Spitze 861,2 MiB), `os_proc_available_memory` mindestens **7.342 MiB** (Limit 8.192 MiB mit Entitlement), `lowMemory` 0, kein Leck in 190 s Feldbetrieb. |
| Thermik | `thermalState` **0** (nominal) in allen Läufen; nur 3 bis 4 Minuten Spiellast, kein Dauertest. |
| Absturzfreiheit | 6 Läufe von 50 bis 190 s ohne Absturz. |
| Tests | **696 von 696 grün** (688 vorher, 8 neue). |

## 2. Ursache der fehlenden Slot-Erkennung **[P]**

Gesucht wurde auf dem Gerät in `Application.persistentDataPath` (iPadOS: `/var/mobile/Containers/Data/Application/<UUID>/Documents`). Vier Fehler, in dieser Reihenfolge gefunden:

1. **Doppelter Ordner `Saves`.** `GameDriver` übergab `persistentDataPath/Saves` als Ablage, `SaveStore` hängt selbst `Saves/<Slot>` an: der Slot lag erwartet unter `Documents/Saves/Saves/main/SaveData.bin`. Die frühere Übertragung legte die Datei nach `Documents/Saves/main/SaveData.bin` – dort schaute niemand nach. Auf dem Mac fiel das nicht auf, weil dort der Slot von der App selbst angelegt wurde. Jetzt: Ablage = `persistentDataPath` (neu `SaveSlotService.ResolveRoot`), der Slot liegt unter **`Documents/Saves/main`**. Ist ein älterer Mac-Slot `…/Saves/Saves/main` vorhanden, bleibt dieser Ordner maßgebend.
2. **Slot = „Ordner vorhanden“.** `HasSlot` prüfte nur, dass ein Ordner `main` existiert; ein leerer Ordner oder eine halb übertragene Datei galt als Spielstand und ließ „Weiter“ später mit unklarem Fehler scheitern. Jetzt gilt ein Slot nur mit gültiger `SaveData.bin` oder `Backup.bin` (Version, Größe, MD5-Hash); sonst gibt es einen Grund im Log und auf dem Titel („Kein gültiger Spielstand: …“). `SaveSlotService.Diagnose()` schreibt beim Start Pfade, Größen, Kurzhash (SHA-256, 12 Zeichen) und Gründe ins Log (`[Game] Spielstand: …`); „Weiter“ liest den Zustand neu, wenn die Datei erst nach dem Start eintrifft.
3. **Ordner mit Besitzer `root`.** `devicectl device copy to … --destination Documents/Saves/main/SaveData.bin` legt fehlende Zwischenordner mit `ownerUid 0`, Modus 755 an (per `devicectl device info files --json-output` gesehen); die Datei selbst gehört dem Nutzer `501`. Die App (Nutzer `mobile`, 501) darf in `Saves/main` dann nichts anlegen: `SaveFileIO.WriteAtomic` scheiterte beim Schreiben der Temp-Datei mit `UnauthorizedAccessException`, Speichern war unmöglich. Folge: siehe 4. Jetzt legt `scripts/ios_push_save.sh` die Datei **ohne Zwischenordner** nach `Documents/SaveData.bin` (Documents gehört der App); die App importiert sie in einen **selbst angelegten** Slot (richtiger Besitzer). Ist ein Slot-Ordner trotzdem nicht beschreibbar, meldet `Diagnose()` das („Slot-Ordner nicht beschreibbar (Besitzer root …)“).
4. **Fehler in Skriptbefehlen wiederholten sich endlos.** Das fehlgeschlagene `save` wurde in jedem Tick erneut versucht und legte dabei jedes Mal ein Backup an: **11.190 Backups (rund 10,7 GB) in 80 s** auf dem iPad, dazu 2.289 Fehlermeldungen in 120 s. Jetzt fängt `GameDriver.Execute` Ausnahmen je Befehl ab (Meldung, `ScriptCommandErrors`, Befehl gilt als erledigt), `SaveNow` meldet Schreibfehler als Text. Der Test-Container wurde danach durch Deinstallation geleert.

Nebenbefund: Argumente nach dem Bundle (`devicectl device process launch … dev.local.xnum0 -- -xnuPerfLog`) kommen in der App **nicht** an (Startzeile ohne Option, kein `XNUPERF`); **Umgebungsvariablen** per `--environment-variables '{…}'` funktionieren (alle Optionen haben eine Variable: `XNU_START_SCENE`, `XNU_SCRIPTED_INPUT`, `XNU_PERF_LOG`, `XNU_TARGET_FPS`, `XNU_GENERATED_SHADERS`, `XNU_ENV_HOUR`). Das Eingabeskript wird relativ zu `Documents` aufgelöst (`XNU_SCRIPTED_INPUT=run-ipad.txt`).

## 3. Verfahren: Spielstand aufs iPad **[P]**

Quelle bleibt unverändert (`Ryujinx/bis/user/save/0000000000000006/0/SaveData.bin`, 979.108 Byte, gitignoriert; nur gelesen). Ausgaben nennen nur Größen und Hashes.

**(a) `scripts/ios_push_save.sh`** (Standardweg, getestet)
- `scripts/ios_push_save.sh [--source Datei] [--bundle-id ID] [--reimport] [--dry-run]`; Gerät aus `xcrun devicectl list devices` (erstes verbundenes iPad, `DEVICE_NAME` optional), Bundle-ID `dev.local.xnum0`; die Team-ID wird nicht gebraucht und nicht ausgegeben.
- Ablauf: Quelle prüfen (Größe ≤ 1 MiB, SHA-256) → vorhandenen Slot vom Gerät nach `work/ipad-save-backup/<Zeit>/` sichern → Datei nach `Documents/SaveData.bin` kopieren → zurückholen, Größe und SHA-256 vergleichen (Prüfsumme vor und nach).
- Beim nächsten **„Weiter“** importiert die App die Datei in `Documents/Saves/main`, sichert einen vorhandenen Slot unter `Documents/Backups/main/<Zeitstempel>/` und schreibt den SHA-256 der Datei in `Documents/ImportedDropIn.sha256`. Dieselbe Datei wird danach **nicht noch einmal** importiert, der Fortschritt im Slot bleibt. Eine **andere** Datei ersetzt den Slot (mit Backup). `--reimport` setzt die Merkdatei zurück (gleiche Datei ersetzt den Slot wieder, z. B. für Wiederholungsläufe).
- `scripts/ios_push_save.sh --pull [--dest Ordner]` holt `Saves/main/SaveData.bin` und `Backup.bin` zurück (nur nach `work/`).
- Nach dem Speichern auf dem Gerät: `Documents/Saves/main/SaveData.bin` und `Backup.bin` je 979.108 Byte (gültig, Besitzer 501), vorheriger Stand in `Documents/Backups/main/<Zeitstempel>/SaveData.bin`.

**(b) Dateien-App und Finder** (`IosPostBuild`, **[A]** im Gerät nicht angesehen)
- Der Build-Schritt `OnPostBuildDocumentSharing` trägt in die `Info.plist` `UIFileSharingEnabled` und `LSSupportsOpeningDocumentsInPlace` ein (reiner Textschritt `Xnu.Core.InfoPlistPatch`, idempotent, ohne Team-ID; `plutil -lint` des Build-Ergebnisses: OK). Damit erscheint der Documents-Ordner der App in der Dateien-App („Auf meinem iPad“) und im Finder; eine dort abgelegte **`SaveData.bin` im Documents-Ordner** (oder in `Documents/Import/`) wird wie in (a) beim nächsten „Weiter“ importiert. Dass der Ordner in der Dateien-App wirklich erscheint, wurde **nicht** am Gerät geprüft (Bedienung der Oberfläche war nicht Teil des Auftrags).

**(c) In-App-Import über den Dokumentenwähler:** nicht umgesetzt (braucht ein natives Plugin und Bedienung am Gerät; (a) und (b) decken den Bedarf).

## 4. Aufbau der Messung

- **Build/Deploy (Zeiten):** `scripts/build_all.sh --target ios --texture-format 6x6 --only assets --bundle-subset scripts/subsets/ipad-start.txt --force`: 33 s, 789 Dateien, 229 MB. Unity-iOS-Build über `Xnu/Build/iOS und iPadOS (Xcode-Projekt)`: 18 bis 26 s (Zielwechsel des Editors vorher rund 1,5 Minuten). `scripts/ios_deploy.sh work/builds/ios/xnu --no-launch`: 1 min 9 s. Danach wurde der Editor auf **macOS** zurückgestellt und `unity/Assets/StreamingAssets/GameData` gelöscht. Wichtig: `IosPostBuild` ist `#if UNITY_IOS`; nach einem Zielwechsel braucht es einen zweiten Build, weil der erste noch ohne die iOS-Nachbearbeitung (Entitlement, Info.plist) lief.
- **Messcode** (neu, `GameDriver`): Skriptbefehl `mem`; mit `XNU_PERF_LOG=1` alle 5 s Echtzeit eine Zeile `XNUPERF|t|state|fps|worstMs|ticks|footprintMiB|peakMiB|internalMiB|compressedMiB|availMiB|thermal|lowPower|unityMiB|monoMiB|errors|warnings|lowMemory` (Zähler aus `Xnu.Probe`/`os_proc_available_memory`, `phys_footprint`, `thermalState`); Zähler für Fehler- und Warnmeldungen (`Application.logMessageReceived`), `Application.lowMemory`; `XNU_TARGET_FPS` setzt `Application.targetFrameRate`; `report` nennt Fehlermeldungen. Einmalig: „Zone geladen nach … s seit ‚Weiter‘“ mit Speicherzeile.
- **Start:** `xcrun devicectl device process launch --device <ID> --terminate-existing --console --environment-variables '{"XNU_START_SCENE":"Game","XNU_SCRIPTED_INPUT":"run-ipad.txt","XNU_PERF_LOG":"1","XNU_GENERATED_SHADERS":"1","XNU_ENV_HOUR":"12"}' dev.local.xnum0 > work/builds/ipad-run-N.log`. Das Skript (`work/ipad-run/run-ipad*.txt`, Befehle wie `work/vslice/run5.txt`, dazu `shot` und `mem`) liegt per `devicectl device copy to` in `Documents/`. Bilder: der Skriptbefehl `shot` rendert die Spielkamera in eine RenderTexture (1280 × 720) und schreibt PNG nach `Documents/Shots`; geholt mit `devicectl device copy from` nach `work/visual/ipad/` (nur dort).
- Läufe: 1 (vor der Behebung, Speichern scheiterte, von Hand beendet), 2 (Ersatzmaterial, 50 s), 3 (Umbau, 190 s, Start im Innenraum), 4 (Umbau, Außenkarte, 50 s), 60-FPS-Lauf, 120-FPS-Lauf innen, 120-FPS-Lauf außen.

## 5. Messwerte **[P]**

| Messgröße | Wert |
|---|---|
| Stammdaten laden („Weiter“) | 1,3 s (707 Trainer, 183 Zonen, 209 Textdateien, 856 Skriptdateien, 12.985 Labels; auf dem Mac 2,2 bis 2,6 s im Editor) |
| Zone 167 steht, seit „Weiter“ | 2,4 s (Ersatzmaterial), 3,2 bis 3,4 s (Umbau mit erzeugten Shadern, „Shader 61/61, 109 Materialeinträge“, 2.431 Renderer, 4 Blöcke) |
| Tür 167 → 168 | 4,2 bis 4,6 s bis „Karte gebaut“ der Innenkarte (61 Renderer, 32 Materialeinträge), Überblendung 634 ms |
| Texturfehler der Zone | **0** (Fehlermeldungen in allen Läufen 0; 39 bis 125 Warnungen sind „referenced script … is missing“ der Original-Komponenten, wie auf dem Mac) |
| Texturspeicher (Unity-Zähler) | Außenkarte 25 MB, Innenkarte 27 bis 29 MB (Mac mit BC: 40 MB) |
| Bildrate 30 / 60 / 120 | 30,0 (Fenster 29,2 bis 30,0) / 60,0 (längste Bildzeit 17 ms) / 119,9 (längste 8 bis 12 ms, einmal 100 ms beim Laden) |
| Erstes Fenster nach „Weiter“ | bei Ziel 30 nur 10 bis 15 FPS im ersten 5-s-Fenster, weil eine Bildzeit 2,2 bis 3,4 s dauert (synchrones Laden der Zone, kein Streaming im Lauf) |
| Footprint | 726 MiB direkt nach der Zone (Innenraum, Umbau) bis 818 MiB (Außenkarte); während der Läufe 736 bis 861 MiB, Spitze 861,2 MiB (`peak`); `internal` 605 bis 705 MiB; `compressed` 0 |
| `os_proc_available_memory` | 7.342 bis 7.466 MiB (Limit 8.192 MiB mit Entitlement) |
| Managed-Heap (Mono) | 266 bis 335 MiB, im 190-s-Lauf 286 → 315 → 296 MiB (GC arbeitet, kein Wachstum), Unity-Allokator 92 bis 107 MiB |
| Dauer ohne Auffälligkeit | 190 s Feld/Kampf/Innenraum (Lauf 3): Footprint konstant 766,7 bis 795,1 MiB, 30,0 FPS, `thermalState` 0, `lowMemory` 0 |
| Thermik | `thermalState` 0, `lowPower` 0 in allen Läufen (3 bis 4 Minuten, kurz) |
| Speichern auf dem Gerät | `Documents/Saves/main/SaveData.bin` und `Backup.bin` je 979.108 Byte, Hash gültig (Validierung beim nächsten Start), Backup des alten Stands in `Documents/Backups/main/…`; je Speichern ein Backup-Ordner |
| Gerätespeicher nach Lauf 1 (Fehler) | 11.190 Backups ≈ 10,7 GB, per Deinstallation beseitigt |
| Ergebnisgleichheit mit dem Mac **[A]** | Der Stand nach dem Durchlauf (Zone 168, gleiche Zelle) hat denselben SHA-256 (`082a7fb0…`) wie die frühere Gerätedatei, die aus dem Mac-Lauf stammte: der iPad-Lauf speichert byteweise dasselbe wie der macOS-Player (gleiche Eingabe, gleicher Ort). Gesehen in Lauf 2; keine weitere Prüfung. |

**Bildbefunde** (nur lokal, sachlich beschrieben; Bildgröße 1280 × 720):
- *Außenkarte (Lauf 4, `f0_feld`):* Pokécenter von oben mit roter Dachfläche und weißem Ball-Zeichen, felsige Terrassen und Kanten in Beige/Braun mit sichtbarer Textur (Risse, Steinkanten), dunklerer Boden rechts unten; Helligkeit mittel, kontrastreich, ohne Schwarzflächen oder Magenta. Die Figur steht grau (Ersatz-Shader).
- *Innenraum (`f1_innen`):* Tresen mit Heilgerät, Pflanze, Regal, Kissen und Teppiche in Rot, Blau und Gelb, gekachelter Boden mit Ball-Zeichen, Holzwände mit Verlauf; Texturen und Helligkeit passend zum Mac-Lauf; NPC-Marker als blaue Kapseln; Spielerfigur grau.
- *Textfenster (Lauf 2, `f2_textbox`):* Original-Rahmen aus `sharedui` (hellgraue Fläche, dunkle Umrandung, Weiter-Zeichen unten rechts), zwei Zeilen Text in dunkler Serifenlosschrift, Umlaute korrekt (Pokémon); Karte dahinter im Lauf 2 noch ohne Umbau (graues Ersatzmaterial, Himmelblau).
- *Kampf (Lauf 4, `f4_kampf_befehl`):* Platzhalter-Kästen (#396 rot, #407 blau) statt Modellen auf zweifarbigem Grün, zwei Infotafeln mit Name, Stufe und grünem KP-Balken (eigene Seite mit Zahl), Befehlsmenü mit Kampf/Beutel/Pokémon/Flucht und Cursor, dunkle Meldungsleiste; lesbar, Layout wie auf dem Mac.

## 6. Lücken (ehrlich)

- **Ersatz-Shader der Spielerfigur** (grau) und **Platzhalter im Kampf** bleiben (wie `docs/vertikaler-durchstich-1.md`); der Umbau der Karte läuft mit `XNU_GENERATED_SHADERS=1` (nicht Standard, siehe `docs/feld-szene-2.md`); ohne die Variable bleibt die Karte grau (Lauf 2).
- **Dateien-App/Finder** (Abschnitt 3 b) am Gerät nicht angesehen; **Dokumentenwähler** (3 c) fehlt.
- **Ladehänger:** Das Laden der Zone ist synchron, das erste Bild steht 2,2 bis 3,4 s; ebenso die Tür (4,2 bis 4,6 s). Kein Ladebildschirm, kein Streaming im Lauf.
- **Außenkarte bei 60 FPS nicht einzeln gemessen** (30 und 120 ja; 120 hält, 60 liegt dazwischen); Innenraum bei allen drei Raten gemessen. Kein Last- oder Dauertest über 190 s; **Thermik** nominal, aber ohne Aussagewert für 30 Minuten Spielzeit; Raumtemperatur und Ladezustand nicht erfasst.
- **Nur ein Gerät, eine iPadOS-Version, eine Zone** (Pokécenter außen und innen), Teilmenge der Bundles (229 MB, nicht die vollen 4,9 GB); keine Tests mit anderen Zonen, kein Trainerkampf, keine Gras-Begegnung (wie am Mac).
- **Argumente** an die App kommen über `devicectl` nicht an (nur Umgebungsvariablen); die Option `-xnuPerfLog` o. ä. wirkt daher auf dem iPad nur per Variable.
- Der Merkdatei-Mechanismus kennt **eine** zuletzt importierte Datei; wer zwischen mehreren Ablage-Dateien wechselt, braucht `--reimport`. Frühere Läufe ohne Merkdatei starten beim ersten Mal mit dem vorhandenen Slot, falls er gültig ist (Ablage-Datei ersetzt ihn nur bei anderem Hash).
- **Messprobe im Spiel-Build:** `Xnu.Game.Unity` hängt jetzt an `Xnu.Probe` (natives Plugin `XnuMemoryProbe.m` ist in jedem iOS-Build enthalten).

## 7. Nächste Schritte

1. Zonenladen im Hintergrund (kein 2- bis 4-Sekunden-Bild) und Ladebildschirm; Streaming je Block statt synchron.
2. Außenkarte bei 60 FPS und 30-Minuten-Lauf mit Thermik; weitere Zonen aus der Teilmenge (Feldwege, Höhlen) und vollständige Bundle-Menge.
3. Dokumentenwähler oder Dateien-App-Test am Gerät (Abschnitt 3).
4. Spielerfigur und NPC-Modelle, Kampf-Modelle und Original-UI (siehe `docs/vertikaler-durchstich-1.md`, Abschnitt 8).

## 8. Geänderte und neue Dateien

`unity/Assets/Scripts/Game/Runtime/SaveSlotService.cs` (Slot-Prüfung, `ResolveRoot`, `DropInSources`, Merkdatei, `Diagnose`), `GameDriver.cs` (Ablage, Diagnose, Messung, Fehlerbehandlung der Skriptbefehle), `GameOptions.cs` (`XNU_TARGET_FPS`, `XNU_PERF_LOG`), `Xnu.Game.Unity.asmdef` (Verweis `Xnu.Probe`); `unity/Assets/Scripts/Core/InfoPlistPatch.cs` (neu); `unity/Assets/Scripts/Build/Editor/IosPostBuild.cs` (Info.plist); `unity/Assets/Tests/EditMode/GameUnityTests.cs` (8 neue Tests: Wurzel, Slot nach externer Kopie, abgeschnittener/leerer Slot, lose Datei und kaputter Slot, neue Ablage-Datei ersetzt den Slot einmal, ungültige Quelle, Info.plist, Optionen); `scripts/ios_push_save.sh` (neu).
