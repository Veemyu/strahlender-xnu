// Synthetic guest tables for linking and booting the unmodified active runtime.
#include "bdsp.h"

static void synthetic_guest(Cpu *cpu) {
    (void)cpu;
    if (getenv("BDSP_TEST_HOST_EXCEPTION"))
        RaiseException(0xe0424242, EXCEPTION_NONCONTINUABLE, 0, NULL);
    ExitProcess(23);
}

#define TABLE(name, address) \
    const uint64_t name##_fn_addrs[] = {address}; \
    const GuestFn name##_fn_ptrs[] = {synthetic_guest}; \
    const uint64_t name##_fn_count = 1
TABLE(main, MAIN_BASE);
TABLE(sdk, SDK_BASE);
TABLE(subsdk0, SUBSDK0_BASE);
TABLE(rtld, RTLD_BASE);
