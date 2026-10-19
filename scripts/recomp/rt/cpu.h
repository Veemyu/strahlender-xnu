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
