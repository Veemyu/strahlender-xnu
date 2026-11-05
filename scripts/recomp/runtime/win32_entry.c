#ifdef _WIN32
#include "plat.h"
#include "exit_report.h"
#include "win32_files.h"
#include <errno.h>
#include <shlobj.h>
#include <timeapi.h>
#include <stdlib.h>
#include <string.h>
#ifndef BDSP_NVN_NONE
#define SDL_MAIN_HANDLED
#include <SDL3/SDL_main.h>
#endif

int bdsp_main(int argc, char **argv);

static int set_path(const char *name, const char *parent, const char *child, bool directory) {
    if (getenv(name)) return 0;
    size_t size = strlen(parent) + strlen(child) + 2;
    char *path = malloc(size);
    if (!path) { errno = ENOMEM; return -1; }
    snprintf(path, size, "%s\\%s", parent, child);
    int result = 0;
    if (directory && !plat_ensure_directory(path)) result = -1;
    if (!result && !plat_setenv(name, path, true)) result = -1;
    free(path);
    return result;
}

// mod.txt beside BDSP.exe, written by the installer for a mod app: the mod's folder name (mods.c finds mods by it), its mods folder and "exefs" when the mod's
// code is compiled into this executable ("romfs" otherwise). The environment may still choose another RomFS mod or "none";
// a compiled code mod always starts its own mod, like the macOS mod app (app_config.c).
static int apply_mod_launch(const char *package) {
    size_t size = strlen(package) + sizeof "\\mod.txt";
    char *path = malloc(size);
    if (!path) { errno = ENOMEM; return -1; }
    snprintf(path, size, "%s\\mod.txt", package);
    FILE *file = fopen(path, "rb");
    if (!file) {
        int missing = errno == ENOENT;
        free(path);
        return missing ? 0 : -1;
    }
    char name[256], dir[1100], kind[16];
    bool valid = fgets(name, sizeof name, file) && fgets(dir, sizeof dir, file) && fgets(kind, sizeof kind, file) &&
                 strchr(name, '\n') && strchr(dir, '\n') && strchr(kind, '\n');
    fclose(file);
    if (valid) {
        name[strcspn(name, "\r\n")] = 0;
        dir[strcspn(dir, "\r\n")] = 0;
        kind[strcspn(kind, "\r\n")] = 0;
        valid = name[0] && dir[0] && (!strcmp(kind, "exefs") || !strcmp(kind, "romfs"));
    }
    if (!valid) {
        bdsp_exit_fatalf("%s is invalid; rebuild this mod app with the installer", path);
        free(path);
        errno = EINVAL;
        return -1;
    }
    free(path);
    bool compiled = !strcmp(kind, "exefs");
    if (!plat_setenv("BDSP_MODS_DIR", dir, compiled) || !plat_setenv("BDSP_MOD", name, compiled) ||
        (compiled && !plat_setenv("BDSP_COMPILED_EXEFS", name, true)))
        return -1;
    return 0;
}

static int prepare_paths(void) {
    bool explicit_data = getenv("BDSP_DATA_DIR") != NULL;
    wchar_t executable[32768];
    DWORD length = GetModuleFileNameW(NULL, executable, 32768);
    if (!length || length >= 32768) { errno = ENAMETOOLONG; return -1; }
    wchar_t *separator = wcsrchr(executable, L'\\');
    if (!separator) { errno = EINVAL; return -1; }
    *separator = 0;
    char *package = bdsp_win32_utf8(executable);
    if (!package) return -1;
    int result = set_path("BDSP_IMG", package, "img", false) ||
                 set_path("BDSP_ROMFS", package, "romfs", false) ||
                 set_path("BDSP_NPDM", package, "exefs\\main.npdm", false) ||
                 set_path("BDSP_PACKAGED_CACHE_DIR", package, "prebuilt", false) ||   // SPIR-V the installer built (vulkan/shaders.c)
                 apply_mod_launch(package);
    free(package);
    if (result) return -1;
    if (!explicit_data && !getenv("BDSP_SAVE")) {
        PWSTR roaming = NULL;
        HRESULT status = SHGetKnownFolderPath(&FOLDERID_RoamingAppData, KF_FLAG_CREATE, NULL, &roaming);
        if (FAILED(status)) {
            bdsp_exit_fatalf("Windows roaming save folder lookup failed (0x%08lx)", (unsigned long)status);
            return -1;
        }
        char *base = bdsp_win32_utf8(roaming);
        CoTaskMemFree(roaming);
        if (!base) return -1;
        size_t size = strlen(base) + sizeof "\\StrahlenderXnu";
        char *save_root = malloc(size);
        if (!save_root) { free(base); errno = ENOMEM; return -1; }
        snprintf(save_root, size, "%s\\StrahlenderXnu", base);
        free(base);
        if (!plat_ensure_directory(save_root)) {
            free(save_root);
            return -1;
        }
        result = set_path("BDSP_SAVE", save_root, "save", true);
        free(save_root);
        if (result) return -1;
    }
    if (!getenv("BDSP_DATA_DIR")) {
        PWSTR local = NULL;
        HRESULT status = SHGetKnownFolderPath(&FOLDERID_LocalAppData, KF_FLAG_CREATE, NULL, &local);
        if (FAILED(status)) {
            bdsp_exit_fatalf("Windows user data folder lookup failed (0x%08lx)", (unsigned long)status);
            return -1;
        }
        char *root = bdsp_win32_utf8(local);
        CoTaskMemFree(local);
        if (!root) return -1;
        result = set_path("BDSP_DATA_DIR", root, "StrahlenderXnu", true);
        free(root);
        if (result) return -1;
    }
    // getenv pointers may be invalidated by subsequent _putenv_s calls.
    char *root = strdup(getenv("BDSP_DATA_DIR"));
    if (!root) { errno = ENOMEM; return -1; }
    if (!plat_ensure_directory(root)) { free(root); return -1; }
    result = set_path("BDSP_CONTROLLER_CONFIG", root, "controller-mode.txt", false) ||
             set_path("BDSP_DISPLAY_CONFIG", root, "display.conf", false) ||   // aspect ratio and render height (display_size.c)
             set_path("BDSP_SAVE", root, "save", true) ||
             set_path("BDSP_CACHE_DIR", root, "cache", true) ||
             set_path("BDSP_SHOT_DIR", root, "shots", true) ||
             set_path("BDSP_LOG_DIR", root, "logs", true) ||
             set_path("BDSP_MODS_DIR", root, "mods", true);
    free(root);
    return result ? -1 : 0;
}

int wmain(int argc, wchar_t **wide_argv) {
    wchar_t *environment = GetEnvironmentStringsW();
    if (!environment) {
        bdsp_exit_fatalf("Windows environment query failed (%lu)", GetLastError());
        return 1;
    }
    for (const wchar_t *item = environment; *item; item += wcslen(item) + 1) {
        if (_wcsnicmp(item, L"BDSP_", 5)) continue;
        char *assignment = bdsp_win32_utf8(item);
        if (!assignment) {
            bdsp_exit_fatalf("Windows UTF-8 environment conversion failed (%d)", errno);
            FreeEnvironmentStringsW(environment); return 1;
        }
        char *equal = strchr(assignment, '=');
        if (!equal) { free(assignment); continue; }
        *equal = 0;
        bool imported = plat_setenv(assignment, equal + 1, true);
        free(assignment);
        if (!imported) {
            bdsp_exit_fatalf("Windows UTF-8 environment import failed (%d)", errno);
            FreeEnvironmentStringsW(environment); return 1;
        }
    }
    FreeEnvironmentStringsW(environment);
    char **argv = calloc((size_t)argc + 1, sizeof *argv);
    if (!argv) { bdsp_exit_fatalf("Windows argument allocation failed"); return 1; }
    int converted = 0, result = 1;
    for (; converted < argc; converted++) {
        argv[converted] = bdsp_win32_utf8(wide_argv[converted]);
        if (!argv[converted]) {
            bdsp_exit_fatalf("Windows UTF-8 argument conversion failed (%d)", errno);
            goto done;
        }
    }
    if (prepare_paths()) {
        bdsp_exit_fatalf("Windows runtime path preparation failed (%d)", errno);
        goto done;
    }
    if (!bdsp_win32_crash_open(getenv("BDSP_LOG_DIR"))) {
        bdsp_exit_fatalf("Windows crash log could not be opened (%lu)", GetLastError());
        goto done;
    }
    timeBeginPeriod(1);  // 1 ms Sleep/condition-variable timeouts instead of 15.6 ms
    // Opt out of EcoQoS and of Windows 11 ignoring the timer resolution while the window is occluded.
    PROCESS_POWER_THROTTLING_STATE throttling = {
        .Version = PROCESS_POWER_THROTTLING_CURRENT_VERSION,
        .ControlMask = PROCESS_POWER_THROTTLING_EXECUTION_SPEED | PROCESS_POWER_THROTTLING_IGNORE_TIMER_RESOLUTION,
    };
    SetProcessInformation(GetCurrentProcess(), ProcessPowerThrottling, &throttling, sizeof throttling);
#ifndef BDSP_NVN_NONE
    SDL_SetMainReady();
#endif
    result = bdsp_main(argc, argv);
done:
    for (int i = 0; i < converted; i++) free(argv[i]);
    free(argv);
    return result;
}
#endif
