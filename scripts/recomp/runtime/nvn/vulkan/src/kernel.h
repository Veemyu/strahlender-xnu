// Replacement for runtime/kernel.h when building the Vulkan version: time (platform.h), guest calls (rt.h) and the size of the guest heap.
#pragma once
#include "rt.h"

uint64_t kernel_heap_size(void);  // bytes from HEAP_BASE that the guest set with SetHeapSize (kernel.c of the BDSP runtime)
