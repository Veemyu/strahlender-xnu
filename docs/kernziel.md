# Kernziel (Vorgabe des Nutzers, 2026-10-18)

**Mit diesem Repository und einer eigenen NSP/XCI von Pokémon Brilliant Diamond / Shining Pearl lässt sich die komplette App für iOS, iPadOS und macOS bauen.** Ein Aufruf soll genügen, und das Repo enthält dafür nur eigenen Code, Skripte und Doku.

## Grundsätze
- Das Repo enthält **keine** Spieldaten, Keys, Dumps oder abgeleiteten Inhalte. Alles Fremde entsteht lokal beim Bauen aus den Dateien, die der Nutzer selbst bereitstellt.
- Der Nutzer liefert lokal: XCI (Basisspiel), NSP (Update) und `prod.keys`/`title.keys` aus seiner eigenen Konsole. Keys werden nie ins Repo oder in die App gepackt.
- **Die gebauten Apps enthalten die Inhalte des Nutzers** (Texturen, Modelle, Töne, Videos). Sie sind daher nur für den persönlichen Gebrauch gedacht und werden nicht weitergegeben. Weitergegeben wird nur das Repo.
- Alle Umwandlungen (z. B. Videoformat) sind **zusätzliche Build-Schritte** und ändern die Quelldaten nicht.

## Build-Pipeline (Ziel)
Einstiegspunkt: `scripts/build_all.sh all --xci <Datei> --nsp <Datei> --keys <Ordner> --target macos|ios|all` (Anleitung: `docs/bauen.md`, Technik: `docs/build-pipeline.md`; `--dry-run` zeigt vorab den Plan).

| Schritt | Inhalt | Stand |
|---|---|---|
| 1 Werkzeuge | hactool, Ghidra-freie Basis: nur was der Build braucht (hactool aus Quellcode, ffmpeg, Unity 6.3 LTS, Xcode) | Stufe `tools` und Preflight (Installationsliste ohne sudo) |
| 2 Entschlüsseln | XCI/NSP entpacken, Update anwenden: `work/exefs`, `work/romfs` | Stufe `extract` (getestet) |
| 3 Stammdaten | Bundles lesen, typisierte Daten erzeugen | Stufen `il2cpp`, `masterdata` (getestet) |
| 4 Assets | Bundles in das Unity-Projekt einbinden, Shader durch eigene ersetzen | Stufen `shaders` (Stichprobe), `assets` (getestet) |
| 5 Video | VP8-WebM nach H.265 (`ffmpeg`) umwandeln | Stufe `video` (Stichprobe getestet) |
| 6 Audio | Wwise-Banks/WEM offline in ein Format für Unity wandeln (vgmstream) | Platzhalter „nicht implementiert“ (`ap-audio`) |
| 7 Unity-Build (**deprecated, Entscheidung 4**) | IL2CPP-Player für macOS (arm64) und iOS/iPadOS (Xcode-Projekt) | Stufe `unity-build`: stillgelegt, nicht mehr gepflegt (`unity/DEPRECATED.md`) |
| 7b Rekompilation (Hauptweg seit Entscheidung 3) | macOS-App aus der Rekompilation: Generator → C → Übersetzen → Laufzeit/Metal → `BDSP.app` | Stufe `recomp` (getestet, Kaltbau 27,5 min; `docs/recomp-macapp.md`) |
| 8 Signieren/Installieren | Xcode mit eigenem Team, `scripts/recomp/ios/deploy_ios.sh` | Stufe `recomp` mit `--target ios` (Team-ID `TEAM_ID` oder `work/local.env`; ohne ID nur Build) |

## Videos (Entscheidungsvorschlag)
- 18 Dateien, VP8 in WebM (`docs/daten-inventar.md`). Ob Unitys VideoPlayer auf macOS und iOS VP8 abspielt, ist **ungeprüft**. Falls nicht, wandelt der Build sie um.
- Zielformat: **H.265 (HEVC, `hvc1`, `.mp4`)**, ausdrücklich ohne H.264-Fallback (Nutzerentscheidung: alle Zielgeräte dekodieren HEVC in Hardware, das ist hier eine Annahme und nicht gemessen). Eine Neukodierung einer bereits verlustbehafteten VP8-Quelle ist nie ganz verlustfrei. Ein echter Lossless-Modus wäre sehr groß. Praktisch: sehr hohe Qualität (CRF-Bereich), danach Größe und Bildvergleich messen.
- `ffmpeg 9.0.2` ist per Homebrew vorhanden.

## Auslieferungsform (Nutzervorgabe 2026-10-18)
- **Primär: vorgepacktes Binary.** Alles wird auf dem Entwicklungsrechner mit Unity und Xcode vorgebaut. Auf dem Zielgerät (iPad/Mac) muss nichts mehr importiert oder ausgewählt werden. Die Spieldaten (umgewandelte Bundles, Videos, Audio) liegen fertig in der App. Das passt zum Modell „selbst gebaut, nichts wird weitergegeben“.
- **Optional später: Core-App plus Import** (Erststart-Assistent, der eine XCI/NSP verarbeitet). Das spart Build-Zeit und App-Größe, ist aber mehr Arbeit auf dem Gerät (Entschlüsseln, Entpacken, Speicher).
- **Zu prüfen beim vorgepackten Weg** (nicht belegt): App-Größe von mehreren GB bei der Installation auf dem iPad per Xcode, Ladezeiten der Bundles aus dem App-Paket, Speicherplatz auf dem Gerät, Verhalten mit einem kostenlosen Team (Profil 7 Tage). Die Lesepfade im Code (`GameDataPaths`) bleiben konfigurierbar, damit beide Formen möglich sind.

## Rechtliche Einordnung
Das ist keine Rechtsberatung. Das Muster „Repo plus eigener Dump“ vermeidet die Weitergabe fremder Inhalte durch uns. Die gebauten Binaries sind ausdrücklich nicht zur Weitergabe bestimmt. Vor einer öffentlichen Veröffentlichung sollte die Rechtslage geklärt werden.
