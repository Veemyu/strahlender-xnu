// Audio services of the BDSP runtime: audout:u plays PCM16 on the host, audren:u, hwopus and audin:u stay stubs.
// Buffers are released after their play time, independent of the host device. Own code.
#include "bdsp.h"
#include "audio_output.h"

// Every appended buffer "plays" in real time (duration from the data size) and is only returned afterwards, as on real hardware. Without this
// pacing the Wwise audio loop always saw free buffers, rendered frames endlessly and held the global Wwise lock meanwhile: the main thread hung
// (QA: stall when entering the Pokémon Center, AkGameObj::SetPosition).
typedef struct { KEvent *ev; uint32_t ev_handle; uint64_t tags[64], due[64], last_due, signaled_due; int ntags, started; uint64_t appended, released, empty_polls; pthread_mutex_t lk; uint32_t rate, channels; uint64_t probe_buffers, probe_samples, probe_nonzero; uint32_t probe_peak; AudioOutput *output; } AudOut;

static int audout_pcm(IpcBuf *b, uint64_t desc[5]) {
    if (!b || b->size < 0x28 || b->addr < GUEST_LO || b->addr > GUEST_HI - 0x28) return 0;
    memcpy(desc, G2H(b->addr), 0x28);
    uint64_t ptr = desc[1], capacity = desc[2], bytes = desc[3], offset = desc[4];
    return ptr >= GUEST_LO && ptr < GUEST_HI && offset <= capacity && bytes <= capacity - offset &&
           offset <= GUEST_HI - ptr && bytes <= GUEST_HI - ptr - offset;
}

// Optional measurement of the negotiated PCM16 stream; no game samples are logged or saved.
// Keep this independent of buffer completion and event timing.
static void audout_probe(AudOut *a, IpcBuf *b) {
    if (!getenv("BDSP_AUDIO_PROBE")) return;
    uint64_t desc[5];
    if (!audout_pcm(b, desc) || (desc[3] & 1)) return;
    uint64_t ptr = desc[1], bytes = desc[3], offset = desc[4];
    const uint8_t *pcm = G2H8(ptr + offset);
    uint64_t nonzero = 0;
    uint32_t peak = 0;
    for (uint64_t i = 0; i < bytes; i += 2) {
        int16_t sample;
        memcpy(&sample, pcm + i, sizeof sample);
        uint32_t magnitude = sample < 0 ? -(int32_t)sample : sample;
        nonzero += sample != 0;
        if (magnitude > peak) peak = magnitude;
    }
    a->probe_buffers++;
    a->probe_samples += bytes / 2;
    a->probe_nonzero += nonzero;
    if (peak > a->probe_peak) a->probe_peak = peak;
    if (a->probe_buffers <= 8 || !(a->probe_buffers % 512))
        LOG("[audio-probe] stream=%u rate=%u channels=%u bytes=%llu offset=%llu buffers=%llu samples=%llu nonzero=%llu peak=%u\n",
            a->ev_handle, a->rate, a->channels, (unsigned long long)bytes, (unsigned long long)offset,
            (unsigned long long)a->probe_buffers, (unsigned long long)a->probe_samples,
            (unsigned long long)a->probe_nonzero, a->probe_peak);
}

static void signal_ev(KEvent *e) {
    pthread_mutex_lock(&g_klock);
    kernel_signal(e);
    pthread_mutex_unlock(&g_klock);
}

static AudOut *g_audouts[8];
static int g_audio_timer_started;
static pthread_mutex_t g_audlock = PTHREAD_MUTEX_INITIALIZER;
// Timer: signals the buffer event as soon as the foremost buffer has finished playing
static void *audout_timer(void *arg) {
    (void)arg;
    for (;;) {
        nanosleep(&(struct timespec){0, 4000000}, NULL);
        uint64_t now = rt_now_ns();
        KEvent *events[8];
        int nevents = 0;
        pthread_mutex_lock(&g_audlock);
        for (int i = 0; i < 8; i++) {
            AudOut *a = g_audouts[i];
            if (!a) continue;
            int fire = 0;
            pthread_mutex_lock(&a->lk);
            if (a->ntags && a->due[0] <= now && a->due[0] != a->signaled_due) { a->signaled_due = a->due[0]; fire = 1; }
            pthread_mutex_unlock(&a->lk);
            if (fire) events[nevents++] = a->ev;
        }
        pthread_mutex_unlock(&g_audlock);
        for (int i = 0; i < nevents; i++) signal_ev(events[i]);
    }
    return NULL;
}
static int audout_register(AudOut *a) {
    pthread_mutex_lock(&g_audlock);
    int slot;
    for (slot = 0; slot < 8 && g_audouts[slot]; slot++) {}
    if (slot == 8) { pthread_mutex_unlock(&g_audlock); return 0; }
    if (!g_audio_timer_started) {
        pthread_t t;
        if (pthread_create(&t, NULL, audout_timer, NULL)) { pthread_mutex_unlock(&g_audlock); return 0; }
        pthread_detach(t);
        g_audio_timer_started = 1;
    }
    g_audouts[slot] = a;
    pthread_mutex_unlock(&g_audlock);
    return 1;
}

static void audout_close(Service *s) {
    AudOut *a = s->state;
    if (!a) return;
    pthread_mutex_lock(&g_audlock);
    for (int i = 0; i < 8; i++) if (g_audouts[i] == a) g_audouts[i] = NULL;
    pthread_mutex_unlock(&g_audlock);
    audio_output_close(a->output);
    pthread_mutex_destroy(&a->lk);
    free(a);
    s->state = NULL;
}

// ---- IAudioOut
static void audout_obj(Service *s, IpcReq *req, IpcResp *resp) {
    AudOut *a = s->state;
    ipc_note("IAudioOut", req->cmd, 0);
    switch (req->cmd) {
    case 0:
        pthread_mutex_lock(&a->lk);
        OUT(uint32_t, 0) = a->started ? 0 : 1;
        pthread_mutex_unlock(&a->lk);
        resp_size(resp, 4); break;
    case 1: case 2:
        pthread_mutex_lock(&a->lk);
        a->started = req->cmd == 1;
        if (a->started) audio_output_start(a->output);
        else audio_output_stop(a->output);
        pthread_mutex_unlock(&a->lk);
        break;
    case 3: case 7: {                                                          // AppendAudioOutBuffer(tag) with AudioOutBuffer in the A buffer
        IpcBuf *b = in_buf(req, 0);   // AudioOutBuffer {next, buffer, capacity, dataSize, offset}: play time from dataSize (16 bit, 2 channels, 48 kHz)
        uint64_t desc[5];
        if (!audout_pcm(b, desc) || desc[3] % (2 * a->channels)) { resp->result = R_INVALID_ADDRESS; break; }
        uint64_t bytes = desc[3];
        uint64_t frames = bytes / (2 * a->channels);
        uint64_t ns = frames ? frames * 1000000000ull / a->rate : 21333333ull;
        if (ns < 5000000ull) ns = 5000000ull;   // at least 5 ms: the guest system enters the buffer into its queue only after the request returns
        if (ns > 200000000ull) ns = 200000000ull;
        uint64_t now = rt_now_ns();
        pthread_mutex_lock(&a->lk);
        if (a->ntags == 64) { pthread_mutex_unlock(&a->lk); resp->result = R_OUT_OF_RESOURCE; break; }
        audout_probe(a, b);
        audio_output_write(a->output, G2H(desc[1] + desc[4]), (size_t)bytes);
        uint64_t start = a->last_due > now ? a->last_due : now;
        a->last_due = start + ns;
        if (a->ntags < 64) { a->tags[a->ntags] = IN(uint64_t, 0); a->due[a->ntags] = a->last_due; a->ntags++; }
        a->appended++;
        pthread_mutex_unlock(&a->lk);
        break;
    }
    case 4: resp->copy_handles[resp->ncopy++] = a->ev_handle; break;           // RegisterBufferEvent
    case 5: case 8: {                                                          // GetReleasedAudioOutBuffer: tags that have finished playing (as many as the buffer holds)
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
        if (n && getenv("BDSP_TRACE_AUDIO")) LOG("[audio] Get: buffer %llu bytes, n %d, tag0 %llx\n", (unsigned long long)(b ? b->size : 0), n, (unsigned long long)G2H64(b->addr)[0]);
        if (!n) {
            if (b && b->size >= 8) *G2H64(b->addr) = 0;   // the SDK reads the tag without pre-filling it: without zeros the game's loop returns the old tag endlessly
            if ((++a->empty_polls % 4000) == 0) LOG("[audio] %llu empty polls in a row (appended %llu, returned %llu, waiting %d)\n",
                                                      (unsigned long long)a->empty_polls, (unsigned long long)a->appended, (unsigned long long)a->released, a->ntags);
            struct timespec ts = {0, 2000000}; nanosleep(&ts, NULL);   // nothing to return: slow down the game's polling loops
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
    case 0: case 2: {  // ListAudioOuts: one device "DeviceOut"
        IpcBuf *b = out_buf(req, 0);
        if (b && b->size >= 0x20) { memset(G2H(b->addr), 0, 0x20); strcpy((char *)G2H(b->addr), "DeviceOut"); }
        OUT(uint32_t, 0) = 1;
        resp_size(resp, 4);
        break;
    }
    case 1: case 3: {  // OpenAudioOut(sample_rate, channels, aruid, handle): output: rate, channels, format (2 = PCM16), state + object + name
        uint32_t rate = IN(uint32_t, 0);
        uint16_t ch = IN(uint16_t, 4);
        AudOut *a = calloc(1, sizeof *a);
        a->rate = rate ? rate : 48000;
        a->channels = ch ? ch : 2;
        if (a->rate < 8000 || a->rate > 192000 || a->channels > 8) {
            free(a); resp->result = R_INVALID_ENUM; break;
        }
        pthread_mutex_init(&a->lk, NULL);
        uint32_t w;
        a->ev = kernel_create_event_pair(&w, &a->ev_handle);
        if (!audout_register(a)) { pthread_mutex_destroy(&a->lk); free(a); resp->result = R_OUT_OF_RESOURCE; break; }
        a->output = audio_output_open(a->rate, a->channels);
        if (getenv("BDSP_AUDIO_PROBE")) LOG("[audio-probe] open stream=%u rate=%u channels=%u format=PCM16\n", a->ev_handle, a->rate, a->channels);
        OUT(uint32_t, 0) = rate ? rate : 48000;
        OUT(uint32_t, 4) = ch ? ch : 2;
        OUT(uint32_t, 8) = 2;
        OUT(uint32_t, 12) = 1;
        resp_size(resp, 16);
        IpcBuf *b = out_buf(req, 0);
        if (b && b->size >= 0x20) { memset(G2H(b->addr), 0, 0x20); strcpy((char *)G2H(b->addr), "DeviceOut"); }
        Service *obj = service_new("IAudioOut", audout_obj, a);
        obj->on_close = audout_close;
        ipc_return_object(resp, obj);
        break;
    }
    default: ipc_note("audout:u", req->cmd, 1); resp_size(resp, 8);
    }
}

// ---- IAudioRenderer: no rendering; RequestUpdate returns a header without sections
typedef struct { KEvent *ev; uint32_t ev_handle; uint32_t rate, count, mix; } AudRen;
static void audren_obj(Service *s, IpcReq *req, IpcResp *resp) {
    AudRen *a = s->state;
    ipc_note("IAudioRenderer", req->cmd, 0);
    switch (req->cmd) {
    case 0: OUT(uint32_t, 0) = a->rate; resp_size(resp, 4); break;   // GetSampleRate
    case 1: OUT(uint32_t, 0) = a->count; resp_size(resp, 4); break;  // GetSampleCount
    case 2: OUT(uint32_t, 0) = a->mix; resp_size(resp, 4); break;    // GetMixBufferCount
    case 3: OUT(uint32_t, 0) = 0; resp_size(resp, 4); break;         // GetState
    case 4: case 10: {  // RequestUpdate(input, output, performance): header with the revision of the input, otherwise empty
        IpcBuf *in = in_buf(req, 0), *out = out_buf(req, 0);
        if (out && out->size >= 0x40) {
            uint32_t rev = in && in->size >= 4 ? *G2H32(in->addr) : 0;
            memset(G2H(out->addr), 0, 0x40);
            *G2H32(out->addr) = rev;
            *(G2H32(out->addr) + 15) = 0x40;  // total size
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

// ---- IAudioDevice: one output device "AudioStereoJackOutput"
static void auddev_obj(Service *s, IpcReq *req, IpcResp *resp) {
    (void)s;
    ipc_note("IAudioDevice", req->cmd, 0);
    switch (req->cmd) {
    case 0: case 6: {  // ListAudioDeviceName(Auto): one device, name in the B buffer
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
    case 4: case 11: case 12: {                                                 // QueryAudioDeviceSystemEvent / InputEvent / OutputEvent: event handle
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
    case 1: {  // GetWorkBufferSize(AudioRendererParameter): generous, by the number of voices
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

// ---- hwopus (IHardwareOpusDecoderManager): work buffer sizes; the decoder returns no samples
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
