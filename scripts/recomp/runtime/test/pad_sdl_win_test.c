// Native controller lifecycle probe with fake SDL devices, not a hardware test.
#include <assert.h>
#include <string.h>
#include "../pad_sdl.c"

static SDL_Gamepad device = {1, {0}, {0}};
static int initialized, init_count, opens, closes, combination = -1, hint_failure;
static int main_thread = 1, init_failures, foreign_owner, open_failure, enumerate_failure;
static SDL_ThreadID thread_id = 1;
static PadState observed;
static SDL_GamepadType kind = SDL_GAMEPAD_TYPE_STANDARD;

bool SDL_IsMainThread(void) { return main_thread != 0; }
SDL_GamepadType SDL_GetGamepadType(SDL_Gamepad *pad) { (void)pad; return kind; }
SDL_ThreadID SDL_GetCurrentThreadID(void) { return thread_id; }
uint32_t SDL_WasInit(uint32_t flags) {
    return (initialized || foreign_owner) ? flags : 0;
}
void SDL_SetGamepadEventsEnabled(bool enabled) { assert(!enabled); }
void SDL_SetJoystickEventsEnabled(bool enabled) { assert(!enabled); }
bool SDL_SetHint(const char *name, const char *value) {
    if (hint_failure) { hint_failure--; return false; }
    if (!strcmp(name, SDL_HINT_JOYSTICK_HIDAPI_COMBINE_JOY_CONS)) {
        assert(!initialized);
        combination = !strcmp(value, "1");
    }
    return true;
}
bool SDL_InitSubSystem(uint32_t flags) {
    assert(flags == SDL_INIT_GAMEPAD && combination >= 0);
    if (init_failures) { init_failures--; return false; }
    initialized = 1;
    init_count++;
    return true;
}
void SDL_QuitSubSystem(uint32_t flags) { assert(flags == SDL_INIT_GAMEPAD); initialized = 0; }
void SDL_UpdateGamepads(void) { assert(initialized); }
bool SDL_GetGamepadButton(SDL_Gamepad *pad, SDL_GamepadButton button) { return pad->buttons[button] != 0; }
int16_t SDL_GetGamepadAxis(SDL_Gamepad *pad, SDL_GamepadAxis axis) { return (int16_t)pad->axes[axis]; }
bool SDL_GamepadConnected(SDL_Gamepad *pad) { return pad->connected != 0; }
const char *SDL_GetGamepadName(SDL_Gamepad *pad) { (void)pad; return "synthetic pad"; }
const char *SDL_GetError(void) { return "synthetic SDL error"; }
void SDL_CloseGamepad(SDL_Gamepad *pad) { assert(pad == &device); closes++; }
SDL_JoystickID *SDL_GetGamepads(int *count) {
    if (enumerate_failure) { *count = 0; return NULL; }
    *count = device.connected ? 1 : 0;
    SDL_JoystickID *ids = malloc(sizeof *ids);
    assert(ids);
    *ids = 7;
    return ids;
}
SDL_JoystickID SDL_GetGamepadID(SDL_Gamepad *pad) { assert(pad == &device); return 7; }
SDL_Gamepad *SDL_OpenGamepad(SDL_JoystickID id) {
    assert(id == 7);
    if (open_failure) return NULL;
    opens++;
    return &device;
}
void input_source_set(InputSource source, const PadState *state) {
    assert(source == INPUT_SRC_PAD);
    observed = *state;
}
void input_tick(void) {}

int main(void) {
    pad_sdl_start();
    assert(init_count == 0);
    assert(pad_sdl_init_main(1));
    assert(combination == 1 && opens == 1 && init_count == 1);
    assert(pad_sdl_init_main(1));
    assert(opens == 1 && init_count == 1);

    device.buttons[SDL_GAMEPAD_BUTTON_EAST] = 1;
    device.axes[SDL_GAMEPAD_AXIS_LEFT_TRIGGER] = 32767;
    device.axes[SDL_GAMEPAD_AXIS_LEFTX] = 32767;
    device.axes[SDL_GAMEPAD_AXIS_LEFTY] = -32768;
    pad_sdl_poll_main();
    assert(observed.buttons == ((1ull << PB_A) | (1ull << PB_ZL)));
    assert(observed.stick[0] == 32767 && observed.stick[1] == 32767);
    assert(observed.stick[2] == 0 && observed.stick[3] == 0);
    assert(opens == 1);
    kind = SDL_GAMEPAD_TYPE_NINTENDO_SWITCH_JOYCON_PAIR;
    device.buttons[SDL_GAMEPAD_BUTTON_LEFT_STICK] = 1;
    device.buttons[SDL_GAMEPAD_BUTTON_START] = 1;
    pad_sdl_poll_main();
    assert(observed.buttons == ((1ull << PB_A) | (1ull << PB_ZL) |
                                (1ull << PB_LSTICK) | (1ull << PB_PLUS)));
    assert(observed.stick[0] == 32767 && observed.stick[1] == 32767);
    device.buttons[SDL_GAMEPAD_BUTTON_LEFT_STICK] = 0;
    device.buttons[SDL_GAMEPAD_BUTTON_START] = 0;

    pad_sdl_focus_main(0);
    assert(observed.buttons == 0);
    pad_sdl_poll_main();
    assert(observed.buttons == 0 && observed.stick[0] == 0);
    pad_sdl_focus_main(1);
    pad_sdl_poll_main();
    assert(observed.buttons & (1ull << PB_A));
    device.connected = 0;
    pad_sdl_poll_main();
    assert(observed.buttons == 0 && closes == 1);
    device.connected = 1;
    pad_sdl_poll_main();
    assert(opens == 2);

    assert(pad_sdl_init_main(0));
    assert(combination == 0 && closes == 2 && opens == 3 && init_count == 2);
    assert(pad_sdl_mode_main() == 0);
    assert(!pad_sdl_init_main(-1) && pad_sdl_mode_main() == 0);
    thread_id = 2;
    assert(!pad_sdl_init_main(1));
    thread_id = 1;
    assert(pad_sdl_mode_main() == 0);
    pad_sdl_focus_main(0);
    assert(pad_sdl_init_main(1));
    pad_sdl_poll_main();
    assert(observed.buttons == 0 && observed.stick[0] == 0);
    hint_failure = 1;
    assert(!pad_sdl_init_main(0) && pad_sdl_mode_main() == 1);
    init_failures = 1;
    assert(!pad_sdl_init_main(0) && pad_sdl_mode_main() == 1);
    foreign_owner = 1;
    assert(!pad_sdl_init_main(0) && pad_sdl_mode_main() == 1);
    foreign_owner = 0;
    init_failures = 2;
    assert(!pad_sdl_init_main(0) && pad_sdl_mode_main() == -1 && !initialized);
    assert(pad_sdl_init_main(0));
    pad_sdl_focus_main(1);
    enumerate_failure = 1;
    pad_sdl_poll_main();
    enumerate_failure = 0;
    device.connected = 0;
    pad_sdl_poll_main();
    device.connected = 1;
    open_failure = 1;
    pad_sdl_poll_main();
    assert(observed.buttons == 0);
    open_failure = 0;
    pad_sdl_poll_main();
    assert(observed.buttons & (1ull << PB_A));
    pad_sdl_shutdown_main();
    assert(!initialized && observed.buttons == 0 && pad_sdl_mode_main() == -1);
    main_thread = 0;
    assert(!pad_sdl_init_main(1));
    main_thread = 1;
    hint_failure = 1;
    assert(!pad_sdl_init_main(1) && !initialized);
    puts("Windows controller lifecycle probe passed (synthetic SDL, no hardware).");
    return 0;
}
