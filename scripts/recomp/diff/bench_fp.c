// Float benchmark proof (docs/recomp-diff.md, section 6): runs the floating point loop from bench_guest.c (1) as
// generated C (c mode) and (2) natively (x86, same source) and prints the result and the hash of the buffer.
// Own code, modeled on scripts/recomp/test/bench_prove.c. Usage: GIMG=<image> OFF_FLOAT=<offset> bench_fp <n>
#define _GNU_SOURCE
#include "cpu.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>

#define bench_int native_bench_int
#define fib native_fib
#define bench_calls native_bench_calls
#define bench_float native_bench_float
#define bench_indirect native_bench_indirect
#include "bench_guest.c"

#define GBASE 0x7008000000ull
#define STACK 0x7010000000ull
#define SSIZE (1ull << 20)
extern const uint64_t gbn_fn_addrs[]; extern const GuestFn gbn_fn_ptrs[]; extern const uint64_t gbn_fn_count;
volatile int g_fnprof;
void fnprof_hit(uint64_t a, uint64_t b, uint64_t c) { (void)a; (void)b; (void)c; }
void rt_nle_enter(Cpu *c) { (void)c; abort(); }
void rt_nle_fatal(Cpu *c) { (void)c; abort(); }
void rt_svc(Cpu *c, uint32_t i, uint64_t pc) { (void)c; (void)i; (void)pc; abort(); }
void rt_brk(Cpu *c, uint32_t i, uint64_t pc) { (void)c; (void)i; (void)pc; abort(); }
void rt_udf(Cpu *c, uint64_t pc) { (void)c; (void)pc; abort(); }
uint64_t rt_ticks(void) { return 0; }

static GuestFn find(uint64_t pc) {
    for (uint64_t i = 0; i < gbn_fn_count; i++) if (gbn_fn_addrs[i] == pc) return gbn_fn_ptrs[i];
    abort();
}
void rt_dispatch(Cpu *c) { GuestFn f = find(c->pc); __attribute__((musttail)) return f(c); }

static uint64_t fnv(const double *p, int n) {
    uint64_t h = 1469598103934665603ull;
    for (int i = 0; i < n; i++) { uint64_t u; memcpy(&u, p + i, 8); h = (h ^ u) * 1099511628211ull; }
    return h;
}

int main(int argc, char **argv) {
    long n = argc > 1 ? atol(argv[1]) : 1000000;
    if (mmap((void *)GBASE, 0x10000, PROT_READ | PROT_WRITE, MAP_FIXED | MAP_PRIVATE | MAP_ANON, -1, 0) == MAP_FAILED) return 2;
    if (mmap((void *)STACK, SSIZE, PROT_READ | PROT_WRITE, MAP_FIXED | MAP_PRIVATE | MAP_ANON, -1, 0) == MAP_FAILED) return 2;
    FILE *f = fopen(getenv("GIMG"), "rb");
    if (!f || fread((void *)GBASE, 1, 0x10000, f) < 4096) return 2;
    fclose(f);
    Cpu *cpu = aligned_alloc(16, sizeof(Cpu)); memset(cpu, 0, sizeof(Cpu));
    double *gfb = (double *)(STACK + 0x10000), *nfb = calloc(1024, 8);
    for (int i = 0; i < 1024; i++) gfb[i] = nfb[i] = i * 0.001;
    cpu->x[0] = (uint64_t)(uintptr_t)gfb; cpu->x[1] = n; cpu->x[30] = 0; cpu->sp = STACK + SSIZE - 64;
    cpu->pc = GBASE + strtoull(getenv("OFF_FLOAT"), 0, 16);
    rt_dispatch(cpu);
    uint64_t rg = (uint64_t)cpu->v[0];
    double d = native_bench_float(nfb, n);
    uint64_t rn; memcpy(&rn, &d, 8);
    printf("REC %016llx %016llx\nNAT %016llx %016llx\n", (unsigned long long)rg, (unsigned long long)fnv(gfb, 1024),
           (unsigned long long)rn, (unsigned long long)fnv(nfb, 1024));
    return 0;
}
