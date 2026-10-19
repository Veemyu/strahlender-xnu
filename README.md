# strahlender-xnu

Statische Rekompilation des ARM64-Codes von Pokémon Brilliant Diamond (BDSP) für macOS und iPadOS. Die Laufzeit (Kernel-SVCs, IPC-Dienste, Dateisystem, Grafik über Metal) liegt in `scripts/recomp/rt-bdsp/`; sie enthält Teile aus LASRecomp (siehe unten).

Das Repository enthält **keine Spieldaten**, keine Schlüssel, keine Speicherstände und keinen erzeugten Code. Zum Bauen braucht man einen eigenen Dump des Spiels. Pokémon ist eine Marke von Nintendo, Game Freak und Creatures; dieses Projekt steht mit keiner dieser Firmen in Verbindung.

## Einstieg

- Stand und Todos: `docs/arbeitsstand-2026-10-19.md`, `docs/betriebshandbuch.md`
- Bauen: `docs/bauen.md`, `docs/build-pipeline.md`, `docs/recomp-macapp.md`, `docs/recomp-ios.md`
- Änderungen: `docs/changelog.md`

Der Unity-Nachbau in `unity/` ist eingestellt (`unity/DEPRECATED.md`).

## Fremdcode und Attribution

Dieses Projekt übernimmt und verändert Teile von **LASRecomp** (https://github.com/peiikai/LASRecomp, Commit `09f8e5ebf28aeefd6daa1456c73ae1b7a51efec5`), Copyright (c) 2026 Peiikai, MIT-Lizenz. Betroffen sind:

- `shader_translator/`: Maxwell-zu-MSL/GLSL-Übersetzer, aus dem Original abgeleitet und verändert (`shader_translator/NOTICE.md`, Lizenz `shader_translator/LICENSE-LASRecomp`).
- `scripts/recomp/rt-bdsp/`: Laufzeit im Entwurf des Originals, enthält Teile davon wörtlich (`scripts/recomp/rt-bdsp/NOTICE.md`, Lizenz `scripts/recomp/rt-bdsp/LICENSE-LASRecomp`).
- Header `cpu.h`, `simd.h`, `simd_fp.h`: unverändert in `scripts/recomp/upstream/runtime/` (Lizenz `scripts/recomp/upstream/LICENSE`).
- NVN-Grafikschicht (Metal und Vulkan): unverändert in `scripts/recomp/upstream/runtime/` (Lizenz `scripts/recomp/upstream/LICENSE`), mit Patches aus `scripts/recomp/rt-bdsp/nvn/` verändert.

Vollständige Liste, Drittkomponenten und Nicht-Übernommenes: `THIRD_PARTY_NOTICES.md`.

Der Nutzer dieses Repositorys hat die Übernahme und Weiterentwicklung des MIT-lizenzierten Codes ausdrücklich freigegeben. Die Lizenz des Originals nimmt Nintendo-Eigentum und die Drittkomponenten seines `third_party/` ausdrücklich aus; davon ist hier nichts enthalten.

## Lizenz des eigenen Codes

Noch nicht festgelegt.
