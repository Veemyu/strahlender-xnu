#pragma once
// Installed layout: <app>/img, <app>/romfs, <app>/main.npdm next to the executable.

// Points BDSP_IMG, BDSP_ROMFS and BDSP_NPDM at the entries of `dir` that exist; variables that are already set stay as they are.
void bdsp_exe_dir_defaults(const char *dir);

// Same for the folder of the running executable (Linux; no-op elsewhere, where the app shells set the paths themselves).
void bdsp_exe_defaults(void);
