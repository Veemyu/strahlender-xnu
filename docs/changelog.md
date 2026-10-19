# Changelog

Chronologisch, neueste Einträge oben. Jeder Schritt mit Datum, Ziel und Dateien.

## 2026-10-19

- **Unity-Stufen entfernt:** `assets`, `stubs`, `unity-build` und `deploy` sind aus `scripts/build_all.sh` und `scripts/build_stages.py` entfernt, ebenso Editor-Erkennung (`editor-open`), `--shaders-into-unity`, Unity- und Xcode-Preflight. Die Shader-Stufe bleibt (liest Unity-Bundles des Spiels per UnityPy). Tests angepasst, 347 Tests bestehen.
- **Unity auf Branch `unity`:** siehe Eintrag oben (Unity-Projekt, Docs, Test für `material_variants`).

- **Unity auf Branch `unity`:** Das Unity-Projekt `unity/` (810 Dateien), `scripts/unity_safe.sh`, `docs/unity6-tooling.md`, `docs/unity-autopilot.md`, `docs/feld-szene-2.md`, `docs/material-remap.md`, `docs/shader-unity-integration.md` und der Test `scripts/tests/test_material_variants.py` (Fixture aus `unity/`) sind aus `main` entfernt. Branch `unity` ist auf origin (Stand 13b3977, vollständig). README, Architekturentscheidung und Doku-Index verweisen darauf.
- **Noch auf main, bewusst:** Build-Stufen `stubs`, `assets`, `unity-build`, `deploy` in `build_all.sh` und `build_stages.py` (Folgeschritt), die Shader-Stufe (liest Unity-Bundles des Spiels per UnityPy) und `stub_*`, `visual_*`, `bundle_retarget.py`, `material_*.py`.
- **Lokal unverändert:** der ignorierte Ordner `unity/` (3,6 GB, u. a. `Library`) bleibt auf der Festplatte, wird nicht versioniert.

- **Lizenz:** `LICENSE` im Root (MIT, Copyright (c) 2026 Veemyu). README-Abschnitt „Lizenz des eigenen Codes“ ergänzt. Fremdcode behält seine Lizenz.

- **Alles vendort:** `scripts/recomp/upstream/runtime/` ist eine unveränderte Kopie der vollständigen Laufzeit des Klons (einschließlich `nvn/`, `nvn/vulkan/`, `hle/`, `services/`, `platform/`, `ui/`), `scripts/recomp/upstream/generator/` die des Werkzeugordners (einschließlich `rando/`). Beide byte-identisch mit `09f8e5e`. Nicht übernommen: `third_party/` des Originals (eigene Lizenzen, Nintendo-Ausschluss), `fonts/`, Klon-Metadaten.
- **Eine NVN-Quelle:** Die Doppelkopie `scripts/recomp/rt-bdsp/nvn/upstream/` ist entfernt. `nvn/prepare.sh` und `nvn/vulkan/prepare_vk.sh` kopieren aus `scripts/recomp/upstream/runtime/`.
- **Ryzen und Diff-Werkzeuge:** Pfade auf `scripts/recomp/upstream/` umgestellt; `sync.sh` und `vk_sync.sh` übertragen den Klon-Ordner nicht mehr, weil `scripts/recomp` ihn enthält.
- **Klon nicht mehr nötig:** `research/` wird vom Build nicht mehr gelesen. Geprüft: Mac-Laufzeit, iPad-Build, NVN-Vorbereitung für Metal und Vulkan, 370 Tests, `repo_check`.

- **Klon nicht mehr nötig:** Generator-Werkzeuge (`gen.py`, `lifter.py`, `analyze.py`, `nso.py`, `patches.py`, `simd_c.py`) unverändert unter `scripts/recomp/upstream/generator/`. Die Pfade in `eh_gen.py`, `mkimg.py`, `build_stages.py`, `recomp_build.sh` und den Tests zeigen dorthin. Der Ordner heißt bewusst nicht `tools/`, weil `repo_check.py` jeden Pfad mit `tools/` ablehnt. Nicht übernommen: Randomizer (`tools/rando/`).
- **Test- und Build-Pfade:** Die Test-Skripte (`scripts/recomp/test/`, `rt-bdsp/test/`) nutzen `scripts/recomp/upstream/runtime`. Nicht umgestellt: `scripts/recomp/diff/`, `scripts/recomp/ryzen/` und `run_boot_probe_las.sh`. Sie brauchen weiterhin die volle LASRecomp-Laufzeit (Dienste, Plattform) aus dem Klon.

- **Header vendored:** `cpu.h`, `simd.h`, `simd_fp.h` unverändert unter `scripts/recomp/upstream/runtime/`. Die App-Build-Skripte (`rt-bdsp/build.sh`, `nvn/build_nvn.sh`, `nvn/vulkan/build_vk.sh`, `ios/build_rt32.sh`, `ios/compile_chunk_ios.sh`) nutzen diesen Pfad. Geprüft: iPad-Build und Mac-Laufzeit gelinkt.
- **Provenienz korrigiert:** Abgleich zeigt wörtlich übernommene Zeilen in `kernel.c`, `ipc.c`, `services*.c` und weiteren Dateien (8 bis 47 %). Die bisherige Aussage „keine Datei wurde kopiert“ war falsch und ist in NOTICE, THIRD_PARTY_NOTICES und README korrigiert.

- **Vendoring NVN:** Die Upstream-Quellen der NVN-Schicht (Metal und Vulkan, ohne `imgui_glue.cpp`, `texpatch.c`, `output_scale.c`, `smaa_data.c`) liegen jetzt unverändert unter `scripts/recomp/rt-bdsp/nvn/upstream/`, mit `LICENSE`. `prepare.sh` und `prepare_vk.sh` kopieren von dort. Der Commit-Pin entfällt, weil das Repo den Stand festhält. Geprüft: byte-identisch mit dem Klon, iPad-Build ohne `.rej`.
- **Pin (überholt):** Der zwischenzeitliche Commit-Pin in `prepare.sh` bleibt nur als Vorstufe in der Historie.
- **Attribution:** Neue Root-`README.md` mit Fremdcode-Abschnitt (LASRecomp, MIT). `THIRD_PARTY_NOTICES.md` korrigiert: der NVN-Renderer wird zur Bauzeit kopiert, widersprach dem bisherigen Text. Ergänzt um FFmpeg und Build-Werkzeuge.
- **Settings.bundle:** war durch `*.bundle` in `.gitignore` ausgeschlossen; Ausnahme ergänzt, Bundle ist jetzt versioniert.
- **Umbenennung:** Alle Umgebungsvariablen `LARECOMP_*` heißen jetzt `BDSP_*` (Code, Patches, Skripte, Dokumentation). `nvn/prepare.sh` und `nvn/vulkan/prepare_vk.sh` benennen die kopierten Upstream-Quellen vor dem Patchen um. Ausnahmen mit Absicht: `shader_translator/NOTICE.md` und `shader.h`, wo der alte Name die Herkunft belegt.
- **Bildrate:** iPad-Einstellungen `bdsp_fps` (30/60/120) und `bdsp_metal_hud`, lokalisiert (`en.lproj`, `de.lproj`, Anzeige „Bildrate“). Mac-Menü „Bildrate“ (noch nicht lokalisiert).
- **Metal-HUD (iPad):** Schalter unter „Debug“ in den Einstellungen; wirkt nach einem Neustart über `MTL_HUD_ENABLED`.
- **Vsync:** Festes 16,67-ms-Intervall driftete auf etwa 50 Hz. Jetzt absolute Deadlines in `services_gfx.c`. Mac misst 59,9 fps.
- **Debug-Thread:** `BDSP_DEBUG_THREAD=1` verlagert Readbacks auf eigenen Thread (`dbgthread.patch`, `debug_thread.c`).
- **Wasser (Todo 1):** Tiefentest nur bei gebundenem Tiefenziel (`fixes.patch`, Commit `f22b7f9`).
