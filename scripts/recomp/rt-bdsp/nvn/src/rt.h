// Replacement for runtime/rt.h of the LAS clone when building the NVN layer (prepare.sh puts it next to the copied sources).
// Only what objects.c, cmdbuf.c, renderer.m, metal.m need; address space and heap come from the BDSP runtime.
#pragma once
#include <pthread.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>

#include "cpu.h"
#include "platform.h"

#define LOG(...) fprintf(stderr, __VA_ARGS__)
#define FATAL(...) (fprintf(stderr, "FATAL: " __VA_ARGS__), nvn_fatal())

// The memory range that holds the NVN memory pools (BDSP: the application memory mapped via MapPhysicalMemory):
// a single Metal buffer covers it, GPU addresses are guest addresses. Set in nvn_glue.m.
extern uint64_t g_nvn_mem_base, g_nvn_mem_size;
#define HEAP_BASE g_nvn_mem_base
#define HEAP_MAX g_nvn_mem_size

typedef void (*HostFn)(Cpu *c);
uint64_t hle_register(const char *name, HostFn fn);
HostFn hle_lookup_impl(const char *name);
void rt_fatal_trace(void);
void nvn_fatal(void) __attribute__((noreturn));   // report and process exit (nvn_glue.c)
void guest_call(Cpu *c, uint64_t addr);
void *hle_alloc(uint64_t size);
void rt_window_icon(void *sdl_window);
int rt_reboot_requested(void);
