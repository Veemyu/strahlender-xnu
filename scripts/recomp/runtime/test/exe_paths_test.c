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
    char dir[] = "/tmp/bdsp_exe_paths_XXXXXX";
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

    printf("exe_paths_test OK\n");
    return 0;
}
