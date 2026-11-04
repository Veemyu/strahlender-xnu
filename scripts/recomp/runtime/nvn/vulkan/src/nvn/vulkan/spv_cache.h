// GLSL -> SPIR-V exactly as the renderer builds it, and the name under which the result is cached. Shared by shaders.c (run
// time) and spirv_warm.c (install time, fills the cache before the first start): one definition, so a prebuilt file is
// the file the renderer would have written itself.
#pragma once
#include <shaderc/shaderc.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum { SPIRV_VERTEX = 0, SPIRV_FRAGMENT = 1, SPIRV_COMPUTE = 5 };  // the translator's STAGE_* values (shader.h; shaders.c checks)

// Cache file name: spirv/<hash of stage + source>.spv. A translator change changes the source, so the old file is never hit.
static inline uint64_t spirv_key(const char *src, int stage) {
    uint64_t h = (0xcbf29ce484222325ull ^ (uint64_t)stage) + 3;  // + version of the post-processing (no_contraction)
    for (const char *p = src; *p; p++) { h ^= (uint8_t)*p; h *= 0x100000001B3ull; }
    return h;
}

static inline void spirv_file_name(char *out, size_t n, uint64_t key) {
    snprintf(out, n, "spirv/%016llx.spv", (unsigned long long)key);
}

// Vertex shaders: every float add/sub/mul/div/fma gets NoContraction, so no compiler fuses or splits them. Depth
// pre-pass and colour pass are different shaders computing the same position, and the colour pass tests EQUAL:
// any difference in fusing leaves holes (foliage flickered black). GLSL's `precise gl_Position` only covers what
// glslang traces back from the position, which the translated register code defeats.
static inline int spirv_float_arith(const uint32_t *w, uint32_t wc, uint32_t op) {
    switch (op) {
    case 127: case 129: case 131: case 133: case 136:  // FNegate FAdd FSub FMul FDiv
    case 142: case 143: case 144: case 145: case 146: case 148:  // vector/matrix products, Dot
        return 1;
    case 12: return wc >= 5 && w[4] == 50;  // ExtInst GLSL.std.450 Fma
    default: return 0;
    }
}

static inline uint32_t *spirv_no_contraction(uint32_t *spv, size_t *nwords) {
    enum { OP_DECORATE = 71, DEC_NO_CONTRACTION = 42 };
    size_t n = *nwords, insert = 0, count = 0;
    uint32_t bound = spv[3];
    uint8_t *done = calloc(bound, 1);  // already decorated (glslang does it for what it traces from precise)
    for (size_t i = 5; i < n;) {
        uint32_t wc = spv[i] >> 16, op = spv[i] & 0xFFFF;
        if (!wc) break;
        if (!insert && op >= 19 && op <= 39) insert = i;  // first type declaration: end of the annotations
        if (op == OP_DECORATE && wc >= 3 && spv[i + 2] == DEC_NO_CONTRACTION && spv[i + 1] < bound) done[spv[i + 1]] = 1;
        i += wc;
    }
    for (size_t i = 5; i < n;) {
        uint32_t wc = spv[i] >> 16, op = spv[i] & 0xFFFF;
        if (!wc) break;
        if (spirv_float_arith(spv + i, wc, op) && spv[i + 2] < bound && !done[spv[i + 2]]) count++;
        i += wc;
    }
    if (!insert || !count) { free(done); return spv; }
    uint32_t *out = malloc((n + count * 3) * 4);
    memcpy(out, spv, insert * 4);
    size_t o = insert;
    for (size_t i = 5; i < n;) {
        uint32_t wc = spv[i] >> 16, op = spv[i] & 0xFFFF;
        if (!wc) break;
        if (spirv_float_arith(spv + i, wc, op) && spv[i + 2] < bound && !done[spv[i + 2]]) {
            done[spv[i + 2]] = 1;
            out[o++] = 3u << 16 | OP_DECORATE;
            out[o++] = spv[i + 2];  // result id
            out[o++] = DEC_NO_CONTRACTION;
        }
        i += wc;
    }
    memcpy(out + o, spv + insert, (n - insert) * 4);
    *nwords = o + (n - insert);
    free(done);
    free(spv);
    return out;
}

// No spirv-opt by default: it rewrote the depth pre-pass and colour-pass vertex shaders differently enough that
// their depths stopped matching (EQUAL test: black holes in foliage), and it was most of the compile time; the
// driver optimises anyway. BDSP_VK_OPT=1 turns it back on (experiments, never with a prebuilt cache).
// malloc'd SPIR-V words, or NULL with the compiler's message in err. comp: one shaderc compiler per calling thread.
static inline uint32_t *spirv_compile(shaderc_compiler_t comp, const char *src, int stage, const char *name, size_t *nwords,
                                      char *err, size_t errn) {
    shaderc_shader_kind kind = stage == SPIRV_VERTEX ? shaderc_vertex_shader
                               : stage == SPIRV_FRAGMENT ? shaderc_fragment_shader : shaderc_compute_shader;
    shaderc_compile_options_t o = shaderc_compile_options_initialize();
    shaderc_compile_options_set_target_env(o, shaderc_target_env_vulkan, shaderc_env_version_vulkan_1_3);
    shaderc_compile_options_set_optimization_level(o, getenv("BDSP_VK_OPT") ? shaderc_optimization_level_performance
                                                                              : shaderc_optimization_level_zero);
    shaderc_compilation_result_t r = shaderc_compile_into_spv(comp, src, strlen(src), kind, name, "main", o);
    shaderc_compile_options_release(o);
    uint32_t *out = NULL;
    if (shaderc_result_get_compilation_status(r) != shaderc_compilation_status_success) {
        if (err && errn) snprintf(err, errn, "%s", shaderc_result_get_error_message(r));
    } else {
        size_t n = shaderc_result_get_length(r);
        out = malloc(n);
        memcpy(out, shaderc_result_get_bytes(r), n);
        *nwords = n / 4;
        if (stage == SPIRV_VERTEX) out = spirv_no_contraction(out, nwords);
    }
    shaderc_result_release(r);
    return out;
}
