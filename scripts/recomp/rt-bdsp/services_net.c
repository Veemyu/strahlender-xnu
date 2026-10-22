// Online-, Peripherie- und Plattformdienste der BDSP-Laufzeit: Fehlerstubs. Nach dem Plan aus docs/architecture.md
// (Abschnitt Laufzeit): Netz/Online (nifm, bsd, ssl, friend, ldn, bcat, nim, …) und alles, was der Mac-Lauf nicht braucht, meldet
// einen Fehler, der Rest (prepo, ldr:ro) wird mit „Erfolg, keine Daten“ beantwortet. Eigener Code.
#include "bdsp.h"

void ipc_note(const char *svc, uint32_t cmd, int unhandled);

// Netz nicht verfügbar: jede Anfrage des Dienstes schlägt fehl (alle Befehle, alle Unterobjekte)
static void svc_error(Service *s, IpcReq *req, IpcResp *resp) {
    ipc_note(s->name, req->cmd, 0);
    resp->result = MAKE_RESULT(110, 1);  // wie nn::nifm „Netzwerk nicht verfügbar“ (Platzhalter; die SDK-Aufrufer prüfen nur auf Misserfolg)
}
static void svc_ok(Service *s, IpcReq *req, IpcResp *resp) {
    ipc_note(s->name, req->cmd, 0);
    resp_size(resp, 0x10);
}
// csrng: GetRandomBytes(B-Puffer)
static void csrng(Service *s, IpcReq *req, IpcResp *resp) {
    (void)s;
    if (req->cmd == 0) {
        IpcBuf *b = out_buf(req, 0);
        if (b) { uint8_t *p = G2H8(b->addr); for (uint64_t i = 0; i < b->size; i++) p[i] = (uint8_t)arc4random(); }
    } else resp_size(resp, 0x10);
}

// bsd:u (nn::socket): Anmeldung gelingt (sonst bricht nn::socket::Initialize ab), jeder Socket-Aufruf scheitert mit ENETDOWN
static void bsd_service(Service *s, IpcReq *req, IpcResp *resp) {
    ipc_note(s->name, req->cmd, 0);
    switch (req->cmd) {
    case 0: OUT(uint64_t, 0) = 0; resp_size(resp, 8); break;  // RegisterClient
    case 1: break;                                             // StartMonitoring
    default: OUT(int32_t, 0) = -1; OUT(int32_t, 4) = 100; resp_size(resp, 8);  // Rückgabe -1, errno ENETDOWN
    }
}

// bcat:u: Sitzung und Unterobjekte antworten „Erfolg ohne Daten“ (die Anmeldung beim Dienst darf nicht scheitern, sonst bricht nn::bcat::Initialize ab)
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
