// Common header of the BDSP runtime (gate 1 of the recompilation). Own code; the kernel/IPC structures follow the
// design of LASRecomp (runtime/kernel.h, ipc.h, MIT, see NOTICE.md).
#pragma once
#include <pthread.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "cpu.h"        // rt/cpu.h (exception extension) and on top of it scripts/recomp/upstream/runtime/cpu.h
#include "guestmem.h"
#include "plat.h"
#ifdef _WIN32
#include "win32_host.h"
#endif

#define LOG(...) fprintf(stderr, __VA_ARGS__)
#define MAKE_RESULT(module, desc) ((uint32_t)(((module) & 0x1FF) | ((desc) << 9)))

// ---- Result codes of the kernel (Horizon)
#undef R_OK  // collides with <unistd.h> (access mode); here it is the Horizon success code
#define R_OK 0
#define R_TIMEOUT 0xEA01
#define R_CANCELLED 0xEC01
#define R_INVALID_HANDLE 0xE401
#define R_INVALID_STATE 0xFA01
#define R_INVALID_ADDRESS 0xCC01
#define R_NOT_FOUND 0xF201
#define R_INVALID_ENUM 0xF001
#define R_OUT_OF_RESOURCE 0xD001
#define R_NOT_IMPLEMENTED 0xDC01

// ---- Guest address space, variant A (fixed window, guest address == host address). The modules sit where the generator
// expects them (gen_all.sh); everything else is freely chosen. Variant B (iPad) is in guestmem.h.
#if !defined(BDSP_REBASE32) && !defined(BDSP_COMPACT_BASE)
#define GUEST_LO     0x7000000000ull
#define GUEST_HI     0x7320000000ull   // 12,5 GiB
#define MAIN_BASE    0x7000000000ull
#define SDK_BASE     0x7006000000ull
#define SUBSDK0_BASE 0x7007000000ull
#define RTLD_BASE    0x7008000000ull
#define HLE_BASE     0x7080000000ull   // fake addresses for host functions (16 bytes per slot)
#define HLE_SIZE     0x0000100000ull
#define TLS_BASE     0x7090000000ull
#define TLS_SIZE     0x0000200000ull
#define HLE_HEAP     0x7092000000ull   // memory managed by the host and visible to the guest
#define HLE_HEAP_SIZE 0x000E000000ull
#define STACK_BASE   0x70A0000000ull
#define STACK_SIZE   0x0020000000ull   // 512 MiB guest stack region
#define HEAP_BASE    0x70C0000000ull
#define HEAP_MAX     0x00D0000000ull   // 3.25 GiB for SetHeapSize
#define ALIAS_BASE   0x7190000000ull   // alias region: target of MapPhysicalMemory/MapMemory
#define ALIAS_SIZE   0x0190000000ull   // 6,25 GiB
#define APP_MEMORY   0xCD500000ull
#define HEAP_REPORT  HEAP_MAX
// In nninitStartup BDSP asks for almost all application memory (3.14 GB) as one contiguous region, which the SDK
// takes from the alias region with MapPhysicalMemory: it must be at least that large (measured: abort in StandardAllocator::Initialize).
#else
// ---- Compact layout. Variant B (--rebase32, iPad): everything below 4 GiB, window at g_base. Variant A-low (BDSP_COMPACT_BASE, iOS): the same
// layout shifted to a fixed host address, guest address == host address (no G2H), NEON inline assembler (scripts/recomp/ios/gen_a.sh).
// gen32.sh generates C and images for variant B with these bases. The alias region takes the application-memory chunk (SDK: 3.14 GiB in one piece via MapPhysicalMemory), the heap region
// (SetHeapSize) stays small: BDSP does not call SetHeapSize (measured, docs/recomp-ios.md).
#ifdef BDSP_COMPACT_BASE
#define LAYOUT_ORG   (BDSP_COMPACT_BASE)
#else
#define LAYOUT_ORG   0x00000000ull
#endif
#define GUEST_LO     LAYOUT_ORG
#define GUEST_HI     (LAYOUT_ORG + 0x100000000ull)
#define MAIN_BASE    (LAYOUT_ORG + 0x01000000ull)
#define SDK_BASE     (LAYOUT_ORG + 0x07000000ull)
#define SUBSDK0_BASE (LAYOUT_ORG + 0x08000000ull)
#define RTLD_BASE    (LAYOUT_ORG + 0x09000000ull)
#define HLE_BASE     (LAYOUT_ORG + 0x0A000000ull)
#define HLE_SIZE     0x00100000ull
#define TLS_BASE     (LAYOUT_ORG + 0x0A100000ull)
#define TLS_SIZE     0x00100000ull
#define HLE_HEAP     (LAYOUT_ORG + 0x0A200000ull)
#define HLE_HEAP_SIZE 0x06000000ull
#define STACK_BASE   (LAYOUT_ORG + 0x10400000ull)
#define STACK_SIZE   0x0FC00000ull   // 252 MiB: the SDK places the thread stacks into this region with MapMemory (32 MiB were enough for 19 threads)
#define ALIAS_BASE   (LAYOUT_ORG + 0x20000000ull)   // the SDK places its block on the next 2 GiB boundary of the alias region (here 0x8000_0000, A: 0x72_0000_0000);
#define ALIAS_SIZE   0xE0000000ull   // the region must be large enough for the randomly placed rest (measured: from 0x4000_0000 on a 32 MiB allocation fails)
#define HEAP_BASE    (LAYOUT_ORG + 0x10300000ull)
#define HEAP_MAX     0x00100000ull   // SetHeapSize is not used (measured); the region sits in a gap only for completeness
#define APP_MEMORY   0x83000000ull   // application memory reported to the SDK (GetInfo 6/21; it deducts 64 MiB of system resources): 1.98 GiB from 0x8000_0000
#define HEAP_REPORT  0xD0000000ull   // reported size of the heap region (GetInfo 5); the SDK checks the application memory against it, SetHeapSize does not use it
#endif
#if defined(BDSP_REBASE32)
#define ADDR_SPACE_END (1ull << 32)
#elif defined(BDSP_COMPACT_BASE)
#define ADDR_SPACE_END GUEST_HI
#else
#define ADDR_SPACE_END (1ull << 39)
#endif
typedef enum { KOBJ_THREAD = 1, KOBJ_EVENT, KOBJ_SESSION, KOBJ_SHMEM, KOBJ_TMEM } KType;
typedef enum { WAIT_NONE = 0, WAIT_MUTEX, WAIT_CONDVAR, WAIT_ARBITER } WaitKind;

typedef struct KObject { KType type; int refs; bool signaled; } KObject;
typedef KObject KEvent;

typedef struct KThread KThread;
struct KThread {
    KObject obj;  // signaled when the thread ends
    Cpu cpu;
    pthread_t host;
    uint64_t entry, tlr, id, stack_lo, stack_hi;
    uint32_t handle;
    int prio, core;
    bool cancel, in_sync_wait, started, finished, suspended;
    WaitKind wait_kind;
    uint64_t wait_addr, wait_mutex;
    uint32_t wait_tag, wait_result;
    KThread *wnext, *snext, *anext;
    pthread_cond_t cond;
    jmp_buf unwind;        // thread_main: Ziel von ExitThread
    uint64_t svc_last, svc_calls, ipc_calls;
    uint64_t wait_since, svc_last_ns;   // start of the current wait (ns), time of the last SVC
    uint32_t wait_h0; int wait_n;       // WaitSynchronization: first handle and count
    uint64_t host_stack_size;
    void *host_stack_lo;
#ifdef _WIN32
    CONTEXT host_context;
#endif
};

typedef struct KSharedMem {
    KObject obj;
    uint64_t size, guest_addr;
    void (*on_map)(struct KSharedMem *s);
} KSharedMem;
typedef struct { KObject obj; uint64_t addr, size; } KTransferMem;

extern pthread_mutex_t g_klock;
KObject *handle_get(uint32_t h);
uint32_t kernel_new_handle(KObject *o);
void kernel_signal(KObject *o);   // caller holds g_klock
KEvent *kernel_create_event_pair(uint32_t *writable, uint32_t *readable);
KSharedMem *kernel_create_shared_memory(uint64_t size, void (*on_map)(KSharedMem *), uint32_t *handle);
void hid_idle_tick(void);   // services.c: empty touch sample per vsync in the HID shared memory
void hid_shmem_unmapped(uint64_t addr);   // services.c: the guest unmaps the shared memory (UnmapSharedMemory): no more samples written there
KThread *kernel_current_thread(void);
Cpu *kernel_current_cpu(void);
void kernel_init(void);
KThread *kernel_create_main_thread(uint64_t entry, uint64_t stack_size, int prio, uint64_t host_stack);
void kernel_run_main(KThread *t, uint64_t x0, uint64_t x1, uint64_t x2, uint64_t x3);
void kernel_region_add(uint64_t addr, uint64_t size, uint32_t type, uint32_t perm);
uint64_t kernel_heap_size(void);
void kernel_phys_range(uint64_t *lo, uint64_t *hi);   // bounding range of the MapPhysicalMemory regions (0/0 = none)
extern uint64_t g_phys_unmaps;
void kernel_report(FILE *f);   // thread/SVC counters, heap, handles
int kernel_thread_count(void);
extern uint64_t g_program_id, g_system_resource_size;
extern volatile int g_stop;     // set when the run is to be ended (watchdog, gate reached)
uint64_t rt_now_ns(void);

// ---- IPC (HIPC/CMIF), guest pointers are guest addresses (G2H on access)
typedef struct { uint64_t addr, size; } IpcBuf;
typedef struct Service Service;
typedef struct IpcReq {
    uint32_t type, cmd;
    const uint8_t *data;
    uint32_t data_size;
    uint64_t pid;
    uint32_t copy_handles[8], move_handles[8];
    int ncopy, nmove;
    IpcBuf x[8], a[8], b[8], c[8];
    int nx, na, nb, nc;
    uint32_t domain_obj;
    uint32_t domain_in_objs[8];
    Service *domain_in_svc[8];   // the objects behind domain_in_objs (NULL = unknown id); interface objects passed in a domain arrive here
    int ndomain_in;
} IpcReq;
typedef struct IpcResp {
    uint32_t result;
    uint8_t data[0x200];
    uint32_t data_size;
    uint32_t copy_handles[8], move_handles[8];
    int ncopy, nmove;
    Service *objects[8];
    int nobjects;
} IpcResp;
typedef void (*ServiceHandler)(Service *s, IpcReq *req, IpcResp *resp);
struct Service {
    const char *name;
    ServiceHandler handler;
    void *state;
    int refs;
    void (*on_close)(Service *s);
};
typedef struct { Service *objs[256]; } Domain;
typedef struct { KObject obj; Service *svc; Domain *domain; } KSession;

#undef IN  // Windows argument annotations share the IPC accessor names.
#undef OUT
#define IN(type, off) (*(const type *)(req->data + (off)))
#define OUT(type, off) (*(type *)(resp->data + (off)))
static inline void resp_size(IpcResp *resp, uint32_t n) { if (n > resp->data_size) resp->data_size = n; }
static inline IpcBuf *out_buf(IpcReq *req, int i) {
    if (i < req->nb && req->b[i].size) return &req->b[i];
    if (i < req->nc && req->c[i].size) return &req->c[i];
    return i < req->nb ? &req->b[i] : i < req->nc ? &req->c[i] : NULL;
}
static inline IpcBuf *in_buf(IpcReq *req, int i) {
    if (i < req->na && req->a[i].size) return &req->a[i];
    if (i < req->nx && req->x[i].size) return &req->x[i];
    return i < req->na ? &req->a[i] : i < req->nx ? &req->x[i] : NULL;
}
Service *service_new(const char *name, ServiceHandler h, void *state);
Service *service_lookup(const char *name);
void ipc_return_object(IpcResp *resp, Service *s);
int ipc_handle_request(Cpu *c, uint32_t handle);
uint32_t ipc_connect_named_port(const char *name);
void ipc_stats(FILE *f);

typedef struct { const char *name; ServiceHandler handler; } ServiceDef;
extern const ServiceDef g_service_defs[];   // services*.c, terminated with {NULL, NULL}
extern const ServiceDef g_service_defs_net[];
extern const ServiceDef g_service_defs_fs[];
extern const ServiceDef g_service_defs_gfx[];

// ---- Dispatch / Module / HLE
#ifndef BDSP_HAS_SUBSDK1
#define BDSP_HAS_SUBSDK1 0
#endif
#define SUBSDK1_BASE (MAIN_BASE + 0x5708000ull)
typedef void (*HostFn)(Cpu *c);
typedef struct Module {
    char name[16];
    uint64_t base, size, text_lo, text_hi, ro_lo, ro_hi, data_lo, data_hi, init, init_array, init_array_sz;
} Module;
extern Module g_modules[4];
extern int g_nmodules;
void loader_load(const char *imgdir);
uint64_t loader_find_symbol(const char *name);
const char *loader_symbol_at(uint64_t addr, uint64_t *offset);  // rough: from the exported symbols
uint64_t hle_register(const char *name, HostFn fn);
void dispatch_init(void);
void guest_call(Cpu *c, uint64_t addr);
GuestFn dispatch_lookup(uint64_t addr);
void rt_fatal(const char *fmt, ...) __attribute__((noreturn, format(printf, 1, 2)));
void rt_fatal_trace(void);
void crash_handler_install(void);
void hle_alloc_reset(void);
void *hle_alloc(uint64_t size);   // Gastspeicher des Hosts, nie freigegeben; liefert Hostzeiger

// Observation of the guest (fnprof_hit): ring of the last function entries, watch addresses
void watch_add(uint64_t addr, const char *name);
void gate_report(FILE *f);
extern volatile uint64_t g_watch_hits;

// Services
int hle_current_slot(void);
const char *hle_slot_name(int i);
int hle_unimpl_report(FILE *f);
void hle_stats_report(FILE *f);
void fnprof_report(FILE *f, unsigned n);
#ifndef BDSP_NVN_NONE   // NVN backend (Metal, later Vulkan): nvn/nvn_glue.c + nvn/metal.m; without a backend (BDSP_NVN_NONE, e.g. Linux without Vulkan) the SDK's NVN driver stays
void nvn_report(FILE *f);       // nvn_glue.c: counters of the NVN layer
void nvn_glue_init(void);       // nvn_glue.c: binds the host functions of the NVN layer to the HLE slots
int ui_run(void);               // nvn/metal.m: window loop of the main thread (does not return)
uint64_t renderer_present_count(void);   // nvn/metal.m: frames presented so far
#else
#define nvn_report(f) ((void)0)
#define nvn_glue_init() ((void)0)
#define ui_run() 0
#define renderer_present_count() 0
#endif
// Per-second performance log (BDSP_PERF_LOG=1, main.c): frames, GC stop-the-world calls (kernel.c), entries of the guest functions
// listed in BDSP_COUNT_FN=<hex>[,<hex>...] (dispatch.c, at most 4; this turns on the function-entry hook, which slows the guest down)
extern uint64_t g_suspends, g_resumes;
extern uint64_t g_count_addr[4], g_count_hits[4];
extern int g_count_n;
void bdsp_fatal_report(const char *why, int code);   // main.c: report from a normal context (main thread) and process exit; does not return from the main thread
void bdsp_gate_hit(const char *what);   // main.c: with BDSP_STOP_AT_GATE=1 (default) report and exit
void guest_log(const char *line);
void ipc_note(const char *svc, uint32_t cmd, int unhandled);
void ipc_count(const char *svc, uint32_t cmd);
const char *settings_language(void);
extern const char *g_romfs_dir;
extern const char *g_save_dir;
void user_id_load(const char *save_dir);
void fs_set_dirs(const char *romfs_dir, const char *save_dir);
bool fs_system_data_exists(uint64_t data_id);   // services_fs.c: a firmware data archive extracted into BDSP_FIRMWARE_DATA (e.g. 0x0100000000000823, NG words)
void fs_report(FILE *f);
