// Synthetic regression cases: no game data, real audio device or guest threads.
#include <assert.h>
#include <stdatomic.h>
#include "../recomp/runtime/services_audio.c"

uint8_t *g_base;
pthread_mutex_t g_klock = PTHREAD_MUTEX_INITIALIZER;
static atomic_uint_fast64_t clock_ns;
static unsigned writes, starts, stops, closes;
static uint8_t last_pcm[4096];
static size_t last_bytes;
static KEvent event;

uint64_t rt_now_ns(void) { return atomic_load(&clock_ns); }
void kernel_signal(KObject *obj) { obj->signaled = true; }
KEvent *kernel_create_event_pair(uint32_t *w, uint32_t *r) {
    static uint32_t next = 100;
    *w = ++next; *r = ++next;
    return &event;
}
void ipc_note(const char *name, uint32_t cmd, int unhandled) { (void)name; (void)cmd; (void)unhandled; }
Service *service_new(const char *name, ServiceHandler handler, void *state) {
    Service *s = calloc(1, sizeof *s);
    s->name = name; s->handler = handler; s->state = state;
    return s;
}
void ipc_return_object(IpcResp *resp, Service *s) { resp->objects[resp->nobjects++] = s; }
AudioOutput *audio_output_open(uint32_t rate, uint32_t channels) {
    (void)rate; (void)channels;
    return (AudioOutput *)&event;
}
void audio_output_start(AudioOutput *out) { (void)out; starts++; }
void audio_output_stop(AudioOutput *out) { (void)out; stops++; }
void audio_output_close(AudioOutput *out) { (void)out; closes++; }
void audio_output_write(AudioOutput *out, const void *pcm, size_t bytes) {
    (void)out;
    assert(bytes <= sizeof last_pcm);
    memcpy(last_pcm, pcm, bytes); last_bytes = bytes; writes++;
}

static IpcResp request(Service *s, uint32_t cmd, uint64_t value) {
    IpcReq req = {.cmd = cmd, .data = (const uint8_t *)&value, .data_size = 8};
    if (cmd == 7) { req.na = 1; req.a[0] = (IpcBuf){0x1000, 0x28}; }
    if (cmd == 8) { req.nb = 1; req.b[0] = (IpcBuf){0x2000, 8}; }
    IpcResp resp = {0};
    s->handler(s, &req, &resp);
    return resp;
}

static void pacing_and_bounds(void) {
    AudOut a = {.rate = 48000, .channels = 2};
    pthread_mutex_init(&a.lk, NULL);
    Service s = {.state = &a, .handler = audout_obj};
    uint64_t *desc = G2H64(0x1000);
    desc[1] = 0x3000; desc[2] = 4104; desc[3] = 4096; desc[4] = 8;
    memset(G2H(0x3000), 0x55, 8);
    memset(G2H(0x3008), 0x33, 4096);
    atomic_store(&clock_ns, 1000000000);
    IpcResp resp = request(&s, 7, 11);
    assert(!resp.result && writes == 1 && last_bytes == 4096 && last_pcm[0] == 0x33);
    // Copying to the host must never release a guest buffer early.
    *G2H64(0x2000) = 999;
    resp = request(&s, 8, 0);
    assert(!*(uint32_t *)resp.data && !*G2H64(0x2000));
    atomic_store(&clock_ns, 1021333332);
    resp = request(&s, 8, 0);
    assert(!*(uint32_t *)resp.data);
    atomic_store(&clock_ns, 1021333333);
    resp = request(&s, 8, 0);
    assert(*(uint32_t *)resp.data == 1 && *G2H64(0x2000) == 11);
    // Duration follows the negotiated mono sample rate rather than fixed stereo/48 kHz.
    a.rate = 24000; a.channels = 1;
    resp = request(&s, 7, 12);
    assert(!resp.result && a.due[0] == 1106666666);
    // Capacity/offset underflow and address wrap must not reach the host.
    desc[4] = desc[2] + 1;
    resp = request(&s, 7, 13);
    assert(resp.result == R_INVALID_ADDRESS && writes == 2);
    desc[4] = 0; desc[1] = GUEST_HI - 4;
    resp = request(&s, 7, 13);
    assert(resp.result == R_INVALID_ADDRESS && writes == 2);
    desc[1] = 0x3000; desc[3] = 3;
    resp = request(&s, 7, 13);
    assert(resp.result == R_INVALID_ADDRESS && writes == 2);
    desc[3] = 2; a.ntags = 64;
    resp = request(&s, 7, 13);
    assert(resp.result == R_OUT_OF_RESOURCE && writes == 2);
    a.ntags = 0; a.last_due = rt_now_ns();
    resp = request(&s, 7, 14);
    assert(!resp.result && a.due[0] == rt_now_ns() + 5000000);
    request(&s, 1, 0); request(&s, 2, 0);
    assert(starts == 1 && stops == 1);
    pthread_mutex_destroy(&a.lk);
}

static void output_lifetime(void) {
    uint32_t params[4] = {48000, 2, 0, 0};
    IpcReq req = {.cmd = 1, .data = (const uint8_t *)params, .data_size = sizeof params};
    // More than eight successive movie outputs must reuse registry slots.
    for (int i = 0; i < 24; i++) {
        IpcResp resp = {0};
        audout_mgr(NULL, &req, &resp);
        assert(!resp.result && resp.nobjects == 1);
        Service *s = resp.objects[0];
        s->on_close(s);
        assert(!s->state);
        free(s);
    }
    assert(closes == 24);
}

int main(void) {
    g_base = calloc(1, 0x10000);
    assert(g_base);
    pacing_and_bounds();
    output_lifetime();
    // The detached timer is terminated with this test process; it no longer holds guest pointers.
    return 0;
}
