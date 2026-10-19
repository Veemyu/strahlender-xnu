// Stumme Audiodienste der BDSP-Laufzeit (derzeit kein Ton; Ton wird erforscht): audout:u (IAudioOut), audren:u (IAudioRenderer, IAudioDevice),
// hwopus und audin:u. Die Dienste melden dem SDK ein funktionierendes Gerät, geben jeden angehängten Puffer sofort zurück und
// liefern leere Rendering-Antworten. Eigener Code.
#include "bdsp.h"

// Jeder angehängte Puffer „spielt“ in Echtzeit (Dauer aus der Datengröße) und wird erst danach zurückgegeben, wie bei echter Hardware. Ohne diese
// Pacing sah die Wwise-Audioschleife immer freie Puffer, rechnete ohne Ende Bilder und hielt dabei die globale Wwise-Sperre: der Hauptthread hing
// (QA: Stillstand beim Betreten des Pokécenters, AkGameObj::SetPosition). Kein Ton: es wird nichts ausgegeben.
typedef struct { KEvent *ev; uint32_t ev_handle; uint64_t tags[64], due[64], last_due, signaled_due; int ntags, started; uint64_t appended, released, empty_polls; pthread_mutex_t lk; } AudOut;

static void signal_ev(KEvent *e) {
    pthread_mutex_lock(&g_klock);
    kernel_signal(e);
    pthread_mutex_unlock(&g_klock);
}

static AudOut *g_audouts[8];
static int g_naudouts;
static pthread_mutex_t g_audlock = PTHREAD_MUTEX_INITIALIZER;
// Zeitgeber: meldet das Pufferereignis, sobald der vorderste Puffer fertig gespielt ist
static void *audout_timer(void *arg) {
    (void)arg;
    for (;;) {
        nanosleep(&(struct timespec){0, 4000000}, NULL);
        uint64_t now = rt_now_ns();
        pthread_mutex_lock(&g_audlock);
        int n = g_naudouts;
        pthread_mutex_unlock(&g_audlock);
        for (int i = 0; i < n; i++) {
            AudOut *a = g_audouts[i];
            int fire = 0;
            pthread_mutex_lock(&a->lk);
            if (a->ntags && a->due[0] <= now && a->due[0] != a->signaled_due) { a->signaled_due = a->due[0]; fire = 1; }
            pthread_mutex_unlock(&a->lk);
            if (fire) signal_ev(a->ev);
        }
    }
    return NULL;
}
static void audout_register(AudOut *a) {
    pthread_mutex_lock(&g_audlock);
    if (g_naudouts < 8) g_audouts[g_naudouts++] = a;
    if (g_naudouts == 1) {
        pthread_t t;
        pthread_create(&t, NULL, audout_timer, NULL);
        pthread_detach(t);
    }
    pthread_mutex_unlock(&g_audlock);
}

// ---- IAudioOut
static void audout_obj(Service *s, IpcReq *req, IpcResp *resp) {
    AudOut *a = s->state;
    ipc_note("IAudioOut", req->cmd, 0);
    switch (req->cmd) {
    case 0: OUT(uint32_t, 0) = a->started ? 0 : 1; resp_size(resp, 4); break;  // GetAudioOutState (0 = Started, 1 = Stopped)
    case 1: a->started = 1; break;                                             // Start
    case 2: a->started = 0; break;                                             // Stop
    case 3: case 7: {                                                          // AppendAudioOutBuffer(tag) mit AudioOutBuffer im A-Puffer
        IpcBuf *b = in_buf(req, 0);   // AudioOutBuffer {next, buffer, capacity, dataSize, offset}: Spieldauer aus dataSize (16 Bit, 2 Kanäle, 48 kHz)
        uint64_t bytes = b && b->size >= 0x20 ? *(G2H64(b->addr) + 3) : 0;
        uint64_t ns = bytes ? bytes / 4 * 1000000000ull / 48000 : 21333333ull;
        if (ns < 5000000ull) ns = 5000000ull;   // mindestens 5 ms: das Gastsystem trägt den Puffer erst nach der Rückkehr der Anfrage in seine Warteschlange ein
        if (ns > 200000000ull) ns = 200000000ull;
        uint64_t now = rt_now_ns();
        pthread_mutex_lock(&a->lk);
        uint64_t start = a->last_due > now ? a->last_due : now;
        a->last_due = start + ns;
        if (a->ntags < 64) { a->tags[a->ntags] = IN(uint64_t, 0); a->due[a->ntags] = a->last_due; a->ntags++; }
        a->appended++;
        pthread_mutex_unlock(&a->lk);
        break;
    }
    case 4: resp->copy_handles[resp->ncopy++] = a->ev_handle; break;           // RegisterBufferEvent
    case 5: case 8: {                                                          // GetReleasedAudioOutBuffer: fertig gespielte Tags (so viele, wie der Puffer fasst)
        IpcBuf *b = out_buf(req, 0);
        int cap = b && b->size ? (int)(b->size / 8) : 0;
        uint64_t now = rt_now_ns();
        pthread_mutex_lock(&a->lk);
        int n = 0;
        while (n < a->ntags && n < cap && a->due[n] <= now) n++;
        if (n) {
            uint64_t *p = G2H64(b->addr);
            for (int i = 0; i < n; i++) p[i] = a->tags[i];
            memmove(a->tags, a->tags + n, (size_t)(a->ntags - n) * 8);
            memmove(a->due, a->due + n, (size_t)(a->ntags - n) * 8);
            a->ntags -= n;
        }
        pthread_mutex_unlock(&a->lk);
        if (n && getenv("BDSP_TRACE_AUDIO")) LOG("[audio] Get: Puffer %llu Byte, n %d, Tag0 %llx\n", (unsigned long long)(b ? b->size : 0), n, (unsigned long long)G2H64(b->addr)[0]);
        if (!n) {
            if (b && b->size >= 8) *G2H64(b->addr) = 0;   // das SDK liest den Tag ohne ihn vorzubelegen: ohne Nullen liefert die Schleife des Spiels den alten Tag endlos zurück
            if ((++a->empty_polls % 4000) == 0) LOG("[audio] %llu leere Abfragen in Folge (angehängt %llu, zurückgegeben %llu, wartend %d)\n",
                                                      (unsigned long long)a->empty_polls, (unsigned long long)a->appended, (unsigned long long)a->released, a->ntags);
            struct timespec ts = {0, 2000000}; nanosleep(&ts, NULL);   // nichts zurückzugeben: Abfrageschleifen des Spiels bremsen
        } else { a->released += (uint64_t)n; a->empty_polls = 0; }
        OUT(uint32_t, 0) = (uint32_t)n;
        resp_size(resp, 4);
        break;
    }
    case 6: OUT(uint32_t, 0) = 0; resp_size(resp, 4); break;                   // ContainsAudioOutBuffer
    case 9: OUT(uint32_t, 0) = (uint32_t)a->ntags; resp_size(resp, 4); break;  // GetAudioOutBufferCount
    case 10: OUT(uint64_t, 0) = a->appended * 1024; resp_size(resp, 8); break; // GetAudioOutPlayedSampleCount
    case 11: OUT(uint32_t, 0) = 0; resp_size(resp, 4); break;                  // FlushAudioOutBuffers
    default: ipc_note("IAudioOut", req->cmd, 1); resp_size(resp, 8);
    }
}

// ---- audout:u (IAudioOutManager)
static void audout_mgr(Service *s, IpcReq *req, IpcResp *resp) {
    (void)s;
    switch (req->cmd) {
    case 0: case 2: {  // ListAudioOuts: ein Gerät „DeviceOut“
        IpcBuf *b = out_buf(req, 0);
        if (b && b->size >= 0x20) { memset(G2H(b->addr), 0, 0x20); strcpy((char *)G2H(b->addr), "DeviceOut"); }
        OUT(uint32_t, 0) = 1;
        resp_size(resp, 4);
        break;
    }
    case 1: case 3: {  // OpenAudioOut(sample_rate, channels, aruid, handle): Ausgabe: Rate, Kanäle, Format (2 = PCM16), Zustand + Objekt + Name
        uint32_t rate = IN(uint32_t, 0);
        uint16_t ch = IN(uint16_t, 4);
        AudOut *a = calloc(1, sizeof *a);
        pthread_mutex_init(&a->lk, NULL);
        uint32_t w;
        a->ev = kernel_create_event_pair(&w, &a->ev_handle);
        audout_register(a);
        OUT(uint32_t, 0) = rate ? rate : 48000;
        OUT(uint32_t, 4) = ch ? ch : 2;
        OUT(uint32_t, 8) = 2;
        OUT(uint32_t, 12) = 1;
        resp_size(resp, 16);
        IpcBuf *b = out_buf(req, 0);
        if (b && b->size >= 0x20) { memset(G2H(b->addr), 0, 0x20); strcpy((char *)G2H(b->addr), "DeviceOut"); }
        ipc_return_object(resp, service_new("IAudioOut", audout_obj, a));
        break;
    }
    default: ipc_note("audout:u", req->cmd, 1); resp_size(resp, 8);
    }
}

// ---- IAudioRenderer: kein Rendering; RequestUpdate liefert einen Kopf ohne Abschnitte
typedef struct { KEvent *ev; uint32_t ev_handle; uint32_t rate, count, mix; } AudRen;
static void audren_obj(Service *s, IpcReq *req, IpcResp *resp) {
    AudRen *a = s->state;
    ipc_note("IAudioRenderer", req->cmd, 0);
    switch (req->cmd) {
    case 0: OUT(uint32_t, 0) = a->rate; resp_size(resp, 4); break;   // GetSampleRate
    case 1: OUT(uint32_t, 0) = a->count; resp_size(resp, 4); break;  // GetSampleCount
    case 2: OUT(uint32_t, 0) = a->mix; resp_size(resp, 4); break;    // GetMixBufferCount
    case 3: OUT(uint32_t, 0) = 0; resp_size(resp, 4); break;         // GetState
    case 4: case 10: {  // RequestUpdate(Eingabe, Ausgabe, Leistung): Kopf mit der Revision der Eingabe, sonst leer
        IpcBuf *in = in_buf(req, 0), *out = out_buf(req, 0);
        if (out && out->size >= 0x40) {
            uint32_t rev = in && in->size >= 4 ? *G2H32(in->addr) : 0;
            memset(G2H(out->addr), 0, 0x40);
            *G2H32(out->addr) = rev;
            *(G2H32(out->addr) + 15) = 0x40;  // Gesamtgröße
        }
        signal_ev(a->ev);
        break;
    }
    case 5: case 6: break;                                                      // Start, Stop
    case 7: resp->copy_handles[resp->ncopy++] = a->ev_handle; break;           // QuerySystemEvent
    case 8: break;                                                              // SetRenderingTimeLimit
    case 9: OUT(uint32_t, 0) = 75; resp_size(resp, 4); break;                   // GetRenderingTimeLimit
    case 11: break;                                                             // ExecuteAudioRendererRendering
    default: ipc_note("IAudioRenderer", req->cmd, 1); resp_size(resp, 8);
    }
}

// ---- IAudioDevice: ein Ausgabegerät „AudioStereoJackOutput“
static void auddev_obj(Service *s, IpcReq *req, IpcResp *resp) {
    (void)s;
    ipc_note("IAudioDevice", req->cmd, 0);
    switch (req->cmd) {
    case 0: case 6: {  // ListAudioDeviceName(Auto): ein Gerät, Name in den B-Puffer
        IpcBuf *b = out_buf(req, 0);
        if (b && b->size >= 0x20) { memset(G2H(b->addr), 0, 0x20); strcpy((char *)G2H(b->addr), "AudioStereoJackOutput"); }
        OUT(int32_t, 0) = 1;
        resp_size(resp, 4);
        break;
    }
    case 3: case 10: {  // GetActiveAudioDeviceName(Auto)
        IpcBuf *b = out_buf(req, 0);
        if (b && b->size >= 0x20) { memset(G2H(b->addr), 0, 0x20); strcpy((char *)G2H(b->addr), "AudioStereoJackOutput"); }
        break;
    }
    case 1: case 7: break;                                                      // SetAudioDeviceOutputVolume(Auto)
    case 2: case 8: OUT(float, 0) = 1.0f; resp_size(resp, 4); break;            // GetAudioDeviceOutputVolume(Auto)
    case 4: case 11: case 12: {                                                 // QueryAudioDeviceSystemEvent / InputEvent / OutputEvent: Ereignis-Handle
        uint32_t w, r;
        kernel_create_event_pair(&w, &r);
        resp->copy_handles[resp->ncopy++] = r;
        break;
    }
    case 5: OUT(uint32_t, 0) = 2; resp_size(resp, 4); break;                    // GetActiveChannelCount
    case 13: OUT(float, 0) = 1.0f; resp_size(resp, 4); break;                   // GetAudioSystemMasterVolumeSetting
    default: ipc_note("IAudioDevice", req->cmd, 1); resp_size(resp, 8);
    }
}

static void audren_mgr(Service *s, IpcReq *req, IpcResp *resp) {
    (void)s;
    switch (req->cmd) {
    case 0: {  // OpenAudioRenderer(AudioRendererParameter, work_buffer_size, aruid, handles)
        AudRen *a = calloc(1, sizeof *a);
        a->rate = IN(uint32_t, 0);
        a->count = IN(uint32_t, 4);
        a->mix = IN(uint32_t, 8);
        uint32_t w;
        a->ev = kernel_create_event_pair(&w, &a->ev_handle);
        signal_ev(a->ev);
        ipc_return_object(resp, service_new("IAudioRenderer", audren_obj, a));
        break;
    }
    case 1: {  // GetWorkBufferSize(AudioRendererParameter): großzügig nach der Zahl der Stimmen
        uint32_t voices = IN(uint32_t, 16), mix = IN(uint32_t, 8);
        OUT(uint64_t, 0) = 0x100000ull + (uint64_t)(voices + 1) * 0x2000 + (uint64_t)(mix + 1) * 0x1000;
        resp_size(resp, 8);
        break;
    }
    case 2: case 4: ipc_return_object(resp, service_new("IAudioDevice", auddev_obj, NULL)); break;  // GetAudioDeviceService(+WithRevisionInfo)
    default: ipc_note("audren:u", req->cmd, 1); resp_size(resp, 8);
    }
}

static void svc_err(Service *s, IpcReq *req, IpcResp *resp) {
    ipc_note(s->name, req->cmd, 0);
    resp->result = MAKE_RESULT(204, 1);
}

// ---- hwopus (IHardwareOpusDecoderManager): Arbeitspuffergrößen; der Decoder liefert keine Samples
static void opus_decoder(Service *s, IpcReq *req, IpcResp *resp) {
    (void)s;
    ipc_note("IHardwareOpusDecoder", req->cmd, 0);
    resp_size(resp, 0x10);   // verbraucht 0 Bytes, 0 Samples
}
static void opus_mgr(Service *s, IpcReq *req, IpcResp *resp) {
    (void)s;
    switch (req->cmd) {
    case 0: case 2: case 4: case 5: ipc_return_object(resp, service_new("IHardwareOpusDecoder", opus_decoder, NULL)); break;
    case 1: case 3: case 6: case 7: OUT(uint32_t, 0) = 0x8000; resp_size(resp, 4); break;   // GetWorkBufferSize(…ForMultiStream/Ex)
    default: ipc_note("hwopus", req->cmd, 1); resp_size(resp, 8);
    }
}

const ServiceDef g_service_defs_audio[] = {
    {"audout:u", audout_mgr}, {"audren:u", audren_mgr}, {"hwopus", opus_mgr}, {"audin:u", svc_err}, {NULL, NULL},
};
