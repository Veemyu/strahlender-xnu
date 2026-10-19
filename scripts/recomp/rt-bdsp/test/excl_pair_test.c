// Synthetischer Test der Exklusiv-Paar-Hilfen (rt/cpu.h: ldxp64/stxp64/ldxp32/stxp32) ohne Spielcode:
// (1) Einzelthread-Semantik (Erfolg 0, Fehlschlag 1 nach fremdem Schreibzugriff), (2) 128-Bit-Zähler mit LL/SC-Schleife aus
// 4 Threads, (3) 32-Bit-Paar. Übersetzen und ausführen: scripts/recomp/rt-bdsp/test/run_excl_test.sh
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "cpu.h"

void rt_dispatch(Cpu *c) { (void)c; }
void rt_svc(Cpu *c, uint32_t imm, uint64_t pc) { (void)c; (void)imm; (void)pc; }
void rt_brk(Cpu *c, uint32_t imm, uint64_t pc) { (void)c; (void)imm; (void)pc; abort(); }
void rt_udf(Cpu *c, uint64_t pc) { (void)c; (void)pc; abort(); }
uint64_t rt_ticks(void) { return 0; }
void rt_nle_enter(Cpu *c) { (void)c; abort(); }
void rt_nle_fatal(Cpu *c) { (void)c; abort(); }
volatile int g_fnprof;
void fnprof_hit(uint64_t a, uint64_t b, uint64_t c) { (void)a; (void)b; (void)c; }

static int fails;
#define CHECK(x) do { if (!(x)) { printf("FEHLER Zeile %d: %s\n", __LINE__, #x); fails++; } } while (0)

typedef struct { uint64_t lo, hi; } Pair __attribute__((aligned(16)));
static Pair counter __attribute__((aligned(16)));
enum { THREADS = 4, ITER = 50000 };

static void *worker(void *arg) {
    Cpu *c = aligned_alloc(16, sizeof(Cpu));
    memset(c, 0, sizeof *c);
    (void)arg;
    for (int i = 0; i < ITER; i++) {
        for (;;) {  // wie die Schleife im Spiel: ldxp; add (mit Übertrag); stxp; cbnz
            uint64_t lo, hi, a = (uint64_t)(uintptr_t)&counter;
            ldxp64(c, a, GPTR(a), &lo, &hi);
            uint64_t nlo = lo + 0xFFFFFFFFull, nhi = hi + (nlo < lo);
            if (!stxp64(c, a, GPTR(a), nlo, nhi)) break;
        }
    }
    free(c);
    return NULL;
}

int main(void) {
    Cpu *c = aligned_alloc(16, sizeof(Cpu));
    memset(c, 0, sizeof *c);
    Pair p __attribute__((aligned(16))) = {0x1111, 0x2222};
    uint64_t a = (uint64_t)(uintptr_t)&p, lo, hi;
    ldxp64(c, a, GPTR(a), &lo, &hi);
    CHECK(lo == 0x1111 && hi == 0x2222);
    CHECK(stxp64(c, a, GPTR(a), 7, 8) == 0);
    CHECK(p.lo == 7 && p.hi == 8);
    CHECK(stxp64(c, a, GPTR(a), 9, 9) == 1);  // Monitor ist verbraucht
    CHECK(p.lo == 7 && p.hi == 8);
    ldxp64(c, a, GPTR(a), &lo, &hi);
    p.hi = 99;  // fremder Schreibzugriff zwischen ldxp und stxp
    CHECK(stxp64(c, a, GPTR(a), 1, 2) == 1);
    CHECK(p.lo == 7 && p.hi == 99);
    // Wert unverändert, aber Adresse anders: stxp muss scheitern
    ldxp64(c, a, GPTR(a), &lo, &hi);
    CHECK(stxp64(c, a + 16, GPTR(a + 16), 1, 2) == 1);

    uint32_t q[2] __attribute__((aligned(8))) = {5, 6};
    uint64_t qa = (uint64_t)(uintptr_t)q;
    ldxp32(c, qa, GPTR(qa), &lo, &hi);
    CHECK(lo == 5 && hi == 6);
    CHECK(stxp32(c, qa, GPTR(qa), 0xAAAAAAAAull, 0xBBBBBBBBull) == 0);
    CHECK(q[0] == 0xAAAAAAAAu && q[1] == 0xBBBBBBBBu);

    pthread_t t[THREADS];
    for (int i = 0; i < THREADS; i++) pthread_create(&t[i], NULL, worker, NULL);
    for (int i = 0; i < THREADS; i++) pthread_join(t[i], NULL);
    unsigned __int128 total = ((unsigned __int128)counter.hi << 64) | counter.lo;
    unsigned __int128 expect = (unsigned __int128)THREADS * ITER * 0xFFFFFFFFull;
    CHECK(total == expect);
    printf(fails ? "Exklusiv-Paare: %d Fehler\n" : "Exklusiv-Paare: bestanden (4 Threads x %d Zählschritte, Summe stimmt)\n", fails ? fails : ITER);
    return fails != 0;
}
