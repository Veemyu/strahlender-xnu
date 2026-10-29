#ifdef _WIN32
#include "win32_host.h"
#include <errno.h>
#include <limits.h>
#include <psapi.h>
#include <stdlib.h>
#include <string.h>

static void *guest_base, *fault_handler;
static size_t guest_size, guest_guard, page_size;
static void *private_parts[2], *mapped_base;
static HANDLE crash_log = INVALID_HANDLE_VALUE;

static bool range(void *address, size_t size) {
    uintptr_t start = (uintptr_t)address, base = (uintptr_t)guest_base;
    if (!guest_base || !size || start < base || start - base < guest_guard ||
        start - base >= guest_size || size > guest_size - (start - base)) {
        SetLastError(ERROR_INVALID_ADDRESS);
        return false;
    }
    return true;
}

static LONG CALLBACK guest_fault(EXCEPTION_POINTERS *exception) {
    EXCEPTION_RECORD *record = exception->ExceptionRecord;
    if (record->ExceptionCode != EXCEPTION_ACCESS_VIOLATION ||
        record->NumberParameters < 2 || record->ExceptionInformation[0] == 8)
        return EXCEPTION_CONTINUE_SEARCH;
    uintptr_t address = record->ExceptionInformation[1], base = (uintptr_t)guest_base;
    if (!guest_base || address < base || address - base < guest_guard ||
        address - base >= guest_size)
        return EXCEPTION_CONTINUE_SEARCH;
    MEMORY_BASIC_INFORMATION info;
    if (!VirtualQuery((void *)address, &info, sizeof info) ||
        (info.AllocationBase != private_parts[0] && info.AllocationBase != private_parts[1]) ||
        info.State != MEM_RESERVE)
        return EXCEPTION_CONTINUE_SEARCH;
    void *page = (void *)(address & ~(uintptr_t)(page_size - 1));
    if (VirtualAlloc(page, page_size, MEM_COMMIT, PAGE_READWRITE))
        return EXCEPTION_CONTINUE_EXECUTION;
    static const char message[] = "FATAL: Windows could not commit a guest memory page.\r\n";
    DWORD written;
    WriteFile(GetStdHandle(STD_ERROR_HANDLE), message, sizeof message - 1, &written, NULL);
    return EXCEPTION_CONTINUE_SEARCH;
}

static bool reserve_window(void *requested, size_t size, size_t guard,
                           size_t offset, size_t shared_size, void **base) {
    SYSTEM_INFO info;
    GetSystemInfo(&info);
    if (guest_base || !base || !size || size % info.dwPageSize ||
        guard >= size || guard % info.dwPageSize ||
        (shared_size && (offset < guard || offset >= size || shared_size > size - offset ||
                        offset % info.dwAllocationGranularity || shared_size % info.dwAllocationGranularity)) ||
        (requested && ((uintptr_t)requested % info.dwAllocationGranularity ||
                       size > UINTPTR_MAX - (uintptr_t)requested))) {
        SetLastError(ERROR_INVALID_PARAMETER);
        return false;
    }
    void *allocation = VirtualAlloc(requested, size, MEM_RESERVE, PAGE_READWRITE);
    if (!allocation) return false;
    if (requested && allocation != requested) {
        VirtualFree(allocation, 0, MEM_RELEASE);
        SetLastError(ERROR_INVALID_ADDRESS);
        return false;
    }
    HANDLE section = NULL;
    void *view = NULL, *prefix = allocation, *suffix = NULL;
    if (shared_size) {
        section = CreateFileMappingW(INVALID_HANDLE_VALUE, NULL, PAGE_READWRITE | SEC_COMMIT,
                                     (DWORD)((uint64_t)shared_size >> 32), (DWORD)shared_size, NULL);
        if (!section) {
            DWORD error = GetLastError();
            VirtualFree(allocation, 0, MEM_RELEASE);
            SetLastError(error);
            return false;
        }
        if (!VirtualFree(allocation, 0, MEM_RELEASE)) {
            DWORD error = GetLastError();
            CloseHandle(section);
            SetLastError(error);
            return false;
        }
        prefix = NULL;
        view = MapViewOfFileEx(section, FILE_MAP_ALL_ACCESS, 0, 0, shared_size,
                               (unsigned char *)allocation + offset);
        DWORD error = GetLastError();
        CloseHandle(section);
        if (view) {
            if (offset) prefix = VirtualAlloc(allocation, offset, MEM_RESERVE, PAGE_READWRITE);
            if (offset && !prefix) error = GetLastError();
            size_t remaining = size - offset - shared_size;
            if ((!offset || prefix) && remaining) {
                suffix = VirtualAlloc((unsigned char *)allocation + offset + shared_size,
                                      remaining, MEM_RESERVE, PAGE_READWRITE);
                if (!suffix) error = GetLastError();
            }
            if ((!offset || prefix) && (!remaining || suffix)) goto mapped_ready;
        }
        if (view) UnmapViewOfFile(view);
        if (prefix) VirtualFree(prefix, 0, MEM_RELEASE);
        if (suffix) VirtualFree(suffix, 0, MEM_RELEASE);
        SetLastError(error);
        return false;
    }
mapped_ready:
    guest_base = allocation;
    guest_size = size;
    guest_guard = guard;
    page_size = info.dwPageSize;
    private_parts[0] = prefix;
    private_parts[1] = suffix;
    mapped_base = view;
    fault_handler = AddVectoredExceptionHandler(1, guest_fault);
    if (!fault_handler) {
        DWORD error = GetLastError();
        if (view) UnmapViewOfFile(view);
        if (prefix) VirtualFree(prefix, 0, MEM_RELEASE);
        if (suffix) VirtualFree(suffix, 0, MEM_RELEASE);
        guest_base = NULL;
        private_parts[0] = private_parts[1] = mapped_base = NULL;
        SetLastError(error);
        return false;
    }
    *base = allocation;
    return true;
}

bool bdsp_win32_reserve(void *requested, size_t size, size_t guard, void **base) {
    return reserve_window(requested, size, guard, 0, 0, base);
}

bool bdsp_win32_reserve_gpu(void *requested, size_t size, size_t guard,
                            size_t offset, size_t size_mapped, void **base) {
    if (!size_mapped) { SetLastError(ERROR_INVALID_PARAMETER); return false; }
    return reserve_window(requested, size, guard, offset, size_mapped, base);
}

bool bdsp_win32_commit(void *address, size_t size) {
    if (!range(address, size)) return false;
    uintptr_t current = (uintptr_t)address, end = current + size;
    while (current < end) {
        MEMORY_BASIC_INFORMATION info;
        if (!VirtualQuery((void *)current, &info, sizeof info)) return false;
        uintptr_t next = (uintptr_t)info.BaseAddress + info.RegionSize;
        if (next > end) next = end;
        if (info.AllocationBase != mapped_base &&
            !VirtualAlloc((void *)current, next - current, MEM_COMMIT, PAGE_READWRITE))
            return false;
        current = next;
    }
    return true;
}

bool bdsp_win32_prepare_write(void *address, size_t size) {
    uintptr_t start = (uintptr_t)address, base = (uintptr_t)guest_base;
    if (size > UINTPTR_MAX - start) { SetLastError(ERROR_INVALID_PARAMETER); return false; }
    if (!size || !guest_base || start >= base + guest_size || start + size <= base)
        return true;
    return bdsp_win32_commit(address, size);
}

bool bdsp_win32_protect(void *address, size_t size, BdspMemoryAccess access) {
    DWORD protection;
    switch (access) {
    case BDSP_MEMORY_NONE: protection = PAGE_NOACCESS; break;
    case BDSP_MEMORY_READ: protection = PAGE_READONLY; break;
    case BDSP_MEMORY_READ_WRITE: protection = PAGE_READWRITE; break;
    default: SetLastError(ERROR_INVALID_PARAMETER); return false;
    }
    if (!bdsp_win32_commit(address, size)) return false;
    uintptr_t current = (uintptr_t)address, end = current + size;
    while (current < end) {
        MEMORY_BASIC_INFORMATION info;
        if (!VirtualQuery((void *)current, &info, sizeof info)) return false;
        uintptr_t next = (uintptr_t)info.BaseAddress + info.RegionSize;
        if (next > end) next = end;
        DWORD previous;
        if (!VirtualProtect((void *)current, next - current, protection, &previous)) return false;
        current = next;
    }
    return true;
}

bool bdsp_win32_discard(void *address, size_t size) {
    if (!range(address, size)) return false;
    if ((uintptr_t)address % page_size || size % page_size) {
        SetLastError(ERROR_INVALID_PARAMETER);
        return false;
    }
    uintptr_t current = (uintptr_t)address, end = current + size;
    while (current < end) {
        MEMORY_BASIC_INFORMATION info;
        if (!VirtualQuery((void *)current, &info, sizeof info)) return false;
        uintptr_t next = (uintptr_t)info.BaseAddress + info.RegionSize;
        if (next > end) next = end;
        if (mapped_base && info.AllocationBase == mapped_base) {
            // GPU imports retain this section's backing: keep its address and zero it on unmap.
            DWORD previous;
            if (!VirtualProtect((void *)current, next - current, PAGE_READWRITE, &previous)) return false;
            memset((void *)current, 0, next - current);
        } else if (!VirtualFree((void *)current, next - current, MEM_DECOMMIT)) {
            return false;
        }
        current = next;
    }
    return true;
}

bool bdsp_win32_release(void) {
    if (!guest_base) {
        SetLastError(ERROR_INVALID_STATE);
        return false;
    }
    if (mapped_base) {
        if (!UnmapViewOfFile(mapped_base)) return false;
        mapped_base = NULL;
    }
    for (size_t i = 0; i < 2; i++) {
        if (private_parts[i]) {
            if (!VirtualFree(private_parts[i], 0, MEM_RELEASE)) return false;
            private_parts[i] = NULL;
        }
    }
    guest_base = NULL;
    if (!RemoveVectoredExceptionHandler(fault_handler)) {
        SetLastError(ERROR_INVALID_FUNCTION);
        return false;
    }
    fault_handler = NULL;
    return true;
}

static INIT_ONCE clock_once = INIT_ONCE_STATIC_INIT;
static LARGE_INTEGER frequency;
static BOOL CALLBACK clock_init(PINIT_ONCE once, PVOID parameter, PVOID *context) {
    (void)once; (void)parameter; (void)context;
    return QueryPerformanceFrequency(&frequency) && frequency.QuadPart > 0;
}

uint64_t bdsp_win32_now_ns(void) {
    LARGE_INTEGER now;
    if (!InitOnceExecuteOnce(&clock_once, clock_init, NULL, NULL) ||
        !QueryPerformanceCounter(&now) || now.QuadPart < 0) {
        fprintf(stderr, "FATAL: Windows monotonic clock failed (%lu).\n", GetLastError());
        ExitProcess(1);
    }
    return (uint64_t)((unsigned __int128)(uint64_t)now.QuadPart * 1000000000ull /
                      (uint64_t)frequency.QuadPart);
}

bool bdsp_win32_memory_usage(uint64_t *current, uint64_t *peak) {
    PROCESS_MEMORY_COUNTERS info = {.cb = sizeof info};
    if (!GetProcessMemoryInfo(GetCurrentProcess(), &info, sizeof info)) return false;
    *current = info.WorkingSetSize;
    *peak = info.PeakWorkingSetSize;
    return true;
}

void bdsp_win32_current_stack(void **low, uint64_t *size) {
    ULONG_PTR bottom, top;
    GetCurrentThreadStackLimits(&bottom, &top);
    MEMORY_BASIC_INFORMATION info;
    if (!VirtualQuery(&bottom, &info, sizeof info)) {
        fprintf(stderr, "FATAL: Windows stack bounds query failed (%lu).\n", GetLastError());
        ExitProcess(1);
    }
    bottom = (ULONG_PTR)info.AllocationBase;
    *low = info.AllocationBase;
    *size = top - bottom;
}

bool bdsp_win32_resident_bytes(void *address, size_t size, uint64_t *resident) {
    SYSTEM_INFO system;
    GetSystemInfo(&system);
    uintptr_t start = (uintptr_t)address;
    if (!resident || start % system.dwPageSize || size % system.dwPageSize ||
        size > UINTPTR_MAX - start) {
        SetLastError(ERROR_INVALID_PARAMETER);
        return false;
    }
    uint64_t total = 0;
    while (size) {
        PSAPI_WORKING_SET_EX_INFORMATION pages[128] = {0};
        size_t count = size / system.dwPageSize;
        if (count > 128) count = 128;
        for (size_t i = 0; i < count; i++)
            pages[i].VirtualAddress = (void *)(start + i * system.dwPageSize);
        if (!QueryWorkingSetEx(GetCurrentProcess(), pages, (DWORD)(count * sizeof *pages)))
            return false;
        for (size_t i = 0; i < count; i++)
            if (pages[i].VirtualAttributes.Valid) total += system.dwPageSize;
        size_t bytes = count * system.dwPageSize;
        start += bytes;
        size -= bytes;
    }
    *resident = total;
    return true;
}

wchar_t *bdsp_win32_widen(const char *path) {
    int length = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, path, -1, NULL, 0);
    if (!length) { errno = EILSEQ; return NULL; }
    wchar_t *wide = malloc((size_t)length * sizeof *wide);
    if (!wide) { errno = ENOMEM; return NULL; }
    if (!MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, path, -1, wide, length)) {
        free(wide); errno = EILSEQ; return NULL;
    }
    return wide;
}

char *bdsp_win32_utf8(const wchar_t *wide) {
    int length = WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, wide, -1, NULL, 0, NULL, NULL);
    if (!length) { errno = EILSEQ; return NULL; }
    char *value = malloc((size_t)length);
    if (!value) { errno = ENOMEM; return NULL; }
    if (!WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, wide, -1, value, length, NULL, NULL)) {
        free(value); errno = EILSEQ; return NULL;
    }
    return value;
}

FILE *bdsp_win32_fopen(const char *path, const char *mode) {
    wchar_t *wide = bdsp_win32_widen(path);
    if (!wide) return NULL;
    wchar_t wide_mode[16];
    size_t i;
    for (i = 0; mode[i] && i < 15; i++) wide_mode[i] = (unsigned char)mode[i];
    if (mode[i]) { free(wide); errno = EINVAL; return NULL; }
    wide_mode[i] = 0;
    FILE *file = _wfopen(wide, wide_mode);
    int error = errno;
    free(wide);
    errno = error;
    return file;
}

bool bdsp_win32_crash_open(const char *directory) {
    size_t capacity = strlen(directory) + sizeof "\\crash.log";
    char *path = malloc(capacity);
    if (!path) { SetLastError(ERROR_OUTOFMEMORY); return false; }
    snprintf(path, capacity, "%s\\crash.log", directory);
    wchar_t *wide = bdsp_win32_widen(path);
    free(path);
    if (!wide) {
        SetLastError(errno == ENOMEM ? ERROR_OUTOFMEMORY : ERROR_NO_UNICODE_TRANSLATION);
        return false;
    }
    HANDLE file = CreateFileW(wide, FILE_APPEND_DATA | SYNCHRONIZE,
                              FILE_SHARE_READ | FILE_SHARE_WRITE, NULL, OPEN_ALWAYS,
                              FILE_ATTRIBUTE_NORMAL | FILE_FLAG_WRITE_THROUGH, NULL);
    DWORD error = GetLastError();
    free(wide);
    if (file == INVALID_HANDLE_VALUE) { SetLastError(error); return false; }
    if (crash_log != INVALID_HANDLE_VALUE) CloseHandle(crash_log);
    crash_log = file;
    return true;
}

bool bdsp_win32_crash_write(const char *message, DWORD length) {
    DWORD written;
    return crash_log != INVALID_HANDLE_VALUE &&
           WriteFile(crash_log, message, length, &written, NULL) && written == length;
}
#endif
