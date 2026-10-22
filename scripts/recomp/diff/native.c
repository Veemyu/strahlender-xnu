// Native reference run on Apple Silicon (docs/recomp-diff.md): copies the finished machine code of the loop
// (tmpl.S, with the instructions inserted) into a JIT region and runs it. macOS/arm64 only. Own code.
#include <libkern/OSCacheControl.h>
#include <pthread.h>
#include <stdint.h>
#include <string.h>
#include <sys/mman.h>

#include "difftest.h"

int run_native(const uint8_t *code, uint64_t len, const Case *in, Out *out, uint64_t n) {
    static uint8_t *mem;
    if (!mem) {
        mem = mmap(0, 16384, PROT_READ | PROT_WRITE | PROT_EXEC, MAP_PRIVATE | MAP_ANON | MAP_JIT, -1, 0);
        if (mem == MAP_FAILED) { mem = 0; return -1; }
    }
    if (len > 16384) return -2;
    pthread_jit_write_protect_np(0);
    memcpy(mem, code, len);
    pthread_jit_write_protect_np(1);
    sys_icache_invalidate(mem, len);
    ((void (*)(const Case *, Out *, uint64_t))mem)(in, out, n);
    return 0;
}
