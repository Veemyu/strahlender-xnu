// Gemeinsamer Kopf der BDSP-Laufzeit (Gate 1 der Rekompilation). Eigener Code; die Kernel-/IPC-Strukturen folgen dem
// Entwurf von LASRecomp (runtime/kernel.h, ipc.h, MIT, siehe NOTICE.md).
#pragma once
#include <pthread.h>
#include <setjmp.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "cpu.h"        // rt/cpu.h (Exception-Erweiterung) und darüber research/LASRecomp/runtime/cpu.h
#include "guestmem.h"

#define LOG(...) fprintf(stderr, __VA_ARGS__)
#define MAKE_RESULT(module, desc) ((uint32_t)(((module) & 0x1FF) | ((desc) << 9)))

// ---- Ergebniscodes des Kernels (Horizon)
#undef R_OK  // kollidiert mit <unistd.h> (access-Modus); hier der Horizon-Erfolgscode
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

// ---- Gastadressraum, Variante A (festes Fenster, Gastadresse == Hostadresse). Die Module liegen dort, wo der Generator
// sie erwartet (gen_all.sh); alles andere frei gewählt. Variante B (iPad) liegt in guestmem.h.
#ifndef BDSP_REBASE32
#define GUEST_LO     0x7000000000ull
#define GUEST_HI     0x7320000000ull   // 12,5 GiB
#define MAIN_BASE    0x7000000000ull
#define SDK_BASE     0x7006000000ull
#define SUBSDK0_BASE 0x7007000000ull
#define RTLD_BASE    0x7008000000ull
#define HLE_BASE     0x7080000000ull   // Scheinadressen für Host-Funktionen (16 Byte je Slot)
#define HLE_SIZE     0x0000100000ull
#define TLS_BASE     0x7090000000ull
#define TLS_SIZE     0x0000200000ull
#define HLE_HEAP     0x7092000000ull   // vom Host verwalteter, für den Gast sichtbarer Speicher
#define HLE_HEAP_SIZE 0x000E000000ull
#define STACK_BASE   0x70A0000000ull
#define STACK_SIZE   0x0020000000ull   // 512 MiB Gast-Stackregion
#define HEAP_BASE    0x70C0000000ull
#define HEAP_MAX     0x00D0000000ull   // 3,25 GiB für SetHeapSize
#define ALIAS_BASE   0x7190000000ull   // Alias-Region: Ziel von MapPhysicalMemory/MapMemory
#define ALIAS_SIZE   0x0190000000ull   // 6,25 GiB
// BDSP verlangt in nninitStartup fast den ganzen Anwendungsspeicher (3,14 GB) als einen zusammenhängenden Bereich, den das SDK
// per MapPhysicalMemory aus der Alias-Region nimmt: sie muss mindestens so groß sein (Messung: Abbruch in StandardAllocator::Initialize).
#else
// ---- Variante B (iPad, Gate 2, hier nur als Layout festgehalten und noch ungetestet): alles unter 4 GiB, Fenster bei g_guest_base
#define GUEST_LO     0x00000000ull
#define GUEST_HI     0x100000000ull
#define MAIN_BASE    0x01000000ull
#define SDK_BASE     0x07000000ull
#define SUBSDK0_BASE 0x08000000ull
#define RTLD_BASE    0x09000000ull
#define HLE_BASE     0x0A000000ull
#define HLE_SIZE     0x00100000ull
#define TLS_BASE     0x0A100000ull
#define TLS_SIZE     0x00100000ull
#define HLE_HEAP     0x0A200000ull
#define HLE_HEAP_SIZE 0x06000000ull
#define STACK_BASE   0x10000000ull
#define STACK_SIZE   0x10000000ull
#define ALIAS_BASE   0x20000000ull
#define ALIAS_SIZE   0x10000000ull
#define HEAP_BASE    0x30000000ull
#define HEAP_MAX     0xD0000000ull
#endif
typedef enum { KOBJ_THREAD = 1, KOBJ_EVENT, KOBJ_SESSION, KOBJ_SHMEM, KOBJ_TMEM } KType;
typedef enum { WAIT_NONE = 0, WAIT_MUTEX, WAIT_CONDVAR, WAIT_ARBITER } WaitKind;

typedef struct KObject { KType type; int refs; bool signaled; } KObject;
typedef KObject KEvent;

typedef struct KThread KThread;
struct KThread {
    KObject obj;  // signalisiert beim Ende des Threads
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
    uint64_t host_stack_size;
    void *host_stack_lo;
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
void kernel_signal(KObject *o);   // Aufrufer hält g_klock
KEvent *kernel_create_event_pair(uint32_t *writable, uint32_t *readable);
KSharedMem *kernel_create_shared_memory(uint64_t size, void (*on_map)(KSharedMem *), uint32_t *handle);
KThread *kernel_current_thread(void);
Cpu *kernel_current_cpu(void);
void kernel_init(void);
KThread *kernel_create_main_thread(uint64_t entry, uint64_t stack_size, int prio, uint64_t host_stack);
void kernel_run_main(KThread *t, uint64_t x0, uint64_t x1, uint64_t x2, uint64_t x3);
void kernel_region_add(uint64_t addr, uint64_t size, uint32_t type, uint32_t perm);
uint64_t kernel_heap_size(void);
void kernel_phys_range(uint64_t *lo, uint64_t *hi);   // Hülle der MapPhysicalMemory-Bereiche (0/0 = keine)
void kernel_report(FILE *f);   // Thread-/SVC-Zähler, Heap, Handles
int kernel_thread_count(void);
extern uint64_t g_program_id, g_system_resource_size;
extern volatile int g_stop;     // gesetzt, wenn der Lauf beendet werden soll (Watchdog, Gate erreicht)
uint64_t rt_now_ns(void);

// ---- IPC (HIPC/CMIF), Gast-Zeiger sind Gastadressen (G2H beim Zugriff)
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
extern const ServiceDef g_service_defs[];   // services*.c, mit {NULL, NULL} abgeschlossen
extern const ServiceDef g_service_defs_net[];
extern const ServiceDef g_service_defs_fs[];
extern const ServiceDef g_service_defs_gfx[];

// ---- Dispatch / Module / HLE
typedef void (*HostFn)(Cpu *c);
typedef struct Module {
    char name[16];
    uint64_t base, size, text_lo, text_hi, ro_lo, ro_hi, data_lo, data_hi, init, init_array, init_array_sz;
} Module;
extern Module g_modules[4];
extern int g_nmodules;
void loader_load(const char *imgdir);
uint64_t loader_find_symbol(const char *name);
const char *loader_symbol_at(uint64_t addr, uint64_t *offset);  // grob: aus den exportierten Symbolen
uint64_t hle_register(const char *name, HostFn fn);
void dispatch_init(void);
void guest_call(Cpu *c, uint64_t addr);
GuestFn dispatch_lookup(uint64_t addr);
void rt_fatal(const char *fmt, ...) __attribute__((noreturn, format(printf, 1, 2)));
void rt_fatal_trace(void);
void crash_handler_install(void);
void hle_alloc_reset(void);
void *hle_alloc(uint64_t size);   // Gastspeicher des Hosts, nie freigegeben; liefert Hostzeiger

// Beobachtung des Gastes (fnprof_hit): Ring der letzten Funktionseintritte, Beobachtungsadressen
void watch_add(uint64_t addr, const char *name);
void gate_report(FILE *f);
extern volatile uint64_t g_watch_hits;

// Dienste
int hle_current_slot(void);
const char *hle_slot_name(int i);
int hle_unimpl_report(FILE *f);
void hle_stats_report(FILE *f);
void fnprof_report(FILE *f, unsigned n);
#ifndef BDSP_NVN_NONE   // NVN-Backend (Metal, später Vulkan): nvn/nvn_glue.c + nvn/metal.m; ohne Backend (BDSP_NVN_NONE, z. B. Linux ohne Vulkan) bleibt der NVN-Treiber des SDK
void nvn_report(FILE *f);       // nvn_glue.c: Zähler der NVN-Schicht
void nvn_glue_init(void);       // nvn_glue.c: bindet die Host-Funktionen der NVN-Schicht an die HLE-Slots
int ui_run(void);               // nvn/metal.m: Fensterschleife des Hauptthreads (kehrt nicht zurück)
#else
#define nvn_report(f) ((void)0)
#define nvn_glue_init() ((void)0)
#define ui_run() 0
#endif
void bdsp_fatal_report(const char *why, int code);   // main.c: Bericht aus normalem Kontext (Hauptthread) und Prozessende; kehrt aus dem Hauptthread nicht zurück
void bdsp_gate_hit(const char *what);   // main.c: bei BDSP_STOP_AT_GATE=1 (Standard) Bericht und Ende
void guest_log(const char *line);
void ipc_note(const char *svc, uint32_t cmd, int unhandled);
void ipc_count(const char *svc, uint32_t cmd);
const char *settings_language(void);
extern const char *g_romfs_dir;
extern const char *g_save_dir;
void fs_set_dirs(const char *romfs_dir, const char *save_dir);
void fs_report(FILE *f);
