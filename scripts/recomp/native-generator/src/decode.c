/* SPDX-License-Identifier: MIT. Diagnostic IR stream for differential tests. */
#include "lifter.h"
#include <ctype.h>
#include <errno.h>
#include <inttypes.h>
#include <stdlib.h>
#include <string.h>
static void nullable(Buffer *b, const char *s) { if (s) cg_json_string(b, s); else cg_buffer(b, "null", 4); }
int cg_decode(int argc, char **argv) {
    uint64_t pc = 0; bool have_pc = false, portable = false, have_previous = false; uint32_t previous = 0;
    cg_phase = "decode";
    for (int i = 0; i < argc; i++) {
        const char *option = argv[i];
        if (++i == argc) cg_fail(2, "missing decode option value");
        if (!strcmp(option, "--pc")) { pc = cg_number(argv[i]); have_pc = true; }
        else if (!strcmp(option, "--simd")) {
            if (strcmp(argv[i], "asm") && strcmp(argv[i], "c")) cg_fail(2, "SIMD mode must be asm or c");
            portable = !strcmp(argv[i], "c");
        } else if (!strcmp(option, "--previous-word")) {
            uint64_t value = cg_number(argv[i]);
            if (value > UINT32_MAX) cg_fail(2, "previous instruction exceeds 32 bits");
            previous = (uint32_t)value; have_previous = true;
        } else cg_fail(2, "unknown decode option");
    }
    if (!have_pc) cg_fail(2, "decode requires --pc");
    const char *const names[] = {"op", "trap", "b", "bcond", "bl", "blr", "br", "ret", "pending"};
    char line[128];
    while (fgets(line, sizeof(line), stdin)) {
        void *mark = cg_mark();
        char *p = line; while (isspace((unsigned char)*p)) p++;
        if (!*p) { cg_rewind(mark); continue; }
        if (*p == '-' || *p == '+') cg_fail(2, "invalid instruction word");
        char *end; errno = 0; uintmax_t word = strtoumax(p, &end, 16);
        if (errno || p == end || word > UINT32_MAX) cg_fail(2, "invalid instruction word");
        while (isspace((unsigned char)*end)) end++;
        if (*end) cg_fail(2, "expected one hexadecimal instruction per line");
        Instruction ins = cg_lift_basic((uint32_t)word, pc, portable, have_previous, previous);
        Buffer b = {0};
        cg_printf(&b, "{\"handled\":%s,\"kind\":\"%s\",\"code\":", ins.kind == CG_PENDING ? "false" : "true", names[ins.kind]);
        cg_json_string(&b, ins.code ? ins.code : ""); cg_buffer(&b, ",\"target\":", 10);
        if (ins.numeric_target) cg_printf(&b, "%s%" PRIu64, ins.negative_target ? "-" : "", ins.target);
        else nullable(&b, ins.target_expression);
        cg_buffer(&b, ",\"cond\":", 8); nullable(&b, ins.condition); cg_buffer(&b, "}\n", 2);
        if (fwrite(b.data, 1, b.size, stdout) != b.size) cg_fail(5, "cannot write decoded instructions");
        cg_rewind(mark);
    }
    if (ferror(stdin)) cg_fail(5, "cannot read instruction stream");
    if (fflush(stdout)) cg_fail(5, "cannot finish decoded instructions");
    return 0;
}
