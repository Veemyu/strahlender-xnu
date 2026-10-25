/* SPDX-License-Identifier: MIT */
#ifndef BDSP_EMITTER_H
#define BDSP_EMITTER_H
#include "lifter.h"
typedef struct { uint64_t pc; Addresses targets; bool all; } JumpTable;
typedef struct {
    const Nso *nso;
    uint64_t base, entry, end;
    bool portable;
    const char *hle;
    Addresses labels, nle;
    JumpTable *tables;
    size_t table_count;
} EmitFunction;
typedef struct { Buffer code; Addresses refs; } EmittedFunction;
EmittedFunction cg_emit_function(const EmitFunction *function);
int cg_emit_checkpoint(int argc, char **argv);
#endif
