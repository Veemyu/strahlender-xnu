/* SPDX-License-Identifier: MIT
 * Built-in patches of the game's `main` module, applied to the mapped image right after the NSO is loaded, so the generator, the module
 * images and the runtime all see the same code. Every patch checks the original instruction first; a module with another build ID is
 * left untouched. Own code.
 *
 * Display size: the game takes its screen size from a few constants (see the sites below). Each constant load is replaced by a call
 * to a tiny stub that reads the size from a slot in the module image; the runtime writes the slot before the guest starts, so the
 * resolution and aspect ratio change without recompiling. A slot value of 0 keeps the original constant (stock 16:9 behavior). */
#include "codegen.h"
#include <string.h>

enum {
    TEXT_END = 0x2cf6a30,   /* original end of main's text; the page up to 0x2cf7000 is zero padding */
    STUB_BASE = 0x2cf6a40,  /* stubs are appended to the text */
    SLOT_BASE = 0x2cf6e00,  /* slots stay outside the text (data), the runtime writes them */
    SLOT_LIMIT = 0x2cf7000,
    SLOT_WIDTH = SLOT_BASE + 12,
    SLOT_HEIGHT = SLOT_BASE + 16,
    SLOT_MATCH_MODE = SLOT_BASE + 20,   /* 0: the canvas keeps its own match setting */
    SLOT_MATCH = SLOT_BASE + 24,        /* float: CanvasScaler match (0 = width, 1 = height) */
    SLOT_UI_WIDTH = SLOT_BASE + 28,     /* float bits: canvas width in UI units (1280 at 16:9), for full-screen RawImages */
    SLOT_UI_HEIGHT = SLOT_BASE + 32,    /* float bits: canvas height in UI units (720 at 16:9) */
    CANVAS_MATCH_LOAD = 0x2263734,      /* CanvasScaler scale factor: ldr s2, [x19, #48] (matchWidthOrHeight) */
};

static const unsigned char MAIN_BUILD_ID[16] = {0x94, 0xce, 0xae, 0x32, 0x5c, 0x20, 0x5c, 0x4b, 0x9d, 0x6f, 0x72, 0x35, 0x55, 0x2f, 0x28, 0xfd};

static uint32_t ldr_w_literal(unsigned rt, uint32_t from, uint32_t to) { return 0x18000000u | ((((to - from) >> 2) & 0x7ffffu) << 5) | rt; }
static uint32_t cbnz_w(unsigned rt, int words) { return 0x35000000u | (((unsigned)words & 0x7ffffu) << 5) | rt; }
static uint32_t ldr_s_literal(unsigned rt, uint32_t from, uint32_t to) { return 0x1c000000u | ((((to - from) >> 2) & 0x7ffffu) << 5) | rt; }
static uint32_t cbz_w(unsigned rt, int words) { return 0x34000000u | (((unsigned)words & 0x7ffffu) << 5) | rt; }
static uint32_t bl_to(uint32_t from, uint32_t to) { return 0x94000000u | ((((int32_t)(to - from)) >> 2) & 0x3ffffff); }
#define RET_INSTRUCTION 0xd65f03c0u

typedef struct { uint32_t offset, orig; unsigned reg; uint32_t slot; } Site;
/* offset: instruction to replace; orig: its encoding (a register move of a constant); the stub loads the slot into reg instead. */
#define MOV(off, reg, value, slot) {off, 0x52800000u | ((value) << 5) | (reg), reg, slot}
#define MOV_FLOAT(off, reg, high16, slot) {off, 0x52a00000u | ((high16) << 5) | (reg), reg, slot}
static const Site sites[] = {
    /* render target of the screen (virtual display) */
    MOV(0x605228, 3, 1080, SLOT_HEIGHT),
    MOV(0x605234, 2, 1920, SLOT_WIDTH),
    /* display size query: handheld default, then the docked and the combined branch */
    MOV(0x60630c, 23, 1280, SLOT_WIDTH),
    MOV(0x606310, 22, 720, SLOT_HEIGHT),
    MOV(0x6063ac, 8, 1920, SLOT_WIDTH),
    MOV(0x6063b4, 9, 1080, SLOT_HEIGHT),
    MOV(0x6063c4, 8, 1920, SLOT_WIDTH),
    MOV(0x6063cc, 8, 1080, SLOT_HEIGHT),
    /* GfxDevice resolution */
    MOV(0x61a724, 1, 1920, SLOT_WIDTH),
    MOV(0x61a728, 2, 1080, SLOT_HEIGHT),
    /* Dpr.Demo.DemoCamera.CreateRenderTex: the cutscene render texture (Rowan, evolution, ...) is 1280x720 */
    MOV(0x1ac8a4c, 1, 1280, SLOT_WIDTH),
    MOV(0x1ac8a50, 2, 720, SLOT_HEIGHT),
    /* Dpr.Demo.DemoSceneManager.CommonInit: the RawImage that shows it has sizeDelta (1280, 720) in canvas units */
    MOV_FLOAT(0x1aca350, 8, 0x44a0, SLOT_UI_WIDTH),
    MOV_FLOAT(0x1aca358, 8, 0x4434, SLOT_UI_HEIGHT),
};

typedef struct { uint32_t orig, slot, address; } Stub;

static void put_word(Nso *n, uint32_t offset, uint32_t word) {
    cg_range(n->size, offset, 4, "builtin patch");
    unsigned char *p = n->image + offset;
    p[0] = (unsigned char)word; p[1] = (unsigned char)(word >> 8); p[2] = (unsigned char)(word >> 16); p[3] = (unsigned char)(word >> 24);
}

void cg_builtin_patches(Nso *n) {
    if (memcmp(n->build_id, MAIN_BUILD_ID, sizeof MAIN_BUILD_ID) || n->segments[0].size != TEXT_END) return;
    Stub stubs[sizeof sites / sizeof sites[0]]; size_t stub_count = 0;
    uint32_t cursor = STUB_BASE;
    for (size_t i = 0; i < sizeof sites / sizeof sites[0]; i++) {
        const Site *s = &sites[i];
        if (cg_u32(n->image + s->offset) != s->orig) cg_fail(4, "builtin patch: unexpected instruction at 0x%x", s->offset);
        size_t k = 0;
        while (k < stub_count && !(stubs[k].orig == s->orig && stubs[k].slot == s->slot)) k++;
        if (k == stub_count) {
            stubs[stub_count] = (Stub){s->orig, s->slot, cursor};
            /* ldr w<reg>, slot; cbnz w<reg>, done; <original instruction>; done: ret */
            put_word(n, cursor, ldr_w_literal(s->reg, cursor, s->slot));
            put_word(n, cursor + 4, cbnz_w(s->reg, 2));
            put_word(n, cursor + 8, s->orig);
            put_word(n, cursor + 12, RET_INSTRUCTION);
            cursor += 16;
            stub_count++;
        }
        put_word(n, s->offset, bl_to(s->offset, stubs[k].address));
    }
    /* Canvas scaling: the UI is designed for 16:9. The runtime asks for height matching on wider and width matching on narrower screens, so
       the canvas never crops. Scratch register x16 is free at a call (intra-procedure-call register). */
    if (cg_u32(n->image + CANVAS_MATCH_LOAD) != 0xbd403262u) cg_fail(4, "builtin patch: unexpected instruction at 0x%x", CANVAS_MATCH_LOAD);
    put_word(n, cursor, ldr_w_literal(16, cursor, SLOT_MATCH_MODE));
    put_word(n, cursor + 4, cbz_w(16, 3));
    put_word(n, cursor + 8, ldr_s_literal(2, cursor + 8, SLOT_MATCH));
    put_word(n, cursor + 12, RET_INSTRUCTION);
    put_word(n, cursor + 16, 0xbd403262u);   /* original: ldr s2, [x19, #48] */
    put_word(n, cursor + 20, RET_INSTRUCTION);
    put_word(n, CANVAS_MATCH_LOAD, bl_to(CANVAS_MATCH_LOAD, cursor));
    cursor += 24;
    if (cursor > SLOT_BASE) cg_fail(4, "builtin patch: stubs overflow the padding");
    memcpy(n->image + SLOT_BASE, "BDSPASPC", 8);
    put_word(n, SLOT_BASE + 8, 1);   /* slot layout version */
    if (SLOT_UI_HEIGHT + 4 > SLOT_LIMIT) cg_fail(4, "builtin patch: slots overflow the padding");
    n->segments[0].size = cursor;
}
