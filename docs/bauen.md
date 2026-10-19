# Bauen: von der eigenen NSP/XCI zur App

Dieses Repository enthält nur eigenen Code, Skripte und Doku. Alles Fremde (Texturen, Modelle, Stammdaten, Videos, Shader-Wrapper) entsteht lokal aus **deiner eigenen** Kopie von Pokémon Brilliant Diamond. Schlüssel, Dumps und Spieldaten gehören nie ins Repo; `work/`, `tools/`, `unity/Assets/StreamingAssets/` und `unity/Assets/GameData/` sind gitignoriert. Die gebauten Apps enthalten deine Spieldaten und sind nur für den persönlichen Gebrauch.

## Was du brauchst

- Mac mit Apple Silicon, macOS, rund **60 GB freier Platz** (Bundles, Kopien, Unity-Bibliothek, Builds).
- Deine Dateien: das Basisspiel als `.xci`, optional das Update als `.nsp`, und `prod.keys` (plus `title.keys`) aus deiner eigenen Konsole. Wo sie liegen, bestimmst du; sie werden nur gelesen.
- Werkzeuge: Xcode, Unity-Editor **6000.3.26f1** mit den Modulen „Mac Build Support (IL2CPP)“ und „iOS Build Support“, `ffmpeg` (mit libx265), `dotnet` (ab 8), Python 3.9 oder neuer. `hactool` baut das Skript selbst (Stufe `tools`).
- Nichts davon wird mit `sudo` installiert. Fehlt etwas, nennt der Preflight eine **Installationsliste** zum selbst Abarbeiten.

## Ein Befehl

```sh
scripts/build_all.sh all --xci <Pfad/zum/Spiel.xci> --nsp <Pfad/zum/Update.nsp> --keys <Ordner/mit/prod.keys> --target all
```

`--target macos`, `ios` oder `all` (Standard) wählt, was Unity baut. Ein iPad wird nur bespielt, wenn eine Team-ID bekannt ist (siehe unten).

Erst ansehen, dann ausführen:

```sh
scripts/build_all.sh --dry-run all --xci <…> --nsp <…> --keys <…>
```

Der Dry-run prüft Voraussetzungen, zeigt je Stufe, ob sie übersprungen oder ausgeführt würde, und gibt die Kommandos aus. Er ändert nichts.

## Stufen

| Stufe | Tut | Ergebnis |
|---|---|---|
| `tools` | baut hactool lokal, prüft ffmpeg, Unity, Xcode | `tools/hactool` |
| `extract` | entpackt XCI/NSP, wendet das Update an | `work/exefs`, `work/romfs`, `work/manifest.json` |
| `il2cpp` | Il2CppDumper über `exefs/main` und `global-metadata.dat` | `work/il2cpp/` |
| `recomp` | **macOS-App aus der Rekompilation** (Hauptweg, siehe Abschnitt unten): Generator → C → Übersetzen → Laufzeit/Metal → `BDSP.app`, RomFS nach Application Support | `work/builds/macos-recomp/BDSP.app` |
| `masterdata` | liest Stammdaten und Texte aus den Bundles | `work/masterdata/` |
| `shaders` | übersetzt die Maxwell-Shader, erzeugt Unity-Wrapper | `work/build/shaders/` (Standard) |
| `video` | WebM (VP8) nach H.265 (`.mp4`, `hvc1`) | `work/video/` |
| `audio` | **nicht implementiert** (Platzhalter, spielt nie etwas ab) | – |
| `assets` | legt Bundles, Videos, Stammdaten und Materialexporte für den Player bereit und setzt die Plattformkennung der Bundles (ohne sie lädt der Player nichts) | `unity/Assets/StreamingAssets/GameData/` |
| `unity-build` | baut macOS und iOS im Batchmodus (IL2CPP, arm64, Metal) | `work/builds/macos/xnu.app`, `work/builds/ios/xnu/` |
| `deploy` | prüft die macOS-App; installiert auf ein angeschlossenes iPad | – |

Kurzformen: `unity` = `unity-build`, `xcode` = `deploy`.

## Teilschritte und Wiederaufnahme

```sh
scripts/build_all.sh --from masterdata --to video      # nur ein Bereich
scripts/build_all.sh --only shaders,video              # genau diese Stufen
scripts/build_all.sh preflight                         # nur Voraussetzungen prüfen
scripts/build_all.sh --only unity-build,deploy         # nach Schließen des Editors wiederholen
```

Jede Stufe schreibt nach Erfolg einen Marker `work/.stages/<Stufe>.json` mit dem Hash ihrer Eingaben (Manifest der Extraktion, Skripte, vorgelagerte Marker, Unity-Quellen). Ein erneuter Aufruf überspringt Stufen, deren Eingaben unverändert sind, und setzt dort fort, wo ein Lauf abgebrochen wurde. `--force` erzwingt Neuerzeugung der gewählten Stufen. Für `extract` genügt nach dem ersten Lauf ein Aufruf ohne `--xci`; das vorhandene Ergebnis wird weiterverwendet.

## macOS-App aus der Rekompilation (Stufe `recomp`)

Seit Entscheidung 3 (`docs/architektur-entscheidung.md`) ist die Rekompilation der Hauptweg: aus **deinem** Dump entsteht das Spiel als native arm64-App mit Metal, derzeit **ohne Ton** (Ton wird erforscht), ohne Netz. Die Stufe läuft nach `extract` (und `il2cpp`); Technik, Tastenbelegung, Spielstand und Messwerte stehen in `docs/recomp-macapp.md`.

```sh
scripts/build_all.sh --only recomp                  # nach extract; ohne --xci wird das vorhandene work/exefs, work/romfs benutzt
scripts/build_all.sh --dry-run --only recomp        # nur Plan, Preflight und Marker-Status
open work/builds/macos-recomp/BDSP.app
```

- **Zusätzlich nötig:** Homebrew-Pakete `llvm`, `sdl3`, `ffmpeg`, `pkg-config` (`brew install llvm sdl3 ffmpeg pkg-config`, `/opt/homebrew/opt/llvm/bin` vor `/usr/bin` im `PATH`), Xcode Command Line Tools, die Python-Pakete `capstone` und `unicorn` in `tools/pydeps` (`python3 -m pip install --target tools/pydeps capstone unicorn`) und der Klon `research/LASRecomp` (`git clone https://github.com/peiikai/LASRecomp research/LASRecomp`, MIT; liefert Generator-Werkzeuge und die NVN-Schicht, die das Skript zur Bauzeit nach `work/` kopiert und patcht). Der Preflight nennt Fehlendes mit der passenden Zeile.
- **Platz:** der Preflight verlangt **≥ 25 GB** frei (`--min-free-gb N` senkt das bewusst). Gemessen belegt die Stufe selbst nur rund 1,7 GB (C 1,0 GB, Objekte 0,3 GB, Programm 0,22 GB, App 0,36 GB, RomFS-Klon 0 GB; kurzzeitig +1 GB Zwischenablage bei Wiederholung des Generators); der Rest ist Reserve für Compiler und Auslagerung.
- **Zeit:** kalt (Generator + Übersetzen + App) gemessen **rund 27,5 Minuten** bei Last 25 bis 50 (Generator 7,2 min, Übersetzen 19,8 min; Zahlen in `docs/recomp-macapp.md`), danach nur geänderte Teile: unveränderte Eingaben 0,4 s, Änderung an der Laufzeit 13 bis 50 s, an einer Generator-Eingabe nur die geänderten C-Dateien. Parallelität höchstens 4 Compiler (`--recomp-jobs N`), Ausreißer-Dateien (eine Funktion, mehr als 300 KB C) werden mit `-O0` übersetzt (`--recomp-o0-kb N`).
- **Idempotenz:** Teilmarker `work/.stages/recomp-gen.json` und `recomp-obj.json` plus der Stufenmarker `recomp.json` (Hash aus den Modulen des Dumps, Generator, Laufzeitquellen, Optionen). Zweiter Aufruf ohne Änderung: „Marker passt, übersprungen“. `--force` erzeugt alles neu.
- **Signatur:** ad hoc (`codesign -s -`), ohne Entwicklerkonto startbar; beim ersten Start aus dem Finder ggf. Rechtsklick → Öffnen (Gatekeeper). `--hardened` signiert mit Hardened Runtime (Entitlement nur `disable-library-validation` für die gebündelten Bibliotheken); JIT wird **nicht** gebraucht, es gibt keine Sandbox und keine Netzrechte.
- **Daten:** die App liest das RomFS aus `~/Library/Application Support/dev.local.xnubdsp/romfs` (die Stufe legt dort einen APFS-Klon von `work/romfs` an, der keinen zusätzlichen Platz braucht; `--no-install-data` überspringt das), den Spielstand aus `…/save` und legt Shader-Cache und Bildschirmfotos unter `~/Library/Caches/dev.local.xnubdsp` ab. Alle Pfade sind über `config.ini` oder Umgebungsvariablen änderbar; nichts davon liegt im Repo.
- **Spielstand importieren:** Menü *Spiel → Spielstand importieren …*, per Ablegen von `SaveData.bin` (oder dem Ordner) auf das Fenster oder `BDSP.app/Contents/MacOS/BDSP --import-save <Pfad>`; der Stand wird vorher geprüft (Größe 979.108 Byte, MD5-Prüfsumme wie `scripts/bdsp_save.py`).
- **Fehlermeldungen:** Fehlt etwas, nennt das Skript es auf Deutsch mit dem nächsten Schritt (Exit-Codes: 4 Werkzeug/Bau, 8 Platz, 10 Voraussetzung/Vorstufe). Logs: `work/logs/recomp-compile.log`, `recomp-runtime.log`, `recomp-images.log`, Generator: `work/recomp/spike2/gen4_<Modul>.log`.

## Wenn der Unity-Editor offen ist

Hält ein Unity-Editor das Projekt `unity/`, kann kein Batch-Build laufen (Projektsperre). Das Skript erkennt das, nennt die PID und überspringt `unity-build` und `deploy`, statt zu scheitern. Der Lauf endet dann mit Exit-Code **11**. Editor schließen und `--only unity-build,deploy` wiederholen, oder im offenen Editor das Menü **Xnu > Build** benutzen (Ausgabe ebenfalls unter `work/builds/`).

## iPad / iPadOS

1. iPad per USB anschließen, entsperren, Entwicklermodus an, Entwicklerprofil vertrauen.
2. Team-ID bereitstellen: als Umgebungsvariable `TEAM_ID` oder als Zeile `TEAM_ID=<deine ID>` in `work/local.env` (gitignoriert). Die ID steht nie in `ProjectSettings`, Logs oder Markern (nur ein Hash).
3. `scripts/build_all.sh --only deploy --target ios` baut mit Xcode und installiert. Mit `--launch` startet die App danach (sie ist derzeit stumm).
4. Spielstand aufs iPad: `scripts/ios_push_save.sh` (Datei nach `Documents/SaveData.bin`, Prüfsumme vor und nach, Import beim nächsten „Weiter“; `--pull` holt den Stand zurück). Der Build trägt `UIFileSharingEnabled` ein, der Documents-Ordner erscheint damit in der Dateien-App. Verfahren, Ursachen und Messwerte: `docs/ipad-durchstich-1.md`.

Ohne Team-ID bleibt es beim Xcode-Projekt unter `work/builds/ios/xnu/`; du kannst es in Xcode mit deinem eigenen Team öffnen. Ohne angeschlossenes iPad wird die Installation übersprungen. Ein kostenloses Apple-Team reicht; das Profil läuft nach 7 Tagen ab.

**Daten auf dem iPad (Stand 2026-10-19):** Für die iPad-Erprobung genügt eine Teilmenge der Bundles: `scripts/build_all.sh --only assets --target ios --bundle-subset scripts/subsets/ipad-start.txt` (fünf Bundles, 34,6 MB, mit Stammdaten 179 MB); danach in Unity `Xnu/Build/iOS und iPadOS (Xcode-Projekt)` und `scripts/ios_deploy.sh work/builds/ios/xnu --no-launch`. Start einer Szene ohne Eingabe: `xcrun devicectl device process launch --device <iPad> --terminate-existing --console --environment-variables '{"XNU_START_SCENE":"FieldTest2"}' dev.local.xnum0`. Die App startet in der Boot-Szene (Auswahlliste der Testszenen). **Texturen:** Bei `--target ios` wandelt die Stufe `assets` die BC/DXT-Texturen der Bundles automatisch nach ASTC 6×6 um (`scripts/texture_transcode.py`, `--texture-format 4x4|6x6|8x8|off`; Teilmenge: 24 s, Zone 422: Texturspeicher 46,4 → 25,5 MiB, Bundles auf der Platte rund 1,4-fach); Technik, Messungen und Grenzen in `docs/ios-texturen.md`. Ohne diesen Schritt bleibt die Karte auf iOS ohne Texturen.

## Daten im Player

Der Player lädt Bundles nur, wenn ihre Plattformkennung zum Ziel passt. Die Original-Bundles tragen die Kennung der Switch; die Stufe `assets` setzt sie je Ziel (`--bundle-platform`, Standard aus `--target`). Bei `--target all` entsteht nur ein Datensatz (macOS); für iOS die Stufe `assets` mit `--target ios` wiederholen. Einzelne Bundles prüfst du mit `PYTHONPATH=tools/pydeps python3 scripts/bundle_retarget.py info <Datei>`.

## Ausgabestruktur (alles gitignoriert)

```
work/
  manifest.json            Extraktion: Titel-ID, Version, Hashes, Größen (keine Schlüssel)
  exefs/  romfs/           entschlüsselter Inhalt
  il2cpp/  masterdata/  video/
  build/shaders/           erzeugte .shader-Wrapper
  builds/macos/xnu.app     macOS-App (arm64)
  builds/macos-recomp/BDSP.app   macOS-App aus der Rekompilation (Stufe recomp)
  recomp/                  Zwischenstände der Stufe recomp (gen4: erzeugtes C, obj4: Objekte, img_app, bdsp_app)
  builds/ios/xnu/          Xcode-Projekt für iOS/iPadOS
  logs/<Stufe>.log         Logs je Stufe
  .stages/<Stufe>.json     Marker mit Eingabe-Hash
unity/Assets/StreamingAssets/GameData/   was in den Player kopiert wird
```

Die App sucht ihre Daten zuerst über die Umgebungsvariable `XNU_GAMEDATA`, dann in `StreamingAssets/GameData` (vorgepackter Build), zuletzt im Anwendungsordner des Geräts.

## Bekannte Lücken

- `audio` ist nicht umgesetzt: die gebaute App enthält derzeit keinen Ton und bleibt stumm; Ton wird erforscht (Todo `rc-audio`).
- Die Shader-Wrapper landen standardmäßig nur in `work/build/shaders/`; ins Unity-Projekt (`--shaders-into-unity`) sollten sie erst nach dem Strippen auf die tatsächlich benutzten Varianten, sonst entstehen tausende Dateien (Stand: `docs/shader-unity-integration.md`, Abschnitt 13).
- Platz: 60 GB sind der Mindestwert des Preflights. Auf knapperen Laufwerken lässt er sich mit `--min-free-gb N` bewusst senken.
- Der erste echte Player-Build lief am 2026-10-19 im offenen Editor (Menü `Xnu/Build/…`) durch: macOS 202 s (kalt) bzw. 44 s, iOS 19 s, Installation 2 min 40 s; die Zone 422 lädt in beiden Apps in rund 1 s mit 30 FPS (`docs/player-build-1.md`). **Neu:** Umwandlung der BC-Texturen nach ASTC (`scripts/texture_transcode.py`, `docs/ios-texturen.md`), auf macOS mit geladenem Bundle geprüft, **auf dem iPad noch nicht**. **Offen:** Lauf der umgewandelten Texturen auf dem iPad, Bild-Sichtprüfung, volle Bundle-Menge auf dem iPad, Lauf des Batch-Treibers bei geschlossenem Editor.
