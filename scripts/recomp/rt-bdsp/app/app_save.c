// Spielstand der App: Sicherung beim Start, Import (Ryujinx/Switch), Zurücksetzen. Reines C.
// Das Format bleibt unverändert: <save>/save_1/SaveData.bin und Backup.bin (979.108 Byte, MD5 bei 0xE9818), wie bei Ryujinx/Switch.
#include "app.h"

#include <CommonCrypto/CommonDigest.h>
#include <dirent.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

// MD5 ist hier keine Sicherheitsfunktion, sondern die Prüfsumme des Spielstandformats
#pragma clang diagnostic ignored "-Wdeprecated-declarations"
#define HASH_OFFSET 0xE9818u
#define HASH_LEN 16u
#define LAUNCH_VERSION 0x25
#define CURRENT_VERSION 0x34
// Größe je Version 0x25 … 0x34 (scripts/bdsp_save.py, BINARY_SIZE)
static const uint32_t k_size[] = {0xE9828, 0xE9BE8, 0xED158, 0xED188, 0xED188, 0xED680, 0xEDC20, 0xEDC20, 0xEDC20, 0xEDC20,
                                  0xEDC20, 0xEDC20, 0xEDC20, 0xEED8C, 0xEED8C, 0xEF0A4};

void bdsp_save_dir(char *out, size_t n) { snprintf(out, n, "%s/save_1", g_app.save); }

static void mkdir_p(const char *path) {
    char buf[1400];
    snprintf(buf, sizeof buf, "%s", path);
    for (char *p = buf + 1; *p; p++) {
        if (*p != '/') continue;
        *p = 0;
        mkdir(buf, 0755);
        *p = '/';
    }
    mkdir(buf, 0755);
}

static uint8_t *read_all(const char *path, size_t *len) {
    FILE *f = fopen(path, "rb");
    if (!f) return NULL;
    fseek(f, 0, SEEK_END);
    long n = ftell(f);
    fseek(f, 0, SEEK_SET);
    if (n < 0 || n > (64l << 20)) { fclose(f); return NULL; }
    uint8_t *b = malloc((size_t)n + 1);
    if (!b || fread(b, 1, (size_t)n, f) != (size_t)n) { free(b); fclose(f); return NULL; }
    fclose(f);
    *len = (size_t)n;
    return b;
}

// atomar: erst <pfad>.tmp schreiben und auf die Platte bringen, dann umbenennen
static int write_atomic(const char *path, const void *data, size_t len) {
    char tmp[1500];
    snprintf(tmp, sizeof tmp, "%s.tmp", path);
    FILE *f = fopen(tmp, "wb");
    if (!f) return -1;
    int ok = fwrite(data, 1, len, f) == len && fflush(f) == 0 && fsync(fileno(f)) == 0;
    ok = fclose(f) == 0 && ok;
    if (!ok || rename(tmp, path) != 0) { unlink(tmp); return -1; }
    return 0;
}

static int copy_file(const char *src, const char *dst) {
    size_t n;
    uint8_t *b = read_all(src, &n);
    if (!b) return -1;
    int r = write_atomic(dst, b, n);
    free(b);
    return r;
}

static void sha12(const uint8_t *d, size_t n, char out[13]) {
    unsigned char h[CC_SHA256_DIGEST_LENGTH];
    CC_SHA256(d, (CC_LONG)n, h);
    for (int i = 0; i < 6; i++) snprintf(out + 2 * i, 3, "%02x", h[i]);
}

int bdsp_save_validate(const uint8_t *d, size_t len, char *msg, size_t n) {
    if (len < 4) { snprintf(msg, n, "Datei kürzer als 4 Byte"); return -1; }
    int32_t version = (int32_t)(d[0] | d[1] << 8 | d[2] << 16 | (uint32_t)d[3] << 24);
    if (version < LAUNCH_VERSION || version > CURRENT_VERSION) {
        snprintf(msg, n, "unbekannte Spielstand-Version 0x%X (bekannt: 0x%X bis 0x%X)", (unsigned)version, LAUNCH_VERSION, CURRENT_VERSION);
        return -1;
    }
    uint32_t want = k_size[version - LAUNCH_VERSION];
    if (len != want) { snprintf(msg, n, "falsche Größe: %zu Byte, erwartet %u Byte (Version 0x%X)", len, want, (unsigned)version); return -1; }
    uint8_t *buf = malloc(want);
    if (!buf) { snprintf(msg, n, "kein Speicher"); return -1; }
    memcpy(buf, d, want);
    memset(buf + HASH_OFFSET, 0, HASH_LEN);
    unsigned char h[CC_MD5_DIGEST_LENGTH];
    CC_MD5(buf, want, h);
    free(buf);
    if (memcmp(h, d + HASH_OFFSET, HASH_LEN)) { snprintf(msg, n, "Prüfsumme (MD5 bei 0xE9818) stimmt nicht: Datei beschädigt oder verändert (scripts/bdsp_save.py check/fix-hash)"); return -1; }
    snprintf(msg, n, "Version 0x%X, %u Byte, Prüfsumme gültig", (unsigned)version, want);
    return 0;
}

static void stamp(char *out, size_t n) {
    time_t t = time(NULL);
    struct tm tm;
    localtime_r(&t, &tm);
    strftime(out, n, "%Y%m%d-%H%M%S", &tm);
}

static int cmp_str(const void *a, const void *b) { return strcmp(*(char *const *)a, *(char *const *)b); }

// Namen der Unterordner von <save>/backups mit Präfix, aufsteigend sortiert
static int list_backups(const char *prefix, char ***out) {
    char dir[1300];
    snprintf(dir, sizeof dir, "%s/backups", g_app.save);
    DIR *d = opendir(dir);
    char **v = NULL;
    int n = 0;
    if (d) {
        struct dirent *e;
        while ((e = readdir(d))) {
            if (strncmp(e->d_name, prefix, strlen(prefix))) continue;
            v = realloc(v, (size_t)(n + 1) * sizeof *v);
            v[n++] = strdup(e->d_name);
        }
        closedir(d);
    }
    if (n) qsort(v, (size_t)n, sizeof *v, cmp_str);
    *out = v;
    return n;
}

static void remove_backup(const char *name) {
    char p[1500], q[1700];
    snprintf(p, sizeof p, "%s/backups/%s", g_app.save, name);
    DIR *d = opendir(p);
    if (d) {
        struct dirent *e;
        while ((e = readdir(d))) {
            if (e->d_name[0] == '.') continue;
            snprintf(q, sizeof q, "%s/%s", p, e->d_name);
            unlink(q);
        }
        closedir(d);
    }
    rmdir(p);
}

static int backup_current(const char *kind, char *where, size_t wn) {
    char sd[1300], f1[1400], f2[1400], bd[1500], stampbuf[32];
    bdsp_save_dir(sd, sizeof sd);
    snprintf(f1, sizeof f1, "%s/SaveData.bin", sd);
    snprintf(f2, sizeof f2, "%s/Backup.bin", sd);
    if (access(f1, R_OK) != 0 && access(f2, R_OK) != 0) { where[0] = 0; return 0; }
    stamp(stampbuf, sizeof stampbuf);
    snprintf(bd, sizeof bd, "%s/backups/%s-%s", g_app.save, kind, stampbuf);
    mkdir_p(bd);
    int rc = 0;
    char dst[1700];
    snprintf(dst, sizeof dst, "%s/SaveData.bin", bd);
    if (access(f1, R_OK) == 0 && copy_file(f1, dst) != 0) rc = -1;
    snprintf(dst, sizeof dst, "%s/Backup.bin", bd);
    if (access(f2, R_OK) == 0 && copy_file(f2, dst) != 0) rc = -1;
    snprintf(where, wn, "%s", bd);
    return rc == 0 ? 1 : -1;
}

int bdsp_save_backup_start(char *msg, size_t n) {
    char sd[1300], f1[1400];
    bdsp_save_dir(sd, sizeof sd);
    snprintf(f1, sizeof f1, "%s/SaveData.bin", sd);
    size_t len;
    uint8_t *cur = read_all(f1, &len);
    if (!cur) { snprintf(msg, n, "kein Spielstand unter %s (das Spiel beginnt neu; Import: Menü Spiel)", sd); return 0; }
    char **v;
    int cnt = list_backups("start-", &v);
    int same = 0;
    if (cnt) {   // identisch zur letzten Sicherung: keine neue anlegen
        char last[1700];
        snprintf(last, sizeof last, "%s/backups/%s/SaveData.bin", g_app.save, v[cnt - 1]);
        size_t ln;
        uint8_t *l = read_all(last, &ln);
        same = l && ln == len && !memcmp(l, cur, len);
        free(l);
    }
    for (int i = 0; i < cnt; i++) free(v[i]);
    free(v);
    free(cur);
    if (same) { snprintf(msg, n, "Spielstand unverändert seit der letzten Sicherung (%s/backups)", g_app.save); return 0; }
    char where[1500];
    int r = backup_current("start", where, sizeof where);
    if (r < 0) { snprintf(msg, n, "Sicherung in %s fehlgeschlagen (%s)", where, strerror(errno)); return -1; }
    cnt = list_backups("start-", &v);
    for (int i = 0; i + g_app.backups < cnt; i++) remove_backup(v[i]);
    for (int i = 0; i < cnt; i++) free(v[i]);
    free(v);
    snprintf(msg, n, "Spielstand gesichert: %s", where);
    return 1;
}

static int is_dir(const char *p) { struct stat st; return stat(p, &st) == 0 && S_ISDIR(st.st_mode); }
static int is_file(const char *p) { struct stat st; return stat(p, &st) == 0 && S_ISREG(st.st_mode); }

int bdsp_save_import(const char *path, char *msg, size_t n) {
    char dir[1300] = "", p[1500];
    if (is_dir(path)) {
        // Ordner mit SaveData.bin, Ryujinx-Layout (…/save/<ID>/0) oder unser Ordner (save_1)
        static const char *const sub[] = {"", "/0", "/save_1", "/save/save_1"};
        for (size_t i = 0; i < sizeof sub / sizeof *sub && !dir[0]; i++) {
            snprintf(p, sizeof p, "%s%s/SaveData.bin", path, sub[i]);
            if (is_file(p)) snprintf(dir, sizeof dir, "%s%s", path, sub[i]);
        }
        if (!dir[0]) { snprintf(msg, n, "In %s liegt keine SaveData.bin (auch nicht in 0/ oder save_1/)", path); return -1; }
    } else if (is_file(path)) {
        const char *b = strrchr(path, '/');
        b = b ? b + 1 : path;
        if (strcmp(b, "SaveData.bin") && strcmp(b, "Backup.bin") && strcmp(b, "ExtraData0")) {
            snprintf(msg, n, "%s ist keine Spielstand-Datei (erwartet: SaveData.bin, Backup.bin oder ein Ordner damit)", b);
            return -1;
        }
        snprintf(dir, sizeof dir, "%.*s", (int)(b - path > 1 ? b - path - 1 : 1), path);
    } else { snprintf(msg, n, "%s nicht gefunden", path); return -1; }

    char src_sd[1500], src_bk[1500], src_x[1500], why[300];
    snprintf(src_sd, sizeof src_sd, "%s/SaveData.bin", dir);
    snprintf(src_bk, sizeof src_bk, "%s/Backup.bin", dir);
    size_t len;
    uint8_t *sd = read_all(src_sd, &len);
    if (!sd) { snprintf(msg, n, "%s lässt sich nicht lesen", src_sd); return -1; }
    if (bdsp_save_validate(sd, len, why, sizeof why) != 0) {
        snprintf(msg, n, "SaveData.bin abgelehnt: %s", why);
        free(sd);
        return -1;
    }
    size_t bl = 0;
    uint8_t *bk = read_all(src_bk, &bl);
    int bk_ok = bk && bdsp_save_validate(bk, bl, why, sizeof why) == 0;
    int bk_present = bk != NULL;
    uint8_t user[16];
    int have_user = 0;
    snprintf(src_x, sizeof src_x, "%s/ExtraData0", dir);
    if (!is_file(src_x)) snprintf(src_x, sizeof src_x, "%s/../ExtraData0", dir);
    size_t xl;
    uint8_t *x = read_all(src_x, &xl);
    if (x && xl >= 24) { memcpy(user, x + 8, 16); have_user = 1; }
    free(x);

    char where[1500], sdir[1300], dst[1500];
    int br = backup_current("import", where, sizeof where);
    if (br < 0) { snprintf(msg, n, "Sicherung des bisherigen Spielstands fehlgeschlagen (%s): Import abgebrochen", strerror(errno)); free(sd); free(bk); return -1; }
    bdsp_save_dir(sdir, sizeof sdir);
    mkdir_p(sdir);
    snprintf(dst, sizeof dst, "%s/SaveData.bin", sdir);
    int rc = write_atomic(dst, sd, len);
    snprintf(dst, sizeof dst, "%s/Backup.bin", sdir);
    if (rc == 0) {
        if (bk_ok) rc = write_atomic(dst, bk, bl);
        else unlink(dst);   // ein altes Backup.bin gehört zum bisherigen Stand
    }
    if (rc == 0 && have_user) {
        char hex[40];
        for (int i = 0; i < 16; i++) snprintf(hex + 2 * i, 3, "%02x", user[i]);
        snprintf(dst, sizeof dst, "%s/user_id.hex", g_app.save);
        rc = write_atomic(dst, hex, 32);
    }
    char h[13];
    sha12(sd, len, h);
    free(sd);
    free(bk);
    if (rc != 0) { snprintf(msg, n, "Schreiben nach %s fehlgeschlagen (%s)", sdir, strerror(errno)); return -1; }
    snprintf(msg, n, "Spielstand importiert (SaveData.bin %zu Byte, sha256 %s%s%s). %s%s", len, h,
             bk_ok ? ", Backup.bin übernommen" : (bk_present ? ", Backup.bin ungültig und ausgelassen" : ", ohne Backup.bin"),
             have_user ? ", Benutzer-ID aus ExtraData0" : "", where[0] ? "Bisheriger Stand gesichert in " : "Kein bisheriger Stand.", where);
    return 0;
}

int bdsp_save_reset(char *msg, size_t n) {
    char where[1500], sd[1300], f[1500];
    int r = backup_current("reset", where, sizeof where);
    if (r < 0) { snprintf(msg, n, "Sicherung fehlgeschlagen (%s): nichts gelöscht", strerror(errno)); return -1; }
    bdsp_save_dir(sd, sizeof sd);
    snprintf(f, sizeof f, "%s/SaveData.bin", sd);
    unlink(f);
    snprintf(f, sizeof f, "%s/Backup.bin", sd);
    unlink(f);
    if (r) snprintf(msg, n, "Spielstand zurückgesetzt, alter Stand in %s", where);
    else snprintf(msg, n, "Es war kein Spielstand vorhanden.");
    return 0;
}
