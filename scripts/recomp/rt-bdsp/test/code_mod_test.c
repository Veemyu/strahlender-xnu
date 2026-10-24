// Synthetic loader and dispatcher checks; no game code or save access.
#include <assert.h>
#include <sys/mman.h>
#include <unistd.h>
#include "bdsp.h"

static void vanilla(Cpu *c) { c->x[0] = 1; }
static void modified(Cpu *c) { c->x[0] = 42; }
#define TABLE(name, base, fn) \
    const uint64_t name##_fn_addrs[] = {(base) + 0x100}; \
    const GuestFn name##_fn_ptrs[] = {fn}; \
    const uint64_t name##_fn_count = 1
TABLE(main, MAIN_BASE, vanilla);
TABLE(sdk, SDK_BASE, vanilla);
TABLE(subsdk0, SUBSDK0_BASE, vanilla);
TABLE(rtld, RTLD_BASE, vanilla);
#if BDSP_HAS_SUBSDK1
TABLE(subsdk1, SUBSDK1_BASE, modified);
#endif

KThread *kernel_current_thread(void) { return NULL; }
Cpu *kernel_current_cpu(void) { return NULL; }
void bdsp_gate_hit(const char *name) { (void)name; }
void bdsp_fatal_report(const char *reason, int code) { (void)reason; exit(code); }
static int regions;
void kernel_region_add(uint64_t addr, uint64_t size, uint32_t type, uint32_t perm) {
    (void)addr; (void)size; (void)type; (void)perm; regions++;
}

static void module(const char *directory, const char *name, uint64_t base, int map) {
    if (map) {
        void *wanted = (void *)(uintptr_t)base;
        void *memory = mmap(wanted, 0x1000, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANON, -1, 0);
        assert(memory == wanted);
    }
    char path[1200];
    snprintf(path, sizeof path, "%s/%s.mod", directory, name);
    FILE *file = fopen(path, "w"); assert(file);
    fprintf(file, "%s %llx 0 4 4 8 8 c 1000 0 0 0\n", name, (unsigned long long)base);
    fclose(file);
    snprintf(path, sizeof path, "%s/%s.img", directory, name);
    file = fopen(path, "wb"); assert(file);
    const uint32_t marker = 0x12345678;
    assert(fwrite(&marker, sizeof marker, 1, file) == 1); fclose(file);
    snprintf(path, sizeof path, "%s/%s.syms.json", directory, name);
    file = fopen(path, "w"); assert(file);
    fprintf(file, "{\"synthetic_%s\": %llu}", name, (unsigned long long)(base + 0x100)); fclose(file);
}

int main(int argc, char **argv) {
    assert(argc == 2 || argc == 3);
    module(argv[1], "main", MAIN_BASE, 1);
    module(argv[1], "sdk", SDK_BASE, 1);
    module(argv[1], "subsdk0", SUBSDK0_BASE, 1);
#if BDSP_HAS_SUBSDK1
    module(argv[1], "subsdk1", argc == 3 ? MAIN_BASE + 0x800 : SUBSDK1_BASE, argc != 3);
#endif
    loader_load(argv[1]);
    assert(g_nmodules == 3 + BDSP_HAS_SUBSDK1);
    assert(regions == 3 * g_nmodules);
    dispatch_init();
    Cpu cpu = {0};
    GuestFn fn = dispatch_lookup(MAIN_BASE + 0x100); assert(fn);
    fn(&cpu); assert(cpu.x[0] == 1);
#if BDSP_HAS_SUBSDK1
    assert(loader_find_symbol("synthetic_subsdk1") == SUBSDK1_BASE + 0x100);
    fn = dispatch_lookup(SUBSDK1_BASE + 0x100); assert(fn);
    fn(&cpu); assert(cpu.x[0] == 42);
    assert(*G2H32(SUBSDK1_BASE) == 0x12345678);
#else
    assert(dispatch_lookup(SUBSDK1_BASE + 0x100) == NULL);
#endif
    assert(dispatch_lookup(SUBSDK1_BASE + 0x104) == NULL);
    puts("Code-mod loader/dispatcher: passed");
    return 0;
}
