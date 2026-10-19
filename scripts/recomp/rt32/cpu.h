// Speichermodell B (32-Bit-Gastadressen): Zugriffe als *(T*)(g_base + (uint32_t)ea).
// Eigener Code für den Spike (docs/recomp-spike-2.md, Schritt 3). Wird mit -DREBASE32 und vor scripts/recomp/rt im
// Include-Pfad benutzt (-I scripts/recomp/rt32 -I scripts/recomp/rt -I <las>/runtime) und überschreibt die Speicher-
// Makros der Original-cpu.h. Der Generator bleibt unverändert; FP/SIMD muss im C-Modus (--simd c) erzeugt werden,
// weil der Inline-asm-Modus Gastadressen direkt als Hostadressen benutzt.
#pragma once
#include <stdint.h>
// Die Exklusiv-/Acquire-Hilfen der Original-cpu.h benutzen (T *)(uintptr_t)a: umbenennen, unten neu definieren.
#define ldx8 orig_ldx8
#define ldx16 orig_ldx16
#define ldx32 orig_ldx32
#define ldx64 orig_ldx64
#define stx8 orig_stx8
#define stx16 orig_stx16
#define stx32 orig_stx32
#define stx64 orig_stx64
#define lda8 orig_lda8
#define lda16 orig_lda16
#define lda32 orig_lda32
#define lda64 orig_lda64
#define stl8 orig_stl8
#define stl16 orig_stl16
#define stl32 orig_stl32
#define stl64 orig_stl64
#include_next "cpu.h"
#undef ldx8
#undef ldx16
#undef ldx32
#undef ldx64
#undef stx8
#undef stx16
#undef stx32
#undef stx64
#undef lda8
#undef lda16
#undef lda32
#undef lda64
#undef stl8
#undef stl16
#undef stl32
#undef stl64

extern uint8_t *g_base;  // Basis des 4-GiB-Gastfensters (vom Host gesetzt)
#define G2H(a) ((void *)(g_base + (uint32_t)(a)))

#undef LD8
#undef LD16
#undef LD32
#undef LD64
#undef ST8
#undef ST16
#undef ST32
#undef ST64
#define LD8(a)  (*(const u8a *)G2H(a))
#define LD16(a) (*(const u16u *)G2H(a))
#define LD32(a) (*(const u32u *)G2H(a))
#define LD64(a) (*(const u64u *)G2H(a))
#define ST8(a, v)  (*(u8a *)G2H(a) = (uint8_t)(v))
#define ST16(a, v) (*(u16u *)G2H(a) = (uint16_t)(v))
#define ST32(a, v) (*(u32u *)G2H(a) = (uint32_t)(v))
#define ST64(a, v) (*(u64u *)G2H(a) = (uint64_t)(v))

#define EXCL32(N, T)                                                                       \
    static inline uint64_t ldx##N(Cpu *c, uint64_t a) {                                    \
        T v = __atomic_load_n((T *)G2H(a), __ATOMIC_ACQUIRE);                              \
        c->excl_addr = a;                                                                  \
        c->excl_val = v;                                                                   \
        return v;                                                                          \
    }                                                                                      \
    static inline uint32_t stx##N(Cpu *c, uint64_t a, uint64_t v) {                        \
        if (c->excl_addr != a) return 1;                                                   \
        c->excl_addr = ~0ull;                                                              \
        T expected = (T)c->excl_val;                                                       \
        return !__atomic_compare_exchange_n((T *)G2H(a), &expected, (T)v, 0,               \
                                            __ATOMIC_SEQ_CST, __ATOMIC_SEQ_CST);           \
    }                                                                                      \
    static inline uint64_t lda##N(uint64_t a) { return __atomic_load_n((T *)G2H(a), __ATOMIC_ACQUIRE); } \
    static inline void stl##N(uint64_t a, uint64_t v) { __atomic_store_n((T *)G2H(a), (T)v, __ATOMIC_RELEASE); }
EXCL32(8, uint8_t)
EXCL32(16, uint16_t)
EXCL32(32, uint32_t)
EXCL32(64, uint64_t)
