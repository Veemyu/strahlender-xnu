// Horizon-Kernel-Ersatz der BDSP-Laufzeit: Handles, echte Host-Threads, Synchronisation, Speicherkarte, SVC-Verteiler.
// Eigener Code auf dem Entwurf von LASRecomp runtime/kernel.c (MIT, Copyright (c) 2026 Peiikai, siehe NOTICE.md):
// Mutex-/Condvar-/Arbiter-Semantik und die Handle-Tabelle sind dort entlehnt. Neu: Mach-Anhalten (SVC 0x32/0x33 für
// den Boehm-GC), kleine Host-Stacks, SVC-Zähler je Thread, Messung, kein Neustart-Mechanismus, Gast-Adressen über G2H.
#include <mach/mach.h>
#include <mach/mach_time.h>
#include <sched.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>

#include "bdsp.h"

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

void kernel_signal(KObject *o) {  // Aufrufer hält g_klock
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
    if (timeout_ns < 0) {  // in Scheiben, damit der Watchdog den Lauf beenden kann
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
static uint64_t phys_mapped, phys_peak;  // per MapPhysicalMemory abgebildete Bytes (aktuell, Spitze)
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
    if (!done) { info[0] = prev_end; info[1] = (1ull << 39) - prev_end; }
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
    if (tls_next > TLS_BASE + TLS_SIZE) { pthread_mutex_unlock(&g_klock); rt_fatal("TLS-Bereich erschöpft\n"); }
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
    if (timeout_ns >= 0) deadline(&ts, timeout_ns);
    waitlist_add(t);
    while (t->wait_kind != WAIT_NONE) {
        if (t->cancel) { t->cancel = false; t->wait_kind = WAIT_NONE; t->wait_result = R_CANCELLED; break; }
        if (!kwait(timeout_ns, &ts)) { t->wait_kind = WAIT_NONE; t->wait_result = R_TIMEOUT; break; }
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
    mutex_release(mutex);
    t->wait_kind = WAIT_CONDVAR; t->wait_addr = key; t->wait_mutex = mutex; t->wait_tag = tag;
    __atomic_store_n(u32p(key), 1, __ATOMIC_SEQ_CST);
    uint32_t r = block_current(timeout);
    if (r != R_OK) {
        if (!mutex_acquire_or_mark(mutex, tag)) { t->wait_kind = WAIT_MUTEX; t->wait_addr = mutex; block_current(-1); }
    }
    pthread_mutex_unlock(&g_klock);
    return r;
}
static void svc_signal_process_wide_key(uint64_t key, int32_t count) {
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

// ------------------------------------------------------------------ Anhalten fremder Threads (Boehm-GC)
// SetThreadActivity(handle, paused) -> thread_suspend; GetThreadContext3 liefert den Gast-Registersatz aus Cpu.
// Der Gast hält seine Register nur in Cpu und auf dem Gast-Stack (Messung im Spike: 100 % der Fenster).
static uint32_t svc_set_thread_activity(uint32_t h, uint32_t activity) {
    KObject *o = handle_get(h);
    if (!o || o->type != KOBJ_THREAD) return R_INVALID_HANDLE;
    KThread *t = (KThread *)o;
    if (t == t_cur) return R_INVALID_STATE;
    if (!t->started || t->finished) return R_INVALID_STATE;
    pthread_mutex_lock(&g_klock);  // das Ziel hält g_klock nie im Anhalten: kein Host-Lock bleibt in der Kernel-Sektion hängen
    mach_port_t mp = pthread_mach_thread_np(t->host);
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

// ------------------------------------------------------------------ SVC-Verteiler
static int trace_svc = -1;
static _Atomic uint64_t svc_count[256];
static _Atomic uint64_t svc_first_seen[256];
static const char *svc_name(unsigned n);

static void svc_impl(Cpu *c, uint32_t imm, uint64_t pc);

void rt_svc(Cpu *c, uint32_t imm, uint64_t pc) {
    KThread *t = t_cur;
    if (g_stop) { pthread_exit(NULL); }
    if (t) { t->svc_last = imm; t->svc_calls++; }
    uint64_t n = ++svc_count[imm & 255];
    if (n == 1) svc_first_seen[imm & 255] = pc;
    if (trace_svc < 0) trace_svc = getenv("BDSP_TRACE_SVC") ? atoi(getenv("BDSP_TRACE_SVC")) : 0;
    if (!trace_svc) return svc_impl(c, imm, pc);
    uint64_t in[4] = {c->x[0], c->x[1], c->x[2], c->x[3]};
    svc_impl(c, imm, pc);
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
        if (size > HEAP_MAX) { LOG("[kernel] SetHeapSize %llu MiB > Fenster (%llu MiB)\n", (unsigned long long)(size >> 20), (unsigned long long)(HEAP_MAX >> 20)); x[0] = R_OUT_OF_RESOURCE; break; }
        LOG("[kernel] SetHeapSize %llu MiB (0x%llx)\n", (unsigned long long)(size >> 20), (unsigned long long)size);
        heap_size = size;
        region_remove(HEAP_BASE);
        if (size) kernel_region_add(HEAP_BASE, size, 5, 3);
        x[0] = R_OK; x[1] = HEAP_BASE;
        break;
    }
    case 0x02: case 0x03: x[0] = R_OK; break;
    case 0x04:  // MapMemory(dst, src, size): src ist währenddessen unzugänglich, Kopieren ist gleichwertig
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
    case 0x14: region_remove(x[1]); x[0] = R_OK; break;
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
    case 0x1A: x[0] = svc_arbitrate_lock((uint32_t)x[0], x[1], (uint32_t)x[2]); break;
    case 0x1B: x[0] = svc_arbitrate_unlock(x[0]); break;
    case 0x1C: x[0] = svc_wait_process_wide_key(x[0], x[1], (uint32_t)x[2], (int64_t)x[3]); break;
    case 0x1D: svc_signal_process_wide_key(x[0], (int32_t)x[1]); x[0] = R_OK; break;
    case 0x1E: x[0] = rt_ticks(); break;
    case 0x1F: {  // ConnectToNamedPort(_, name)
        uint32_t h = ipc_connect_named_port(G2HC(x[1]));
        x[0] = h ? R_OK : R_NOT_FOUND;
        x[1] = h;
        break;
    }
    case 0x20: x[0] = R_NOT_IMPLEMENTED; if (svc_count[imm] <= 3) LOG("[kernel] SendSyncRequestLight (nicht unterstützt) @%llx\n", (unsigned long long)pc); break;
    case 0x21: t_cur->ipc_calls++; x[0] = ipc_handle_request(c, (uint32_t)x[0]); break;
    case 0x22: {  // SendSyncRequestWithUserBuffer(buf, size, handle)
        uint64_t saved = c->tpidrro;
        c->tpidrro = x[0];
        x[0] = ipc_handle_request(c, (uint32_t)x[2]);
        c->tpidrro = saved;
        break;
    }
    case 0x23:  // SendAsyncRequestWithUserBuffer: keine Gegenstelle mit asynchroner Antwort
        x[0] = R_NOT_IMPLEMENTED; x[1] = 0;
        if (svc_count[imm] <= 3) LOG("[kernel] SendAsyncRequestWithUserBuffer (nicht unterstützt) @%llx\n", (unsigned long long)pc);
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
        case 2: v = ALIAS_BASE; break;
        case 3: v = ALIAS_SIZE; break;
        case 4: v = HEAP_BASE; break;
        case 5: v = HEAP_MAX; break;
        case 6: case 21: v = 0xCD500000ull; break;  // Anwendungsspeicher (ca. 3,2 GB wie auf der Konsole)
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
    case 0x2C:  // MapPhysicalMemory(addr, size): die Seiten des Fensters sind frisch (null) und werden erst beim Zugriff belegt
        kernel_region_add(x[0], x[1], 0x7, 3);
        if ((phys_mapped += x[1]) > phys_peak) phys_peak = phys_mapped;
        x[0] = R_OK;
        break;
    case 0x2D:  // UnmapPhysicalMemory: Seiten verwerfen (nächste Abbildung beginnt wieder mit Nullen)
        region_remove(x[0]);
        phys_mapped -= x[1] < phys_mapped ? x[1] : phys_mapped;
        mmap(G2H(x[0]), x[1], PROT_READ | PROT_WRITE, MAP_FIXED | MAP_PRIVATE | MAP_ANON, -1, 0);
        x[0] = R_OK;
        break;
    case 0x2F: x[0] = R_NOT_IMPLEMENTED; break;  // GetLastThreadInfo
    case 0x30: case 0x31: case 0x37: x[0] = R_OK; x[1] = 0; break;  // Ressourcenlimits: unbegrenzt/0
    case 0x32: x[0] = svc_set_thread_activity((uint32_t)x[0], (uint32_t)x[1]); break;
    case 0x33: x[0] = svc_get_thread_context3(x[0], (uint32_t)x[1]); break;
    case 0x34: x[0] = svc_wait_for_address(x[0], (uint32_t)x[1], (int32_t)x[2], (int64_t)x[3]); break;
    case 0x35: x[0] = svc_signal_to_address(x[0], (uint32_t)x[1], (int32_t)x[2], (int32_t)x[3]); break;
    case 0x36: break;  // SynchronizePreemptionState: ohne Vorrang-Scheduler nichts zu tun
    case 0x45: {
        KObject *ev = calloc(1, sizeof *ev);
        ev->type = KOBJ_EVENT;
        x[0] = R_OK;
        x[1] = kernel_new_handle(ev);
        x[2] = kernel_new_handle(ev);
        break;
    }
    default:
        rt_fatal("nicht umgesetzte SVC 0x%x (%s) bei %llx (x0=%llx x1=%llx x2=%llx)\n", imm, svc_name(imm), (unsigned long long)pc,
                 (unsigned long long)x[0], (unsigned long long)x[1], (unsigned long long)x[2]);
    }
}

// ------------------------------------------------------------------ Bericht
#include <mach/mach_vm.h>
static unsigned resident_stack_kib(KThread *t) {
    if (!t->started || !t->host_stack_lo || t->finished) return 0;
    uintptr_t lo = (uintptr_t)t->host_stack_lo, hi = lo + t->host_stack_size;
    mach_vm_address_t a = lo;
    uint64_t total = 0;
    while (a < hi) {  // belegte Seiten des Host-Stacks (Rahmen der rekompilierten Funktionen)
        mach_vm_size_t sz = 0;
        vm_region_extended_info_data_t info;
        mach_msg_type_number_t cnt = VM_REGION_EXTENDED_INFO_COUNT;
        mach_port_t obj;
        if (mach_vm_region(mach_task_self(), &a, &sz, VM_REGION_EXTENDED_INFO, (vm_region_info_t)&info, &cnt, &obj) != KERN_SUCCESS) break;
        if (a >= hi) break;
        total += (uint64_t)info.pages_resident * vm_page_size;
        a += sz;
    }
    return (unsigned)(total >> 10);
}

void kernel_report(FILE *f) {
    fprintf(f, "Threads angelegt %d (gleichzeitig höchstens %d, aktuell %d), Handles aktuell %d (Spitze %d), SetHeapSize-Heap %llu MiB, per MapPhysicalMemory abgebildet %llu MiB (Spitze %llu MiB)\n",
            g_thread_count, g_thread_peak, g_thread_live, handles_used, handles_peak, (unsigned long long)(heap_size >> 20),
            (unsigned long long)(phys_mapped >> 20), (unsigned long long)(phys_peak >> 20));
    fprintf(f, "SVC-Zähler:");
    uint64_t total = 0;
    int distinct = 0;
    for (int i = 0; i < 256; i++)
        if (svc_count[i]) { fprintf(f, " %02x=%llu", i, (unsigned long long)svc_count[i]); total += svc_count[i]; distinct++; }
    fprintf(f, "\n%d verschiedene SVCs, %llu Aufrufe\n", distinct, (unsigned long long)total);
    pthread_mutex_lock(&g_klock);
    int shown = 0;
    for (KThread *t = g_threads; t && shown < 64; t = t->anext, shown++) {
        fprintf(f, "  Thread %llu: entry %llx, %s, letzte SVC %02x (%s), %llu SVCs, %llu IPC, Host-Stack %u KiB belegt von %llu KiB, Gast-sp %llx\n",
                (unsigned long long)t->id, (unsigned long long)t->entry, t->finished ? "beendet" : (t->started ? "läuft" : "nicht gestartet"),
                (unsigned)t->svc_last, svc_name((unsigned)t->svc_last), (unsigned long long)t->svc_calls, (unsigned long long)t->ipc_calls,
                resident_stack_kib(t), (unsigned long long)(t->host_stack_size >> 10), (unsigned long long)t->cpu.sp);
    }
    pthread_mutex_unlock(&g_klock);
}
