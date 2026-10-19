// Host-Gleitkommazustand für den portablen c-Modus (docs/recomp-diff.md, Abschnitt 5). Eigener Code.
//
// Der c-Modus (scripts/recomp/upstream/runtime/simd.h, MIT) rechnet auf dem Schnellpfad (FPCR = 0) mit der Host-FPU und setzt
// voraus: Rundung auf nächste gerade Zahl, Denormale an (kein FTZ/DAZ), alle Ausnahmen maskiert. Treiber, Audio- und
// Grafikbibliotheken und manche Laufzeiten ändern MXCSR in ihren Threads (typisch FTZ/DAZ); der Test zeigt dann
// Abweichungen bei Denormalen und Rundung. rt_fp_guest_mode() stellt den Zustand wieder her. Aufrufen: am Anfang jedes
// Gast-Threads und nach jedem Aufruf in Fremdcode (HLE-Dienste, Treiber-Callbacks), der FP-Zustand ändern könnte.
#pragma once
#include <stdint.h>

#if defined(__x86_64__) || defined(_M_X64)
#include <xmmintrin.h>
#define RT_MXCSR_GUEST 0x1F80u // RN, Ausnahmen maskiert, FTZ = 0, DAZ = 0
static inline void rt_fp_guest_mode(void) {
    if (__builtin_expect(_mm_getcsr() != RT_MXCSR_GUEST, 0)) _mm_setcsr(RT_MXCSR_GUEST);
}
#elif defined(__aarch64__)
// Auf arm64-Hosts im c-Modus muss das Host-FPCR 0 sein (RN, FZ = 0, DN = 0); Gast-FPCR liegt in Cpu.
static inline void rt_fp_guest_mode(void) {
    uint64_t v;
    __asm__ volatile("mrs %0, fpcr" : "=r"(v));
    if (__builtin_expect(v != 0, 0)) __asm__ volatile("msr fpcr, xzr");
}
#else
static inline void rt_fp_guest_mode(void) {}
#endif
