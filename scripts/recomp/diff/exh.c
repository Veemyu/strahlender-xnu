// Erschöpfender Einzelbefehlstest (docs/recomp-diff.md, Abschnitt 4). Eigener Code.
// Läuft über alle 2^32 Eingaben (32-Bit-Formate vollständig; 64-Bit-Formate: obere 32 Bit vollständig, untere 32 Bit aus
// einem Mischer) und bildet einen Hash über (V0 niedrige 64 Bit, X0). Zwei Übersetzungen derselben Quelle:
//   -DREF_ASM : nativer Lauf auf Apple Silicon (Inline-asm, echte Befehle)  -> Referenz
//   ohne      : erzeugtes C des Lifters (c-Modus), x86 oder arm64
// Aufruf: exh <befehlsnummer|-1 für alle> <fpcr-hex> <schritt> ; Ausgabe: Nr|Name|FPCR|Schritt|Hash|Fälle
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifndef REF_ASM
#include "cpu.h"
#include "simd.h"
#else
#include <stdint.h>
#endif
#include "exh_ops.h"

static uint64_t mix(uint64_t z) {
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ull;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBull;
    return z ^ (z >> 31);
}

static uint64_t run_all(int k, uint64_t fpcr, uint64_t step, uint64_t *cases) {
    uint64_t h = 1469598103934665603ull, n = 0;
    char kind = OPS[k].kind;
#ifdef REF_ASM
    uint64_t save;
    __asm__ volatile("mrs %0, fpcr\n\tmsr fpcr, %1" : "=&r"(save) : "r"(fpcr));
#else
    static Cpu cpu __attribute__((aligned(16)));
    Cpu *c = &cpu;
#endif
    for (uint64_t i = 0; i < (1ull << 32); i += step) {
        uint64_t in = (kind == 'd' || kind == 'x') ? (i << 32) | (mix(i) & 0xffffffffull) : i;
        uint64_t v, x;
#ifdef REF_ASM
        run_op(k, in, &v, &x);
#else
        c->v[0] = 0; c->x[0] = 0; c->v[1] = in; c->x[1] = in; c->fpcr = fpcr;
        FN[k](c);
        v = (uint64_t)c->v[0]; x = c->x[0];
#endif
        h = (h ^ v) * 1099511628211ull; h = (h ^ x) * 1099511628211ull;
        n++;
    }
#ifdef REF_ASM
    __asm__ volatile("msr fpcr, %0" :: "r"(save));
#endif
    *cases = n;
    return h;
}

int main(int argc, char **argv) {
    int which = argc > 1 ? atoi(argv[1]) : -1;
    uint64_t fpcr = argc > 2 ? strtoull(argv[2], 0, 16) : 0, step = argc > 3 ? strtoull(argv[3], 0, 0) : 1;
    for (int k = 0; k < NOPS; k++) {
        if (which >= 0 && k != which) continue;
        uint64_t n, h = run_all(k, fpcr, step, &n);
        printf("%d|%s|%llx|%llu|%016llx|%llu\n", k, OPS[k].name, (unsigned long long)fpcr, (unsigned long long)step, (unsigned long long)h, (unsigned long long)n);
        fflush(stdout);
    }
    return 0;
}
