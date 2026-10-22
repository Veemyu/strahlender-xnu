// GC proof (step 2): Shows on recompiled guest code that an asynchronously suspended thread can hold guest values only in the
// host register state, and that mirroring the Mach register state (plus the upper part of the host stack)
// into the reported guest context suffices for a conservative GC to lose no object.
// Own code, macOS/iOS. The guest code (gc_guest.c) is generated with eh_gen.py (module "gct").
#define _GNU_SOURCE
#include "cpu.h"
#include <mach/mach.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <time.h>
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
static volatile int running;
static mach_port_t worker_port;

static void *worker(void *arg) {
    (void)arg;
    worker_port = mach_thread_self();
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
    pthread_t th;
    pthread_create(&th, NULL, worker, NULL);
    while (!running) ;
    struct timespec ts = {0, 5 * 1000 * 1000}; nanosleep(&ts, NULL);
    int n = 20000, windows = 0, hit_cpu = 0, hit_all = 0, hit_host_only = 0;
    unsigned seed = 12345;
    for (int it = 0; it < n; it++) {
        struct timespec w = {0, 20000 + (rand_r(&seed) % 200000)}; nanosleep(&w, NULL);
        thread_suspend(worker_port);
        arm_thread_state64_t st;
        mach_msg_type_number_t cnt = ARM_THREAD_STATE64_COUNT;
        thread_get_state(worker_port, ARM_THREAD_STATE64, (thread_state_t)&st, &cnt);
        if (*(volatile uint64_t *)SLOT == 0) {  // the object is only reachable in registers/intermediate values
            windows++;
            uint64_t gx[33]; memcpy(gx, cpu->x, 31 * 8); gx[31] = cpu->sp;
            int in_cpu = has(gx, 32);
            for (uint64_t a = cpu->sp & ~7ull; a < STACK + SSIZE && !in_cpu; a += 8)
                if (*(volatile uint64_t *)a == MARKER) in_cpu = 1;
            uint64_t hx[40]; int nh = 0;
            for (int r = 0; r < 29; r++) hx[nh++] = st.__x[r];
            hx[nh++] = arm_thread_state64_get_fp(st); hx[nh++] = arm_thread_state64_get_lr(st);
            const uint64_t *hs = (const uint64_t *)(uintptr_t)arm_thread_state64_get_sp(st);
            int in_host = has(hx, nh);
            for (int k = 0; k < 64 && !in_host; k++) if (hs[k] == MARKER) in_host = 1;  // upper part of the host stack (512 bytes)
            hit_cpu += in_cpu;
            hit_all += in_cpu || in_host;
            hit_host_only += !in_cpu && in_host;
        }
        thread_resume(worker_port);
    }
    printf("GC proof: %d suspension points, %d of them in the window (pointer only in registers/intermediate values, slot empty)\n", n, windows);
    printf("  found with guest state only (Cpu + guest stack):        %d of %d (%.1f %%)\n", hit_cpu, windows, windows ? 100.0 * hit_cpu / windows : 0);
    printf("  found with additional host register/host stack:        %d of %d (%.1f %%); of those only there: %d\n", hit_all, windows, windows ? 100.0 * hit_all / windows : 0, hit_host_only);
    return 0;
}
