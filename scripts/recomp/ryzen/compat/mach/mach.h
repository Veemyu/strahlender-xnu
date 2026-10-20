// Linux-Ersatz für den kleinen Teil der Mach-API, den scripts/recomp/rt-bdsp (kernel.c, main.c) benutzt.
// Eigener Code, nur für die Ryzen-Farm (docs/recomp-ryzen.md): macht es möglich, die Laufzeit unverändert unter Linux zu
// übersetzen (`-I scripts/recomp/ryzen/compat`), ohne ihre Dateien anzufassen. Kein Ersatz für die Mach-Semantik auf dem
// Mac: Anhalten per Signal (SIGUSR2), Speicherbelegung aus /proc, Regionen per mincore.
#pragma once
#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include <errno.h>
#include <pthread.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>

typedef int kern_return_t;
extern int pthread_getattr_np(pthread_t, pthread_attr_t *);
typedef uint32_t mach_port_t;
typedef uint32_t mach_msg_type_number_t;
typedef int *thread_state_t;
#define KERN_SUCCESS 0
#define KERN_FAILURE 5

// ---- Zeit (mach_time.h)
typedef struct { uint32_t numer, denom; } mach_timebase_info_data_t;
static inline kern_return_t mach_timebase_info(mach_timebase_info_data_t *i) { i->numer = i->denom = 1; return KERN_SUCCESS; }
static inline uint64_t mach_absolute_time(void) {
    struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t);
    return (uint64_t)t.tv_sec * 1000000000ull + (uint64_t)t.tv_nsec;
}

// ---- Threads anhalten: Signal-Handler blockiert den Zielthread, bis thread_resume ihn freigibt
#define COMPAT_MAX_THREADS 256
static pthread_t compat_threads[COMPAT_MAX_THREADS];
static volatile int compat_stopped[COMPAT_MAX_THREADS], compat_go[COMPAT_MAX_THREADS];
static int compat_nthreads;
static pthread_mutex_t compat_lock = PTHREAD_MUTEX_INITIALIZER;

static inline void compat_on_stop(int sig) {
    (void)sig;
    pthread_t me = pthread_self();
    int s = -1;
    for (int i = 0; i < compat_nthreads; i++) if (pthread_equal(compat_threads[i], me)) { s = i; break; }
    if (s < 0) return;
    compat_stopped[s] = 1;
    while (!compat_go[s]) __asm__ volatile("pause" ::: "memory");
    compat_go[s] = 0;
    compat_stopped[s] = 0;
}
static inline mach_port_t pthread_mach_thread_np(pthread_t t) {
    pthread_mutex_lock(&compat_lock);
    int i;
    for (i = 0; i < compat_nthreads; i++) if (pthread_equal(compat_threads[i], t)) break;
    if (i == compat_nthreads && i < COMPAT_MAX_THREADS) {
        compat_threads[i] = t; compat_nthreads++;
        struct sigaction sa; memset(&sa, 0, sizeof sa);
        sa.sa_handler = compat_on_stop;
        sigaction(SIGUSR2, &sa, NULL);
    }
    pthread_mutex_unlock(&compat_lock);
    return (mach_port_t)(i + 1);
}
static inline kern_return_t thread_suspend(mach_port_t p) {
    int s = (int)p - 1;
    if (s < 0 || s >= compat_nthreads) return KERN_FAILURE;
    compat_go[s] = 0;
    pthread_kill(compat_threads[s], SIGUSR2);
    return KERN_SUCCESS;
}
static inline kern_return_t thread_resume(mach_port_t p) {
    int s = (int)p - 1;
    if (s < 0 || s >= compat_nthreads) return KERN_FAILURE;
    compat_go[s] = 1;
    return KERN_SUCCESS;
}

// ---- Stackgröße/-adresse (Darwin-Aufrufe; stackaddr = obere Grenze wie auf macOS)
static inline size_t pthread_get_stacksize_np(pthread_t t) {
    pthread_attr_t a; void *lo = NULL; size_t sz = 0;
    if (pthread_getattr_np(t, &a) != 0) return 0;
    pthread_attr_getstack(&a, &lo, &sz); pthread_attr_destroy(&a);
    return sz;
}
static inline void *pthread_get_stackaddr_np(pthread_t t) {
    pthread_attr_t a; void *lo = NULL; size_t sz = 0;
    if (pthread_getattr_np(t, &a) != 0) return NULL;
    pthread_attr_getstack(&a, &lo, &sz); pthread_attr_destroy(&a);
    return (char *)lo + sz;
}

// ---- Prozessinformation (task_info)
#define MACH_TASK_BASIC_INFO 20
#define MACH_TASK_BASIC_INFO_COUNT 12
typedef struct { uint64_t resident_size, virtual_size, resident_size_max; } mach_task_basic_info_data_t;
typedef int *task_info_t;
static inline mach_port_t mach_task_self(void) { return 1; }
static inline kern_return_t task_info(mach_port_t t, int flavor, task_info_t out, mach_msg_type_number_t *cnt) {
    (void)t; (void)flavor; (void)cnt;
    mach_task_basic_info_data_t *i = (mach_task_basic_info_data_t *)out;
    FILE *f = fopen("/proc/self/statm", "r");
    if (!f) return KERN_FAILURE;
    unsigned long vm = 0, rss = 0;
    if (fscanf(f, "%lu %lu", &vm, &rss) != 2) { fclose(f); return KERN_FAILURE; }
    fclose(f);
    i->virtual_size = vm * 4096ul; i->resident_size = rss * 4096ul; i->resident_size_max = i->resident_size;
    return KERN_SUCCESS;
}
