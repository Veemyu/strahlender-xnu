// Memory model B for the C SIMD path: 128-bit accesses via the guest base. See rt32/cpu.h.
#pragma once
#include_next "simd.h"
#undef LD128
#undef ST128
#define LD128(a) (*(const u128u *)G2H(a))
#define ST128(a, v) (*(u128u *)G2H(a) = (u128)(v))
