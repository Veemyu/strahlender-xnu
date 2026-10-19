# Dokumentation: Einstieg

Stand 2026-10-19. Zum Weitermachen: `../todo/neustart.md` (Todos, Kurzstand, Fundstellen). Zuerst `arbeitsstand-2026-10-19.md` lesen (Gesamtbild), dann `betriebshandbuch.md` (Regeln, Befehle, Agenten-Stand), dann nach Thema.

## Wo anfangen
| Frage | Dokument |
|---|---|
| Wo stehen wir, was fehlt? | `arbeitsstand-2026-10-19.md` |
| Regeln, Befehle, Spielstand-Verteilung, Agenten und Todos, unbelegte Annahmen, Wiederaufnahme | `betriebshandbuch.md` |
| Warum Rekompilation, was wurde entschieden? | `architektur-entscheidung.md` (Entscheidungen 1–4), `kernziel.md` |
| Wie baue ich die App? | `bauen.md`, `build-pipeline.md`, `recomp-macapp.md` |

## Rekompilation (aktiver Strang)
`recomp-machbarkeit.md` (Spike 1, LAS-Analyse) → `recomp-spike-2.md` (Exceptions, GC, Speicher, Entscheidungsvorlage) → `recomp-gate1.md` (Boot bis nnMain) → `recomp-gate2.md` (Grafik, Film, Spielstand, Stadt) → `recomp-macapp.md` (BDSP.app) → `recomp-ios.md` (iPad) → `recomp-qa.md` (Testläufe) → `recomp-vulkan.md` (Linux/Vulkan) → `recomp-ryzen.md` (Build-Farm) → `recomp-diff.md` (Bitgenauigkeit) → `recomp-referenzen.md`, `referenz-las-shader.md`.

## Shader, Texturen, Video, Wasser
`shader-translator.md`, `shader-inventar.md`, `shader-harness.md`, `shader-globals.md`, `wasser.md`, `ios-texturen.md`, `video-umwandlung.md`, `render-treue.md`, `shader-audio-machbarkeit.md`.

## Daten, Saves, Analyse
`extraktion.md`, `daten-inventar.md`, `bundle-katalog.md`, `masterdata.md`, `save-format.md`, `save-spec-entwurf.md`, `save-validator.md`, `save-kompatibilitaet.md`, `spielcode-inventar.md`, `cpp2il-bewertung.md`, `ios-speicher-entitlements.md`, `ipad-messung-1.md`, `ipad-durchstich-1.md`.

## Bildprüfung
`visuelle-pruefung.md` (Ryujinx-Referenz, Tasten-Spieler, Szenarien), `sichtpruefung-1…3.md` (Unity-Zeit).

## Spezifikationen des Originalverhaltens (aus dem Unity-Zweig, weiter als Referenz nutzbar)
Kampf: `kampf-spezifikation-1…7.md`, `kampf-handler-liste.md`. Pokémon: `pokepara-spezifikation.md`. Events: `evscript-spezifikation.md`, `spielkern-1…2.md`. UI/Text: `ui-spezifikation-1…3.md`, `lokalisierung.md`. Eingabe: `eingabe.md`.

## Deprecated (Unity-Rebuild, Entscheidung 4)
`m0-bundle-kompatibilitaet.md`, `unity6-tooling.md`, `unity-autopilot.md`, `player-build-1.md`, `feld-szene-1…2.md`, `vertikaler-durchstich-1.md`, `material-remap.md`, `shader-unity-integration.md`, `stubs-1.md`, `opendpr-*.md`, `arbeitsplan.md`, `nachtbericht.md`, `nachtbericht-2.md`. Nicht mehr gepflegt; siehe `unity/DEPRECATED.md`.
