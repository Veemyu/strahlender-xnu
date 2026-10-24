// The keyboard's scene as draw lists for any renderer: one vertex array (pixel positions, uv, colour) and a short list of draws, each a run of
// vertices drawn with one texture (or the focus frame shader). Text becomes glyph quads of the shared atlas (swkbd_text.c). Own code.
#ifndef SWKBD_DRAW_H
#define SWKBD_DRAW_H

#include "lyt_scene.h"

typedef struct { float pos[2], uv[2], col[4]; } SwkbdVtx;   // pos in target pixels (y down), straight colour

enum { SWKBD_DRAW_QUADS, SWKBD_DRAW_FRAME };
#define SWKBD_TEX_WHITE ((const LytTex *)0)   // flat colour: a renderer binds a 1x1 white texture
#define SWKBD_TEX_ATLAS ((const LytTex *)1)   // the glyph atlas (swkbd_text_atlas)

typedef struct {
    int kind;
    const LytTex *tex;               // SWKBD_TEX_WHITE, SWKBD_TEX_ATLAS or a layout texture
    int first, count;                // vertices (triangle list)
    // SWKBD_DRAW_FRAME: the focus frame's shader values (half size of the key in layout pixels, corner radius, one target pixel in layout pixels, colour)
    float half[2], rad, px, col[4];
} SwkbdDraw;

typedef struct {
    SwkbdVtx *v; int nv, capv;
    SwkbdDraw *d; int nd, capd;
} SwkbdBatch;

// Rebuilds the lists from a scene (target pixels: canvas * scale + off). Text uses swkbd_text_place; call swkbd_text_frame_begin() before.
void swkbd_draw_build(SwkbdBatch *b, const LytScene *sc, float scale, const float off[2]);
void swkbd_draw_free(SwkbdBatch *b);

#endif
