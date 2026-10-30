// Executes recorded NVN command lists with Metal.
#include <pthread.h>
#include <dirent.h>
#include <unistd.h>
#include <sys/sysctl.h>
#include <TargetConditionals.h>
#import <Metal/Metal.h>
#include <mach/mach_time.h>
#include <stdlib.h>
#include <string.h>
#include <float.h>
#include <math.h>
#include <sys/stat.h>
#include <SDL3/SDL_timer.h>

#include "maxwell/shader.h"
// The XNU translator dropped the original's debug hooks (nvn_glue.c defines them as unused variables).
extern const uint8_t *maxwell_dbg_code, *maxwell_dbg_vs;
extern uint32_t maxwell_dbg_pc;
extern int maxwell_dbg_reg;
#define DBG_VS_BUFFER_INDEX 29
#include "nvn.h"
#include "renderer.h"
#include "bctc.h"
#include "exec_worker.inc"

static id<MTLDevice> dev;
static id<MTLCommandBuffer> cmdbuf;
static id<MTLRenderCommandEncoder> enc;
static id<MTLRenderPipelineState> clear_pipes[64];
static NSMutableDictionary<NSString *, id> *cache;
// (stats) GPU wait time by cause: 0 = guest fence (nvnSyncWait), 1 = full flush (CPU reads GPU results / ring), 2 = sync all
static uint64_t stat_wait_by[3], stat_wait_n[3];
// (stats) full flushes by cause: compute-write hazard on a vertex stream, texture read-back, buffer copy, other
enum { FL_OTHER, FL_HAZARD, FL_READBACK, FL_BUF2BUF, FL_ARENA, FL_N };
// (stats) GPU memory arena (BDSP_GMEM_ARENA): bytes copied in, ranges reused from earlier GPU work, bytes written back
static uint64_t stat_arena_bytes, stat_arena_n, stat_arena_reuse, stat_arena_wb, stat_arena_flushes;
static bool arena_on(void);
static uint64_t stat_flush_n[FL_N], stat_flush_ticks[FL_N];
static uint64_t stat_draws, stat_skipped, stat_passes, stat_dispatches, stat_wait_ns, stat_flushes, stat_feedback_copies;
static double stat_gpu_s;
// BDSP_PASS_TIMES (render_debug.inc): GPU time per pass
static void pt_attach_render(MTLRenderPassDescriptor *rp);
static void pt_name_encoder(id<MTLRenderCommandEncoder> e);
static void pt_close_render(void);
static id<MTLComputeCommandEncoder> pt_compute_encoder(const char *label);
static void pt_submit(id<MTLCommandBuffer> c);
static void pt_report(void);
static uint64_t prof_exec_ns, prof_submit_ns, prof_n, prof_last_ns;
uint64_t g_gpu_total_ns;  // GPU time of all completed command buffers (dynamic resolution: output_scale.c)
// (forward: texture-lifetime cleanup and stats, defined further down)
static int g_views_live;
static void views_forget(void *base);
static NSMutableDictionary *g_snap_copies;
static NvnTexture *snap_tex[8];
static bool snap_ok[8];
static uint64_t op_counts[CMD_COUNT];
bool g_debug_frame;
void renderer_save_texture(id<MTLTexture> tex, const char *path);
void renderer_save_texture_alpha(id<MTLTexture> tex, const char *path);
static char stats_text[1024];
// (stats) bytes copied into the ring by what they are: 0 other, 1 vertex streams, 2 uniform buffers, 3 indices
static int ring_site;
static uint64_t stat_ring_bytes[4], stat_ring_n[4];

// ------------------------------------------------------------------ state
typedef struct {
    NvnTexture *color[8];
    NvnTextureView cview[8];
    uint8_t has_cview[8];
    int ncolor;
    NvnTexture *depth;
    NvnTextureView dview;
    uint8_t has_dview;
} RtState;

typedef struct { uint64_t addr, size; } Range;

static struct {
    RtState rt;
    bool rt_dirty;
    NvnProgram *program;
    uint8_t blend[8][8];
    uint32_t channel_mask;
    uint8_t color_state[4], ds[8], ms[0x18], poly[4];
    float poly_offset[3];  // factor, units, clamp (nvnCommandBufferSetPolygonOffsetClamp)
    uint32_t attrib[16];
    int nattrib;
    uint32_t stream[16][2];
    int nstream;
    Range vbuf[16], ubuf[6][18], sbuf[6][16];
    uint64_t tex[6][32], img[6][8], smp[6][32];  // smp: separate sampler handles (id << 20)
    NvnDescPool *tpool, *spool;
    float viewport[16][4];
    int32_t scissor[16][4];
    float depth_range[16][2];
    float blend_color[4];
    uint32_t stencil_ref[2], stencil_mask[2], stencil_vmask[2];
    bool prim_restart;
    uint32_t restart_index;
    uint64_t copy_row_stride, copy_image_stride;
} st;

extern uint32_t g_window_origin_lower_left_hack;
uint32_t nvn_window_origin(void);
bool renderer_origin_lower_left(void) { return nvn_window_origin() == 0; }

static double stat_compile_ms;  // time spent building shaders/pipelines (first-use stutter)
static int stat_compiles;
static inline double now_ms(void) { return (double)clock_gettime_nsec_np(CLOCK_UPTIME_RAW) / 1e6; }
#define TIMED_COMPILE(expr) ({ double t0_ = now_ms(); __auto_type r_ = (expr); stat_compile_ms += now_ms() - t0_; stat_compiles++; r_; })

void renderer_draw_counts(uint64_t *draws, uint64_t *skipped) { *draws = stat_draws; *skipped = stat_skipped; }
// Texture release waits for the worker while it still has work (BDSP_XW_DRAIN_DESTROY=1, iOS default)
void renderer_xw_destroy_wait(void) {
    if (!xw_enabled() || xw_is_worker) return;
    static int drain = -1;
    static uint64_t n, pending;
    if (drain < 0) drain = getenv("BDSP_XW_DRAIN_DESTROY") != NULL;
    n++;
    pthread_mutex_lock(&xw_lock);
    bool busy = xw_done < xw_tail;
    pthread_mutex_unlock(&xw_lock);
    if (busy) pending++;
    if (n % 200 == 0 || n == 1) printf("[xw] textures destroyed %llu, of those with the worker running %llu\n", (unsigned long long)n, (unsigned long long)pending);
    if (drain) xw_drain();
}
const char *renderer_stats(void) {
    static int dumps;
    if (dumps++ < 3) {
        LOG("[metal] command counts:");
        for (int i = 0; i < CMD_COUNT; i++) if (op_counts[i]) LOG(" %d:%llu", i, op_counts[i]);
        LOG("\n");
    }
    extern int g_tex_live;
    extern uint64_t g_tex_live_bytes;
    struct task_vm_info vmi;
    mach_msg_type_number_t vn = TASK_VM_INFO_COUNT;
    uint64_t foot = task_info(mach_task_self(), TASK_VM_INFO, (task_info_t)&vmi, &vn) == KERN_SUCCESS ? vmi.phys_footprint : 0;
    snprintf(stats_text, sizeof stats_text, "%llu draws, %llu skipped, %llu passes, %llu dispatches, %llu flushes, gpu %.0fms, wait %.0fms, compile %d/%.0fms, fbcopy %llu | tex %d (%.0f MB) views %d snaps %lu mem %.0f MB | waits fence %.0fms/%llu flush %.0fms/%llu all %.0fms/%llu | flush by hazard %llu/%.0fms readback %llu/%.0fms buf2buf %llu/%.0fms other %llu/%.0fms", stat_draws, stat_skipped,
             stat_passes, stat_dispatches, stat_flushes, stat_gpu_s * 1000.0, (double)stat_wait_ns / 1e6 * 125.0 / 3.0, stat_compiles, stat_compile_ms, stat_feedback_copies,
             g_tex_live, g_tex_live_bytes / 1048576.0, g_views_live, (unsigned long)(g_snap_copies ? g_snap_copies.count : 0), foot / 1048576.0, stat_wait_by[0] / 24e3, (unsigned long long)stat_wait_n[0], stat_wait_by[1] / 24e3, (unsigned long long)stat_wait_n[1], stat_wait_by[2] / 24e3, (unsigned long long)stat_wait_n[2],
             (unsigned long long)stat_flush_n[FL_HAZARD], stat_flush_ticks[FL_HAZARD] / 24e3, (unsigned long long)stat_flush_n[FL_READBACK], stat_flush_ticks[FL_READBACK] / 24e3,
             (unsigned long long)stat_flush_n[FL_BUF2BUF], stat_flush_ticks[FL_BUF2BUF] / 24e3, (unsigned long long)stat_flush_n[FL_OTHER], stat_flush_ticks[FL_OTHER] / 24e3);
    memset(stat_flush_n, 0, sizeof stat_flush_n); memset(stat_flush_ticks, 0, sizeof stat_flush_ticks);
    {
        size_t n = strlen(stats_text);
        snprintf(stats_text + n, sizeof stats_text - n, " | ring MB vertex %.0f/%llu uniform %.0f/%llu index %.0f/%llu other %.0f/%llu", stat_ring_bytes[1] / 1048576.0, (unsigned long long)stat_ring_n[1],
                 stat_ring_bytes[2] / 1048576.0, (unsigned long long)stat_ring_n[2], stat_ring_bytes[3] / 1048576.0, (unsigned long long)stat_ring_n[3], stat_ring_bytes[0] / 1048576.0, (unsigned long long)stat_ring_n[0]);
        memset(stat_ring_bytes, 0, sizeof stat_ring_bytes); memset(stat_ring_n, 0, sizeof stat_ring_n);
    }
    if (arena_on()) {
        size_t n = strlen(stats_text);
        snprintf(stats_text + n, sizeof stats_text - n, " | arena MB %.1f/%llu reused %llu written back KB %.0f flushes %llu", stat_arena_bytes / 1048576.0,
                 (unsigned long long)stat_arena_n, (unsigned long long)stat_arena_reuse, stat_arena_wb / 1024.0, (unsigned long long)stat_arena_flushes);
        stat_arena_bytes = stat_arena_n = stat_arena_reuse = stat_arena_wb = stat_arena_flushes = 0;
    }
    pt_report();
    stat_compiles = 0;
    stat_feedback_copies = 0;
    stat_compile_ms = 0;
    stat_draws = stat_skipped = stat_passes = stat_dispatches = stat_flushes = stat_wait_ns = 0;
    memset(stat_wait_by, 0, sizeof stat_wait_by); memset(stat_wait_n, 0, sizeof stat_wait_n);
    stat_gpu_s = 0;
    return stats_text;
}

static void st_defaults(void) {
    memset(&st, 0, sizeof st);
    for (int i = 0; i < 16; i++) {
        st.viewport[i][2] = 1280; st.viewport[i][3] = 720;
        st.scissor[i][2] = 16384; st.scissor[i][3] = 16384;
        st.depth_range[i][1] = 1.0f;
    }
    st.channel_mask = 0xFFFFFFFF;
    st.stencil_mask[0] = st.stencil_mask[1] = 0xFF;
    st.stencil_vmask[0] = st.stencil_vmask[1] = 0xFF;
    st.ds[1] = 1; st.ds[2] = 2;
    st.poly[1] = 1; st.poly[2] = 2;
    for (int i = 0; i < 8; i++) { st.blend[i][1] = 2; st.blend[i][2] = 1; st.blend[i][3] = 2; st.blend[i][4] = 1; st.blend[i][5] = 1; st.blend[i][6] = 1; }
}

void renderer_init(id<MTLDevice> d) {
    dev = d;
    cache = [NSMutableDictionary new];
    st_defaults();
}

static int g_passes_in_cb;  // render passes encoded into the open command buffer (chunked commits)
static id<MTLCommandBuffer> cb(void) {
    if (!cmdbuf) cmdbuf = [renderer_queue() commandBuffer];
    return cmdbuf;
}

void renderer_texture_scale(NvnTexture *t, float *sx, float *sy);
void renderer_get_scale(float *sx, float *sy);
static float pass_sx = 1, pass_sy = 1;  // allocation scale of the current pass's attachments
bool renderer_texture_presented(NvnTexture *t);
// Widescreen UI: 2D draws into the swapchain image use a centred 16:9 region (uniform scale) instead of
// the stretched wide mapping. vp_* is the mapping for the current draw: physical = guest * s + off.
static float vp_sx = 1, vp_sy = 1, vp_ox = 0, vp_oy = 0;
static float tex_sc[2][64][2];          // per bound texture slot: allocation scale (for shaders' texel math)
static uint32_t tex_wh[2][64][2];       // per bound texture slot: guest size
static int draw_bottle;                 // a fragment texture is the bottle's item icon (1) / model map (2): Escape Bottle
static int draw_heart;                  // ... a HUD / file select heart's: heart colour (Cosmetics tab)
static bool draw_item_cursor;           // a fragment texture is the Items page's cursor brackets
#define RSCALE_BUFFER_INDEX 18

static int debug_pass_no;
static id<MTLTexture> pass_color0;  // first colour attachment of the open pass (st.rt already names the next pass when end_pass runs)
static void end_pass(void) {
    if (enc) {
        [enc endEncoding];
        enc = nil;
        pt_close_render();
        if (g_debug_frame && pass_color0) {
            id<MTLTexture> t = pass_color0;
            id<MTLCommandBuffer> c = cmdbuf;
            cmdbuf = nil;
            [c commit];
            [c waitUntilCompleted];
            char path[512];
            const char *dir = getenv("BDSP_PASS_DIR") ? getenv("BDSP_PASS_DIR") : "build";  // the app's working directory has no build/
            snprintf(path, sizeof path, "%s/pass_%03d.png", dir, debug_pass_no);
            renderer_save_texture(t, path);
            snprintf(path, sizeof path, "%s/pass_%03d_a.png", dir, debug_pass_no++);
            renderer_save_texture_alpha(t, path);
        }
    }
}

static void ring_reset(void);
static void arena_writeback_upto(uint64_t seq);
static void arena_assign(uint64_t seq);
// Submitted work runs asynchronously; last_cb is the most recently committed command buffer (the queue
// executes in order, so waiting for it waits for everything before it). Other guest threads (nvnSyncWait)
// read last_cb, so it is guarded by cb_lock; everything else here runs on the submitting thread.
static id<MTLCommandBuffer> last_cb;
static pthread_mutex_t cb_lock = PTHREAD_MUTEX_INITIALIZER;
// Fences: each committed command buffer gets a sequence number; a fence remembers the number of the submission
// that contains it, and nvnSyncWait waits only for that one (not for everything submitted since), so the game's
// CPU work on frame N+1 overlaps the GPU's frame N as on the Switch.
#define CB_HIST 256
static uint64_t submit_seq;
static id<MTLCommandBuffer> cb_hist[CB_HIST];

static int g_wait_kind;
static void wait_cb(id<MTLCommandBuffer> c) {
    if (!c) return;
    uint64_t t0 = mach_absolute_time();
    [c waitUntilCompleted];
    uint64_t d = mach_absolute_time() - t0;
    stat_wait_ns += d;
    stat_wait_by[g_wait_kind] += d;
    if (d > 24000) stat_wait_n[g_wait_kind]++;  // (> ~1 ms counts as a real wait)
}

// Textures the game destroyed (any thread): their cached views and snapshot copies are dropped on the render thread.
static pthread_mutex_t gone_lock = PTHREAD_MUTEX_INITIALIZER;
static struct { void *nvn, *mtl; } gone[4096];
static int ngone;
void renderer_texture_gone(void *nvn_tex, void *mtl_tex) {
    pthread_mutex_lock(&gone_lock);
    if (ngone < 4096) { gone[ngone].nvn = nvn_tex; gone[ngone].mtl = mtl_tex; ngone++; }
    pthread_mutex_unlock(&gone_lock);
}
static void drain_gone(void) {
    pthread_mutex_lock(&gone_lock);
    int n = ngone;
    static struct { void *nvn, *mtl; } local[4096];
    memcpy(local, gone, sizeof local[0] * n);
    ngone = 0;
    pthread_mutex_unlock(&gone_lock);
    for (int i = 0; i < n; i++) {
        if (local[i].mtl) views_forget(local[i].mtl);
        if (local[i].nvn) {
            if (g_snap_copies) [g_snap_copies removeObjectForKey:[NSValue valueWithPointer:local[i].nvn]];
            for (int k = 0; k < 8; k++) if (snap_tex[k] == local[i].nvn) { snap_tex[k] = NULL; snap_ok[k] = false; }
        }
    }
}

// Commit recorded work without waiting.
void renderer_submit(void) {
    xw_drain();
    end_pass();
    drain_gone();
    if (cmdbuf) {
        id<MTLCommandBuffer> c = cmdbuf;
        cmdbuf = nil;
        uint64_t seq = submit_seq + 1;  // (submit_seq only changes on this thread)
        arena_assign(seq);
        [c addCompletedHandler:^(id<MTLCommandBuffer> done) {
            arena_writeback_upto(seq);
            stat_gpu_s += done.GPUEndTime - done.GPUStartTime;
            __atomic_add_fetch(&g_gpu_total_ns, (uint64_t)((done.GPUEndTime - done.GPUStartTime) * 1e9), __ATOMIC_RELAXED);
            if (done.error) LOG("[metal] command buffer error: %s\n", done.error.localizedDescription.UTF8String);
        }];
        pt_submit(c);
        [c commit];
        g_passes_in_cb = 0;
        pthread_mutex_lock(&cb_lock);
        last_cb = c;
        submit_seq++;
        cb_hist[submit_seq % CB_HIST] = c;
        pthread_mutex_unlock(&cb_lock);
        stat_flushes++;
    }
}

// Compute dispatches write storage buffers on the GPU, but a draw copies its vertex streams from guest memory when it is
// encoded (bind_guest). Skinned meshes are drawn from such buffers, so a stream that overlaps a range a still-pending
// dispatch writes would be copied before the dispatch ran. The ranges are remembered here until the GPU has caught up.
#define HZ_MAX 128
static struct { uint64_t addr, size; } hz_ranges[HZ_MAX];
static int hz_n;

// Finish all recorded GPU work (the CPU is about to read GPU results, or reuse the ring).
static void flush_why(int why) {
    renderer_submit();
    pthread_mutex_lock(&cb_lock);
    id<MTLCommandBuffer> c = last_cb;
    pthread_mutex_unlock(&cb_lock);
    g_wait_kind = 1;
    uint64_t t0 = mach_absolute_time();
    wait_cb(c);
    arena_writeback_upto(submit_seq);
    stat_flush_n[why]++;
    stat_flush_ticks[why] += mach_absolute_time() - t0;
    g_wait_kind = 0;
    hz_n = 0;  // the GPU has run everything submitted so far
    ring_reset();
}
void renderer_flush(void) { flush_why(FL_OTHER); }

#include "render_debug.inc"  // environment-driven debug tools (geometry check, draw hiding, compute MSL dump)

// Wait for submitted work without committing anything new (nvnSyncWait / QueueFinish).
// Callable from any thread: everything submitted so far was committed by renderer_submit.
void renderer_sync(void) {
    xw_drain();
    pthread_mutex_lock(&cb_lock);
    id<MTLCommandBuffer> c = last_cb;
    uint64_t seq = submit_seq;
    pthread_mutex_unlock(&cb_lock);
    g_wait_kind = 2;
    wait_cb(c);
    arena_writeback_upto(seq);   // the guest may read what the GPU wrote as soon as this returns
    g_wait_kind = 0;
}

// Sequence number a fence placed now belongs to: the pending (uncommitted) work's submission, else the last one.
uint64_t renderer_fence_seq(void) {
    if (xw_enabled()) return xw_fence_token();
    pthread_mutex_lock(&cb_lock);
    uint64_t q = submit_seq + (cmdbuf ? 1 : 0);
    pthread_mutex_unlock(&cb_lock);
    return q;
}

uint64_t renderer_last_submit_seq(void) {
    pthread_mutex_lock(&cb_lock);
    uint64_t q = submit_seq;
    pthread_mutex_unlock(&cb_lock);
    return q;
}

// Wait until submission `seq` has completed (0 = nothing to wait for).
void renderer_wait_seq(uint64_t seq) {
    if (seq & XW_TAG) {  // worker token: wait for that job, then for the command buffer it ended in (not for later frames' work)
        uint64_t n = seq & ~XW_TAG;
        xw_wait_job(n);
        static int old_wait = -1;
        if (old_wait < 0) old_wait = getenv("BDSP_FENCE_LAST") != NULL;
        seq = old_wait || !n ? UINT64_MAX : xw_job_seq[(n - 1) % XW_CAP];
    }
    if (!seq) return;
    if (ENV("BDSP_LOG_FENCES")) {  // (debug) how far behind the newest submission the waited fence is
        extern uint64_t renderer_present_count(void);
        static uint64_t f0, hist[6], frames_seen;
        uint64_t f = renderer_present_count();
        uint64_t pend = submit_seq + (cmdbuf ? 1 : 0);
        uint64_t age = pend > seq ? pend - seq : 0;
        bool done_already = false;
        pthread_mutex_lock(&cb_lock);
        if (seq <= submit_seq && submit_seq - seq < CB_HIST && cb_hist[seq % CB_HIST])
            done_already = cb_hist[seq % CB_HIST].status >= MTLCommandBufferStatusCompleted;
        pthread_mutex_unlock(&cb_lock);
        hist[age > 4 ? 4 : age]++;
        if (done_already) hist[5]++;
        if (f - f0 >= 300) {
            frames_seen = f - f0;
            LOG("[fences] per %llu frames: waits by age (submissions behind newest) 0:%llu 1:%llu 2:%llu 3:%llu 4+:%llu, already done %llu; submissions now %llu\n",
                (unsigned long long)frames_seen, hist[0], hist[1], hist[2], hist[3], hist[4], hist[5], (unsigned long long)submit_seq);
            memset(hist, 0, sizeof hist);
            f0 = f;
        }
    }
    pthread_mutex_lock(&cb_lock);
    id<MTLCommandBuffer> c = nil;
    uint64_t upto = seq > submit_seq ? submit_seq : seq;
    if (seq > submit_seq) c = last_cb;  // not committed yet (other thread): wait for everything committed so far
    else if (submit_seq - seq < CB_HIST) c = cb_hist[seq % CB_HIST];
    pthread_mutex_unlock(&cb_lock);
    wait_cb(c);
    arena_writeback_upto(upto);
}

// ------------------------------------------------------------------ textures with views
// Texture view cache: views are made per bind otherwise (an allocation per draw). Keyed by the base texture and
// the view parameters; a cached view retains its base, so a key's base pointer can't be reused while cached.
#define VIEW_TAB 16384
static struct { uint64_t key; void *base; void *view; } view_tab[VIEW_TAB];

// Views keep their base texture alive: when the game frees a texture its views must go too (they piled up -
// render targets of a 32:9 window held long after the game dropped them - and a new texture at the same address
// could get a stale view). Entries are tombstoned (key ~0) so probe chains stay intact.
static void views_forget(void *base) {
    for (int i = 0; i < VIEW_TAB; i++)
        if (view_tab[i].base == base && view_tab[i].view) {
            CFRelease(view_tab[i].view);
            view_tab[i].view = NULL;
            view_tab[i].base = NULL;
            view_tab[i].key = ~0ull;
            g_views_live--;
        }
}

static id<MTLTexture> view_cached(id<MTLTexture> base, uint64_t params, id<MTLTexture> (^make)(void)) {
    uint64_t k = ((uint64_t)(uintptr_t)(__bridge void *)base * 0x9E3779B97F4A7C15ull) ^ (params * 0xC2B2AE3D27D4EB4Full);
    if (!k) k = 1;
    if (k == ~0ull) k = 2;
    // up to 8 probes; a miss is stored in the first free or tombstoned slot of those, else over the first one.
    // (It used to go to the slot past the 8 probes - never found again - and tombstones were never reused: on the
    // overworld, where textures stream in and out, more and more binds made a new view every time, the slowdown
    // that grew with play time until a level change - user report 2026-10-08, 32:9.)
    uint32_t start = (uint32_t)(k ^ (k >> 32)) & (VIEW_TAB - 1), slot = start;
    int free_slot = -1;
    for (int probe = 0; probe < 8; probe++, slot = (slot + 1) & (VIEW_TAB - 1)) {
        if (view_tab[slot].key == k && view_tab[slot].base == (__bridge void *)base) return (__bridge id<MTLTexture>)view_tab[slot].view;
        if (!view_tab[slot].key || view_tab[slot].key == ~0ull) {
            if (free_slot < 0) free_slot = (int)slot;
            if (!view_tab[slot].key) break;  // (end of the chain)
        }
    }
    slot = free_slot >= 0 ? (uint32_t)free_slot : start;
    id<MTLTexture> v = make();
    if (!v) return base;
    if (ENV("BDSP_LOG_VIEWCREATE")) {  // (debug: what keeps making new views - overworld soak, views pile up)
        extern uint64_t renderer_present_count(void);
        static int n;
        if (renderer_present_count() > (uint64_t)atol(ENV("BDSP_LOG_VIEWCREATE")) && n++ < 400)
            LOG("[viewnew] f%llu base %p %s %lux%lu fmt %lu type %lu params %#llx live %d\n", (unsigned long long)renderer_present_count(),
                (__bridge void *)base, base.label.UTF8String, (unsigned long)base.width, (unsigned long)base.height,
                (unsigned long)base.pixelFormat, (unsigned long)base.textureType, (unsigned long long)params, g_views_live);
    }
    if (view_tab[slot].view) { CFRelease(view_tab[slot].view); g_views_live--; }  // evict (8 probes all taken)
    g_views_live++;
    view_tab[slot].key = k;
    view_tab[slot].base = (__bridge void *)base;
    view_tab[slot].view = (void *)CFBridgingRetain(v);
    return v;
}

static id<MTLTexture> view_texture(NvnTexture *t, const NvnTextureView *v, bool has_view, bool render,
                                   id<MTLBlitCommandEncoder> blit) {
    id<MTLTexture> base = renderer_texture(t, blit, render);
    if (!has_view || !v->setmask) return base;
    MTLPixelFormat pf = (v->setmask & 4) ? renderer_pixel_format(v->format) : base.pixelFormat;
    NSUInteger lv0 = (v->setmask & 1) ? v->base_level : 0;
    NSUInteger nlv = (v->setmask & 1) && v->num_levels ? v->num_levels : base.mipmapLevelCount - lv0;
    NSUInteger ly0 = (v->setmask & 2) ? v->min_layer : 0;
    NSUInteger nly = (v->setmask & 2) && v->num_layers ? v->num_layers : base.arrayLength - ly0;
    if (base.textureType == MTLTextureTypeCube) nly = 6;
    MTLTextureType type = base.textureType;
    if (render && (type == MTLTextureType2DArray || type == MTLTextureTypeCube) && nly == 1) type = MTLTextureType2D;
    if (lv0 + nlv > base.mipmapLevelCount) nlv = base.mipmapLevelCount - lv0;
    if (nlv == 0 || nly == 0) return base;  // empty view: Metal aborts, use the base
    if (pf == base.pixelFormat && lv0 == 0 && nlv == base.mipmapLevelCount && ly0 == 0 && type == base.textureType)
        return base;
    static int vlog;  // BDSP_LOG_VIEWS: texture views that change the pixel format
    if (pf != base.pixelFormat && vlog < 20 && getenv("BDSP_LOG_VIEWS")) {
        vlog++;
        LOG("[view] tex fmt %#x (mtl %lu) viewed as nvn %#x (mtl %lu)\n", t->format, (unsigned long)base.pixelFormat, v->format, (unsigned long)pf);
    }
    NSUInteger ns = type == MTLTextureType2D ? 1 : nly;
    uint64_t params = (uint64_t)pf | (uint64_t)type << 16 | (uint64_t)lv0 << 24 | (uint64_t)nlv << 32 | (uint64_t)ly0 << 40 | (uint64_t)ns << 52;
    id<MTLTexture> got = view_cached(base, params, ^{
        return [base newTextureViewWithPixelFormat:pf textureType:type levels:NSMakeRange(lv0, nlv) slices:NSMakeRange(ly0, ns)];
    });
    if (got == base && pf != base.pixelFormat) {
        static int nfail;
        if (nfail++ < 10) LOG("[view] FAILED %lu -> %lu (nvn %#x -> %#x)\n", (unsigned long)base.pixelFormat, (unsigned long)pf, t->format, v->format);
    }
    return got;
}

// ------------------------------------------------------------------ render passes
static __unsafe_unretained id last_bias_enc;  // encoder the depth bias was last set on

static void begin_pass(void) {
    if (enc && !st.rt_dirty) return;
    end_pass();
    st.rt_dirty = false;
    MTLRenderPassDescriptor *rp = [MTLRenderPassDescriptor renderPassDescriptor];
    int w = 0, h = 0;
    pass_color0 = nil;
    for (int i = 0; i < st.rt.ncolor; i++) {
        NvnTexture *t = st.rt.color[i];
        if (!t) continue;
        renderer_mark_gpu_owned(t);
        id<MTLTexture> tex = view_texture(t, &st.rt.cview[i], st.rt.has_cview[i], true, nil);
        if (!pass_color0) pass_color0 = tex;
        rp.colorAttachments[i].texture = tex;
        rp.colorAttachments[i].loadAction = MTLLoadActionLoad;
        // reshaped output: areas outside the game's 16:9 drawing (interiors, fades) start black each frame
        extern bool renderer_texture_first_write(NvnTexture *t);
        extern bool renderer_texture_level_fresh(NvnTexture *t);
        extern bool renderer_texture_frame_fresh(NvnTexture *t);
        bool fresh = renderer_texture_level_fresh(t) | renderer_texture_frame_fresh(t);
        if (renderer_texture_first_write(t) || fresh) {
            rp.colorAttachments[i].loadAction = MTLLoadActionClear;
            rp.colorAttachments[i].clearColor = MTLClearColorMake(0, 0, 0, fresh ? 0 : 1);
        }
        rp.colorAttachments[i].storeAction = MTLStoreActionStore;
        if (!w) renderer_texture_scale(t, &pass_sx, &pass_sy);
        w = (int)tex.width; h = (int)tex.height;
    }
    if (st.rt.depth) {
        renderer_mark_gpu_owned(st.rt.depth);
        id<MTLTexture> tex = view_texture(st.rt.depth, &st.rt.dview, st.rt.has_dview, true, nil);
        if (renderer_format_is_depth(st.rt.depth->format) && st.rt.depth->format != 0x31) {
            rp.depthAttachment.texture = tex;
            rp.depthAttachment.loadAction = MTLLoadActionLoad;
            rp.depthAttachment.storeAction = MTLStoreActionStore;
        }
        if (renderer_format_has_stencil(st.rt.depth->format)) {
            rp.stencilAttachment.texture = tex;
            rp.stencilAttachment.loadAction = MTLLoadActionLoad;
            rp.stencilAttachment.storeAction = MTLStoreActionStore;
        }
        if (!w) { renderer_texture_scale(st.rt.depth, &pass_sx, &pass_sy); w = (int)tex.width; h = (int)tex.height; }
    }
    if (!w) {
        pass_sx = pass_sy = 1;
        rp.renderTargetWidth = 16; rp.renderTargetHeight = 16;
        rp.defaultRasterSampleCount = 1;
    }
    // Commit the frame in chunks: the GPU starts on the first passes while the CPU still encodes the rest. The
    // game waits for its previous frame before it submits the next one, so with one command buffer per frame the
    // GPU sat idle during our encoding and a frame cost GPU + encoding time (5120x1440 with the GPU clocked down:
    // ~15.5 + a few ms -> missed vsync -> 30 fps). BDSP_CHUNK_PASSES=<n> (0 = one buffer per frame).
    static int chunk = -1;
    if (chunk < 0) { const char *e = ENV("BDSP_CHUNK_PASSES"); chunk = e ? atoi(e) : 8; }
    if (chunk > 0 && cmdbuf && ++g_passes_in_cb >= chunk) renderer_submit();
    pt_attach_render(rp);
    enc = [cb() renderCommandEncoderWithDescriptor:rp];
    pt_name_encoder(enc);
    vp_sx = pass_sx; vp_sy = pass_sy; vp_ox = 0; vp_oy = 0;
    stat_passes++;
}

// Physical size of the current pass (guest size times the attachments' allocation scale).
static void pass_size(int *w, int *h) {
    *w = *h = 0;
    for (int i = 0; i < st.rt.ncolor && !*w; i++)
        if (st.rt.color[i]) { *w = (int)st.rt.color[i]->width; *h = (int)st.rt.color[i]->height; }
    if (!*w && st.rt.depth) { *w = (int)st.rt.depth->width; *h = (int)st.rt.depth->height; }
    *w = (int)lroundf(*w * pass_sx);
    *h = (int)lroundf(*h * pass_sy);
}

static void apply_scissor(void) {
    int w, h;
    pass_size(&w, &h);
    if (!w) return;
    int x = st.scissor[0][0], y = st.scissor[0][1], sw = st.scissor[0][2], sh = st.scissor[0][3];
    if (vp_sx != 1 || vp_sy != 1 || vp_ox != 0 || vp_oy != 0) {
        double x0 = floor(x * (double)vp_sx + vp_ox), y0 = floor(y * (double)vp_sy + vp_oy);
        double x1 = ceil(((double)x + sw) * vp_sx + vp_ox), y1 = ceil(((double)y + sh) * vp_sy + vp_oy);
        if (sw >= 16384) x1 = 1e9;  // "unbounded" scissors stay unbounded
        if (sh >= 16384) y1 = 1e9;
        if (x1 > 1e9) x1 = 1e9;
        if (y1 > 1e9) y1 = 1e9;
        x = (int)x0; y = (int)y0; sw = (int)(x1 - x0); sh = (int)(y1 - y0);
    }
    if (x < 0) { sw += x; x = 0; }
    if (y < 0) { sh += y; y = 0; }
    if (x >= w || y >= h) { x = y = 0; sw = sh = 0; }
    if (x + sw > w) sw = w - x;
    if (y + sh > h) sh = h - y;
    if (sw < 0) sw = 0;
    if (sh < 0) sh = 0;
    [enc setScissorRect:(MTLScissorRect){(NSUInteger)x, (NSUInteger)y, (NSUInteger)sw, (NSUInteger)sh}];
}

// ------------------------------------------------------------------ clears (full-screen triangle)
static const char *clear_src =
    "#include <metal_stdlib>\nusing namespace metal;\n"
    "struct V { float4 pos [[position]]; };\n"
    "vertex V vs(uint vid [[vertex_id]], constant float4 &d [[buffer(0)]]) {\n"
    "  float2 p = float2((vid << 1) & 2, vid & 2); V o; o.pos = float4(p * 2.0 - 1.0, d.x, 1); return o; }\n"
    "struct OF { float4 c [[color(INDEX)]]; };\n"
    "fragment OF fs_f(V in [[stage_in]], constant float4 &c [[buffer(0)]]) { OF o; o.c = c; return o; }\n"
    "struct OI { int4 c [[color(INDEX)]]; };\n"
    "fragment OI fs_i(V in [[stage_in]], constant int4 &c [[buffer(0)]]) { OI o; o.c = c; return o; }\n"
    "struct OU { uint4 c [[color(INDEX)]]; };\n"
    "fragment OU fs_u(V in [[stage_in]], constant uint4 &c [[buffer(0)]]) { OU o; o.c = c; return o; }\n"
    "fragment void fs_none(V in [[stage_in]]) {}\n";

static id<MTLLibrary> clear_lib(int index) {
    static id<MTLLibrary> libs[8];
    if (!libs[index]) {
        NSString *src = [@(clear_src) stringByReplacingOccurrencesOfString:@"INDEX" withString:[NSString stringWithFormat:@"%d", index]];
        NSError *err;
        libs[index] = TIMED_COMPILE([dev newLibraryWithSource:src options:nil error:&err]);
        if (!libs[index]) FATAL("clear shader: %s\n", err.localizedDescription.UTF8String);
    }
    return libs[index];
}

// Sample count of the current pass (pipelines must match it): the colour attachments', else the depth attachment's.
static uint32_t pass_samples(void) {
    for (int i = 0; i < st.rt.ncolor; i++)
        if (st.rt.color[i] && st.rt.color[i]->samples > 1) return st.rt.color[i]->samples;
    return st.rt.depth && st.rt.depth->samples > 1 ? st.rt.depth->samples : 1;
}

static void attachment_formats(MTLRenderPipelineDescriptor *pd) {
    for (int i = 0; i < st.rt.ncolor; i++)
        if (st.rt.color[i]) pd.colorAttachments[i].pixelFormat = view_texture(st.rt.color[i], &st.rt.cview[i], st.rt.has_cview[i], true, nil).pixelFormat;
    if (st.rt.depth) {
        MTLPixelFormat pf = renderer_pixel_format(st.rt.depth->format);
        if (renderer_format_is_depth(st.rt.depth->format) && st.rt.depth->format != 0x31) pd.depthAttachmentPixelFormat = pf;
        if (renderer_format_has_stencil(st.rt.depth->format)) pd.stencilAttachmentPixelFormat = pf;
    }
    pd.rasterSampleCount = pass_samples();
}

static void clear(int index, int kind, const void *color, uint32_t mask, bool depth, float dval, bool stencil,
                  uint32_t sval, uint32_t smask) {
    begin_pass();
    if (g_debug_frame) {
        int pw, ph;
        pass_size(&pw, &ph);
        LOG("[clear] pass %d idx %d depth %d (%g) stencil %d | pass %dx%d scissor %d,%d %dx%d\n", debug_pass_no, index, depth,
            dval, stencil, pw, ph, st.scissor[0][0], st.scissor[0][1], st.scissor[0][2], st.scissor[0][3]);
    }
    MTLRenderPipelineDescriptor *pd = [MTLRenderPipelineDescriptor new];
    id<MTLLibrary> lib = clear_lib(index < 0 ? 0 : index);
    pd.vertexFunction = [lib newFunctionWithName:@"vs"];
    static NSString *const fs[] = {@"fs_f", @"fs_i", @"fs_u"};
    pd.fragmentFunction = [lib newFunctionWithName:index >= 0 ? fs[kind] : @"fs_none"];
    attachment_formats(pd);
    for (int i = 0; i < 8; i++) pd.colorAttachments[i].writeMask = MTLColorWriteMaskNone;
    if (index >= 0) {
        MTLColorWriteMask m = 0;
        if (mask & 1) m |= MTLColorWriteMaskRed;
        if (mask & 2) m |= MTLColorWriteMaskGreen;
        if (mask & 4) m |= MTLColorWriteMaskBlue;
        if (mask & 8) m |= MTLColorWriteMaskAlpha;
        pd.colorAttachments[index].writeMask = m;
    }
    NSError *err;
    NSString *key = [NSString stringWithFormat:@"clear %d %d %u %d %d %lu %lu %lu %lu", index, kind, mask, depth, stencil,
                     (unsigned long)pd.colorAttachments[index < 0 ? 0 : index].pixelFormat,
                     (unsigned long)pd.depthAttachmentPixelFormat, (unsigned long)pd.stencilAttachmentPixelFormat,
                     (unsigned long)pd.rasterSampleCount];  // (the sample count must match the pass: 4x MSAA passes need their own pipelines)
    id<MTLRenderPipelineState> pipe = cache[key];
    if (!pipe) {
        pipe = TIMED_COMPILE([dev newRenderPipelineStateWithDescriptor:pd error:&err]);
        if (!pipe) { LOG("[metal] clear pipeline: %s\n", err.localizedDescription.UTF8String); return; }
        cache[key] = pipe;
    }
    MTLDepthStencilDescriptor *dd = [MTLDepthStencilDescriptor new];
    dd.depthCompareFunction = MTLCompareFunctionAlways;
    dd.depthWriteEnabled = depth;
    if (stencil) {
        MTLStencilDescriptor *sd = [MTLStencilDescriptor new];
        sd.stencilCompareFunction = MTLCompareFunctionAlways;
        sd.depthStencilPassOperation = MTLStencilOperationReplace;
        sd.writeMask = smask;
        dd.frontFaceStencil = sd;
        dd.backFaceStencil = sd;
    }
    [enc setRenderPipelineState:pipe];
    [enc setDepthStencilState:[dev newDepthStencilStateWithDescriptor:dd]];
    [enc setStencilReferenceValue:sval];
    [enc setCullMode:MTLCullModeNone];
    int w, h;
    pass_size(&w, &h);
    [enc setViewport:(MTLViewport){0, 0, w, h, 0, 1}];
    vp_sx = pass_sx; vp_sy = pass_sy; vp_ox = 0; vp_oy = 0;
    apply_scissor();
    float d4[4] = {dval, 0, 0, 0};
    [enc setVertexBytes:d4 length:16 atIndex:0];
    if (index >= 0) [enc setFragmentBytes:color length:16 atIndex:0];
    [enc drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];
}

// ------------------------------------------------------------------ shaders (debug dump)
static void dump_program(NvnProgram *p) {
    if (!getenv("BDSP_DUMP_SHADERS")) return;
    static int n;
    mkdir("build/shaders", 0755);
    for (int s = 0; s < 6; s++) {
        if (!(p->stage_mask & (1u << s))) continue;
        char path[256];
        snprintf(path, sizeof path, "build/shaders/%llx_s%d_code.bin", p->stages[s].code_addr, s);
        FILE *f = fopen(path, "wb");
        fwrite((void *)(uintptr_t)p->stages[s].code_addr, 1, 0x10000, f);
        fclose(f);
        snprintf(path, sizeof path, "build/shaders/%llx_s%d_ctrl.bin", p->stages[s].code_addr, s);
        f = fopen(path, "wb");
        fwrite(p->stages[s].control, 1, 0x4000, f);
        fclose(f);
    }
    n++;
}

// ------------------------------------------------------------------ draw support
uint32_t nvn_window_origin(void);
uint32_t nvn_depth_mode(void);
static int cbuf_base = 3, tex_base = 8;

@interface Prog : NSObject {
@public
    id<MTLFunction> vs, fs;
    ShaderInfo *vi, *fi;
    bool failed;
    bool ready;
    uint64_t vh, fh;     // fnv64 of the MSL sources (names of the pre-compiled libraries)
}
@end
@implementation Prog
@end

static id<MTLBuffer> ring;
static uint64_t ring_off;
#define RING_POOL_CAP 12
// BDSP_RING_MB (default 64, 16 on devices with less than 5 GiB of RAM) sizes a ring, BDSP_RING_POOL (default 12, 4 on those devices,
// 0 = no reuse) bounds the retired ones kept for reuse
static bool small_ram_device(void) {
    static int v = -1;
    if (v < 0) { uint64_t ram = 0; size_t len = sizeof ram; v = sysctlbyname("hw.memsize", &ram, &len, NULL, 0) == 0 && ram < (5ull << 30); }
    return v;
}
static uint64_t ring_size_mb(void) { static uint64_t v; if (!v) { const char *e = getenv("BDSP_RING_MB"); v = e && atoi(e) > 0 ? (uint64_t)atoi(e) : small_ram_device() ? 16 : 64; } return v; }
static int ring_pool_max(void) { static int v = -1; if (v < 0) { const char *e = getenv("BDSP_RING_POOL"); v = e && atoi(e) > 0 ? (atoi(e) < RING_POOL_CAP ? atoi(e) : RING_POOL_CAP) : small_ram_device() ? 4 : RING_POOL_CAP; } return v; }
#define RING_SIZE (ring_size_mb() << 20)
#define RING_POOL_MAX ring_pool_max()
static struct { id<MTLBuffer> buf; uint64_t seq; } ring_retired[RING_POOL_CAP];  // seq: last command buffer that may read it
static int ring_nretired;

static uint64_t ring_alloc_skip(const void *data, uint64_t size, uint64_t skip);
static uint64_t ring_alloc(const void *data, uint64_t size) { return ring_alloc_skip(data, size, 0); }
// Reserves `size` bytes but copies only [skip, size): the caller reads nothing below `skip`.
static uint64_t ring_alloc_skip(const void *data, uint64_t size, uint64_t skip) {
    stat_ring_bytes[ring_site] += size - skip; stat_ring_n[ring_site]++; ring_site = 0;
    if (!ring) ring = [dev newBufferWithLength:RING_SIZE options:MTLResourceStorageModeShared];
    uint64_t aligned = (ring_off + 255) & ~255ull;
    if (aligned + size > RING_SIZE) {
        // Start a fresh ring; command buffers in flight keep the old one alive until they complete. A fresh 64 MB buffer
        // costs the kernel zeroing and page faults (~25 per second here), so a retired ring is reused once the last
        // command buffer that could read it has completed (BDSP_RING_POOL=0: always allocate).
        static int pool_on = -1;
        if (pool_on < 0) pool_on = !(getenv("BDSP_RING_POOL") && !strcmp(getenv("BDSP_RING_POOL"), "0"));
        pthread_mutex_lock(&cb_lock);
        uint64_t pend = submit_seq + (cmdbuf ? 1 : 0), done_to = submit_seq;
        pthread_mutex_unlock(&cb_lock);
        if (pool_on && ring.length == RING_SIZE) {
            if (ring_nretired == RING_POOL_MAX) {  // pool full: let the oldest go (freed when its command buffers finish)
                for (int i = 1; i < ring_nretired; i++) ring_retired[i - 1] = ring_retired[i];
                ring_retired[--ring_nretired].buf = nil;
            }
            ring_retired[ring_nretired].buf = ring; ring_retired[ring_nretired].seq = pend; ring_nretired++;
        }
        id<MTLBuffer> reuse = nil;
        for (int i = 0; i < ring_nretired && !reuse; i++) {
            uint64_t q = ring_retired[i].seq;
            bool done = q <= done_to && (done_to - q >= CB_HIST || cb_hist[q % CB_HIST].status >= MTLCommandBufferStatusCompleted);
            if (!done) continue;
            reuse = ring_retired[i].buf;
            for (int k = i + 1; k < ring_nretired; k++) ring_retired[k - 1] = ring_retired[k];
            ring_retired[--ring_nretired].buf = nil;
        }
        ring = reuse ?: [dev newBufferWithLength:(size > RING_SIZE ? size : RING_SIZE) options:MTLResourceStorageModeShared];
        aligned = 0;
    }
    memcpy((uint8_t *)ring.contents + aligned + skip, (const uint8_t *)data + skip, size - skip);
    ring_off = aligned + size;
    return aligned;
}

static void ring_reset(void) { ring_off = 0; }

// Bind guest memory [addr, addr+size) as a buffer: zero-copy inside the heap, copied otherwise.
// BDSP_NO_GUEST_BUFFER=1 (experiment): the GPU never sees the buffer over guest memory. On the iPhone the first command buffer that
// uses it wires the whole range (about 1.5 GiB), which the system cannot compress; skinned meshes and gmem shaders then draw wrong.
static id<MTLBuffer> gpu_guest_buffer(void) {
    static int off = -1;
    if (off < 0) off = getenv("BDSP_NO_GUEST_BUFFER") != NULL;
    return off ? nil : g_guest_buffer;
}
static bool guest_heap_ok(uint64_t addr, uint64_t size) {
    static int off = -1;  // default: copy data through the ring; BDSP_GUEST_BUF=1 uses the wrapped guest memory (see docs/rendering.md: the GPU saw old pages there)
    if (off < 0) off = getenv("BDSP_GUEST_BUF") == NULL;
    return !off && !arena_on() && addr >= HEAP_BASE && addr + size <= HEAP_BASE + HEAP_MAX;
}

// ------------------------------------------------------------------ GPU memory arena (BDSP_GMEM_ARENA=1)
// Shaders reach storage buffers (and compute's extra uniform buffers) through global memory: an address from the driver
// constants, minus maxwell_gmem_base, indexes the buffer bound at GMEM_BUFFER_INDEX. Without the arena that buffer is the
// Metal buffer over the whole guest heap, which iOS wires on first use (about 1.5 GiB on the iPhone: the compressor can no
// longer touch it and the system thrashes). With the arena each draw and dispatch gets copies of exactly the ranges it binds in
// a small shared buffer, and the driver constants point there. Ranges a shader may write are written back once the GPU ran them,
// only the words that differ from the copy taken before (CPU writes elsewhere in the range survive, as on the hardware). A range
// the GPU wrote that is not written back yet is reused by later work, so GPU-to-GPU chains (skinning, then drawing the skinned
// vertices) stay on the GPU.
#define ARENA_SIZE (16ull << 20)
#define ARENA_VA 0x7e0000000000ull   // where the arena sits in the shaders' address space (far from any guest memory)
#define ARENA_POOL 8
#define ARENA_ENT 2048
#define ARENA_UNSUBMITTED UINT64_MAX
// A written range awaiting write-back. seq: the submission that contains the work (ARENA_UNSUBMITTED until it is committed);
// encoded: the work is in the open command buffer (begin_pass may commit the buffer between mapping and encoding).
typedef struct { uint64_t guest, size, off, seq; bool encoded; id<MTLBuffer> buf; uint8_t *snap; } ArenaEnt;
static pthread_mutex_t arena_lock = PTHREAD_MUTEX_INITIALIZER;
static id<MTLBuffer> arena_cur;
static uint64_t arena_off, arena_cur_last;   // fill level of arena_cur, newest submission that may use it
static struct { id<MTLBuffer> buf; uint64_t last; } arena_old[ARENA_POOL];
static int arena_nold;
static ArenaEnt arena_ent[ARENA_ENT];
static int arena_nent;
static uint64_t arena_done;   // submissions up to this one have completed and are written back

// BDSP_GMEM_ARENA=0/1; default on for devices with less than 5 GiB of RAM (the iPhone), off elsewhere
static bool arena_on(void) {
    static int on = -1;
    if (on < 0) { const char *e = getenv("BDSP_GMEM_ARENA"); on = e && *e ? atoi(e) > 0 : small_ram_device(); }
    return on;
}

// (arena_lock held) Write back the ranges of submissions up to `seq`.
static void arena_writeback_locked(uint64_t seq) {
    int w = 0;
    for (int i = 0; i < arena_nent; i++) {
        ArenaEnt *e = &arena_ent[i];
        if (e->seq > seq) { if (w != i) arena_ent[w] = *e; w++; continue; }
        const uint8_t *a = (const uint8_t *)e->buf.contents + e->off, *s = e->snap;
        uint8_t *g = (uint8_t *)GA(e->guest);
        uint64_t k = 0;
        if (!((uintptr_t)g & 3))
            for (; k + 4 <= e->size; k += 4)
                if (*(const uint32_t *)(a + k) != *(const uint32_t *)(s + k)) { *(uint32_t *)(g + k) = *(const uint32_t *)(a + k); stat_arena_wb += 4; }
        for (; k < e->size; k++) if (a[k] != s[k]) { g[k] = a[k]; stat_arena_wb++; }
        static int ndbg;
        if (getenv("BDSP_ARENA_LOG") && ndbg++ < 40) {
            uint64_t nz = 0;
            for (uint64_t j = 0; j < e->size; j++) nz += a[j] != 0;
            LOG("[arena] write-back %llx/%llu seq %llu: %llu nonzero bytes in the GPU result\n", (unsigned long long)e->guest,
                (unsigned long long)e->size, (unsigned long long)e->seq, (unsigned long long)nz);
        }
        free(e->snap);
        e->snap = NULL;
    }
    for (int i = w; i < arena_nent; i++) { arena_ent[i].buf = nil; arena_ent[i].snap = NULL; }
    arena_nent = w;
    if (seq > arena_done) arena_done = seq;
}

static void arena_writeback_upto(uint64_t seq) {
    if (!arena_on()) return;
    pthread_mutex_lock(&arena_lock);
    arena_writeback_locked(seq);
    pthread_mutex_unlock(&arena_lock);
}

// The open command buffer is committed as submission `seq`: the ranges encoded into it belong to it.
static void arena_assign(uint64_t seq) {
    if (!arena_on()) return;
    pthread_mutex_lock(&arena_lock);
    for (int i = 0; i < arena_nent; i++)
        if (arena_ent[i].seq == ARENA_UNSUBMITTED && arena_ent[i].encoded) arena_ent[i].seq = seq;
    pthread_mutex_unlock(&arena_lock);
}

// The draw or dispatch the last arena_map was for is now in the open command buffer.
static void arena_mark_encoded(void) {
    if (!arena_on()) return;
    pthread_mutex_lock(&arena_lock);
    for (int i = 0; i < arena_nent; i++) if (arena_ent[i].seq == ARENA_UNSUBMITTED) arena_ent[i].encoded = true;
    pthread_mutex_unlock(&arena_lock);
}

// (arena_lock held) Index of the written range that contains [a, a+s); -2 if one overlaps without containing it, -1 if none.
static int arena_find(uint64_t a, uint64_t s) {
    for (int i = arena_nent - 1; i >= 0; i--) {
        const ArenaEnt *e = &arena_ent[i];
        if (a < e->guest + e->size && a + s > e->guest) return a >= e->guest && a + s <= e->guest + e->size ? i : -2;
    }
    return -1;
}

// True if the GPU may still write into [a, a+s): the CPU must not read or write it before a flush.
static bool arena_pending(uint64_t a, uint64_t s) {
    if (!arena_on()) return false;
    pthread_mutex_lock(&arena_lock);
    bool p = arena_find(a, s) != -1;
    pthread_mutex_unlock(&arena_lock);
    return p;
}

// (arena_lock held) Continue in a fresh arena buffer: a retired one the GPU is done with, or a new one.
static void arena_rotate_locked(void) {
    if (arena_cur) {
        if (arena_nold == ARENA_POOL) {  // (pending ranges and command buffers keep their buffers alive)
            for (int i = 1; i < arena_nold; i++) arena_old[i - 1] = arena_old[i];
            arena_old[--arena_nold].buf = nil;
        }
        arena_old[arena_nold].buf = arena_cur; arena_old[arena_nold].last = arena_cur_last; arena_nold++;
    }
    id<MTLBuffer> b = nil;
    for (int i = 0; i < arena_nold; i++)
        if (arena_old[i].last <= arena_done) {
            b = arena_old[i].buf;
            for (int k = i + 1; k < arena_nold; k++) arena_old[k - 1] = arena_old[k];
            arena_old[--arena_nold].buf = nil;
            break;
        }
    arena_cur = b ?: [dev newBufferWithLength:ARENA_SIZE options:MTLResourceStorageModeShared];
    arena_off = 0;
}

// Maps the ranges of ng binding tables (r[g][0..n[g]-1]; bit i of wmask[g]: the shader may write range i) into the arena and
// returns their arena addresses in va[g][i] (0 for an empty range) and the buffer to bind for table g in buf[g]. May flush, so
// call it before a render pass is opened.
static void arena_map(int ng, const Range *const r[], const int n[], const uint32_t wmask[], uint64_t *const va[],
                      __strong id<MTLBuffer> buf[]) {
    for (int attempt = 0;; attempt++) {
        pthread_mutex_lock(&arena_lock);
        bool conflict = false, reuse = false;
        uint64_t need = 0;
        int nwrite = 0;
        for (int g = 0; g < ng; g++)
            for (int i = 0; i < n[g]; i++) {
                uint64_t a = r[g][i].addr, s = r[g][i].size;
                if (!a || !s) continue;
                int f = arena_find(a, s);
                if (f == -2 || (f >= 0 && arena_ent[f].buf != arena_cur)) conflict = true;
                else if (f >= 0) reuse = true;
                else { need += (s + 255) & ~255ull; nwrite += (wmask[g] >> i) & 1; }
            }
        bool full = !arena_cur || arena_off + need > ARENA_SIZE;
        static int dbg = -1, ndbg;   // BDSP_ARENA_LOG=<n> (diagnostics): log the first n mappings
        if (dbg < 0) dbg = getenv("BDSP_ARENA_LOG") ? atoi(getenv("BDSP_ARENA_LOG")) : 0;
        if (attempt == 0 && ndbg < dbg) {
            ndbg++;
            LOG("[arena] map:");
            for (int g = 0; g < ng; g++)
                for (int i = 0; i < n[g]; i++)
                    if (r[g][i].addr && r[g][i].size)
                        LOG(" %d.%d=%llx/%llu%s%s", g, i, (unsigned long long)r[g][i].addr, (unsigned long long)r[g][i].size,
                            (wmask[g] >> i) & 1 ? "w" : "", arena_find(r[g][i].addr, r[g][i].size) >= 0 ? "(reuse)" : "");
            LOG(" | entries %d conflict %d\n", arena_nent, conflict);
        }
        if (attempt == 0 && (conflict || (reuse && full) || arena_nent + nwrite > ARENA_ENT)) {
            // a range the GPU wrote lies in another arena buffer (or only partly matches): write everything back, then copy afresh
            pthread_mutex_unlock(&arena_lock);
            stat_arena_flushes++;
            flush_why(FL_ARENA);
            continue;
        }
        if (full) arena_rotate_locked();
        for (int g = 0; g < ng; g++) {
            buf[g] = arena_cur;
            for (int i = 0; i < n[g]; i++) {
                uint64_t a = r[g][i].addr, s = r[g][i].size;
                va[g][i] = 0;
                if (!a || !s) continue;
                int f = arena_find(a, s);
                if (f >= 0 && arena_ent[f].buf == arena_cur) {
                    va[g][i] = ARENA_VA + arena_ent[f].off + (a - arena_ent[f].guest);
                    stat_arena_reuse++;
                    continue;
                }
                uint64_t off = (arena_off + 255) & ~255ull;
                if (off + s > ARENA_SIZE) {  // (larger than the arena: the shader reads zeros)
                    static int nlog;
                    if (nlog++ < 10) LOG("[arena] no room for %llx + %llu\n", (unsigned long long)a, (unsigned long long)s);
                    continue;
                }
                memcpy((uint8_t *)arena_cur.contents + off, (const void *)GA(a), s);
                arena_off = off + s;
                stat_arena_bytes += s;
                stat_arena_n++;
                va[g][i] = ARENA_VA + off;
                if (((wmask[g] >> i) & 1) && arena_nent < ARENA_ENT) {
                    ArenaEnt *e = &arena_ent[arena_nent++];
                    e->guest = a; e->size = s; e->off = off; e->seq = ARENA_UNSUBMITTED; e->encoded = false; e->buf = arena_cur;
                    e->snap = malloc(s);
                    memcpy(e->snap, (uint8_t *)arena_cur.contents + off, s);
                }
            }
        }
        arena_cur_last = submit_seq + 2;  // (the work lands in the open command buffer or, after a chunked commit, the next one)
        pthread_mutex_unlock(&arena_lock);
        return;
    }
}

// The draw being encoded: arena addresses of the vertex (0) and fragment (1) storage buffers and the buffers to bind for them.
static uint64_t arena_va_draw[2][16];
static id<MTLBuffer> arena_buf_draw[2];

// Of the vertex streams in `mask` (they overlap ranges a pending dispatch uses): those the GPU wrote into the arena, with the
// buffer and offset to bind them from. Streams the GPU did not write are current in guest memory and are copied as usual.
// A stream that only partly matches a written range is flushed (written back) first, then all are copied.
static uint32_t arena_streams(uint32_t mask, __strong id<MTLBuffer> buf[12], uint64_t off[12]) {
    uint32_t out = 0;
    bool conflict = false;
    pthread_mutex_lock(&arena_lock);
    for (int s = 0; s < 12; s++) {
        if (!(mask & (1u << s)) || !st.vbuf[s].addr) continue;
        uint64_t a = st.vbuf[s].addr, size = st.vbuf[s].size ? st.vbuf[s].size : 16;
        int f = arena_find(a, size);
        static int ndbg;
        if (getenv("BDSP_ARENA_LOG") && ndbg++ < 40) LOG("[arena] stream %d %llx/%llu: %d\n", s, (unsigned long long)a, (unsigned long long)size, f);
        if (f == -2) { conflict = true; break; }
        if (f < 0) continue;
        uint64_t o = arena_ent[f].off + (a - arena_ent[f].guest);
        if (o & 3) { conflict = true; break; }
        buf[s] = arena_ent[f].buf;
        off[s] = o;
        out |= 1u << s;
    }
    pthread_mutex_unlock(&arena_lock);
    if (conflict) {
        flush_why(FL_HAZARD);
        for (int s = 0; s < 12; s++) buf[s] = nil;
        return 0;
    }
    return out;
}

// The vertex range [*lo, *hi] (before the stream stride) a draw reads, so only that part of a stream is copied;
// false if it can't be told. Indices equal to the primitive-restart value are skipped.
static bool draw_vertex_range(const CmdRec *r, bool indexed, uint64_t *lo, uint64_t *hi) {
    if (!indexed) {
        uint64_t first = (uint32_t)r->x[1], count = (uint32_t)r->x[2];
        if (!count) return false;
        *lo = first; *hi = first + count - 1;
        return true;
    }
    uint32_t itype = (uint32_t)r->x[1], count = (uint32_t)r->x[2];
    const void *p = (const void *)(uintptr_t)r->x[3];
    int64_t base = (int32_t)r->x[4];
    if (!count || !p) return false;
    uint32_t mn = UINT32_MAX, mx = 0;
    // branch-free (vectorizes): a restart value counts as the neutral element of min and of max
#define SCAN_RANGE(T, RESTART) do { const T *q = p; \
        for (uint32_t i = 0; i < count; i++) { uint32_t v = q[i]; uint32_t lo_v = v == (RESTART) ? UINT32_MAX : v, hi_v = v == (RESTART) ? 0 : v; \
            mn = lo_v < mn ? lo_v : mn; mx = hi_v > mx ? hi_v : mx; } } while (0)
    if (itype == 0) SCAN_RANGE(uint8_t, 0xFF);
    else if (itype == 1) SCAN_RANGE(uint16_t, 0xFFFF);
    else SCAN_RANGE(uint32_t, 0xFFFFFFFFu);
#undef SCAN_RANGE
    if (mn > mx) return false;
    int64_t l = (int64_t)mn + base, h = (int64_t)mx + base;
    if (l < 0) l = 0;
    if (h < l) return false;
    *lo = (uint64_t)l; *hi = (uint64_t)h;
    return true;
}

static void bind_guest(id<MTLRenderCommandEncoder> e, bool vertex_stage, uint64_t addr, uint64_t size, int index, uint64_t skip) {
    if (guest_heap_ok(addr, size) && (addr & 3) == 0) {
        if (vertex_stage) [e setVertexBuffer:g_guest_buffer offset:addr - HEAP_BASE atIndex:index];
        else [e setFragmentBuffer:g_guest_buffer offset:addr - HEAP_BASE atIndex:index];
        return;
    }
    ring_site = 1;
    uint64_t off = ring_alloc_skip((void *)(uintptr_t)addr, size, skip < size ? skip : 0);
    if (vertex_stage) [e setVertexBuffer:ring offset:off atIndex:index];
    else [e setFragmentBuffer:ring offset:off atIndex:index];
}

static int attr_kind(uint32_t fmt) {
    switch (fmt) {
    case 0x03: case 0x08: case 0x0B: case 0x0F: case 0x14: case 0x17: case 0x1B: case 0x20: case 0x23:
    case 0x27: case 0x2C: case 0x2F: case 0x3E:
        return 2;
    case 0x04: case 0x09: case 0x0C: case 0x10: case 0x15: case 0x18: case 0x1C: case 0x21: case 0x24:
    case 0x28: case 0x2D: case 0x30:
        return 1;
    default: return 0;
    }
}

static MTLVertexFormat vertex_format(uint32_t f) {
    switch (f) {
    case 0x01: return MTLVertexFormatUCharNormalized;
    case 0x02: return MTLVertexFormatCharNormalized;
    case 0x03: return MTLVertexFormatUChar;
    case 0x04: return MTLVertexFormatChar;
    case 0x05: return MTLVertexFormatHalf;
    case 0x06: return MTLVertexFormatUShortNormalized;
    case 0x07: return MTLVertexFormatShortNormalized;
    case 0x08: return MTLVertexFormatUShort;
    case 0x09: return MTLVertexFormatShort;
    case 0x0A: return MTLVertexFormatFloat;
    case 0x0B: return MTLVertexFormatUInt;
    case 0x0C: return MTLVertexFormatInt;
    case 0x0D: return MTLVertexFormatUChar2Normalized;
    case 0x0E: return MTLVertexFormatChar2Normalized;
    case 0x0F: return MTLVertexFormatUChar2;
    case 0x10: return MTLVertexFormatChar2;
    case 0x11: return MTLVertexFormatHalf2;
    case 0x12: return MTLVertexFormatUShort2Normalized;
    case 0x13: return MTLVertexFormatShort2Normalized;
    case 0x14: return MTLVertexFormatUShort2;
    case 0x15: return MTLVertexFormatShort2;
    case 0x16: return MTLVertexFormatFloat2;
    case 0x17: return MTLVertexFormatUInt2;
    case 0x18: return MTLVertexFormatInt2;
    case 0x19: return MTLVertexFormatUChar3Normalized;
    case 0x1A: return MTLVertexFormatChar3Normalized;
    case 0x1B: return MTLVertexFormatUChar3;
    case 0x1C: return MTLVertexFormatChar3;
    case 0x1D: return MTLVertexFormatHalf3;
    case 0x1E: return MTLVertexFormatUShort3Normalized;
    case 0x1F: return MTLVertexFormatShort3Normalized;
    case 0x20: return MTLVertexFormatUShort3;
    case 0x21: return MTLVertexFormatShort3;
    case 0x22: return MTLVertexFormatFloat3;
    case 0x23: return MTLVertexFormatUInt3;
    case 0x24: return MTLVertexFormatInt3;
    case 0x25: return MTLVertexFormatUChar4Normalized;
    case 0x26: return MTLVertexFormatChar4Normalized;
    case 0x27: return MTLVertexFormatUChar4;
    case 0x28: return MTLVertexFormatChar4;
    case 0x29: return MTLVertexFormatHalf4;
    case 0x2A: return MTLVertexFormatUShort4Normalized;
    case 0x2B: return MTLVertexFormatShort4Normalized;
    case 0x2C: return MTLVertexFormatUShort4;
    case 0x2D: return MTLVertexFormatShort4;
    case 0x2E: return MTLVertexFormatFloat4;
    case 0x2F: return MTLVertexFormatUInt4;
    case 0x30: return MTLVertexFormatInt4;
    case 0x3D: return MTLVertexFormatUInt1010102Normalized;
    case 0x69: return MTLVertexFormatInt1010102Normalized;
    case 0x3F: return MTLVertexFormatFloatRG11B10;
    case 0x40: return MTLVertexFormatFloatRGB9E5;
    // integer-to-float ("I2F") formats: converted to float by the vertex fetch
    case 0x51: return MTLVertexFormatUChar;   // these read as raw integers converted in shader
    default:
        return MTLVertexFormatFloat4;
    }
}

static bool is_int_format(uint32_t f) { return attr_kind(f) != 0; }

static MTLBlendFactor blend_factor(uint8_t f) {
    switch (f) {
    case 1: return MTLBlendFactorZero;
    case 2: return MTLBlendFactorOne;
    case 3: return MTLBlendFactorSourceColor;
    case 4: return MTLBlendFactorOneMinusSourceColor;
    case 5: return MTLBlendFactorSourceAlpha;
    case 6: return MTLBlendFactorOneMinusSourceAlpha;
    case 7: return MTLBlendFactorDestinationAlpha;
    case 8: return MTLBlendFactorOneMinusDestinationAlpha;
    case 9: return MTLBlendFactorDestinationColor;
    case 10: return MTLBlendFactorOneMinusDestinationColor;
    case 11: return MTLBlendFactorSourceAlphaSaturated;
    case 0x10: return MTLBlendFactorSource1Color;
    case 0x11: return MTLBlendFactorOneMinusSource1Color;
    case 0x12: return MTLBlendFactorSource1Alpha;
    case 0x13: return MTLBlendFactorOneMinusSource1Alpha;
    case 0x61: return MTLBlendFactorBlendColor;
    case 0x62: return MTLBlendFactorOneMinusBlendColor;
    case 0x63: return MTLBlendFactorBlendAlpha;
    case 0x64: return MTLBlendFactorOneMinusBlendAlpha;
    default: {
        static uint8_t warned[256];
        if (!warned[f]++) LOG("[metal] unknown blend factor %#x\n", f);
        return MTLBlendFactorOne;
    }
    }
}

static MTLBlendOperation blend_op(uint8_t e) {
    switch (e) {
    case 2: return MTLBlendOperationSubtract;
    case 3: return MTLBlendOperationReverseSubtract;
    case 4: return MTLBlendOperationMin;
    case 5: return MTLBlendOperationMax;
    default: return MTLBlendOperationAdd;
    }
}

static MTLCompareFunction compare_fn(uint8_t f) {
    switch (f) {
    case 1: return MTLCompareFunctionNever;
    case 2: return MTLCompareFunctionLess;
    case 3: return MTLCompareFunctionEqual;
    case 4: return MTLCompareFunctionLessEqual;
    case 5: return MTLCompareFunctionGreater;
    case 6: return MTLCompareFunctionNotEqual;
    case 7: return MTLCompareFunctionGreaterEqual;
    default: return MTLCompareFunctionAlways;
    }
}

static MTLStencilOperation stencil_op(uint8_t o) {
    switch (o) {
    case 2: return MTLStencilOperationZero;
    case 3: return MTLStencilOperationReplace;
    case 4: return MTLStencilOperationIncrementClamp;
    case 5: return MTLStencilOperationDecrementClamp;
    case 6: return MTLStencilOperationInvert;
    case 7: return MTLStencilOperationIncrementWrap;
    case 8: return MTLStencilOperationDecrementWrap;
    default: return MTLStencilOperationKeep;
    }
}

static int rt_kind(uint32_t f) {
    switch (f) {
    case 0x03: case 0x08: case 0x0B: case 0x0F: case 0x14: case 0x17: case 0x27: case 0x2C: case 0x2F: case 0x3E: return 2;
    case 0x04: case 0x09: case 0x0C: case 0x10: case 0x15: case 0x18: case 0x28: case 0x2D: case 0x30: return 1;
    default: return 0;
    }
}

#define PROG_TAB 4096
static struct { uint64_t key; void *prog; } prog_tab[PROG_TAB];

// Compiler warnings of the shader translator (unused functions and variables) only clutter the console; they are placed
// in front of every shader source.
#define MSL_QUIET @"#pragma clang diagnostic ignored \"-Wunused-function\"\n#pragma clang diagnostic ignored \"-Wunused-variable\"\n#pragma clang diagnostic ignored \"-Wunused-but-set-variable\"\n#pragma clang diagnostic ignored \"-Wunused-label\"\n"

// Shader warm-up cache: every translated shader's MSL is kept in cache/shaders/ (v_/f_<hash>.metal). At startup
// they're all compiled once on a background queue, which fills Metal's own on-disk shader cache so that a later
// first use in-game costs ~0.1 ms instead of ~40 ms. Delete cache/ to reset it.
static uint64_t fnv64(const char *t) {
    uint64_t h = 0xcbf29ce484222325ull;
    for (; *t; t++) { h ^= (uint8_t)*t; h *= 0x100000001B3ull; }
    return h;
}

static void shader_cache_note(const char *vs, const char *fs) {
    static NSString *directory;
    static dispatch_once_t once;
    dispatch_once(&once, ^{
#ifdef BDSP_IOS
        directory = [[NSSearchPathForDirectoriesInDomains(NSCachesDirectory, NSUserDomainMask, YES) firstObject]
            stringByAppendingPathComponent:@"BDSP/shaders"];
#else
        directory = @"work/recomp/cache/shaders";
#endif
        [NSFileManager.defaultManager createDirectoryAtPath:directory withIntermediateDirectories:YES attributes:nil error:nil];
    });
    const char *src[2] = {vs, fs};
    for (int i = 0; i < 2; i++) {
        NSString *path = [directory stringByAppendingPathComponent:[NSString stringWithFormat:@"%c_%016llx.metal",
            i ? 'f' : 'v', (unsigned long long)fnv64(src[i])]];
        if (access(path.fileSystemRepresentation, F_OK) == 0) continue;
        FILE *f = fopen(path.fileSystemRepresentation, "w");
        if (f) { fputs(src[i], f); fclose(f); }
    }
}

static NSMutableDictionary *prebuilt_libs;  // path -> MTLLibrary (gate and draws share the libraries)
static NSString *prebuilt_dir_path;
static bool prebuilt_dir_looked;

static NSString *prebuilt_dir(void) {
    if (!prebuilt_dir_looked) {
        prebuilt_dir_looked = true;
        prebuilt_libs = [NSMutableDictionary new];
        NSString *b = [[NSBundle mainBundle].resourcePath stringByAppendingPathComponent:@"shaders-bin"];
        if ([[NSFileManager defaultManager] fileExistsAtPath:b]) prebuilt_dir_path = b;
        #ifndef BDSP_IOS
        else if ([[NSFileManager defaultManager] fileExistsAtPath:@"work/recomp/cache/shaders-bin-macosx"]) prebuilt_dir_path = @"work/recomp/cache/shaders-bin-macosx";
#endif
        if (getenv("BDSP_SHADER_SALT") || getenv("BDSP_NO_PREBUILT")) prebuilt_dir_path = nil;
        LOG("[shader] pre-compiled libraries: %s\n", prebuilt_dir_path ? prebuilt_dir_path.UTF8String : "none found");
    }
    return prebuilt_dir_path;
}

// Pre-compiled shader library (scripts/recomp/shader_bin.sh, folder shaders-bin in the app bundle) by hash of the
// MSL source. If the file is missing, it returns nil.
static id<MTLLibrary> prebuilt_library_hash(uint64_t h, char kind) {
    NSString *dir = prebuilt_dir();
    if (!dir) return nil;
    NSString *path = [dir stringByAppendingPathComponent:[NSString stringWithFormat:@"%c_%016llx.metallib", kind, (unsigned long long)h]];
    @synchronized(prebuilt_libs) { id l = prebuilt_libs[path]; if (l) return l; }
    if (![[NSFileManager defaultManager] fileExistsAtPath:path]) return nil;
    NSError *err = nil;
    id<MTLLibrary> lib = [dev newLibraryWithURL:[NSURL fileURLWithPath:path] error:&err];
    if (lib) @synchronized(prebuilt_libs) { prebuilt_libs[path] = lib; }
    else { static int n; if (n++ < 3) LOG("[shader] %s not loaded: %s\n", path.lastPathComponent.UTF8String, err.localizedDescription.UTF8String); }
    return lib;
}

static id<MTLLibrary> prebuilt_library(const char *msl, char kind) {
    return prebuilt_library_hash(fnv64(msl), kind);
}
// Compiler warnings of the shader translator (unused functions and variables from the translated shaders) only
// clutter the console; they are placed in front of every shader source.
#define MSL_QUIET @"#pragma clang diagnostic ignored \"-Wunused-function\"\n#pragma clang diagnostic ignored \"-Wunused-variable\"\n#pragma clang diagnostic ignored \"-Wunused-but-set-variable\"\n#pragma clang diagnostic ignored \"-Wunused-label\"\n"

static void compile_program_impl(Prog *pr) {
    NSError *err = nil;
    static MTLCompileOptions *vopts;
    static dispatch_once_t once;
    dispatch_once(&once, ^{ vopts = [MTLCompileOptions new]; vopts.preserveInvariance = YES; });
    double t0 = now_ms();
    // BDSP_SHADER_SALT=<text>: tag sources so Metal's disk cache misses (measure cold first-use compiles)
    NSString *salt = getenv("BDSP_SHADER_SALT") ? [NSString stringWithFormat:@"\n// %s\n", getenv("BDSP_SHADER_SALT")] : @"";
    id<MTLLibrary> vl = prebuilt_library(pr->vi->msl, 'v');
    BOOL vertexPrebuilt = vl != nil;
    if (!vl) vl = [dev newLibraryWithSource:[MSL_QUIET stringByAppendingString:[@(pr->vi->msl) stringByAppendingString:salt]] options:vopts error:&err];
    if (!vl) { LOG("[shader] VS compile failed: %s\n%s\n", err.localizedDescription.UTF8String, pr->vi->msl); pr->failed = true; return; }
    id<MTLLibrary> fl = prebuilt_library(pr->fi->msl, 'f');
    BOOL fragmentPrebuilt = fl != nil;
    if (!fl) fl = [dev newLibraryWithSource:[MSL_QUIET stringByAppendingString:[@(pr->fi->msl) stringByAppendingString:salt]] options:nil error:&err];
    if (!fl) { LOG("[shader] FS compile failed: %s\n%s\n", err.localizedDescription.UTF8String, pr->fi->msl); pr->failed = true; return; }
    static unsigned prebuiltStages, compiledStages;
    prebuiltStages += vertexPrebuilt + fragmentPrebuilt;
    compiledStages += !vertexPrebuilt + !fragmentPrebuilt;
    if ((prebuiltStages + compiledStages) <= 6 || (prebuiltStages + compiledStages) % 512 == 0)
        LOG("[shader] libraries loaded: %u prebuilt, %u compiled on device\n", prebuiltStages, compiledStages);
    pr->vs = [vl newFunctionWithName:@"main0"];
    pr->fs = [fl newFunctionWithName:@"main0"];
    __atomic_fetch_add(&stat_compiles, 1, __ATOMIC_RELAXED);
    double dt = now_ms() - t0;
    @synchronized(cache) { stat_compile_ms += dt; }
    pr->ready = true;
}

extern void bdsp_shader_compile_status(int active) __attribute__((weak_import));
extern void bdsp_shader_gate_status(uint64_t done, uint64_t total, int active) __attribute__((weak_import));
static void compile_program(Prog *pr) {
    if (bdsp_shader_compile_status) bdsp_shader_compile_status(1);
    @try { compile_program_impl(pr); }
    @finally { if (bdsp_shader_compile_status) bdsp_shader_compile_status(0); }
}

static void startup_gate(void);
static Prog *get_program(NvnProgram *p, ShaderKey *vkey, ShaderKey *fkey) {
    startup_gate();
    if (!(p->stage_mask & 1) || !(p->stage_mask & 2)) return nil;
    // fast path: hash of the code addresses and keys
    uint64_t h = 0xcbf29ce484222325ull;
    for (int i = 0; i < 2; i++) { uint64_t a = p->stages[i].code_addr; for (int k = 0; k < 8; k++) { h ^= (a >> (k * 8)) & 0xFF; h *= 0x100000001B3ull; } }
    const uint8_t *vb = (const uint8_t *)vkey;
    for (size_t i = 0; i < sizeof *vkey; i++) { h ^= vb[i]; h *= 0x100000001B3ull; }
    for (int i = 0; i < 8; i++) { h ^= fkey->rt_kind[i]; h *= 0x100000001B3ull; }
    if (!h) h = 1;
    uint32_t slot = (uint32_t)(h ^ (h >> 31)) & (PROG_TAB - 1);
    while (prog_tab[slot].key && prog_tab[slot].key != h) slot = (slot + 1) & (PROG_TAB - 1);
    if (prog_tab[slot].key) { Prog *fp = (__bridge Prog *)prog_tab[slot].prog; return fp->failed ? nil : fp; }
    NSString *key = [NSString stringWithFormat:@"%llx/%llx/%@/%@%s", p->stages[0].code_addr, p->stages[1].code_addr,
                     [NSData dataWithBytes:vkey length:sizeof *vkey], [NSData dataWithBytes:fkey->rt_kind length:8],
                     vkey->flip_x ? "/mirror" : ""];  // (NSData's description elides the middle of the key's bytes)
    Prog *pr = cache[key];
    if (pr) {
        prog_tab[slot].key = h;
        prog_tab[slot].prog = (__bridge void *)pr;
        return pr->failed ? nil : pr;
    }
    pr = [Prog new];
    cache[key] = pr;
    prog_tab[slot].key = h;
    prog_tab[slot].prog = (__bridge void *)pr;  // retained by the cache dictionary
    dump_program(p);
    maxwell_gmem_base = arena_on() ? ARENA_VA : HEAP_BASE;
    maxwell_gmem_size = arena_on() ? ARENA_SIZE : HEAP_MAX;
    {
        // BDSP_DBG_FS=<fs code addr hex>:<pc hex>:<reg>
        static int parsed;
        static unsigned long long dbg_addr;
        static unsigned dbg_pc;
        static int dbg_reg;
        if (!parsed) { parsed = 1; const char *e = getenv("BDSP_DBG_FS"); if (e) sscanf(e, "%llx:%x:%d", &dbg_addr, &dbg_pc, &dbg_reg); }
        maxwell_dbg_code = dbg_addr ? (const uint8_t *)(uintptr_t)dbg_addr : NULL;
        static unsigned long long dbg_vs;
        static int vparsed;
        if (!vparsed) { vparsed = 1; const char *e = getenv("BDSP_DBG_VS"); if (e) dbg_vs = strtoull(e, NULL, 16); }
        maxwell_dbg_vs = dbg_vs ? (const uint8_t *)(uintptr_t)dbg_vs : NULL;
        maxwell_dbg_pc = dbg_pc;
        maxwell_dbg_reg = dbg_reg;
    }
    // the compiler constants follow the code, so they bound the instruction scan
    size_t vmax = p->stages[0].const_offset ? p->stages[0].const_offset : 0x10000;
    size_t fmax = p->stages[1].const_offset ? p->stages[1].const_offset : 0x10000;
    pr->vi = maxwell_translate((const uint8_t *)(uintptr_t)p->stages[0].code_addr, vmax, STAGE_VERTEX, vkey);
    if (!pr->vi->msl) {
        LOG("[shader] VS translate failed: %s (code %llx)\n", pr->vi->error, p->stages[0].code_addr);
        char path[128];
        snprintf(path, sizeof path, "build/shaders/fail_%llx_s0_code.bin", p->stages[0].code_addr);
        FILE *f = fopen(path, "wb");
        if (f) { fwrite((void *)(uintptr_t)p->stages[0].code_addr, 1, 0x4000, f); fclose(f); }
        pr->failed = true;
        return nil;
    }
    fkey->vs_out_mask = pr->vi->out_mask;
    pr->fi = maxwell_translate((const uint8_t *)(uintptr_t)p->stages[1].code_addr, fmax, STAGE_FRAGMENT, fkey);
    if (!pr->fi->msl) { LOG("[shader] FS translate failed: %s\n", pr->fi->error); pr->failed = true; return nil; }
    if (getenv("BDSP_SAVE_MSL")) {
        mkdir("build/msl", 0755);
        char path[256];
        snprintf(path, sizeof path, "build/msl/%llx_vs.metal", p->stages[0].code_addr);
        FILE *f = fopen(path, "w"); fputs(pr->vi->msl, f); fclose(f);
        snprintf(path, sizeof path, "build/msl/%llx_fs.metal", p->stages[1].code_addr);
        f = fopen(path, "w"); fputs(pr->fi->msl, f); fclose(f);
    }
    shader_cache_note(pr->vi->msl, pr->fi->msl);
    pr->vh = fnv64(pr->vi->msl);
    pr->fh = fnv64(pr->fi->msl);
    compile_program(pr);
    // The sources are not needed after the libraries exist (~350 MB for the shaders of a session); keep them with BDSP_KEEP_MSL=1
    static int keep_msl = -1;
    if (keep_msl < 0) keep_msl = getenv("BDSP_KEEP_MSL") != NULL;
    if (!keep_msl) { free(pr->vi->msl); pr->vi->msl = NULL; free(pr->fi->msl); pr->fi->msl = NULL; }
    return pr->failed ? nil : pr;
}

static id<MTLSamplerState> sampler_for(NvnSamplerDesc *d) {
    if (d->backend) return (__bridge id<MTLSamplerState>)d->backend;
    MTLSamplerDescriptor *sd = [MTLSamplerDescriptor new];
    sd.magFilter = d->mag_filter == 1 ? MTLSamplerMinMagFilterLinear : MTLSamplerMinMagFilterNearest;
    uint32_t mf = d->min_filter;
    sd.minFilter = (mf == 1 || mf == 3 || mf == 5) ? MTLSamplerMinMagFilterLinear : MTLSamplerMinMagFilterNearest;
    sd.mipFilter = mf <= 1 ? MTLSamplerMipFilterNotMipmapped : (mf == 2 || mf == 3) ? MTLSamplerMipFilterNearest : MTLSamplerMipFilterLinear;
    MTLSamplerAddressMode modes[3];
    for (int i = 0; i < 3; i++) {
        switch (d->wrap[i]) {
        case 0: case 7: modes[i] = MTLSamplerAddressModeClampToEdge; break;
        case 1: modes[i] = MTLSamplerAddressModeRepeat; break;
        case 2: case 3: modes[i] = MTLSamplerAddressModeMirrorClampToEdge; break;
        case 4: case 5: modes[i] = MTLSamplerAddressModeClampToBorderColor; break;
        case 6: modes[i] = MTLSamplerAddressModeMirrorRepeat; break;
        default: modes[i] = MTLSamplerAddressModeRepeat;
        }
    }
    sd.sAddressMode = modes[0]; sd.tAddressMode = modes[1]; sd.rAddressMode = modes[2];
    sd.lodMinClamp = d->lod_min;
    sd.lodMaxClamp = d->lod_max > 1000 ? FLT_MAX : d->lod_max;
    if (d->max_aniso > 1) sd.maxAnisotropy = (NSUInteger)fminf(d->max_aniso, 16);
    if (d->lod_bias != 0 && getenv("BDSP_LOG_BIAS"))
        LOG("[sampler] lod bias %g (min filter %u, aniso %g)\n", d->lod_bias, mf, d->max_aniso);
    static float lodmin = -1;  // BDSP_LOD_MIN=<n>: skip the n sharpest mips everywhere (aliasing experiments)
    if (lodmin < 0) lodmin = getenv("BDSP_LOD_MIN") ? (float)atof(getenv("BDSP_LOD_MIN")) : 0;
    if (lodmin > 0 && mf > 1) sd.lodMinClamp = fmaxf(sd.lodMinClamp, lodmin);
    static int stest = -1;  // BDSP_SAMPLER_TEST: full mip range + 16x aniso on mipmapped samplers (moire test)
    if (stest < 0) stest = getenv("BDSP_SAMPLER_TEST") != NULL;
    if (stest && mf > 1) { sd.lodMinClamp = 0; sd.lodMaxClamp = FLT_MAX; sd.maxAnisotropy = 16; }
    if (getenv("BDSP_LOG_SAMPLERS"))
        LOG("[sampler] min %u mag %u lod %g..%g aniso %g wrap %u %u\n", mf, d->mag_filter, d->lod_min, d->lod_max, d->max_aniso,
            d->wrap[0], d->wrap[1]);
    if (d->compare_mode) sd.compareFunction = getenv("BDSP_NO_SHADOW") ? MTLCompareFunctionAlways : compare_fn((uint8_t)d->compare_func);
    sd.supportArgumentBuffers = NO;
    id<MTLSamplerState> s = [dev newSamplerStateWithDescriptor:sd];
    d->backend = (void *)CFBridgingRetain(s);
    return s;
}

static id<MTLSamplerState> default_sampler(void) {
    static id<MTLSamplerState> s;
    if (!s) {
        MTLSamplerDescriptor *sd = [MTLSamplerDescriptor new];
        sd.minFilter = sd.magFilter = MTLSamplerMinMagFilterLinear;
        s = [dev newSamplerStateWithDescriptor:sd];
    }
    return s;
}

static id<MTLTexture> dummy_texture(int type) {
    static id<MTLTexture> t[10];
    if (!t[type]) {
        MTLTextureDescriptor *d = [MTLTextureDescriptor new];
        d.pixelFormat = MTLPixelFormatRGBA8Unorm;
        d.width = d.height = 1;
        d.textureType = type == TEXTYPE_CUBE ? MTLTextureTypeCube : type == TEXTYPE_3D ? MTLTextureType3D
                      : type == TEXTYPE_2D_ARRAY ? MTLTextureType2DArray : type == TEXTYPE_1D ? MTLTextureType1D
                      : MTLTextureType2D;
        t[type] = [dev newTextureWithDescriptor:d];
    }
    return t[type];
}

static MTLTextureType mtl_type_for(int t) {
    switch (t) {
    case TEXTYPE_1D: return MTLTextureType1D;
    case TEXTYPE_3D: return MTLTextureType3D;
    case TEXTYPE_CUBE: return MTLTextureTypeCube;
    case TEXTYPE_2D_ARRAY: return MTLTextureType2DArray;
    case TEXTYPE_CUBE_ARRAY: return MTLTextureTypeCubeArray;
    case TEXTYPE_1D_ARRAY: return MTLTextureType1DArray;
    default: return MTLTextureType2D;
    }
}

// NVN texture/view component swizzle (same enum values as MTLTextureSwizzle), applied as a view.
static id<MTLTexture> apply_swizzle(id<MTLTexture> tex, NvnTexture *t, const NvnTextureView *v, bool has_view) {
    const uint8_t *sw = (has_view && (v->setmask & 8)) ? v->swizzle : t->swizzle;
    uint8_t c[4];
    for (int i = 0; i < 4; i++) c[i] = sw[i] <= 5 ? sw[i] : (uint8_t)(2 + i);
    if (!c[0] && !c[1] && !c[2] && !c[3]) return tex;  // never set: identity
    if (renderer_format_alpha_one(t->format))
        for (int i = 0; i < 4; i++) if (c[i] == MTLTextureSwizzleAlpha) c[i] = MTLTextureSwizzleOne;
    if (c[0] == 2 && c[1] == 3 && c[2] == 4 && c[3] == (renderer_format_alpha_one(t->format) ? 1 : 5)) return tex;
    if (tex.sampleCount > 1 || renderer_format_is_depth(t->format) || tex.mipmapLevelCount == 0) return tex;
    uint32_t swz = c[0] | c[1] << 8 | c[2] << 16 | (uint32_t)c[3] << 24;
    MTLTextureSwizzleChannels chans = MTLTextureSwizzleChannelsMake(c[0], c[1], c[2], c[3]);
    id<MTLTexture> view = view_cached(tex, 0x5000000000000000ull | swz, ^{
        NSUInteger slices = tex.textureType == MTLTextureType3D ? 1 : tex.arrayLength * (tex.textureType == MTLTextureTypeCube || tex.textureType == MTLTextureTypeCubeArray ? 6 : 1);
        return [tex newTextureViewWithPixelFormat:tex.pixelFormat textureType:tex.textureType
                                           levels:NSMakeRange(0, tex.mipmapLevelCount) slices:NSMakeRange(0, slices)
                                          swizzle:chans];
    });
    return view;
}

// Upload helper: a separate command buffer, committed now so it runs before the current pass.
static id<MTLTexture> sampled_texture(NvnTexture *t, const NvnTextureView *v, bool has_view, int want_type) {
    // uploads (if the CPU-side contents changed) go into their own command buffer, committed before
    // the current one so they land first
    id<MTLTexture> tex = view_texture(t, v, has_view, false, nil);
    if (tex.mipmapLevelCount == 0) return dummy_texture(want_type);  // invalid texture (target/format 0), no Metal view
    tex = apply_swizzle(tex, t, v, has_view);
    MTLTextureType want = mtl_type_for(want_type);
    if (tex.textureType != want && tex.textureType != MTLTextureType2DMultisample) {
        id<MTLTexture> src = tex;
        if (want == MTLTextureType2D && (tex.textureType == MTLTextureType2DArray || tex.textureType == MTLTextureTypeCube))
            tex = view_cached(src, 0x6000000000000000ull | 1, ^{ return [src newTextureViewWithPixelFormat:src.pixelFormat textureType:MTLTextureType2D levels:NSMakeRange(0, src.mipmapLevelCount) slices:NSMakeRange(0, 1)]; });
        else if (want == MTLTextureType2DArray && tex.textureType == MTLTextureType2D)
            tex = view_cached(src, 0x6000000000000000ull | 2, ^{ return [src newTextureViewWithPixelFormat:src.pixelFormat textureType:MTLTextureType2DArray levels:NSMakeRange(0, src.mipmapLevelCount) slices:NSMakeRange(0, 1)]; });
        else if (want == MTLTextureTypeCube && tex.textureType == MTLTextureType2DArray && tex.arrayLength >= 6)
            tex = view_cached(src, 0x6000000000000000ull | 3, ^{ return [src newTextureViewWithPixelFormat:src.pixelFormat textureType:MTLTextureTypeCube levels:NSMakeRange(0, src.mipmapLevelCount) slices:NSMakeRange(0, 6)]; });
        else {
            static int nlog;
            if (nlog++ < 30) LOG("[tex] type mismatch: want %lu have %lu (%ux%ux%u target %u fmt %#x arr %lu)\n", (unsigned long)want,
                                 (unsigned long)tex.textureType, t->width, t->height, t->depth, t->target, t->format, (unsigned long)tex.arrayLength);
            return dummy_texture(want_type);
        }
    }
    return tex;
}


// ---- render-target feedback: a draw that samples one of the pass's own attachments (e.g. depth
// bound for testing while the shader reads it) gets a snapshot copy, as sampling an attachment of the
// current Metal pass is undefined.
static NvnTexture *feedback_tex[4];
static id<MTLTexture> feedback_copy[4];
static int nfeedback;
// Snapshots stay valid until their texture is written again (a draw writing that attachment, a clear, copy or
// compute). Soft particles (grass-cut leaves, smoke) sample the depth buffer they're tested against but don't
// write it, so a burst of them shares one snapshot instead of a pass break + full-screen copy per draw.
static uint64_t g_cur_fs_hash;
static const char *snap_why[8];
static const char *snap_reason = "?";
static void snapshots_invalidate(NvnTexture *t) {  // NULL = all
    for (int i = 0; i < 8; i++) if ((!t || snap_tex[i] == t) && snap_ok[i]) { snap_ok[i] = false; snap_why[i] = snap_reason; }
}

// BDSP (Unity) reads texture handles bindlessly from the driver's constant buffer 2: texture words at 0x568 + 8 * slot
// (nvnCommandBufferBindSeparateTexture), sampler words at 0x168 + 8 * slot (BindSeparateSampler); the combined handle is the OR.
static uint64_t shader_handle(int stage, const ShaderTexture *st_) {
    if (!st_->bindless) {
        int slot = ((int)st_->handle_offset - 0x20) / 8;  // 64-bit handles from offset 0x20
        return (slot >= 0 && slot < 32) ? st.tex[stage][slot] : 0;
    }
    // Handles of two words: the texture is in the table starting at 0x168, the sampler in the one at 0x568 (finding of the Vulkan branch)
    int ti = ((int)(st_->bindless_has_sampler ? st_->bindless_sampler_offset : st_->bindless_offset) - (st_->bindless_has_sampler ? 0x168 : 0x568)) / 8;
    uint64_t th = (ti >= 0 && ti < 32) ? st.tex[stage][ti] : 0;
    if (!th) return 0;
    uint64_t sh = 0;
    if (st_->bindless_has_sampler) {
        int si = ((int)st_->bindless_offset - 0x568) / 8;
        sh = (si >= 0 && si < 32) ? st.smp[stage][si] : 0;
    }
    return (th & 0xFFFFF) | (sh & 0xFFF00000ull);
}

static NvnTexture *shader_texture_object(int stage, ShaderTexture *st_) {
    uint64_t h = shader_handle(stage, st_);
    uint32_t tic = h & 0xFFFFF;
    if (!h || !st.tpool || tic >= (uint32_t)st.tpool->count) return NULL;
    return ((NvnTexEntry *)st.tpool->entries)[tic].tex;
}

static bool is_attachment(NvnTexture *t) {
    if (!t) return false;
    if (t == st.rt.depth) return true;
    for (int i = 0; i < st.rt.ncolor; i++) if (t == st.rt.color[i]) return true;
    return false;
}

static void resolve_feedback(Prog *pr) {
    nfeedback = 0;
    static int off = -1;
    if (off < 0) off = getenv("BDSP_NO_FEEDBACK") != NULL;
    if (off) return;
    ShaderInfo *infos[2] = {pr->vi, pr->fi};
    for (int sg = 0; sg < 2; sg++)
        for (int i = 0; i < infos[sg]->ntex; i++) {
            NvnTexture *t = shader_texture_object(sg, &infos[sg]->tex[i]);
            if (!is_attachment(t)) continue;
            bool have = false;
            for (int k = 0; k < nfeedback; k++) have |= feedback_tex[k] == t;
            if (have || nfeedback == 4) continue;
            if (!g_snap_copies) g_snap_copies = [NSMutableDictionary new];
            NSMutableDictionary *copies = g_snap_copies;
            NSValue *key = [NSValue valueWithPointer:t];
            static int nosnap = -1;
            if (nosnap < 0) nosnap = getenv("BDSP_NO_SNAPSHOT_REUSE") != NULL;
            int si = -1;
            for (int k = 0; k < 8; k++) if (snap_tex[k] == t) si = k;
            // A draw that writes the same depth buffer it samples can't depend on what it reads (that is undefined on the
            // Switch too): seen in the shadow-map pass, whose material shader still declares the shadow map from the
            // main pass. Any earlier snapshot does; no copy, no pass break.
            bool self_write = t == st.rt.depth && st.ds[0] && st.ds[1];
            if (!nosnap && si >= 0 && (snap_ok[si] || self_write) && copies[key]) {  // unchanged since the last snapshot
                feedback_tex[nfeedback] = t;
                feedback_copy[nfeedback++] = copies[key];
                continue;
            }
            stat_feedback_copies++;
            static int logfb = -1;
            if (logfb < 0) logfb = getenv("BDSP_LOG_FEEDBACK") != NULL;
            if (logfb && stat_feedback_copies % 50 == 1)
                LOG("[feedback] copy %s %ux%u fmt %#x stage %d fs %016llx (last invalidated by %s) ds %d/%d/%d stencil %d ncolor %d c0 %ux%u fmt %#x mask %x\n", t == st.rt.depth ? "DEPTH" : "COLOR",
                    t->width, t->height, t->format, sg, (unsigned long long)g_cur_fs_hash, si >= 0 ? snap_why[si] : "new",
                    st.ds[0], st.ds[1], st.ds[2], st.ds[3], st.rt.ncolor, st.rt.ncolor && st.rt.color[0] ? st.rt.color[0]->width : 0,
                    st.rt.ncolor && st.rt.color[0] ? st.rt.color[0]->height : 0, st.rt.ncolor && st.rt.color[0] ? st.rt.color[0]->format : 0, st.channel_mask);
            end_pass();
            id<MTLTexture> src = renderer_texture(t, nil, true);
            id<MTLTexture> dst = copies[key];
            if (!dst || dst.width != src.width || dst.height != src.height || dst.pixelFormat != src.pixelFormat) {
                MTLTextureDescriptor *d = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:src.pixelFormat width:src.width
                                                                                           height:src.height mipmapped:NO];
                d.textureType = src.textureType == MTLTextureType2DMultisample ? MTLTextureType2DMultisample : MTLTextureType2D;
                d.sampleCount = src.sampleCount;
                d.usage = MTLTextureUsageShaderRead | MTLTextureUsagePixelFormatView;
                d.storageMode = MTLStorageModePrivate;
                dst = [dev newTextureWithDescriptor:d];
                copies[key] = dst;
            }
            id<MTLBlitCommandEncoder> b = [cb() blitCommandEncoder];
            [b copyFromTexture:src sourceSlice:0 sourceLevel:0 sourceOrigin:MTLOriginMake(0, 0, 0)
                    sourceSize:MTLSizeMake(src.width, src.height, 1) toTexture:dst destinationSlice:0 destinationLevel:0
             destinationOrigin:MTLOriginMake(0, 0, 0)];
            [b endEncoding];
            feedback_tex[nfeedback] = t;
            feedback_copy[nfeedback++] = dst;
            if (si < 0) { static int rr; si = rr++ & 7; snap_tex[si] = t; }
            snap_ok[si] = true;
            st.rt_dirty = true;  // the pass resumes (loading) after the copy
        }
}

static void bind_textures(int stage, ShaderInfo *si) {
    if (stage == 1) draw_bottle = draw_heart = 0, draw_item_cursor = false;
    for (int i = 0; i < si->ntex; i++) {
        ShaderTexture *st_ = &si->tex[i];
        uint64_t h = shader_handle(stage, st_);
        id<MTLTexture> tex = nil;
        id<MTLSamplerState> smp = nil;
        uint32_t tic = h & 0xFFFFF, tsc = (uint32_t)(h >> 20) & 0xFFF;
        tex_sc[stage][i][0] = tex_sc[stage][i][1] = 1;
        if (i < 64) tex_wh[stage][i][0] = tex_wh[stage][i][1] = 0;
        if (h && st.tpool && tic < (uint32_t)st.tpool->count) {
            NvnTexEntry *e = &((NvnTexEntry *)st.tpool->entries)[tic];
            if (e->tex) tex = sampled_texture(e->tex, &e->view, e->has_view, st_->type);
            if (e->tex && stage == 1) {
                extern int renderer_texpatch_of(NvnTexture *t);
                extern int texpatch_bottle_kind(int id);
                extern int texpatch_heart_kind(int id);
                extern bool texpatch_is_item_cursor(int id);
                int id = renderer_texpatch_of(e->tex);
                if (!draw_bottle) draw_bottle = texpatch_bottle_kind(id);
                if (!draw_heart) draw_heart = texpatch_heart_kind(id);
                draw_item_cursor |= texpatch_is_item_cursor(id);
            }
            if (e->tex && i < 64) {
                renderer_texture_scale(e->tex, &tex_sc[stage][i][0], &tex_sc[stage][i][1]);
                tex_wh[stage][i][0] = e->tex->width; tex_wh[stage][i][1] = e->tex->height;
            }
            for (int k = 0; k < nfeedback; k++)
                if (e->tex == feedback_tex[k]) {
                    id<MTLTexture> fc = feedback_copy[k];
                    MTLTextureType want = mtl_type_for(st_->type);
                    if (fc.textureType != want && want == MTLTextureType2DArray)
                        fc = [fc newTextureViewWithPixelFormat:fc.pixelFormat textureType:MTLTextureType2DArray levels:NSMakeRange(0, 1) slices:NSMakeRange(0, 1)];
                    tex = fc;
                }
            if (g_debug_frame && e->tex && e->tex->addr) {
                uint64_t total = tegra_total_size(&e->tex->layout), nz = 0;
                const uint8_t *p = (const uint8_t *)(uintptr_t)e->tex->addr;
                for (uint64_t k = 0; k < total; k++) nz += p[k] != 0;
                if (e->tex->width == 1024 && e->tex->height == 2048) {
                    static int once;
                    if (!once++ || g_debug_frame) {
                        id<MTLTexture> base = renderer_texture(e->tex, nil, false);
                        LOG("[dtex] glyph cache target %u depth %u layers %u levels %u stride %u flags %#x base type %lu arrlen %lu\n",
                            e->tex->target, e->tex->depth, e->tex->layout.layers, e->tex->levels, e->tex->stride, e->tex->flags,
                            (unsigned long)base.textureType, (unsigned long)base.arrayLength);
                        LOG("[dtex] glyph view: has %d mask %#x levels %u+%u layers %u+%u fmt %#x target %u\n", e->has_view, e->view.setmask,
                            e->view.base_level, e->view.num_levels, e->view.min_layer, e->view.num_layers, e->view.format, e->view.target);
                        LOG("[dtex] glyph cache: mtl fmt %lu type %lu swizzle tex %d %d %d %d view(%d) %d %d %d %d, tex.swz %08x\n",
                            (unsigned long)base.pixelFormat, (unsigned long)tex.textureType, e->tex->swizzle[0], e->tex->swizzle[1],
                            e->tex->swizzle[2], e->tex->swizzle[3], e->has_view && (e->view.setmask & 8), e->view.swizzle[0],
                            e->view.swizzle[1], e->view.swizzle[2], e->view.swizzle[3],
                            (unsigned)(tex.swizzle.red | tex.swizzle.green << 8 | tex.swizzle.blue << 16 | tex.swizzle.alpha << 24));
                        renderer_save_texture(base, "build/glyph_gpu.png");
                        NvnSamplerDesc *sd = (h && st.spool && tsc < (uint32_t)st.spool->count) ? &((NvnSamplerDesc *)st.spool->entries)[tsc] : NULL;
                        if (sd) { const uint32_t *w = (const uint32_t *)sd; LOG("[dtex] glyph sampler words %08x %08x %08x %08x %08x %08x %08x %08x\n", w[0], w[1], w[2], w[3], w[4], w[5], w[6], w[7]); }
                    }
                }
                if (e->tex->width == 2 && e->tex->height == 2 && e->tex->depth == 6) {
                    static int once2;
                    if (!once2++) {
                        FILE *rf = fopen("build/raw_cube2.bin", "wb");
                        if (rf) { fwrite(p, 1, total, rf); fclose(rf); }
                        LOG("[dtex] cube2 levels %u layers %u bh %u layer_size %llu\n", e->tex->levels, e->tex->layout.layers,
                            e->tex->layout.block_height_log2, tegra_layer_size(&e->tex->layout));
                    }
                }
                if ((e->tex->flags & 0x10) && !getenv("NO_RAW")) {
                    static int nraw;
                    if (nraw++ < 2) {
                        char rp[64];
                        snprintf(rp, sizeof rp, "build/raw_%llx.bin", e->tex->addr);
                        FILE *rf = fopen(rp, "wb");
                        if (rf) { fwrite(p, 1, total, rf); fclose(rf); }
                        LOG("[dtex] linear texture stride %u -> %s\n", e->tex->stride, rp);
                    }
                }
                LOG("[dtex] slot %d tex %ux%u f%#x addr %llx size %llu nonzero %llu gpu_owned %d\n", i, e->tex->width,
                    e->tex->height, e->tex->format, e->tex->addr, total, nz, renderer_is_gpu_owned(e->tex));
            }
        }
        if (h && st.spool && tsc < (uint32_t)st.spool->count) smp = sampler_for(&((NvnSamplerDesc *)st.spool->entries)[tsc]);
        if (!tex) tex = dummy_texture(st_->type);
        if (!smp) smp = default_sampler();
        if (g_debug_frame && tex.textureType == MTLTextureType2D && stage == 1) {
            static int dn;
            char path[128];
            snprintf(path, sizeof path, "build/dtex_%03d_%d.png", dn++, i);
            renderer_save_texture(tex, path);
            snprintf(path, sizeof path, "build/dtex_%03d_%d_a.png", dn - 1, i);
            renderer_save_texture_alpha(tex, path);
        }
        if (stage == 0) { [enc setVertexTexture:tex atIndex:i]; [enc setVertexSamplerState:smp atIndex:i]; }
        else { [enc setFragmentTexture:tex atIndex:i]; [enc setFragmentSamplerState:smp atIndex:i]; }
    }
}

static void bind_cbufs(int stage, ShaderInfo *si) {
    for (int k = 0; k < 18; k++) {
        if (!(si->cbuf_mask & (1u << k))) continue;
        if (k == 0) {
            // driver constants: storage buffer bindings {addr_lo, addr_hi, size, 0} in a 0x100-byte table
            // per hardware stage at 0x110 + 0x100 * stage (vertex 0, fragment 4)
            uint32_t drv[0x800 / 4] = {0};
            uint32_t base = 0x110 + 0x100 * (stage == 1 ? 4 : 0);
            for (int i = 0; i < 16; i++) {
                uint32_t *e = &drv[(base + 16 * i) / 4];
                uint64_t a = arena_on() && si->uses_gmem ? arena_va_draw[stage][i] : st.sbuf[stage][i].addr;
                e[0] = (uint32_t)a;
                e[1] = (uint32_t)(a >> 32);
                e[2] = (uint32_t)st.sbuf[stage][i].size;
                if (ENV("BDSP_LOG_SBUF") && st.sbuf[stage][i].addr && st.sbuf[stage][i].size >= 16) {  // (debug) storage buffer contents per frame, once per address
                    extern uint64_t renderer_present_count(void);
                    static uint64_t seen_frame[4096], seen_addr[4096];
                    static FILE *lf;
                    uint64_t f = renderer_present_count(), lo = (uint64_t)atol(ENV("BDSP_LOG_SBUF")), a = st.sbuf[stage][i].addr;
                    unsigned h = (unsigned)((a >> 4) * 2654435761u) & 4095;
                    if (f >= lo && f < lo + 240 && !(seen_addr[h] == a && seen_frame[h] == f)) {
                        seen_addr[h] = a; seen_frame[h] = f;
                        if (!lf) lf = fopen(ENV("BDSP_LOG_SBUF_FILE") ? ENV("BDSP_LOG_SBUF_FILE") : "sbuf.log", "w");
                        if (lf) {
                            uint64_t sz = st.sbuf[stage][i].size, n = sz > 4096 ? 4096 : sz;
                            fprintf(lf, "S %llu %llu %llx %d %llu", (unsigned long long)f, (unsigned long long)(clock_gettime_nsec_np(CLOCK_UPTIME_RAW) / 1000), (unsigned long long)a, stage * 16 + i, (unsigned long long)sz);
                            for (uint64_t j = 0; j + 4 <= n; j += 4) fprintf(lf, " %08x", *(const uint32_t *)((const uint8_t *)GA(a) + j));
                            fputc('\n', lf);
                            fflush(lf);
                        }
                    }
                }
            }
            uint64_t size = si->cbuf_size[0] > sizeof drv ? sizeof drv : (si->cbuf_size[0] ? si->cbuf_size[0] : 256);
            uint64_t off = ring_alloc(drv, size);
            if (stage == 0) [enc setVertexBuffer:ring offset:off atIndex:0];
            else [enc setFragmentBuffer:ring offset:off atIndex:0];
            continue;
        }
        if (k == 1) {  // compiler constants stored after the shader code
            NvnShaderStage *ss = &st.program->stages[stage];
            uint64_t size = ss->const_size ? ss->const_size : 16;
            if (size < si->cbuf_size[1]) size = si->cbuf_size[1];
            uint64_t off = ring_alloc((void *)(uintptr_t)(ss->code_addr + ss->const_offset), size);
            if (stage == 0) [enc setVertexBuffer:ring offset:off atIndex:1];
            else [enc setFragmentBuffer:ring offset:off atIndex:1];
            continue;
        }
        int idx = k - cbuf_base;
        Range r = (idx >= 0 && idx < 18) ? st.ubuf[stage][idx] : (Range){0, 0};
        uint64_t size = si->cbuf_size[k];
        if (!r.addr) {
            static const uint8_t zeros[0x10000];
            uint64_t off = ring_alloc(zeros, size ? size : 256);
            if (stage == 0) [enc setVertexBuffer:ring offset:off atIndex:k];
            else [enc setFragmentBuffer:ring offset:off atIndex:k];
            continue;
        }
        if ((si->cbuf_dynamic & (1u << k)) && r.size) size = r.size > 0x10000 ? 0x10000 : r.size;  // indexed: whole buffer
        if (size > r.size && r.size) size = r.size;
        if (size < 16) size = 16;
        ring_site = 2;
        uint64_t off = ring_alloc((void *)(uintptr_t)r.addr, size);  // snapshot, as later CPU writes must not leak in
        if (ENV("BDSP_LOG_UBUF")) {  // (debug) per frame once per guest address: time-like values show up as a steady rise
            extern uint64_t renderer_present_count(void);
            static uint64_t seen_frame[4096], seen_addr[4096];
            static FILE *lf;
            uint64_t f = renderer_present_count(), lo = (uint64_t)atol(ENV("BDSP_LOG_UBUF"));
            unsigned h = (unsigned)((r.addr >> 4) * 2654435761u) & 4095;
            if (f >= lo && f < lo + 240 && !(seen_addr[h] == r.addr && seen_frame[h] == f)) {
                seen_addr[h] = r.addr; seen_frame[h] = f;
                if (!lf) lf = fopen(ENV("BDSP_LOG_UBUF_FILE") ? ENV("BDSP_LOG_UBUF_FILE") : "ubuf.log", "w");
                if (lf) {
                    uint64_t n = size > 256 ? 256 : size;
                    fprintf(lf, "F %llu %llu %llx %d %llu", (unsigned long long)f, (unsigned long long)(clock_gettime_nsec_np(CLOCK_UPTIME_RAW) / 1000), (unsigned long long)r.addr, k, (unsigned long long)size);
                    for (uint64_t i = 0; i + 4 <= n; i += 4) fprintf(lf, " %08x", *(const uint32_t *)((const uint8_t *)(uintptr_t)r.addr + i));
                    fputc('\n', lf);
                    fflush(lf);
                }
            }
        }
        if (stage == 0) [enc setVertexBuffer:ring offset:off atIndex:k];
        else [enc setFragmentBuffer:ring offset:off atIndex:k];
    }
}


// ------------------------------------------------------------------ compute
// Compute driver constants (c0): 0x200 work group counts, 0x210 + 16*i uniform buffers (compute has
// few hardware cbuf slots, so the compiler reads the rest through global memory), 0x310 + 16*i
// storage buffers; each table entry is {addr_lo, addr_hi, size, 0}.
typedef struct { id<MTLComputePipelineState> pipe; ShaderInfo *si; uint32_t local[3]; bool failed; } CsProg;
static NSMutableDictionary *g_cs_progs;  // code address -> CsProg

static CsProg *compute_program(NvnProgram *p) {
    NvnShaderStage *ss = &p->stages[5];
    if (!ss->code_addr) return NULL;
    NSValue *key = [NSValue valueWithPointer:(void *)(uintptr_t)ss->code_addr];
    NSMutableDictionary *progs = g_cs_progs;
    if (!progs) progs = g_cs_progs = [NSMutableDictionary new];
    NSValue *v = progs[key];
    if (v) { CsProg *cp = v.pointerValue; return cp->failed ? NULL : cp; }
    CsProg *cp = calloc(1, sizeof *cp);
    progs[key] = [NSValue valueWithPointer:cp];
    maxwell_gmem_base = arena_on() ? ARENA_VA : HEAP_BASE;
    maxwell_gmem_size = arena_on() ? ARENA_SIZE : HEAP_MAX;
    ShaderKey k = {0};
    cp->si = maxwell_translate((const uint8_t *)(uintptr_t)ss->code_addr, ss->const_offset ? ss->const_offset : 0x10000, STAGE_COMPUTE, &k);
    if (!cp->si->msl) { LOG("[compute] translate failed: %s (code %llx)\n", cp->si->error, ss->code_addr); cp->failed = true; return NULL; }
    for (int i = 0; i < 3; i++) {
        cp->local[i] = ss->control ? ss->local_size[i] : 1;
        if (!cp->local[i]) cp->local[i] = 1;
    }
    debug_save_compute_msl(ss->code_addr, cp->si->msl);
    NSError *err = nil;
    id<MTLLibrary> lib = TIMED_COMPILE([dev newLibraryWithSource:@(cp->si->msl) options:nil error:&err]);
    id<MTLFunction> f = lib ? [lib newFunctionWithName:@"main0"] : nil;
    cp->pipe = f ? TIMED_COMPILE([dev newComputePipelineStateWithFunction:f error:&err]) : nil;
    if (!cp->pipe) {
        LOG("[compute] compile failed: %s\n%s\n", err.localizedDescription.UTF8String, cp->si->msl);
        cp->failed = true;
        return NULL;
    }
    LOG("[compute] program %llx: local size %ux%ux%u, %d cbufs mask %#x\n", ss->code_addr, cp->local[0], cp->local[1],
        cp->local[2], 0, cp->si->cbuf_mask);
    return cp;
}

static void dispatch_compute(uint32_t gx, uint32_t gy, uint32_t gz) {
    snap_reason = "compute"; snapshots_invalidate(NULL);
    if (!st.program || !gx || !gy || !gz) return;
    CsProg *cp = compute_program(st.program);
    if (!cp) return;
    for (int i = 0; i < 16; i++)  // every storage range this dispatch can write (see hz_ranges)
        if (st.sbuf[5][i].addr && st.sbuf[5][i].size) {
            int k = 0;  // ranges are kept until a flush; the same buffer is written every frame, so deduplicate
            while (k < hz_n && !(hz_ranges[k].addr == st.sbuf[5][i].addr && hz_ranges[k].size == st.sbuf[5][i].size)) k++;
            if (k == HZ_MAX) k = HZ_MAX - 1;  // full: reuse the last slot
            else if (k == hz_n) hz_n++;
            hz_ranges[k].addr = st.sbuf[5][i].addr; hz_ranges[k].size = st.sbuf[5][i].size;
        }
    static int trace = -1;
    if (trace < 0) trace = getenv("BDSP_TRACE_CS") != NULL;
#define CST(x) do { if (trace) { fprintf(stderr, "[cs] %s\n", x); fflush(stderr); } } while (0)
    // arena: compute reads its extra uniform buffers and its storage buffers through global memory
    uint64_t arena_u[16] = {0}, arena_s[16] = {0};
    __strong id<MTLBuffer> arena_b[2] = {nil, nil};
    bool use_arena = arena_on() && cp->si->uses_gmem;
    if (use_arena) {
        const Range *rr[2] = {st.ubuf[5], st.sbuf[5]};
        const int nn[2] = {16, 16};
        const uint32_t wm[2] = {0, cp->si->uses_gmem_store ? 0xFFFFu : 0};
        uint64_t *const vv[2] = {arena_u, arena_s};
        arena_map(2, rr, nn, wm, vv, arena_b);
    }
    CST("end_pass");
    end_pass();
    CST("encoder");
    id<MTLComputeCommandEncoder> ce = pt_compute_encoder("compute");
    arena_mark_encoded();
    CST("pipeline");
    [ce setComputePipelineState:cp->pipe];
    ShaderInfo *si = cp->si;
    for (int k = 0; k < 18; k++) {
        if (!(si->cbuf_mask & (1u << k))) continue;
        uint64_t off;
        if (k == 0) {
            uint32_t drv[0x500 / 4] = {0};  // tables end at 0x310 + 16 * 16
            drv[0x200 / 4] = gx; drv[0x204 / 4] = gy; drv[0x208 / 4] = gz;
            for (int i = 0; i < 16; i++) {
                uint32_t *u = &drv[(0x210 + 16 * i) / 4];
                uint64_t ua = use_arena ? arena_u[i] : st.ubuf[5][i].addr, sa = use_arena ? arena_s[i] : st.sbuf[5][i].addr;
                u[0] = (uint32_t)ua; u[1] = (uint32_t)(ua >> 32); u[2] = (uint32_t)st.ubuf[5][i].size;
                uint32_t *e = &drv[(0x310 + 16 * i) / 4];
                e[0] = (uint32_t)sa; e[1] = (uint32_t)(sa >> 32); e[2] = (uint32_t)st.sbuf[5][i].size;
                if (ENV("BDSP_LOG_SBUF") && st.sbuf[5][i].addr && st.sbuf[5][i].size >= 16) {  // (debug) compute storage buffers per frame, once per address (before the dispatch runs)
                    extern uint64_t renderer_present_count(void);
                    static uint64_t seen_frame[4096], seen_addr[4096];
                    static FILE *lf;
                    uint64_t f = renderer_present_count(), lo = (uint64_t)atol(ENV("BDSP_LOG_SBUF")), a = st.sbuf[5][i].addr;
                    unsigned h = (unsigned)((a >> 4) * 2654435761u) & 4095;
                    if (f >= lo && f < lo + 240 && !(seen_addr[h] == a && seen_frame[h] == f)) {
                        seen_addr[h] = a; seen_frame[h] = f;
                        if (!lf) lf = fopen(ENV("BDSP_LOG_SBUF_FILE") ? ENV("BDSP_LOG_SBUF_FILE") : "sbuf.log", "a");
                        if (lf) {
                            uint64_t sz = st.sbuf[5][i].size, n = sz > 4096 ? 4096 : sz;
                            fprintf(lf, "S %llu %llu %llx %d %llu", (unsigned long long)f, (unsigned long long)(clock_gettime_nsec_np(CLOCK_UPTIME_RAW) / 1000), (unsigned long long)a, 100 + i, (unsigned long long)sz);
                            for (uint64_t j = 0; j + 4 <= n; j += 4) fprintf(lf, " %08x", *(const uint32_t *)((const uint8_t *)GA(a) + j));
                            fputc('\n', lf);
                            fflush(lf);
                        }
                    }
                }
            }
            off = ring_alloc(drv, sizeof drv);
        } else if (k == 1) {
            NvnShaderStage *ss = &st.program->stages[5];
            uint64_t size = ss->const_size ? ss->const_size : 16;
            if (size < si->cbuf_size[1]) size = si->cbuf_size[1];
            off = ring_alloc((void *)(uintptr_t)(ss->code_addr + ss->const_offset), size);
        } else {
            int idx = k - cbuf_base;
            Range r = (idx >= 0 && idx < 18) ? st.ubuf[5][idx] : (Range){0, 0};
            uint64_t size = si->cbuf_size[k] ? si->cbuf_size[k] : 256;
            if (r.addr) {
                if ((si->cbuf_dynamic & (1u << k)) && r.size) size = r.size > 0x10000 ? 0x10000 : r.size;
                if (size > r.size && r.size) size = r.size;
                if (size < 16) size = 16;
                off = ring_alloc((void *)(uintptr_t)r.addr, size);
            } else {
                static const uint8_t zeros[0x10000];
                off = ring_alloc(zeros, size);
            }
        }
        [ce setBuffer:ring offset:off atIndex:k];
    }
    CST("gmem");
    if (si->uses_gmem) [ce setBuffer:use_arena ? arena_b[1] : gpu_guest_buffer() offset:0 atIndex:GMEM_BUFFER_INDEX];
    CST("textures");
    for (int i = 0; i < si->ntex; i++) {
        ShaderTexture *st_ = &si->tex[i];
        int slot = ((int)st_->handle_offset - 0x20) / 8;
        uint64_t h = (slot >= 0 && slot < 32) ? st.tex[5][slot] : 0;
        id<MTLTexture> tex = nil;
        id<MTLSamplerState> smp = nil;
        uint32_t tic = h & 0xFFFFF, tsc = (uint32_t)(h >> 20) & 0xFFF;
        tex_sc[0][i][0] = tex_sc[0][i][1] = 1;
        if (h && st.tpool && tic < (uint32_t)st.tpool->count) {
            NvnTexEntry *e = &((NvnTexEntry *)st.tpool->entries)[tic];
            if (e->tex) tex = sampled_texture(e->tex, &e->view, e->has_view, st_->type);
            if (e->tex && i < 64) renderer_texture_scale(e->tex, &tex_sc[0][i][0], &tex_sc[0][i][1]);
            for (int k = 0; k < nfeedback; k++)
                if (e->tex == feedback_tex[k]) {
                    id<MTLTexture> fc = feedback_copy[k];
                    MTLTextureType want = mtl_type_for(st_->type);
                    if (fc.textureType != want && want == MTLTextureType2DArray)
                        fc = [fc newTextureViewWithPixelFormat:fc.pixelFormat textureType:MTLTextureType2DArray levels:NSMakeRange(0, 1) slices:NSMakeRange(0, 1)];
                    tex = fc;
                }
        }
        if (h && st.spool && tsc < (uint32_t)st.spool->count) smp = sampler_for(&((NvnSamplerDesc *)st.spool->entries)[tsc]);
        [ce setTexture:tex ? tex : dummy_texture(st_->type) atIndex:i];
        [ce setSamplerState:smp ? smp : default_sampler() atIndex:i];
    }
    if (si->uses_rscale) {
        float rs[65][4] = {{1, 1, 0, 0}};
        for (int i = 0; i < si->ntex && i < 64; i++) { rs[1 + i][0] = tex_sc[0][i][0]; rs[1 + i][1] = tex_sc[0][i][1]; }
        [ce setBytes:rs length:(NSUInteger)(1 + si->ntex) * 16 atIndex:RSCALE_BUFFER_INDEX];
    }
    CST("dispatch");
    extern bool g_debug_frame;
    if (g_debug_frame) {
        LOG("[dispatch] cs=%llx groups %ux%ux%u ssbo:", st.program->stages[5].code_addr, gx, gy, gz);
        for (int i = 0; i < 16; i++) if (st.sbuf[5][i].addr) LOG(" %d(%llx,%llu)", i, st.sbuf[5][i].addr, st.sbuf[5][i].size);
        LOG(" ubo:");
        for (int i = 0; i < 18; i++) if (st.ubuf[5][i].addr) LOG(" %d(%llx,%llu)", i, st.ubuf[5][i].addr, st.ubuf[5][i].size);
        LOG(" gmem %d\n", si->uses_gmem);
    }
    [ce dispatchThreadgroups:MTLSizeMake(gx, gy, gz) threadsPerThreadgroup:MTLSizeMake(cp->local[0], cp->local[1], cp->local[2])];
    [ce endEncoding];
    CST("done");
    stat_dispatches++;
}

static MTLPrimitiveType prim_type(uint32_t mode, bool *ok) {
    *ok = true;
    switch (mode) {
    case 0: return MTLPrimitiveTypePoint;
    case 1: return MTLPrimitiveTypeLine;
    case 3: return MTLPrimitiveTypeLineStrip;
    case 4: return MTLPrimitiveTypeTriangle;
    case 5: return MTLPrimitiveTypeTriangleStrip;
    default: *ok = false; return MTLPrimitiveTypeTriangle;
    }
}

// Expand quads/fans/polygons into a triangle index list (32-bit) referencing the original vertices.
static id<MTLBuffer> expand_indices(uint32_t mode, uint32_t count, const void *indices, int itype, uint32_t first,
                                    uint32_t *out_count) {
    uint32_t tris = mode == 7 ? count / 4 * 2 : count >= 3 ? count - 2 : 0;
    uint32_t *out = malloc(tris * 3 * 4 + 4);
    uint32_t n = 0;
#define IDX(i) (indices ? (itype == 0 ? ((const uint8_t *)indices)[i] : itype == 1 ? ((const uint16_t *)indices)[i] : ((const uint32_t *)indices)[i]) : first + (i))
    if (mode == 7) {  // quads
        for (uint32_t q = 0; q + 3 < count; q += 4) {
            out[n++] = IDX(q); out[n++] = IDX(q + 1); out[n++] = IDX(q + 2);
            out[n++] = IDX(q); out[n++] = IDX(q + 2); out[n++] = IDX(q + 3);
        }
    } else {  // fan / polygon
        for (uint32_t i = 1; i + 1 < count; i++) { out[n++] = IDX(0); out[n++] = IDX(i); out[n++] = IDX(i + 1); }
    }
#undef IDX
    *out_count = n;
    id<MTLBuffer> b = [dev newBufferWithBytes:out length:n * 4 + 4 options:MTLResourceStorageModeShared];
    free(out);
    return b;
}

static void debug_draw(Prog *pr, CmdRec *r, bool indexed) {
    static uint64_t dump_fs = 1;
    if (dump_fs == 1) { const char *e = getenv("BDSP_DUMP_UBO"); dump_fs = e ? strtoull(e, NULL, 16) : 0; }
    if (dump_fs && st.program && st.program->stages[1].code_addr == dump_fs) {
        for (int i = 0; i < 18; i++) {
            if (!st.ubuf[1][i].addr) continue;
            const float *f = (const float *)(uintptr_t)st.ubuf[1][i].addr;
            LOG("[ubo] f%d (%llu):", i, st.ubuf[1][i].size);
            for (uint64_t k = 0; k < st.ubuf[1][i].size / 4 && k < 1200; k++) LOG(" %g", f[k]);
            LOG("\n");
        }
    }
    static int dump_vs = -1;  // BDSP_DUMP_VSUBO: every vertex-stage UBO (first 48 floats) of debug-frame draws
    if (dump_vs < 0) dump_vs = getenv("BDSP_DUMP_VSUBO") != NULL;
    for (int i = 0; dump_vs && i < 18; i++) {
        if (!st.ubuf[0][i].addr) continue;
        const float *f = (const float *)(uintptr_t)st.ubuf[0][i].addr;
        LOG("[vsubo] v%d (%llu):", i, st.ubuf[0][i].size);
        for (uint64_t k = 0; k < st.ubuf[0][i].size / 4 && k < 48; k++) LOG(" %g", f[k]);
        LOG("\n");
    }
    if (st.sbuf[0][0].addr && st.sbuf[0][0].size >= 64 && st.sbuf[0][0].size <= 8192) {
        int recw = (st.sbuf[0][0].size % 96 == 0 && st.sbuf[0][0].size % 64 != 0) ? 24 : 16;
        const float *f = (const float *)(uintptr_t)st.sbuf[0][0].addr;
        const uint32_t *u = (const uint32_t *)f;
        for (int g = 0; g < (int)(st.sbuf[0][0].size / (recw * 4)) && g < 6; g++) {
            LOG("[ssbo] rec%d:", g);
            for (int k = 0; k < recw; k++) LOG(" %g(%08x)", f[g * recw + k], u[g * recw + k]);
            LOG("\n");
        }
    }
    LOG("[draw] %s inst %llu", indexed ? "e" : "a", indexed ? r->x[6] : r->x[4]);
    LOG(" %s mode %llu count %llu prog vs=%llx fs=%llx | vs cb %#x fs cb %#x | ubufs:",
        indexed ? "elems" : "arrays", r->x[0], r->x[2], st.program->stages[0].code_addr, st.program->stages[1].code_addr,
        pr->vi->cbuf_mask, pr->fi->cbuf_mask);
    for (int s = 0; s < 2; s++)
        for (int i = 0; i < 18; i++)
            if (st.ubuf[s][i].addr) LOG(" %c%d(%llx,%llu)", s ? 'f' : 'v', i, st.ubuf[s][i].addr, st.ubuf[s][i].size);
    LOG(" | fubo0:");
    for (int i = 0; i < 6; i++)
        if (st.ubuf[1][i].addr) { const float *f = (const float *)(uintptr_t)st.ubuf[1][i].addr; LOG(" f%d=[%g %g %g %g]", i, f[0], f[1], f[2], f[3]); }
    LOG(" | ssbo:");
    for (int sg = 0; sg < 2; sg++)
        for (int i = 0; i < 16; i++)
            if (st.sbuf[sg][i].addr) LOG(" %c%d(%llx,%llu)", sg ? 'f' : 'v', i, st.sbuf[sg][i].addr, st.sbuf[sg][i].size);
    LOG(" | tex:");
    for (int i = 0; i < pr->fi->ntex; i++) LOG(" off%u", pr->fi->tex[i].handle_offset);
    LOG(" bound:");
    for (int i = 0; i < 32; i++) {
        if (!st.tex[1][i]) continue;
        uint32_t tic = st.tex[1][i] & 0xFFFFF;
        NvnTexture *t = st.tpool && tic < (uint32_t)st.tpool->count ? ((NvnTexEntry *)st.tpool->entries)[tic].tex : NULL;
        if (t) LOG(" %d=[%ux%ux%u t%u f%#x fl%#x %s]", i, t->width, t->height, t->depth, t->target, t->format, t->flags, t->label);
        else LOG(" %d=%llx", i, st.tex[1][i]);
    }
    LOG(" | rt %d", st.rt.ncolor);
    for (int i = 0; i < st.rt.ncolor; i++) if (st.rt.color[i]) LOG(" %ux%u/f%#x", st.rt.color[i]->width, st.rt.color[i]->height, st.rt.color[i]->format);
    if (st.rt.depth) LOG(" d%#x", st.rt.depth->format);
    LOG(" | vp %.0f %.0f %.0f %.0f | attrs %#x streams:", st.viewport[0][0], st.viewport[0][1], st.viewport[0][2], st.viewport[0][3], pr->vi->attr_mask);
    for (int i = 0; i < st.nattrib; i++) LOG(" a%d(f%#x s%u o%u)", i, st.attrib[i] & 0xFF, (st.attrib[i] >> 8) & 0x1F, st.attrib[i] >> 13);
    for (int i = 0; i < 12; i++) if (st.vbuf[i].addr) LOG(" vb%d(%llx,%llu,stride %u div %u)", i, st.vbuf[i].addr, st.vbuf[i].size, st.stream[i][0], st.stream[i][1]);
    if (st.ubuf[0][0].addr && st.ubuf[0][0].size == 560) {
        const float *f = (const float *)(uintptr_t)st.ubuf[0][0].addr;
        LOG("\n  vs ubo0:");
        for (int i = 0; i < 36; i++) LOG("%s[%d] %g %g %g %g", i % 2 ? " " : "\n   ", i, f[i*4], f[i*4+1], f[i*4+2], f[i*4+3]);
    }
    LOG(" blend %#x ds %02x%02x%02x poly %02x%02x scissor %d,%d %dx%d chmask %08x stencil %02x%02x%02x%02x%02x ref %u/%u wm %x vm %x bf %d,%d,%d,%d,%d,%d\n", st.color_state[0], st.ds[0], st.ds[1], st.ds[2], st.poly[0], st.poly[1],
        st.scissor[0][0], st.scissor[0][1], st.scissor[0][2], st.scissor[0][3], st.channel_mask, st.ds[3], st.ds[4], st.ds[5], st.ds[6],
        st.ds[7], st.stencil_ref[0], st.stencil_ref[1], st.stencil_mask[0], st.stencil_vmask[0], st.blend[0][1], st.blend[0][2],
        st.blend[0][3], st.blend[0][4], st.blend[0][5], st.blend[0][6]);
}


// ---- pipeline cache keyed by a hash of the raw state that shapes the pipeline (avoids building a
// descriptor and a string key per draw)
// Pipelines are keyed by their shader functions' addresses: a reboot frees the old functions, so keys carry the
// boot generation (a build still in flight can't land on a new function at a reused address).
static unsigned g_boot_gen;

static uint64_t hmix(uint64_t h, const void *p, size_t n) {
    const uint8_t *b = p;
    for (size_t i = 0; i < n; i++) { h ^= b[i]; h *= 0x100000001B3ull; }
    return h;
}
#define PIPE_TAB 8192
static struct { uint64_t key; void *pipe; } pipe_tab[PIPE_TAB];

static uint64_t pipeline_state_hash(Prog *pr) {
    uint64_t h = 0xcbf29ce484222325ull;
    h = hmix(h, &pr, sizeof pr);
    h = hmix(h, &st.rt.ncolor, sizeof st.rt.ncolor);
    for (int i = 0; i < st.rt.ncolor && i < 8; i++) {
        NvnTexture *t = st.rt.color[i];
        uint32_t v[4] = {t ? t->format : 0, t ? t->samples : 0, st.rt.has_cview[i], st.rt.has_cview[i] ? st.rt.cview[i].format | (st.rt.cview[i].setmask << 16) : 0};
        h = hmix(h, v, sizeof v);
        h = hmix(h, st.blend[i], 8);
    }
    uint32_t dfmt = st.rt.depth ? st.rt.depth->format : 0, dsamples = st.rt.depth ? st.rt.depth->samples : 0;
    h = hmix(h, &dfmt, 4);
    h = hmix(h, &dsamples, 4);
    h = hmix(h, &st.nattrib, sizeof st.nattrib);
    h = hmix(h, st.attrib, sizeof st.attrib[0] * (size_t)(st.nattrib < 32 ? st.nattrib : 32));
    h = hmix(h, &st.nstream, sizeof st.nstream);
    h = hmix(h, st.stream, sizeof st.stream[0] * (size_t)(st.nstream < 16 ? st.nstream : 16));
    h = hmix(h, &st.channel_mask, sizeof st.channel_mask);
    h = hmix(h, &st.color_state[0], sizeof st.color_state[0]);
    h = hmix(h, &st.ms[0xC], 1);
    return h ? h : 1;
}

// Pipeline as data (no pointers, no draw state). It is both the cache key and the entry in
// pipelines.bin; at startup the gate builds all entries of the file in advance (startup_gate).
typedef struct {
    uint64_t vh, fh;  // fnv64 of the MSL sources (names of the pre-compiled libraries)
    uint32_t depth_fmt, stencil_fmt, samples, a2c, ncolor;
    struct { uint32_t present, fmt, wmask, blend, sf, df, sa, da, ro, ao; } ca[8];
    struct { uint32_t present, fmt, off, buf; } attr[32];
    struct { uint32_t present, stride, step, rate; } lay[32];
} PipeRec;

typedef struct { char magic[4]; uint32_t ver, recsize; } PipeHdr;
#define PIPE_MAGIC "BDPL"
#define PIPE_VER 1

static void rec_from_state(const Prog *pr, uint32_t used_streams, PipeRec *r) {
    memset(r, 0, sizeof *r);
    r->vh = pr->vh;
    r->fh = pr->fh;
    r->ncolor = st.rt.ncolor < 8 ? st.rt.ncolor : 8;
    for (int i = 0; i < r->ncolor; i++) {
        if (!st.rt.color[i]) continue;
        uint32_t m = (st.channel_mask >> (i * 4)) & 0xF;
        r->ca[i].present = 1;
        r->ca[i].fmt = (uint32_t)view_texture(st.rt.color[i], &st.rt.cview[i], st.rt.has_cview[i], true, nil).pixelFormat;
        r->ca[i].wmask = (m & 1 ? MTLColorWriteMaskRed : 0) | (m & 2 ? MTLColorWriteMaskGreen : 0) |
                         (m & 4 ? MTLColorWriteMaskBlue : 0) | (m & 8 ? MTLColorWriteMaskAlpha : 0);
        if (((st.color_state[0] >> i) & 1) && !rt_kind(st.rt.color[i]->format)) {
            uint8_t *b = st.blend[i];
            r->ca[i].blend = 1;
            r->ca[i].sf = blend_factor(b[1]);
            r->ca[i].df = blend_factor(b[2]);
            r->ca[i].sa = blend_factor(b[3]);
            r->ca[i].da = blend_factor(b[4]);
            r->ca[i].ro = blend_op(b[5]);
            r->ca[i].ao = blend_op(b[6]);
        }
    }
    if (st.rt.depth) {
        uint32_t pf = (uint32_t)renderer_pixel_format(st.rt.depth->format);
        if (renderer_format_is_depth(st.rt.depth->format) && st.rt.depth->format != 0x31) r->depth_fmt = pf;
        if (renderer_format_has_stencil(st.rt.depth->format)) r->stencil_fmt = pf;
    }
    uint32_t ps = pass_samples();
    r->samples = ps > 1 ? ps : 0;  // (0 for single-sample: the manifest's keys stay valid)
    r->a2c = st.ms[0xC] != 0;
    for (int i = 0; i < 32; i++) {
        if (!(pr->vi->attr_mask & (1u << i))) continue;
        uint32_t a = i < st.nattrib ? st.attrib[i] : 0x2E;
        uint32_t fmt = a & 0xFF, stream = (a >> 8) & 0x1F, off = a >> 13;
        if (i >= st.nattrib || fmt == 0) {  // unbound attribute: zeros from a constant stream
            r->attr[i] = (typeof(r->attr[0])){1, MTLVertexFormatFloat4, 0, 30};
            r->lay[30] = (typeof(r->lay[0])){1, 16, MTLVertexStepFunctionConstant, 0};
            continue;
        }
        r->attr[i] = (typeof(r->attr[0])){1, vertex_format(fmt), off, 18 + stream};
    }
    for (int s = 0; s < 12; s++) {
        if (!(used_streams & (1u << s))) continue;
        uint32_t stride = s < st.nstream ? st.stream[s][0] : 0, div = s < st.nstream ? st.stream[s][1] : 0;
        if (stride == 0) r->lay[18 + s] = (typeof(r->lay[0])){1, 16, MTLVertexStepFunctionConstant, 0};
        else {
            r->lay[18 + s] = (typeof(r->lay[0])){1, (stride + 3) & ~3u, MTLVertexStepFunctionPerVertex, 1};
            if (div) { r->lay[18 + s].step = MTLVertexStepFunctionPerInstance; r->lay[18 + s].rate = div; }
        }
    }
}

static MTLRenderPipelineDescriptor *pd_from_rec(const PipeRec *r, id<MTLFunction> vs, id<MTLFunction> fs) {
    MTLRenderPipelineDescriptor *pd = [MTLRenderPipelineDescriptor new];
    pd.vertexFunction = vs;
    pd.fragmentFunction = fs;
    for (int i = 0; i < r->ncolor; i++) {
        if (!r->ca[i].present) continue;
        MTLRenderPipelineColorAttachmentDescriptor *ca = pd.colorAttachments[i];
        ca.pixelFormat = (MTLPixelFormat)r->ca[i].fmt;
        ca.writeMask = r->ca[i].wmask;
        if (r->ca[i].blend) {
            ca.blendingEnabled = YES;
            ca.sourceRGBBlendFactor = (MTLBlendFactor)r->ca[i].sf;
            ca.destinationRGBBlendFactor = (MTLBlendFactor)r->ca[i].df;
            ca.sourceAlphaBlendFactor = (MTLBlendFactor)r->ca[i].sa;
            ca.destinationAlphaBlendFactor = (MTLBlendFactor)r->ca[i].da;
            ca.rgbBlendOperation = (MTLBlendOperation)r->ca[i].ro;
            ca.alphaBlendOperation = (MTLBlendOperation)r->ca[i].ao;
        }
    }
    if (r->depth_fmt) pd.depthAttachmentPixelFormat = (MTLPixelFormat)r->depth_fmt;
    if (r->stencil_fmt) pd.stencilAttachmentPixelFormat = (MTLPixelFormat)r->stencil_fmt;
    if (r->samples > 1) pd.rasterSampleCount = r->samples;
    pd.alphaToCoverageEnabled = r->a2c;
    MTLVertexDescriptor *vd = [MTLVertexDescriptor vertexDescriptor];
    for (int i = 0; i < 32; i++) {
        if (!r->attr[i].present) continue;
        vd.attributes[i].format = (MTLVertexFormat)r->attr[i].fmt;
        vd.attributes[i].offset = r->attr[i].off;
        vd.attributes[i].bufferIndex = r->attr[i].buf;
    }
    for (int s = 0; s < 32; s++) {
        if (!r->lay[s].present) continue;
        vd.layouts[s].stride = r->lay[s].stride;
        vd.layouts[s].stepFunction = (MTLVertexStepFunction)r->lay[s].step;
        vd.layouts[s].stepRate = r->lay[s].rate;
    }
    pd.vertexDescriptor = vd;
    return pd;
}

static id<MTLRenderPipelineState> build_pipeline(const PipeRec *r, id<MTLFunction> vs, id<MTLFunction> fs) {
    NSError *err = nil;
    if (bdsp_shader_compile_status) bdsp_shader_compile_status(1);
    id<MTLRenderPipelineState> p = TIMED_COMPILE([dev newRenderPipelineStateWithDescriptor:pd_from_rec(r, vs, fs) error:&err]);
    if (bdsp_shader_compile_status) bdsp_shader_compile_status(0);
    if (!p) { static int n; if (n++ < 10) LOG("[metal] pipeline failed: %s\n", err.localizedDescription.UTF8String); }
    return p;
}

static NSString *pipe_key(const PipeRec *r) { return [[NSData dataWithBytes:r length:sizeof *r] base64EncodedStringWithOptions:0]; }

// All pipeline keys that are known (loaded from the manifests or already appended).
static NSMutableSet *known_recs;

static NSString *pipe_manifest_path(void) {
    NSString *d = [NSSearchPathForDirectoriesInDomains(NSCachesDirectory, NSUserDomainMask, YES) firstObject];
    d = [d stringByAppendingPathComponent:@"BDSP"];
    [[NSFileManager defaultManager] createDirectoryAtPath:d withIntermediateDirectories:YES attributes:nil error:nil];
    return [d stringByAppendingPathComponent:@"pipelines.bin"];
}

// New pipeline from the draw: append it once to the caches file (the shipped pipelines.bin in the bundle is only
// created by hand from this file).
static void pipe_record_add(const PipeRec *r) {
    NSString *k = pipe_key(r);
    if ([known_recs containsObject:k]) return;
    [known_recs addObject:k];
    FILE *f = fopen(pipe_manifest_path().fileSystemRepresentation, "ab");
    if (!f) return;
    fseek(f, 0, SEEK_END);
    if (ftell(f) == 0) {
        PipeHdr h = {{'B', 'D', 'P', 'L'}, PIPE_VER, sizeof(PipeRec)};
        fwrite(&h, sizeof h, 1, f);
    }
    fwrite(r, sizeof *r, 1, f);
    fclose(f);
}

static void load_manifest(NSString *path, NSMutableArray *out) {
    FILE *f = fopen(path.fileSystemRepresentation, "rb");
    if (!f) return;
    PipeHdr h;
    if (fread(&h, sizeof h, 1, f) == 1 && !memcmp(h.magic, PIPE_MAGIC, 4) && h.ver == PIPE_VER && h.recsize == sizeof(PipeRec)) {
        PipeRec r;
        while (fread(&r, sizeof r, 1, f) == 1) {
            NSString *k = pipe_key(&r);
            if ([known_recs containsObject:k]) continue;
            [known_recs addObject:k];
            [out addObject:[NSData dataWithBytes:&r length:sizeof r]];
        }
    }
    fclose(f);
}

// Start gate: before the first guest draw all pipelines from pipelines.bin are built. Meanwhile the guest stands still;
// a presentation thread shows the counter (renderer_gate_present, metal.m) at a fixed 60 Hz.
static uint64_t gate_done, gate_total;
static bool gate_finished;
void renderer_gate_present(uint64_t done, uint64_t total);  // metal.m

static void *gate_presenter(void *arg) {
    (void)arg;
    double next = now_ms();
    while (!__atomic_load_n(&gate_finished, __ATOMIC_ACQUIRE)) {
        uint64_t done = __atomic_load_n(&gate_done, __ATOMIC_RELAXED);
        if (bdsp_shader_gate_status) bdsp_shader_gate_status(done, gate_total, 1);
#ifndef BDSP_IOS
        else renderer_gate_present(done, gate_total); // standalone desktop runtime
#endif
        next += bdsp_shader_gate_status ? 100.0 : 1000.0 / 60.0;
        double wait = next - now_ms();
        if (wait > 0) usleep((useconds_t)(wait * 1000.0));
        else next = now_ms();
    }
    return NULL;
}

static void startup_gate(void) {
    static bool started;
    if (started) return;
    started = true;
    known_recs = [NSMutableSet new];
    if (getenv("BDSP_NO_GATE")) return;
    NSMutableArray *recs = [NSMutableArray new];
    load_manifest([[NSBundle mainBundle].resourcePath stringByAppendingPathComponent:@"pipelines.bin"], recs);
    load_manifest(pipe_manifest_path(), recs);
    NSMutableArray *gated = [NSMutableArray new];  // only entries whose libraries are present
    for (NSData *d in recs) {
        const PipeRec *r = d.bytes;
        NSString *dir = prebuilt_dir();
        if (!dir) break;
        NSFileManager *fm = [NSFileManager defaultManager];
        if ([fm fileExistsAtPath:[dir stringByAppendingPathComponent:[NSString stringWithFormat:@"v_%016llx.metallib", (unsigned long long)r->vh]]] &&
            [fm fileExistsAtPath:[dir stringByAppendingPathComponent:[NSString stringWithFormat:@"f_%016llx.metallib", (unsigned long long)r->fh]]])
            [gated addObject:d];
    }
    if (!gated.count) return;
    gate_total = gated.count;
    gate_done = 0;
    gate_finished = false;
    double t0 = now_ms();
    pthread_t th;
    pthread_create(&th, NULL, gate_presenter, NULL);
    dispatch_apply(gated.count, dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^(size_t i) {
        const PipeRec *r = [gated[i] bytes];
        id<MTLLibrary> vl = prebuilt_library_hash(r->vh, 'v');
        id<MTLLibrary> fl = prebuilt_library_hash(r->fh, 'f');
        id<MTLRenderPipelineState> p = nil;
        if (vl && fl) p = build_pipeline(r, [vl newFunctionWithName:@"main0"], [fl newFunctionWithName:@"main0"]);
        @synchronized(cache) { cache[pipe_key(r)] = p ? (id)p : (id)[NSNull null]; }
        __atomic_fetch_add(&gate_done, 1, __ATOMIC_RELAXED);
    });
    __atomic_store_n(&gate_finished, true, __ATOMIC_RELEASE);
    pthread_join(th, NULL);
    if (bdsp_shader_gate_status) bdsp_shader_gate_status(gate_total, gate_total, 0);
    LOG("[gate] %llu Pipelines in %.0f ms vorgebaut\n", (unsigned long long)gate_total, now_ms() - t0);
}

// True if one of the vertex streams in `used` covers a storage range that a compute dispatch may still write.
static bool getenv_flag_hz_flush(void) {
    static int v = -1;
    if (v < 0) v = getenv("BDSP_HZ_FLUSH") != NULL;
    return v;
}
// True if [addr, addr+size) overlaps a storage range a compute dispatch not yet known to be finished uses.
static bool range_pending_compute(uint64_t addr, uint64_t size) {
    for (int i = 0; i < hz_n; i++)
        if (addr < hz_ranges[i].addr + hz_ranges[i].size && addr + size > hz_ranges[i].addr) return true;
    return false;
}
// Mask of the used vertex streams that overlap a range a pending compute dispatch writes.
static uint32_t streams_pending_compute(uint32_t used) {
    uint32_t m = 0;
    for (int s = 0; s < 12; s++) {
        if (!(used & (1u << s)) || !st.vbuf[s].addr) continue;
        uint64_t lo = st.vbuf[s].addr, hi = lo + (st.vbuf[s].size ? st.vbuf[s].size : 16);
        for (int i = 0; i < hz_n; i++)
            if (lo < hz_ranges[i].addr + hz_ranges[i].size && hi > hz_ranges[i].addr) { m |= 1u << s; break; }
    }
    return m;
}

static void draw(CmdRec *r, bool indexed) {
    if (!st.program) { stat_skipped++; return; }
    if (debug_skip_draw(r)) { stat_skipped++; return; }
    static bool logged_modes;
    if (!logged_modes) {
        logged_modes = true;
        const char *cb = getenv("BDSP_CBUF_BASE"), *tb = getenv("BDSP_TEX_BASE");
        if (cb) cbuf_base = atoi(cb);
        if (tb) tex_base = atoi(tb);
    }
    ShaderKey vkey = {0}, fkey = {0};
    vkey.flip_y = fkey.flip_y = nvn_window_origin() == 0;
    vkey.no_rscale = fkey.no_rscale = true;  // no resolution scaling (XNU translator option)
    vkey.depth_minus_one = nvn_depth_mode() == 0;
    for (int i = 0; i < st.nattrib; i++) vkey.attr_kind[i] = (uint8_t)attr_kind(st.attrib[i] & 0xFF);
    GeomState geom = geom_state(&vkey);  // render_debug.inc: BDSP_GEOM_CHECK
    for (int i = 0; i < st.rt.ncolor; i++) if (st.rt.color[i]) fkey.rt_kind[i] = (uint8_t)rt_kind(st.rt.color[i]->format);
    Prog *pr = get_program(st.program, &vkey, &fkey);
    if (!pr || !pr->ready) { stat_skipped++; return; }
    {   // mirror mode (runtime/hle/mirror.c): the scene's composite into the window image is drawn mirrored - the
        // unblended full-screen draw sampling an image the window's size (the window images also serve as scratch
        // targets earlier in the frame: those draws sample smaller images; the HUD after it blends)
        extern bool mirror_draw(bool composite);
        bool composite = false;
        if (st.rt.ncolor && st.rt.color[0] && renderer_texture_presented(st.rt.color[0]) && !(st.color_state[0] & 1) &&
            r->x[2] <= 6 && st.viewport[0][0] == 0 && st.viewport[0][1] == 0 &&
            st.viewport[0][2] >= st.rt.color[0]->width && st.viewport[0][3] >= st.rt.color[0]->height && pr->fi->ntex) {
            NvnTexture *t0 = shader_texture_object(1, &pr->fi->tex[0]);
            composite = t0 && t0->width == st.rt.color[0]->width && t0->height == st.rt.color[0]->height;
        }
        if (mirror_draw(composite)) {  // (the vertex flip mirrors a composite drawn with uvs, the fragment one a
            vkey.flip_x = fkey.flip_x = true;  // composite reading pixel positions; get_program keys on vkey)
            pr = get_program(st.program, &vkey, &fkey);
            if (!pr || !pr->ready) { stat_skipped++; return; }
        }
    }
    {   // Interiors/dungeons draw a 16:9 backdrop quad over the still-rendered overworld: frames that
        // draw it are presented cropped to 16:9 (see backend_present).
        static uint64_t last_fs, last_hash;
        uint64_t fs = st.program->stages[1].code_addr;
        if (fs != last_fs) {
            last_fs = fs;
            last_hash = fs ? hmix(1469598103934665603ull, (const void *)(uintptr_t)(fs + 0x30), 0x200) : 0;
        }
        static uint64_t log_hash = 1;
        if (log_hash == 1) log_hash = getenv("BDSP_LOG_FSHASH") ? 0 : 2;
        if (!log_hash && g_debug_frame) LOG("[fshash] fs=%llx hash %016llx\n", fs, last_hash);
        {   // BDSP_SKIP_FSHASH=h1,h2,...: drop draws using these fragment shaders (find which draw makes what)
            static uint64_t skip[16];
            static int nskip = -1;
            if (nskip < 0) {
                nskip = 0;
                for (const char *p = getenv("BDSP_SKIP_FSHASH"); p && *p && nskip < 16;) {
                    skip[nskip++] = strtoull(p, (char **)&p, 16);
                    while (*p == ',') p++;
                }
            }
            for (int i = 0; i < nskip; i++) if (last_hash == skip[i]) { stat_skipped++; return; }
            extern bool pot_level_active(void);
            if (last_hash == 0xa2177dbb72197bd9ull && pot_level_active()) { stat_skipped++; return; }  // item twinkle
        }
        g_cur_fs_hash = last_hash;
        extern void widescreen_backdrop_seen(uint64_t hash);
        if (last_hash) widescreen_backdrop_seen(last_hash);
        extern void widescreen_scene_ubo(const float *u, uint64_t size);  // (the camera's view-projection)
        if (st.ubuf[0][5].addr) widescreen_scene_ubo((const float *)(uintptr_t)st.ubuf[0][5].addr, st.ubuf[0][5].size);
        if (last_hash == 0x71fe31bbf03c3515ull && getenv("BDSP_LOG_INDOOR")) {
            static uint64_t lf;
            extern uint64_t renderer_present_count(void);
            if (renderer_present_count() != lf) {
                lf = renderer_present_count();
                LOG("[backdrop] frame %llu count %llu rt %ux%u vp %.0f %.0f %.0f %.0f scissor %d %d %d %d\n", (unsigned long long)lf, r->x[2],
                    st.rt.ncolor && st.rt.color[0] ? st.rt.color[0]->width : 0, st.rt.ncolor && st.rt.color[0] ? st.rt.color[0]->height : 0,
                    st.viewport[0][0], st.viewport[0][1], st.viewport[0][2], st.viewport[0][3], st.scissor[0][0], st.scissor[0][1],
                    st.scissor[0][2], st.scissor[0][3]);
            }
        }
    }
    static int log_rt_w = -1, log_rt_h;
    if (log_rt_w < 0) { const char *e = getenv("BDSP_LOG_RT"); log_rt_w = 0; if (e) sscanf(e, "%dx%d", &log_rt_w, &log_rt_h); }
    static uint64_t log_rt_addr = 1;
    if (log_rt_addr == 1) { const char *e = getenv("BDSP_LOG_RT_ADDR"); log_rt_addr = e ? strtoull(e, NULL, 16) : 0; }
    bool addr_hit = false;
    for (int i = 0; log_rt_addr && i < st.rt.ncolor; i++)
        if (st.rt.color[i] && st.rt.color[i]->addr <= log_rt_addr + 0x40000 && st.rt.color[i]->addr + 0x40000 >= log_rt_addr) addr_hit = true;
    if (addr_hit) LOG("[rtaddr] rt0 addr %llx\n", st.rt.color[0] ? st.rt.color[0]->addr : 0);
    if (g_debug_frame || addr_hit || (log_rt_w && st.rt.ncolor && st.rt.color[0] && (int)st.rt.color[0]->width == log_rt_w &&
                          (int)st.rt.color[0]->height == log_rt_h))
        debug_draw(pr, r, indexed);
    resolve_feedback(pr);
    // this draw's writes make snapshots of its attachments stale
    snap_reason = "draw-depthwrite";
    if (st.rt.depth && st.ds[0] && st.ds[1]) snapshots_invalidate(st.rt.depth);  // stencil-only writes: shaders sample depth
    snap_reason = "draw-colorwrite";
    for (int i = 0; i < st.rt.ncolor; i++)
        if (st.rt.color[i] && ((st.channel_mask >> (i * 4)) & 0xF)) snapshots_invalidate(st.rt.color[i]);
    // vertex streams this draw reads (also computed inside the pipeline build on a cache miss)
    uint32_t used_streams = 0;
    for (int i = 0; i < 32; i++) {
        if (!(pr->vi->attr_mask & (1u << i))) continue;
        uint32_t a = i < st.nattrib ? st.attrib[i] : 0x2E;
        if (i >= st.nattrib || (a & 0xFF) == 0) used_streams |= 1u << 31;
        else used_streams |= 1u << ((a >> 8) & 0x1F);
    }
    // A stream the draw would copy now may overlap a compute write the GPU has not run yet (its ssbo range was recorded
    // in dispatch_compute): such a stream is bound straight from the guest buffer the dispatch writes, so the GPU orders
    // the draw after it (no CPU copy of stale data, no flush). BDSP_HZ_FLUSH=1: the old behaviour (flush, then copy).
    static int hz_flush = -1;
    if (hz_flush < 0) hz_flush = getenv("BDSP_HZ_FLUSH") != NULL;
    uint32_t gpu_streams = hz_n ? streams_pending_compute(used_streams) : 0;
    if (hz_flush && gpu_streams) { flush_why(FL_HAZARD); gpu_streams = 0; }
    // arena: copies of both stages' storage buffers, and the streams a dispatch wrote into the arena (both may flush, so before the pass)
    id<MTLBuffer> stream_buf[12] = {nil};
    uint64_t stream_off[12] = {0};
    if (arena_on()) {
        arena_buf_draw[0] = arena_buf_draw[1] = nil;
        if (pr->vi->uses_gmem || pr->fi->uses_gmem) {
            const Range *rr[2] = {st.sbuf[0], st.sbuf[1]};
            const int nn[2] = {pr->vi->uses_gmem ? 16 : 0, pr->fi->uses_gmem ? 16 : 0};
            const uint32_t wm[2] = {pr->vi->uses_gmem_store ? 0xFFFFu : 0, pr->fi->uses_gmem_store ? 0xFFFFu : 0};
            uint64_t *const vv[2] = {arena_va_draw[0], arena_va_draw[1]};
            arena_map(2, rr, nn, wm, vv, arena_buf_draw);
        }
        if (gpu_streams) gpu_streams = arena_streams(gpu_streams, stream_buf, stream_off);
    }
    begin_pass();
    arena_mark_encoded();

    // pipeline
    uint64_t phash = pipeline_state_hash(pr);
    uint32_t pslot = (uint32_t)(phash ^ (phash >> 29)) & (PIPE_TAB - 1);
    while (pipe_tab[pslot].key && pipe_tab[pslot].key != phash) pslot = (pslot + 1) & (PIPE_TAB - 1);
    id<MTLRenderPipelineState> pipe = pipe_tab[pslot].key ? (__bridge id<MTLRenderPipelineState>)pipe_tab[pslot].pipe : nil;
    if (!pipe) {
        PipeRec rec;
        rec_from_state(pr, used_streams, &rec);
        NSString *key = pipe_key(&rec);
        id pobj = cache[key];
        if (!pobj) {
            pobj = build_pipeline(&rec, pr->vs, pr->fs) ?: (id)[NSNull null];
            @synchronized(cache) { cache[key] = pobj; }
            pipe_record_add(&rec);
        }
        if (pobj == [NSNull null]) { stat_skipped++; return; }
        pipe = pobj;
        pipe_tab[pslot].key = phash;
        pipe_tab[pslot].pipe = (__bridge void *)pipe;  // retained by the cache dictionary
    }
    [enc setRenderPipelineState:pipe];

    // depth / stencil
    static uint64_t last_dsk;
    static id<MTLDepthStencilState> last_dss;
    uint64_t dsk = hmix(hmix(hmix(hmix(0xcbf29ce484222325ull, st.ds, 8), &(char){st.rt.depth != NULL}, 1), st.stencil_mask, sizeof st.stencil_mask), st.stencil_vmask, sizeof st.stencil_vmask);
    id<MTLDepthStencilState> dss = dsk == last_dsk ? last_dss : nil;
    NSString *dk = nil;
    if (!dss) {
        dk = [NSString stringWithFormat:@"ds%d %02x%02x%02x%02x%02x%02x%02x%02x %x %x %x %x", st.rt.depth != NULL, st.ds[0], st.ds[1], st.ds[2], st.ds[3],
                    st.ds[4], st.ds[5], st.ds[6], st.ds[7], st.stencil_mask[0], st.stencil_vmask[0], st.stencil_mask[1], st.stencil_vmask[1]];
        dss = cache[dk];
    }
    if (!dss) {
        MTLDepthStencilDescriptor *dd = [MTLDepthStencilDescriptor new];
        static int nodt = -1;
        if (nodt < 0) nodt = getenv("BDSP_NO_DEPTH_TEST") != NULL;
        // no depth target bound: the GPU skips the depth test (Metal would test against nothing and drop everything)
        if (st.ds[0] && !nodt && st.rt.depth) { dd.depthCompareFunction = compare_fn(st.ds[2]); dd.depthWriteEnabled = st.ds[1] != 0; }
        else { dd.depthCompareFunction = MTLCompareFunctionAlways; dd.depthWriteEnabled = NO; }
        if (st.ds[3]) {
            uint32_t ops = st.ds[5] | st.ds[6] << 8 | st.ds[7] << 16;
            for (int f = 0; f < 2; f++) {
                MTLStencilDescriptor *sd = [MTLStencilDescriptor new];
                sd.stencilCompareFunction = compare_fn(f ? st.ds[4] >> 4 : st.ds[4] & 0xF);
                uint32_t o = f ? ops >> 12 : ops;
                sd.stencilFailureOperation = stencil_op(o & 0xF);
                sd.depthFailureOperation = stencil_op((o >> 4) & 0xF);
                sd.depthStencilPassOperation = stencil_op((o >> 8) & 0xF);
                sd.readMask = st.stencil_vmask[f] & 0xFF;
                sd.writeMask = st.stencil_mask[f] & 0xFF;
                if (f) dd.backFaceStencil = sd; else dd.frontFaceStencil = sd;
            }
        }
        dss = [dev newDepthStencilStateWithDescriptor:dd];
        cache[dk] = dss;
    }
    [enc setDepthStencilState:dss];
    last_dsk = dsk;
    last_dss = dss;
    [enc setStencilFrontReferenceValue:st.stencil_ref[0] backReferenceValue:st.stencil_ref[1]];
    [enc setBlendColorRed:st.blend_color[0] green:st.blend_color[1] blue:st.blend_color[2] alpha:st.blend_color[3]];

    // rasterizer
    uint8_t cull = st.poly[0];
    if (vkey.flip_x) cull = 0;  // (mirror mode's composite: one full-screen quad, either winding)
    [enc setCullMode:cull == 1 ? MTLCullModeFront : cull == 2 ? MTLCullModeBack : MTLCullModeNone];
    bool ccw = st.poly[1] == 1;
    [enc setFrontFacingWinding:(ccw != vkey.flip_y) ? MTLWindingCounterClockwise : MTLWindingClockwise];
    [enc setTriangleFillMode:st.poly[2] == 1 ? MTLTriangleFillModeLines : MTLTriangleFillModeFill];
    {   // polygon offset (decals on floors: without it they z-fight). Enables: bit 2 = fill (NVN PolygonOffsetEnable)
        static float last[3] = {0, 0, 0};
        float f[3] = {0, 0, 0};
        static int off = -1;  // BDSP_NO_DEPTH_BIAS: ignore the game's polygon offset (A/B tests)
        if (off < 0) off = getenv("BDSP_NO_DEPTH_BIAS") != NULL;
        if ((st.poly[3] & 4) && !off) memcpy(f, st.poly_offset, sizeof f);
        static int nlog;
        if ((st.poly[3] & 4) && nlog < 3 && getenv("BDSP_LOG_BIAS")) { nlog++; LOG("[bias] factor %g units %g clamp %g\n", st.poly_offset[0], st.poly_offset[1], st.poly_offset[2]); }
        if (memcmp(f, last, sizeof f) || enc != last_bias_enc) {
            [enc setDepthBias:f[1] slopeScale:f[0] clamp:f[2]];
            memcpy(last, f, sizeof f);
            last_bias_enc = enc;
        }
    }
    float *vp = st.viewport[0];
    float zn = st.depth_range[0][0], zf = st.depth_range[0][1];

    // resources
    bind_cbufs(0, pr->vi);
    bind_cbufs(1, pr->fi);
    if (pr->vi->uses_gmem) [enc setVertexBuffer:arena_on() ? arena_buf_draw[0] : gpu_guest_buffer() offset:0 atIndex:GMEM_BUFFER_INDEX];
    static id<MTLBuffer> dbgvs;
    bool dbg_this = maxwell_dbg_vs && (const uint8_t *)(uintptr_t)st.program->stages[0].code_addr == maxwell_dbg_vs;
    if (dbg_this) {
        if (!dbgvs) dbgvs = [dev newBufferWithLength:2 * 64 * 8 * 16 options:MTLResourceStorageModeShared];
        memset(dbgvs.contents, 0xff, 2 * 64 * 8 * 16);
        [enc setVertexBuffer:dbgvs offset:0 atIndex:DBG_VS_BUFFER_INDEX];
    }
    if (pr->fi->uses_gmem) [enc setFragmentBuffer:arena_on() ? arena_buf_draw[1] : gpu_guest_buffer() offset:0 atIndex:GMEM_BUFFER_INDEX];
    id<MTLBuffer> geom_buf = vkey.dbg_pos ? geom_bind(enc, geom.scan) : nil;
    bind_textures(0, pr->vi);
    bind_textures(1, pr->fi);
    extern bool pets_hide_item_cursor(void);  // (the cursor is on the companion card: runtime/hle/pets.c)
    if (draw_item_cursor && pets_hide_item_cursor()) { stat_skipped++; return; }
    vp_sx = pass_sx; vp_sy = pass_sy; vp_ox = 0; vp_oy = 0;
    if (fabsf(pass_sx - pass_sy) > 0.01f * pass_sy && st.rt.ncolor && renderer_texture_presented(st.rt.color[0])) {
        // Draws into the swapchain image: draws that sample the full-size reshaped scene (the final
        // composite, blurred menu backgrounds) and untextured full-screen fades fill the window; everything
        // else (HUD, text, menus, movie frames) goes into a centred 16:9 box.
        bool reads_scene = false;  // samples a reshaped texture the size of the framebuffer (the scene itself)
        for (int i = 0; i < pr->fi->ntex && i < 64; i++)
            if ((tex_sc[1][i][0] != 1 || tex_sc[1][i][1] != 1) && tex_wh[1][i][0] == st.rt.color[0]->width &&
                tex_wh[1][i][1] == st.rt.color[0]->height)
                reads_scene = true;
        // Full-screen overlays without textures (fades, flashes) cover the whole window too.
        bool fullscreen_quad = r->x[2] <= 6 && st.viewport[0][0] == 0 && st.viewport[0][1] == 0 &&
                               st.viewport[0][2] >= st.rt.color[0]->width && st.viewport[0][3] >= st.rt.color[0]->height;
        bool fullscreen_fill = pr->fi->ntex == 0 && fullscreen_quad;
        // A full-screen quad sampling a reshaped (screen-shaped) texture is a scene background too, even a
        // downscaled one: the blurred scene behind the pause menu reads a 192x108 copy.
        // (single-texture draws only: the menu's frosted panels sample the same blurred copy but are UI pieces)
        if (fullscreen_quad && !reads_scene && pr->fi->ntex == 1 && (tex_sc[1][0][0] != 1 || tex_sc[1][0][1] != 1))
            reads_scene = true;
        extern uint64_t renderer_present_count(void);
        static uint64_t wide_frame = ~0ull;  // the latest draw this frame filled the window (nothing boxed since)
        if (reads_scene) wide_frame = renderer_present_count();
        // Black or white fills are fades and flashes: always the whole window. Coloured ones (the file-select
        // tint) stay boxed unless they directly follow the composite. Colour = first fragment cbuf (rgb).
        bool fade_fill = false;
        if (fullscreen_fill && st.ubuf[1][0].addr && st.ubuf[1][0].size >= 12) {
            const float *c = (const float *)(uintptr_t)st.ubuf[1][0].addr;
            bool black = c[0] < 0.01f && c[1] < 0.01f && c[2] < 0.01f, white = c[0] > 0.99f && c[1] > 0.99f && c[2] > 0.99f;
            fade_fill = black || white;
        }
        bool composite = reads_scene || fade_fill || (fullscreen_fill && wide_frame == renderer_present_count());
        if (!composite) wide_frame = ~0ull;
        static int log_fills = -1;  // BDSP_LOG_FILLS: every full-screen untextured fill (fs hash, colour cbuf, decision)
        if (log_fills < 0) log_fills = getenv("BDSP_LOG_FILLS") != NULL;
        if (log_fills && fullscreen_fill) {
            static uint64_t lastf; static int nthis;
            uint64_t f = renderer_present_count();
            if (f != lastf) { lastf = f; nthis = 0; }
            if (nthis++ < 4 && f % 6 == 0) {
                const float *c = st.ubuf[1][0].addr ? (const float *)(uintptr_t)st.ubuf[1][0].addr : NULL;
                LOG("[fill] frame %llu fs=%llx composite %d cb0 %g %g %g %g | %g %g %g %g\n", (unsigned long long)f,
                    st.program->stages[1].code_addr, composite, c ? c[0] : -1, c ? c[1] : -1, c ? c[2] : -1, c ? c[3] : -1,
                    c ? c[4] : -1, c ? c[5] : -1, c ? c[6] : -1, c ? c[7] : -1);
            }
        }
        if (g_debug_frame && getenv("BDSP_LOG_UI")) {
            LOG("[ui2] fs=%llx count %llu ntex %d reads_scene %d fill %d quad %d -> %d |", st.program->stages[1].code_addr, r->x[2],
                pr->fi->ntex, reads_scene, fullscreen_fill, fullscreen_quad, composite);
            for (int i = 0; i < pr->fi->ntex && i < 4; i++)
                LOG(" t%d %dx%d sc %.2f,%.2f", i, tex_wh[1][i][0], tex_wh[1][i][1], tex_sc[1][i][0], tex_sc[1][i][1]);
            LOG(" | rt %ux%u vp %.0f,%.0f %.0fx%.0f\n", st.rt.color[0]->width, st.rt.color[0]->height, st.viewport[0][0],
                st.viewport[0][1], st.viewport[0][2], st.viewport[0][3]);
        }
        if (!composite) {  // centred 16:9 region with a uniform scale
            int pw, ph;
            pass_size(&pw, &ph);
            float u = fminf(pass_sx, pass_sy);
            vp_sx = vp_sy = u;
            vp_ox = (pw - st.rt.color[0]->width * u) * 0.5f;
            vp_oy = (ph - st.rt.color[0]->height * u) * 0.5f;
        }
    }
    {   // camera-attached effects sized for 16:9 are widened with the view (runtime/hle/widescreen.c)
        extern float widescreen_effect_stretch(uint64_t fs_hash);
        float k = widescreen_effect_stretch(g_cur_fs_hash);
        double vx = vp[0] * vp_sx + vp_ox, vw = vp[2] * vp_sx;
        if (k > 1.0f) { vx -= vw * (k - 1) / 2; vw *= k; }
        [enc setViewport:(MTLViewport){vx, vp[1] * vp_sy + vp_oy, vw, vp[3] * vp_sy, zn, zf}];
    }
    apply_scissor();
    if (pr->fi->uses_rscale) {  // [0] = render target scale, [1 + i] = scale of texture i
        float rs[66][4] = {{vp_sx, vp_sy, vp_ox, vp_oy}};
        for (int i = 0; i < pr->fi->ntex && i < 64; i++) { rs[1 + i][0] = tex_sc[1][i][0]; rs[1 + i][1] = tex_sc[1][i][1]; }
        if (fkey.flip_x) rs[65][0] = (float)st.rt.color[0]->width;  // (mirror mode: the composite's width, guest pixels)
        [enc setFragmentBytes:rs length:(NSUInteger)(fkey.flip_x ? 66 : 1 + pr->fi->ntex) * 16 atIndex:RSCALE_BUFFER_INDEX];
    }
    if (st.ubuf[0][2].addr && st.ubuf[0][2].size >= 48 && !(st.ubuf[0][2].addr & 3)) {  // cut bushes' items
        extern void pot_item_draw(float *m);                                                 // (runtime/hle/pot_glow.c)
        pot_item_draw((float *)(uintptr_t)st.ubuf[0][2].addr);
    }
    if (ENV("BDSP_POT_PROBE") && st.ubuf[0][2].addr && st.ubuf[0][2].size >= 48) {  // (debug: bush / pot draws)
        extern void pot_probe(const float *m, bool tintable, uint64_t mesh, uint32_t inst);
        uint32_t ninst = indexed ? (uint32_t)r->x[6] : (uint32_t)r->x[4];
        pot_probe((const float *)(uintptr_t)st.ubuf[0][2].addr, 0, st.vbuf[0].addr, ninst);
        extern uint64_t renderer_present_count(void);
        static uint64_t pf; static int pn;
        if (renderer_present_count() != pf) { pf = renderer_present_count(); pn = 0; }
        if (ninst > 1 && pf % 300 == 0 && pn++ < 40) {
            const float *m = (const float *)(uintptr_t)st.ubuf[0][2].addr;
            LOG("[potprobe] instanced x%u count %u tint %d ubuf sizes %u %u %u %u %u %u  m2 t (%.2f %.2f %.2f)\n", ninst,
                (uint32_t)r->x[2], 0, (unsigned)st.ubuf[0][0].size, (unsigned)st.ubuf[0][1].size,
                (unsigned)st.ubuf[0][2].size, (unsigned)st.ubuf[0][3].size, (unsigned)st.ubuf[0][4].size,
                (unsigned)st.ubuf[0][5].size, m[3], m[7], m[11]);
            for (int i = 0; i < st.nattrib; i++) LOG(" a%d(f%#x s%u o%u)", i, st.attrib[i] & 0xFF, (st.attrib[i] >> 8) & 0x1F, st.attrib[i] >> 13);
            for (int i = 0; i < 12; i++)
                if (st.vbuf[i].addr && i < st.nstream && st.stream[i][1]) {
                    const float *v = (const float *)(uintptr_t)st.vbuf[i].addr;
                    LOG(" vb%d(size %llu stride %u div %u: %.2f %.2f %.2f %.2f | %.2f %.2f %.2f %.2f | %.2f %.2f %.2f %.2f)", i,
                        st.vbuf[i].size, st.stream[i][0], st.stream[i][1], v[0], v[1], v[2], v[3], v[4], v[5], v[6], v[7], v[8], v[9], v[10], v[11]);
                }
            LOG("\n");
            for (int i = 0; i < 4; i++)
                if (st.sbuf[0][i].addr) {
                    const float *f = (const float *)(uintptr_t)st.sbuf[0][i].addr;
                    LOG("   ssbo%d size %llu:", i, st.sbuf[0][i].size);
                    for (int k = 0; k < 48 && k * 4 < (int)st.sbuf[0][i].size; k++) LOG(" %.2f", f[k]);
                    LOG("\n");
                }
        }
    }
    if (0) {  // per-draw highlight tint (golden unchecked pots, runtime/hle/pot_glow.c)
        float tint[8] = {0};
        extern bool pot_tint(const float *m, float tint[8], uint64_t mesh);
        extern bool pot_glow_active(void);
        if (st.ubuf[0][2].addr && st.ubuf[0][2].size >= 48 && pot_glow_active())
            pot_tint((const float *)(uintptr_t)st.ubuf[0][2].addr, tint, st.vbuf[0].addr);
        if (draw_bottle) {  // the gold Escape Bottle (runtime/hle/escape.c): its item icon / held-up model
            extern void escape_bottle_tint(int kind, const float *ui, uint32_t ui_size, float tint[8]);
            int u = draw_bottle == 3 ? 3 : 0;  // (the fairy model: its bone matrices, for where it stands - souls.c)
            escape_bottle_tint(draw_bottle, (const float *)(uintptr_t)st.ubuf[0][u].addr, (uint32_t)st.ubuf[0][u].size, tint);
        }
        if (draw_heart) { extern void texpatch_heart_tint(int kind, float tint[8]); texpatch_heart_tint(draw_heart, tint); }
        [enc setFragmentBytes:tint length:sizeof tint atIndex:19];
    }
    // A vertex-rate stream is copied only as far as the draw's indices reach (static meshes sit in large buffers: copying
    // whole streams was ~5.6 GB/s of memcpy in the render worker). BDSP_FULL_VB=1: copy whole streams.
    static int full_vb = -1;
    if (full_vb < 0) full_vb = getenv("BDSP_FULL_VB") != NULL;
    uint64_t vlo = 0, vhi = 0;
    bool have_range = !full_vb && draw_vertex_range(r, indexed, &vlo, &vhi);
    for (int s = 0; s < 12; s++) {
        if (!(used_streams & (1u << s))) continue;
        Range v = st.vbuf[s];
        uint64_t size = v.size ? v.size : 16, skip = 0;
        uint32_t stride = s < st.nstream ? st.stream[s][0] : 0, div = s < st.nstream ? st.stream[s][1] : 0;
        if (have_range && stride && !div) {
            uint64_t need = (vhi + 1) * stride;
            if (need < size) size = need;
            skip = vlo * stride;
            if (skip > size) skip = 0;
        }
        if (v.addr && (gpu_streams & (1u << s)) && arena_on())
            [enc setVertexBuffer:stream_buf[s] offset:stream_off[s] atIndex:18 + s];
        else if (v.addr && (gpu_streams & (1u << s)) && v.addr >= HEAP_BASE && v.addr + (v.size ? v.size : 16) <= HEAP_BASE + HEAP_MAX && !(v.addr & 3))
            [enc setVertexBuffer:gpu_guest_buffer() offset:v.addr - HEAP_BASE atIndex:18 + s];
        else if (v.addr) bind_guest(enc, true, v.addr, size, 18 + s, skip);
        else { static const float zero[4]; [enc setVertexBytes:zero length:16 atIndex:18 + s]; }
    }
    if (used_streams & (1u << 31)) { static const float zero[4] = {0, 0, 0, 1}; [enc setVertexBytes:zero length:16 atIndex:30]; }

    // Instanced draws with item spots among their instances (bushsanity: bushes are drawn in batches, each instance's
    // model matrix in vertex storage buffer 0, indexed by instance id): drawn as runs of instances, gold runs tinted.
    // (Metal's instance_id includes the base instance, so a run [b + k, b + k + n) draws exactly those instances.)
    uint32_t inst_all = indexed ? (uint32_t)r->x[6] : (uint32_t)r->x[4], base_all = indexed ? (uint32_t)r->x[5] : (uint32_t)r->x[3];
    if (!inst_all) inst_all = 1;
    enum { MAX_RUNS = 64 };
    uint32_t run_at[MAX_RUNS], run_n[MAX_RUNS];
    bool run_gold[MAX_RUNS];
    int nruns = 0;
    if (0 && inst_all > 1 && st.sbuf[0][0].addr) {
        extern bool pot_glow_active(void);
        extern bool pot_instance_gold(const float *m);
        uint64_t recs = st.sbuf[0][0].size / 64;
        if (pot_glow_active() && (uint64_t)base_all + inst_all <= recs) {
            const float *m = (const float *)(uintptr_t)st.sbuf[0][0].addr;
            for (uint32_t k = 0; k < inst_all; k++) {
                bool g = pot_instance_gold(m + (size_t)(base_all + k) * 16);
                if (nruns && run_gold[nruns - 1] == g) { run_n[nruns - 1]++; continue; }
                if (nruns == MAX_RUNS) { nruns = 0; break; }  // (too fragmented: draw as is)
                run_at[nruns] = k; run_n[nruns] = 1; run_gold[nruns] = g; nruns++;
            }
            if (nruns == 1 && !run_gold[0]) nruns = 0;
        }
    }
    if (!nruns) { run_at[0] = 0; run_n[0] = inst_all; nruns = 1; run_gold[0] = false; }
    for (int ri = 0; ri < nruns; ri++) {
    if (nruns > 1 || run_gold[0]) {
        float tint[8] = {0};
        extern void pot_gold_tint(float tint[8]);
        if (run_gold[ri]) pot_gold_tint(tint);
        [enc setFragmentBytes:tint length:sizeof tint atIndex:19];
    }
    // draw
    bool native;
    uint32_t mode = (uint32_t)r->x[0];
    MTLPrimitiveType pt = prim_type(mode, &native);
    if (!indexed) {
        uint32_t first = (uint32_t)r->x[1], count = (uint32_t)r->x[2], base_inst = base_all + run_at[ri], inst = run_n[ri];
        if (native) {
            [enc drawPrimitives:pt vertexStart:first vertexCount:count instanceCount:inst baseInstance:base_inst];
        } else if (mode == 6 || mode == 7 || mode == 9) {
            uint32_t n;
            id<MTLBuffer> ib = expand_indices(mode, count, NULL, 0, first, &n);
            [enc drawIndexedPrimitives:MTLPrimitiveTypeTriangle indexCount:n indexType:MTLIndexTypeUInt32 indexBuffer:ib
                     indexBufferOffset:0 instanceCount:inst baseVertex:0 baseInstance:base_inst];
        } else { stat_skipped++; return; }
    } else {
        uint32_t itype = (uint32_t)r->x[1], count = (uint32_t)r->x[2];
        uint64_t iaddr = r->x[3];
        int32_t base_vertex = (int32_t)r->x[4];
        uint32_t base_inst = base_all + run_at[ri], inst = run_n[ri];
        if (native && itype != 0) {
            MTLIndexType it = itype == 1 ? MTLIndexTypeUInt16 : MTLIndexTypeUInt32;
            uint32_t isz = itype == 1 ? 2 : 4;
            id<MTLBuffer> ib;
            uint64_t ioff;
            if (guest_heap_ok(iaddr, (uint64_t)count * isz) && (iaddr % isz) == 0) {
                ib = g_guest_buffer; ioff = iaddr - HEAP_BASE;
            } else {
                ring_site = 3;
                ioff = ring_alloc((void *)(uintptr_t)iaddr, (uint64_t)count * isz); ib = ring;
            }
            [enc drawIndexedPrimitives:pt indexCount:count indexType:it indexBuffer:ib indexBufferOffset:ioff
                         instanceCount:inst baseVertex:base_vertex baseInstance:base_inst];
        } else {
            uint32_t n;
            id<MTLBuffer> ib;
            if (native) {  // 8-bit indices: widen
                uint32_t *w = malloc(count * 4 + 4);
                for (uint32_t i = 0; i < count; i++) w[i] = ((const uint8_t *)(uintptr_t)iaddr)[i];
                ib = [dev newBufferWithBytes:w length:count * 4 + 4 options:MTLResourceStorageModeShared];
                free(w);
                n = count;
            } else {
                ib = expand_indices(mode, count, (const void *)(uintptr_t)iaddr, (int)itype, 0, &n);
                pt = MTLPrimitiveTypeTriangle;
            }
            [enc drawIndexedPrimitives:pt indexCount:n indexType:MTLIndexTypeUInt32 indexBuffer:ib indexBufferOffset:0
                         instanceCount:inst baseVertex:base_vertex baseInstance:base_inst];
        }
    }
    }  // runs
    stat_draws++;
    if (geom_buf) geom_report(r, indexed, geom_buf, &vkey, geom.frame);  // render_debug.inc
    if (dbg_this) {
        static int nlog;
        if (nlog++ < 4) {
            renderer_flush();
            const float *f = dbgvs.contents;
            LOG("[dbgvs] draw %d:", nlog);
            for (int i = 0; i < 2; i++)
                for (int v = 0; v < 4; v++) LOG(" i%d v%d (%g %g %g %g) uv(%g %g %g)", i, v, f[(i * 8 + v) * 4], f[(i * 8 + v) * 4 + 1], f[(i * 8 + v) * 4 + 2], f[(i * 8 + v) * 4 + 3],
                                                f[(512 + i * 8 + v) * 4], f[(512 + i * 8 + v) * 4 + 1], f[(512 + i * 8 + v) * 4 + 2]);
            LOG("\n");
        }
    }
}

// ------------------------------------------------------------------ texture copies
typedef struct { uint64_t tex; NvnTextureView view; uint8_t has_view; int32_t region[6]; } TexRefRec;

static const char *copy_src =
    "#include <metal_stdlib>\nusing namespace metal;\n"
    "struct V { float4 pos [[position]]; float2 uv; };\n"
    "vertex V vs(uint vid [[vertex_id]], constant float4 &r [[buffer(0)]]) {\n"
    "  float2 p = float2((vid << 1) & 2, vid & 2); V o; o.pos = float4(p.x * 2 - 1, 1 - p.y * 2, 0, 1);\n"
    "  o.uv = r.xy + p * r.zw; return o; }\n"
    "fragment float4 fs(V in [[stage_in]], texture2d<float> t [[texture(0)]], sampler s [[sampler(0)]]) {\n"
    "  return t.sample(s, in.uv); }\n"
    "struct D { float d [[depth(any)]]; };\n"
    "fragment D fs_depth(V in [[stage_in]], depth2d<float> t [[texture(0)]], sampler s [[sampler(0)]]) {\n"
    "  D o; o.d = t.sample(s, in.uv); return o; }\n";

// Bytes per block of the Metal texture backing an NVN format (RGB8 is expanded to RGBA8 on the host).
static uint64_t renderer_pixel_format_bytes(MTLPixelFormat pf, uint64_t nvn_bpb) {
    (void)pf;
    return nvn_bpb == 3 ? 4 : nvn_bpb;
}

// Linear guest memory <-> texture region. Row/image strides of 0 mean tightly packed.
static void copy_region_dims(NvnTexture *t, const TexRefRec *ref, const FormatInfo **fi, int32_t rg[6], int *level,
                             uint64_t *row, uint64_t *img) {
    *fi = nvn_format_info(t->format);
    memcpy(rg, ref->region, sizeof ref->region);
    if (!rg[3]) rg[3] = (int32_t)t->width;
    if (!rg[4]) rg[4] = (int32_t)t->height;
    if (!rg[5]) rg[5] = 1;
    *level = ref->has_view && (ref->view.setmask & 1) ? ref->view.base_level : 0;
    uint32_t wb = ((uint32_t)rg[3] + (*fi)->bw - 1) / (*fi)->bw, hb = ((uint32_t)rg[4] + (*fi)->bh - 1) / (*fi)->bh;
    *row = st.copy_row_stride ? st.copy_row_stride : (uint64_t)wb * (*fi)->bpb;
    *img = st.copy_image_stride ? st.copy_image_stride : *row * hb;
}

static void copy_buffer_to_texture(uint64_t src, const TexRefRec *dst) {
    snap_reason = "buf2tex"; snapshots_invalidate(NULL);
    NvnTexture *t = (NvnTexture *)(uintptr_t)dst->tex;
    if (!t || !src) return;
    end_pass();
    const FormatInfo *fi;
    int32_t rg[6];
    int level;
    uint64_t row, img;
    copy_region_dims(t, dst, &fi, rg, &level, &row, &img);
    if (!fi || !fi->bpb) return;
    static int nlog;
    if (nlog++ < 20) LOG("[copy] buf %llx -> tex %ux%u f%#x region %d,%d,%d %dx%dx%d row %llu lvl %d\n", src, t->width, t->height, t->format, rg[0], rg[1], rg[2], rg[3], rg[4], rg[5], row, level);
    id<MTLBlitCommandEncoder> b = [cb() blitCommandEncoder];
    id<MTLTexture> tex = renderer_texture(t, b, false);  // make sure prior CPU contents are uploaded first
    renderer_mark_gpu_owned(t);
    bool array = tex.textureType == MTLTextureType2DArray || tex.textureType == MTLTextureTypeCube;
    uint32_t hb = ((uint32_t)rg[4] + fi->bh - 1) / fi->bh, wb = ((uint32_t)rg[3] + fi->bw - 1) / fi->bw;
    uint64_t mtl_bpb = renderer_pixel_format_bytes(tex.pixelFormat, fi->bpb);
    for (int z = 0; z < (array ? rg[5] : 1); z++) {
        const uint8_t *s = (const uint8_t *)(uintptr_t)(src + (uint64_t)z * img);
        uint64_t out_row = (uint64_t)wb * mtl_bpb, out_rows = hb;
        uint8_t *data = malloc(out_row * hb * (array ? 1 : rg[5]));
        for (int d = 0; d < (array ? 1 : rg[5]); d++)
            for (uint32_t y = 0; y < hb; y++) {
                const uint8_t *sr = s + (uint64_t)d * img + (uint64_t)y * row;
                uint8_t *dr = data + ((uint64_t)d * hb + y) * out_row;
                if (mtl_bpb == fi->bpb) memcpy(dr, sr, out_row);
                else if (fi->bpb == 3 && mtl_bpb == 4)
                    for (uint32_t x = 0; x < wb; x++) { memcpy(dr + x * 4, sr + x * 3, 3); dr[x * 4 + 3] = 255; }
                else memset(dr, 0, out_row);
            }
        extern bool renderer_no_bc(void);
        if (renderer_no_bc() && bctc_kind(t->format)) {   // GPU without BC (metal.m): the packed blocks are converted
            uint32_t crow, crows;
            uint8_t *c = bctc_convert(t->format, data, wb, hb, array ? 1 : (uint32_t)rg[5], &crow, &crows);
            free(data);
            data = c;
            out_row = crow;
            out_rows = crows;
        }
        id<MTLBuffer> staging = [dev newBufferWithBytes:data length:out_row * out_rows * (array ? 1 : rg[5])
                                                options:MTLResourceStorageModeShared];
        free(data);
        [b copyFromBuffer:staging sourceOffset:0 sourceBytesPerRow:out_row sourceBytesPerImage:out_row * out_rows
               sourceSize:MTLSizeMake(rg[3], rg[4], array ? 1 : rg[5]) toTexture:tex
         destinationSlice:array ? rg[2] + z : 0 destinationLevel:level
        destinationOrigin:MTLOriginMake(rg[0], rg[1], array ? 0 : rg[2])];
    }
    [b endEncoding];
}

// Color copy with scaling: draw src rect into dst rect (physical texels).
static id<MTLTexture> copy_raw_view(id<MTLTexture> t) {
    MTLPixelFormat pf = t.pixelFormat;
    MTLPixelFormat raw = pf == MTLPixelFormatRGBA8Unorm_sRGB ? MTLPixelFormatRGBA8Unorm
                       : pf == MTLPixelFormatBGRA8Unorm_sRGB ? MTLPixelFormatBGRA8Unorm : pf;
    if (raw == pf) return t;
    id<MTLTexture> v = [t newTextureViewWithPixelFormat:raw];
    return v ? v : t;
}

static void draw_copy(id<MTLTexture> s, int sx0, int sy0, int sw, int sh, id<MTLTexture> d, int dx0, int dy0, int dw, int dh,
                      bool linear) {
    static int raw = -1;  // BDSP_COPY_RAW_SRGB: copies move values unchanged (no sRGB decode/encode on either side)
    if (raw < 0) raw = getenv("BDSP_COPY_RAW_SRGB") != NULL;
    if (raw) { s = copy_raw_view(s); d = copy_raw_view(d); }
    MTLRenderPassDescriptor *rp = [MTLRenderPassDescriptor renderPassDescriptor];
    rp.colorAttachments[0].texture = d;
    rp.colorAttachments[0].loadAction = MTLLoadActionLoad;
    rp.colorAttachments[0].storeAction = MTLStoreActionStore;
    id<MTLRenderCommandEncoder> e = [cb() renderCommandEncoderWithDescriptor:rp];
    NSString *key = [NSString stringWithFormat:@"copy %lu", (unsigned long)d.pixelFormat];
    id<MTLRenderPipelineState> pipe = cache[key];
    if (!pipe) {
        static id<MTLLibrary> lib;
        if (!lib) lib = TIMED_COMPILE([dev newLibraryWithSource:@(copy_src) options:nil error:nil]);
        MTLRenderPipelineDescriptor *pd = [MTLRenderPipelineDescriptor new];
        pd.vertexFunction = [lib newFunctionWithName:@"vs"];
        pd.fragmentFunction = [lib newFunctionWithName:@"fs"];
        pd.colorAttachments[0].pixelFormat = d.pixelFormat;
        pipe = TIMED_COMPILE([dev newRenderPipelineStateWithDescriptor:pd error:nil]);
        cache[key] = pipe;
    }
    static id<MTLSamplerState> lin, near;
    if (!lin) {
        MTLSamplerDescriptor *sd = [MTLSamplerDescriptor new];
        near = [dev newSamplerStateWithDescriptor:sd];
        sd.minFilter = sd.magFilter = MTLSamplerMinMagFilterLinear;
        lin = [dev newSamplerStateWithDescriptor:sd];
    }
    float r[4] = {(float)sx0 / s.width, (float)sy0 / s.height, (float)sw / s.width, (float)sh / s.height};
    [e setRenderPipelineState:pipe];
    [e setViewport:(MTLViewport){dx0, dy0, dw, dh, 0, 1}];
    [e setVertexBytes:r length:16 atIndex:0];
    [e setFragmentTexture:s atIndex:0];
    [e setFragmentSamplerState:linear ? lin : near atIndex:0];
    [e drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];
    [e endEncoding];
    stat_passes++;
}

static void copy_texture_to_buffer(const TexRefRec *src, uint64_t dst) {
    NvnTexture *t = (NvnTexture *)(uintptr_t)src->tex;
    if (!t || !dst || dst < HEAP_BASE) return;
    end_pass();
    const FormatInfo *fi;
    int32_t rg[6];
    int level;
    uint64_t row, img;
    copy_region_dims(t, src, &fi, rg, &level, &row, &img);
    if (!fi || !fi->bpb) return;
    {
        static int nlog;
        if (nlog++ < 12 || getenv("BDSP_LOG_READBACK"))
            LOG("[readback] tex %ux%u f%#x level %d region %d,%d %dx%d -> %llx row %llu\n", t->width, t->height,
                t->format, level, rg[0], rg[1], rg[3], rg[4], dst, row);
    }
    id<MTLTexture> tex = renderer_texture(t, nil, false);
    float tsx, tsy;
    renderer_texture_scale(t, &tsx, &tsy);
    if ((tsx != 1 || tsy != 1) && level == 0 && !renderer_format_is_depth(t->format)) {
        // the CPU expects guest-sized texels: filter the scaled allocation down first
        MTLTextureDescriptor *td = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:tex.pixelFormat width:t->width
                                                                                      height:t->height mipmapped:NO];
        td.usage = MTLTextureUsageRenderTarget | MTLTextureUsageShaderRead;
        td.storageMode = MTLStorageModePrivate;
        id<MTLTexture> small = [dev newTextureWithDescriptor:td];
        draw_copy(tex, 0, 0, tex.width, tex.height, small, 0, 0, t->width, t->height, true);
        tex = small;
    }
    id<MTLBlitCommandEncoder> b = [cb() blitCommandEncoder];
    if (renderer_pixel_format_bytes(tex.pixelFormat, fi->bpb) != fi->bpb) { [b endEncoding]; return; }
    bool array = tex.textureType == MTLTextureType2DArray || tex.textureType == MTLTextureTypeCube;
    // arena mode: through a staging buffer that starts as a copy of the guest bytes (the copy skips row padding), then back
    uint64_t total = img * (uint64_t)(rg[5] > 0 ? rg[5] : 1);
    id<MTLBuffer> staging = arena_on() ? [dev newBufferWithBytes:(const void *)GA(dst) length:total options:MTLResourceStorageModeShared] : nil;
    for (int z = 0; z < (array ? rg[5] : 1); z++)
        [b copyFromTexture:tex sourceSlice:array ? rg[2] + z : 0 sourceLevel:level
              sourceOrigin:MTLOriginMake(rg[0], rg[1], array ? 0 : rg[2])
                sourceSize:MTLSizeMake(rg[3], rg[4], array ? 1 : rg[5]) toBuffer:staging ?: g_guest_buffer
         destinationOffset:(staging ? 0 : dst - HEAP_BASE) + (uint64_t)z * img destinationBytesPerRow:row destinationBytesPerImage:img];
    [b endEncoding];
    flush_why(FL_READBACK);  // the CPU may read the result right after the fence
    if (staging) memcpy((void *)GA(dst), staging.contents, total);
}

static void copy_texture(const TexRefRec *src, const TexRefRec *dst, uint64_t flags) {
    snap_reason = "tex2tex"; snapshots_invalidate(NULL);
    NvnTexture *st_ = (NvnTexture *)(uintptr_t)src->tex, *dt = (NvnTexture *)(uintptr_t)dst->tex;
    if (!st_ || !dt) return;
    end_pass();
    id<MTLTexture> s = sampled_texture(st_, &src->view, src->has_view, TEXTYPE_2D);
    renderer_mark_gpu_owned(dt);
    id<MTLTexture> d = view_texture(dt, &dst->view, dst->has_view, true, nil);
    // a full copy into a swapchain image: the source is the frame's final framebuffer (UI is drawn there)
    extern void renderer_texture_mark_presented(NvnTexture *t);
    if (renderer_texture_presented(dt) && st_->width == dt->width && st_->height == dt->height)
        renderer_texture_mark_presented(st_);
    extern bool renderer_texture_first_write(NvnTexture *t);
    renderer_texture_first_write(dt);  // a copy fills the image: no clear afterwards this frame
    extern bool renderer_texture_level_fresh(NvnTexture *t);
    renderer_texture_level_fresh(dt);  // nor a level-change clear
    const int32_t *sr = src->region, *dr = dst->region;
    if (g_debug_frame) {
        static int nl;
        uint64_t total = tegra_total_size(&st_->layout), nz = 0;
        for (uint64_t k = 0; k < total && st_->addr; k++) nz += ((const uint8_t *)(uintptr_t)st_->addr)[k] != 0;
        if (nl < 400) LOG("[copytex] src addr %llx size %llu nonzero %llu tflags %#x stride %u bh %u\n", st_->addr, total, nz, st_->flags, st_->stride, st_->layout.block_height_log2);
        if (nl++ < 400) LOG("[copytex] %ux%u f%#x (%d,%d %dx%d) -> %ux%u f%#x (%d,%d %dx%d) flags %llx src_gpu %d\n", st_->width, st_->height, st_->format,
            sr[0], sr[1], sr[3], sr[4], dt->width, dt->height, dt->format, dr[0], dr[1], dr[3], dr[4], flags, renderer_is_gpu_owned(st_));
    }
    // regions are in guest texels; scaled allocations (output resolution) need physical texels
    float ssx, ssy, dsx, dsy;
    renderer_texture_scale(st_, &ssx, &ssy);
    renderer_texture_scale(dt, &dsx, &dsy);
    int sx0 = (int)lroundf(sr[0] * ssx), sy0 = (int)lroundf(sr[1] * ssy);
    int dx0 = (int)lroundf(dr[0] * dsx), dy0 = (int)lroundf(dr[1] * dsy);
    int sw = sr[3] ? (int)lroundf(sr[3] * ssx) : (int)s.width, sh = sr[4] ? (int)lroundf(sr[4] * ssy) : (int)s.height;
    int dw = dr[3] ? (int)lroundf(dr[3] * dsx) : (int)d.width, dh = dr[4] ? (int)lroundf(dr[4] * dsy) : (int)d.height;
    static int no_depth_scale = -1;
    if (no_depth_scale < 0) no_depth_scale = getenv("BDSP_NO_DEPTH_SCALE") != NULL;
    if (!no_depth_scale && renderer_format_is_depth(dt->format) && (sw != dw || sh != dh) && s.sampleCount == 1 && dt->format != 0x31) {
        // scaled depth copy (the game builds its depth pyramid this way): draw, writing fragment depth
        MTLRenderPassDescriptor *drp = [MTLRenderPassDescriptor renderPassDescriptor];
        drp.depthAttachment.texture = d;
        drp.depthAttachment.loadAction = MTLLoadActionLoad;
        drp.depthAttachment.storeAction = MTLStoreActionStore;
        if (renderer_format_has_stencil(dt->format)) {
            drp.stencilAttachment.texture = d;
            drp.stencilAttachment.loadAction = MTLLoadActionLoad;
            drp.stencilAttachment.storeAction = MTLStoreActionStore;
        }
        id<MTLRenderCommandEncoder> e = [cb() renderCommandEncoderWithDescriptor:drp];
        NSString *key = [NSString stringWithFormat:@"copydepth %lu", (unsigned long)d.pixelFormat];
        id<MTLRenderPipelineState> pipe = cache[key];
        if (!pipe) {
            static id<MTLLibrary> dlib;
            NSError *derr = nil;
            if (!dlib) dlib = TIMED_COMPILE([dev newLibraryWithSource:@(copy_src) options:nil error:&derr]);
            if (!dlib) LOG("[copy] depth copy library: %s\n", derr.localizedDescription.UTF8String);
            MTLRenderPipelineDescriptor *pd = [MTLRenderPipelineDescriptor new];
            pd.vertexFunction = [dlib newFunctionWithName:@"vs"];
            pd.fragmentFunction = [dlib newFunctionWithName:@"fs_depth"];
            pd.depthAttachmentPixelFormat = d.pixelFormat;
            if (renderer_format_has_stencil(dt->format)) pd.stencilAttachmentPixelFormat = d.pixelFormat;
            NSError *perr = nil;
            pipe = TIMED_COMPILE([dev newRenderPipelineStateWithDescriptor:pd error:&perr]);
            if (!pipe) { LOG("[copy] depth copy pipeline: %s\n", perr.localizedDescription.UTF8String); return; }
            cache[key] = pipe;
        }
        static id<MTLDepthStencilState> always;
        if (!always) {
            MTLDepthStencilDescriptor *dd = [MTLDepthStencilDescriptor new];
            dd.depthCompareFunction = MTLCompareFunctionAlways;
            dd.depthWriteEnabled = YES;
            always = [dev newDepthStencilStateWithDescriptor:dd];
        }
        static id<MTLSamplerState> dnear;
        if (!dnear) dnear = [dev newSamplerStateWithDescriptor:[MTLSamplerDescriptor new]];
        id<MTLTexture> sdepth = s;
        if (s.pixelFormat == MTLPixelFormatDepth32Float_Stencil8 || s.pixelFormat == MTLPixelFormatDepth24Unorm_Stencil8)
            sdepth = [s newTextureViewWithPixelFormat:s.pixelFormat];
        float r[4] = {(float)sx0 / s.width, (float)sy0 / s.height, (float)sw / s.width, (float)sh / s.height};
        [e setRenderPipelineState:pipe];
        [e setDepthStencilState:always];
        [e setViewport:(MTLViewport){dx0, dy0, dw, dh, 0, 1}];
        [e setVertexBytes:r length:16 atIndex:0];
        [e setFragmentTexture:sdepth atIndex:0];
        [e setFragmentSamplerState:dnear atIndex:0];
        [e drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];
        [e endEncoding];
        stat_passes++;
        static int dbgc = -1;
        if (dbgc < 0) dbgc = getenv("BDSP_DEBUG_DEPTHCOPY") != NULL;
        if (dbgc) {
            static int nlog;
            if (nlog++ < 6) {
                id<MTLBuffer> rb = [dev newBufferWithLength:64 options:MTLResourceStorageModeShared];
                id<MTLBlitCommandEncoder> bb = [cb() blitCommandEncoder];
                MTLBlitOption opt = (s.pixelFormat == MTLPixelFormatDepth32Float_Stencil8) ? MTLBlitOptionDepthFromDepthStencil : MTLBlitOptionNone;
                [bb copyFromTexture:s sourceSlice:0 sourceLevel:0 sourceOrigin:MTLOriginMake(s.width / 2, s.height / 2, 0)
                         sourceSize:MTLSizeMake(1, 1, 1) toBuffer:rb destinationOffset:0 destinationBytesPerRow:4 destinationBytesPerImage:4 options:opt];
                opt = (d.pixelFormat == MTLPixelFormatDepth32Float_Stencil8) ? MTLBlitOptionDepthFromDepthStencil : MTLBlitOptionNone;
                [bb copyFromTexture:d sourceSlice:0 sourceLevel:0 sourceOrigin:MTLOriginMake(d.width / 2, d.height / 2, 0)
                         sourceSize:MTLSizeMake(1, 1, 1) toBuffer:rb destinationOffset:16 destinationBytesPerRow:4 destinationBytesPerImage:4 options:opt];
                [bb endEncoding];
                renderer_flush();
                const float *f = rb.contents;
                LOG("[copy] depth %lux%lu fmt %lu -> %lux%lu fmt %lu: centre src %g dst %g\n", (unsigned long)s.width, (unsigned long)s.height,
                    (unsigned long)s.pixelFormat, (unsigned long)d.width, (unsigned long)d.height, (unsigned long)d.pixelFormat, f[0], f[4]);
            }
        }
        return;
    }
    if (s.sampleCount > 1 && d.sampleCount == 1 && s.pixelFormat == d.pixelFormat && s.width == d.width && s.height == d.height &&
        sx0 == 0 && sy0 == 0 && dx0 == 0 && dy0 == 0 && sw == (int)s.width && sh == (int)s.height) {
        // MSAA resolve (NVN Downsample): neither a blit nor a sampled draw can read a multisample texture as texture2d, the
        // pass's store action resolves it
        MTLRenderPassDescriptor *rp = [MTLRenderPassDescriptor renderPassDescriptor];
        if (renderer_format_is_depth(dt->format)) {
            rp.depthAttachment.texture = s;
            rp.depthAttachment.loadAction = MTLLoadActionLoad;
            rp.depthAttachment.storeAction = MTLStoreActionMultisampleResolve;
            rp.depthAttachment.resolveTexture = d;
            rp.depthAttachment.depthResolveFilter = MTLMultisampleDepthResolveFilterSample0;
            if (renderer_format_has_stencil(dt->format)) {
                rp.stencilAttachment.texture = s;
                rp.stencilAttachment.loadAction = MTLLoadActionLoad;
                rp.stencilAttachment.storeAction = MTLStoreActionMultisampleResolve;
                rp.stencilAttachment.resolveTexture = d;
            }
        } else {
            rp.colorAttachments[0].texture = s;
            rp.colorAttachments[0].loadAction = MTLLoadActionLoad;
            rp.colorAttachments[0].storeAction = MTLStoreActionMultisampleResolve;
            rp.colorAttachments[0].resolveTexture = d;
        }
        id<MTLRenderCommandEncoder> e = [cb() renderCommandEncoderWithDescriptor:rp];
        [e endEncoding];
        stat_passes++;
        return;
    }
    if (renderer_format_is_depth(dt->format) || (s.pixelFormat == d.pixelFormat && sw == dw && sh == dh && s.sampleCount == d.sampleCount)) {
        id<MTLBlitCommandEncoder> b = [cb() blitCommandEncoder];
        [b copyFromTexture:s sourceSlice:0 sourceLevel:0 sourceOrigin:MTLOriginMake(sx0, sy0, 0)
                sourceSize:MTLSizeMake(MIN(sw, dw), MIN(sh, dh), 1) toTexture:d destinationSlice:0 destinationLevel:0
         destinationOrigin:MTLOriginMake(dx0, dy0, 0)];
        [b endEncoding];
        return;
    }
    draw_copy(s, sx0, sy0, sw, sh, d, dx0, dy0, dw, dh, flags & 1);
}

// ------------------------------------------------------------------ executor
// Experiment (BDSP_XW_SKIP=<mask>, off by default): leave out what the renderer writes into guest memory, to find which write
// corrupts the guest. 1 uniform update, 2 buffer copy, 4 counter report, 8 texture read-back, 16 compute dispatch.
static unsigned xw_skip(unsigned bit) {
    static int mask = -1;
    if (mask < 0) mask = getenv("BDSP_XW_SKIP") ? (int)strtol(getenv("BDSP_XW_SKIP"), NULL, 0) : 0;
    return mask & bit;
}
static void exec_list(uint64_t handle, int depth) {
    uint64_t p = handle;
    for (int guard = 0; guard < 10000000; guard++) {
        CmdRec *r = (CmdRec *)(uintptr_t)p;
        void *x = r->extra;
        if (r->op < CMD_COUNT) op_counts[r->op]++;
        switch (r->op) {
        case CMD_END: return;
        case CMD_JUMP: p = r->x[0]; continue;
        case CMD_CALL: {
            const uint64_t *h = x;
            for (uint64_t i = 0; i < r->x[0] && depth < 8; i++) exec_list(h[i], depth + 1);
            break;
        }
        case CMD_BIND_PROGRAM: {
            // BDSP binds separable programs: one NVNprogram per stage, selected by the stage mask (x2). Graphics stages are
            // merged into one program record; a compute-only bind uses the program itself.
            static NvnProgram *stage_prog[5];
            static NvnProgram merged;
            NvnProgram *pp = (NvnProgram *)(uintptr_t)r->x[0];
            uint32_t mask = (uint32_t)r->x[1];
            if ((mask & 0x20) && !(mask & 0x1F)) { st.program = pp; break; }
            for (int i = 0; i < 5; i++) if (mask & (1u << i)) stage_prog[i] = pp;
            memset(&merged, 0, sizeof merged);
            for (int i = 0; i < 5; i++) {
                NvnProgram *sp = stage_prog[i];
                if (sp && (sp->stage_mask & (1u << i))) { merged.stages[i] = sp->stages[i]; merged.stage_mask |= 1u << i; }
            }
            st.program = merged.stage_mask ? &merged : NULL;
            break;
        }
        case CMD_BIND_BLEND: { uint8_t *b = x; memcpy(st.blend[b[0] & 7], b, 8); break; }
        case CMD_BIND_CHANNEL_MASK: memcpy(&st.channel_mask, x, 4); break;
        case CMD_BIND_COLOR: memcpy(st.color_state, x, 4); break;
        case CMD_BIND_DEPTH_STENCIL: memcpy(st.ds, x, 8); break;
        case CMD_BIND_MULTISAMPLE: memcpy(st.ms, x, 0x18); break;
        case CMD_BIND_POLYGON: memcpy(st.poly, x, 4); break;
        case CMD_BIND_VERTEX_ATTRIB:
            st.nattrib = (int)r->x[0] > 16 ? 16 : (int)r->x[0];
            memcpy(st.attrib, x, st.nattrib * 4);
            break;
        case CMD_BIND_VERTEX_STREAM:
            st.nstream = (int)r->x[0] > 16 ? 16 : (int)r->x[0];
            memcpy(st.stream, x, st.nstream * 8);
            break;
        case CMD_BIND_VERTEX_BUFFERS:
            for (uint64_t i = 0; i < r->x[1] && r->x[0] + i < 16; i++) memcpy(&st.vbuf[r->x[0] + i], (uint8_t *)x + i * 16, 16);
            break;
        case CMD_BIND_UNIFORM_BUFFERS:
            for (uint64_t i = 0; i < r->x[2] && r->x[1] + i < 18 && r->x[0] < 6; i++)
                memcpy(&st.ubuf[r->x[0]][r->x[1] + i], (uint8_t *)x + i * 16, 16);
            break;
        case CMD_BIND_STORAGE_BUFFERS:
            for (uint64_t i = 0; i < r->x[2] && r->x[1] + i < 16 && r->x[0] < 6; i++)
                memcpy(&st.sbuf[r->x[0]][r->x[1] + i], (uint8_t *)x + i * 16, 16);
            break;
        case CMD_BIND_TEXTURES:
            for (uint64_t i = 0; i < r->x[2] && r->x[1] + i < 32 && r->x[0] < 6; i++)
                memcpy(&st.tex[r->x[0]][r->x[1] + i], (uint8_t *)x + i * 8, 8);
            break;
        case CMD_BIND_SAMPLERS:
            for (uint64_t i = 0; i < r->x[2] && r->x[1] + i < 32 && r->x[0] < 6; i++)
                memcpy(&st.smp[r->x[0]][r->x[1] + i], (uint8_t *)x + i * 8, 8);
            break;
        case CMD_BIND_IMAGES:
            for (uint64_t i = 0; i < r->x[2] && r->x[1] + i < 8 && r->x[0] < 6; i++)
                memcpy(&st.img[r->x[0]][r->x[1] + i], (uint8_t *)x + i * 8, 8);
            break;
        case CMD_SET_TEXTURE_POOL: st.tpool = (NvnDescPool *)(uintptr_t)r->x[0]; break;
        case CMD_SET_SAMPLER_POOL: st.spool = (NvnDescPool *)(uintptr_t)r->x[0]; break;
        case CMD_SET_RENDER_TARGETS: {
            {
                const uint64_t *tx = x;
                for (int i = 0; i < (int)r->x[0] && i < 8; i++) {
                    NvnTexture *t = (NvnTexture *)(uintptr_t)tx[i];
                    static int nlog;
                    if (t && (t->flags & 2) && nlog++ < 5) LOG("[metal] video texture %p used as render target\n", t);
                }
            }
            const struct { uint64_t tex[8]; NvnTextureView views[8]; uint8_t has_view[8]; uint64_t depth;
                           NvnTextureView dview; uint8_t has_dview; } *rt = x;
            memset(&st.rt, 0, sizeof st.rt);
            st.rt.ncolor = (int)r->x[0];
            for (int i = 0; i < st.rt.ncolor; i++) {
                st.rt.color[i] = (NvnTexture *)(uintptr_t)rt->tex[i];
                st.rt.cview[i] = rt->views[i];
                st.rt.has_cview[i] = rt->has_view[i];
            }
            st.rt.depth = (NvnTexture *)(uintptr_t)rt->depth;
            st.rt.dview = rt->dview;
            st.rt.has_dview = rt->has_dview;
            st.rt_dirty = true;
            break;
        }
        case CMD_SET_VIEWPORTS:
            for (uint64_t i = 0; i < r->x[1] && r->x[0] + i < 16; i++) memcpy(st.viewport[r->x[0] + i], (uint8_t *)x + i * 16, 16);
            break;
        case CMD_SET_SCISSORS:
            for (uint64_t i = 0; i < r->x[1] && r->x[0] + i < 16; i++) memcpy(st.scissor[r->x[0] + i], (uint8_t *)x + i * 16, 16);
            break;
        case CMD_SET_DEPTH_RANGES:
            for (uint64_t i = 0; i < r->x[1] && r->x[0] + i < 16; i++) memcpy(st.depth_range[r->x[0] + i], (uint8_t *)x + i * 8, 8);
            break;
        case CMD_SET_BLEND_COLOR: memcpy(st.blend_color, x, 16); break;
        case CMD_SET_STENCIL: {
            int face = (int)r->x[0];
            for (int f = 0; f < 2; f++) {
                if (!(face & (1 << f))) continue;
                if (r->x[6] == 0) st.stencil_ref[f] = (uint32_t)r->x[1];
                else if (r->x[6] == 1) st.stencil_mask[f] = (uint32_t)r->x[1];
                else st.stencil_vmask[f] = (uint32_t)r->x[1];
            }
            break;
        }
        case CMD_SET_POLYGON_OFFSET: memcpy(st.poly_offset, r->f, sizeof st.poly_offset); break;
        case CMD_SET_PRIMITIVE_RESTART: st.prim_restart = r->x[0] != 0; st.restart_index = (uint32_t)r->x[1]; break;
        case CMD_SET_COPY_STRIDES: st.copy_row_stride = r->x[0]; st.copy_image_stride = r->x[1]; break;
        case CMD_CLEAR_COLOR: {
            snap_reason = "clear-color"; snapshots_invalidate(NULL);
            int index = (int)r->x[0];
            static int log_clears = -1;  // BDSP_LOG_CLEARS: every colour clear (frame, target size, mask, scissor)
            if (log_clears < 0) log_clears = getenv("BDSP_LOG_CLEARS") != NULL;
            if (log_clears && index < st.rt.ncolor && st.rt.color[index])
                LOG("[cclear] frame %llu idx %d %ux%u f%#x mask %#x scissor %d,%d %dx%d\n", (unsigned long long)renderer_present_count(),
                    index, st.rt.color[index]->width, st.rt.color[index]->height, st.rt.color[index]->format, (uint32_t)r->x[2],
                    st.scissor[0][0], st.scissor[0][1], st.scissor[0][2], st.scissor[0][3]);
            else if (log_clears) LOG("[cclear] frame %llu idx %d: no target bound (ncolor %d)\n", (unsigned long long)renderer_present_count(), index, st.rt.ncolor);
            if (index < st.rt.ncolor && st.rt.color[index]) clear(index, (int)r->x[5], x, (uint32_t)r->x[2], false, 0, false, 0, 0);
            break;
        }
        case CMD_CLEAR_TEXTURE: {
            // ClearTexture(cmd, texture, view, region, color, mask) (runtime/nvn/cmdbuf.c clear_texture). Was never
            // executed: the game clears its text-box textures this way before drawing a new message, so the old
            // text stayed behind the new one (user 2026-10-08: "Load this file?" over "Please select a file.").
            // Done as a render-target clear: bind the texture alone, scissor = region, clear(), restore.
            const struct { uint64_t tex; NvnTextureView view; uint8_t has_view; int32_t region[6]; float color[4]; } *ct = x;
            NvnTexture *t = (NvnTexture *)(uintptr_t)ct->tex;
            if (!t) break;
            snap_reason = "clear-texture"; snapshots_invalidate(NULL);
            RtState saved = st.rt;
            int32_t sc[4];
            memcpy(sc, st.scissor[0], sizeof sc);
            end_pass();
            memset(&st.rt, 0, sizeof st.rt);
            st.rt.ncolor = 1;
            st.rt.color[0] = t;
            if (ct->has_view) { st.rt.cview[0] = ct->view; st.rt.has_cview[0] = 1; }
            st.rt_dirty = true;
            const int32_t *rg = ct->region;
            if (rg[3] > 0 && rg[4] > 0) { st.scissor[0][0] = rg[0]; st.scissor[0][1] = rg[1]; st.scissor[0][2] = rg[3]; st.scissor[0][3] = rg[4]; }
            else { st.scissor[0][0] = st.scissor[0][1] = 0; st.scissor[0][2] = st.scissor[0][3] = 16384; }
            static int nlog;
            if (nlog++ < 8 || g_debug_frame)
                LOG("[cleartex] %ux%u f%#x region %d,%d %dx%d color %g %g %g %g mask %#llx kind %llu\n", t->width, t->height, t->format,
                    rg[0], rg[1], rg[3], rg[4], ct->color[0], ct->color[1], ct->color[2], ct->color[3], r->x[4], r->x[6]);
            clear(0, (int)r->x[6], ct->color, (uint32_t)r->x[4] ? (uint32_t)r->x[4] : 0xF, false, 0, false, 0, 0);
            end_pass();
            st.rt = saved;
            memcpy(st.scissor[0], sc, sizeof sc);
            st.rt_dirty = true;
            break;
        }
        case CMD_CLEAR_DEPTH_STENCIL:
            snap_reason = "clear-depth"; snapshots_invalidate(NULL);
            if (st.rt.depth) {
                // (depth s0, depthMask x1, stencil x2, stencilMask x3)
                bool has_stencil = renderer_format_has_stencil(st.rt.depth->format);
                clear(-1, 0, NULL, 0, r->x[0] != 0, r->f[0], has_stencil && r->x[2] != 0, (uint32_t)r->x[1],
                      (uint32_t)r->x[2]);
            }
            break;
        case CMD_DISPATCH:
            if (xw_skip(16)) break;
            dispatch_compute((uint32_t)r->x[0], (uint32_t)r->x[1], (uint32_t)r->x[2]);
            if (st.program) {
                static uint64_t seen[16];
                static int nseen;
                uint64_t cs = st.program->stages[5].code_addr;
                bool known = false;
                for (int i = 0; i < nseen; i++) known |= seen[i] == cs;
                if (!known && nseen < 16) {
                    seen[nseen++] = cs;
                    char path[64];
                    snprintf(path, sizeof path, "build/cs_%d.bin", nseen - 1);
                    FILE *f = fopen(path, "wb");  // (no build/ outside a source checkout: the app's data root)
                    if (f) fwrite((void *)(uintptr_t)cs, 1, 0x4000, f), fclose(f);
                    LOG("[dispatch] new compute program %d: cs %llx groups %llu %llu %llu images:", nseen - 1, cs, r->x[0], r->x[1], r->x[2]);
                    for (int i = 0; i < 8; i++) if (st.img[5][i]) LOG(" %d=%llx", i, st.img[5][i]);
                    LOG(" tex:");
                    for (int i = 0; i < 8; i++) if (st.tex[5][i]) LOG(" %d=%llx", i, st.tex[5][i]);
                    LOG(" ubuf:");
                    for (int i = 0; i < 8; i++) if (st.ubuf[5][i].addr) LOG(" %d=%llx/%llu", i, st.ubuf[5][i].addr, st.ubuf[5][i].size);
                    LOG(" ssbo:");
                    for (int i = 0; i < 8; i++) if (st.sbuf[5][i].addr) LOG(" %d=%llx/%llu", i, st.sbuf[5][i].addr, st.sbuf[5][i].size);
                    LOG("\n");
                }
            }
            if (g_debug_frame && st.program) {
                LOG("[dispatch] %llu %llu %llu prog %p cs %llx\n", r->x[0], r->x[1], r->x[2], st.program, st.program->stages[5].code_addr);
                FILE *f = fopen("build/cs_code.bin", "wb");
                if (f) fwrite((void *)(uintptr_t)st.program->stages[5].code_addr, 1, 0x4000, f), fclose(f);
                f = fopen("build/cs_ctrl.bin", "wb");
                if (f) fwrite(st.program->stages[5].control, 1, 0x900, f), fclose(f);
                LOG("[dispatch] images:");
                for (int i = 0; i < 8; i++) if (st.img[5][i]) LOG(" %d=%llx", i, st.img[5][i]);
                LOG(" tex:");
                for (int i = 0; i < 8; i++) if (st.tex[5][i]) LOG(" %d=%llx", i, st.tex[5][i]);
                LOG(" ubuf:");
                for (int i = 0; i < 8; i++) if (st.ubuf[5][i].addr) LOG(" %d=%llx/%llu", i, st.ubuf[5][i].addr, st.ubuf[5][i].size);
                LOG("\n");
            }
            break;
        case CMD_DRAW_ARRAYS: draw(r, false); break;
        case CMD_DRAW_ELEMENTS: draw(r, true); break;
        case CMD_UPDATE_UNIFORM_BUFFER:
            // (buffer, size, offset, dataSize, data): apply the update in command order (after the GPU wrote the range back)
            if (arena_pending(r->x[0] + r->x[2], r->x[3])) flush_why(FL_ARENA);
            if (!xw_skip(1)) memcpy((void *)(uintptr_t)(r->x[0] + r->x[2]), x, r->x[3]);
            break;
        case CMD_FENCE_SYNC: {
            // The CPU may read GPU-written memory (compute results) once the fence is signaled.
            static int fence_flush = -1;
            if (fence_flush < 0) fence_flush = getenv("BDSP_FENCE_FLUSH") ? 1 : 0;
            if (fence_flush) renderer_flush();
            extern void nvn_sync_set_seq(uint64_t guest, uint64_t seq);
            if (r->x[1] && !xw_is_worker) nvn_sync_set_seq(r->x[1], renderer_fence_seq());   // in the worker the enqueueing already sets the token (xw_prescan_fences)
            break;
        }
        case CMD_REPORT_COUNTER: {
            uint64_t *out = (uint64_t *)(uintptr_t)r->x[1];
            static uint32_t seen;
            uint32_t type = (uint32_t)r->x[0];
            if (type < 32 && !(seen & (1u << type))) { seen |= 1u << type; LOG("[nvn] ReportCounter type %u\n", type); }
            // (Switch GPU ticks, 614.4 MHz: the game converts the difference to ns itself - see the Vulkan exec.c)
            if (out && !xw_skip(4)) { out[0] = 0; out[1] = (uint64_t)((unsigned __int128)plat_now_ns() * 384 / 625); }
            break;
        }
        case CMD_COPY_TEXTURE_TO_TEXTURE: {
            const TexRefRec *t = x;
            copy_texture(&t[0], &t[1], r->x[6]);
            break;
        }
        case CMD_DOWNSAMPLE: {
            const TexRefRec *t = x;
            copy_texture(&t[0], &t[1], 1);
            break;
        }
        case CMD_COPY_BUFFER_TO_TEXTURE: copy_buffer_to_texture(r->x[0], x); break;
        case CMD_COPY_TEXTURE_TO_BUFFER: if (!xw_skip(8)) copy_texture_to_buffer(x, r->x[3]); break;
        case CMD_COPY_BUFFER_TO_BUFFER:
            // The copy runs on the CPU, so the GPU must be done with what it touches: only a range a dispatch reads or writes
            // (hz_ranges) is. The game does this many times a frame (walking along the water: ~25), each flush stalled
            // the worker. BDSP_HZ_FLUSH=1: flush every time as before.
            if (getenv_flag_hz_flush() || range_pending_compute(r->x[0], r->x[2]) || range_pending_compute(r->x[1], r->x[2]) ||
                arena_pending(r->x[0], r->x[2]) || arena_pending(r->x[1], r->x[2]))
                flush_why(FL_BUF2BUF);
            if (!xw_skip(2)) memmove((void *)(uintptr_t)r->x[1], (void *)(uintptr_t)r->x[0], r->x[2]);
            break;
        default: break;
        }
        p += r->size;
    }
}

// In-place reboot (runtime/nvn/metal.m backend_reset; GPU idle, the game's textures already destroyed): drop
// everything keyed by guest addresses or guest-owned objects - programs (by code address), pipelines (by program),
// views, snapshots, bound state - so the next boot can't hit a stale entry. Metal's own shader cache stays warm.
void renderer_reset(void) {
    renderer_flush();
    pthread_mutex_lock(&gone_lock);
    ngone = 0;
    pthread_mutex_unlock(&gone_lock);
    for (int i = 0; i < VIEW_TAB; i++) {
        if (view_tab[i].view) CFRelease(view_tab[i].view);
        view_tab[i].view = view_tab[i].base = NULL;
        view_tab[i].key = 0;
    }
    g_views_live = 0;
    memset(prog_tab, 0, sizeof prog_tab);
    memset(pipe_tab, 0, sizeof pipe_tab);
    [cache removeAllObjects];
    [g_cs_progs removeAllObjects];
    g_boot_gen++;
    [g_snap_copies removeAllObjects];
    memset(snap_tex, 0, sizeof snap_tex);
    memset(snap_ok, 0, sizeof snap_ok);
    for (int i = 0; i < 4; i++) { feedback_tex[i] = NULL; feedback_copy[i] = nil; }
    nfeedback = 0;
    g_cur_fs_hash = 0;
    last_bias_enc = nil;
    pthread_mutex_lock(&cb_lock);
    last_cb = nil;
    for (int i = 0; i < CB_HIST; i++) cb_hist[i] = nil;  // (they retain the old guest heap buffer)
    pthread_mutex_unlock(&cb_lock);
    pthread_mutex_lock(&arena_lock);  // (the ranges belong to the old boot: dropped, not written back)
    for (int i = 0; i < arena_nent; i++) { free(arena_ent[i].snap); arena_ent[i].snap = NULL; arena_ent[i].buf = nil; }
    arena_nent = 0;
    pthread_mutex_unlock(&arena_lock);
    st_defaults();
}

// Worker mode: fences that are in the list (nvnCommandBufferFenceSync) get their token already when enqueued.
// Otherwise an nvnSyncWait in the guest still reads the old state before the worker has executed the fence instruction, and
// returns too early; the guest would then overwrite memory that the worker still reads.
// Checksum over all records of a list (following jumps and calls); with a fence token ≠ 0 it also sets the fences.
static int xw_measure = -1;
static struct { uint64_t n[3], uniq[3], bytes[3], ubytes[3], set[8192]; uint64_t frame, frames; } xw_ms;
static void xw_measure_report(uint64_t pres) {   // per frame: sum up counters, print every 240 frames, clear the set
    if (xw_ms.frame == pres) return;
    xw_ms.frame = pres;
    memset(xw_ms.set, 0, sizeof xw_ms.set);
    if (++xw_ms.frames % 240 == 0) {
        static const char *nm[3] = {"Uniform", "Storage", "Vertex"};
        for (int k = 0; k < 3; k++)
            printf("[xw] %s per frame: %llu bindings (%llu distinct), bound %.1f KiB, distinct %.1f KiB\n", nm[k],
                   (unsigned long long)(xw_ms.n[k] / 240), (unsigned long long)(xw_ms.uniq[k] / 240), xw_ms.bytes[k] / 240 / 1024.0, xw_ms.ubytes[k] / 240 / 1024.0);
        memset(xw_ms.n, 0, sizeof xw_ms.n); memset(xw_ms.uniq, 0, sizeof xw_ms.uniq);
        memset(xw_ms.bytes, 0, sizeof xw_ms.bytes); memset(xw_ms.ubytes, 0, sizeof xw_ms.ubytes);
    }
}
static uint64_t xw_walk(uint64_t handle, uint64_t token, int depth) {
    extern void nvn_sync_set_seq(uint64_t guest, uint64_t seq);
    uint64_t hsh = 1469598103934665603ull, p = handle;
    for (int guard = 0; guard < 10000000; guard++) {
        CmdRec *r = (CmdRec *)(uintptr_t)p;
        const uint64_t *w = (const uint64_t *)r;
        for (uint32_t i = 0; i + 8 <= r->size; i += 8) hsh = (hsh ^ *w++) * 0x100000001B3ull;
        switch (r->op) {
        case CMD_END: return hsh;
        case CMD_JUMP: p = r->x[0]; continue;
        case CMD_CALL: {
            const uint64_t *h = (const uint64_t *)r->extra;
            for (uint64_t i = 0; i < r->x[0] && depth < 8; i++) hsh = (hsh ^ xw_walk(h[i], token, depth + 1)) * 0x100000001B3ull;
            break;
        }
        case CMD_FENCE_SYNC: if (token && r->x[1]) nvn_sync_set_seq(r->x[1], token); break;
        case CMD_BIND_UNIFORM_BUFFERS: case CMD_BIND_STORAGE_BUFFERS: case CMD_BIND_VERTEX_BUFFERS:
            if (xw_measure) {   // BDSP_XW_MEASURE=1: what a snapshot of the bound ranges would cost
                uint64_t cnt = r->op == CMD_BIND_VERTEX_BUFFERS ? r->x[1] : r->x[2];
                const uint64_t *rg = (const uint64_t *)r->extra;
                int k = r->op == CMD_BIND_UNIFORM_BUFFERS ? 0 : r->op == CMD_BIND_STORAGE_BUFFERS ? 1 : 2;
                for (uint64_t i = 0; i < cnt && i < 18; i++) {
                    uint64_t a = rg[i * 2], sz = rg[i * 2 + 1];
                    xw_ms.n[k]++; xw_ms.bytes[k] += sz;
                    uint64_t key = (a * 0x9E3779B97F4A7C15ull) ^ (sz * 0xC2B2AE3D27D4EB4Full);
                    unsigned slot = (unsigned)(key >> 40) & 8191;
                    while (xw_ms.set[slot] && xw_ms.set[slot] != key) slot = (slot + 1) & 8191;
                    if (!xw_ms.set[slot]) { xw_ms.set[slot] = key; xw_ms.uniq[k]++; xw_ms.ubytes[k] += sz; }
                }
            }
            break;
        default: break;
        }
        p += r->size;
    }
    return hsh;
}
static uint64_t xw_list_hash(uint64_t handle) { return xw_walk(handle, 0, 0); }

// BDSP_XW_SNAP=1: copy of the list for the worker. The worker reads uniform and index data only at execution time
// (ring_alloc in the draw); by then the guest may already have overwritten them for the next frame. Therefore the
// enqueueing copies the records together with the bound uniform ranges (at most 64 KiB per binding) and the index data.
// Storage and vertex data are read by the GPU through the wrapped guest memory (addresses), they stay untouched.
// State 2026-10-22: yields empty command lists (exec_list sees only CMD_END, 0 draw calls on Mac and iPad). Do not use until the cause is fixed.
typedef struct { void **blk; int n, cap; } XwSnap;
static void xw_snap_add(XwSnap *s, void *p) {
    if (s->n == s->cap) { s->cap = s->cap ? s->cap * 2 : 64; s->blk = realloc(s->blk, s->cap * sizeof *s->blk); }
    s->blk[s->n++] = p;
}
static void xw_snap_free(void *p) {
    XwSnap *s = p;
    for (int i = 0; i < s->n; i++) free(s->blk[i]);
    free(s->blk);
    free(s);
}
static struct { uint64_t gen, addr, len; void *ptr; } xw_dup_tab[4096];   // generation counter instead of clearing
static uint64_t xw_dup_gen;
static uint64_t xw_snap_bytes;   // Diagnose: kopierte Bytes
static void *xw_dup(XwSnap *s, uint64_t addr, uint64_t len) {
    uint64_t key = (addr * 0x9E3779B97F4A7C15ull) ^ (len * 0xC2B2AE3D27D4EB4Full);
    unsigned slot = (unsigned)(key >> 40) & 4095;
    for (int probe = 0; probe < 8; probe++, slot = (slot + 1) & 4095)
        if (xw_dup_tab[slot].gen == xw_dup_gen && xw_dup_tab[slot].addr == addr && xw_dup_tab[slot].len == len) return xw_dup_tab[slot].ptr;
    void *c = malloc(len);
    memcpy(c, (const void *)(uintptr_t)addr, len);
    xw_snap_add(s, c);
    xw_snap_bytes += len;
    slot = (unsigned)(key >> 40) & 4095;
    for (int probe = 0; probe < 8; probe++, slot = (slot + 1) & 4095)
        if (xw_dup_tab[slot].gen != xw_dup_gen) { xw_dup_tab[slot].gen = xw_dup_gen; xw_dup_tab[slot].addr = addr; xw_dup_tab[slot].len = len; xw_dup_tab[slot].ptr = c; break; }
    return c;
}
static uint8_t *xw_snap_list(XwSnap *s, uint64_t handle, int depth) {
    size_t total = 0;
    uint64_t p = handle;
    for (int guard = 0; guard < 10000000; guard++) {
        CmdRec *r = (CmdRec *)(uintptr_t)p;
        if (r->op == CMD_JUMP) { p = r->x[0]; continue; }
        total += r->size;
        if (r->op == CMD_END) break;
        p += r->size;
    }
    uint8_t *buf = malloc(total), *q = buf;
    xw_snap_add(s, buf);
    p = handle;
    for (int guard = 0; guard < 10000000; guard++) {
        CmdRec *r = (CmdRec *)(uintptr_t)p;
        if (r->op == CMD_JUMP) { p = r->x[0]; continue; }
        memcpy(q, r, r->size);
        CmdRec *c = (CmdRec *)q;
        q += r->size;
        p += r->size;
        switch (c->op) {
        case CMD_END: return buf;
        case CMD_CALL: {
            uint64_t *h = (uint64_t *)c->extra;
            for (uint64_t i = 0; i < c->x[0] && depth < 8; i++) h[i] = (uint64_t)(uintptr_t)xw_snap_list(s, h[i], depth + 1);
            break;
        }
        case CMD_BIND_UNIFORM_BUFFERS: {
            uint64_t *rg = (uint64_t *)c->extra;
            for (uint64_t i = 0; i < c->x[2]; i++) {
                uint64_t a = rg[i * 2], sz = rg[i * 2 + 1];
                if (!a || !sz) continue;
                if (sz > 0x10000) sz = 0x10000;
                rg[i * 2] = (uint64_t)(uintptr_t)xw_dup(s, a, sz);
                rg[i * 2 + 1] = sz;
            }
            break;
        }
        case CMD_DRAW_ELEMENTS: {
            uint64_t cnt = c->x[2], isz = c->x[1] == 0 ? 1 : c->x[1] == 1 ? 2 : 4;
            if (c->x[3] && cnt && cnt * isz <= (64u << 20)) c->x[3] = (uint64_t)(uintptr_t)xw_dup(s, c->x[3], cnt * isz);
            break;
        }
        case CMD_UPDATE_UNIFORM_BUFFER:
            // applies in command order: apply now, so the following copies see the new state (as in the default path when
            // submitting); the instruction itself then writes nothing more
            if (c->x[3]) memcpy((void *)GA(c->x[0] + c->x[2]), c->extra, c->x[3]);
            c->x[3] = 0;
            xw_dup_gen++;
            break;
        default: break;
        }
    }
    return buf;
}

void backend_execute(uint64_t handle) {
    if (xw_enabled()) {
        if (xw_measure < 0) xw_measure = getenv("BDSP_XW_MEASURE") != NULL;
        if (xw_measure) xw_measure_report(xw_pres_enq);
        uint64_t chk = xw_walk(handle, xw_next_token(), 0);
        static int snapon = -1, snapdbg;
        if (snapon < 0) snapon = getenv("BDSP_XW_SNAP") != NULL;
        XwSnap *snap = NULL;
        uint64_t h2 = handle;
        if (snapon) {
            xw_dup_gen++;
            snap = calloc(1, sizeof *snap);
            h2 = (uint64_t)(uintptr_t)xw_snap_list(snap, handle, 0);
            if (xw_measure && ++snapdbg % 1000 == 0) printf("[xw] Snapshot kopiert insgesamt %.1f MiB in %d Listen\n", xw_snap_bytes / 1048576.0, snapdbg);
        }
        xw_enqueue(h2, xw_check && !snapon ? chk : 0, snap);
        static int xsync = -1;  // BDSP_EXEC_SYNC=1 (data race test): the guest waits for the worker after every enqueue
        if (xsync < 0) xsync = getenv("BDSP_EXEC_SYNC") != NULL;
        if (xsync) xw_drain();
        return;
    }
    static int prof = -1;
    if (prof < 0) prof = getenv("BDSP_PROFILE") != NULL;
    @autoreleasepool {
        uint64_t t0 = clock_gettime_nsec_np(CLOCK_UPTIME_RAW);
        exec_list(handle, 0);
        uint64_t t1 = clock_gettime_nsec_np(CLOCK_UPTIME_RAW);
        static int sync_submit = -1;
        if (sync_submit < 0) sync_submit = getenv("BDSP_SYNC_SUBMIT") ? 1 : 0;
        if (sync_submit) renderer_flush();  // old behaviour: finish the GPU work before returning
        else renderer_submit();  // the guest fences (nvnSyncWait) before reusing memory the GPU reads
        if (prof) {
            uint64_t t2 = clock_gettime_nsec_np(CLOCK_UPTIME_RAW);
            prof_exec_ns += t1 - t0; prof_submit_ns += t2 - t1; prof_n++;
            if (!prof_last_ns) prof_last_ns = t2;
            if (t2 - prof_last_ns >= 3000000000ull && prof_n) {
                printf("[prof] %llu calls per 3 s: exec %.2f ms per call (sum %.0f ms), submit %.2f ms per call\n",
                       (unsigned long long)prof_n, prof_exec_ns / 1e6 / prof_n, prof_exec_ns / 1e6, prof_submit_ns / 1e6 / prof_n);
                prof_exec_ns = prof_submit_ns = prof_n = 0;
                prof_last_ns = t2;
            }
        }
    }
}
