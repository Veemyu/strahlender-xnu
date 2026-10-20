**English version: [README.md](README.md)**

# strahlender-xnu

Statische Rekompilation des ARM64-Codes von Pokémon Brilliant Diamond (BDSP) für macOS und iPadOS, mit einem Vulkan-Weg für Linux (in Arbeit). Die Laufzeit (Kernel-SVCs, IPC-Dienste, Dateisystem, Grafik über Metal bzw. Vulkan) liegt in `scripts/recomp/rt-bdsp/`; sie enthält Teile aus LASRecomp (siehe unten).

Das Repository enthält **keine Spieldaten**, keine Schlüssel, keine Speicherstände und keinen erzeugten Code. Zum Bauen braucht man einen eigenen Dump des Spiels. Pokémon ist eine Marke von Nintendo, Game Freak und Creatures; dieses Projekt steht mit keiner dieser Firmen in Verbindung.

## Bauen und Dokumentation

- Bauanleitung: [docs/BUILD.de.md](docs/BUILD.de.md) (englische Fassung: [docs/BUILD.md](docs/BUILD.md))
- Weitere Dokumente liegen im Ordner [docs/](docs/), zum Beispiel `docs/recomp-macapp.md`, `docs/recomp-ios.md`, `docs/recomp-vulkan.md` und `docs/changelog.md`.

Der Unity-Nachbau ist eingestellt und liegt vollständig auf dem Branch `unity` (`unity/DEPRECATED.md` dort). `main` enthält ihn nicht mehr.

### Verwandte Projekte

Der Weg über das Original-Unity-Projekt und die Rekreation in modernem Unity wurde bewusst verworfen. Wer diesen Weg verfolgen möchte, findet die Arbeit an anderer Stelle:

- [uDPR](https://github.com/shatter9652/uDPR) von shatter9652, eine Unity-Rekreation, die auf [opendpr](https://github.com/TeamLumi/opendpr) aufbaut.
- [opendpr](https://github.com/TeamLumi/opendpr) von TeamLumi, das ursprüngliche Projekt.

## Fremdcode und Attribution

Dieses Projekt übernimmt und verändert Teile von **LASRecomp** (https://github.com/peiikai/LASRecomp, Commit `09f8e5ebf28aeefd6daa1456c73ae1b7a51efec5`), Copyright (c) 2026 Peiikai, MIT-Lizenz. Betroffen sind:

- `shader_translator/`: Maxwell-zu-MSL/GLSL-Übersetzer, aus dem Original abgeleitet und verändert (`shader_translator/NOTICE.md`, Lizenz `shader_translator/LICENSE-LASRecomp`).
- `scripts/recomp/rt-bdsp/`: Laufzeit im Entwurf des Originals, enthält Teile davon wörtlich (`scripts/recomp/rt-bdsp/NOTICE.md`, Lizenz `scripts/recomp/rt-bdsp/LICENSE-LASRecomp`).
- Header `cpu.h`, `simd.h`, `simd_fp.h`: unverändert in `scripts/recomp/upstream/runtime/` (Lizenz `scripts/recomp/upstream/LICENSE`).
- NVN-Grafikschicht (Metal und Vulkan): geändert gegenüber LASRecomp, Quellen unter `scripts/recomp/rt-bdsp/nvn/src/`; Original zum Vergleich in `scripts/recomp/upstream/runtime/`.

Vollständige Liste, Drittkomponenten und Nicht-Übernommenes: `THIRD_PARTY_NOTICES.md`.

Der Nutzer dieses Repositorys hat die Übernahme und Weiterentwicklung des MIT-lizenzierten Codes ausdrücklich freigegeben. Die Lizenz des Originals nimmt Nintendo-Eigentum und die Drittkomponenten seines `third_party/` ausdrücklich aus; davon ist hier nichts enthalten.

## Lizenz des eigenen Codes

Der eigene Code dieses Repositorys steht unter der MIT-Lizenz (`LICENSE`, Copyright (c) 2026 Veemyu). Ausgenommen sind die Fremdteile oben: Sie behalten ihre eigene Lizenz (`scripts/recomp/rt-bdsp/LICENSE-LASRecomp`, `scripts/recomp/upstream/LICENSE`, `shader_translator/LICENSE-LASRecomp`). Spieldaten, Keys und Dumps gehören nicht zum Repository und fallen nicht unter diese Lizenz.
