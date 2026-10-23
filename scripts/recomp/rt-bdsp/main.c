// Entry point of the BDSP runtime (gate 1): reserve the guest window, load modules, start nn::init::Start on a host thread,
// supervise the run (time limit, gate detection, progress lines) and print the result log.
// No graphics, no audio output. Own code.
#ifdef __APPLE__
#include <TargetConditionals.h>
#endif
#include <errno.h>
#include <mach/mach.h>
#include <signal.h>
#include <sys/mman.h>
#include <sys/resource.h>
#include <unistd.h>
#if !defined(__APPLE__) || !TARGET_OS_IPHONE
#include <mach/mach_vm.h>
#endif

#include "bdsp.h"
#ifdef BDSP_APP
#include "app/app.h"
#endif

#ifdef BDSP_REBASE32
uint8_t *g_base;
#endif

// Claim the guest window before anything else (otherwise the host allocator places regions in the same window).
#ifdef BDSP_REBASE32
// Variant B: 4 GiB window anywhere in the host address space; pages are only committed on access (anonymous, zero). The first 64 KiB stay
// blocked, so null pointers of the guest crash as on the console.
__attribute__((constructor(101))) static void reserve_guest_space(void) {
    void *p = mmap(NULL, GUEST_HI - GUEST_LO, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANON, -1, 0);
    if (p == MAP_FAILED) { fprintf(stderr, "FATAL: guest window (4 GiB) cannot be reserved: %s\n", strerror(errno)); _exit(1); }
    g_base = p;
    mprotect(p, 0x10000, PROT_NONE);
}
#elif defined(BDSP_COMPACT_BASE)
// Variant A-low (iOS): the compact layout at a fixed address (guest address == host address). mach_vm_allocate does not exist on iOS.
__attribute__((constructor(101))) static void reserve_guest_space(void) {
    vm_address_t a = GUEST_LO;
    if (vm_allocate(mach_task_self(), &a, GUEST_HI - GUEST_LO, VM_FLAGS_FIXED) == KERN_SUCCESS) return;
    fprintf(stderr, "FATAL: guest window %llx-%llx is not free\n", (unsigned long long)GUEST_LO, (unsigned long long)GUEST_HI);
    _exit(1);
}
#else
__attribute__((constructor(101))) static void reserve_guest_space(void) {
    mach_vm_address_t a = GUEST_LO;
    if (mach_vm_allocate(mach_task_self(), &a, GUEST_HI - GUEST_LO, VM_FLAGS_FIXED) == KERN_SUCCESS) return;
    fprintf(stderr, "FATAL: guest window %llx-%llx is not free\n", (unsigned long long)GUEST_LO, (unsigned long long)GUEST_HI);
    _exit(1);
}
#endif

// ---- Guest log (lm and OutputDebugString)
static pthread_mutex_t log_lock = PTHREAD_MUTEX_INITIALIZER;
static char last_line[1024];
static uint64_t log_lines;
void guest_log(const char *line) {
    pthread_mutex_lock(&log_lock);
    snprintf(last_line, sizeof last_line, "%s", line);
    log_lines++;
    uint64_t n = log_lines;
    pthread_mutex_unlock(&log_lock);
    static int verbose = -1;
    if (verbose < 0) verbose = getenv("BDSP_LOG_ALL") != NULL;
    if (verbose || n <= 400) printf("[guest] %s\n", line);
}

static long rss_now_mib(void) {
    mach_task_basic_info_data_t info;
    mach_msg_type_number_t cnt = MACH_TASK_BASIC_INFO_COUNT;
    if (task_info(mach_task_self(), MACH_TASK_BASIC_INFO, (task_info_t)&info, &cnt) != KERN_SUCCESS) return -1;
    return (long)(info.resident_size >> 20);
}
static long rss_peak_mib(void) { struct rusage ru; getrusage(RUSAGE_SELF, &ru); return (long)(ru.ru_maxrss >> 20); }

// ---- rtld replacement: nn::init::Start calls x2 after nnosInitialize (initialisation of the SDK module) and x3 before nnMain (main)
static void module_init(Cpu *c, Module *m) {
    LOG("[init] %s (DT_INIT %llx, %llu init_array entries)\n", m->name, (unsigned long long)(m->base + m->init), (unsigned long long)(m->init_array_sz / 8));
    if (m->init) { guest_call(c, m->base + m->init); return; }
    for (uint64_t i = 0; i < m->init_array_sz / 8; i++) {
        uint64_t fn = *G2H64(m->base + m->init_array + i * 8);
        if (fn) guest_call(c, fn);
    }
}
static void rtld_init_sdk(Cpu *c) { module_init(c, &g_modules[1]); }
static void rtld_init_main(Cpu *c) { module_init(c, &g_modules[0]); }
static void rtld_nop(Cpu *c) { (void)c; LOG("[init] fini callback after nnMain reached\n"); }

static volatile uint64_t g_start_ns;
uint64_t g_proc_start_ns;   // process start (time base of the input test script in nvn/nvn_glue.c)
static pthread_t g_main_thread_id;
static volatile uint64_t g_stress_cycles;
static void report(const char *why) {
    double secs = (rt_now_ns() - g_start_ns) / 1e9;
    fflush(NULL);
    printf("\n==== RESULT: %s after %.1f s ====\n", why, secs);
    kernel_report(stdout);
    pthread_mutex_lock(&log_lock);
    printf("Guest log lines: %llu, last: %s\n", (unsigned long long)log_lines, last_line[0] ? last_line : "(none)");
    pthread_mutex_unlock(&log_lock);
    gate_report(stdout);
    printf("NVN functions without host implementation (called by the guest):\n");
    if (!hle_unimpl_report(stdout)) printf("  (none)\n");
    nvn_report(stdout);
    if (getenv("BDSP_NVN_STATS")) hle_stats_report(stdout);
    ipc_stats(stdout);
    fs_report(stdout);
    printf("RSS now %ld MiB, peak %ld MiB\n", rss_now_mib(), rss_peak_mib());
    if (g_stress_cycles) printf("Suspend stress test (BDSP_SUSPEND_STRESS): %llu suspend/context/resume cycles on running guest threads\n", (unsigned long long)g_stress_cycles);
    fflush(NULL);
}

static void *suspend_stress(void *arg) {
    (void)arg;
    Cpu c;
    memset(&c, 0, sizeof c);
    uint8_t *buf = malloc(0x400);
    uint64_t gbuf = H2G(hle_alloc(0x400));
    (void)buf;
    for (;;) {
        for (uint32_t h = 0x101; h < 0x101 + 256; h++) {
            KObject *o = handle_get(h);
            if (!o || o->type != KOBJ_THREAD) continue;
            c.x[0] = h; c.x[1] = 1; rt_svc(&c, 0x32, 0);                 // anhalten
            if (c.x[0] == 0) {
                c.x[0] = gbuf; c.x[1] = h; rt_svc(&c, 0x33, 0);          // Kontext lesen
                c.x[0] = h; c.x[1] = 0; rt_svc(&c, 0x32, 0);             // fortsetzen
                g_stress_cycles++;
            }
        }
        usleep(200);
    }
    return NULL;
}

static void on_sigint(int s) { (void)s; g_stop = 4; }

static int g_stop_at_gate;
static const char *volatile g_fatal_why;
static volatile int g_fatal_code;
void bdsp_fatal_report(const char *why, int code) {
    g_fatal_code = code;
    g_fatal_why = why;
    if (g_main_thread_id && pthread_equal(pthread_self(), g_main_thread_id)) { report(why); _exit(code); }  // before the guest threads start
}
void bdsp_gate_hit(const char *what) {
    if (!g_stop_at_gate) return;
    static volatile int once;
    if (__atomic_exchange_n(&once, 1, __ATOMIC_SEQ_CST)) return;
    char why[128];
    snprintf(why, sizeof why, "Gate 1 reached (%s was called)", what);
    report(why);
    _exit(0);
}

static int g_timeout = 120;

// A fixed amount of dependent integer work, best of three: its duration follows the CPU clock, so thermal throttling shows in the perf log
// (microseconds; the same number on a cool and a throttled device means the game's growing cost per frame is not the clock).
static uint64_t cpu_cal_us(void) {
    uint64_t best = ~0ull;
    for (int r = 0; r < 3; r++) {
        uint64_t t0 = rt_now_ns(), x = 88172645463325252ull;
        for (int i = 0; i < 4000000; i++) { x ^= x << 13; x ^= x >> 7; x ^= x << 17; }
        __asm__ volatile("" : : "r"(x));
        uint64_t d = (rt_now_ns() - t0) / 1000;
        if (d < best) best = d;
    }
    return best;
}

// Supervision: time limit, guest end, crash report, progress lines
static void *monitor_loop(void *arg) {
    (void)arg;
    uint64_t last_progress = 0, last_perf = 0;
    const char *why = "time limit";
    const int perf_log = getenv("BDSP_PERF_LOG") != NULL || g_count_n > 0;
    if (perf_log) pthread_set_qos_class_self_np(QOS_CLASS_USER_INTERACTIVE, 0);   // stay on a performance core: the calibration must see the clock
    for (;;) {
        usleep(20000);
        double secs = (rt_now_ns() - g_start_ns) / 1e9;
        if (g_fatal_why) { report(g_fatal_why); _exit(g_fatal_code); }
        if (g_stop) { why = g_stop == 3 ? "guest requested exit" : g_stop == 4 ? "abort (SIGINT)" : "guest ended the process"; break; }
        if (secs > g_timeout) break;
        if (perf_log && (uint64_t)secs > last_perf) {   // cumulative values; the difference between two lines is the rate
            last_perf = (uint64_t)secs;
            char fns[160] = "";
            for (int i = 0, n = 0; i < g_count_n; i++)
                n += snprintf(fns + n, sizeof fns - n, " %llx=%llu", (unsigned long long)g_count_addr[i], (unsigned long long)g_count_hits[i]);
            struct rusage ru;   // CPU time of all threads: independent of the frame rate cap, so growing cost per frame shows at 120 fps too
            getrusage(RUSAGE_SELF, &ru);
            long long cpu_ms = ((long long)ru.ru_utime.tv_sec + ru.ru_stime.tv_sec) * 1000 + (ru.ru_utime.tv_usec + ru.ru_stime.tv_usec) / 1000;
            LOG("[perf] %.0f s frames %llu cpu_ms %lld gc_suspends %llu gc_resumes %llu rss %ld MiB cal_us %llu fn%s\n", secs, (unsigned long long)renderer_present_count(),
                cpu_ms, (unsigned long long)g_suspends, (unsigned long long)g_resumes, rss_now_mib(), (unsigned long long)cpu_cal_us(), fns);
        }
        if ((uint64_t)secs >= last_progress + 10) {
            last_progress = (uint64_t)secs;
            LOG("[progress] %.0f s, Threads %d, RSS %ld MiB\n", secs, kernel_thread_count(), rss_now_mib());
        }
    }
    if (getenv("BDSP_DUMP")) rt_fatal_trace();   // memory dump also at the time limit
    if (getenv("BDSP_RINGDUMP")) fnprof_report(stdout, (unsigned)atoi(getenv("BDSP_RINGDUMP")));
    report(why);
    _exit(0);
    return NULL;
}

int main(int argc, char **argv) {
    setvbuf(stdout, NULL, _IOLBF, 0);
    setvbuf(stderr, NULL, _IOLBF, 0);
#ifdef BDSP_APP
    bdsp_app_init(argc, argv);   // macOS app: paths/configuration, environment of the runtime, save backup (rt-bdsp/app)
#endif
    signal(SIGINT, on_sigint);
    signal(SIGPIPE, SIG_IGN);
#ifndef BDSP_APP
    {   // without the app configuration (bdsp_boot32, tests): BDSP_FPS=30|60|120 sets the frame rate target
        extern volatile int g_bdsp_fps;
        int f = getenv("BDSP_FPS") ? atoi(getenv("BDSP_FPS")) : 0;
        if (f == 30 || f == 60 || f == 120) g_bdsp_fps = f;
    }
#endif
    int no_window = 0;
#ifdef BDSP_NVN_NONE
    no_window = 1;
#endif
    for (int i = 1; i < argc; i++) {   // options (set the environment variables of the NVN layer)
        if (!strcmp(argv[i], "--screenshot-after") && i + 1 < argc) {   // save frame no. N to work/recomp/shots (BDSP_SHOT_DIR)
            setenv("BDSP_SCREENSHOT_EVERY", argv[i + 1], 1);
            setenv("BDSP_SCREENSHOT_FROM", argv[i + 1], 1);
            i++;
        } else if (!strcmp(argv[i], "--exit-after-shot")) setenv("BDSP_EXIT_AFTER_SHOT", "1", 1);
        else if (!strcmp(argv[i], "--headless")) setenv("BDSP_HIDDEN", "1", 1);   // window never visible, rendering stays Metal
        else if (!strcmp(argv[i], "--window") && i + 1 < argc) setenv("BDSP_WINDOW", argv[++i], 1);
        else if (!strcmp(argv[i], "--no-window")) no_window = 1;   // no graphics (gate 1 measurement only): NVN functions stay unused
        else if (!strcmp(argv[i], "--input-script") && i + 1 < argc) setenv("BDSP_INPUT_SCRIPT", argv[++i], 1);   // "second:KEY[+KEY]:duration,..." (nvn_glue.c)
        else if (!strcmp(argv[i], "--save") && i + 1 < argc) setenv("BDSP_SAVE", argv[++i], 1);   // save folder (default work/recomp/save, see install_save.sh)
        else if (!strcmp(argv[i], "--timeout") && i + 1 < argc) setenv("BDSP_TIMEOUT", argv[++i], 1);
        else { fprintf(stderr, "unbekannte Option %s\n", argv[i]); return 2; }
    }
    const char *img = getenv("BDSP_IMG") ? getenv("BDSP_IMG") : "work/recomp/img";
    const char *npdm = getenv("BDSP_NPDM") ? getenv("BDSP_NPDM") : "work/exefs/main.npdm";
    g_timeout = getenv("BDSP_TIMEOUT") ? atoi(getenv("BDSP_TIMEOUT")) : 120;
    int timeout = g_timeout;
    fs_set_dirs(getenv("BDSP_ROMFS"), getenv("BDSP_SAVE"));
    g_start_ns = rt_now_ns();
    g_proc_start_ns = g_start_ns;
    g_main_thread_id = pthread_self();

    uint32_t stack_size = 0x100000;
    int prio = 44;
    FILE *f = fopen(npdm, "rb");
    if (f) {
        uint8_t meta[0x80];
        if (fread(meta, 1, sizeof meta, f) == sizeof meta && !memcmp(meta, "META", 4)) {
            prio = meta[0xE];
            g_system_resource_size = *(uint32_t *)(meta + 0x14);
            stack_size = *(uint32_t *)(meta + 0x1C);
            uint32_t aci0 = *(uint32_t *)(meta + 0x70);
            uint8_t aci[0x20];
            if (!fseek(f, aci0, SEEK_SET) && fread(aci, 1, sizeof aci, f) == sizeof aci && !memcmp(aci, "ACI0", 4)) memcpy(&g_program_id, aci + 0x10, 8);
        }
        fclose(f);
    }

    kernel_init();
    loader_load(img);
    dispatch_init();
    if (getenv("BDSP_WATCH")) {   // debugging: "hexaddress,hexaddress": log calls through the dispatcher with x0..x2 and lr
        char *spec = strdup(getenv("BDSP_WATCH")), *sv = NULL;
        for (char *tok = strtok_r(spec, ",", &sv); tok; tok = strtok_r(NULL, ",", &sv)) watch_add(strtoull(tok, NULL, 16), tok);
    }
    nvn_glue_init();
    kernel_region_add(TLS_BASE, TLS_SIZE, 0xB, 3);
    kernel_region_add(HLE_HEAP, HLE_HEAP_SIZE, 0xB, 3);
    g_stop_at_gate = getenv("BDSP_STOP_AT_GATE") != NULL && atoi(getenv("BDSP_STOP_AT_GATE"));   // gate 1 only on request (gate 2: keep running)

    uint64_t start = loader_find_symbol("_ZN2nn4init5StartEmmPFvvES2_S2_");
    if (!start) rt_fatal("nn::init::Start not found\n");
    uint64_t init_fn = hle_register("<rtld_init_sdk>", rtld_init_sdk);
    uint64_t fini_fn = hle_register("<rtld_init_main>", rtld_init_main);
    uint64_t nop_fn = hle_register("<rtld_fini>", rtld_nop);
    LOG("[boot] main thread: priority %d, guest stack 0x%x, host stack %s MiB, time limit %d s\n", prio, stack_size,
        getenv("BDSP_HOST_STACK_MB") ? getenv("BDSP_HOST_STACK_MB") : "16", timeout);
    KThread *t = kernel_create_main_thread(start, stack_size, prio, 0);
    t->cpu.x[4] = nop_fn;
    kernel_run_main(t, t->handle, 0, init_fn, fini_fn);  // nn::init::Start(thread_handle, args_region, init, init_main, fini)
    if (getenv("BDSP_SUSPEND_STRESS")) {  // check of the GC path: a host thread suspends all guest threads in turn (SVC 0x32/0x33) and resumes them
        pthread_t st;
        pthread_create(&st, NULL, suspend_stress, NULL);
        pthread_detach(st);
    }
    if (no_window) { monitor_loop(NULL); return 0; }
    // The main thread belongs to the window (AppKit/SDL require it); the supervision runs in its own thread.
    pthread_t mt;
    pthread_create(&mt, NULL, monitor_loop, NULL);
    pthread_detach(mt);
    ui_run();
    return 0;
}
