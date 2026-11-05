// Names of the nn::fs results a guest abort (svcBreak) usually carries, and what they say about the guest. Own code.
#pragma once
#include <stdint.h>

// module 2 is nn::fs; the numbers are the descriptions of the SDK (value >> 9)
static inline const char *nn_result_name(uint32_t v) {
    if ((v & 0x1ff) != 2) return NULL;
    switch (v >> 9) {
    case 1: return "fs PathNotFound";
    case 2: return "fs PathAlreadyExists";
    case 7: return "fs TargetLocked";
    case 8: return "fs DirectoryNotEmpty";
    case 6061: return "fs InvalidOffset";
    case 6062: return "fs InvalidSize";
    case 6063: return "fs NullptrArgument";
    case 6064: return "fs InvalidAlignment";
    case 6065: return "fs InvalidMountName";
    default: return NULL;
    }
}

// The SDK checks the arguments of ReadFile before it talks to the file system service, so these never come from our IPC answers.
static inline const char *nn_result_hint(uint32_t v) {
    if ((v & 0x1ff) != 2) return NULL;
    switch (v >> 9) {
    case 6061: case 6062: case 6063: case 6064:
        return "rejected inside the guest SDK before any file system request: the game passed a bad argument (6063: a null buffer, "
               "usually its own allocation that failed)";
    default: return NULL;
    }
}
