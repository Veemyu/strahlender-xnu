// Synthetic guest callbacks exercise the active kernel, not whole-game GC correctness.
#include "bdsp.h"
#include <stdarg.h>
#include <stdatomic.h>

static atomic_int complete;
static int failures;
enum { WORKERS = 4, CYCLES = 32 };
typedef struct {
    uint64_t r[29], fp, lr, sp, pc;
    uint32_t psr, pad;
    __uint128_t v[32];
    uint32_t fpcr, fpsr;
    uint64_t tpidr;
} GuestContext;
extern uint64_t g_suspends, g_resumes;
extern void f_7000000020(Cpu *cpu);
volatile int g_fnprof;
void fnprof_hit(uint64_t address, uint64_t lr, uint64_t x0) {}
#define CHECK(expression) do { \
    if (!(expression)) { fprintf(stderr, "line %d: %s\n", __LINE__, #expression); failures++; } \
} while (0)

void rt_fatal(const char *format, ...) {
    va_list arguments;
    va_start(arguments, format);
    vfprintf(stderr, format, arguments);
    va_end(arguments);
    ExitProcess(2);
}
void crash_handler_install(void) {}
void guest_log(const char *line) { (void)line; }
void hid_shmem_unmapped(uint64_t address) { (void)address; }
uint32_t ipc_connect_named_port(const char *name) { (void)name; return 0; }
int ipc_handle_request(Cpu *cpu, uint32_t handle) { (void)cpu; (void)handle; return R_NOT_IMPLEMENTED; }
const char *loader_symbol_at(uint64_t address, uint64_t *offset) { (void)address; *offset = 0; return NULL; }

static uint64_t svc(Cpu *cpu, uint32_t number, uint64_t a, uint64_t b, uint64_t c) {
    cpu->x[0] = a; cpu->x[1] = b; cpu->x[2] = c;
    rt_svc(cpu, number, 0);
    return cpu->x[0];
}

#ifdef SOLE_ROOT_PROBE
static bool contains_root(const void *memory, size_t size, uint64_t root) {
    const unsigned char *bytes = memory;
    for (size_t offset = 0; offset + sizeof root <= size; offset += sizeof root) {
        uint64_t word;
        memcpy(&word, bytes + offset, sizeof word);
        if (word >= root && word < root + 16) return true;
    }
    return false;
}

static void sole_root_test(Cpu *cpu) {
    for (int trial = 0; trial < 3; trial++) {
        uint64_t root = HEAP_BASE + 0x10000 + trial * 0x1000;
        uint64_t cell = MAIN_BASE + 0x2000;
        uint64_t stack_top = STACK_BASE + 0x100000;
        *G2H64(root) = 0x12345678;
        *G2H64(cell) = ~root;
        memset(G2H(stack_top - 0x1000), 0, 0x1000);
        cpu->x[0] = 0; cpu->x[1] = 1; cpu->x[2] = 0;
        cpu->x[3] = stack_top; cpu->x[4] = 44; cpu->x[5] = 0;
        rt_svc(cpu, 0x08, 0);
        CHECK(cpu->x[0] == R_OK);
        uint32_t handle = (uint32_t)cpu->x[1];
        KThread *target = (KThread *)handle_get(handle);
        CHECK(target != NULL);
        CHECK(svc(cpu, 0x09, handle, 0, 0) == R_OK);
        int observations = 0;
        for (int attempt = 0; attempt < 256 && observations < 8; attempt++) {
            Sleep(1 + attempt % 3);
            uint32_t result = (uint32_t)svc(cpu, 0x32, handle, 1, 0);
            if (result == R_INVALID_STATE) break;  // A finite guest loop may already have ended.
            CHECK(result == R_OK);
            CHECK(svc(cpu, 0x33, MAIN_BASE, handle, 0) == R_OK);
            if (*G2H64(cell) == 0 &&
                    contains_root(&target->host_context, sizeof target->host_context, root)) {
                CHECK(!contains_root(G2H(MAIN_BASE), sizeof(GuestContext), root));
                CHECK(!contains_root(&target->cpu, sizeof target->cpu, root));
                CHECK(!contains_root(G2H(stack_top - 0x1000), 0x1000, root));
                GuestContext positive = *(GuestContext *)G2H(MAIN_BASE);
                positive.r[19] = root + 8;
                CHECK(contains_root(&positive, sizeof positive, root));
                *G2H64(stack_top - 16) = root;
                CHECK(contains_root(G2H(stack_top - 0x1000), 0x1000, root));
                *G2H64(stack_top - 16) = 0;
                observations++;
            }
            CHECK(svc(cpu, 0x32, handle, 0, 0) == R_OK);
        }
        CHECK(observations == 8);
        *(uint32_t *)G2H(MAIN_BASE) = handle;
        cpu->x[0] = 0; cpu->x[1] = MAIN_BASE; cpu->x[2] = 1; cpu->x[3] = 5000000000;
        rt_svc(cpu, 0x18, 0);
        CHECK(cpu->x[0] == R_OK);
        CHECK(target->finished);
        pthread_join(target->host, NULL);
        CHECK(*G2H64(cell) == root);
        CHECK(target->cpu.x[19] == root);
        CHECK(*G2H64(root) == 0x12345678);
    }
    puts("Windows sole root: 24 live host-context roots absent from exported guest contexts and guest stacks");
    atomic_store_explicit(&complete, 1, memory_order_release);
}
#endif

void guest_call(Cpu *cpu, uint64_t entry) {
    if (entry == 1) {
#ifdef SOLE_ROOT_PROBE
        cpu->x[21] = (1ull << 30) + 1;
        cpu->x[23] = ~0ull;
        cpu->x[25] = MAIN_BASE + 0x2000;
#else
        uint64_t worker = cpu->x[0];
        for (int r = 0; r < 31; r++) cpu->x[r] = HEAP_BASE + worker * 0x10000 + r * 16;
        cpu->x[19] += 0x8000;
        cpu->x[20] = cpu->x[22] = 0;
        cpu->sp -= 0x200;
        for (int r = 0; r < 32; r++) {
            uint64_t root = HEAP_BASE + worker * 0x10000 + r * 16;
            G2H64(cpu->sp)[r * 2] = root;
            G2H64(cpu->sp)[r * 2 + 1] = root + 8;
        }
        cpu->x[23] = 16;
        cpu->x[24] = MAIN_BASE + 0x1000 + worker * 8;
        cpu->x[26] = MAIN_BASE + 0x1100 + worker * 8;
        cpu->x[27] = 1;
        cpu->nzcv = 0xa0000000;
        cpu->fpcr = 0x400000;
        cpu->fpsr = 0x10;
        cpu->tpidr = TLS_BASE + worker * 0x200;
#endif
        f_7000000020(cpu);
        return;
    }
    CHECK(entry == 2);
#ifdef SOLE_ROOT_PROBE
    sole_root_test(cpu);
#else
    uint32_t handles[WORKERS];
    KThread *targets[WORKERS];
    for (int worker = 0; worker < WORKERS; worker++) {
        cpu->x[0] = 0; cpu->x[1] = 1; cpu->x[2] = worker;
        cpu->x[3] = STACK_BASE + (worker + 1) * 0x100000;
        cpu->x[4] = 44; cpu->x[5] = 0;
        rt_svc(cpu, 0x08, 0);
        CHECK(cpu->x[0] == R_OK);
        handles[worker] = (uint32_t)cpu->x[1];
        targets[worker] = (KThread *)handle_get(handles[worker]);
        CHECK(targets[worker] != NULL);
        CHECK(svc(cpu, 0x09, handles[worker], 0, 0) == R_OK);
        uint64_t *ready = G2H64(MAIN_BASE + 0x1100 + worker * 8);
        for (int wait = 0; wait < 1000 && !__atomic_load_n(ready, __ATOMIC_ACQUIRE); wait++)
            Sleep(1);
        CHECK(__atomic_load_n(ready, __ATOMIC_ACQUIRE) == 1);
        CHECK(svc(cpu, 0x33, MAIN_BASE, handles[worker], 0) == R_INVALID_STATE);
    }
    CHECK(svc(cpu, 0x32, 0xffff8000u, 1, 0) == R_INVALID_STATE);
    uint64_t previous[WORKERS] = {0};
    for (int cycle = 0; cycle < CYCLES; cycle++) {
        Sleep(1);
        // On a busy machine a worker may not have run within 1 ms; give each up to 500 ms to make progress.
        for (int worker = 0; worker < WORKERS && cycle; worker++)
            for (int wait = 0; wait < 500 && __atomic_load_n(&targets[worker]->cpu.x[20], __ATOMIC_RELAXED) <= previous[worker]; wait++)
                Sleep(1);
        for (int worker = 0; worker < WORKERS; worker++)
            CHECK(svc(cpu, 0x32, handles[worker], 1, 0) == R_OK);
        for (int worker = 0; worker < WORKERS; worker++) {
            uint32_t handle = handles[worker];
            KThread *target = targets[worker];
            CHECK(svc(cpu, 0x32, handle, 1, 0) == R_OK);
            CHECK(target->suspended);
            uint64_t counter = target->cpu.x[20];
            if (cycle) CHECK(counter > previous[worker]);
            previous[worker] = counter;
            Sleep(1);
            CHECK(target->cpu.x[20] == counter);
#if defined(__x86_64__)
            CHECK(target->host_context.Rip != 0);
            uint64_t sp = target->host_context.Rsp;
#elif defined(__aarch64__)
            CHECK(target->host_context.Pc != 0);
            uint64_t sp = target->host_context.Sp;
#else
#error Unsupported Windows test architecture
#endif
            CHECK(sp >= (uintptr_t)target->host_stack_lo);
            CHECK(sp - (uintptr_t)target->host_stack_lo < target->host_stack_size);
            CHECK(svc(cpu, 0x33, MAIN_BASE, handle, 0) == R_OK);
            GuestContext *context = G2H(MAIN_BASE);
            CHECK(memcmp(context->r, target->cpu.x, sizeof context->r) == 0);
            CHECK(context->fp == target->cpu.x[29]);
            CHECK(context->lr == target->cpu.x[30]);
            CHECK(context->sp == target->cpu.sp);
            CHECK(memcmp(context->v, target->cpu.v, sizeof context->v) == 0);
            CHECK(context->psr == target->cpu.nzcv);
            CHECK(context->fpcr == target->cpu.fpcr);
            CHECK(context->fpsr == target->cpu.fpsr);
            CHECK(context->tpidr == target->cpu.tpidr);
            uint64_t root = HEAP_BASE + worker * 0x10000;
            for (int r = 0; r < 29; r++) {
                if (r == 19 || r == 20 || r == 22 || r == 23 || r == 24 || r == 26 || r == 27) continue;
                CHECK(context->r[r] == root + r * 16);
            }
            CHECK(context->fp == root + 29 * 16);
            CHECK(context->lr == root + 30 * 16);
            CHECK(context->r[19] == root + 0x8000 + (19 * 16) ||
                  context->r[19] == ((root + 0x8000 + (19 * 16)) ^ 16ull));
            for (int r = 0; r < 32; r++) {
                CHECK(G2H64(context->sp)[r * 2] == root + r * 16);
                CHECK(G2H64(context->sp)[r * 2 + 1] == root + r * 16 + 8);
                CHECK((uint64_t)context->v[r] == root + r * 16);
                CHECK((uint64_t)(context->v[r] >> 64) == root + r * 16 + 8);
            }
            GuestContext snapshot = *context;
            Sleep(1);
            CHECK(svc(cpu, 0x33, MAIN_BASE, handle, 0) == R_OK);
            CHECK(memcmp(&snapshot, context, sizeof snapshot) == 0);
            CHECK(svc(cpu, 0x32, handle, 1, 0) == R_OK);
        }
        for (int worker = 0; worker < WORKERS; worker++) {
            uint32_t handle = handles[worker];
            CHECK(svc(cpu, 0x32, handle, 0, 0) == R_OK);
            CHECK(svc(cpu, 0x33, MAIN_BASE, handle, 0) == R_INVALID_STATE);
        }
    }
    CHECK(g_suspends == WORKERS * CYCLES && g_resumes == WORKERS * CYCLES);
    for (int worker = 0; worker < WORKERS; worker++) {
        KThread *target = targets[worker];
        uint32_t handle = handles[worker];
        __atomic_store_n(G2H64(MAIN_BASE + 0x1000 + worker * 8), 1, __ATOMIC_RELEASE);
        *(uint32_t *)G2H(MAIN_BASE) = handle;
        cpu->x[0] = 0; cpu->x[1] = MAIN_BASE; cpu->x[2] = 1; cpu->x[3] = 2000000000;
        rt_svc(cpu, 0x18, 0);
        CHECK(cpu->x[0] == R_OK);
        CHECK(target->finished);
        CHECK(svc(cpu, 0x32, handle, 1, 0) == R_INVALID_STATE);
        pthread_join(target->host, NULL);
    }
    puts("Windows GC context: four workers, all guest GPR/SIMD roots and guest stacks, repeated frozen snapshots");
    atomic_store_explicit(&complete, 1, memory_order_release);
#endif
}

int main(void) {
    void *window;
    if (!bdsp_win32_reserve((void *)(uintptr_t)GUEST_LO, GUEST_HI - GUEST_LO, 0, &window))
        return 2;
    kernel_init();
    KThread *controller = kernel_create_main_thread(2, 0x10000, 44, 0);
    kernel_run_main(controller, 0, 0, 0, 0);
    uint64_t end = rt_now_ns() + 15000000000ull;
    while (!atomic_load_explicit(&complete, memory_order_acquire) && rt_now_ns() < end) Sleep(1);
    if (!atomic_load_explicit(&complete, memory_order_acquire)) {
        fprintf(stderr, "Windows kernel probe timed out\n");
        return 2;
    }
    pthread_join(controller->host, NULL);
    kernel_report(stdout);
    CHECK(bdsp_win32_release());
    return failures != 0;
}
