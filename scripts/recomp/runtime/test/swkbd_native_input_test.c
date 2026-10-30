// iOS policy without proprietary firmware: only native editing, no fallback grid.
#include "../swkbd_ui.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
int swkbd_text_firmware_ready(const char *root) { (void)root; return 0; }
static char submitted[1024];
static void submit(void *user, const char *text) { (void)user; snprintf(submitted, sizeof submitted, "%s", text); }
int main(void) {
    setenv("BDSP_SWKBD_SIMPLE", "1", 1); setenv("BDSP_SWKBD_SOUND", "0", 1);
    setenv("BDSP_SWKBD_LAYOUT", "ja", 1); // UIKit text must not be converted again by the Horizon IME.
    swkbd_ui_set_display(1);
    SwkbdParams p = {.minlen=2, .maxlen=4};
    strcpy(p.header, "Tell me, what is your name?"); strcpy(p.initial, "A");
    assert(!swkbd_ui_open(&p, (SwkbdCallbacks){.submit=submit}, NULL));
    SwkbdNativeState state;
    assert(swkbd_ui_native_state(&state) && !strcmp(state.text, "A"));
    float scale, off[2];
    const LytScene *scene = swkbd_ui_scene(0.016, 2688, 1242, &scale, off);
    assert(scene && scene->n == 1 && scene->items[0].type == LYT_ITEM_QUAD);
    swkbd_ui_unlock(); // No rendered prompt, key rows, counter or footer glyphs.
    swkbd_ui_replace_text("äbcde");
    assert(swkbd_ui_native_state(&state) && !strcmp(state.text, "äbcd"));
    swkbd_ui_pad(1, 0, 0); swkbd_ui_pad(0, 0, 0);
    swkbd_ui_touch(1, 0.5f, 0.7f); swkbd_ui_touch(0, 0.5f, 0.7f);
    assert(swkbd_ui_native_state(&state) && !strcmp(state.text, "äbcd"));
    swkbd_ui_replace_text("Vee"); swkbd_ui_key(SWKBD_KEY_ENTER);
    assert(!strcmp(submitted, "Vee"));
    assert(swkbd_ui_native_state(&state) && state.busy);
    swkbd_ui_replace_text("no");
    assert(swkbd_ui_native_state(&state) && !strcmp(state.text, "Vee"));
    swkbd_ui_resolve(0, "Choose another name");
    assert(swkbd_ui_native_state(&state) && !state.busy && !strcmp(state.message, "Choose another name"));
    swkbd_ui_replace_text(""); assert(swkbd_ui_native_state(&state) && !state.text[0]);
    swkbd_ui_replace_text("Ok"); swkbd_ui_key(SWKBD_KEY_ENTER);
    assert(!strcmp(submitted, "Ok"));
    swkbd_ui_resolve(1, NULL); assert(!swkbd_ui_native_state(NULL));
    puts("Native keyboard fallback passed.");
}
