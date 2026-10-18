# opendpr als Machbarkeitstest (Stand: 2026-10-18)

Alles hier ist eine eigene Zusammenfassung. Aus `opendpr` und `Lumi_Small_Scripts` wurde nichts ins Repo kopiert.
Beide Klone liegen nur lokal und gitignored unter `tools/opendpr` und `tools/Lumi_Small_Scripts`.
Beide Repos haben auf GitHub keine Lizenz (`gh repo view` liefert `licenseInfo: null`), also gelten alle Rechte als vorbehalten.
Das Skript-Repo gehört laut README-Link `SaltContainer/Lumi_Small_Scripts`, nicht TeamLumi.
Zum Lesen der AssetRipper-API liegt außerdem der Quellcode (Tag 1.1.8, Commit `97e8b07`) unter `tools/AssetRipper-src-1.1.8`.

## 1. Was opendpr ist

- Ein rekonstruiertes Unity-Projekt für BDSP (Editor 2019.4.27f1, Changeset `23dc10685eb4`), keine echte Decompilation.
- Im Repo liegen: ca. 3800 handgeschriebene C#-Dateien (ca. 307.000 Zeilen, 37 MB) unter `Assets/Scripts`, die Wwise-Integration (2019.2.4, 139 MB, mit Mac- und Windows-Plugins), DOTween (Plugins), `ProjectSettings` und `Packages` (TextMeshPro 2.1.6, Timeline, ugui, Standardmodule) sowie das Wwise-Projekt `Dpr_WwiseProject`.
- Spieldaten und Assets liegen **nicht** im Repo. Sie müssen aus dem eigenen Dump erzeugt werden.
- Viele Methoden sind noch Platzhalter (ca. 4300 Mal `return default;`). Ein Start des Editors zeigt also höchstens, dass das Gerüst läuft, nicht ein spielbares Spiel.
- Das Projekt hat keine Szene in den Build-Einstellungen. Die Szene `level0.unity` muss man von Hand öffnen.
- Offene Issues: #2 (README sei unklar zur Ordnerstruktur und zu `TextMesh Pro`), #1 (fehlende Mesh-Assets). Zu den Windows-Bundles gibt es keine Antwort.
- Die README erklärt, dass keine generative KI genutzt wurde, und rät anderen Projekten davon ab. Das ist eine Haltung, keine Lizenzbedingung.

## 2. Ablauf bis zum öffnenbaren Projekt

Status: ✅ haben wir, ⚠️ unsicher, ❌ fehlt.

| # | Schritt | Aus unserem Dump | Status |
|---|---|---|---|
| 0 | Repos klonen | – | ✅ erledigt |
| 1 | AssetRipper 1.1.8 auf RomFS + ExeFS, StreamingAssets überspringen | `work/exefs/main`, `work/romfs/Data` (inkl. `Managed/Metadata/global-metadata.dat`) | ✅ Eingabe vollständig, Export noch nicht gelaufen |
| 2 | Python-Skript `fix_pathids.py` | Export-Ordner `Assets` als `input/` | ⚠️ Struktur der Eingabe ist in der README nicht beschrieben |
| 3 | Von-Hand-Schritte (löschen, verschieben, Assembly-Name ersetzen) | Ergebnis aus Schritt 2 | ⚠️ |
| 4 | Ordner `AssetBundles/Editor` mit Windows-Bundles `fxparticle` und `shaders` | nur die Switch-Versionen | ❌ **Blocker B1** |
| 5 | StreamingAssets aus dem RomFS nach `Assets/StreamingAssets` kopieren | `work/romfs/Data/StreamingAssets` (4,7 GB) | ✅ |
| 6 | `GeneratedSoundBanks/Switch` in `.../Windows` umbenennen | vorhanden (427 MB) | ✅ |
| 7 | Unity 2019.4.27f1 öffnen, Packages auflösen, Szene wählen | – | ⚠️ siehe Abschnitt 5 |

### 2a. AssetRipper-Automatisierung (aus dem 1.1.8-Quellcode gelesen)

Start: `tools/AssetRipper-1.1.8/AssetRipper.GUI.Free --port 8765 --launch-browser false --log true --log-path <Datei>`.
Die Datei ist eine arm64-Mach-O-Binärdatei. Der Server lauscht nur auf `127.0.0.1`.

| Zweck | Aufruf (Formular `application/x-www-form-urlencoded`) |
|---|---|
| Einstellungen setzen | `POST /Settings/Update` mit `ScriptContentLevel=Level2`, `ScriptExportMode=Hybrid`, `ScriptLanguageVersion=AutoSafe`, `SpriteExportMode=Texture2D`, `IgnoreStreamingAssets=` |
| Eingabe laden | `POST /LoadFolder` mit `Path=<Ordner mit exefs/ und romfs/Data>` |
| Exportieren | `POST /Export/UnityProject` mit `Path=<Zielordner>` |
| Zurücksetzen | `POST /Reset` |
| API-Doku | `GET /openapi.json` plus Swagger-Oberfläche (Route `/swagger`, Standard von `UseSwaggerUI`) |

Wichtige Eigenheiten, die im Code stehen:

- Bei `/Settings/Update` werden alle Checkboxen auf false gesetzt, deren Schlüssel nicht im Formular steht. „Skip StreamingAssets“ ist die Checkbox `IgnoreStreamingAssets`. Der Wert darf leer sein, nur der Schlüssel zählt.
- Die Defaults sind schon Level 2, Hybrid und AutoSafe. Geändert werden müssen nur Sprite-Export (Default `Yaml`) und die StreamingAssets-Checkbox.
- Einstellungen lassen sich nur ändern, solange nichts geladen ist.
- Laden und Export laufen synchron. Die HTTP-Antwort kommt erst nach Abschluss, und zwar als 302-Redirect auf `/`.
- Fehler werden von einer Middleware verschluckt und ebenfalls als Redirect auf `/` beantwortet. Erfolg muss man also am Log und am Ausgabeordner prüfen.
- `Export/UnityProject` ruft `Directory.Delete(Path, true)` auf und legt den Ordner neu an. Der Zielordner muss vorher existieren, und sein Inhalt geht verloren.
- Die Ausgabe landet in `<Path>/ExportedProject/{Assets,ProjectSettings}` und `<Path>/AuxiliaryFiles`.
- Die Switch-Erkennung (`SwitchGameStructure`) erwartet einen Ordner mit den Unterordnern `exefs` (Datei `main`) und `romfs/Data`. Unser `work/` erfüllt das direkt, es braucht keine Kopie.
- Bei IL2CPP und Level 2 haben die exportierten Skripte leere Methodenrümpfe (Kommentar im Enum `ScriptContentLevel`). opendpr verwendet die gerippten Skripte offenbar auch gar nicht, denn das Python-Skript überspringt `Scripts`, `Plugins` und `Shader`.
- Nicht verifiziert: ob Cpp2IL in AssetRipper 1.1.8 Metadata v24.4 (laut unserem Il2CppDumper-Lauf) problemlos liest. Die opendpr-Autoren behaupten es für dieselbe Unity-Version. Unsere Bundles tragen ebenfalls `2019.4.27f1` im Header.

Vorbereitet ist `scripts/assetripper_export.py` (reine Standardbibliothek, mit `--dry-run`, nicht ausgeführt). Es prüft vorab:

- Ghidra-PID (Default 4461) läuft nicht mehr,
- Eingabedateien sind vorhanden,
- das Ziel liegt unter `work/` und ist leer,
- mindestens 5 GB sind frei.

Danach startet es AssetRipper, setzt die Einstellungen, lädt und exportiert. Anschließend prüft es im Konsolen-Log, ob die Einstellungen angekommen sind und der Export fertig ist, und beendet AssetRipper wieder.
Ausgabe: `work/ripper/out/ExportedProject/`, Logs: `work/ripper/assetripper*.log`.
Es ist ungetestet, die Syntax und der Dry-Run sind aber geprüft.
Hinweis: Ghidra (PID 4461) lief beim Schreiben dieses Dokuments schon nicht mehr (`ps -p 4461` ohne Treffer).

Größenhinweis: Außerhalb von StreamingAssets enthält `work/romfs/Data` nur wenige MB (`resources.assets` ca. 1 MB, `.resS` 3 MB, `globalgamemanagers` unter 0,5 MB). Der Export sollte also klein und schnell sein. Die 3,9 GB Bundles unter `StreamingAssets/AssetAssistant` werden nicht gerippt, sondern nur kopiert.

### 2b. Das Python-Skript `asset_ripper_resources/fix_pathids.py`

- Reines Python 3 mit `os` und `shutil`. Es gibt keine `requirements`-Datei und keine Versionsangabe. Hier läuft Python 3.14.3, das sollte genügen.
- Eingabe: Ordner `input/` im aktuellen Arbeitsverzeichnis. Dort liegen die Unterordner des AssetRipper-Exports (nach meiner Lesart der Inhalt von `ExportedProject/Assets`; die README sagt nur „die Ordner, die AssetRipper erzeugt hat“).
- Ausgabe: Ordner `output/` mit derselben Struktur.
- Das Skript ersetzt in `.asset`- und `.prefab`-Dateien rund 40 Paare aus Script-GUID und FileID durch die GUIDs, die opendpr benutzt. Es betrifft TextMeshPro, DOTween, Wwise, die Startup-Einstellungen und eigene Spielklassen. Alle anderen Dateien werden unverändert kopiert.
- Szenen (`.unity`) bekommen keine Ersetzung. Das ist laut Skript so gewollt oder ein Versehen, das wir erst am echten Export sehen.
- `input/Scripts`, `input/Plugins` und `input/Shader` werden übersprungen.
- Schwächen im Skript (nicht verändern, nur beachten): Die Dateiendung wird mit `split('.')[1]` bestimmt. Dateien ohne Punkt lösen einen `IndexError` aus, bei mehreren Punkten wird die falsche Endung gelesen. Der Zielpfad entsteht mit `replace('input','output')` auf dem ganzen Pfad. Ein Ordnername mit „input“ würde also auch ersetzt.

### 2c. Von-Hand-Schritte laut README (in eigenen Worten)

1. Vier Dateien (und ihre `.meta`) aus `MonoBehaviour` löschen: `AkWwiseInitializationSettings`, `Mac`, `Switch`, `Windows`. Sie widersprechen den Wwise-Assets des Projekts.
2. Aus `Resources` die TextMeshPro-Teile (`fonts & materials`, `sprite assets`, `style sheets` und die beiden `LineBreaking …txt`) nach `TextMesh Pro/Resources/…` verschieben. Woher der Ordner `TextMesh Pro` kommt, sagt die README nicht (Issue #2). Er stammt vermutlich aus dem TMP-Essentials-Import des Unity-Pakets. Das ist nicht verifiziert.
3. `Scenes/level0.unity` direkt nach `Assets` legen. Alles Übrige kommt direkt nach `Assets/Resources`.
4. In `StartupSettings.asset` den Assembly-Verweis `AssetAssistant, Version=0.0.0.0,` durch `Assembly-CSharp, Version=1.6.28.12450,` ersetzen. Die Versionsnummer passt zu unserem Dump (Assembly-CSharp 1.6.28.12450, siehe `docs/extraktion.md`).
5. `AssetBundles/Editor` im Projektstamm anlegen und dort die Windows-Bundles `fxparticle` und `shaders` ablegen (Blocker B1).
6. Den Inhalt von `romfs/Data/StreamingAssets` nach `Assets/StreamingAssets` kopieren, dann `Audio/GeneratedSoundBanks/Switch` in `Windows` umbenennen.

## 3. Anforderungen aus unserem Dump

| Benötigt | Vorhanden | Anmerkung |
|---|---|---|
| `exefs/main` (NSO, IL2CPP) | ✅ 37,9 MB | wird von AssetRipper direkt gelesen |
| `romfs/Data` mit `globalgamemanagers`, `level0`, `resources.assets`, `sharedassets0.assets`, `Resources`, `Managed/Metadata/global-metadata.dat` | ✅ | |
| StreamingAssets (`AssetAssistant` 3,9 GB, `Audio` 427 MB, `Movie` 456 MB) | ✅ | Bundles tragen `UnityFS` mit Version `2019.4.27f1` |
| Switch-Bundles `AssetAssistant/Effects/fxparticle` (3,9 MB) und `AssetAssistant/Dpr/shaders` (6,7 MB) | ✅ | enthalten Switch-Shader, nicht Windows/Mac |
| Windows-Bundles `fxparticle` und `shaders` | ❌ | Blocker B1 |
| Wwise-Soundbanks für Windows | ⚠️ | wir haben nur `Switch` (427 MB). Das Umbenennen ändert das Format nicht. Ob das Wwise-Plugin sie am Mac abspielt, ist nicht verifiziert. Für das bloße Öffnen des Projekts ist es nicht nötig |
| Unity-Editor 2019.4.27f1 | ❌ | Abschnitt 5 |
| Netzzugang beim ersten Öffnen | – | der Package Manager löst die Pakete aus `Packages/manifest.json` auf |

## 4. Blocker und Risiken

**B1 – Windows-Bundles `fxparticle` und `shaders` (harter Blocker, Herkunft unklar).**

- Der Editor-Code (`AssetManager.editorPath`) liest im Editor die Bundles aus `<Ziel>/AssetBundles/Editor`. `EffectManager` verlangt `fxparticle` und `effect_common`.
- Die README erklärt weder, woher die „prepared bundles“ kommen, noch wie man sie baut. Die Issues geben ebenfalls nichts her. Im Repo liegen sie nicht (nur der Dateiname `fxparticle` kommt im Code vor).
- Meine Vermutung, ausdrücklich nicht belegt: Ein Switch-Shader enthält nur Binärcode für NVN und keinen Quelltext. Für Windows müsste man die Shader aus Quelltext neu bauen oder sie von Dritten (Lumi-Community) erhalten. Der Shader-Export von AssetRipper (Standard `Dummy`, alternativ `Yaml`) liefert keinen kompilierbaren Quelltext.
- Rechtlich: Die Shader sind urheberrechtlich geschützte Spielinhalte. Fertige Bundles aus fremder Hand wären Weitergabe von Nintendo-/Game-Freak-Material. Eigenbau aus dem eigenen Dump ist privat vermutlich unproblematisch. Das ist keine Rechtsberatung und nicht geprüft.
- Mac: Windows-Bundles enthalten Direct3D-Shaderblobs. Der Mac-Editor rendert über Metal. Ohne Metal-Varianten wären Materialien magentafarben oder unsichtbar. Ob die Bundles Metal-Varianten enthalten, ist unbekannt (nicht verifiziert). Auf dem Mac müsste man die Bundles selbst mit Ziel `StandaloneOSX` aus Shader-Quelltext bauen.
- Das Projekt lässt sich vermutlich auch ohne diese Bundles öffnen (Konsolenfehler, rosa Materialien). Das ist nicht belegt.

**B2 – Unity 2019.4 unter Rosetta auf macOS 26.** Siehe Abschnitt 5. Offiziell nicht unterstützt, das Ergebnis ist nur durch Ausprobieren zu klären.

**R1 – Struktur des Exports.** Die README ist laut Issue #2 unklar. Nach dem ersten Export prüfen wir die Ordner, bevor wir verschieben.

**R2 – Skript-Fehler** (Abschnitt 2b) bei unerwarteten Dateinamen.

**R3 – Cpp2IL und Metadata v24.4** (Abschnitt 2a). Falls AssetRipper die Skripte nicht lädt, erscheint im Log „Switching to the 'Unknown' scripting backend“. Dann fehlen die MonoBehaviour-Typen, und das Skript-GUID-Mapping greift nicht.

**R4 – Datenschutz/Urheberrecht.** Nichts aus `work/` oder aus dem gebauten Projekt gehört ins Git-Repo. `work/` und `tools/` sind bereits gitignored.

**R5 – Wenig freier Platz** (38 GB frei bei 91 % Belegung), siehe unten.

### Platzbedarf (grobe Schätzung)

| Posten | Größe |
|---|---|
| Unity-Editor-Paket (Download) | 2,15 GB (gemessen per HEAD-Anfrage) |
| Unity-Editor entpackt/installiert | ca. 6–8 GB (nicht verifiziert) |
| AssetRipper-Export | unter 0,2 GB (Schätzung aus der Eingabegröße) |
| opendpr-Kopie ohne Spieldaten | 0,22 GB |
| StreamingAssets im Projekt | 4,7 GB, mit APFS-Klon (`cp -c`, gleiche Partition) ca. 0 GB zusätzlich |
| Unity `Library` | 2–6 GB (nicht verifiziert, Schätzung) |
| **Summe** | **ca. 11–16 GB mit Klon, bis ca. 21 GB mit voller Kopie** |

Das Installer-Paket kann nach der Installation gelöscht werden. Das passt in die 38 GB, lässt aber nicht viel Luft.

## 5. Mac-Machbarkeit (Unity 2019.4.27f1)

Belegt:

- Die Version ist im Archiv vorhanden: Changeset **`23dc10685eb4`**, Hub-Link `unityhub://2019.4.27f1/23dc10685eb4` (https://unity.com/releases/editor/whats-new/2019.4.27f1, https://unity.com/releases/editor/archive).
- Direktlinks (per HEAD-Anfrage geprüft, HTTP 200):
  - `https://download.unity3d.com/download_unity/23dc10685eb4/MacEditorInstaller/Unity-2019.4.27f1.pkg` mit 2.148.927.494 Byte (ca. 2,0 GiB). Es ist ein Intel-(x64)-Editor, ein Apple-Silicon-Build existiert für 2019.4 nicht.
  - `.../MacEditorTargetInstaller/UnitySetup-Mac-IL2CPP-Support-for-Editor-2019.4.27f1.pkg` mit 142,7 MB.
  - `.../MacEditorTargetInstaller/UnitySetup-Windows-Mono-Support-for-Editor-2019.4.27f1.pkg` mit 111,5 MB.
  - Der DownloadAssistant `https://download.unity3d.com/download_unity/23dc10685eb4/UnityDownloadAssistant-2019.4.27f1.dmg` hat 0,5 MB.
- Module: Für das Öffnen und Ausführen im Editor sind keine Zusatzmodule nötig. Das Projekt nutzt den Editor mit Mono. „Mac IL2CPP Support“ und „Windows Build Support“ braucht man nur zum Bauen, nicht für diese Aufgabe.
- Das Unity-Handbuch 2019.4 nennt als Editor-Mindestanforderung für macOS Sierra 10.12.6+, x64 mit SSE2 und „Metal-capable Intel and AMD GPUs“. Der Editor sei „supported … running without emulation, container or compatibility layer“ (https://docs.unity3d.com/2019.4/Documentation/Manual/system-requirements.html). Rosetta ist also offiziell nicht abgedeckt.
- Rosetta ist hier installiert (Prozess `oahd` läuft, `/Library/Apple/usr/share/rosetta` vorhanden).
- Laut Unity-Dokumentation für Unity 6 wird Rosetta von Apple abgekündigt (https://docs.unity.com/en-us/engine/6000.0/manual/platform-specific/apple-mac/macos-requirements-and-compatibility). Langfristig ist der Intel-Editor damit auf neuen macOS-Versionen gefährdet.
- Im opendpr-Projekt ist `metalEditorSupport: 1` bereits gesetzt (`ProjectSettings/ProjectSettings.asset`). Die Wwise-Mac-Plugins sind x86_64-Bundles. Beides passt zu einem Rosetta-Editor.
- Unity Hub: Homebrew zeigt `unity-hub` 3.22.3 (nicht installiert).

Nicht verifiziert (nur Hinweise aus einer Websuche, Quellen nicht gelesen):

- Ob Hub 3.22.3 auf Apple Silicon den Intel-Editor 2019.4.27f1 zuverlässig installiert und startet.
- Ob der Editor unter macOS 26 abstürzt oder schwarze Fenster zeigt. Ein Forenthread nennt `metalEditorSupport: 1` als Abhilfe (https://discussions.unity.com/t/unity-editor-crashes-macos/757071, nicht abrufbar). Das ist hier ohnehin gesetzt.
- Die Größe des installierten Editors und der Library.

Lizenz/Login: Das muss der Nutzer selbst erledigen. Der Hub verlangt eine Unity-ID und eine Personal-Lizenz.
Ein Hub-Login ist keine Aktion für uns. Wir geben dazu keine Zugangsdaten an.

Fazit Mac: Der Editor sollte unter Rosetta starten, ist aber offiziell nicht unterstützt. Das ist ein Experiment, das ca. 2 GB Download kostet. Der wahrscheinliche Engpass sind die Shader (B1), nicht der Editor.

## 6. Befehlsliste für den Nutzer (ohne sudo)

Alle Befehle im Repo-Stamm `/Users/vee/Work/strahlender-xnu`.

```sh
# 0) Ghidra muss beendet sein (keine Ausgabe außer Kopfzeile = ok)
ps -p 4461

# 1) Export-Plan prüfen, dann ausführen (AssetRipper, ca. wenige Minuten, wenig RAM)
python3 scripts/assetripper_export.py --dry-run
python3 scripts/assetripper_export.py
ls work/ripper/out/ExportedProject/Assets

# 2) Projektordner anlegen (opendpr-Kopie, APFS-Klone sparen Platz)
mkdir -p work/dpr-prep work/dpr-project
cp -cR tools/opendpr/Assets tools/opendpr/Packages tools/opendpr/ProjectSettings tools/opendpr/Dpr_WwiseProject work/dpr-project/
cp -cR work/ripper/out/ExportedProject/Assets work/dpr-prep/input

# 3) Python-Skript aus dem Fremdrepo unverändert aus work/dpr-prep laufen lassen
cd work/dpr-prep && python3 ../../tools/Lumi_Small_Scripts/asset_ripper_resources/fix_pathids.py && cd ../..
ls work/dpr-prep/output

# 4) Von-Hand-Schritte (Struktur erst nach Schritt 3 prüfen!)
find work/dpr-prep/output -name StartupSettings.asset
#    dann die Löschungen und Verschiebungen aus Abschnitt 2c ausführen
#    und im StartupSettings.asset den Assembly-Namen ersetzen,
#    das Ergebnis nach work/dpr-project/Assets legen

# 5) StreamingAssets als APFS-Klon (kostet keinen zusätzlichen Platz) und Soundbank-Ordner umbenennen
cp -cR work/romfs/Data/StreamingAssets/. work/dpr-project/Assets/StreamingAssets/
mv work/dpr-project/Assets/StreamingAssets/Audio/GeneratedSoundBanks/Switch work/dpr-project/Assets/StreamingAssets/Audio/GeneratedSoundBanks/Windows

# 6) Unity-Hub installieren und den Editor über den Archiv-Link holen (Anmeldung durch den Nutzer)
brew install --cask unity-hub
open "unityhub://2019.4.27f1/23dc10685eb4"

# 7) Projekt in Hub über „Hinzufügen“ öffnen: work/dpr-project
#    Vor dem ersten Öffnen fehlt noch B1: work/dpr-project/AssetBundles/Editor
```

Alternative zum Hub ohne sudo (nicht verifiziert): Das Paket per `curl -L -O` laden und mit `pkgutil --expand-full <pkg> <Zielordner>` entpacken. Das Entpackte enthält die `Unity.app`, die man im Benutzerordner starten könnte.
Die Installation per `installer` verlangt dagegen Adminrechte.
Hinweis zu Schritt 5: `cp -c` funktioniert nur, wenn Quelle und Ziel auf derselben APFS-Partition liegen. Das trifft für `work/` zu.

## 7. Entscheidungsfrage

Wie weit wollen wir den Test treiben?

- **A (empfohlen, günstig):** Export und Aufbereitung jetzt machen und das Projekt ohne Windows-Shader-Bundles öffnen. Ziel: prüfen, ob Rosetta-Editor, Skriptgerüst und Ressourcen-Zuordnung laufen. Kosten: ca. 2 GB Download, ca. 10–15 GB Platz. Shader bleiben ungeklärt.
- **B:** Zusätzlich Zeit in die Shader-Frage stecken (B1), also Bundles aus Quelltext für Mac/Windows neu bauen. Das ist der Teil, der echten Aufwand und Unsicherheit trägt.
- **C:** Auf Unity verzichten und opendpr nur als Namens- und Strukturreferenz lesen. Wir bleiben beim IL2CPP-/Ghidra-Strang und sparen Platz und Zeit.

Mein Vorschlag: A, weil der AssetRipper-Teil nach Eingabegröße klein ist. Danach entscheiden wir zwischen B und C, sobald klar ist, ob der Editor unter Rosetta läuft.
