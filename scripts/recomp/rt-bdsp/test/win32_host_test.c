#include "bdsp.h"
#include <stdarg.h>
#include <wchar.h>

static int failures;
#define CHECK(expression) do { \
    if (!(expression)) { fprintf(stderr, "line %d: %s (Windows %lu)\n", \
                                 __LINE__, #expression, GetLastError()); failures++; } \
} while (0)

void rt_fatal(const char *format, ...) {
    va_list arguments;
    va_start(arguments, format);
    vfprintf(stderr, format, arguments);
    va_end(arguments);
    ExitProcess(2);
}

static unsigned regions, slots;
void kernel_region_add(uint64_t address, uint64_t size, uint32_t type, uint32_t permissions) {
    (void)address; (void)size; (void)type; (void)permissions;
    regions++;
}
uint64_t hle_register(const char *name, HostFn function) {
    (void)function;
    CHECK(!strcmp(name, "synthetic_hle"));
    return HLE_BASE + 16 * slots++;
}

static void test_memory(const wchar_t *mode) {
    void *allocation = NULL;
    const size_t size = 8u << 20;
    CHECK(bdsp_win32_reserve(NULL, size, 0x10000, &allocation));
    if (!allocation) return;
    volatile unsigned char *bytes = allocation;
    if (!wcscmp(mode, L"guard-fault")) { bytes[0] = 1; return; }
    CHECK(bytes[0x10000] == 0);
    if (!wcscmp(mode, L"execute-fault")) {
        bytes[0x10000] = 0xc3;
        ((void (*)(void))(uintptr_t)(bytes + 0x10000))();
        return;
    }
    bytes[size - 1] = 45;
    CHECK(bytes[size - 1] == 45);
    CHECK(!bdsp_win32_commit(allocation, 1));
    CHECK(!bdsp_win32_commit((void *)((uintptr_t)allocation + size), 1));
    CHECK(!bdsp_win32_commit((void *)(uintptr_t)UINTPTR_MAX, 2));
    CHECK(!bdsp_win32_discard((void *)(bytes + 0x10001), 4096));
    CHECK(bdsp_win32_protect((void *)(bytes + 0x10000), 4096, BDSP_MEMORY_READ));
    MEMORY_BASIC_INFORMATION info;
    CHECK(VirtualQuery((void *)(bytes + 0x10000), &info, sizeof info) == sizeof info);
    CHECK(info.Protect == PAGE_READONLY);
    if (!wcscmp(mode, L"readonly-fault")) { bytes[0x10000] = 1; return; }
    CHECK(bdsp_win32_protect((void *)(bytes + 0x10000), 4096, BDSP_MEMORY_NONE));
    if (!wcscmp(mode, L"noaccess-fault")) { bytes[0x10000] = 1; return; }
    CHECK(bdsp_win32_protect((void *)(bytes + 0x10000), 4096, BDSP_MEMORY_READ_WRITE));
    bytes[0x10000] = 18;
    CHECK(bdsp_win32_discard((void *)(bytes + 0x10000), 4096));
    CHECK(bytes[0x10000] == 0);
    CHECK(bdsp_win32_release());
    CHECK(VirtualQuery(allocation, &info, sizeof info) == sizeof info);
    CHECK(info.State == MEM_FREE);
    void *again;
    CHECK(bdsp_win32_reserve(allocation, size, 0, &again));
    CHECK(again == allocation);
    CHECK(bdsp_win32_release());
    uint64_t start = bdsp_win32_now_ns();
    Sleep(5);
    CHECK(bdsp_win32_now_ns() > start);
    uint64_t current, peak;
    CHECK(bdsp_win32_memory_usage(&current, &peak));
    CHECK(current > 0 && peak >= current);
    void *low;
    uint64_t stack_size;
    bdsp_win32_current_stack(&low, &stack_size);
    CHECK((uintptr_t)&start >= (uintptr_t)low);
    CHECK((uintptr_t)&start - (uintptr_t)low < stack_size);
    uint64_t resident;
    CHECK(bdsp_win32_resident_bytes(low, stack_size, &resident));
    CHECK(resident > 0 && resident <= stack_size);
}

static void test_gpu_memory(void) {
    void *allocation = NULL;
    const size_t size = 8u << 20, offset = 2u << 20, shared = 4u << 20;
    CHECK(!bdsp_win32_reserve_gpu(NULL, size, 0x10000, 0, shared, &allocation));
    CHECK(!bdsp_win32_reserve_gpu(NULL, size, 0, offset + 1, shared, &allocation));
    CHECK(!bdsp_win32_reserve_gpu(NULL, size, 0, offset, size, &allocation));
    CHECK(bdsp_win32_reserve_gpu(NULL, size, 0x10000, offset, shared, &allocation));
    if (!allocation) return;
    volatile unsigned char *bytes = allocation;
    MEMORY_BASIC_INFORMATION info;
    CHECK(VirtualQuery((void *)(bytes + offset), &info, sizeof info) == sizeof info);
    CHECK(info.Type == MEM_MAPPED && info.State == MEM_COMMIT);
    CHECK(info.AllocationBase == (void *)(bytes + offset));
    CHECK(VirtualQuery((void *)(bytes + 0x10000), &info, sizeof info) == sizeof info);
    CHECK(info.Type == MEM_PRIVATE && info.State == MEM_RESERVE);
    CHECK(bytes[0x10000] == 0 && bytes[offset] == 0 && bytes[size - 1] == 0);
    bytes[0x10000] = 3;
    bytes[size - 1] = 5;
    CHECK(bdsp_win32_commit((void *)(bytes + offset - 4096), 8192));
    bytes[offset - 1] = 7;
    bytes[offset] = 11;
    CHECK(bdsp_win32_protect((void *)(bytes + offset - 4096), 8192, BDSP_MEMORY_READ));
    CHECK(bdsp_win32_protect((void *)(bytes + offset - 4096), 8192, BDSP_MEMORY_READ_WRITE));
    CHECK(bdsp_win32_discard((void *)(bytes + offset - 4096), 8192));
    CHECK(bytes[offset - 1] == 0 && bytes[offset] == 0);
    CHECK(bdsp_win32_discard((void *)(bytes + offset + shared - 4096), 8192));
    CHECK(bdsp_win32_protect((void *)(bytes + offset), 4096, BDSP_MEMORY_NONE));
    CHECK(bdsp_win32_discard((void *)(bytes + offset), 4096));
    CHECK(bytes[offset] == 0 && bytes[0x10000] == 3 && bytes[size - 1] == 5);
    CHECK(!bdsp_win32_discard((void *)(bytes + offset + 1), 4096));
    CHECK(bdsp_win32_release());
    CHECK(VirtualQuery((void *)(bytes + offset), &info, sizeof info) == sizeof info);
    CHECK(info.State == MEM_FREE);
    CHECK(bdsp_win32_reserve_gpu(allocation, size, 0, offset, shared, &allocation));
    CHECK(bdsp_win32_release());
}

int wmain(int argc, wchar_t **argv) {
    SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX);
    if (argc == 2 && !wcsncmp(argv[1], L"--", 2)) {
        if (!wcscmp(argv[1], L"--gpu-memory")) test_gpu_memory();
        else test_memory(argv[1] + 2);
    } else if (argc == 2) {
        void *base;
        CHECK(bdsp_win32_reserve((void *)(uintptr_t)GUEST_LO, GUEST_HI - GUEST_LO, 0, &base));
        int length = WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, argv[1], -1, NULL, 0, NULL, NULL);
        CHECK(length > 0);
        char *path = malloc((size_t)length);
        CHECK(path != NULL);
        if (!path) return 2;
        CHECK(WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, argv[1], -1, path, length, NULL, NULL));
        loader_load(path);
        CHECK(g_nmodules == 3 && regions == 9 && slots == 1);
        CHECK(*G2H8(MAIN_BASE) == 0x41 && *G2H8(SDK_BASE) == 0x42 && *G2H8(SUBSDK0_BASE) == 0x43);
        CHECK(loader_find_symbol("synthetic_symbol") == MAIN_BASE);
        CHECK(bdsp_win32_release());
        free(path);
    } else return 2;
    return failures != 0;
}
