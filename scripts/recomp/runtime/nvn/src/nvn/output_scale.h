// Output resolution (runtime/nvn/output_scale.c), shared by the Metal and Vulkan backends.
#pragma once
#include <stdbool.h>

typedef struct {
    double sx, sy;             // render-target scale (relative to the game's 1920x1080 sizes)
    double shape;              // window aspect / 16:9 when the camera is widened, else 1
    double vx, vy, vw, vh;     // where the image is drawn in the window (pixels)
} OutScale;

// dw x dh: the window's drawable size in pixels; src_aspect: aspect of the image to show (guest swapchain image, after the game's crop);
// now: seconds; gpu_ms: GPU time of the last frame (< 0: unknown)
void output_scale(double dw, double dh, double src_aspect, bool reshape_allowed, double now, double gpu_ms, OutScale *o);

// Aspect of the region of a swapchain image tw x th that is shown; crop = uv origin and size from nvnWindowSetCrop (NULL: whole image).
static inline double present_src_aspect(uint32_t tw, uint32_t th, const float *crop) {
    double w = tw, h = th;
    if (crop) { w *= crop[2]; h *= crop[3]; }
    return w > 0 && h > 0 ? w / h : 16.0 / 9.0;
}
double output_scale_dynamic_factor(void);
