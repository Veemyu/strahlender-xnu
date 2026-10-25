/* SPDX-License-Identifier: MIT
 * Function C emission follows the frozen LASRecomp Module.emit_function and
 * this project's EH wrapper. Analysis/chunk orchestration remains separate. */
#include "emitter.h"
#include <inttypes.h>
#include <string.h>
#include <stdlib.h>

static bool contains(const Addresses *a, uint64_t value) {
    size_t lo = 0, hi = a->size;
    while (lo < hi) { size_t mid = lo + (hi - lo) / 2; if (a->items[mid] < value) lo = mid + 1; else hi = mid; }
    return lo < a->size && a->items[lo] == value;
}
static int table_order(const void *left, const void *right) {
    uint64_t a = ((const JumpTable *)left)->pc, b = ((const JumpTable *)right)->pc;
    return (a > b) - (a < b);
}
static const char *hex_target(uint64_t target, bool negative) { return cg_format("0x%s%" PRIx64 "ull", negative ? "-" : "", target); }
static const char *tail(const char *expression, bool eh) {
    return eh ? cg_format("do { EH_POP(); __attribute__((musttail)) return %s; } while (0);", expression)
              : cg_format("__attribute__((musttail)) return %s;", expression);
}
static const char *jump(const EmitFunction *f, EmittedFunction *out, uint64_t t, bool negative, bool eh) {
    if (!negative && t >= f->entry && t < f->end) return cg_format("goto L_%" PRIx64 ";", t);
    uint64_t lo = f->base + f->nso->segments[0].offset, hi = lo + f->nso->segments[0].size;
    if (negative || t < lo || t >= hi || t % 4) return cg_format("c->pc = %s; %s", hex_target(t, negative), tail("rt_dispatch(c)", eh));
    cg_address(&out->refs, t);
    return tail(cg_format("f_%" PRIx64 "(c)", t), eh);
}
static void line(Buffer *b, const char *text) { cg_printf(b, "%s\n", text); }
static void flush_assembly(Buffer *b, AsmInstruction *batch, size_t *count) {
    if (!*count) return;
    const char *code;
    if (!cg_emit_asm_batch(batch, *count, &code)) cg_fail(4, "assembly batch exceeds scratch register capacity");
    line(b, cg_format("    %s", code)); *count = 0;
}
static const JumpTable *table_at(const EmitFunction *f, uint64_t pc) {
    size_t lo = 0, hi = f->table_count;
    while (lo < hi) { size_t mid = lo + (hi - lo) / 2; if (f->tables[mid].pc < pc) lo = mid + 1; else hi = mid; }
    return lo < f->table_count && f->tables[lo].pc == pc ? &f->tables[lo] : NULL;
}
static const char *sanitize(const char *name) {
    Buffer b = {0}; cg_buffer(&b, "hle_", 4);
    /* Python's ASCII whitelist replaces each non-ASCII Unicode character once. */
    for (const unsigned char *p = (const unsigned char *)name; *p; p++) {
        if ((*p & 0xc0) == 0x80) continue;
        unsigned char c = *p;
        if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '_')) c = '_';
        cg_buffer(&b, &c, 1);
    }
    cg_buffer(&b, "", 1); return (const char *)b.data;
}
static void cases(Buffer *b, const Addresses *targets) {
    for (size_t i = 0; i < targets->size; i++) cg_printf(b, "%scase 0x%" PRIx64 "ull: goto L_%" PRIx64 ";", i ? " " : "", targets->items[i], targets->items[i]);
}
static void validate_address(const EmitFunction *f, uint64_t a) {
    if (a < f->entry || a >= f->end || a % 4) cg_fail(4, "emission label or table address outside function");
}
EmittedFunction cg_emit_function(const EmitFunction *f) {
    EmittedFunction out = {0}; Buffer *b = &out.code;
    EmitFunction normalized = *f;
    if (f->table_count) {
        normalized.tables = cg_alloc(f->table_count, sizeof(JumpTable));
        memcpy(normalized.tables, f->tables, f->table_count * sizeof(JumpTable));
        qsort(normalized.tables, f->table_count, sizeof(JumpTable), table_order);
    }
    f = &normalized;
    uint64_t lo = f->base + f->nso->segments[0].offset, hi = lo + f->nso->segments[0].size;
    if (lo < f->base || hi < lo || lo % 4 || f->entry < lo || f->end > hi || f->entry >= f->end || f->entry % 4 || f->end % 4)
        cg_fail(4, "invalid function emission range");
    Addresses pads = {0}, labels = {0};
    for (size_t i = 0; i < f->labels.size; i++) {
        validate_address(f, f->labels.items[i]); cg_address(&labels, f->labels.items[i]);
    }
    cg_unique(&labels);
    for (size_t i = 0; i < f->nle.size; i++) if (f->nle.items[i] >= f->entry && f->nle.items[i] < f->end) {
        validate_address(f, f->nle.items[i]); cg_address(&pads, f->nle.items[i]);
    }
    cg_unique(&pads); bool eh = pads.size && !f->hle;
    line(b, cg_format("void f_%" PRIx64 "(Cpu *c) {", f->entry));
    if (f->hle) { line(b, cg_format("    %s(c);", sanitize(f->hle))); line(b, "}"); return out; }
    for (size_t i = 0; i < f->table_count; i++) {
        const JumpTable *table = &f->tables[i]; validate_address(f, table->pc);
        uint32_t w = cg_u32(f->nso->image + (size_t)(table->pc - f->base));
        Instruction ins = cg_lift_basic(w, table->pc, f->portable, table->pc > lo,
            table->pc > lo ? cg_u32(f->nso->image + (size_t)(table->pc - f->base - 4)) : 0);
        if (ins.kind != CG_BR || (!table->all && !table->targets.size)) cg_fail(4, "jump table must describe an indirect branch with targets");
        if (i && f->tables[i - 1].pc == table->pc) cg_fail(4, "duplicate jump table address");
        for (size_t j = 0; j < table->targets.size; j++) validate_address(f, table->targets.items[j]);
    }
    line(b, cg_format("    FN_ENTER(0x%" PRIx64 "ull);", f->entry));
    if (eh) {
        line(b, cg_format("    EH_ENTER(0x%" PRIx64 "ull, 0x%" PRIx64 "ull);", f->entry, f->end));
        cg_buffer(b, "    if (EH_SETJMP()) { switch (c->pc) { ", strlen("    if (EH_SETJMP()) { switch (c->pc) { "));
        cases(b, &pads); line(b, " default: rt_nle_fatal(c); } }");
    }
    AsmInstruction batch[24]; size_t batch_count = 0;
    InsnKind last = CG_PENDING;
    for (uint64_t pc = f->entry; pc < f->end; pc += 4) {
        uint32_t w = cg_u32(f->nso->image + (size_t)(pc - f->base));
        Instruction ins = cg_lift_basic(w, pc, f->portable, pc > lo, pc > lo ? cg_u32(f->nso->image + (size_t)(pc - f->base - 4)) : 0);
        if (ins.kind == CG_PENDING) cg_fail(4, "function contains an instruction family not yet implemented in native emission");
        if ((ins.kind == CG_B || ins.kind == CG_BCOND) && !ins.negative_target && ins.target >= f->entry && ins.target < f->end
            && !f->table_count && !contains(&labels, ins.target) && !contains(&pads, ins.target))
            cg_fail(4, "local branch target missing from supplied analysis labels");
        if (f->table_count || contains(&labels, pc) || contains(&pads, pc)) {
            flush_assembly(b, batch, &batch_count); line(b, cg_format("L_%" PRIx64 ":;", pc));
        }
        if (ins.kind == CG_ASM) {
            if (batch_count == 24) flush_assembly(b, batch, &batch_count);
            batch[batch_count++] = ins.assembly;
            if (!cg_emit_asm_batch(batch, batch_count, NULL)) {
                batch_count--; flush_assembly(b, batch, &batch_count);
                batch[batch_count++] = ins.assembly;
                if (!cg_emit_asm_batch(batch, batch_count, NULL)) cg_fail(4, "single instruction exceeds scratch register capacity");
            }
            last = CG_ASM; continue;
        }
        flush_assembly(b, batch, &batch_count);
        const char *statement = NULL;
        switch (ins.kind) {
            case CG_OP: case CG_TRAP: statement = ins.code; break;
            case CG_B: statement = jump(f, &out, ins.target, ins.negative_target, eh); break;
            case CG_BCOND: statement = cg_format("if (%s) { %s }", ins.condition, jump(f, &out, ins.target, ins.negative_target, eh)); break;
            case CG_BL:
                if (!ins.negative_target && ins.target >= lo && ins.target < hi && !(ins.target % 4)) {
                    cg_address(&out.refs, ins.target);
                    statement = cg_format("c->x[30] = 0x%" PRIx64 "ull; f_%" PRIx64 "(c);", pc + 4, ins.target);
                } else statement = cg_format("c->x[30] = 0x%" PRIx64 "ull; c->pc = %s; rt_dispatch(c);", pc + 4, hex_target(ins.target, ins.negative_target));
                break;
            case CG_BLR: statement = cg_format("c->pc = %s; c->x[30] = 0x%" PRIx64 "ull; rt_dispatch(c);", ins.target_expression, pc + 4); break;
            case CG_BR: {
                const JumpTable *table = table_at(f, pc);
                if (table) {
                    if (!table->all) { cg_printf(b, "    switch (%s) { ", ins.target_expression); cases(b, &table->targets); line(b, " default: break; }"); }
                    line(b, cg_format("    c->pc = %s; goto L_dispatch;", ins.target_expression));
                    /* Preserve reference last-kind handling on a table branch. */
                    continue;
                }
                statement = cg_format("c->pc = %s; %s", ins.target_expression, tail("rt_dispatch(c)", eh)); break;
            }
            case CG_RET: statement = eh ? "{ EH_POP(); return; }" : "return;"; break;
            case CG_ASM: cg_fail(4, "unflushed assembly instruction");
            case CG_PENDING: cg_fail(4, "pending instruction in emission");
        }
        line(b, cg_format("    %s", statement)); last = ins.kind;
    }
    flush_assembly(b, batch, &batch_count);
    if (last != CG_B && last != CG_BR && last != CG_RET && last != CG_TRAP)
        line(b, cg_format("    %s", f->end < hi ? jump(f, &out, f->end, false, eh) : cg_format("rt_udf(c, 0x%" PRIx64 "ull);", f->end)));
    if (f->table_count) {
        line(b, "L_dispatch:"); cg_buffer(b, "    switch (c->pc) { ", strlen("    switch (c->pc) { "));
        for (uint64_t pc = f->entry; pc < f->end; pc += 4) cg_printf(b, "%scase 0x%" PRIx64 "ull: goto L_%" PRIx64 ";", pc == f->entry ? "" : " ", pc, pc);
        line(b, " default: break; }"); line(b, cg_format("    %s", tail("rt_dispatch(c)", eh)));
    }
    line(b, "}"); cg_unique(&out.refs); return out;
}
