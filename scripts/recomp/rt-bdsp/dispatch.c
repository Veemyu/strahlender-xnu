// Verteiler der BDSP-Laufzeit: Gastadresse -> rekompilierte Funktion (4 Tabellen), HLE-Slots, Wiedereinstieg der
// Exception-Mechanik (Landing-Pads, setjmp-Rücksprünge), Abbruch- und Absturzmeldungen. Eigener Code.
#include <dlfcn.h>
#include <execinfo.h>
#include <signal.h>
#include <stdarg.h>
#include <unistd.h>

#include "bdsp.h"

extern const uint64_t main_fn_addrs[]; extern const GuestFn main_fn_ptrs[]; extern const uint64_t main_fn_count;
extern const uint64_t sdk_fn_addrs[]; extern const GuestFn sdk_fn_ptrs[]; extern const uint64_t sdk_fn_count;
extern const uint64_t subsdk0_fn_addrs[]; extern const GuestFn subsdk0_fn_ptrs[]; extern const uint64_t subsdk0_fn_count;
extern const uint64_t rtld_fn_addrs[]; extern const GuestFn rtld_fn_ptrs[]; extern const uint64_t rtld_fn_count;

typedef struct { const uint64_t *addrs; const GuestFn *fns; uint64_t count, lo, hi; } FnTable;
static FnTable tables[4];
volatile int g_fnprof;

// ---- HLE-Slots: Scheinadressen HLE_BASE + 16 * i
#define MAX_HLE 4096
static struct { char *name; HostFn fn; uint64_t calls, ncall; } hle_slots[MAX_HLE];
static int hle_count;
static pthread_mutex_t hle_lock = PTHREAD_MUTEX_INITIALIZER;

uint64_t hle_register(const char *name, HostFn fn) {
    pthread_mutex_lock(&hle_lock);
    for (int i = 0; i < hle_count; i++)
        if (!strcmp(hle_slots[i].name, name)) {
            if (fn && !hle_slots[i].fn) hle_slots[i].fn = fn;
            pthread_mutex_unlock(&hle_lock);
            return HLE_BASE + 16ull * i;
        }
    if (hle_count == MAX_HLE) { pthread_mutex_unlock(&hle_lock); rt_fatal("zu viele HLE-Slots\n"); }
    hle_slots[hle_count].name = strdup(name);
    hle_slots[hle_count].fn = fn;
    uint64_t a = HLE_BASE + 16ull * hle_count++;
    pthread_mutex_unlock(&hle_lock);
    return a;
}

// ---- Beobachtungsadressen (Gate-Erkennung): bei jedem Aufruf über rt_dispatch gezählt und protokolliert
#define MAX_WATCH 32
static struct { uint64_t addr; char name[48]; uint64_t hits; } watches[MAX_WATCH];
static int nwatch;
volatile uint64_t g_watch_hits;
void watch_add(uint64_t addr, const char *name) {
    if (nwatch == MAX_WATCH) return;
    watches[nwatch].addr = addr;
    snprintf(watches[nwatch].name, sizeof watches[nwatch].name, "%s", name);
    nwatch++;
}
static uint64_t g_nle_enters, g_nle_frames;
void gate_report(FILE *f) {
    fprintf(f, "Exception-/longjmp-Wiedereinstiege: %llu (abgewickelte Host-Rahmen %llu)\n", (unsigned long long)g_nle_enters, (unsigned long long)g_nle_frames);
    for (int i = 0; i < nwatch; i++)
        fprintf(f, "  Beobachtung %s @%llx: %llu Aufrufe über den Verteiler\n", watches[i].name, (unsigned long long)watches[i].addr, (unsigned long long)watches[i].hits);
}

// BDSP_IL2SYM=<tsv> (Adresse hex <TAB> Name, aufsteigend; erzeugt aus den IL2CPP-Metadaten): jede IL2CPP-Methode beim ersten Aufruf melden
static struct { uint64_t addr; char *name; } *il2_syms;
static char *il2_seen;
static size_t il2_n;
static void il2_load(const char *path) {
    FILE *f = fopen(path, "r");
    if (!f) return;
    size_t cap = 0;
    char line[1024];
    while (fgets(line, sizeof line, f)) {
        char *tab = strchr(line, '\t');
        if (!tab) continue;
        *tab = 0;
        tab++;
        tab[strcspn(tab, "\n")] = 0;
        if (il2_n == cap) { cap = cap ? cap * 2 : 1 << 16; il2_syms = realloc(il2_syms, cap * sizeof *il2_syms); }
        il2_syms[il2_n].addr = strtoull(line, NULL, 16);
        il2_syms[il2_n].name = strdup(tab);
        il2_n++;
    }
    fclose(f);
    il2_seen = calloc(il2_n + 1, 1);
}
static int il2_cmp(const void *a, const void *b) {
    uint64_t x = ((const typeof(*il2_syms) *)a)->addr, y = ((const typeof(*il2_syms) *)b)->addr;
    return x < y ? -1 : x > y;
}
static void il2_hit(uint64_t a) {
    size_t lo = 0, hi = il2_n;
    while (lo < hi) {
        size_t m = (lo + hi) / 2;
        if (il2_syms[m].addr < a) lo = m + 1; else hi = m;
    }
    if (lo >= il2_n || il2_syms[lo].addr != a) return;
    if (__atomic_exchange_n(&il2_seen[lo], 1, __ATOMIC_RELAXED)) return;
    KThread *kt = kernel_current_thread();
    static uint64_t t0;
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    uint64_t ms = (uint64_t)ts.tv_sec * 1000 + ts.tv_nsec / 1000000;
    if (!t0) t0 = ms;
    fprintf(stderr, "[il2] %6llu ms t%llu %s\n", (unsigned long long)(ms - t0), (unsigned long long)(kt ? kt->id : 0), il2_syms[lo].name);
}
// ---- Funktionsring (BDSP_FNPROF=1: jeder Funktionseintritt kostet einen Aufruf)
#define RING 4096
static __thread uint64_t ring_fn[RING], ring_lr[RING];
static __thread unsigned ring_pos;
static struct { uint64_t tid; uint64_t *fn, *lr; unsigned *pos; } ring_reg[128];
static int ring_nreg;
void fnprof_hit(uint64_t a, uint64_t lr, uint64_t x0) {
    (void)x0;
    static __thread int registered;
    if (il2_n) il2_hit(a);
    if (!registered) {
        registered = 1;
        KThread *kt = kernel_current_thread();
        int i = __atomic_fetch_add(&ring_nreg, 1, __ATOMIC_SEQ_CST);
        if (i < 128) { ring_reg[i].tid = kt ? kt->id : 0; ring_reg[i].fn = ring_fn; ring_reg[i].lr = ring_lr; ring_reg[i].pos = &ring_pos; }
    }
    ring_fn[ring_pos & (RING - 1)] = a; ring_lr[ring_pos & (RING - 1)] = lr; ring_pos++;
}
// BDSP_RINGDUMP=n (mit BDSP_FNPROF=1): die letzten n Funktionseintritte der Threads mit mehr als 50 Eintritten im Ergebnisprotokoll
void fnprof_report(FILE *f, unsigned n) {
    for (int i = 0; i < ring_nreg && i < 128; i++) {
        unsigned pos = *ring_reg[i].pos;
        if (pos < 50) continue;
        fprintf(f, "Thread %llu: %u Funktionseintritte, die letzten %u (älteste zuerst, Aufrufer):\n", (unsigned long long)ring_reg[i].tid, pos, n);
        for (unsigned k = n; k-- > 0;) {
            if (pos < k + 1) continue;
            unsigned j = (pos - 1 - k) & (RING - 1);
            uint64_t off = 0, off2 = 0;
            const char *s = loader_symbol_at(ring_reg[i].fn[j], &off);
            fprintf(f, "  %llx %s+%llx (lr %llx)\n", (unsigned long long)ring_reg[i].fn[j], s ? s : "", (unsigned long long)off, (unsigned long long)ring_reg[i].lr[j]);
            (void)off2;
        }
    }
}

void dispatch_init(void) {
    tables[0] = (FnTable){main_fn_addrs, main_fn_ptrs, main_fn_count, main_fn_addrs[0], main_fn_addrs[main_fn_count - 1]};
    tables[1] = (FnTable){sdk_fn_addrs, sdk_fn_ptrs, sdk_fn_count, sdk_fn_addrs[0], sdk_fn_addrs[sdk_fn_count - 1]};
    tables[2] = (FnTable){subsdk0_fn_addrs, subsdk0_fn_ptrs, subsdk0_fn_count, subsdk0_fn_addrs[0], subsdk0_fn_addrs[subsdk0_fn_count - 1]};
    tables[3] = (FnTable){rtld_fn_addrs, rtld_fn_ptrs, rtld_fn_count, rtld_fn_addrs[0], rtld_fn_addrs[rtld_fn_count - 1]};
    if (getenv("BDSP_FNPROF")) g_fnprof = 1;
    if (getenv("BDSP_IL2SYM")) {
        il2_load(getenv("BDSP_IL2SYM"));
        if (il2_n) qsort(il2_syms, il2_n, sizeof *il2_syms, il2_cmp);
        g_fnprof = 1;
    }
}

GuestFn dispatch_lookup(uint64_t addr) {
    for (int t = 0; t < 4; t++) {
        FnTable *ft = &tables[t];
        if (addr < ft->lo || addr > ft->hi) continue;
        uint64_t lo = 0, hi = ft->count;
        while (lo < hi) {
            uint64_t mid = (lo + hi) / 2;
            if (ft->addrs[mid] < addr) lo = mid + 1; else hi = mid;
        }
        if (lo < ft->count && ft->addrs[lo] == addr) return ft->fns[lo];
    }
    return NULL;
}

#define DCACHE 4096
static __thread struct { uint64_t addr; GuestFn fn; } dcache[DCACHE];

static __thread int t_hle_slot = -1;
int hle_current_slot(void) { return t_hle_slot; }  // Slot des gerade laufenden HLE-Aufrufs (nur gültig in der Host-Funktion)
const char *hle_slot_name(int i) { return i >= 0 && i < hle_count ? hle_slots[i].name : "?"; }

// Importe ohne Host-Umsetzung, die der Gast aufgerufen hat (Name, Aufrufzahl): die fehlenden NVN-Funktionen von Gate 2
int hle_unimpl_report(FILE *f) {
    int n = 0;
    for (int i = 0; i < hle_count; i++)
        if (!hle_slots[i].fn && hle_slots[i].calls) { fprintf(f, "  fehlt: %s: %llu Aufrufe\n", hle_slots[i].name, (unsigned long long)hle_slots[i].calls); n++; }
    return n;
}

static void hle_unimplemented(Cpu *c) { c->x[0] = 0; }

// Aufrufzahlen aller Host-Funktionen (Name, Anzahl), absteigend; BDSP_NVN_STATS=1 gibt sie im Ergebnisprotokoll aus
void hle_stats_report(FILE *f) {
    int *idx = malloc(sizeof(int) * hle_count), n = 0;
    for (int i = 0; i < hle_count; i++) if (hle_slots[i].ncall) idx[n++] = i;
    for (int a = 0; a < n; a++)
        for (int b = a + 1; b < n; b++)
            if (hle_slots[idx[b]].ncall > hle_slots[idx[a]].ncall) { int t = idx[a]; idx[a] = idx[b]; idx[b] = t; }
    fprintf(f, "Host-Funktionen (HLE) aufgerufen: %d verschiedene\n", n);
    for (int a = 0; a < n; a++) fprintf(f, "  %8llu  %s\n", (unsigned long long)hle_slots[idx[a]].ncall, hle_slots[idx[a]].name);
    free(idx);
}

static GuestFn dispatch_slow(Cpu *c) {
    uint64_t pc = c->pc;
    if (pc >= HLE_BASE && pc < HLE_BASE + HLE_SIZE) {
        int i = (int)((pc - HLE_BASE) / 16);
        if (i < hle_count) {
            t_hle_slot = i;
            __atomic_add_fetch(&hle_slots[i].ncall, 1, __ATOMIC_RELAXED);
            static int trace = -1;   // BDSP_TRACE_HLE=<n>: die ersten n Aufrufe der Host-Funktionen mit Thread und Argumenten protokollieren (nvnDeviceGetProcAddress ausgenommen)
            if (trace < 0) trace = getenv("BDSP_TRACE_HLE") ? atoi(getenv("BDSP_TRACE_HLE")) : 0;
            if (trace > 0 && strcmp(hle_slots[i].name, "nvnDeviceGetProcAddress") && __atomic_fetch_sub(&trace, 1, __ATOMIC_RELAXED) > 0) {
                KThread *kt = kernel_current_thread();
                LOG("[hle] T%llu %s(%llx, %llx, %llx, %llx) lr=%llx\n", (unsigned long long)(kt ? kt->id : 0), hle_slots[i].name, (unsigned long long)c->x[0],
                    (unsigned long long)c->x[1], (unsigned long long)c->x[2], (unsigned long long)c->x[3], (unsigned long long)c->x[30]);
            }
            if (hle_slots[i].fn) return hle_slots[i].fn;
            if (hle_slots[i].calls++ < 3)
                LOG("[hle] nicht umgesetzter Import %s (x0=%llx x1=%llx lr=%llx) -> 0\n", hle_slots[i].name, (unsigned long long)c->x[0],
                    (unsigned long long)c->x[1], (unsigned long long)c->x[30]);
            return hle_unimplemented;
        }
    }
    GuestFn f = dispatch_lookup(pc);
    for (int i = 0; i < nwatch; i++)
        if (watches[i].addr == pc) {
            uint64_t n = __atomic_add_fetch(&watches[i].hits, 1, __ATOMIC_RELAXED);
            __atomic_add_fetch(&g_watch_hits, 1, __ATOMIC_RELAXED);
            if (n <= 5)
                LOG("[gate] %s aufgerufen (#%llu), x0=%llx x1=%llx lr=%llx\n", watches[i].name, (unsigned long long)n, (unsigned long long)c->x[0],
                    (unsigned long long)c->x[1], (unsigned long long)c->x[30]);
            bdsp_gate_hit(watches[i].name);
            return f;  // nicht in den Cache: jeder Aufruf kommt wieder hier vorbei
        }
    if (!f) return NULL;
    unsigned h = (unsigned)(pc >> 2) & (DCACHE - 1);
    dcache[h].addr = pc;
    dcache[h].fn = f;
    return f;
}

void rt_nle_fatal(Cpu *c) {
    rt_fatal("unbekannter Wiedereinstiegspunkt %llx (lr=%llx)\n", (unsigned long long)c->pc, (unsigned long long)c->x[30]);
}

// Sprung mitten in eine Gastfunktion (Landing-Pad nach _Unwind, Rückkehr hinter setjmp): innerster Rahmeneintrag, dessen
// Bereich die Adresse enthält und dessen Eintritts-SP über dem Ziel-SP liegt (rekursive Aufrufe liegen tiefer).
void rt_nle_enter(Cpu *c) {
    EhRec *top = EH_TOP(c);
    for (EhRec *r = top; r; r = r->prev)
        if (c->pc >= r->lo && c->pc < r->hi && r->sp > c->sp) {
            for (EhRec *q = top; q != r; q = q->prev) __atomic_add_fetch(&g_nle_frames, 1, __ATOMIC_RELAXED);
            __atomic_add_fetch(&g_nle_enters, 1, __ATOMIC_RELAXED);
            EH_TOP(c) = r;
            _longjmp(r->jb, 1);
        }
    uint64_t off = 0;
    const char *s = loader_symbol_at(c->x[30], &off);
    rt_fatal("kein Gastcode bei %llx (lr=%llx %s+%llx): Sprung in Daten oder ohne Funktion\n", (unsigned long long)c->pc, (unsigned long long)c->x[30],
             s ? s : "?", (unsigned long long)off);
}

// Ruft immer per Tail-Call, damit Ketten indirekter Sprünge den Host-Stack nicht wachsen lassen.
void rt_dispatch(Cpu *c) {
    unsigned h = (unsigned)(c->pc >> 2) & (DCACHE - 1);
    GuestFn f = dcache[h].addr == c->pc ? dcache[h].fn : dispatch_slow(c);
    if (__builtin_expect(!f, 0)) rt_nle_enter(c);
    __attribute__((musttail)) return f(c);
}

void guest_call(Cpu *c, uint64_t addr) {
    uint64_t lr = c->x[30], pc = c->pc;
    c->x[30] = 0;
    c->pc = addr;
    rt_dispatch(c);
    c->x[30] = lr;
    c->pc = pc;
}

void rt_udf(Cpu *c, uint64_t pc) {
    uint64_t off = 0;
    const char *s = loader_symbol_at(pc, &off);
    rt_fatal("UDF/nicht umgesetzter Befehl bei %llx (%s+%llx), lr=%llx\n", (unsigned long long)pc, s ? s : "?", (unsigned long long)off, (unsigned long long)c->x[30]);
}
void rt_brk(Cpu *c, uint32_t imm, uint64_t pc) {
    uint64_t off = 0;
    const char *s = loader_symbol_at(pc, &off);
    rt_fatal("BRK #%u bei %llx (%s+%llx), lr=%llx\n", imm, (unsigned long long)pc, s ? s : "?", (unsigned long long)off, (unsigned long long)c->x[30]);
}

// ---- Speicher des Hosts im Gastfenster
static uint64_t hle_next = HLE_HEAP;
void *hle_alloc(uint64_t size) {
    static pthread_mutex_t m = PTHREAD_MUTEX_INITIALIZER;
    pthread_mutex_lock(&m);
    uint64_t a = hle_next;
    hle_next += (size + 63) & ~63ull;
    if (hle_next > HLE_HEAP + HLE_HEAP_SIZE) { pthread_mutex_unlock(&m); rt_fatal("HLE-Heap erschöpft\n"); }
    pthread_mutex_unlock(&m);
    memset(G2H(a), 0, size);
    return G2H(a);
}

// ---- Abbruch und Absturz
static void print_guest_regs(Cpu *c) {
    LOG("Gast: sp=%llx lr=%llx fp=%llx\n", (unsigned long long)c->sp, (unsigned long long)c->x[30], (unsigned long long)c->x[29]);
    for (int i = 0; i < 28; i += 4)
        LOG("  x%-2d %016llx  x%-2d %016llx  x%-2d %016llx  x%-2d %016llx\n", i, (unsigned long long)c->x[i], i + 1, (unsigned long long)c->x[i + 1],
            i + 2, (unsigned long long)c->x[i + 2], i + 3, (unsigned long long)c->x[i + 3]);
    uint64_t fp = c->x[29];
    uint64_t off = 0;
    const char *s0 = loader_symbol_at(c->x[30], &off);
    LOG("Gast-Rückverfolgung (Rücksprungadressen):\n  lr  %llx %s+%llx\n", (unsigned long long)c->x[30], s0 ? s0 : "?", (unsigned long long)off);
    for (int n = 0; n < 24 && fp >= STACK_BASE && fp < STACK_BASE + STACK_SIZE; n++) {
        uint64_t lr = *G2H64(fp + 8);
        const char *s = loader_symbol_at(lr, &off);
        LOG("  #%d %llx %s+%llx\n", n, (unsigned long long)lr, s ? s : "?", (unsigned long long)off);
        uint64_t next = *G2H64(fp);
        if (next <= fp) break;
        fp = next;
    }
    if (g_fnprof) {
        LOG("letzte Gastfunktionen (neueste zuletzt, Aufrufer):\n");
        unsigned nring = getenv("BDSP_RING") ? (unsigned)atoi(getenv("BDSP_RING")) : 16;
        if (nring > RING) nring = RING;
        for (unsigned i = nring; i-- > 0;) {
            if (ring_pos < i + 1) continue;
            unsigned k = (ring_pos - 1 - i) & (RING - 1);
            LOG("  %llx (lr %llx)\n", (unsigned long long)ring_fn[k], (unsigned long long)ring_lr[k]);
        }
    }
}

void rt_fatal_trace(void) {
    Cpu *c = kernel_current_cpu();
    if (c) print_guest_regs(c);
    // BDSP_DUMP="adresse[:wörter],…" (hex): Gastspeicher beim Abbruch ausgeben
    const char *d = getenv("BDSP_DUMP");
    while (d && *d) {
        char *end;
        uint64_t a = strtoull(d, &end, 16);
        unsigned n = 16;
        if (*end == ':') n = (unsigned)strtoul(end + 1, &end, 10);
        LOG("dump %llx:", (unsigned long long)a);
        for (unsigned i = 0; i < n; i++) LOG(" %08x", *G2H32(a + 4ull * i));
        LOG("\n");
        d = *end == ',' ? end + 1 : end;
        if (end == d && *d) break;
    }
    fflush(NULL);
}

void rt_fatal(const char *fmt, ...) {
    static volatile int once;
    if (__atomic_exchange_n(&once, 1, __ATOMIC_SEQ_CST)) { for (;;) pause(); }
    char buf[1024];
    va_list ap; va_start(ap, fmt); vsnprintf(buf, sizeof buf, fmt, ap); va_end(ap);
    LOG("FATAL: %s", buf);
    rt_fatal_trace();
    bdsp_fatal_report("Abbruch durch die Laufzeit (siehe FATAL)", 3);  // endet nicht: der Hauptthread erstellt den Bericht und beendet den Prozess
    for (;;) pause();
}

static void crash_handler(int sig, siginfo_t *si, void *ctx) {
    (void)ctx;
    static volatile int once;
    if (sig != SIGTRAP && __atomic_exchange_n(&once, 1, __ATOMIC_SEQ_CST)) { for (;;) pause(); }
    LOG("\n*** Signal %d bei Hostadresse %p\n", sig, si->si_addr);
    void *bt[48];
    int n = backtrace(bt, 48);
    char **syms = backtrace_symbols(bt, n);
    for (int i = 0; i < n; i++) LOG("  %s\n", syms ? syms[i] : "?");
    rt_fatal_trace();
    bdsp_fatal_report("Absturz im Gastcode (Signal)", 139);
    for (;;) pause();
}

void crash_handler_install(void) {
    stack_t ss = {.ss_sp = malloc(1 << 20), .ss_size = 1 << 20};
    sigaltstack(&ss, NULL);
    struct sigaction sa = {0};
    sa.sa_sigaction = crash_handler;
    sa.sa_flags = SA_SIGINFO | SA_ONSTACK;
    sigaction(SIGSEGV, &sa, NULL);
    sigaction(SIGBUS, &sa, NULL);
    sigaction(SIGILL, &sa, NULL);
    sigaction(SIGABRT, &sa, NULL);
    sigaction(SIGTRAP, &sa, NULL);
}
