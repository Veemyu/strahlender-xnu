// BNTX texture reader (see lyt.h): finds the BRTI texture records, undoes the Tegra block-linear swizzle and decodes BC4/BC5 on the CPU.
// ASTC textures are only deswizzled; the renderer hands the blocks to Metal (MTLPixelFormatASTC_4x4_LDR).
#include "lyt.h"

#include <math.h>
#include <stdlib.h>
#include <string.h>

static uint32_t rd32(const uint8_t *b, size_t n, size_t o) {
    uint32_t v = 0;
    if (o + 4 <= n) memcpy(&v, b + o, 4);
    return v;
}
static uint64_t rd64(const uint8_t *b, size_t n, size_t o) {
    uint64_t v = 0;
    if (o + 8 <= n) memcpy(&v, b + o, 8);
    return v;
}

// One GOB column is 64 bytes wide and 8 rows tall; bh is the block height in GOBs. Block coordinates, bpp = bytes per block.
static void deswizzle(uint8_t *out, uint32_t wb, uint32_t hb, uint32_t bpp, uint32_t bh, const uint8_t *data, size_t dn) {
    size_t wg = ((size_t)wb * bpp + 63) / 64;
    for (uint32_t y = 0; y < hb; y++) {
        for (uint32_t x = 0; x < wb; x++) {
            size_t xb = (size_t)x * bpp;
            size_t gob = (size_t)(y / (8 * bh)) * 512 * bh * wg + (xb / 64) * 512 * bh + (size_t)((y % (8 * bh)) / 8) * 512;
            size_t xx = xb % 64, yy = y % 8;
            size_t a = gob + ((xx % 64) / 32) * 256 + ((yy % 8) / 2) * 64 + ((xx % 32) / 16) * 32 + (yy % 2) * 16 + (xx % 16);
            if (a + bpp <= dn) memcpy(out + ((size_t)y * wb + x) * bpp, data + a, bpp);
        }
    }
}

static void bc4_block(const uint8_t *b, uint8_t px[16]) {
    unsigned p[8];
    p[0] = b[0]; p[1] = b[1];
    if (p[0] > p[1]) for (unsigned i = 1; i < 7; i++) p[1 + i] = ((7 - i) * p[0] + i * p[1]) / 7;
    else {
        for (unsigned i = 1; i < 5; i++) p[1 + i] = ((5 - i) * p[0] + i * p[1]) / 5;
        p[6] = 0; p[7] = 255;
    }
    uint64_t bits = 0;
    for (int i = 0; i < 6; i++) bits |= (uint64_t)b[2 + i] << (8 * i);
    for (int i = 0; i < 16; i++) px[i] = (uint8_t)p[(bits >> (3 * i)) & 7];
}

int lyt_texset_open(LytTexSet *t, const uint8_t *src, size_t size) {
    memset(t, 0, sizeof *t);
    if (size < 0x20 || memcmp(src, "BNTX", 4)) return -1;
    t->buf = malloc(size);
    if (!t->buf) return -1;
    memcpy(t->buf, src, size);
    const uint8_t *d = t->buf;
    uint32_t cap = 0;
    for (size_t i = 0; i + 0x80 <= size; i++) {
        if (memcmp(d + i, "BRTI", 4)) continue;
        if (t->ntex == cap) {
            cap = cap ? cap * 2 : 16;
            LytTex *nt = realloc(t->tex, cap * sizeof *nt);
            if (!nt) goto bad;
            t->tex = nt;
        }
        LytTex *x = &t->tex[t->ntex];
        memset(x, 0, sizeof *x);
        x->fmt = rd32(d, size, i + 0x1c);
        x->w = rd32(d, size, i + 0x24);
        x->h = rd32(d, size, i + 0x28);
        x->chan = rd32(d, size, i + 0x58);
        uint32_t lay = rd32(d, size, i + 0x34), isz = rd32(d, size, i + 0x50);
        uint64_t nameoff = rd64(d, size, i + 0x60), ptr = rd64(d, size, i + 0x70);
        if (nameoff + 2 <= size) {
            uint32_t nl = d[nameoff] | d[nameoff + 1] << 8;
            if (nl > 64) nl = 64;
            if (nameoff + 2 + nl <= size) { memcpy(x->name, d + nameoff + 2, nl); x->name[nl] = 0; }
        }
        uint32_t kind = x->fmt >> 8;
        x->block_bytes = (kind == 0x1a || kind == 0x1d) ? 8 : 16;
        x->bw = (x->w + 3) / 4;
        x->bh = (x->h + 3) / 4;
        if (x->w == 0 || x->h == 0 || x->w > 8192 || x->h > 8192) { t->ntex++; continue; }
        uint64_t mip0 = rd64(d, size, ptr);
        if (kind == 0x1a || kind == 0x1d || kind == 0x1e || kind == 0x2d) {
            if (mip0 <= size && isz <= size - mip0) {
                x->blocks = calloc((size_t)x->bw * x->bh, x->block_bytes);
                if (!x->blocks) goto bad;
                deswizzle(x->blocks, x->bw, x->bh, x->block_bytes, 1u << (lay & 7), d + mip0, isz);
            }
        }
        t->ntex++;
        i += 0x7F;
    }
    return 0;
bad:
    lyt_texset_free(t);
    return -1;
}

void lyt_texset_free(LytTexSet *t) {
    for (uint32_t i = 0; i < t->ntex; i++) free(t->tex[i].blocks);
    free(t->tex);
    free(t->buf);
    memset(t, 0, sizeof *t);
}

const LytTex *lyt_texset_find(const LytTexSet *t, const char *name) {
    for (uint32_t i = 0; i < t->ntex; i++)
        if (!strcmp(t->tex[i].name, name)) return &t->tex[i];
    return NULL;
}

int lyt_tex_is_astc(const LytTex *t) { return (t->fmt >> 8) == 0x2d; }

int lyt_tex_decode_raw(const LytTex *t, uint8_t *out) {
    uint32_t kind = t->fmt >> 8;
    if (!t->blocks || (kind != 0x1d && kind != 0x1e)) return 0;
    for (uint32_t by = 0; by < t->bh; by++) {
        for (uint32_t bx = 0; bx < t->bw; bx++) {
            const uint8_t *blk = t->blocks + ((size_t)by * t->bw + bx) * t->block_bytes;
            uint8_t r[16], g[16];
            bc4_block(blk, r);
            if (kind == 0x1e) bc4_block(blk + 8, g);
            for (int i = 0; i < 16; i++) {
                uint32_t x = bx * 4 + i % 4, y = by * 4 + i / 4;
                if (x >= t->w || y >= t->h) continue;
                uint8_t *px = out + ((size_t)y * t->w + x) * 4;
                if (kind == 0x1d) { px[0] = px[1] = px[2] = r[i]; }
                else { px[0] = r[i]; px[1] = g[i]; px[2] = 0; }
                px[3] = 255;
            }
        }
    }
    return 1;
}

void lyt_tex_apply_chan(const LytTex *t, uint8_t *rgba) {
    for (size_t i = 0; i < (size_t)t->w * t->h; i++) {
        uint8_t in[4], *px = rgba + i * 4;
        memcpy(in, px, 4);
        for (int k = 0; k < 4; k++) {
            switch ((t->chan >> (8 * k)) & 0xFF) {
            case 0: px[k] = 0; break;
            case 1: px[k] = 255; break;
            case 2: px[k] = in[0]; break;
            case 3: px[k] = in[1]; break;
            case 4: px[k] = in[2]; break;
            case 5: px[k] = in[3]; break;
            default: px[k] = 0; break;
            }
        }
    }
}

int lyt_tex_decode(const LytTex *t, uint8_t *out) {
    if (!lyt_tex_decode_raw(t, out)) return 0;
    lyt_tex_apply_chan(t, out);
    return 1;
}

// The icon textures are 64 px (the backspace one a single BC4 channel with visible 4x4 blocks) and are drawn at about 75 device pixels. They are
// scaled to twice the size with a Catmull-Rom filter and their alpha edge is sharpened, so the shape stays crisp instead of soft and blocky.
static float cubic(float p0, float p1, float p2, float p3, float t) {
    return p1 + 0.5f * t * (p2 - p0 + t * (2 * p0 - 5 * p1 + 4 * p2 - p3 + t * (3 * (p1 - p2) + p3 - p0)));
}
static uint8_t *upscale2_sharp(const uint8_t *px, int w, int h) {
    int W = w * 2, H = h * 2;
    uint8_t *out = malloc((size_t)W * H * 4);
    if (!out) return NULL;
    for (int y = 0; y < H; y++)
        for (int x = 0; x < W; x++) {
            float sx = (x + 0.5f) / 2 - 0.5f, sy = (y + 0.5f) / 2 - 0.5f;
            int ix = (int)floorf(sx), iy = (int)floorf(sy);
            float fx = sx - ix, fy = sy - iy;
            for (int c = 0; c < 4; c++) {
                float col[4];
                for (int j = 0; j < 4; j++) {
                    int yy = iy - 1 + j; yy = yy < 0 ? 0 : yy >= h ? h - 1 : yy;
                    float v[4];
                    for (int i = 0; i < 4; i++) { int xx = ix - 1 + i; xx = xx < 0 ? 0 : xx >= w ? w - 1 : xx; v[i] = px[((size_t)yy * w + xx) * 4 + c]; }
                    col[j] = cubic(v[0], v[1], v[2], v[3], fx);
                }
                float r = cubic(col[0], col[1], col[2], col[3], fy);
                r = r < 0 ? 0 : r > 255 ? 255 : r;
                if (c == 3) {   // sharpen the edge of the shape
                    float a = r / 255, u = (a - 0.3f) / 0.4f;
                    u = u < 0 ? 0 : u > 1 ? 1 : u;
                    r = 255 * u * u * (3 - 2 * u);
                }
                out[((size_t)y * W + x) * 4 + c] = (uint8_t)(r + 0.5f);
            }
        }
    return out;
}

uint8_t *lyt_tex_to_rgba(const LytTex *t, const uint8_t *raw_astc, int *w, int *h) {
    uint8_t *px = malloc((size_t)t->w * t->h * 4);
    if (!px) return NULL;
    if (raw_astc) { memcpy(px, raw_astc, (size_t)t->w * t->h * 4); lyt_tex_apply_chan(t, px); }
    else if (!lyt_tex_decode(t, px)) { free(px); return NULL; }
    *w = (int)t->w; *h = (int)t->h;
    if (!strncmp(t->name, "Ico", 3)) {
        uint8_t *big = upscale2_sharp(px, *w, *h);
        if (big) { free(px); px = big; *w *= 2; *h *= 2; }
    }
    return px;
}
