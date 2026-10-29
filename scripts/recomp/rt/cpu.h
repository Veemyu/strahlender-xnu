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
