// Paths, configuration and start of the app shell (see app.h, docs/recomp-macapp.md). Plain C, no AppKit.
#include "app.h"
#include "../mods.h"

#include <ApplicationServices/ApplicationServices.h>
#include <CoreFoundation/CoreFoundation.h>
#include <errno.h>
#include <mach-o/dyld.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <sys/stat.h>
#include <unistd.h>

BdspApp g_app;

static void mkdir_p(const char *path) {
    char buf[1100];
    snprintf(buf, sizeof buf, "%s", path);
    for (char *p = buf + 1; *p; p++) {
        if (*p != '/') continue;
        *p = 0;
        mkdir(buf, 0755);
        *p = '/';
    }
    mkdir(buf, 0755);
}

static void trim(char *s) {
    size_t n = strlen(s);
    while (n && (s[n - 1] == '\n' || s[n - 1] == '\r' || s[n - 1] == ' ' || s[n - 1] == '\t')) s[--n] = 0;
    char *a = s;
    while (*a == ' ' || *a == '\t') a++;
    if (a != s) memmove(s, a, strlen(a) + 1);
}

// Turn "~" and relative paths (against the working directory of the call) into absolute paths
static void absolutize(char *dst, size_t n, const char *src) {
    if (src[0] == '~' && (src[1] == '/' || !src[1])) {
        const char *h = getenv("HOME");
        snprintf(dst, n, "%s%s", h ? h : "", src + 1);
    } else if (src[0] == '/') {
        snprintf(dst, n, "%s", src);
    } else {
        char cwd[1024];
        if (!getcwd(cwd, sizeof cwd)) cwd[0] = 0;
        snprintf(dst, n, "%s/%s", cwd, src);
    }
}

// Configuration file: lines "key = value", # starts a comment.
static const char *cfg_get(char (*keys)[32], char (*vals)[1024], int n, const char *k) {
    for (int i = 0; i < n; i++) if (!strcmp(keys[i], k)) return vals[i];
    return NULL;
}

static int cfg_int(const char *env, const char *cfg, int def) {
    const char *e = getenv(env);
    if (e && *e) return atoi(e);
    return cfg && *cfg ? atoi(cfg) : def;
}

static void pick_path(char *dst, size_t n, const char *env, const char *cfg, const char *def) {
    const char *e = getenv(env);
    if (e && *e) absolutize(dst, n, e);
    else if (cfg && *cfg) absolutize(dst, n, cfg);
    else snprintf(dst, n, "%s", def);
}

static void redirect_log_if_gui(void) {
    struct stat so, dn;
    if (getenv("BDSP_LOG_STDOUT")) return;
    // started from Finder/Dock: stdout points to /dev/null
    if (fstat(1, &so) != 0 || stat("/dev/null", &dn) != 0 || !S_ISCHR(so.st_mode) || so.st_rdev != dn.st_rdev) return;
    char path[1200], prev[1200];
    mkdir_p(g_app.logs);
    snprintf(path, sizeof path, "%s/bdsp.log", g_app.logs);
    snprintf(prev, sizeof prev, "%s/bdsp.prev.log", g_app.logs);
    rename(path, prev);
    FILE *f = freopen(path, "w", stdout);
    if (!f) return;
    dup2(fileno(stdout), 2);
    setvbuf(stdout, NULL, _IOLBF, 0);
    setvbuf(stderr, NULL, _IOLBF, 0);
}

// ---- Mods: <home>/mods (BDSP_MODS_DIR, "mods =" in config.ini) holds mod folders (<name>/romfs, <name>/exefs). BDSP_MOD or --mod <name|none>
// chooses without a dialog. Otherwise, with at least one mod, a dialog at launch asks what to start; "don't ask again" keeps the last choice
// (Option held at launch asks again). The active mod gets a save folder of its own (<save>/mods/<name>) and g_app.save points there from then
// on, so backups, import and reset only ever touch the mod's save.
static int pref_string(const char *key, char *out, size_t n) {
    CFStringRef k = CFStringCreateWithCString(NULL, key, kCFStringEncodingUTF8);
    CFPropertyListRef v = CFPreferencesCopyAppValue(k, kCFPreferencesCurrentApplication);
    CFRelease(k);
    int ok = v && CFGetTypeID(v) == CFStringGetTypeID() && CFStringGetCString(v, out, (CFIndex)n, kCFStringEncodingUTF8);
    if (v) CFRelease(v);
    return ok;
}

static void pref_set(const char *key, CFTypeRef value) {
    CFStringRef k = CFStringCreateWithCString(NULL, key, kCFStringEncodingUTF8);
    CFPreferencesSetAppValue(k, value, kCFPreferencesCurrentApplication);
    CFPreferencesAppSynchronize(kCFPreferencesCurrentApplication);
    CFRelease(k);
}

static void choose_mod(const char *mods_cfg, int argc, char **argv) {
    char def[1200], dir[1100];
    snprintf(def, sizeof def, "%s/mods", g_app.home);
    pick_path(dir, sizeof dir, "BDSP_MODS_DIR", mods_cfg, def);
    char bundled_name[256] = "", bundled_dir[1100] = "", bundled_root[1100] = "", bundle_meta[1400];
    if (g_app.resources[0] && snprintf(bundle_meta, sizeof bundle_meta, "%s/mod-build.txt", g_app.resources) < (int)sizeof bundle_meta) {
        FILE *meta = fopen(bundle_meta, "r");
        if (meta) {
            int valid = fgets(bundled_name, sizeof bundled_name, meta) && fgets(bundled_dir, sizeof bundled_dir, meta) && fgets(bundled_root, sizeof bundled_root, meta);
            valid = valid && strchr(bundled_name, '\n') && strchr(bundled_dir, '\n') && strchr(bundled_root, '\n');
            fclose(meta);
            if (!valid) {
                bdsp_app_alert("BDSP: mod build", "This app has invalid mod metadata. Rebuild it with the installer.");
                exit(2);
            }
            bundled_name[strcspn(bundled_name, "\r\n")] = 0;
            bundled_dir[strcspn(bundled_dir, "\r\n")] = 0;
            bundled_root[strcspn(bundled_root, "\r\n")] = 0;
            if (!bundled_name[0] || bundled_dir[0] != '/' || bundled_root[0] != '/') {
                bdsp_app_alert("BDSP: mod build", "This app has an invalid mod name or folder.");
                exit(2);
            }
            snprintf(dir, sizeof dir, "%s", bundled_dir);
        }
    }
    mkdir_p(dir);
    setenv("BDSP_MODS_DIR", dir, 1);
    ModInfo list[MODS_MAX];
    int n = mods_scan(dir, list, MODS_MAX);
    const char *want = bundled_name[0] ? bundled_name : getenv("BDSP_MOD");
    if (!bundled_name[0]) for (int i = 1; i + 1 < argc; i++) if (!strcmp(argv[i], "--mod")) want = argv[i + 1];
    int pick = -1;   // index in list; -1: the game
    if (want && *want) {
        if (bundled_name[0] || (strcasecmp(want, "none") && strcasecmp(want, "diamond"))) {
            for (int i = 0; i < n && pick < 0; i++) {
                if (bundled_name[0] ? !strcmp(list[i].root, bundled_root) : !strcasecmp(list[i].name, want)) pick = i;
            }
            if (pick < 0) {
                char msg[2048];
                snprintf(msg, sizeof msg, "There is no mod \"%s\" in %s (%d found).", want, dir, n);
                bdsp_app_alert("BDSP: mod not found", msg);
                exit(2);
            }
        }
    } else if (n > 0 && !g_app.headless) {
        char last[256] = "";
        pref_string("bdsp_mod", last, sizeof last);
        int preselect = 0;   // 0: the game, i + 1: list[i]
        for (int i = 0; i < n; i++) if (!strcmp(list[i].name, last)) preselect = i + 1;
        CFPropertyListRef ask_pref = CFPreferencesCopyAppValue(CFSTR("bdsp_mod_ask"), kCFPreferencesCurrentApplication);
        int ask = !(ask_pref && CFGetTypeID(ask_pref) == CFBooleanGetTypeID() && !CFBooleanGetValue(ask_pref));
        if (ask_pref) CFRelease(ask_pref);
        if (!ask && (CGEventSourceFlagsState(kCGEventSourceStateCombinedSessionState) & kCGEventFlagMaskAlternate)) ask = 1;
        int choice = preselect;
        if (ask) {
            const char *names[MODS_MAX];
            for (int i = 0; i < n; i++) names[i] = list[i].name;
            int again = 1;
            choice = bdsp_app_pick_game(names, n, preselect, &again);
            if (choice < 0) exit(0);
            pref_set("bdsp_mod_ask", again ? kCFBooleanTrue : kCFBooleanFalse);
        }
        pick = choice - 1;
        CFStringRef v = CFStringCreateWithCString(NULL, pick >= 0 ? list[pick].name : "", kCFStringEncodingUTF8);
        pref_set("bdsp_mod", v);
        CFRelease(v);
    }
    if (pick >= 0) {
        if (bundled_name[0]) {
            snprintf(list[pick].name, sizeof list[pick].name, "%s", bundled_name);
            setenv("BDSP_COMPILED_EXEFS", bundled_name, 1);
        }
        if (mods_activate(&list[pick], g_app.save) != 0) {
            bdsp_app_alert("BDSP: mod", "The save folder of the mod could not be created.");
            exit(2);
        }
        snprintf(g_app.save, sizeof g_app.save, "%s", mods_active_save());
    }
}

void bdsp_app_init(int argc, char **argv) {
    // Metal HUD (menu View > Debug): MTL_HUD_ENABLED is read at start, hence here and before any Metal initialisation
    Boolean hud_valid = false;
    if (CFPreferencesGetAppBooleanValue(CFSTR("bdsp_metal_hud"), kCFPreferencesCurrentApplication, &hud_valid) && hud_valid && !getenv("BDSP_NO_HUD")) {   // BDSP_NO_HUD=1: measurement runs without HUD
        setenv("MTL_HUD_ENABLED", "1", 1);
        printf("[app] Metal-HUD an (Start)\n");
    }
    g_app.argc = argc;
    g_app.argv = argv;
    char raw[1024];
    uint32_t sz = sizeof raw;
    if (_NSGetExecutablePath(raw, &sz) != 0 || !realpath(raw, g_app.exe)) snprintf(g_app.exe, sizeof g_app.exe, "%s", argv[0]);
    // <X>.app/Contents/MacOS/<exe>
    char *m = strstr(g_app.exe, ".app/Contents/MacOS/");
    if (m) {
        snprintf(g_app.bundle, sizeof g_app.bundle, "%.*s.app", (int)(m - g_app.exe), g_app.exe);
        snprintf(g_app.resources, sizeof g_app.resources, "%s/Contents/Resources", g_app.bundle);
    } else if (getenv("BDSP_RESOURCES")) {
        absolutize(g_app.resources, sizeof g_app.resources, getenv("BDSP_RESOURCES"));
    }
    for (int i = 1; i < argc; i++) if (!strcmp(argv[i], "--headless")) g_app.headless = 1;
    if (getenv("BDSP_NO_ALERT")) g_app.headless = 1;

    const char *home = getenv("HOME");
    if (!home) home = "/tmp";
    char def_home[1100], def_cache[1100], def_logs[1100];
    snprintf(def_home, sizeof def_home, "%s/Library/Application Support/dev.local.xnubdsp", home);
    snprintf(def_cache, sizeof def_cache, "%s/Library/Caches/dev.local.xnubdsp", home);
    snprintf(def_logs, sizeof def_logs, "%s/Library/Logs/dev.local.xnubdsp", home);
    pick_path(g_app.home, sizeof g_app.home, "BDSP_HOME", NULL, def_home);
    mkdir_p(g_app.home);

    char (*keys)[32] = calloc(64, 32);
    char (*vals)[1024] = calloc(64, 1024);
    int n = 0;
    char cfgdef[1100];
    snprintf(cfgdef, sizeof cfgdef, "%s/config.ini", g_app.home);
    pick_path(g_app.config, sizeof g_app.config, "BDSP_CONFIG", NULL, cfgdef);
    FILE *f = fopen(g_app.config, "r");
    if (f) {
        char line[1200];
        while (n < 64 && fgets(line, sizeof line, f)) {
            char *c = strchr(line, '#');
            if (c) *c = 0;
            char *eq = strchr(line, '=');
            if (!eq) continue;
            *eq = 0;
            trim(line);
            trim(eq + 1);
            if (!*line) continue;
            snprintf(keys[n], 32, "%s", line);
            snprintf(vals[n], 1024, "%s", eq + 1);
            n++;
        }
        fclose(f);
    }

    char d_romfs[1100], d_save[1100];
    snprintf(d_romfs, sizeof d_romfs, "%s/romfs", g_app.home);
    snprintf(d_save, sizeof d_save, "%s/save", g_app.home);
    pick_path(g_app.romfs, sizeof g_app.romfs, "BDSP_ROMFS", cfg_get(keys, vals, n, "romfs"), d_romfs);
    pick_path(g_app.save, sizeof g_app.save, "BDSP_SAVE", cfg_get(keys, vals, n, "save"), d_save);
    pick_path(g_app.cache, sizeof g_app.cache, "BDSP_CACHE", cfg_get(keys, vals, n, "cache"), def_cache);
    pick_path(g_app.logs, sizeof g_app.logs, "BDSP_LOG_DIR", cfg_get(keys, vals, n, "logs"), def_logs);
    for (int i = 1; i + 1 < argc; i++) if (!strcmp(argv[i], "--save")) {   // runtime option: takes effect before the configuration
        absolutize(g_app.save, sizeof g_app.save, argv[i + 1]);
    }
    const char *pl = getenv("BDSP_PAD_LAYOUT");
    if (!pl) pl = cfg_get(keys, vals, n, "pad_layout");
    snprintf(g_app.pad_layout, sizeof g_app.pad_layout, "%s", pl && !strcmp(pl, "xbox") ? "xbox" : "nintendo");
    g_app.pause_on_focus_loss = cfg_int("BDSP_PAUSE_ON_FOCUS_LOSS", cfg_get(keys, vals, n, "pause_on_focus_loss"), 0);
    g_app.fullscreen = cfg_int("BDSP_FULLSCREEN", cfg_get(keys, vals, n, "fullscreen"), 0);
    g_app.backups = cfg_int("BDSP_BACKUPS", cfg_get(keys, vals, n, "backups"), 10);
    bdsp_set_fps(cfg_int("BDSP_FPS", cfg_get(keys, vals, n, "fps"), 60));
    g_app.win_w = 1280;
    g_app.win_h = 720;
    const char *win = getenv("BDSP_WINDOW");
    if (!win) win = cfg_get(keys, vals, n, "window");
    if (win) sscanf(win, "%dx%d", &g_app.win_w, &g_app.win_h);
    const char *lang = cfg_get(keys, vals, n, "language");
    if (lang && *lang) setenv("BDSP_LANG", lang, 0);   // e.g. de-DE, en-US (language the game asks the console for)

    mkdir_p(g_app.save);
    mkdir_p(g_app.cache);
    mkdir_p(g_app.logs);
    redirect_log_if_gui();

    // --import-save <SaveData.bin or folder>: check and install the save, then exit (no window; for scripts)
    for (int i = 1; i + 1 < argc; i++) if (!strcmp(argv[i], "--import-save")) {
        char abs[1200], msg[3000];
        absolutize(abs, sizeof abs, argv[i + 1]);
        int r = bdsp_save_import(abs, msg, sizeof msg);
        fprintf(r == 0 ? stdout : stderr, "%s\n", msg);
        exit(r == 0 ? 0 : 1);
    }
    choose_mod(cfg_get(keys, vals, n, "mods"), argc, argv);   // may point g_app.save at the save folder of a mod
    for (int i = 1; i + 1 < argc; i++) if (!strcmp(argv[i], "--save")) argv[i + 1] = strdup(g_app.save);
    // Environment of the runtime (the command-line options override it later)
    setenv("BDSP_ROMFS", g_app.romfs, 1);
    setenv("BDSP_SAVE", g_app.save, 1);
    char tmp[1200];
    if (g_app.resources[0]) {
        snprintf(tmp, sizeof tmp, "%s/img", g_app.resources);
        setenv("BDSP_IMG", tmp, 0);
        snprintf(tmp, sizeof tmp, "%s/main.npdm", g_app.resources);
        setenv("BDSP_NPDM", tmp, 0);
    }
    setenv("BDSP_TIMEOUT", "2000000000", 0);   // the app runs until the user quits it
    snprintf(tmp, sizeof tmp, "%s/shots", g_app.cache);
    setenv("BDSP_SHOT_DIR", tmp, 0);
    {
        char w[32];
        snprintf(w, sizeof w, "%dx%d", g_app.win_w, g_app.win_h);
        setenv("BDSP_WINDOW", w, 0);
    }
    // Relative paths from the environment and the command line refer to the call: make them absolute before changing the working directory
    static const char *const path_env[] = {"BDSP_IMG", "BDSP_NPDM", "BDSP_IL2SYM", "BDSP_SHOT_DIR", "BDSP_SHOT_PATH", NULL};
    for (int i = 0; path_env[i]; i++) {
        const char *v = getenv(path_env[i]);
        char a[1200];
        if (v && *v && v[0] != '/') { absolutize(a, sizeof a, v); setenv(path_env[i], a, 1); }
    }
    for (int i = 1; i + 1 < argc; i++) if (!strcmp(argv[i], "--input-script") && argv[i + 1][0] == '@' && argv[i + 1][1] != '/') {
        char a[1200], b[1300];
        absolutize(a, sizeof a, argv[i + 1] + 1);
        snprintf(b, sizeof b, "@%s", a);
        argv[i + 1] = strdup(b);
    }
    // Working directory in the cache: the NVN layer writes relative to work/recomp/cache/shaders (shader cache). The folder "cache"
    // there is a link to the app's cache folder, so nothing is created in the repo or in the application folder.
    char cwd[1200], p[1400];
    snprintf(cwd, sizeof cwd, "%s/cwd", g_app.cache);
    snprintf(p, sizeof p, "%s/work/recomp", cwd);
    mkdir_p(p);
    snprintf(p, sizeof p, "%s/work/recomp/cache", cwd);
    struct stat st;
    if (lstat(p, &st) != 0 && symlink(g_app.cache, p) != 0) fprintf(stderr, "Note: link %s not created: %s\n", p, strerror(errno));
    if (chdir(cwd) != 0) fprintf(stderr, "Note: working directory %s not reachable: %s\n", cwd, strerror(errno));

    // Preconditions with clear messages
    char msg[2048];
    snprintf(tmp, sizeof tmp, "%s/Data", g_app.romfs);
    if (access(tmp, R_OK) != 0) {
        snprintf(msg, sizeof msg,
                 "The RomFS was not found:\n%s\n\nIt is provided from your own dump when building (scripts/build_all.sh --only recomp) "
                 "or set with the entry romfs = <folder> in %s.", g_app.romfs, g_app.config);
        bdsp_app_alert("BDSP: RomFS missing", msg);
        exit(2);
    }
    if (g_app.resources[0]) {
        snprintf(tmp, sizeof tmp, "%s/img/main.img", g_app.resources);
        if (access(tmp, R_OK) != 0) {
            snprintf(msg, sizeof msg, "The module images are missing in the app:\n%s\n\nThe app was built incompletely (scripts/build_all.sh --only recomp --force).", tmp);
            bdsp_app_alert("BDSP: app incomplete", msg);
            exit(2);
        }
    }
    free(keys);
    free(vals);
    if (bdsp_save_backup_start(msg, sizeof msg) >= 0) fprintf(stderr, "[app] %s\n", msg);
    else fprintf(stderr, "[app] Save backup: %s\n", msg);
    fprintf(stderr, "[app] Data: %s | Save: %s | Cache: %s | Log: %s\n", g_app.romfs, g_app.save, g_app.cache, g_app.logs);
}
