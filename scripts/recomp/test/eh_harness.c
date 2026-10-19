// Testharness für den Exception-Spike (docs/recomp-spike-2.md): Host-Laufzeit für rekompilierten Gastcode.
// Eigener Code. Gast = Host-Adressen wie in LASRecomp; es wird nur das SDK-Modul des Spiels (rekompiliert, aus
// dem lokalen Dump) und ein synthetisches Testmodul geladen. Es gibt kein Spiel, keine Grafik, keine Dienste.
#define _GNU_SOURCE
#include "cpu.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <time.h>
#include <sys/mman.h>
#include <sys/stat.h>

#ifdef REBASE32
// Speichermodell B: Gastadressen < 4 GiB, Zugriff über g_base (rt32/cpu.h)
#define SDK_BASE  0x01000000ull
#define EHT_BASE  0x02000000ull
#define MAIN_BASE 0x10000000ull
#define STACK_LO  0x03000000ull
#define HLE_BASE  0x08000000ull
#define HEAP_LO   0x20000000ull
uint8_t *g_base;
#define H(a) ((void *)(g_base + (uint32_t)(a)))
#define GA(p) ((uint64_t)((uint8_t *)(p) - g_base))
#else
#define SDK_BASE  0x7004000000ull
#define EHT_BASE  0x7008000000ull
#define MAIN_BASE 0x7040000000ull
#define STACK_LO  0x7010000000ull
#define HLE_BASE  0x7080000000ull
#define H(a) ((void *)(uintptr_t)(a))
#define GA(p) ((uint64_t)(uintptr_t)(p))
#endif
#define STACK_SZ  (4ull << 20)

extern const uint64_t sdk_fn_addrs[]; extern const GuestFn sdk_fn_ptrs[]; extern const uint64_t sdk_fn_count;
extern const uint64_t eht_fn_addrs[]; extern const GuestFn eht_fn_ptrs[]; extern const uint64_t eht_fn_count;
// optional: Teilbau von `main` (nur im Modus real=...)
extern const uint64_t main_fn_addrs[] __attribute__((weak_import)); extern const GuestFn main_fn_ptrs[] __attribute__((weak_import));
extern const uint64_t main_fn_count __attribute__((weak_import));

typedef struct { const uint64_t *addrs; const GuestFn *fns; uint64_t n; } Tab;
static int trace;
static Tab tabs[3];
static int ntabs = 2;
volatile int g_fnprof;
void fnprof_hit(uint64_t a, uint64_t b, uint64_t c) { fprintf(stderr, "enter %llx lr=%llx x0=%llx\n", a, b, c); }

static const char *hle_names[256];
static int hle_count;
static struct { uint64_t nle_enters, frames_dropped; } stats;
static struct {
    uint64_t alloc, thr, zti, ra, first_lp;
    int thrown, calls, skipped, nsites;
    unsigned long long (*sites)[3];
} rs;

static void die(const char *fmt, ...) __attribute__((noreturn, format(printf, 1, 2)));
#include <stdarg.h>
static void die(const char *fmt, ...) {
    va_list ap; va_start(ap, fmt); vfprintf(stderr, fmt, ap); va_end(ap); fputc('\n', stderr); exit(4);
}

static void map_file(const char *path, uint64_t addr) {
    int fd = open(path, O_RDONLY);
    if (fd < 0) die("open %s", path);
    struct stat st; fstat(fd, &st);
    size_t len = (st.st_size + 0x3FFF) & ~0x3FFFull;
#ifdef REBASE32
    void *p = H(addr);
#else
    void *p = mmap((void *)addr, len + 0x4000, PROT_READ | PROT_WRITE, MAP_FIXED | MAP_PRIVATE | MAP_ANON, -1, 0);
    if (p != (void *)addr) die("mmap %s @%llx fehlgeschlagen", path, addr);
#endif
    if (read(fd, p, st.st_size) != st.st_size) die("read %s", path);
    close(fd);
}

static GuestFn lookup(uint64_t a) {
    for (int t = 0; t < ntabs; t++) {
        uint64_t lo = 0, hi = tabs[t].n;
        while (lo < hi) { uint64_t m = (lo + hi) / 2; if (tabs[t].addrs[m] < a) lo = m + 1; else hi = m; }
        if (lo < tabs[t].n && tabs[t].addrs[lo] == a) return tabs[t].fns[lo];
    }
    return NULL;
}

void rt_nle_fatal(Cpu *c) { die("rt_nle_fatal: pc=%llx unbekannter Wiedereinstiegspunkt", c->pc); }

// Wiedereinstieg mitten in einer Gastfunktion (Landing-Pad, Rücksprung nach setjmp): den Host-Stack bis zu der
// Funktion abwickeln, die den Rahmen besitzt. Innerster Eintrag, dessen Bereich pc enthält und dessen Eintritts-SP
// oberhalb des Ziel-SP liegt (rekursive Aufrufe derselben Funktion liegen tiefer).
void rt_nle_enter(Cpu *c) {
    EhRec *top = EH_TOP(c);
    for (EhRec *r = top; r; r = r->prev) {
        if (c->pc >= r->lo && c->pc < r->hi && r->sp > c->sp) {
            for (EhRec *q = top; q != r; q = q->prev) stats.frames_dropped++;
            stats.nle_enters++;
            if (!rs.first_lp) rs.first_lp = c->pc;
            EH_TOP(c) = r;
            _longjmp(r->jb, 1);
        }
    }
    die("rt_nle_enter: kein Rahmen fuer pc=%llx sp=%llx (Kette %p)", c->pc, c->sp, (void *)top);
}


static int real_mode;
// Aufrufziel ohne rekompilierte Funktion (Teilbau von main): der erste Aufruf wirft eine C++-Exception über den
// echten Gast-Unwinder (als käme sie aus dem Aufgerufenen), alle weiteren kehren harmlos zurück.
// PLT-Stub von main (adrp x16; ldr x17,[x16,#o]; add x16,..; br x17): Sprungziel aus dem GOT, 0 wenn keiner
static uint64_t plt_target(uint64_t pc) {
    if (pc < MAIN_BASE || pc >= MAIN_BASE + 84287488) return 0;
    const uint32_t *w = (const uint32_t *)(uintptr_t)pc;
    if ((w[0] & 0x9F00001F) != 0x90000010 || (w[1] & 0xFFC003FF) != 0xF9400211 || w[3] != 0xD61F0220) return 0;
    int64_t imm = (int64_t)(((w[0] >> 5) & 0x7FFFF) << 2 | ((w[0] >> 29) & 3));
    if (imm & (1 << 20)) imm -= 1 << 21;
    uint64_t slot = ((pc & ~0xFFFull) + (uint64_t)(imm << 12)) + ((w[1] >> 10) & 0xFFF) * 8;
    return *(const uint64_t *)(uintptr_t)slot;
}

static void stub_callee(Cpu *c) {
    rs.calls++;
    if (rs.thrown) {  // nach dem Wurf: Importe (_Unwind_Resume, __cxa_*) laufen echt über den SDK-Code, der Rest kehrt zurück
        uint64_t t = plt_target(c->pc);
        if (t) { c->pc = t; rt_dispatch(c); return; }
        c->x[0] = 0;
        return;
    }
    int covered = 0;  // nur Aufrufe, die in einer Call-Site mit Landing-Pad liegen, werfen (sonst wird kein Pad getestet)
    for (int i = 0; i < rs.nsites; i++)
        if (c->x[30] - 4 >= rs.sites[i][0] && c->x[30] - 4 < rs.sites[i][1]) { covered = 1; break; }
    if (!covered) { rs.skipped++; c->x[0] = 0; return; }
    rs.thrown = 1;
    rs.ra = c->x[30];
    uint64_t lr = c->x[30], sp = c->sp;
    c->x[0] = 64; c->x[30] = 0; c->pc = rs.alloc;
    rt_dispatch(c);
    c->x[1] = rs.zti; c->x[2] = 0; c->x[30] = lr; c->sp = sp; c->pc = rs.thr;
    rt_dispatch(c);
    die("__cxa_throw kehrte zurueck");
}

void rt_dispatch(Cpu *c) {
    uint64_t pc = c->pc;
    if (trace) fprintf(stderr, "dispatch %llx lr=%llx sp=%llx\n", pc, c->x[30], c->sp);
    if (pc >= HLE_BASE && pc < HLE_BASE + 16ull * hle_count) {
        int i = (int)((pc - HLE_BASE) / 16);
        extern GuestFn hle_fns[];
        if (hle_fns[i]) { hle_fns[i](c); return; }
        if (real_mode) { c->x[0] = 0; return; }
        die("HLE nicht umgesetzt: %s (lr=%llx)", hle_names[i], c->x[30]);
    }
    GuestFn f = lookup(pc);
    if (f) { __attribute__((musttail)) return f(c); }
    if (real_mode) {
        for (EhRec *r = EH_TOP(c); r; r = r->prev)
            if (pc >= r->lo && pc < r->hi && r->sp > c->sp) rt_nle_enter(c);
        stub_callee(c);
        return;
    }
    rt_nle_enter(c);
}

void rt_svc(Cpu *c, uint32_t imm, uint64_t pc) {
    if (imm == 0x27) die("OutputDebugString: %.*s", (int)c->x[1], (const char *)H(c->x[0]));
    die("SVC %#x bei %llx", imm, pc);
}
void rt_brk(Cpu *c, uint32_t imm, uint64_t pc) { (void)c; die("BRK %u bei %llx", imm, pc); }
void rt_udf(Cpu *c, uint64_t pc) { (void)c; die("UDF bei %llx", pc); }
uint64_t rt_ticks(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return (uint64_t)t.tv_sec * 19200000ull + t.tv_nsec * 19200000ull / 1000000000ull; }

// ---- HLE (Host-Ersatz für Importe und ausgewählte SDK-Funktionen)
#ifdef REBASE32
// Gast-Heap im 4-GiB-Fenster: einfacher Zeigerzähler mit 16-Byte-Kopf (Größe), free ohne Wirkung
static uint64_t heap_next = HEAP_LO + 0x1000;
static uint64_t galloc(uint64_t n, uint64_t al) {
    if (n > (64ull << 20)) return 0;
    if (al < 16) al = 16;
    uint64_t a = (heap_next + 16 + al - 1) & ~(al - 1);
    heap_next = a + n;
    *(uint64_t *)H(a - 8) = n;
    memset(H(a), 0, n);
    return a;
}
static void h_malloc(Cpu *c) { c->x[0] = galloc(c->x[0] ? c->x[0] : 1, 16); }
static void h_calloc(Cpu *c) { c->x[0] = galloc(c->x[0] * c->x[1], 16); }
static void h_realloc(Cpu *c) {
    uint64_t old = c->x[0], n = c->x[1], a = galloc(n, 16);
    if (old && a) { uint64_t on = *(uint64_t *)H(old - 8); memcpy(H(a), H(old), on < n ? on : n); }
    c->x[0] = a;
}
static void h_free(Cpu *c) { (void)c; }
static void h_aligned_alloc(Cpu *c) { c->x[0] = galloc(c->x[1], c->x[0]); }
static uint64_t cxa_globals_g;
void hle___cxa_get_globals(Cpu *c) { if (!cxa_globals_g) cxa_globals_g = galloc(16, 16); c->x[0] = cxa_globals_g; }
void hle___cxa_get_globals_fast(Cpu *c) { hle___cxa_get_globals(c); }
#else
static void h_malloc(Cpu *c) { uint64_t n = c->x[0]; c->x[0] = n > (1ull << 40) ? 0 : (uint64_t)(uintptr_t)malloc(n ? n : 1); }
static void h_calloc(Cpu *c) { c->x[0] = (uint64_t)(uintptr_t)calloc(c->x[0], c->x[1]); }
static void h_realloc(Cpu *c) { c->x[0] = (uint64_t)(uintptr_t)realloc((void *)(uintptr_t)c->x[0], c->x[1]); }
static void h_free(Cpu *c) { free((void *)(uintptr_t)c->x[0]); }
static void h_aligned_alloc(Cpu *c) { void *p = NULL; if (posix_memalign(&p, c->x[0] < 16 ? 16 : c->x[0], c->x[1])) p = NULL; c->x[0] = (uint64_t)(uintptr_t)p; }

static struct { uint64_t caught; uint32_t uncaught; } cxa_globals;
void hle___cxa_get_globals(Cpu *c) { c->x[0] = (uint64_t)(uintptr_t)&cxa_globals; }
void hle___cxa_get_globals_fast(Cpu *c) { c->x[0] = (uint64_t)(uintptr_t)&cxa_globals; }
#endif

void hle__ZN2nn2os9LockMutexEPNS0_9MutexTypeE(Cpu *c) { (void)c; }
void hle__ZN2nn2os11UnlockMutexEPNS0_9MutexTypeE(Cpu *c) { (void)c; }

static const struct { uint64_t base, span; } mods[] = { { SDK_BASE, 13844480 }, { EHT_BASE, 12288 }, { MAIN_BASE, 84287488 } };
// nn::ro::detail::GetExceptionInfo(info, pc): {Modulbasis, Spanne, Offset von eh_frame_hdr, Länge von eh_frame_hdr}
void hle__ZN2nn2ro6detail16GetExceptionInfoEPNS1_13ExceptionInfoEm(Cpu *c) {
    uint64_t *info = (uint64_t *)H(c->x[0]), pc = c->x[1];
    for (unsigned i = 0; i < 3; i++) {
        if (pc < mods[i].base || pc >= mods[i].base + mods[i].span) continue;
        const uint8_t *img = (const uint8_t *)H(mods[i].base);
        uint32_t mod0 = *(const uint32_t *)(img + 4);
        int32_t e0 = *(const int32_t *)(img + mod0 + 16), e1 = *(const int32_t *)(img + mod0 + 20);
        info[0] = mods[i].base; info[1] = mods[i].span; info[2] = mod0 + e0; info[3] = (uint64_t)(e1 - e0);
        if (trace) fprintf(stderr, "GetExceptionInfo pc=%llx -> mod %u hdr_off=%llx len=%llx\n", pc, i, info[2], info[3]);
        c->x[0] = 1;
        return;
    }
    c->x[0] = 0;
}

GuestFn hle_fns[256];
static void hle_bind(void) {
    struct { const char *n; GuestFn f; } b[] = {
        { "malloc", h_malloc }, { "calloc", h_calloc }, { "realloc", h_realloc }, { "free", h_free },
        { "aligned_alloc", h_aligned_alloc },
    };
    for (int i = 0; i < hle_count; i++)
        for (unsigned k = 0; k < sizeof b / sizeof *b; k++)
            if (!strcmp(hle_names[i], b[k].n)) hle_fns[i] = b[k].f;
}

static Cpu *cpu;
static uint64_t call(uint64_t addr, uint64_t a0, uint64_t a1, uint64_t a2, uint64_t a3) {
    cpu->x[0] = a0; cpu->x[1] = a1; cpu->x[2] = a2; cpu->x[3] = a3;
    cpu->x[30] = 0; cpu->sp = STACK_LO + STACK_SZ - 64; cpu->pc = addr;
    EH_TOP(cpu) = NULL;
    rt_dispatch(cpu);
    return cpu->x[0];
}

// ---- Modus real=<spec>: Wurf durch echte Funktionen aus main (Teilbau), je Funktion ein Kindprozess
#include <sys/wait.h>
#define SCR 0x7050000000ull
static int run_one(char *line, uint64_t wrapper) {
    char kind[32]; unsigned long long f, zti; int n, off;
    if (sscanf(line, "%31s %llx %llx %d%n", kind, &f, &zti, &n, &off) < 4) return 3;
    unsigned long long (*sites)[3] = calloc(n + 1, sizeof *sites);
    char *p = line + off;
    for (int i = 0; i < n; i++) {
        int k;
        if (sscanf(p, " %llx %llx %llx%n", &sites[i][0], &sites[i][1], &sites[i][2], &k) < 3) return 3;
        p += k;
    }
    memset(cpu, 0, sizeof(Cpu));
    cpu->tpidrro = cpu->tpidr = (uint64_t)(uintptr_t)calloc(1, 0x400);
    if (mmap((void *)SCR, 1 << 16, PROT_READ | PROT_WRITE, MAP_FIXED | MAP_PRIVATE | MAP_ANON, -1, 0) != (void *)SCR) return 3;
    for (uint64_t *w = (uint64_t *)SCR; w < (uint64_t *)(SCR + (1 << 16)); w++) *w = SCR;  // Zeiger zeigen auf sich selbst
    if (zti) rs.zti = zti;
    rs.sites = sites; rs.nsites = n;
    alarm(10);
    long r = (long)call(wrapper, f, SCR, 0, 0);
    if (!rs.thrown) { printf("  %-11s %llx: kein gedeckter Aufruf erreicht (%d Aufrufe uebersprungen, Wrapper %ld)\n", kind, f, rs.skipped, r); return 1; }
    unsigned long long expect = 0;
    for (int i = 0; i < n; i++)
        if (rs.ra - 4 >= sites[i][0] && rs.ra - 4 < sites[i][1]) { expect = sites[i][2]; break; }
    int ok = expect ? rs.first_lp == expect : 0;
    printf("  %-11s %llx: Wurf nach %d Aufrufen, erwartetes Landing-Pad %llx, betreten %llx, Wrapper %ld -> %s\n",
           kind, f, rs.skipped, expect, (unsigned long long)rs.first_lp, r, ok ? "OK" : "ABWEICHUNG");
    return ok ? 0 : 2;
}

static int real_main(const char *spec, uint64_t alloc, uint64_t thr, uint64_t zti_default, uint64_t wrapper) {
    real_mode = 1;
    rs.alloc = alloc; rs.thr = thr; rs.zti = zti_default;
    FILE *fp = fopen(spec, "r");
    if (!fp) die("spec %s", spec);
    static char *lines[4096];
    int nl = 0;
    {
        static char line[1 << 16];
        while (nl < 4096 && fgets(line, sizeof line, fp)) lines[nl++] = strdup(line);
        fclose(fp);  // vor dem Forken lesen: exit() eines Kindes darf den Dateizeiger nicht zurückspulen
    }
    int tot = 0, ok = 0, none = 0, bad = 0, crash = 0, trap = 0;
    for (int li = 0; li < nl; li++) {
        char *line = lines[li];
        tot++;
        fflush(stdout);
        pid_t pid = fork();
        if (!pid) { _exit(run_one(line, wrapper)); }
        int st;
        waitpid(pid, &st, 0);
        if (WIFEXITED(st)) { int c = WEXITSTATUS(st); if (c == 0) ok++; else if (c == 1) none++; else if (c == 4) trap++; else bad++; }
        else { crash++; printf("  Absturz/Zeitueberschreitung (Signal %d) bei Eintrag %d\n", WIFSIGNALED(st) ? WTERMSIG(st) : 0, tot); }
    }
    printf("REAL: %d echte LSDA-Funktionen aus main: %d bestanden (Landing-Pad stimmt), %d ohne erreichten gedeckten Aufruf, %d Landing-Pad-Abweichung, %d Absturz/Zeitlimit durch die synthetische Umgebung, %d Laufzeitfehler (UDF/fehlende Emulation)\n",
           tot, ok, none, bad, crash, trap);
    return bad ? 1 : 0;
}

static int fails;
#define CHECK(cond, ...) do { if (!(cond)) { fails++; printf("  FEHLER: "); printf(__VA_ARGS__); printf("\n"); } } while (0)

int main(int argc, char **argv) {
    setvbuf(stdout, NULL, _IONBF, 0);
    trace = getenv("EH_TRACE") != NULL;
    g_fnprof = getenv("EH_FNTRACE") != NULL;
    if (argc < 4) die("usage: %s <spike2-dir> <sdk-img> <eht-img> [symbols.json-ersatz: test_*=addr ...]", argv[0]);
    char path[512];
    snprintf(path, sizeof path, "%s/hle.txt", argv[1]);
    FILE *f = fopen(path, "r");
    if (f) { char line[512]; while (fgets(line, sizeof line, f) && hle_count < 256) { line[strcspn(line, "\n")] = 0; hle_names[hle_count++] = strdup(line); } fclose(f); }
    hle_bind();
#ifdef REBASE32
    g_base = mmap(NULL, 1ull << 32, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANON | MAP_NORESERVE, -1, 0);
    if (g_base == MAP_FAILED) die("4-GiB-Fenster nicht reservierbar");
    printf("Gastfenster 4 GiB bei Host %p\n", (void *)g_base);
#endif
    map_file(argv[2], SDK_BASE);
    map_file(argv[3], EHT_BASE);
#ifndef REBASE32
    if (mmap((void *)STACK_LO, STACK_SZ, PROT_READ | PROT_WRITE, MAP_FIXED | MAP_PRIVATE | MAP_ANON, -1, 0) != (void *)STACK_LO) die("stack");
#endif
    tabs[0] = (Tab){ sdk_fn_addrs, sdk_fn_ptrs, sdk_fn_count };
    tabs[1] = (Tab){ eht_fn_addrs, eht_fn_ptrs, eht_fn_count };
    cpu = aligned_alloc(16, sizeof(Cpu)); memset(cpu, 0, sizeof(Cpu));
#ifdef REBASE32
    cpu->tpidrro = cpu->tpidr = galloc(0x400, 16);
#else
    cpu->tpidrro = cpu->tpidr = (uint64_t)(uintptr_t)calloc(1, 0x400);  // ThreadLocalRegion (0x200) des Gast-Threads
#endif
    uint64_t t_basic = 0, t_rethrow = 0, t_deep = 0, t_bad = 0, t_nothrow = 0, t_bench = 0, t_bt = 0, t_lj = 0;
    uint64_t a_alloc = 0, a_throw = 0, a_zti = 0, t_run = 0;
    const char *real_spec = NULL, *main_img = NULL;
    for (int i = 4; i < argc; i++) {
        uint64_t v = strtoull(strchr(argv[i], '=') + 1, 0, 0);
        if (!strncmp(argv[i], "test_basic=", 11)) t_basic = v;
        else if (!strncmp(argv[i], "test_rethrow=", 13)) t_rethrow = v;
        else if (!strncmp(argv[i], "test_deep=", 10)) t_deep = v;
        else if (!strncmp(argv[i], "test_badalloc=", 14)) t_bad = v;
        else if (!strncmp(argv[i], "test_nothrow=", 13)) t_nothrow = v;
        else if (!strncmp(argv[i], "test_bench=", 11)) t_bench = v;
        else if (!strncmp(argv[i], "test_backtrace=", 15)) t_bt = v;
        else if (!strncmp(argv[i], "test_longjmp=", 13)) t_lj = v;
        else if (!strncmp(argv[i], "real=", 5)) real_spec = strchr(argv[i], '=') + 1;
        else if (!strncmp(argv[i], "mainimg=", 8)) main_img = strchr(argv[i], '=') + 1;
        else if (!strncmp(argv[i], "alloc=", 6)) a_alloc = v;
        else if (!strncmp(argv[i], "throw=", 6)) a_throw = v;
        else if (!strncmp(argv[i], "zti=", 4)) a_zti = v;
        else if (!strncmp(argv[i], "test_run=", 9)) t_run = v;
    }
    if (real_spec) {
        if (!main_img || !main_fn_addrs) die("real=: mainimg= und ein main-Teilbau werden gebraucht");
        map_file(main_img, MAIN_BASE);
        tabs[2] = (Tab){ main_fn_addrs, main_fn_ptrs, main_fn_count };
        ntabs = 3;
        return real_main(real_spec, a_alloc, a_throw, a_zti, t_run);
    }
    volatile int *log = (volatile int *)H(STACK_LO + 0x1000);

    if (t_bt) {
        long *out = (long *)H(STACK_LO + 0x2000);
        long n = (long)call(t_bt, GA(out), 0, 0, 0);
        printf("T0 Gast-Unwinder ohne Wurf (_Unwind_Backtrace): %ld Rahmen\n", n);
        for (long i = 0; i < n && i < 30; i++)
            printf("  Rahmen %ld: ip=%lx lsda=%lx start=%lx\n", i, out[1 + i * 3], out[2 + i * 3], out[3 + i * 3]);
    }

    printf("T1 throw -> catch ueber 3 Gastrahmen (leaf, mid, mid2 -> test_basic)\n");
    *log = 1;
    long r = (long)call(t_basic, GA(log), 7, 5, 3);
    long k1 = 5 * 7 + 1, k2 = 3 * 5 + 2;
    printf("  Rueckgabe %ld (erwartet %ld), Log %d (erwartet 1234)\n", r, 7 + k1 + k2, *log);
    CHECK(r == 7 + k1 + k2, "Rueckgabe/Callee-Saved");
    CHECK(*log == 1234, "Reihenfolge Aufraeumen/Fang");

    printf("T2 kein Wurf: Rahmenkette bleibt konsistent\n");
    *log = 1;
    r = (long)call(t_nothrow, GA(log), 0, 0, 0);
    printf("  Rueckgabe %ld (erwartet 1), Log %d (erwartet 999992), Kette %p\n", r, *log, (void *)EH_TOP(cpu));
    CHECK(r == 1 && *log == 999992 && EH_TOP(cpu) == NULL, "nothrow");

    printf("T3 catch(...) + throw; (Rethrow) + Fang mit Typ\n");
    *log = 1;
    r = (long)call(t_rethrow, GA(log), 9, 0, 0);
    printf("  Rueckgabe %ld (erwartet 9), Log %d (erwartet 1256)\n", r, *log);
    CHECK(r == 9 && *log == 256 + 1000, "rethrow");

    printf("T4 Tiefe: 200 Rahmen mit Landing-Pads\n");
    r = (long)call(t_deep, GA(log), 200, 5, 0);
    printf("  Rueckgabe %ld (erwartet 5201)\n", r);
    CHECK(r == 5 * 1000 + 201, "deep");

    if (t_bad) {
        printf("T5 Wurf aus echtem SDK-Code (operator new -> bad_alloc)\n");
        *log = 1;
        r = (long)call(t_bad, GA(log), 0, 0, 0);
        printf("  Rueckgabe %ld (erwartet 77), Log %d (erwartet 17)\n", r, *log);
        CHECK(r == 77 && *log == 17, "badalloc");
    }

    if (t_lj) {
        printf("T7 setjmp/longjmp (Wiedereinstieg hinter bl setjmp), longjmp aus 3 + 20 Rahmen, Destruktoren duerfen nicht laufen\n");
        for (int pass = 0; pass < 2; pass++) {  // zweiter Durchlauf: Rahmenkette nach dem ersten Wiedereinstieg unversehrt
            *log = 1;
            r = (long)call(t_lj, GA(log), 5, 3, 20);
            long expect = 5 + (3 * 7 + 1) + (20 * 5 + 2);
            printf("  Durchlauf %d: Rueckgabe %ld (erwartet %ld), Log %d (erwartet 18), Kette %p\n", pass + 1, r, expect, *log, (void *)EH_TOP(cpu));
            CHECK(r == expect && *log == 18 && EH_TOP(cpu) == NULL, "longjmp");
        }
    }

    if (t_bench) {
        long n = 20000;
        struct timespec a, b; clock_gettime(CLOCK_MONOTONIC, &a);
        long s = (long)call(t_bench, GA(log), n, 0, 0);
        clock_gettime(CLOCK_MONOTONIC, &b);
        double us = ((b.tv_sec - a.tv_sec) * 1e9 + (b.tv_nsec - a.tv_nsec)) / 1e3 / n;
        printf("T6 Durchsatz: %ld Wuerfe, %.2f us je Wurf+Fang (4 Rahmen), Summe %ld\n", n, us, s);
    }
    printf("Wiedereinstiege %llu, abgewickelte Host-Rahmen %llu\n", (unsigned long long)stats.nle_enters, (unsigned long long)stats.frames_dropped);
    printf(fails ? "ERGEBNIS: %d FEHLER\n" : "ERGEBNIS: alle Tests bestanden\n", fails);
    return fails ? 1 : 0;
}
