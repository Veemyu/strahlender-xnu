/* SPDX-License-Identifier: MIT */
#ifndef BDSP_ANALYSIS_H
#define BDSP_ANALYSIS_H
#include "emitter.h"
typedef struct {
    Addresses boundaries, entries, landing_pads, returns;
    size_t adr_bases_kept;
} InitialAnalysis;
InitialAnalysis cg_initial_analysis(const Nso *nso, uint64_t base, const Addresses *extra_setjmp, const char *entry_offsets);
typedef struct {
    uint64_t entry, end;
    Addresses labels, external;
    JumpTable *tables; size_t table_count;
} FunctionPlan;
typedef struct {
    InitialAnalysis initial;
    FunctionPlan **functions; size_t count, rounds;
    size_t jump_tables, all_label_branches, dispatch_branches;
} ModuleAnalysis;
ModuleAnalysis cg_analyze_module(const Nso *nso, uint64_t base, bool portable, const Addresses *setjmp, const char *entry_offsets, size_t jobs);
int cg_analyze_checkpoint(int argc, char **argv);
#endif
