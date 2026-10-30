// Memory model of the BDSP runtime: the one place that converts guest addresses to host addresses.
// Own code.
//
// Variant A (gate 1, Mac only): a fixed 12.5 GiB window at 0x70_0000_0000, guest address == host address.
//   G2H(a) = (void *)a, H2G(p) = (uint64_t)p. The generated code accesses memory through LD8..ST64 (cpu.h): directly.
// Variant B (iPad, gate 2): all guest addresses < 4 GiB, one window at g_base.
//   G2H(a) = g_base + (uint32_t)a. The generated code is compiled with -I scripts/recomp/rt32 before rt/
//   (rt32/cpu.h overrides LD*/ST* with the same computation), the modules sit at addresses < 4 GiB
//   (gen_all.sh with other bases), and the runtime is built with -DBDSP_REBASE32.
//
// Rule for all host sources: every guest address (register, IPC buffer, table in guest memory) goes through G2H(),
// every pointer into guest memory that is returned to the guest goes through H2G(). No conversion to uintptr_t
// outside this header.
#pragma once
#include <stdint.h>

#ifdef BDSP_REBASE32
extern uint8_t *g_base;  // base of the 4 GiB window (same name as in rt32/cpu.h, set by the host)
#ifndef G2H
#define G2H(a) ((void *)(g_base + (uint32_t)(uint64_t)(a)))
#endif
#define H2G(p) ((uint64_t)((const uint8_t *)(p) - g_base))
#else
#define G2H(a) ((void *)(uintptr_t)(a))
#define H2G(p) ((uint64_t)(uintptr_t)(p))
#endif

#define G2H8(a)  ((uint8_t *)G2H(a))
#define G2H16(a) ((uint16_t *)G2H(a))
#define G2H32(a) ((uint32_t *)G2H(a))
#define G2H64(a) ((uint64_t *)G2H(a))
#define G2HC(a)  ((const char *)G2H(a))
