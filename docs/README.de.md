# Dokumentation: Einstieg

Stand 2026-10-19. Zum Weitermachen: `../todo/neustart.md` (Todos, Kurzstand, Fundstellen). Zuerst `arbeitsstand-2026-10-19.md` lesen (Gesamtbild), dann `betriebshandbuch.md` (Regeln, Befehle, Agenten-Stand), dann nach Thema.

## Wo anfangen
| Frage | Dokument |
|---|---|
| Wo stehen wir, was fehlt? | `arbeitsstand-2026-10-19.md` |
| Regeln, Befehle, Spielstand-Verteilung, Agenten und Todos, unbelegte Annahmen, Wiederaufnahme | `betriebshandbuch.md` |
| Warum Rekompilation, was wurde entschieden? | `architektur-entscheidung.md` (Entscheidungen 1–4), `kernziel.md` |
| Wie baue ich die App? | `BUILD.de.md`, `recomp-macapp.md` |

## Rekompilation (aktiver Strang)
`recomp-machbarkeit.md` (Spike 1, LAS-Analyse) → `recomp-spike-2.md` (Exceptions, GC, Speicher, Entscheidungsvorlage) → `recomp-gate1.md` (Boot bis nnMain) → `recomp-gate2.md` (Grafik, Film, Spielstand, Stadt) → `recomp-macapp.md` (BDSP.app) → `recomp-ios.md` (iPad) → `recomp-qa.md` (Testläufe) → `recomp-vulkan.md` (Linux/Vulkan) → `recomp-linux.md` (Build-Farm) → `recomp-diff.md` (Bitgenauigkeit) → `recomp-referenzen.md`, `referenz-las-shader.md`.

## Shader, Texturen, Video, Wasser
`shader-translator.md`, `shader-inventar.md`, `shader-harness.md`, `shader-globals.md`, `wasser.md`, `video-umwandlung.md`, `render-treue.md`, `shader-audio-machbarkeit.md`.

## Ton der nativen Rekompilation
[recomp-audio.md](recomp-audio.md): tatsächlich genutzte Dienste, PCM-Ausgabe auf
macOS und iPadOS, Messwerte und Hörproben, verbleibende Prüfungen.

## App-Symbole
[recomp-icons.md](recomp-icons.md): Originalicons aus dem eigenen Dump,
Sprachvarianten, gespeicherte Auswahl und deterministische Apple-Gestaltung.

## Daten, Saves, Analyse
`extraktion.md`, `daten-inventar.md`, `masterdata.md`, `save-format.md`, `save-spec-entwurf.md`, `save-validator.md`, `save-kompatibilitaet.md`, `spielcode-inventar.md`, `ios-speicher-entitlements.md`, `ipad-messung-1.md`.

## Spezifikationen des Originalverhaltens (aus dem Unity-Zweig, weiter als Referenz nutzbar)
Kampf: `kampf-spezifikation-1…7.md`, `kampf-handler-liste.md`. Pokémon: `pokepara-spezifikation.md`. Events: `evscript-spezifikation.md`. Text: `lokalisierung.md`. Eingabe: `eingabe.md`.

## Entfernt (Unity-Rebuild, Entscheidung 4)
Die Unity-Dokumente (Machbarkeits- und Bauberichte, UI-, Szenen- und Sichtprüfungs-Notizen, Nachtberichte, die alte Bauanleitung und Pipeline-Beschreibung, u. a. `bauen.md`, `build-pipeline.md`, `opendpr-*.md`, `sichtpruefung-1…3.md`, `ui-spezifikation-1…3.md`, `spielkern-1…2.md`) wurden aus `main` entfernt. Sie stehen im Git-Verlauf und im Branch `unity`.

Die verbleibenden Spezifikationen (Kampf, Pokémon, Events, Text, Saves) nennen Unity-Skripte (`battle_oracle*`, `evscript_stats`, `data_inventory`, `il2cpp_lookup`, `assetripper_export`, die `visual_*`- und `ui_*`-Werkzeuge u. a.) und `work/`-Ordner, die es auf `main` nicht mehr gibt. Die Skripte stehen im Git-Verlauf und im Branch `unity`.
