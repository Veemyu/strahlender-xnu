# Changelog

Chronologisch, neueste Einträge oben. Jeder Schritt mit Datum, Ziel und Dateien.

## 2026-10-19

- **Attribution:** Neue Root-`README.md` mit Fremdcode-Abschnitt (LASRecomp, MIT). `THIRD_PARTY_NOTICES.md` korrigiert: der NVN-Renderer wird zur Bauzeit kopiert, widersprach dem bisherigen Text. Ergänzt um FFmpeg und Build-Werkzeuge.
- **Umbenennung:** Alle Umgebungsvariablen `LARECOMP_*` heißen jetzt `BDSP_*` (Code, Patches, Skripte, Dokumentation). `nvn/prepare.sh` und `nvn/vulkan/prepare_vk.sh` benennen die kopierten Upstream-Quellen vor dem Patchen um. Ausnahmen mit Absicht: `shader_translator/NOTICE.md` und `shader.h`, wo der alte Name die Herkunft belegt.
- **Bildrate:** iPad-Einstellungen `bdsp_fps` (30/60/120) und `bdsp_metal_hud`, lokalisiert (`en.lproj`, `de.lproj`, Anzeige „Bildrate“). Mac-Menü „Bildrate“ (noch nicht lokalisiert).
- **Metal-HUD (iPad):** Schalter unter „Debug“ in den Einstellungen; wirkt nach einem Neustart über `MTL_HUD_ENABLED`.
- **Vsync:** Festes 16,67-ms-Intervall driftete auf etwa 50 Hz. Jetzt absolute Deadlines in `services_gfx.c`. Mac misst 59,9 fps.
- **Debug-Thread:** `BDSP_DEBUG_THREAD=1` verlagert Readbacks auf eigenen Thread (`dbgthread.patch`, `debug_thread.c`).
- **Wasser (Todo 1):** Tiefentest nur bei gebundenem Tiefenziel (`fixes.patch`, Commit `f22b7f9`).
