// Mods: folders in the layout of Ryujinx/yuzu mods (<mod>/romfs, <mod>/exefs), the one active mod and its separate save folder.
// Own code. The runtime merges the active mod's RomFS over the game's (services_fs.c) and main.c redirects the save folder;
// the app shells (iOS, macOS) call mods_scan/mods_activate to offer the choice at launch.
#ifndef BDSP_MODS_H
#define BDSP_MODS_H

#include <stddef.h>

#define MODS_MAX 32

typedef struct {
    char name[256];    // shown to the user: the folder that holds romfs/ and/or exefs/
    char root[1100];   // that folder
    char romfs[1200];  // <root>/romfs, "" if absent (the folder name may differ in case)
    char exefs[1200];  // <root>/exefs, "" if absent
} ModInfo;

// Mods below mods_dir: every folder up to 4 levels down that contains romfs/ or exefs/ (so an unpacked archive with an outer
// wrapper folder works). Sorted by path; duplicate names get " (2)". Returns the count (at most max).
int mods_scan(const char *mods_dir, ModInfo *out, int max);

// Makes m the active mod and creates its own save folder <saves_dir>/mods/<name> (user_id.hex is copied from saves_dir so the
// account stays the same). The game's own save folder is never touched while a mod is active. Returns 0 on success.
int mods_activate(const ModInfo *m, const char *saves_dir);
const ModInfo *mods_active(void);   // NULL: the unmodified game
const char *mods_active_save(void); // save folder of the active mod, "" if none

// BDSP_MODS_DIR + BDSP_MOD=<name> (tests, Linux; the app shells choose with their own dialog). "", "none" and "diamond" mean
// the unmodified game. Returns 1 if a mod was activated, 0 if none was requested, -1 on an error (already printed).
int mods_select_from_env(const char *saves_dir);

// Host path of the RomFS file for a path like "Data/StreamingAssets/Movie/x.webm" in the merged tree (mod first); 1 if found.
// Implemented in services_fs.c; used by the movie layer, which opens files by host path.
int fs_resolve_rom_path(const char *rel, char *out, size_t n);

#endif
