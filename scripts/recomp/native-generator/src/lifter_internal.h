/* SPDX-License-Identifier: MIT. Shared expression formatting for native lifters. */
#ifndef BDSP_LIFTER_INTERNAL_H
#define BDSP_LIFTER_INTERNAL_H
#include "lifter.h"
#include <inttypes.h>
static inline unsigned bits(uint32_t w, unsigned lo, unsigned width) { return (w >> lo) & ((1u << width) - 1); }
static inline uint64_t ones(unsigned width) { return width == 64 ? UINT64_MAX : (UINT64_C(1) << width) - 1; }
static inline int64_t sext(uint64_t value, unsigned width) { return (int64_t)value - ((value & (UINT64_C(1) << (width - 1))) ? (INT64_C(1) << width) : 0); }
static inline const char *hex(uint64_t value) { return cg_format("0x%" PRIx64 "ull", value); }
static inline const char *reg(bool sf, unsigned r, bool sp) {
    if (r == 31) return sp ? (sf ? "c->sp" : "(uint32_t)c->sp") : (sf ? "0ull" : "0u");
    return cg_format("%sc->x[%u]", sf ? "" : "(uint32_t)", r);
}
static inline const char *set(bool sf, unsigned r, const char *expression, bool sp) {
    if (r == 31 && !sp) return cg_format("(void)(%s);", expression);
    return cg_format("%s = (uint%u_t)(%s);", reg(true, r, true), sf ? 64u : 32u, expression);
}
static inline Instruction op(const char *code) { return (Instruction){.kind = CG_OP, .code = code}; }
static inline Instruction unsupported(uint64_t pc, const char *reason) { return (Instruction){.kind = CG_TRAP, .code = cg_format("rt_udf(c, %s); /* %s */", hex(pc), reason)}; }
static inline const char *extend(unsigned r, unsigned option, unsigned shift) {
    const char *value = reg(true, r, false);
    const char *formats[] = {"(uint64_t)(uint8_t)%s", "(uint64_t)(uint16_t)%s", "(uint64_t)(uint32_t)%s", "%s",
        "(uint64_t)(int64_t)(int8_t)%s", "(uint64_t)(int64_t)(int16_t)%s", "(uint64_t)(int64_t)(int32_t)%s", "%s"};
    const char *expression = cg_format(formats[option], value);
    return shift ? cg_format("(%s << %u)", expression, shift) : expression;
}
static inline const char *offset(const char *base, int64_t displacement) {
    return cg_format("%s %s %" PRIu64, base, displacement < 0 ? "-" : "+", (uint64_t)(displacement < 0 ? -displacement : displacement));
}
static inline const char *condition(unsigned cond) {
    const char *const names[] = {"EQ", "NE", "CS", "CC", "MI", "PL", "VS", "VC", "HI", "LS", "GE", "LT", "GT", "LE"};
    return cond >= 14 ? "1" : cg_format("COND_%s(c)", names[cond]);
}
static inline uint64_t fp_immediate(unsigned imm8, unsigned width) {
    unsigned exponent = width == 32 ? 8u : 11u, fraction = width - exponent - 1, b6 = (imm8 >> 6) & 1;
    uint64_t exp = ((uint64_t)(b6 ^ 1) << (exponent - 1)) | ((b6 ? ones(exponent - 3) : 0) << 2) | ((imm8 >> 4) & 3);
    return ((uint64_t)(imm8 >> 7) << (width - 1)) | (exp << fraction) | ((uint64_t)(imm8 & 15) << (fraction - 4));
}
Instruction cg_portable_vector(uint32_t word, uint64_t pc);
Instruction cg_portable_load_store(uint32_t word, uint64_t pc);
Instruction cg_portable_simd(uint32_t word, uint64_t pc);
#endif
