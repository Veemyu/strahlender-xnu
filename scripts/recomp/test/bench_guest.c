// Micro-benchmarks for the performance comparison "recompiled against native" (docs/architecture.md).
// Own code, no game code. The same source is (1) compiled for aarch64-linux and recompiled, (2) compiled natively on
// the Mac (bench_prove.c includes it with renamed symbols).
typedef unsigned long u64;

// Integer and memory: xorshift, random accesses to 32 KiB
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

// Calls and stack: recursive Fibonacci function
u64 fib(u64 n) { return n < 2 ? n : fib(n - 1) + fib(n - 2); }
u64 bench_calls(u64 n) { return fib(n); }

// Floating point (inline asm blocks in the recompilation)
double bench_float(double *buf, u64 n) {
    double a = 1.0001, b = 0.5;
    for (u64 i = 0; i < n; i++) {
        double v = buf[i & 1023];
        b = b * a + v * 0.25;
        buf[(i * 3) & 1023] = b - v;
    }
    return b;
}

// Indirect calls (function pointer table: one rt_dispatch per call in the recompilation)
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
