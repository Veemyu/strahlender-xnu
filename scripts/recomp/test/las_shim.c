// Mini-Kernel-Ersatz für die LASRecomp-IPC-/Dienstschicht (ipc.c, services/*.c), nur für den Boot-Probelauf
// (docs/recomp-spike-2.md, Schritt 5). Eigener Code: Handle-Tabelle und Ereignisse ohne Threads. Die Dienstquellen
// des Klons werden von run_boot_probe.sh nur übersetzt und gelinkt, nicht kopiert.
#include "kernel.h"
#include <stdlib.h>
#include <string.h>

pthread_mutex_t g_klock = PTHREAD_MUTEX_INITIALIZER;
static KObject *htab[8192];
static uint32_t hnext = 0x1000;

uint32_t kernel_new_handle(KObject *o) {
    uint32_t h = hnext++;
    htab[h & 8191] = o;
    o->refs++;
    return h;
}
KObject *handle_get(uint32_t h) { return htab[h & 8191]; }
void kernel_signal(KObject *o) { o->signaled = true; }
KEvent *kernel_create_event_pair(uint32_t *w, uint32_t *r) {
    KEvent *e = calloc(1, sizeof *e);
    e->type = KOBJ_EVENT;
    *w = kernel_new_handle(e);
    *r = kernel_new_handle(e);
    return e;
}
KSharedMem *kernel_create_shared_memory(uint64_t size, void (*on_map)(KSharedMem *), uint32_t *handle) {
    KSharedMem *s = calloc(1, sizeof *s);
    s->obj.type = KOBJ_SHMEM;
    s->size = size;
    s->on_map = on_map;
    if (handle) *handle = kernel_new_handle(&s->obj);
    return s;
}
const char *settings_language(void) { return "en"; }
