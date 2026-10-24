// Scene layer on top of the layout readers (lyt.h): a bank of the layout archives of one keyboard screen, layout instances
// with animation state (parts such as a key button are instanced once per use), and a builder that flattens an instance
// tree into an ordered list of coloured, textured quads and text boxes in canvas pixels. No graphics API in here;
// the Metal renderer (swkbd_overlay.m) draws the list. Own code, formats as documented in docs/ (no Nintendo data).
#ifndef LYT_SCENE_H
#define LYT_SCENE_H

#include "lyt.h"

typedef struct LytBank LytBank;
typedef struct LytInst LytInst;

// Opens the named archives (e.g. "Qwerty", "common") from <root>/swkbd/lyt/<name>.szs (or <root>/swkbd/romfs/lyt/). Archives that are
// missing are skipped; returns NULL when none could be read.
LytBank *lytbank_open(const char *root, const char *const *archives, int n);
void lytbank_free(LytBank *b);
const LytLayout *lytbank_layout(LytBank *b, const char *name);                       // cached; NULL if no archive has it
const LytAnim *lytbank_anim(LytBank *b, const LytLayout *owner, const char *tag);   // "<owner name>_<tag>"; NULL if missing
const LytTex *lytbank_tex(const LytBank *b, const char *name);
// All textures of the bank in a stable order (for uploading).
int lytbank_ntex(const LytBank *b);
const LytTex *lytbank_tex_at(const LytBank *b, int i);

// Builds an instance tree for a layout; every part (prt1) gets an instance of its layout, recursively.
LytInst *lytinst_new(LytBank *b, const char *layout);
void lytinst_free(LytInst *in);
const LytLayout *lytinst_layout(const LytInst *in);
// Child instance for the part pane called `name` (or a "/"-separated path of part names). NULL if there is none.
LytInst *lytinst_part(LytInst *in, const char *path);
// Starts / sets an animation of this layout (file "<layout>_<tag>.bflan") at a frame. Animations are applied in the order they were set;
// setting one again moves it to the end. Returns 0 when the animation does not exist.
int lytinst_set_anim(LytInst *in, const char *tag, float frame);
void lytinst_clear_anims(LytInst *in);
// Resting state of a freshly built tree: the UnFocus* animations at their last frame, "Wait" at the end, "Alpha" at frame 10, for the
// instance and every part below it.
void lytinst_default_state(LytInst *in);
float lytinst_anim_frames(LytInst *in, const char *tag);   // length in frames, 0 if missing
void lytinst_set_text(LytInst *in, const char *pane, const char *utf8);
void lytinst_set_visible(LytInst *in, const char *pane, int visible);   // overrides the pane flag
// Colour override of a pane: replaces the material colour of a picture (its corner colours still shade it) and the colours of a text. (The layouts are white; the colour scheme
// comes from the program, so the keyboard sets it here.) Pass a == 0 and all-zero to remove.
void lytinst_set_color(LytInst *in, const char *pane, uint8_t r, uint8_t g, uint8_t b);
// Alpha (0..255) of a pane instead of the one in the layout; an animation that drives the pane's alpha still wins.
void lytinst_set_pane_alpha(LytInst *in, const char *pane, int a);
// Moves a pane by (dx, dy) in its parent's units (y up), after the part magnification.
void lytinst_set_offset(LytInst *in, const char *pane, float dx, float dy);
// Glyph size (width, height in canvas pixels) of a text pane instead of the one in the layout.
void lytinst_set_font_size(LytInst *in, const char *pane, float w, float h);
void lytinst_set_alpha(LytInst *in, float alpha);                        // multiplies the whole instance (0..1)

// LYT_ITEM_FRAME (the keyboard's focus frame): the rectangle of the key is given by x[0], y[0] and x[3], y[3]; the renderer draws the frame around it
enum { LYT_ITEM_QUAD, LYT_ITEM_TEXT, LYT_ITEM_FRAME };

typedef struct {
    int type;
    // Both: corners in canvas pixels, y down, order left-top, right-top, left-bottom, right-bottom (of the pane rectangle before rotation)
    float x[4], y[4];
    float alpha;                     // accumulated pane alpha (0..1)
    // quad
    uint8_t col[4][4];               // per-corner colour RGBA with the material colour already multiplied in
    float uv[4][2];
    const LytTex *tex;               // NULL: untextured (flat colour)
    // text
    const char *str;                 // utf-8, owned by the instance
    float font_size[2];              // in canvas pixels
    float char_space, line_space;
    uint8_t top_color[4], bottom_color[4];
    uint8_t origin, align;           // txt1 text position (like a pane base position) and line alignment
    float rot;                       // radians, counter-clockwise on screen
    const char *pane;                // name, for debugging
} LytItem;

typedef struct {
    LytItem *items;
    int n, cap;
} LytScene;

// Flattens the instance tree. The canvas is the layout's own size (1280x720 for the keyboard screens); `ox, oy` shift the whole
// picture, `scale` zooms it around the canvas centre (for fitting the window).
void lyt_scene_build(LytScene *sc, LytInst *root, float ox, float oy, float scale);
// Same, but adds to the items already in the scene (layers drawn in order).
void lyt_scene_append(LytScene *sc, LytInst *root, float ox, float oy, float scale);
void lyt_scene_free(LytScene *sc);

// Axis-aligned bounds {left, top, right, bottom} in canvas pixels of pane `pane` of the instance `inst` (somewhere below root) after the current
// animation state, for hit tests. Same ox/oy/scale as lyt_scene_build. Returns 0 if the pane is hidden or not found.
int lyt_pane_bounds(LytInst *root, LytInst *inst, const char *pane, float ox, float oy, float scale, float out[4]);

#endif
