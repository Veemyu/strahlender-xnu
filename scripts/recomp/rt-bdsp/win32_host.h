#pragma once
#ifdef _WIN32
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <windows.h>

typedef enum {
    BDSP_MEMORY_NONE,
    BDSP_MEMORY_READ,
    BDSP_MEMORY_READ_WRITE
} BdspMemoryAccess;

// One process-owned window. Release only after all guest threads have stopped.
bool bdsp_win32_reserve(void *requested, size_t size, size_t guard, void **base);
// The GPU-importable subrange uses a committed pagefile section, not MEM_PRIVATE.
bool bdsp_win32_reserve_gpu(void *requested, size_t size, size_t guard,
                            size_t mapped_offset, size_t mapped_size, void **base);
bool bdsp_win32_commit(void *address, size_t size);
bool bdsp_win32_prepare_write(void *address, size_t size);
bool bdsp_win32_protect(void *address, size_t size, BdspMemoryAccess access);
bool bdsp_win32_discard(void *address, size_t size);
bool bdsp_win32_release(void);
uint64_t bdsp_win32_now_ns(void);
bool bdsp_win32_memory_usage(uint64_t *current, uint64_t *peak);
bool bdsp_win32_resident_bytes(void *address, size_t size, uint64_t *resident);
void bdsp_win32_current_stack(void **low, uint64_t *size);
FILE *bdsp_win32_fopen(const char *path, const char *mode);
// Strict conversions return owned storage; the caller frees it.
wchar_t *bdsp_win32_widen(const char *utf8);
char *bdsp_win32_utf8(const wchar_t *wide);
bool bdsp_win32_crash_open(const char *directory);
bool bdsp_win32_crash_write(const char *message, DWORD length);
#endif
