// Bounded PCM16 playback. Guest completion remains on the service's real-time clock.
#include "audio_output.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <pthread.h>

static pthread_mutex_t outputs_lock = PTHREAD_MUTEX_INITIALIZER;
static AudioOutput *outputs[8];
static int outputs_active = 1;

#if defined(__APPLE__) || ((defined(__linux__) || defined(_WIN32)) && !defined(BDSP_NVN_NONE))
static float output_gain(void) {
    const char *value = getenv("BDSP_AUDIO_GAIN");
    if (value) {
        char *end;
        float gain = strtof(value, &end);
        if (end != value && !*end && gain >= 0 && gain <= 1) return gain;
    }
    return 1.0f;
}
#endif

#if defined(__APPLE__)
#include <AudioToolbox/AudioToolbox.h>
#include <stdatomic.h>

static bool output_init_main(void) { return true; }
static void output_shutdown_main(void) {}

#define OUTPUT_SLOTS 8
typedef struct {
    AudioQueueBufferRef buffer;
    atomic_bool busy;
} OutputSlot;

struct AudioOutput {
    AudioQueueRef queue;
    OutputSlot slots[OUTPUT_SLOTS];
    size_t frame_bytes, max_bytes;
    int started, running, failed;
    uint64_t submitted, dropped;
    int peak;   // BDSP_AUDIO_PROBE: loudest PCM16 sample since the last report
    int kicked; // BDSP_AUDIO_KICK: the one-time restart has happened
    int64_t sum, activity, samples;   // BDSP_AUDIO_PROBE: DC offset and sample-to-sample change since the last report
    double probe_sample, probe_t;     // BDSP_AUDIO_PROBE: device sample time at the last report (played rate)
    atomic_uint_fast64_t returned;
};

// The callback never accesses guest memory, locks, the kernel or IPC.
static void output_returned(void *context, AudioQueueRef queue, AudioQueueBufferRef buffer) {
    (void)queue;
    AudioOutput *out = context;
    OutputSlot *slot = buffer->mUserData;
    atomic_fetch_add_explicit(&out->returned, 1, memory_order_relaxed);
    atomic_store_explicit(&slot->busy, 0, memory_order_release);
}

static void output_error(AudioOutput *out, const char *operation, OSStatus status) {
    if (!out->failed) fprintf(stderr, "[audio-output] %s failed (%d); silent fallback\n", operation, (int)status);
    out->failed = 1;
}

static void output_resume(AudioOutput *out) {
    if (!outputs_active || !out->started || out->running || !out->submitted || out->failed) return;
    OSStatus status = AudioQueueStart(out->queue, NULL);
    if (status) output_error(out, "start", status);
    else out->running = 1;
}

static AudioOutput *output_open(uint32_t rate, uint32_t channels) {
    const char *enabled = getenv("BDSP_AUDIO");
    if (enabled && !strcmp(enabled, "0")) return NULL;
    if (rate < 8000 || rate > 192000 || !channels || channels > 8) return NULL;
    AudioOutput *out = calloc(1, sizeof *out);
    if (!out) return NULL;
    out->frame_bytes = 2 * channels;
    // At most eight 25 ms buffers: bounded memory and approximately 200 ms queued audio.
    out->max_bytes = (rate / 40) * out->frame_bytes;
    atomic_init(&out->returned, 0);
    for (int i = 0; i < OUTPUT_SLOTS; i++) atomic_init(&out->slots[i].busy, 0);
    AudioStreamBasicDescription format = {
        .mSampleRate = rate, .mFormatID = kAudioFormatLinearPCM,
        .mFormatFlags = kLinearPCMFormatFlagIsSignedInteger | kLinearPCMFormatFlagIsPacked,
        .mBytesPerPacket = (UInt32)out->frame_bytes, .mFramesPerPacket = 1,
        .mBytesPerFrame = (UInt32)out->frame_bytes, .mChannelsPerFrame = channels, .mBitsPerChannel = 16,
    };
    OSStatus status = AudioQueueNewOutput(&format, output_returned, out, NULL, NULL, 0, &out->queue);
    if (status) {
        fprintf(stderr, "[audio-output] open failed (%d); silent fallback\n", (int)status);
        free(out);
        return NULL;
    }
    float gain = output_gain();
    status = AudioQueueSetParameter(out->queue, kAudioQueueParam_Volume, gain);
    if (status) output_error(out, "volume", status);
    fprintf(stderr, "[audio-output] PCM16 %u Hz %u channels, gain %.2f\n", rate, channels, gain);
    return out;
}

static void output_start(AudioOutput *out) {
    if (!out) return;
    out->started = 1;
    output_resume(out);
}

static void output_stop(AudioOutput *out) {
    if (!out) return;
    out->started = out->running = 0;
    OSStatus status = AudioQueueStop(out->queue, true);
    if (status) { output_error(out, "stop", status); return; }
    // Synchronous stop quiesces callbacks and removes all queued buffers.
    for (int i = 0; i < OUTPUT_SLOTS; i++) atomic_store(&out->slots[i].busy, 0);
    out->submitted = 0;
    atomic_store(&out->returned, 0);
}

static void output_write(AudioOutput *out, const void *pcm, size_t bytes) {
    if (!outputs_active || !out || out->failed || !bytes || bytes % out->frame_bytes) return;
    {   // BDSP_AUDIO_KICK=<s> (diagnostics): once, after s seconds, stop the queue and let the next write start it again
        static double kick_at = -1, t0;
        if (kick_at < 0) { const char *e = getenv("BDSP_AUDIO_KICK"); kick_at = e ? atof(e) : 0; t0 = CFAbsoluteTimeGetCurrent(); }
        if (kick_at > 0 && !out->kicked && CFAbsoluteTimeGetCurrent() - t0 > kick_at) {
            out->kicked = 1;
            fprintf(stderr, "[audio-output] kick: restarting the queue\n");
            AudioQueueStop(out->queue, true);
            out->running = 0;
            for (int i = 0; i < OUTPUT_SLOTS; i++) atomic_store(&out->slots[i].busy, 0);
        }
    }
    const uint8_t *src = pcm;
    while (bytes) {
        OutputSlot *slot = NULL;
        for (int i = 0; i < OUTPUT_SLOTS; i++) {
            if (!atomic_load_explicit(&out->slots[i].busy, memory_order_acquire)) { slot = &out->slots[i]; break; }
        }
        if (!slot) {
            out->dropped++;
            if (!(out->dropped & (out->dropped - 1)))
                fprintf(stderr, "[audio-output] queue full, dropped writes=%llu\n", (unsigned long long)out->dropped);
            return;
        }
        if (!slot->buffer) {
            OSStatus status = AudioQueueAllocateBuffer(out->queue, (UInt32)out->max_bytes, &slot->buffer);
            if (status) { output_error(out, "allocate", status); return; }
            slot->buffer->mUserData = slot;
        }
        size_t count = bytes < out->max_bytes ? bytes : out->max_bytes;
        memcpy(slot->buffer->mAudioData, src, count);
        slot->buffer->mAudioDataByteSize = (UInt32)count;
        static int probe = -1;
        if (probe < 0) probe = getenv("BDSP_AUDIO_PROBE") != NULL;
        if (probe) {
            const int16_t *s = slot->buffer->mAudioData;
            for (size_t i = 0; i < count / 2; i++) {
                int a = s[i] < 0 ? -s[i] : s[i];
                if (a > out->peak) out->peak = a;
                out->sum += s[i];
                if (i >= 2) { int d = s[i] - s[i - 2]; out->activity += d < 0 ? -d : d; }
                out->samples++;
            }
        }
        atomic_store_explicit(&slot->busy, 1, memory_order_release);
        OSStatus status = AudioQueueEnqueueBuffer(out->queue, slot->buffer, 0, NULL);
        if (status) {
            atomic_store(&slot->busy, 0);
            output_error(out, "enqueue", status);
            return;
        }
        out->submitted++;
        output_resume(out);
        if (getenv("BDSP_AUDIO_PROBE") && !(out->submitted % 128)) {
            UInt32 is_running = 0, size = sizeof is_running;
            AudioQueueGetProperty(out->queue, kAudioQueueProperty_IsRunning, &is_running, &size);
            {   // samples the device really played per wall-clock second (48000 expected)
                AudioTimeStamp ts;
                double now = CFAbsoluteTimeGetCurrent();
                if (AudioQueueGetCurrentTime(out->queue, NULL, &ts, NULL) == 0 && out->probe_t > 0 && now > out->probe_t)
                    fprintf(stderr, "[audio-output] played rate %.0f samples/s\n", (ts.mSampleTime - out->probe_sample) / (now - out->probe_t));
                if (AudioQueueGetCurrentTime(out->queue, NULL, &ts, NULL) == 0) { out->probe_sample = ts.mSampleTime; out->probe_t = now; }
            }
            fprintf(stderr, "[audio-output] submitted=%llu returned=%llu dropped=%llu peak=%d queue_running=%u dc=%lld activity=%lld\n",
                (unsigned long long)out->submitted, (unsigned long long)atomic_load(&out->returned),
                (unsigned long long)out->dropped, out->peak, (unsigned)is_running,
                (long long)(out->samples ? out->sum / out->samples : 0), (long long)(out->samples ? out->activity / out->samples : 0));
            out->peak = 0;
            out->sum = out->activity = out->samples = 0;
        }
        src += count;
        bytes -= count;
    }
}

static void output_close(AudioOutput *out) {
    if (!out) return;
    // Dispose synchronously before releasing the callback context and its slots.
    OSStatus status = AudioQueueDispose(out->queue, true);
    if (status) { output_error(out, "dispose", status); return; }
    fprintf(stderr, "[audio-output] closed, submitted=%llu returned=%llu dropped=%llu\n",
        (unsigned long long)out->submitted, (unsigned long long)atomic_load(&out->returned),
        (unsigned long long)out->dropped);
    free(out);
}

#elif (defined(__linux__) || defined(_WIN32)) && !defined(BDSP_NVN_NONE)
#include <SDL3/SDL.h>

static bool sdl_initialized;
static bool output_init_main(void) {
    if (sdl_initialized) return true;
    const char *enabled = getenv("BDSP_AUDIO");
    if (enabled && !strcmp(enabled, "0")) return true;
    if (!SDL_InitSubSystem(SDL_INIT_AUDIO)) {
        fprintf(stderr, "[audio-output] initialization failed: %s\n", SDL_GetError());
        return false;
    }
    sdl_initialized = true;
    return true;
}
static void output_shutdown_main(void) {
    if (sdl_initialized) SDL_QuitSubSystem(SDL_INIT_AUDIO);
    sdl_initialized = false;
}

struct AudioOutput {
    SDL_AudioStream *stream;
    size_t frame_bytes, max_bytes;
    int started, failed;
    uint64_t dropped;
};

static void output_error(AudioOutput *out, const char *operation) {
    if (!out->failed) fprintf(stderr, "[audio-output] %s failed: %s\n", operation, SDL_GetError());
    out->failed = 1;
}

static void output_resume(AudioOutput *out) {
    if (outputs_active && out->started && !out->failed && !SDL_ResumeAudioStreamDevice(out->stream))
        output_error(out, "resume");
}

static AudioOutput *output_open(uint32_t rate, uint32_t channels) {
    const char *enabled = getenv("BDSP_AUDIO");
    if (enabled && !strcmp(enabled, "0")) return NULL;
    if (rate < 8000 || rate > 192000 || !channels || channels > 8) {
        fprintf(stderr, "[audio-output] invalid PCM16 format %u Hz, %u channels\n", rate, channels);
        return NULL;
    }
    if (!sdl_initialized) {
        fprintf(stderr, "[audio-output] subsystem was not initialized on the window thread\n");
        return NULL;
    }
    AudioOutput *out = calloc(1, sizeof *out);
    if (!out) { fprintf(stderr, "[audio-output] allocation failed\n"); return NULL; }
    SDL_AudioSpec spec = {.format = SDL_AUDIO_S16LE, .channels = (int)channels, .freq = (int)rate};
    out->stream = SDL_OpenAudioDeviceStream(SDL_AUDIO_DEVICE_DEFAULT_PLAYBACK, &spec, NULL, NULL);
    if (!out->stream) {
        fprintf(stderr, "[audio-output] open failed: %s\n", SDL_GetError());
        free(out); return NULL;
    }
    out->frame_bytes = 2 * channels;
    out->max_bytes = rate * out->frame_bytes / 5;  // 200 ms, as on AudioQueue.
    float gain = output_gain();
    if (!SDL_SetAudioStreamGain(out->stream, gain)) output_error(out, "volume");
    fprintf(stderr, "[audio-output] SDL PCM16 %u Hz %u channels, gain %.2f\n", rate, channels, gain);
    return out;
}

static void output_start(AudioOutput *out) {
    if (!out) return;
    out->started = 1;
    output_resume(out);
}
static void output_stop(AudioOutput *out) {
    if (!out) return;
    out->started = 0;
    if (!SDL_PauseAudioStreamDevice(out->stream)) output_error(out, "pause");
    if (!SDL_ClearAudioStream(out->stream)) output_error(out, "clear");
}
static void output_write(AudioOutput *out, const void *pcm, size_t bytes) {
    if (!outputs_active || !out || out->failed || !bytes) return;
    if (bytes % out->frame_bytes) {
        fprintf(stderr, "[audio-output] unaligned PCM write\n");
        out->failed = 1; return;
    }
    int queued = SDL_GetAudioStreamQueued(out->stream);
    if (queued < 0) { output_error(out, "queued size"); return; }
    if (bytes > out->max_bytes || (size_t)queued > out->max_bytes - bytes) {
        out->dropped++;
        if (!(out->dropped & (out->dropped - 1)))
            fprintf(stderr, "[audio-output] queue full, dropped writes=%llu\n", (unsigned long long)out->dropped);
        return;
    }
    if (!SDL_PutAudioStreamData(out->stream, pcm, (int)bytes)) { output_error(out, "enqueue"); return; }
    output_resume(out);
}
static void output_close(AudioOutput *out) {
    if (!out) return;
    SDL_DestroyAudioStream(out->stream);
    free(out);
}
#else
struct AudioOutput { int started; };
static bool output_init_main(void) { return true; }
static void output_shutdown_main(void) {}
static AudioOutput *output_open(uint32_t rate, uint32_t channels) { (void)rate; (void)channels; return NULL; }
static void output_start(AudioOutput *out) { (void)out; }
static void output_stop(AudioOutput *out) { (void)out; }
static void output_write(AudioOutput *out, const void *pcm, size_t bytes) { (void)out; (void)pcm; (void)bytes; }
static void output_close(AudioOutput *out) { (void)out; }
static void output_resume(AudioOutput *out) { (void)out; }
#endif

bool audio_output_init_main(void) {
    pthread_mutex_lock(&outputs_lock);
    bool initialized = output_init_main();
    pthread_mutex_unlock(&outputs_lock);
    return initialized;
}

void audio_output_shutdown_main(void) {
    pthread_mutex_lock(&outputs_lock);
    for (int i = 0; i < 8; i++) {
        output_close(outputs[i]);
        outputs[i] = NULL;
    }
    output_shutdown_main();
    pthread_mutex_unlock(&outputs_lock);
}

AudioOutput *audio_output_open(uint32_t rate, uint32_t channels) {
    pthread_mutex_lock(&outputs_lock);
    AudioOutput *out = NULL;
    for (int i = 0; i < 8; i++) if (!outputs[i]) {
        out = output_open(rate, channels);
        outputs[i] = out;
        break;
    }
    pthread_mutex_unlock(&outputs_lock);
    return out;
}

void audio_output_start(AudioOutput *out) {
    pthread_mutex_lock(&outputs_lock);
    output_start(out);
    pthread_mutex_unlock(&outputs_lock);
}

void audio_output_stop(AudioOutput *out) {
    pthread_mutex_lock(&outputs_lock);
    output_stop(out);
    pthread_mutex_unlock(&outputs_lock);
}

void audio_output_write(AudioOutput *out, const void *pcm, size_t bytes) {
    pthread_mutex_lock(&outputs_lock);
    output_write(out, pcm, bytes);
    pthread_mutex_unlock(&outputs_lock);
}

void audio_output_close(AudioOutput *out) {
    pthread_mutex_lock(&outputs_lock);
    for (int i = 0; i < 8; i++) if (outputs[i] == out) outputs[i] = NULL;
    output_close(out);
    pthread_mutex_unlock(&outputs_lock);
}

void audio_output_set_active(int active) {
    pthread_mutex_lock(&outputs_lock);
    outputs_active = active != 0;
    for (int i = 0; i < 8; i++) {
        AudioOutput *out = outputs[i];
        if (!out) continue;
        if (outputs_active) output_resume(out);
        else {
            int started = out->started;
            output_stop(out);
            out->started = started;
        }
    }
    pthread_mutex_unlock(&outputs_lock);
}
