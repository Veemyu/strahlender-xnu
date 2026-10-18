# Hinweise zu Fremdcode

Dieses Repository enthält eigenen Code und folgende übernommene Teile. Das Repository enthält keine Spieldaten, Keys oder daraus abgeleitete Inhalte.

## LASRecomp (MIT)

- **Wo:** `shader_translator/translate.c`, `shader_translator/shader.h` (verändert, Änderungen in `shader_translator/NOTICE.md`)
- **Quelle:** https://github.com/peiikai/LASRecomp, Commit `09f8e5ebf28aeefd6daa1456c73ae1b7a51efec5`
- **Urheber/Lizenz:** Copyright (c) 2026 Peiikai, MIT-Lizenz. Der Lizenztext liegt unverändert in `shader_translator/LICENSE-LASRecomp`.
- **Hinweis des Originals:** Das README nennt den Code „almost exclusively“ KI-erstellt (Claude über Claude Code), von einem Menschen gelenkt und geprüft.
- **Weitere Quellen darin (nur Kommentare des Originals, keine Dateien von dort):** Feldlayouts nach den Decodern des Ryujinx-Projekts und der envytools-Dokumentation (Lizenzen dieser Projekte hier nicht geprüft). Welche Teile des Originals daraus stammen, ist nicht geklärt.

## Nicht übernommen

Alles Übrige aus LASRecomp (Laufzeit, Renderer, `third_party/`, UI, Schriften, Rekompilierer) ist nicht Teil dieses Repositories.
