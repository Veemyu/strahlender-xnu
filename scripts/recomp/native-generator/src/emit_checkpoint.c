/* SPDX-License-Identifier: MIT. Explicit-analysis development checkpoint. */
#include "emitter.h"
#include <inttypes.h>
#include <string.h>
static void parse_table(JumpTable *t, const char *text) {
    char *copy = cg_string(text, strlen(text)), *separator = strchr(copy, '=');
    if (!separator) cg_fail(2, "table must be PC=all or PC=TARGET,TARGET");
    *separator++ = 0; t->pc = cg_number(copy);
    if (!strcmp(separator, "all")) { t->all = true; return; }
    while (*separator) {
        char *next = strchr(separator, ','); if (next) *next++ = 0;
        cg_address(&t->targets, cg_number(separator));
        if (!next) break;
        if (!*next) cg_fail(2, "empty table target");
        separator = next;
    }
}
int cg_emit_checkpoint(int argc, char **argv) {
    cg_phase = "emit-function";
    if (argc < 1) cg_fail(2, "emit-function requires an NSO");
    const char *path = argv[0], *output = NULL; bool json = false, have_base = false, have_entry = false, have_end = false;
    EmitFunction function = {.tables = cg_alloc((size_t)argc, sizeof(JumpTable))};
    for (int i = 1; i < argc; i++) {
        const char *option = argv[i];
        if (!strcmp(option, "--json")) { json = true; continue; }
        if (!strcmp(option, "--events=jsonl")) continue;
        if (++i == argc) cg_fail(2, "missing emission option value");
        if (!strcmp(option, "--base")) { function.base = cg_number(argv[i]); have_base = true; }
        else if (!strcmp(option, "--entry")) { function.entry = cg_number(argv[i]); have_entry = true; }
        else if (!strcmp(option, "--end")) { function.end = cg_number(argv[i]); have_end = true; }
        else if (!strcmp(option, "--label")) cg_address(&function.labels, cg_number(argv[i]));
        else if (!strcmp(option, "--nle")) cg_address(&function.nle, cg_number(argv[i]));
        else if (!strcmp(option, "--table")) parse_table(&function.tables[function.table_count++], argv[i]);
        else if (!strcmp(option, "--hle")) function.hle = cg_utf8_normalize(argv[i]);
        else if (!strcmp(option, "--out")) output = argv[i];
        else if (!strcmp(option, "--simd")) {
            if (strcmp(argv[i], "asm") && strcmp(argv[i], "c")) cg_fail(2, "SIMD mode must be asm or c");
            function.portable = !strcmp(argv[i], "c");
        } else cg_fail(2, "unknown emission option");
    }
    if (!have_base || !have_entry || !have_end) cg_fail(2, "emit-function requires --base, --entry and --end");
    Nso nso = cg_nso(path); function.nso = &nso; cg_phase = "emit-function";
    cg_address(&function.labels, function.entry);
    EmittedFunction emitted = cg_emit_function(&function); Buffer rendered = {0};
    if (json) {
        cg_buffer(&rendered, "{\"code\":", 8);
        cg_buffer(&emitted.code, "", 1); cg_json_string(&rendered, (char *)emitted.code.data);
        cg_buffer(&rendered, ",\"refs\":[", 9);
        for (size_t i = 0; i < emitted.refs.size; i++) cg_printf(&rendered, "%s%" PRIu64, i ? "," : "", emitted.refs.items[i]);
        cg_buffer(&rendered, "]}\n", 3);
    } else rendered = emitted.code;
    if (output) cg_write(output, rendered.data, rendered.size);
    else if (fwrite(rendered.data, 1, rendered.size, stdout) != rendered.size || fflush(stdout)) cg_fail(5, "cannot write emitted function");
    return 0;
}
