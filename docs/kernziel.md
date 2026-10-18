# Kernziel (Vorgabe des Nutzers, 2026-10-18)

**Mit diesem Repository und einer eigenen NSP/XCI von Pokémon Brilliant Diamond / Shining Pearl lässt sich die komplette App für iOS, iPadOS und macOS bauen.** Ein Aufruf soll genügen, und das Repo enthält dafür nur eigenen Code, Skripte und Doku.

## Grundsätze
- Das Repo enthält **keine** Spieldaten, Keys, Dumps oder abgeleiteten Inhalte. Alles Fremde entsteht lokal beim Bauen aus den Dateien, die der Nutzer selbst bereitstellt.
- Der Nutzer liefert lokal: XCI (Basisspiel), NSP (Update) und `prod.keys`/`title.keys` aus seiner eigenen Konsole. Keys werden nie ins Repo oder in die App gepackt.
- **Die gebauten Apps enthalten die Inhalte des Nutzers** (Texturen, Modelle, Töne, Videos). Sie sind daher nur für den persönlichen Gebrauch gedacht und werden nicht weitergegeben. Weitergegeben wird nur das Repo.
- Alle Umwandlungen (z. B. Videoformat) sind **zusätzliche Build-Schritte** und ändern die Quelldaten nicht.

## Build-Pipeline (Ziel)
Einstiegspunkt (geplant): `scripts/build_all.sh --xci <Datei> --nsp <Datei> --keys <Ordner> --target macos|ios|all`.

| Schritt | Inhalt | Stand |
|---|---|---|
| 1 Werkzeuge | hactool, Ghidra-freie Basis: nur was der Build braucht (hactool aus Quellcode, ffmpeg, Unity 6.3 LTS, Xcode) | Teile vorhanden (`tools/`, Hub) |
| 2 Entschlüsseln | XCI/NSP entpacken, Update anwenden: `work/exefs`, `work/romfs` | manuell erledigt (docs/extraktion.md) |
| 3 Stammdaten | Bundles lesen, typisierte Daten erzeugen | in Arbeit (`ap-masterdata`) |
| 4 Assets | Bundles in das Unity-Projekt einbinden, Shader durch eigene ersetzen | geplant |
| 5 Video | VP8-WebM nach H.264 oder H.265 umwandeln (`ffmpeg`), nur falls VP8 auf Apple-Plattformen nicht abspielbar ist | geplant (`ap-cutscenes-video`) |
| 6 Audio | Wwise-Banks/WEM offline in ein Format für Unity wandeln (vgmstream) | geplant (`ap-audio`) |
| 7 Unity-Build | IL2CPP-Player für macOS (universell) und iOS/iPadOS (Xcode-Projekt) | Leerbuild getestet |
| 8 Signieren/Installieren | Xcode mit eigenem Team, `scripts/ios_deploy.sh` | getestet |

## Videos (Entscheidungsvorschlag)
- 18 Dateien, VP8 in WebM (`docs/daten-inventar.md`). Ob Unitys VideoPlayer auf macOS und iOS VP8 abspielt, ist **ungeprüft**. Falls nicht, wandelt der Build sie um.
- Zielformat: H.265 (HEVC) oder H.264, so verlustarm wie sinnvoll. Eine Neukodierung einer bereits verlustbehafteten VP8-Quelle ist nie ganz verlustfrei. Ein echter Lossless-Modus wäre sehr groß. Praktisch: sehr hohe Qualität (CRF-Bereich), danach Größe und Bildvergleich messen.
- `ffmpeg 9.0.2` ist per Homebrew vorhanden.

## Rechtliche Einordnung
Das ist keine Rechtsberatung. Das Muster „Repo plus eigener Dump“ vermeidet die Weitergabe fremder Inhalte durch uns. Die gebauten Binaries sind ausdrücklich nicht zur Weitergabe bestimmt. Vor einer öffentlichen Veröffentlichung sollte die Rechtslage geklärt werden.
