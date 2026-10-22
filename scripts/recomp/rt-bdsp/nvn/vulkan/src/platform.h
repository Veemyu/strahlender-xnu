// Replacement for runtime/platform.h when building the Vulkan version (overlays nvn/shim/platform.h): time, write tracking, terminate.
#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

uint64_t plat_now_ns(void);
void plat_sleep_until_ns(uint64_t t);
// Pages written since the last query; -1: no write tracking (vk_glue.c: always -1, the vertex and
// texture caches then re-check on every use)
int plat_written_pages(uint64_t addr, uint64_t size, uint64_t *pages, int max, uint64_t *page);
void plat_terminate(void);
