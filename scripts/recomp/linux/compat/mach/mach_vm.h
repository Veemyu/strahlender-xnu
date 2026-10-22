// Linux replacement for <mach/mach_vm.h> (see mach/mach.h): mach_vm_allocate (fixed range, only if free) and
// mach_vm_region (residency per 1 MiB step via mincore; only for runtime reports).
#pragma once
#include <mach/mach.h>
#include <stdlib.h>
#include <sys/mman.h>

typedef uint64_t mach_vm_address_t;
typedef uint64_t mach_vm_size_t;
typedef int *vm_region_info_t;
#define VM_FLAGS_FIXED 0
#define VM_REGION_EXTENDED_INFO 13
#define VM_REGION_EXTENDED_INFO_COUNT 9
typedef struct { uint32_t pages_resident; } vm_region_extended_info_data_t;
static const uint64_t vm_page_size = 4096;

static inline kern_return_t mach_vm_allocate(mach_port_t t, mach_vm_address_t *a, mach_vm_size_t size, int flags) {
    (void)t; (void)flags;
    void *p = mmap((void *)(uintptr_t)*a, size, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANON | MAP_NORESERVE | MAP_FIXED_NOREPLACE, -1, 0);
    return p == (void *)(uintptr_t)*a ? KERN_SUCCESS : KERN_FAILURE;
}
static inline kern_return_t mach_vm_region(mach_port_t t, mach_vm_address_t *a, mach_vm_size_t *size, int flavor, vm_region_info_t info,
                                           mach_msg_type_number_t *cnt, mach_port_t *obj) {
    (void)t; (void)flavor; (void)cnt; (void)obj;
    vm_region_extended_info_data_t *i = (vm_region_extended_info_data_t *)info;
    uint64_t sz = 1ull << 20, base = *a & ~4095ull;
    unsigned char vec[256];
    if (mincore((void *)(uintptr_t)base, sz, vec) != 0) return KERN_FAILURE;
    uint32_t n = 0;
    for (int k = 0; k < 256; k++) n += vec[k] & 1;
    i->pages_resident = n;
    *a = base; *size = sz;
    return KERN_SUCCESS;
}
