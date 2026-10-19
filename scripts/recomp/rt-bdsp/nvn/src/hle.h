// Ersatz für runtime/hle.h des LAS-Klons: HLE_FUNC bindet eine Host-Funktion in einem Mach-O-Abschnitt an einen Namen;
// hle_lookup_impl (nvn_glue.m) durchsucht ihn. Entwurf wie im Original (MIT, siehe NOTICE.md).
#pragma once
#include <stdlib.h>

#include "rt.h"

typedef struct { const char *name; HostFn fn; } HleImplEntry;

#define ENV(name) ({ static const char *env_v_; static int env_i_; if (!env_i_) { env_v_ = getenv(name); env_i_ = 1; } env_v_; })
#define HLE_CAT2(a, b) a##b
#define HLE_CAT(a, b) HLE_CAT2(a, b)
#ifdef __APPLE__
#define HLE_SECTION "__DATA,__hle_impls"
#else
#define HLE_SECTION "hle_impls"   // ELF (Linux): der Linker liefert __start_hle_impls / __stop_hle_impls
#endif
#define HLE_FUNC(sym, fn)                                                                   \
    static void fn(Cpu *c);                                                                 \
    __attribute__((used, section(HLE_SECTION))) static const HleImplEntry                   \
        HLE_CAT(hle_entry_, __LINE__) = {sym, fn};                                          \
    static void fn(Cpu *c)

#define RES_OK 0u
// Neustart im Prozess gibt es hier nicht: die Rücksetz-Funktionen des Klons bleiben ungenutzt.
#define RT_ON_RESET(fn) static void fn(void) __attribute__((unused)); static void fn(void)
#define MAKE_RESULT(module, desc) ((uint32_t)(module) | ((uint32_t)(desc) << 9))
