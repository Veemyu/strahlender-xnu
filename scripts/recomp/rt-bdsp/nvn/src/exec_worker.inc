// Translation worker (Mac: on by default, BDSP_EXEC_WORKER=0 = old synchronous path), included by renderer.m.
// backend_execute enqueues the handles; a worker thread runs exec_list and renderer_submit in order.
// backend_present (metal.m) enqueues the presentation as a job (renderer_worker_present), the guest runs at most
// BDSP_EXEC_FRAMES (default 2) frames ahead.
// Guest-side synchronisation (renderer_submit, renderer_sync, renderer_fence_seq, renderer_wait_seq) waits for the worker first.
// Without the environment variable all counters are 0 and the drains return immediately.
void renderer_submit(void);
static void exec_list(uint64_t handle, int depth);

#define XW_CAP 8192
static pthread_mutex_t xw_lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t xw_cond = PTHREAD_COND_INITIALIZER;
static uint64_t xw_handles[XW_CAP], xw_tail, xw_next, xw_done;   // enqueued / taken / done
uint64_t renderer_last_submit_seq(void);
static uint64_t xw_job_seq[XW_CAP];   // per job: sequence number of the newest command buffer committed when it finished
static void *xw_blocks[XW_CAP];   // != NULL: presentation job (retained block) instead of a command list
static uint8_t xw_isp[XW_CAP];   // block is a presentation (counts toward the frame lead limit)
static uint64_t xw_chk[XW_CAP];   // checksum of the records at enqueue time (only BDSP_XW_CHECK)
static int xw_check;
static uint64_t xw_list_hash(uint64_t handle);
bool xw_ordered(void (*fn)(void *), void *arg);
static void *xw_snaps[XW_CAP];   // copy of the list including uniform/index data (BDSP_XW_SNAP), released by the worker after execution
static void xw_snap_free(void *s);
static uint64_t xw_pres_enq, xw_pres_done;   // enqueued / finished presentations
static int xw_max_frames = 2;   // this many frames the guest may be ahead of the worker (BDSP_EXEC_FRAMES)
static int xw_on = -1;
static __thread int xw_is_worker;
// BDSP_XW_LOG=1: timestamp per job, queue length, wait time of the guest (one [xw-t] line every 2 s, outliers individually)
static int xw_log;
static uint64_t xw_ts[XW_CAP];
static uint64_t xw_now_ns(void) { return clock_gettime_nsec_np(CLOCK_UPTIME_RAW); }
static void xw_cond_wait(const char *what);
static struct { uint64_t t0, njobs, npres, qmax, lat_max, list_max, pres_max, guest_wait_max, guest_wait_sum, nwait, busy; } xw_st;

bool renderer_on_worker(void) { return xw_is_worker; }

static void *xw_main(void *arg) {
    (void)arg;
    xw_is_worker = 1;
    for (;;) {
        pthread_mutex_lock(&xw_lock);
        while (xw_next == xw_tail) pthread_cond_wait(&xw_cond, &xw_lock);
        uint64_t h = xw_handles[xw_next % XW_CAP];
        void *blk = xw_blocks[xw_next % XW_CAP];
        uint64_t chk = xw_chk[xw_next % XW_CAP];
        void *snap = xw_snaps[xw_next % XW_CAP];
        int isp = xw_isp[xw_next % XW_CAP];
        uint64_t enq_ts = xw_ts[xw_next % XW_CAP], t_start = xw_log ? xw_now_ns() : 0;
        uint64_t qlen = xw_tail - xw_next;
        uint64_t jidx = xw_next;
        xw_next++;
        pthread_mutex_unlock(&xw_lock);
        @autoreleasepool {
            if (blk) {
                void (^job)(void) = CFBridgingRelease(blk);
                job();
            } else {
                if (xw_check) {   // BDSP_XW_CHECK=1: were the command records changed between enqueueing and execution?
                    static uint64_t njobs, nbad;
                    njobs++;
                    if (xw_list_hash(h) != chk) {
                        nbad++;
                        if (nbad <= 30) printf("[xw] command list %llx was changed after enqueueing (%llu of %llu)\n", (unsigned long long)h, (unsigned long long)nbad, (unsigned long long)njobs);
                    }
                    if (njobs % 1000 == 0) printf("[xw] lists %llu, changed %llu\n", (unsigned long long)njobs, (unsigned long long)nbad);
                }
                exec_list(h, 0);
                if (snap) xw_snap_free(snap);
                renderer_submit();
            }
        }
        uint64_t seq_now = renderer_last_submit_seq();   // the GPU work this job (and every earlier one) ended up in
        pthread_mutex_lock(&xw_lock);
        xw_job_seq[jidx % XW_CAP] = seq_now;
        if (blk && isp) xw_pres_done++;
        xw_done++;
        pthread_cond_broadcast(&xw_cond);
        pthread_mutex_unlock(&xw_lock);
        if (xw_log) {
            uint64_t t_end = xw_now_ns(), lat = t_start - enq_ts, dur = t_end - t_start;
            if (!xw_st.t0) xw_st.t0 = t_end;
            xw_st.njobs++;
            if (qlen > xw_st.qmax) xw_st.qmax = qlen;
            if (lat > xw_st.lat_max) xw_st.lat_max = lat;
            if (blk && isp) { xw_st.npres++; if (dur > xw_st.pres_max) xw_st.pres_max = dur; }
            else if (!blk && dur > xw_st.list_max) xw_st.list_max = dur;
            xw_st.busy += dur;
            if (dur > 12000000ull) printf("[xw-t] t=%.3f %s takes %.2f ms (latency %.2f ms, queue %llu)\n", t_end / 1e9, blk ? (isp ? "presentation" : "state job") : "command list", dur / 1e6, lat / 1e6, (unsigned long long)qlen);
            if (t_end - xw_st.t0 >= 2000000000ull) {
                printf("[xw-t] t=%.3f jobs %llu, presentations %llu, queue max %llu, latency max %.2f ms, list max %.2f ms, presentation max %.2f ms, guest wait max %.2f ms mean %.2f ms, worker busy %.0f %%\n", t_end / 1e9,
                       (unsigned long long)xw_st.njobs, (unsigned long long)xw_st.npres, (unsigned long long)xw_st.qmax, xw_st.lat_max / 1e6, xw_st.list_max / 1e6, xw_st.pres_max / 1e6,
                       xw_st.guest_wait_max / 1e6, xw_st.nwait ? xw_st.guest_wait_sum / 1e6 / xw_st.nwait : 0.0, 100.0 * xw_st.busy / (double)(t_end - xw_st.t0));
                memset(&xw_st, 0, sizeof xw_st);
            }
        }
    }
    return NULL;
}

static int xw_enabled(void) {
    if (xw_on < 0) {
        const char *ew = getenv("BDSP_EXEC_WORKER");   // Mac: on by default; BDSP_EXEC_WORKER=0 switches to the old synchronous path
        xw_on = !(ew && !strcmp(ew, "0"));
        xw_check = xw_on && getenv("BDSP_XW_CHECK") != NULL;
        xw_log = xw_on && getenv("BDSP_XW_LOG") != NULL;
        if (xw_on) {
            extern bool (*g_nvn_ordered)(void (*)(void *), void *);
            g_nvn_ordered = xw_ordered;
            if (getenv("BDSP_EXEC_FRAMES") && atoi(getenv("BDSP_EXEC_FRAMES")) > 0) xw_max_frames = atoi(getenv("BDSP_EXEC_FRAMES"));
            pthread_t t;
            pthread_attr_t xa;
            pthread_attr_init(&xa);
#ifdef BDSP_IOS   // the worker sat 30 % of its time on efficiency cores in the profile (see kernel.c, BDSP_QOS=0 switches it off)
            if (!getenv("BDSP_QOS") || atoi(getenv("BDSP_QOS"))) pthread_attr_set_qos_class_np(&xa, QOS_CLASS_USER_INTERACTIVE, 0);
#endif
            pthread_create(&t, &xa, xw_main, NULL);
            pthread_attr_destroy(&xa);
            pthread_detach(t);
        }
    }
    return xw_on;
}

static void xw_enqueue(uint64_t h, uint64_t chk, void *snap) {
    pthread_mutex_lock(&xw_lock);
    while (xw_tail - xw_done >= XW_CAP) pthread_cond_wait(&xw_cond, &xw_lock);
    xw_handles[xw_tail % XW_CAP] = h;
    xw_blocks[xw_tail % XW_CAP] = NULL;
    xw_isp[xw_tail % XW_CAP] = 0;
    xw_chk[xw_tail % XW_CAP] = chk;
    xw_snaps[xw_tail % XW_CAP] = snap;
    xw_ts[xw_tail % XW_CAP] = xw_log ? xw_now_ns() : 0;
    xw_tail++;
    pthread_cond_broadcast(&xw_cond);
    pthread_mutex_unlock(&xw_lock);
}

// Presentation as a job in the same queue (the order relative to the command lists stays). The guest waits only if it is more
// than xw_max_frames frames ahead. false: worker off (or call from the worker), the caller presents itself.
bool renderer_worker_present(void (^job)(void)) {
    if (!xw_enabled() || xw_is_worker) return false;
    void *blk = (void *)CFBridgingRetain([job copy]);
    pthread_mutex_lock(&xw_lock);
    while (xw_tail - xw_done >= XW_CAP) pthread_cond_wait(&xw_cond, &xw_lock);
    xw_handles[xw_tail % XW_CAP] = 0;
    xw_blocks[xw_tail % XW_CAP] = blk;
    xw_isp[xw_tail % XW_CAP] = 1;
    xw_snaps[xw_tail % XW_CAP] = NULL;
    xw_ts[xw_tail % XW_CAP] = xw_log ? xw_now_ns() : 0;
    xw_tail++;
    xw_pres_enq++;
    pthread_cond_broadcast(&xw_cond);
    uint64_t w0 = xw_log ? xw_now_ns() : 0;
    while (xw_pres_enq - xw_pres_done > (uint64_t)xw_max_frames) xw_cond_wait("presentation lead");
    if (xw_log) {
        uint64_t w = xw_now_ns() - w0;
        xw_st.nwait++; xw_st.guest_wait_sum += w;
        if (w > xw_st.guest_wait_max) xw_st.guest_wait_max = w;
    }
    pthread_mutex_unlock(&xw_lock);
    return true;
}

// Fence token: bit 63 set, rest = number of jobs enqueued up to then. The waiter waits only until this job,
// not for the whole queue.
// State changes of the guest that the worker reads while executing (texture/sampler pools) run in queue order:
// the guest enqueues the change instead of writing it immediately; the worker applies it between the lists.
bool xw_ordered(void (*fn)(void *), void *arg) {
    if (xw_on <= 0 || xw_is_worker) return false;
    void (^job)(void) = ^{ fn(arg); };
    void *blk = (void *)CFBridgingRetain([job copy]);
    pthread_mutex_lock(&xw_lock);
    while (xw_tail - xw_done >= XW_CAP) pthread_cond_wait(&xw_cond, &xw_lock);
    xw_handles[xw_tail % XW_CAP] = 0;
    xw_blocks[xw_tail % XW_CAP] = blk;
    xw_isp[xw_tail % XW_CAP] = 0;
    xw_snaps[xw_tail % XW_CAP] = NULL;
    xw_ts[xw_tail % XW_CAP] = xw_log ? xw_now_ns() : 0;
    xw_tail++;
    pthread_cond_broadcast(&xw_cond);
    pthread_mutex_unlock(&xw_lock);
    return true;
}

#define XW_TAG (1ull << 63)
static uint64_t xw_fence_token(void) {
    pthread_mutex_lock(&xw_lock);
    uint64_t t = xw_tail;
    pthread_mutex_unlock(&xw_lock);
    return XW_TAG | t;
}
static uint64_t xw_next_token(void) {   // token of the job that is enqueued next (only one submitting thread)
    pthread_mutex_lock(&xw_lock);
    uint64_t t = xw_tail + 1;
    pthread_mutex_unlock(&xw_lock);
    return XW_TAG | t;
}
// With BDSP_XW_LOG a waiter that hangs for longer than 1 s reports the state of the queue (hang diagnosis).
static void xw_cond_wait(const char *what) {
    if (!xw_log) { pthread_cond_wait(&xw_cond, &xw_lock); return; }
    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);
    ts.tv_sec += 1;
    if (pthread_cond_timedwait(&xw_cond, &xw_lock, &ts))
        printf("[xw-t] t=%.3f HANGS in %s: enqueued %llu, taken %llu, done %llu, presentations %llu/%llu\n", xw_now_ns() / 1e9, what,
               (unsigned long long)xw_tail, (unsigned long long)xw_next, (unsigned long long)xw_done, (unsigned long long)xw_pres_done, (unsigned long long)xw_pres_enq);
}
static void xw_wait_job(uint64_t n) {
    if (xw_is_worker) return;
    pthread_mutex_lock(&xw_lock);
    while (xw_done < n) xw_cond_wait("xw_wait_job");
    pthread_mutex_unlock(&xw_lock);
}

// Waits until everything enqueued is translated and submitted. Has no effect when called from the worker itself.
static void xw_drain(void) {
    if (xw_is_worker) return;
    pthread_mutex_lock(&xw_lock);
    while (xw_done < xw_tail) xw_cond_wait("xw_drain");
    pthread_mutex_unlock(&xw_lock);
}
