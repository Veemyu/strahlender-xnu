// Synthetic test of the kernel of the BDSP runtime (without game code): host threads, SVC 0x32/0x33 (suspend and register state
// for the Boehm GC), WaitSynchronization on the thread object, ArbitrateLock/Unlock and WaitForAddress/SignalToAddress.
// The "guest functions" are hand-written C functions with the signature of the generated functions and sit in an
// artificial dispatch table. Build and run: scripts/recomp/rt-bdsp/test/run_kernel_test.sh
#include <mach/mach.h>
#include <mach/mach_vm.h>
#include <unistd.h>

#include "bdsp.h"

// ---- artificial guest functions
static void guest_counter(Cpu *c) {  // counts in x20, remembers x19; ends when x22 != 0
    c->x[19] = 0x1234;
    for (;;) {
        __atomic_fetch_add(&c->x[20], 1, __ATOMIC_RELAXED);  // otherwise the compiler keeps the counter in a register
        if (__atomic_load_n(&c->x[22], __ATOMIC_RELAXED)) return;
    }
}
static uint64_t waiter_addr, waiter_result;
static void guest_waiter(Cpu *c) {  // waits for *waiter_addr > 0 (WaitForAddress), reports the result
    c->x[0] = waiter_addr; c->x[1] = 0 /* WAIT_LESS */; c->x[2] = 1; c->x[3] = (uint64_t)-1;
    rt_svc(c, 0x34, 0);
    waiter_result = c->x[0] + 1;  // 1 = R_OK
}
static uint64_t lock_addr;
static volatile int lock_hits;
static void guest_locker(Cpu *c) {  // mutex Horizon style: 0 = free, otherwise owner handle (+ waiter bit), handover by the kernel
    uint32_t tag = (uint32_t)c->x[0];
    uint32_t *m = G2H32(lock_addr);
    for (int i = 0; i < 2000; i++) {
        for (;;) {
            uint32_t exp = 0;
            if (__atomic_compare_exchange_n(m, &exp, tag, 0, __ATOMIC_SEQ_CST, __ATOMIC_SEQ_CST)) break;
            if ((exp & ~0x40000000u) == tag) break;
            uint32_t want = exp | 0x40000000u;
            if (!(exp & 0x40000000u) && !__atomic_compare_exchange_n(m, &exp, want, 0, __ATOMIC_SEQ_CST, __ATOMIC_SEQ_CST)) continue;
            c->x[0] = want & ~0x40000000u; c->x[1] = lock_addr; c->x[2] = tag;
            rt_svc(c, 0x1A, 0);
            if ((__atomic_load_n(m, __ATOMIC_SEQ_CST) & ~0x40000000u) == tag) break;  // ownership handed over by the kernel
        }
        lock_hits++;
        uint32_t exp = tag;
        if (!__atomic_compare_exchange_n(m, &exp, 0, 0, __ATOMIC_SEQ_CST, __ATOMIC_SEQ_CST)) { c->x[0] = lock_addr; rt_svc(c, 0x1B, 0); }
    }
}

static void guest_test(Cpu *c);
static volatile int exit_before, exit_after;
static void guest_exiter(Cpu *c) {  // ExitThread mitten in verschachtelten Rahmen: nichts danach darf laufen
    exit_before = 1;
    rt_svc(c, 0x0A, 0);
    exit_after = 1;
}
#define FN_BASE 0x7000001000ull
const uint64_t main_fn_addrs[] = {FN_BASE, FN_BASE + 16, FN_BASE + 32, FN_BASE + 48, FN_BASE + 64, FN_BASE + 80};
const GuestFn main_fn_ptrs[] = {guest_counter, guest_waiter, guest_locker, guest_locker, guest_test, guest_exiter};
const uint64_t main_fn_count = 6;
const uint64_t sdk_fn_addrs[] = {0x7006000000ull}; const GuestFn sdk_fn_ptrs[] = {guest_counter}; const uint64_t sdk_fn_count = 1;
const uint64_t subsdk0_fn_addrs[] = {0x7007000000ull}; const GuestFn subsdk0_fn_ptrs[] = {guest_counter}; const uint64_t subsdk0_fn_count = 1;
const uint64_t rtld_fn_addrs[] = {0x7008000000ull}; const GuestFn rtld_fn_ptrs[] = {guest_counter}; const uint64_t rtld_fn_count = 1;

void guest_log(const char *line) { (void)line; }
void bdsp_gate_hit(const char *what) { (void)what; }
void bdsp_fatal_report(const char *why, int code) { printf("FATAL im Test: %s\n", why); _exit(code); }
uint64_t rt_ticks(void);

static int fails;
#define CHECK(x) do { if (!(x)) { printf("ERROR line %d: %s\n", __LINE__, #x); fails++; } } while (0)

static Cpu *mc;  // Cpu of the test kernel thread (guest_test), so t_cur is set in the kernel
static uint64_t svc(uint32_t n, uint64_t a0, uint64_t a1, uint64_t a2, uint64_t a3, uint64_t *r1) {
    mc->x[0] = a0; mc->x[1] = a1; mc->x[2] = a2; mc->x[3] = a3;
    rt_svc(mc, n, 0);
    if (r1) *r1 = mc->x[1];
    return mc->x[0];
}
static uint64_t make_thread(uint64_t entry, uint64_t arg) {
    uint64_t h;
    CHECK(svc(0x08, 0, entry, arg, STACK_BASE + 0x100000, &h) == 0);
    return h;
}

static volatile int test_done;
static void guest_test(Cpu *c) {
    mc = c;
    // T1: Thread starten, anhalten, Kontext lesen, fortsetzen, beenden
    uint64_t h = make_thread(FN_BASE, 0);
    CHECK(svc(0x09, h, 0, 0, 0, NULL) == 0);
    KThread *t = (KThread *)handle_get((uint32_t)h);
    for (int i = 0; i < 200 && t->cpu.x[20] < 1000; i++) usleep(1000);
    CHECK(t->cpu.x[20] >= 1000);
    CHECK(svc(0x32, h, 1, 0, 0, NULL) == 0);  // SetThreadActivity(Paused)
    uint64_t c1 = t->cpu.x[20];
    usleep(30000);
    CHECK(t->cpu.x[20] == c1);                // wirklich angehalten
    uint8_t *buf = hle_alloc(0x400);
    CHECK(svc(0x33, H2G(buf), h, 0, 0, NULL) == 0);
    const uint64_t *ctx = (const uint64_t *)buf;
    CHECK(ctx[19] == 0x1234);                 // x19 im Kontext
    CHECK(ctx[20] == c1);                     // x20 = counter value at suspension
    CHECK(svc(0x32, h, 0, 0, 0, NULL) == 0);  // fortsetzen
    for (int i = 0; i < 200 && t->cpu.x[20] == c1; i++) usleep(1000);
    CHECK(t->cpu.x[20] > c1);
    CHECK(svc(0x32, 0xFFFF8000u, 1, 0, 0, NULL) != 0);  // suspend itself: error (handle invalid in the test main thread)
    __atomic_store_n(&t->cpu.x[22], 1, __ATOMIC_RELAXED);
    uint64_t idx;
    uint64_t *hs = (uint64_t *)hle_alloc(16);
    *(uint32_t *)hs = (uint32_t)h;
    CHECK(svc(0x18, 0, H2G(hs), 1, 2000000000ll, &idx) == 0);  // WaitSynchronization on the thread object (2 s)
    CHECK(t->finished);

    // T2: WaitForAddress / SignalToAddress
    uint32_t *flag = (uint32_t *)hle_alloc(16);
    waiter_addr = H2G(flag);
    *flag = 0;
    uint64_t hw = make_thread(FN_BASE + 16, 0);
    CHECK(svc(0x09, hw, 0, 0, 0, NULL) == 0);
    usleep(50000);
    CHECK(waiter_result == 0);
    *flag = 1;
    CHECK(svc(0x35, H2G(flag), 0 /* SIGNAL */, 0, 1, NULL) == 0);
    for (int i = 0; i < 200 && !waiter_result; i++) usleep(1000);
    CHECK(waiter_result == 1);

    // T3: ArbitrateLock/Unlock with two threads around a mutex (4000 locks)
    uint32_t *mutex = (uint32_t *)hle_alloc(16);
    lock_addr = H2G(mutex);
    uint64_t l1 = make_thread(FN_BASE + 32, 0), l2 = make_thread(FN_BASE + 48, 0);
    ((KThread *)handle_get((uint32_t)l1))->cpu.x[0] = (uint32_t)l1;
    ((KThread *)handle_get((uint32_t)l2))->cpu.x[0] = (uint32_t)l2;
    CHECK(svc(0x09, l1, 0, 0, 0, NULL) == 0);
    CHECK(svc(0x09, l2, 0, 0, 0, NULL) == 0);
    *(uint32_t *)hs = (uint32_t)l1; ((uint32_t *)hs)[1] = (uint32_t)l2;
    CHECK(svc(0x18, 0, H2G(hs), 2, 5000000000ll, &idx) == 0);
    for (int i = 0; i < 2000 && !(((KThread *)handle_get((uint32_t)l1))->finished && ((KThread *)handle_get((uint32_t)l2))->finished); i++) usleep(2000);
    CHECK(lock_hits == 4000);
    CHECK(*mutex == 0);

    // T4: ExitThread ends the thread and signals the thread object
    uint64_t hx = make_thread(FN_BASE + 80, 0);
    CHECK(svc(0x09, hx, 0, 0, 0, NULL) == 0);
    *(uint32_t *)hs = (uint32_t)hx;
    CHECK(svc(0x18, 0, H2G(hs), 1, 2000000000ll, &idx) == 0);
    CHECK(exit_before == 1 && exit_after == 0);
    CHECK(((KThread *)handle_get((uint32_t)hx))->finished);

    printf(fails ? "Kernel test: %d errors\n" : "Kernel test: passed (threads, suspend/context, arbiter, mutex, ExitThread)\n", fails);
    test_done = fails ? 2 : 1;
}

int main(void) {
    mach_vm_address_t a = GUEST_LO;
    if (mach_vm_allocate(mach_task_self(), &a, GUEST_HI - GUEST_LO, VM_FLAGS_FIXED) != KERN_SUCCESS) { printf("Gastfenster nicht frei\n"); return 2; }
    kernel_init();
    dispatch_init();
    KThread *t = kernel_create_main_thread(FN_BASE + 64, 0x10000, 44, 0);
    kernel_run_main(t, 0, 0, 0, 0);
    for (int i = 0; i < 3000 && !test_done; i++) usleep(10000);  // at most 30 s
    if (!test_done) { printf("Kernel test: timeout\n"); return 1; }
    return test_done == 2;
}
