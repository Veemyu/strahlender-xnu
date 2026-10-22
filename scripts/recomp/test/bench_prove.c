// Performance comparison: the same C functions (bench_guest.c) recompiled (Cpu in memory, dispatch) against native.
// Own code. The guest code comes from eh_gen.py (module "gbn"); the native variant includes the same source with
// renamed symbols. Output: time per function and ratio recompiled / native.
#define _GNU_SOURCE
#include "cpu.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <time.h>

#define bench_int native_bench_int
#define fib native_fib
#define bench_calls native_bench_calls
#define bench_float native_bench_float
#define bench_indirect native_bench_indirect
#include "bench_guest.c"
#undef bench_int
#undef fib
#undef bench_calls
#undef bench_float
#undef bench_indirect

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

// Dispatch as in LASRecomp: direct-mapped cache (4096) before the binary search
#define DC 4096
static struct { uint64_t a; GuestFn f; } dcache[DC];
static GuestFn find(uint64_t pc) {
    uint64_t lo = 0, hi = gbn_fn_count;
    while (lo < hi) { uint64_t m = (lo + hi) / 2; if (gbn_fn_addrs[m] < pc) lo = m + 1; else hi = m; }
    if (lo < gbn_fn_count && gbn_fn_addrs[lo] == pc) return gbn_fn_ptrs[lo];
    abort();
}
void rt_dispatch(Cpu *c) {
    unsigned h = (unsigned)(c->pc >> 2) & (DC - 1);
    GuestFn f = dcache[h].a == c->pc ? dcache[h].f : (dcache[h].a = c->pc, dcache[h].f = find(c->pc));
    __attribute__((musttail)) return f(c);
}

static double now(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return t.tv_sec + t.tv_nsec * 1e-9; }
static Cpu *cpu;
static uint64_t gcall(const char *off_env, uint64_t a0, uint64_t a1) {
    cpu->x[0] = a0; cpu->x[1] = a1; cpu->x[30] = 0; cpu->sp = STACK + SSIZE - 64;
    cpu->pc = GBASE + strtoull(getenv(off_env), 0, 16);
    rt_dispatch(cpu);
    return cpu->x[0];
}

int main(void) {
    if (mmap((void *)GBASE, 0x10000, PROT_READ | PROT_WRITE, MAP_FIXED | MAP_PRIVATE | MAP_ANON, -1, 0) == MAP_FAILED) return 2;
    if (mmap((void *)STACK, SSIZE, PROT_READ | PROT_WRITE, MAP_FIXED | MAP_PRIVATE | MAP_ANON, -1, 0) == MAP_FAILED) return 2;
    FILE *f = fopen(getenv("GIMG"), "rb");
    if (!f || fread((void *)GBASE, 1, 0x10000, f) < 4096) return 2;
    fclose(f);
    cpu = aligned_alloc(16, sizeof(Cpu)); memset(cpu, 0, sizeof(Cpu));
    uint64_t *gbuf = (uint64_t *)(STACK + 0x1000);
    u64 *nbuf = calloc(4096, 8);
    double *gfb = (double *)(STACK + 0x10000), *nfb = calloc(1024, 8);
    for (int i = 0; i < 1024; i++) { gfb[i] = nfb[i] = i * 0.001; }
    struct { const char *name, *env; long n; } B[] = {
        { "Integer+memory (xorshift, 32 KiB)", "OFF_INT", 100000000 },
        { "Calls+stack (fib(35))", "OFF_CALLS", 35 },
        { "Floating point (FMA loop)", "OFF_FLOAT", 100000000 },
        { "indirekte Aufrufe (8er-Tabelle)", "OFF_IND", 60000000 },
    };
    for (int i = 0; i < 4; i++) {
        double t0 = now(), tg, tn;
        uint64_t rg, rn;
        if (i == 0) { rg = gcall(B[i].env, (uint64_t)(uintptr_t)gbuf, B[i].n); tg = now() - t0; t0 = now(); rn = native_bench_int(nbuf, B[i].n); tn = now() - t0; }
        else if (i == 1) { rg = gcall(B[i].env, B[i].n, 0); tg = now() - t0; t0 = now(); rn = native_bench_calls(B[i].n); tn = now() - t0; }
        else if (i == 2) { gcall(B[i].env, (uint64_t)(uintptr_t)gfb, B[i].n); rg = (uint64_t)(cpu->v[0]); tg = now() - t0; t0 = now(); double d = native_bench_float(nfb, B[i].n); memcpy(&rn, &d, 8); tn = now() - t0; }
        else { rg = gcall(B[i].env, 0, B[i].n); tg = now() - t0; t0 = now(); rn = native_bench_indirect(0, B[i].n); tn = now() - t0; }
        printf("%-40s recompiled %7.3f s, native %7.3f s, factor %5.2f  (result %s)\n", B[i].name, tg, tn, tg / tn, rg == rn ? "equal" : "DIFFERENT");
    }
    return 0;
}
