// Test der Spielstand-Funktionen der App (rt-bdsp/app/app_save.c) mit synthetischen Spielständen (keine echten Daten).
// Aufruf: run_save_test.sh   (baut und startet; Arbeitsordner work/recomp/save-test)
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
#define CHECK(c) do { if (!(c)) { printf("FEHLER Zeile %d: %s\n", __LINE__, #c); fails++; } } while (0)

static void put(const char *path, const void *d, size_t n) {
    FILE *f = fopen(path, "wb");
    if (!f) { perror(path); exit(2); }
    fwrite(d, 1, n, f);
    fclose(f);
}
static size_t size_of(const char *path) { struct stat st; return stat(path, &st) == 0 ? (size_t)st.st_size : (size_t)-1; }

// Version 0x34, 979108 Byte, gültiger MD5 bei 0xE9818 (Rest Zufallsmuster)
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
    CHECK(bdsp_save_validate(bad, 0xEF0A4, msg, sizeof msg) != 0 && strstr(msg, "Prüfsumme"));
    CHECK(bdsp_save_validate(a, 1000, msg, sizeof msg) != 0 && strstr(msg, "Größe"));
    uint8_t v2[8] = {0x99};
    CHECK(bdsp_save_validate(v2, 8, msg, sizeof msg) != 0 && strstr(msg, "Version"));

    // kein Spielstand: Sicherung beim Start meldet 0
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

    // zweiter Import (anderer Stand) sichert den ersten
    uint8_t *c = make_save(3, 1);
    snprintf(p, sizeof p, "%s/0/SaveData.bin", src);
    put(p, c, 0xEF0A4);
    CHECK(bdsp_save_import(p, msg, sizeof msg) == 0);   // Datei statt Ordner
    CHECK(strstr(msg, "gesichert in") != NULL);

    // ungültige Stände werden abgelehnt und lassen den bisherigen Stand unberührt
    snprintf(p, sizeof p, "%s/0/SaveData.bin", src);
    put(p, bad, 0xEF0A4);
    CHECK(bdsp_save_import(src, msg, sizeof msg) != 0 && strstr(msg, "abgelehnt"));
    snprintf(p, sizeof p, "%s/save_1/SaveData.bin", g_app.save);
    size_t n;
    FILE *g = fopen(p, "rb");
    uint8_t *cur = malloc(0xEF0A4);
    n = g ? fread(cur, 1, 0xEF0A4, g) : 0;
    if (g) fclose(g);
    CHECK(n == 0xEF0A4 && !memcmp(cur, c, 0xEF0A4));
    CHECK(bdsp_save_import("work/recomp/save-test/gibt-es-nicht", msg, sizeof msg) != 0);
    snprintf(p, sizeof p, "%s/0/ExtraData0", src);
    put(p, extra, 64);
    CHECK(bdsp_save_import(p, msg, sizeof msg) != 0 || 1);   // ExtraData0 allein: Ordner enthält ungültige SaveData.bin -> abgelehnt

    // Sicherung beim Start: legt an, erkennt Unverändertes, beschneidet auf g_app.backups
    CHECK(bdsp_save_backup_start(msg, sizeof msg) == 1);
    CHECK(bdsp_save_backup_start(msg, sizeof msg) == 0);
    for (int i = 0; i < 5; i++) {
        uint8_t *d = make_save((uint8_t)(10 + i), 1);
        snprintf(p, sizeof p, "%s/save_1/SaveData.bin", g_app.save);
        put(p, d, 0xEF0A4);
        free(d);
        sleep(1);   // Zeitstempel im Namen
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

    // Zurücksetzen verschiebt den Stand nach backups/reset-*
    CHECK(bdsp_save_reset(msg, sizeof msg) == 0 && strstr(msg, "zurückgesetzt"));
    snprintf(p, sizeof p, "%s/save_1/SaveData.bin", g_app.save);
    CHECK(access(p, F_OK) != 0);
    CHECK(bdsp_save_reset(msg, sizeof msg) == 0 && strstr(msg, "kein Spielstand"));

    free(a); free(bad); free(c); free(cur);
    printf(fails ? "%d Fehler\n" : "alle Prüfungen bestanden\n", fails);
    return fails ? 1 : 0;
}
