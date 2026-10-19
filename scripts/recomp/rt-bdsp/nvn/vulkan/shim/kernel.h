// Ersatz für runtime/kernel.h beim Bau der Vulkan-Fassung: Zeit (platform.h), Gastaufrufe (rt.h) und die Größe des Gast-Heaps.
#pragma once
#include "rt.h"

uint64_t kernel_heap_size(void);  // Bytes ab HEAP_BASE, die der Gast mit SetHeapSize gesetzt hat (kernel.c der BDSP-Laufzeit)
