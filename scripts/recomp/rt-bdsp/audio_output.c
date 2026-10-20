// Bounded PCM16 playback. Guest completion remains on the service's real-time clock.
#include "audio_output.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#if defined(__APPLE__)
#include <AudioToolbox/AudioToolbox.h>
#include <stdatomic.h>
#include <pthread.h>

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
    atomic_uint_fast64_t returned;
};

static pthread_mutex_t outputs_lock = PTHREAD_MUTEX_INITIALIZER;
static AudioOutput *outputs[8];
static int outputs_active = 1;

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
    float gain = 1.0f;
    const char *value = getenv("BDSP_AUDIO_GAIN");
    if (value) {
        char *end;
        float parsed = strtof(value, &end);
        if (end != value && !*end && parsed >= 0 && parsed <= 1) gain = parsed;
    }
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
        atomic_store_explicit(&slot->busy, 1, memory_order_release);
        OSStatus status = AudioQueueEnqueueBuffer(out->queue, slot->buffer, 0, NULL);
        if (status) {
            atomic_store(&slot->busy, 0);
            output_error(out, "enqueue", status);
            return;
        }
        out->submitted++;
        output_resume(out);
        if (getenv("BDSP_AUDIO_PROBE") && !(out->submitted % 512))
            fprintf(stderr, "[audio-output] submitted=%llu returned=%llu dropped=%llu\n",
                (unsigned long long)out->submitted, (unsigned long long)atomic_load(&out->returned),
                (unsigned long long)out->dropped);
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
#else
// Linux output remains a later step.
struct AudioOutput { int unused; };
AudioOutput *audio_output_open(uint32_t rate, uint32_t channels) { (void)rate; (void)channels; return NULL; }
void audio_output_start(AudioOutput *out) { (void)out; }
void audio_output_stop(AudioOutput *out) { (void)out; }
void audio_output_write(AudioOutput *out, const void *pcm, size_t bytes) { (void)out; (void)pcm; (void)bytes; }
void audio_output_close(AudioOutput *out) { (void)out; }
void audio_output_set_active(int active) { (void)active; }
#endif
