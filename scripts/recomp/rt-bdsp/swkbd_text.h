// Text of the on-screen keyboard without a platform text system: the firmware's own fonts (.bfttf, read from the user's firmware folder) are
// rasterized glyph by glyph into one small R8 atlas, a string becomes a list of glyph quads. The same code serves every renderer (Vulkan today,
// Metal behind BDSP_SWKBD_ATLAS=1). Own code; the rasterizer is stb_truetype (third_party/, public domain / MIT).
#ifndef SWKBD_TEXT_H
#define SWKBD_TEXT_H

#include <stdint.h>
#include "lyt_scene.h"

// One glyph of a placed string: its rectangle in target pixels, its place in the atlas (0..1), and how far down the string's colour
// gradient (0 top colour .. 1 bottom colour) its top and bottom edge lie.
typedef struct { float x0, y0, x1, y1, u0, v0, u1, v1, g0, g1; } SwkbdGlyph;

// 1 when the text font is in <root>/fonts (nothing is read yet).
int swkbd_text_available(const char *root);
// Validate both the firmware text font and button-glyph font.
int swkbd_text_firmware_ready(const char *root);
// Reads the fonts from <root>/fonts (std text font, button glyph font; Korean and Chinese ones when present, loaded when a glyph needs them).
// Returns 0 when there is no text font (nothing can be drawn then). Safe to call again.
int swkbd_text_open(const char *root);
// Frees the fonts and the atlas.
void swkbd_text_close(void);

// Width of a string in pixels at an em size, with `kern` added after every character.
float swkbd_text_measure(const char *utf8, float px, float kern);

// The callback for swkbd_ui_set_measure: the width of a string at an em size (at least 1 px), no extra spacing.
float swkbd_text_measure_px(const char *utf8, float px);

// Places the text of a scene item (box corners X/Y in target pixels, em size, character spacing, origin flags, squeeze to fit) as glyph quads.
// Returns the number of glyphs written to out (at most max). `scale` is the canvas-to-target factor.
int swkbd_text_place(const LytItem *it, float scale, const float X[4], const float Y[4], SwkbdGlyph *out, int max);

// The atlas: 8 bit coverage, row 0 on top. `version` changes whenever pixels were added or the atlas was cleared; a renderer re-uploads then.
// Call swkbd_text_frame_begin() once per frame before placing text: a full atlas is cleared there (never in the middle of a frame).
const uint8_t *swkbd_text_atlas(int *w, int *h, unsigned *version);
void swkbd_text_frame_begin(void);

#endif
