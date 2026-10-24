// Test of the glyph atlas text (swkbd_text.c) with the user's firmware fonts (BDSP_FIRMWARE_DATA=<folder with fonts/>); skipped without them.
// Optional argument: PGM file with a rendering of a few strings.
#include "../swkbd_text.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int fails;
#define CHECK(x) do { if (!(x)) { printf("ERROR line %d: %s\n", __LINE__, #x); fails++; } } while (0)

static void blit(unsigned char *img, int W, int H, const SwkbdGlyph *g, int n) {
    int aw, ah;
    const unsigned char *at = swkbd_text_atlas(&aw, &ah, NULL);
    for (int i = 0; i < n; i++)
        for (int y = 0; y < (int)(g[i].y1 - g[i].y0); y++)
            for (int x = 0; x < (int)(g[i].x1 - g[i].x0); x++) {
                int px = (int)g[i].x0 + x, py = (int)g[i].y0 + y;
                if (px < 0 || py < 0 || px >= W || py >= H) continue;
                int v = at[((int)(g[i].v0 * ah + 0.5f) + y) * aw + (int)(g[i].u0 * aw + 0.5f) + x];
                if (v > img[py * W + px]) img[py * W + px] = (unsigned char)v;
            }
}

int main(int argc, char **argv) {
    const char *root = getenv("BDSP_FIRMWARE_DATA");
    if (!root || !swkbd_text_open(root)) { printf("swkbd_text_test: no firmware fonts, skipped\n"); return 0; }
    float w1 = swkbd_text_measure("Hello", 30, 0), w2 = swkbd_text_measure("Hello", 30, 2);
    printf("Hello at 30 px: %.2f px, with kern 2: %.2f px\n", w1, w2);
    CHECK(w1 > 40 && w1 < 120);
    CHECK(w2 > w1 + 9 && w2 < w1 + 11);
    CHECK(swkbd_text_measure("", 30, 0) == 0);
    LytItem it;
    memset(&it, 0, sizeof it);
    it.type = LYT_ITEM_TEXT; it.str = "Wie hei\xC3\x9F" "t du denn?"; it.font_size[0] = it.font_size[1] = 30; it.origin = 0;
    float X[4] = {20, 520, 20, 520}, Y[4] = {20, 20, 80, 80};
    SwkbdGlyph g[64];
    swkbd_text_frame_begin();
    int n = swkbd_text_place(&it, 1, X, Y, g, 64);
    printf("placed %d glyphs\n", n);
    CHECK(n == 15);   // 18 characters, 3 of them blanks
    for (int i = 0; i < n; i++) CHECK(g[i].x0 >= 20 && g[i].x1 <= 520 && g[i].y0 >= 20 && g[i].y1 <= 80);
    for (int i = 1; i < n; i++) CHECK(g[i].x0 > g[i - 1].x0);   // left to right
    unsigned v1, v2;
    swkbd_text_atlas(NULL, NULL, &v1);
    swkbd_text_frame_begin();
    CHECK(swkbd_text_place(&it, 1, X, Y, g, 64) == n);
    swkbd_text_atlas(NULL, NULL, &v2);
    CHECK(v1 == v2);   // the second time everything comes from the atlas
    // too long for its box: squeezed in proportion
    float X2[4] = {20, 120, 20, 120};
    n = swkbd_text_place(&it, 1, X2, Y, g, 64);
    CHECK(n > 0 && g[n - 1].x1 <= 121);
    // a character no font has is skipped, the button font's glyphs come from the extra font
    it.str = "A\xEE\x80\x80";   // U+E000
    CHECK(swkbd_text_place(&it, 1, X, Y, g, 64) >= 1);
    // an atlas that runs full is cleared at the next frame and keeps working
    unsigned before;
    swkbd_text_atlas(NULL, NULL, &before);
    for (int i = 0; i < 400; i++) {
        char s[16];
        snprintf(s, sizeof s, "Zq%d", i);
        it.str = s; it.font_size[0] = 14 + (i % 40) * 0.5f;
        if (i % 20 == 0) swkbd_text_frame_begin();
        CHECK(swkbd_text_place(&it, 1, X, Y, g, 64) >= 2);
    }
    if (argc > 1) {
        enum { W = 560, H = 240 };
        unsigned char *img = calloc(W * H, 1);
        const char *lines[] = {("Wie hei\xC3\x9F" "t du denn?"), "ABC abc 123 \xC3\x84\xC3\x96\xC3\x9C", "\xE3\x81\x82\xE3\x81\x84\xE3\x81\x86 \xED\x95\x9C\xEA\xB8\x80"};
        swkbd_text_frame_begin();
        for (int l = 0; l < 3; l++) {
            float Yl[4] = {10 + l * 70.0f, 10 + l * 70.0f, 70 + l * 70.0f, 70 + l * 70.0f};
            it.str = lines[l]; it.font_size[0] = 32;
            n = swkbd_text_place(&it, 1, X, Yl, g, 64);
            blit(img, W, H, g, n);
        }
        FILE *f = fopen(argv[1], "wb");
        fprintf(f, "P5\n%d %d\n255\n", W, H);
        fwrite(img, 1, W * H, f);
        fclose(f);
        free(img);
    }
    swkbd_text_close();
    if (fails) { printf("%d errors\n", fails); return 1; }
    printf("swkbd_text_test: ok\n");
    return 0;
}
