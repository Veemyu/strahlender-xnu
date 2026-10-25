/* SPDX-License-Identifier: MIT */
#ifndef BDSP_LIFTER_H
#define BDSP_LIFTER_H
#include "codegen.h"
typedef enum { CG_OP, CG_TRAP, CG_B, CG_BCOND, CG_BL, CG_BLR, CG_BR, CG_RET, CG_PENDING } InsnKind;
typedef struct {
    InsnKind kind;
    const char *code, *condition, *target_expression;
    uint64_t target;
    bool numeric_target, negative_target;
} Instruction;
Instruction cg_lift_basic(uint32_t word, uint64_t pc, bool portable, bool has_previous, uint32_t previous);
int cg_decode(int argc, char **argv);
#endif
