// Memory model of the BDSP runtime: the one place that converts guest addresses to host addresses.
// Own code.
//
// Guest address == host address in every build: a fixed 12.5 GiB window at 0x70_0000_0000 on Mac and Linux (variant A), the compact
// 4 GiB layout at a fixed host address on iPhone and iPad (variant A-low, -DBDSP_COMPACT_BASE).
//   G2H(a) = (void *)a, H2G(p) = (uint64_t)p. The generated code accesses memory through LD8..ST64 (cpu.h): directly.
//
// Rule for all host sources: every guest address (register, IPC buffer, table in guest memory) goes through G2H(),
// every pointer into guest memory that is returned to the guest goes through H2G(). No conversion to uintptr_t
// outside this header.
#pragma once
#include <stdint.h>

#define G2H(a) ((void *)(uintptr_t)(a))
#define H2G(p) ((uint64_t)(uintptr_t)(p))

#define G2H8(a)  ((uint8_t *)G2H(a))
#define G2H16(a) ((uint16_t *)G2H(a))
#define G2H32(a) ((uint32_t *)G2H(a))
#define G2H64(a) ((uint64_t *)G2H(a))
#define G2HC(a)  ((const char *)G2H(a))
