#if defined(__linux__) && !defined(_GNU_SOURCE)
#define _GNU_SOURCE
#endif
#include "swkbd_keepalive.h"
#include "swkbd_ui.h"

#include <pthread.h>
#include <unistd.h>

#define TICK_NS 16666667ull           // the thread wakes at a fixed 60 Hz rhythm: sleeping a fixed 16 ms after each draw added the draw time (about 48 fps)
#define GAME_ACTIVE_NS 50000000ull    // the game presented this recently: it is running, nothing to repeat
#define IDLE_REDRAW_NS 100000000ull   // a frozen picture is drawn again this often (the caret blinks)

static pthread_mutex_t g_lock = PTHREAD_MUTEX_INITIALIZER;
static int g_running;
static const SwkbdKeepalive *g_k;

static void *run(void *arg) {
    (void)arg;
    const SwkbdKeepalive *k = g_k;
#if defined(__APPLE__)
    pthread_setname_np("swkbd-present");
#elif defined(__linux__)
    pthread_setname_np(pthread_self(), "swkbd-present");
#endif
    unsigned seen = swkbd_ui_revision() - 1;
    uint64_t last = 0, next = k->now_ns();
    for (;;) {
        uint64_t t = k->now_ns();
        if (t < next) usleep((useconds_t)((next - t) / 1000)); else next = t;   // behind schedule: no catching up with a burst
        next += TICK_NS;
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
