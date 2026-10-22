// Synthetic guest program for the GC test (docs/architecture.md, section threads and GC). No game code.
// A "pointer" is temporarily kept only in a register: it is taken out of the slot, the slot is cleared,
// and it is put back only after a longer computation without a call. A stop-the-world GC that suspends in this window
// finds the object only if it also evaluates the register state of the suspended thread.
long churn(long *slot, long n) {
    long acc = 0;
    for (long i = 0; i < n; i++) {
        long p = *slot;
        *slot = 0;
        __asm__ volatile("dmb ish" ::: "memory");  // prevents the host compiler from removing the dead memory access
        for (long k = 0; k < 60; k++) acc = acc * 31 + (p >> (k & 7)) + k;
        *slot = p;
    }
    return acc;
}
