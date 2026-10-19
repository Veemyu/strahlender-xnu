// Übersetzungs-Worker (BDSP_EXEC_WORKER=1, Standard aus), eingebunden von renderer.m über exec_worker.patch.
// backend_execute reiht die Handles ein; ein Worker-Thread führt exec_list und renderer_submit in Reihenfolge aus.
// Gast-seitige Synchronisation (renderer_submit, renderer_sync, renderer_fence_seq, renderer_wait_seq) wartet vorher auf den Worker.
// Ohne Umgebungsvariable sind alle Zähler 0 und die Drains kehren sofort zurück.
void renderer_submit(void);
static void exec_list(uint64_t handle, int depth);

#define XW_CAP 1024
static pthread_mutex_t xw_lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t xw_cond = PTHREAD_COND_INITIALIZER;
static uint64_t xw_handles[XW_CAP], xw_tail, xw_next, xw_done;   // eingereiht / übernommen / fertig
static int xw_on = -1;
static __thread int xw_is_worker;

static void *xw_main(void *arg) {
    (void)arg;
    xw_is_worker = 1;
    for (;;) {
        pthread_mutex_lock(&xw_lock);
        while (xw_next == xw_tail) pthread_cond_wait(&xw_cond, &xw_lock);
        uint64_t h = xw_handles[xw_next % XW_CAP];
        xw_next++;
        pthread_mutex_unlock(&xw_lock);
        @autoreleasepool {
            exec_list(h, 0);
            renderer_submit();
        }
        pthread_mutex_lock(&xw_lock);
        xw_done++;
        pthread_cond_broadcast(&xw_cond);
        pthread_mutex_unlock(&xw_lock);
    }
    return NULL;
}

static int xw_enabled(void) {
    if (xw_on < 0) {
        xw_on = getenv("BDSP_EXEC_WORKER") != NULL;
        if (xw_on) {
            pthread_t t;
            pthread_create(&t, NULL, xw_main, NULL);
            pthread_detach(t);
        }
    }
    return xw_on;
}

static void xw_enqueue(uint64_t h) {
    pthread_mutex_lock(&xw_lock);
    while (xw_tail - xw_done >= XW_CAP) pthread_cond_wait(&xw_cond, &xw_lock);
    xw_handles[xw_tail % XW_CAP] = h;
    xw_tail++;
    pthread_cond_broadcast(&xw_cond);
    pthread_mutex_unlock(&xw_lock);
}

// Fence-Token: Bit 63 gesetzt, Rest = Anzahl der bis dahin eingereihten Jobs. Der Wartende wartet nur bis zu diesem Job,
// nicht auf die ganze Warteschlange.
#define XW_TAG (1ull << 63)
static uint64_t xw_fence_token(void) {
    pthread_mutex_lock(&xw_lock);
    uint64_t t = xw_tail;
    pthread_mutex_unlock(&xw_lock);
    return XW_TAG | t;
}
static void xw_wait_job(uint64_t n) {
    if (xw_is_worker) return;
    pthread_mutex_lock(&xw_lock);
    while (xw_done < n) pthread_cond_wait(&xw_cond, &xw_lock);
    pthread_mutex_unlock(&xw_lock);
}

// Wartet, bis alles Eingereihte übersetzt und eingereicht ist. Vom Worker selbst aus wirkungslos.
static void xw_drain(void) {
    if (xw_is_worker) return;
    pthread_mutex_lock(&xw_lock);
    while (xw_done < xw_tail) pthread_cond_wait(&xw_cond, &xw_lock);
    pthread_mutex_unlock(&xw_lock);
}
