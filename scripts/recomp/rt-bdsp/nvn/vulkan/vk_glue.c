// Connection of the Vulkan version of the LAS NVN layer (nvn/vulkan/prepare_vk.sh → work/recomp/nvn-src-vk) to the BDSP runtime:
// the few platform functions that the Vulkan part of the clone needs and that nvn_glue.c (backend-independent) does not provide.
// Own code. Template of the signatures: runtime/platform.h and runtime/kernel.h of the clone (MIT, see ../NOTICE.md).
#define _GNU_SOURCE
#include <stdint.h>
#include <stdlib.h>
#include <unistd.h>

#include "plat.h"
#include "kernel.h"
#include "platform.h"
#ifdef _WIN32
#include "hle.h"
// Separate from the lookup TU: its optimizer must see linker bounds, not one-entry arrays.
__attribute__((used, section(".hle$a"))) const HleImplEntry bdsp_hle_begin[1] = {{0}};
__attribute__((used, section(".hle$z"))) const HleImplEntry bdsp_hle_end[1] = {{0}};
#endif

// Overlay drawn over the finished frame (the on-screen keyboard); a no-op until swkbd_overlay_vk.c, which replaces it, is built.
__attribute__((weak)) void menu_render(void *cmd, uint32_t w, uint32_t h) { (void)cmd; (void)w; (void)h; }

// No write tracking of the guest pages: the vertex cache stays off, textures are re-checked on every use
// (textures.c: hash comparison). Tracking via mprotect/userfaultfd would be the later optimization (docs/recomp-linux.md).
int plat_written_pages(uint64_t addr, uint64_t size, uint64_t *pages, int max, uint64_t *page) {
    (void)addr; (void)size; (void)pages; (void)max; (void)page;
    return -1;
}

// Terminate the process immediately, without tearing down the driver threads (guest threads are still running)
void plat_terminate(void) { _exit(0); }

// Time this thread was blocked in wait/sleep calls of the kernel (exec.c: frame pacing measurement of the clone). The BDSP runtime
// does not track it; frame pacing stays with the game (vsync event from services_gfx.c), the clone's rate detection is off.
__thread uint64_t g_blocked_ns;
__attribute__((constructor)) static void vk_glue_defaults(void) {
    if (!plat_setenv("BDSP_PACE", "0", false)) {  // (Windows: SDL's own setter would bypass the CRT environment)
        fprintf(stderr, "FATAL: Vulkan pacing default could not be set.\n");
        _exit(1);
    }
}
