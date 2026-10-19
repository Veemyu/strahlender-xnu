// Vorversuch für Gate 2 (nur mit Bildern, die mit HLE_LIST=scripts/recomp/rt-bdsp/hle_nvn.txt gebaut wurden): `nvnBootstrapLoader`
// und alle NVN-Funktionen, die der Gast darüber holt, laufen als Host-Stubs, die nichts tun und 0 liefern. Zweck: sehen, was Unity
// nach dem Scheitern der Grafikinitialisierung tut (Logzeilen, Abbruch), ohne den NVN-Treiber des SDK. Kein Renderer. Eigener Code.
#include "bdsp.h"

static _Atomic int nvn_calls;

static void nvn_generic(Cpu *c) {
    const char *name = hle_slot_name(hle_current_slot());
    if (!strcmp(name, "nvnDeviceGetProcAddress")) {  // (device, name) -> Funktionszeiger: wieder ein Stub mit diesem Namen
        const char *want = G2HC(c->x[1]);
        c->x[0] = hle_register(want, nvn_generic);
        return;
    }
    int n = ++nvn_calls;
    if (getenv("BDSP_TRACE_NVN") && n <= 300) LOG("[nvn] %s(x0=%llx x1=%llx x2=%llx) lr=%llx\n", name, (unsigned long long)c->x[0], (unsigned long long)c->x[1], (unsigned long long)c->x[2], (unsigned long long)c->x[30]);
    c->x[0] = 0;
}

static void nvn_bootstrap(Cpu *c) {
    const char *name = G2HC(c->x[0]);
    static int logged;
    if (logged++ < 3) LOG("[gate] nvnBootstrapLoader(\"%s\") (Host-Stub), lr=%llx\n", name, (unsigned long long)c->x[30]);
    __atomic_add_fetch(&g_watch_hits, 1, __ATOMIC_RELAXED);
    bdsp_gate_hit("nvnBootstrapLoader (Host-Stub)");
    c->x[0] = hle_register(name, nvn_generic);
}

void nvn_null_init(void) { hle_register("nvnBootstrapLoader", nvn_bootstrap); }
