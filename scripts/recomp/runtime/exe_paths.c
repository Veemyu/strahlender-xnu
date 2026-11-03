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

void bdsp_exe_dir_defaults(const char *dir) {
    if (!dir || !*dir) return;
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
