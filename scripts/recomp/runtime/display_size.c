// Display size of the game: resolution and aspect ratio are runtime settings of every build. The game's code reads its screen size from
// two slots in the main module image (native-generator/src/builtin_patches.c); this file chooses the size and writes the slots before
// the guest starts. A slot of 0 keeps the stock 1920x1080.
//   BDSP_RENDER=WxH            exact render size (tests)
//   BDSP_ASPECT=<preset|auto>  16:9 (default), 16:10, 4:3, 21:9, mbp (14"/16" MacBook Pro panel), auto (shape of the window), or a ratio like 1.6
//   BDSP_RENDER_H=<pixels|auto> height of the render image; auto = native height of the window's drawable (default 1080)
#include <math.h>

#include "bdsp.h"

#define SLOT_OFFSET 0x2cf6e00u   // builtin_patches.c: SLOT_BASE

int __attribute__((weak)) ui_drawable_size(int *w, int *h) { (void)w; (void)h; return 0; }
void __attribute__((weak)) ui_window_init(void) {}

typedef struct { const char *name; double aspect; } Preset;
static const Preset presets[] = {{"16:9", 16.0 / 9}, {"16:10", 1.6}, {"4:3", 4.0 / 3}, {"21:9", 3440.0 / 1440}, {"mbp", 3024.0 / 1964}};

static bool parse_aspect(const char *text, double *out) {
    for (size_t i = 0; i < sizeof presets / sizeof presets[0]; i++)
        if (!strcasecmp(text, presets[i].name)) { *out = presets[i].aspect; return true; }
    int a, b;
    if (sscanf(text, "%d:%d", &a, &b) == 2 && a > 0 && b > 0) { *out = (double)a / b; return true; }
    char *end;
    double v = strtod(text, &end);
    if (end != text && !*end && v >= 1.0 && v <= 4.0) { *out = v; return true; }
    return false;
}

static Module *main_module(void) {
    for (int i = 0; i < g_nmodules; i++)
        if (!strcmp(g_modules[i].name, "main")) return &g_modules[i];
    return NULL;
}

// Writes the slots; returns false when this build's main module carries no slot block (other game version).
bool display_size_set(int w, int h) {
    Module *m = main_module();
    if (!m) return false;
    uint8_t *slot = G2H8(m->base + SLOT_OFFSET);
    if (memcmp(slot, "BDSPASPC", 8)) return false;
    float match = (double)w / h >= 16.0 / 9 ? 1.0f : 0.0f;   // canvas: wider keeps the height scale, narrower the width scale (UI is never cropped)
    uint32_t v[4] = {(uint32_t)w, (uint32_t)h, 1, 0};
    memcpy(&v[3], &match, sizeof match);
    memcpy(slot + 12, v, sizeof v);
    return true;
}

void display_size_init(void) {
    int w = 0, h = 0;
    const char *render = getenv("BDSP_RENDER");
    if (render && sscanf(render, "%dx%d", &w, &h) == 2 && w >= 320 && h >= 240) {
    } else {
        const char *as = getenv("BDSP_ASPECT"), *hs = getenv("BDSP_RENDER_H");
        int dw = 0, dh = 0;
        if ((as && !strcasecmp(as, "auto")) || (hs && !strcasecmp(hs, "auto"))) ui_window_init();   // main thread: the window decides the size
        bool have_window = ui_drawable_size(&dw, &dh) && dw > 0 && dh > 0;
        double aspect = 16.0 / 9;
        if (as && !strcasecmp(as, "auto")) {
            if (have_window) aspect = (double)dw / dh;
        } else if (as && !parse_aspect(as, &aspect)) {
            LOG("[display] unknown BDSP_ASPECT \"%s\", using 16:9\n", as);
            aspect = 16.0 / 9;
        }
        double ref = 1080;
        if (hs && !strcasecmp(hs, "auto")) {
            if (have_window) ref = dh;
        } else if (hs && atoi(hs) >= 240) ref = atoi(hs);
        if (!as && !hs) return;   // stock: slots stay 0
        // largest image of this shape inside the drawable when the height follows the window
        h = (int)ref;
        w = (int)lround(h * aspect);
        if (hs && !strcasecmp(hs, "auto") && have_window && w > dw) { w = dw; h = (int)lround(w / aspect); }
        w &= ~1; h &= ~1;
    }
    if (display_size_set(w, h)) LOG("[display] render size %dx%d (aspect %.4f)\n", w, h, (double)w / h);
    else LOG("[display] this module has no size slots; the game keeps its stock resolution\n");
}
