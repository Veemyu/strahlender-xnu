// Host PCM16 playback. Callers serialize operations on each output.
#pragma once
#include <stddef.h>
#include <stdint.h>

typedef struct AudioOutput AudioOutput;
AudioOutput *audio_output_open(uint32_t rate, uint32_t channels);
void audio_output_start(AudioOutput *out);
void audio_output_stop(AudioOutput *out);
void audio_output_write(AudioOutput *out, const void *pcm, size_t bytes);
void audio_output_close(AudioOutput *out);
// App-wide suspension; unlike guest Stop, this preserves the requested playback state.
void audio_output_set_active(int active);
