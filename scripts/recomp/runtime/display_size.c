// Display size of the game: resolution and aspect ratio are runtime settings of every build. The game's code reads its screen size from
// two slots in the main module image (native-generator/src/builtin_patches.c); this file chooses the size and writes the slots before
// the guest starts. A slot of 0 keeps the stock 1920x1080.
//   BDSP_RENDER=WxH            exact render size (tests)
//   BDSP_ASPECT=<preset|auto>  16:9 (default), 16:10, 4:3, 21:9, mbp (14"/16" MacBook Pro panel), ipad11 (11" iPad Pro), auto (shape of the window), or a ratio like 1.6
//   BDSP_RENDER_H=<pixels|auto> height of the render image; auto = native height of the window's drawable (default 1080)
// A shell without its own settings store (Qt on Linux/Windows) persists the choice in the file named by BDSP_DISPLAY_CONFIG ("aspect=4:3" and
// "render_height=1080" lines); the environment variables win over the file.
#include <math.h>
#include <stdio.h>

#include "bdsp.h"
#include "display_size.h"

#define SLOT_OFFSET 0x2cf6e00u   // builtin_patches.c: SLOT_BASE
#define CAMERA_GET_ASPECT 0x26a4c90u   // UnityEngine.Camera::get_aspect (il2cpp wrapper of the native getter)
#define PI_D 3.14159265358979323846

int __attribute__((weak)) ui_drawable_size(int *w, int *h) { (void)w; (void)h; return 0; }
void __attribute__((weak)) ui_window_init(void) {}

// Value of a display preference: environment variable, else the line key=value of BDSP_DISPLAY_CONFIG; NULL when unset.
const char *display_pref_get(const char *key) {
    static char values[2][64];
    static const char *const keys[2] = {"aspect", "render_height"}, *const envs[2] = {"BDSP_ASPECT", "BDSP_RENDER_H"};
    for (int i = 0; i < 2; i++) {
        if (strcmp(key, keys[i])) continue;
        const char *e = getenv(envs[i]);
        if (e && *e) return e;
        const char *path = getenv("BDSP_DISPLAY_CONFIG");
        FILE *f = path && *path ? fopen(path, "r") : NULL;
        if (!f) return NULL;
        char line[128];
        size_t n = strlen(key);
        const char *found = NULL;
        while (fgets(line, sizeof line, f)) {
            if (strncmp(line, key, n) || line[n] != '=') continue;
            line[strcspn(line, "\r\n")] = 0;
            snprintf(values[i], sizeof values[i], "%s", line + n + 1);
            found = values[i][0] ? values[i] : NULL;
        }
        fclose(f);
        return found;
    }
    return NULL;
}

// Stores both preferences in BDSP_DISPLAY_CONFIG (an empty value removes the line). Returns false if the file cannot be written.
bool display_pref_store(const char *aspect, const char *render_height) {
    const char *path = getenv("BDSP_DISPLAY_CONFIG");
    if (!path || !*path) return false;
    char tmp[1200];
    snprintf(tmp, sizeof tmp, "%s.tmp", path);
    FILE *f = fopen(tmp, "w");
    if (!f) return false;
    if (aspect && *aspect) fprintf(f, "aspect=%s\n", aspect);
    if (render_height && *render_height) fprintf(f, "render_height=%s\n", render_height);
    if (fclose(f)) return false;
#ifdef _WIN32
    remove(path);
#endif
    return rename(tmp, path) == 0;
}

// The choices every shell offers (macOS menu, Qt menu); the iPhone/iPad Settings.bundle lists the same values. label is an English key for the shells' translations.
// 12.9" iPad Pro is 4:3; the 11" iPad Pro is about 1.43:1; 21:9 is exactly 21/9 (a 3440x1440 monitor is 2.39:1: choose "auto" for it).
static const DisplayChoice aspect_choices[] = {
    {"16:9", "16:9 (Original)", 16.0 / 9}, {"auto", "Window Shape", 0}, {"16:10", "16:10", 1.6}, {"4:3", "4:3", 4.0 / 3}, {"21:9", "21:9", 21.0 / 9},
    {"mbp", "MacBook Pro Display", 3024.0 / 1964}, {"ipad11", "iPad Pro 11\"", 2388.0 / 1668}};
static const DisplayChoice height_choices[] = {
    {"720", "720p", 0}, {"1080", "1080p", 0}, {"1440", "1440p", 0}, {"2160", "2160p", 0}, {"auto", "Native (window pixels)", 0}};
const DisplayChoice *display_aspect_choices(int *count) { *count = (int)(sizeof aspect_choices / sizeof aspect_choices[0]); return aspect_choices; }
const DisplayChoice *display_height_choices(int *count) { *count = (int)(sizeof height_choices / sizeof height_choices[0]); return height_choices; }

static double g_render_aspect;   // aspect of the render size the game was started with (0 before display_size_init)
double display_aspect(void) { return g_render_aspect > 0 ? g_render_aspect : 16.0 / 9; }

static bool parse_aspect(const char *text, double *out) {
    for (size_t i = 0; i < sizeof aspect_choices / sizeof aspect_choices[0]; i++)
        if (aspect_choices[i].aspect > 0 && !strcasecmp(text, aspect_choices[i].value)) { *out = aspect_choices[i].aspect; return true; }
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

// Camera field of view. Unity's angle is vertical; on a screen narrower than 16:9 the horizontal view would shrink, so cameras that render at the
// screen's shape (the screen itself, or a render texture of the same aspect) get a wider vertical angle that keeps the 16:9 horizontal view.
// The game keeps setting and reading the angles it knows: these hooks run in the Camera::set_/get_fieldOfView wrappers (builtin_patches.c).
// Cameras with another aspect (model views, previews) are left alone.
static double fov_factor(Cpu *c, Module *m, uint64_t camera) {
    c->x[0] = camera;
    guest_call(c, m->base + CAMERA_GET_ASPECT);
    float a;
    memcpy(&a, &c->v[0], sizeof a);
    if (!(a > 0.1f) || fabs(a - g_render_aspect) > 0.01 * g_render_aspect) return 1.0;
    return (16.0 / 9) / a;
}

static void fov_adjust(Cpu *c, bool in) {
    Module *m = main_module();
    float fov;
    memcpy(&fov, &c->v[0], sizeof fov);
    if (!m || !(fov > 0.0f) || fov >= 179.0f) return;
    uint64_t x[31], camera = c->x[0];
    __uint128_t v[32];
    memcpy(x, c->x, sizeof x);
    memcpy(v, c->v, sizeof v);
    double k = fov_factor(c, m, camera);
    memcpy(c->x, x, sizeof x);
    memcpy(c->v, v, sizeof v);
    if (k == 1.0) return;
    double half = tan(fov * PI_D / 360);
    float out = (float)(2 * atan(in ? half * k : half / k) * 180 / PI_D);
    memcpy(&c->v[0], &out, sizeof out);   // the rest of the register stays as it was
}
static void fov_set_hook(Cpu *c) { fov_adjust(c, true); }
static void fov_get_hook(Cpu *c) { fov_adjust(c, false); }

// Writes the slots; returns false when this build's main module carries no slot block (other game version).
bool display_size_set(int w, int h) {
    Module *m = main_module();
    if (!m) return false;
    uint8_t *slot = G2H8(m->base + SLOT_OFFSET);
    if (memcmp(slot, "BDSPASPC", 8)) return false;
    float match = (double)w / h >= 16.0 / 9 ? 1.0f : 0.0f;   // canvas: wider keeps the height scale, narrower the width scale (UI is never cropped)
    // canvas size in UI units (reference 1280x720): the units the scaler lays out, used for full-screen RawImages
    double aspect = (double)w / h;
    float ui_w = aspect >= 16.0 / 9 ? (float)(720 * aspect) : 1280.0f, ui_h = aspect >= 16.0 / 9 ? 720.0f : (float)(1280 / aspect);
    uint32_t v[6] = {(uint32_t)w, (uint32_t)h, 1, 0, 0, 0};
    memcpy(&v[3], &match, sizeof match);
    memcpy(&v[4], &ui_w, sizeof ui_w);
    memcpy(&v[5], &ui_h, sizeof ui_h);
    memcpy(slot + 12, v, sizeof v);
    uint64_t fov[2] = {0, 0};   // only for screens narrower than 16:9; elsewhere the wrappers skip the hook
    if (aspect < 16.0 / 9 - 0.005) { fov[0] = hle_register("<bdsp fov set>", fov_set_hook); fov[1] = hle_register("<bdsp fov get>", fov_get_hook); }
    memcpy(slot + 40, fov, sizeof fov);
    return true;
}

void display_size_init(void) {
    int w = 0, h = 0;
    const char *render = getenv("BDSP_RENDER");
    if (render && sscanf(render, "%dx%d", &w, &h) == 2 && w >= 320 && h >= 240) {
    } else {
        const char *as = display_pref_get("aspect"), *hs = display_pref_get("render_height");
        int dw = 0, dh = 0;
        bool have_window = ui_drawable_size(&dw, &dh) && dw > 0 && dh > 0;
        if (!have_window && ((as && !strcasecmp(as, "auto")) || (hs && !strcasecmp(hs, "auto")))) {
            ui_window_init();   // the window (or the app's layer) decides the size
            have_window = ui_drawable_size(&dw, &dh) && dw > 0 && dh > 0;
        }
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
        if (!as && !hs) { g_render_aspect = 16.0 / 9; return; }   // stock: slots stay 0
        // largest image of this shape inside the drawable when the height follows the window
        h = (int)ref;
        w = (int)lround(h * aspect);
        if (hs && !strcasecmp(hs, "auto") && have_window && w > dw) { w = dw; h = (int)lround(w / aspect); }
        w &= ~1; h &= ~1;
    }
    g_render_aspect = (double)w / h;
    if (display_size_set(w, h)) LOG("[display] render size %dx%d (aspect %.4f)\n", w, h, (double)w / h);
    else LOG("[display] this module has no size slots; the game keeps its stock resolution\n");
}
