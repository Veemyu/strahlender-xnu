// Host floating point state for the portable c mode (docs/recomp-diff.md, section 5). Own code.
//
// The c mode (scripts/recomp/upstream/runtime/simd.h, MIT) computes on the fast path (FPCR = 0) with the host FPU and assumes:
// round to nearest even, denormals on (no FTZ/DAZ), all exceptions masked. Drivers, audio and
// graphics libraries and some runtimes change MXCSR in their threads (typically FTZ/DAZ); the test then shows
// deviations in denormals and rounding. rt_fp_guest_mode() restores the state. Call it: at the start of every
// guest thread and after every call into foreign code (HLE services, driver callbacks) that could change the FP state.
#pragma once
#include <stdint.h>

#if defined(__x86_64__) || defined(_M_X64)
#include <xmmintrin.h>
#define RT_MXCSR_GUEST 0x1F80u // RN, exceptions masked, FTZ = 0, DAZ = 0
static inline void rt_fp_guest_mode(void) {
    if (__builtin_expect(_mm_getcsr() != RT_MXCSR_GUEST, 0)) _mm_setcsr(RT_MXCSR_GUEST);
}
#elif defined(__aarch64__)
// On arm64 hosts in c mode the host FPCR must be 0 (RN, FZ = 0, DN = 0); the guest FPCR lives in Cpu.
static inline void rt_fp_guest_mode(void) {
    uint64_t v;
    __asm__ volatile("mrs %0, fpcr" : "=r"(v));
    if (__builtin_expect(v != 0, 0)) __asm__ volatile("msr fpcr, xzr");
}
#else
static inline void rt_fp_guest_mode(void) {}
#endif
