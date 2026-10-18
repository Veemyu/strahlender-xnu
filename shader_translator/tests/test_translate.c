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
#define W_HSETP2_CBUF 0x7e85038c0457ff07ull   // not implemented by the translator (cbuf form)
#define W_BINDLESS_TEX 0xdeb80001a0b70008ull  // TEX.B
#define W_UNKNOWN 0xfff0000000070001ull

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
    const uint64_t code[] = {W_SCHED, W_UNKNOWN, W_HSETP2_CBUF, W_MOV_R3_RZ,  //
                             W_SCHED, W_UNKNOWN, W_BINDLESS_TEX, W_EXIT,      //
                             W_SCHED, W_BRA_SELF_8, W_NOP, W_NOP};
    Survey sv;
    memset(&sv, 0, sizeof sv);
    ShaderInfo *s = translate(code, 12, STAGE_FRAGMENT, &sv);
    CHECK(s->error[0] == 0);  // survey mode never aborts
    CHECK(sv.n == 3);
    int unknown_ffff = -1, hsetp = -1, bindless = -1;
    for (int i = 0; i < sv.n; i++) {
        if (!strcmp(sv.items[i].name, "opfff")) unknown_ffff = i;
        if (!strcmp(sv.items[i].name, "op7e8")) hsetp = i;
        if (!strcmp(sv.items[i].name, "bindless tex")) bindless = i;
    }
    CHECK(unknown_ffff >= 0 && hsetp >= 0 && bindless >= 0);
    if (unknown_ffff >= 0) {
        CHECK(sv.items[unknown_ffff].count == 2);
        CHECK(sv.items[unknown_ffff].unknown_opcode);
        CHECK(sv.items[unknown_ffff].opcode_bits == 0xfff);
        CHECK(sv.items[unknown_ffff].example_word == W_UNKNOWN);
    }
    if (hsetp >= 0) CHECK(sv.items[hsetp].count == 1 && sv.items[hsetp].unknown_opcode);
    if (bindless >= 0) CHECK(sv.items[bindless].count == 1 && !sv.items[bindless].unknown_opcode);
    maxwell_free(s);
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

int main(void) {
    test_minimal_vertex();
    test_minimal_fragment_and_compute();
    test_unknown_stops_original_mode();
    test_survey_collects_all();
    test_survey_clean_shader();
    test_code_end_detection();
    test_input_checks();
    test_no_rscale_flag();
    test_container();
    printf("test_translate: %d checks, %d failures\n", checks, failures);
    return failures ? 1 : 0;
}
