// Spike 2, Schritt 2: Thread-Anhalten für einen Stop-the-World-GC (Boehm) im Modell der Rekompilation.
// Eigener Code, nur macOS/iOS (Mach). Zeigt:
//  (1) thread_suspend + thread_get_state auf eigenen Threads: Latenz bei 1 bis 64 Threads
//  (2) Gastwerte können beim asynchronen Anhalten nur in Host-Registern stehen (Cpu im Speicher ist dann veraltet);
//      das Registerabbild des Mach-Zustands enthält sie, der Cpu-Speicher nicht
//  (3) Kosten kooperativer Sicherheitspunkte (Poll am Funktionseintritt) als Alternative
// Übersetzen: clang -O1 -o gc_suspend gc_suspend.c
#include <mach/mach.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

typedef struct { uint64_t x[32]; uint64_t sp; volatile uint32_t gc_pending; } MiniCpu;

typedef struct {
    MiniCpu cpu;
    uint64_t marker;          // "Gastzeiger", wird nur im Host-Register gehalten
    volatile int run;
    volatile uint64_t spin;
    pthread_t th;
    volatile mach_port_t port;
} Worker;

static void *worker_main(void *arg) {
    Worker *w = arg;
    w->port = mach_thread_self();
    register uint64_t m __asm__("x20") = w->marker;   // lebt nur im Host-Register
    uint64_t n = 0;
    while (w->run) {
        n++;
        __asm__ volatile("" : "+r"(m));
        if ((n & 0xFFFFF) == 0) w->spin = n;
    }
    return (void *)m;
}

static double now_us(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return t.tv_sec * 1e6 + t.tv_nsec / 1e3; }

static int run_suspend_test(int n, int iters, int verify) {
    Worker *ws = calloc(n, sizeof *ws);
    for (int i = 0; i < n; i++) {
        ws[i].run = 1;
        ws[i].marker = 0x7200000000ull + (uint64_t)i * 0x1000;
        pthread_create(&ws[i].th, NULL, worker_main, &ws[i]);
    }
    for (int i = 0; i < n; i++) while (!ws[i].port) ;
    struct timespec ts = {0, 20 * 1000 * 1000}; nanosleep(&ts, NULL);
    double total = 0, worst = 0;
    int found_in_regs = 0, found_in_cpu = 0;
    for (int it = 0; it < iters; it++) {
        double t0 = now_us();
        for (int i = 0; i < n; i++) thread_suspend(ws[i].port);
        arm_thread_state64_t st;
        for (int i = 0; i < n; i++) {
            mach_msg_type_number_t cnt = ARM_THREAD_STATE64_COUNT;
            kern_return_t kr = thread_get_state(ws[i].port, ARM_THREAD_STATE64, (thread_state_t)&st, &cnt);
            if (kr != KERN_SUCCESS) { printf("thread_get_state fehlgeschlagen: %d\n", kr); return 1; }
            if (verify && it == 0) {
                for (int r = 0; r < 29; r++) if (st.__x[r] == ws[i].marker) found_in_regs++;
                for (int r = 0; r < 32; r++) if (ws[i].cpu.x[r] == ws[i].marker) found_in_cpu++;
            }
        }
        for (int i = 0; i < n; i++) thread_resume(ws[i].port);
        double dt = now_us() - t0;
        total += dt;
        if (dt > worst) worst = dt;
    }
    if (verify)
        printf("  Marker (Gastzeiger nur im Host-Register) gefunden: im Mach-Registerzustand %d von %d Threads, im Cpu-Speicher %d\n", found_in_regs, n, found_in_cpu);
    printf("  %3d Threads: anhalten + Zustand lesen + fortsetzen im Mittel %.1f us (schlechtester %.1f us), %.2f us je Thread\n",
           n, total / iters, worst, total / iters / n);
    for (int i = 0; i < n; i++) ws[i].run = 0;
    for (int i = 0; i < n; i++) pthread_join(ws[i].th, NULL);
    free(ws);
    return 0;
}

// Sicherheitspunkt-Mikrobenchmark: Kette winziger "Gastfunktionen" über Cpu, mit und ohne Poll am Eintritt
typedef void (*Fn)(MiniCpu *);
static void slow_path(MiniCpu *c) { c->gc_pending = 0; }
#define POLL(c) do { if (__builtin_expect((c)->gc_pending, 0)) slow_path(c); } while (0)
__attribute__((noinline)) static void leaf_np(MiniCpu *c) { c->x[0] = c->x[0] * 3 + c->x[1]; c->x[1] ^= c->x[0] >> 3; }
__attribute__((noinline)) static void leaf_p(MiniCpu *c) { POLL(c); c->x[0] = c->x[0] * 3 + c->x[1]; c->x[1] ^= c->x[0] >> 3; }
__attribute__((noinline)) static void mid_np(MiniCpu *c) { for (int i = 0; i < 4; i++) { c->x[2] += i; leaf_np(c); } }
__attribute__((noinline)) static void mid_p(MiniCpu *c) { POLL(c); for (int i = 0; i < 4; i++) { c->x[2] += i; leaf_p(c); } POLL(c); }
static double bench(Fn f, long n) {
    MiniCpu c; memset(&c, 0, sizeof c); c.x[1] = 1;
    double t0 = now_us();
    for (long i = 0; i < n; i++) f(&c);
    double dt = now_us() - t0;
    volatile uint64_t sink = c.x[0] + c.x[2]; (void)sink;
    return dt * 1e3 / n;  // ns je Aufruf
}

int main(void) {
    printf("Mach thread_suspend/thread_get_state auf eigenen Threads (kein Entitlement, kein task_for_pid):\n");
    run_suspend_test(1, 200, 1);
    run_suspend_test(4, 200, 0);
    run_suspend_test(16, 100, 0);
    run_suspend_test(64, 50, 0);
    long n = 20000000;
    double a = bench(mid_np, n), b = bench(mid_p, n), a2 = bench(mid_np, n), b2 = bench(mid_p, n);
    a = a < a2 ? a : a2; b = b < b2 ? b : b2;
    printf("Kooperative Sicherheitspunkte (Poll am Funktionseintritt, 5 Funktionen je Durchlauf): ohne %.2f ns, mit %.2f ns, Aufschlag %.1f %%\n", a, b, (b / a - 1) * 100);
    return 0;
}
