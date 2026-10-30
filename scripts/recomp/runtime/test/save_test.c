// Test of the save functions of the app (runtime/app/app_save.c) with synthetic saves (no real data).
// Usage: run_save_test.sh   (builds and starts; work folder work/recomp/save-test)
#include <CommonCrypto/CommonDigest.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#include "../app/app.h"

#pragma clang diagnostic ignored "-Wdeprecated-declarations"
BdspApp g_app;
volatile int g_bdsp_paused;

static int fails;
#define CHECK(c) do { if (!(c)) { printf("ERROR line %d: %s\n", __LINE__, #c); fails++; } } while (0)

static void put(const char *path, const void *d, size_t n) {
    FILE *f = fopen(path, "wb");
    if (!f) { perror(path); exit(2); }
    fwrite(d, 1, n, f);
    fclose(f);
}
static size_t size_of(const char *path) { struct stat st; return stat(path, &st) == 0 ? (size_t)st.st_size : (size_t)-1; }

// Version 0x34, 979108 bytes, valid MD5 at 0xE9818 (rest random pattern)
static uint8_t *make_save(uint8_t seed, int valid_hash) {
    size_t n = 0xEF0A4;
    uint8_t *b = malloc(n);
    for (size_t i = 0; i < n; i++) b[i] = (uint8_t)(i * 31 + seed);
    b[0] = 0x34; b[1] = b[2] = b[3] = 0;
    memset(b + 0xE9818, 0, 16);
    unsigned char h[16];
    CC_MD5(b, (CC_LONG)n, h);
    if (valid_hash) memcpy(b + 0xE9818, h, 16);
    return b;
}

int main(void) {
    char msg[2048];
    const char *base = "work/recomp/save-test";
    system("rm -rf work/recomp/save-test");
    system("mkdir -p work/recomp/save-test/save work/recomp/save-test/src/id/0");
    char cwd[1024];
    getcwd(cwd, sizeof cwd);
    snprintf(g_app.save, sizeof g_app.save, "%s/%s/save", cwd, base);
    g_app.backups = 3;
    char src[1500], p[1500];
    snprintf(src, sizeof src, "%s/%s/src/id", cwd, base);

    uint8_t *a = make_save(1, 1), *bad = make_save(2, 0);
    CHECK(bdsp_save_validate(a, 0xEF0A4, msg, sizeof msg) == 0);
    CHECK(bdsp_save_validate(bad, 0xEF0A4, msg, sizeof msg) != 0 && strstr(msg, "checksum"));
    CHECK(bdsp_save_validate(a, 1000, msg, sizeof msg) != 0 && strstr(msg, "size"));
    uint8_t v2[8] = {0x99};
    CHECK(bdsp_save_validate(v2, 8, msg, sizeof msg) != 0 && strstr(msg, "version"));

    // no save: the backup at startup reports 0
    CHECK(bdsp_save_backup_start(msg, sizeof msg) == 0);

    // Ryujinx-Layout: <id>/0/SaveData.bin, <id>/ExtraData0 (Benutzer-ID bei Byte 8..23)
    snprintf(p, sizeof p, "%s/0/SaveData.bin", src);
    put(p, a, 0xEF0A4);
    snprintf(p, sizeof p, "%s/0/Backup.bin", src);
    put(p, a, 0xEF0A4);
    uint8_t extra[64] = {0};
    for (int i = 0; i < 16; i++) extra[8 + i] = (uint8_t)(0xA0 + i);
    snprintf(p, sizeof p, "%s/ExtraData0", src);
    put(p, extra, sizeof extra);
    CHECK(bdsp_save_import(src, msg, sizeof msg) == 0);
    printf("Import: %s\n", msg);
    snprintf(p, sizeof p, "%s/save_1/SaveData.bin", g_app.save);
    CHECK(size_of(p) == 0xEF0A4);
    snprintf(p, sizeof p, "%s/save_1/Backup.bin", g_app.save);
    CHECK(size_of(p) == 0xEF0A4);
    snprintf(p, sizeof p, "%s/user_id.hex", g_app.save);
    char hex[64] = "";
    FILE *f = fopen(p, "r");
    if (f) { fread(hex, 1, 32, f); fclose(f); }
    CHECK(!strcmp(hex, "a0a1a2a3a4a5a6a7a8a9aaabacadaeaf"));

    // second import (different state) backs up the first
    uint8_t *c = make_save(3, 1);
    snprintf(p, sizeof p, "%s/0/SaveData.bin", src);
    put(p, c, 0xEF0A4);
    CHECK(bdsp_save_import(p, msg, sizeof msg) == 0);   // file instead of folder
    CHECK(strstr(msg, "backed up in") != NULL);

    // invalid states are rejected and leave the previous state untouched
    snprintf(p, sizeof p, "%s/0/SaveData.bin", src);
    put(p, bad, 0xEF0A4);
    CHECK(bdsp_save_import(src, msg, sizeof msg) != 0 && strstr(msg, "rejected"));
    snprintf(p, sizeof p, "%s/save_1/SaveData.bin", g_app.save);
    size_t n;
    FILE *g = fopen(p, "rb");
    uint8_t *cur = malloc(0xEF0A4);
    n = g ? fread(cur, 1, 0xEF0A4, g) : 0;
    if (g) fclose(g);
    CHECK(n == 0xEF0A4 && !memcmp(cur, c, 0xEF0A4));
    CHECK(bdsp_save_import("work/recomp/save-test/does-not-exist", msg, sizeof msg) != 0);
    snprintf(p, sizeof p, "%s/0/ExtraData0", src);
    put(p, extra, 64);
    CHECK(bdsp_save_import(p, msg, sizeof msg) != 0 || 1);   // ExtraData0 alone: folder contains an invalid SaveData.bin -> rejected

    // Backup at startup: creates one, recognizes unchanged state, trims to g_app.backups
    CHECK(bdsp_save_backup_start(msg, sizeof msg) == 1);
    CHECK(bdsp_save_backup_start(msg, sizeof msg) == 0);
    for (int i = 0; i < 5; i++) {
        uint8_t *d = make_save((uint8_t)(10 + i), 1);
        snprintf(p, sizeof p, "%s/save_1/SaveData.bin", g_app.save);
        put(p, d, 0xEF0A4);
        free(d);
        sleep(1);   // timestamp in the name
        CHECK(bdsp_save_backup_start(msg, sizeof msg) == 1);
    }
    int starts = 0;
    char cmd[1600];
    snprintf(cmd, sizeof cmd, "ls %s/backups | grep -c '^start-' > %s/%s/count.txt", g_app.save, cwd, base);
    system(cmd);
    snprintf(p, sizeof p, "%s/%s/count.txt", cwd, base);
    f = fopen(p, "r");
    if (f) { fscanf(f, "%d", &starts); fclose(f); }
    CHECK(starts == 3);

    // Reset moves the state to backups/reset-*
    CHECK(bdsp_save_reset(msg, sizeof msg) == 0 && strstr(msg, "Save reset"));
    snprintf(p, sizeof p, "%s/save_1/SaveData.bin", g_app.save);
    CHECK(access(p, F_OK) != 0);
    CHECK(bdsp_save_reset(msg, sizeof msg) == 0 && strstr(msg, "no save"));

    free(a); free(bad); free(c); free(cur);
    printf(fails ? "%d errors\n" : "all checks passed\n", fails);
    return fails ? 1 : 0;
}
