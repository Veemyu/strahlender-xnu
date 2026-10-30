// Platform helpers of the runtime: one interface, written once; the few OS differences sit inside plat.c.
// Call these instead of repeating #ifdef _WIN32 around setenv/arc4random/mkdir/rename.
#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

// Fills the buffer from the operating system's secure random source.
bool plat_random(void *buffer, size_t size);
// Sets an environment variable; with overwrite == false an existing value is kept.
bool plat_setenv(const char *name, const char *value, bool overwrite);
// Creates one directory level (mode 0700); an already existing directory counts as success.
bool plat_ensure_directory(const char *path);
// Writes the whole file through a temporary neighbour (write, fsync, rename), so a reader never sees a partial file.
bool plat_write_file_atomic(const char *path, const void *data, size_t size);
// Monotonic clock in nanoseconds (does not count time spent asleep); the base of rt_now_ns().
uint64_t plat_now_ns(void);
// Sleeps until the given plat_now_ns() value.
void plat_sleep_until_ns(uint64_t t);

// Guest memory window. Windows reserves it and commits pages on demand; elsewhere the OS maps pages on first touch,
// so commit and prepare_write are no-ops there.
bool plat_memory_commit(void *address, size_t size);
// Makes the range writable before the host (not the guest) fills it, e.g. a read() into guest memory.
bool plat_memory_prepare_write(void *address, size_t size);
// Drops the contents of the range; it reads as zeros afterwards. POSIX: best effort, Windows: false on failure.
bool plat_memory_discard(void *address, size_t size);
