#include "swkbd_keepalive.h"
#include "swkbd_ui.h"

#include <pthread.h>
#include <unistd.h>

#define POLL_US 16000
#define GAME_ACTIVE_NS 50000000ull    // the game presented this recently: it is running, nothing to repeat
#define IDLE_REDRAW_NS 100000000ull   // a frozen picture is drawn again this often (the caret blinks)

static pthread_mutex_t g_lock = PTHREAD_MUTEX_INITIALIZER;
static int g_running;
static const SwkbdKeepalive *g_k;

static void *run(void *arg) {
    (void)arg;
    const SwkbdKeepalive *k = g_k;
    pthread_setname_np("swkbd-present");
    unsigned seen = swkbd_ui_revision() - 1;
    uint64_t last = 0;
    for (;;) {
        usleep(POLL_US);
        pthread_mutex_lock(&g_lock);
        if (!swkbd_ui_visible()) { g_running = 0; pthread_mutex_unlock(&g_lock); return NULL; }
        pthread_mutex_unlock(&g_lock);
        uint64_t now = k->now_ns();
        if (now - k->game_present_ns() < GAME_ACTIVE_NS) continue;
        unsigned rev = swkbd_ui_revision();
        if (rev == seen && !swkbd_ui_animating() && now - last < IDLE_REDRAW_NS) continue;
        seen = rev; last = now;
        k->represent();
    }
}

void swkbd_keepalive_wake(const SwkbdKeepalive *k) {
    pthread_mutex_lock(&g_lock);
    if (!g_running) {
        g_k = k;
        pthread_t th;
        if (!pthread_create(&th, NULL, run, NULL)) { pthread_detach(th); g_running = 1; }
    }
    pthread_mutex_unlock(&g_lock);
}
