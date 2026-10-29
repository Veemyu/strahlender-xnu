// The thread that keeps the keyboard's picture alive while the game is stopped inside the keyboard call and presents nothing: it asks the
// renderer to present the last game image again (with the keyboard drawn over it) whenever the game has not presented for a moment and
// something was entered or moves (otherwise only for the blinking caret). It presents only while the keyboard is visible. Shared by the Metal and
// the Vulkan overlay; each supplies its clock and its "present again" call.
#ifndef SWKBD_KEEPALIVE_H
#define SWKBD_KEEPALIVE_H

#include <stdint.h>
#include <time.h>

typedef struct {
    uint64_t (*now_ns)(void);
    uint64_t (*game_present_ns)(void);   // time of the game's last own presentation (same clock as now_ns)
    void (*represent)(void);             // presents the last game image again
} SwkbdKeepalive;

// Starts/wakes the worker, which sleeps while hidden until terminal stop.
// Called when the keyboard opens; `k` must stay valid until stop has joined.
void swkbd_keepalive_wake(const SwkbdKeepalive *k);
/* Terminal, main-thread-only stop. No future wake is admitted; joins without
   holding the worker lock. Deadline is absolute TIME_UTC. */
int swkbd_keepalive_stop(const struct timespec *deadline);

#endif
