// Reader for the Unity shader-program container of Switch bundles (own code of the strahlender-xnu project).
//
// Layout (see docs/referenz-las-shader.md and scripts/shader_map.py:parse_nvn):
//   0x00 u32 magic 0x0C07513C, 0x04 u32 version, 0x18 u32 keyword count n
//   0x1C n x {u32 len, text (len bytes incl. NUL), padded to 4}  (global keywords), u32 m, m x {...} (local keywords)
//   then the control header: +0x00 total, +0x04 stage (0 vertex, 1 fragment), +0x0C data offset, +0x10 data size
//   (not used: they do not always cover the code), +0x14 magic 0x98761234; after it the GLSLC data with the Maxwell blob that starts with 0x12345678.
#pragma once
#include <stddef.h>
#include <stdint.h>

#define UNITY_PROGRAM_MAGIC 0x0C07513Cu
#define UNITY_CONTROL_MAGIC 0x98761234u
#define MAXWELL_BLOB_MAGIC 0x12345678u

typedef struct {
    uint32_t version;
    uint32_t keyword_count;  // global + local
    int stage;               // STAGE_* of shader.h (vertex / fragment), -1 if the container names another stage
    size_t blob_offset;      // start of the Maxwell blob (the 0x12345678 NVN header) inside the container
    size_t blob_size;        // bytes from blob_offset to the end of the program (code, constants, trailing data)
} UnityProgram;

// 0 on success, otherwise a static error text.
const char *unity_program_parse(const uint8_t *d, size_t n, UnityProgram *out);
