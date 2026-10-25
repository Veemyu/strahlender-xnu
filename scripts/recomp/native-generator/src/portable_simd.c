/* SPDX-License-Identifier: MIT. Portable SIMD/FP lowering, adapted from SimdC. */
#include "lifter_internal.h"

static const char *vector_source(unsigned scale, unsigned r) {
    return scale == 4 ? cg_format("c->v[%u]", r) : cg_format("VS%u(%u)", 8u << scale, r);
}
static Instruction structure(uint32_t w, uint64_t pc) {
    unsigned q = bits(w, 30, 1), load = bits(w, 22, 1), post = bits(w, 23, 1);
    unsigned rm = bits(w, 16, 5), rn = bits(w, 5, 5), rt = bits(w, 0, 5), size = bits(w, 10, 2), total;
    if (!post && rm) return unsupported(pc, "ldst struct rm");
    const char *access;
    if (!bits(w, 24, 1)) {
        if (bits(w, 21, 1)) return unsupported(pc, "ldst multiple bit21");
        unsigned opc = bits(w, 12, 4), selem = 0, rpt = 0;
        switch (opc) {
            case 0: selem = 4; rpt = 1; break;
            case 2: selem = 1; rpt = 4; break;
            case 4: selem = 3; rpt = 1; break;
            case 6: selem = 1; rpt = 3; break;
            case 7: selem = 1; rpt = 1; break;
            case 8: selem = 2; rpt = 1; break;
            case 10: selem = 1; rpt = 2; break;
            default: return unsupported(pc, "ldst multiple opcode");
        }
        if (size == 3 && !q && selem > 1) return unsupported(pc, "ldst multiple 1d");
        total = (8u << q) * selem * rpt;
        if (selem == 1) {
            access = "";
            for (unsigned i = 0; i < rpt; i++) {
                unsigned r = (rt + i) % 32;
                access = load ? cg_format("%s%sc->v[%u] = LD%u(ea + %u);", access, i ? " " : "", r, q ? 128u : 64u, i * (q ? 16u : 8u))
                    : cg_format("%s%sST%u(ea + %u, %s);", access, i ? " " : "", q ? 128u : 64u, i * (q ? 16u : 8u), vector_source(q ? 4u : 3u, r));
            }
        } else access = cg_format("sl_%s(c, %u, %u, %u, %u, %u, ea);", load ? "ldm" : "stm", q, size, selem, rpt, rt);
    } else {
        unsigned opc = bits(w, 13, 3), s = bits(w, 12, 1), r = bits(w, 21, 1), scale = opc >> 1;
        unsigned selem = ((opc & 1) << 1 | r) + 1;
        if (scale == 3) {
            if (!load || s) return unsupported(pc, "ldnr");
            total = selem << size; access = cg_format("sl_ldr(c, %u, %u, %u, %u, ea);", q, size, selem, rt);
        } else {
            unsigned index;
            if (scale == 0) index = (q << 3) | (s << 2) | size;
            else if (scale == 1) {
                if (size & 1) return unsupported(pc, "ld1 h size");
                index = (q << 2) | (s << 1) | (size >> 1);
            } else {
                if (size & 2) return unsupported(pc, "ld1 s size");
                if (size & 1) {
                    if (s) return unsupported(pc, "ld1 d S");
                    index = q; scale = 3;
                } else index = (q << 1) | s;
            }
            total = selem << scale; access = cg_format("sl_%s(c, %u, %u, %u, %u, ea);", load ? "lds" : "sts", scale, selem, index, rt);
        }
    }
    const char *base = reg(true, rn, true), *code = cg_format("{ uint64_t ea = %s; %s", base, access);
    if (post) code = cg_format("%s %s = ea + %s;", code, base, rm == 31 ? cg_format("%u", total) : reg(true, rm, false));
    return op(cg_format("%s }", code));
}
Instruction cg_portable_load_store(uint32_t w, uint64_t pc) {
    unsigned rt = bits(w, 0, 5), rn = bits(w, 5, 5), rt2 = bits(w, 10, 5);
    const char *base = reg(true, rn, true);
    if (bits(w, 27, 3) == 3 && !bits(w, 24, 2)) {
        unsigned opc = bits(w, 30, 2);
        if (opc == 3) return unsupported(pc, "ldr literal opc");
        uint64_t address = pc + (uint64_t)(sext(bits(w, 5, 19), 19) * 4);
        return op(cg_format("c->v[%u] = LD%u(%s);", rt, 32u << opc, hex(address)));
    }
    if (!bits(w, 31, 1) && (bits(w, 24, 6) == 12 || bits(w, 24, 6) == 13)) return structure(w, pc);
    if (bits(w, 27, 3) == 5) {
        unsigned opc = bits(w, 30, 2), mode = bits(w, 23, 2), load = bits(w, 22, 1);
        if (opc == 3) return unsupported(pc, "pair opc 3");
        unsigned scale = 2 + opc, size = 1u << scale, width = 8u << scale;
        int64_t off = sext(bits(w, 15, 7), 7) * size;
        const char *code = cg_format("{ uint64_t ea = %s;", mode == 1 ? base : offset(base, off));
        if (load) code = cg_format("%s u128 a = LD%u(ea), b = LD%u(ea + %u); c->v[%u] = a; c->v[%u] = b;", code, width, width, size, rt, rt2);
        else code = cg_format("%s ST%u(ea, %s); ST%u(ea + %u, %s);", code, width, vector_source(scale, rt), width, size, vector_source(scale, rt2));
        if (mode == 1 || mode == 3) code = cg_format("%s %s = %s;", code, base, mode == 1 ? offset("ea", off) : "ea");
        return op(cg_format("%s }", code));
    }
    if (bits(w, 27, 3) == 7) {
        unsigned size = bits(w, 30, 2), opc = bits(w, 22, 2), scale = size;
        if (opc & 2) { if (size) return unsupported(pc, "ldst simd size"); scale = 4; }
        const char *ea, *wb = NULL;
        if (bits(w, 24, 2) == 1) ea = cg_format("%s + %s", base, hex((uint64_t)bits(w, 10, 12) << scale));
        else if (!bits(w, 24, 2)) {
            unsigned kind = bits(w, 10, 2);
            if (bits(w, 21, 1)) {
                if (kind != 2) return unsupported(pc, "ldst simd reg kind");
                unsigned option = bits(w, 13, 3);
                if (option != 2 && option != 3 && option != 6 && option != 7) return unsupported(pc, "ldst simd reg option");
                ea = cg_format("%s + %s", base, extend(bits(w, 16, 5), option, bits(w, 12, 1) ? scale : 0));
            } else {
                ea = offset(base, sext(bits(w, 12, 9), 9));
                if (kind == 1) { wb = ea; ea = base; }
                else if (kind == 3) wb = "ea";
                else if (kind != 0) return unsupported(pc, "ldst simd unprivileged");
            }
        } else return unsupported(pc, "ldst simd");
        const char *code = (opc & 1) ? cg_format("{ uint64_t ea = %s; c->v[%u] = LD%u(ea);", ea, rt, 8u << scale)
            : cg_format("{ uint64_t ea = %s; ST%u(ea, %s);", ea, 8u << scale, vector_source(scale, rt));
        if (wb) code = cg_format("%s %s = %s;", code, base, wb);
        return op(cg_format("%s }", code));
    }
    return unsupported(pc, cg_format("ldst simd %08x", w));
}
Instruction cg_portable_simd(uint32_t w, uint64_t pc) {
    unsigned op0 = bits(w, 28, 4), op1 = bits(w, 23, 2), op2 = bits(w, 19, 4), op3 = bits(w, 10, 9);
    if ((op0 & 5) != 1) return cg_portable_vector(w, pc);
    if (bits(w, 29, 1) || (bits(w, 31, 1) && ((op1 & 2) || ((op2 & 4) && (op3 & 63))))) return unsupported(pc, "fp M/S");
    unsigned t = bits(w, 22, 2), d = bits(w, 0, 5), n = bits(w, 5, 5), m = bits(w, 16, 5);
    const char *f = t == 0 ? "s" : "d", *sf = t == 0 ? "VSF32" : "VSF64", *su = t == 0 ? "VS32" : "VS64", *dst = t == 0 ? "FP_SETS" : "FP_SETD";
    if (op1 & 2) {
        if (t > 1) return unsupported(pc, "fp type");
        unsigned o1 = bits(w, 21, 1), o0 = bits(w, 15, 1);
        return op(cg_format("fp_fma_%s(c, %u, %u, %u, %u, %u, %u);", f, o1, o1 ^ o0, d, n, m, bits(w, 10, 5)));
    }
    bool integer64 = bits(w, 31, 1) != 0;
    unsigned rmode = bits(w, 19, 2), opc = bits(w, 16, 3), ib = integer64 ? 64u : 32u;
    if (!(op2 & 4)) {
        unsigned scale = bits(w, 10, 6), fb = 64 - scale;
        if (t > 1) return unsupported(pc, "fixed type");
        if (!integer64 && scale < 32) return unsupported(pc, "fixed scale");
        if (!rmode && (opc == 2 || opc == 3)) return op(cg_format("%s(%u, fromint_%s(c, %s, %u, %u, %u));", dst, d, f, reg(integer64, n, false), ib, opc & 1, fb));
        if (rmode == 3 && opc <= 1) return op(set(integer64, d, cg_format("toint_%s(c, %s(%u), 3, %u, %u, %u)", f, sf, n, fb, ib, opc), false));
        return unsupported(pc, "fixed opcode");
    }
    if (!(op3 & 63)) {
        if (opc == 6 || opc == 7) {
            if (t == 2 && integer64 && rmode == 1) return opc == 6 ? op(set(true, d, cg_format("VHI64(%u)", n), false)) : op(cg_format("VHI64(%u) = %s;", d, reg(true, n, false)));
            if (rmode || t != (unsigned)integer64 || t > 1) return unsupported(pc, "fmov general");
            if (opc == 6) return op(set(integer64, d, cg_format("VS%u(%u)", ib, n), false));
            return op(cg_format("c->v[%u] = %s;", d, reg(integer64, n, false)));
        }
        if (t > 1) return unsupported(pc, "fp int type");
        if (opc == 2 || opc == 3) {
            if (rmode) return unsupported(pc, "cvtf rmode");
            return op(cg_format("%s(%u, fromint_%s(c, %s, %u, %u, 0));", dst, d, f, reg(integer64, n, false), ib, opc & 1));
        }
        if (opc == 4 || opc == 5) { if (rmode) return unsupported(pc, "fcvta rmode"); rmode = 4; }
        return op(set(integer64, d, cg_format("toint_%s(c, %s(%u), %u, 0, %u, %u)", f, sf, n, rmode, ib, opc & 1), false));
    }
    if ((op3 & 31) == 16) {
        unsigned opcode = bits(w, 15, 6);
        if (t == 3) {
            if (opcode == 4 || opcode == 5) return op(cg_format("FP_SET%s(%u, simd_h2%s(c, VS16(%u)));", opcode == 4 ? "S" : "D", d, opcode == 4 ? "s" : "d", n));
            return unsupported(pc, "fp16 dp1");
        }
        if (t == 2) return unsupported(pc, "fp type");
        const char *sign = t == 0 ? "0x80000000u" : "0x8000000000000000ull";
        if (opcode == 0) return op(cg_format("c->v[%u] = %s(%u);", d, su, n));
        if (opcode == 1 || opcode == 2) return op(cg_format("c->v[%u] = %s(%u) %s %s%s;", d, su, n, opcode == 1 ? "&" : "^", opcode == 1 ? "~" : "", sign));
        if (opcode == 3) return op(cg_format("fp_op_%s(c, FOP_SQRT, %u, %u, %u);", f, d, n, n));
        if (opcode == 4 || opcode == 5 || opcode == 7) {
            unsigned to = opcode == 4 ? 0u : (opcode == 5 ? 1u : 3u);
            if (to == t) return unsupported(pc, "fcvt same");
            if (to == 3) return op(cg_format("c->v[%u] = %s(c, %s(%u));", d, t == 0 ? "simd_s2h" : "simd_dd2h", sf, n));
            return op(cg_format("FP_SET%s(%u, simd_%s(c, VSF%u(%u)));", to ? "D" : "S", d, to ? "s2d" : "d2s", to ? 32u : 64u, n));
        }
        unsigned rounding;
        switch (opcode) {
            case 8: rounding = 0; break; case 9: rounding = 1; break; case 10: rounding = 2; break;
            case 11: rounding = 3; break; case 12: rounding = 4; break; case 14: rounding = 5; break;
            case 15: rounding = 6; break; default: return unsupported(pc, "fp dp1 opcode");
        }
        return op(cg_format("%s(%u, frint_%s(c, %s(%u), %u));", dst, d, f, sf, n, rounding));
    }
    if ((op3 & 15) != 8 && (op3 & 7) != 4 && !(op3 & 3)) return unsupported(pc, "fp op3");
    if (t > 1) return unsupported(pc, "fp type");
    if ((op3 & 15) == 8) {
        if (bits(w, 14, 2) || bits(w, 0, 3)) return unsupported(pc, "fcmp op");
        const char *right = bits(w, 3, 1) ? "0" : cg_format("%s(%u)", sf, m);
        return op(cg_format("c->nzcv = cmp_%s(c, %s(%u), %s);", f, sf, n, right));
    }
    if ((op3 & 7) == 4) {
        if (n) return unsupported(pc, "fmov imm5");
        return op(cg_format("c->v[%u] = %s;", d, hex(fp_immediate(bits(w, 13, 8), 32u << t))));
    }
    if ((op3 & 3) == 1) return op(cg_format("c->nzcv = %s ? cmp_%s(c, %s(%u), %s(%u)) : %s;", condition(bits(w, 12, 4)), f, sf, n, sf, m, hex((uint64_t)bits(w, 0, 4) << 28)));
    if ((op3 & 3) == 2) {
        unsigned opcode = bits(w, 12, 4);
        const char *operations[] = {"FOP_MUL", "FOP_DIV", "FOP_ADD", "FOP_SUB", "FOP_MAX", "FOP_MIN", "FOP_MAXNM", "FOP_MINNM", "FOP_NMUL"};
        if (opcode > 8) return unsupported(pc, "fp dp2");
        return op(cg_format("fp_op_%s(c, %s, %u, %u, %u);", f, operations[opcode], d, n, m));
    }
    if ((op3 & 3) == 3) return op(cg_format("c->v[%u] = %s ? %s(%u) : %s(%u);", d, condition(bits(w, 12, 4)), su, n, su, m));
    return unsupported(pc, "fp op3");
}
