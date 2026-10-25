// Controllers on macOS and iPadOS, through GameController.framework only (Switch Pro, Joy-Con, DualShock, DualSense, Xbox, MFi).
// SDL's gamepad subsystem must stay off here: it opens the same devices through HIDAPI and fights with Apple's driver over them.
// pad_gc_update() merges all connected controllers into one PadState (player 1) and hands it to the runtime (input.h); the Mac shell calls it
// every frame, the iPad shell from the controllers' change handlers. Included by one translation unit per app (app_ui.m, ios/app/app.m).
#pragma once
#import <GameController/GameController.h>
#include <math.h>
#include <stdatomic.h>
#include <stdio.h>
#include <time.h>
#include "input.h"

// Nintendo pads (Switch Pro, Joy-Con) arrive with the face buttons named like the labels on the pad: buttonA is the right button, as on the
// console. Xbox, PlayStation and generic pads name them by position (buttonA is the bottom one). Telling them apart keeps a Switch pad on
// the console's layout without a setting; the other pads follow the position rule unless the "xbox" layout option keeps their labels.
static inline BOOL pad_is_nintendo(GCController *c) {
    NSString *s = [NSString stringWithFormat:@"%@ %@", c.productCategory ?: @"", c.vendorName ?: @""].lowercaseString;
    return [s containsString:@"nintendo"] || [s containsString:@"switch"] || [s containsString:@"joy-con"] || [s containsString:@"joycon"];
}

static BOOL g_pad_by_position = YES;   // face buttons of non-Nintendo pads follow the console's positions (A right, B bottom, X top, Y left)

// A console passes the stick through raw and the game applies its own dead zone; ours stays small (4 %) and the rest of the travel is scaled up
// to the full range, so there is no jump at its edge. A large one adds to the game's and delays every move through the centre.
static int32_t pad_axis(float v) {
    const float dz = 0.04f;
    float a = fabsf(v);
    if (a <= dz) return 0;
    float r = (a - dz) / (1.0f - dz);
    int32_t o = (int32_t)(r * 32767.0f);
    if (o > 32767) o = 32767;
    return v < 0 ? -o : o;
}

static void pad_gc_update(void) {
    PadState s = {0};
    for (GCController *c in GCController.controllers) {
        GCExtendedGamepad *g = c.extendedGamepad;
        if (!g) continue;
        BOOL swap = g_pad_by_position && !pad_is_nintendo(c);
        if ((swap ? g.buttonB : g.buttonA).pressed) s.buttons |= 1ull << PB_A;
        if ((swap ? g.buttonA : g.buttonB).pressed) s.buttons |= 1ull << PB_B;
        if ((swap ? g.buttonY : g.buttonX).pressed) s.buttons |= 1ull << PB_X;
        if ((swap ? g.buttonX : g.buttonY).pressed) s.buttons |= 1ull << PB_Y;
        if (g.leftShoulder.pressed) s.buttons |= 1ull << PB_L;
        if (g.rightShoulder.pressed) s.buttons |= 1ull << PB_R;
        if (g.leftTrigger.pressed) s.buttons |= 1ull << PB_ZL;
        if (g.rightTrigger.pressed) s.buttons |= 1ull << PB_ZR;
        if (g.buttonMenu.pressed) s.buttons |= 1ull << PB_PLUS;
        if (g.buttonOptions.pressed) s.buttons |= 1ull << PB_MINUS;
        if (g.leftThumbstickButton.pressed) s.buttons |= 1ull << PB_LSTICK;
        if (g.rightThumbstickButton.pressed) s.buttons |= 1ull << PB_RSTICK;
        if (g.dpad.left.pressed) s.buttons |= 1ull << PB_LEFT;
        if (g.dpad.right.pressed) s.buttons |= 1ull << PB_RIGHT;
        if (g.dpad.up.pressed) s.buttons |= 1ull << PB_UP;
        if (g.dpad.down.pressed) s.buttons |= 1ull << PB_DOWN;
        int32_t v[4] = {pad_axis(g.leftThumbstick.xAxis.value), pad_axis(g.leftThumbstick.yAxis.value),
                        pad_axis(g.rightThumbstick.xAxis.value), pad_axis(g.rightThumbstick.yAxis.value)};
        for (int i = 0; i < 4; i++) if (!s.stick[i]) s.stick[i] = v[i];   // first pad that moves the stick wins
    }
    input_pad_set(&s);
    static int log_on = -1;   // BDSP_PAD_LOG=1: every change of the buttons with the time, to see when the pad's report reached us
    if (log_on < 0) log_on = getenv("BDSP_PAD_LOG") != NULL;
    static uint64_t last_b = ~0ull;
    if (log_on && s.buttons != last_b) {
        last_b = s.buttons;
        fprintf(stderr, "[pad] %.3f buttons %#llx\n", (double)clock_gettime_nsec_np(CLOCK_MONOTONIC) / 1e9, (unsigned long long)s.buttons);
    }
}

// Event-driven: reports every change of this controller the moment Apple's driver delivers it. On the Mac the handlers run on a queue of their
// own, so a slow window loop (it waits up to 16 ms and is busy with other events) cannot add to the delay; a controller that went away is dropped
// from the next update.
__attribute__((unused)) static dispatch_queue_t pad_gc_queue(void) {
    static dispatch_queue_t q;
    static dispatch_once_t once;
    dispatch_once(&once, ^{ q = dispatch_queue_create("pad-gc", dispatch_queue_attr_make_with_qos_class(DISPATCH_QUEUE_SERIAL, QOS_CLASS_USER_INTERACTIVE, 0)); });
    return q;
}

__attribute__((unused)) static void pad_gc_bind(GCController *c) {
#if !TARGET_OS_IPHONE
    c.handlerQueue = pad_gc_queue();
#endif
    c.extendedGamepad.valueChangedHandler = ^(GCExtendedGamepad *p, GCControllerElement *e) {
        static int log_on = -1;   // BDSP_PAD_LOG=1: how often Apple's driver reports a change per second (its report rate; sticks report constantly)
        if (log_on < 0) log_on = getenv("BDSP_PAD_LOG") != NULL;
        if (log_on) {
            static _Atomic unsigned n;
            static _Atomic uint64_t t0;
            uint64_t now = clock_gettime_nsec_np(CLOCK_MONOTONIC), start = atomic_load(&t0);
            if (!start) { atomic_store(&t0, now); start = now; }
            atomic_fetch_add(&n, 1);
            if (now - start >= 1000000000ull) {
                unsigned c = atomic_exchange(&n, 0);
                atomic_store(&t0, now);
                if (c > 1) fprintf(stderr, "[pad] driver changes: %.1f per second\n", c * 1e9 / (double)(now - start));
            }
        }
        pad_gc_update();
    };
}

// Binds controllers that appeared since the last call (the Mac shell calls this every frame instead of waiting for the connect notification).
__attribute__((unused)) static void pad_gc_bind_new(void) {
    static NSHashTable *bound;
    if (!bound) bound = [NSHashTable weakObjectsHashTable];
    for (GCController *c in GCController.controllers)
        if (c.extendedGamepad && ![bound containsObject:c]) { [bound addObject:c]; pad_gc_bind(c); }
}
