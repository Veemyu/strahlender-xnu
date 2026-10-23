# Dokumentation: Einstieg

Die Dokumentation ist englisch; Deutsch gibt es nur für die Haupt-README, diesen Einstieg und die Bauanleitung
([README.de.md](../README.de.md), [BUILD.de.md](BUILD.de.md)). Die englische Fassung dieses Index: [README.md](README.md).

## Ziel

Dieses Repository und dein eigenes Exemplar von Pokémon Brilliant Diamond (eine XCI, optional das Update als NSP, und deine
`prod.keys`) sollen genügen, um die App für macOS, iPadOS und (in Arbeit) Linux zu bauen. Das Repository enthält nur eigenen Code,
Skripte und Dokumentation: keine Spieldaten, Schlüssel, Saves oder erzeugten Code. Alles aus dem Spiel Abgeleitete entsteht lokal
unter `work/`, und eine gebaute App ist nur für den persönlichen Gebrauch. Der Code des Spiels selbst läuft, Logik, Oberfläche und
Saves verhalten sich also wie im Original.

## Wo anfangen

| Thema | Dokument |
|---|---|
| Bauen und Installieren (geführte Installer, Stufen, Optionen, Fehlerhilfe) | [BUILD.de.md](BUILD.de.md) |
| Wie die Rekompilation arbeitet (Generator, Ausnahmen, Speichermodell, Laufzeit, Grafik) | [architecture.md](architecture.md) (englisch) |
| Arbeitsregeln, Befehle, Tests, Test-Saves, was in `work/` liegt | [development.md](development.md) (englisch) |

## Plattformen, Rendering, Saves

| Thema | Dokument (englisch) |
|---|---|
| macOS-App | [recomp-macapp.md](recomp-macapp.md) |
| Bildschirmtastatur, Texteingabe, Test-Schalter | [input.md](input.md) (englisch) |
| iPadOS | [recomp-ios.md](recomp-ios.md) |
| Linux (Bau und Vulkan, in Arbeit) | [recomp-linux.md](recomp-linux.md) |
| Ton, App-Symbole | [recomp-audio.md](recomp-audio.md), [recomp-icons.md](recomp-icons.md) |
| Metal-Renderer: Fehlersuche, Leistung, Bildrate, Wasser | [rendering.md](rendering.md) |
| Shader-Übersetzer und Harness | [shaders.md](shaders.md) |
| Save-Format, Prüfskript, Ablageorte | [saves.md](saves.md) |
| QA-Läufe, Bitgenauigkeitstest, Änderungsverlauf | [recomp-qa.md](recomp-qa.md), [recomp-diff.md](recomp-diff.md), [changelog.md](changelog.md) |

## Entfernt

Der Unity-Nachbau ist eingestellt und liegt im Branch `unity`. Seine Dokumente, die frühen Machbarkeits-, Spike- und Gate-Berichte der
Rekompilation (verdichtet in [architecture.md](architecture.md)) und die Spezifikationen zum Nachbauen der Spiellogik (Kampf,
Pokémon-Parameter, Event-Skripte, Stammdaten, Lokalisierung, Eingabe) wurden aus `main` entfernt; sie stehen im Git-Verlauf und in
diesem Branch. Codekommentare und einzelne Notizen können noch Skripte oder `work/`-Ordner aus jener Zeit nennen.
