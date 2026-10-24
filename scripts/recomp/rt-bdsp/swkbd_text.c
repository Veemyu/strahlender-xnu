// Text of the on-screen keyboard without a platform text system (see swkbd_text.h).
#include "swkbd_text.h"

#include <math.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define STB_TRUETYPE_IMPLEMENTATION
#define STBTT_STATIC
#include "third_party/stb_truetype.h"

#define ATLAS_W 1024
#define ATLAS_H 512
#define CACHE_SIZE 4096          // glyph entries (power of two); the atlas is cleared when it is more than three quarters full
#define SUBPIXEL 4               // horizontal positions per pixel a glyph is rasterized for

enum { F_STD, F_EXT, F_KO, F_ZHCN, F_ZHTW, F_COUNT };
static const struct { const char *file; } k_fonts[F_COUNT] = {
    {"nintendo_udsg-r_std_003.bfttf"}, {"nintendo_ext_003.bfttf"}, {"nintendo_udsg-r_ko_003.bfttf"},
    {"nintendo_udsg-r_org_zh-cn_003.bfttf"}, {"nintendo_udjxh-db_zh-tw_003.bfttf"},
};

typedef struct { unsigned char *data; stbtt_fontinfo info; int tried, ok; } Font;

typedef struct { uint32_t key; int16_t ax, ay, w, h, ox, oy; uint8_t used; } Entry;   // atlas place, size and the bitmap's offset from the pen / baseline

static struct {
    pthread_mutex_t lock;
    char root[1024];
    Font font[F_COUNT];
    uint8_t *atlas;
    Entry *cache;
    int count, cx, cy, row_h, full;
    unsigned version;
} T = {.lock = PTHREAD_MUTEX_INITIALIZER};

// ---- fonts. The .bfttf files are TrueType with every 32-bit word XORed with a key taken from the first word (first word ^ 0x18029A7F), after an 8 byte header.
static void font_load(int i) {
    Font *f = &T.font[i];
    if (f->tried) return;
    f->tried = 1;
    char path[1200];
    snprintf(path, sizeof path, "%s/fonts/%s", T.root, k_fonts[i].file);
    FILE *fp = fopen(path, "rb");
    if (!fp) return;
    fseek(fp, 0, SEEK_END);
    long n = ftell(fp);
    fseek(fp, 0, SEEK_SET);
    if (n > 16 && n < (32 << 20)) {
        uint8_t *raw = malloc((size_t)n);
        if (raw && fread(raw, 1, (size_t)n, fp) == (size_t)n) {
            uint32_t w0;
            memcpy(&w0, raw, 4);
            uint32_t key = w0 ^ 0x18029A7Fu;
            size_t words = (size_t)n / 4 - 2;
            f->data = malloc(words * 4);
            if (f->data) {
                for (size_t k = 0; k < words; k++) { uint32_t v; memcpy(&v, raw + 8 + k * 4, 4); v ^= key; memcpy(f->data + k * 4, &v, 4); }
                f->ok = stbtt_InitFont(&f->info, f->data, 0);
                if (!f->ok) { free(f->data); f->data = NULL; }
            }
        }
        free(raw);
    }
    fclose(fp);
}

static void fonts_free(void) {
    for (int i = 0; i < F_COUNT; i++) { free(T.font[i].data); memset(&T.font[i], 0, sizeof T.font[i]); }
}

// ---- utf-8
static uint32_t u8_next(const unsigned char **p) {
    const unsigned char *s = *p;
    uint32_t c = *s;
    int n = c >= 0xF0 ? 3 : c >= 0xE0 ? 2 : c >= 0xC0 ? 1 : 0;
    if (n) c &= 0x3Fu >> n;
    s++;
    for (; n && (*s & 0xC0) == 0x80; n--, s++) c = c << 6 | (*s & 0x3F);
    *p = s;
    return c;
}

// The font and glyph that draw a character: the button font for the private use area, the text font, else a Korean / Chinese one.
static int pick(uint32_t cp, int *glyph) {
    if (cp >= 0xE000 && cp <= 0xF8FF && T.font[F_EXT].ok && (*glyph = stbtt_FindGlyphIndex(&T.font[F_EXT].info, (int)cp))) return F_EXT;
    if (T.font[F_STD].ok && (*glyph = stbtt_FindGlyphIndex(&T.font[F_STD].info, (int)cp))) return F_STD;
    for (int i = F_KO; i < F_COUNT; i++) {
        font_load(i);
        if (T.font[i].ok && (*glyph = stbtt_FindGlyphIndex(&T.font[i].info, (int)cp))) return i;
    }
    return -1;
}

// ---- atlas
static void atlas_clear(void) {
    if (T.atlas) memset(T.atlas, 0, (size_t)ATLAS_W * ATLAS_H);
    if (T.cache) memset(T.cache, 0, CACHE_SIZE * sizeof *T.cache);
    T.count = T.cx = T.cy = T.row_h = T.full = 0;
    T.version++;
}

int swkbd_text_open(const char *root) {
    pthread_mutex_lock(&T.lock);
    if (!T.atlas) {
        T.atlas = calloc(1, (size_t)ATLAS_W * ATLAS_H);
        T.cache = calloc(CACHE_SIZE, sizeof *T.cache);
        T.version++;
    }
    if (root && strcmp(root, T.root)) { fonts_free(); snprintf(T.root, sizeof T.root, "%s", root); }
    font_load(F_STD);
    font_load(F_EXT);
    int ok = T.atlas && T.cache && T.font[F_STD].ok;
    pthread_mutex_unlock(&T.lock);
    return ok;
}

void swkbd_text_close(void) {
    pthread_mutex_lock(&T.lock);
    fonts_free();
    free(T.atlas); free(T.cache);
    T.atlas = NULL; T.cache = NULL;
    T.count = T.cx = T.cy = T.row_h = T.full = 0;
    T.version++;
    pthread_mutex_unlock(&T.lock);
}

const uint8_t *swkbd_text_atlas(int *w, int *h, unsigned *version) {
    if (w) *w = ATLAS_W;
    if (h) *h = ATLAS_H;
    if (version) *version = T.version;
    return T.atlas;
}

void swkbd_text_frame_begin(void) {
    pthread_mutex_lock(&T.lock);
    if (T.full || T.count > CACHE_SIZE * 3 / 4) atlas_clear();
    pthread_mutex_unlock(&T.lock);
}

// The cached glyph for a font, glyph, size and horizontal sub-pixel position; rasterized into the atlas on first use. NULL when it does not fit (the atlas is cleared next frame).
static const Entry *glyph_entry(int fi, int glyph, float px, int sub) {
    uint32_t key = (uint32_t)(fi + 1) | (uint32_t)(sub & 3) << 4 | (uint32_t)((int)(px * 8 + 0.5f) & 0xFFF) << 6 | (uint32_t)(glyph & 0x3FFF) << 18;
    uint32_t h = (key * 2654435761u) >> 8;
    Entry *e = NULL;
    for (int n = 0; n < CACHE_SIZE; n++) {
        Entry *c = &T.cache[(h + (uint32_t)n) & (CACHE_SIZE - 1)];
        if (!c->used) { e = c; break; }
        if (c->key == key) return c;
    }
    if (!e) { T.full = 1; return NULL; }
    const stbtt_fontinfo *fi_ = &T.font[fi].info;
    float s = stbtt_ScaleForMappingEmToPixels(fi_, px), shx = (float)sub / SUBPIXEL;
    int x0, y0, x1, y1;
    stbtt_GetGlyphBitmapBoxSubpixel(fi_, glyph, s, s, shx, 0, &x0, &y0, &x1, &y1);
    int w = x1 - x0, hh = y1 - y0;
    if (w < 0 || hh < 0 || w > 512 || hh > 256) return NULL;
    int need_w = w + 2, need_h = hh + 2;   // one pixel around every glyph, so linear filtering never reaches a neighbour
    if (T.cx + need_w > ATLAS_W) { T.cx = 0; T.cy += T.row_h; T.row_h = 0; }
    if (T.cy + need_h > ATLAS_H) { T.full = 1; return NULL; }
    e->key = key; e->used = 1; e->w = (int16_t)w; e->h = (int16_t)hh; e->ox = (int16_t)x0; e->oy = (int16_t)y0;
    e->ax = (int16_t)(T.cx + 1); e->ay = (int16_t)(T.cy + 1);
    if (w > 0 && hh > 0) stbtt_MakeGlyphBitmapSubpixel(fi_, T.atlas + (size_t)e->ay * ATLAS_W + e->ax, w, hh, ATLAS_W, s, s, shx, 0, glyph);
    T.cx += need_w;
    if (need_h > T.row_h) T.row_h = need_h;
    T.count++;
    T.version++;
    return e;
}

// ---- layout
typedef struct { int font, glyph; float adv; } Run;

// Measures and (when out is given) places a string with its pen starting at (x0, baseline). Returns the width.
static float lay_string(const char *utf8, float px, float kern, float x0, float baseline, float gtop, float gh, SwkbdGlyph *out, int max, int *n_out) {
    float x = 0;
    int n = 0, prev_font = -1, prev_glyph = 0;
    for (const unsigned char *p = (const unsigned char *)utf8; *p;) {
        uint32_t cp = u8_next(&p);
        int g = 0, fi = pick(cp, &g);
        if (fi < 0) { x += px * 0.5f + kern; prev_font = -1; continue; }
        const stbtt_fontinfo *info = &T.font[fi].info;
        float s = stbtt_ScaleForMappingEmToPixels(info, px);
        if (fi == prev_font) x += stbtt_GetGlyphKernAdvance(info, prev_glyph, g) * s;
        if (out && n < max) {
            float pos = floorf((x0 + x) * SUBPIXEL + 0.5f) / SUBPIXEL, ix = floorf(pos);
            int sub = (int)((pos - ix) * SUBPIXEL + 0.5f) & (SUBPIXEL - 1);
            const Entry *e = glyph_entry(fi, g, px, sub);
            if (e && e->w > 0 && e->h > 0) {
                SwkbdGlyph *q = &out[n++];
                q->x0 = ix + e->ox; q->y0 = baseline + e->oy; q->x1 = q->x0 + e->w; q->y1 = q->y0 + e->h;
                q->u0 = (float)e->ax / ATLAS_W; q->v0 = (float)e->ay / ATLAS_H;
                q->u1 = (float)(e->ax + e->w) / ATLAS_W; q->v1 = (float)(e->ay + e->h) / ATLAS_H;
                q->g0 = gh > 0 ? (q->y0 - gtop) / gh : 0; q->g1 = gh > 0 ? (q->y1 - gtop) / gh : 0;
                if (q->g0 < 0) q->g0 = 0;
                if (q->g1 > 1) q->g1 = 1;
            }
        }
        int adv, lsb;
        stbtt_GetGlyphHMetrics(info, g, &adv, &lsb);
        x += adv * s + kern;
        prev_font = fi; prev_glyph = g;
    }
    if (n_out) *n_out = n;
    return x;
}

float swkbd_text_measure(const char *utf8, float px, float kern) {
    pthread_mutex_lock(&T.lock);
    float w = T.font[F_STD].ok ? lay_string(utf8, px, kern, 0, 0, 0, 0, NULL, 0, NULL) : 0;
    pthread_mutex_unlock(&T.lock);
    return w;
}

int swkbd_text_place(const LytItem *it, float scale, const float X[4], const float Y[4], SwkbdGlyph *out, int max) {
    if (!it->str || !it->str[0]) return 0;
    float bw = X[3] - X[0], bh = Y[3] - Y[0], px = it->font_size[0] * scale, kern = it->char_space * scale;
    if (px < 4 || bw <= 0 || bh <= 0) return 0;
    int n = 0;
    pthread_mutex_lock(&T.lock);
    if (T.font[F_STD].ok) {
        const stbtt_fontinfo *info = &T.font[F_STD].info;
        int ia, id, il;
        stbtt_GetFontVMetrics(info, &ia, &id, &il);
        float s = stbtt_ScaleForMappingEmToPixels(info, px);
        float asc = ia * s, desc = -id * s;
        float pad = ceilf(px * 0.3f);   // room above and below for accents and descenders: a fixed amount, so the baseline stands at the same place for every string
        asc += pad; desc += pad;
        float w = ceilf(lay_string(it->str, px, kern, 0, 0, 0, 0, NULL, 0, NULL));
        float th = ceilf(asc + desc) + 4;
        int glyph = 0;   // button glyphs are never squeezed
        for (const unsigned char *u = (const unsigned char *)it->str; *u; u++) if (*u == 0xEE) glyph = 1;   // utf-8 lead byte of U+E000..EFFF
        float sx = (w > bw && !glyph) ? bw / w : 1;   // too long for its box: smaller, in proportion
        float drawW = w * sx, drawH = th * sx, padd = pad * sx;
        int ox = it->origin & 3, oy = (it->origin >> 2) & 3;
        float left = X[0] + (ox == 1 ? 0 : ox == 2 ? bw - drawW : (bw - drawW) / 2);
        float top = Y[0] + (oy == 1 ? -padd : oy == 2 ? bh - drawH + padd : (bh - drawH) / 2);
        float baseline = floorf(top + sx * (th - desc - 2) + 0.5f);
        lay_string(it->str, px * sx, kern * sx, left, baseline, top, drawH, out, max, &n);
    }
    pthread_mutex_unlock(&T.lock);
    return n;
}
