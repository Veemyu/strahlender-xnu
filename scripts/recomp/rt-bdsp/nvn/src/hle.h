// HLE_FUNC binds a host function to a name in a platform linker section;
// hle_lookup_impl (nvn_glue.c) searches it. Design as in the original (MIT, see NOTICE.md).
#pragma once
#include <stdlib.h>

#include "rt.h"

typedef struct { const char *name; HostFn fn; } HleImplEntry;

#define ENV(name) ({ static const char *env_v_; static int env_i_; if (!env_i_) { env_v_ = getenv(name); env_i_ = 1; } env_v_; })
#define HLE_CAT2(a, b) a##b
#define HLE_CAT(a, b) HLE_CAT2(a, b)
#ifdef __APPLE__
#define HLE_SECTION "__DATA,__hle_impls"
#elif defined(_WIN32)
#define HLE_SECTION ".hle$m"
extern const HleImplEntry bdsp_hle_begin[], bdsp_hle_end[];
#else
#define HLE_SECTION "hle_impls"   // ELF (Linux): the linker provides __start_hle_impls / __stop_hle_impls
#endif
#define HLE_FUNC(sym, fn)                                                                   \
    static void fn(Cpu *c);                                                                 \
    __attribute__((used, section(HLE_SECTION))) static const HleImplEntry                   \
        HLE_CAT(hle_entry_, __LINE__) = {sym, fn};                                          \
    static void fn(Cpu *c)

#define RES_OK 0u
// There is no in-process restart here: the clone's reset functions stay unused.
#define RT_ON_RESET(fn) static void fn(void) __attribute__((unused)); static void fn(void)
#define MAKE_RESULT(module, desc) ((uint32_t)(module) | ((uint32_t)(desc) << 9))
