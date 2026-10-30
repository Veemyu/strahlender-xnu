#include "swkbd_draw.h"
#include "swkbd_text.h"

#include <stdlib.h>
#include <string.h>

static SwkbdVtx *vtx_room(SwkbdBatch *b, int n) {
    if (b->nv + n > b->capv) {
        int nc = b->capv ? b->capv * 2 : 2048;
        while (nc < b->nv + n) nc *= 2;
        SwkbdVtx *p = realloc(b->v, (size_t)nc * sizeof *p);
        if (!p) return NULL;
        b->v = p; b->capv = nc;
    }
    return b->v + b->nv;
}

// Starts a draw, or continues the last one when it is the same kind of draw with the same texture.
static SwkbdDraw *draw_for(SwkbdBatch *b, int kind, const LytTex *tex) {
    if (kind == SWKBD_DRAW_QUADS && b->nd) {
        SwkbdDraw *l = &b->d[b->nd - 1];
        if (l->kind == kind && l->tex == tex && l->first + l->count == b->nv) return l;
    }
    if (b->nd == b->capd) {
        int nc = b->capd ? b->capd * 2 : 64;
        SwkbdDraw *p = realloc(b->d, (size_t)nc * sizeof *p);
        if (!p) return NULL;
        b->d = p; b->capd = nc;
    }
    SwkbdDraw *d = &b->d[b->nd++];
    memset(d, 0, sizeof *d);
    d->kind = kind; d->tex = tex; d->first = b->nv;
    return d;
}

// One quad from its four corners (left-top, right-top, left-bottom, right-bottom).
static void quad(SwkbdBatch *b, int kind, const LytTex *tex, const float X[4], const float Y[4], const float uv[4][2], const float col[4][4], SwkbdDraw **out) {
    SwkbdVtx *v = vtx_room(b, 6);
    SwkbdDraw *d = v ? draw_for(b, kind, tex) : NULL;
    if (!d) return;
    static const int idx[6] = {0, 1, 2, 1, 3, 2};
    for (int k = 0; k < 6; k++) {
        v[k].pos[0] = X[idx[k]]; v[k].pos[1] = Y[idx[k]];
        v[k].uv[0] = uv[idx[k]][0]; v[k].uv[1] = uv[idx[k]][1];
        memcpy(v[k].col, col[idx[k]], sizeof v[k].col);
    }
    b->nv += 6;
    d->count += 6;
    if (out) *out = d;
}

void swkbd_draw_build(SwkbdBatch *b, const LytScene *sc, float scale, const float off[2]) {
    b->nv = b->nd = 0;
    for (int i = 0; i < sc->n; i++) {
        const LytItem *it = &sc->items[i];
        float X[4], Y[4];
        for (int k = 0; k < 4; k++) { X[k] = off[0] + it->x[k] * scale; Y[k] = off[1] + it->y[k] * scale; }
        if (it->type == LYT_ITEM_FRAME) {   // focus frame around the key rectangle (items x[0], y[0] .. x[3], y[3]); the faint outer 1.9 px do not count, so the radius of the outer shape is 2.5 + 1.9
            float kx0 = X[0], ky0 = Y[0], kx1 = X[3], ky1 = Y[3], m = 8 * scale;
            float cx = (kx0 + kx1) / 2, cy = (ky0 + ky1) / 2, hw = (kx1 - kx0) / 2 / scale + 7, hh = (ky1 - ky0) / 2 / scale + 7;
            float fx[4] = {cx - hw * scale - m + 7 * scale, cx + hw * scale + m - 7 * scale, cx - hw * scale - m + 7 * scale, cx + hw * scale + m - 7 * scale};
            float fy[4] = {cy - hh * scale - m + 7 * scale, cy - hh * scale - m + 7 * scale, cy + hh * scale + m - 7 * scale, cy + hh * scale + m - 7 * scale};
            float fuv[4][2], fcol[4][4] = {{1, 1, 1, 1}, {1, 1, 1, 1}, {1, 1, 1, 1}, {1, 1, 1, 1}};
            for (int k = 0; k < 4; k++) { fuv[k][0] = (fx[k] - cx) / scale; fuv[k][1] = (fy[k] - cy) / scale; }
            SwkbdDraw *d = NULL;
            quad(b, SWKBD_DRAW_FRAME, SWKBD_TEX_WHITE, fx, fy, fuv, fcol, &d);   // (a frame is always a draw of its own)
            if (!d) continue;
            d->half[0] = hw; d->half[1] = hh; d->rad = 4.4f; d->px = 1.0f / scale;
            for (int c = 0; c < 3; c++) d->col[c] = it->col[0][c] / 255.0f;
            d->col[3] = it->alpha;
        } else if (it->type == LYT_ITEM_QUAD) {
            float col[4][4];
            for (int k = 0; k < 4; k++) { for (int c = 0; c < 3; c++) col[k][c] = it->col[k][c] / 255.0f; col[k][3] = it->col[k][3] / 255.0f * it->alpha; }
            quad(b, SWKBD_DRAW_QUADS, it->tex, X, Y, (const float (*)[2])it->uv, col, NULL);
        } else if (it->str && it->str[0]) {
            SwkbdGlyph gl[96];
            int ng = swkbd_text_place(it, scale, X, Y, gl, 96);
            for (int q = 0; q < ng; q++) {
                float gx[4] = {gl[q].x0, gl[q].x1, gl[q].x0, gl[q].x1}, gy[4] = {gl[q].y0, gl[q].y0, gl[q].y1, gl[q].y1};
                float uv[4][2] = {{gl[q].u0, gl[q].v0}, {gl[q].u1, gl[q].v0}, {gl[q].u0, gl[q].v1}, {gl[q].u1, gl[q].v1}}, col[4][4];
                for (int k = 0; k < 4; k++) {   // the text's colour runs from its top to its bottom colour over the string's height
                    float t = k < 2 ? gl[q].g0 : gl[q].g1;
                    for (int c = 0; c < 3; c++) col[k][c] = (it->top_color[c] + (it->bottom_color[c] - it->top_color[c]) * t) / 255.0f;
                    col[k][3] = (it->top_color[3] + (it->bottom_color[3] - it->top_color[3]) * t) / 255.0f * it->alpha;
                }
                quad(b, SWKBD_DRAW_QUADS, SWKBD_TEX_ATLAS, gx, gy, uv, col, NULL);
            }
        }
    }
}

void swkbd_draw_free(SwkbdBatch *b) {
    free(b->v); free(b->d);
    memset(b, 0, sizeof *b);
}
