// Reader and player of the keyboard's sound archive (see swkbd_snd.h). Formats, as found in the archive (little endian):
//   FSAR  header, three blocks: STRG (names), INFO (sound table), FILE (the files in it).
//   INFO  sound table: per sound its file id (+0), volume (+8), a reference to its wave sound info (+0x0c / +0x10, whose first word is the
//         index into the wave sound table of that file) and the index of its name in STRG (+0x18).
//   FWSD  wave sound set (one per file id, in the order they lie in the archive): a wave id table (archive item, wave index) and a table of wave
//         sound entries; an entry has its pitch (info +8) and a note info whose first word is an index into the wave id table.
//   FWAR  wave archive: a table of (offset, size) into its FILE block, each a FWAV.
//   FWAV  one wave: encoding (1 = PCM16), sample rate, sample count and the offset of the samples in its DATA block.
// Only mono PCM16 is played (all keyboard sounds are, apart from one looping waiting sound that the keyboard does not use).
#include "swkbd_snd.h"

#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#if defined(__APPLE__)
#include <AudioToolbox/AudioToolbox.h>
#endif

typedef struct {
    char name[56];
    int volume;                     // 0..127
    float pitch;
    uint32_t rate;
    int16_t *pcm;
    size_t frames;
} Snd;

static pthread_mutex_t g_lock = PTHREAD_MUTEX_INITIALIZER;
static char g_root[1024];
static int g_state;                 // 0 not tried, 1 loaded, -1 failed
static Snd *g_snd;
static int g_nsnd;

typedef struct { const uint8_t *d; size_t n; } Buf;

static int rd32(const Buf *b, size_t o, uint32_t *v) {
    if (o > b->n || b->n - o < 4) return 0;
    *v = (uint32_t)b->d[o] | (uint32_t)b->d[o + 1] << 8 | (uint32_t)b->d[o + 2] << 16 | (uint32_t)b->d[o + 3] << 24;
    return 1;
}
static int rd16(const Buf *b, size_t o, uint32_t *v) {
    if (o > b->n || b->n - o < 2) return 0;
    *v = (uint32_t)b->d[o] | (uint32_t)b->d[o + 1] << 8;
    return 1;
}
static int tag(const Buf *b, size_t o, const char *t) { return o <= b->n && b->n - o >= 4 && !memcmp(b->d + o, t, 4); }

// Position of the first block of a Nintendo container header (magic, bom, header size, version, size, block count, blocks of 12 bytes)
// that has the given block type; the blocks of FSAR (type 0x2000...) lie 0x14 after the start, those of FWSD / FWAR / FWAV as well.
static int block_off(const Buf *b, size_t start, uint32_t want, size_t *off) {
    uint32_t nb;
    if (!rd16(b, start + 0x10, &nb) || nb > 8) return 0;
    for (uint32_t i = 0; i < nb; i++) {
        uint32_t t, bo;
        if (!rd16(b, start + 0x14 + i * 12, &t) || !rd32(b, start + 0x14 + i * 12 + 4, &bo)) return 0;
        if (t == want) { *off = start + bo; return 1; }
    }
    return 0;
}

static size_t find_all(const Buf *b, const char *magic, size_t *out, size_t max) {
    size_t k = 0;
    for (size_t o = 0; o + 4 <= b->n && k < max; o += 4)   // the containers start on 4 byte boundaries
        if (!memcmp(b->d + o, magic, 4)) out[k++] = o;
    return k;
}

static void free_all(void) {
    for (int i = 0; i < g_nsnd; i++) free(g_snd[i].pcm);
    free(g_snd);
    g_snd = NULL; g_nsnd = 0;
}

// Parses the archive; fills g_snd. Returns the number of playable sounds, -1 when it is not an archive we understand.
static int parse(const uint8_t *data, size_t size) {
    Buf b = {data, size};
    if (!tag(&b, 0, "FSAR")) return -1;
    // FSAR: three blocks at 0x14, each {u16 type, u16 pad, u32 offset, u32 size}: STRG 0x2000, INFO 0x2001, FILE 0x2002
    size_t strg = 0, info = 0;
    uint32_t nb, bt, bo;
    if (!rd32(&b, 0x10, &nb) || nb > 8) return -1;
    for (uint32_t i = 0; i < nb; i++) {
        if (!rd16(&b, 0x14 + i * 12, &bt) || !rd32(&b, 0x14 + i * 12 + 4, &bo)) return -1;
        if (bt == 0x2000) strg = bo; else if (bt == 0x2001) info = bo;
    }
    if (!strg || !info || !tag(&b, strg, "STRG") || !tag(&b, info, "INFO")) return -1;
    // names: the string table is the first reference of STRG (offsets relative to STRG + 8), entries {u32 type, u32 offset, u32 size} relative to the table
    uint32_t v;
    if (!rd32(&b, strg + 8 + 4, &v)) return -1;
    size_t st = strg + 8 + v;
    uint32_t nstr;
    if (!rd32(&b, st, &nstr) || nstr > 4096) return -1;
    // sound table: first reference of INFO
    if (!rd32(&b, info + 8 + 4, &v)) return -1;
    size_t sndt = info + 8 + v;
    uint32_t nsnd;
    if (!rd32(&b, sndt, &nsnd) || nsnd > 4096) return -1;
    // wave sound sets and the first wave archive
    size_t fwsd[16], fwar[4];
    size_t nfwsd = find_all(&b, "FWSD", fwsd, 16), nfwar = find_all(&b, "FWAR", fwar, 4);
    if (!nfwsd || !nfwar) return -1;
    size_t war_info, war_file;
    if (!block_off(&b, fwar[0], 0x6800, &war_info) || !block_off(&b, fwar[0], 0x6801, &war_file)) return -1;
    war_info += 8; war_file += 8;
    uint32_t nwaves;
    if (!rd32(&b, war_info, &nwaves) || nwaves > 4096) return -1;

    Snd *out = calloc(nsnd ? nsnd : 1, sizeof *out);
    if (!out) return -1;
    int n = 0;
    for (uint32_t i = 0; i < nsnd; i++) {
        uint32_t t, off, fid, vol, ref_t, ref_o, wsd_index, name_i;
        if (!rd16(&b, sndt + 4 + i * 8, &t) || !rd32(&b, sndt + 4 + i * 8 + 4, &off)) continue;
        size_t e = sndt + off;
        if (!rd32(&b, e, &fid) || !rd32(&b, e + 8, &vol) || !rd16(&b, e + 0x0c, &ref_t) || !rd32(&b, e + 0x10, &ref_o) || !rd32(&b, e + 0x18, &name_i)) continue;
        if (ref_t != 0x2202 || fid < 1 || fid > nfwsd || name_i >= nstr) continue;   // wave sounds of the sets only
        vol &= 0xFF;
        if (!rd32(&b, e + ref_o, &wsd_index)) continue;
        // name
        uint32_t no, ns;
        if (!rd32(&b, st + 4 + name_i * 12 + 4, &no) || !rd32(&b, st + 4 + name_i * 12 + 8, &ns) || ns < 2 || ns > sizeof out[0].name) continue;
        if (st + no + ns > size) continue;
        // wave sound set: refs of its INFO body (block at +0x20, body +8): wave id table, wave sound table
        size_t body = fwsd[fid - 1] + 0x28, widtab, wsdtab;
        uint32_t o1, o2, nw, nwsd;
        if (!rd32(&b, body + 4, &o1) || !rd32(&b, body + 12, &o2)) continue;
        widtab = body + o1; wsdtab = body + o2;
        if (!rd32(&b, widtab, &nw) || !rd32(&b, wsdtab, &nwsd) || wsd_index >= nwsd) continue;
        uint32_t eo;
        if (!rd32(&b, wsdtab + 4 + wsd_index * 8 + 4, &eo)) continue;
        size_t ec = wsdtab + eo;
        uint32_t io, no2, noteo, widx, wave_i;
        union { uint32_t u; float f; } pitch;
        if (!rd32(&b, ec + 4, &io) || !rd32(&b, ec + io + 8, &pitch.u)) continue;   // wave sound info: pitch at +8
        if (!rd32(&b, ec + 0x14, &no2)) continue;                                   // note info table
        size_t nt = ec + no2;
        if (!rd32(&b, nt + 8, &noteo) || !rd32(&b, nt + noteo, &widx) || widx >= nw) continue;
        if (!rd32(&b, widtab + 4 + widx * 8 + 4, &wave_i) || wave_i >= nwaves) continue;
        uint32_t wo;
        if (!rd32(&b, war_info + 4 + wave_i * 12 + 4, &wo)) continue;
        size_t w = war_file + wo;
        if (!tag(&b, w, "FWAV")) continue;
        size_t winfo, wdata;
        if (!block_off(&b, w, 0x7000, &winfo) || !block_off(&b, w, 0x7001, &wdata)) continue;
        winfo += 8; wdata += 8;
        uint32_t enc, rate, frames, nch, so;
        if (!rd32(&b, winfo, &enc) || !rd32(&b, winfo + 4, &rate) || !rd32(&b, winfo + 12, &frames) || !rd32(&b, winfo + 0x14, &nch) || !rd32(&b, winfo + 0x24, &so)) continue;
        if ((enc & 0xFF) != 1 || nch != 1 || rate < 4000 || rate > 192000 || frames == 0 || frames > 2000000) continue;   // mono PCM16 only
        size_t s0 = wdata + so;
        if (s0 > size || size - s0 < (size_t)frames * 2) continue;
        Snd *s = &out[n];
        memcpy(s->name, data + st + no, ns - 1);
        s->name[ns - 1] = 0;
        s->volume = (int)vol > 127 ? 127 : (int)vol;
        s->pitch = pitch.f > 0.25f && pitch.f < 4.0f ? pitch.f : 1.0f;
        s->rate = rate;
        s->frames = frames;
        s->pcm = malloc((size_t)frames * 2);
        if (!s->pcm) continue;
        for (uint32_t k = 0; k < frames; k++) s->pcm[k] = (int16_t)((uint16_t)data[s0 + k * 2] | (uint16_t)data[s0 + k * 2 + 1] << 8);
        n++;
    }
    free_all();
    g_snd = out; g_nsnd = n;
    return n;
}

static int ensure_loaded(void) {
    if (g_state) return g_state > 0;
    g_state = -1;
    if (!g_root[0]) return 0;
    char path[1100];
    snprintf(path, sizeof path, "%s/swkbd/sound/swkbd.bfsar", g_root);
    FILE *f = fopen(path, "rb");
    if (!f) return 0;
    fseek(f, 0, SEEK_END);
    long sz = ftell(f);
    fseek(f, 0, SEEK_SET);
    if (sz > 16 && sz < (64 << 20)) {
        uint8_t *buf = malloc((size_t)sz);
        if (buf && fread(buf, 1, (size_t)sz, f) == (size_t)sz && parse(buf, (size_t)sz) > 0) g_state = 1;
        free(buf);
    }
    fclose(f);
    return g_state > 0;
}

void swkbd_snd_set_root(const char *root) {
    pthread_mutex_lock(&g_lock);
    snprintf(g_root, sizeof g_root, "%s", root ? root : "");
    g_state = 0;
    pthread_mutex_unlock(&g_lock);
}

int swkbd_snd_load_memory(const uint8_t *data, size_t size) {
    pthread_mutex_lock(&g_lock);
    int n = parse(data, size);
    g_state = n > 0 ? 1 : -1;
    pthread_mutex_unlock(&g_lock);
    return n;
}

static const Snd *lookup(const char *name) {
    for (int i = 0; i < g_nsnd; i++) if (!strcmp(g_snd[i].name, name)) return &g_snd[i];
    return NULL;
}

int swkbd_snd_info(const char *name, size_t *frames, uint32_t *rate, int *volume, int *peak) {
    pthread_mutex_lock(&g_lock);
    int ok = 0;
    if (ensure_loaded()) {
        const Snd *s = lookup(name);
        if (s) {
            ok = 1;
            if (frames) *frames = s->frames;
            if (rate) *rate = s->rate;
            if (volume) *volume = s->volume;
            if (peak) { int p = 0; for (size_t i = 0; i < s->frames; i++) { int a = abs(s->pcm[i]); if (a > p) p = a; } *peak = p; }
        }
    }
    pthread_mutex_unlock(&g_lock);
    return ok;
}

#if defined(__APPLE__)
typedef struct { const int16_t *pcm; size_t frames; double rate; float gain; } Play;

static void queue_done(void *user, AudioQueueRef q, AudioQueueBufferRef buf) { (void)user; (void)q; (void)buf; }

// One queue per sound, disposed after it has played; the sounds are a few milliseconds to 130 ms long.
static void *play_thread(void *arg) {
    Play *p = arg;
    AudioStreamBasicDescription f = {0};
    f.mSampleRate = p->rate;
    f.mFormatID = kAudioFormatLinearPCM;
    f.mFormatFlags = kAudioFormatFlagIsSignedInteger | kAudioFormatFlagIsPacked;
    f.mBitsPerChannel = 16; f.mChannelsPerFrame = 1; f.mFramesPerPacket = 1; f.mBytesPerFrame = 2; f.mBytesPerPacket = 2;
    AudioQueueRef q = NULL;
    OSStatus st = AudioQueueNewOutput(&f, queue_done, NULL, NULL, NULL, 0, &q);
    if (getenv("BDSP_TRACE_APPLET")) fprintf(stderr, "[swkbd_snd] queue %d (%zu frames at %.0f Hz, gain %.2f)\n", (int)st, p->frames, p->rate, p->gain);
    if (st == 0) {
        AudioQueueBufferRef buf = NULL;
        UInt32 bytes = (UInt32)(p->frames * 2);
        if (AudioQueueAllocateBuffer(q, bytes, &buf) == 0) {
            memcpy(buf->mAudioData, p->pcm, bytes);
            buf->mAudioDataByteSize = bytes;
            AudioQueueSetParameter(q, kAudioQueueParam_Volume, p->gain);
            OSStatus se = AudioQueueEnqueueBuffer(q, buf, 0, NULL), ss = se == 0 ? AudioQueueStart(q, NULL) : se;
            if (getenv("BDSP_TRACE_APPLET")) fprintf(stderr, "[swkbd_snd] start %d\n", (int)ss);
            if (ss == 0) usleep((useconds_t)(p->frames * 1000000.0 / p->rate) + 150000);
        }
        AudioQueueStop(q, true);
        AudioQueueDispose(q, true);
    }
    free(p);
    return NULL;
}
#endif

void swkbd_snd_play(const char *name) {
    static int off = -1;
    if (off < 0) off = getenv("BDSP_SWKBD_SOUND") && !strcmp(getenv("BDSP_SWKBD_SOUND"), "0");
    if (off || !name) return;
#if defined(__APPLE__)
    pthread_mutex_lock(&g_lock);
    const Snd *s = ensure_loaded() ? lookup(name) : NULL;
    Play *p = NULL;
    if (s && s->volume > 0) {
        p = malloc(sizeof *p);
        if (p) { p->pcm = s->pcm; p->frames = s->frames; p->rate = s->rate * s->pitch; p->gain = s->volume / 127.0f; }
    }
    pthread_mutex_unlock(&g_lock);
    if (!p) return;
    pthread_t th;
    pthread_attr_t at;
    pthread_attr_init(&at);
    pthread_attr_setdetachstate(&at, PTHREAD_CREATE_DETACHED);
    if (pthread_create(&th, &at, play_thread, p)) free(p);
    pthread_attr_destroy(&at);
#else
    (void)name;
#endif
}
