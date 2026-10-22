// Debug tools of the Metal renderer. Included by renderer.m, so it shares its state (st, LOG, dev, ...). Everything here is
// switched on by environment variables and does nothing otherwise.
//
//   BDSP_GEOM_CHECK=1 BDSP_GEOM_FROM=<f> [BDSP_GEOM_TO=<f>] [BDSP_GEOM_EVERY=<n>] [BDSP_GEOM_WARM=<n>] [BDSP_GEOM_LIMIT=<x>]
//       Geometry check (what Xcode's Geometry Viewer shows, as a log): from frame FROM-WARM to TO the vertex shaders also
//       store their clip positions (translator key dbg_pos). Every EVERY-th frame (default 30) in [FROM, TO] is scanned: each
//       draw is run to completion and any vertex with NaN/Inf, w ~ 0 or |x/w|, |y/w| above LIMIT (default 1000; the
//       visible range is 1) is logged with the draw's shaders, attribute formats and the raw input of the first broken
//       vertex. BDSP_DEBUG_FRAME=<f> is accepted instead of FROM. The scan flushes per draw: use it for short windows.
//       Programs compile asynchronously and a draw is skipped until its program is ready, hence the warm-up frames.
//   BDSP_SKIP_VS=<vs hex>[:<count>][,...]
//       Hide the draws of a vertex shader (and index/vertex count). Bisecting which draw paints what.
//   BDSP_SAVE_CS_DIR=<absolute dir>
//       Write the translated MSL of every compute program there (<code addr>_cs.metal).
//   BDSP_PASS_TIMES=1
//       GPU time per render pass / compute dispatch, grouped by target, with the stats line (see the end of this file).

typedef struct { bool on, scan; int64_t frame; } GeomState;

// Configuration and per-frame state. `key` gets the translator flag when this frame needs the clip positions.
static GeomState geom_state(ShaderKey *key) {
    static int on = -1, from, to, every, warm;
    if (on < 0) {
        on = getenv("BDSP_GEOM_CHECK") != NULL;
        const char *df = getenv("BDSP_DEBUG_FRAME");
        from = getenv("BDSP_GEOM_FROM") ? atoi(getenv("BDSP_GEOM_FROM")) : (df ? atoi(df) : 0);
        to = getenv("BDSP_GEOM_TO") ? atoi(getenv("BDSP_GEOM_TO")) : from;
        every = getenv("BDSP_GEOM_EVERY") ? atoi(getenv("BDSP_GEOM_EVERY")) : 30;
        warm = getenv("BDSP_GEOM_WARM") ? atoi(getenv("BDSP_GEOM_WARM")) : 90;
        if (every < 1) every = 1;
    }
    extern uint64_t renderer_present_count(void);
    GeomState g = {.on = on && from, .frame = (int64_t)renderer_present_count()};
    if (!g.on) return g;
    g.scan = g.frame >= from && g.frame <= to && (g.frame - from) % every == 0;
    if (g.frame >= (int64_t)from - warm && g.frame <= to) key->dbg_pos = 1;
    return g;
}

// Binds the buffer the dbg_pos variant writes to. Scanned frames get a fresh one (returned, to be read after the draw),
// the others a shared scratch buffer, because the shader argument must never stay unbound.
static id<MTLBuffer> geom_bind(id<MTLRenderCommandEncoder> e, bool scan) {
    static id<MTLBuffer> scratch;
    if (!scan && scratch) { [e setVertexBuffer:scratch offset:0 atIndex:DBG_VS_BUFFER_INDEX]; return nil; }
    id<MTLBuffer> b = [dev newBufferWithLength:8 * 4096 * 16 options:MTLResourceStorageModeShared];
    memset(b.contents, 0xff, 8 * 4096 * 16);  // NaN pattern: slots the shader did not write stay recognizable
    [e setVertexBuffer:b offset:0 atIndex:DBG_VS_BUFFER_INDEX];
    if (scan) return b;
    scratch = b;
    return nil;
}

// Call after the draw was encoded (and only for a scanned frame): waits for it and logs the broken vertices.
static void geom_report(const CmdRec *r, bool indexed, id<MTLBuffer> buf, const ShaderKey *vkey, int64_t frame) {
    static int64_t last_frame = -1;
    static int scanned, broken;
    static float limit = -1;
    if (limit < 0) limit = getenv("BDSP_GEOM_LIMIT") ? (float)atof(getenv("BDSP_GEOM_LIMIT")) : 1000.0f;
    if (last_frame != frame) {  // one summary line per scanned frame
        if (last_frame >= 0) LOG("[geom] frame %lld: %d draws scanned, %d with broken positions\n", (long long)last_frame, scanned, broken);
        last_frame = frame; scanned = broken = 0;
    }
    renderer_flush();
    uint32_t span = indexed || r->x[2] > 4096 ? 4096 : (uint32_t)r->x[2];  // indexed draws: the slot is the index value
    uint32_t ninst = (uint32_t)(indexed ? r->x[6] : r->x[4]);
    ninst = ninst > 8 ? 8 : (ninst ? ninst : 1);
    const float *p = buf.contents;
    uint32_t seen = 0, bad = 0, first = 0;
    for (uint32_t i = 0; i < ninst; i++)
        for (uint32_t v = 0; v < span; v++) {
            const float *c = p + ((size_t)i * 4096 + v) * 4;
            if (*(const uint32_t *)c == 0xffffffffu && *(const uint32_t *)(c + 3) == 0xffffffffu) continue;  // slot never written
            seen++;
            float w = fabsf(c[3]), ax = fabsf(c[0]), ay = fabsf(c[1]);
            bool nan = c[0] != c[0] || c[1] != c[1] || c[2] != c[2] || c[3] != c[3];
            if (nan || w < 1e-6f || ax > limit * w || ay > limit * w || ax > 1e7f || ay > 1e7f) {
                if (!bad) first = i * 4096 + v;
                bad++;
            }
        }
    scanned++;
    if (!bad) return;
    broken++;
    const float *c = p + (size_t)first * 4;
    LOG("[geom] BAD frame %lld vs %#llx fs %#llx %s count %llu inst %u: verts %u bad %u | first v%u (%g %g %g %g)\n", (long long)frame,
        (unsigned long long)st.program->stages[0].code_addr, (unsigned long long)st.program->stages[1].code_addr, indexed ? "elems" : "arrays",
        (unsigned long long)r->x[2], ninst, seen, bad, first % 4096, c[0], c[1], c[2], c[3]);
    LOG("[geom]   attrs:");
    for (int i = 0; i < st.nattrib; i++)
        LOG(" a%d(f%#x s%u o%u k%d)", i, st.attrib[i] & 0xFF, (st.attrib[i] >> 8) & 0x1F, st.attrib[i] >> 13, vkey->attr_kind[i]);
    LOG(" | streams:");
    for (int i = 0; i < st.nstream && i < 6; i++)
        LOG(" s%d(stride %u size %llu)", i, st.stream[i][0], (unsigned long long)st.vbuf[i].size);
    LOG("\n");
    uint32_t v = first % 4096;
    uint64_t stride = st.stream[0][0];
    if (st.vbuf[0].addr && stride && (uint64_t)v * stride + 16 <= st.vbuf[0].size) {  // is the vertex stream itself garbage at that vertex?
        const float *in = (const float *)GA(st.vbuf[0].addr + (uint64_t)v * stride);
        LOG("[geom]   input vb0 v%u: %g %g %g %g | %g %g %g %g\n", v, in[0], in[1], in[2], in[3], in[4], in[5], in[6], in[7]);
    }
}

// BDSP_SKIP_VS: true if this draw is to be hidden.
static bool debug_skip_draw(const CmdRec *r) {
    static int n = -1;
    static uint64_t vs[32];
    static uint32_t count[32];
    if (n < 0) {
        n = 0;
        for (const char *s = getenv("BDSP_SKIP_VS"); s && *s && n < 32;) {
            vs[n] = strtoull(s, (char **)&s, 16);
            count[n++] = *s == ':' ? (uint32_t)strtoul(s + 1, (char **)&s, 10) : 0;
            if (*s == ',') s++; else break;
        }
    }
    uint64_t cur = st.program->stages[0].code_addr;
    for (int i = 0; i < n; i++)
        if (vs[i] == cur && (!count[i] || count[i] == (uint32_t)r->x[2])) return true;
    return false;
}

// BDSP_SAVE_CS_DIR: the translated MSL of a compute program.
static void debug_save_compute_msl(uint64_t code_addr, const char *msl) {
    const char *dir = getenv("BDSP_SAVE_CS_DIR");
    if (!dir) return;
    char path[512];
    snprintf(path, sizeof path, "%s/%llx_cs.metal", dir, (unsigned long long)code_addr);
    FILE *f = fopen(path, "w");
    if (!f) return;
    fputs(msl, f);
    fclose(f);
}

// BDSP_PASS_TIMES=1: GPU time per render pass and compute dispatch (stage-boundary timestamps), summed by pass target and
// printed with the stats line as "[pass]". Apple GPUs overlap the vertex work of a pass with the fragment work of the
// previous one, so each pass is charged only the time after the previous pass ended ("timed" then adds up to at most
// the command buffers' total).
#define PT_MAX 128
typedef struct { id<MTLCounterSampleBuffer> buf; int n; struct { char label[72]; uint32_t d0, draws; } e[PT_MAX]; } PtCb;
static int pt_on = -1, pt_open = -1;
static PtCb *pt_cur, *pt_pool[64];
static int pt_npool;
static pthread_mutex_t pt_lock = PTHREAD_MUTEX_INITIALIZER;
static struct { char label[72]; uint64_t n, draws, ns; } pt_agg[64];
static int pt_nagg;
static uint64_t pt_timed_ns, pt_cb_ns;
static int pt_dump;  // command buffers still to print (BDSP_PASS_TIMES=2)
static char pt_last_label[72];
// Back to the pool (caller holds pt_lock); a full pool releases the sample buffer.
static void pt_recycle(PtCb *p) {
    if (pt_npool < 64) { pt_pool[pt_npool++] = p; return; }
    p->buf = nil;
    free(p);
}
// Name the encoder after its target so Instruments / Xcode captures show which pass is which.
static void pt_name_encoder(id<MTLRenderCommandEncoder> e) { if (pt_on > 0) e.label = @(pt_last_label); }

static bool pt_enabled(void) {
    if (pt_on < 0) pt_on = getenv("BDSP_PASS_TIMES") != NULL && [dev supportsCounterSampling:MTLCounterSamplingPointAtStageBoundary];
    return pt_on;
}

// Sample index of a new entry in the open command buffer's sample buffer, or -1.
static int pt_start(const char *label) {
    if (!pt_enabled()) return -1;
    if (!pt_cur) {
        pthread_mutex_lock(&pt_lock);
        if (pt_npool) pt_cur = pt_pool[--pt_npool];
        pthread_mutex_unlock(&pt_lock);
    }
    if (!pt_cur) {
        id<MTLCounterSet> set = nil;
        for (id<MTLCounterSet> s in dev.counterSets) if ([s.name isEqualToString:MTLCommonCounterSetTimestamp]) set = s;
        MTLCounterSampleBufferDescriptor *d = [MTLCounterSampleBufferDescriptor new];
        d.counterSet = set;
        d.storageMode = MTLStorageModeShared;
        d.sampleCount = 2 * PT_MAX;
        NSError *err = nil;
        id<MTLCounterSampleBuffer> b = set ? [dev newCounterSampleBufferWithDescriptor:d error:&err] : nil;
        if (!b) { LOG("[pass] no sample buffer: %s\n", err.localizedDescription.UTF8String); pt_on = 0; return -1; }
        pt_cur = calloc(1, sizeof *pt_cur);
        pt_cur->buf = b;
    }
    if (pt_cur->n >= PT_MAX) return -1;
    int e = pt_cur->n++;
    snprintf(pt_cur->e[e].label, sizeof pt_cur->e[e].label, "%s", label);
    pt_cur->e[e].d0 = (uint32_t)stat_draws;
    pt_cur->e[e].draws = 0;
    return 2 * e;
}

static void pt_attach_render(MTLRenderPassDescriptor *rp) {
    pt_open = -1;
    if (!pt_enabled()) return;
    id<MTLTexture> c = nil, dt = rp.depthAttachment.texture;
    int nc = 0;
    for (int i = 0; i < 8; i++)
        if (rp.colorAttachments[i].texture) { if (!c) c = rp.colorAttachments[i].texture; nc++; }
    id<MTLTexture> t = c ?: dt;
    char label[72] = "no target";
    if (t) snprintf(label, sizeof label, "%lux%lu s%lu pf%lu c%d%s", (unsigned long)t.width, (unsigned long)t.height, (unsigned long)t.sampleCount, (unsigned long)t.pixelFormat, nc, dt ? " +depth" : "");
    snprintf(pt_last_label, sizeof pt_last_label, "%s", label);
    int s = pt_start(label);
    if (s < 0) return;
    MTLRenderPassSampleBufferAttachmentDescriptor *a = rp.sampleBufferAttachments[0];
    a.sampleBuffer = pt_cur->buf;
    a.startOfVertexSampleIndex = s;
    a.endOfVertexSampleIndex = MTLCounterDontSample;
    a.startOfFragmentSampleIndex = MTLCounterDontSample;
    a.endOfFragmentSampleIndex = s + 1;
    pt_open = s / 2;
}

static void pt_close_render(void) {
    if (pt_open >= 0 && pt_cur) pt_cur->e[pt_open].draws = (uint32_t)stat_draws - pt_cur->e[pt_open].d0;
    pt_open = -1;
}

static id<MTLComputeCommandEncoder> pt_compute_encoder(const char *label) {
    int s = pt_start(label);
    if (s < 0) return [cb() computeCommandEncoder];
    MTLComputePassDescriptor *d = [MTLComputePassDescriptor computePassDescriptor];
    d.sampleBufferAttachments[0].sampleBuffer = pt_cur->buf;
    d.sampleBufferAttachments[0].startOfEncoderSampleIndex = s;
    d.sampleBufferAttachments[0].endOfEncoderSampleIndex = s + 1;
    return [cb() computeCommandEncoderWithDescriptor:d];
}

static void pt_resolve(PtCb *p, id<MTLCommandBuffer> done) {
    NSData *data = [p->buf resolveCounterRange:NSMakeRange(0, 2 * p->n)];
    const uint64_t *ts = data.bytes;
    // The tick length is taken from this command buffer: its timestamps span (about) its GPU start to end.
    uint64_t lo = UINT64_MAX, hi = 0;
    for (int i = 0; data && i < 2 * p->n; i++) { if (!ts[i]) continue; if (ts[i] < lo) lo = ts[i]; if (ts[i] > hi) hi = ts[i]; }
    double sc = hi > lo ? (done.GPUEndTime - done.GPUStartTime) / (double)(hi - lo) : 1e-9;
    uint64_t prev_end = 0;
    pthread_mutex_lock(&pt_lock);
    for (int i = 0; data && i < p->n; i++) {
        uint64_t a = ts[2 * i], b = ts[2 * i + 1];
        if (!a || b <= a) continue;
        if (pt_dump > 0)  // BDSP_PASS_TIMES=2: timeline of the first command buffers after a report (us from the first sample)
            LOG("[pass-tl] cb%d %-40s start %7.0f dur %7.0f gap %6.0f draws %u\n", pt_dump, p->e[i].label, (a - lo) * sc * 1e6, (b - a) * sc * 1e6,
                prev_end && a > prev_end ? (a - prev_end) * sc * 1e6 : 0.0, p->e[i].draws);
        // exclusive time: the part of the pass after the previous one finished (passes overlap on the GPU)
        uint64_t from = a > prev_end ? a : prev_end;
        if (b <= from) continue;
        prev_end = b;
        uint64_t ns = (uint64_t)((double)(b - from) * sc * 1e9);
        int k = 0;
        while (k < pt_nagg && strcmp(pt_agg[k].label, p->e[i].label)) k++;
        if (k == pt_nagg && pt_nagg < 64) { snprintf(pt_agg[k].label, sizeof pt_agg[k].label, "%s", p->e[i].label); pt_nagg++; }
        if (k == 64) continue;
        pt_agg[k].n++; pt_agg[k].draws += p->e[i].draws; pt_agg[k].ns += ns;
        pt_timed_ns += ns;
    }
    pt_cb_ns += (uint64_t)((done.GPUEndTime - done.GPUStartTime) * 1e9);
    if (pt_dump > 0) pt_dump--;
    p->n = 0;
    pt_recycle(p);
    pthread_mutex_unlock(&pt_lock);
}

// Called with the command buffer about to be committed: its sample buffer is resolved when the GPU is done.
static void pt_submit(id<MTLCommandBuffer> c) {
    PtCb *p = pt_cur;
    pt_cur = NULL;
    pt_open = -1;
    if (!p || !p->n) { if (p) { pthread_mutex_lock(&pt_lock); pt_recycle(p); pthread_mutex_unlock(&pt_lock); } return; }
    [c addCompletedHandler:^(id<MTLCommandBuffer> done) { pt_resolve(p, done); }];
}

// Largest entries since the last report, per presented frame.
static void pt_report(void) {
    if (!pt_on) return;
    extern uint64_t renderer_present_count(void);
    static uint64_t last_frames;
    uint64_t frames = renderer_present_count(), nf = frames > last_frames ? frames - last_frames : 1;
    last_frames = frames;
    pthread_mutex_lock(&pt_lock);
    LOG("[pass] per frame: timed %.2f ms of %.2f ms in command buffers\n", pt_timed_ns / 1e6 / nf, pt_cb_ns / 1e6 / nf);
    for (int shown = 0; shown < 12; shown++) {
        int best = -1;
        for (int k = 0; k < pt_nagg; k++) if (pt_agg[k].ns && (best < 0 || pt_agg[k].ns > pt_agg[best].ns)) best = k;
        if (best < 0) break;
        LOG("[pass]   %-44s %6.2f ms  %5.1f passes  %6.0f draws\n", pt_agg[best].label, pt_agg[best].ns / 1e6 / nf, (double)pt_agg[best].n / nf, (double)pt_agg[best].draws / nf);
        pt_agg[best].ns = 0;
    }
    memset(pt_agg, 0, sizeof pt_agg);
    pt_nagg = 0;
    if (!strcmp(getenv("BDSP_PASS_TIMES"), "2")) pt_dump = 7;
    pt_timed_ns = pt_cb_ns = 0;
    pthread_mutex_unlock(&pt_lock);
}
