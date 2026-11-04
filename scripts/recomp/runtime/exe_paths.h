#pragma once
// Installed layout: <app>/img, <app>/romfs, <app>/main.npdm next to the executable.

// Points BDSP_IMG, BDSP_ROMFS and BDSP_NPDM at the entries of `dir` that exist; variables that are already set stay as they are.
// A mod.txt in `dir` (mod folder name, mods folder, "exefs" or "romfs") selects the mod of a mod app: BDSP_MOD, BDSP_MODS_DIR and, for
// "exefs" (code compiled in), BDSP_COMPILED_EXEFS are set even when the environment names another mod. An unusable mod.txt ends the process.
void bdsp_exe_dir_defaults(const char *dir);

// Same for the folder of the running executable (Linux; no-op elsewhere, where the app shells set the paths themselves).
void bdsp_exe_defaults(void);
