#if defined(__linux__) && !defined(_GNU_SOURCE)
#define _GNU_SOURCE
#endif
#include "swkbd_keepalive.h"
#include "swkbd_ui.h"

#include <pthread.h>
#include <unistd.h>
#include <errno.h>
#include <stdio.h>

#define TICK_NS 16666667ull           // the thread wakes at a fixed 60 Hz rhythm: sleeping a fixed 16 ms after each draw added the draw time (about 48 fps)
#define GAME_ACTIVE_NS 50000000ull    // the game presented this recently: it is running, nothing to repeat
#define IDLE_REDRAW_NS 100000000ull   // a frozen picture is drawn again this often (the caret blinks)

static pthread_mutex_t g_lock = PTHREAD_MUTEX_INITIALIZER;
static int g_running;
static int g_stopping, g_joinable;
static pthread_t g_thread;
static pthread_cond_t g_changed = PTHREAD_COND_INITIALIZER;
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
        while (!g_stopping && !swkbd_ui_visible())
            pthread_cond_wait(&g_changed, &g_lock);
        if (g_stopping) {
            g_running = 0;
            pthread_cond_broadcast(&g_changed);
            pthread_mutex_unlock(&g_lock);
            return NULL;
        }
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
    if (!g_stopping && !g_running) {
        g_k = k;
        int status = pthread_create(&g_thread, NULL, run, NULL);
        if (!status) { g_joinable = 1; g_running = 1; }
        else fprintf(stderr, "[swkbd] keepalive creation failed: %d\n", status);
    }
    pthread_cond_broadcast(&g_changed);
    pthread_mutex_unlock(&g_lock);
}

int swkbd_keepalive_stop(const struct timespec *deadline) {
    pthread_mutex_lock(&g_lock);
    g_stopping = 1;
    pthread_cond_broadcast(&g_changed);
    while (g_running) {
        int status = pthread_cond_timedwait(&g_changed, &g_lock, deadline);
        if (status) {
            pthread_mutex_unlock(&g_lock);
            fprintf(stderr, "[swkbd] keepalive stop failed: %d%s\n",
                    status, status == ETIMEDOUT ? " (timeout)" : "");
            return 0;
        }
    }
    int joinable = g_joinable;
    pthread_t thread = g_thread;
    pthread_mutex_unlock(&g_lock);
    if (joinable) {
        int status = pthread_join(thread, NULL);
        if (status) {
            fprintf(stderr, "[swkbd] keepalive join failed: %d\n", status);
            return 0;
        }
        pthread_mutex_lock(&g_lock);
        g_joinable = 0;
        pthread_mutex_unlock(&g_lock);
    }
    return 1;
}
