#include "exe_paths.h"

#ifndef _WIN32
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

static void default_path(const char *name, const char *dir, const char *entry, int want_directory) {
    if (getenv(name)) return;
    char path[PATH_MAX];
    if (snprintf(path, sizeof path, "%s/%s", dir, entry) >= (int)sizeof path) return;
    struct stat info;
    if (stat(path, &info) != 0) return;
    if (want_directory ? !S_ISDIR(info.st_mode) : !S_ISREG(info.st_mode)) return;
    setenv(name, path, 0);
}

// mod.txt next to the executable (written by the installer for a mod app, same three lines as on Windows): the mod's folder name, its mods
// folder and "exefs" when the mod's code is compiled into this executable ("romfs" otherwise). A compiled code mod always starts its own
// mod, a RomFS mod yields to the environment. Returns 0 without a mod.txt, -1 when it is unusable.
static int apply_mod_launch(const char *dir) {
    char path[PATH_MAX];
    if (snprintf(path, sizeof path, "%s/mod.txt", dir) >= (int)sizeof path) return 0;
    FILE *file = fopen(path, "rb");
    if (!file) return 0;
    char name[256], mods[1100], kind[16];
    int valid = fgets(name, sizeof name, file) && fgets(mods, sizeof mods, file) && fgets(kind, sizeof kind, file) &&
                strchr(name, '\n') && strchr(mods, '\n') && strchr(kind, '\n');
    fclose(file);
    if (valid) {
        name[strcspn(name, "\r\n")] = 0;
        mods[strcspn(mods, "\r\n")] = 0;
        kind[strcspn(kind, "\r\n")] = 0;
        valid = name[0] && mods[0] && (!strcmp(kind, "exefs") || !strcmp(kind, "romfs"));
    }
    if (!valid) {
        fprintf(stderr, "FATAL: %s is invalid; rebuild this mod app with the installer.\n", path);
        return -1;
    }
    int compiled = !strcmp(kind, "exefs");
    setenv("BDSP_MODS_DIR", mods, compiled);
    setenv("BDSP_MOD", name, compiled);
    if (compiled) setenv("BDSP_COMPILED_EXEFS", name, 1);
    return 0;
}

void bdsp_exe_dir_defaults(const char *dir) {
    if (!dir || !*dir) return;
    if (apply_mod_launch(dir)) exit(1);
    default_path("BDSP_IMG", dir, "img", 1);
    default_path("BDSP_ROMFS", dir, "romfs", 1);
    default_path("BDSP_NPDM", dir, "main.npdm", 0);
}

void bdsp_exe_defaults(void) {
#ifdef __linux__
    char path[PATH_MAX];
    ssize_t length = readlink("/proc/self/exe", path, sizeof path - 1);
    if (length <= 0) return;
    path[length] = 0;
    char *slash = strrchr(path, '/');
    if (!slash) return;
    *slash = 0;
    bdsp_exe_dir_defaults(path);
#endif
}
#else
void bdsp_exe_dir_defaults(const char *dir) { (void)dir; }
void bdsp_exe_defaults(void) {}
#endif
