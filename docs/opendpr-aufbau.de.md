# opendpr-Projekt aus eigenem Dump zusammengebaut (2026-10-18)

> **Historisch (Stand 2026-10-20):** Unity-Weg, eingestellt. `scripts/opendpr_build.sh` ist auf `main` entfernt (nur Branch `unity`). Die Schritte unten gelten nicht mehr für `main`.

Eigene Zusammenfassung. Nichts aus `opendpr` oder `Lumi_Small_Scripts` liegt im getrackten Repo.
Das Projekt steht unter `work/opendpr-project/` (gitignored). Die Originale in `tools/` blieben unverändert.
Alle Schritte laufen wiederholbar über `scripts/opendpr_build.sh` (eigenes Skript, bricht ab, wenn das Ziel schon existiert).
Der Editor wurde nicht geöffnet.

## Protokoll

Freier Platz auf `/System/Volumes/Data` vor dem Lauf: 38 GiB (Grenze: 15 GiB). Nach dem Lauf ebenfalls 38 GiB (Messwert schwankt im Rahmen von ±1 GiB, die APFS-Clones kosten praktisch nichts). Der gesamte Lauf dauerte etwa 6 Sekunden.

| # | Schritt | Befehl / Ergebnis | Platz |
|---|---|---|---|
| 1 | Repo kopieren | `cp -c -R tools/opendpr work/opendpr-project`, danach die kopierte `.git` entfernt. 221 MB, davon 139 MB Wwise | ca. 0 (Clone) |
| 2a | Eingabe vorbereiten | Alle Ordner aus `work/ripper/out/ExportedProject/Assets` per `cp -c -R` nach `work/opendpr-stage/input`, **ohne** `StreamingAssets`, `.DS_Store` entfernt | ca. 0 |
| 2b | Skript | `python3 …/asset_ripper_resources/fix_pathids.py` im Stage-Ordner. Lief ohne Fehler. Das Log (96 Zeilen) besteht nur aus „Ignoring …“ für `Scripts` und `Plugins`. Ergebnis `output/`: 29 MB (Stage) | 29 MB, danach gelöscht |
| 3a | Löschen | `AkWwiseInitializationSettings`, `Mac`, `Switch`, `Windows` (je `.asset` + `.meta`) aus `MonoBehaviour` | – |
| 3b | TextMeshPro | `fonts & materials`, `sprite assets`, `style sheets` und beide `LineBreaking …txt` (mit `.meta`) nach `Assets/TextMesh Pro/Resources/` | 1 MB |
| 3c | Szene | `level0.unity` + `.meta` nach `Assets/` | – |
| 3d | Rest | Der übrige Inhalt von `Resources` und die Ordner `AnimationClip`, `AnimatorController`, `Font`, `Material`, `MonoBehaviour`, `PrefabInstance`, `Texture2D` liegen jetzt unter `Assets/Resources/` | 3,2 MB |
| 3e | Assembly-Name | `sed` auf `Assets/Resources/StartupSettings.asset`: 21 Ersetzungen, 0 Reste von „AssetAssistant, Version=0.0.0.0,“ | – |
| 4 | Bundle-Ordner | `AssetBundles/Editor/` angelegt, leer (Blocker B1) | 0 |
| 5 | StreamingAssets | `cp -c -R work/romfs/Data/StreamingAssets/. Assets/StreamingAssets/` (zusammengeführt mit dem vorhandenen Ordner `AK`). 18019 Dateien statt 18014 im RomFS (die 5 Extra-Dateien sind `AK` und `desc.txt` samt `.meta`). Stichprobe per `cmp` identisch | ca. 0 (Clone, 4,7 GB logisch) |
| 6 | Soundbanks | `Audio/GeneratedSoundBanks/Switch` → `Windows` | 0 |

Aufgeräumt: `work/opendpr-stage` (nur Zwischenstand) wurde gelöscht.

## Auffälligkeiten

- Der AssetRipper-Export enthielt trotz der Einstellung „StreamingAssets überspringen“ einen Ordner `StreamingAssets` mit 4,9 GB. Er wurde bewusst nicht in die Eingabe genommen, sonst hätte das Skript ihn per `shutil.copy` (ohne Clone) echt kopiert. Die Daten stammen aus dem RomFS (Schritt 5). Ursache nicht geklärt.
- Die Skript-Schwächen (Dateiendung per `split('.')[1]`) wurden nicht ausgelöst: Es gibt keine Dateien ohne Punkt und keine binären `.asset`/`.prefab`.
- Die Ordner `Scripts`, `Plugins`, `Shader` des Exports bleiben außen vor (vom Skript so vorgesehen). `.unity` wird nicht ersetzt.
- Im Projektstamm liegt eine `.DS_Store` aus dem Klon, harmlos.

## Statische Prüfung

- **GUIDs:** In 4503 `.meta`-Dateien definierte GUIDs gegen alle Verweise in `.asset`, `.prefab`, `.unity`, `.mat` (ohne Scripts, Wwise, Plugins, StreamingAssets). 35 unaufgelöste GUIDs:
  - TextMeshPro-Skripte und -Shader (z. B. TMP_FontAsset, TMP_Settings, TMP_SDF-Material-Shader) und UnityEngine.UI (`EventSystem`, `StandaloneInputModule`): kommen aus den Paketen `textmeshpro` und `ugui`, nach dem Paketimport erwartbar.
  - Szenen-GUIDs in `SceneDatabase.asset`: andere Szenen sind nicht im Projekt (nur `level0`).
  - `0000…e000…`/`f000…`: Unity-interne Ressourcen.
  - `level0.unity` selbst hat keine fehlenden Projekt-GUIDs.
  Dass die per Skript ersetzten Spiel-GUIDs (GameManager, StartupSettings usw.) alle aufgelöst sind, spricht für ein funktionierendes Mapping.
- **Pakete:** `Packages/manifest.json` hat 6 Registry-Pakete, die nicht im Editor stecken: `textmeshpro` 2.1.6, `timeline` 1.2.18, `test-framework` 1.1.24, `ide.rider` 1.2.1, `ide.vscode` 1.2.3 und (über die Lock-Datei) `ext.nunit` 1.0.6. Alle Modul-Pakete und `ugui` sind im Editor (`BuiltInPackages`) enthalten. Offline allein reicht es also **nicht**: Das erste Öffnen braucht Netz (`packages.unity.com` war per HEAD erreichbar, HTTP 200). Einen lokalen Paketcache haben wir nicht geprüft, um nicht außerhalb des Repos zu suchen.
- Eine Kompilierung ist statisch nicht prüfbar (ca. 3800 Skripte, viele Platzhalter).

## Bekannte Lücken

1. **B1:** `AssetBundles/Editor` ist leer. Der Editorpfad des `AssetManager` und der `EffectManager` suchen dort `fxparticle`/`shaders`. Zu erwarten sind Fehler in der Konsole beim Laden von Effekten und Materialien sowie rosa oder fehlende Shader. Das Projekt sollte sich trotzdem öffnen lassen (nicht belegt).
2. Wwise-Soundbanks sind Switch-Format (nur umbenannt). Ton ist wahrscheinlich nicht abspielbar, fürs Öffnen irrelevant.
3. TextMeshPro: Das TMP-Essentials-Material-Set kommt erst mit dem Paketimport. Beim ersten Öffnen eventuell „Import TMP Essentials“ bestätigen, falls Unity fragt (Hinweis: dieser Import legt Dateien unter `Assets/TextMesh Pro` an, kann also mit den verschobenen Dateien kollidieren).
4. `StreamingAssets` enthält 18000 Dateien. Unity legt dafür beim Öffnen `.meta`-Dateien an und importiert zum Beispiel Filme. Das kann den ersten Start deutlich verlängern und den `Library`-Ordner aufblähen. Die `.meta`-Dateien entstehen dabei im Klon-Ziel und verändern das RomFS nicht.
5. Mac statt Windows: Die Windows-Wwise-Plugins liegen im Projekt, der Mac-Editor nutzt aber die macOS-Plugins.

## Öffnen (vom Nutzer auszuführen)

```
open -n <UNITY_APP> --args -projectPath <REPO_ROOT>/work/opendpr-project
```

Danach `Assets/level0.unity` von Hand öffnen (keine Szene in den Build-Einstellungen).

## Testergebnis im Unity-Editor (2019.4.27f1, Rosetta, 2026-10-18)
- Das Projekt öffnet, kompiliert fehlerfrei (`Assembly-CSharp.dll` in ca. 12 s) und löst die Pakete auf.
- `level0.unity` zeigt beim Start nur Schwarz. Der Log zeigt zwei Abbrüche beim Boot:
  1. `NullReferenceException` in `GameManager.OnetimeInitializeOperation` (`GameManager.cs:249`): `UIManager.Instance` ist `null`. Ursache offen.
  2. Das Bundle `shaders` fehlt in `AssetBundles/Editor` (Blocker B1): `AssetBundle.LoadFromFile` liefert `null`, danach `NullReferenceException` in `AssetManager.LoadAssetBundle`.
- Offen: Ob die Switch-Bundles aus dem Dump im Mac-Editor ladbar sind, und warum `UIManager.Instance` fehlt.
- Einschätzung: opendpr taugt als Referenz (Klassen, Boot-Ablauf), ist aber auf dem Mac nicht ohne Weiteres lauffähig.
