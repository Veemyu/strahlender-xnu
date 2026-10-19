// Ersatz für runtime/platform.h beim Bau der Vulkan-Fassung (überlagert nvn/shim/platform.h): Zeit, Schreibverfolgung, Beenden.
#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

uint64_t plat_now_ns(void);
void plat_sleep_until_ns(uint64_t t);
// Seiten, die seit der letzten Abfrage beschrieben wurden; -1: keine Schreibverfolgung (vk_glue.c: immer -1, Vertex- und
// Textur-Zwischenspeicher prüfen dann bei jeder Verwendung neu)
int plat_written_pages(uint64_t addr, uint64_t size, uint64_t *pages, int max, uint64_t *page);
void plat_terminate(void);
