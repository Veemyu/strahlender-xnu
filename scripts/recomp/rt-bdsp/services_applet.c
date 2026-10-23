// Library applets for the game: am::ILibraryAppletCreator, ILibraryAppletAccessor and the data channels of the software keyboard.
// Own code. Protocol after Switchbrew (Applet Manager services, Software Keyboard) and libnx applet.c command numbers; every command is
// confirmed by the game's own SDK calls (BDSP_TRACE_APPLET=1 logs them).
#include "applet.h"
#include "swkbd_ui.h"

#define AM_NO_DATA MAKE_RESULT(128, 2)
#define AM_NOT_AVAILABLE MAKE_RESULT(128, 5)

static pthread_mutex_t g_am_lock = PTHREAD_MUTEX_INITIALIZER;
static int trace_applet(void) {
    static int on = -1;
    if (on < 0) on = getenv("BDSP_TRACE_APPLET") != NULL;
    return on;
}

static void ev_signal(KEvent *e) {
    pthread_mutex_lock(&g_klock);
    kernel_signal(e);
    pthread_mutex_unlock(&g_klock);
}
static uint32_t ev_handle(KEvent *e) { return kernel_new_handle(e); }

// ------------------------------------------------------------------ queues of storages
static void q_push(Service **q, int *n, Service *s) {
    pthread_mutex_lock(&g_am_lock);
    if (*n < AM_MAX_Q) { s->refs++; q[(*n)++] = s; }
    pthread_mutex_unlock(&g_am_lock);
}
// The data channel events are level triggered: signaled while the queue holds storages, cleared when the last one is taken
static Service *q_pop(Service **q, int *n, KEvent *ev) {
    pthread_mutex_lock(&g_am_lock);
    Service *s = NULL;
    if (*n) { s = q[0]; memmove(q, q + 1, (--*n) * sizeof *q); }
    if (!*n && ev) { pthread_mutex_lock(&g_klock); ev->signaled = false; pthread_mutex_unlock(&g_klock); }
    pthread_mutex_unlock(&g_am_lock);
    return s;
}

// A storage handed over as an interface object arrives as a domain object (the SDK converts the application proxy to a domain) or, outside
// a domain, as a move handle (the session object that owns the IStorage)
static Service *in_object(IpcReq *req, int i) {
    if (i < req->ndomain_in) return req->domain_in_svc[i];
    if (i >= req->nmove) return NULL;
    KObject *o = handle_get(req->move_handles[i]);
    return o && o->type == KOBJ_SESSION ? ((KSession *)o)->svc : NULL;
}

void applet_push_out(LibApplet *a, Service *storage) {
    q_push(a->out, &a->nout, storage);
    ev_signal(a->ev_out);
}
void applet_push_out_interactive(LibApplet *a, Service *storage) {
    q_push(a->out_inter, &a->nout_inter, storage);
    ev_signal(a->ev_out_inter);
}
void applet_complete(LibApplet *a, uint32_t result) {
    a->result = result;
    a->completed = true;
    ev_signal(a->ev_state);
}

// ------------------------------------------------------------------ software keyboard, protocol-level backend
// KeyboardConfig (Switchbrew, 0x4C8 bytes on SDKs from 6.0.0): the fields the keyboard needs. Output storage 0x7D8 bytes:
// u32 result (0 = Enter, 1 = Cancel), then the text (UTF-16, UTF-8 when IsUseUtf8). Text check: interactive output {u64 8 + text bytes; text},
// interactive input {u32 TextCheckResult; message}.
enum { KC_MODE = 0x0, KC_HEADER = 0x24, KC_SUB = 0xA6, KC_GUIDE = 0x1A8, KC_MAXLEN = 0x3AC, KC_MINLEN = 0x3B0, KC_PASSWORD = 0x3B4,
       KC_UTF8 = 0x3BD, KC_INIT_OFF = 0x3C0, KC_INIT_LEN = 0x3C4, KC_TEXTCHECK = 0x3D0, KC_MIN_SIZE = 0x3D4 };
#define SWKBD_OUT_SIZE 0x7D8
#define SWKBD_INTER_OUT_SIZE 0x7D4

typedef struct { char text[0x400]; bool utf8; bool ui; bool textcheck; LibApplet *applet; } SwkbdState;

static int u16_to_u8(const uint16_t *s, int n, char *out, int cap) {
    int o = 0;
    for (int i = 0; i < n && s[i]; i++) {
        uint32_t c = s[i];
        if (c >= 0xD800 && c < 0xDC00 && i + 1 < n && s[i + 1] >= 0xDC00 && s[i + 1] < 0xE000) { c = 0x10000 + ((c - 0xD800) << 10) + (s[i + 1] - 0xDC00); i++; }
        if (c < 0x80) { if (o + 1 >= cap) break; out[o++] = (char)c; }
        else if (c < 0x800) { if (o + 2 >= cap) break; out[o++] = (char)(0xC0 | (c >> 6)); out[o++] = (char)(0x80 | (c & 0x3F)); }
        else if (c < 0x10000) { if (o + 3 >= cap) break; out[o++] = (char)(0xE0 | (c >> 12)); out[o++] = (char)(0x80 | ((c >> 6) & 0x3F)); out[o++] = (char)(0x80 | (c & 0x3F)); }
        else { if (o + 4 >= cap) break; out[o++] = (char)(0xF0 | (c >> 18)); out[o++] = (char)(0x80 | ((c >> 12) & 0x3F)); out[o++] = (char)(0x80 | ((c >> 6) & 0x3F)); out[o++] = (char)(0x80 | (c & 0x3F)); }
    }
    out[o] = 0;
    return o;
}
static int u8_to_u16(const char *s, uint16_t *out, int cap) {
    int o = 0;
    for (const uint8_t *p = (const uint8_t *)s; *p && o + 1 < cap;) {
        uint32_t c = *p++;
        int extra = c >= 0xF0 ? 3 : c >= 0xE0 ? 2 : c >= 0xC0 ? 1 : 0;
        if (extra) c &= 0x3F >> extra;
        for (int i = 0; i < extra && (*p & 0xC0) == 0x80; i++) c = (c << 6) | (*p++ & 0x3F);
        if (c >= 0x10000 && o + 2 < cap) { c -= 0x10000; out[o++] = (uint16_t)(0xD800 + (c >> 10)); out[o++] = (uint16_t)(0xDC00 + (c & 0x3FF)); }
        else out[o++] = (uint16_t)c;
    }
    out[o] = 0;
    return o;
}

static void swkbd_finish(LibApplet *a, SwkbdState *st, uint32_t result) {
    uint8_t out[SWKBD_OUT_SIZE] = {0};
    *(uint32_t *)out = result;
    if (st->utf8) strncpy((char *)out + 4, st->text, SWKBD_OUT_SIZE - 5);
    else u8_to_u16(st->text, (uint16_t *)(out + 4), (SWKBD_OUT_SIZE - 4) / 2);
    applet_push_out(a, am_storage_new(out, sizeof out));
    applet_complete(a, 0);
}

// On-screen keyboard answers (any thread). Enter: the text goes through the game's own checker when there is one (interactive channel);
// its verdict arrives in swkbd_interactive_in. Cancel: result 1 (the keyboard has already closed).
static void swkbd_ui_submit(void *user, const char *text) {
    SwkbdState *st = user;
    snprintf(st->text, sizeof st->text, "%s", text);
    if (st->textcheck) {
        uint8_t inter[SWKBD_INTER_OUT_SIZE] = {0};
        int n;
        if (st->utf8) { n = (int)strlen(st->text) + 1; memcpy(inter + 8, st->text, n); }
        else { n = 2 * (u8_to_u16(st->text, (uint16_t *)(inter + 8), (SWKBD_INTER_OUT_SIZE - 8) / 2) + 1); }
        *(uint64_t *)inter = 8 + (uint64_t)n;
        applet_push_out_interactive(st->applet, am_storage_new(inter, sizeof inter));
        return;
    }
    swkbd_ui_resolve(1, NULL);
    swkbd_finish(st->applet, st, 0);
}
static void swkbd_ui_cancel(void *user) {
    SwkbdState *st = user;
    st->text[0] = 0;
    swkbd_finish(st->applet, st, 1);
}

static void swkbd_start(LibApplet *a) {
    SwkbdState *st = a->backend_state = calloc(1, sizeof *st);
    AmStorage *cfg = a->nin > 1 ? am_storage_get(a->in[1]) : NULL;
    AmStorage *work = a->nin > 2 ? am_storage_get(a->in[2]) : NULL;
    if (!cfg || cfg->size < KC_MIN_SIZE) { LOG("[am] swkbd: no KeyboardConfig (%d storages)\n", a->nin); swkbd_finish(a, st, 1); return; }
    const uint8_t *c = cfg->data;
    st->utf8 = c[KC_UTF8] != 0;
    uint32_t off = *(const uint32_t *)(c + KC_INIT_OFF), len = *(const uint32_t *)(c + KC_INIT_LEN);
    if (work && len && (uint64_t)off + 2ull * len <= work->size) u16_to_u8((const uint16_t *)(work->data + off), (int)len, st->text, sizeof st->text);
    if (trace_applet()) {
        char hdr[256], sub[256], guide[256];
        u16_to_u8((const uint16_t *)(c + KC_HEADER), 0x41, hdr, sizeof hdr);
        u16_to_u8((const uint16_t *)(c + KC_SUB), 0x81, sub, sizeof sub);
        u16_to_u8((const uint16_t *)(c + KC_GUIDE), 0x101, guide, sizeof guide);
        LOG("[am] swkbd: mode %u, header \"%s\", sub \"%s\", guide \"%s\", length %d..%d, password %u, utf8 %d, textcheck %d, initial \"%s\" (cfg %llu, work %llu bytes)\n",
            *(const uint32_t *)(c + KC_MODE), hdr, sub, guide, *(const int32_t *)(c + KC_MINLEN), *(const int32_t *)(c + KC_MAXLEN),
            *(const uint32_t *)(c + KC_PASSWORD), st->utf8, c[KC_TEXTCHECK], st->text, (unsigned long long)cfg->size, (unsigned long long)(work ? work->size : 0));
    }
    // On-screen keyboard (swkbd_ui.c) when the firmware layouts are available and nobody scripts the run; otherwise the automatic answer below.
    st->applet = a;
    st->textcheck = c[KC_TEXTCHECK] && fs_system_data_exists(0x0100000000000823ull);
    bool scripted = getenv("BDSP_SWKBD_TEXT") || getenv("BDSP_SWKBD_AUTO") || getenv("BDSP_INPUT_SCRIPT") || getenv("BDSP_KEY_SCRIPT") || getenv("BDSP_NO_ALERT");
    if ((!scripted || getenv("BDSP_SWKBD_UI")) && swkbd_ui_available()) {   // BDSP_SWKBD_UI=1: keyboard even in a scripted test run
        SwkbdParams p = {0};
        p.mode = *(const uint32_t *)(c + KC_MODE);
        u16_to_u8((const uint16_t *)(c + KC_HEADER), 0x41, p.header, sizeof p.header);
        u16_to_u8((const uint16_t *)(c + KC_SUB), 0x81, p.sub, sizeof p.sub);
        u16_to_u8((const uint16_t *)(c + KC_GUIDE), 0x101, p.guide, sizeof p.guide);
        snprintf(p.initial, sizeof p.initial, "%s", st->text);
        p.minlen = *(const int32_t *)(c + KC_MINLEN);
        p.maxlen = *(const int32_t *)(c + KC_MAXLEN);
        p.password = *(const uint32_t *)(c + KC_PASSWORD) != 0;
        SwkbdCallbacks cb = {swkbd_ui_submit, swkbd_ui_cancel};
        if (swkbd_ui_open(&p, cb, st) == 0) { st->ui = true; LOG("[am] swkbd: on-screen keyboard open\n"); return; }
    }
    // Interim policy until a keyboard UI exists: BDSP_SWKBD_TEXT=<text> answers with that text; otherwise the initial text, otherwise "Player".
    // Cut to the length limit (ASCII only here); an answer shorter than the minimum is padded with the last character.
    const char *forced = getenv("BDSP_SWKBD_TEXT");
    if (forced) snprintf(st->text, sizeof st->text, "%s", forced);
    else if (!st->text[0]) snprintf(st->text, sizeof st->text, "Player");
    int maxlen = *(const int32_t *)(c + KC_MAXLEN), minlen = *(const int32_t *)(c + KC_MINLEN);
    if (maxlen > 0 && (int)strlen(st->text) > maxlen) st->text[maxlen] = 0;
    for (int n = (int)strlen(st->text); n > 0 && n < minlen && n < (int)sizeof st->text - 1; n++) st->text[n] = st->text[n - 1], st->text[n + 1] = 0;
    uint32_t result = st->text[0] ? 0 : 1;
    // The game's own checker (NG words) decides first, through the interactive channel. It reads the firmware's profanity data
    // (data id 0x0100000000000823); without that archive the SDK aborts, so the check is skipped then.
    bool ng_data = fs_system_data_exists(0x0100000000000823ull);
    if (c[KC_TEXTCHECK] && !ng_data) LOG("[am] swkbd: text check skipped (no firmware data 0100000000000823, BDSP_FIRMWARE_DATA)\n");
    if (c[KC_TEXTCHECK] && result == 0 && ng_data) {
        uint8_t inter[SWKBD_INTER_OUT_SIZE] = {0};
        int n;
        if (st->utf8) { n = (int)strlen(st->text) + 1; memcpy(inter + 8, st->text, n); }
        else { n = 2 * (u8_to_u16(st->text, (uint16_t *)(inter + 8), (SWKBD_INTER_OUT_SIZE - 8) / 2) + 1); }
        *(uint64_t *)inter = 8 + (uint64_t)n;
        applet_push_out_interactive(a, am_storage_new(inter, sizeof inter));
        return;
    }
    swkbd_finish(a, st, result);
}

static void swkbd_interactive_in(LibApplet *a) {
    SwkbdState *st = a->backend_state;
    AmStorage *r = a->ninter ? am_storage_get(a->in_inter[a->ninter - 1]) : NULL;
    uint32_t check = r && r->size >= 4 ? *(const uint32_t *)r->data : 0;
    if (trace_applet()) LOG("[am] swkbd: text check result %u\n", check);
    if (st->ui && swkbd_ui_active()) {   // the keyboard stays open on a rejected text and shows the checker's message
        if (check == 0) { swkbd_ui_resolve(1, NULL); swkbd_finish(a, st, 0); return; }
        char msg[256] = "This text cannot be used.";
        if (r && r->size > 6 && ((const uint16_t *)(r->data + 4))[0]) u16_to_u8((const uint16_t *)(r->data + 4), (int)((r->size - 4) / 2), msg, sizeof msg);
        swkbd_ui_resolve(0, msg);
        return;
    }
    swkbd_finish(a, st, check == 0 ? 0 : 1);
}

static const AppletBackend swkbd_backend = {"swkbd (protocol only)", swkbd_start, swkbd_interactive_in};

const AppletBackend *applet_backend_for(uint32_t applet_id) {
    return applet_id == AM_APPLET_SWKBD ? &swkbd_backend : NULL;
}

// ------------------------------------------------------------------ ILibraryAppletAccessor
static void accessor_handler(Service *s, IpcReq *req, IpcResp *resp) {
    LibApplet *a = s->state;
    if (trace_applet()) LOG("[am] ILibraryAppletAccessor cmd %u (data %u, handles %d/%d)\n", req->cmd, req->data_size, req->ncopy, req->nmove);
    switch (req->cmd) {
    case 0: resp->copy_handles[resp->ncopy++] = ev_handle(a->ev_state); break;           // GetAppletStateChangedEvent
    case 1: OUT(uint8_t, 0) = a->completed; resp_size(resp, 1); break;                    // IsCompleted
    case 10: {                                                                             // Start
        if (!a->started) { a->started = true; if (a->backend->start) a->backend->start(a); }
        break;
    }
    case 20: case 25: break;                                                               // RequestExit, Terminate
    case 30: resp->result = a->result; break;                                              // GetResult
    case 50: case 60: case 150: break;                                                     // out-of-focus suspending, GPU time slice, foreground request
    case 100: {                                                                            // PushInData(IStorage)
        Service *st = in_object(req, 0);
        if (st) q_push(a->in, &a->nin, st);
        break;
    }
    case 101: {                                                                            // PopOutData -> IStorage
        Service *st = q_pop(a->out, &a->nout, a->ev_out);
        if (st) ipc_return_object(resp, st); else resp->result = AM_NO_DATA;
        break;
    }
    case 103: {                                                                            // PushInteractiveInData(IStorage)
        Service *st = in_object(req, 0);
        if (st) { q_push(a->in_inter, &a->ninter, st); if (a->backend->interactive_in) a->backend->interactive_in(a); }
        break;
    }
    case 104: {                                                                            // PopInteractiveOutData -> IStorage
        Service *st = q_pop(a->out_inter, &a->nout_inter, a->ev_out_inter);
        if (st) ipc_return_object(resp, st); else resp->result = AM_NO_DATA;
        break;
    }
    case 105: resp->copy_handles[resp->ncopy++] = ev_handle(a->ev_out); break;            // GetPopOutDataEvent
    case 106: resp->copy_handles[resp->ncopy++] = ev_handle(a->ev_out_inter); break;      // GetPopInteractiveOutDataEvent
    case 110: OUT(uint8_t, 0) = 0; resp_size(resp, 1); break;                              // NeedsToExitProcess
    default: ipc_note("ILibraryAppletAccessor", req->cmd, 1); resp_size(resp, 0x10);
    }
}

// ------------------------------------------------------------------ ILibraryAppletCreator
void am_library_applet_creator(Service *s, IpcReq *req, IpcResp *resp) {
    (void)s;
    if (trace_applet()) LOG("[am] ILibraryAppletCreator cmd %u (data %u, handles %d/%d)\n", req->cmd, req->data_size, req->ncopy, req->nmove);
    switch (req->cmd) {
    case 0: {                                                                              // CreateLibraryApplet(applet id, mode)
        uint32_t id = IN(uint32_t, 0), mode = IN(uint32_t, 4);
        const AppletBackend *be = applet_backend_for(id);
        if (trace_applet()) LOG("[am] CreateLibraryApplet id 0x%x mode %u -> %s\n", id, mode, be ? be->name : "not available");
        if (!be) { resp->result = AM_NOT_AVAILABLE; break; }
        LibApplet *a = calloc(1, sizeof *a);
        a->applet_id = id;
        a->mode = mode;
        a->backend = be;
        a->ev_state = kernel_create_event_pair(NULL, &a->ev_state_r);
        a->ev_out = kernel_create_event_pair(NULL, &a->ev_out_r);
        a->ev_out_inter = kernel_create_event_pair(NULL, &a->ev_out_inter_r);
        ipc_return_object(resp, service_new("ILibraryAppletAccessor", accessor_handler, a));
        break;
    }
    case 1: break;                                                                         // TerminateAllLibraryApplets
    case 2: OUT(uint8_t, 0) = 0; resp_size(resp, 1); break;                                // AreAnyLibraryAppletsLeft
    case 10: ipc_return_object(resp, am_storage_new(NULL, (uint64_t)IN(int64_t, 0))); break;   // CreateStorage(size)
    case 11: {                                                                             // CreateTransferMemoryStorage(writable, size) + transfer memory handle
        KObject *o = req->ncopy ? handle_get(req->copy_handles[0]) : NULL;
        if (!o || o->type != KOBJ_TMEM) { resp->result = AM_NOT_AVAILABLE; break; }
        KTransferMem *t = (KTransferMem *)o;
        uint64_t size = IN(uint64_t, 8);
        if (size > t->size) size = t->size;
        Service *st = am_storage_new(NULL, 0);
        AmStorage *as = am_storage_get(st);
        free(as->data);
        as->data = G2H(t->addr);
        as->size = size;
        as->borrowed = true;
        ipc_return_object(resp, st);
        break;
    }
    default: ipc_note("ILibraryAppletCreator", req->cmd, 1); resp_size(resp, 0x10);
    }
}
