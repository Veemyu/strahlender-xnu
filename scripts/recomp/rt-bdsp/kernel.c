// Horizon kernel replacement of the BDSP runtime: handles, real host threads, synchronisation, memory map, SVC dispatcher.
// Own code following the design of LASRecomp runtime/kernel.c (MIT, Copyright (c) 2026 Peiikai, see NOTICE.md):
// the mutex/condvar/arbiter semantics and the handle table are borrowed from there. New: Mach suspension (SVC 0x32/0x33 for
// the Boehm GC), small host stacks, per-thread SVC counters, measurement, no restart mechanism, guest addresses through G2H.
#include <mach/mach.h>
#include <mach/mach_time.h>
#ifdef __APPLE__
#include <mach-o/dyld.h>
#include <sys/sysctl.h>
#endif
#include <sched.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>

#include "bdsp.h"
#include "../c_exact/fp_env.h"

#define PSEUDO_THREAD 0xFFFF8000u
#define PSEUDO_PROCESS 0xFFFF8001u
#define WAITERS_BIT 0x40000000u

pthread_mutex_t g_klock = PTHREAD_MUTEX_INITIALIZER;
static __thread KThread *t_cur;
volatile int g_stop;
uint64_t g_program_id, g_system_resource_size = 0x1000000;

uint64_t rt_now_ns(void) {
    static mach_timebase_info_data_t tb;
    if (!tb.denom) mach_timebase_info(&tb);
    return mach_absolute_time() * tb.numer / tb.denom;
}
uint64_t rt_ticks(void) { return (uint64_t)((__uint128_t)rt_now_ns() * 192 / 10000); }  // 19,2 MHz

// ------------------------------------------------------------------ Handle-Tabelle
#define MAX_HANDLES 16384
static KObject *handles[MAX_HANDLES];
static int handles_used, handles_peak;

static uint32_t handle_alloc(KObject *o) {
    static int hint = 1;
    for (int n = 0; n < MAX_HANDLES; n++) {
        int i = 1 + (hint - 1 + n) % (MAX_HANDLES - 1);
        if (!handles[i]) {
            handles[i] = o;
            o->refs++;
            hint = i + 1;
            if (++handles_used > handles_peak) handles_peak = handles_used;
            return 0x100 + i;
        }
    }
    rt_fatal("Handle-Tabelle voll (%d)\n", MAX_HANDLES);
}

KObject *handle_get(uint32_t h) {
    if (h == PSEUDO_THREAD) return t_cur ? &t_cur->obj : NULL;
    if (h < 0x101 || h >= 0x100 + MAX_HANDLES) return NULL;
    return handles[h - 0x100];
}
uint32_t kernel_new_handle(KObject *o) {
    pthread_mutex_lock(&g_klock);
    uint32_t h = handle_alloc(o);
    pthread_mutex_unlock(&g_klock);
    return h;
}
static void handle_close(uint32_t h) {
    KObject *o = handle_get(h);
    if (!o || h == PSEUDO_THREAD) return;
    handles[h - 0x100] = NULL;
    handles_used--;
    o->refs--;
}

static KThread *g_syncwaiters;
KThread *g_waitlist;
static void wake(KThread *t) { pthread_cond_signal(&t->cond); }

void kernel_signal(KObject *o) {  // caller holds g_klock
    o->signaled = true;
    for (KThread *t = g_syncwaiters; t; t = t->snext) wake(t);
}

KEvent *kernel_create_event_pair(uint32_t *w, uint32_t *r) {
    KEvent *e = calloc(1, sizeof *e);
    e->type = KOBJ_EVENT;
    uint32_t h1 = kernel_new_handle(e), h2 = kernel_new_handle(e);
    if (w) *w = h1;
    if (r) *r = h2;
    return e;
}

KSharedMem *kernel_create_shared_memory(uint64_t size, void (*on_map)(KSharedMem *), uint32_t *handle) {
    KSharedMem *s = calloc(1, sizeof *s);
    s->obj.type = KOBJ_SHMEM;
    s->size = size;
    s->on_map = on_map;
    uint32_t h = kernel_new_handle(&s->obj);
    if (handle) *handle = h;
    return s;
}

static void deadline(struct timespec *ts, int64_t timeout_ns) {
    clock_gettime(CLOCK_REALTIME, ts);
    ts->tv_sec += timeout_ns / 1000000000;
    ts->tv_nsec += timeout_ns % 1000000000;
    if (ts->tv_nsec >= 1000000000) { ts->tv_sec++; ts->tv_nsec -= 1000000000; }
}

static pthread_cond_t g_nothread_cond = PTHREAD_COND_INITIALIZER;
static bool kwait(int64_t timeout_ns, const struct timespec *ts) {
    pthread_cond_t *cv = t_cur ? &t_cur->cond : &g_nothread_cond;
    if (timeout_ns < 0) {  // in slices, so the watchdog can end the run
        struct timespec slice;
        deadline(&slice, 200000000);
        pthread_cond_timedwait(cv, &g_klock, &slice);
        return true;
    }
    return pthread_cond_timedwait(cv, &g_klock, ts) == 0;
}

// ------------------------------------------------------------------ Speicherkarte
typedef struct { uint64_t addr, size; uint32_t type, perm; } Region;
static Region regions[2048];
static int nregions;
static uint64_t heap_size;
static uint64_t phys_mapped, phys_peak;  // bytes mapped by MapPhysicalMemory (current, peak)

// Application memory reported to the SDK (GetInfo 6/21). The game sizes its own heaps and caches from it, so on a phone with 4 GiB
// of RAM a smaller figure is what keeps the field load below the system's page shortage (iPhone 11 Pro Max: killed at 1.98 GiB, stable
// at 1.6 GiB; measured only on that phone). BDSP_APPMEM (hex bytes) overrides; devices with 5 GiB or more keep the full figure.
static uint64_t app_memory(void) {
    if (getenv("BDSP_APPMEM")) return strtoull(getenv("BDSP_APPMEM"), NULL, 16);
#ifdef BDSP_COMPACT_BASE
    uint64_t ram = 0;
    size_t len = sizeof ram;
    if (sysctlbyname("hw.memsize", &ram, &len, NULL, 0) == 0 && ram < (5ull << 30)) return 0x66000000ull;
#endif
    return APP_MEMORY;
}
static uint64_t phys_lo, phys_hi;        // bounding range of all MapPhysicalMemory mappings (for the Metal buffer of the NVN layer)
uint64_t g_phys_unmaps;                  // number of UnmapPhysicalMemory calls: afterwards wrapped pages (Metal) point at discarded pages
void kernel_phys_range(uint64_t *lo, uint64_t *hi) { *lo = phys_lo; *hi = phys_hi; }
static pthread_mutex_t g_rlock = PTHREAD_MUTEX_INITIALIZER;
uint64_t kernel_heap_size(void) { return heap_size; }

static void region_add_locked(uint64_t addr, uint64_t size, uint32_t type, uint32_t perm) {
    if (nregions == 2048) rt_fatal("zu viele Speicherregionen\n");
    int i = nregions++;
    while (i > 0 && regions[i - 1].addr > addr) { regions[i] = regions[i - 1]; i--; }
    regions[i] = (Region){addr, size, type, perm};
}
void kernel_region_add(uint64_t addr, uint64_t size, uint32_t type, uint32_t perm) {
    pthread_mutex_lock(&g_rlock);
    region_add_locked(addr, size, type, perm);
    pthread_mutex_unlock(&g_rlock);
}
static void region_remove(uint64_t addr) {
    pthread_mutex_lock(&g_rlock);
    for (int i = 0; i < nregions; i++)
        if (regions[i].addr == addr) {
            memmove(&regions[i], &regions[i + 1], (nregions - i - 1) * sizeof(Region));
            nregions--;
            break;
        }
    pthread_mutex_unlock(&g_rlock);
}

static void query_memory(uint64_t addr, uint64_t out) {
    uint64_t prev_end = 0, info[5] = {0};  // addr, size, type|attr<<32, perm|ipc<<32, device
    pthread_mutex_lock(&g_rlock);
    int done = 0;
    for (int i = 0; i < nregions && !done; i++) {
        Region *r = &regions[i];
        if (addr >= r->addr && addr < r->addr + r->size) {
            info[0] = r->addr; info[1] = r->size; info[2] = r->type; info[3] = r->perm;
            done = 1;
        } else if (addr < r->addr) {
            info[0] = prev_end; info[1] = r->addr - prev_end;
            done = 1;
        } else prev_end = r->addr + r->size;
    }
    pthread_mutex_unlock(&g_rlock);
    if (!done) { info[0] = prev_end; info[1] = ADDR_SPACE_END - prev_end; }
    memcpy(G2H(out), info, 0x28);
}

// ------------------------------------------------------------------ Threads
static uint64_t next_thread_id = 0x50;
static uint64_t tls_next = TLS_BASE;
static KThread *g_threads;
static int g_thread_count, g_thread_peak, g_thread_live;
static uint64_t g_host_stack = 16ull << 20;

int kernel_thread_count(void) { return g_thread_count; }

static void *thread_main(void *arg) {
    KThread *t = arg;
    t_cur = t;
    t->host_stack_size = pthread_get_stacksize_np(pthread_self());
    t->host_stack_lo = (void *)((uintptr_t)pthread_get_stackaddr_np(pthread_self()) - t->host_stack_size);
    crash_handler_install();
    rt_set_fpcr(0);
    rt_fp_guest_mode();   // host FPU environment as assumed in c mode (docs/recomp-diff.md): RN, no FTZ/DAZ
    pthread_mutex_lock(&g_klock);
    if (++g_thread_live > g_thread_peak) g_thread_peak = g_thread_live;
    pthread_mutex_unlock(&g_klock);
    if (!setjmp(t->unwind)) guest_call(&t->cpu, t->entry);
    pthread_mutex_lock(&g_klock);
    t->finished = true;
    g_thread_live--;
    kernel_signal(&t->obj);
    pthread_mutex_unlock(&g_klock);
    t_cur = NULL;
    return NULL;
}

static KThread *thread_new(uint64_t entry, uint64_t arg, uint64_t stack_top, int prio, int core) {
    KThread *t = calloc(1, sizeof *t);
    pthread_cond_init(&t->cond, NULL);
    t->obj.type = KOBJ_THREAD;
    t->entry = entry;
    t->prio = prio;
    t->core = core < 0 ? 0 : core;
    t->cpu.x[0] = arg;
    t->cpu.sp = stack_top & ~15ull;
    t->cpu.excl_addr = ~0ull;
    pthread_mutex_lock(&g_klock);
    t->id = next_thread_id++;
    t->tlr = tls_next;
    tls_next += 0x200;
    if (tls_next > TLS_BASE + TLS_SIZE) { pthread_mutex_unlock(&g_klock); rt_fatal("TLS area exhausted\n"); }
    t->anext = g_threads;
    g_threads = t;
    g_thread_count++;
    pthread_mutex_unlock(&g_klock);
    t->cpu.tpidrro = t->tlr;
    t->cpu.thread = t;
    return t;
}

static void thread_start(KThread *t, uint64_t host_stack) {
    pthread_attr_t attr;
    pthread_attr_init(&attr);
    t->host_stack_size = host_stack ? host_stack : g_host_stack;
    pthread_attr_setstacksize(&attr, t->host_stack_size);
#ifdef BDSP_IOS
    // The iPad has 4 performance cores for 5 busy guest threads: the game and job threads (Horizon priority 44 or better, lower is
    // more important) get a QoS class so they stay on performance cores. BDSP_QOS=0 switches it off.
    static int qos = -1;
    if (qos < 0) qos = getenv("BDSP_QOS") ? atoi(getenv("BDSP_QOS")) : 1;
    if (qos) {
        if (t->prio <= 32) pthread_attr_set_qos_class_np(&attr, QOS_CLASS_USER_INTERACTIVE, 0);
        else if (t->prio <= 50) pthread_attr_set_qos_class_np(&attr, QOS_CLASS_USER_INITIATED, 0);
    }
#endif
    t->started = true;
    int rc = pthread_create(&t->host, &attr, thread_main, t);
    pthread_attr_destroy(&attr);
    if (rc) rt_fatal("pthread_create: %d (Threads %d)\n", rc, g_thread_count);
}

void kernel_init(void) {
    const char *e = getenv("BDSP_HOST_STACK_MB");
    if (e && atoi(e) > 0) g_host_stack = (uint64_t)atoi(e) << 20;
}

KThread *kernel_create_main_thread(uint64_t entry, uint64_t stack_size, int prio, uint64_t host_stack) {
    uint64_t stack = STACK_BASE + STACK_SIZE - ((stack_size + 0xFFFF) & ~0xFFFFull);
    kernel_region_add(stack, stack_size, 0xB, 3);
    KThread *t = thread_new(entry, 0, stack + stack_size, prio, 0);
    t->stack_lo = stack;
    t->stack_hi = stack + stack_size;
    t->handle = kernel_new_handle(&t->obj);
    t->host_stack_size = host_stack;
    return t;
}
void kernel_run_main(KThread *t, uint64_t x0, uint64_t x1, uint64_t x2, uint64_t x3) {
    t->cpu.x[0] = x0; t->cpu.x[1] = x1; t->cpu.x[2] = x2; t->cpu.x[3] = x3;
    thread_start(t, t->host_stack_size);
}
KThread *kernel_current_thread(void) { return t_cur; }
Cpu *kernel_current_cpu(void) { return t_cur ? &t_cur->cpu : NULL; }

// ------------------------------------------------------------------ Mutex / Condvar (Horizon-Semantik)
static uint32_t *u32p(uint64_t a) { return G2H32(a); }

static bool mutex_acquire_or_mark(uint64_t m, uint32_t tag) {
    for (;;) {
        uint32_t v = __atomic_load_n(u32p(m), __ATOMIC_SEQ_CST);
        if (v == 0) {
            if (__atomic_compare_exchange_n(u32p(m), &v, tag, false, __ATOMIC_SEQ_CST, __ATOMIC_SEQ_CST)) return true;
        } else {
            if ((v & WAITERS_BIT) || __atomic_compare_exchange_n(u32p(m), &v, v | WAITERS_BIT, false, __ATOMIC_SEQ_CST, __ATOMIC_SEQ_CST))
                return false;
        }
    }
}

static void mutex_release(uint64_t addr) {  // g_klock gehalten
    KThread *next = NULL;
    int count = 0;
    for (KThread *t = g_waitlist; t; t = t->wnext)
        if (t->wait_kind == WAIT_MUTEX && t->wait_addr == addr) {
            if (!next || t->prio < next->prio) next = t;
            count++;
        }
    if (!next) { __atomic_store_n(u32p(addr), 0, __ATOMIC_SEQ_CST); return; }
    __atomic_store_n(u32p(addr), next->handle | (count > 1 ? WAITERS_BIT : 0), __ATOMIC_SEQ_CST);
    next->wait_kind = WAIT_NONE;
    next->wait_result = R_OK;
    wake(next);
}

static void waitlist_add(KThread *t) { t->wnext = g_waitlist; g_waitlist = t; }
static void waitlist_remove(KThread *t) {
    for (KThread **p = &g_waitlist; *p; p = &(*p)->wnext)
        if (*p == t) { *p = t->wnext; return; }
}

static uint32_t block_current(int64_t timeout_ns) {  // g_klock gehalten
    KThread *t = t_cur;
    struct timespec ts;
    t->wait_since = rt_now_ns();
    if (timeout_ns >= 0) deadline(&ts, timeout_ns);
    waitlist_add(t);
    while (t->wait_kind != WAIT_NONE) {
        if (t->cancel) { t->cancel = false; t->wait_kind = WAIT_NONE; t->wait_result = R_CANCELLED; break; }
        if (!kwait(timeout_ns, &ts)) {
            // Timeout and wake-up can overlap (pthread_cond_timedwait also reports ETIMEDOUT when the waker held the lock first):
            // if the waker already ended the wait state (mutex handover!), its result counts; otherwise the thread holds the mutex and the
            // SDK code locks it again itself after the timeout (self-deadlock, on the iPad at about every second start in the opening movie)
            if (t->wait_kind != WAIT_NONE) { t->wait_kind = WAIT_NONE; t->wait_result = R_TIMEOUT; }
            break;
        }
    }
    waitlist_remove(t);
    return t->wait_result;
}

static uint32_t svc_arbitrate_lock(uint32_t owner, uint64_t addr, uint32_t tag) {
    pthread_mutex_lock(&g_klock);
    uint32_t v = __atomic_load_n(u32p(addr), __ATOMIC_SEQ_CST);
    if (v != (owner | WAITERS_BIT)) { pthread_mutex_unlock(&g_klock); return R_OK; }
    KThread *t = t_cur;
    t->wait_kind = WAIT_MUTEX; t->wait_addr = addr; t->wait_tag = tag;
    uint32_t r = block_current(-1);
    pthread_mutex_unlock(&g_klock);
    return r == R_CANCELLED ? R_OK : r;
}
static uint32_t svc_arbitrate_unlock(uint64_t addr) {
    pthread_mutex_lock(&g_klock);
    mutex_release(addr);
    pthread_mutex_unlock(&g_klock);
    return R_OK;
}
static uint32_t svc_wait_process_wide_key(uint64_t mutex, uint64_t key, uint32_t tag, int64_t timeout) {
    pthread_mutex_lock(&g_klock);
    KThread *t = t_cur;
    // The key must be set before the mutex is released: the SDK's signal/broadcast read it without the kernel lock and call the SVC only if != 0;
    // whoever takes the mutex next could otherwise lose a signal (lost wake-up, Unity semaphores)
    __atomic_store_n(u32p(key), 1, __ATOMIC_SEQ_CST);
    mutex_release(mutex);
    t->wait_kind = WAIT_CONDVAR; t->wait_addr = key; t->wait_mutex = mutex; t->wait_tag = tag;
    uint32_t r = block_current(timeout);
    if (r != R_OK) {
        // Timeout/cancel: the kernel does NOT take the mutex back (the SDK code locks it again itself; otherwise self-deadlock).
        bool any = false;
        for (KThread *w = g_waitlist; w; w = w->wnext)
            if (w->wait_kind == WAIT_CONDVAR && w->wait_addr == key) any = true;
        if (!any) __atomic_store_n(u32p(key), 0, __ATOMIC_SEQ_CST);
    }
    pthread_mutex_unlock(&g_klock);
    return r;
}
// Trace of the synchronisation SVCs (BDSP_TRACE_SYNC=1): last events per run, printed in the result log
static struct { uint64_t tid, a, b, c; uint32_t svc; } sync_ring[4096];
static uint32_t sync_pos;
static int sync_trace = -1;
static void sync_note(uint32_t svc, uint64_t a, uint64_t b, uint64_t c) {
    if (sync_trace < 0) sync_trace = getenv("BDSP_TRACE_SYNC") != NULL;
    if (!sync_trace) return;
    uint32_t i = __atomic_fetch_add(&sync_pos, 1, __ATOMIC_RELAXED) & 4095;
    sync_ring[i].tid = t_cur ? t_cur->id : 0; sync_ring[i].svc = svc; sync_ring[i].a = a; sync_ring[i].b = b; sync_ring[i].c = c;
}
static int svc_signal_process_wide_key(uint64_t key, int32_t count) {
    pthread_mutex_lock(&g_klock);
    int woken = 0;
    bool any_left = false;
    for (;;) {
        if (count > 0 && woken >= count) break;
        KThread *best = NULL;
        for (KThread *t = g_waitlist; t; t = t->wnext)
            if (t->wait_kind == WAIT_CONDVAR && t->wait_addr == key && (!best || t->prio < best->prio)) best = t;
        if (!best) break;
        woken++;
        uint64_t m = best->wait_mutex;
        best->wait_result = R_OK;
        if (mutex_acquire_or_mark(m, best->wait_tag)) { best->wait_kind = WAIT_NONE; wake(best); }
        else { best->wait_kind = WAIT_MUTEX; best->wait_addr = m; }
    }
    for (KThread *t = g_waitlist; t; t = t->wnext)
        if (t->wait_kind == WAIT_CONDVAR && t->wait_addr == key) any_left = true;
    if (!any_left) __atomic_store_n(u32p(key), 0, __ATOMIC_SEQ_CST);
    pthread_mutex_unlock(&g_klock);
    return woken;
}

// ------------------------------------------------------------------ Address-Arbiter
enum { ARB_WAIT_LESS = 0, ARB_DEC_WAIT_LESS = 1, ARB_WAIT_EQ = 2 };
enum { ARB_SIGNAL = 0, ARB_SIGNAL_INC_EQ = 1, ARB_SIGNAL_MOD_EQ = 2 };

static uint32_t svc_wait_for_address(uint64_t addr, uint32_t type, int32_t value, int64_t timeout) {
    pthread_mutex_lock(&g_klock);
    int32_t cur = (int32_t)__atomic_load_n(u32p(addr), __ATOMIC_SEQ_CST);
    bool wait;
    if (type == ARB_WAIT_LESS) wait = cur < value;
    else if (type == ARB_DEC_WAIT_LESS) { wait = cur < value; if (wait) __atomic_store_n(u32p(addr), (uint32_t)(cur - 1), __ATOMIC_SEQ_CST); }
    else if (type == ARB_WAIT_EQ) wait = cur == value;
    else { pthread_mutex_unlock(&g_klock); return R_INVALID_ENUM; }
    if (!wait) { pthread_mutex_unlock(&g_klock); return R_INVALID_STATE; }
    if (timeout == 0) { pthread_mutex_unlock(&g_klock); return R_TIMEOUT; }
    t_cur->wait_kind = WAIT_ARBITER;
    t_cur->wait_addr = addr;
    uint32_t r = block_current(timeout);
    pthread_mutex_unlock(&g_klock);
    return r;
}
static int arbiter_wake(uint64_t addr, int32_t count) {
    int woken = 0;
    for (KThread *t = g_waitlist; t; t = t->wnext) {
        if (count > 0 && woken >= count) break;
        if (t->wait_kind == WAIT_ARBITER && t->wait_addr == addr) { t->wait_kind = WAIT_NONE; t->wait_result = R_OK; wake(t); woken++; }
    }
    return woken;
}
static uint32_t svc_signal_to_address(uint64_t addr, uint32_t type, int32_t value, int32_t count) {
    pthread_mutex_lock(&g_klock);
    uint32_t r = R_OK;
    int32_t cur = (int32_t)__atomic_load_n(u32p(addr), __ATOMIC_SEQ_CST);
    if (type == ARB_SIGNAL) arbiter_wake(addr, count);
    else if (type == ARB_SIGNAL_INC_EQ) {
        if (cur != value) r = R_INVALID_STATE;
        else { __atomic_store_n(u32p(addr), (uint32_t)(cur + 1), __ATOMIC_SEQ_CST); arbiter_wake(addr, count); }
    } else if (type == ARB_SIGNAL_MOD_EQ) {
        int waiting = 0;
        for (KThread *t = g_waitlist; t; t = t->wnext)
            if (t->wait_kind == WAIT_ARBITER && t->wait_addr == addr) waiting++;
        int32_t nv;
        if (count <= 0) nv = waiting > 0 ? value - 2 : value + 1;
        else nv = waiting == 0 ? value + 1 : (waiting <= count ? value - 1 : value);
        if (cur != value) r = R_INVALID_STATE;
        else { __atomic_store_n(u32p(addr), (uint32_t)nv, __ATOMIC_SEQ_CST); arbiter_wake(addr, count); }
    } else r = R_INVALID_ENUM;
    pthread_mutex_unlock(&g_klock);
    return r;
}

// ------------------------------------------------------------------ WaitSynchronization
static uint32_t svc_wait_synchronization(uint64_t handles_ptr, int32_t count, int64_t timeout, int32_t *index) {
    pthread_mutex_lock(&g_klock);
    struct timespec ts;
    if (timeout > 0) deadline(&ts, timeout);
    KThread *t = t_cur;
    uint32_t *hs = G2H32(handles_ptr);
    t->wait_since = rt_now_ns(); t->wait_h0 = count > 0 ? hs[0] : 0; t->wait_n = count;
    uint32_t r;
    for (;;) {
        for (int i = 0; i < count; i++) {
            KObject *o = handle_get(hs[i]);
            if (!o) { r = R_INVALID_HANDLE; goto out; }
            if (o->signaled) { *index = i; r = R_OK; goto out; }
        }
        if (t->cancel) { t->cancel = false; r = R_CANCELLED; goto out; }
        if (timeout == 0) { r = R_TIMEOUT; goto out; }
        t->in_sync_wait = true;
        t->snext = g_syncwaiters;
        g_syncwaiters = t;
        bool ok = kwait(timeout < 0 ? -1 : timeout, &ts);
        for (KThread **p = &g_syncwaiters; *p; p = &(*p)->snext)
            if (*p == t) { *p = t->snext; break; }
        t->in_sync_wait = false;
        if (!ok) { r = R_TIMEOUT; goto out; }
    }
out:
    pthread_mutex_unlock(&g_klock);
    return r;
}

// ------------------------------------------------------------------ Suspending other threads (Boehm GC)
// SetThreadActivity(handle, paused) -> thread_suspend; GetThreadContext3 returns the guest register set from Cpu.
// The guest keeps its registers only in Cpu and on the guest stack (spike measurement: 100 % of the windows).
uint64_t g_suspends, g_resumes;
static uint32_t svc_set_thread_activity(uint32_t h, uint32_t activity) {
    KObject *o = handle_get(h);
    if (!o || o->type != KOBJ_THREAD) return R_INVALID_HANDLE;
    KThread *t = (KThread *)o;
    if (t == t_cur) return R_INVALID_STATE;
    if (!t->started || t->finished) return R_INVALID_STATE;
    pthread_mutex_lock(&g_klock);  // the target never holds g_klock while being suspended: no host lock stays stuck in the kernel section
    mach_port_t mp = pthread_mach_thread_np(t->host);
    __atomic_fetch_add(activity == 1 ? &g_suspends : &g_resumes, 1, __ATOMIC_RELAXED);
    if (activity == 1 && !t->suspended) { thread_suspend(mp); t->suspended = true; }
    else if (activity == 0 && t->suspended) { thread_resume(mp); t->suspended = false; }
    pthread_mutex_unlock(&g_klock);
    return R_OK;
}

typedef struct {
    uint64_t r[29], fp, lr, sp, pc;
    uint32_t psr, pad;
    __uint128_t v[32];
    uint32_t fpcr, fpsr;
    uint64_t tpidr;
} ThreadContext;

static uint32_t svc_get_thread_context3(uint64_t out, uint32_t h) {
    KObject *o = handle_get(h);
    if (!o || o->type != KOBJ_THREAD) return R_INVALID_HANDLE;
    KThread *t = (KThread *)o;
    if (t == t_cur) return R_INVALID_STATE;
    ThreadContext tc;
    memset(&tc, 0, sizeof tc);
    for (int i = 0; i < 29; i++) tc.r[i] = t->cpu.x[i];
    tc.fp = t->cpu.x[29];
    tc.lr = t->cpu.x[30];
    tc.sp = t->cpu.sp;
    tc.pc = t->cpu.x[30];
    for (int i = 0; i < 32; i++) tc.v[i] = t->cpu.v[i];
    tc.tpidr = t->cpu.tpidr;
    memcpy(G2H(out), &tc, sizeof tc);
    return R_OK;
}

// ------------------------------------------------------------------ SVC dispatcher
static int trace_svc = -1;
static _Atomic uint64_t svc_count[256];
static _Atomic uint64_t svc_first_seen[256];
static const char *svc_name(unsigned n);

static void svc_impl(Cpu *c, uint32_t imm, uint64_t pc);

void rt_svc(Cpu *c, uint32_t imm, uint64_t pc) {
    KThread *t = t_cur;
    if (g_stop) { pthread_exit(NULL); }
    if (t) { t->svc_last = imm; t->svc_calls++; t->svc_last_ns = rt_now_ns(); }
    uint64_t n = ++svc_count[imm & 255];
    if (n == 1) svc_first_seen[imm & 255] = pc;
    if (trace_svc < 0) trace_svc = getenv("BDSP_TRACE_SVC") ? atoi(getenv("BDSP_TRACE_SVC")) : 0;
    if (!trace_svc) { svc_impl(c, imm, pc); rt_fp_guest_mode(); return; }
    uint64_t in[4] = {c->x[0], c->x[1], c->x[2], c->x[3]};
    svc_impl(c, imm, pc);
    rt_fp_guest_mode();
    if (trace_svc > 1 || n <= 3)
        LOG("[svc] t%llu %02x %s(%llx, %llx, %llx, %llx) -> %llx %llx %llx @%llx\n", (unsigned long long)(t ? t->id : 0), imm,
            svc_name(imm), (unsigned long long)in[0], (unsigned long long)in[1], (unsigned long long)in[2], (unsigned long long)in[3],
            (unsigned long long)c->x[0], (unsigned long long)c->x[1], (unsigned long long)c->x[2], (unsigned long long)pc);
}

static const char *svc_name(unsigned n) {
    static const char *t[256] = {
        [0x01] = "SetHeapSize", [0x02] = "SetMemoryPermission", [0x03] = "SetMemoryAttribute", [0x04] = "MapMemory",
        [0x05] = "UnmapMemory", [0x06] = "QueryMemory", [0x07] = "ExitProcess", [0x08] = "CreateThread", [0x09] = "StartThread",
        [0x0A] = "ExitThread", [0x0B] = "SleepThread", [0x0C] = "GetThreadPriority", [0x0D] = "SetThreadPriority",
        [0x0E] = "GetThreadCoreMask", [0x0F] = "SetThreadCoreMask", [0x10] = "GetCurrentProcessorNumber", [0x11] = "SignalEvent",
        [0x12] = "ClearEvent", [0x13] = "MapSharedMemory", [0x14] = "UnmapSharedMemory", [0x15] = "CreateTransferMemory",
        [0x16] = "CloseHandle", [0x17] = "ResetSignal", [0x18] = "WaitSynchronization", [0x19] = "CancelSynchronization",
        [0x1A] = "ArbitrateLock", [0x1B] = "ArbitrateUnlock", [0x1C] = "WaitProcessWideKeyAtomic", [0x1D] = "SignalProcessWideKey",
        [0x1E] = "GetSystemTick", [0x1F] = "ConnectToNamedPort", [0x20] = "SendSyncRequestLight", [0x21] = "SendSyncRequest",
        [0x22] = "SendSyncRequestWithUserBuffer", [0x23] = "SendAsyncRequestWithUserBuffer", [0x24] = "GetProcessId",
        [0x25] = "GetThreadId", [0x26] = "Break", [0x27] = "OutputDebugString", [0x28] = "ReturnFromException", [0x29] = "GetInfo",
        [0x2A] = "FlushEntireDataCache", [0x2B] = "FlushDataCache", [0x2C] = "MapPhysicalMemory", [0x2D] = "UnmapPhysicalMemory",
        [0x2F] = "GetLastThreadInfo", [0x30] = "GetResourceLimitLimitValue", [0x31] = "GetResourceLimitCurrentValue",
        [0x32] = "SetThreadActivity", [0x33] = "GetThreadContext3", [0x34] = "WaitForAddress", [0x35] = "SignalToAddress",
        [0x36] = "SynchronizePreemptionState", [0x37] = "GetResourceLimitPeakValue", [0x45] = "CreateEvent", [0x5F] = "FlushProcessDataCache",
    };
    return t[n & 255] ? t[n & 255] : "?";
}

static void sleep_ns(int64_t ns) {
    if (ns <= 0) { sched_yield(); return; }
    for (uint64_t end = rt_now_ns() + (uint64_t)ns, now; !g_stop && (now = rt_now_ns()) < end;) {
        uint64_t d = end - now < 50000000 ? end - now : 50000000;
        struct timespec ts = {(time_t)(d / 1000000000), (long)(d % 1000000000)};
        nanosleep(&ts, NULL);
    }
}

static void svc_impl(Cpu *c, uint32_t imm, uint64_t pc) {
    uint64_t *x = c->x;
    switch (imm) {
    case 0x01: {  // SetHeapSize
        uint64_t size = x[1];
        if (size > HEAP_MAX) { LOG("[kernel] SetHeapSize %llu MiB > window (%llu MiB)\n", (unsigned long long)(size >> 20), (unsigned long long)(HEAP_MAX >> 20)); x[0] = R_OUT_OF_RESOURCE; break; }
        LOG("[kernel] SetHeapSize %llu MiB (0x%llx)\n", (unsigned long long)(size >> 20), (unsigned long long)size);
        heap_size = size;
        region_remove(HEAP_BASE);
        if (size) kernel_region_add(HEAP_BASE, size, 5, 3);
        x[0] = R_OK; x[1] = HEAP_BASE;
        break;
    }
    case 0x02: case 0x03: x[0] = R_OK; break;
    case 0x04:  // MapMemory(dst, src, size): src is inaccessible meanwhile, copying is equivalent
        memcpy(G2H(x[0]), G2H(x[1]), x[2]);
        kernel_region_add(x[0], x[2], 0xB, 3);
        x[0] = R_OK;
        break;
    case 0x05:
        memcpy(G2H(x[1]), G2H(x[0]), x[2]);
        region_remove(x[0]);
        x[0] = R_OK;
        break;
    case 0x06: query_memory(x[2], x[0]); x[0] = R_OK; x[1] = 0; break;
    case 0x07: LOG("[kernel] ExitProcess\n"); g_stop = 2; fflush(NULL); _exit(0);
    case 0x08: {  // CreateThread(_, entry, arg, stack_top, prio, core)
        KThread *t = thread_new(x[1], x[2], x[3], (int)x[4], (int)(int32_t)x[5]);
        t->handle = kernel_new_handle(&t->obj);
        t->stack_hi = x[3];
        LOG("[kernel] CreateThread #%d entry=%llx arg=%llx stack_top=%llx prio=%d core=%d -> %x\n", g_thread_count, (unsigned long long)x[1],
            (unsigned long long)x[2], (unsigned long long)x[3], (int)x[4], (int)(int32_t)x[5], t->handle);
        x[0] = R_OK; x[1] = t->handle;
        break;
    }
    case 0x09: {
        KObject *o = handle_get((uint32_t)x[0]);
        if (!o || o->type != KOBJ_THREAD) { x[0] = R_INVALID_HANDLE; break; }
        thread_start((KThread *)o, 0);
        x[0] = R_OK;
        break;
    }
    case 0x0A: longjmp(t_cur->unwind, 1);
    case 0x0B: sleep_ns((int64_t)x[0]); break;
    case 0x0C: {
        KObject *o = handle_get((uint32_t)x[1]);
        x[0] = o ? R_OK : R_INVALID_HANDLE;
        x[1] = o ? (uint64_t)((KThread *)o)->prio : 0;
        break;
    }
    case 0x0D: {
        KObject *o = handle_get((uint32_t)x[0]);
        if (o) ((KThread *)o)->prio = (int)x[1];
        x[0] = o ? R_OK : R_INVALID_HANDLE;
        break;
    }
    case 0x0E: {
        KObject *o = handle_get((uint32_t)x[2]);
        x[0] = o ? R_OK : R_INVALID_HANDLE;
        x[1] = o ? (uint64_t)((KThread *)o)->core : 0;
        x[2] = 0xF;
        break;
    }
    case 0x0F: x[0] = R_OK; break;
    case 0x10: x[0] = t_cur ? (uint64_t)t_cur->core : 0; break;
    case 0x11: case 0x12: case 0x17: {  // SignalEvent / ClearEvent / ResetSignal
        pthread_mutex_lock(&g_klock);
        KObject *ev = handle_get((uint32_t)x[0]);
        if (!ev || ev->type != KOBJ_EVENT) x[0] = R_INVALID_HANDLE;
        else {
            x[0] = R_OK;
            if (imm == 0x11) kernel_signal(ev);
            else if (imm == 0x17 && !ev->signaled) x[0] = R_INVALID_STATE;
            else ev->signaled = false;
        }
        pthread_mutex_unlock(&g_klock);
        break;
    }
    case 0x13: {  // MapSharedMemory(handle, addr, size, perm)
        KObject *o = handle_get((uint32_t)x[0]);
        if (!o || o->type != KOBJ_SHMEM) { x[0] = R_INVALID_HANDLE; break; }
        KSharedMem *s = (KSharedMem *)o;
        memset(G2H(x[1]), 0, x[2]);
        s->guest_addr = x[1];
        kernel_region_add(x[1], x[2], 6, 3);
        if (s->on_map) s->on_map(s);
        x[0] = R_OK;
        break;
    }
    case 0x14: region_remove(x[1]); hid_shmem_unmapped(x[1]); x[0] = R_OK; break;
    case 0x15: {
        KTransferMem *t = calloc(1, sizeof *t);
        t->obj.type = KOBJ_TMEM;
        t->addr = x[1]; t->size = x[2];
        x[0] = R_OK; x[1] = kernel_new_handle(&t->obj);
        break;
    }
    case 0x16:
        pthread_mutex_lock(&g_klock);
        handle_close((uint32_t)x[0]);
        pthread_mutex_unlock(&g_klock);
        x[0] = R_OK;
        break;
    case 0x18: {
        int32_t idx = -1;
        x[0] = svc_wait_synchronization(x[1], (int32_t)x[2], (int64_t)x[3], &idx);
        x[1] = (uint32_t)idx;
        break;
    }
    case 0x19: {
        pthread_mutex_lock(&g_klock);
        KObject *o = handle_get((uint32_t)x[0]);
        if (o && o->type == KOBJ_THREAD) { ((KThread *)o)->cancel = true; wake((KThread *)o); x[0] = R_OK; }
        else x[0] = R_INVALID_HANDLE;
        pthread_mutex_unlock(&g_klock);
        break;
    }
    case 0x1A: sync_note(0x1A, x[1], x[0], x[2]); x[0] = svc_arbitrate_lock((uint32_t)x[0], x[1], (uint32_t)x[2]); break;
    case 0x1B: sync_note(0x1B, x[0], 0, 0); x[0] = svc_arbitrate_unlock(x[0]); break;
    case 0x1C: sync_note(0x1C, x[0], x[1], x[3]); x[0] = svc_wait_process_wide_key(x[0], x[1], (uint32_t)x[2], (int64_t)x[3]); break;
    case 0x1D: { uint64_t k = x[0]; int w = svc_signal_process_wide_key(x[0], (int32_t)x[1]); sync_note(0x1D, k, x[1], (uint64_t)w); x[0] = R_OK; break; }
    case 0x1E: x[0] = rt_ticks(); break;
    case 0x1F: {  // ConnectToNamedPort(_, name)
        uint32_t h = ipc_connect_named_port(G2HC(x[1]));
        x[0] = h ? R_OK : R_NOT_FOUND;
        x[1] = h;
        break;
    }
    case 0x20: x[0] = R_NOT_IMPLEMENTED; if (svc_count[imm] <= 3) LOG("[kernel] SendSyncRequestLight (not supported) @%llx\n", (unsigned long long)pc); break;
    case 0x21: t_cur->ipc_calls++; x[0] = ipc_handle_request(c, (uint32_t)x[0]); break;
    case 0x22: {  // SendSyncRequestWithUserBuffer(buf, size, handle)
        uint64_t saved = c->tpidrro;
        c->tpidrro = x[0];
        x[0] = ipc_handle_request(c, (uint32_t)x[2]);
        c->tpidrro = saved;
        break;
    }
    case 0x23:  // SendAsyncRequestWithUserBuffer: no peer with an asynchronous reply
        x[0] = R_NOT_IMPLEMENTED; x[1] = 0;
        if (svc_count[imm] <= 3) LOG("[kernel] SendAsyncRequestWithUserBuffer (not supported) @%llx\n", (unsigned long long)pc);
        break;
    case 0x24: x[0] = R_OK; x[1] = 0x81; break;
    case 0x25: {
        KObject *o = handle_get((uint32_t)x[1]);
        x[0] = o ? R_OK : R_INVALID_HANDLE;
        x[1] = o ? ((KThread *)o)->id : 0;
        break;
    }
    case 0x26:  // Break(reason, info, size)
        if (x[0] & 0x80000000u) { LOG("[kernel] Break (Benachrichtigung) %llx\n", (unsigned long long)x[0]); x[0] = R_OK; break; }
        rt_fatal("svcBreak(reason=%llx, info=%llx, size=%llx) bei %llx, lr=%llx\n", (unsigned long long)x[0], (unsigned long long)x[1],
                 (unsigned long long)x[2], (unsigned long long)pc, (unsigned long long)x[30]);
    case 0x27: {
        uint64_t len = x[1];
        char line[0x401];
        if (len > 0x400) len = 0x400;
        memcpy(line, G2H(x[0]), len);
        line[len] = 0;
        while (len && (line[len - 1] == '\n' || line[len - 1] == '\r')) line[--len] = 0;
        guest_log(line);
        x[0] = R_OK;
        break;
    }
    case 0x28: rt_fatal("svcReturnFromException bei %llx\n", (unsigned long long)pc);
    case 0x29: {  // GetInfo(_, id0, handle, id1)
        uint32_t id0 = (uint32_t)x[1];
        uint64_t v = 0;
        uint32_t r = R_OK;
        switch (id0) {
        case 0: v = 0xF; break;
        case 1: v = 0xFFFFFFFFFFFFFFFFull; break;
        case 2: v = getenv("BDSP_ALIAS_BASE") ? strtoull(getenv("BDSP_ALIAS_BASE"), NULL, 16) : ALIAS_BASE; break;   // Umgebung: Fehlersuche
        case 3: v = getenv("BDSP_ALIAS_SIZE") ? strtoull(getenv("BDSP_ALIAS_SIZE"), NULL, 16) : ALIAS_SIZE; break;
        case 4: v = HEAP_BASE; break;
        case 5: v = HEAP_REPORT; break;
        case 6: case 21: v = app_memory(); break;
        case 7: case 22: v = heap_size + 0x4000000; break;
        case 8: case 9: v = 0; break;
        case 11: v = ((uint64_t)arc4random() << 32) | arc4random(); break;
        case 12: v = GUEST_LO; break;
        case 13: v = GUEST_HI - GUEST_LO; break;
        case 14: v = STACK_BASE; break;
        case 15: v = STACK_SIZE; break;
        case 16: v = g_system_resource_size; break;
        case 17: v = 0; break;
        case 18: v = g_program_id; break;
        case 20: v = 0; break;
        default: r = R_INVALID_ENUM; LOG("[kernel] GetInfo: unbekannte Id %u/%llu\n", id0, (unsigned long long)x[3]);
        }
        x[0] = r; x[1] = v;
        break;
    }
    case 0x2A: case 0x2B: case 0x5F: x[0] = R_OK; break;  // Cache-Wartung: nichts zu tun
    case 0x2C:  // MapPhysicalMemory(addr, size): the window's pages are fresh (zero) and only committed on access
        kernel_region_add(x[0], x[1], 0x7, 3);
        if (getenv("BDSP_TRACE_UNMAP")) LOG("[kernel] MapPhysicalMemory %llx + %llx\n", (unsigned long long)x[0], (unsigned long long)x[1]);
        if (!phys_lo || x[0] < phys_lo) phys_lo = x[0];
        if (x[0] + x[1] > phys_hi) phys_hi = x[0] + x[1];
        if ((phys_mapped += x[1]) > phys_peak) phys_peak = phys_mapped;
        x[0] = R_OK;
        break;
    case 0x2D:  // UnmapPhysicalMemory: discard pages (the next mapping starts with zeros again)
        region_remove(x[0]);
        phys_mapped -= x[1] < phys_mapped ? x[1] : phys_mapped;
        g_phys_unmaps++;
        if (getenv("BDSP_TRACE_UNMAP")) LOG("[kernel] UnmapPhysicalMemory %llx + %llx (Nr. %llu)\n", (unsigned long long)x[0], (unsigned long long)x[1], (unsigned long long)g_phys_unmaps);
        mmap(G2H(x[0]), x[1], PROT_READ | PROT_WRITE, MAP_FIXED | MAP_PRIVATE | MAP_ANON, -1, 0);
        x[0] = R_OK;
        break;
    case 0x2F: x[0] = R_NOT_IMPLEMENTED; break;  // GetLastThreadInfo
    case 0x30: case 0x31: case 0x37: x[0] = R_OK; x[1] = 0; break;  // resource limits: unlimited/0
    case 0x32: x[0] = svc_set_thread_activity((uint32_t)x[0], (uint32_t)x[1]); break;
    case 0x33: x[0] = svc_get_thread_context3(x[0], (uint32_t)x[1]); break;
    case 0x34: x[0] = svc_wait_for_address(x[0], (uint32_t)x[1], (int32_t)x[2], (int64_t)x[3]); break;
    case 0x35: x[0] = svc_signal_to_address(x[0], (uint32_t)x[1], (int32_t)x[2], (int32_t)x[3]); break;
    case 0x36: break;  // SynchronizePreemptionState: nothing to do without a preemptive scheduler
    case 0x45: {
        KObject *ev = calloc(1, sizeof *ev);
        ev->type = KOBJ_EVENT;
        x[0] = R_OK;
        x[1] = kernel_new_handle(ev);
        x[2] = kernel_new_handle(ev);
        break;
    }
    default:
        rt_fatal("unimplemented SVC 0x%x (%s) at %llx (x0=%llx x1=%llx x2=%llx)\n", imm, svc_name(imm), (unsigned long long)pc,
                 (unsigned long long)x[0], (unsigned long long)x[1], (unsigned long long)x[2]);
    }
}

// ------------------------------------------------------------------ Bericht
#include <mach/vm_map.h>
static unsigned resident_stack_kib(KThread *t) {
    if (!t->started || !t->host_stack_lo || t->finished) return 0;
    uintptr_t lo = (uintptr_t)t->host_stack_lo, hi = lo + t->host_stack_size;
    vm_address_t a = lo;
    uint64_t total = 0;
    while (a < hi) {  // resident pages of the host stack (frames of the recompiled functions); vm_region_64 also exists on iOS
        vm_size_t sz = 0;
        vm_region_extended_info_data_t info;
        mach_msg_type_number_t cnt = VM_REGION_EXTENDED_INFO_COUNT;
        mach_port_t obj;
        if (vm_region_64(mach_task_self(), &a, &sz, VM_REGION_EXTENDED_INFO, (vm_region_info_t)&info, &cnt, &obj) != KERN_SUCCESS) break;
        if (a >= hi) break;
        total += (uint64_t)info.pages_resident * vm_page_size;
        a += sz;
    }
    return (unsigned)(total >> 10);
}

#ifdef __APPLE__
// BDSP_HANG_DUMP=1: the report also prints the host thread state of every guest thread and briefly suspends busy ones to read
// their registers. Off by default: it must not run when a normal session ends.
static int hang_dump_on(void) {
    static int on = -1;
    if (on < 0) on = getenv("BDSP_HANG_DUMP") != NULL;
    return on;
}
#endif

void kernel_report(FILE *f) {
    fprintf(f, "Threads created %d (at most %d at once, now %d), handles now %d (peak %d), SetHeapSize heap %llu MiB, mapped by MapPhysicalMemory %llu MiB (peak %llu MiB)\n",
            g_thread_count, g_thread_peak, g_thread_live, handles_used, handles_peak, (unsigned long long)(heap_size >> 20),
            (unsigned long long)(phys_mapped >> 20), (unsigned long long)(phys_peak >> 20));
    fprintf(f, "SetThreadActivity: %llu suspends, %llu resumes\n", (unsigned long long)g_suspends, (unsigned long long)g_resumes);
    fprintf(f, "SVC counters:");
    uint64_t total = 0;
    int distinct = 0;
    for (int i = 0; i < 256; i++)
        if (svc_count[i]) { fprintf(f, " %02x=%llu", i, (unsigned long long)svc_count[i]); total += svc_count[i]; distinct++; }
    fprintf(f, "\n%d distinct SVCs, %llu calls\n", distinct, (unsigned long long)total);
    pthread_mutex_lock(&g_klock);
    int shown = 0;
    for (KThread *t = g_threads; t && shown < 64; t = t->anext, shown++) {
        fprintf(f, "  Thread %llu: entry %llx, %s, last SVC %02x (%s), %llu SVCs, %llu IPC, host stack %u KiB used of %llu KiB, guest sp %llx\n",
                (unsigned long long)t->id, (unsigned long long)t->entry, t->finished ? "finished" : (t->started ? "running" : "not started"),
                (unsigned)t->svc_last, svc_name((unsigned)t->svc_last), (unsigned long long)t->svc_calls, (unsigned long long)t->ipc_calls,
                resident_stack_kib(t), (unsigned long long)(t->host_stack_size >> 10), (unsigned long long)t->cpu.sp);
        if (getenv("BDSP_BT") || getenv("BDSP_WAIT")) {   // wait state: kind, address/key, duration
            uint64_t now = rt_now_ns();
            const char *k = t->in_sync_wait ? "WaitSynchronization" : t->wait_kind == WAIT_MUTEX ? "Mutex" : t->wait_kind == WAIT_CONDVAR ? "ProcessWideKey" :
                            t->wait_kind == WAIT_ARBITER ? "Arbiter" : "(running/sleeping)";
            fprintf(f, "      waiting: %s addr %llx mutex %llx handle0 %x/%d since %.1f s, last SVC %.1f s ago\n", k, (unsigned long long)t->wait_addr,
                    (unsigned long long)t->wait_mutex, t->wait_h0, t->wait_n, t->wait_since ? (now - t->wait_since) / 1e9 : 0.0,
                    t->svc_last_ns ? (now - t->svc_last_ns) / 1e9 : 0.0);
#ifdef __APPLE__
            if (hang_dump_on() && t->started && !t->finished) {   // hang diagnosis: is the host thread stopped (suspend count > 0) although it should be running?
                thread_basic_info_data_t bi;
                mach_msg_type_number_t cnt = THREAD_BASIC_INFO_COUNT;
                if (thread_info(pthread_mach_thread_np(t->host), THREAD_BASIC_INFO, (thread_info_t)&bi, &cnt) == KERN_SUCCESS) {
                    fprintf(f, "      host thread: suspend count %d, state %d (1 running, 2 stopped, 3 waiting, 4 uninterruptible), load %d/1000, t->suspended %d\n",
                            (int)bi.suspend_count, (int)bi.run_state, (int)bi.cpu_usage, (int)t->suspended);
                    if (bi.run_state == TH_STATE_RUNNING && bi.cpu_usage > 500 && t != t_cur) {   // busy thread: program counter (image address = pc - slide)
                        mach_port_t mp = pthread_mach_thread_np(t->host);
                        arm_thread_state64_t st;
                        mach_msg_type_number_t sc = ARM_THREAD_STATE64_COUNT;
                        thread_suspend(mp);
                        if (thread_get_state(mp, ARM_THREAD_STATE64, (thread_state_t)&st, &sc) == KERN_SUCCESS) {
                            fprintf(f, "      host thread pc %llx lr %llx fp %llx sp %llx (slide %llx, image address pc %llx lr %llx)\n",
                                    (unsigned long long)arm_thread_state64_get_pc(st), (unsigned long long)arm_thread_state64_get_lr(st),
                                    (unsigned long long)arm_thread_state64_get_fp(st), (unsigned long long)arm_thread_state64_get_sp(st),
                                    (unsigned long long)_dyld_get_image_vmaddr_slide(0), (unsigned long long)(arm_thread_state64_get_pc(st) - _dyld_get_image_vmaddr_slide(0)),
                                    (unsigned long long)(arm_thread_state64_get_lr(st) - _dyld_get_image_vmaddr_slide(0)));
                            fprintf(f, "      host registers x0-x5 %llx %llx %llx %llx %llx %llx, x8 %llx x14 %llx x16 %llx x18 %llx\n", (unsigned long long)st.__x[0],
                                    (unsigned long long)st.__x[1], (unsigned long long)st.__x[2], (unsigned long long)st.__x[3], (unsigned long long)st.__x[4],
                                    (unsigned long long)st.__x[5], (unsigned long long)st.__x[8], (unsigned long long)st.__x[14], (unsigned long long)st.__x[16],
                                    (unsigned long long)st.__x[18]);
                            if (st.__x[0] >= 0x10000 && st.__x[0] < 0xFFFFF000ull) {   // guest pointer x0 (here the LIFO): head and first entries
                                const uint32_t *w = G2H32(st.__x[0]);
                                fprintf(f, "      guest memory at x0:");
                                for (int k = 0; k < 24; k++) fprintf(f, " %08x", w[k]);
                                fprintf(f, "\n");
                            }
                        }
                        thread_resume(mp);
                    }
                }
            }
#endif
            if (t->wait_kind == WAIT_MUTEX || (t->wait_kind == WAIT_CONDVAR && t->wait_mutex)) {   // owner of the mutex (deadlock search)
                uint64_t ma = t->wait_kind == WAIT_MUTEX ? t->wait_addr : t->wait_mutex;
                uint32_t v = *G2H32(ma), ow = v & ~WAITERS_BIT;
                KThread *o = NULL;
                for (KThread *x = g_threads; x; x = x->anext) if (x->handle == ow) o = x;
                fprintf(f, "      Mutex %llx = %08x: owner thread %llu (%s, last SVC %02x)\n", (unsigned long long)ma, v, o ? (unsigned long long)o->id : 0ull,
                        !o ? "unknown" : o->finished ? "FINISHED" : o->wait_kind == WAIT_MUTEX ? "waiting for mutex" : o->wait_kind == WAIT_CONDVAR ? "waiting for key" :
                        o->in_sync_wait ? "WaitSynchronization" : "running/sleeping", o ? (unsigned)o->svc_last : 0u);
            }
        }
        if (getenv("BDSP_BT") && t->svc_calls > 20) {   // return addresses from the frame chain (x29), only for threads with activity
            uint64_t fp = t->cpu.x[29], off = 0;
            const char *s0 = loader_symbol_at(t->cpu.x[30], &off);
            fprintf(f, "      lr %llx %s+%llx\n", (unsigned long long)t->cpu.x[30], s0 ? s0 : "?", (unsigned long long)off);
            for (int n = 0; n < 16 && fp >= STACK_BASE && fp < STACK_BASE + STACK_SIZE; n++) {
                uint64_t lr = *G2H64(fp + 8);
                const char *s = loader_symbol_at(lr, &off);
                fprintf(f, "      #%d %llx %s+%llx\n", n, (unsigned long long)lr, s ? s : "?", (unsigned long long)off);
                uint64_t next = *G2H64(fp);
                if (next <= fp) break;
                fp = next;
            }
        }
    }
    pthread_mutex_unlock(&g_klock);
    if (sync_trace > 0) {   // last 300 events (oldest first): 1C = wait (mutex, key, time limit), 1D = signal (key, count, woken)
        fprintf(f, "Synchronization, last events:\n");
        uint32_t end = sync_pos, lim = (uint32_t)atoi(getenv("BDSP_TRACE_SYNC")), n = end < lim ? end : lim;
        if (n > 4096) n = 4096;
        for (uint32_t k = end - n; k < end; k++) {
            uint32_t i = k & 4095;
            fprintf(f, "  T%llu %s mutex/key=%llx %llx %lld\n", (unsigned long long)sync_ring[i].tid, sync_ring[i].svc == 0x1C ? "WAIT  " : sync_ring[i].svc == 0x1A ? "LOCK  " : sync_ring[i].svc == 0x1B ? "UNLOCK" : "SIGNAL",
                    (unsigned long long)sync_ring[i].a, (unsigned long long)sync_ring[i].b, (long long)sync_ring[i].c);
        }
    }
}
