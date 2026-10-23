// Debug tool: renders layouts from the user's firmware to a PPM with a plain software rasteriser (no text, no ASTC), to check the scene
// builder (lyt_scene.c) without a graphics API.   lyt_render <firmware dir> <out.ppm> <archive[,archive]> <layout> [layout ...]
// Each layout is drawn in its resting state, on top of the previous ones.
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "../lyt_scene.h"

static uint8_t *fb;
static int W = 1280, H = 720;

static void sample(const LytTex *t, const uint8_t *px, float u, float v, float out[4]) {
    // bilinear, clamp
    float x = u * t->w - 0.5f, y = v * t->h - 0.5f;
    int x0 = (int)floorf(x), y0 = (int)floorf(y);
    float fx = x - x0, fy = y - y0;
    for (int c = 0; c < 4; c++) out[c] = 0;
    for (int j = 0; j < 2; j++)
        for (int i = 0; i < 2; i++) {
            int xx = x0 + i, yy = y0 + j;
            xx = xx < 0 ? 0 : xx >= (int)t->w ? (int)t->w - 1 : xx;
            yy = yy < 0 ? 0 : yy >= (int)t->h ? (int)t->h - 1 : yy;
            float wgt = (i ? fx : 1 - fx) * (j ? fy : 1 - fy);
            for (int c = 0; c < 4; c++) out[c] += wgt * px[((size_t)yy * t->w + xx) * 4 + c] / 255.0f;
        }
}

typedef struct { const LytTex *t; uint8_t *px; } TexPx;
static TexPx *texes; static int ntexes;

static uint8_t *tex_pixels(const LytTex *t) {
    for (int i = 0; i < ntexes; i++) if (texes[i].t == t) return texes[i].px;
    texes = realloc(texes, (size_t)(ntexes + 1) * sizeof *texes);
    uint8_t *px = malloc((size_t)t->w * t->h * 4);
    if (!lyt_tex_decode(t, px)) { free(px); px = NULL; }
    texes[ntexes].t = t; texes[ntexes++].px = px;
    return px;
}

static void tri(const LytItem *it, const uint8_t *px, int a, int b, int c, int second) {
    float minx = fminf(it->x[a], fminf(it->x[b], it->x[c])), maxx = fmaxf(it->x[a], fmaxf(it->x[b], it->x[c]));
    float miny = fminf(it->y[a], fminf(it->y[b], it->y[c])), maxy = fmaxf(it->y[a], fmaxf(it->y[b], it->y[c]));
    float d = (it->y[b] - it->y[c]) * (it->x[a] - it->x[c]) + (it->x[c] - it->x[b]) * (it->y[a] - it->y[c]);
    if (fabsf(d) < 1e-6f) return;
    for (int y = (int)floorf(miny); y <= (int)ceilf(maxy); y++)
        for (int x = (int)floorf(minx); x <= (int)ceilf(maxx); x++) {
            if (x < 0 || y < 0 || x >= W || y >= H) continue;
            float fx = x + 0.5f, fy = y + 0.5f;
            float l0 = ((it->y[b] - it->y[c]) * (fx - it->x[c]) + (it->x[c] - it->x[b]) * (fy - it->y[c])) / d;
            float l1 = ((it->y[c] - it->y[a]) * (fx - it->x[c]) + (it->x[a] - it->x[c]) * (fy - it->y[c])) / d;
            float l2 = 1 - l0 - l1;
            if (l0 < 0 || l1 < 0 || l2 < 0 || (second && l1 == 0)) continue;   // shared diagonal only once
            float col[4], tx[4] = {1, 1, 1, 1};
            for (int k = 0; k < 4; k++) col[k] = (l0 * it->col[a][k] + l1 * it->col[b][k] + l2 * it->col[c][k]) / 255.0f;
            if (px) sample(it->tex, px, l0 * it->uv[a][0] + l1 * it->uv[b][0] + l2 * it->uv[c][0], l0 * it->uv[a][1] + l1 * it->uv[b][1] + l2 * it->uv[c][1], tx);
            float al = col[3] * tx[3] * it->alpha;
            uint8_t *o = fb + ((size_t)y * W + x) * 3;
            for (int k = 0; k < 3; k++) o[k] = (uint8_t)fminf(255, o[k] * (1 - al) + 255 * col[k] * tx[k] * al);
        }
}

int main(int argc, char **argv) {
    if (argc < 5) { fprintf(stderr, "usage: lyt_render <dir> <out.ppm> <archive[,archive]> <layout>...\n"); return 2; }
    const char *names[8];
    int n = 0;
    char *list = strdup(argv[3]);
    for (char *t = strtok(list, ","); t && n < 8; t = strtok(NULL, ",")) names[n++] = t;
    LytBank *b = lytbank_open(argv[1], names, n);
    if (!b) { fprintf(stderr, "no archives\n"); return 1; }
    fb = malloc((size_t)W * H * 3);
    for (int i = 0; i < W * H; i++) { fb[i * 3] = 40; fb[i * 3 + 1] = 44; fb[i * 3 + 2] = 56; }
    for (int a = 4; a < argc; a++) {
        LytInst *in = lytinst_new(b, argv[a]);
        if (!in) { fprintf(stderr, "layout %s not found\n", argv[a]); continue; }
        lytinst_default_state(in);
        LytScene sc = {0};
        lyt_scene_build(&sc, in, 0, 0, 1);
        for (int i = 0; i < sc.n; i++) {
            const LytItem *it = &sc.items[i];
            if (it->type != LYT_ITEM_QUAD) continue;
            uint8_t *px = it->tex ? tex_pixels(it->tex) : NULL;
            if (it->tex && !px) continue;
            tri(it, px, 0, 1, 2, 0);
            tri(it, px, 1, 3, 2, 1);
        }
        fprintf(stderr, "%s: %d items\n", argv[a], sc.n);
        lyt_scene_free(&sc);
        lytinst_free(in);
    }
    FILE *f = fopen(argv[2], "wb");
    fprintf(f, "P6\n%d %d\n255\n", W, H);
    fwrite(fb, 1, (size_t)W * H * 3, f);
    fclose(f);
    lytbank_free(b);
    return 0;
}
