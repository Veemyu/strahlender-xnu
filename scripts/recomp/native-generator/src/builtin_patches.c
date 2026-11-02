/* SPDX-License-Identifier: MIT
 * Built-in patches of the game's `main` module, applied to the mapped image right after the NSO is loaded, so the generator, the module
 * images and the runtime all see the same code. Every patch checks the original instruction first; a module with another build ID is
 * left untouched. Own code.
 *
 * Display size: the game takes its screen size from a few constants (see the sites below). Each constant load is replaced by a call
 * to a tiny stub that reads the size from a slot in the module image; the runtime writes the slot before the guest starts, so the
 * resolution and aspect ratio change without recompiling. A slot value of 0 keeps the original constant (stock 16:9 behavior).
 * Cutscenes: their render texture and the image that shows it follow the same slots (render size, canvas size in UI units).
 * Canvas: the scaler's match value comes from a slot (height when wider than 16:9, width when narrower: the UI is never cropped).
 * Camera: the field-of-view wrappers call host functions (registered by the runtime for aspects below 16:9) that keep the 16:9 horizontal view.
 * The slot block is laid out as AspectSlots in runtime/display_size.c; the SLOT_* offsets below must match it. */
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
    SLOT_FOV_SET = SLOT_BASE + 40,      /* 64 bit: host function that adjusts a camera's field of view on its way in (0 = off) */
    SLOT_FOV_GET = SLOT_BASE + 48,      /* 64 bit: ... and on its way out */
    FOV_SET_MOV = 0x26a4988,            /* UnityEngine.Camera::set_fieldOfView wrapper: mov v8.16b, v0.16b */
    FOV_GET_EXIT1 = 0x26a493c,          /* Camera::get_fieldOfView wrapper: the two exits (icall cached / resolved) that tail-call the native getter */
    FOV_GET_EXIT2 = 0x26a4960,
    CANVAS_MATCH_LOAD = 0x2263734,      /* CanvasScaler scale factor: ldr s2, [x19, #48] (matchWidthOrHeight) */
};

static const unsigned char MAIN_BUILD_ID[16] = {0x94, 0xce, 0xae, 0x32, 0x5c, 0x20, 0x5c, 0x4b, 0x9d, 0x6f, 0x72, 0x35, 0x55, 0x2f, 0x28, 0xfd};

static uint32_t ldr_w_literal(unsigned rt, uint32_t from, uint32_t to) { return 0x18000000u | ((((to - from) >> 2) & 0x7ffffu) << 5) | rt; }
static uint32_t cbnz_w(unsigned rt, int words) { return 0x35000000u | (((unsigned)words & 0x7ffffu) << 5) | rt; }
static uint32_t ldr_s_literal(unsigned rt, uint32_t from, uint32_t to) { return 0x1c000000u | ((((to - from) >> 2) & 0x7ffffu) << 5) | rt; }
static uint32_t ldr_x_literal(unsigned rt, uint32_t from, uint32_t to) { return 0x58000000u | ((((to - from) >> 2) & 0x7ffffu) << 5) | rt; }
static uint32_t cbz_w(unsigned rt, int words) { return 0x34000000u | (((unsigned)words & 0x7ffffu) << 5) | rt; }
static uint32_t cbz_x(unsigned rt, int words) { return 0xb4000000u | (((unsigned)words & 0x7ffffu) << 5) | rt; }
static uint32_t b_to(uint32_t from, uint32_t to) { return 0x14000000u | ((((int32_t)(to - from)) >> 2) & 0x3ffffff); }
static uint32_t bl_to(uint32_t from, uint32_t to) { return 0x94000000u | ((((int32_t)(to - from)) >> 2) & 0x3ffffff); }
#define RET_INSTRUCTION 0xd65f03c0u
#define BLR_X16 0xd63f0200u
#define BLR_X1 0xd63f0020u
#define STR_X30_PRE 0xf81f0ffeu     /* str x30, [sp, #-16]! */
#define LDR_X30_POST 0xf84107feu    /* ldr x30, [sp], #16 */

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
    /* Field of view: Unity's camera angle is vertical, so a screen narrower than 16:9 would lose horizontal view. The runtime registers two host
       functions (only for such aspects) that widen the vertical angle on the way in and undo it on the way out, so the game keeps working with
       the angles it knows. Both wrappers are patched in place: set at its argument copy, get at the two exits that tail-call the native getter. */
    static const struct { uint32_t offset, word; } fov_checks[] = {
        {FOV_SET_MOV, 0x4ea01c08u}, {FOV_GET_EXIT1, 0xa9417bfdu}, {FOV_GET_EXIT1 + 4, 0xaa1303e0u}, {FOV_GET_EXIT1 + 8, 0xa8c24ff4u},
        {FOV_GET_EXIT1 + 12, 0xd61f0020u}, {FOV_GET_EXIT2, 0xa9417bfdu}, {FOV_GET_EXIT2 + 4, 0xaa1303e0u}, {FOV_GET_EXIT2 + 8, 0xa8c24ff4u},
        {FOV_GET_EXIT2 + 12, 0xd61f0020u}};
    for (size_t i = 0; i < sizeof fov_checks / sizeof fov_checks[0]; i++)
        if (cg_u32(n->image + fov_checks[i].offset) != fov_checks[i].word) cg_fail(4, "builtin patch: unexpected instruction at 0x%x", fov_checks[i].offset);
    uint32_t set_stub = cursor;
    put_word(n, cursor, STR_X30_PRE);
    put_word(n, cursor + 4, ldr_x_literal(16, cursor + 4, SLOT_FOV_SET));
    put_word(n, cursor + 8, cbz_x(16, 2));
    put_word(n, cursor + 12, BLR_X16);
    put_word(n, cursor + 16, LDR_X30_POST);
    put_word(n, cursor + 20, 0x4ea01c08u);   /* original: mov v8.16b, v0.16b */
    put_word(n, cursor + 24, RET_INSTRUCTION);
    cursor += 28;
    uint32_t get_stub = cursor;
    put_word(n, cursor, 0xaa1303e0u);        /* mov x0, x19 (the camera) */
    put_word(n, cursor + 4, BLR_X1);         /* native getter; the wrapper's frame stays alive, so x30 is free */
    put_word(n, cursor + 8, ldr_x_literal(16, cursor + 8, SLOT_FOV_GET));
    put_word(n, cursor + 12, cbz_x(16, 3));
    put_word(n, cursor + 16, 0xaa1303e0u);   /* x0 = camera for the host function, the angle is in s0 */
    put_word(n, cursor + 20, BLR_X16);
    put_word(n, cursor + 24, 0xa9417bfdu);   /* the wrapper's own epilogue, now ending in ret */
    put_word(n, cursor + 28, 0xa8c24ff4u);
    put_word(n, cursor + 32, RET_INSTRUCTION);
    cursor += 36;
    put_word(n, FOV_SET_MOV, bl_to(FOV_SET_MOV, set_stub));
    put_word(n, FOV_GET_EXIT1, b_to(FOV_GET_EXIT1, get_stub));
    put_word(n, FOV_GET_EXIT2, b_to(FOV_GET_EXIT2, get_stub));
    if (cursor > SLOT_BASE) cg_fail(4, "builtin patch: stubs overflow the padding");
    memcpy(n->image + SLOT_BASE, "BDSPASPC", 8);
    put_word(n, SLOT_BASE + 8, 1);   /* slot layout version */
    if (SLOT_FOV_GET + 8 > SLOT_LIMIT) cg_fail(4, "builtin patch: slots overflow the padding");
    n->segments[0].size = cursor;
}
