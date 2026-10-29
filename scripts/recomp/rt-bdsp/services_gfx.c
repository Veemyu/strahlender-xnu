// Graphics-related services of the BDSP runtime for gate 1: vi:u/vi:s/vi:m (display service) and nvdrv (device driver) as logging
// stubs without graphics output. They answer the SDK initialisation (nn::vi::Initialize, nvdrv open/ioctl) with plausible
// values, so the guest runs up to the call of nvnBootstrapLoader; the real NVN/Metal layer is gate 2. Own code.
#include <time.h>
#include <unistd.h>

#include "bdsp.h"

#define UNHANDLED(name) do { ipc_note(name, req->cmd, 1); resp_size(resp, 0x10); } while (0)

static uint32_t new_event_handle(KEvent **out) {
    uint32_t w, r;
    KEvent *e = kernel_create_event_pair(&w, &r);
    if (out) *out = e;
    return r;
}

// ---- Vsync event without a display (the guest waits for this event before it starts a frame)
static KEvent *g_vsync;
volatile int g_bdsp_paused;   // set by the app shell (pause, focus loss): the vsync event stays off, the game waits
volatile int g_bdsp_fps = 60; // frame rate: 30, 60 or 120 (app setting, see bdsp_set_fps)
void bdsp_set_fps(int fps) {
    if (fps == 30 || fps == 60 || fps == 120) g_bdsp_fps = fps;
}
// Absolute target times instead of a relative nanosleep: otherwise the clock drifts to ~20 ms (≈50 Hz) and the game stays at 50 fps.
uint64_t g_vsync_ticks;   // hang diagnosis: number of vsync events; BDSP_VSYNC_LOG=1 prints it every 2 s (is the clock still alive when the guest no longer progresses?)
static void *vsync_thread(void *arg) {
    (void)arg;
    uint64_t next = plat_now_ns();
    static int vlog = -1;
    if (vlog < 0) vlog = getenv("BDSP_VSYNC_LOG") != NULL;
    for (;;) {
        uint64_t period = 1000000000ull / (uint64_t)g_bdsp_fps;
        next += period;
        uint64_t now = plat_now_ns();
        if (next > now) {
            uint64_t d = next - now;
            struct timespec ts = {(time_t)(d / 1000000000ull), (long)(d % 1000000000ull)};
            nanosleep(&ts, NULL);
        } else if (now > next + 4 * period) {
            next = now;   // restart after a standstill (e.g. loading), no catching up
        }
        while (g_bdsp_paused) {
            nanosleep(&(struct timespec){0, 10000000}, NULL);
            next = plat_now_ns();
        }
        pthread_mutex_lock(&g_klock);
        kernel_signal(g_vsync);
        pthread_mutex_unlock(&g_klock);
        hid_idle_tick();
        if (vlog) {   // BDSP_VSYNC_LOG only: no counting without it
            uint64_t n = ++g_vsync_ticks;
            if (n % 120 == 0) LOG("[vsync] %llu Ereignisse, signaled=%d\n", (unsigned long long)n, g_vsync ? (int)g_vsync->signaled : -1);
        }
    }
    return NULL;
}
uint32_t vi_vsync_handle(void) {
    static uint32_t handle;
    if (!g_vsync) {
        uint32_t w;
        g_vsync = kernel_create_event_pair(&w, &handle);
        pthread_t t;
        pthread_attr_t a;
        pthread_attr_init(&a);
        pthread_attr_setstacksize(&a, 256 << 10);
        pthread_create(&t, &a, vsync_thread, NULL);
        pthread_detach(t);
    }
    return handle;
}

// ---- IHOSBinderDriver (parcel transactions of the Android buffer queue): only logged, response empty
static void hos_binder(Service *s, IpcReq *req, IpcResp *resp) {
    (void)s;
    switch (req->cmd) {
    case 0: case 3: {  // TransactParcel(binder id, code, flags, A in, B out)
        uint32_t code = IN(uint32_t, 4);
        ipc_note("IHOSBinderDriver.Transact", code, 0);
        IpcBuf *b = out_buf(req, 0);
        if (b && b->size) memset(G2H(b->addr), 0, b->size < 0x400 ? b->size : 0x400);
        break;
    }
    case 1: break;                                                    // AdjustRefcount
    case 2: resp->copy_handles[resp->ncopy++] = new_event_handle(NULL); break;  // GetNativeHandle
    case 4: break;                                                    // TransactParcelAuto
    default: UNHANDLED("IHOSBinderDriver");
    }
}

// ---- IApplicationDisplayService
static void vi_display_service(Service *s, IpcReq *req, IpcResp *resp) {
    (void)s;
    switch (req->cmd) {
    case 100: ipc_return_object(resp, service_new("IHOSBinderDriver", hos_binder, NULL)); break;  // GetRelayService
    case 101: case 102: case 103: ipc_return_object(resp, service_new("IHOSBinderDriver", hos_binder, NULL)); break;
    case 1000: {  // ListDisplays -> count; one entry "Default" in the B buffer
        IpcBuf *b = out_buf(req, 0);
        if (b && b->size >= 0x60) {
            uint8_t *d = G2H8(b->addr);
            memset(d, 0, 0x60);
            strcpy((char *)d, "Default");
            *(uint64_t *)(d + 0x48) = 1;
            *(uint64_t *)(d + 0x50) = 1920;
            *(uint64_t *)(d + 0x58) = 1080;
        }
        OUT(int64_t, 0) = 1;
        resp_size(resp, 8);
        break;
    }
    case 1010: case 1011: OUT(uint64_t, 0) = 1; resp_size(resp, 8); break;   // OpenDisplay/OpenDefaultDisplay -> Anzeigen-Id
    case 1020: case 1101: break;                                             // CloseDisplay, SetDisplayEnabled
    case 1102: OUT(int64_t, 0) = 1920; OUT(int64_t, 8) = 1080; resp_size(resp, 16); break;  // GetDisplayResolution
    case 2020: case 2030: {  // OpenLayer / CreateStrayLayer -> layer ID and size of the native window parcel (B buffer)
        IpcBuf *b = out_buf(req, 0);
        if (b && b->size) memset(G2H(b->addr), 0, b->size < 0x400 ? b->size : 0x400);
        OUT(uint64_t, 0) = 1;
        OUT(uint64_t, 8) = 0;
        resp_size(resp, 16);
        break;
    }
    case 2021: case 2031: case 2101: break;                                   // CloseLayer, DestroyStrayLayer, SetLayerScalingMode
    case 5202: resp->copy_handles[resp->ncopy++] = vi_vsync_handle(); break;    // GetDisplayVsyncEvent
    default: UNHANDLED("IApplicationDisplayService");
    }
}
static void vi_root(Service *s, IpcReq *req, IpcResp *resp) {
    (void)s;
    if (req->cmd == 0 || req->cmd == 1 || req->cmd == 2 || req->cmd == 3)  // GetDisplayService (u: 0, s: 1, m: 2)
        ipc_return_object(resp, service_new("IApplicationDisplayService", vi_display_service, NULL));
    else UNHANDLED("vi");
}

// ---- nvdrv: Open returns file descriptors, ioctl "success" with zeros (no driver behind the service)
static int g_nv_fd = 1;
// ---- "Null GPU": the ioctls of the nvgpu driver are answered with plausible values, there is no hardware behind them
enum { DEV_UNKNOWN, DEV_NVMAP, DEV_CTRL, DEV_CTRL_GPU, DEV_AS_GPU, DEV_GPU };
static uint8_t nv_dev[256];
static uint32_t nv_next_handle = 0x1000;
static uint64_t nv_next_va = 0x100000000ull;  // GPU address space: handed out consecutively
static uint32_t nv_map_size[4096];

static void nv_ioctl(int dev, uint32_t cmd, const uint8_t *in, uint32_t isz, uint8_t *out, uint32_t osz) {
    uint32_t nr = cmd & 0xFF, type = (cmd >> 8) & 0xFF;
    if (out && in && osz) memcpy(out, in, isz < osz ? isz : osz);  // input/output ioctls: the response starts with the input
    else if (out && osz) memset(out, 0, osz);
    if (!out) return;
    switch (dev) {
    case DEV_CTRL_GPU:
        if (type == 0x47 && nr == 5 && osz >= 176) {  // GET_CHARACTERISTICS: {buffer size, buffer address, characteristics (0xA0)}
            uint8_t *c = out + 16;
            memset(c, 0, 160);
            uint32_t *w = (uint32_t *)c;
            w[0] = 0x120; w[1] = 0xB; w[2] = 0xA1; w[3] = 1;                    // arch, impl, rev, num_gpc
            *(uint64_t *)(c + 16) = 0x40000;                                     // L2-Cache
            w[9] = 2; w[10] = 0x20; w[11] = 0x20000; w[12] = 0x20000; w[13] = 0x1B; w[14] = 0x30000;  // tpc, bus, big page, comp page, pde bits, big page sizes
            w[15] = 1; w[16] = 0x503; w[17] = 0x503; w[18] = 0x80; w[19] = 0x28;  // gpc mask, sm version, spa version, warps, VA-Bits
            *(uint64_t *)(c + 88 - 0) = 0x55;                                    // flags
            w[23] = 0x902D; w[24] = 0xB197; w[25] = 0xB1C0; w[26] = 0xB06F; w[27] = 0xA140; w[28] = 0xB0B5;  // Klassen
            w[29] = 1; w[31] = 2; w[32] = 1; w[34] = 1; w[35] = 0x21D70;
            *(uint64_t *)out = 160;
        } else if (type == 0x47 && nr == 6 && osz >= 24) {  // GET_TPC_MASKS
            *(uint32_t *)out = 8;
            *(uint64_t *)(out + 8) = 0;
            *(uint32_t *)(out + 16) = 3;
        }
        break;
    case DEV_NVMAP:
        if (nr == 1 && osz >= 8) {                       // CREATE {size, handle}
            uint32_t h = nv_next_handle++;
            if ((h & 0xFFF) < 4096) nv_map_size[h & 0xFFF] = *(uint32_t *)in;
            *(uint32_t *)(out + 4) = h;
        } else if (nr == 3 && osz >= 8) *(uint32_t *)(out + 4) = *(uint32_t *)in;           // FROM_ID {id, handle}
        else if (nr == 14 && osz >= 8) *(uint32_t *)(out + 4) = *(uint32_t *)in;           // GET_ID {id, handle}
        else if (nr == 9 && osz >= 12) {                 // PARAM {handle, param, result}
            uint32_t h = *(uint32_t *)in, p = *(uint32_t *)(in + 4);
            *(uint32_t *)(out + 8) = p == 1 ? nv_map_size[h & 0xFFF] : p == 2 ? 0x20000 : 0;  // 1 SIZE, 2 ALIGNMENT
        }
        break;
    case DEV_AS_GPU:
        if (nr == 2 && osz >= 24) {                      // ALLOC_SPACE {pages, page_size, flags, pad, offset}
            uint32_t pages = *(uint32_t *)in, ps = *(uint32_t *)(in + 4);
            uint64_t sz = (uint64_t)pages * ps;
            nv_next_va = (nv_next_va + ps - 1) & ~(uint64_t)(ps - 1);
            *(uint64_t *)(out + 16) = nv_next_va;
            nv_next_va += sz;
        } else if (nr == 6 && osz >= 40) {               // MAP_BUFFER_EX {flags, kind, handle, page_size, offset_in, mapping_size, offset}
            uint32_t h = *(uint32_t *)(in + 8);
            uint64_t sz = nv_map_size[h & 0xFFF] ? nv_map_size[h & 0xFFF] : 0x1000;
            nv_next_va = (nv_next_va + 0xFFFF) & ~(uint64_t)0xFFFF;
            *(uint64_t *)(out + 32) = nv_next_va;
            nv_next_va += (sz + 0xFFFF) & ~(uint64_t)0xFFFF;
        } else if (nr == 8 && osz >= 64) {               // GET_VA_REGIONS: zwei Bereiche
            *(uint32_t *)(out + 8) = 2 * 24;
            *(uint64_t *)(out + 16) = 0x20000;           // range 0: start, page size, pages
            *(uint32_t *)(out + 24) = 0x20000;
            *(uint64_t *)(out + 32) = 0x7FFFFF;
        }
        break;
    default: break;
    }
}

static void nvdrv(Service *s, IpcReq *req, IpcResp *resp) {
    (void)s;
    switch (req->cmd) {
    case 0: {  // Open(path A) -> fd, error
        IpcBuf *a = in_buf(req, 0);
        char path[64] = {0};
        if (a && a->size) snprintf(path, sizeof path, "%.*s", (int)(a->size < 63 ? a->size : 63), G2HC(a->addr));
        int fd = g_nv_fd++;
        static int logged;
        if (logged++ < 30) LOG("[nvdrv] Open %s -> fd %d\n", path, fd);
        if (fd < 256) nv_dev[fd] = strstr(path, "nvmap") ? DEV_NVMAP : strstr(path, "ctrl-gpu") ? DEV_CTRL_GPU : strstr(path, "as-gpu") ? DEV_AS_GPU :
                                   strstr(path, "nvhost-ctrl") ? DEV_CTRL : strstr(path, "nvhost-gpu") ? DEV_GPU : DEV_UNKNOWN;
        OUT(uint32_t, 0) = (uint32_t)fd;
        OUT(uint32_t, 4) = 0;
        resp_size(resp, 8);
        break;
    }
    case 1: case 11: case 12: {  // Ioctl(fd, cmd, in A, out B)
        uint32_t fd = IN(uint32_t, 0), cmd = IN(uint32_t, 4);
        static int logged;
        IpcBuf *ib = in_buf(req, 0), *ob = out_buf(req, 0);
        if (logged++ < 200)
            LOG("[nvdrv] Ioctl fd %u (dev %d) cmd %08x (in %llu, out %llu Byte)\n", fd, fd < 256 ? nv_dev[fd] : -1, cmd,
                (unsigned long long)(ib ? ib->size : 0), (unsigned long long)(ob ? ob->size : 0));
        ipc_count("nvdrv.ioctl", cmd);
        nv_ioctl(fd < 256 ? nv_dev[fd] : DEV_UNKNOWN, cmd, ib && ib->size ? G2H8(ib->addr) : NULL, ib ? (uint32_t)ib->size : 0, ob && ob->size ? G2H8(ob->addr) : NULL,
                 ob ? (uint32_t)ob->size : 0);
        OUT(uint32_t, 0) = 0;
        resp_size(resp, 4);
        break;
    }
    case 2: case 3: case 5: case 8: case 9: case 10: case 13:  // Close, Initialize, MapSharedMem, SetClientPID, …: Erfolg
        OUT(uint32_t, 0) = 0;
        resp_size(resp, 4);
        break;
    case 4:  // QueryEvent(fd, event id) -> Handle, error
        resp->copy_handles[resp->ncopy++] = new_event_handle(NULL);
        OUT(uint32_t, 0) = 0;
        resp_size(resp, 4);
        break;
    case 6: OUT(uint32_t, 0) = 0; OUT(uint32_t, 4) = 0; resp_size(resp, 8); break;
    default: UNHANDLED("nvdrv");
    }
}

const ServiceDef g_service_defs_gfx[] = {
    {"vi:u", vi_root}, {"vi:s", vi_root}, {"vi:m", vi_root}, {"nvdrv", nvdrv}, {"nvdrv:a", nvdrv}, {"nvdrv:s", nvdrv}, {"nvdrv:t", nvdrv},
    {NULL, NULL},
};
