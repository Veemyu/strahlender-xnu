// Synthetisches Gast-Testprogramm für den Exception-Spike (docs/recomp-spike-2.md). Kein Spielcode.
// Übersetzung: clang --target=aarch64-linux-gnu -O1 -fexceptions -fno-rtti -c eh_guest.cpp
// Die C++-Laufzeit (__cxa_*, __gxx_personality_v0, _Unwind_*) kommt aus dem echten SDK-Modul des Spiels
// (rekompiliert); hier wird nur aufgerufen.
typedef unsigned long usize;

extern void *operator new(usize);

struct Guard {
    volatile int *log;
    int tag;
    ~Guard() { *log = *log * 10 + tag; }
};

__attribute__((noinline)) static void leaf(int v) {
    if (v) throw v;
}

__attribute__((noinline)) static void mid(volatile int *log, int v) {
    Guard g{log, 2};
    leaf(v);
    *log = 99999;  // darf bei v != 0 nie laufen
}

__attribute__((noinline)) static void mid2(volatile int *log, int v) {
    Guard g{log, 3};
    mid(log, v);
    *log = 88888;
}

// Wurf in Rahmen 1, Aufräumen in Rahmen 2 und 3, Fang in Rahmen 4; k1/k2 leben über den Aufruf (x19..x28).
extern "C" long test_basic(volatile int *log, int v, long a, long b) {
    long k1 = a * 7 + 1, k2 = b * 5 + 2;
    try {
        mid2(log, v);
    } catch (int e) {
        *log = *log * 10 + 4;
        return e + k1 + k2;
    }
    return -1000 + k1 + k2;
}

__attribute__((noinline)) static void rethrower(volatile int *log, int v) {
    try {
        mid(log, v);
    } catch (...) {
        *log = *log * 10 + 5;
        throw;
    }
}

// catch(...) mit Rethrow (__cxa_rethrow, _Unwind_Resume_or_Rethrow), äußerer Fang mit Typ
extern "C" long test_rethrow(volatile int *log, int v) {
    try {
        rethrower(log, v);
    } catch (int e) {
        *log = *log * 10 + 6;
        return e;
    }
    return -1;
}

__attribute__((noinline)) static void deep(volatile int *log, int depth, int v) {
    struct Count {
        volatile int *log;
        ~Count() { *log = *log + 1; }
    } g{log};
    if (depth == 0) leaf(v);
    else deep(log, depth - 1, v);
}

// n Rahmen mit Aufräum-Landing-Pads, Fang oben
extern "C" long test_deep(volatile int *log, int depth, int v) {
    *log = 0;
    try {
        deep(log, depth, v);
    } catch (int e) {
        return e * 1000 + *log;
    }
    return -1;
}

// Wurf aus echtem SDK-Code (operator new -> std::bad_alloc); mindestens ein echter SDK-Rahmen liegt dazwischen
extern "C" long test_badalloc(volatile int *log) {
    try {
        volatile void *p = ::operator new((usize)0x7fffffffffffull);
        (void)p;
    } catch (...) {
        *log = *log * 10 + 7;
        return 77;
    }
    return -1;
}

extern "C" long test_nothrow(volatile int *log) {
    try {
        mid(log, 0);
    } catch (int) {
        return -1;
    }
    return 1;
}

extern "C" long test_bench(volatile int *log, long n) {
    long sum = 0;
    for (long i = 0; i < n; i++) {
        *log = 0;
        sum += test_basic(log, 7, i, 1);
    }
    return sum;
}

// Wrapper für den Wurf-Test mit echten Funktionen (eh_harness real=...): ruft f mit Zeigerargumenten, fängt alles
extern "C" long test_run(void (*f)(void *, void *, void *, void *), void *a) {
    try {
        f(a, a, a, a);
    } catch (...) {
        return 1;
    }
    return 0;
}

// Diagnose: Gast-Unwinder ohne Wurf benutzen (_Unwind_Backtrace) und je Rahmen IP, LSDA und Funktionsanfang melden
extern "C" {
int _Unwind_Backtrace(int (*)(void *, void *), void *);
unsigned long _Unwind_GetIP(void *);
void *_Unwind_GetLanguageSpecificData(void *);
unsigned long _Unwind_GetRegionStart(void *);
}
static int bt_cb(void *ctx, void *arg) {
    long *out = (long *)arg;
    long n = out[0];
    if (n < 30) {
        out[1 + n * 3] = (long)_Unwind_GetIP(ctx);
        out[2 + n * 3] = (long)_Unwind_GetLanguageSpecificData(ctx);
        out[3 + n * 3] = (long)_Unwind_GetRegionStart(ctx);
    }
    out[0] = n + 1;
    return 0;
}
__attribute__((noinline)) static void bt_leaf(long *out) { Guard g{(volatile int *)out + 200, 0}; _Unwind_Backtrace(bt_cb, out); }
extern "C" long test_backtrace(long *out) {
    out[0] = 0;
    bt_leaf(out);
    return out[0];
}
