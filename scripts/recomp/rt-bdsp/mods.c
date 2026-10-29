// Mods: discovery of mod folders, the active mod and its separate save folder (see mods.h). Own code.
#include "mods.h"

#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <sys/stat.h>
#include <unistd.h>
#include "win32_files.h"

#define SCAN_DEPTH 4

static ModInfo g_active;
static int g_have_active;
static char g_active_save[1200];

static int is_dir(const char *p) {
    BdspFileInfo st;
    return stat(p, &st) == 0 && S_ISDIR(st.st_mode);
}

static int cmp_str(const void *a, const void *b) { return strcmp(*(char *const *)a, *(char *const *)b); }

// Sorted names of the sub-folders of dir (without hidden ones); the caller frees the array and the names.
static int list_dirs(const char *dir, char ***names) {
    DIR *d = opendir(dir);
    *names = NULL;
    if (!d) return 0;
    int n = 0, cap = 0;
    struct dirent *e;
    while ((e = readdir(d))) {
        if (e->d_name[0] == '.') continue;
        char p[1500];
        if (snprintf(p, sizeof p, "%s/%s", dir, e->d_name) >= (int)sizeof p || !is_dir(p)) continue;
        if (n == cap) *names = realloc(*names, sizeof **names * (size_t)(cap = cap ? cap * 2 : 16));
        (*names)[n++] = strdup(e->d_name);
    }
    closedir(d);
    if (n) qsort(*names, (size_t)n, sizeof **names, cmp_str);
    return n;
}

// Folder of dir named like want (ignoring case; the Files app and unpacked archives do not keep the case of Switch mods).
static int child_dir(const char *dir, const char *want, char *out, size_t n) {
    DIR *d = opendir(dir);
    if (!d) return 0;
    int ok = 0;
    struct dirent *e;
    while ((e = readdir(d))) {
        if (strcasecmp(e->d_name, want)) continue;
        if (snprintf(out, n, "%s/%s", dir, e->d_name) < (int)n && is_dir(out)) { ok = 1; break; }
    }
    closedir(d);
    if (!ok) out[0] = 0;
    return ok;
}

static void add_mod(const char *dir, const char *name, const char *romfs, const char *exefs, ModInfo *out, int max, int *cnt) {
    if (*cnt >= max) return;
    ModInfo *m = &out[*cnt];
    memset(m, 0, sizeof *m);
    snprintf(m->root, sizeof m->root, "%s", dir);
    snprintf(m->romfs, sizeof m->romfs, "%s", romfs);
    snprintf(m->exefs, sizeof m->exefs, "%s", exefs);
    for (int k = 1;; k++) {   // names are the identity of a mod (save folder): make them unique
        char cand[256];
        if (k == 1) snprintf(cand, sizeof cand, "%s", name);
        else snprintf(cand, sizeof cand, "%.240s (%d)", name, k);
        int dup = 0;
        for (int i = 0; i < *cnt; i++) if (!strcasecmp(out[i].name, cand)) dup = 1;
        if (!dup) { snprintf(m->name, sizeof m->name, "%s", cand); break; }
    }
    (*cnt)++;
}

static void scan_dir(const char *dir, const char *name, int depth, ModInfo *out, int max, int *cnt) {
    char romfs[1200], exefs[1200];
    int has_r = child_dir(dir, "romfs", romfs, sizeof romfs), has_e = child_dir(dir, "exefs", exefs, sizeof exefs);
    if (has_r || has_e) { add_mod(dir, name, romfs, exefs, out, max, cnt); return; }
    if (depth <= 0) return;
    char **sub;
    int n = list_dirs(dir, &sub);
    for (int i = 0; i < n; i++) {
        char p[1500];
        if (snprintf(p, sizeof p, "%s/%s", dir, sub[i]) < (int)sizeof p) scan_dir(p, sub[i], depth - 1, out, max, cnt);
        free(sub[i]);
    }
    free(sub);
}

int mods_scan(const char *mods_dir, ModInfo *out, int max) {
    int cnt = 0;
    if (!mods_dir || !*mods_dir) return 0;
    char **sub;
    int n = list_dirs(mods_dir, &sub);
    for (int i = 0; i < n; i++) {
        char p[1500];
        if (snprintf(p, sizeof p, "%s/%s", mods_dir, sub[i]) < (int)sizeof p) scan_dir(p, sub[i], SCAN_DEPTH - 1, out, max, &cnt);
        free(sub[i]);
    }
    free(sub);
    return cnt;
}

static int mkdir_p(const char *path) {
    char tmp[1400];
    if (snprintf(tmp, sizeof tmp, "%s", path) >= (int)sizeof tmp) return -1;
    for (char *p = tmp + 1; *p; p++) {
        if (*p != '/') continue;
        *p = 0;
        if (mkdir(tmp, 0755) != 0 && errno != EEXIST) return -1;
        *p = '/';
    }
    return mkdir(tmp, 0755) != 0 && errno != EEXIST ? -1 : 0;
}

static void copy_small_file(const char *src, const char *dst) {
    int in = open(src, O_RDONLY);
    if (in < 0) return;
    char buf[4096];
    ssize_t n = read(in, buf, sizeof buf);
    close(in);
    if (n <= 0) return;
    int out = open(dst, O_WRONLY | O_CREAT | O_EXCL, 0644);   // never overwrites
    if (out < 0) return;
    if (write(out, buf, (size_t)n) != n) { close(out); unlink(dst); return; }
    close(out);
}

int mods_activate(const ModInfo *m, const char *saves_dir) {
    return mods_activate_profile(m, saves_dir, NULL);
}

int mods_activate_profile(const ModInfo *m, const char *saves_dir, const char *profile) {
    char root[1500];
    if (profile) {
        if (strlen(profile) != 20) return -1;
        for (const char *p = profile; *p; p++) if (!(*p >= '0' && *p <= '9') && !(*p >= 'a' && *p <= 'f')) return -1;
    }
    if (!m || !saves_dir || !*saves_dir || snprintf(root, sizeof root, "%s/mods/%s", saves_dir, profile ? profile : m->name) >= (int)sizeof root) return -1;
    if (mkdir_p(root) != 0) {
        fprintf(stderr, "[mods] cannot create the save folder %s: %s\n", root, strerror(errno));
        return -1;
    }
    char src[1500], dst[1600];
    snprintf(src, sizeof src, "%s/user_id.hex", saves_dir);
    snprintf(dst, sizeof dst, "%s/user_id.hex", root);
    copy_small_file(src, dst);
    g_active = *m;
    g_have_active = 1;
    snprintf(g_active_save, sizeof g_active_save, "%s", root);
    fprintf(stderr, "[mods] active: %s (romfs %s, exefs %s), own save folder %s\n", m->name, m->romfs[0] ? m->romfs : "-",
            m->exefs[0] ? m->exefs : "-", root);
    DIR *d = m->exefs[0] ? opendir(m->exefs) : NULL;   // the game's code is compiled ahead of time: IPS patches and extra NSOs are not applied yet
    int nexe = 0;
    struct dirent *e;
    while (d && (e = readdir(d))) if (e->d_name[0] != '.' && strcasecmp(e->d_name, "LICENSE") && strcasecmp(e->d_name, "NOTICE")) nexe++;
    if (d) closedir(d);
    const char *compiled = getenv("BDSP_COMPILED_EXEFS");
    if (nexe && compiled && !strcmp(compiled, m->name)) fprintf(stderr, "[mods] ExeFS for %s is already compiled into this app\n", m->name);
    else if (nexe) fprintf(stderr, "[mods] WARNING: %s has %d ExeFS file(s) (code patches); they are not applied, only its RomFS is\n", m->name, nexe);
    return 0;
}

const ModInfo *mods_active(void) { return g_have_active ? &g_active : NULL; }
const char *mods_active_save(void) { return g_have_active ? g_active_save : ""; }

int mods_select_from_env(const char *saves_dir) {
    const char *want = getenv("BDSP_MOD"), *dir = getenv("BDSP_MODS_DIR");
    if (!want || !*want || !strcasecmp(want, "none") || !strcasecmp(want, "diamond")) return 0;
    if (!dir || !*dir) {
        fprintf(stderr, "[mods] BDSP_MOD=%s needs BDSP_MODS_DIR (the folder that holds the mods)\n", want);
        return -1;
    }
    ModInfo list[MODS_MAX];
    int n = mods_scan(dir, list, MODS_MAX);
    for (int i = 0; i < n; i++) {
        if (strcasecmp(list[i].name, want)) continue;
        return mods_activate(&list[i], saves_dir) == 0 ? 1 : -1;
    }
    fprintf(stderr, "[mods] no mod \"%s\" in %s (found %d:", want, dir, n);
    for (int i = 0; i < n; i++) fprintf(stderr, " \"%s\"", list[i].name);
    fprintf(stderr, ")\n");
    return -1;
}
