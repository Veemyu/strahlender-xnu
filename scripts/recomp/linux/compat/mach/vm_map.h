// Linux replacement for <mach/vm_map.h> (see mach/mach.h): vm_region_64 via mach_vm_region (mincore).
#pragma once
#include <mach/mach_vm.h>

typedef uint64_t vm_address_t;
typedef uint64_t vm_size_t;

static inline kern_return_t vm_region_64(mach_port_t t, vm_address_t *a, vm_size_t *size, int flavor, vm_region_info_t info,
                                         mach_msg_type_number_t *cnt, mach_port_t *obj) {
    mach_vm_address_t aa = *a;
    mach_vm_size_t sz = 0;
    kern_return_t r = mach_vm_region(t, &aa, &sz, flavor, info, cnt, obj);
    *a = aa; *size = sz;
    return r;
}
