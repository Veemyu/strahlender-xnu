#include "bdsp.h"
#include "plat.h"
#include "runtime_paths.h"
#include "win32_files.h"
#include <errno.h>

int bdsp_joycon_mode(void) {
    const char *mode = getenv("BDSP_JOYCONS");
    char stored[16];
    if (!mode) {
        const char *path = getenv("BDSP_CONTROLLER_CONFIG");
        if (!path) return 1;
        FILE *file = fopen(path, "rb");
        if (!file) {
            if (errno == ENOENT) return 1;
            fprintf(stderr, "[pad] cannot read controller configuration (%d)\n", errno);
            return -1;
        }
        size_t size = fread(stored, 1, sizeof stored - 1, file);
        int failed = ferror(file);
        if (fclose(file)) failed = 1;
        if (failed || size == sizeof stored - 1 || memchr(stored, 0, size)) {
            fprintf(stderr, "[pad] cannot parse controller configuration\n");
            return -1;
        }
        while (size && (stored[size - 1] == '\r' || stored[size - 1] == '\n')) size--;
        stored[size] = 0;
        mode = stored;
    }
    if (!strcmp(mode, "pair")) return 1;
    if (!strcmp(mode, "single")) return 0;
    fprintf(stderr, "[pad] controller mode must be pair or single\n");
    return -1;
}

#ifdef _WIN32
bool bdsp_joycon_store(const char *path, int combine) {
    if (!path || !*path || (combine != 0 && combine != 1)) {
        fprintf(stderr, "[pad] invalid controller configuration destination or mode\n");
        errno = EINVAL;
        return false;
    }
    const char *text = combine ? "pair\n" : "single\n";
    if (plat_write_file_atomic(path, text, strlen(text))) return true;
    fprintf(stderr, "[pad] cannot publish controller configuration (%d)\n", errno);
    return false;
}
#endif

static const char *cache_directory(void) {
    const char *path = getenv("BDSP_CACHE_DIR");
#ifdef _WIN32
    if (!path || !*path) rt_fatal("Windows cache directory was not initialized\n");
#endif
    return path && *path ? path : "work/recomp/cache";
}

void bdsp_cache_path(char *out, size_t capacity, const char *relative) {
    int length = snprintf(out, capacity, "%s/%s", cache_directory(), relative);
    if (length < 0 || (size_t)length >= capacity)
        rt_fatal("cache path exceeds runtime limit\n");
}

static bool ensure_directory(const char *path) {
    if (plat_ensure_directory(path)) return true;
    fprintf(stderr, "[cache] cannot prepare directory (%d)\n", errno);
    return false;
}

bool bdsp_cache_prepare(const char *subdirectory) {
#ifndef _WIN32
    if (!getenv("BDSP_CACHE_DIR") &&
        (!ensure_directory("work") || !ensure_directory("work/recomp"))) return false;
#endif
    if (!ensure_directory(cache_directory())) return false;
    if (subdirectory && *subdirectory) {
        char path[4096];
        bdsp_cache_path(path, sizeof path, subdirectory);
        return ensure_directory(path);
    }
    return true;
}
