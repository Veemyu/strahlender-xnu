// Pfade, Konfiguration und Start der App-Hülle (siehe app.h, docs/recomp-macapp.md). Reines C, kein AppKit.
#include "app.h"

#include <CoreFoundation/CoreFoundation.h>
#include <errno.h>
#include <mach-o/dyld.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
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

// "~" und relative Pfade (gegen das Arbeitsverzeichnis des Aufrufs) in absolute Pfade verwandeln
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

// Konfigurationsdatei: Zeilen "schlüssel = wert", # beginnt einen Kommentar.
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
    // aus Finder/Dock gestartet: stdout zeigt auf /dev/null
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

void bdsp_app_init(int argc, char **argv) {
    // Metal-HUD (Menü Ansicht > Debug): MTL_HUD_ENABLED wird beim Start gelesen, daher hier und vor jeder Metal-Initialisierung
    Boolean hud_valid = false;
    if (CFPreferencesGetAppBooleanValue(CFSTR("bdsp_metal_hud"), kCFPreferencesCurrentApplication, &hud_valid) && hud_valid) {
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
    for (int i = 1; i + 1 < argc; i++) if (!strcmp(argv[i], "--save")) {   // Option der Laufzeit: gilt vor der Konfiguration
        absolutize(g_app.save, sizeof g_app.save, argv[i + 1]);
        argv[i + 1] = strdup(g_app.save);
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
    if (lang && *lang) setenv("BDSP_LANG", lang, 0);   // z. B. de-DE, en-US (Sprache, die das Spiel von der Konsole erfragt)

    mkdir_p(g_app.save);
    mkdir_p(g_app.cache);
    mkdir_p(g_app.logs);
    redirect_log_if_gui();

    // --import-save <SaveData.bin oder Ordner>: Spielstand prüfen, installieren, beenden (ohne Fenster; für Skripte)
    for (int i = 1; i + 1 < argc; i++) if (!strcmp(argv[i], "--import-save")) {
        char abs[1200], msg[3000];
        absolutize(abs, sizeof abs, argv[i + 1]);
        int r = bdsp_save_import(abs, msg, sizeof msg);
        fprintf(r == 0 ? stdout : stderr, "%s\n", msg);
        exit(r == 0 ? 0 : 1);
    }
    // Umgebung der Laufzeit (die Optionen der Kommandozeile überschreiben sie später)
    setenv("BDSP_ROMFS", g_app.romfs, 1);
    setenv("BDSP_SAVE", g_app.save, 1);
    char tmp[1200];
    if (g_app.resources[0]) {
        snprintf(tmp, sizeof tmp, "%s/img", g_app.resources);
        setenv("BDSP_IMG", tmp, 0);
        snprintf(tmp, sizeof tmp, "%s/main.npdm", g_app.resources);
        setenv("BDSP_NPDM", tmp, 0);
    }
    setenv("BDSP_TIMEOUT", "2000000000", 0);   // die App läuft, bis der Nutzer sie beendet
    snprintf(tmp, sizeof tmp, "%s/shots", g_app.cache);
    setenv("BDSP_SHOT_DIR", tmp, 0);
    {
        char w[32];
        snprintf(w, sizeof w, "%dx%d", g_app.win_w, g_app.win_h);
        setenv("BDSP_WINDOW", w, 0);
    }
    // Relative Pfade der Umgebung und der Kommandozeile beziehen sich auf den Aufruf: vor dem Wechsel des Arbeitsverzeichnisses absolut machen
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
    // Arbeitsverzeichnis im Cache: die NVN-Schicht schreibt relativ nach work/recomp/cache/shaders (Shader-Cache). Der Ordner "cache"
    // dort ist ein Verweis auf den Cache-Ordner der App, damit nichts im Repo oder im Anwendungsordner entsteht.
    char cwd[1200], p[1400];
    snprintf(cwd, sizeof cwd, "%s/cwd", g_app.cache);
    snprintf(p, sizeof p, "%s/work/recomp", cwd);
    mkdir_p(p);
    snprintf(p, sizeof p, "%s/work/recomp/cache", cwd);
    struct stat st;
    if (lstat(p, &st) != 0 && symlink(g_app.cache, p) != 0) fprintf(stderr, "Hinweis: Verweis %s nicht angelegt: %s\n", p, strerror(errno));
    if (chdir(cwd) != 0) fprintf(stderr, "Hinweis: Arbeitsverzeichnis %s nicht erreichbar: %s\n", cwd, strerror(errno));

    // Voraussetzungen mit klaren Meldungen
    char msg[2048];
    snprintf(tmp, sizeof tmp, "%s/Data", g_app.romfs);
    if (access(tmp, R_OK) != 0) {
        snprintf(msg, sizeof msg,
                 "Das RomFS wurde nicht gefunden:\n%s\n\nEs wird beim Bauen aus deinem eigenen Dump bereitgestellt (scripts/build_all.sh --only recomp) "
                 "oder per Eintrag romfs = <Ordner> in %s gesetzt.", g_app.romfs, g_app.config);
        bdsp_app_alert("BDSP: RomFS fehlt", msg);
        exit(2);
    }
    if (g_app.resources[0]) {
        snprintf(tmp, sizeof tmp, "%s/img/main.img", g_app.resources);
        if (access(tmp, R_OK) != 0) {
            snprintf(msg, sizeof msg, "Die Modulbilder fehlen in der App:\n%s\n\nDie App wurde unvollständig gebaut (scripts/build_all.sh --only recomp --force).", tmp);
            bdsp_app_alert("BDSP: App unvollständig", msg);
            exit(2);
        }
    }
    free(keys);
    free(vals);
    if (bdsp_save_backup_start(msg, sizeof msg) >= 0) fprintf(stderr, "[app] %s\n", msg);
    else fprintf(stderr, "[app] Sicherung des Spielstands: %s\n", msg);
    fprintf(stderr, "[app] Daten: %s | Spielstand: %s | Cache: %s | Log: %s\n", g_app.romfs, g_app.save, g_app.cache, g_app.logs);
}
