// Spike 2, Schritt 5: kleinstes lauffähiges Stück. Lädt main, sdk und subsdk0 des Dumps (rekompiliert, siehe
// scripts/recomp/gen_all.sh und build_all.sh), startet nn::init::Start auf dem Hauptthread und läuft, bis das erste
// fehlende Stück (SVC, Dienst, Thread, Import) den Lauf beendet oder nnMain erreicht ist. Es gibt keine Grafik.
// Eigener Code. Mini-Kernel nur für den Befund: kein Mehrthreadbetrieb, keine echten Dienste.
#define _GNU_SOURCE
#include "cpu.h"
#include <fcntl.h>
#include <setjmp.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/resource.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#ifdef USE_LAS_IPC
uint32_t ipc_connect_named_port(const char *name);  // LASRecomp runtime/ipc.c (nur gelinkt)
int ipc_handle_request(Cpu *c, uint32_t handle);
#endif

#define HLE_BASE   0x7080000000ull
#define STACK_LO   0x7200000000ull
#define STACK_SZ   0x100000ull          // 1 MiB laut NPDM
#define TLS_BASE   0x7300000000ull
#define HEAP_BASE  0x7100000000ull
#define HEAP_MAX   (3ull << 30) + (1ull << 28)  // 3,25 GiB wie LAS (HEAP_MAX)

extern const uint64_t main_fn_addrs[]; extern const GuestFn main_fn_ptrs[]; extern const uint64_t main_fn_count;
extern const uint64_t sdk_fn_addrs[]; extern const GuestFn sdk_fn_ptrs[]; extern const uint64_t sdk_fn_count;
extern const uint64_t subsdk0_fn_addrs[]; extern const GuestFn subsdk0_fn_ptrs[]; extern const uint64_t subsdk0_fn_count;
typedef struct { const uint64_t *addrs; const GuestFn *fns; uint64_t n; } Tab;
static Tab tabs[3];

volatile int g_fnprof;
// Ring der letzten Funktionseintritte (EH_FNTRACE=1), wird bei einem Absturz (SIGSEGV) ausgegeben
#include <signal.h>
static uint64_t ring_fn[64], ring_lr[64];
static unsigned ring_pos;
void fnprof_hit(uint64_t a, uint64_t b, uint64_t c) { (void)c; ring_fn[ring_pos & 63] = a; ring_lr[ring_pos & 63] = b; ring_pos++; }
static void segv(int sig, siginfo_t *si, void *uc) {
    (void)uc;
    char buf[160];
    int n = snprintf(buf, sizeof buf, "ABSTURZ (Signal %d) bei Hostadresse %p; letzte Gastfunktionen (neueste zuletzt, Aufrufer in Klammern):\n", sig, si->si_addr);
    write(2, buf, n);
    for (unsigned i = 24; i-- > 0;) {
        unsigned k = (ring_pos - 1 - i) & 63;
        if (ring_pos - 1 < i) continue;
        n = snprintf(buf, sizeof buf, "  %llx (lr %llx)\n", (unsigned long long)ring_fn[k], (unsigned long long)ring_lr[k]);
        write(2, buf, n);
    }
    _exit(139);
}

typedef struct { char name[16]; uint64_t base, text_lo, text_hi, ro_lo, ro_hi, data_lo, data_hi, end, init, init_array, init_array_sz; } Mod;
static Mod mods[3];
static int nmods;
static const char *hle_names[512];
static int hle_count;
static jmp_buf stop_jb;
static const char *stop_reason;
static Cpu *cpu;
static uint64_t heap_size;
static struct { uint64_t svc[256]; uint64_t ipc, ipc_sync; uint64_t dispatch_miss; } cnt;
static int ipc_seen;
static char ipc_names[32][32];
static uint64_t next_handle = 0xD100;
static int threads_created, threads_started;
static uint64_t trace_limit = 60;

static void die(const char *fmt, ...) __attribute__((noreturn, format(printf, 1, 2)));
static void die(const char *fmt, ...) {
    static char buf[512];
    va_list ap; va_start(ap, fmt); vsnprintf(buf, sizeof buf, fmt, ap); va_end(ap);
    stop_reason = buf;
    longjmp(stop_jb, 1);
}

static GuestFn lookup(uint64_t a) {
    for (int t = 0; t < 3; t++) {
        uint64_t lo = 0, hi = tabs[t].n;
        while (lo < hi) { uint64_t m = (lo + hi) / 2; if (tabs[t].addrs[m] < a) lo = m + 1; else hi = m; }
        if (lo < tabs[t].n && tabs[t].addrs[lo] == a) return tabs[t].fns[lo];
    }
    return NULL;
}

void rt_nle_fatal(Cpu *c) { die("unbekannter Wiedereinstiegspunkt %llx", c->pc); }
void rt_nle_enter(Cpu *c) {
    for (EhRec *r = EH_TOP(c); r; r = r->prev)
        if (c->pc >= r->lo && c->pc < r->hi && r->sp > c->sp) { EH_TOP(c) = r; _longjmp(r->jb, 1); }
    cnt.dispatch_miss++;
    die("kein Gastcode bei %llx (lr=%llx): Sprung in Daten/ohne Funktion", c->pc, c->x[30]);
}

static void module_init(Cpu *c, Mod *m);
static void guest_call(Cpu *c, uint64_t addr) {
    uint64_t lr = c->x[30], pc = c->pc;
    c->x[30] = 0; c->pc = addr;
    rt_dispatch(c);
    c->x[30] = lr; c->pc = pc;
}
static void module_init(Cpu *c, Mod *m) {
    printf("  init %s (DT_INIT %llx, %llu init_array-Eintraege)\n", m->name, m->base + m->init, m->init_array_sz / 8);
    if (m->init) { guest_call(c, m->base + m->init); return; }
    for (uint64_t i = 0; i < m->init_array_sz / 8; i++) {
        uint64_t fn = *(uint64_t *)(uintptr_t)(m->base + m->init_array + i * 8);
        if (fn) guest_call(c, fn);
    }
}

#define SLOT_INIT_SDK  (HLE_BASE + 16ull * 500)
#define SLOT_INIT_MAIN (HLE_BASE + 16ull * 501)
#define SLOT_NOP       (HLE_BASE + 16ull * 502)

void rt_dispatch(Cpu *c) {
    uint64_t pc = c->pc;
    if (pc >= HLE_BASE && pc < HLE_BASE + 16ull * 512) {
        if (pc == SLOT_INIT_SDK) { module_init(c, &mods[1]); return; }
        if (pc == SLOT_INIT_MAIN) { module_init(c, &mods[0]); return; }
        if (pc == SLOT_NOP) { printf("  Fini-Rueckruf (nach nnMain) erreicht\n"); return; }
        int i = (int)((pc - HLE_BASE) / 16);
        extern void hle_call(Cpu *, int);
        hle_call(c, i);
        return;
    }
    GuestFn f = lookup(pc);
    if (f) { __attribute__((musttail)) return f(c); }
    rt_nle_enter(c);
}

void rt_brk(Cpu *c, uint32_t imm, uint64_t pc) { (void)c; die("BRK %u bei %llx (Abbruch im Gastcode)", imm, pc); }
void rt_udf(Cpu *c, uint64_t pc) { (void)c; die("UDF bei %llx (nicht lift-bare/Datenworte oder fehlender Befehl)", pc); }
uint64_t rt_ticks(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return (uint64_t)t.tv_sec * 19200000ull + t.tv_nsec * 19200000ull / 1000000000ull; }

// ---- HLE-Importe: nur die wirklich nötigen Host-Ersatzfunktionen
void hle_call(Cpu *c, int i) {
    const char *n = i < hle_count ? hle_names[i] : "?";
    if (!strcmp(n, "malloc") || !strcmp(n, "calloc") || !strcmp(n, "realloc") || !strcmp(n, "free") || !strcmp(n, "aligned_alloc"))
        die("Import %s (Allokator der Anwendung) wurde aufgerufen, bevor nninitStartup ihn bereitgestellt hat", n);
    die("fehlender Import/HLE: %s (lr=%llx)", n, c->x[30]);
}

// ---- Mini-Kernel
static const char *svc_name(unsigned n) {
    static const char *t[256] = {
        [0x01] = "SetHeapSize", [0x03] = "SetMemoryAttribute", [0x04] = "MapMemory", [0x05] = "UnmapMemory", [0x06] = "QueryMemory",
        [0x07] = "ExitProcess", [0x08] = "CreateThread", [0x09] = "StartThread", [0x0A] = "ExitThread", [0x0B] = "SleepThread",
        [0x0C] = "GetThreadPriority", [0x0D] = "SetThreadPriority", [0x0E] = "GetThreadCoreMask", [0x0F] = "SetThreadCoreMask",
        [0x10] = "GetCurrentProcessorNumber", [0x11] = "SignalEvent", [0x12] = "ClearEvent", [0x13] = "MapSharedMemory",
        [0x14] = "UnmapSharedMemory", [0x15] = "CreateTransferMemory", [0x16] = "CloseHandle", [0x17] = "ResetSignal",
        [0x18] = "WaitSynchronization", [0x19] = "CancelSynchronization", [0x1A] = "ArbitrateLock", [0x1B] = "ArbitrateUnlock",
        [0x1C] = "WaitProcessWideKeyAtomic", [0x1D] = "SignalProcessWideKey", [0x1E] = "GetSystemTick", [0x1F] = "ConnectToNamedPort",
        [0x21] = "SendSyncRequest", [0x22] = "SendSyncRequestWithUserBuffer", [0x25] = "GetThreadId", [0x26] = "Break",
        [0x27] = "OutputDebugString", [0x29] = "GetInfo", [0x2C] = "MapPhysicalMemory", [0x2D] = "UnmapPhysicalMemory",
        [0x32] = "SetThreadActivity", [0x33] = "GetThreadContext3", [0x34] = "WaitForAddress", [0x35] = "SignalToAddress",
        [0x36] = "SynchronizePreemptionState", [0x45] = "CreateEvent",
    };
    return t[n & 255] ? t[n & 255] : "?";
}

typedef struct { uint32_t handle; char svc[24]; int domain; uint32_t next_obj; char obj[8][24]; } Session;
static Session sess[64];
static int nsess;
static char missing[16][24];
static int nmissing;
static uint32_t session_new(const char *svc) {
    Session *s = &sess[nsess++];
    s->handle = next_handle++;
    snprintf(s->svc, sizeof s->svc, "%s", svc);
    s->next_obj = 2;
    snprintf(s->obj[1], 24, "%s", svc);
    return s->handle;
}
static Session *session_find(uint32_t h) {
    for (int i = 0; i < nsess; i++) if (sess[i].handle == h) return &sess[i];
    return NULL;
}
// CMIF-Antwort: [Kopf][ggf. Move-Handle][Domain-Kopf][SFCO][Nutzdaten][Out-Objekt-IDs]
static void ipc_reply2(uint32_t *msg, int domain, uint32_t result, const uint32_t *pay, int npay, const uint32_t *outs, int nout, uint32_t move_handle) {
    memset(msg, 0, 128);
    uint32_t pos = 2;
    if (move_handle) { msg[2] = 1u << 5; msg[3] = move_handle; pos = 4; }
    uint32_t w = (pos + 3) & ~3u;
    if (domain) { msg[w] = nout; w += 4; }
    msg[w] = 0x4F434653; msg[w + 2] = result; w += 4;
    for (int i = 0; i < npay; i++) msg[w++] = pay[i];
    for (int i = 0; i < nout; i++) msg[w++] = outs[i];
    msg[1] = (w - pos) | (move_handle ? 1u << 31 : 0);
}
static void ipc_reply(uint32_t *msg, uint32_t result, uint32_t move_handle) { ipc_reply2(msg, 0, result, NULL, 0, NULL, 0, move_handle); }
// Dienste, die der Test mit "Erfolg, keine Daten" beantwortet (Umgebungsvariable STUBS=a,b,c erweitert die Liste)
static int is_stub(const char *name) {
    const char *list = getenv("STUBS");
    char buf[512];
    snprintf(buf, sizeof buf, "lm,%s", list ? list : "");
    for (char *t = strtok(buf, ","); t; t = strtok(NULL, ",")) if (!strncmp(t, name, strlen(t)) && strlen(t) == strnlen(name, 8)) return 1;
    return 0;
}

static void ipc_request(Cpu *c) {
    cnt.ipc_sync++;
    uint32_t *msg = (uint32_t *)(uintptr_t)(cpu->tpidrro);
    uint32_t h0 = msg[0], h1 = msg[1];
    unsigned nx = (h0 >> 16) & 15, na = (h0 >> 20) & 15, nb = (h0 >> 24) & 15, nw = (h0 >> 28) & 15;
    uint32_t pos = 2;
    if (h1 >> 31) { uint32_t sh = msg[2]; pos = 3 + ((sh & 1) ? 2 : 0) + ((sh >> 1) & 15) + ((sh >> 5) & 15); }
    pos += nx * 2 + na * 3 + nb * 3 + nw * 3;
    uint32_t raw = (pos + 3) & ~3u;
    unsigned type = h0 & 0xFFFF;
    Session *s = session_find((uint32_t)c->x[0]);
    const char *svc = s ? s->svc : "?";
    int control = (type == 5 || type == 7);
    int dom = s && s->domain && !control;
    uint32_t obj = 1, sf = raw;
    if (dom) { obj = msg[raw + 1]; sf = raw + 4; }
    uint32_t cmd = msg[sf + 2];
    const char *oname = (s && obj < 8 && s->obj[obj][0]) ? s->obj[obj] : svc;
    char name[16] = "";
    if (!strcmp(svc, "sm:") && !control && cmd == 1) memcpy(name, &msg[sf + 4], 8);
    cnt.ipc++;
    if (cnt.ipc <= 60) printf("  IPC #%llu an %s%s: %sBefehl %u%s%.8s%s (Typ %u, %u Byte)\n", (unsigned long long)cnt.ipc, oname, dom ? " (Domain)" : "", control ? "Steuer" : "", cmd, name[0] ? " GetService \"" : "", name, name[0] ? "\"" : "", type, (h1 & 0x3FF) * 4);
    if (control) {  // Steuerbefehle: 0 ConvertCurrentObjectToDomain, 3 QueryPointerBufferSize
        if (cmd == 0) { uint32_t id = 1; if (s) s->domain = 1; ipc_reply2(msg, 0, 0, &id, 1, NULL, 0, 0); }
        else if (cmd == 3) { uint32_t sz = 0x8000; ipc_reply2(msg, 0, 0, &sz, 1, NULL, 0, 0); }
        else ipc_reply(msg, 0, 0);
        c->x[0] = 0;
        return;
    }
    if (!strcmp(svc, "sm:")) {
        if (cmd == 0) { ipc_reply(msg, 0, 0); c->x[0] = 0; return; }
        if (cmd == 1) {
            if (ipc_seen < 32) snprintf(ipc_names[ipc_seen++], 32, "%.8s", name);
            if (is_stub(name)) { ipc_reply(msg, 0, session_new(name)); c->x[0] = 0; return; }
            if (nmissing < 16) snprintf(missing[nmissing++], 24, "%.8s", name);
            ipc_reply(msg, 0x0000EE01, 0);  // MAKERESULT(21, 7): Dienst nicht registriert
            c->x[0] = 0;
            return;
        }
        die("sm: Befehl %u nicht umgesetzt", cmd);
    }
    if (s && !strcmp(s->svc, "lm") && obj == 1 && cmd == 0) {  // ILogService::OpenLogger -> ILogger als Domain-Objekt
        uint32_t id = s->next_obj++;
        snprintf(s->obj[id & 7], 24, "lm.logger");
        ipc_reply2(msg, dom, 0, NULL, 0, &id, 1, 0);
        c->x[0] = 0;
        return;
    }
    ipc_reply2(msg, dom, 0, NULL, 0, NULL, 0, 0);
    c->x[0] = 0;
}

static void svc_getinfo(Cpu *c) {
    uint64_t id = c->x[1], sub = c->x[3], v = 0;
    switch (id) {
    case 0: v = 0xF; break; case 1: v = 0xFFFFFFFFFFFFFFFFull; break;
    case 2: v = 0x7400000000ull; break; case 3: v = 0x40000000ull; break;
    case 4: v = HEAP_BASE; break; case 5: v = HEAP_MAX; break;
    case 6: v = 0xC6000000ull; break; case 7: v = heap_size + 0x6400000ull; break;
    case 12: v = 0x8000000ull; break; case 13: v = 0x7FF8000000ull; break;
    case 14: v = STACK_LO; break; case 15: v = 0x10000000ull; break;
    case 16: v = 0x1000000ull; break; case 17: v = 0x200000ull; break;
    case 18: v = 0x0100000000000000ull; break;  // ProgramId (Platzhalter)
    case 20: v = TLS_BASE + 0x1000; break; case 21: v = 0xC6000000ull; break; case 22: v = heap_size; break;
    default: cnt.svc[255]++; break;
    }
    (void)sub;
    c->x[0] = 0; c->x[1] = v;
}

static void svc_query_memory(Cpu *c) {
    // x0 = MemoryInfo*, x2 = Adresse; Typ/Rechte nach den Modulsegmenten (GetExceptionInfo des SDK wertet sie aus)
    uint64_t a = c->x[2], base = a & ~0xFFFull, size = 0x1000;
    uint32_t type = 0, perm = 0;
    for (int i = 0; i < nmods; i++) {
        Mod *m = &mods[i];
        if (a >= m->base + m->text_lo && a < m->base + m->text_hi) { base = m->base + m->text_lo; size = m->text_hi - m->text_lo; type = 3; perm = 5; }
        else if (a >= m->base + m->ro_lo && a < m->base + m->ro_hi) { base = m->base + m->ro_lo; size = m->ro_hi - m->ro_lo; type = 3; perm = 1; }
        else if (a >= m->base + m->data_lo && a < m->base + m->end) { base = m->base + m->data_lo; size = m->end - m->data_lo; type = 4; perm = 3; }
    }
    if (a >= HEAP_BASE && a < HEAP_BASE + heap_size) { base = HEAP_BASE; size = heap_size; type = 5; perm = 3; }
    uint64_t *mi = (uint64_t *)(uintptr_t)c->x[0];
    mi[0] = base; mi[1] = size;
    ((uint32_t *)mi)[4] = type; ((uint32_t *)mi)[5] = 0; ((uint32_t *)mi)[6] = perm; ((uint32_t *)mi)[7] = 0; ((uint32_t *)mi)[8] = 0;
    c->x[0] = 0; c->x[1] = 0;
}

void rt_svc(Cpu *c, uint32_t imm, uint64_t pc) {
    cnt.svc[imm & 255]++;
    if (cnt.svc[imm & 255] == 1 && trace_limit) { trace_limit--; printf("  SVC %#04x %-24s (erstmals, pc=%llx)\n", imm, svc_name(imm), pc); }
    switch (imm) {
    case 0x01: {  // SetHeapSize(size) -> addr
        uint64_t sz = c->x[1];
        if (sz > HEAP_MAX) { c->x[0] = 0xD001; return; }
        heap_size = sz;
        c->x[0] = 0; c->x[1] = HEAP_BASE;
        printf("  SetHeapSize %llu MiB\n", sz >> 20);
        return;
    }
    case 0x2C: {  // MapPhysicalMemory(addr, size): im Probelauf ist jede Adresse im Heap-/Aliasfenster schon abgebildet
        printf("  MapPhysicalMemory addr=%llx size=%llx\n", c->x[0], c->x[1]);
        uint64_t a = c->x[0] & ~0xFFFull, n = (c->x[1] + 0xFFF) & ~0xFFFull;
        if (!(a >= HEAP_BASE && a + n <= HEAP_BASE + HEAP_MAX))
            mmap((void *)a, n, PROT_READ | PROT_WRITE, MAP_FIXED | MAP_PRIVATE | MAP_ANON, -1, 0);
        c->x[0] = 0;
        return;
    }
    case 0x03: case 0x04: case 0x05: case 0x13: case 0x14: case 0x16: case 0x2D: case 0x0F: case 0x0D: case 0x12: case 0x17: case 0x19:
        c->x[0] = 0; return;
    case 0x06: svc_query_memory(c); return;
    case 0x0B: c->x[0] = 0; return;
    case 0x0C: c->x[0] = 0; c->x[1] = 44; return;
    case 0x0E: c->x[0] = 0; c->x[1] = 0; c->x[2] = 0xF; return;
    case 0x10: c->x[0] = 0; return;
    case 0x1E: c->x[0] = rt_ticks(); return;
    case 0x25: c->x[0] = 0; c->x[1] = 1; return;
    case 0x29: svc_getinfo(c); return;
    case 0x08: threads_created++; c->x[0] = 0; c->x[1] = next_handle++; printf("  CreateThread #%d (entry %llx, arg %llx, stack %llx, prio %lld)\n", threads_created, c->x[1] ? c->x[1] : 0, c->x[2], c->x[3], (long long)c->x[4]); return;
    case 0x09: threads_started++; c->x[0] = 0; return;
    case 0x11: c->x[0] = 0; return;
    case 0x45: c->x[0] = 0; c->x[1] = next_handle++; c->x[2] = next_handle++; return;
    case 0x18: c->x[0] = 0; c->x[1] = 0; return;  // WaitSynchronization: Eingabe gilt als signalisiert
    case 0x1A: case 0x1B: c->x[0] = 0; return;    // Arbitrate (ohne Konkurrenz)
    case 0x1C: case 0x1D: c->x[0] = 0; return;
    case 0x34: case 0x35: c->x[0] = 0; return;
    case 0x1F: {  // ConnectToNamedPort(name)
        const char *name = (const char *)(uintptr_t)c->x[1];
        printf("  ConnectToNamedPort \"%.12s\"\n", name);
#ifdef USE_LAS_IPC
        uint32_t h = ipc_connect_named_port(name);
        c->x[0] = h ? 0 : 0xF601; c->x[1] = h;
        return;
#endif
        if (ipc_seen < 32) { snprintf(ipc_names[ipc_seen++], 32, "%.12s", name); }
        if (!strncmp(name, "sm:", 3)) { c->x[0] = 0; c->x[1] = session_new("sm:"); return; }
        c->x[0] = 0xF601; return;
    }
    case 0x21: case 0x22:
#ifdef USE_LAS_IPC
        cnt.ipc++;
        c->x[0] = (uint32_t)ipc_handle_request(c, (uint32_t)c->x[0]);
        return;
#endif
        ipc_request(c); return;
    case 0x26: die("Break (Gast bricht ab, Grund %llx): %s", c->x[0], "svcBreak");
    case 0x27: printf("  OutputDebugString: %.*s\n", (int)c->x[1], (const char *)(uintptr_t)c->x[0]); c->x[0] = 0; return;
    case 0x07: die("ExitProcess");
    case 0x0A: die("ExitThread auf dem Hauptthread");
    default: die("SVC %#x (%s) nicht umgesetzt (pc=%llx)", imm, svc_name(imm), pc);
    }
}

static void map_file(const char *path, uint64_t addr) {
    int fd = open(path, O_RDONLY);
    if (fd < 0) { perror(path); exit(2); }
    struct stat st; fstat(fd, &st);
    size_t len = (st.st_size + 0x3FFF) & ~0x3FFFull;
    void *p = mmap((void *)addr, len, PROT_READ | PROT_WRITE, MAP_FIXED | MAP_PRIVATE | MAP_ANON, -1, 0);
    if (p != (void *)addr) { fprintf(stderr, "mmap %s @%llx fehlgeschlagen\n", path, addr); exit(2); }
    if (read(fd, p, st.st_size) != st.st_size) { perror("read"); exit(2); }
    close(fd);
}

static long rss_mib(void) { struct rusage ru; getrusage(RUSAGE_SELF, &ru); return ru.ru_maxrss / (1024 * 1024); }

int main(int argc, char **argv) {
    if (getenv("FNTRACE")) {
        struct sigaction sa; memset(&sa, 0, sizeof sa);
        sa.sa_sigaction = segv; sa.sa_flags = SA_SIGINFO;
        sigaction(SIGSEGV, &sa, NULL); sigaction(SIGBUS, &sa, NULL);
        g_fnprof = 1;
    }
    setvbuf(stdout, NULL, _IOLBF, 0);
    if (argc < 3) { fprintf(stderr, "usage: %s <spike2-dir> <start-symbol-adresse>\n", argv[0]); return 2; }
    char path[512];
    snprintf(path, sizeof path, "%s/hle.txt", argv[1]);
    FILE *f = fopen(path, "r");
    if (f) { char l[512]; while (fgets(l, sizeof l, f) && hle_count < 500) { l[strcspn(l, "\n")] = 0; hle_names[hle_count++] = strdup(l); } fclose(f); }
    const char *order[] = { "main", "sdk", "subsdk0" };
    for (int i = 0; i < 3; i++) {
        snprintf(path, sizeof path, "%s/%s.mod", argv[1], order[i]);
        f = fopen(path, "r");
        if (!f) { perror(path); return 2; }
        Mod *m = &mods[nmods++];
        unsigned long long v[11];
        if (fscanf(f, "%15s %llx %llx %llx %llx %llx %llx %llx %llx %llx %llx %llx", m->name, &v[0], &v[1], &v[2], &v[3], &v[4], &v[5], &v[6], &v[7], &v[8], &v[9], &v[10]) != 12) { fprintf(stderr, "mod %s\n", path); return 2; }
        m->base = v[0]; m->text_lo = v[1]; m->text_hi = v[2]; m->ro_lo = v[3]; m->ro_hi = v[4]; m->data_lo = v[5]; m->data_hi = v[6]; m->end = v[7];
        m->init = v[8]; m->init_array = v[9]; m->init_array_sz = v[10];
        fclose(f);
        snprintf(path, sizeof path, "%s/%s.img", argv[1], order[i]);
        map_file(path, m->base);
    }
    if (mmap((void *)STACK_LO, STACK_SZ, PROT_READ | PROT_WRITE, MAP_FIXED | MAP_PRIVATE | MAP_ANON, -1, 0) != (void *)STACK_LO) return 2;
    if (mmap((void *)TLS_BASE, 0x10000, PROT_READ | PROT_WRITE, MAP_FIXED | MAP_PRIVATE | MAP_ANON, -1, 0) != (void *)TLS_BASE) return 2;
    if (mmap((void *)HEAP_BASE, HEAP_MAX, PROT_READ | PROT_WRITE, MAP_FIXED | MAP_PRIVATE | MAP_ANON | MAP_NORESERVE, -1, 0) != (void *)HEAP_BASE) { fprintf(stderr, "Heap-Fenster nicht reservierbar\n"); return 2; }
    tabs[0] = (Tab){ main_fn_addrs, main_fn_ptrs, main_fn_count };
    tabs[1] = (Tab){ sdk_fn_addrs, sdk_fn_ptrs, sdk_fn_count };
    tabs[2] = (Tab){ subsdk0_fn_addrs, subsdk0_fn_ptrs, subsdk0_fn_count };
    cpu = aligned_alloc(16, sizeof(Cpu)); memset(cpu, 0, sizeof(Cpu));
    cpu->tpidrro = cpu->tpidr = TLS_BASE;
    cpu->sp = STACK_LO + STACK_SZ - 0x40;
    cpu->x[0] = 0xD000; cpu->x[1] = 0; cpu->x[2] = SLOT_INIT_SDK; cpu->x[3] = SLOT_INIT_MAIN; cpu->x[4] = SLOT_NOP;
    cpu->pc = strtoull(argv[2], 0, 16);
    printf("Start: nn::init::Start @%llx, Hauptthread Stack %llu KiB, Module main/sdk/subsdk0 geladen, RSS %ld MiB\n", cpu->pc, STACK_SZ >> 10, rss_mib());
    if (!setjmp(stop_jb)) {
        rt_dispatch(cpu);
        printf("ERGEBNIS: nn::init::Start kehrte zurueck (unerwartet)\n");
    } else {
        printf("ERGEBNIS: Lauf beendet: %s\n", stop_reason);
    }
    uint64_t total = 0; int distinct = 0;
    printf("SVC-Zaehler:");
    for (int i = 0; i < 256; i++) if (cnt.svc[i]) { printf(" %#x=%llu", i, (unsigned long long)cnt.svc[i]); total += cnt.svc[i]; distinct++; }
    printf("\n%d verschiedene SVCs, %llu Aufrufe; Threads angelegt %d, gestartet %d; Dienste angefragt:", distinct, (unsigned long long)total, threads_created, threads_started);
    for (int i = 0; i < ipc_seen; i++) printf(" %s", ipc_names[i]);
    printf("\nHeap angefordert %llu MiB, Spitzen-RSS %ld MiB\n", (unsigned long long)(heap_size >> 20), rss_mib());
    return 0;
}
