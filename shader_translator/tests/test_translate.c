// Unit tests for the translator core and the container reader. Only synthetic shaders built in memory, no game data.
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "container.h"
#include "shader.h"

static int failures, checks;
#define CHECK(cond)                                                                   \
    do {                                                                              \
        checks++;                                                                     \
        if (!(cond)) { failures++; fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond); } \
    } while (0)

// Words taken from real shaders (their encodings are what the translator decodes)
#define W_MOV_R3_RZ 0x5c9807800ff70003ull
#define W_EXIT 0xe30000000007000full
#define W_BRA_SELF_8 0xe2400fffff87000full    // displacement -8: targets itself
#define W_BRA_SELF_16 0xe2400fffff07000full   // displacement -16: targets the scheduling word before it (Unity's spelling)
#define W_NOP 0x50b0000000070f00ull
#define W_SCHED 0x001f8000fc0007ffull
#define W_HSETP2_CBUF 0x7e85038c0457ff07ull   // HSETP2, constant buffer form (c[3][0x114])
#define W_HSETP2_IMM 0x7e0883bc0f071207ull    // HSETP2, immediate form (1.0 on both halves)
#define W_BINDLESS_TEX 0xdeb80001a0b70008ull  // TEX.B: coordinates R0.., handle R11, results R8, R9
#define W_MOV_C2_168_R11 0x4c98078805a7000bull  // MOV R11, c[2][0x168]   (sampler word)
#define W_LOP_OR_C2_568_R11 0x4c47020815a70b0bull  // LOP.OR R11, R11, c[2][0x568]   (texture word)
#define W_MOV_C2_170_R11 0x4c98078805c7000bull  // MOV R11, c[2][0x170]
#define W_LOP_OR_C2_570_R11 0x4c47020815c70b0bull  // LOP.OR R11, R11, c[2][0x570]
#define W_MOV_C2_568_R11 0x4c98078815a7000bull  // MOV R11, c[2][0x568]   (a handle made of one word)
#define W_HMUL2_R7_R14 0x5d08000011c70e07ull  // HMUL2 R7 = R14.. * R28.. (both halves packed)
#define W_HMUL2_R7_R7 0x5d08000011c70707ull   // HMUL2 R7 = R7.. * R28..
#define W_UNKNOWN 0xfff0000000070001ull
#define W_UNKNOWN2 0xfee0000000070001ull

static uint8_t *make_blob(const uint64_t *code, size_t n, size_t *size, int graphics) {
    size_t hdr = graphics ? 0x80 : 0;
    *size = hdr + n * 8;
    uint8_t *b = calloc(1, *size);
    if (graphics) {
        uint32_t magic = 0x12345678u;
        memcpy(b, &magic, 4);
    }
    memcpy(b + hdr, code, n * 8);
    return b;
}

static ShaderInfo *translate(const uint64_t *code, size_t n, int stage, Survey *sv) {
    size_t size;
    uint8_t *b = make_blob(code, n, &size, stage != STAGE_COMPUTE);
    ShaderKey key = {0};
    key.no_rscale = true;
    ShaderInfo *s = maxwell_translate_ex(b, size, stage, &key, sv);
    free(b);
    return s;
}

static void test_minimal_vertex(void) {
    const uint64_t code[] = {W_SCHED, W_MOV_R3_RZ, W_EXIT, W_BRA_SELF_8};
    ShaderInfo *s = translate(code, 4, STAGE_VERTEX, NULL);
    CHECK(s->msl != NULL);
    CHECK(s->error[0] == 0);
    CHECK(s->num_insts == 2);
    CHECK(s->msl && strstr(s->msl, "vertex VOut main0(") != NULL);
    CHECK(s->msl && strstr(s->msl, "uint r3 = 0;") != NULL);
    maxwell_free(s);
}

static void test_minimal_fragment_and_compute(void) {
    const uint64_t code[] = {W_SCHED, W_MOV_R3_RZ, W_EXIT, W_BRA_SELF_8};
    ShaderInfo *f = translate(code, 4, STAGE_FRAGMENT, NULL);
    CHECK(f->msl && strstr(f->msl, "fragment FOut main0(") != NULL);
    maxwell_free(f);
    ShaderInfo *c = translate(code, 4, STAGE_COMPUTE, NULL);
    CHECK(c->msl && strstr(c->msl, "kernel void main0(") != NULL);
    maxwell_free(c);
}

static void test_unknown_stops_original_mode(void) {
    const uint64_t code[] = {W_SCHED, W_UNKNOWN, W_EXIT, W_BRA_SELF_8};
    ShaderInfo *s = translate(code, 4, STAGE_VERTEX, NULL);
    CHECK(s->msl == NULL);
    CHECK(strstr(s->error, "unknown instruction") != NULL);
    maxwell_free(s);
}

static void test_survey_collects_all(void) {
    // two unknown opcodes plus a TEX.B whose handle register was never built from cbuf words
    const uint64_t code[] = {W_SCHED, W_UNKNOWN, W_UNKNOWN2, W_MOV_R3_RZ,  //
                             W_SCHED, W_UNKNOWN, W_BINDLESS_TEX, W_EXIT,   //
                             W_SCHED, W_BRA_SELF_8, W_NOP, W_NOP};
    Survey sv;
    memset(&sv, 0, sizeof sv);
    ShaderInfo *s = translate(code, 12, STAGE_FRAGMENT, &sv);
    CHECK(s->error[0] == 0);  // survey mode never aborts
    CHECK(sv.n == 3);
    int unknown_ffff = -1, unknown_fee = -1, bindless = -1;
    for (int i = 0; i < sv.n; i++) {
        if (!strcmp(sv.items[i].name, "opfff")) unknown_ffff = i;
        if (!strcmp(sv.items[i].name, "opfee")) unknown_fee = i;
        if (!strcmp(sv.items[i].name, "bindless handle not from cbuf words")) bindless = i;
    }
    CHECK(unknown_ffff >= 0 && unknown_fee >= 0 && bindless >= 0);
    if (unknown_ffff >= 0) {
        CHECK(sv.items[unknown_ffff].count == 2);
        CHECK(sv.items[unknown_ffff].unknown_opcode);
        CHECK(sv.items[unknown_ffff].opcode_bits == 0xfff);
        CHECK(sv.items[unknown_ffff].example_word == W_UNKNOWN);
    }
    if (unknown_fee >= 0) CHECK(sv.items[unknown_fee].count == 1 && sv.items[unknown_fee].unknown_opcode);
    if (bindless >= 0) CHECK(sv.items[bindless].count == 1 && !sv.items[bindless].unknown_opcode);
    maxwell_free(s);
}

// HSETP2 with a constant buffer / immediate operand B used to be unknown opcodes (0x7e8 / 0x7e0).
static void test_hsetp2_forms(void) {
    const uint64_t code[] = {W_SCHED, W_HSETP2_CBUF, W_HSETP2_IMM, W_EXIT, W_SCHED, W_BRA_SELF_8, W_NOP, W_NOP};
    Survey sv;
    memset(&sv, 0, sizeof sv);
    ShaderInfo *s = translate(code, 8, STAGE_FRAGMENT, &sv);
    CHECK(sv.n == 0);
    CHECK(s->msl != NULL);
    CHECK(s->msl && strstr(s->msl, "float2 hx_") != NULL);
    CHECK(s->cbuf_mask == (1u << 3));
    CHECK(s->cbuf_min_off[3] == 0x114 && s->cbuf_end_off[3] == 0x118);  // statically addressed range of c[3]
    maxwell_free(s);
}

// TEX.B: the handle register is built as MOV R11, c[2][a]; LOP.OR R11, R11, c[2][b]
static void test_bindless_texture(void) {
    const uint64_t code[] = {W_SCHED, W_MOV_C2_168_R11, W_LOP_OR_C2_568_R11, W_BINDLESS_TEX,  //
                             W_SCHED, W_BINDLESS_TEX, W_EXIT, W_BRA_SELF_8};
    ShaderInfo *s = translate(code, 8, STAGE_FRAGMENT, NULL);
    CHECK(s->msl != NULL);
    CHECK(s->ntex == 1);  // the same handle twice: one slot
    if (s->ntex == 1) {
        const ShaderTexture *t = &s->tex[0];
        CHECK(t->bindless && t->bindless_cbuf == 2 && t->bindless_offset == 0x568);
        CHECK(t->bindless_has_sampler && t->bindless_sampler_offset == 0x168);
        CHECK(t->type == TEXTYPE_2D && !t->shadow && !t->is_array);
    }
    CHECK(s->msl && strstr(s->msl, "texture2d<float> t0 [[texture(0)]], sampler s0 [[sampler(0)]]") != NULL);
    CHECK(s->msl && strstr(s->msl, "t0.sample(s0, float2(as_type<float>(r0), as_type<float>(r1)))") != NULL);
    maxwell_free(s);

    // two different handles: two slots, in order of first use
    const uint64_t two[] = {W_SCHED, W_MOV_C2_168_R11, W_LOP_OR_C2_568_R11, W_BINDLESS_TEX,  //
                            W_SCHED, W_MOV_C2_170_R11, W_LOP_OR_C2_570_R11, W_BINDLESS_TEX,  //
                            W_SCHED, W_EXIT, W_BRA_SELF_8, W_NOP};
    s = translate(two, 12, STAGE_FRAGMENT, NULL);
    CHECK(s->msl != NULL && s->ntex == 2);
    if (s->ntex == 2) CHECK(s->tex[0].bindless_offset == 0x568 && s->tex[1].bindless_offset == 0x570 && s->tex[1].bindless_sampler_offset == 0x170);
    maxwell_free(s);

    // a handle made of one cbuf word has no sampler word
    const uint64_t one[] = {W_SCHED, W_MOV_C2_568_R11, W_BINDLESS_TEX, W_EXIT, W_SCHED, W_BRA_SELF_8, W_NOP, W_NOP};
    s = translate(one, 8, STAGE_FRAGMENT, NULL);
    CHECK(s->msl != NULL && s->ntex == 1);
    if (s->ntex == 1) CHECK(s->tex[0].bindless && !s->tex[0].bindless_has_sampler && s->tex[0].bindless_offset == 0x568);
    maxwell_free(s);

    // an unresolved handle stops the original mode with a clear message
    const uint64_t bad[] = {W_SCHED, W_BINDLESS_TEX, W_EXIT, W_BRA_SELF_8};
    s = translate(bad, 4, STAGE_FRAGMENT, NULL);
    CHECK(s->msl == NULL && strstr(s->error, "bindless handle") != NULL);
    maxwell_free(s);

    // another write to the register in between resets the provenance
    const uint64_t overwritten[] = {W_SCHED, W_MOV_C2_168_R11, W_LOP_OR_C2_568_R11, 0x5c9807800ff7000bull,  // MOV R11, RZ
                                    W_SCHED, W_BINDLESS_TEX, W_EXIT, W_BRA_SELF_8};
    s = translate(overwritten, 8, STAGE_FRAGMENT, NULL);
    CHECK(s->msl == NULL && strstr(s->error, "bindless handle") != NULL);
    maxwell_free(s);
}

// Exact arithmetic: the MSL turns fast math and FMA contraction off unless key->fast_math is set.
static void test_math_pragmas(void) {
    const uint64_t code[] = {W_SCHED, W_MOV_R3_RZ, W_EXIT, W_BRA_SELF_8};
    size_t size;
    uint8_t *b = make_blob(code, 4, &size, 1);
    ShaderKey key = {0};
    ShaderInfo *s = maxwell_translate(b, size, STAGE_VERTEX, &key);
    CHECK(s->msl && strncmp(s->msl, "#pragma METAL fp math_mode(safe)\n#pragma METAL fp contract(off)\n#include", 70) == 0);
    maxwell_free(s);
    key.fast_math = true;
    s = maxwell_translate(b, size, STAGE_VERTEX, &key);
    CHECK(s->msl && strstr(s->msl, "#pragma") == NULL);
    maxwell_free(s);
    // where the compiler constants (cbuf 1) start: behind the 0x80-byte header and 3 code words, aligned to 0x100
    s = maxwell_translate(b, size, STAGE_VERTEX, &key);
    CHECK(s->cbuf1_blob_offset == 0x100);
    maxwell_free(s);
    free(b);
}

// half_compat keeps an unrounded float2 shadow of registers written by half operations
static void test_half_compat(void) {
    const uint64_t code[] = {W_SCHED, W_HMUL2_R7_R14, W_HMUL2_R7_R7, W_EXIT, W_SCHED, W_BRA_SELF_8, W_NOP, W_NOP};
    size_t size;
    uint8_t *b = make_blob(code, 8, &size, 1);
    ShaderKey key = {0};
    ShaderInfo *s = maxwell_translate(b, size, STAGE_FRAGMENT, &key);
    CHECK(s->msl && strstr(s->msl, "hvf7") == NULL && strstr(s->msl, "hpack(") != NULL);
    maxwell_free(s);
    key.half_compat = true;
    s = maxwell_translate(b, size, STAGE_FRAGMENT, &key);
    CHECK(s->msl != NULL);
    CHECK(s->msl && strstr(s->msl, "float2 hs7 = float2(0.0f); bool hvf7 = false;") != NULL);
    CHECK(s->msl && strstr(s->msl, "hxs(r7, hs7, hvf7, ") != NULL);  // the second HMUL2 reads the shadow of R7
    maxwell_free(s);
    free(b);
}

static void test_survey_clean_shader(void) {
    const uint64_t code[] = {W_SCHED, W_MOV_R3_RZ, W_EXIT, W_BRA_SELF_8};
    Survey sv;
    memset(&sv, 0, sizeof sv);
    ShaderInfo *s = translate(code, 4, STAGE_VERTEX, &sv);
    CHECK(sv.n == 0);
    CHECK(s->msl != NULL);
    maxwell_free(s);
}

// Constants behind the code must not be read as instructions; Unity encodes the padding branch with displacement -16.
static void test_code_end_detection(void) {
    const uint64_t junk = 0xbf19a0003f000000ull;  // a float constant pair: would decode as an unknown opcode
    const uint64_t a[] = {W_SCHED, W_MOV_R3_RZ, W_MOV_R3_RZ, W_EXIT, W_SCHED, W_BRA_SELF_16, W_NOP, W_NOP, W_SCHED, junk, junk, junk};
    const uint64_t b[] = {W_SCHED, W_MOV_R3_RZ, W_MOV_R3_RZ, W_EXIT, W_SCHED, W_BRA_SELF_8, W_NOP, W_NOP, W_SCHED, junk, junk, junk};
    const uint64_t *variants[] = {a, b};
    for (int v = 0; v < 2; v++) {
        Survey sv;
        memset(&sv, 0, sizeof sv);
        ShaderInfo *s = translate(variants[v], 12, STAGE_VERTEX, &sv);
        CHECK(sv.n == 0);
        CHECK(s->num_insts == 3);
        maxwell_free(s);
    }
    // the original -16 spelling with the padding branch in the first slot would have run into the constants
    const uint64_t c[] = {W_SCHED, W_MOV_R3_RZ, W_MOV_R3_RZ, W_EXIT, W_SCHED, junk, junk, junk};
    Survey sv;
    memset(&sv, 0, sizeof sv);
    ShaderInfo *s = translate(c, 8, STAGE_VERTEX, &sv);
    CHECK(sv.n > 0);  // without any padding branch the junk is decoded: the survey reports it
    maxwell_free(s);
}

static void test_input_checks(void) {
    uint8_t small[16] = {0};
    ShaderInfo *s = maxwell_translate(small, sizeof small, STAGE_VERTEX, NULL);
    CHECK(s->msl == NULL);
    CHECK(strstr(s->error, "too small") != NULL);
    maxwell_free(s);
    s = maxwell_translate(NULL, 0, STAGE_COMPUTE, NULL);
    CHECK(s->msl == NULL);
    maxwell_free(s);
}

static void test_no_rscale_flag(void) {
    // IPA-free check: a fragment shader that reads gl_FragCoord.x through ALD a[0x70] needs the scale table
    // unless key->no_rscale is set. ALD encoding: 0xefd8 .. with address in bits 20..30; use R3 = a[0x70].
    const uint64_t ald = 0xefd800000007ff03ull | (0x70ull << 20);
    const uint64_t code[] = {W_SCHED, ald, W_EXIT, W_BRA_SELF_8};
    size_t size;
    uint8_t *b = make_blob(code, 4, &size, 1);
    ShaderKey key = {0};
    ShaderInfo *s = maxwell_translate(b, size, STAGE_FRAGMENT, &key);
    CHECK(s->msl != NULL);
    CHECK(s->msl && strstr(s->msl, "rscale") != NULL);
    maxwell_free(s);
    key.no_rscale = true;
    s = maxwell_translate(b, size, STAGE_FRAGMENT, &key);
    CHECK(s->msl != NULL);
    CHECK(s->msl && strstr(s->msl, "rscale") == NULL);
    CHECK(s->msl && strstr(s->msl, "in.pos[0]") != NULL);
    CHECK(!s->uses_rscale);
    maxwell_free(s);
    free(b);
}

// ---------------------------------------------------------------- container
static size_t put32(uint8_t *b, size_t o, uint32_t v) {
    memcpy(b + o, &v, 4);
    return o + 4;
}

static size_t make_program(uint8_t *b, uint32_t stage, int with_ctrl_magic) {
    size_t o = 0;
    o = put32(b, o, UNITY_PROGRAM_MAGIC);
    o = put32(b, o, 201806u);  // version
    o = 0x18;
    o = put32(b, o, 1);        // one global keyword
    o = put32(b, o, 3);        // "AB\0"
    memcpy(b + o, "AB", 3);
    o = (o + 3 + 3) & ~(size_t)3;
    o = put32(b, o, 0);  // no local keywords
    size_t hdr = o;
    put32(b, hdr + 0, 0x200);
    put32(b, hdr + 4, stage);
    put32(b, hdr + 0xC, 0x100);
    put32(b, hdr + 0x10, 0x80);
    put32(b, hdr + 0x14, with_ctrl_magic ? UNITY_CONTROL_MAGIC : 0);
    size_t blob = hdr + 0x40;
    put32(b, blob, MAXWELL_BLOB_MAGIC);
    return blob;
}

static void test_container(void) {
    uint8_t buf[1024];
    memset(buf, 0, sizeof buf);
    size_t blob = make_program(buf, 1, 1);
    UnityProgram up;
    const char *err = unity_program_parse(buf, sizeof buf, &up);
    CHECK(err == NULL);
    CHECK(up.stage == STAGE_FRAGMENT);
    CHECK(up.keyword_count == 1);
    CHECK(up.version == 201806u);
    CHECK(up.blob_offset == blob);
    CHECK(up.blob_size == sizeof buf - blob);

    memset(buf, 0, sizeof buf);
    make_program(buf, 0, 1);
    CHECK(unity_program_parse(buf, sizeof buf, &up) == NULL && up.stage == STAGE_VERTEX);
    memset(buf, 0, sizeof buf);
    make_program(buf, 3, 1);
    CHECK(unity_program_parse(buf, sizeof buf, &up) == NULL && up.stage == -1);

    memset(buf, 0, sizeof buf);
    make_program(buf, 0, 0);
    CHECK(unity_program_parse(buf, sizeof buf, &up) != NULL);  // control magic missing
    memset(buf, 0, sizeof buf);
    CHECK(unity_program_parse(buf, sizeof buf, &up) != NULL);  // no magic at all
    memset(buf, 0, sizeof buf);
    make_program(buf, 0, 1);
    CHECK(unity_program_parse(buf, 0x30, &up) != NULL);        // truncated
    CHECK(unity_program_parse(buf, 3, &up) != NULL);
    // blob magic missing
    memset(buf, 0, sizeof buf);
    size_t blob2 = make_program(buf, 0, 1);
    put32(buf, blob2, 0);
    CHECK(unity_program_parse(buf, sizeof buf, &up) != NULL);
}

// XNU: HLSL backend (key->hlsl): output structure and the constructs that differ from MSL
static ShaderInfo *translate_hlsl(const uint64_t *code, size_t n, int stage) {
    size_t size;
    uint8_t *b = make_blob(code, n, &size, stage != STAGE_COMPUTE);
    ShaderKey key = {0};
    key.no_rscale = true;
    key.hlsl = 1;
    ShaderInfo *s = maxwell_translate(b, size, stage, &key);
    free(b);
    return s;
}

static void test_hlsl_backend(void) {
    const uint64_t vcode[] = {W_SCHED, W_MOV_R3_RZ, W_EXIT, W_BRA_SELF_8};
    ShaderInfo *s = translate_hlsl(vcode, 4, STAGE_VERTEX);
    CHECK(s->msl != NULL);
    CHECK(s->msl && strstr(s->msl, "MxVOut mx_vs(MxVIn i_, uint vid, uint iid)") != NULL);
    CHECK(s->msl && strstr(s->msl, "uint r3 = 0u;") != NULL);
    CHECK(s->msl && strstr(s->msl, "#ifndef MX_PRELUDE_DEFINED") != NULL);
    CHECK(s->msl && strstr(s->msl, "as_type") == NULL && strstr(s->msl, "ulong") == NULL);
    maxwell_free(s);
    const uint64_t fcode[] = {W_SCHED, W_MOV_R3_RZ, W_EXIT, W_BRA_SELF_8};
    s = translate_hlsl(fcode, 4, STAGE_FRAGMENT);
    CHECK(s->msl && strstr(s->msl, "MxFOut mx_fs(MxFIn i_, bool front_facing)") != NULL);
    maxwell_free(s);

    // TEX.B: Unity-style declarations (replaceable with MX_EXTERNAL_RESOURCES), Sample on the mx_ names
    const uint64_t tex[] = {W_SCHED, W_MOV_C2_168_R11, W_LOP_OR_C2_568_R11, W_BINDLESS_TEX, W_SCHED, W_EXIT, W_BRA_SELF_8, W_NOP};
    s = translate_hlsl(tex, 8, STAGE_FRAGMENT);
    CHECK(s->msl != NULL);
    CHECK(s->msl && strstr(s->msl, "#ifndef MX_EXTERNAL_RESOURCES") != NULL);
    CHECK(s->msl && strstr(s->msl, "Texture2D<float4> mx_t0 : register(t0);") != NULL);
    CHECK(s->msl && strstr(s->msl, "cbuffer MxCB2 : register(b2)") != NULL);
    CHECK(s->msl && strstr(s->msl, "mx_t0.Sample(mx_s0, float2(asfloat(r0), asfloat(r1)))") != NULL);
    CHECK(s->msl && strstr(s->msl, "mx_cb2[") != NULL && strstr(s->msl, " cb2[") == NULL);
    maxwell_free(s);

    // half arithmetic goes through f16tof32 / f32tof16 (no half type)
    const uint64_t half[] = {W_SCHED, W_HMUL2_R7_R14, W_HMUL2_R7_R7, W_EXIT, W_SCHED, W_BRA_SELF_8, W_NOP, W_NOP};
    s = translate_hlsl(half, 8, STAGE_FRAGMENT);
    CHECK(s->msl && strstr(s->msl, "hpack(") != NULL && strstr(s->msl, "f16tof32") != NULL && strstr(s->msl, "half2") == NULL);
    maxwell_free(s);

    // compute and the exclusive/unsupported keys fail with a message
    const uint64_t ccode[] = {W_MOV_R3_RZ, W_EXIT, W_BRA_SELF_8, W_NOP};
    s = translate_hlsl(ccode, 4, STAGE_COMPUTE);
    CHECK(s->msl == NULL && strstr(s->error, "hlsl:") != NULL);
    maxwell_free(s);
    size_t size;
    uint8_t *b = make_blob(vcode, 4, &size, 1);
    ShaderKey key = {0};
    key.hlsl = 1;
    key.glsl = 1;
    s = maxwell_translate(b, size, STAGE_VERTEX, &key);
    CHECK(s->msl == NULL && strstr(s->error, "exclusive") != NULL);
    maxwell_free(s);
    key.glsl = 0;
    key.half_compat = true;
    s = maxwell_translate(b, size, STAGE_VERTEX, &key);
    CHECK(s->msl == NULL && strstr(s->error, "half_compat") != NULL);
    maxwell_free(s);
    free(b);
}

int main(void) {
    test_minimal_vertex();
    test_minimal_fragment_and_compute();
    test_unknown_stops_original_mode();
    test_survey_collects_all();
    test_hsetp2_forms();
    test_bindless_texture();
    test_math_pragmas();
    test_half_compat();
    test_survey_clean_shader();
    test_code_end_detection();
    test_input_checks();
    test_no_rscale_flag();
    test_hlsl_backend();
    test_container();
    printf("test_translate: %d checks, %d failures\n", checks, failures);
    return failures ? 1 : 0;
}
