/* SPDX-License-Identifier: MIT
 * C port of LASRecomp lifter.py immediate/control families plus our EH returns.
 * Further families report CG_PENDING, never a fabricated supported instruction. */
#include "lifter.h"
#include <inttypes.h>
#include <string.h>

static unsigned bits(uint32_t w, unsigned lo, unsigned width) { return (w >> lo) & ((1u << width) - 1); }
static uint64_t ones(unsigned width) { return width == 64 ? UINT64_MAX : (UINT64_C(1) << width) - 1; }
static int64_t sext(uint64_t value, unsigned width) { return (int64_t)value - ((value & (UINT64_C(1) << (width - 1))) ? (INT64_C(1) << width) : 0); }
static const char *hex(uint64_t value) { return cg_format("0x%" PRIx64 "ull", value); }
static const char *reg(bool sf, unsigned r, bool sp) {
    if (r == 31) return sp ? (sf ? "c->sp" : "(uint32_t)c->sp") : (sf ? "0ull" : "0u");
    return cg_format("%sc->x[%u]", sf ? "" : "(uint32_t)", r);
}
static const char *set(bool sf, unsigned r, const char *expression, bool sp) {
    if (r == 31 && !sp) return cg_format("(void)(%s);", expression);
    return cg_format("%s = (uint%u_t)(%s);", reg(true, r, true), sf ? 64u : 32u, expression);
}
static Instruction op(const char *code) { return (Instruction){.kind = CG_OP, .code = code}; }
static Instruction unsupported(uint64_t pc, const char *reason) { return (Instruction){.kind = CG_TRAP, .code = cg_format("rt_udf(c, %s); /* %s */", hex(pc), reason)}; }
static Instruction target(InsnKind kind, uint64_t pc, int64_t delta, bool wrap, const char *condition) {
    Instruction ins = {.kind = kind, .numeric_target = true, .condition = condition};
    uint64_t magnitude = delta < 0 ? (uint64_t)(-delta) : 0;
    if (!wrap && delta < 0 && pc < magnitude) { ins.negative_target = true; ins.target = magnitude - pc; }
    else ins.target = pc + (uint64_t)delta;
    return ins;
}
static uint64_t rotate(uint64_t value, unsigned amount, unsigned width) {
    amount %= width;
    if (!amount) return value & ones(width);
    return ((value >> amount) | (value << (width - amount))) & ones(width);
}
static uint64_t repeat(uint64_t value, unsigned width, unsigned size) {
    uint64_t result = 0;
    for (unsigned i = 0; i < size; i += width) result |= value << i;
    return result;
}
static bool masks(unsigned n, unsigned imms, unsigned immr, unsigned size, bool immediate, uint64_t *wmask, uint64_t *tmask) {
    unsigned x = (n << 6) | (~imms & 63), length = 0;
    if (x < 2) return false;
    while ((x >> (length + 1)) != 0) length++;
    unsigned levels = (1u << length) - 1;
    if (immediate && (imms & levels) == levels) return false;
    unsigned s = imms & levels, r = immr & levels, d = ((s - r) & 63) & levels;
    unsigned width = 1u << length;
    *wmask = repeat(rotate(ones(s + 1), r, width), width, size);
    *tmask = repeat(ones(d + 1), width, size);
    return true;
}
static Instruction immediate(uint32_t w, uint64_t pc) {
    unsigned family = bits(w, 23, 3), rd = bits(w, 0, 5), rn = bits(w, 5, 5);
    bool sf = bits(w, 31, 1) != 0; unsigned size = sf ? 64u : 32u;
    if (family <= 1) {
        int64_t delta = sext((bits(w, 5, 19) << 2) | bits(w, 29, 2), 21);
        uint64_t value = sf ? (pc & ~UINT64_C(0xfff)) + (uint64_t)(delta * 4096) : pc + (uint64_t)delta;
        return op(set(true, rd, hex(value), false));
    }
    if (family == 2) {
        bool subtract = bits(w, 30, 1) != 0, flags = bits(w, 29, 1) != 0;
        uint64_t value = (uint64_t)bits(w, 10, 12) << (bits(w, 22, 1) ? 12 : 0);
        const char *left = reg(sf, rn, true);
        if (flags) return op(set(sf, rd, cg_format("%s%u(c, %s, %s)", subtract ? "subs" : "adds", size, left, hex(value)), false));
        return op(set(sf, rd, cg_format("%s %s %s", left, subtract ? "-" : "+", hex(value)), true));
    }
    if (family == 4) {
        unsigned opc = bits(w, 29, 2), n = bits(w, 22, 1); uint64_t wm, tm;
        if (!sf && n) return unsupported(pc, "logical imm N=1 32-bit");
        if (!masks(n, bits(w, 10, 6), bits(w, 16, 6), size, true, &wm, &tm)) return unsupported(pc, "reserved bitmask");
        const char *a = reg(sf, rn, false);
        if (opc < 3) return op(set(sf, rd, cg_format("%s %s %s", a, (const char *const[]){"&", "|", "^"}[opc], hex(wm)), true));
        return op(set(sf, rd, cg_format("logic%u(c, %s & %s)", size, a, hex(wm)), false));
    }
    if (family == 5) {
        unsigned opc = bits(w, 29, 2), hw = bits(w, 21, 2);
        if (!sf && hw > 1) return unsupported(pc, "movw hw");
        uint64_t value = (uint64_t)bits(w, 5, 16) << (hw * 16);
        if (opc == 0) return op(set(sf, rd, hex(~value & ones(size)), false));
        if (opc == 2) return op(set(sf, rd, hex(value), false));
        if (opc == 3) return op(set(sf, rd, cg_format("(%s & %s) | %s", reg(true, rd, false), hex(~(UINT64_C(0xffff) << (hw * 16))), hex(value)), false));
        return unsupported(pc, "movw opc");
    }
    if (family == 6) {
        unsigned opc = bits(w, 29, 2), n = bits(w, 22, 1), immr = bits(w, 16, 6), imms = bits(w, 10, 6); uint64_t wm, tm;
        if (n != (unsigned)sf) return unsupported(pc, "bitfield N");
        if (!masks(n, imms, immr, size, false, &wm, &tm)) return unsupported(pc, "reserved bitmask");
        const char *src = reg(sf, rn, false), *rot = immr ? cg_format("ROR%u(%s, %u)", size, src, immr) : src;
        if (opc == 2) return op(set(sf, rd, cg_format("%s & %s", rot, hex(wm & tm)), false));
        if (opc == 0) {
            const char *top = cg_format("(uint%u_t)(-(int%u_t)((%s >> %u) & 1))", size, size, src, imms);
            return op(set(sf, rd, cg_format("(%s & %s) | (%s & %s)", top, hex(~tm & ones(size)), rot, hex(wm & tm)), false));
        }
        if (opc == 1) {
            const char *dst = reg(sf, rd, false);
            const char *bottom = cg_format("((%s & %s) | (%s & %s))", dst, hex(~wm & ones(size)), rot, hex(wm));
            return op(set(sf, rd, cg_format("(%s & %s) | (%s & %s)", dst, hex(~tm & ones(size)), bottom, hex(tm)), false));
        }
        return unsupported(pc, "bitfield opc");
    }
    if (family == 7) {
        unsigned rm = bits(w, 16, 5), lsb = bits(w, 10, 6);
        if (!lsb) return op(set(sf, rd, reg(sf, rm, false), false));
        return op(set(sf, rd, cg_format("(%s >> %u) | ((uint%u_t)%s << %d)", reg(sf, rm, false), lsb, size, reg(sf, rn, false), (int)size - (int)lsb), false));
    }
    return unsupported(pc, cg_format("dp_imm %08x", w));
}
static Instruction system_instruction(uint32_t w, uint64_t pc, bool portable) {
    bool load = bits(w, 21, 1) != 0;
    unsigned op0 = bits(w, 19, 2), op1 = bits(w, 16, 3), crn = bits(w, 12, 4), crm = bits(w, 8, 4), op2 = bits(w, 5, 3), rt = bits(w, 0, 5);
    if (!op0 && !load) {
        if (crn == 2 && op1 == 3 && rt == 31) return op("/* hint */");
        if (crn == 3 && op1 == 3 && rt == 31) return op(op2 == 2 ? "c->excl_addr = ~0ull;" : "__atomic_thread_fence(__ATOMIC_SEQ_CST);");
        return unsupported(pc, cg_format("pstate/system %08x", w));
    }
    if (op0 == 1) {
        if (!load && op1 == 3 && crn == 7 && crm == 4 && op2 == 1) return op(cg_format("memset((void*)(uintptr_t)(%s & ~63ull), 0, 64);", reg(true, rt, false)));
        return op("/* cache maintenance */");
    }
    const char *src = NULL, *format = NULL;
    if (op0 == 3 && op1 == 3) {
        if (load) {
            if (crn == 13 && !crm && op2 == 3) src = "c->tpidrro";
            else if (crn == 13 && !crm && op2 == 2) src = "c->tpidr";
            else if (crn == 14 && !crm && !op2) src = "19200000ull";
            else if (crn == 14 && !crm && (op2 == 1 || op2 == 2)) src = "rt_ticks()";
            else if (crn == 4 && crm == 2 && !op2) src = "c->nzcv";
            else if (crn == 4 && crm == 4 && !op2) src = portable ? "c->fpcr" : "rt_get_fpcr()";
            else if (crn == 4 && crm == 4 && op2 == 1) src = portable ? "c->fpsr" : "rt_get_fpsr()";
            else if (!crn && !crm && op2 == 7) src = "4ull";
            else if (!crn && !crm && op2 == 1) src = "0x8444c004ull";
        } else {
            if (crn == 13 && !crm && op2 == 2) format = "c->tpidr = %s;";
            else if (crn == 4 && crm == 2 && !op2) format = "c->nzcv = %s & 0xf0000000ull;";
            else if (crn == 4 && crm == 4 && !op2) format = portable ? "c->fpcr = %s & 0x7c00000ull;" : "rt_set_fpcr(%s);";
            else if (crn == 4 && crm == 4 && op2 == 1) format = portable ? "c->fpsr = %s & 0xf800009full;" : "rt_set_fpsr(%s);";
        }
    }
    if (src) return op(set(true, rt, src, false));
    if (format) return op(cg_format(format, reg(true, rt, false)));
    return unsupported(pc, cg_format("%s (%u, %u, %u, %u, %u)", load ? "mrs" : "msr", op0, op1, crn, crm, op2));
}
static Instruction control(uint32_t w, uint64_t pc, bool portable, bool has_previous, uint32_t previous) {
    const char *const names[] = {"EQ", "NE", "CS", "CC", "MI", "PL", "VS", "VC", "HI", "LS", "GE", "LT", "GT", "LE"};
    if (bits(w, 26, 5) == 5) return target(bits(w, 31, 1) ? CG_BL : CG_B, pc, sext(bits(w, 0, 26), 26) * 4, true, NULL);
    if (bits(w, 25, 7) == 0x2a && !bits(w, 4, 1)) {
        unsigned cond = bits(w, 0, 4);
        return target(cond >= 14 ? CG_B : CG_BCOND, pc, sext(bits(w, 5, 19), 19) * 4, false, cond >= 14 ? NULL : cg_format("COND_%s(c)", names[cond]));
    }
    if (bits(w, 25, 6) == 0x1a) return target(CG_BCOND, pc, sext(bits(w, 5, 19), 19) * 4, false, cg_format("%s %s 0", reg(bits(w, 31, 1) != 0, bits(w, 0, 5), false), bits(w, 24, 1) ? "!=" : "=="));
    if (bits(w, 25, 6) == 0x1b) return target(CG_BCOND, pc, sext(bits(w, 5, 14), 14) * 4, false, cg_format("((%s >> %u) & 1) %s 0", reg(true, bits(w, 0, 5), false), (bits(w, 31, 1) << 5) | bits(w, 19, 5), bits(w, 24, 1) ? "!=" : "=="));
    if (bits(w, 25, 7) == 0x6b) {
        unsigned opc = bits(w, 21, 4), rn = bits(w, 5, 5);
        if (bits(w, 16, 5) != 31 || bits(w, 10, 6) || bits(w, 0, 5)) return unsupported(pc, "branch reg variant");
        if (opc < 2) return (Instruction){.kind = opc ? CG_BLR : CG_BR, .target_expression = reg(true, rn, false)};
        if (opc == 2) {
            if (rn != 30) return (Instruction){.kind = CG_BR, .target_expression = cg_format("c->x[%u]", rn)};
            if (has_previous && (previous & 0xfffffc1f) == 0x9100001f) return (Instruction){.kind = CG_BR, .target_expression = "c->x[30]"};
            return (Instruction){.kind = CG_RET};
        }
        return unsupported(pc, "branch reg opc");
    }
    if (bits(w, 24, 8) == 0xd4) {
        unsigned opc = bits(w, 21, 3), ll = bits(w, 0, 5), value = bits(w, 5, 16);
        if (!opc && ll == 1) return op(cg_format("rt_svc(c, %u, %s);", value, hex(pc)));
        if (opc == 1 && !ll) return (Instruction){.kind = CG_TRAP, .code = cg_format("rt_brk(c, %u, %s);", value, hex(pc))};
        return unsupported(pc, "exception");
    }
    if (bits(w, 22, 10) == 0x354) return system_instruction(w, pc, portable);
    return unsupported(pc, cg_format("branch_sys %08x", w));
}
Instruction cg_lift_basic(uint32_t w, uint64_t pc, bool portable, bool has_previous, uint32_t previous) {
    unsigned op0 = bits(w, 25, 4);
    if ((op0 & 14) == 8) return immediate(w, pc);
    if ((op0 & 14) == 10) return control(w, pc, portable, has_previous, previous);
    if ((op0 & 5) == 4 || (op0 & 7) == 5 || (op0 & 7) == 7) return (Instruction){.kind = CG_PENDING};
    return (Instruction){.kind = CG_TRAP, .code = cg_format("rt_udf(c, %s);", hex(pc))};
}
