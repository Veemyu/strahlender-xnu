// Speichermodell B für den C-SIMD-Pfad: 128-Bit-Zugriffe über die Gastbasis. Siehe rt32/cpu.h.
#pragma once
#include_next "simd.h"
#undef LD128
#undef ST128
#define LD128(a) (*(const u128u *)G2H(a))
#define ST128(a, v) (*(u128u *)G2H(a) = (u128)(v))
