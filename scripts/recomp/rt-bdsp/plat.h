// Platform helpers of the runtime: one interface, written once; the few OS differences sit inside plat.c.
// Call these instead of repeating #ifdef _WIN32 around setenv/arc4random/mkdir/rename.
#pragma once
#include <stdbool.h>
#include <stddef.h>

// Fills the buffer from the operating system's secure random source.
bool plat_random(void *buffer, size_t size);
// Sets an environment variable; with overwrite == false an existing value is kept.
bool plat_setenv(const char *name, const char *value, bool overwrite);
// Creates one directory level (mode 0700); an already existing directory counts as success.
bool plat_ensure_directory(const char *path);
// Writes the whole file through a temporary neighbour (write, fsync, rename), so a reader never sees a partial file.
bool plat_write_file_atomic(const char *path, const void *data, size_t size);
