// Synthetisches Gastprogramm für den GC-Test (docs/architecture.md, Abschnitt Threads und GC). Kein Spielcode.
// Ein "Zeiger" wird zeitweise nur noch in einem Register gehalten: er wird aus dem Slot genommen, der Slot geleert,
// und erst nach einer längeren Rechnung ohne Aufruf zurückgelegt. Ein Stop-the-World-GC, der in diesem Fenster anhält,
// findet das Objekt nur, wenn er den Registerzustand des angehaltenen Threads mit auswertet.
long churn(long *slot, long n) {
    long acc = 0;
    for (long i = 0; i < n; i++) {
        long p = *slot;
        *slot = 0;
        __asm__ volatile("dmb ish" ::: "memory");  // verhindert, dass der Host-Compiler den toten Speicherzugriff entfernt
        for (long k = 0; k < 60; k++) acc = acc * 31 + (p >> (k & 7)) + k;
        *slot = p;
    }
    return acc;
}
