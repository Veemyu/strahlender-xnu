// Controllers on macOS and iPadOS, through GameController.framework only (Switch Pro, Joy-Con, DualShock, DualSense, Xbox, MFi).
// SDL's gamepad subsystem must stay off here: it opens the same devices through HIDAPI and fights with Apple's driver over them.
// pad_gc_update() merges all connected controllers into one PadState (player 1) and hands it to the runtime (input.h); the Mac shell calls it
// every frame, the iPad shell from the controllers' change handlers. Included by one translation unit per app (app_ui.m, ios/app/app.m).
#pragma once
#import <GameController/GameController.h>
#include <math.h>
#include "input.h"

// Nintendo pads (Switch Pro, Joy-Con) arrive with the face buttons named like the labels on the pad: buttonA is the right button, as on the
// console. Xbox, PlayStation and generic pads name them by position (buttonA is the bottom one). Telling them apart keeps a Switch pad on
// the console's layout without a setting; the other pads follow the position rule unless the "xbox" layout option keeps their labels.
static inline BOOL pad_is_nintendo(GCController *c) {
    NSString *s = [NSString stringWithFormat:@"%@ %@", c.productCategory ?: @"", c.vendorName ?: @""].lowercaseString;
    return [s containsString:@"nintendo"] || [s containsString:@"switch"] || [s containsString:@"joy-con"] || [s containsString:@"joycon"];
}

static BOOL g_pad_by_position = YES;   // face buttons of non-Nintendo pads follow the console's positions (A right, B bottom, X top, Y left)

static int32_t pad_axis(float v) {   // 12 % dead zone
    if (v > -0.12f && v < 0.12f) return 0;
    int32_t r = (int32_t)(v * 32767.0f);
    return r > 32767 ? 32767 : r < -32767 ? -32767 : r;
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
}

// Event-driven shells (iPadOS): reports every change of this controller; a controller that went away is dropped from the next update.
__attribute__((unused)) static void pad_gc_bind(GCController *c) {
    c.extendedGamepad.valueChangedHandler = ^(GCExtendedGamepad *p, GCControllerElement *e) { pad_gc_update(); };
}
