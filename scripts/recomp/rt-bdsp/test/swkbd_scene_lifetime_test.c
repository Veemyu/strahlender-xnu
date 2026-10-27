// Scene text must remain valid until the renderer releases the keyboard lock.
#include "../swkbd_ui.h"
#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
__attribute__((noinline)) static void reuse_stack(void) {
    volatile char overwrite[8192];
    for (unsigned i = 0; i < sizeof overwrite; i++) overwrite[i] = (char)0xff;
}
int main(void) {
    setenv("BDSP_SWKBD_SIMPLE", "1", 1);
    setenv("BDSP_SWKBD_SOUND", "0", 1);
    swkbd_ui_set_display(1);
    for (int password = 0; password <= 1; password++) {
        SwkbdParams p = {.maxlen=12, .password=password};
        strcpy(p.header, "Name"); strcpy(p.initial, "Test");
        assert(!swkbd_ui_open(&p, (SwkbdCallbacks){0}, NULL));
        float scale, off[2];
        const LytScene *scene = swkbd_ui_scene(0.016, 1280, 720, &scale, off);
        assert(scene);
        reuse_stack();
        int countFound = 0, textFound = 0;
        for (int i = 0; i < scene->n; i++) {
            const LytItem *item = &scene->items[i];
            if (item->type != LYT_ITEM_TEXT) continue;
            assert(item->str && strlen(item->str) < 1100);
            countFound |= !strcmp(item->str, "4/12");
            textFound |= !strcmp(item->str, password ? "****" : "Test");
        }
        assert(countFound && textFound);
        swkbd_ui_unlock();
        swkbd_ui_resolve(1, NULL);
        for (int i = 0; i < 30; i++) if (swkbd_ui_scene(0.016, 1280, 720, &scale, off)) swkbd_ui_unlock();
    }
    puts("Keyboard scene text lifetime passed.");
}
