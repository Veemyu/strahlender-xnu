# Build-Pipeline: Stufen, Marker und Werkzeuge

Einstiegspunkt ist `scripts/build_all.sh` (bash 3.2-kompatibel). Hilfslogik: `scripts/build_helpers.py` (Entschlüsselung, Manifest) und `scripts/build_stages.py` (Stufenauswahl, Marker mit Eingabe-Hashes, Preflight, Editor-Erkennung). Die Nutzeranleitung „NSP/XCI angeben, App erhalten“ steht in `docs/bauen.md`; dieses Dokument beschreibt die Technik.

Stufen in fester Reihenfolge: `tools`, `extract`, `il2cpp`, `masterdata`, `shaders`, `video`, `audio` (Platzhalter), `assets`, `unity-build`, `deploy`. Vor den Stufen läuft ein Preflight. Stand der Umsetzung: alle Stufen sind im Skript vorhanden; `audio` meldet „nicht implementiert“. Getestet sind Dry-run, `extract` (früherer Lauf, siehe unten), `il2cpp`, `masterdata`, `video` (Stichprobe), `shaders` (Stichprobe), `assets` und die Editor-Erkennung; der echte Unity-Build und der iOS-Deploy wurden in diesem Auftrag bewusst **nicht** ausgeführt.

## Aufruf

```
scripts/build_all.sh all --xci <x.xci> --nsp <update.nsp> --keys <Ordner> [--target macos|ios|all]
scripts/build_all.sh --dry-run all --xci … --keys …       # Plan, Marker-Status, Kommandos; ändert nichts
scripts/build_all.sh --from masterdata --to video
scripts/build_all.sh --only shaders,video
scripts/build_all.sh preflight
```

| Option | Bedeutung |
|---|---|
| `--xci`, `--nsp`, `--keys`, `--prod-keys`, `--title-keys` | Eingaben für `extract` (NSP optional; `title.keys` nur Rückfall). Nach einem erfolgreichen `extract` ist `--xci` nicht mehr nötig. |
| `--work` | Arbeitsordner, Standard **`work/`** (früher `work/build`). Dort erwarten auch die übrigen Skripte `exefs/`, `romfs/`, `il2cpp/`, `masterdata/`. |
| `--target` | `macos`, `ios`, `all` (Standard) für `unity-build` und `deploy`. |
| `--dry-run` | Nichts ausführen, schreiben oder installieren; Kommandos mit `[dry-run]` anzeigen. |
| `--from`, `--to`, `--only` | Bereich bzw. genaue Auswahl der Stufen (`--only` nicht mit `--from/--to` kombinierbar). `unity` und `xcode` sind Kurzformen. |
| `--force` | Gewählte Stufen neu erzeugen, auch wenn der Marker passt. |
| `--no-preflight`, `--min-free-gb N` | Preflight auslassen bzw. Mindestplatz ändern (Standard 60). |
| `--keep-nca` | Entpackte NCAs (mehrere GB) behalten. |
| `--video-profile`, `--movie-src` | `h265-crf18` (Standard) oder `h265-crf14`; abweichende Videoquelle (Stichproben, ohne Marker). |
| `--shaders-into-unity`, `--shader-only NAME` | Shader nach `unity/Assets/GameData/Shaders` statt `work/build/shaders`; nur ein Shader (Test, ohne Marker). |
| `--launch` | iOS-App nach der Installation starten (Standard: nicht starten). |

Umgebungsvariablen: `TOOLS_DIR` (Standard `tools/`), `MIN_FREE_GB` (Reserve in `extract`, Standard 25), `PREFLIGHT_MIN_FREE_GB`, `UNITY_EDITOR_ROOT`, `DEVELOPER_DIR`, `TEAM_ID`, `SHADER_USED` (JSON der benutzten Keyword-Mengen), `ASSETS_DEST` (gitignorierter Zielordner der Stufe `assets`), `XNU_UNITY_DRIVER=cli|editor|auto`, `XNU_LOCAL_ENV` (statt `work/local.env`).

## Preflight

Nur Prüfung, nie Installation, nie `sudo`. Geprüft wird, was die gewählten Stufen brauchen:

- **Plattenplatz ≥ 60 GB** frei (bei allen Stufen außer `tools`/`audio`); knapper Platz → Exit-Code 8 und Hinweis auf `--min-free-gb`.
- `tools`: git, make, cc. `extract`: `tools/hactool/hactool` (oder wird von `tools` gebaut). `il2cpp`: `dotnet` ≥ 8 und `tools/il2cppdumper-bin/Il2CppDumper.dll`. `masterdata`/`shaders`: `tools/pydeps/UnityPy`; `shaders`: make, cc. `video`: `ffmpeg` mit `libx265`.
- `unity-build`: Editor **6000.3.26f1**, Modul Mac Build Support (IL2CPP, arm64) und/oder iOS Build Support je nach `--target`, `unity`-CLI (nur Hinweis; Rückfall: Editor direkt im Batchmodus). `unity-build`/`deploy`: Xcode über `DEVELOPER_DIR` (`xcodebuild -version`).

Fehlendes erscheint als **Installationsliste** (Befehle zum selbst Ausführen). Exit-Code 4 bei fehlenden Werkzeugen, 8 bei zu wenig Platz. Im Dry-run endet ein nicht bestandener Preflight nicht; er zeigt, mit welchem Code der echte Lauf enden würde.

## Marker und Idempotenz

Nach Erfolg schreibt jede Stufe (außer `tools`, `audio`, Stichproben) `work/.stages/<Stufe>.json`: Schema, Stufe, Eingabe-Hash, Zeitstempel, Notizen (Zählwerte, Größen). Der Hash (`build_stages.py stage-hash`) umfasst je Stufe:

| Stufe | Eingabe-Hash aus |
|---|---|
| `il2cpp` | Kern von `manifest.json`, SHA-256 von `global-metadata.dat` und Il2CppDumper |
| `masterdata` | Manifest-Kern, `masterdata_export.py` |
| `shaders` | Manifest-Kern, alle `shader_*.py`/`shader_build.sh`, Quellen von `shader_translator/`, `SHADER_USED` |
| `video` | Manifest-Kern, `video_convert.sh`, Profil, Pfade und Größen der WebM-Quellen |
| `assets` | Manifest-Kern, Pfad/Größen aller Bundles, Marker von `video`, `masterdata`, `audio` |
| `unity-build` | Marker von `assets`/`shaders`, Inhalt von `Assets/Scripts`, `Assets/Scenes`, `ProjectSettings`, `Packages/manifest.json`, Ziel, Editorversion |
| `deploy` | Marker von `unity-build`, **Hash** der Team-ID, Ziel |

Stufen mit passendem Marker (und vorhandener Ausgabe) werden übersprungen; ein abgebrochener Lauf setzt dort fort, wo die Marker enden. `extract` behält sein eigenes `manifest.json`-Verfahren (siehe unten). Marker, Logs und Ausgaben enthalten nie Schlüssel; die Team-ID erscheint nirgends im Klartext.

## Stufen im Einzelnen

### `il2cpp`
`DOTNET_ROLL_FORWARD=Major dotnet tools/il2cppdumper-bin/Il2CppDumper.dll exefs/main global-metadata.dat work/il2cpp.stage`, danach Umbenennen nach `work/il2cpp/` (`dump.cs`, `script.json`, `il2cpp.h`, `DummyDll`, `stringliteral.json`). Der Dumper wirft am Ende ohne Terminal eine harmlose Ausnahme (Tastenabfrage); der Erfolg zählt am Ergebnis. Test: Lauf in einen Sandbox-Arbeitsordner (5,7 s) lieferte `dump.cs` und `script.json` **byte-identisch** zum früheren manuellen Lauf. Für die App selbst wird diese Stufe nicht gebraucht, nur für Analyse und den Abgleich der Stammdaten.

### `masterdata`
`masterdata_export.py export --set all --messages` und `counts` mit `PYTHONPATH=tools/pydeps` nach `work/masterdata/`. Test (Sandbox): 9 s, 129 Dateien, 104.649.610 Byte.

### `shaders`
Ruft `scripts/shader_build.sh` (`docs/shader-unity-integration.md`, Abschnitt 13.6). Standardausgabe `work/build/shaders/`; mit `--shaders-into-unity` nach `unity/Assets/GameData/Shaders` (nur gitignorierte Pfade). Exit 9 (16 Varianten mit Subgroup-Shuffle nicht verpackbar) ist eine Warnung. Weil die Hilfsskripte fest `work/romfs` lesen, legt die Stufe bei einem anderen `--work` einen Symlink dorthin an (oder bricht ab, wenn dort ein echter, anderer Ordner liegt). Test: Stichprobe `Custom/EffectCopyTexture` in 1,3 s. Ein Vollauf (6.804 Varianten) wurde hier nicht gestartet; ohne Strippen (`SHADER_USED`) sind Importzeit und Dateimenge im Unity-Projekt unverhältnismäßig, deshalb der Standard außerhalb des Projekts.

### `video`
`scripts/video_convert.sh <Movie> work/video <Profil>`: libx265, `hvc1`, kein H.264-Rückfall (`docs/video-umwandlung.md`). Das Skript ist über `video-manifest.json` selbst idempotent. Test: 4-s-Loop in 2,5 s, zweiter Lauf „unverändert, übersprungen“; ein Vollauf der 18 Videos wurde nicht gestartet (rund 10 Minuten Kodierzeit).

### `audio`
**Nicht implementiert.** Die Stufe meldet das deutlich und endet mit Erfolg ohne Marker. Vorgesehen ist ausschließlich Offline-Konvertierung der Wwise-Banks in Dateien (vgmstream); die Pipeline spielt nie Ton ab, die App ist standardmäßig stumm (`AudioSafety`).

### `assets`
Legt für den Player unter `unity/Assets/StreamingAssets/GameData/` (gitignoriert, per `git check-ignore` erzwungen; sonst Abbruch, Exit 2) bereit:

```
GameData/romfs/Data/StreamingAssets/AssetAssistant/   alle Bundles (APFS-Klon, sonst Kopie)
GameData/romfs/Data/StreamingAssets/Movie/            H.265-Videos aus work/video
GameData/masterdata/                                  JSON aus work/masterdata
```

Die Struktur entspricht `GameDataPaths` (`Root` = `StreamingAssets/GameData`, wenn `XNU_GAMEDATA` nicht gesetzt ist), sodass `AssetAssistant` und `masterdata` ohne Codeänderung der Verbraucher gefunden werden. Audio wird nicht kopiert. Anzahl und Größe werden gemessen und ausgegeben. Test (Sandbox, echte Bundles): 14.183 Dateien, 3,9 GB in 4 s ohne zusätzlichen Plattenverbrauch (Klon). Beim Unity-Build kopiert Unity die Daten danach einmal vollständig in das Paket (je Ziel ca. 4,4 GB plus Xcode-Derived-Data).

### `unity-build`
Je Ziel ein Batch-Build mit `Xnu.Build.Editor.BuildScript` (`BuildMacOS`, `BuildIos`):

- Treiber `cli`: `unity --non-interactive --no-banner build unity --target StandaloneOSX|iOS --execute-method … --output-path … --editor-version 6000.3.26f1 --architecture arm64 --allow-dirty-build --log-file …`.
- Treiber `editor` (Rückfall oder `XNU_UNITY_DRIVER=editor`): `Unity -batchmode -quit -projectPath unity -buildTarget … -executeMethod … -xnuOutput …`.
- Das Buildskript setzt vor dem Bauen: Scripting-Backend IL2CPP, **nur Metal** als Grafik-API, macOS-Architektur arm64 (per Reflection, fällt sonst auf den Editor-Standard zurück), iOS Gerätetyp iPhone und iPad. Szenen: aktivierte Szenen der Build Settings, sonst `FieldTest` und `InputTest` (Einstieg: erste Szene); `-xnuScenes a;b` überschreibt. Ausgabe: `-xnuOutput` bzw. `-buildOutput`. Im Batchmodus Exit-Code 1 bei Fehlern. Der iOS-Postbuild `IosPostBuild.cs` (Entitlement „Increased Memory Limit“) bleibt unverändert; er läuft nur, wenn der Build mit dem Ziel iOS gestartet wird, was beide Treiber (`--target iOS` bzw. `-buildTarget iOS`) tun. Das Skript prüft nach dem Bau, dass `Xnu.entitlements` im Xcode-Projekt liegt.
- Die Ausgabe wird vorher gelöscht (Unity würde sonst an alte Xcode-Projekte anhängen).
- **Editor offen:** Erkennt `build_stages.py editor-open` einen Unity-Prozess mit `-projectpath unity` (Import-Worker und Shader-Compiler zählen nicht), wird der Build nicht versucht. Das Skript nennt die PID und zwei Auswege, überspringt `unity-build` und `deploy` und endet mit Exit-Code **11**.
- Exit-Code 12: Unity-Build fehlgeschlagen (Auszug aus dem Unity-Log).

### `deploy`
- macOS: prüft `work/builds/macos/xnu.app` und `codesign --verify` (nur lesend); die App liegt bereits im Zielordner.
- iOS: ohne Team-ID (Umgebung `TEAM_ID` oder `work/local.env`) nur Hinweis „nur gebaut“. Mit Team-ID `scripts/ios_deploy.sh work/builds/ios/xnu --no-launch` (mit `--launch` startet die App). Kein iPad → übersprungen mit Hinweis; sonst Exit-Code 13.

## Stufe `tools`

Prüft oder erzeugt alles lokal, nichts wird systemweit installiert: hactool (Klon von github.com/SciresM/hactool, `config.mk`, `make`, Log `tools/hactool/build.log`), ffmpeg, python3 ≥ 3.9, Unity Hub CLI und Editor samt iOS-Modul, Xcode. Fehlt etwas, werden alle Lücken aufgelistet (Exit-Code 4).

## Stufe `extract`

1. Secure-Partition der XCI und Inhalt der NSP nach `<work>/nca-base` bzw. `<work>/nca-update` entpacken.
2. Jede NCA per `hactool -i` lesen; nur Content-Type, Titel-ID, Master-Key-Revision, Rights-ID und Größe werden übernommen. Das Base-Programm ist die größte Program-NCA der XCI, das Update-Programm die Program-NCA der NSP mit derselben Titel-ID.
3. Titlekey: Ticket (`.tik`) in der NSP parsen (Signaturtyp bestimmt die Offsets); bei einem Common-Ticket sind die ersten 16 Byte des Schlüsselblocks der Titlekey; sonst `title.keys`.
4. Update per `--basenca` anwenden; ExeFS und RomFS landen in `<work>/exefs` und `<work>/romfs`.
5. Version aus cnmt und `control.nacp`, dann `<work>/manifest.json` (Titel-ID, Versionen, Eingabegrößen, SHA-256/SHA-1 von `exefs/main`, SHA-256 der ExeFS-Dateien, Anzahl und Größe der RomFS-Dateien; kein Schlüsselmaterial).
6. Temporäre NCAs werden gelöscht (auch bei Fehlern), außer mit `--keep-nca`.

**Idempotenz:** Passt `manifest.json` zu den Eingabegrößen und den vorhandenen Ergebnissen, wird die Stufe übersprungen. **Schutz vor Schlüssel-Leaks:** hactool schreibt Schlüsselwerte nach stdout und stderr; das Skript verwirft beides. Der Titlekey liegt nur in einer Shell-Variable und wird hactool als Argument übergeben (kurzzeitig in der Prozessliste desselben Benutzers sichtbar). **Platz:** Es müssen nach dem Lauf mindestens `MIN_FREE_GB` frei bleiben (Bedarf ca. 2 × XCI + NSP, Spitze rund 12 GB).

## Exit-Codes

0 ok · 2 Aufruf · 3 Eingabedatei fehlt · 4 Werkzeug fehlt oder Build fehlgeschlagen · 5 hactool-Fehler · 6 Schlüssel/Titlekey · 7 passende NCA nicht gefunden · 8 zu wenig Platz · 9 Ergebnisprüfung fehlgeschlagen · 10 Voraussetzung/Vorstufe fehlt · **11 Unity-Editor hält das Projekt (Build übersprungen)** · 12 Unity-Build fehlgeschlagen · 13 iOS-Deploy fehlgeschlagen · 14 il2cpp/masterdata/shaders/video/assets fehlgeschlagen.

## Tests

- `python3 -m unittest discover -s scripts/tests` (alle grün). Neu: `test_build_stages.py` (Stufenauswahl, Marker, Hash-Abhängigkeiten, Team-ID nie im Klartext, Editor-Erkennung an Beispielausgaben von `ps`, Preflight mit simulierten Werkzeugen, Installationsliste ohne `sudo`) und `test_build_all.py` (Dry-run ohne Schreibzugriff, `--from/--to/--only`, Aufruffehler, Audio-Platzhalter, Assets-Stufe mit synthetischen Bundles: Kopie, Überspringen, Neu-Erzeugen, gitignore-Erzwingung). `test_build_helpers.py` deckt weiter Ticket-Parser, NCA-Auswahl und Manifest ab.
- Das C#-Buildskript wurde ohne Editorstart gegen die Unity-6000.3.26f1-Assemblies **übersetzt** (0 Fehler); ausgeführt wurde es nicht.
- `bash -n scripts/build_all.sh` ist sauber; `shellcheck` ist hier nicht installiert.

## Testergebnis `extract` (Stand 2026-10-18, macOS arm64)

Lauf in ein neues Verzeichnis (inzwischen gelöscht): `tools` unter 1 s; `extract` komplett 31 s und 34 s; zweiter Aufruf mit passendem Manifest 0,3 s (übersprungen). Fehlerfälle: fehlende XCI/Keys Exit 3, fehlender Parameter Exit 2, leere Keys Exit 6. Vergleich mit dem manuellen Stand: `exefs/main` und alle fünf ExeFS-Dateien identisch; RomFS byte-identisch bis auf sechs `.DS_Store`-Dateien. Ermittelte Version: Titelversion 393216, Anzeigeversion 1.3.0.

## Offene Punkte

- Voller Unity-Build mit Bundles und iOS-Deploy: nicht ausgeführt (Auftrag: nur Dry-run und Review). Erst dann ist die Szenenliste (`FieldTest`, `InputTest` als Rückfall) gegen eine echte Startszene zu ersetzen.
- Auf dieser Entwicklungsmaschine liegt der freie Platz (≈ 41 GB) unter dem Preflight-Mindestwert von 60 GB; der echte Gesamtlauf braucht dort `--min-free-gb` oder mehr Platz.
- `audio` fehlt; Shader-Strippen (`SHADER_USED`) fehlt, daher Shader standardmäßig außerhalb des Unity-Projekts.
