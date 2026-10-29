// Gamepads through SDL3 (Linux, Windows): Switch Pro, Joy-Con, DualShock/DualSense, Xbox and others, over USB or Bluetooth.
// Linux uses a poller thread; Windows uses the SDL window/event thread.
// All connected pads merge into one PadState (player 1).
// BDSP_PAD_LOG=1 logs connect/disconnect and every button change.
#if (defined(__linux__) || defined(_WIN32)) && !defined(BDSP_NVN_NONE)
#include <SDL3/SDL.h>
#ifndef _WIN32
#include <pthread.h>
#include <time.h>
#endif
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "input.h"
#include "runtime_paths.h"
#ifdef __linux__
#include <dirent.h>
#include <unistd.h>
#endif

#define DEADZONE 1300       // 4 % of the range, scaled out below: a console passes sticks raw and the game has its own dead zone
#define TRIGGER_ON 10000    // analog trigger counted as pressed (the Pro Controller's ZL/ZR report 0 or full)

static int pad_log;
#ifdef _WIN32
static SDL_ThreadID pad_owner;
static int pad_ready, pad_focused = 1, pad_combined;
#endif

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
    int m = v < 0 ? -v : v;
    if (m <= DEADZONE) return 0;
    int32_t o = (int32_t)((int64_t)(m - DEADZONE) * 32767 / (32767 - DEADZONE));
    if (o > 32767) o = 32767;
    if (v < 0) o = -o;
    return up_positive ? -o : o;   // SDL: y grows downward
}

#define MAX_PADS 8
static SDL_Gamepad *pads[MAX_PADS];
static struct { int active, block_stick; uint64_t blocked, directions; } layers[MAX_PADS];

static void poll_pad(int slot, PadState *out) {
    SDL_Gamepad *g = pads[slot];
    SDL_GamepadType type = SDL_GetGamepadType(g);
    int single = type == SDL_GAMEPAD_TYPE_NINTENDO_SWITCH_JOYCON_LEFT ||
                 type == SDL_GAMEPAD_TYPE_NINTENDO_SWITCH_JOYCON_RIGHT;
    int layer = single && SDL_GetGamepadButton(g, SDL_GAMEPAD_BUTTON_LEFT_STICK);
    uint64_t buttons = 0;
    for (size_t k = 0; k < sizeof k_buttons / sizeof *k_buttons; k++)
        if (SDL_GetGamepadButton(g, k_buttons[k].sdl)) buttons |= 1ull << k_buttons[k].pb;
    static const SDL_GamepadAxis ax[4] = {
        SDL_GAMEPAD_AXIS_LEFTX, SDL_GAMEPAD_AXIS_LEFTY, SDL_GAMEPAD_AXIS_RIGHTX, SDL_GAMEPAD_AXIS_RIGHTY
    };
    for (int a = 0; a < 4; a++) out->stick[a] = stick_axis(g, ax[a], a & 1);
    if (single) {
        const uint64_t shifted = (1ull << PB_PLUS) | (1ull << PB_L) | (1ull << PB_R);
        // Releasing the modifier first must not turn a held chord into a normal button/movement.
        if (layers[slot].active && !layer) {
            layers[slot].blocked |= buttons & shifted;
            layers[slot].block_stick = out->stick[0] || out->stick[1];
        }
        layers[slot].blocked &= buttons;
        buttons &= ~(layers[slot].blocked | (1ull << PB_LSTICK));
        if (!out->stick[0] && !out->stick[1]) layers[slot].block_stick = 0;
        if (layer) {
            if (buttons & (1ull << PB_PLUS)) buttons |= 1ull << PB_MINUS;
            if (buttons & (1ull << PB_L)) buttons |= 1ull << PB_ZL;
            if (buttons & (1ull << PB_R)) buttons |= 1ull << PB_ZR;
            buttons &= ~shifted;
            uint64_t directions = 0;
            static const int direction[2][2] = {{PB_LEFT, PB_RIGHT}, {PB_DOWN, PB_UP}};
            for (int axis = 0; axis < 2; axis++) {
                for (int sign = 0; sign < 2; sign++) {
                    uint64_t bit = 1ull << direction[axis][sign];
                    int threshold = (layers[slot].directions & bit) ? 12000 : 16000;
                    if ((sign ? out->stick[axis] : -out->stick[axis]) > threshold) directions |= bit;
                }
            }
            layers[slot].directions = directions;
            buttons |= directions;
        } else {
            layers[slot].directions = 0;
        }
        if (layer || layers[slot].block_stick) out->stick[0] = out->stick[1] = 0;
        layers[slot].active = layer;
    } else {
        memset(&layers[slot], 0, sizeof layers[slot]);
    }
    if (SDL_GetGamepadAxis(g, SDL_GAMEPAD_AXIS_LEFT_TRIGGER) > TRIGGER_ON) buttons |= 1ull << PB_ZL;
    if (SDL_GetGamepadAxis(g, SDL_GAMEPAD_AXIS_RIGHT_TRIGGER) > TRIGGER_ON) buttons |= 1ull << PB_ZR;
    out->buttons = buttons;
}

static void poll_pads(PadState *out) {
    *out = (PadState){0};
    for (int i = 0; i < MAX_PADS; i++) {
        SDL_Gamepad *g = pads[i];
        if (!g) continue;
        PadState state = {0};
        poll_pad(i, &state);
        out->buttons |= state.buttons;
        for (int a = 0; a < 4; a++) {
            int32_t v = state.stick[a];
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
            memset(&layers[i], 0, sizeof layers[i]);
        }
    int n = 0;
    SDL_JoystickID *ids = SDL_GetGamepads(&n);
    if (!ids) {
        fprintf(stderr, "[pad] cannot enumerate controllers: %s\n", SDL_GetError());
        return;
    }
    for (int i = 0; ids && i < n; i++) {
        int slot = -1, known = 0;
        for (int k = 0; k < MAX_PADS; k++) {
            if (pads[k] && SDL_GetGamepadID(pads[k]) == ids[i]) known = 1;
            if (!pads[k] && slot < 0) slot = k;
        }
        if (known || slot < 0) continue;
        pads[slot] = SDL_OpenGamepad(ids[i]);
        memset(&layers[slot], 0, sizeof layers[slot]);
        if (!pads[slot]) fprintf(stderr, "[pad] cannot open controller: %s\n", SDL_GetError());
        else if (pad_log) fprintf(stderr, "[pad] connected: %s\n", SDL_GetGamepadName(pads[slot]));
    }
    SDL_free(ids);
}

static void log_state(const PadState *s) {
    if (!pad_log) return;
    static uint64_t last_b = ~0ull;
    static int32_t last_s[4];
    int moved = 0;
    for (int a = 0; a < 4; a++) if (abs(s->stick[a] - last_s[a]) > 8000) moved = 1;
    if (s->buttons != last_b || moved) {
        static const char *const names[16] = {"A", "B", "X", "Y", "LSTICK", "RSTICK", "L", "R", "ZL", "ZR", "PLUS", "MINUS", "LEFT", "UP", "RIGHT", "DOWN"};
        char line[160] = "";
        size_t used = 0;
        for (int i = 0; i < 16; i++) if (s->buttons & (1ull << i)) {
            int n = snprintf(line + used, sizeof line - used, "%s ", names[i]);
            if (n < 0 || (size_t)n >= sizeof line - used) break;
            used += (size_t)n;
        }
        fprintf(stderr, "[pad] buttons %#llx %s| L(%d,%d) R(%d,%d)\n", (unsigned long long)s->buttons, line, s->stick[0], s->stick[1], s->stick[2], s->stick[3]);
        last_b = s->buttons;
        memcpy(last_s, s->stick, sizeof last_s);
    }
}

#ifdef __linux__
// A Nintendo or Sony pad is connected, but SDL sees no gamepad and the pad's /dev/hidraw node is not readable: say once what to do.
// (Most pads need nothing: the kernel's own drivers expose them as input devices. The rules file adds hidraw access for SDL's own drivers.)
static void hint_missing_access(void) {
    DIR *d = opendir("/sys/class/hidraw");
    if (!d) return;
    struct dirent *e;
    while ((e = readdir(d))) {
        if (strncmp(e->d_name, "hidraw", 6)) continue;
        char path[160], line[200];
        snprintf(path, sizeof path, "/sys/class/hidraw/%s/device/uevent", e->d_name);
        FILE *f = fopen(path, "r");
        int ours = 0;
        while (f && fgets(line, sizeof line, f))
            if (!strncmp(line, "HID_ID=", 7) && (strstr(line, ":0000057E:") || strstr(line, ":0000054C:"))) ours = 1;
        if (f) fclose(f);
        snprintf(path, sizeof path, "/dev/%s", e->d_name);
        if (ours && access(path, R_OK) != 0) {
            fprintf(stderr, "[pad] A Nintendo or Sony controller is connected, but %s is not readable for you. Install udev/70-bdsp-controllers.rules "
                            "(from the app folder or scripts/recomp/rt-bdsp/app/linux/udev/; the commands are in the file) and reconnect the pad.\n", path);
            break;
        }
    }
    closedir(d);
}
#endif

#ifndef _WIN32
static void *pad_thread(void *arg) {
    (void)arg;
#ifdef __linux__
    int ticks = 0;
#endif
    for (;;) {
        SDL_UpdateGamepads();   // events are off, state and the device list are refreshed here
        hotplug();
        PadState s;
        poll_pads(&s);
        input_pad_set(&s);
        input_tick();
#ifdef __linux__
        if (++ticks == 750) {   // 3 s after the start
            int n = 0;
            SDL_free(SDL_GetGamepads(&n));
            if (n == 0) hint_missing_access();
        }
#endif
        log_state(&s);
        struct timespec ts = {0, 4 * 1000 * 1000};   // 250 Hz
        nanosleep(&ts, NULL);
    }
    return NULL;
}

static pthread_once_t start_once = PTHREAD_ONCE_INIT;

static void start(void) {
    const char *v = getenv("BDSP_PAD_LOG");
    pad_log = v && atoi(v);
    int combine = bdsp_joycon_mode();
    if (combine < 0) return;
    if (!SDL_SetHint(SDL_HINT_JOYSTICK_HIDAPI_COMBINE_JOY_CONS, combine ? "1" : "0")) {
        fprintf(stderr, "[pad] cannot configure Joy-Con mode: %s\n", SDL_GetError());
        return;
    }
    SDL_SetHint(SDL_HINT_JOYSTICK_ALLOW_BACKGROUND_EVENTS, "1");
    SDL_SetHint(SDL_HINT_JOYSTICK_THREAD, "1");   // HIDAPI pads (Switch, PlayStation) are read by SDL's own thread
    if (!SDL_Init(SDL_INIT_GAMEPAD)) { fprintf(stderr, "[pad] SDL gamepad init failed: %s\n", SDL_GetError()); return; }
    SDL_SetGamepadEventsEnabled(false);    // nobody drains the queue (Qt has no SDL loop); state is polled instead
    SDL_SetJoystickEventsEnabled(false);
    pthread_t t;
    int rc = pthread_create(&t, NULL, pad_thread, NULL);
    if (rc) {
        fprintf(stderr, "[pad] cannot start polling thread: %s\n", strerror(rc));
        SDL_QuitSubSystem(SDL_INIT_GAMEPAD);
        return;
    }
    pthread_detach(t);
}

void pad_sdl_start(void) { pthread_once(&start_once, start); }
#else
static int on_owner(void) {
    if (pad_ready && SDL_GetCurrentThreadID() == pad_owner) return 1;
    fprintf(stderr, "[pad] controller operation requires the initialized SDL window thread\n");
    return 0;
}

void pad_sdl_shutdown_main(void) {
    if (!pad_ready) return;
    if (!on_owner()) return;
    for (int i = 0; i < MAX_PADS; i++) {
        if (pads[i]) SDL_CloseGamepad(pads[i]);
        pads[i] = NULL;
        memset(&layers[i], 0, sizeof layers[i]);
    }
    PadState empty = {0};
    input_pad_set(&empty);
    SDL_QuitSubSystem(SDL_INIT_GAMEPAD);
    pad_ready = 0;
}

static int acquire_main(int combine_joycons) {
    if (!SDL_InitSubSystem(SDL_INIT_GAMEPAD)) {
        fprintf(stderr, "[pad] SDL gamepad init failed: %s\n", SDL_GetError());
        return 0;
    }
    pad_combined = combine_joycons;
    pad_ready = 1;
    SDL_SetGamepadEventsEnabled(false);
    SDL_SetJoystickEventsEnabled(false);
    hotplug();
    return 1;
}

static int initialize_main(int combine_joycons) {
    pad_owner = SDL_GetCurrentThreadID();
    const char *v = getenv("BDSP_PAD_LOG");
    pad_log = v && atoi(v);
    if (!SDL_SetHint(SDL_HINT_JOYSTICK_HIDAPI, "1") ||
        !SDL_SetHint(SDL_HINT_JOYSTICK_HIDAPI_SWITCH, "1") ||
        !SDL_SetHint(SDL_HINT_JOYSTICK_HIDAPI_PS4, "1") ||
        !SDL_SetHint(SDL_HINT_JOYSTICK_HIDAPI_JOY_CONS, "1") ||
        !SDL_SetHint(SDL_HINT_JOYSTICK_HIDAPI_COMBINE_JOY_CONS, combine_joycons ? "1" : "0") ||
        !SDL_SetHint(SDL_HINT_JOYSTICK_ALLOW_BACKGROUND_EVENTS, "0")) {
        fprintf(stderr, "[pad] cannot configure Windows controller backends: %s\n", SDL_GetError());
        return 0;
    }
    return acquire_main(combine_joycons);
}

int pad_sdl_mode_main(void) {
    return pad_ready && on_owner() ? pad_combined : -1;
}

int pad_sdl_init_main(int combine_joycons) {
    if ((combine_joycons != 0 && combine_joycons != 1) || !SDL_IsMainThread()) {
        fprintf(stderr, "[pad] controller mode must be 0/1 on the SDL main thread\n");
        return 0;
    }
    if (pad_ready && !on_owner()) return 0;
    if (pad_ready && pad_combined == combine_joycons) return 1;
    int previous = pad_ready ? pad_combined : -1;
    if (pad_ready) pad_sdl_shutdown_main();
    // Another SDL client retaining joystick ownership prevents applying startup-only hints.
    if (SDL_WasInit(SDL_INIT_JOYSTICK | SDL_INIT_GAMEPAD)) {
        fprintf(stderr, "[pad] controller reinitialization blocked by another SDL joystick owner\n");
        if (previous >= 0 && !acquire_main(previous))
            fprintf(stderr, "[pad] previous controller mode could not be restored; keyboard remains available\n");
        return 0;
    }
    if (initialize_main(combine_joycons)) return 1;
    if (previous >= 0 && !initialize_main(previous))
        fprintf(stderr, "[pad] previous controller mode could not be restored; keyboard remains available\n");
    return 0;
}

void pad_sdl_focus_main(int focused) {
    if (!on_owner()) return;
    pad_focused = !!focused;
    if (!pad_focused) {
        memset(layers, 0, sizeof layers);
        PadState empty = {0};
        input_pad_set(&empty);
    }
}

void pad_sdl_poll_main(void) {
    if (!pad_ready) return;
    if (!on_owner()) return;
    SDL_UpdateGamepads();
    hotplug();
    PadState state = {0};
    if (pad_focused) poll_pads(&state);
    log_state(&state);
    input_pad_set(&state);
    input_tick();
}

// Guest input reads never initialize SDL or create a second polling thread.
void pad_sdl_start(void) {}
#endif
#endif
