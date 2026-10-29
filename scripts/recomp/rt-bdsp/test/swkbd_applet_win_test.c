// Real UI/backend callbacks and output queues; synthetic storage/kernel transport.
#include "applet.h"
#include "swkbd_ui.h"
#include <assert.h>
#include <string.h>

pthread_mutex_t g_klock = PTHREAD_MUTEX_INITIALIZER;
KObject *handle_get(uint32_t handle) { (void)handle; abort(); }
uint32_t kernel_new_handle(KObject *object) { (void)object; abort(); }
KEvent *kernel_create_event_pair(uint32_t *write, uint32_t *read) { (void)write; (void)read; abort(); }
Service *service_new(const char *name, ServiceHandler handler, void *state) {
    (void)name; (void)handler; (void)state; abort();
}
void ipc_return_object(IpcResp *response, Service *service) { (void)response; (void)service; abort(); }
void ipc_note(const char *service, uint32_t command, int unhandled) {
    (void)service; (void)command; (void)unhandled; abort();
}
void kernel_signal(KObject *event) { assert(event); event->signaled = true; }
bool fs_system_data_exists(uint64_t id) { assert(id == 0x0100000000000823ull); return true; }
Service *am_storage_new(const void *data, uint64_t size) {
    Service *service = calloc(1, sizeof *service);
    AmStorage *storage = calloc(1, sizeof *storage);
    assert(service && storage);
    storage->data = calloc(1, size ? size : 1);
    assert(storage->data);
    if (data) memcpy(storage->data, data, size);
    storage->size = size;
    service->state = storage;
    return service;
}
AmStorage *am_storage_get(Service *service) { return service ? service->state : NULL; }

static void release_storage(Service *service) {
    AmStorage *storage = am_storage_get(service);
    free(storage->data);
    free(storage);
    free(service);
}
static void start(LibApplet *applet, KEvent events[3], int utf8, int check) {
    memset(applet, 0, sizeof *applet);
    memset(events, 0, 3 * sizeof *events);
    applet->ev_state = &events[0];
    applet->ev_out = &events[1];
    applet->ev_out_inter = &events[2];
    uint8_t config[0x4c8] = {0};
    int32_t limit = 16, minimum = 1;
    memcpy(config + 0x3ac, &limit, 4);
    memcpy(config + 0x3b0, &minimum, 4);
    config[0x3bd] = (uint8_t)utf8;
    config[0x3d0] = (uint8_t)check;
    applet->in[0] = am_storage_new(NULL, 0);
    applet->in[1] = am_storage_new(config, sizeof config);
    applet->nin = 2;
    applet->backend = applet_backend_for(AM_APPLET_SWKBD);
    assert(applet->backend && !applet_backend_for(0xffff));
    applet->backend->start(applet);
    assert(swkbd_ui_active() && !applet->completed && !applet->nout);
}
static void cleanup(LibApplet *applet) {
    // Finish the existing close animation before releasing the callback owner.
    for (int i = 0; i < 30; i++) {
        float scale, offset[2];
        if (swkbd_ui_scene(0.016f, 1280, 720, &scale, offset)) swkbd_ui_unlock();
    }
    for (int i = 0; i < applet->nin; i++) release_storage(applet->in[i]);
    for (int i = 0; i < applet->nout; i++) release_storage(applet->out[i]);
    for (int i = 0; i < applet->ninter; i++) release_storage(applet->in_inter[i]);
    for (int i = 0; i < applet->nout_inter; i++) release_storage(applet->out_inter[i]);
    free(applet->backend_state);
}
static void output(LibApplet *applet, uint32_t result) {
    assert(applet->completed && applet->result == 0 && applet->nout == 1);
    assert(applet->ev_state->signaled && applet->ev_out->signaled);
    AmStorage *storage = am_storage_get(applet->out[0]);
    assert(storage->size == 0x7d8 && *(uint32_t *)storage->data == result);
    assert(!swkbd_ui_active());
}

int main(void) {
    swkbd_ui_set_display(1); // No renderer: only existing UI/backend protocol is under test.
    LibApplet applet;
    KEvent events[3];
    const char *text = "Test\xc3\xa4";
    for (int utf8 = 0; utf8 < 2; utf8++) {
        start(&applet, events, utf8, 0);
        swkbd_ui_key(SWKBD_KEY_ENTER);
        assert(!applet.completed); // Minimum length rejects an empty submission.
        swkbd_ui_text(text);
        assert(!strcmp(swkbd_ui_text_value(), text));
        swkbd_ui_key(SWKBD_KEY_ENTER);
        output(&applet, 0);
        AmStorage *storage = am_storage_get(applet.out[0]);
        if (utf8) assert(!strcmp((char *)storage->data + 4, text));
        else {
            const uint16_t expected[] = {'T', 'e', 's', 't', 0xe4, 0};
            assert(!memcmp(storage->data + 4, expected, sizeof expected));
        }
        cleanup(&applet);
    }
    start(&applet, events, 1, 0);
    swkbd_ui_text("Discard");
    swkbd_ui_key(SWKBD_KEY_ESCAPE);
    output(&applet, 1);
    assert(am_storage_get(applet.out[0])->data[4] == 0);
    cleanup(&applet);

    start(&applet, events, 1, 1);
    swkbd_ui_text(text);
    swkbd_ui_key(SWKBD_KEY_ENTER);
    assert(!applet.completed && !applet.nout && applet.nout_inter == 1);
    AmStorage *interactive = am_storage_get(applet.out_inter[0]);
    assert(*(uint64_t *)interactive->data == 8 + strlen(text) + 1);
    assert(!strcmp((char *)interactive->data + 8, text) && events[2].signaled);
    uint32_t rejected = 1;
    applet.in_inter[applet.ninter++] = am_storage_new(&rejected, sizeof rejected);
    applet.backend->interactive_in(&applet);
    assert(!applet.completed && swkbd_ui_active());
    swkbd_ui_key(SWKBD_KEY_ENTER);
    assert(applet.nout_inter == 2 && !applet.completed);
    uint32_t accepted = 0;
    applet.in_inter[applet.ninter++] = am_storage_new(&accepted, sizeof accepted);
    applet.backend->interactive_in(&applet);
    output(&applet, 0);
    assert(!strcmp((char *)am_storage_get(applet.out[0])->data + 4, text));
    cleanup(&applet);
    puts("Real swkbd UI/backend: UTF-8/UTF-16 submit, cancel and interactive verdict passed.");
    return 0;
}
