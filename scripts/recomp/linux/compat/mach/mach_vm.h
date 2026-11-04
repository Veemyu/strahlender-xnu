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
#define vm_page_size compat_page_size()

static inline kern_return_t mach_vm_allocate(mach_port_t t, mach_vm_address_t *a, mach_vm_size_t size, int flags) {
    (void)t; (void)flags;
    void *p = mmap((void *)(uintptr_t)*a, size, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANON | MAP_NORESERVE | MAP_FIXED_NOREPLACE, -1, 0);
    return p == (void *)(uintptr_t)*a ? KERN_SUCCESS : KERN_FAILURE;
}
static inline kern_return_t mach_vm_region(mach_port_t t, mach_vm_address_t *a, mach_vm_size_t *size, int flavor, vm_region_info_t info,
                                           mach_msg_type_number_t *cnt, mach_port_t *obj) {
    (void)t; (void)flavor; (void)cnt; (void)obj;
    vm_region_extended_info_data_t *i = (vm_region_extended_info_data_t *)info;
    uint64_t sz = 1ull << 20, pg = compat_page_size(), base = *a & ~(pg - 1);
    unsigned char vec[256];   // one byte per host page of the 1 MiB step (at most 256)
    if (mincore((void *)(uintptr_t)base, sz, vec) != 0) return KERN_FAILURE;
    uint32_t n = 0;
    for (uint64_t k = 0; k < sz / pg; k++) n += vec[k] & 1;
    i->pages_resident = n;
    *a = base; *size = sz;
    return KERN_SUCCESS;
}
