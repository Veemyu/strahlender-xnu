// The thread that keeps the keyboard's picture alive while the game is stopped inside the keyboard call and presents nothing: it asks the
// renderer to present the last game image again (with the keyboard drawn over it) whenever the game has not presented for a moment and
// something was entered or moves (otherwise only for the blinking caret). It runs only while the keyboard is visible. Shared by the Metal and
// the Vulkan overlay; each supplies its clock and its "present again" call.
#ifndef SWKBD_KEEPALIVE_H
#define SWKBD_KEEPALIVE_H

#include <stdint.h>

typedef struct {
    uint64_t (*now_ns)(void);
    uint64_t (*game_present_ns)(void);   // time of the game's last own presentation (same clock as now_ns)
    void (*represent)(void);             // presents the last game image again
} SwkbdKeepalive;

// Starts the thread unless it runs already (called from the keyboard's wake-up when it opens). `k` must stay valid.
void swkbd_keepalive_wake(const SwkbdKeepalive *k);

#endif
