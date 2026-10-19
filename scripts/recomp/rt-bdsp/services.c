// Dienste der BDSP-Laufzeit (sm:-Unterobjekte): lm, apm, appletOE, acc:u0, aoc:u, pctl, ectx:aw, set, set:sys, time, hid.
// Eigener Code; Aufbau und Teile der Antworten (Zeitdienst-Gemeinsamspeicher, Sprachliste, Profilstruktur) nach LASRecomp
// runtime/services/*.c (MIT, Copyright (c) 2026 Peiikai, siehe NOTICE.md). Neu gegenüber dem Vorbild: vollständige
// ICommonStateGetter-/ISelfController-/IApplicationFunctions-Tabellen (Ereignis-Handles für alle bekannten *Event-Befehle),
// Mitschrift nicht umgesetzter Befehle (ipc_note), Sprache über BDSP_LANG.
#include <sys/time.h>
#include <time.h>

#include "bdsp.h"

void ipc_note(const char *svc, uint32_t cmd, int unhandled);
void guest_log(const char *line);

const char *settings_language(void) { return getenv("BDSP_LANG") ? getenv("BDSP_LANG") : "en-US"; }

static uint32_t new_event_handle(void) {
    uint32_t w, r;
    kernel_create_event_pair(&w, &r);
    return r;
}
#define EVENT_OUT() (resp->copy_handles[resp->ncopy++] = new_event_handle())
#define UNHANDLED(name) do { ipc_note(name, req->cmd, 1); resp_size(resp, 0x10); } while (0)

// ------------------------------------------------------------------ lm (Gast-Log)
static void lm_logger(Service *s, IpcReq *req, IpcResp *resp) {
    (void)s; (void)resp;
    if (req->cmd != 0) { ipc_note("lm:ILogger", req->cmd, 1); return; }
    IpcBuf *b = in_buf(req, 0);
    if (!b || !b->size) return;
    // Paketaufbau: 0x18 Byte Kopf, danach TLV-Blöcke (Schlüssel, Länge, Wert); Textblöcke ausgeben
    const uint8_t *p = G2H8(b->addr), *end = p + b->size;
    p += 0x18;
    char line[1024];
    int n = 0;
    while (p + 2 <= end) {
        uint8_t key = p[0], len = p[1];
        p += 2;
        if (p + len > end) break;
        if (key == 2 || key == 4 || key == 5 || key == 6 || key == 7) {
            n += snprintf(line + n, sizeof line - n, "%s%.*s", n ? " | " : "", len, (const char *)p);
            if (n >= (int)sizeof line) { n = sizeof line - 1; break; }
        }
        p += len;
    }
    if (n) guest_log(line);
}
static void lm_service(Service *s, IpcReq *req, IpcResp *resp) {
    (void)s;
    if (req->cmd == 0) ipc_return_object(resp, service_new("lm:ILogger", lm_logger, NULL));
    else ipc_note("lm", req->cmd, 1);
}

// ------------------------------------------------------------------ apm
static void apm_session(Service *s, IpcReq *req, IpcResp *resp) {
    (void)s;
    if (req->cmd == 0) return;                                              // SetPerformanceConfiguration
    if (req->cmd == 1) { OUT(uint32_t, 0) = 0x92220008; resp_size(resp, 4); return; }  // GetPerformanceConfiguration
    if (req->cmd == 2 || req->cmd == 3) { resp->copy_handles[resp->ncopy++] = new_event_handle(); return; }  // Ereignis
    UNHANDLED("apm:ISession");
}
static void apm_service(Service *s, IpcReq *req, IpcResp *resp) {
    (void)s;
    if (req->cmd == 0) ipc_return_object(resp, service_new("apm:ISession", apm_session, NULL));
    else if (req->cmd == 1) { OUT(uint32_t, 0) = 1; resp_size(resp, 4); }  // GetPerformanceMode: Boost
    else if (req->cmd == 6) { OUT(uint8_t, 0) = 0; resp_size(resp, 1); }   // IsCpuOverclockEnabled
    else UNHANDLED("apm");
}

// ------------------------------------------------------------------ appletOE
#define AM_NO_MESSAGE MAKE_RESULT(128, 3)
#define AM_NO_DATA MAKE_RESULT(128, 2)
static KEvent *msg_event;
static uint32_t msg_event_r, msg_event_w;
static uint32_t msg_queue[16];
static int msg_count;
static bool preselected_popped;
const uint8_t g_user_id[16] = {0x42, 0x44, 0x53, 0x50, 0x72, 0x65, 0x63, 0x6f, 0x6d, 0x70, 0x01, 0, 0, 0, 0, 0x01};

static void am_init_once(void) {
    if (msg_event) return;
    msg_event = kernel_create_event_pair(&msg_event_w, &msg_event_r);
    msg_queue[msg_count++] = 15;  // FocusStateChanged
    pthread_mutex_lock(&g_klock);
    kernel_signal(msg_event);
    pthread_mutex_unlock(&g_klock);
}

static void common_state_getter(Service *s, IpcReq *req, IpcResp *resp) {
    (void)s;
    switch (req->cmd) {
    case 0: resp->copy_handles[resp->ncopy++] = msg_event_r; break;  // GetEventHandle
    case 1:                                                           // ReceiveMessage
        pthread_mutex_lock(&g_klock);
        if (msg_count) {
            OUT(uint32_t, 0) = msg_queue[0];
            memmove(msg_queue, msg_queue + 1, --msg_count * sizeof(uint32_t));
            if (!msg_count) msg_event->signaled = false;
            resp_size(resp, 4);
        } else resp->result = AM_NO_MESSAGE;
        pthread_mutex_unlock(&g_klock);
        break;
    case 5: OUT(uint8_t, 0) = 1; resp_size(resp, 1); break;   // GetOperationMode: Dock
    case 6: OUT(uint32_t, 0) = 1; resp_size(resp, 4); break;  // GetPerformanceMode: Boost
    case 8: OUT(uint8_t, 0) = 0; resp_size(resp, 1); break;   // GetBootMode
    case 9: OUT(uint8_t, 0) = 1; resp_size(resp, 1); break;   // GetCurrentFocusState: im Fokus
    case 13: case 61: EVENT_OUT(); break;                      // Sleep-Lock-/Auflösungsereignis
    case 60: OUT(int32_t, 0) = 1920; OUT(int32_t, 4) = 1080; resp_size(resp, 8); break;  // GetDefaultDisplayResolution
    case 10: case 11: case 12: case 20: case 30: case 31: case 900: resp_size(resp, 0x10); break;  // Sleep-Lock, PushToGeneralChannel, CpuBoost
    default: UNHANDLED("ICommonStateGetter");
    }
}
static void self_controller(Service *s, IpcReq *req, IpcResp *resp) {
    (void)s;
    switch (req->cmd) {
    case 0: LOG("[am] Anwendung verlangt Beenden (Exit)\n"); g_stop = 3; break;
    case 9: case 91: EVENT_OUT(); break;                                  // LaunchableEvent, AccumulatedSuspendedTickChangedEvent
    case 40: OUT(uint64_t, 0) = 1; resp_size(resp, 8); break;           // CreateManagedDisplayLayer
    case 41: case 69: OUT(uint8_t, 0) = 0; resp_size(resp, 1); break;   // IsSystemBufferSharingEnabled, IsAutoSleepDisabled
    case 63: OUT(uint32_t, 0) = 0; resp_size(resp, 4); break;           // GetIdleTimeDetectionExtension
    case 66: OUT(float, 0) = 0.f; resp_size(resp, 4); break;            // GetCurrentIlluminance
    case 67: OUT(uint8_t, 0) = 0; resp_size(resp, 1); break;            // IsIlluminanceAvailable
    case 90: OUT(uint64_t, 0) = 0; resp_size(resp, 8); break;           // GetAccumulatedSuspendedTickValue
    case 1: case 2: case 3: case 4: case 10: case 11: case 12: case 13: case 14: case 16: case 19: case 50: case 51: case 60: case 62:
    case 64: case 65: case 68: case 70: case 80: case 100: case 1000: resp_size(resp, 0x10); break;
    default: UNHANDLED("ISelfController");
    }
}
static void window_controller(Service *s, IpcReq *req, IpcResp *resp) {
    (void)s;
    switch (req->cmd) {
    case 1: OUT(uint64_t, 0) = 0x1234; resp_size(resp, 8); break;  // GetAppletResourceUserId
    case 10: case 11: case 12: resp_size(resp, 0x10); break;       // Foreground-Rechte
    default: UNHANDLED("IWindowController");
    }
}
static void generic_ok(Service *s, IpcReq *req, IpcResp *resp) {
    ipc_note(s->name, req->cmd, 1);
    resp_size(resp, 0x10);
}

typedef struct { uint8_t *data; uint64_t size; } AmStorage;
static void storage_accessor(Service *s, IpcReq *req, IpcResp *resp) {
    AmStorage *st = s->state;
    switch (req->cmd) {
    case 0: OUT(int64_t, 0) = (int64_t)st->size; resp_size(resp, 8); break;
    case 10: {  // Write(offset, A)
        int64_t off = IN(int64_t, 0);
        IpcBuf *a = in_buf(req, 0);
        uint64_t n = a->size;
        if ((uint64_t)off + n > st->size) n = st->size - (uint64_t)off;
        memcpy(st->data + off, G2H(a->addr), n);
        break;
    }
    case 11: {  // Read(offset, B)
        int64_t off = IN(int64_t, 0);
        IpcBuf *b = out_buf(req, 0);
        uint64_t n = b->size;
        if ((uint64_t)off + n > st->size) n = st->size - (uint64_t)off;
        memcpy(G2H(b->addr), st->data + off, n);
        break;
    }
    default: ipc_note("IStorageAccessor", req->cmd, 1);
    }
}
static void am_storage(Service *s, IpcReq *req, IpcResp *resp) {
    if (req->cmd == 0) ipc_return_object(resp, service_new("IStorageAccessor", storage_accessor, s->state));
    else ipc_note("IStorage", req->cmd, 1);
}
static Service *new_am_storage(const void *data, uint64_t size) {
    AmStorage *st = calloc(1, sizeof *st);
    st->data = calloc(1, size);
    st->size = size;
    if (data) memcpy(st->data, data, size);
    return service_new("IStorage", am_storage, st);
}

static void application_functions(Service *s, IpcReq *req, IpcResp *resp) {
    (void)s;
    switch (req->cmd) {
    case 1:  // PopLaunchParameter(kind): einmalig der vorgewählte Benutzer
        if (IN(uint32_t, 0) == 2 && !preselected_popped) {
            uint8_t p[0x88] = {0};
            *(uint32_t *)p = 0xC79497CA;
            *(uint32_t *)(p + 4) = 1;
            memcpy(p + 8, g_user_id, 16);
            preselected_popped = true;
            ipc_return_object(resp, new_am_storage(p, sizeof p));
        } else resp->result = AM_NO_DATA;
        break;
    case 20: OUT(uint64_t, 0) = 0; resp_size(resp, 8); break;  // EnsureSaveData -> Ergebnis „vorhanden“
    case 21: {                                                  // GetDesiredLanguage
        char lang[8] = {0};
        snprintf(lang, sizeof lang, "%s", settings_language());
        memcpy(resp->data, lang, 8);
        resp_size(resp, 8);
        break;
    }
    case 23: memcpy(resp->data, "1.0.0", 6); resp_size(resp, 0x10); break;  // GetDisplayVersion
    case 25: case 26: OUT(int64_t, 0) = 0; resp_size(resp, 8); break;       // ExtendSaveData, GetSaveDataSize
    case 40: OUT(uint8_t, 0) = 0; resp_size(resp, 1); break;                // NotifyRunning
    case 50: memset(resp->data, 0x5a, 16); resp_size(resp, 16); break;      // GetPseudoDeviceId
    case 130: case 140: case 150: case 160: EVENT_OUT(); break;            // Gpu-/Einladungs-/Benachrichtigungs-/Health-Ereignis
    case 22: case 30: case 31: case 32: case 33: case 60: case 66: case 67: case 68: case 90: case 100: case 101: case 102: case 110: case 111:
    case 121: case 124: case 170: case 190: resp_size(resp, 0x10); break;
    case 123: OUT(int32_t, 0) = 0; resp_size(resp, 4); break;               // GetPreviousProgramIndex
    case 180: case 200: OUT(uint64_t, 0) = 0; resp_size(resp, 8); break;
    default: UNHANDLED("IApplicationFunctions");
    }
}
static void application_proxy(Service *s, IpcReq *req, IpcResp *resp) {
    (void)s;
    static const struct { int cmd; const char *name; ServiceHandler h; } subs[] = {
        {0, "ICommonStateGetter", common_state_getter}, {1, "ISelfController", self_controller}, {2, "IWindowController", window_controller},
        {3, "IAudioController", generic_ok}, {4, "IDisplayController", generic_ok}, {10, "IProcessWindingController", generic_ok},
        {11, "ILibraryAppletCreator", generic_ok}, {20, "IApplicationFunctions", application_functions}, {1000, "IDebugFunctions", generic_ok},
    };
    for (unsigned i = 0; i < sizeof subs / sizeof *subs; i++)
        if (subs[i].cmd == (int)req->cmd) { ipc_return_object(resp, service_new(subs[i].name, subs[i].h, NULL)); return; }
    UNHANDLED("IApplicationProxy");
}
static void applet_oe(Service *s, IpcReq *req, IpcResp *resp) {
    (void)s;
    am_init_once();
    if (req->cmd == 0) ipc_return_object(resp, service_new("IApplicationProxy", application_proxy, NULL));
    else UNHANDLED("appletOE");
}

// ------------------------------------------------------------------ acc:u0 (ein lokaler Benutzer)
static void write_uid_list(IpcReq *req) {
    IpcBuf *c = out_buf(req, 0);
    if (!c) return;
    memset(G2H(c->addr), 0, c->size);
    if (c->size >= 16) memcpy(G2H(c->addr), g_user_id, 16);
}
static void acc_profile(Service *s, IpcReq *req, IpcResp *resp) {
    (void)s;
    switch (req->cmd) {
    case 0: case 1:  // Get / GetBase -> ProfileBase {uid, Zeitstempel, Spitzname[0x20]}
        memset(resp->data, 0, 0x38);
        memcpy(resp->data, g_user_id, 16);
        *(uint64_t *)(resp->data + 16) = 1600000000;
        strcpy((char *)resp->data + 24, "Player");
        resp_size(resp, 0x38);
        if (req->cmd == 0 && out_buf(req, 0)) memset(G2H(out_buf(req, 0)->addr), 0, out_buf(req, 0)->size);
        break;
    case 10: case 11: OUT(uint32_t, 0) = 0; resp_size(resp, 4); break;
    default: UNHANDLED("acc:IProfile");
    }
}
static void acc_manager(Service *s, IpcReq *req, IpcResp *resp) {
    (void)s;
    switch (req->cmd) {
    case 0: break;
    case 1: OUT(uint64_t, 0) = 0x1234567890abcdefull; resp_size(resp, 8); break;
    default: UNHANDLED("acc:IManagerForApplication");
    }
}
static void acc_u0(Service *s, IpcReq *req, IpcResp *resp) {
    (void)s;
    switch (req->cmd) {
    case 0: OUT(int32_t, 0) = 1; resp_size(resp, 4); break;
    case 1: OUT(uint8_t, 0) = !memcmp(req->data, g_user_id, 16); resp_size(resp, 1); break;
    case 2: case 3: case 131: case 141: write_uid_list(req); break;
    case 4: case 51: memcpy(resp->data, g_user_id, 16); resp_size(resp, 16); break;
    case 5: ipc_return_object(resp, service_new("IProfile", acc_profile, NULL)); break;
    case 50: OUT(uint8_t, 0) = 0; resp_size(resp, 1); break;
    case 100: case 140: break;
    case 101: ipc_return_object(resp, service_new("IManagerForApplication", acc_manager, NULL)); break;
    case 150: OUT(uint8_t, 0) = 0; resp_size(resp, 1); break;
    default: UNHANDLED("acc:u0");
    }
}

// ------------------------------------------------------------------ aoc:u (keine DLC), pctl (keine Einschränkungen), ectx:aw
static void aoc_u(Service *s, IpcReq *req, IpcResp *resp) {
    (void)s;
    switch (req->cmd) {
    case 2: case 3: OUT(uint32_t, 0) = 0; resp_size(resp, 4); break;      // CountAddOnContent, ListAddOnContent
    case 5: OUT(uint64_t, 0) = 0; resp_size(resp, 8); break;
    case 8: EVENT_OUT(); break;
    default: UNHANDLED("aoc:u");
    }
}
static void pctl_service(Service *s, IpcReq *req, IpcResp *resp) {
    (void)s;
    switch (req->cmd) {
    case 1031: case 1035: case 1018: OUT(uint8_t, 0) = 0; resp_size(resp, 1); break;
    case 1032: OUT(uint32_t, 0) = 0; resp_size(resp, 4); break;
    case 1001: case 1002: resp_size(resp, 0x10); break;
    default: UNHANDLED("IParentalControlService");
    }
}
static void pctl_root(Service *s, IpcReq *req, IpcResp *resp) {
    (void)s;
    if (req->cmd == 0 || req->cmd == 1) ipc_return_object(resp, service_new("IParentalControlService", pctl_service, NULL));
    else UNHANDLED("pctl");
}
static void ectx_writer(Service *s, IpcReq *req, IpcResp *resp) { (void)s; resp_size(resp, 0x10); (void)req; }  // Fehlerkontext: verwerfen

// ------------------------------------------------------------------ set / set:sys
static const char *const languages[] = {"ja", "en-US", "fr", "de", "it", "es", "zh-CN", "ko", "nl", "pt", "ru", "zh-TW", "en-GB", "fr-CA", "es-419", "zh-Hans", "zh-Hant", "pt-BR"};
#define NLANG 18
static uint64_t lang_code(const char *s) { uint64_t v = 0; memcpy(&v, s, strlen(s) < 8 ? strlen(s) : 8); return v; }
static void language_list(IpcReq *req, IpcResp *resp, int max) {
    IpcBuf *b = out_buf(req, 0);
    int n = 0;
    if (b) {
        uint64_t *out = G2H64(b->addr);
        for (; n < max && n < NLANG && (uint64_t)(n + 1) * 8 <= b->size; n++) out[n] = lang_code(languages[n]);
    }
    OUT(int32_t, 0) = n;
    resp_size(resp, 4);
}
static void set_service(Service *s, IpcReq *req, IpcResp *resp) {
    (void)s;
    switch (req->cmd) {
    case 0: OUT(uint64_t, 0) = lang_code(settings_language()); resp_size(resp, 8); break;
    case 1: language_list(req, resp, 15); break;
    case 2: { uint32_t i = IN(uint32_t, 0); OUT(uint64_t, 0) = i < NLANG ? lang_code(languages[i]) : 0; resp_size(resp, 8); break; }
    case 3: OUT(int32_t, 0) = 15; resp_size(resp, 4); break;
    case 4: OUT(uint32_t, 0) = 1; resp_size(resp, 4); break;  // GetRegionCode: USA
    case 5: language_list(req, resp, NLANG); break;
    case 6: OUT(int32_t, 0) = NLANG; resp_size(resp, 4); break;
    case 8: OUT(uint8_t, 0) = 0; resp_size(resp, 1); break;
    default: UNHANDLED("set");
    }
}
static void set_sys(Service *s, IpcReq *req, IpcResp *resp) {
    (void)s;
    switch (req->cmd) {
    case 3: case 4: {  // GetFirmwareVersion(2)
        IpcBuf *b = out_buf(req, 0);
        if (b) {
            uint8_t *v = G2H8(b->addr);
            memset(v, 0, 0x100);
            v[0] = 13; v[1] = 1; v[2] = 0; v[4] = 13; v[5] = 1; v[6] = 0;
            strcpy((char *)v + 0x68, "13.1.0");
            strcpy((char *)v + 0x80, "13.1.0-1.0");
        }
        break;
    }
    case 23: OUT(uint32_t, 0) = 1; resp_size(resp, 4); break;
    default: UNHANDLED("set:sys");
    }
}

// ------------------------------------------------------------------ time
static const uint8_t clock_uuid[16] = {0x42, 0x44, 0x53, 0x50, 0x72, 0x65, 0x63, 0x6f, 1, 2, 3, 4, 5, 6, 7, 8};
static int64_t steady_seconds(void) { return (int64_t)(rt_ticks() / 19200000ull); }
static int64_t unix_now(void) { return (int64_t)time(NULL); }
static void write_system_context(uint8_t *p) {  // SystemClockContext (0x20)
    int64_t steady = steady_seconds();
    *(int64_t *)p = unix_now() - steady;
    *(int64_t *)(p + 8) = steady;
    memcpy(p + 0x10, clock_uuid, 16);
}
static void time_shmem_map(KSharedMem *s) {
    uint8_t *m = G2H8(s->guest_addr);
    *(uint32_t *)m = 0;
    *(uint64_t *)(m + 0x08) = 0;
    memcpy(m + 0x10, clock_uuid, 16);
    *(uint32_t *)(m + 0x38) = 0;
    write_system_context(m + 0x40);
    *(uint32_t *)(m + 0x80) = 0;
    write_system_context(m + 0x88);
    *(uint32_t *)(m + 0xC8) = 0;
    m[0xCC] = 0;
}
static void system_clock(Service *s, IpcReq *req, IpcResp *resp) {
    (void)s;
    switch (req->cmd) {
    case 0: OUT(int64_t, 0) = unix_now(); resp_size(resp, 8); break;
    case 2: write_system_context(resp->data); resp_size(resp, 0x20); break;
    default: UNHANDLED("ISystemClock");
    }
}
static void steady_clock(Service *s, IpcReq *req, IpcResp *resp) {
    (void)s;
    if (req->cmd == 0) { OUT(int64_t, 0) = steady_seconds(); memcpy(resp->data + 8, clock_uuid, 16); resp_size(resp, 0x18); }
    else { OUT(int64_t, 0) = 0; resp_size(resp, 8); ipc_note("ISteadyClock", req->cmd, 1); }
}
static void to_calendar(int64_t t, IpcResp *resp, int utc) {
    time_t tt = (time_t)t;
    struct tm tm;
    if (utc) gmtime_r(&tt, &tm); else localtime_r(&tt, &tm);
    uint8_t *o = resp->data;
    *(uint16_t *)o = (uint16_t)(tm.tm_year + 1900);
    o[2] = (uint8_t)(tm.tm_mon + 1); o[3] = (uint8_t)tm.tm_mday; o[4] = (uint8_t)tm.tm_hour; o[5] = (uint8_t)tm.tm_min; o[6] = (uint8_t)tm.tm_sec;
    *(uint32_t *)(o + 8) = (uint32_t)tm.tm_wday;
    *(uint32_t *)(o + 12) = (uint32_t)tm.tm_yday;
    memcpy(o + 16, utc ? "UTC" : tm.tm_zone, 4);
    *(uint32_t *)(o + 24) = (uint32_t)tm.tm_isdst;
    *(int32_t *)(o + 28) = utc ? 0 : (int32_t)tm.tm_gmtoff;
    resp_size(resp, 0x20);
}
static void timezone_service(Service *s, IpcReq *req, IpcResp *resp) {
    (void)s;
    switch (req->cmd) {
    case 0: memcpy(resp->data, "UTC", 4); resp_size(resp, 0x24); break;
    case 100: to_calendar(IN(int64_t, 0), resp, 1); break;
    case 101: to_calendar(IN(int64_t, 0), resp, 0); break;
    case 201: case 202: {
        const uint8_t *in = req->data;
        struct tm tm = {0};
        tm.tm_year = *(uint16_t *)in - 1900; tm.tm_mon = in[2] - 1; tm.tm_mday = in[3]; tm.tm_hour = in[4]; tm.tm_min = in[5]; tm.tm_sec = in[6]; tm.tm_isdst = -1;
        int64_t t = mktime(&tm);
        if (req->nc) *(int64_t *)G2H(req->c[0].addr) = t;
        else if (req->nb) *(int64_t *)G2H(req->b[0].addr) = t;
        OUT(uint32_t, 0) = 1;
        resp_size(resp, 4);
        break;
    }
    default: UNHANDLED("ITimeZoneService");
    }
}
static uint32_t g_time_shmem_handle;
static void time_static(Service *s, IpcReq *req, IpcResp *resp) {
    (void)s;
    switch (req->cmd) {
    case 0: case 1: case 4: case 5: ipc_return_object(resp, service_new("ISystemClock", system_clock, NULL)); break;
    case 2: ipc_return_object(resp, service_new("ISteadyClock", steady_clock, NULL)); break;
    case 3: ipc_return_object(resp, service_new("ITimeZoneService", timezone_service, NULL)); break;
    case 20:
        if (!g_time_shmem_handle) kernel_create_shared_memory(0x1000, time_shmem_map, &g_time_shmem_handle);
        resp->copy_handles[resp->ncopy++] = g_time_shmem_handle;
        break;
    case 100: case 101: OUT(uint8_t, 0) = 0; resp_size(resp, 1); break;
    default: UNHANDLED("IStaticService");
    }
}

// ------------------------------------------------------------------ hid (gemeinsamer Speicher, Eingaben bleiben leer)
static uint32_t hid_shmem_handle;
static void hid_applet_resource(Service *s, IpcReq *req, IpcResp *resp) {
    (void)s;
    if (req->cmd == 0) {
        if (!hid_shmem_handle) kernel_create_shared_memory(0x40000, NULL, &hid_shmem_handle);
        resp->copy_handles[resp->ncopy++] = hid_shmem_handle;
    } else UNHANDLED("IAppletResource");
}
static void hid_service(Service *s, IpcReq *req, IpcResp *resp) {
    (void)s;
    switch (req->cmd) {
    case 0: ipc_return_object(resp, service_new("IAppletResource", hid_applet_resource, NULL)); break;
    case 40: case 106: EVENT_OUT(); break;
    case 101: OUT(uint32_t, 0) = 0x1F; resp_size(resp, 4); break;
    case 121: case 129: OUT(int64_t, 0) = 0; resp_size(resp, 8); break;
    case 200: memset(resp->data, 0, 0x10); OUT(uint32_t, 0) = 1; resp_size(resp, 0x10); break;
    default: resp_size(resp, 0x10); break;  // Activate*/Set*: annehmen
    }
}

const ServiceDef g_service_defs[] = {
    {"lm", lm_service}, {"apm", apm_service}, {"appletOE", applet_oe}, {"acc:u0", acc_u0}, {"aoc:u", aoc_u},
    {"pctl", pctl_root}, {"pctl:s", pctl_root}, {"pctl:a", pctl_root}, {"pctl:r", pctl_root}, {"ectx:aw", ectx_writer},
    {"set", set_service}, {"set:sys", set_sys}, {"time:u", time_static}, {"time:a", time_static}, {"time:s", time_static},
    {"hid", hid_service},
    {NULL, NULL},
};
