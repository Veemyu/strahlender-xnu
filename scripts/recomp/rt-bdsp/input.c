#include "input.h"
#include <stdatomic.h>
#include <string.h>
#include "swkbd_ui.h"

extern _Atomic uint64_t g_ext_buttons;   // nvn_glue.c: what the game's Npad reads
extern _Atomic int32_t g_ext_stick[4];

void input_pad_set(const PadState *s) {
    static PadState last;
    static int first = 1;
    if (!first && !memcmp(&last, s, sizeof last)) return;
    first = 0;
    last = *s;
    if (swkbd_ui_active()) {   // the on-screen keyboard has the input; the game sees nothing meanwhile
        atomic_store(&g_ext_buttons, 0);
        for (int i = 0; i < 4; i++) atomic_store(&g_ext_stick[i], 0);
    } else {
        atomic_store(&g_ext_buttons, s->buttons);
        for (int i = 0; i < 4; i++) atomic_store(&g_ext_stick[i], s->stick[i]);
    }
    swkbd_ui_pad(s->buttons, s->stick[0], s->stick[1]);
}
