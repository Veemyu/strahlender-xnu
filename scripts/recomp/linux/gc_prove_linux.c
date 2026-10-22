// GC proof for Linux/x86-64 (counterpart of test/gc_prove.c, which uses Mach APIs and ARM64 state).
// Own code. The guest thread is stopped at an arbitrary point by a signal (SIGUSR1); the handler runs on the
// guest thread, reads the x86 register state from the ucontext and waits until the main thread has finished the check.
// The check is the same as in gc_prove.c: if the marker is only "in a register" (slot empty), is it then found in Cpu/guest stack?
// Guest code: gc_guest.c, generated with eh_gen.py in c mode (module "gct").
#define _GNU_SOURCE
#include "cpu.h"
#include <pthread.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <time.h>
#include <ucontext.h>
#include <unistd.h>

#define GBASE  0x7008000000ull
#define STACK  0x7010000000ull
#define SSIZE  (1ull << 20)
#define SLOT   (STACK + 0x100)
#define MARKER 0x7123456789ABCDE0ull

extern const uint64_t gct_fn_addrs[]; extern const GuestFn gct_fn_ptrs[]; extern const uint64_t gct_fn_count;
volatile int g_fnprof;
void fnprof_hit(uint64_t a, uint64_t b, uint64_t c) { (void)a; (void)b; (void)c; }
void rt_nle_enter(Cpu *c) { (void)c; abort(); }
void rt_nle_fatal(Cpu *c) { (void)c; abort(); }
void rt_svc(Cpu *c, uint32_t i, uint64_t pc) { (void)c; (void)i; (void)pc; abort(); }
void rt_brk(Cpu *c, uint32_t i, uint64_t pc) { (void)c; (void)i; (void)pc; abort(); }
void rt_udf(Cpu *c, uint64_t pc) { (void)c; (void)pc; abort(); }
uint64_t rt_ticks(void) { return 0; }
void rt_dispatch(Cpu *c) {
    for (uint64_t i = 0; i < gct_fn_count; i++)
        if (gct_fn_addrs[i] == c->pc) { __attribute__((musttail)) return gct_fn_ptrs[i](c); }
    abort();
}

static Cpu *cpu;
static volatile int running, stopped, resume_go, resumed;
static pthread_t worker_th;
static greg_t saved[NGREG];

static void on_stop(int sig, siginfo_t *si, void *uc_) {
    (void)sig; (void)si;
    ucontext_t *uc = uc_;
    memcpy(saved, uc->uc_mcontext.gregs, sizeof saved);
    stopped = 1;
    while (!resume_go) __asm__ volatile("pause");
    resume_go = 0;
    resumed = 1;
}

static void *worker(void *arg) {
    (void)arg;
    cpu->x[0] = SLOT; cpu->x[1] = 1ull << 40; cpu->x[30] = 0;
    cpu->sp = STACK + SSIZE - 64;
    cpu->pc = GBASE + strtoull(getenv("CHURN_OFF"), 0, 16);
    running = 1;
    rt_dispatch(cpu);
    return NULL;
}

static int has(const uint64_t *v, int n) { for (int i = 0; i < n; i++) if (v[i] == MARKER) return 1; return 0; }

int main(void) {
    void *img = mmap((void *)GBASE, 0x10000, PROT_READ | PROT_WRITE, MAP_FIXED | MAP_PRIVATE | MAP_ANON, -1, 0);
    void *stk = mmap((void *)STACK, SSIZE, PROT_READ | PROT_WRITE, MAP_FIXED | MAP_PRIVATE | MAP_ANON, -1, 0);
    if (img == MAP_FAILED || stk == MAP_FAILED) return 2;
    cpu = aligned_alloc(16, sizeof(Cpu)); memset(cpu, 0, sizeof(Cpu));
    *(volatile uint64_t *)SLOT = MARKER;
    struct sigaction sa; memset(&sa, 0, sizeof sa);
    sa.sa_sigaction = on_stop; sa.sa_flags = SA_SIGINFO;
    sigaction(SIGUSR1, &sa, NULL);
    pthread_create(&worker_th, NULL, worker, NULL);
    while (!running) ;
    struct timespec ts = {0, 5 * 1000 * 1000}; nanosleep(&ts, NULL);
    int n = 20000, windows = 0, hit_cpu = 0, hit_all = 0, hit_host_only = 0;
    unsigned seed = 12345;
    for (int it = 0; it < n; it++) {
        struct timespec w = {0, 20000 + (rand_r(&seed) % 200000)}; nanosleep(&w, NULL);
        stopped = 0; resumed = 0;
        pthread_kill(worker_th, SIGUSR1);
        while (!stopped) __asm__ volatile("pause");
        if (*(volatile uint64_t *)SLOT == 0) {  // object is only reachable via registers/intermediate values
            windows++;
            uint64_t gx[33]; memcpy(gx, cpu->x, 31 * 8); gx[31] = cpu->sp;
            int in_cpu = has(gx, 32);
            for (uint64_t a = cpu->sp & ~7ull; a < STACK + SSIZE && !in_cpu; a += 8)
                if (*(volatile uint64_t *)a == MARKER) in_cpu = 1;
            uint64_t hx[NGREG]; int nh = 0;
            for (int r = 0; r < NGREG; r++) hx[nh++] = (uint64_t)saved[r];
            const uint64_t *hs = (const uint64_t *)(uintptr_t)(saved[REG_RSP] & ~7ull);
            int in_host = has(hx, nh);
            for (int k = 0; k < 64 && !in_host; k++) if (hs[k] == MARKER) in_host = 1;  // top part of the host stack (512 bytes)
            hit_cpu += in_cpu;
            hit_all += in_cpu || in_host;
            hit_host_only += !in_cpu && in_host;
        }
        resume_go = 1;
        while (!resumed) __asm__ volatile("pause");
    }
    printf("GC proof (Linux/x86-64, signal stop): %d suspension points, %d of them in the window (pointer only in registers/intermediate values, slot empty)\n", n, windows);
    printf("  found with guest state only (Cpu + guest stack):        %d of %d (%.1f %%)\n", hit_cpu, windows, windows ? 100.0 * hit_cpu / windows : 0);
    printf("  found with additional host register/host stack:        %d of %d (%.1f %%); of those only there: %d\n", hit_all, windows, windows ? 100.0 * hit_all / windows : 0, hit_host_only);
    return 0;
}
