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
        const float *in = (const float *)(uintptr_t)(st.vbuf[0].addr + (uint64_t)v * stride);
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
