// Test of the keyboard's sound archive reader. The synthetic part always runs; the firmware part runs when BDSP_FIRMWARE_DATA points at a
// folder with swkbd/sound/swkbd.bfsar (the user's own firmware files) and otherwise is skipped.
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "../swkbd_snd.h"

static int fails;
#define CHECK(c) do { if (!(c)) { printf("FAIL line %d: %s\n", __LINE__, #c); fails++; } } while (0)

int main(void) {
    uint8_t junk[64];
    memset(junk, 0x5a, sizeof junk);
    CHECK(swkbd_snd_load_memory(junk, sizeof junk) == -1);          // not an archive
    CHECK(swkbd_snd_load_memory((const uint8_t *)"FSAR", 4) == -1);  // truncated
    uint8_t cut[0x40] = {'F', 'S', 'A', 'R'};
    cut[0x10] = 3;
    CHECK(swkbd_snd_load_memory(cut, sizeof cut) == -1);            // blocks point nowhere

    const char *root = getenv("BDSP_FIRMWARE_DATA");
    if (root && *root) {
        swkbd_snd_set_root(root);
        size_t frames = 0;
        uint32_t rate = 0;
        int vol = 0, peak = 0;
        if (swkbd_snd_info("SeSwkbdGlyph", &frames, &rate, &vol, &peak)) {
            printf("SeSwkbdGlyph: %zu frames at %u Hz, volume %d, peak %d\n", frames, rate, vol, peak);
            CHECK(rate == 48000 && frames > 1000 && frames < 6000 && vol == 127 && peak > 10000);
            CHECK(swkbd_snd_info("SeSwkbdGlyphFocus", &frames, &rate, &vol, &peak) && frames < 500 && vol < 100);   // a short, quiet tick
            CHECK(swkbd_snd_info("SeSwkbdBsDecide", NULL, NULL, NULL, NULL));
            CHECK(swkbd_snd_info("SeSwkbdEnterDecide", NULL, NULL, NULL, NULL));
            CHECK(swkbd_snd_info("SeSwkbdLengthError", NULL, NULL, NULL, NULL));
            CHECK(!swkbd_snd_info("NoSuchSound", NULL, NULL, NULL, NULL));
            printf("firmware part ok\n");
        } else {
            printf("no sound archive in %s, firmware part skipped\n", root);
        }
    } else {
        printf("BDSP_FIRMWARE_DATA not set, firmware part skipped\n");
    }
    printf(fails ? "swkbd_snd_test: %d FAILED\n" : "swkbd_snd_test: ok\n", fails);
    return fails != 0;
}
