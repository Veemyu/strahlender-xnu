// Installed layout: the executable folder supplies the paths that the launcher script would have set.
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#include "../exe_paths.h"

static void touch(const char *path) {
    FILE *f = fopen(path, "wb");
    assert(f);
    fclose(f);
}

int main(void) {
    const char *base = getenv("TMPDIR") && *getenv("TMPDIR") ? getenv("TMPDIR") : "/tmp";
    char dir[400];
    snprintf(dir, sizeof dir, "%s/bdsp_exe_paths_XXXXXX", base);
    assert(mkdtemp(dir));
    char path[512];
    snprintf(path, sizeof path, "%s/img", dir);
    assert(!mkdir(path, 0700));
    snprintf(path, sizeof path, "%s/romfs", dir);
    assert(!mkdir(path, 0700));
    snprintf(path, sizeof path, "%s/main.npdm", dir);
    touch(path);

    unsetenv("BDSP_IMG");
    unsetenv("BDSP_ROMFS");
    unsetenv("BDSP_NPDM");
    setenv("BDSP_ROMFS", "/explicit/romfs", 1);
    bdsp_exe_dir_defaults(dir);
    snprintf(path, sizeof path, "%s/img", dir);
    assert(getenv("BDSP_IMG") && !strcmp(getenv("BDSP_IMG"), path));
    assert(!strcmp(getenv("BDSP_ROMFS"), "/explicit/romfs"));   // an explicit setting wins
    snprintf(path, sizeof path, "%s/main.npdm", dir);
    assert(getenv("BDSP_NPDM") && !strcmp(getenv("BDSP_NPDM"), path));

    unsetenv("BDSP_IMG");
    unsetenv("BDSP_ROMFS");
    unsetenv("BDSP_NPDM");
    bdsp_exe_dir_defaults("/tmp/bdsp_exe_paths_missing_folder");   // development layouts keep the work/ defaults
    assert(!getenv("BDSP_IMG") && !getenv("BDSP_ROMFS") && !getenv("BDSP_NPDM"));

    // mod.txt of a mod app: a compiled code mod overrides the environment, a RomFS mod does not
    unsetenv("BDSP_MOD");
    unsetenv("BDSP_MODS_DIR");
    unsetenv("BDSP_COMPILED_EXEFS");
    snprintf(path, sizeof path, "%s/mod.txt", dir);
    FILE *launch = fopen(path, "wb");
    assert(launch);
    fputs("Example Mod\n/mods/dir\nromfs\n", launch);
    fclose(launch);
    setenv("BDSP_MOD", "other", 1);
    bdsp_exe_dir_defaults(dir);
    assert(!strcmp(getenv("BDSP_MOD"), "other") && !strcmp(getenv("BDSP_MODS_DIR"), "/mods/dir") && !getenv("BDSP_COMPILED_EXEFS"));
    unsetenv("BDSP_MODS_DIR");
    launch = fopen(path, "wb");
    assert(launch);
    fputs("Example Mod\n/mods/dir\nexefs\n", launch);
    fclose(launch);
    bdsp_exe_dir_defaults(dir);
    assert(!strcmp(getenv("BDSP_MOD"), "Example Mod") && !strcmp(getenv("BDSP_MODS_DIR"), "/mods/dir"));
    assert(getenv("BDSP_COMPILED_EXEFS") && !strcmp(getenv("BDSP_COMPILED_EXEFS"), "Example Mod"));

    printf("exe_paths_test OK\n");
    return 0;
}
