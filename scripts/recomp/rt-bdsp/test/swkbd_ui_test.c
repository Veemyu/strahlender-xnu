// Test of the on-screen keyboard logic (swkbd_ui.c) with the user's firmware layouts: typing, limits, focus moves, submit / resolve / cancel,
// and a software rendering of the result to a PPM. With BDSP_FIRMWARE_DATA (folder with swkbd/lyt/*.szs) it uses the firmware layouts, otherwise
// (or with BDSP_SWKBD_SIMPLE=1) the simple keyboard; the text items are listed, the rendering shows only quads.
// Build and run: scripts/recomp/rt-bdsp/test/run_swkbd_ui_test.sh [out.ppm]
#define LYT_RENDER_NO_MAIN
#include "lyt_render.c"
#include "../swkbd_ui.h"

static int fails, submits, cancels;
static char last[256];
#define CHECK(x) do { if (!(x)) { printf("ERROR line %d: %s\n", __LINE__, #x); fails++; } } while (0)

static void on_submit(void *u, const char *t) { (void)u; submits++; snprintf(last, sizeof last, "%s", t); }
static void on_cancel(void *u) { (void)u; cancels++; }

static void draw(const char *out) {
    float sc, off[2];
    const LytScene *s = swkbd_ui_scene(0.016, W, H, &sc, off);
    if (!s) return;
    for (int i = 0; i < W * H; i++) { fb[i * 3] = 70; fb[i * 3 + 1] = 120; fb[i * 3 + 2] = 70; }   // a fake game picture
    for (int i = 0; i < s->n; i++) {
        const LytItem *it = &s->items[i];
        if (it->type != LYT_ITEM_QUAD) continue;
        uint8_t *px = it->tex ? tex_pixels(it->tex) : NULL;
        if (it->tex && !px) continue;
        tri(it, px, 0, 1, 2, 0);
        tri(it, px, 1, 3, 2, 1);
    }
    for (int i = 0; i < s->n; i++) if (s->items[i].type == LYT_ITEM_TEXT) printf("text item %s: \"%s\"\n", s->items[i].pane, s->items[i].str);
    swkbd_ui_unlock();
    if (out) {
        FILE *f = fopen(out, "wb");
        fprintf(f, "P6\n%d %d\n255\n", W, H);
        fwrite(fb, 1, (size_t)W * H * 3, f);
        fclose(f);
    }
}

int main(int argc, char **argv) {
    swkbd_ui_set_display(1);
    if (!swkbd_ui_available()) { printf("keyboard not available\n"); return 1; }
    printf("keyboard mode: %s\n", getenv("BDSP_SWKBD_SIMPLE") || !getenv("BDSP_FIRMWARE_DATA") ? "simple (no firmware layouts)" : "firmware layouts");
    fb = malloc((size_t)W * H * 3);
    SwkbdParams p = {0};
    if (getenv("SWKBD_TEST_SCREEN")) {   // look test: render the symbol or the numeric keyboard to argv[1]
        const char *w = getenv("SWKBD_TEST_SCREEN");
        p.minlen = 1; p.maxlen = 12; p.mode = !strcmp(w, "numeric");
        snprintf(p.header, sizeof p.header, "Screen test");
        SwkbdCallbacks cb0 = {on_submit, on_cancel};
        swkbd_ui_open(&p, cb0, NULL);
        if (!strcmp(w, "sign")) {
            for (int i = 0; i < 4; i++) { swkbd_ui_pad(1ull << 15, 0, 0); swkbd_ui_pad(0, 0, 0); printf("down %d -> %s\n", i + 1, swkbd_ui_focus_name()); }
            swkbd_ui_pad(1ull << 14, 0, 0); swkbd_ui_pad(0, 0, 0);
            swkbd_ui_pad(1ull << 0, 0, 0); swkbd_ui_pad(0, 0, 0);
        }
        for (int i = 0; i < 40; i++) { float s, o[2]; if (swkbd_ui_scene(0.016, W, H, &s, o)) swkbd_ui_unlock(); }
        if (getenv("SWKBD_TEST_CLOSE")) {   // look test: a frame of the closing animation
            swkbd_ui_key(SWKBD_KEY_ESCAPE);
            for (int i = 0, n = atoi(getenv("SWKBD_TEST_CLOSE")); i < n - 1; i++) { float s, o[2]; if (swkbd_ui_scene(0.016, W, H, &s, o)) swkbd_ui_unlock(); }
        }
        draw(argc > 1 ? argv[1] : NULL);
        return 0;
    }
    p.minlen = 1; p.maxlen = 5;
    snprintf(p.header, sizeof p.header, "Enter your name");
    snprintf(p.guide, sizeof p.guide, "Name");
    SwkbdCallbacks cb = {on_submit, on_cancel};
    CHECK(swkbd_ui_open(&p, cb, NULL) == 0 && swkbd_ui_active());
    CHECK(swkbd_ui_open(&p, cb, NULL) != 0);               // already open
    swkbd_ui_text("Hello!");
    CHECK(!strcmp(swkbd_ui_text_value(), "Hello"));        // limit of 5
    swkbd_ui_key(SWKBD_KEY_BACKSPACE);
    CHECK(!strcmp(swkbd_ui_text_value(), "Hell"));
    swkbd_ui_key(SWKBD_KEY_LEFT); swkbd_ui_text("X");
    CHECK(!strcmp(swkbd_ui_text_value(), "HelXl"));
    swkbd_ui_key(SWKBD_KEY_HOME); swkbd_ui_key(SWKBD_KEY_DELETE);
    CHECK(!strcmp(swkbd_ui_text_value(), "elXl"));
    // pad: A on the first key types "1", down + A types a letter row key
    swkbd_ui_pad(1ull << 0, 0, 0); swkbd_ui_pad(0, 0, 0);
    CHECK(!strcmp(swkbd_ui_text_value(), "1elXl"));
    swkbd_ui_pad(1ull << 15, 0, 0); swkbd_ui_pad(0, 0, 0);
    swkbd_ui_pad(1ull << 0, 0, 0); swkbd_ui_pad(0, 0, 0);
    CHECK(!strcmp(swkbd_ui_text_value(), "1elXl"));        // full (5), nothing added
    swkbd_ui_pad(1ull << 1, 0, 0); swkbd_ui_pad(0, 0, 0);  // B: backspace
    CHECK(!strcmp(swkbd_ui_text_value(), "elXl"));         // the caret was after the "1"
    swkbd_ui_pad(1ull << 0, 0, 0); swkbd_ui_pad(0, 0, 0);
    CHECK(!strcmp(swkbd_ui_text_value(), "qelXl"));        // focus is on the "q" key (one row down)
    for (int i = 0; i < 60; i++) { float s, o[2]; if (swkbd_ui_scene(0.016, W, H, &s, o)) swkbd_ui_unlock(); }
    draw(argc > 1 ? argv[1] : NULL);
    swkbd_ui_key(SWKBD_KEY_ENTER);
    CHECK(submits == 1 && !strcmp(last, "qelXl"));
    swkbd_ui_resolve(0, "Not allowed");
    CHECK(swkbd_ui_active());
    swkbd_ui_key(SWKBD_KEY_ENTER);
    CHECK(submits == 2);
    swkbd_ui_resolve(1, NULL);
    CHECK(!swkbd_ui_active() && cancels == 0);
    CHECK(swkbd_ui_open(&p, cb, NULL) == 0);
    swkbd_ui_pad(1ull << 2, 0, 0);                         // X: cancel
    CHECK(!swkbd_ui_active() && cancels == 1);
    CHECK(swkbd_ui_visible());                             // the closing animation still draws it ...
    for (int i = 0; i < 20; i++) { float sc, o[2]; if (swkbd_ui_scene(0.016, W, H, &sc, o)) swkbd_ui_unlock(); }
    CHECK(!swkbd_ui_visible());                            // ... for 14 frames, then it is gone
    p.initial[0] = 0;
    // pages: from the bottom row to the symbol tab (or key), press it, then a key of the fourth row types a symbol
    swkbd_ui_resolve(1, NULL);
    CHECK(swkbd_ui_open(&p, cb, NULL) == 0);
    for (int i = 0; i < 4; i++) { swkbd_ui_pad(1ull << 15, 0, 0); swkbd_ui_pad(0, 0, 0); }
    for (int i = 0; i < 6 && !strstr(swkbd_ui_focus_name(), "InputMode_01") && strcmp(swkbd_ui_focus_name(), "symbol") && strcmp(swkbd_ui_focus_name(), "L_BtnSymbol"); i++) { swkbd_ui_pad(1ull << 14, 0, 0); swkbd_ui_pad(0, 0, 0); }
    swkbd_ui_pad(1ull << 0, 0, 0); swkbd_ui_pad(0, 0, 0);               // opens the symbol page
    int layouts = !strncmp(swkbd_ui_focus_name(), "L_", 2);
    if (layouts) { swkbd_ui_pad(1ull << 14, 0, 0); swkbd_ui_pad(0, 0, 0); }   // the tab column is left of the keys: right into the second row
    swkbd_ui_pad(1ull << 0, 0, 0); swkbd_ui_pad(0, 0, 0);
    printf("symbol page: focus %s, text \"%s\"\n", swkbd_ui_focus_name(), swkbd_ui_text_value());
    CHECK(strlen(swkbd_ui_text_value()) == 1 && strchr(layouts ? "!@#$%^&*()_" : "1", swkbd_ui_text_value()[0]));
    swkbd_ui_resolve(1, NULL);
    // the globe key switches the layout: us -> uk -> de -> fr, where the first letter of the second row is an "a" (a "q" before)
    CHECK(swkbd_ui_open(&p, cb, NULL) == 0);
    for (int i = 0; i < 4; i++) { swkbd_ui_pad(1ull << 15, 0, 0); swkbd_ui_pad(0, 0, 0); }
    CHECK(strstr(swkbd_ui_focus_name(), "BtnArray") != NULL);
    for (int i = 0; i < 3; i++) { swkbd_ui_pad(1ull << 0, 0, 0); swkbd_ui_pad(0, 0, 0); }
    CHECK(swkbd_ui_text_value()[0] == 0);                  // the globe types nothing
    for (int i = 0; i < 3; i++) { swkbd_ui_pad(1ull << 13, 0, 0); swkbd_ui_pad(0, 0, 0); }
    swkbd_ui_pad(1ull << 0, 0, 0); swkbd_ui_pad(0, 0, 0);
    CHECK(!strcmp(swkbd_ui_text_value(), "a"));
    swkbd_ui_resolve(1, NULL);
    // Korean: five more presses of the globe (fr -> es, it, pt, ru, ko); typed letters become jamo and syllables, backspace takes one jamo
    CHECK(swkbd_ui_open(&p, cb, NULL) == 0);
    for (int i = 0; i < 4; i++) { swkbd_ui_pad(1ull << 15, 0, 0); swkbd_ui_pad(0, 0, 0); }
    for (int i = 0; i < 5; i++) { swkbd_ui_pad(1ull << 0, 0, 0); swkbd_ui_pad(0, 0, 0); }
    swkbd_ui_text("gksrmf");
    CHECK(!strcmp(swkbd_ui_text_value(), "한글"));
    swkbd_ui_key(SWKBD_KEY_BACKSPACE);
    CHECK(!strcmp(swkbd_ui_text_value(), "한그"));
    swkbd_ui_key(SWKBD_KEY_BACKSPACE);
    CHECK(!strcmp(swkbd_ui_text_value(), "한ㄱ"));
    swkbd_ui_resolve(1, NULL);
    // Japanese: two more presses of the globe (ko -> ja romaji -> 50on grid); typed letters become kana; a key of the grid, the dakuten key (left stick)
    CHECK(swkbd_ui_open(&p, cb, NULL) == 0);
    for (int i = 0; i < 4; i++) { swkbd_ui_pad(1ull << 15, 0, 0); swkbd_ui_pad(0, 0, 0); }
    for (int i = 0; i < 1; i++) { swkbd_ui_pad(1ull << 0, 0, 0); swkbd_ui_pad(0, 0, 0); }   // ko -> ja
    swkbd_ui_text("nihon");
    CHECK(!strcmp(swkbd_ui_text_value(), "にほn"));          // 5 letters: the last n is still composing
    swkbd_ui_pad(1ull << 0, 0, 0); swkbd_ui_pad(0, 0, 0);    // ja -> 50on: the focus is on the globe of the grid
    CHECK(strstr(swkbd_ui_focus_name(), "BtnArray") != NULL);
    swkbd_ui_pad(1ull << 14, 0, 0); swkbd_ui_pad(0, 0, 0);   // right: the first key of the bottom row
    for (int i = 0; i < 4; i++) { swkbd_ui_pad(1ull << 13, 0, 0); swkbd_ui_pad(0, 0, 0); }
    for (int i = 0; i < 9; i++) { swkbd_ui_pad(1ull << 14, 0, 0); swkbd_ui_pad(0, 0, 0); }
    swkbd_ui_key(SWKBD_KEY_HOME); swkbd_ui_key(SWKBD_KEY_DELETE); swkbd_ui_key(SWKBD_KEY_DELETE); swkbd_ui_key(SWKBD_KEY_DELETE);
    swkbd_ui_pad(1ull << 0, 0, 0); swkbd_ui_pad(0, 0, 0);    // the key in the top row, ninth to the right of the sign column
    CHECK(!strcmp(swkbd_ui_text_value(), "か"));
    swkbd_ui_pad(1ull << 4, 0, 0); swkbd_ui_pad(0, 0, 0);    // left stick: next form of the kana before the caret
    CHECK(!strcmp(swkbd_ui_text_value(), "が"));
    swkbd_ui_resolve(1, NULL);
    // a second opening fades in again to full opacity
    CHECK(swkbd_ui_open(&p, cb, NULL) == 0);
    float maxa = 0;
    for (int i = 0; i < 30; i++) {
        float sc, o[2];
        const LytScene *s2 = swkbd_ui_scene(0.016, W, H, &sc, o);
        if (!s2) break;
        maxa = 0;
        for (int k = 0; k < s2->n; k++) if (s2->items[k].alpha > maxa) maxa = s2->items[k].alpha;
        swkbd_ui_unlock();
    }
    CHECK(maxa > 0.9f);
    if (fails) { printf("%d errors\n", fails); return 1; }
    printf("swkbd_ui_test: ok\n");
    return 0;
}
