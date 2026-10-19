// Gemeinsame Testdaten-Erzeugung und Struktur-Definitionen des Differenzialtests (docs/recomp-diff.md).
// Eigener Code. Deterministisch (splitmix64, fester Startwert je Test); läuft auf Mac und Ryzen identisch und wird
// per ctypes aus difftest.py benutzt. Keine Spielbytes: alle Eingaben sind synthetisch.
#include <math.h>
#include <stdint.h>
#include <string.h>

#include "difftest.h"

typedef struct { uint64_t s; } Rng;
static inline uint64_t rnext(Rng *r) {
    uint64_t z = (r->s += 0x9E3779B97F4A7C15ull);
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ull;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBull;
    return z ^ (z >> 31);
}
static inline uint32_t rbelow(Rng *r, uint32_t n) { return (uint32_t)(rnext(r) % n); }

// ---- Gleitkomma-Spezialwerte je Format (Bits)
static const uint32_t SP32[] = {
    0x00000000, 0x80000000, 0x7f800000, 0xff800000, 0x7fc00000, 0xffc00000, 0x7fc12345, 0xffc00001, 0x7f800001,
    0x7fa00000, 0xff812345, 0x7fffffff, 0xffffffff, 0x00000001, 0x80000001, 0x007fffff, 0x807fffff, 0x00800000,
    0x80800000, 0x7f7fffff, 0xff7fffff, 0x3f800000, 0xbf800000, 0x40000000, 0x3f000000, 0x40400000, 0x4b800000,
    0x4f000000, 0x4f800000, 0x5f000000, 0x5f800000, 0x477fe000, 0x38800000, 0x33800000, 0x3effffff, 0x3f7fffff,
    0x3f800001, 0x4b7fffff, 0x4b000001, 0x00400000, 0x01000000, 0x7e800000, 0x7f000000, 0x3fc00000, 0x40490fdb};
static const uint64_t SP64[] = {
    0x0000000000000000ull, 0x8000000000000000ull, 0x7ff0000000000000ull, 0xfff0000000000000ull, 0x7ff8000000000000ull,
    0xfff8000000000000ull, 0x7ff8123456789abcull, 0xfff0000000000001ull, 0x7ff0000000000001ull, 0x7ff4000000000000ull,
    0xfff1234567890abcull, 0x7fffffffffffffffull, 0xffffffffffffffffull, 0x0000000000000001ull, 0x8000000000000001ull,
    0x000fffffffffffffull, 0x800fffffffffffffull, 0x0010000000000000ull, 0x8010000000000000ull, 0x7fefffffffffffffull,
    0xffefffffffffffffull, 0x3ff0000000000000ull, 0xbff0000000000000ull, 0x4000000000000000ull, 0x3fe0000000000000ull,
    0x4008000000000000ull, 0x4340000000000000ull, 0x41e0000000000000ull, 0x43e0000000000000ull, 0x43f0000000000000ull,
    0x41dfffffffc00000ull, 0x3ff0000000000001ull, 0x433fffffffffffffull, 0x4330000000000001ull, 0x3fefffffffffffffull,
    0x0008000000000000ull, 0x7fe0000000000000ull, 0x3e70000000000000ull, 0x47efffffe0000000ull, 0x36a0000000000000ull};
static const uint16_t SP16[] = {0x0000, 0x8000, 0x7c00, 0xfc00, 0x7e00, 0xfe00, 0x7d00, 0x7c01, 0x7fff, 0xffff, 0x0001,
                                0x03ff, 0x0400, 0x7bff, 0xfbff, 0x3c00, 0xbc00, 0x4000, 0x3800, 0x0200, 0x5640};
#define NSP32 (int)(sizeof SP32 / 4)
#define NSP64 (int)(sizeof SP64 / 8)
#define NSP16 (int)(sizeof SP16 / 2)

static uint32_t gen_f32(Rng *r) {
    uint32_t m = rbelow(r, 100), x;
    uint32_t rnd = (uint32_t)rnext(r);
    if (m < 22) return SP32[rbelow(r, NSP32)];
    if (m < 40) return rnd;
    if (m < 62) return (rnd & 0x807fffff) | ((96 + rbelow(r, 64)) << 23);
    if (m < 72) { x = SP32[rbelow(r, NSP32)]; return x + (int32_t)rbelow(r, 7) - 3; }
    if (m < 82) { // kleine exakte Zahlen: ganze Zahlen / 2^k
        float f = (float)(int32_t)(rbelow(r, 2001) - 1000) / (float)(1u << rbelow(r, 12));
        memcpy(&x, &f, 4);
        return x;
    }
    if (m < 91) return (rnd & 0x807fffff) | (rbelow(r, 5) << 23);   // Denormale / kleinste Normale
    if (m < 96) return (rnd & 0x807fffff) | ((250 + rbelow(r, 5)) << 23); // Überlauf-Nähe
    return (rnd & 0x807fffff) | ((126 + rbelow(r, 4)) << 23);
}
static uint64_t gen_f64(Rng *r) {
    uint32_t m = rbelow(r, 100);
    uint64_t rnd = rnext(r), x;
    if (m < 22) return SP64[rbelow(r, NSP64)];
    if (m < 40) return rnd;
    if (m < 62) return (rnd & 0x800fffffffffffffull) | ((uint64_t)(960 + rbelow(r, 128)) << 52);
    if (m < 72) { x = SP64[rbelow(r, NSP64)]; return x + (int64_t)rbelow(r, 7) - 3; }
    if (m < 82) {
        double f = (double)(int64_t)(rbelow(r, 2001) - 1000) / (double)(1ull << rbelow(r, 30));
        memcpy(&x, &f, 8);
        return x;
    }
    if (m < 91) return (rnd & 0x800fffffffffffffull) | ((uint64_t)rbelow(r, 5) << 52);
    if (m < 96) return (rnd & 0x800fffffffffffffull) | ((uint64_t)(2042 + rbelow(r, 5)) << 52);
    return (rnd & 0x800fffffffffffffull) | ((uint64_t)(1022 + rbelow(r, 4)) << 52);
}
static uint16_t gen_f16(Rng *r) {
    uint32_t m = rbelow(r, 100);
    uint16_t rnd = (uint16_t)rnext(r);
    if (m < 25) return SP16[rbelow(r, NSP16)];
    if (m < 50) return rnd;
    if (m < 80) return (rnd & 0x83ff) | ((8 + rbelow(r, 16)) << 10);
    return (rnd & 0x83ff) | (rbelow(r, 3) << 10);
}

static uint64_t gen_int(Rng *r, int bits) {
    uint64_t mask = bits == 64 ? ~0ull : ((1ull << bits) - 1);
    uint64_t hi = 1ull << (bits - 1);
    uint32_t m = rbelow(r, 100);
    uint64_t rnd = rnext(r), x;
    if (m < 35) return rnd & mask;
    if (m < 65) {
        static const int k[] = {0, 1, 2, 3, 0x7f, 0x80, 0xff, 0x55, 0xaa};
        x = k[rbelow(r, 9)];
        switch (rbelow(r, 6)) {
        case 0: return 0;
        case 1: return mask;
        case 2: return hi & mask;
        case 3: return (hi - 1) & mask;
        case 4: return (-x) & mask;
        default: return x & mask;
        }
    }
    if (m < 85) return (uint64_t)((int64_t)rbelow(r, 65) - 32) & mask;
    if (m < 93) return ((hi - 1 - rbelow(r, 4)) & mask) ^ (rbelow(r, 2) ? 0 : mask);
    return ((rnd & 0x0101010101010101ull) * 0xff) & mask; // Byte-Muster
}

static void gen_reg(Rng *r, uint8_t *dst, int type) {
    uint64_t u[2];
    switch (type) {
    case T_F32: for (int i = 0; i < 4; i++) { uint32_t x = gen_f32(r); memcpy(dst + 4 * i, &x, 4); } return;
    case T_F64: for (int i = 0; i < 2; i++) { uint64_t x = gen_f64(r); memcpy(dst + 8 * i, &x, 8); } return;
    case T_F16: for (int i = 0; i < 8; i++) { uint16_t x = gen_f16(r); memcpy(dst + 2 * i, &x, 2); } return;
    case T_I8: for (int i = 0; i < 16; i++) dst[i] = (uint8_t)gen_int(r, 8); return;
    case T_I16: for (int i = 0; i < 8; i++) { uint16_t x = (uint16_t)gen_int(r, 16); memcpy(dst + 2 * i, &x, 2); } return;
    case T_I32: for (int i = 0; i < 4; i++) { uint32_t x = (uint32_t)gen_int(r, 32); memcpy(dst + 4 * i, &x, 4); } return;
    case T_I64: for (int i = 0; i < 2; i++) { uint64_t x = gen_int(r, 64); memcpy(dst + 8 * i, &x, 8); } return;
    default: u[0] = rnext(r); u[1] = rnext(r); memcpy(dst, u, 16);
    }
}

static uint64_t gen_gpr(Rng *r) {
    switch (rbelow(r, 5)) {
    case 0: return gen_int(r, 64);
    case 1: return gen_int(r, 32) | (rbelow(r, 2) ? (uint64_t)rnext(r) << 32 : 0);
    case 2: return gen_f32(r) | (rbelow(r, 2) ? (uint64_t)rnext(r) << 32 : 0);
    case 3: return gen_f64(r);
    default: { static const uint64_t k[] = {0x1000001ull, 0x20000000000001ull, 0x7fffffffffffffffull, 0x8000000000000000ull,
                                            0xffffffffull, 0x80000000ull, 0x7fffffffull, 0xffffff80ull, 0x1000000ull, 0x2000001ull};
               return k[rbelow(r, 10)]; }
    }
}

// Rundungsnahe Paare: Operand teilweise aus dem vorigen abgeleitet (gleich, negiert, +-1 ulp), FMA-Auslöschung.
static void partner(Rng *r, uint8_t *dst, const uint8_t *prev, int type) {
    int sz = type == T_F32 ? 4 : type == T_F64 ? 8 : 2;
    for (int i = 0; i < 16; i += sz) {
        uint32_t m = rbelow(r, 100);
        if (m >= 14) continue;
        memcpy(dst + i, prev + i, sz);
        if (m < 4) dst[i + sz - 1] ^= 0x80;
        else if (m < 8) { uint64_t x = 0; memcpy(&x, dst + i, sz); x += (int64_t)rbelow(r, 3) - 1; memcpy(dst + i, &x, sz); }
    }
}

void gen_cases(const Desc *d, Case *out, int n) {
    Rng r = {d->seed * 0x2545F4914F6CDD1Dull + 12345};
    static const uint32_t fpcrs[] = {0, 0x400000, 0x800000, 0xc00000, 0x1000000, 0x1400000, 0x1800000, 0x1c00000,
                                     0x2000000, 0x2400000, 0x2800000, 0x2c00000, 0x3000000, 0x3400000, 0x3800000, 0x3c00000};
    for (int i = 0; i < n; i++) {
        Case *c = &out[i];
        memset(c, 0, sizeof *c);
        for (int k = 0; k < 8; k++) {
            gen_reg(&r, c->v[k], d->rt[k]);
            if (k >= 1 && k <= 3 && (d->rt[k] == T_F32 || d->rt[k] == T_F64) && d->rt[k] == d->rt[k - 1]) partner(&r, c->v[k], c->v[k - 1], d->rt[k]);
        }
        // FMA-Auslöschung: c = -(a*b) (auf Registern 1,2,3, gleiche Typen)
        if ((d->flags & DF_FMACANCEL) && rbelow(&r, 100) < 8) {
            if (d->rt[3] == T_F32) for (int l = 0; l < 4; l++) { float a, b, p; memcpy(&a, c->v[1] + 4 * l, 4); memcpy(&b, c->v[2] + 4 * l, 4); p = -(a * b); memcpy(c->v[3] + 4 * l, &p, 4); }
            else if (d->rt[3] == T_F64) for (int l = 0; l < 2; l++) { double a, b, p; memcpy(&a, c->v[1] + 8 * l, 8); memcpy(&b, c->v[2] + 8 * l, 8); p = -(a * b); memcpy(c->v[3] + 8 * l, &p, 8); }
        }
        for (int k = 0; k < 4; k++) c->x[k] = gen_gpr(&r);
        if (d->flags & DF_MEM) {
            c->memflag = 1;
            for (int k = 0; k < 12; k++) gen_reg(&r, c->mem + 16 * k, d->rt[0]);
        }
        c->nzcv = (uint64_t)rbelow(&r, 16) << 28;
        c->fpcr = 0;
        if (d->flags & DF_FPCR) {
            uint32_t m = rbelow(&r, 100);
            if (m >= 40) c->fpcr = fpcrs[rbelow(&r, 16)];
            else if (m >= 30) c->fpcr = fpcrs[rbelow(&r, 4) * 4]; // nur RMode
            if ((d->flags & DF_AHP) && rbelow(&r, 4) == 0) c->fpcr |= 1u << 26;
        }
    }
}
