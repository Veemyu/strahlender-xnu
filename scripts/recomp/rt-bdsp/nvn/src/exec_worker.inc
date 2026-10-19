// Übersetzungs-Worker (Mac: Standard an, BDSP_EXEC_WORKER=0 = alter synchroner Pfad), eingebunden von renderer.m.
// backend_execute reiht die Handles ein; ein Worker-Thread führt exec_list und renderer_submit in Reihenfolge aus.
// backend_present (metal.m) reiht die Präsentation als Job ein (renderer_worker_present), der Gast läuft höchstens
// BDSP_EXEC_FRAMES (Standard 2) Bilder voraus.
// Gast-seitige Synchronisation (renderer_submit, renderer_sync, renderer_fence_seq, renderer_wait_seq) wartet vorher auf den Worker.
// Ohne Umgebungsvariable sind alle Zähler 0 und die Drains kehren sofort zurück.
void renderer_submit(void);
static void exec_list(uint64_t handle, int depth);

#define XW_CAP 8192
static pthread_mutex_t xw_lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t xw_cond = PTHREAD_COND_INITIALIZER;
static uint64_t xw_handles[XW_CAP], xw_tail, xw_next, xw_done;   // eingereiht / übernommen / fertig
static void *xw_blocks[XW_CAP];   // != NULL: Präsentations-Job (retained Block) statt Befehlsliste
static uint8_t xw_isp[XW_CAP];   // Block ist eine Präsentation (zählt für die Bild-Vorlaufgrenze)
static uint64_t xw_chk[XW_CAP];   // Prüfsumme der Datensätze beim Einreihen (nur BDSP_XW_CHECK)
static int xw_check;
static uint64_t xw_list_hash(uint64_t handle);
bool xw_ordered(void (*fn)(void *), void *arg);
static void *xw_snaps[XW_CAP];   // Kopie der Liste samt Uniform-/Indexdaten (BDSP_XW_SNAP), vom Worker nach der Ausführung freigegeben
static void xw_snap_free(void *s);
static uint64_t xw_pres_enq, xw_pres_done;   // eingereihte / fertige Präsentationen
static int xw_max_frames = 2;   // so viele Bilder darf der Gast dem Worker voraus sein (BDSP_EXEC_FRAMES)
static int xw_on = -1;
static __thread int xw_is_worker;

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
        xw_next++;
        pthread_mutex_unlock(&xw_lock);
        @autoreleasepool {
            if (blk) {
                void (^job)(void) = CFBridgingRelease(blk);
                job();
            } else {
                if (xw_check) {   // BDSP_XW_CHECK=1: wurden die Befehlsdatensätze zwischen Einreihen und Ausführen verändert?
                    static uint64_t njobs, nbad;
                    njobs++;
                    if (xw_list_hash(h) != chk) {
                        nbad++;
                        if (nbad <= 30) printf("[xw] Befehlsliste %llx wurde nach dem Einreihen verändert (%llu von %llu)\n", (unsigned long long)h, (unsigned long long)nbad, (unsigned long long)njobs);
                    }
                    if (njobs % 1000 == 0) printf("[xw] Listen %llu, verändert %llu\n", (unsigned long long)njobs, (unsigned long long)nbad);
                }
                exec_list(h, 0);
                if (snap) xw_snap_free(snap);
                renderer_submit();
            }
        }
        pthread_mutex_lock(&xw_lock);
        if (blk && isp) xw_pres_done++;
        xw_done++;
        pthread_cond_broadcast(&xw_cond);
        pthread_mutex_unlock(&xw_lock);
    }
    return NULL;
}

static int xw_enabled(void) {
    if (xw_on < 0) {
        const char *ew = getenv("BDSP_EXEC_WORKER");   // Mac: Standard an; BDSP_EXEC_WORKER=0 schaltet auf den alten synchronen Pfad
        xw_on = !(ew && !strcmp(ew, "0"));
        xw_check = xw_on && getenv("BDSP_XW_CHECK") != NULL;
        if (xw_on) {
            extern bool (*g_nvn_ordered)(void (*)(void *), void *);
            g_nvn_ordered = xw_ordered;
            if (getenv("BDSP_EXEC_FRAMES") && atoi(getenv("BDSP_EXEC_FRAMES")) > 0) xw_max_frames = atoi(getenv("BDSP_EXEC_FRAMES"));
            pthread_t t;
            pthread_create(&t, NULL, xw_main, NULL);
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
    xw_tail++;
    pthread_cond_broadcast(&xw_cond);
    pthread_mutex_unlock(&xw_lock);
}

// Präsentation als Job in dieselbe Warteschlange (Reihenfolge zu den Befehlslisten bleibt). Der Gast wartet nur, wenn er mehr
// als xw_max_frames Bilder voraus ist. false: Worker aus (oder Aufruf aus dem Worker), der Aufrufer präsentiert selbst.
bool renderer_worker_present(void (^job)(void)) {
    if (!xw_enabled() || xw_is_worker) return false;
    void *blk = (void *)CFBridgingRetain([job copy]);
    pthread_mutex_lock(&xw_lock);
    while (xw_tail - xw_done >= XW_CAP) pthread_cond_wait(&xw_cond, &xw_lock);
    xw_handles[xw_tail % XW_CAP] = 0;
    xw_blocks[xw_tail % XW_CAP] = blk;
    xw_isp[xw_tail % XW_CAP] = 1;
    xw_snaps[xw_tail % XW_CAP] = NULL;
    xw_tail++;
    xw_pres_enq++;
    pthread_cond_broadcast(&xw_cond);
    while (xw_pres_enq - xw_pres_done > (uint64_t)xw_max_frames) pthread_cond_wait(&xw_cond, &xw_lock);
    pthread_mutex_unlock(&xw_lock);
    return true;
}

// Fence-Token: Bit 63 gesetzt, Rest = Anzahl der bis dahin eingereihten Jobs. Der Wartende wartet nur bis zu diesem Job,
// nicht auf die ganze Warteschlange.
// Zustandsänderungen des Gasts, die der Worker beim Ausführen liest (Textur-/Sampler-Pools), laufen in Reihenfolge der
// Warteschlange: Der Gast reiht die Änderung ein statt sie sofort zu schreiben; der Worker wendet sie zwischen den Listen an.
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
static uint64_t xw_next_token(void) {   // Token des Jobs, der als nächster eingereiht wird (nur ein einreichender Thread)
    pthread_mutex_lock(&xw_lock);
    uint64_t t = xw_tail + 1;
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
