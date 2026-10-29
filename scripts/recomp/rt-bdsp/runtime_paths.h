#pragma once
#include <stdbool.h>
#include <stddef.h>

void bdsp_cache_path(char *out, size_t capacity, const char *relative);
bool bdsp_cache_prepare(const char *subdirectory);
// Pair=1, single=0, malformed/unreadable explicit configuration=-1.
int bdsp_joycon_mode(void);
#ifdef _WIN32
// Atomic store to the caller-selected configuration file; no environment changes.
bool bdsp_joycon_store(const char *path, int combine);
#endif
