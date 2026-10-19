// Harness für den erzeugten C-Code (c-Modus) im Differenzialtest (docs/recomp-diff.md). Eigener Code.
// lifted.c (von mktests.py erzeugt) definiert die Tabelle `test_fns[]` mit Gast-Funktionen `void t_<id>(Cpu *)`.
// Übersetzt als Bibliothek (Mac: Gegenprobe, Ryzen: Varianten), von difftest.py per ctypes geladen.
#include <string.h>
#if defined(__x86_64__)
#include <xmmintrin.h>
#endif

#include "cpu.h"
#include "difftest.h"
#include "simd.h"
#ifdef CEXACT_GUARD
#include "fp_env.h"
#endif

extern GuestFn test_fns[];
extern const int test_count;

static uint32_t g_mxcsr; // Host-FPU-Zustand während des Laufs (nur x86; 0 = unverändert lassen)
void set_mxcsr(uint32_t v) { g_mxcsr = v; }

// Mikro-Benchmark: n Aufrufe derselben Gastfunktion auf harmlosen Werten (Ergebnis zurück in V1..V3, damit die Kette
// nicht ausläuft); gibt einen Prüfwert zurück. Zeit misst der Aufrufer.
uint64_t bench_c(int id, uint64_t n, uint64_t fpcr) {
    GuestFn f = test_fns[id];
    static Cpu cpu_b __attribute__((aligned(16)));
    Cpu *c = &cpu_b;
    memset(c, 0, sizeof *c);
    float a = 1.5f, b = 2.25f, d = 0.75f;
    for (int k = 0; k < 4; k++) { memcpy((char *)&c->v[1] + 4 * k, &a, 4); memcpy((char *)&c->v[2] + 4 * k, &b, 4); memcpy((char *)&c->v[3] + 4 * k, &d, 4); }
    double da = 1.5, db = 2.25;
    memcpy((char *)&c->v[4], &da, 8); memcpy((char *)&c->v[5], &db, 8);
    c->fpcr = fpcr & 0x7c00000ull;
    c->x[1] = 12345;
    uint64_t acc = 0;
    for (uint64_t i = 0; i < n; i++) {
        f(c);
        acc += (uint64_t)c->v[0] + c->x[0];
        c->x[1] += 3;
    }
    return acc;
}

// Ablauf eines Falls wie im erzeugten Code: Cpu ist null außer den Eingaben; Speicher = lokaler Puffer (Gast = Host).
int run_c(int id, const Case *in, Out *out, uint64_t n) {
    if (id < 0 || id >= test_count) return -1;
    GuestFn f = test_fns[id];
    static Cpu cpu_buf __attribute__((aligned(16)));
    Cpu *c = &cpu_buf;
    uint8_t mem[192] __attribute__((aligned(16)));
#if defined(__x86_64__)
    unsigned saved = _mm_getcsr();
    if (g_mxcsr) _mm_setcsr(g_mxcsr);
#endif
#ifdef CEXACT_GUARD
    rt_fp_guest_mode(); // Gegenprobe: der Schutz aus c_exact/fp_env.h macht den gestörten Host-Zustand unschädlich
#endif
#if defined(__x86_64__)
#endif
    for (uint64_t i = 0; i < n; i++) {
        memset(c, 0, sizeof *c);
        for (int k = 0; k < 8; k++) memcpy(&c->v[k], in[i].v[k], 16);
        for (int k = 0; k < 4; k++) c->x[k] = in[i].x[k];
        memcpy(mem, in[i].mem, sizeof mem);
        if (in[i].memflag) c->x[1] = (uint64_t)(uintptr_t)(mem + 64);
        c->nzcv = in[i].nzcv;
        c->fpcr = in[i].fpcr & 0x7c00000ull;
        f(c);
        memcpy(out[i].v0, &c->v[0], 16);
        out[i].x0 = c->x[0];
        out[i].nzcv = c->nzcv & 0xf0000000ull;
        out[i].fpsr = c->fpsr;
        out[i].x1 = in[i].memflag ? c->x[1] - (uint64_t)(uintptr_t)(mem - 192) : c->x[1];
        memcpy(out[i].mem, mem, sizeof mem);
    }
#if defined(__x86_64__)
    _mm_setcsr(saved);
#endif
    return 0;
}
