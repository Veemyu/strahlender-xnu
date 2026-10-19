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
| `masterdata` | liest Stammdaten und Texte aus den Bundles | `work/masterdata/` |
| `shaders` | übersetzt die Maxwell-Shader, erzeugt Unity-Wrapper | `work/build/shaders/` (Standard) |
| `video` | WebM (VP8) nach H.265 (`.mp4`, `hvc1`) | `work/video/` |
| `audio` | **nicht implementiert** (Platzhalter, spielt nie etwas ab) | – |
| `assets` | legt Bundles, Videos und Stammdaten für den Player bereit | `unity/Assets/StreamingAssets/GameData/` |
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

## Wenn der Unity-Editor offen ist

Hält ein Unity-Editor das Projekt `unity/`, kann kein Batch-Build laufen (Projektsperre). Das Skript erkennt das, nennt die PID und überspringt `unity-build` und `deploy`, statt zu scheitern. Der Lauf endet dann mit Exit-Code **11**. Editor schließen und `--only unity-build,deploy` wiederholen, oder im offenen Editor das Menü **Xnu > Build** benutzen (Ausgabe ebenfalls unter `work/builds/`).

## iPad / iPadOS

1. iPad per USB anschließen, entsperren, Entwicklermodus an, Entwicklerprofil vertrauen.
2. Team-ID bereitstellen: als Umgebungsvariable `TEAM_ID` oder als Zeile `TEAM_ID=<deine ID>` in `work/local.env` (gitignoriert). Die ID steht nie in `ProjectSettings`, Logs oder Markern (nur ein Hash).
3. `scripts/build_all.sh --only deploy --target ios` baut mit Xcode und installiert. Mit `--launch` startet die App danach (sie ist standardmäßig stumm).

Ohne Team-ID bleibt es beim Xcode-Projekt unter `work/builds/ios/xnu/`; du kannst es in Xcode mit deinem eigenen Team öffnen. Ohne angeschlossenes iPad wird die Installation übersprungen. Ein kostenloses Apple-Team reicht; das Profil läuft nach 7 Tagen ab.

## Ausgabestruktur (alles gitignoriert)

```
work/
  manifest.json            Extraktion: Titel-ID, Version, Hashes, Größen (keine Schlüssel)
  exefs/  romfs/           entschlüsselter Inhalt
  il2cpp/  masterdata/  video/
  build/shaders/           erzeugte .shader-Wrapper
  builds/macos/xnu.app     macOS-App (arm64)
  builds/ios/xnu/          Xcode-Projekt für iOS/iPadOS
  logs/<Stufe>.log         Logs je Stufe
  .stages/<Stufe>.json     Marker mit Eingabe-Hash
unity/Assets/StreamingAssets/GameData/   was in den Player kopiert wird
```

Die App sucht ihre Daten zuerst über die Umgebungsvariable `XNU_GAMEDATA`, dann in `StreamingAssets/GameData` (vorgepackter Build), zuletzt im Anwendungsordner des Geräts.

## Bekannte Lücken

- `audio` ist nicht umgesetzt: die gebaute App enthält keinen Ton und bleibt stumm.
- Die Shader-Wrapper landen standardmäßig nur in `work/build/shaders/`; ins Unity-Projekt (`--shaders-into-unity`) sollten sie erst nach dem Strippen auf die tatsächlich benutzten Varianten, sonst entstehen tausende Dateien (Stand: `docs/shader-unity-integration.md`, Abschnitt 13).
- Platz: 60 GB sind der Mindestwert des Preflights. Auf knapperen Laufwerken lässt er sich mit `--min-free-gb N` bewusst senken.
- Der vollständige Unity-Build mit echten Bundles wurde noch nicht durchlaufen, nur Dry-run und Teilstufen; Details in `docs/build-pipeline.md`.
