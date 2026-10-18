// Maxwell (GM20B) shader translation to Metal Shading Language (macOS) or Vulkan GLSL (Windows; compiled to
// SPIR-V at runtime with shaderc). ShaderKey.glsl selects the dialect; the MSL output does not depend on it.
//
// GLSL contract (what the Vulkan renderer binds):
//  - `#version 460`, entry point `main`. Descriptor set: vertex 0, fragment 1, compute 0.
//  - hardware cbuf k -> binding k: `layout(std140, set=S, binding=k) uniform CB<k> { uvec4 cb<k>[N]; };`
//    (anonymous block). N = max(cbuf_size[k] / 16, highest constant-index vec4 + 1), and at least 4096 when
//    cbuf_dynamic has bit k (the renderer binds up to 64 KB). Register-indexed reads are clamped to N - 1.
//  - global memory (LDG/STG) -> binding GMEM_BUFFER_INDEX (17):
//    `layout(std430, set=S, binding=17) [readonly] buffer GMem { uint w[]; } gmem_;`, 32-bit words relative to
//    maxwell_gmem_base. `readonly` unless the shader stores (needs vertexPipeline/fragmentStoresAndAtomics then);
//    byte / short stores are atomicAnd + atomicOr on the containing word.
//  - rscale table -> binding 18: `uniform RScale { vec4 rscale[65]; };` (std140, the MSL buffer 18 contents).
//  - (XNU: the per-draw tint of the original, binding 19, was removed.)
//  - texture slot i (ShaderInfo.tex[i]) -> binding 32 + i, a combined image sampler: sampler1D/2D/3D/Cube/
//    1DArray/2DArray/CubeArray, or its *Shadow variant when tex[i].shadow.
//  - vertex inputs `layout(location=i) in vec4|ivec4|uvec4 a<i>;` (key->attr_kind); varyings: location i =
//    generic attribute i, `vec4 v<i>` (fragment side flat / noperspective as in MSL); `invariant gl_Position`;
//    gl_PointSize when writes_point_size. Fragment outputs `layout(location=rt) out vec4|ivec4|uvec4 c<rt>;`,
//    gl_FragDepth when writes_depth.
//  - clip space exactly as the MSL output (key->flip_y / depth_minus_one epilogue unchanged): the renderer uses
//    a negative-height viewport so Vulkan matches Metal's y-up NDC, clip z in [0, 1].
//  - compute: `layout(local_size_x_id = 0, local_size_y_id = 1, local_size_z_id = 2) in;` (spec constants 0..2).
//  - extensions: GL_EXT_shader_explicit_arithmetic_types_int64 (64-bit carry / address math -> shaderInt64),
//    GL_KHR_shader_subgroup_basic/_shuffle/_shuffle_relative (SHFL, FSWZADD lane: fragment/compute subgroup
//    support), GL_EXT_texture_shadow_lod (explicit-LOD array / cube shadow lookups).
//
// Derived from LASRecomp (https://github.com/peiikai/LASRecomp, commit 09f8e5e), MIT License, Copyright (c) 2026 Peiikai.
// See ../LICENSE-LASRecomp and ../NOTICE.md. Modifications for the strahlender-xnu project are marked "XNU:".
#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

enum { STAGE_VERTEX = 0, STAGE_FRAGMENT = 1, STAGE_GEOMETRY = 2, STAGE_TESS_CTRL = 3, STAGE_TESS_EVAL = 4,
       STAGE_COMPUTE = 5 };

enum { TEXTYPE_1D, TEXTYPE_2D, TEXTYPE_3D, TEXTYPE_CUBE, TEXTYPE_2D_ARRAY, TEXTYPE_CUBE_ARRAY, TEXTYPE_1D_ARRAY,
       TEXTYPE_BUFFER, TEXTYPE_2D_MS };

typedef struct {
    uint8_t attr_kind[32];  // vertex inputs: 0 float, 1 signed int, 2 unsigned int
    uint8_t rt_kind[8];     // fragment outputs: 0 float, 1 signed int, 2 unsigned int
    bool depth_minus_one;   // NVN depth mode [-1,1]: remap clip z
    bool flip_y;            // lower-left window origin
    bool flip_x;            // mirror the image left to right (mirror mode's scene composite). (In the padding
                            // after flip_y: keys without it hash as before - shader caches stay valid.)
    uint32_t vs_out_mask;   // fragment: varyings the vertex shader provides
    uint8_t glsl;           // emit Vulkan GLSL (see the contract above) instead of MSL
    bool no_rscale;         // XNU: plain window coordinates / texture sizes, never read the resolution-scale table
    bool annotate;          // XNU: comment every instruction with its pc and 64-bit word (was LARECOMP_SAVE_MSL)
    bool fast_math;         // XNU: MSL without the pragmas that disable fast math and FMA contraction (original behaviour)
    bool half_compat;       // XNU: Ryujinx-compatible half precision: no rounding to fp16 between half operations (see translate.c hstore)
} ShaderKey;

typedef struct {
    uint32_t handle_offset;  // byte offset of the texture handle in the bound texture cbuf
    uint8_t type;            // TEXTYPE_*
    bool shadow, is_array, is_image, bindless;
    uint32_t bindless_cbuf, bindless_offset;
    // XNU: TEX.B. The handle register is built from one or two words of a constant buffer (handle = word0 | word1,
    // NVN: texture id in the low 20 bits, sampler id in the upper 12). bindless_cbuf is the buffer, bindless_offset
    // the byte offset of the word that is OR-ed in last (texture table), bindless_sampler_offset the word it is
    // combined with (sampler table). bindless_has_sampler is false when the handle is a single word.
    bool bindless_has_sampler;
    uint32_t bindless_sampler_offset;
} ShaderTexture;

typedef struct {
    int stage;
    char *msl;              // complete MSL or GLSL source (MSL entry "main0", GLSL "main"); NULL on failure
    uint32_t cbuf_mask;     // hardware constant buffers read
    uint32_t cbuf_size[18];
    uint32_t cbuf_dynamic;  // cbufs indexed with a register: bind the whole buffer
    int ntex;
    ShaderTexture tex[64];
    uint32_t attr_mask;     // vertex: input attributes; fragment: input varyings
    uint32_t out_mask;      // vertex: output varyings; fragment: render targets written
    bool writes_depth, uses_discard, writes_point_size;
    bool uses_gmem;         // global memory access: bind the guest heap at GMEM_BUFFER_INDEX
    bool uses_gmem_map;     // (GLSL compute only) gmem loads look their address up in GMap (uniform, binding
                            // GMAP_BUFFER_INDEX) and read GFast (storage, GFAST_BUFFER_INDEX) - a device-local copy of the
                            // dispatch's storage buffers - when found, stores too (copied back after the dispatch).
                            // runtime/nvn/vulkan/exec.c
    bool uses_gmem_store;   // writes global memory (STG)
    bool uses_rscale;       // reads the resolution-scale table (fragment/compute buffer 18): float4 [0] = render
                            // target scale, [1 + i] = allocation scale of texture i
    // XNU: data for the resource map (maxwell2msl --info): statically addressed byte range of each cbuf (end = one past
    // the last byte read; min > end when only register-indexed reads exist), component masks (bit i = .xyzw) of the
    // stage inputs / outputs per generic attribute, and the fragment inputs with flat interpolation.
    uint32_t cbuf_min_off[18], cbuf_end_off[18];
    uint32_t cbuf1_blob_offset;  // XNU: where the compiler constants (cbuf 1) start in the blob passed to the translator
    uint8_t in_comp[32], out_comp[32];
    uint32_t flat_mask, noperspective_mask;
    uint32_t local_mem;     // bytes of local memory
    uint32_t num_insts;
    char error[256];        // set when translation fails
} ShaderInfo;

// Global memory (LDG/STG) is addressed through one buffer that wraps the guest heap.
#define GMEM_BUFFER_INDEX 17
// (GLSL compute, Vulkan) the fast copy of a dispatch's storage buffers: its address table and its data
#define GMAP_BUFFER_INDEX 20
#define GFAST_BUFFER_INDEX 21
#define GMAP_MAX 16  // ranges in the table (GMap { uvec4 gmap[GMAP_MAX + 1]; }: [i] = addr lo, addr hi, size, word offset;
                     // [GMAP_MAX].x = count)
extern uint64_t maxwell_gmem_base, maxwell_gmem_size;

// XNU: coverage survey. With a Survey passed to maxwell_translate_ex() the translator does not stop at the first
// unsupported construct: it records every problem (unknown opcode or partially supported form) and goes on.
#define SURVEY_MAX_ITEMS 64
#define SURVEY_NAME_LEN 64
typedef struct {
    char name[SURVEY_NAME_LEN];  // "op<top 12 bits in hex>" for unknown opcodes, else the translator's message
    uint32_t opcode_bits;        // top 12 bits of the first offending word
    uint64_t example_word;
    uint32_t count;              // occurrences in the shader
    bool unknown_opcode;         // no decoder pattern matched (otherwise: recognised, but this form is unsupported)
} SurveyItem;
typedef struct {
    SurveyItem items[SURVEY_MAX_ITEMS];
    int n;
    bool overflow;                // more distinct problems than SURVEY_MAX_ITEMS
    uint32_t num_problem_insts;   // instructions with at least one problem (counted per problem)
} Survey;

// code: shader binary (with the 0x50-byte SPH header for graphics stages)
ShaderInfo *maxwell_translate(const uint8_t *code, size_t max_size, int stage, const ShaderKey *key);
// XNU: same, with an optional survey (NULL = original behaviour: stop at the first problem, error in ShaderInfo.error)
ShaderInfo *maxwell_translate_ex(const uint8_t *code, size_t max_size, int stage, const ShaderKey *key, Survey *sv);
void maxwell_free(ShaderInfo *s);
// Disassemble for debugging (writes text to f).
void maxwell_disassemble(const uint8_t *code, size_t max_size, int stage, void *file);
