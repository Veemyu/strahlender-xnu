// Erweiterung von cpu.h für den Exception-Spike: Rahmeneinträge für Landing-Pads und setjmp-Rücksprünge.
// Eigener Code. Liegt vor research/LASRecomp/runtime im Include-Pfad (-I scripts/recomp/rt -I <las>/runtime)
// und zieht per #include_next die Original-cpu.h nach.
#pragma once
#include_next "cpu.h"
#include <setjmp.h>

// Ein Eintrag pro aktiver Gastfunktion, die einen Wiedereinstiegspunkt enthält. Liegt auf dem Host-Stack
// der erzeugten Funktion; die Kette hängt am Cpu (Offset 336, im Original ungenutzter Füllbereich).
typedef struct EhRec {
    struct EhRec *prev;
    uint64_t lo, hi;   // Gastadressbereich der Funktion
    uint64_t sp;       // Gast-SP beim Eintritt (Rahmen liegen darunter)
    jmp_buf jb;        // _setjmp-Puffer (ohne Signalmaske)
} EhRec;

#define EH_TOP(c) (*(EhRec **)((char *)(c) + 336))
#define EH_ENTER(lo_, hi_)                                              \
    EhRec eh;                                                           \
    eh.prev = EH_TOP(c); eh.lo = (lo_); eh.hi = (hi_); eh.sp = c->sp;   \
    EH_TOP(c) = &eh
#define EH_SETJMP() _setjmp(eh.jb)
#define EH_POP() (EH_TOP(c) = eh.prev)

void rt_nle_enter(Cpu *c) __attribute__((noreturn));   // c->pc = Wiedereinstiegspunkt mitten in einer Funktion
void rt_nle_fatal(Cpu *c) __attribute__((noreturn));

// ---- Exklusiv-Paare (LDXP/LDAXP/STXP/STLXP), Gate 1: der Monitor des Originals (cpu.h) merkt sich nur einen 64-Bit-Wert.
// Hier kommt der zweite Teil bei Cpu-Offset 344 dazu (liegt im ungenutzten Füllbereich, hinter EH_TOP bei 336). Der Speicher-
// zugriff geschieht über GPTR(a); Speichermodell B (rt32/cpu.h) ersetzt GPTR. Erfolg von STXP wie auf der Hardware: 0.
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
