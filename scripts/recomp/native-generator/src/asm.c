/* SPDX-License-Identifier: MIT. Exact AArch64 inline-assembly batch rendering. */
#include "lifter.h"
#include <inttypes.h>
#include <string.h>

typedef struct { unsigned guest, scratch; } MappedRegister;
typedef struct { unsigned scratch; uint64_t value; bool negative; } MappedConstant;
static void asm_line(Buffer *b, bool *first, const char *line) {
    if (!*first) cg_buffer(b, "\\n\\t", 4);
    *first = false; cg_buffer(b, line, strlen(line));
}
bool cg_emit_asm_batch(const AsmInstruction *batch, size_t count, const char **result) {
    if (!count || count > 24) return false;
    unsigned scratch[] = {9, 10, 11, 12, 13, 14, 15, 16, 17};
    MappedRegister map[9]; MappedConstant constants[9]; uint32_t words[24], vregs = 0;
    size_t mapped = 0, const_count = 0; bool flags = false;
    for (size_t i = 0; i < count; i++) {
        const AsmInstruction *ins = &batch[i];
        if (ins->gpr_count > 3 || ins->constant_count > 1) cg_fail(4, "invalid assembly metadata");
        vregs |= ins->vregs; flags |= ins->flags; uint32_t w = ins->word;
        for (size_t j = 0; j < ins->gpr_count; j++) {
            unsigned g = ins->gprs[j].reg, position = ins->gprs[j].position;
            if (g > 31 || position > 27) cg_fail(4, "invalid assembly register metadata");
            size_t at = 0; while (at < mapped && map[at].guest != g) at++;
            if (at == mapped) {
                if (mapped + const_count >= 9) return false;
                map[at] = (MappedRegister){g, scratch[mapped + const_count]}; mapped++;
            }
            w = (w & ~(31u << position)) | (map[at].scratch << position);
        }
        for (size_t j = 0; j < ins->constant_count; j++) {
            if (mapped + const_count >= 9) return false;
            unsigned s = scratch[mapped + const_count], position = ins->constants[j].position;
            if (position > 27) cg_fail(4, "invalid assembly constant metadata");
            constants[const_count++] = (MappedConstant){s, ins->constants[j].value, ins->constants[j].negative};
            w = (w & ~(31u << position)) | (s << position);
        }
        words[i] = w;
    }
    if (!result) return true;
    Buffer b = {0}; cg_buffer(&b, "__asm__ volatile(\"", strlen("__asm__ volatile(\"")); bool first = true;
    for (size_t i = 0; i < mapped; i++) asm_line(&b, &first, cg_format("ldr x%u, [%%0, #%u]", map[i].scratch, map[i].guest == 31 ? 256u : 8u * map[i].guest));
    for (size_t i = 0; i < const_count; i++) asm_line(&b, &first, cg_format("mov x%u, %%%zu", constants[i].scratch, i + 1));
    for (unsigned v = 0; v < 32; v++) if (vregs & (UINT32_C(1) << v)) asm_line(&b, &first, cg_format("ldr q%u, [%%0, #%u]", v, 512u + 16u * v));
    if (flags) { asm_line(&b, &first, "ldr x16, [%0, #272]"); asm_line(&b, &first, "msr nzcv, x16"); }
    for (size_t i = 0; i < count; i++) asm_line(&b, &first, cg_format(".inst 0x%08" PRIx32, words[i]));
    if (flags) { asm_line(&b, &first, "mrs x16, nzcv"); asm_line(&b, &first, "str x16, [%0, #272]"); }
    for (unsigned v = 0; v < 32; v++) if (vregs & (UINT32_C(1) << v)) asm_line(&b, &first, cg_format("str q%u, [%%0, #%u]", v, 512u + 16u * v));
    for (size_t i = 0; i < mapped; i++) asm_line(&b, &first, cg_format("str x%u, [%%0, #%u]", map[i].scratch, map[i].guest == 31 ? 256u : 8u * map[i].guest));
    cg_buffer(&b, "\" :: \"r\"(c)", strlen("\" :: \"r\"(c)"));
    for (size_t i = 0; i < const_count; i++) cg_printf(&b, ", \"r\"(0x%s%" PRIx64 "ull)", constants[i].negative ? "-" : "", constants[i].value);
    cg_buffer(&b, " : ", 3); const char *separator = "";
    for (unsigned v = 0; v < 32; v++) if (vregs & (UINT32_C(1) << v)) { cg_printf(&b, "%s\"v%u\"", separator, v); separator = ", "; }
    bool clobber[32] = {0}; clobber[16] = flags;
    for (size_t i = 0; i < mapped; i++) clobber[map[i].scratch] = true;
    for (size_t i = 0; i < const_count; i++) clobber[constants[i].scratch] = true;
    for (unsigned s = 0; s < 32; s++) if (clobber[s]) { cg_printf(&b, "%s\"x%u\"", separator, s); separator = ", "; }
    cg_printf(&b, "%s\"cc\", \"memory\");", separator); cg_buffer(&b, "", 1); *result = (char *)b.data; return true;
}
