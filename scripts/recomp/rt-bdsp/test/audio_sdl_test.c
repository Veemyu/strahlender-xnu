#include <assert.h>
#include <stdio.h>
#include <pthread.h>
#include <string.h>
#include <SDL3/SDL.h>
#include "audio_output.h"

struct SDL_AudioStream { int queued, running; };
static int references, streams, writes, resumed, fail_enqueue, fail_open;
static float last_gain;
static pthread_t main_thread;
bool SDL_InitSubSystem(uint32_t flags) {
    assert(pthread_equal(main_thread, pthread_self()));
    assert(flags == SDL_INIT_AUDIO); references++; return true;
}
void SDL_QuitSubSystem(uint32_t flags) {
    assert(pthread_equal(main_thread, pthread_self()));
    assert(flags == SDL_INIT_AUDIO); assert(references > 0); references--;
}
const char *SDL_GetError(void) { return "injected SDL audio error"; }
SDL_AudioStream *SDL_OpenAudioDeviceStream(uint32_t device, const SDL_AudioSpec *spec,
                                         SDL_AudioStreamCallback callback, void *user) {
    assert(device == SDL_AUDIO_DEVICE_DEFAULT_PLAYBACK && !callback && !user);
    assert(spec->format == SDL_AUDIO_S16LE && spec->freq == 48000 && spec->channels == 2);
    if (fail_open) return NULL;
    streams++;
    return calloc(1, sizeof(SDL_AudioStream));
}
bool SDL_ResumeAudioStreamDevice(SDL_AudioStream *stream) { stream->running = 1; resumed++; return true; }
bool SDL_PauseAudioStreamDevice(SDL_AudioStream *stream) { stream->running = 0; return true; }
bool SDL_ClearAudioStream(SDL_AudioStream *stream) { stream->queued = 0; return true; }
bool SDL_SetAudioStreamGain(SDL_AudioStream *stream, float gain) { assert(stream); last_gain = gain; return true; }
int SDL_GetAudioStreamQueued(SDL_AudioStream *stream) { return stream->queued; }
bool SDL_PutAudioStreamData(SDL_AudioStream *stream, const void *data, int bytes) {
    assert(data && bytes > 0);
    if (fail_enqueue) return false;
    writes++; stream->queued += bytes;
    assert(stream->queued <= 48000 * 4 / 5);
    return true;
}
void SDL_DestroyAudioStream(SDL_AudioStream *stream) { assert(stream); streams--; free(stream); }

static void *guest_audio(void *unused) {
    (void)unused;
    AudioOutput *output = audio_output_open(48000, 2);
    assert(output);
    char pcm[64] = {0};
    audio_output_start(output);
    audio_output_write(output, pcm, sizeof pcm);
    audio_output_close(output);
    return NULL;
}

int main(void) {
    main_thread = pthread_self();
    assert(!audio_output_open(48000, 2));
    assert(audio_output_init_main() && references == 1);
    assert(audio_output_init_main() && references == 1);
    fail_open = 1;
    assert(!audio_output_open(48000, 2) && references == 1 && streams == 0);
    fail_open = 0;
    AudioOutput *output = audio_output_open(48000, 2);
    assert(output && references == 1 && streams == 1 && last_gain == 1);
    char pcm[4096] = {0};
    audio_output_write(output, pcm, sizeof pcm);
    assert(writes == 1 && resumed == 0);
    audio_output_start(output);
    assert(resumed == 1);
    for (int i = 0; i < 100; i++) audio_output_write(output, pcm, sizeof pcm);
    assert(writes == 9);  // 36864 bytes fits in 200 ms; the next 4096 does not.
    audio_output_set_active(0);
    audio_output_write(output, pcm, sizeof pcm);
    assert(writes == 9);
    audio_output_set_active(1);
    audio_output_write(output, pcm, sizeof pcm);
    assert(writes == 10);
    audio_output_stop(output);
    int before = resumed;
    audio_output_set_active(0);
    audio_output_set_active(1);
    assert(resumed == before);
    fail_enqueue = 1;
    audio_output_write(output, pcm, sizeof pcm);
    fail_enqueue = 0;
    audio_output_write(output, pcm, sizeof pcm);
    assert(writes == 10);
    audio_output_close(output);
    audio_output_close(NULL);
    assert(references == 1 && !streams);
    pthread_t guest;
    assert(!pthread_create(&guest, NULL, guest_audio, NULL));
    assert(!pthread_join(guest, NULL));
    assert(references == 1 && !streams);
    audio_output_shutdown_main();
    audio_output_shutdown_main();
    assert(!references && !streams);
    puts("SDL bounded audio, suspend/resume and failure lifetime passed");
    return 0;
}
