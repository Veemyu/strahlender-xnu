// HIPC/CMIF messages and sessions of the BDSP runtime.
// Own code following the design of LASRecomp runtime/ipc.c (MIT, Copyright (c) 2026 Peiikai, see NOTICE.md); changes:
// guest addresses through G2H (variant A/B), registry as tables instead of a linker section, a record of all (service, command)
// pairs with counters for the result log, an error stub for services without an implementation instead of "success without data".
#include "bdsp.h"

extern const ServiceDef g_service_defs_sm[];
extern const ServiceDef g_service_defs_audio[];
static const ServiceDef *const registries[] = {g_service_defs_sm, g_service_defs, g_service_defs_fs, g_service_defs_gfx, g_service_defs_audio, g_service_defs_net};

// ---- Record (service/object, command) -> count and whether handled
typedef struct { char svc[28]; uint32_t cmd; uint64_t n; int unhandled; } Seen;
static Seen seen[1024];
static int nseen;
static pthread_mutex_t seen_lock = PTHREAD_MUTEX_INITIALIZER;
static int trace_ipc = -1;
static uint64_t ipc_total;

static int seen_slot(const char *svc, uint32_t cmd) {  // seen_lock gehalten
    int i;
    for (i = 0; i < nseen; i++)
        if (seen[i].cmd == cmd && !strcmp(seen[i].svc, svc)) return i;
    if (nseen >= 1024) return -1;
    snprintf(seen[nseen].svc, sizeof seen[nseen].svc, "%s", svc);
    seen[nseen].cmd = cmd;
    return nseen++;
}

// every request to a service object counts once (ipc_handle_request)
void ipc_count(const char *svc, uint32_t cmd) {
    pthread_mutex_lock(&seen_lock);
    int i = seen_slot(svc, cmd);
    if (i >= 0) seen[i].n++;
    pthread_mutex_unlock(&seen_lock);
}

// The services use this to mark commands without an implementation (unhandled = 1); with 0 the call has no effect (old call sites)
void ipc_note(const char *svc, uint32_t cmd, int unhandled) {
    if (!unhandled) return;
    pthread_mutex_lock(&seen_lock);
    int i = seen_slot(svc, cmd);
    if (i >= 0) seen[i].unhandled = 1;
    pthread_mutex_unlock(&seen_lock);
    static int logged;
    if (logged++ < 400) LOG("[ipc] %s command %u not implemented (default response)\n", svc, cmd);
}

void ipc_stats(FILE *f) {
    pthread_mutex_lock(&seen_lock);
    fprintf(f, "IPC requests total %llu, distinct (service, command): %d\n", (unsigned long long)ipc_total, nseen);
    int unh = 0;
    for (int i = 0; i < nseen; i++) if (seen[i].unhandled) unh++;
    fprintf(f, "of those with default response (not implemented): %d\n", unh);
    for (int i = 0; i < nseen; i++)
        if (seen[i].unhandled) fprintf(f, "  missing: %s command %u (%llux)\n", seen[i].svc, seen[i].cmd, (unsigned long long)seen[i].n);
    fprintf(f, "Services/commands (count):");
    for (int i = 0; i < nseen; i++) fprintf(f, " %s:%u(%llu)", seen[i].svc, seen[i].cmd, (unsigned long long)seen[i].n);
    fprintf(f, "\n");
    pthread_mutex_unlock(&seen_lock);
}

static void stub_error_handler(Service *s, IpcReq *req, IpcResp *resp) {
    ipc_note(s->name, req->cmd, 1);
    resp->result = MAKE_RESULT(0x1FF, 1);  // error stub (not available)
}

Service *service_new(const char *name, ServiceHandler h, void *state) {
    Service *s = calloc(1, sizeof *s);
    s->name = strdup(name);
    s->handler = h;
    s->state = state;
    return s;
}

Service *service_lookup(const char *name) {
    for (unsigned r = 0; r < sizeof registries / sizeof *registries; r++)
        for (const ServiceDef *d = registries[r]; d->name; d++)
            if (!strcmp(d->name, name)) return service_new(name, d->handler, NULL);
    LOG("[ipc] no service '%s' (error stub)\n", name);
    return service_new(name, stub_error_handler, NULL);
}

void ipc_return_object(IpcResp *resp, Service *s) { resp->objects[resp->nobjects++] = s; }

static uint32_t session_new(Service *s) {
    KSession *k = calloc(1, sizeof *k);
    k->obj.type = KOBJ_SESSION;
    k->svc = s;
    s->refs++;
    return kernel_new_handle(&k->obj);
}

static void service_release(Service *s) {
    if (s && --s->refs == 0 && s->on_close) s->on_close(s);
}

uint32_t ipc_connect_named_port(const char *name) {
    if (!strcmp(name, "sm:")) return session_new(service_lookup("sm:"));
    LOG("[ipc] ConnectToNamedPort('%s') not supported\n", name);
    return 0;
}

// ------------------------------------------------------------------ sm:
// Services without an entry (e.g. not in the NPDM list) report like the real sm "not registered".
static void sm_handler(Service *s, IpcReq *req, IpcResp *resp) {
    (void)s;
    switch (req->cmd) {
    case 0: break;  // RegisterClient
    case 1: {       // GetServiceHandle(name)
        char name[9] = {0};
        memcpy(name, req->data, 8);
        if (trace_ipc) LOG("[sm] GetService %s\n", name);
        char tag[28];
        snprintf(tag, sizeof tag, "GetService>%s", name);
        ipc_count(tag, 1);
        Service *t = service_lookup(name);
        ipc_return_object(resp, t);
        break;
    }
    case 2: resp->result = MAKE_RESULT(21, 7); ipc_note("sm:", 2, 1); break;  // RegisterService
    default: ipc_note("sm:", req->cmd, 1);
    }
}

// ------------------------------------------------------------------ Nachrichtenkodierung
static uint64_t buf_addr(const uint32_t *w) {
    return w[1] | ((uint64_t)(w[2] >> 28) << 32) | ((uint64_t)((w[2] >> 2) & 7) << 36);
}

int ipc_handle_request(Cpu *c, uint32_t handle) {
    KObject *o = handle_get(handle);
    if (!o || o->type != KOBJ_SESSION) { LOG("[ipc] SendSyncRequest on invalid handle %x\n", handle); return R_INVALID_HANDLE; }
    if (trace_ipc < 0) trace_ipc = getenv("BDSP_TRACE_IPC") ? atoi(getenv("BDSP_TRACE_IPC")) : 0;
    __atomic_add_fetch(&ipc_total, 1, __ATOMIC_RELAXED);
    KSession *sess = (KSession *)o;
    uint32_t *msg = G2H32(c->tpidrro);
    IpcReq req = {0};
    IpcResp resp = {0};
    req.type = msg[0] & 0xFFFF;
    int nx = (msg[0] >> 16) & 0xF, na = (msg[0] >> 20) & 0xF, nb = (msg[0] >> 24) & 0xF;
    uint32_t raw_words = msg[1] & 0x3FF;
    uint32_t cflags = (msg[1] >> 10) & 0xF;
    uint32_t *p = msg + 2;
    if (msg[1] & 0x80000000u) {
        uint32_t hd = *p++;
        if (hd & 1) { req.pid = p[0] | ((uint64_t)p[1] << 32); p += 2; }
        req.ncopy = (hd >> 1) & 0xF;
        req.nmove = (hd >> 5) & 0xF;
        for (int i = 0; i < req.ncopy; i++) req.copy_handles[i] = *p++;
        for (int i = 0; i < req.nmove; i++) req.move_handles[i] = *p++;
    }
    for (int i = 0; i < nx; i++, p += 2) {
        req.x[i].addr = p[1] | ((uint64_t)((p[0] >> 12) & 0xF) << 32) | ((uint64_t)((p[0] >> 6) & 0x7) << 36);
        req.x[i].size = p[0] >> 16;
    }
    req.nx = nx;
    for (int i = 0; i < na; i++, p += 3) { req.a[i].size = p[0] | ((uint64_t)((p[2] >> 24) & 0xF) << 32); req.a[i].addr = buf_addr(p); }
    req.na = na;
    for (int i = 0; i < nb; i++, p += 3) { req.b[i].size = p[0] | ((uint64_t)((p[2] >> 24) & 0xF) << 32); req.b[i].addr = buf_addr(p); }
    req.nb = nb;
    uint32_t *raw = p;
    uint32_t *aligned = (uint32_t *)((uint8_t *)msg + ((((uint8_t *)raw - (uint8_t *)msg) + 15) & ~(uintptr_t)15));  // 16-byte alignment relative to the start of the message
    if (cflags >= 2) {
        uint32_t *cdesc = raw + raw_words;
        int ncd = cflags == 2 ? 1 : (int)cflags - 2;
        for (int i = 0; i < ncd && i < 8; i++) {
            req.c[i].addr = cdesc[2 * i] | ((uint64_t)(cdesc[2 * i + 1] & 0xFFFF) << 32);
            req.c[i].size = cdesc[2 * i + 1] >> 16;
        }
        req.nc = ncd;
    }

    if (req.type == 2) {  // close
        if (trace_ipc) LOG("[ipc] close %s (handle %x)\n", sess->svc->name, handle);
        if (!sess->domain) service_release(sess->svc);
        return 0;
    }
    uint8_t *payload = (uint8_t *)aligned;
    bool dom = false;
    if (req.type == 4 || req.type == 6) {
        if (sess->domain) {
            dom = true;
            uint8_t dcmd = payload[0], nin = payload[1];
            uint16_t dsize = *(uint16_t *)(payload + 2);
            req.domain_obj = *(uint32_t *)(payload + 4);
            if (dcmd == 2) {
                if (req.domain_obj < 256) {
                    Service *od = sess->domain->objs[req.domain_obj];
                    sess->domain->objs[req.domain_obj] = NULL;
                    service_release(od);
                }
                goto write_response;
            }
            req.ndomain_in = nin;
            for (int i = 0; i < nin && i < 8; i++) req.domain_in_objs[i] = *(uint32_t *)(payload + 16 + dsize + 4 * i);
            payload += 16;
        }
        if (memcmp(payload, "SFCI", 4)) LOG("[ipc] invalid SFCI magic at %s\n", sess->svc->name);
        req.cmd = *(uint32_t *)(payload + 8);
        req.data = payload + 16;
        req.data_size = raw_words * 4 > 32 ? raw_words * 4 - 32 : 0;
        Service *target = sess->svc;
        if (sess->domain) {
            target = req.domain_obj < 256 ? sess->domain->objs[req.domain_obj] : NULL;
            if (!target) { LOG("[ipc] domain object %u missing\n", req.domain_obj); return R_INVALID_HANDLE; }
        }
        if (trace_ipc > 1 || (trace_ipc && strcmp(target->name, "lm:ILogger")))
            LOG("[ipc] t%llu %s cmd %u (data %u, x%d a%d b%d c%d, handles %d/%d)\n", (unsigned long long)(kernel_current_thread() ? kernel_current_thread()->id : 0),
                target->name, req.cmd, req.data_size, req.nx, req.na, req.nb, req.nc, req.ncopy, req.nmove);
        ipc_count(target->name, req.cmd);
        target->handler(target, &req, &resp);
        if (trace_ipc && resp.result) LOG("[ipc]   -> %s cmd %u result 0x%x\n", target->name, req.cmd, resp.result);
    } else if (req.type == 5 || req.type == 7) {  // Steuerbefehle
        req.cmd = *(uint32_t *)(payload + 8);
        switch (req.cmd) {
        case 0:  // ConvertCurrentObjectToDomain
            sess->domain = calloc(1, sizeof(Domain));
            sess->domain->objs[1] = sess->svc;
            sess->svc->refs++;
            resp_size(&resp, 4);
            *(uint32_t *)resp.data = 1;
            break;
        case 2: case 4: {  // CloneCurrentObject(Ex)
            uint32_t h = session_new(sess->svc);
            ((KSession *)handle_get(h))->domain = sess->domain;
            resp.move_handles[resp.nmove++] = h;
            break;
        }
        case 3: *(uint16_t *)resp.data = 0x8000; resp_size(&resp, 4); break;  // QueryPointerBufferSize
        default: ipc_note("control", req.cmd, 1);
        }
    } else {
        LOG("[ipc] Nachrichtentyp %u\n", req.type);
    }

write_response:;
    uint32_t domain_out[8];
    int ndomain_out = 0;
    for (int i = 0; i < resp.nobjects; i++) {
        if (dom) {
            int id = 1;
            while (id < 256 && sess->domain->objs[id]) id++;
            sess->domain->objs[id] = resp.objects[i];
            resp.objects[i]->refs++;
            domain_out[ndomain_out++] = id;
        } else {
            resp.move_handles[resp.nmove++] = session_new(resp.objects[i]);
        }
    }
    memset(msg, 0, 0x100);
    uint32_t *w = msg;
    int has_handles = resp.ncopy || resp.nmove;
    uint32_t payload_words = 4 + (resp.data_size + 3) / 4;
    if (dom) payload_words += 4 + ndomain_out;
    uint32_t raw_size = payload_words + 4;
    w[0] = 0;
    w[1] = raw_size | (has_handles ? 0x80000000u : 0);
    uint32_t *q = w + 2;
    if (has_handles) {
        *q++ = (resp.ncopy << 1) | (resp.nmove << 5);
        for (int i = 0; i < resp.ncopy; i++) *q++ = resp.copy_handles[i];
        for (int i = 0; i < resp.nmove; i++) *q++ = resp.move_handles[i];
    }
    uint32_t *out = (uint32_t *)((uint8_t *)msg + ((((uint8_t *)q - (uint8_t *)msg) + 15) & ~(uintptr_t)15));
    if (dom) { out[0] = ndomain_out; out += 4; }
    memcpy(out, "SFCO", 4);
    out[1] = 0;
    out[2] = resp.result;
    out[3] = 0;
    memcpy(out + 4, resp.data, resp.data_size);
    if (dom)
        for (int i = 0; i < ndomain_out; i++) out[4 + (resp.data_size + 3) / 4 + i] = domain_out[i];
    return 0;
}

// sm: belongs to the IPC layer and is therefore in no service table of the service files
const ServiceDef g_service_defs_sm[] = {{"sm:", sm_handler}, {NULL, NULL}};
