// Library applets (am: ILibraryAppletCreator / ILibraryAppletAccessor / IStorage). Own code.
// The game asks the system for a library applet (the software keyboard) through the SDK; this layer implements the system's side of that
// protocol (Switchbrew: Applet Manager services, Software Keyboard). What runs behind it is an AppletBackend.
#pragma once
#include <stdbool.h>
#include <stdint.h>

#include "bdsp.h"

// IStorage contents: a copy (CreateStorage, pushed data) or a window into guest memory (CreateTransferMemoryStorage; borrowed = not owned)
typedef struct { uint8_t *data; uint64_t size; bool borrowed; } AmStorage;
Service *am_storage_new(const void *data, uint64_t size);          // services.c
AmStorage *am_storage_get(Service *s);                             // NULL if s is not an IStorage

// ILibraryAppletCreator (services.c hands it out from IApplicationProxy)
void am_library_applet_creator(Service *s, IpcReq *req, IpcResp *resp);

// One library applet instance, as the guest sees it. The backend fills the output queues and calls applet_complete.
#define AM_MAX_Q 8
typedef struct LibApplet LibApplet;
typedef struct {
    const char *name;
    // The guest started the applet; storages pushed with PushInData are in in[0..nin).
    void (*start)(LibApplet *a);
    // The guest pushed interactive data (text check reply); in_inter[ninter - 1] is the new one.
    void (*interactive_in)(LibApplet *a);
} AppletBackend;

struct LibApplet {
    uint32_t applet_id, mode;
    Service *in[AM_MAX_Q], *in_inter[AM_MAX_Q], *out[AM_MAX_Q], *out_inter[AM_MAX_Q];
    int nin, ninter, nout, nout_inter;
    KEvent *ev_state, *ev_out, *ev_out_inter;
    uint32_t ev_state_r, ev_out_r, ev_out_inter_r;   // readable handles given to the guest
    bool started, completed;
    uint32_t result;
    const AppletBackend *backend;
    void *backend_state;
};

// Backend calls (any thread)
void applet_push_out(LibApplet *a, Service *storage);              // PopOutData queue + event
void applet_push_out_interactive(LibApplet *a, Service *storage);  // PopInteractiveOutData queue + event
void applet_complete(LibApplet *a, uint32_t result);               // state-changed event, IsCompleted = true, GetResult = result

// The backend for an applet id; NULL = not supported (CreateLibraryApplet fails)
const AppletBackend *applet_backend_for(uint32_t applet_id);

// Library applet ids; the software keyboard is 0x11 (seen in the game's CreateLibraryApplet call, BDSP_TRACE_APPLET=1)
#define AM_APPLET_SWKBD 0x11
