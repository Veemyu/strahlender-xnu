// Gamepads through SDL3 (Linux, Windows): Switch Pro, Joy-Con, DualShock/DualSense, Xbox and others, over USB or Bluetooth.
// Only the joystick/gamepad subsystem is used, no window and no SDL event loop, so every front end (Qt, SDL window, a later toolkit)
// gets the same controllers. A poller thread merges all connected pads into one PadState (player 1) and hands it to input_pad_set.
// BDSP_PAD_LOG=1 logs connect/disconnect and every button change.
#if (defined(__linux__) || defined(_WIN32)) && !defined(BDSP_NVN_NONE)
#include <SDL3/SDL.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include "input.h"

#define DEADZONE 4000       // about 12 % of the range, as on the Mac
#define TRIGGER_ON 10000    // analog trigger counted as pressed (the Pro Controller's ZL/ZR report 0 or full)

static int pad_log;

// Switch layout by position: the right button is A, the lower one B, the upper X, the left Y (whatever the labels on the pad say).
static const struct { SDL_GamepadButton sdl; int pb; } k_buttons[] = {
    {SDL_GAMEPAD_BUTTON_EAST, PB_A},          {SDL_GAMEPAD_BUTTON_SOUTH, PB_B},
    {SDL_GAMEPAD_BUTTON_NORTH, PB_X},         {SDL_GAMEPAD_BUTTON_WEST, PB_Y},
    {SDL_GAMEPAD_BUTTON_LEFT_STICK, PB_LSTICK}, {SDL_GAMEPAD_BUTTON_RIGHT_STICK, PB_RSTICK},
    {SDL_GAMEPAD_BUTTON_LEFT_SHOULDER, PB_L}, {SDL_GAMEPAD_BUTTON_RIGHT_SHOULDER, PB_R},
    {SDL_GAMEPAD_BUTTON_START, PB_PLUS},      {SDL_GAMEPAD_BUTTON_BACK, PB_MINUS},
    {SDL_GAMEPAD_BUTTON_DPAD_LEFT, PB_LEFT},  {SDL_GAMEPAD_BUTTON_DPAD_UP, PB_UP},
    {SDL_GAMEPAD_BUTTON_DPAD_RIGHT, PB_RIGHT}, {SDL_GAMEPAD_BUTTON_DPAD_DOWN, PB_DOWN},
};

static int32_t stick_axis(SDL_Gamepad *g, SDL_GamepadAxis a, int up_positive) {
    int v = SDL_GetGamepadAxis(g, a);
    if (v > -DEADZONE && v < DEADZONE) return 0;
    if (v < -32767) v = -32767;
    return up_positive ? -v : v;   // SDL: y grows downward
}

#define MAX_PADS 8
static SDL_Gamepad *pads[MAX_PADS];

static void poll_pads(PadState *out) {
    *out = (PadState){0};
    for (int i = 0; i < MAX_PADS; i++) {
        SDL_Gamepad *g = pads[i];
        if (!g) continue;
        for (size_t k = 0; k < sizeof k_buttons / sizeof *k_buttons; k++)
            if (SDL_GetGamepadButton(g, k_buttons[k].sdl)) out->buttons |= 1ull << k_buttons[k].pb;
        if (SDL_GetGamepadAxis(g, SDL_GAMEPAD_AXIS_LEFT_TRIGGER) > TRIGGER_ON) out->buttons |= 1ull << PB_ZL;
        if (SDL_GetGamepadAxis(g, SDL_GAMEPAD_AXIS_RIGHT_TRIGGER) > TRIGGER_ON) out->buttons |= 1ull << PB_ZR;
        static const SDL_GamepadAxis ax[4] = {SDL_GAMEPAD_AXIS_LEFTX, SDL_GAMEPAD_AXIS_LEFTY, SDL_GAMEPAD_AXIS_RIGHTX, SDL_GAMEPAD_AXIS_RIGHTY};
        for (int a = 0; a < 4; a++) {
            int32_t v = stick_axis(g, ax[a], a & 1);
            if (v && !out->stick[a]) out->stick[a] = v;   // first pad that moves the stick wins
        }
    }
}

// Close pads that went away, open pads that appeared.
static void hotplug(void) {
    for (int i = 0; i < MAX_PADS; i++)
        if (pads[i] && !SDL_GamepadConnected(pads[i])) {
            if (pad_log) fprintf(stderr, "[pad] disconnected: %s\n", SDL_GetGamepadName(pads[i]));
            SDL_CloseGamepad(pads[i]);
            pads[i] = NULL;
        }
    int n = 0;
    SDL_JoystickID *ids = SDL_GetGamepads(&n);
    for (int i = 0; ids && i < n; i++) {
        int slot = -1, known = 0;
        for (int k = 0; k < MAX_PADS; k++) {
            if (pads[k] && SDL_GetGamepadID(pads[k]) == ids[i]) known = 1;
            if (!pads[k] && slot < 0) slot = k;
        }
        if (known || slot < 0) continue;
        pads[slot] = SDL_OpenGamepad(ids[i]);
        if (pad_log) fprintf(stderr, "[pad] connected: %s\n", pads[slot] ? SDL_GetGamepadName(pads[slot]) : SDL_GetError());
    }
    SDL_free(ids);
}

static void *pad_thread(void *arg) {
    (void)arg;
    uint64_t last_b = ~0ull;
    int32_t last_s[4] = {0, 0, 0, 0};
    for (;;) {
        SDL_UpdateGamepads();   // events are off, state and the device list are refreshed here
        hotplug();
        PadState s;
        poll_pads(&s);
        input_pad_set(&s);
        input_tick();
        if (pad_log) {
            // log on a change of the buttons or of a stick by more than a quarter of its range (names for the manual check of a pad)
            int moved = 0;
            for (int a = 0; a < 4; a++) if (abs(s.stick[a] - last_s[a]) > 8000) moved = 1;
            if (s.buttons != last_b || moved) {
                static const char *const names[16] = {"A", "B", "X", "Y", "LSTICK", "RSTICK", "L", "R", "ZL", "ZR", "PLUS", "MINUS", "LEFT", "UP", "RIGHT", "DOWN"};
                char line[160] = "";
                for (int i = 0; i < 16; i++) if (s.buttons & (1ull << i)) { strcat(line, names[i]); strcat(line, " "); }
                fprintf(stderr, "[pad] buttons %#llx %s| L(%d,%d) R(%d,%d)\n", (unsigned long long)s.buttons, line, s.stick[0], s.stick[1], s.stick[2], s.stick[3]);
                last_b = s.buttons;
                for (int a = 0; a < 4; a++) last_s[a] = s.stick[a];
            }
        }
        struct timespec ts = {0, 4 * 1000 * 1000};   // 250 Hz
        nanosleep(&ts, NULL);
    }
    return NULL;
}

static pthread_once_t start_once = PTHREAD_ONCE_INIT;

static void start(void) {
    const char *v = getenv("BDSP_PAD_LOG");
    pad_log = v && atoi(v);
    SDL_SetHint(SDL_HINT_JOYSTICK_ALLOW_BACKGROUND_EVENTS, "1");
    SDL_SetHint(SDL_HINT_JOYSTICK_THREAD, "1");   // HIDAPI pads (Switch, PlayStation) are read by SDL's own thread
    if (!SDL_Init(SDL_INIT_GAMEPAD)) { fprintf(stderr, "[pad] SDL gamepad init failed: %s\n", SDL_GetError()); return; }
    SDL_SetGamepadEventsEnabled(false);    // nobody drains the queue (Qt has no SDL loop); state is polled instead
    SDL_SetJoystickEventsEnabled(false);
    pthread_t t;
    if (pthread_create(&t, NULL, pad_thread, NULL) == 0) pthread_detach(t);
}

void pad_sdl_start(void) { pthread_once(&start_once, start); }
#endif
