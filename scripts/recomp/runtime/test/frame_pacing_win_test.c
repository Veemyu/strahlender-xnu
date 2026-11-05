// Deterministic deadline tests against the real input_frame path, with a quantized OS sleep.
#include "plat.h"
#include <assert.h>
#include <stdio.h>
#include <time.h>

volatile int g_bdsp_fps = 60;
static uint64_t now = 1000000000ull;
static unsigned waits;

uint64_t frame_test_now(void) { return now; }
int __wrap_nanosleep64(const struct timespec *duration, struct timespec *remaining) {
    (void)remaining;
    now += (uint64_t)duration->tv_sec * 1000000000ull +
           (uint64_t)(duration->tv_nsec / 1000000) * 1000000ull;
    waits++;
    return 0;
}
void frame_test_sleep_until(uint64_t deadline) {
    assert(deadline > now);
    now = deadline;
    waits++;
}

void input_frame(uint64_t frame);

int main(void) {
    const uint64_t start = now, period = 1000000000ull / 60;
    for (unsigned frame = 1; frame <= 120; frame++) {
        input_frame(frame);
        uint64_t expected = start + frame * period;
        if (now < expected) {
            fprintf(stderr, "Frame %u returned %llu ns before its deadline\n", frame,
                    (unsigned long long)(expected - now));
            return 1;
        }
        assert(now == expected);
        now += 3000000;  // the next frame's work
    }
    assert(waits == 120);
    now += 1000000000ull;  // resume after a loading stall; do not burst to catch up
    uint64_t resume = now;
    input_frame(121);
    assert(now == resume + period);
    puts("frame pacing deadlines ok");
    return 0;
}
