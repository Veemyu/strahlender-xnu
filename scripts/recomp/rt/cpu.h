// Extension of cpu.h for the exception spike: frame entries for landing pads and setjmp return points.
// Own code. Sits before scripts/recomp/upstream/runtime in the include path (-I scripts/recomp/rt -I scripts/recomp/upstream/runtime)
// and pulls in the original cpu.h via #include_next.
#pragma once
// ---- __builtin_elementwise_* for Clang before 16 (Ubuntu 22.04 ships 14) ----
// Where the compiler has a builtin it is used untouched. Where it is missing, a macro of the same name calls an
// overloaded inline function (Clang's `overloadable`) that handles scalars and the vector types the runtime and the
// generated code use lane by lane. The generator and the vendored simd headers keep using the original names.
#include <stdint.h>
#ifndef __has_builtin
#define __has_builtin(x) 0
#endif
#ifdef BDSP_EW_FORCE_FALLBACK  // the test builds with this to compare the fallbacks with the real builtins
#define EW_HAS_(b) 0
#else
#define EW_HAS_(b) __has_builtin(b)
#endif

#if !EW_HAS_(__builtin_elementwise_abs) || !EW_HAS_(__builtin_elementwise_sqrt) || !EW_HAS_(__builtin_elementwise_fma) || \
    !EW_HAS_(__builtin_elementwise_rint) || !EW_HAS_(__builtin_elementwise_add_sat) || !EW_HAS_(__builtin_elementwise_max)
#define EW_OV_ static inline __attribute__((overloadable, unused))
#define EW_VEC_(T, B) ew_vec_##T##_##B
#define EW_LANES_(V, T) (sizeof(V) / sizeof(T))
#define EW_F1_(name, x) _Generic((x), float: __builtin_##name##f(x), default: __builtin_##name(x))
#define EW_F3_(name, x, y, z) _Generic((x), float: __builtin_##name##f(x, y, z), default: __builtin_##name(x, y, z))
#define EW_UN_(name, V, T, expr) EW_OV_ V ew_##name(V a) { V r; for (unsigned i = 0; i < EW_LANES_(V, T); i++) { T x = a[i]; r[i] = (expr); } return r; }
#define EW_BIN_(name, V, T, expr) EW_OV_ V ew_##name(V a, V b) { V r; for (unsigned i = 0; i < EW_LANES_(V, T); i++) { T x = a[i], y = b[i]; r[i] = (expr); } return r; }
#define EW_TER_(name, V, T, expr) EW_OV_ V ew_##name(V a, V b, V c) { V r; for (unsigned i = 0; i < EW_LANES_(V, T); i++) { T x = a[i], y = b[i], z = c[i]; r[i] = (expr); } return r; }

// Floating point: scalars and vectors; a NaN operand loses in max/min like in the builtin.
#define EW_FP_(T, B)                                                                                   \
    typedef T EW_VEC_(T, B) __attribute__((vector_size(B)));                                          \
    EW_UN_(abs, EW_VEC_(T, B), T, EW_F1_(fabs, x)) EW_UN_(sqrt, EW_VEC_(T, B), T, EW_F1_(sqrt, x))   \
    EW_UN_(rint, EW_VEC_(T, B), T, EW_F1_(rint, x)) EW_UN_(ceil, EW_VEC_(T, B), T, EW_F1_(ceil, x))  \
    EW_UN_(floor, EW_VEC_(T, B), T, EW_F1_(floor, x)) EW_UN_(trunc, EW_VEC_(T, B), T, EW_F1_(trunc, x)) \
    EW_UN_(round, EW_VEC_(T, B), T, EW_F1_(round, x))                                                 \
    EW_TER_(fma, EW_VEC_(T, B), T, EW_F3_(fma, x, y, z))                                              \
    EW_BIN_(max, EW_VEC_(T, B), T, (y != y || x > y) ? x : y) EW_BIN_(min, EW_VEC_(T, B), T, (y != y || x < y) ? x : y)
EW_FP_(float, 16) EW_FP_(float, 8) EW_FP_(double, 16)
#define EW_FP_SCALAR_(T)                                                                               \
    EW_OV_ T ew_abs(T x) { return EW_F1_(fabs, x); } EW_OV_ T ew_sqrt(T x) { return EW_F1_(sqrt, x); } \
    EW_OV_ T ew_rint(T x) { return EW_F1_(rint, x); } EW_OV_ T ew_ceil(T x) { return EW_F1_(ceil, x); } \
    EW_OV_ T ew_floor(T x) { return EW_F1_(floor, x); } EW_OV_ T ew_trunc(T x) { return EW_F1_(trunc, x); } \
    EW_OV_ T ew_round(T x) { return EW_F1_(round, x); } EW_OV_ T ew_fma(T x, T y, T z) { return EW_F3_(fma, x, y, z); } \
    EW_OV_ T ew_max(T x, T y) { return (y != y || x > y) ? x : y; } EW_OV_ T ew_min(T x, T y) { return (y != y || x < y) ? x : y; }
EW_FP_SCALAR_(float) EW_FP_SCALAR_(double)

// Integers: abs, max/min and saturating add/sub. The limits come from the element type.
#define EW_SIGNED_(x) (((__typeof__(x))-1) < 0)
#define EW_SMAX_(x) ((__typeof__(x))((1ull << (sizeof(x) * 8 - 1)) - 1))
#define EW_SMIN_(x) ((__typeof__(x))~EW_SMAX_(x))
#define EW_UMAX_(x) ((__typeof__(x))~(__typeof__(x))0)
#define EW_INT_(T, B)                                                                                  \
    typedef T EW_VEC_(T, B) __attribute__((vector_size(B)));                                          \
    EW_UN_(abs, EW_VEC_(T, B), T, (T)(x < 0 ? 0ull - (unsigned long long)x : (unsigned long long)x))  \
    EW_BIN_(max, EW_VEC_(T, B), T, x > y ? x : y) EW_BIN_(min, EW_VEC_(T, B), T, x < y ? x : y)       \
    EW_BIN_(add_sat, EW_VEC_(T, B), T, ({ T s_; __builtin_add_overflow(x, y, &s_)                     \
        ? (EW_SIGNED_(x) ? (x < 0 ? EW_SMIN_(x) : EW_SMAX_(x)) : EW_UMAX_(x)) : s_; }))               \
    EW_BIN_(sub_sat, EW_VEC_(T, B), T, ({ T s_; __builtin_sub_overflow(x, y, &s_)                     \
        ? (EW_SIGNED_(x) ? (x < 0 ? EW_SMIN_(x) : EW_SMAX_(x)) : (T)0) : s_; }))
#define EW_INT_SIZES_(T) EW_INT_(T, 16) EW_INT_(T, 8)
EW_INT_SIZES_(int8_t) EW_INT_SIZES_(uint8_t) EW_INT_SIZES_(int16_t) EW_INT_SIZES_(uint16_t)
EW_INT_SIZES_(int32_t) EW_INT_SIZES_(uint32_t) EW_INT_SIZES_(int64_t) EW_INT_SIZES_(uint64_t)

#if !EW_HAS_(__builtin_elementwise_abs)
#define __builtin_elementwise_abs(a) ew_abs(a)
#endif
#if !EW_HAS_(__builtin_elementwise_sqrt)
#define __builtin_elementwise_sqrt(a) ew_sqrt(a)
#endif
#if !EW_HAS_(__builtin_elementwise_rint)
#define __builtin_elementwise_rint(a) ew_rint(a)
#endif
#if !EW_HAS_(__builtin_elementwise_ceil)
#define __builtin_elementwise_ceil(a) ew_ceil(a)
#endif
#if !EW_HAS_(__builtin_elementwise_floor)
#define __builtin_elementwise_floor(a) ew_floor(a)
#endif
#if !EW_HAS_(__builtin_elementwise_trunc)
#define __builtin_elementwise_trunc(a) ew_trunc(a)
#endif
#if !EW_HAS_(__builtin_elementwise_round)
#define __builtin_elementwise_round(a) ew_round(a)
#endif
#if !EW_HAS_(__builtin_elementwise_fma)
#define __builtin_elementwise_fma(a, b, c) ew_fma(a, b, c)
#endif
#if !EW_HAS_(__builtin_elementwise_max)
#define __builtin_elementwise_max(a, b) ew_max(a, b)
#endif
#if !EW_HAS_(__builtin_elementwise_min)
#define __builtin_elementwise_min(a, b) ew_min(a, b)
#endif
#if !EW_HAS_(__builtin_elementwise_add_sat)
#define __builtin_elementwise_add_sat(a, b) ew_add_sat(a, b)
#endif
#if !EW_HAS_(__builtin_elementwise_sub_sat)
#define __builtin_elementwise_sub_sat(a, b) ew_sub_sat(a, b)
#endif
#endif

// (The block above must come first: the original cpu.h pulls in simd.h and simd_fp.h, which use these builtins.)
#include_next "cpu.h"
#if defined(_WIN32) && !defined(__USE_MINGW_SETJMP_NON_SEH)
// Guest unwinding owns the EhRec chain; Windows must not unwind host SEH frames.
#define __USE_MINGW_SETJMP_NON_SEH
#endif
#include <setjmp.h>

// One entry per active guest function that contains a re-entry point. Lives on the host stack
// of the generated function; the chain hangs off the Cpu (offset 336, unused padding in the original).
typedef struct EhRec {
    struct EhRec *prev;
    uint64_t lo, hi;   // guest address range of the function
    uint64_t sp;       // guest SP at entry (frames lie below)
    jmp_buf jb;        // _setjmp buffer (without signal mask)
} EhRec;

#define EH_TOP(c) (*(EhRec **)((char *)(c) + 336))
#define EH_ENTER(lo_, hi_)                                              \
    EhRec eh;                                                           \
    eh.prev = EH_TOP(c); eh.lo = (lo_); eh.hi = (hi_); eh.sp = c->sp;   \
    EH_TOP(c) = &eh
#ifdef _WIN32
#define EH_SETJMP() setjmp(eh.jb)
#define EH_LONGJMP(buffer, value) longjmp(buffer, value)
#else
#define EH_SETJMP() _setjmp(eh.jb)
#define EH_LONGJMP(buffer, value) _longjmp(buffer, value)
#endif
#define EH_POP() (EH_TOP(c) = eh.prev)

void rt_nle_enter(Cpu *c) __attribute__((noreturn));   // c->pc = re-entry point in the middle of a function
void rt_nle_fatal(Cpu *c) __attribute__((noreturn));

// ---- Exclusive pairs (LDXP/LDAXP/STXP/STLXP), gate 1: the monitor of the original (cpu.h) remembers only one 64-bit value.
// The second part is added here at Cpu offset 344 (in the unused padding, behind EH_TOP at 336). Memory
// access goes through GPTR(a); memory model B (rt32/cpu.h) replaces GPTR. Success of STXP as on the hardware: 0.
#ifndef GPTR
#define GPTR(a) ((void *)(uintptr_t)(a))
#endif
typedef unsigned __int128 xp128;
#define EXCL_VAL2(c) (*(uint64_t *)((char *)(c) + 344))
static inline void ldxp64(Cpu *c, uint64_t a, void *p, uint64_t *lo, uint64_t *hi) {
    xp128 v = __atomic_load_n((xp128 *)p, __ATOMIC_ACQUIRE);
    c->excl_addr = a;
    c->excl_val = (uint64_t)v;
    EXCL_VAL2(c) = (uint64_t)(v >> 64);
    *lo = (uint64_t)v;
    *hi = (uint64_t)(v >> 64);
}
static inline uint32_t stxp64(Cpu *c, uint64_t a, void *p, uint64_t lo, uint64_t hi) {
    if (c->excl_addr != a) return 1;
    c->excl_addr = ~0ull;
    xp128 expected = ((xp128)EXCL_VAL2(c) << 64) | c->excl_val, desired = ((xp128)hi << 64) | lo;
    return !__atomic_compare_exchange_n((xp128 *)p, &expected, desired, 0, __ATOMIC_SEQ_CST, __ATOMIC_SEQ_CST);
}
static inline void ldxp32(Cpu *c, uint64_t a, void *p, uint64_t *lo, uint64_t *hi) {
    uint64_t v = __atomic_load_n((uint64_t *)p, __ATOMIC_ACQUIRE);
    c->excl_addr = a;
    c->excl_val = v;
    *lo = (uint32_t)v;
    *hi = (uint32_t)(v >> 32);
}
static inline uint32_t stxp32(Cpu *c, uint64_t a, void *p, uint64_t lo, uint64_t hi) {
    if (c->excl_addr != a) return 1;
    c->excl_addr = ~0ull;
    uint64_t expected = c->excl_val, desired = ((uint64_t)(uint32_t)hi << 32) | (uint32_t)lo;
    return !__atomic_compare_exchange_n((uint64_t *)p, &expected, desired, 0, __ATOMIC_SEQ_CST, __ATOMIC_SEQ_CST);
}
