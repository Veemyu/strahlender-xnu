#include "input.h"
#include <pthread.h>
#include <string.h>
#include "swkbd_ui.h"

static pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;
static PadState src[INPUT_SRC_COUNT];
static int kb_was;

void input_source_set(InputSource id, const PadState *s) {
    pthread_mutex_lock(&lock);
    int changed = memcmp(&src[id], s, sizeof *s) != 0;
    src[id] = *s;
    pthread_mutex_unlock(&lock);
    if (changed && id == INPUT_SRC_PAD && swkbd_ui_active()) swkbd_ui_pad(s->buttons, s->stick[0], s->stick[1]);
}

void input_current(PadState *out) {
    memset(out, 0, sizeof *out);
    if (swkbd_ui_active()) return;
    pthread_mutex_lock(&lock);
    for (int i = 0; i < INPUT_SRC_COUNT; i++) {
        out->buttons |= src[i].buttons;
        for (int a = 0; a < 4; a++) if (!out->stick[a]) out->stick[a] = src[i].stick[a];
    }
    pthread_mutex_unlock(&lock);
}

void input_tick(void) {
    int on = swkbd_ui_active() != 0;
    pthread_mutex_lock(&lock);
    int opened = on && !kb_was;
    kb_was = on;
    PadState pad = src[INPUT_SRC_PAD];
    pthread_mutex_unlock(&lock);
    if (opened) swkbd_ui_pad_held(pad.buttons, pad.stick[0], pad.stick[1]);
}
