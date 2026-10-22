// Shared types of the differential test (docs/recomp-diff.md). Own code.
#pragma once
#include <stdint.h>

enum { T_BITS, T_F32, T_F64, T_F16, T_I8, T_I16, T_I32, T_I64 };
enum { DF_FPCR = 1, DF_AHP = 2, DF_FMACANCEL = 4, DF_MEM = 8 };

// Input of a case (384 bytes, fixed layout, read by tmpl.S): V0..V7, X0..X3, NZCV, FPCR, memory flag, 192 bytes
// of memory (with DF_MEM X1 points to mem+64)
typedef struct { uint8_t v[8][16]; uint64_t x[4]; uint64_t nzcv, fpcr, memflag, pad; uint8_t mem[192]; } Case;
// Result (240 bytes): V0, X0, NZCV, FPSR, X1 (with DF_MEM relative to the case start), memory afterwards
typedef struct { uint64_t v0[2]; uint64_t x0, nzcv, fpsr, x1; uint8_t mem[192]; } Out;
typedef struct { uint64_t seed; int8_t rt[8]; uint32_t flags; } Desc;

void gen_cases(const Desc *d, Case *out, int n);
