// BC -> ASTC 4x4 / R8 / RG8 conversion for GPUs without BC support (see bctc.h). Own implementation; the approach (BC1
// four-colour blocks map exactly onto 2-bit ASTC weights, the rest is decoded and encoded again) follows MacNativeGames
// (games/totk, nvn_bc1astc.c, MIT). The BC7 partition and anchor tables are the ones of the BC7 specification, taken from
// bcdec (Sergii Kudlai, MIT / Unlicense).
#include "bctc.h"

#include <math.h>
#include <stdlib.h>
#include <string.h>

int bctc_kind(uint32_t f) {
    switch (f) {
    case 0x41: case 0x42: case 0x43: case 0x44: case 0x4D: return BCTC_ASTC;
    case 0x45: case 0x46: case 0x47: case 0x48: case 0x4E: return BCTC_ASTC_SRGB;
    case 0x49: return BCTC_R8;
    case 0x4A: return BCTC_R8S;
    case 0x4B: return BCTC_RG8;
    case 0x4C: return getenv("BDSP_BC5_UNORM") ? BCTC_RG8 : BCTC_RG8S;   // as the BC path in metal.m
    default: return BCTC_NONE;
    }
}

// ------------------------------------------------------------------ BC decoding
static void rgb565(uint16_t c, uint8_t o[4]) {
    uint32_t r = c >> 11, g = (c >> 5) & 63, b = c & 31;
    o[0] = (uint8_t)(r << 3 | r >> 2); o[1] = (uint8_t)(g << 2 | g >> 4); o[2] = (uint8_t)(b << 3 | b >> 2); o[3] = 255;
}

// Colour part of BC1/BC2/BC3; four_only: BC2/BC3 always use the four-colour palette.
static void decode_color(const uint8_t *b, int four_only, uint8_t px[16][4]) {
    uint16_t c0 = (uint16_t)(b[0] | b[1] << 8), c1 = (uint16_t)(b[2] | b[3] << 8);
    uint8_t pal[4][4];
    rgb565(c0, pal[0]);
    rgb565(c1, pal[1]);
    if (c0 > c1 || four_only) {
        for (int c = 0; c < 3; c++) {
            pal[2][c] = (uint8_t)((2 * pal[0][c] + pal[1][c]) / 3);
            pal[3][c] = (uint8_t)((pal[0][c] + 2 * pal[1][c]) / 3);
        }
        pal[2][3] = pal[3][3] = 255;
    } else {
        for (int c = 0; c < 3; c++) pal[2][c] = (uint8_t)((pal[0][c] + pal[1][c]) / 2);
        pal[2][3] = 255;
        memset(pal[3], 0, 4);   // transparent black (Metal's BC1_RGBA, which the BC path uses for both BC1 formats)
    }
    uint32_t idx = (uint32_t)(b[4] | b[5] << 8 | b[6] << 16 | (uint32_t)b[7] << 24);
    for (int i = 0; i < 16; i++) memcpy(px[i], pal[(idx >> (2 * i)) & 3], 4);
}

// a * (n - i) / n + b * i / n, rounded to nearest (as the GPU's BC decoders)
static int mix_round(int a, int b, int i, int n) {
    double v = ((double)a * (n - i) + (double)b * i) / n;
    return (int)lrint(v);
}

// One BC4 channel block (also the alpha of BC3): 16 values
static void decode_bc4(const uint8_t *b, int sgn, uint8_t out[16]) {
    int v[8];
    if (sgn) {
        int r0 = (int8_t)b[0], r1 = (int8_t)b[1];
        if (r0 < -127) r0 = -127;
        if (r1 < -127) r1 = -127;
        v[0] = r0; v[1] = r1;
        if (r0 > r1) for (int i = 1; i < 7; i++) v[i + 1] = mix_round(r0, r1, i, 7);
        else { for (int i = 1; i < 5; i++) v[i + 1] = mix_round(r0, r1, i, 5); v[6] = -127; v[7] = 127; }
    } else {
        int r0 = b[0], r1 = b[1];
        v[0] = r0; v[1] = r1;
        if (r0 > r1) for (int i = 1; i < 7; i++) v[i + 1] = mix_round(r0, r1, i, 7);
        else { for (int i = 1; i < 5; i++) v[i + 1] = mix_round(r0, r1, i, 5); v[6] = 0; v[7] = 255; }
    }
    uint64_t idx = 0;
    for (int i = 0; i < 6; i++) idx |= (uint64_t)b[2 + i] << (8 * i);
    for (int i = 0; i < 16; i++) out[i] = (uint8_t)v[(idx >> (3 * i)) & 7];
}
void bctc_decode_bc4(const uint8_t blk[8], int is_signed, uint8_t out[16]) { decode_bc4(blk, is_signed, out); }

static const uint16_t bc7_p2[64] = {
    0xcccc, 0x8888, 0xeeee, 0xecc8, 0xc880, 0xfeec, 0xfec8, 0xec80,
    0xc800, 0xffec, 0xfe80, 0xe800, 0xffe8, 0xff00, 0xfff0, 0xf000,
    0xf710, 0x008e, 0x7100, 0x08ce, 0x008c, 0x7310, 0x3100, 0x8cce,
    0x088c, 0x3110, 0x6666, 0x366c, 0x17e8, 0x0ff0, 0x718e, 0x399c,
    0xaaaa, 0xf0f0, 0x5a5a, 0x33cc, 0x3c3c, 0x55aa, 0x9696, 0xa55a,
    0x73ce, 0x13c8, 0x324c, 0x3bdc, 0x6996, 0xc33c, 0x9966, 0x0660,
    0x0272, 0x04e4, 0x4e40, 0x2720, 0xc936, 0x936c, 0x39c6, 0x639c,
    0x9336, 0x9cc6, 0x817e, 0xe718, 0xccf0, 0x0fcc, 0x7744, 0xee22,
};
static const uint32_t bc7_p3[64] = {
    0xaa685050, 0x6a5a5040, 0x5a5a4200, 0x5450a0a8, 0xa5a50000, 0xa0a05050, 0x5555a0a0, 0x5a5a5050,
    0xaa550000, 0xaa555500, 0xaaaa5500, 0x90909090, 0x94949494, 0xa4a4a4a4, 0xa9a59450, 0x2a0a4250,
    0xa5945040, 0x0a425054, 0xa5a5a500, 0x55a0a0a0, 0xa8a85454, 0x6a6a4040, 0xa4a45000, 0x1a1a0500,
    0x0050a4a4, 0xaaa59090, 0x14696914, 0x69691400, 0xa08585a0, 0xaa821414, 0x50a4a450, 0x6a5a0200,
    0xa9a58000, 0x5090a0a8, 0xa8a09050, 0x24242424, 0x00aa5500, 0x24924924, 0x24499224, 0x50a50a50,
    0x500aa550, 0xaaaa4444, 0x66660000, 0xa5a0a5a0, 0x50a050a0, 0x69286928, 0x44aaaa44, 0x66666600,
    0xaa444444, 0x54a854a8, 0x95809580, 0x96969600, 0xa85454a8, 0x80959580, 0xaa141414, 0x96960000,
    0xaaaa1414, 0xa05050a0, 0xa0a5a5a0, 0x96000000, 0x40804080, 0xa9a8a9a8, 0xaaaaaa44, 0x2a4a5254,
};
static const uint8_t bc7_a2[64] = {
    15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 2, 8, 2, 2, 8, 8, 15, 2, 8, 2, 2, 8, 8, 2, 2,
    15, 15, 6, 8, 2, 8, 15, 15, 2, 8, 2, 2, 2, 15, 15, 6, 6, 2, 6, 8, 15, 15, 2, 2, 15, 15, 15, 15, 15, 2, 2, 15,
};
static const uint8_t bc7_a3a[64] = {
    3, 3, 15, 15, 8, 3, 15, 15, 8, 8, 6, 6, 6, 5, 3, 3, 3, 3, 8, 15, 3, 3, 6, 10, 5, 8, 8, 6, 8, 5, 15, 15,
    8, 15, 3, 5, 6, 10, 8, 15, 15, 3, 15, 5, 15, 15, 15, 15, 3, 15, 5, 5, 5, 8, 5, 10, 5, 10, 8, 13, 15, 12, 3, 3,
};
static const uint8_t bc7_a3b[64] = {
    15, 8, 8, 3, 15, 15, 3, 8, 15, 15, 15, 15, 15, 15, 15, 8, 15, 8, 15, 3, 15, 8, 15, 8, 3, 15, 6, 10, 15, 15, 10, 8,
    15, 3, 15, 10, 10, 8, 9, 10, 6, 15, 8, 15, 3, 6, 6, 8, 15, 3, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 3, 15, 15, 8,
};
static const int bc7_w2[4] = {0, 21, 43, 64}, bc7_w3[8] = {0, 9, 18, 27, 37, 46, 55, 64},
                 bc7_w4[16] = {0, 4, 9, 13, 17, 21, 26, 30, 34, 38, 43, 47, 51, 55, 60, 64};

typedef struct { const uint8_t *b; int pos; } Bits;
static uint32_t rd(Bits *s, int n) {
    uint32_t v = 0;
    for (int i = 0; i < n; i++, s->pos++) v |= (uint32_t)((s->b[s->pos >> 3] >> (s->pos & 7)) & 1) << i;
    return v;
}
static int bc7_interp(int e0, int e1, int bits, int idx) {
    int w = bits == 2 ? bc7_w2[idx] : bits == 3 ? bc7_w3[idx] : bc7_w4[idx];
    return ((64 - w) * e0 + w * e1 + 32) >> 6;
}

static void decode_bc7(const uint8_t *b, uint8_t px[16][4]) {
    // per mode: subsets, partition bits, rotation bits, index selection bit, colour bits, alpha bits, endpoint p-bits,
    // shared p-bits, index bits, second index bits
    static const uint8_t M[8][10] = {
        {3, 4, 0, 0, 4, 0, 1, 0, 3, 0}, {2, 6, 0, 0, 6, 0, 0, 1, 3, 0}, {3, 6, 0, 0, 5, 0, 0, 0, 2, 0}, {2, 6, 0, 0, 7, 0, 1, 0, 2, 0},
        {1, 0, 2, 1, 5, 6, 0, 0, 2, 3}, {1, 0, 2, 0, 7, 8, 0, 0, 2, 2}, {1, 0, 0, 0, 7, 7, 1, 0, 4, 0}, {2, 6, 0, 0, 5, 5, 1, 0, 2, 0},
    };
    int mode = 0;
    while (mode < 8 && !((b[0] >> mode) & 1)) mode++;
    if (mode == 8) {   // reserved: opaque black, as Metal decodes it
        memset(px, 0, 64);
        for (int i = 0; i < 16; i++) px[i][3] = 255;
        return;
    }
    const uint8_t *m = M[mode];
    Bits s = {b, mode + 1};
    int ns = m[0], part = (int)rd(&s, m[1]), rot = (int)rd(&s, m[2]), isel = (int)rd(&s, m[3]);
    int cb = m[4], ab = m[5], ne = ns * 2;
    int ep[6][4];
    for (int c = 0; c < 3; c++) for (int e = 0; e < ne; e++) ep[e][c] = (int)rd(&s, cb);
    for (int e = 0; e < ne; e++) ep[e][3] = ab ? (int)rd(&s, ab) : 0;
    int pb[6] = {0};
    if (m[6]) for (int e = 0; e < ne; e++) pb[e] = (int)rd(&s, 1);
    if (m[7]) for (int i = 0; i < ns; i++) pb[2 * i] = pb[2 * i + 1] = (int)rd(&s, 1);
    for (int e = 0; e < ne; e++)
        for (int c = 0; c < 4; c++) {
            int bits = c < 3 ? cb : ab;
            if (!bits) { ep[e][c] = 255; continue; }
            int v = ep[e][c];
            if (m[6] || m[7]) { v = v << 1 | pb[e]; bits++; }
            v <<= 8 - bits;
            ep[e][c] = v | v >> bits;
        }
    int sub[16];
    for (int i = 0; i < 16; i++) sub[i] = ns == 2 ? (bc7_p2[part] >> i) & 1 : ns == 3 ? (int)(bc7_p3[part] >> (2 * i)) & 3 : 0;
    int anchor2 = ns == 2 ? bc7_a2[part] : ns == 3 ? bc7_a3a[part] : -1, anchor3 = ns == 3 ? bc7_a3b[part] : -1;
    int ib = m[8], ib2 = m[9], i1[16], i2[16];
    for (int i = 0; i < 16; i++) i1[i] = (int)rd(&s, ib - (i == 0 || i == anchor2 || i == anchor3));
    for (int i = 0; i < 16 && ib2; i++) i2[i] = (int)rd(&s, ib2 - (i == 0));
    for (int i = 0; i < 16; i++) {
        const int *e0 = ep[2 * sub[i]], *e1 = ep[2 * sub[i] + 1];
        int cbits = ib, cidx = i1[i], abits = ib, aidx = i1[i];
        if (ib2) {
            if (isel) { cbits = ib2; cidx = i2[i]; } else { abits = ib2; aidx = i2[i]; }
        }
        int o[4];
        for (int c = 0; c < 3; c++) o[c] = bc7_interp(e0[c], e1[c], cbits, cidx);
        o[3] = bc7_interp(e0[3], e1[3], abits, aidx);
        if (rot) { int t = o[3]; o[3] = o[rot - 1]; o[rot - 1] = t; }
        for (int c = 0; c < 4; c++) px[i][c] = (uint8_t)o[c];
    }
}

void bctc_decode_rgba(uint32_t f, const uint8_t *b, uint8_t px[16][4]) {
    switch (f) {
    case 0x41: case 0x42: case 0x45: case 0x46: decode_color(b, 0, px); break;
    case 0x43: case 0x47:
        decode_color(b + 8, 1, px);
        for (int i = 0; i < 16; i++) px[i][3] = (uint8_t)(((b[i >> 1] >> (4 * (i & 1))) & 15) * 17);
        break;
    case 0x44: case 0x48: {
        uint8_t a[16];
        decode_color(b + 8, 1, px);
        decode_bc4(b, 0, a);
        for (int i = 0; i < 16; i++) px[i][3] = a[i];
        break;
    }
    case 0x4D: case 0x4E: decode_bc7(b, px); break;
    default: memset(px, 0, 64);
    }
}

// ------------------------------------------------------------------ ASTC 4x4 encoding
// Two block kinds, both one partition, a 4x4 weight grid and 8-bit endpoints (no integer sequence encoding needed):
//   CEM 8  (RGB direct)  with 3-bit weights, block mode 0x053: 17 + 48 colour + 48 weight bits
//   CEM 12 (RGBA direct) with 2-bit weights, block mode 0x042: 17 + 64 colour + 32 weight bits
// (BC1 four-colour blocks: CEM 8 with 2-bit weights.) The decoder takes the largest endpoint range that fits the bits
// left over, which is 8 bits per value in all three cases. Weights are stored bit-reversed from the top of the block.
static const int astc_w2[4] = {0, 21, 43, 64}, astc_w3[8] = {0, 9, 18, 27, 37, 46, 55, 64};

static void put(uint8_t *b, int pos, int n, uint32_t v) {
    for (int i = 0; i < n; i++)
        if ((v >> i) & 1) b[(pos + i) >> 3] |= (uint8_t)(1u << ((pos + i) & 7));
}

static void astc_write(uint8_t out[16], int cem, int wbits, const int e0[4], const int e1[4], const uint8_t w[16]) {
    memset(out, 0, 16);
    put(out, 0, 11, wbits == 2 ? 0x042 : 0x053);
    put(out, 13, 4, (uint32_t)cem);
    int nc = cem == 12 ? 4 : 3;
    for (int c = 0; c < nc; c++) { put(out, 17 + 16 * c, 8, (uint32_t)e0[c]); put(out, 25 + 16 * c, 8, (uint32_t)e1[c]); }
    for (int i = 0; i < 16; i++)
        for (int k = 0; k < wbits; k++)
            if ((w[i] >> k) & 1) { int p = 127 - (i * wbits + k); out[p >> 3] |= (uint8_t)(1u << (p & 7)); }
}

// The decoder swaps the endpoints (and applies blue contraction) when the second has the smaller RGB sum: keep it larger.
static void astc_order(int e0[4], int e1[4], uint8_t w[16], int levels) {
    if (e1[0] + e1[1] + e1[2] >= e0[0] + e0[1] + e0[2]) return;
    for (int c = 0; c < 4; c++) { int t = e0[c]; e0[c] = e1[c]; e1[c] = t; }
    for (int i = 0; i < 16; i++) w[i] = (uint8_t)(levels - 1 - w[i]);
}

static int lerp8(int a, int b, int u) { return ((a * 257) * (64 - u) + (b * 257) * u + 32) >> 6 >> 8; }   // as the LDR decoder

// Best weight per texel for fixed endpoints; returns the squared error
static int assign(const uint8_t px[16][4], int nc, const int e0[4], const int e1[4], const int *uw, int levels, uint8_t w[16]) {
    int pal[8][4], err = 0;
    for (int k = 0; k < levels; k++) for (int c = 0; c < 4; c++) pal[k][c] = lerp8(e0[c], e1[c], uw[k]);
    for (int i = 0; i < 16; i++) {
        int best = 1 << 30, bk = 0;
        for (int k = 0; k < levels; k++) {
            int d = 0;
            for (int c = 0; c < nc; c++) { int t = pal[k][c] - px[i][c]; d += t * t; }
            if (d < best) { best = d; bk = k; }
        }
        w[i] = (uint8_t)bk;
        err += best;
    }
    return err;
}

static int clamp8(double v) { return v < 0 ? 0 : v > 255 ? 255 : (int)lrint(v); }

// Endpoints along the principal axis, then two least-squares refinements; nc = 3 (RGB) or 4 (RGBA)
static void fit(const uint8_t px[16][4], int nc, const int *uw, int levels, int e0[4], int e1[4], uint8_t w[16]) {
    double mean[4] = {0}, cov[4][4] = {{0}};
    for (int i = 0; i < 16; i++) for (int c = 0; c < nc; c++) mean[c] += px[i][c] / 16.0;
    for (int i = 0; i < 16; i++)
        for (int a = 0; a < nc; a++)
            for (int b = 0; b < nc; b++) cov[a][b] += (px[i][a] - mean[a]) * (px[i][b] - mean[b]);
    double ax[4] = {1, 1, 1, 1};
    for (int it = 0; it < 8; it++) {
        double n[4] = {0}, len = 0;
        for (int a = 0; a < nc; a++) for (int b = 0; b < nc; b++) n[a] += cov[a][b] * ax[b];
        for (int a = 0; a < nc; a++) len += n[a] * n[a];
        if (len < 1e-9) break;
        len = sqrt(len);
        for (int a = 0; a < nc; a++) ax[a] = n[a] / len;
    }
    double tmin = 1e9, tmax = -1e9;
    for (int i = 0; i < 16; i++) {
        double t = 0;
        for (int c = 0; c < nc; c++) t += (px[i][c] - mean[c]) * ax[c];
        if (t < tmin) tmin = t;
        if (t > tmax) tmax = t;
    }
    for (int c = 0; c < 4; c++) {
        e0[c] = c < nc ? clamp8(mean[c] + ax[c] * tmin) : 255;
        e1[c] = c < nc ? clamp8(mean[c] + ax[c] * tmax) : 255;
    }
    int err = assign(px, nc, e0, e1, uw, levels, w);
    for (int it = 0; it < 2 && err; it++) {
        double a = 0, b = 0, cc = 0, r0[4] = {0}, r1[4] = {0};
        for (int i = 0; i < 16; i++) {
            double t = uw[w[i]] / 64.0;
            a += (1 - t) * (1 - t); b += t * (1 - t); cc += t * t;
            for (int c = 0; c < nc; c++) { r0[c] += (1 - t) * px[i][c]; r1[c] += t * px[i][c]; }
        }
        double det = a * cc - b * b;
        if (fabs(det) < 1e-9) break;
        int n0[4], n1[4];
        uint8_t nw[16];
        for (int c = 0; c < 4; c++) {
            n0[c] = c < nc ? clamp8((cc * r0[c] - b * r1[c]) / det) : 255;
            n1[c] = c < nc ? clamp8((a * r1[c] - b * r0[c]) / det) : 255;
        }
        int ne = assign(px, nc, n0, n1, uw, levels, nw);
        if (ne >= err) break;
        err = ne;
        memcpy(e0, n0, sizeof n0); memcpy(e1, n1, sizeof n1); memcpy(w, nw, 16);
    }
}

void bctc_astc_encode(const uint8_t px[16][4], uint8_t out[16]) {
    int amin = 255, amax = 0;
    for (int i = 0; i < 16; i++) { if (px[i][3] < amin) amin = px[i][3]; if (px[i][3] > amax) amax = px[i][3]; }
    int e0[4], e1[4];
    uint8_t w[16];
    if (amin == 255) {   // opaque: RGB with 3-bit weights
        fit(px, 3, astc_w3, 8, e0, e1, w);
        astc_order(e0, e1, w, 8);
        astc_write(out, 8, 3, e0, e1, w);
        return;
    }
    if (amin == amax) {   // constant alpha: the colour axis alone, alpha in both endpoints
        fit(px, 3, astc_w2, 4, e0, e1, w);
        e0[3] = e1[3] = amin;
    } else {
        fit(px, 4, astc_w2, 4, e0, e1, w);
    }
    astc_order(e0, e1, w, 4);
    astc_write(out, 12, 2, e0, e1, w);
}

// BC1 four-colour blocks: palette (c0, c1, 2/3 c0 + 1/3 c1, 1/3 c0 + 2/3 c1) = 2-bit ASTC weights (0, 3, 1, 2)
void bctc_astc_from_bc1(const uint8_t b[8], uint8_t out[16]) {
    uint16_t c0 = (uint16_t)(b[0] | b[1] << 8), c1 = (uint16_t)(b[2] | b[3] << 8);
    if (c0 <= c1) {   // three-colour block (or transparent texels): decode and encode
        uint8_t px[16][4];
        decode_color(b, 0, px);
        bctc_astc_encode(px, out);
        return;
    }
    static const uint8_t map[4] = {0, 3, 1, 2};
    uint8_t p0[4], p1[4], w[16];
    rgb565(c0, p0);
    rgb565(c1, p1);
    int e0[4] = {p0[0], p0[1], p0[2], 255}, e1[4] = {p1[0], p1[1], p1[2], 255};
    uint32_t idx = (uint32_t)(b[4] | b[5] << 8 | b[6] << 16 | (uint32_t)b[7] << 24);
    for (int i = 0; i < 16; i++) w[i] = map[(idx >> (2 * i)) & 3];
    astc_order(e0, e1, w, 4);
    astc_write(out, 8, 2, e0, e1, w);
}

int bctc_astc_decode(const uint8_t b[16], uint8_t px[16][4]) {
    Bits s = {b, 0};
    uint32_t mode = rd(&s, 11);
    s.pos = 13;
    uint32_t cem = rd(&s, 4);
    int wbits = mode == 0x042 ? 2 : mode == 0x053 ? 3 : 0;
    if (!wbits || (cem != 8 && cem != 12)) return 0;
    int nc = cem == 12 ? 4 : 3, e0[4] = {0, 0, 0, 255}, e1[4] = {0, 0, 0, 255};
    for (int c = 0; c < nc; c++) { e0[c] = (int)rd(&s, 8); e1[c] = (int)rd(&s, 8); }
    const int *uw = wbits == 2 ? astc_w2 : astc_w3;
    for (int i = 0; i < 16; i++) {
        int w = 0;
        for (int k = 0; k < wbits; k++) { int p = 127 - (i * wbits + k); w |= ((b[p >> 3] >> (p & 7)) & 1) << k; }
        for (int c = 0; c < 4; c++) px[i][c] = (uint8_t)lerp8(e0[c], e1[c], uw[w]);
    }
    return 1;
}

// ------------------------------------------------------------------ whole levels
uint8_t *bctc_convert(uint32_t f, const uint8_t *src, uint32_t wb, uint32_t hb, uint32_t d, uint32_t *row, uint32_t *rows) {
    int kind = bctc_kind(f);
    uint64_t nblk = (uint64_t)wb * hb * d;
    if (kind == BCTC_ASTC || kind == BCTC_ASTC_SRGB) {
        uint8_t *out = malloc(nblk * 16);
        int bc1 = f == 0x41 || f == 0x42 || f == 0x45 || f == 0x46, bpb = bc1 ? 8 : 16;
        for (uint64_t i = 0; i < nblk; i++) {
            if (bc1) bctc_astc_from_bc1(src + i * 8, out + i * 16);
            else {
                uint8_t px[16][4];
                bctc_decode_rgba(f, src + i * bpb, px);
                bctc_astc_encode(px, out + i * 16);
            }
        }
        *row = wb * 16;
        *rows = hb;
        return out;
    }
    // BC4/BC5: texels, 1 or 2 bytes each
    int ch = kind == BCTC_RG8 || kind == BCTC_RG8S ? 2 : 1, sgn = kind == BCTC_R8S || kind == BCTC_RG8S, bpb = ch * 8;
    uint32_t w = wb * 4, h = hb * 4;
    uint8_t *out = malloc((uint64_t)w * h * d * ch);
    for (uint32_t z = 0; z < d; z++)
        for (uint32_t by = 0; by < hb; by++)
            for (uint32_t bx = 0; bx < wb; bx++) {
                const uint8_t *b = src + (((uint64_t)z * hb + by) * wb + bx) * bpb;
                uint8_t v[2][16];
                for (int c = 0; c < ch; c++) decode_bc4(b + 8 * c, sgn, v[c]);
                for (int i = 0; i < 16; i++)
                    for (int c = 0; c < ch; c++)
                        out[(((uint64_t)z * h + by * 4 + i / 4) * w + bx * 4 + i % 4) * ch + c] = v[c][i];
            }
    *row = w * ch;
    *rows = h;
    return out;
}
