# Hinweise zu Fremdcode

Dieses Repository enthält eigenen Code und folgende übernommene Teile. Das Repository enthält keine Spieldaten, Keys oder daraus abgeleitete Inhalte.

## LASRecomp (MIT)

- **Wo:** `shader_translator/translate.c`, `shader_translator/shader.h` (verändert, Änderungen in `shader_translator/NOTICE.md`)
- **Quelle:** https://github.com/peiikai/LASRecomp, Commit `09f8e5ebf28aeefd6daa1456c73ae1b7a51efec5`
- **Urheber/Lizenz:** Copyright (c) 2026 Peiikai, MIT-Lizenz. Der Lizenztext liegt unverändert in `shader_translator/LICENSE-LASRecomp`.
- **Hinweis des Originals:** Das README nennt den Code „almost exclusively“ KI-erstellt (Claude über Claude Code), von einem Menschen gelenkt und geprüft.
- **Weitere Quellen darin (nur Kommentare des Originals, keine Dateien von dort):** Feldlayouts nach den Decodern des Ryujinx-Projekts und der envytools-Dokumentation (Lizenzen dieser Projekte hier nicht geprüft). Welche Teile des Originals daraus stammen, ist nicht geklärt.
- **Eigene Ergänzungen (Teil 2, kein Fremdcode):** TEX.B, HSETP2 (cbuf/imm), Ressourcenkarte, Fast-Math-Pragmas. Die Feldlage von TEX.B und HSETP2 habe ich aus dem Gedächtnis nach dem Aufbau der Ryujinx-Decoder-Tabellen angesetzt und ausschließlich numerisch gegen die Ryujinx-Referenz geprüft (`scripts/shader_fidelity.py`); es wurde kein Ryujinx-Quelltext kopiert oder gelesen.

## LASRecomp, weitere Teile (MIT, Copyright (c) 2026 Peiikai)

- **Wo:** `scripts/recomp/rt-bdsp/` (Entwurf der Laufzeit, teils wörtlich übernommen; Abgleich und Details in `scripts/recomp/rt-bdsp/NOTICE.md`; Lizenztext `scripts/recomp/rt-bdsp/LICENSE-LASRecomp`), `scripts/recomp/rt-bdsp/nvn/movie_glue.c` (nach `runtime/hle/movie.c`).
- **Header und Generator:** `cpu.h`, `simd.h`, `simd_fp.h` unverändert in `scripts/recomp/upstream/runtime/`; Generator-Werkzeuge in `scripts/recomp/upstream/generator/` (Lizenz `scripts/recomp/upstream/LICENSE`).
- **NVN-Grafikschicht (Metal und Vulkan):** unverändert unter `scripts/recomp/upstream/runtime/` (Lizenz `scripts/recomp/upstream/LICENSE`, Commit `09f8e5e`); Änderungen nur in den Patches unter `scripts/recomp/rt-bdsp/nvn/`. Details: `scripts/recomp/rt-bdsp/NOTICE.md`, `scripts/recomp/rt-bdsp/nvn/vulkan/NOTICE.md`.
- **Vollständig vendort:** Laufzeit `runtime/` (einschließlich `hle/`, `services/`, `platform/`, `ui/`, `nvn/`) und Generator `generator/` (einschließlich `rando/`), jeweils unverändert.
- **Nicht übernommen:** `third_party/` des Originals (eigene Lizenzen, u. a. imgui, smaa, Schriften, LAS-Randomizer; Nintendo-Ausschluss laut Original-LICENSE), `fonts/`, Klon-Metadaten (`.git`, Makefile, README, CONTRIBUTING, `docs/`). Ohne `third_party/` bauen die UI-Teile von `runtime/ui/` nicht; wir bauen sie nicht.

## Weitere Drittkomponenten (nur Verweis)

- **FFmpeg** (LGPL/GPL je nach Bauart): wird bei der Filmwiedergabe gelinkt, nicht mitgeliefert. Die Bauart ist in `docs/bauen.md` zu prüfen.
- **Build-Werkzeuge** `capstone`, `unicorn`, `lz4` (`tools/pydeps`): nur lokal genutzt, nicht mitgeliefert.
