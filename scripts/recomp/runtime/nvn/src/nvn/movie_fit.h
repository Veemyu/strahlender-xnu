// Movies keep their own aspect ratio (shared by the Metal and the Vulkan backend). The game draws a decoded movie frame as one full-target
// quad from two textures (NV12: the Y plane and the half-size UV plane). On a render target of another shape that quad would stretch the picture,
// so its viewport is reduced to the largest centered area with the movie's aspect ratio; the rest of the target keeps the clear color (black bars).
// Every movie, the cinematic title loop included, is 16:9 material: it is never stretched and never cropped, a differently shaped target gets bars.
#pragma once
#include <math.h>
#include <stdint.h>

// count: vertex/index count of the draw; ntex: fragment textures; t0/t1: their sizes (guest pixels); vp: guest viewport x, y, w, h (changed in place).
static inline void movie_fit_viewport(uint64_t count, int ntex, const uint32_t t0[2], const uint32_t t1[2], float vp[4]) {
    if (count != 6 || ntex != 2 || !t0[0] || !t0[1] || t1[0] * 2 != t0[0] || t1[1] * 2 != t0[1] || vp[2] <= 0 || vp[3] <= 0) return;
    const float movie = (float)t0[0] / (float)t0[1], target = vp[2] / vp[3];
    if (fabsf(movie - target) < 0.01f * movie) return;
    if (target > movie) {  // wider target: bars left and right
        const float w = vp[3] * movie;
        vp[0] += (vp[2] - w) * 0.5f;
        vp[2] = w;
    } else {               // taller target: bars above and below
        const float h = vp[2] / movie;
        vp[1] += (vp[3] - h) * 0.5f;
        vp[3] = h;
    }
}
