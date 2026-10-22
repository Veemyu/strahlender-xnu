// Verbindung der Vulkan-Fassung der LAS-NVN-Schicht (nvn/vulkan/prepare_vk.sh → work/recomp/nvn-src-vk) mit der BDSP-Laufzeit:
// die wenigen Plattformfunktionen, die der Vulkan-Teil des Klons braucht und die nvn_glue.c (backend-unabhängig) nicht liefert.
// Eigener Code. Vorlage der Signaturen: runtime/platform.h und runtime/kernel.h des Klons (MIT, siehe ../NOTICE.md).
#define _GNU_SOURCE
#include <stdint.h>
#include <stdlib.h>
#include <unistd.h>

#include "kernel.h"
#include "platform.h"

// Keine Schreibverfolgung der Gast-Seiten: Der Vertex-Zwischenspeicher bleibt aus, Texturen werden bei jeder Verwendung neu geprüft
// (textures.c: Hash-Vergleich). Eine Verfolgung über mprotect/userfaultfd wäre die spätere Optimierung (docs/recomp-linux.md).
int plat_written_pages(uint64_t addr, uint64_t size, uint64_t *pages, int max, uint64_t *page) {
    (void)addr; (void)size; (void)pages; (void)max; (void)page;
    return -1;
}

// Prozess sofort beenden, ohne Abbau der Treiber-Threads (Gast-Threads laufen noch)
void plat_terminate(void) { _exit(0); }

// Zeit, die dieser Thread in Warte-/Schlaf-Aufrufen des Kernels blockiert war (exec.c: Bildtakt-Messung des Klons). Die BDSP-Laufzeit
// führt sie nicht; der Bildtakt bleibt beim Spiel (Vsync-Ereignis aus services_gfx.c), die Takterkennung des Klons ist aus.
__thread uint64_t g_blocked_ns;
__attribute__((constructor)) static void vk_glue_defaults(void) { setenv("BDSP_PACE", "0", 0); }
