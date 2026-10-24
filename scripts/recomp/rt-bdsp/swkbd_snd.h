// Sounds of the on-screen keyboard (key focus ticks, key presses, error), read from the user's own firmware: <BDSP_FIRMWARE_DATA>/swkbd/sound/swkbd.bfsar
// (sound archive of the keyboard applet, see scripts/swkbd_firmware_extract.py). Own code; nothing of it is stored in the repository.
// The archive holds named wave sounds (SeSwkbdGlyph, SeSwkbdBsDecide, ...); each name leads through a wave sound table to a PCM16 sample.
#ifndef SWKBD_SND_H
#define SWKBD_SND_H

#include <stddef.h>
#include <stdint.h>

// Folder that contains swkbd/sound/swkbd.bfsar (the firmware data folder). Without it, or when the file is missing, nothing is played.
void swkbd_snd_set_root(const char *root);
// Plays the sound with this name (e.g. "SeSwkbdGlyph") once, in the background. Safe from any thread. BDSP_SWKBD_SOUND=0 switches the sounds off.
void swkbd_snd_play(const char *name);
// For tests: sample count, sample rate, volume (0..127) and peak of a decoded sound; 0 when the name is unknown, 1 when found.
int swkbd_snd_info(const char *name, size_t *frames, uint32_t *rate, int *volume, int *peak);
// For tests: parses an archive held in memory. Returns the number of playable sounds, -1 when it is not a sound archive.
int swkbd_snd_load_memory(const uint8_t *data, size_t size);

#endif
