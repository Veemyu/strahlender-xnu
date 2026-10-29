// Online, peripheral and platform services of the BDSP runtime: error stubs. As planned in docs/architecture.md
// (runtime section): network/online (nifm, bsd, ssl, friend, ldn, bcat, nim, …) and everything the Mac run does not need reports
// an error, the rest (prepo, ldr:ro) is answered with "success, no data". Own code.
#include "bdsp.h"
#ifdef _WIN32
#include <bcrypt.h>
#endif

void ipc_note(const char *svc, uint32_t cmd, int unhandled);

// Network unavailable: every request to the service fails (all commands, all sub-objects)
static void svc_error(Service *s, IpcReq *req, IpcResp *resp) {
    ipc_note(s->name, req->cmd, 0);
    resp->result = MAKE_RESULT(110, 1);  // like nn::nifm "network unavailable" (placeholder; the SDK callers only check for failure)
}
static void svc_ok(Service *s, IpcReq *req, IpcResp *resp) {
    ipc_note(s->name, req->cmd, 0);
    resp_size(resp, 0x10);
}
// csrng: GetRandomBytes(B buffer)
static void csrng(Service *s, IpcReq *req, IpcResp *resp) {
    (void)s;
    if (req->cmd == 0) {
        IpcBuf *b = out_buf(req, 0);
        if (b) {
#ifdef _WIN32
            if (b->size > ULONG_MAX || !bdsp_win32_prepare_write(G2H8(b->addr), (size_t)b->size) ||
                BCryptGenRandom(NULL, G2H8(b->addr), (ULONG)b->size, BCRYPT_USE_SYSTEM_PREFERRED_RNG) < 0) {
                LOG("[csrng] Windows system randomness failed\n");
                resp->result = MAKE_RESULT(1, 1);
            }
#else
            uint8_t *p = G2H8(b->addr);
            for (uint64_t i = 0; i < b->size; i++) p[i] = (uint8_t)arc4random();
#endif
        }
    } else resp_size(resp, 0x10);
}

// bsd:u (nn::socket): registration succeeds (otherwise nn::socket::Initialize aborts), every socket call fails with ENETDOWN
static void bsd_service(Service *s, IpcReq *req, IpcResp *resp) {
    ipc_note(s->name, req->cmd, 0);
    switch (req->cmd) {
    case 0: OUT(uint64_t, 0) = 0; resp_size(resp, 8); break;  // RegisterClient
    case 1: break;                                             // StartMonitoring
    default: OUT(int32_t, 0) = -1; OUT(int32_t, 4) = 100; resp_size(resp, 8);  // return -1, errno ENETDOWN
    }
}

// bcat:u: session and sub-objects answer "success without data" (registering with the service must not fail, otherwise nn::bcat::Initialize aborts)
static void bcat_obj(Service *s, IpcReq *req, IpcResp *resp) {
    ipc_note(s->name, req->cmd, 0);
    resp_size(resp, 0x10);
}
static void bcat_creator(Service *s, IpcReq *req, IpcResp *resp) {
    ipc_note(s->name, req->cmd, 0);
    ipc_return_object(resp, service_new("IBcatService", bcat_obj, NULL));
}

#define ERR(n) {n, svc_error}
const ServiceDef g_service_defs_net[] = {
    ERR("nifm:u"), {"bsd:u", bsd_service}, {"bsd:s", bsd_service}, ERR("bsdcfg"), ERR("ssl"), ERR("friend:u"), ERR("ldn:u"), {"bcat:u", bcat_creator}, ERR("nim:eca"), ERR("notif:a"),
    ERR("sfdnsres"), ERR("nsd:u"), ERR("ntc"), ERR("ngct:u"), ERR("htc"), ERR("htc:tenv"), ERR("htcs"), ERR("irs"), ERR("nfc:mf:u"),
    ERR("nfc:user"), ERR("nfp:user"), ERR("mii:u"), ERR("banana"), ERR("pcm"), ERR("mm:u"), ERR("caps:su"), ERR("caps:u"), ERR("pl:u"),
    ERR("audin:u"), ERR("audout:u"), ERR("hwopus"),
    {"prepo:u", svc_ok}, {"ldr:ro", svc_ok}, {"csrng", csrng},
    {NULL, NULL},
};
