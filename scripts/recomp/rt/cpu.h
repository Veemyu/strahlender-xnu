// Extension of cpu.h for the exception spike: frame entries for landing pads and setjmp return points.
// Own code. Sits before scripts/recomp/upstream/runtime in the include path (-I scripts/recomp/rt -I scripts/recomp/upstream/runtime)
// and pulls in the original cpu.h via #include_next.
#pragma once
#include_next "cpu.h"
#if defined(_WIN32) && !defined(__USE_MINGW_SETJMP_NON_SEH)
// Guest unwinding owns the EhRec chain; Windows must not unwind host SEH frames.
#define __USE_MINGW_SETJMP_NON_SEH
#endif
#include <setjmp.h>

// ---- __builtin_elementwise_* for Clang before 16 (Ubuntu 22.04 ships 14) ----
// Where the compiler has a builtin it is used untouched. Where it is missing, a macro of the same name maps the vector
// lane by lane onto scalar builtins (the auto-vectoriser turns that back into SIMD where the target allows). The generator
// and the vendored simd headers keep using the original names; this header sits before them in the include path.
#ifndef __has_builtin
#define __has_builtin(x) 0
#endif
#ifdef BDSP_EW_FORCE_FALLBACK  // the test builds with this to compare the fallbacks with the real builtins
#define EW_HAS_(b) 0
#else
#define EW_HAS_(b) __has_builtin(b)
#endif

#define EW_LANES_(v) (sizeof(v) / sizeof((v)[0]))

// One operand, one result per lane.
#define EW_MAP1_(a, expr)                                                                         \
    ({ __typeof__(a) ew_a_ = (a); __typeof__(ew_a_) ew_r_;                                        \
       for (unsigned ew_i_ = 0; ew_i_ < EW_LANES_(ew_a_); ew_i_++) {                              \
           __typeof__(ew_a_[0]) x = ew_a_[ew_i_]; ew_r_[ew_i_] = (expr); }                        \
       ew_r_; })
#define EW_MAP2_(a, b, expr)                                                                      \
    ({ __typeof__(a) ew_a_ = (a); __typeof__(ew_a_) ew_b_ = (b); __typeof__(ew_a_) ew_r_;         \
       for (unsigned ew_i_ = 0; ew_i_ < EW_LANES_(ew_a_); ew_i_++) {                              \
           __typeof__(ew_a_[0]) x = ew_a_[ew_i_], y = ew_b_[ew_i_]; ew_r_[ew_i_] = (expr); }      \
       ew_r_; })
#define EW_MAP3_(a, b, c, expr)                                                                   \
    ({ __typeof__(a) ew_a_ = (a); __typeof__(ew_a_) ew_b_ = (b), ew_c_ = (c); __typeof__(ew_a_) ew_r_; \
       for (unsigned ew_i_ = 0; ew_i_ < EW_LANES_(ew_a_); ew_i_++) {                              \
           __typeof__(ew_a_[0]) x = ew_a_[ew_i_], y = ew_b_[ew_i_], z = ew_c_[ew_i_];             \
           ew_r_[ew_i_] = (expr); }                                                               \
       ew_r_; })

// Builtins must be called directly, so the call sits inside each _Generic association.
#define EW_F1_(name, x) _Generic((x), float: __builtin_##name##f(x), default: __builtin_##name(x))
#define EW_F3_(name, x, y, z) _Generic((x), float: __builtin_##name##f(x, y, z), default: __builtin_##name(x, y, z))

#if !EW_HAS_(__builtin_elementwise_abs)
#define __builtin_elementwise_abs(a)                                                              \
    EW_MAP1_(a, _Generic(x, float: __builtin_fabsf(x), double: __builtin_fabs(x),                 \
                         default: (__typeof__(x))(x < 0 ? 0ull - (unsigned long long)x : (unsigned long long)x)))
#endif
#if !EW_HAS_(__builtin_elementwise_sqrt)
#define __builtin_elementwise_sqrt(a) EW_MAP1_(a, EW_F1_(sqrt, x))
#endif
#if !EW_HAS_(__builtin_elementwise_rint)
#define __builtin_elementwise_rint(a) EW_MAP1_(a, EW_F1_(rint, x))
#endif
#if !EW_HAS_(__builtin_elementwise_ceil)
#define __builtin_elementwise_ceil(a) EW_MAP1_(a, EW_F1_(ceil, x))
#endif
#if !EW_HAS_(__builtin_elementwise_floor)
#define __builtin_elementwise_floor(a) EW_MAP1_(a, EW_F1_(floor, x))
#endif
#if !EW_HAS_(__builtin_elementwise_trunc)
#define __builtin_elementwise_trunc(a) EW_MAP1_(a, EW_F1_(trunc, x))
#endif
#if !EW_HAS_(__builtin_elementwise_round)
#define __builtin_elementwise_round(a) EW_MAP1_(a, EW_F1_(round, x))
#endif
#if !EW_HAS_(__builtin_elementwise_fma)
#define __builtin_elementwise_fma(a, b, c) EW_MAP3_(a, b, c, EW_F3_(fma, x, y, z))
#endif
// A NaN operand loses, like the builtin.
#if !EW_HAS_(__builtin_elementwise_max)
#define __builtin_elementwise_max(a, b) EW_MAP2_(a, b, (y != y || x > y) ? x : y)
#endif
#if !EW_HAS_(__builtin_elementwise_min)
#define __builtin_elementwise_min(a, b) EW_MAP2_(a, b, (y != y || x < y) ? x : y)
#endif

// Saturating integer add/sub per lane. The limits come from the element type.
#define EW_SIGNED_(x) (((__typeof__(x))-1) < 0)
#define EW_SMAX_(x) ((__typeof__(x))((1ull << (sizeof(x) * 8 - 1)) - 1))
#define EW_SMIN_(x) ((__typeof__(x))~EW_SMAX_(x))
#define EW_UMAX_(x) ((__typeof__(x))~(__typeof__(x))0)
#if !EW_HAS_(__builtin_elementwise_add_sat)
#define __builtin_elementwise_add_sat(a, b)                                                       \
    EW_MAP2_(a, b, ({ __typeof__(x) s_; __builtin_add_overflow(x, y, &s_)                          \
                      ? (EW_SIGNED_(x) ? (x < 0 ? EW_SMIN_(x) : EW_SMAX_(x)) : EW_UMAX_(x)) : s_; }))
#endif
#if !EW_HAS_(__builtin_elementwise_sub_sat)
#define __builtin_elementwise_sub_sat(a, b)                                                       \
    EW_MAP2_(a, b, ({ __typeof__(x) s_; __builtin_sub_overflow(x, y, &s_)                          \
                      ? (EW_SIGNED_(x) ? (x < 0 ? EW_SMIN_(x) : EW_SMAX_(x)) : (__typeof__(x))0) : s_; }))
#endif

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
