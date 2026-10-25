/* SPDX-License-Identifier: MIT
 * C port of LASRecomp lifter.py scalar families plus our EH overrides.
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
static const char *extend(unsigned r, unsigned option, unsigned shift) {
    const char *value = reg(true, r, false);
    const char *formats[] = {"(uint64_t)(uint8_t)%s", "(uint64_t)(uint16_t)%s", "(uint64_t)(uint32_t)%s", "%s",
        "(uint64_t)(int64_t)(int8_t)%s", "(uint64_t)(int64_t)(int16_t)%s", "(uint64_t)(int64_t)(int32_t)%s", "%s"};
    const char *expression = cg_format(formats[option], value);
    return shift ? cg_format("(%s << %u)", expression, shift) : expression;
}
static const char *offset(const char *base, int64_t displacement) {
    return cg_format("%s %s %" PRIu64, base, displacement < 0 ? "-" : "+", (uint64_t)(displacement < 0 ? -displacement : displacement));
}
static Instruction assembly(uint32_t word, uint32_t vregs) {
    return (Instruction){.kind = CG_ASM, .assembly = {.word = word, .vregs = vregs}};
}
static void asm_reg(Instruction *ins, unsigned position, unsigned r) {
    ins->assembly.gprs[ins->assembly.gpr_count++] = (AsmRegister){position, r};
}
static Instruction simd_load_store(uint32_t w, uint64_t pc) {
    unsigned rt = bits(w, 0, 5), rn = bits(w, 5, 5), rm = bits(w, 16, 5);
    if (bits(w, 27, 3) == 3 && !bits(w, 24, 2)) {
        unsigned opc = bits(w, 30, 2);
        if (opc == 3) return unsupported(pc, "SIMD literal opc 3"); /* Frozen Python rejects this reserved encoding. */
        unsigned size = (unsigned[]){2, 3, 0}[opc], o = opc == 2 ? 3u : 1u;
        Instruction ins = assembly((size << 30) | 0x3d000000 | (o << 22) | (31u << 5) | rt, UINT32_C(1) << rt);
        int64_t displacement = sext(bits(w, 5, 19), 19) * 4;
        uint64_t magnitude = displacement < 0 ? (uint64_t)(-displacement) : 0;
        bool negative = displacement < 0 && pc < magnitude;
        ins.assembly.constants[0] = (AsmConstant){5, negative ? magnitude - pc : pc + (uint64_t)displacement, negative};
        ins.assembly.constant_count = 1; return ins;
    }
    Instruction ins = assembly(w, UINT32_C(1) << rt);
    if (!bits(w, 31, 1) && (bits(w, 24, 6) == 12 || bits(w, 24, 6) == 13)) {
        unsigned n;
        if (!bits(w, 24, 1)) {
            unsigned counts[] = {4, 0, 4, 0, 3, 0, 3, 1, 2, 0, 2, 0, 0, 0, 0, 0};
            n = counts[bits(w, 12, 4)];
            if (!n) return unsupported(pc, "ldst multiple opcode");
        } else n = ((bits(w, 13, 1) << 1) | bits(w, 21, 1)) + 1;
        for (unsigned i = 0; i < n; i++) ins.assembly.vregs |= UINT32_C(1) << ((rt + i) % 32);
        asm_reg(&ins, 5, rn);
        if (bits(w, 23, 1) && rm != 31) asm_reg(&ins, 16, rm);
        return ins;
    }
    asm_reg(&ins, 5, rn);
    if (bits(w, 27, 3) == 5) ins.assembly.vregs |= UINT32_C(1) << bits(w, 10, 5);
    else if (bits(w, 27, 3) == 7 && !bits(w, 24, 2) && bits(w, 21, 1) && bits(w, 10, 2) == 2 && rm != 31) asm_reg(&ins, 16, rm);
    return ins;
}
static Instruction simd_instruction(uint32_t w) {
    unsigned rd = bits(w, 0, 5), rn = bits(w, 5, 5), rm = bits(w, 16, 5), ra = bits(w, 10, 5);
    Instruction ins = assembly(w, (UINT32_C(1) << rd) | (UINT32_C(1) << rn) | (UINT32_C(1) << rm) | (UINT32_C(1) << ra));
    bool from_fp = false, conversion = false;
    if ((w & 0x5f20fc00) == 0x1e200000) {
        unsigned opcode = bits(w, 16, 3); conversion = true;
        from_fp = opcode == 0 || opcode == 1 || opcode == 4 || opcode == 5 || opcode == 6;
    } else if ((w & 0x5f200000) == 0x1e000000) {
        unsigned opcode = bits(w, 16, 3); conversion = true; from_fp = opcode == 0 || opcode == 1;
    } else if ((w & 0x9fe08400) == 0x0e000400 && !bits(w, 29, 1)) {
        unsigned imm4 = bits(w, 11, 4);
        if (imm4 == 1 || imm4 == 3 || imm4 == 5 || imm4 == 7) { conversion = true; from_fp = imm4 == 5 || imm4 == 7; }
        else ins.assembly.vregs = (UINT32_C(1) << rd) | (UINT32_C(1) << rn);
    } else if ((w & 0xbfe08c00) == 0x0e000000) {
        ins.assembly.vregs = (UINT32_C(1) << rd) | (UINT32_C(1) << rm);
        for (unsigned i = 0; i <= bits(w, 13, 2); i++) ins.assembly.vregs |= UINT32_C(1) << ((rn + i) % 32);
    }
    if (conversion) {
        ins.assembly.vregs = UINT32_C(1) << (from_fp ? rn : rd);
        if ((from_fp ? rd : rn) != 31) asm_reg(&ins, from_fp ? 0u : 5u, from_fp ? rd : rn);
    }
    ins.assembly.flags = (w & 0x5f203c00) == 0x1e202000 || (w & 0x5f200c00) == 0x1e200400 || (w & 0x5f200c00) == 0x1e200c00;
    return ins;
}
static Instruction load_store(uint32_t w, uint64_t pc, bool portable) {
    unsigned rn = bits(w, 5, 5), rt = bits(w, 0, 5), rt2 = bits(w, 10, 5);
    const char *base = reg(true, rn, true);
    /* EH generator override: pair exclusives use our reservation helpers. */
    if ((w & 0xbfa00000) == 0x88200000) {
        bool sf = bits(w, 30, 1) != 0;
        unsigned width = sf ? 64u : 32u;
        if (bits(w, 22, 1)) return op(cg_format("{ uint64_t ea = %s; uint64_t lo, hi; ldxp%u(c, ea, GPTR(ea), &lo, &hi); %s %s }",
            base, width, set(sf, rt, "lo", false), set(sf, rt2, "hi", false)));
        return op(cg_format("{ uint64_t ea = %s; uint32_t st = stxp%u(c, ea, GPTR(ea), %s, %s); %s }",
            base, width, reg(true, rt, false), reg(true, rt2, false), set(false, bits(w, 16, 5), "st", false)));
    }
    if (bits(w, 26, 1)) return portable ? (Instruction){.kind = CG_PENDING} : simd_load_store(w, pc);
    if (bits(w, 24, 6) == 8) {
        unsigned width = 8u << bits(w, 30, 2);
        bool acquire = bits(w, 23, 1) != 0, load = bits(w, 22, 1) != 0;
        if (bits(w, 21, 1)) return unsupported(pc, "exclusive pair / CAS");
        if (!acquire) {
            if (load) return op(set(true, rt, cg_format("ldx%u(c, %s)", width, base), false));
            return op(cg_format("{ uint32_t st = stx%u(c, %s, %s); %s }", width, base,
                reg(true, rt, false), set(false, bits(w, 16, 5), "st", false)));
        }
        if (load) return op(set(true, rt, cg_format("lda%u(%s)", width, base), false));
        return op(cg_format("stl%u(%s, %s);", width, base, reg(true, rt, false)));
    }
    if (bits(w, 27, 3) == 3 && !bits(w, 24, 2)) {
        unsigned opc = bits(w, 30, 2);
        int64_t displacement = sext(bits(w, 5, 19), 19) * 4;
        uint64_t magnitude = displacement < 0 ? (uint64_t)(-displacement) : 0;
        const char *address = displacement < 0 && pc < magnitude
            ? cg_format("0x-%" PRIx64 "ull", magnitude - pc) : hex(pc + (uint64_t)displacement);
        if (opc == 0) return op(set(false, rt, cg_format("LD32(%s)", address), false));
        if (opc == 1) return op(set(true, rt, cg_format("LD64(%s)", address), false));
        if (opc == 2) return op(set(true, rt, cg_format("(int64_t)(int32_t)LD32(%s)", address), false));
        return op("/* prfm */");
    }
    if (bits(w, 27, 3) == 5) {
        unsigned opc = bits(w, 30, 2), mode = bits(w, 23, 2);
        bool load = bits(w, 22, 1) != 0, post = mode == 1, wb = mode == 1 || mode == 3;
        if (opc == 3) return unsupported(pc, "pair opc 3");
        int64_t displacement = sext(bits(w, 15, 7), 7) * (opc == 2 ? 8 : 4);
        const char *code = cg_format("{ uint64_t ea = %s;", post ? base : offset(base, displacement));
        if (load) {
            const char *loads[] = {"uint64_t a = LD32(ea), b = LD32(ea + 4);",
                "uint64_t a = (int64_t)(int32_t)LD32(ea), b = (int64_t)(int32_t)LD32(ea + 4);",
                "uint64_t a = LD64(ea), b = LD64(ea + 8);"};
            code = cg_format("%s %s", code, loads[opc]);
        } else {
            code = cg_format("%s ST%u(ea, %s); ST%u(ea + %u, %s);", code, opc == 2 ? 64u : 32u,
                reg(opc == 2, rt, false), opc == 2 ? 64u : 32u, opc == 2 ? 8u : 4u, reg(opc == 2, rt2, false));
        }
        if (wb) code = cg_format("%s %s = %s;", code, base, post ? offset("ea", displacement) : "ea");
        if (load) code = cg_format("%s %s %s", code, set(true, rt, "a", false), set(true, rt2, "b", false));
        return op(cg_format("%s }", code));
    }
    if (bits(w, 27, 3) == 7) {
        unsigned size = bits(w, 30, 2), opc = bits(w, 22, 2), width = 8u << size;
        const char *ea = NULL, *wb = NULL;
        if (bits(w, 24, 2) == 1) ea = cg_format("%s + %s", base, hex((uint64_t)bits(w, 10, 12) << size));
        else {
            unsigned kind = bits(w, 10, 2);
            if (bits(w, 21, 1)) {
                if (kind != 2) return unsupported(pc, "ldst reg atomic/pac");
                unsigned option = bits(w, 13, 3);
                if (option != 2 && option != 3 && option != 6 && option != 7) return unsupported(pc, "ldst reg option");
                ea = cg_format("%s + %s", base, extend(bits(w, 16, 5), option, bits(w, 12, 1) ? size : 0));
            } else {
                ea = offset(base, sext(bits(w, 12, 9), 9));
                if (kind == 1) { wb = ea; ea = base; }
                else if (kind == 3) wb = "ea";
            }
        }
        const char *body = NULL, *load = NULL;
        if (opc == 0) body = cg_format("ST%u(ea, %s);", width, reg(size == 3, rt, false));
        else if (opc == 1) { body = cg_format("uint64_t v = LD%u(ea);", width); load = set(true, rt, "v", false); }
        else if (size == 3) return op("/* prfm */");
        else if (size == 2 && opc == 3) return unsupported(pc, "ldst size2 opc3");
        else { body = cg_format("uint64_t v = (uint64_t)(int64_t)(int%u_t)LD%u(ea);", width, width); load = set(opc == 2, rt, "v", false); }
        const char *code = cg_format("{ uint64_t ea = %s; %s", ea, body);
        if (wb) code = cg_format("%s %s = %s;", code, base, wb);
        if (load) code = cg_format("%s %s", code, load);
        return op(cg_format("%s }", code));
    }
    return unsupported(pc, cg_format("ldst %08x", w));
}
static const char *shift(bool sf, const char *value, unsigned type, unsigned amount) {
    unsigned size = sf ? 64u : 32u;
    if (!amount && type != 3) return value;
    if (type == 0 || type == 1) return cg_format("(%s %s %u)", value, type == 0 ? "<<" : ">>", amount);
    if (type == 2) return cg_format("(uint%u_t)((int%u_t)%s >> %u)", size, size, value, amount);
    return cg_format("ROR%u(%s, %u)", size, value, amount);
}
static const char *condition(unsigned cond) {
    const char *const names[] = {"EQ", "NE", "CS", "CC", "MI", "PL", "VS", "VC", "HI", "LS", "GE", "LT", "GT", "LE"};
    return cond >= 14 ? "1" : cg_format("COND_%s(c)", names[cond]);
}
static Instruction register_instruction(uint32_t w, uint64_t pc, bool portable) {
    bool sf = bits(w, 31, 1) != 0;
    unsigned rd = bits(w, 0, 5), rn = bits(w, 5, 5), rm = bits(w, 16, 5), size = sf ? 64u : 32u;
    const char *a = reg(sf, rn, false), *b = reg(sf, rm, false);
    if (!bits(w, 28, 1)) {
        if (bits(w, 24, 4) == 10) {
            unsigned opc = bits(w, 29, 2), amount = bits(w, 10, 6);
            if (!sf && amount >= 32) return unsupported(pc, "logical shift amount");
            b = shift(sf, b, bits(w, 22, 2), amount);
            if (bits(w, 21, 1)) b = cg_format("(uint%u_t)~%s", size, b);
            const char *expression = cg_format("%s %s %s", a, (const char *const[]){"&", "|", "^", "&"}[opc], b);
            if (opc == 3) expression = cg_format("logic%u(c, (uint%u_t)(%s))", size, size, expression);
            return op(set(sf, rd, expression, false));
        }
        if (bits(w, 24, 4) == 11) {
            bool subtract = bits(w, 30, 1) != 0, flags = bits(w, 29, 1) != 0, sp = false;
            if (!bits(w, 21, 1)) {
                unsigned type = bits(w, 22, 2);
                if (type == 3) return unsupported(pc, "add shift ror");
                b = shift(sf, b, type, bits(w, 10, 6));
            } else {
                if (bits(w, 22, 2)) return unsupported(pc, "add ext opt");
                a = reg(sf, rn, true);
                b = extend(rm, bits(w, 13, 3), bits(w, 10, 3));
                if (!sf) b = cg_format("(uint32_t)(%s)", b);
                sp = !flags;
            }
            if (flags) return op(set(sf, rd, cg_format("%s%u(c, %s, (uint%u_t)(%s))", subtract ? "subs" : "adds", size, a, size, b), false));
            return op(set(sf, rd, cg_format("%s %s %s", a, subtract ? "-" : "+", b), sp));
        }
        return unsupported(pc, cg_format("dp_reg %08x", w));
    }
    if (bits(w, 24, 4) == 11) {
        unsigned op31 = bits(w, 21, 3), ra = bits(w, 10, 5);
        const char *sign = bits(w, 15, 1) ? "-" : "+";
        if (bits(w, 29, 2)) return unsupported(pc, "dp3 op54");
        if (op31 == 0) return op(set(sf, rd, cg_format("%s %s %s * %s", reg(sf, ra, false), sign, a, b), false));
        if (op31 == 1) return op(set(true, rd, cg_format("%s %s (uint64_t)((int64_t)(int32_t)%s * (int64_t)(int32_t)%s)",
            reg(true, ra, false), sign, reg(false, rn, false), reg(false, rm, false)), false));
        if (op31 == 5) return op(set(true, rd, cg_format("%s %s (uint64_t)%s * (uint64_t)%s",
            reg(true, ra, false), sign, reg(false, rn, false), reg(false, rm, false)), false));
        if (op31 == 2) return op(set(true, rd, cg_format("(uint64_t)(((__int128)(int64_t)%s * (__int128)(int64_t)%s) >> 64)",
            reg(true, rn, false), reg(true, rm, false)), false));
        if (op31 == 6) return op(set(true, rd, cg_format("(uint64_t)(((unsigned __int128)%s * %s) >> 64)",
            reg(true, rn, false), reg(true, rm, false)), false));
        return unsupported(pc, "dp3");
    }
    unsigned op2 = bits(w, 21, 4);
    if (op2 == 0) return op(set(sf, rd, cg_format("%s%s%u(c, %s, %s)", bits(w, 30, 1) ? "sbc" : "adc", bits(w, 29, 1) ? "s" : "", size, a, b), false));
    if (op2 == 2) return op(cg_format("if (%s) (void)%s%u(c, %s, %s); else c->nzcv = %s;",
        condition(bits(w, 12, 4)), bits(w, 30, 1) ? "subs" : "adds", size, a,
        bits(w, 11, 1) ? hex(rm) : b, hex((uint64_t)bits(w, 0, 4) << 28)));
    if (op2 == 4) {
        unsigned o2 = bits(w, 10, 2); bool negate = bits(w, 30, 1) != 0;
        if (o2 > 1) return unsupported(pc, "csel variant");
        const char *alternative = negate ? cg_format("%s%s", o2 ? "-" : "~", b) : (o2 ? cg_format("%s + 1", b) : b);
        return op(set(sf, rd, cg_format("(%s) ? %s : (uint%u_t)(%s)", condition(bits(w, 12, 4)), a, size, alternative), false));
    }
    if (op2 == 6) {
        unsigned opcode = bits(w, 10, 6);
        const char *expression = NULL;
        if (bits(w, 30, 1)) {
            if (rm) return unsupported(pc, "dp1 opcode2");
            switch (opcode) {
                case 0: expression = cg_format("rbit%u(%s)", size, a); break;
                case 1: expression = cg_format("rev16_%u(%s)", size, a); break;
                case 2: expression = cg_format(sf ? "rev32_64(%s)" : "__builtin_bswap32(%s)", a); break;
                case 3: if (sf) expression = cg_format("__builtin_bswap64(%s)", a); break;
                case 4: expression = cg_format("clz%u(%s)", size, a); break;
                case 5: expression = cg_format("cls%u(%s)", size, a); break;
            }
            if (!expression) return unsupported(pc, "dp1");
        } else {
            if (opcode >= 16 && opcode <= 23) {
                if (!portable) {
                    Instruction ins = assembly(w, 0);
                    if (rd != 31) asm_reg(&ins, 0, rd);
                    if (rn != 31) asm_reg(&ins, 5, rn);
                    if (rm != 31) asm_reg(&ins, 16, rm);
                    return ins;
                }
                unsigned crc_size = bits(w, 10, 2);
                if ((crc_size == 3) != sf) return unsupported(pc, "crc size");
                return op(set(false, rd, cg_format("%s(%s, %s, %u)", bits(w, 12, 1) ? "CRC32C" : "CRC32",
                    reg(false, rn, false), reg(crc_size == 3, rm, false), 1u << crc_size), false));
            }
            switch (opcode) {
                case 2: expression = cg_format("udiv%u(%s, %s)", size, a, b); break;
                case 3: expression = cg_format("sdiv%u(%s, %s)", size, a, b); break;
                case 8: expression = cg_format("%s << (%s & %u)", a, b, size - 1); break;
                case 9: expression = cg_format("%s >> (%s & %u)", a, b, size - 1); break;
                case 10: expression = cg_format("(uint%u_t)((int%u_t)%s >> (%s & %u))", size, size, a, b, size - 1); break;
                case 11: expression = cg_format("ROR%u(%s, %s & %u)", size, a, b, size - 1); break;
            }
            if (!expression) return unsupported(pc, "dp2");
        }
        return op(set(sf, rd, expression, false));
    }
    return unsupported(pc, cg_format("dp_reg %08x", w));
}
Instruction cg_lift_basic(uint32_t w, uint64_t pc, bool portable, bool has_previous, uint32_t previous) {
    unsigned op0 = bits(w, 25, 4);
    if ((op0 & 14) == 8) return immediate(w, pc);
    if ((op0 & 14) == 10) return control(w, pc, portable, has_previous, previous);
    if ((op0 & 5) == 4) return load_store(w, pc, portable);
    if ((op0 & 7) == 5) return register_instruction(w, pc, portable);
    if ((op0 & 7) == 7) return portable ? (Instruction){.kind = CG_PENDING} : simd_instruction(w);
    return (Instruction){.kind = CG_TRAP, .code = cg_format("rt_udf(c, %s);", hex(pc))};
}
