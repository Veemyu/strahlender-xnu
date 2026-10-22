// Mikro-Benchmarks für den Leistungsvergleich "rekompiliert gegen nativ" (docs/architecture.md).
// Eigener Code, kein Spielcode. Dieselbe Quelle wird (1) für aarch64-linux übersetzt und rekompiliert, (2) nativ auf
// dem Mac übersetzt (bench_prove.c bindet sie mit umbenannten Symbolen ein).
typedef unsigned long u64;

// Ganzzahl und Speicher: Xorshift, zufällige Zugriffe auf 32 KiB
u64 bench_int(u64 *buf, u64 n) {
    u64 x = 88172645463325252ull, s = 0;
    for (u64 i = 0; i < n; i++) {
        x ^= x << 13; x ^= x >> 7; x ^= x << 17;
        u64 k = x & 4095;
        buf[k] += x;
        s += buf[(k * 7) & 4095];
    }
    return s;
}

// Aufrufe und Stack: rekursive Fibonacci-Funktion
u64 fib(u64 n) { return n < 2 ? n : fib(n - 1) + fib(n - 2); }
u64 bench_calls(u64 n) { return fib(n); }

// Gleitkomma (Inline-asm-Blöcke im Rekompilat)
double bench_float(double *buf, u64 n) {
    double a = 1.0001, b = 0.5;
    for (u64 i = 0; i < n; i++) {
        double v = buf[i & 1023];
        b = b * a + v * 0.25;
        buf[(i * 3) & 1023] = b - v;
    }
    return b;
}

// Indirekte Aufrufe (Funktionszeiger-Tabelle: im Rekompilat ein rt_dispatch je Aufruf)
typedef u64 (*fn)(u64);
__attribute__((noinline)) static u64 f0(u64 x) { return x + 1; }
__attribute__((noinline)) static u64 f1(u64 x) { return x * 3; }
__attribute__((noinline)) static u64 f2(u64 x) { return x ^ 0x55; }
__attribute__((noinline)) static u64 f3(u64 x) { return x - 7; }
__attribute__((noinline)) static u64 f4(u64 x) { return x + (x >> 3); }
__attribute__((noinline)) static u64 f5(u64 x) { return x * 5 + 1; }
__attribute__((noinline)) static u64 f6(u64 x) { return x ^ (x << 1); }
__attribute__((noinline)) static u64 f7(u64 x) { return x + 11; }
u64 bench_indirect(u64 *unused, u64 n) {
    static const fn t[8] = { f0, f1, f2, f3, f4, f5, f6, f7 };
    u64 s = 1;
    (void)unused;
    for (u64 i = 0; i < n; i++) s = t[(s + i) & 7](s);
    return s;
}
