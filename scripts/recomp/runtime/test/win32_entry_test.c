#include <assert.h>
#include <stdlib.h>
#include <stdarg.h>
#include <string.h>
#include "win32_files.h"
#include "runtime_paths.h"
#ifdef BDSP_ENTRY_PATH_TEST
#include <shlobj.h>
static char *test_environment(const wchar_t *name) {
    wchar_t value[32768];
    DWORD size = GetEnvironmentVariableW(name, value, 32768);
    assert(size && size < 32768);
    return bdsp_win32_utf8(value);
}
static HRESULT test_known_folder(REFKNOWNFOLDERID id, DWORD flags, HANDLE token, PWSTR *path) {
    (void)flags;
    (void)token;
    const wchar_t *name = IsEqualGUID(id, &FOLDERID_RoamingAppData) ? L"TEST_ROAMING_ROOT" :
                          IsEqualGUID(id, &FOLDERID_LocalAppData) ? L"TEST_LOCAL_ROOT" : NULL;
    assert(name);
    if (getenv("TEST_ROAMING_FAIL") && !wcscmp(name, L"TEST_ROAMING_ROOT")) return E_FAIL;
    char *value = test_environment(name);
    wchar_t *wide = bdsp_win32_widen(value);
    free(value);
    assert(wide);
    size_t bytes = (wcslen(wide) + 1) * sizeof(wchar_t);
    *path = CoTaskMemAlloc(bytes);
    assert(*path);
    memcpy(*path, wide, bytes);
    free(wide);
    return S_OK;
}
#define SHGetKnownFolderPath test_known_folder
#include "../win32_entry.c"
#undef SHGetKnownFolderPath
#endif

void rt_fatal(const char *format, ...) {
    va_list arguments;
    va_start(arguments, format);
    vfprintf(stderr, format, arguments);
    va_end(arguments);
    exit(2);
}

int bdsp_main(int argc, char **argv) {
    assert(argc == 2 && !strcmp(argv[1], "argument-\xe6\x97\xa5\xe6\x9c\xac\xe8\xaa\x9e"));
    assert(!strcmp(getenv("BDSP_ENTRY_PROBE"), "environment-\xe6\x97\xa5\xe6\x9c\xac\xe8\xaa\x9e"));
#ifdef BDSP_ENTRY_PATH_TEST
    char *save = test_environment(L"TEST_EXPECT_SAVE"), *data = test_environment(L"TEST_EXPECT_DATA");
    assert(!strcmp(getenv("BDSP_SAVE"), save));
    assert(!strcmp(getenv("BDSP_DATA_DIR"), data));
    free(save);
    free(data);
#endif
    const char *directories[] = {"BDSP_DATA_DIR", "BDSP_SAVE", "BDSP_CACHE_DIR",
                                "BDSP_LOG_DIR", "BDSP_SHOT_DIR", "BDSP_MODS_DIR"};
    for (unsigned i = 0; i < sizeof directories / sizeof *directories; i++) {
        BdspFileInfo info;
        const char *path = getenv(directories[i]);
        assert(path && stat(path, &info) == 0 && S_ISDIR(info.st_mode));
    }
    const char *img = getenv("BDSP_IMG");
    assert(img && strstr(img, "img") && strchr(img, ':'));
    char *original_config = strdup(getenv("BDSP_CONTROLLER_CONFIG"));
    assert(original_config && strstr(original_config, "controller-mode.txt"));
    char mode_path[4096];
    snprintf(mode_path, sizeof mode_path, "%s/controller-mode.txt", getenv("BDSP_DATA_DIR"));
    assert(_putenv_s("BDSP_CONTROLLER_CONFIG", mode_path) == 0);
    assert(bdsp_joycon_mode() == 1);
    static const struct { const char *text; size_t size; int mode; } modes[] = {
        {"single\n", 7, 0}, {"pair\r\n", 6, 1}, {"unknown", 7, -1},
        {"single\0junk", 11, -1}, {"singleXXXXXXXXXXXX", 18, -1}, {"", 0, -1}
    };
    for (size_t i = 0; i < sizeof modes / sizeof *modes; i++) {
        FILE *config = fopen(mode_path, "wb");
        assert(config && fwrite(modes[i].text, 1, modes[i].size, config) == modes[i].size);
        assert(fclose(config) == 0);
        assert(bdsp_joycon_mode() == modes[i].mode);
    }
    assert(_putenv_s("BDSP_JOYCONS", "single") == 0);
    assert(bdsp_joycon_mode() == 0);
    assert(_putenv_s("BDSP_JOYCONS", "pair") == 0);
    assert(bdsp_joycon_mode() == 1);
    assert(_putenv_s("BDSP_JOYCONS", "") == 0);
    assert(bdsp_joycon_store(mode_path, 0));
    assert(bdsp_joycon_mode() == 0);
    assert(bdsp_joycon_store(mode_path, 1));
    assert(bdsp_joycon_mode() == 1);
    assert(!bdsp_joycon_store(mode_path, 2));
    assert(bdsp_joycon_mode() == 1);
    assert(!bdsp_joycon_store(NULL, 1));
    assert(!bdsp_joycon_store("", 1));
    char missing_path[4096];
    snprintf(missing_path, sizeof missing_path, "%s/nonexistent/mode.txt", getenv("BDSP_DATA_DIR"));
    assert(!bdsp_joycon_store(missing_path, 0));
    assert(bdsp_joycon_mode() == 1);
    // Sharing violation must not truncate the existing configuration or leave a temporary behind.
    wchar_t *wide_mode = bdsp_win32_widen(mode_path);
    HANDLE locked = CreateFileW(wide_mode, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, 0, NULL);
    free(wide_mode);
    assert(locked != INVALID_HANDLE_VALUE);
    assert(!bdsp_joycon_store(mode_path, 0));
    assert(CloseHandle(locked));
    assert(bdsp_joycon_mode() == 1);
    DIR *directory = opendir(getenv("BDSP_DATA_DIR"));
    assert(directory);
    struct dirent *entry;
    while ((entry = readdir(directory)))
        assert(strncmp(entry->d_name, "controller-mode.txt.", strlen("controller-mode.txt.")));
    assert(closedir(directory) == 0);
    assert(unlink(mode_path) == 0);
    assert(_putenv_s("BDSP_CONTROLLER_CONFIG", original_config) == 0);
    free(original_config);
    assert(bdsp_cache_prepare("spirv"));
    char cache_path[4096];
    bdsp_cache_path(cache_path, sizeof cache_path, "spirv/probe.bin");
    FILE *cache = fopen(cache_path, "wb");
    assert(cache && fputc(7, cache) == 7 && fclose(cache) == 0);
    assert(unlink(cache_path) == 0);
    FILE *file = fopen(getenv("BDSP_NPDM"), "rb");
    assert(file && fgetc(file) == 42 && fclose(file) == 0);
    puts("UTF-8 entry, environment and relocated read/write paths passed");
    return 0;
}
