// movie:: (nnMedia des SDK) mit FFmpeg: Android-artige Extractor-/Decoder-Schnittstelle für den Unity-SwitchVideoPlayer.
// Entwurf und Teile nach scripts/recomp/upstream/runtime/hle/movie.c (MIT, siehe NOTICE.md), für BDSP angepasst:
//  - Extractor-Aufrufe, die BDSP direkt (nicht über die Vtable) importiert: GetTrackCount, SetDataSource(const char*), GetTrackConfiguration;
//  - nur die Videospur wird angeboten (kein Ton), Ausgabe NV12 im Puffer (Unity lädt Y und UV selbst);
//  - Pfade „rom:/…“ liegen im RomFS-Ordner der Laufzeit (g_romfs_dir).
// Die Objekte gehören dem Spiel (Vtable bei +0), Host-Zustand bei +8.
// Extractor-Slots: 4 GetTrackCount(int*), 5 GetTrackConfiguration(int, MediaData*), 6 SelectTrack(int), 8 SeekTo(us),
//   9 GetSampleTrackIndex(size_t*), 10 Read(Buffer*), 11 Advance(), 12 GetSampleTime(int64*), 14 GetCachedDuration, 15 SetDataSource(DataSource*, path).
// Decoder-Slots: 2 Configure(MediaData*), 3 RegisterClientEvents(EventType*[4]), 4 GetOutputFormat(MediaData*), 5 Start, 6 Stop,
//   9 AcquireInputBufferIndex(int*, int*), 10 GetInputBuffer(int, Buffer*), 11 SendInputBufferForDecode(int, off, size, int64 time, flags),
//   12 AcquireOutputBufferIndex(int*, int64*, uint32*, int*), 13 GetOutputBuffer(int, Buffer*), 15 ReleaseOutputBufferIndex(int),
//   18 GetOutputBufferFormat(int, MediaData*).
#include <libavcodec/avcodec.h>
#include <libavformat/avformat.h>
#include <pthread.h>
#include <stdlib.h>
#include <string.h>

#include "hle.h"

extern const char *g_romfs_dir;
uint64_t loader_find_symbol(const char *name);
#define guest_sym loader_find_symbol

#define MOVIE_EOS 4u

// ------------------------------------------------------------------ MediaData (8-Byte-Handle)
typedef struct { char *key; char *sval; int64_t ival; bool is_str; } MdEntry;
typedef struct { MdEntry e[32]; int n; void *codecpar; } MediaData;

static MediaData *md(uint64_t guest) {
    MediaData **p = (MediaData **)(uintptr_t)guest;
    if (!*p) *p = calloc(1, sizeof(MediaData));
    return *p;
}
static void md_clear(MediaData *m) {
    for (int i = 0; i < m->n; i++) { free(m->e[i].key); free(m->e[i].sval); }
    m->n = 0;
    m->codecpar = NULL;
}
static MdEntry *md_slot(MediaData *m, const char *k) {
    for (int i = 0; i < m->n; i++) if (!strcmp(m->e[i].key, k)) return &m->e[i];
    if (m->n == 32) return NULL;
    MdEntry *e = &m->e[m->n++];
    memset(e, 0, sizeof *e);
    e->key = strdup(k);
    return e;
}
static void md_set_int(MediaData *m, const char *k, int64_t v) { MdEntry *e = md_slot(m, k); if (e) { e->ival = v; e->is_str = false; } }
static void md_set_str(MediaData *m, const char *k, const char *v) {
    MdEntry *e = md_slot(m, k);
    if (e) { free(e->sval); e->sval = strdup(v); e->is_str = true; }
}
static MdEntry *md_find(MediaData *m, const char *k, bool str) {
    for (int i = 0; i < m->n; i++) if (m->e[i].is_str == str && !strcmp(m->e[i].key, k)) return &m->e[i];
    return NULL;
}

HLE_FUNC("_ZN5movie9MediaDataC1Ev", md_ctor) { *(uint64_t *)(uintptr_t)c->x[0] = (uint64_t)(uintptr_t)calloc(1, sizeof(MediaData)); }
HLE_FUNC("_ZN5movie9MediaDataD1Ev", md_dtor) {
    MediaData *m = *(MediaData **)(uintptr_t)c->x[0];
    if (m) { md_clear(m); free(m); }
    *(uint64_t *)(uintptr_t)c->x[0] = 0;
}
HLE_FUNC("_ZN5movie9MediaData5ClearEv", md_clear_hle) { md_clear(md(c->x[0])); }
HLE_FUNC("_ZNK5movie9MediaData9FindInt32EPKcPi", md_find_int32) {
    MdEntry *e = md_find(md(c->x[0]), (const char *)(uintptr_t)c->x[1], false);
    if (e) *(int32_t *)(uintptr_t)c->x[2] = (int32_t)e->ival;
    c->x[0] = e != NULL;
}
HLE_FUNC("_ZNK5movie9MediaData9FindInt64EPKcPl", md_find_int64) {
    MdEntry *e = md_find(md(c->x[0]), (const char *)(uintptr_t)c->x[1], false);
    if (e) *(int64_t *)(uintptr_t)c->x[2] = e->ival;
    c->x[0] = e != NULL;
}
HLE_FUNC("_ZNK5movie9MediaData10FindStringEPKcPS2_", md_find_string) {
    MdEntry *e = md_find(md(c->x[0]), (const char *)(uintptr_t)c->x[1], true);
    if (e) *(uint64_t *)(uintptr_t)c->x[2] = (uint64_t)(uintptr_t)e->sval;
    c->x[0] = e != NULL;
}
// FindRect(key, left*, top*, right*, bottom*): das Zuschneiderechteck ist das ganze Bild
HLE_FUNC("_ZNK5movie9MediaData8FindRectEPKcPiS3_S3_S3_", md_find_rect) {
    MediaData *m = md(c->x[0]);
    MdEntry *w = md_find(m, "width", false), *h = md_find(m, "height", false);
    if (!w || !h) { c->x[0] = 0; return; }
    *(int32_t *)(uintptr_t)c->x[2] = 0;
    *(int32_t *)(uintptr_t)c->x[3] = 0;
    *(int32_t *)(uintptr_t)c->x[4] = (int32_t)w->ival - 1;
    *(int32_t *)(uintptr_t)c->x[5] = (int32_t)h->ival - 1;
    c->x[0] = 1;
}

// ------------------------------------------------------------------ Buffer (undurchsichtig, <= 0x40 Byte)
typedef struct {
    uint64_t base, capacity;
    int32_t offset, size;
    int64_t i64;
    uint32_t u32;
    int32_t i32;
} MBuffer;
_Static_assert(sizeof(MBuffer) <= 0x40, "movie::Buffer size");
#define BUF(x) ((MBuffer *)(uintptr_t)(x))

HLE_FUNC("_ZN5movie6BufferC1Ev", buf_ctor) { memset(BUF(c->x[0]), 0, sizeof(MBuffer)); }
HLE_FUNC("_ZN5movie6BufferD1Ev", buf_dtor) { (void)c; }
HLE_FUNC("_ZNK5movie6Buffer4DataEv", buf_data) { c->x[0] = BUF(c->x[0])->base; }
HLE_FUNC("_ZNK5movie6Buffer4SizeEv", buf_size) { c->x[0] = (uint32_t)BUF(c->x[0])->size; }
HLE_FUNC("_ZNK5movie6Buffer6OffsetEv", buf_offset) { c->x[0] = (uint32_t)BUF(c->x[0])->offset; }
HLE_FUNC("_ZN5movie6Buffer8SetRangeEii", buf_set_range) { BUF(c->x[0])->offset = (int32_t)c->x[1]; BUF(c->x[0])->size = (int32_t)c->x[2]; }
HLE_FUNC("_ZN5movie6Buffer18SetDataAndCapacityEPvm", buf_set_data) { BUF(c->x[0])->base = c->x[1]; BUF(c->x[0])->capacity = c->x[2]; }

HLE_FUNC("_ZN5movie12SetAllocatorEPFPvmmS0_EPFvS0_S0_EPFS0_S0_mS0_ES0_", movie_set_allocator) { (void)c; }
HLE_FUNC("_ZN5movie11SetCoreMaskEm", movie_set_core_mask) { (void)c; }
HLE_FUNC("_ZN5movie17GetThreadPriorityEv", movie_get_thread_priority) { c->x[0] = 16; }

// ------------------------------------------------------------------ Hilfen
static uint64_t make_vtable(HostFn *fns, int n, const char *prefix) {
    uint64_t *t = hle_alloc(64 * 8);
    char name[96];
    for (int i = 0; i < 64; i++) {
        snprintf(name, sizeof name, "<%s slot %d>", prefix, i);
        t[i] = hle_register(name, i < n ? fns[i] : NULL);
    }
    return (uint64_t)(uintptr_t)t;
}

// Der Gast liest Spuren aus verschiedenen Threads; der FFmpeg-Demuxer ist nicht threadsicher.
static pthread_mutex_t ex_lock = PTHREAD_MUTEX_INITIALIZER;

static void *self_state(Cpu *c) { return (void *)(uintptr_t)((uint64_t *)(uintptr_t)c->x[0])[1]; }

static void signal_guest_event(Cpu *c, uint64_t event) {
    if (!event) return;
    uint64_t saved[8];
    memcpy(saved, c->x, sizeof saved);
    c->x[0] = event;
    guest_call(c, guest_sym("_ZN2nn2os11SignalEventEPNS0_9EventTypeE"));
    memcpy(c->x, saved, sizeof saved);
}

static void ok(Cpu *c) { c->x[0] = 0; }

// ------------------------------------------------------------------ Extractor
typedef struct {
    AVFormatContext *fmt;
    int map[16], ntracks;  // angebotene Spur -> Strom (nur Video)
    uint64_t selected;     // Bitmaske der Ströme
    AVPacket *pkt;
    bool have_pkt, eof;
} Extractor;

static void ex_fill(Extractor *e) {
    while (!e->have_pkt && !e->eof) {
        if (av_read_frame(e->fmt, e->pkt) < 0) { e->eof = true; break; }
        if (e->selected & (1ull << e->pkt->stream_index)) e->have_pkt = true;
        else av_packet_unref(e->pkt);
    }
}

static void ex_open(Extractor *e, const char *path, Cpu *c) {
    const char *rel = path && strstr(path, ":/") ? strstr(path, ":/") + 2 : path;
    char host[1024];
    snprintf(host, sizeof host, "%s/%s", g_romfs_dir, rel ? rel : "");
    LOG("[movie] öffnen %s -> %s\n", path ? path : "(null)", host);
    if (avformat_open_input(&e->fmt, host, NULL, NULL) < 0 || avformat_find_stream_info(e->fmt, NULL) < 0) {
        LOG("[movie] Datei nicht lesbar: %s\n", host);
        c->x[0] = 1;
        return;
    }
    e->pkt = av_packet_alloc();
    e->ntracks = 0;
    for (unsigned i = 0; i < e->fmt->nb_streams && e->ntracks < 16; i++)
        if (e->fmt->streams[i]->codecpar->codec_type == AVMEDIA_TYPE_VIDEO) e->map[e->ntracks++] = (int)i;
    c->x[0] = 0;
}

static void ex_set_data_source_direct(Cpu *c) { ex_open(self_state(c), (const char *)(uintptr_t)c->x[1], c); }
static void ex_set_data_source_slot(Cpu *c) { ex_open(self_state(c), (const char *)(uintptr_t)c->x[2], c); }

static void ex_get_track_count(Cpu *c) {
    Extractor *e = self_state(c);
    *(int32_t *)(uintptr_t)c->x[1] = e->fmt ? e->ntracks : 0;
    c->x[0] = 0;
}

static void ex_get_track_config(Cpu *c) {
    Extractor *e = self_state(c);
    int i = (int)c->x[1];
    MediaData *m = md(c->x[2]);
    md_clear(m);
    if (!e->fmt || i >= e->ntracks) { c->x[0] = 1; return; }
    AVStream *s = e->fmt->streams[e->map[i]];
    AVCodecParameters *p = s->codecpar;
    m->codecpar = p;
    md_set_str(m, "mime", p->codec_id == AV_CODEC_ID_VP9 ? "video/x-vnd.on2.vp9" : p->codec_id == AV_CODEC_ID_VP8 ? "video/x-vnd.on2.vp8" : "video/avc");
    md_set_int(m, "width", p->width);
    md_set_int(m, "height", p->height);
    int fps = s->avg_frame_rate.den ? s->avg_frame_rate.num / s->avg_frame_rate.den : 30;
    md_set_int(m, "frame-rate", fps ? fps : 30);
    if (e->fmt->duration > 0) md_set_int(m, "durationUs", e->fmt->duration);
    LOG("[movie] Spur %d: %s %dx%d %d Bilder/s\n", i, avcodec_get_name(p->codec_id), p->width, p->height, fps);
    c->x[0] = 0;
}

static void ex_select_track(Cpu *c) {
    Extractor *e = self_state(c);
    int i = (int)c->x[1];
    if (i >= 0 && i < e->ntracks) e->selected |= 1ull << e->map[i];
    c->x[0] = 0;
}

static void ex_get_sample_track(Cpu *c) {
    Extractor *e = self_state(c);
    ex_fill(e);
    if (!e->have_pkt) { c->x[0] = 1; return; }
    uint64_t t = 0;
    for (int i = 0; i < e->ntracks; i++) if (e->map[i] == e->pkt->stream_index) t = (uint64_t)i;
    *(uint64_t *)(uintptr_t)c->x[1] = t;
    c->x[0] = 0;
}

static void ex_read(Cpu *c) {
    Extractor *e = self_state(c);
    MBuffer *b = BUF(c->x[1]);
    ex_fill(e);
    if (!e->have_pkt) { c->x[0] = 1; return; }
    uint32_t n = (uint32_t)e->pkt->size;
    if (n > b->capacity) { LOG("[movie] Paket %u > Puffer %llu\n", n, (unsigned long long)b->capacity); n = (uint32_t)b->capacity; }
    memcpy((void *)(uintptr_t)b->base, e->pkt->data, n);
    b->offset = 0;
    b->size = (int32_t)n;
    c->x[0] = 0;
}

static void ex_advance(Cpu *c) {
    Extractor *e = self_state(c);
    if (e->have_pkt) { av_packet_unref(e->pkt); e->have_pkt = false; }
    c->x[0] = 0;
}

static void ex_get_sample_time(Cpu *c) {
    Extractor *e = self_state(c);
    ex_fill(e);
    if (!e->have_pkt) { c->x[0] = 1; return; }
    AVStream *s = e->fmt->streams[e->pkt->stream_index];
    int64_t ts = e->pkt->pts != AV_NOPTS_VALUE ? e->pkt->pts : e->pkt->dts;
    *(int64_t *)(uintptr_t)c->x[1] = av_rescale_q(ts, s->time_base, (AVRational){1, 1000000});
    c->x[0] = 0;
}

static void ex_seek(Cpu *c) {
    Extractor *e = self_state(c);
    if (!e->fmt) { c->x[0] = 1; return; }
    if (e->have_pkt) { av_packet_unref(e->pkt); e->have_pkt = false; }
    e->eof = false;
    av_seek_frame(e->fmt, -1, (int64_t)c->x[1], AVSEEK_FLAG_BACKWARD);
    c->x[0] = 0;
}

static void ex_cached_duration(Cpu *c) {  // lokale Dateien sind vollständig im Zwischenspeicher
    Extractor *e = self_state(c);
    int64_t dur = e->fmt && e->fmt->duration > 0 ? e->fmt->duration : INT64_MAX / 4;
    if (c->x[1]) *(int64_t *)(uintptr_t)c->x[1] = 1;
    if (c->x[2]) *(int64_t *)(uintptr_t)c->x[2] = dur;
    c->x[0] = 0;
}

static void ex_dtor(Cpu *c) {
    Extractor *e = self_state(c);
    if (e && e->fmt) avformat_close_input(&e->fmt);
    c->x[0] = 0;
}

static void movie_log_slot(Cpu *c) {
    static int n;
    if (n++ < 20) LOG("[movie] nicht umgesetzter virtueller Aufruf (lr=%llx)\n", (unsigned long long)c->x[30]);
    c->x[0] = 0;
}

#define EX_LOCKED(fn) \
    static void fn##_l(Cpu *c) { pthread_mutex_lock(&ex_lock); fn(c); pthread_mutex_unlock(&ex_lock); }
EX_LOCKED(ex_dtor)
EX_LOCKED(ex_get_track_count)
EX_LOCKED(ex_get_track_config)
EX_LOCKED(ex_select_track)
EX_LOCKED(ex_seek)
EX_LOCKED(ex_get_sample_track)
EX_LOCKED(ex_read)
EX_LOCKED(ex_advance)
EX_LOCKED(ex_get_sample_time)
EX_LOCKED(ex_cached_duration)
EX_LOCKED(ex_set_data_source_slot)
EX_LOCKED(ex_set_data_source_direct)

static uint64_t g_ex_vt, g_dec_vt;
HLE_FUNC("_ZN5movie9ExtractorC1ENS_13ContainerTypeE", movie_extractor_ctor) {
    uint64_t vt = g_ex_vt;
    if (!vt) {
        HostFn f[16] = {ex_dtor_l, ex_dtor_l, ex_set_data_source_direct_l, movie_log_slot, ex_get_track_count_l, ex_get_track_config_l, ex_select_track_l,
                        movie_log_slot, ex_seek_l, ex_get_sample_track_l, ex_read_l, ex_advance_l, ex_get_sample_time_l, movie_log_slot,
                        ex_cached_duration_l, ex_set_data_source_slot_l};
        vt = g_ex_vt = make_vtable(f, 16, "Extractor");
    }
    uint64_t *self = (uint64_t *)(uintptr_t)c->x[0];
    self[0] = vt;
    self[1] = (uint64_t)(uintptr_t)calloc(1, sizeof(Extractor));
}
HLE_FUNC("_ZN5movie9ExtractorD1Ev", movie_extractor_dtor) { ex_dtor_l(c); }
HLE_FUNC("_ZN5movie9Extractor13GetTrackCountEPi", movie_ex_track_count) { ex_get_track_count_l(c); }
HLE_FUNC("_ZN5movie9Extractor21GetTrackConfigurationEiPNS_9MediaDataE", movie_ex_track_config) { ex_get_track_config_l(c); }
HLE_FUNC("_ZN5movie9Extractor13SetDataSourceEPKc", movie_ex_set_source) { ex_set_data_source_direct_l(c); }

// ------------------------------------------------------------------ Decoder (nur Video, NV12)
#define NIN 4
#define NOUT 6
#define NPENDING 16

typedef struct { int idx; int64_t time; uint32_t flags; } OutReady;

typedef struct {
    AVCodecContext *ctx;
    AVFrame *frame;
    AVPacket *pkt;
    uint64_t events[4];  // Eingabe frei, Ausgabe bereit, Format geändert, Fehler
    uint8_t *in_mem[NIN];
    uint32_t in_cap;
    bool in_busy[NIN];
    uint8_t *out_mem[NOUT];
    uint32_t out_cap, out_size[NOUT];
    bool out_busy[NOUT];
    OutReady ready[NOUT];
    int nready;
    int width, height, stride;
    AVFrame *pending[NPENDING];
    int64_t pending_time[NPENDING];
    int npending;
    bool eos_pending;
    int64_t eos_time;
    bool stopped;
    pthread_mutex_t lock;
} Decoder;

static void dec_signal(Cpu *c, Decoder *d, int i) {
    pthread_mutex_lock(&d->lock);
    if (!d->stopped) signal_guest_event(c, d->events[i]);
    pthread_mutex_unlock(&d->lock);
}

static void dec_configure(Cpu *c) {
    Decoder *d = self_state(c);
    MediaData *m = md(c->x[1]);
    AVCodecParameters *p = m->codecpar;
    if (!p) { LOG("[movie] Configure ohne Codec-Parameter\n"); c->x[0] = 1; return; }
    const AVCodec *codec = avcodec_find_decoder(p->codec_id);
    d->ctx = avcodec_alloc_context3(codec);
    avcodec_parameters_to_context(d->ctx, p);
    d->ctx->thread_count = 4;
    if (avcodec_open2(d->ctx, codec, NULL) < 0) { LOG("[movie] Decoder lässt sich nicht öffnen\n"); c->x[0] = 1; return; }
    d->frame = av_frame_alloc();
    d->pkt = av_packet_alloc();
    d->width = p->width;
    d->height = p->height;
    d->stride = (p->width + 255) & ~255;
    d->in_cap = 4 << 20;
    d->out_cap = (uint32_t)(d->stride * ((d->height + 15) & ~15) * 3 / 2);
    for (int i = 0; i < NIN; i++) d->in_mem[i] = hle_alloc(d->in_cap);
    for (int i = 0; i < NOUT; i++) d->out_mem[i] = hle_alloc(d->out_cap);
    LOG("[movie] Decoder %s: %dx%d\n", codec->name, d->width, d->height);
    c->x[0] = 0;
}

static void dec_register_events(Cpu *c) {
    Decoder *d = self_state(c);
    memcpy(d->events, (void *)(uintptr_t)c->x[1], sizeof d->events);
    c->x[0] = 0;
}

static void dec_output_format(Decoder *d, MediaData *m) {
    md_clear(m);
    md_set_str(m, "mime", "video/raw");
    md_set_int(m, "width", d->width);
    md_set_int(m, "height", d->height);
    md_set_int(m, "nv12-y-stride", d->stride);
    md_set_int(m, "nv12-y-offset", 0);
    md_set_int(m, "nv12-uv-offset", d->stride * ((d->height + 15) & ~15));
    md_set_int(m, "nv12-colorspace", 0);
}
static void dec_get_output_format(Cpu *c) { dec_output_format(self_state(c), md(c->x[1])); c->x[0] = 0; }
static void dec_get_output_buffer_format(Cpu *c) { dec_output_format(self_state(c), md(c->x[2])); c->x[0] = 0; }

static void dec_start(Cpu *c) {
    Decoder *d = self_state(c);
    pthread_mutex_lock(&d->lock);
    d->stopped = false;
    pthread_mutex_unlock(&d->lock);
    dec_signal(c, d, 0);  // alle Eingabepuffer sind frei
    c->x[0] = 0;
}

// Stop: danach meldet der Decoder nichts mehr; noch gesetzte Ereignisse werden gelöscht (der Spieler löscht seine Decoder und
// weckt dann einen Thread, der sonst über den Nullzeiger virtuell aufriefe).
static void dec_stop(Cpu *c) {
    Decoder *d = self_state(c);
    static uint64_t clear_event;
    if (!clear_event) clear_event = guest_sym("_ZN2nn2os10ClearEventEPNS0_9EventTypeE");
    pthread_mutex_lock(&d->lock);
    if (!d->stopped) {
        d->stopped = true;
        uint64_t saved[8];
        memcpy(saved, c->x, sizeof saved);
        for (int i = 0; i < 4; i++)
            if (d->events[i]) { c->x[0] = d->events[i]; guest_call(c, clear_event); }
        memcpy(c->x, saved, sizeof saved);
    }
    pthread_mutex_unlock(&d->lock);
    c->x[0] = 0;
}

static void dec_acquire_input(Cpu *c) {
    Decoder *d = self_state(c);
    pthread_mutex_lock(&d->lock);
    int out_free = 0;
    for (int i = 0; i < NOUT; i++) if (!d->out_busy[i]) out_free++;
    if (out_free < 2 || d->npending) { pthread_mutex_unlock(&d->lock); c->x[0] = 1; return; }  // Gegendruck
    int idx = -1, free_n = 0;
    for (int i = 0; i < NIN; i++)
        if (!d->in_busy[i]) { if (idx < 0) idx = i; else free_n++; }
    if (idx >= 0) d->in_busy[idx] = true;
    pthread_mutex_unlock(&d->lock);
    if (idx < 0) { c->x[0] = 1; return; }
    *(int32_t *)(uintptr_t)c->x[1] = idx;
    if (c->x[2]) *(int32_t *)(uintptr_t)c->x[2] = free_n;
    c->x[0] = 0;
}

static void dec_get_input_buffer(Cpu *c) {
    Decoder *d = self_state(c);
    int i = (int)c->x[1];
    MBuffer *b = BUF(c->x[2]);
    if (i < 0 || i >= NIN) { c->x[0] = 1; return; }
    memset(b, 0, sizeof *b);
    b->base = (uint64_t)(uintptr_t)d->in_mem[i];
    b->capacity = d->in_cap;
    c->x[0] = 0;
}

static bool emit_frame(Decoder *d, AVFrame *f, int64_t time, uint32_t flags) {
    int slot = -1;
    for (int i = 0; i < NOUT; i++) if (!d->out_busy[i]) { slot = i; break; }
    if (slot < 0) return false;
    uint8_t *o = d->out_mem[slot];
    uint32_t size = 0;
    if (!(flags & MOVIE_EOS)) {
        int h = d->height, w = d->width, uv_off = d->stride * ((h + 15) & ~15);
        for (int y = 0; y < h; y++) memcpy(o + y * d->stride, f->data[0] + y * f->linesize[0], w);
        for (int y = 0; y < h / 2; y++) {  // U und V zu NV12 verschränken
            uint8_t *uv = o + uv_off + y * d->stride;
            const uint8_t *u = f->data[1] + y * f->linesize[1], *v = f->data[2] + y * f->linesize[2];
            for (int x = 0; x < w / 2; x++) { uv[2 * x] = u[x]; uv[2 * x + 1] = v[x]; }
        }
        size = (uint32_t)(uv_off + d->stride * (h / 2));
    }
    d->out_busy[slot] = true;
    d->out_size[slot] = size;
    d->ready[d->nready++] = (OutReady){slot, time, flags};
    return true;
}

static bool flush_pending(Decoder *d) {
    bool any = false;
    while (d->npending && emit_frame(d, d->pending[0], d->pending_time[0], 0)) {
        av_frame_free(&d->pending[0]);
        memmove(d->pending, d->pending + 1, (d->npending - 1) * sizeof d->pending[0]);
        memmove(d->pending_time, d->pending_time + 1, (d->npending - 1) * sizeof d->pending_time[0]);
        d->npending--;
        any = true;
    }
    if (!d->npending && d->eos_pending && emit_frame(d, NULL, d->eos_time, MOVIE_EOS)) {
        d->eos_pending = false;
        any = true;
    }
    return any;
}

static void dec_send_input(Cpu *c) {
    Decoder *d = self_state(c);
    int idx = (int)c->x[1], off = (int)c->x[2], size = (int)c->x[3];
    int64_t time = (int64_t)c->x[4];
    uint32_t flags = (uint32_t)c->x[5];
    pthread_mutex_lock(&d->lock);
    if (size > 0 && idx >= 0 && idx < NIN) {
        av_packet_unref(d->pkt);
        d->pkt->data = d->in_mem[idx] + off;
        d->pkt->size = size;
        d->pkt->pts = time;
        avcodec_send_packet(d->ctx, d->pkt);
    }
    if (flags & MOVIE_EOS) avcodec_send_packet(d->ctx, NULL);
    bool produced = false;
    while (avcodec_receive_frame(d->ctx, d->frame) == 0) {
        int64_t t = d->frame->pts != AV_NOPTS_VALUE ? d->frame->pts : time;
        if (d->npending || !emit_frame(d, d->frame, t, 0)) {  // Reihenfolge halten: hinter Wartendes stellen
            if (d->npending < NPENDING) {
                d->pending[d->npending] = av_frame_clone(d->frame);
                d->pending_time[d->npending++] = t;
            } else LOG("[movie] Ausgabewarteschlange voll, Bild verworfen\n");
        }
        produced = true;
    }
    if (flags & MOVIE_EOS) { d->eos_pending = true; d->eos_time = time; }
    produced |= flush_pending(d);
    if (idx >= 0 && idx < NIN) d->in_busy[idx] = false;
    pthread_mutex_unlock(&d->lock);
    dec_signal(c, d, 0);
    if (produced) dec_signal(c, d, 1);
    c->x[0] = 0;
}

static void dec_acquire_output(Cpu *c) {
    Decoder *d = self_state(c);
    pthread_mutex_lock(&d->lock);
    if (!d->nready) { pthread_mutex_unlock(&d->lock); c->x[0] = 1; return; }
    OutReady r = d->ready[0];
    memmove(d->ready, d->ready + 1, --d->nready * sizeof *d->ready);
    int remaining = d->nready;
    pthread_mutex_unlock(&d->lock);
    *(int32_t *)(uintptr_t)c->x[1] = r.idx;
    if (c->x[2]) *(int64_t *)(uintptr_t)c->x[2] = r.time;
    if (c->x[3]) *(uint32_t *)(uintptr_t)c->x[3] = r.flags;
    if (c->x[4]) *(int32_t *)(uintptr_t)c->x[4] = remaining;
    c->x[0] = 0;
}

static void dec_get_output_buffer(Cpu *c) {
    Decoder *d = self_state(c);
    int i = (int)c->x[1];
    MBuffer *b = BUF(c->x[2]);
    if (i < 0 || i >= NOUT) { c->x[0] = 1; return; }
    if (b->base && b->capacity >= d->out_size[i] && d->out_size[i]) {  // das Spiel hat den Puffer selbst bereitgestellt (SetDataAndCapacity): dorthin schreiben
        memcpy((void *)(uintptr_t)b->base, d->out_mem[i], d->out_size[i]);
        b->offset = 0;
        b->size = (int32_t)d->out_size[i];
        c->x[0] = 0;
        return;
    }
    memset(b, 0, sizeof *b);
    b->base = (uint64_t)(uintptr_t)d->out_mem[i];
    b->capacity = d->out_cap;
    b->size = (int32_t)d->out_size[i];
    c->x[0] = 0;
}

static void dec_release_output(Cpu *c) {
    Decoder *d = self_state(c);
    dec_signal(c, d, 0);
    int i = (int)c->x[1];
    pthread_mutex_lock(&d->lock);
    if (i >= 0 && i < NOUT) d->out_busy[i] = false;
    bool produced = flush_pending(d);
    pthread_mutex_unlock(&d->lock);
    if (produced) dec_signal(c, d, 1);
    c->x[0] = 0;
}

static void dec_dtor(Cpu *c) {
    Decoder *d = self_state(c);
    if (!d) { c->x[0] = 0; return; }
    dec_stop(c);
    pthread_mutex_lock(&d->lock);
    if (d->ctx) avcodec_free_context(&d->ctx);
    for (int i = 0; i < d->npending; i++) av_frame_free(&d->pending[i]);
    d->npending = d->nready = 0;  // (die Puffer liegen im Host-Heap des Gastes und bleiben)
    av_frame_free(&d->frame);
    av_packet_free(&d->pkt);
    pthread_mutex_unlock(&d->lock);
    c->x[0] = 0;
}

static void dec_get_counts(Cpu *c) {  // Slot 14: (int*, int64*) nach Configure
    if (c->x[1]) *(int32_t *)(uintptr_t)c->x[1] = 0;
    if (c->x[2]) *(int64_t *)(uintptr_t)c->x[2] = 0;
    c->x[0] = 0;
}

HLE_FUNC("_ZN5movie7DecoderC1ENS_11DecoderTypeENS_19DecoderOutputFormatENS_11DecoderModeEi", movie_decoder_ctor) {
    uint64_t vt = g_dec_vt;
    if (!vt) {
        HostFn f[19] = {dec_dtor, dec_dtor, dec_configure, dec_register_events, dec_get_output_format, dec_start, dec_stop, ok, ok,
                        dec_acquire_input, dec_get_input_buffer, dec_send_input, dec_acquire_output, dec_get_output_buffer, dec_get_counts,
                        dec_release_output, ok, movie_log_slot, dec_get_output_buffer_format};
        vt = g_dec_vt = make_vtable(f, 19, "Decoder");
    }
    uint64_t *self = (uint64_t *)(uintptr_t)c->x[0];
    Decoder *d = calloc(1, sizeof *d);
    pthread_mutex_init(&d->lock, NULL);
    self[0] = vt;
    self[1] = (uint64_t)(uintptr_t)d;
}
