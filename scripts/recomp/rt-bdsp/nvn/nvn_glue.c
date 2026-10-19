// Verbindung der LAS-NVN-Schicht (scripts/recomp/rt-bdsp/nvn/prepare.sh → work/recomp/nvn-src) mit der BDSP-Laufzeit:
// Funktionstabelle von nvnBootstrapLoader, nn::vi/nv-Ersatz, Speicherbereich der Metal-Puffer und wirkungslose Stummel für die
// Spiel-Hooks des Klons (Breitbild, Zelda-spezifische Textur- und Zeichenänderungen, Menü). Eigener Code.
#ifdef __APPLE__
#include <mach-o/getsect.h>
#include <mach-o/ldsyms.h>
#include <SDL3/SDL.h>
#include <stdatomic.h>
#include <string.h>
#include <strings.h>
#endif
#include <time.h>
#include <unistd.h>
#include "guestmem.h"
#include "hle.h"
#include "nvn.h"
#include "output_scale.h"
#include "settings.h"

// Funktionen der BDSP-Laufzeit (bdsp.h kann hier nicht eingebunden werden: es kollidiert mit der Adressraum-Nachbildung in rt.h)
uint64_t rt_now_ns(void);
void bdsp_fatal_report(const char *why, int code);
void bdsp_gate_hit(const char *what);
void kernel_phys_range(uint64_t *lo, uint64_t *hi);
uint64_t loader_find_symbol(const char *name);
void rt_fatal(const char *fmt, ...);
#define ALIAS_BASE 0x7190000000ull
#define ALIAS_SIZE 0x0190000000ull

BdspSettings g_settings;
uint64_t g_nvn_mem_base, g_nvn_mem_size;

uint64_t plat_now_ns(void) { return rt_now_ns(); }
void nvn_fatal(void) {
    rt_fatal_trace();
    bdsp_fatal_report("FATAL in der NVN-Schicht", 3);
    for (;;) sleep(1);   // der Hauptthread/die Überwachung erstellt den Bericht und beendet den Prozess
}
void plat_sleep_until_ns(uint64_t t) {
    uint64_t now = rt_now_ns();
    if (t > now) { struct timespec ts = {(time_t)((t - now) / 1000000000ull), (long)((t - now) % 1000000000ull)}; nanosleep(&ts, NULL); }
}

// Tabelle der HLE_FUNC-Einträge: Mach-O-Abschnitt (macOS) oder ELF-Abschnitt mit __start_/__stop_ (Linux)
#ifdef __APPLE__
static const HleImplEntry *hle_entries(size_t *n) {
    unsigned long size = 0;
    const HleImplEntry *start = (const HleImplEntry *)getsectiondata(&_mh_execute_header, "__DATA", "__hle_impls", &size);
    *n = start ? size / sizeof *start : 0;
    return start;
}
#else
extern const HleImplEntry __start_hle_impls[] __attribute__((weak)), __stop_hle_impls[] __attribute__((weak));
static const HleImplEntry *hle_entries(size_t *n) {
    *n = __start_hle_impls ? (size_t)(__stop_hle_impls - __start_hle_impls) : 0;
    return __start_hle_impls;
}
#endif

HostFn hle_lookup_impl(const char *name) {
    size_t n;
    const HleImplEntry *start = hle_entries(&n);
    for (size_t i = 0; i < n; i++)
        if (start[i].name && !strcmp(start[i].name, name)) return start[i].fn;
    return NULL;
}

// Bindet die HLE_FUNC-Einträge an Slots, die der Lader für HLE-gebundene Importe (hle.txt) schon angelegt hat; den Rest legt nvn_proc an.
void nvn_glue_init(void) {
    size_t n;
    const HleImplEntry *start = hle_entries(&n);
    for (size_t i = 0; i < n; i++) {
        const HleImplEntry *p = &start[i];
        if (p->name && strncmp(p->name, "nvn", 3)) hle_register(p->name, p->fn);
        else if (p->name && !strcmp(p->name, "nvnBootstrapLoader")) hle_register(p->name, p->fn);
    }
}

// Hülle des vom Spiel belegten Anwendungsspeichers: in ihr liegen die NVN-Speicherpools (Aufruf aus backend_init).
void nvn_glue_mem_range(void) {
    uint64_t lo, hi;
    kernel_phys_range(&lo, &hi);
    if (!lo) { lo = ALIAS_BASE; hi = ALIAS_BASE + ALIAS_SIZE; }
    lo &= ~0x3FFFull;
    hi = (hi + 0x3FFF) & ~0x3FFFull;
    if (getenv("BDSP_NVN_MEM_MB")) hi = lo + ((uint64_t)atol(getenv("BDSP_NVN_MEM_MB")) << 20);
    g_nvn_mem_base = lo;
    g_nvn_mem_size = hi - lo;
    LOG("[nvn] Metal-Puffer über 0x%llx + %llu MiB\n", (unsigned long long)lo, (unsigned long long)(g_nvn_mem_size >> 20));
}

// ---- NVN-Funktionstabelle: jeder Name wird an die Host-Implementierung gebunden; fehlende Namen werden gezählt (hle_unimpl_report)
static uint64_t nvn_proc(const char *name) {
    if (!name || !*name) return 0;
    HostFn f = hle_lookup_impl(name);
    return hle_register(name, f);
}

HLE_FUNC("nvnBootstrapLoader", nvn_bootstrap_loader) {
    const char *name = (const char *)G2HC(c->x[0]);
    static int logged;
    if (logged++ < 3) LOG("[nvn] nvnBootstrapLoader(\"%s\")\n", name);
    bdsp_gate_hit("nvnBootstrapLoader");
    c->x[0] = nvn_proc(name);
}

HLE_FUNC("nvnDeviceGetProcAddress", nvn_device_get_proc_address) {
    c->x[0] = nvn_proc((const char *)G2HC(c->x[1]));
}

// ---- Videowiedergabe (Unity SwitchVideoPlayer -> Android-Stagefright im SDK): die Codec-Liste ist ohne Hardware-Decoder leer;
// strcasecmp bekommt dort einen Null-Namen. Ein NULL-sicheres strcasecmp lässt die Suche leer enden (Codec nicht gefunden).
HLE_FUNC("strcasecmp", libc_strcasecmp) {
    const char *a = c->x[0] ? (const char *)G2HC(c->x[0]) : NULL, *b = c->x[1] ? (const char *)G2HC(c->x[1]) : NULL;
    c->x[0] = (uint64_t)(int64_t)(!a || !b ? (a == b ? 0 : a ? 1 : -1) : strcasecmp(a, b));
}

// ---- Debug-Prüfpunkte des NVN-SDK (in der LAS-Schicht nicht vorhanden): wirkungslos
HLE_FUNC("nvnCommandBufferInsertCheckpointDynamic", nvn_ckpt_dyn) { (void)c; }
HLE_FUNC("nvnCommandBufferInsertCheckpointStatic", nvn_ckpt_static) { (void)c; }
HLE_FUNC("nvnDeviceSetAutomaticCheckpointsByDebugGroup", nvn_ckpt_group) { (void)c; }
HLE_FUNC("nvnDeviceSetAutomaticCheckpointsEnable", nvn_ckpt_enable) { (void)c; }
HLE_FUNC("nvnDeviceSetAutomaticCheckpointsSamplingInterval", nvn_ckpt_interval) { (void)c; }
HLE_FUNC("nvnDeviceSetCheckpointCallStacksEnable", nvn_ckpt_stacks) { (void)c; }
HLE_FUNC("nvnDeviceSetCheckpointMaxCallStacksDepth", nvn_ckpt_depth) { (void)c; }

// ---- nn::vi / nv: Anzeige und Grafiktreiber-Initialisierung des SDK auf dem Host
uint32_t vi_vsync_handle(void);
uint64_t g_native_window;

HLE_FUNC("_ZN2nn2vi10InitializeEv", vi_initialize) { (void)c; }
HLE_FUNC("_ZN2nn2vi18OpenDefaultDisplayEPPNS0_7DisplayE", vi_open_default_display) {
    *(uint64_t *)G2H(c->x[0]) = H2G(hle_alloc(0x100));
    c->x[0] = 0;
}
HLE_FUNC("_ZN2nn2vi11CreateLayerEPPNS0_5LayerEPNS0_7DisplayE", vi_create_layer) {
    *(uint64_t *)G2H(c->x[0]) = H2G(hle_alloc(0x100));
    c->x[0] = 0;
}
HLE_FUNC("_ZN2nn2vi15GetNativeWindowEPPvPNS0_5LayerE", vi_get_native_window) {
    if (!g_native_window) g_native_window = H2G(hle_alloc(0x100));
    *(uint64_t *)G2H(c->x[0]) = g_native_window;
    c->x[0] = 0;
}
HLE_FUNC("_ZN2nn2vi20GetDisplayVsyncEventEPNS_2os15SystemEventTypeEPNS0_7DisplayE", vi_get_vsync_event) {
    // nn::os::AttachReadableHandleToSystemEvent(event, handle, managed = false, clear_mode = AutoClear)
    c->x[1] = vi_vsync_handle();
    c->x[2] = 0;
    c->x[3] = 1;
    uint64_t f = loader_find_symbol("_ZN2nn2os33AttachReadableHandleToSystemEventEPNS0_15SystemEventTypeEjbNS0_14EventClearModeE");
    if (!f) rt_fatal("AttachReadableHandleToSystemEvent nicht gefunden\n");
    guest_call(c, f);
    c->x[0] = 0;
}
HLE_FUNC("_ZN2nv18InitializeGraphicsEPvm", nv_initialize_graphics) { (void)c; }
HLE_FUNC("_ZN2nv20SetGraphicsAllocatorEPFPvmmS0_EPFvS0_S0_EPFS0_S0_mS0_ES0_", nv_set_allocator) { (void)c; }
HLE_FUNC("_ZN2nv28SetGraphicsDevtoolsAllocatorEPFPvmmS0_EPFvS0_S0_EPFS0_S0_mS0_ES0_", nv_set_dt_allocator) { (void)c; }

// ---- Zähler für das Ergebnisprotokoll
uint64_t renderer_present_count(void);
void nvn_report(FILE *f) { fprintf(f, "NVN: %llu Bilder präsentiert, Metal-Puffer %llu MiB\n", (unsigned long long)renderer_present_count(), (unsigned long long)(g_nvn_mem_size >> 20)); }

// ---- Ausgabegröße: das 1920x1080-Bild des Spiels wird eingepasst, ohne Skalierung des Rendering
void output_scale(double dw, double dh, bool reshape_allowed, double now, double gpu_ms, OutScale *o) {
    (void)reshape_allowed; (void)now; (void)gpu_ms;
    double k = dw / 1920.0 < dh / 1080.0 ? dw / 1920.0 : dh / 1080.0;
    o->sx = o->sy = 1.0;
    o->shape = 1.0;
    o->vw = 1920.0 * k;
    o->vh = 1080.0 * k;
    o->vx = (dw - o->vw) / 2;
    o->vy = (dh - o->vh) / 2;
}
double output_scale_dynamic_factor(void) { return 1.0; }

// SMAA (Nachbearbeitung des Klons) ist abgeschaltet: die Tabellen fehlen, g_settings.antialias bleibt 0
const char smaa_hlsl_src[] = "";
const unsigned char *smaa_area_tex(void) { return NULL; }
const unsigned char *smaa_search_tex(void) { return NULL; }

// ---- Debug-Haken des LAS-Übersetzers (renderer.m verweist darauf; der XNU-Übersetzer hat sie entfernt)
const uint8_t *maxwell_dbg_code, *maxwell_dbg_vs;
uint32_t maxwell_dbg_pc;
int maxwell_dbg_reg;

// ---- Eingabe (nn::hid): Tastatur aus dem Fenster und ein Testskript speisen den Npad-Zustand (Muster: runtime/hle/input.c des Klons).
// Die SDK-Funktionen GetNpadState(s)/GetNpadStyleSet werden durch Host-Funktionen ersetzt; der hid-Dienst bleibt für Verbindung/Aktivierung zuständig.
// Tasten: Eingabe/Leertaste/K = A, Rücktaste/J = B, X, Y, Pfeiltasten und WASD = Steuerkreuz, Q/E = L/R, P = Plus, O = Minus.
// Testskript (--input-script / BDSP_INPUT_SCRIPT): "Sekunde:TASTE[+TASTE]:Dauer, ..." ab Prozessstart, z. B. "30:A:0.3,34:A+DOWN:0.2".
enum { PB_A, PB_B, PB_X, PB_Y, PB_LSTICK, PB_RSTICK, PB_L, PB_R, PB_ZL, PB_ZR, PB_PLUS, PB_MINUS, PB_LEFT, PB_UP, PB_RIGHT, PB_DOWN };
static const char *const pad_names[16] = {"A", "B", "X", "Y", "LSTICK", "RSTICK", "L", "R", "ZL", "ZR", "PLUS", "MINUS", "LEFT", "UP", "RIGHT", "DOWN"};
static _Atomic uint64_t key_buttons;
static int64_t pad_sampling;
extern uint64_t g_proc_start_ns;
typedef struct { double at, len; uint32_t mask; } ScriptStep;
static ScriptStep script[256];
static int nscript = -1;

static void script_load(void) {
    nscript = 0;
    const char *spec = getenv("BDSP_INPUT_SCRIPT");
    static char buf[4096];
    if (!spec) return;
    snprintf(buf, sizeof buf, "%s", spec);
    char *save1 = NULL;
    for (char *tok = strtok_r(buf, ",", &save1); tok && nscript < 256; tok = strtok_r(NULL, ",", &save1)) {
        double at = 0, len = 0.3;
        char names[96] = "";
        if (sscanf(tok, "%lf:%95[A-Z+]:%lf", &at, names, &len) < 2) continue;
        uint32_t m = 0;
        char *save2 = NULL;
        for (char *n = strtok_r(names, "+", &save2); n; n = strtok_r(NULL, "+", &save2))
            for (int i = 0; i < 16; i++) if (!strcmp(n, pad_names[i])) m |= 1u << i;
        script[nscript++] = (ScriptStep){at, len, m};
    }
    LOG("[input] Testskript mit %d Schritten\n", nscript);
}

static uint64_t buttons_now(void) {
    if (nscript < 0) script_load();
    uint64_t b = key_buttons;
    double t = (rt_now_ns() - g_proc_start_ns) / 1e9;
    for (int i = 0; i < nscript; i++)
        if (t >= script[i].at && t < script[i].at + script[i].len) b |= script[i].mask;
    return b;
}

void input_handle_event(const void *ev) {
    const SDL_Event *e = ev;
    if (e->type != SDL_EVENT_KEY_DOWN && e->type != SDL_EVENT_KEY_UP) return;
    int bit = -1;
    switch (e->key.scancode) {
    case SDL_SCANCODE_RETURN: case SDL_SCANCODE_SPACE: case SDL_SCANCODE_K: bit = PB_A; break;
    case SDL_SCANCODE_BACKSPACE: case SDL_SCANCODE_J: bit = PB_B; break;
    case SDL_SCANCODE_X: bit = PB_X; break;
    case SDL_SCANCODE_Y: bit = PB_Y; break;
    case SDL_SCANCODE_Q: bit = PB_L; break;
    case SDL_SCANCODE_E: bit = PB_R; break;
    case SDL_SCANCODE_P: bit = PB_PLUS; break;
    case SDL_SCANCODE_O: bit = PB_MINUS; break;
    case SDL_SCANCODE_LEFT: case SDL_SCANCODE_A: bit = PB_LEFT; break;
    case SDL_SCANCODE_RIGHT: case SDL_SCANCODE_D: bit = PB_RIGHT; break;
    case SDL_SCANCODE_UP: case SDL_SCANCODE_W: bit = PB_UP; break;
    case SDL_SCANCODE_DOWN: case SDL_SCANCODE_S: bit = PB_DOWN; break;
    default: return;
    }
    if (e->type == SDL_EVENT_KEY_DOWN) atomic_fetch_or(&key_buttons, 1ull << bit);
    else atomic_fetch_and(&key_buttons, ~(1ull << bit));
}

// Npad-Zustand (alle Zustandstypen gleich aufgebaut): {s64 Abtastnummer, u64 Tasten, Stick L {s32 x, y}, Stick R, u32 Attribute}; Spieler 1 ist ein verbundener Pro Controller
static void npad_fill(uint8_t *s) {
    memset(s, 0, 0x28);
    *(int64_t *)s = ++pad_sampling;
    uint64_t b = buttons_now();
    *(uint64_t *)(s + 8) = b;
    *(uint32_t *)(s + 32) = 1;
    static uint64_t last;
    if (b != last && getenv("BDSP_TRACE_INPUT")) LOG("[input] Tasten %#llx\n", (unsigned long long)b);
    last = b;
}
#define NPAD_STATE(sym, fn) HLE_FUNC(sym, fn) { if (*(uint32_t *)G2HC(c->x[1]) == 0) npad_fill((uint8_t *)G2H(c->x[0])); }
#define NPAD_STATES(sym, fn) HLE_FUNC(sym, fn) {                          \
    if (*(uint32_t *)G2HC(c->x[2]) != 0 || (int)c->x[1] < 1) { c->x[0] = 0; return; } \
    npad_fill((uint8_t *)G2H(c->x[0]));                                  \
    c->x[0] = 1;                                                         \
}
NPAD_STATE("_ZN2nn3hid12GetNpadStateEPNS0_16NpadFullKeyStateERKj", npad_s_full)
NPAD_STATE("_ZN2nn3hid12GetNpadStateEPNS0_16NpadJoyDualStateERKj", npad_s_dual)
NPAD_STATE("_ZN2nn3hid12GetNpadStateEPNS0_16NpadJoyLeftStateERKj", npad_s_left)
NPAD_STATE("_ZN2nn3hid12GetNpadStateEPNS0_17NpadHandheldStateERKj", npad_s_hand)
NPAD_STATE("_ZN2nn3hid12GetNpadStateEPNS0_17NpadJoyRightStateERKj", npad_s_right)
NPAD_STATES("_ZN2nn3hid13GetNpadStatesEPNS0_16NpadFullKeyStateEiRKj", npad_ss_full)
NPAD_STATES("_ZN2nn3hid13GetNpadStatesEPNS0_16NpadJoyDualStateEiRKj", npad_ss_dual)
NPAD_STATES("_ZN2nn3hid13GetNpadStatesEPNS0_16NpadJoyLeftStateEiRKj", npad_ss_left)
NPAD_STATES("_ZN2nn3hid13GetNpadStatesEPNS0_17NpadHandheldStateEiRKj", npad_ss_hand)
NPAD_STATES("_ZN2nn3hid13GetNpadStatesEPNS0_17NpadJoyRightStateEiRKj", npad_ss_right)
HLE_FUNC("_ZN2nn3hid15GetNpadStyleSetERKj", npad_style) { c->x[0] = *(uint32_t *)G2HC(c->x[0]) == 0 ? 1 : 0; }  // nur Spieler 1, Stil „Pro Controller“

// ---- Stummel für Hooks des Klons (Breitbild, Zelda-Effekte, Menü, Eingabe, Neustart im Prozess)
void settings_load(void) {}
void rt_window_icon(void *w) { (void)w; }
int rt_reboot_requested(void) { return 0; }
bool input_user_blocked(const void *e) { (void)e; return false; }
bool menu_handle_event(const void *e) { (void)e; return false; }
bool menu_is_open(void) { return false; }
void menu_apply_window_requests(void *w) { (void)w; }
void menu_test_open(void) {}
void menu_render(void *dev, void *cb, void *target) { (void)dev; (void)cb; (void)target; }
void input_frame(uint64_t f) { (void)f; }
void fnprof_frame(uint64_t f) { (void)f; }
void warp_frame(uint64_t f) { (void)f; }
void reboot_test_frame(uint64_t f) { (void)f; }
void save_editor_frame(uint64_t f) { (void)f; }
const char *game_level_name(void) { return "-"; }
char g_window_shot_request[256];
volatile int g_debug_frame_request;
bool g_debug_frame;
bool widescreen_allowed(void) { return false; }
void widescreen_frame_end(uint64_t f) { (void)f; }
void widescreen_set_factor(float f) { (void)f; }
void widescreen_present_crop(uint64_t f, double shape, float *crop, double *vx, double *vy, double *vw, double *vh) {
    (void)f; (void)shape; (void)vx; (void)vy; (void)vw; (void)vh;
    crop[0] = crop[1] = 0; crop[2] = crop[3] = 1;
}
void widescreen_backdrop_seen(uint64_t h) { (void)h; }
float widescreen_effect_stretch(uint64_t h) { (void)h; return 1.0f; }
void widescreen_scene_ubo(const float *u, uint64_t size) { (void)u; (void)size; }
bool mirror_draw(bool composite) { (void)composite; return false; }
bool pets_hide_item_cursor(void) { return false; }
void pot_item_draw(float *m) { (void)m; }
void pot_probe(const float *m, bool tintable, uint64_t mesh, uint32_t inst) { (void)m; (void)tintable; (void)mesh; (void)inst; }
bool pot_tint(const float *m, float tint[8], uint64_t mesh) { (void)m; (void)tint; (void)mesh; return false; }
bool pot_glow_active(void) { return false; }
bool pot_level_active(void) { return false; }
bool pot_instance_gold(const float *m) { (void)m; return false; }
void pot_gold_tint(float tint[8]) { (void)tint; }
void escape_bottle_tint(int kind, const float *ui, uint32_t ui_size, float tint[8]) { (void)kind; (void)ui; (void)ui_size; (void)tint; }
int texpatch_identify(const NvnTexture *t) { (void)t; return -1; }
int texpatch_bottle_kind(int id) { (void)id; return 0; }
bool texpatch_is_item_cursor(int id) { (void)id; return false; }
uint32_t texpatch_generation(void) { return 0; }
void texpatch_apply(int id, uint32_t lv, uint8_t *blocks, uint32_t w, uint32_t h, uint32_t row) { (void)id; (void)lv; (void)blocks; (void)w; (void)h; (void)row; }
int texpatch_heart_kind(int id) { (void)id; return 0; }
void texpatch_heart_tint(int kind, float tint[8]) { (void)kind; (void)tint; }
