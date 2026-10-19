// Ersatz für runtime/rt.h des LAS-Klons beim Bau der NVN-Schicht (prepare.sh legt ihn neben die kopierten Quellen).
// Nur das, was objects.c, cmdbuf.c, renderer.m, metal.m brauchen; Adressraum und Heap kommen aus der BDSP-Laufzeit.
#pragma once
#include <pthread.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>

#include "cpu.h"
#include "platform.h"

#define LOG(...) fprintf(stderr, __VA_ARGS__)
#define FATAL(...) (fprintf(stderr, "FATAL: " __VA_ARGS__), nvn_fatal())

// Der Speicherbereich, in dem NVN-Speicherpools liegen (BDSP: der per MapPhysicalMemory belegte Anwendungsspeicher):
// ein einziger Metal-Puffer deckt ihn ab, GPU-Adressen sind Gastadressen. Gesetzt in nvn_glue.m.
extern uint64_t g_nvn_mem_base, g_nvn_mem_size;
#define HEAP_BASE g_nvn_mem_base
#define HEAP_MAX g_nvn_mem_size

typedef void (*HostFn)(Cpu *c);
uint64_t hle_register(const char *name, HostFn fn);
HostFn hle_lookup_impl(const char *name);
void rt_fatal_trace(void);
void nvn_fatal(void) __attribute__((noreturn));   // Bericht und Prozessende (nvn_glue.c)
void guest_call(Cpu *c, uint64_t addr);
void *hle_alloc(uint64_t size);
void rt_window_icon(void *sdl_window);
int rt_reboot_requested(void);
