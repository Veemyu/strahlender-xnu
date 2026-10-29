#ifdef _WIN32
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
    if (directory && mkdir(path, 0700) && errno != EEXIST) result = -1;
    if (!result) result = _putenv_s(name, path);
    free(path);
    return result;
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
                 set_path("BDSP_NPDM", package, "exefs\\main.npdm", false);
    free(package);
    if (result) return -1;
    if (!explicit_data && !getenv("BDSP_SAVE")) {
        PWSTR roaming = NULL;
        HRESULT status = SHGetKnownFolderPath(&FOLDERID_RoamingAppData, KF_FLAG_CREATE, NULL, &roaming);
        if (FAILED(status)) {
            fprintf(stderr, "FATAL: Windows roaming save folder lookup failed (0x%08lx).\n", (unsigned long)status);
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
        if (mkdir(save_root, 0700) && errno != EEXIST) {
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
            fprintf(stderr, "FATAL: Windows user data folder lookup failed (0x%08lx).\n", (unsigned long)status);
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
    if (mkdir(root, 0700) && errno != EEXIST) { free(root); return -1; }
    result = set_path("BDSP_CONTROLLER_CONFIG", root, "controller-mode.txt", false) ||
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
        fprintf(stderr, "FATAL: Windows environment query failed (%lu).\n", GetLastError());
        return 1;
    }
    for (const wchar_t *item = environment; *item; item += wcslen(item) + 1) {
        if (_wcsnicmp(item, L"BDSP_", 5)) continue;
        char *assignment = bdsp_win32_utf8(item);
        if (!assignment) {
            fprintf(stderr, "FATAL: Windows UTF-8 environment conversion failed (%d).\n", errno);
            FreeEnvironmentStringsW(environment); return 1;
        }
        char *equal = strchr(assignment, '=');
        if (!equal) { free(assignment); continue; }
        *equal = 0;
        int error = _putenv_s(assignment, equal + 1);
        free(assignment);
        if (error) {
            fprintf(stderr, "FATAL: Windows UTF-8 environment import failed (%d).\n", error);
            FreeEnvironmentStringsW(environment); return 1;
        }
    }
    FreeEnvironmentStringsW(environment);
    char **argv = calloc((size_t)argc + 1, sizeof *argv);
    if (!argv) { fprintf(stderr, "FATAL: Windows argument allocation failed.\n"); return 1; }
    int converted = 0, result = 1;
    for (; converted < argc; converted++) {
        argv[converted] = bdsp_win32_utf8(wide_argv[converted]);
        if (!argv[converted]) {
            fprintf(stderr, "FATAL: Windows UTF-8 argument conversion failed (%d).\n", errno);
            goto done;
        }
    }
    if (prepare_paths()) {
        fprintf(stderr, "FATAL: Windows runtime path preparation failed (%d).\n", errno);
        goto done;
    }
    if (!bdsp_win32_crash_open(getenv("BDSP_LOG_DIR"))) {
        fprintf(stderr, "FATAL: Windows crash log could not be opened (%lu).\n", GetLastError());
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
