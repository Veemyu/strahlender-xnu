// Real SDL DLL integration with virtual input/dummy audio, not hardware acceptance.
#include <SDL3/SDL.h>
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include "../audio_output.h"
#include "../input.h"

static PadState captured;

void input_source_set(InputSource source, const PadState *state) {
    assert(source == INPUT_SRC_PAD);
    captured = *state;
}

void input_tick(void) {}

static void require(bool ok) {
    if (!ok) {
        fprintf(stderr, "SDL integration probe failed: %s\n", SDL_GetError());
        exit(1);
    }
}

static int SDLCALL audio_worker(void *unused) {
    (void)unused;
    AudioOutput *output = audio_output_open(48000, 2);
    assert(output);
    const int16_t samples[960] = {0};
    audio_output_start(output);
    audio_output_write(output, samples, sizeof samples);
    audio_output_set_active(0);
    audio_output_set_active(1);
    SDL_Delay(50);
    audio_output_stop(output);
    audio_output_close(output);
    return 0;
}

static void single_joycon(const char *name, const char *type) {
    SDL_VirtualJoystickDesc descriptor;
    SDL_INIT_INTERFACE(&descriptor);
    descriptor.name = name;
    descriptor.type = SDL_JOYSTICK_TYPE_GAMEPAD;
    descriptor.vendor_id = 0x1209;
    descriptor.product_id = 0x0001;
    descriptor.naxes = SDL_GAMEPAD_AXIS_COUNT;
    descriptor.nbuttons = SDL_GAMEPAD_BUTTON_COUNT;
    descriptor.axis_mask = (1u << SDL_GAMEPAD_AXIS_COUNT) - 1;
    descriptor.button_mask = (1u << SDL_GAMEPAD_BUTTON_COUNT) - 1;
    SDL_JoystickID id = SDL_AttachVirtualJoystick(&descriptor);
    require(id != 0);
    SDL_GUID guid = SDL_GetJoystickGUIDForID(id);
    char text[33], mapping[1024];
    SDL_GUIDToString(guid, text, sizeof text);
    // SDL's HIDAPI mini mode supplies horizontal face buttons, left stick and Start on either half.
    snprintf(mapping, sizeof mapping,
             "%s,%s,a:b0,b:b1,x:b2,y:b3,start:b6,leftstick:b7,leftshoulder:b8,"
             "rightshoulder:b9,leftx:a0,lefty:a1,type:%s,", text, name, type);
    require(SDL_AddGamepadMapping(mapping) >= 0);
    SDL_Gamepad *gamepad = SDL_OpenGamepad(id);
    require(gamepad != NULL);
    SDL_GamepadType expected = !SDL_strcmp(type, "joyconleft")
        ? SDL_GAMEPAD_TYPE_NINTENDO_SWITCH_JOYCON_LEFT : SDL_GAMEPAD_TYPE_NINTENDO_SWITCH_JOYCON_RIGHT;
    assert(SDL_GetGamepadType(gamepad) == expected);
    SDL_Joystick *joystick = SDL_OpenJoystick(id);
    require(joystick != NULL);
    static const struct { int raw; int guest; } buttons[] = {
        {0, PB_B}, {1, PB_A}, {2, PB_Y}, {3, PB_X}, {6, PB_PLUS},
        {8, PB_L}, {9, PB_R}
    };
    for (size_t i = 0; i < sizeof buttons / sizeof *buttons; i++) {
        require(SDL_SetJoystickVirtualButton(joystick, buttons[i].raw, true));
        pad_sdl_poll_main();
        assert(captured.buttons == (1ull << buttons[i].guest));
        require(SDL_SetJoystickVirtualButton(joystick, buttons[i].raw, false));
        pad_sdl_poll_main();
        assert(!captured.buttons);
    }
    static const struct { int raw; int guest; } chords[] = {
        {6, PB_MINUS}, {8, PB_ZL}, {9, PB_ZR}
    };
    for (size_t i = 0; i < sizeof chords / sizeof *chords; i++) {
        require(SDL_SetJoystickVirtualButton(joystick, 7, true));
        pad_sdl_poll_main();
        assert(!captured.buttons);
        require(SDL_SetJoystickVirtualButton(joystick, chords[i].raw, true));
        for (int repeat = 0; repeat < 3; repeat++) {
            pad_sdl_poll_main();
            assert(captured.buttons == (1ull << chords[i].guest));
        }
        require(SDL_SetJoystickVirtualButton(joystick, 7, false));
        pad_sdl_poll_main();
        assert(!captured.buttons);
        require(SDL_SetJoystickVirtualButton(joystick, 7, true));
        pad_sdl_poll_main();
        assert(!captured.buttons);
        require(SDL_SetJoystickVirtualButton(joystick, chords[i].raw, false));
        pad_sdl_poll_main();
        require(SDL_SetJoystickVirtualButton(joystick, chords[i].raw, true));
        pad_sdl_poll_main();
        assert(captured.buttons == (1ull << chords[i].guest));
        require(SDL_SetJoystickVirtualButton(joystick, chords[i].raw, false));
        require(SDL_SetJoystickVirtualButton(joystick, 7, false));
        pad_sdl_poll_main();
        assert(!captured.buttons);
    }
    require(SDL_SetJoystickVirtualButton(joystick, 7, true));
    for (int axis = 0; axis < 2; axis++) {
        for (int sign = 0; sign < 2; sign++) {
            static const int direction[2][2] = {{PB_LEFT, PB_RIGHT}, {PB_UP, PB_DOWN}};
            require(SDL_SetJoystickVirtualAxis(joystick, axis, sign ? 32767 : -32768));
            pad_sdl_poll_main();
            assert(captured.buttons == (1ull << direction[axis][sign]));
            assert(!captured.stick[0] && !captured.stick[1]);
            require(SDL_SetJoystickVirtualAxis(joystick, axis, sign ? 15000 : -15000));
            pad_sdl_poll_main();
            assert(captured.buttons == (1ull << direction[axis][sign]));
            require(SDL_SetJoystickVirtualAxis(joystick, axis, sign ? 12000 : -12000));
            pad_sdl_poll_main();
            assert(!captured.buttons);
            require(SDL_SetJoystickVirtualAxis(joystick, axis, sign ? 15000 : -15000));
            pad_sdl_poll_main();
            assert(!captured.buttons);
            require(SDL_SetJoystickVirtualAxis(joystick, axis, 0));
        }
    }
    require(SDL_SetJoystickVirtualAxis(joystick, 0, 32767));
    pad_sdl_poll_main();
    assert(captured.buttons == (1ull << PB_RIGHT));
    require(SDL_SetJoystickVirtualButton(joystick, 7, false));
    pad_sdl_poll_main();
    assert(!captured.buttons && !captured.stick[0]);
    require(SDL_SetJoystickVirtualAxis(joystick, 0, 0));
    pad_sdl_poll_main();
    require(SDL_SetJoystickVirtualAxis(joystick, 0, -32768));
    require(SDL_SetJoystickVirtualAxis(joystick, 1, 32767));
    require(SDL_SetJoystickVirtualButton(joystick, 1, true));
    pad_sdl_poll_main();
    assert(captured.stick[0] == -32767 && captured.stick[1] == -32767);
    assert(captured.stick[2] == 0 && captured.stick[3] == 0);
    pad_sdl_focus_main(0);
    assert(!captured.buttons && !captured.stick[0] && !captured.stick[1]);
    pad_sdl_focus_main(1);
    pad_sdl_poll_main();
    assert(captured.buttons == (1ull << PB_A));
    require(SDL_SetJoystickVirtualButton(joystick, 7, true));
    require(SDL_SetJoystickVirtualButton(joystick, 6, true));
    pad_sdl_poll_main();
    uint64_t held = (1ull << PB_A) | (1ull << PB_MINUS) | (1ull << PB_LEFT) | (1ull << PB_DOWN);
    assert(captured.buttons == held);
    pad_sdl_focus_main(0);
    assert(!captured.buttons && !captured.stick[0]);
    pad_sdl_focus_main(1);
    pad_sdl_poll_main();
    assert(captured.buttons == held);
    SDL_CloseGamepad(gamepad);
    SDL_CloseJoystick(joystick);
    require(SDL_DetachVirtualJoystick(id));
    pad_sdl_poll_main();
    assert(!captured.buttons && !captured.stick[0] && !captured.stick[1]);
}

int bdsp_main(int argc, char **argv) {
    (void)argc; (void)argv;
    assert(SDL_GetVersion() == SDL_VERSION);
    require(SDL_SetHint(SDL_HINT_VIDEO_DRIVER, "dummy"));
    require(SDL_SetHint(SDL_HINT_AUDIO_DRIVER, "dummy"));
    require(SDL_SetHint(SDL_HINT_GAMECONTROLLER_IGNORE_DEVICES_EXCEPT, "0x1209/0x0001"));
    require(audio_output_init_main());
    require(SDL_Init(SDL_INIT_VIDEO));
    assert(SDL_IsMainThread());
    require(pad_sdl_init_main(1));

    SDL_VirtualJoystickDesc descriptor;
    SDL_INIT_INTERFACE(&descriptor);
    descriptor.name = "BDSP synthetic gamepad";
    descriptor.type = SDL_JOYSTICK_TYPE_GAMEPAD;
    descriptor.vendor_id = 0x1209;
    descriptor.product_id = 0x0001;
    descriptor.naxes = SDL_GAMEPAD_AXIS_COUNT;
    descriptor.nbuttons = SDL_GAMEPAD_BUTTON_COUNT;
    descriptor.axis_mask = (1u << SDL_GAMEPAD_AXIS_COUNT) - 1;
    descriptor.button_mask = (1u << SDL_GAMEPAD_BUTTON_COUNT) - 1;
    SDL_JoystickID id = SDL_AttachVirtualJoystick(&descriptor);
    require(id != 0);
    require(SDL_IsGamepad(id));
    SDL_Joystick *joystick = SDL_OpenJoystick(id);
    require(joystick != NULL);
    require(SDL_SetJoystickVirtualButton(joystick, SDL_GAMEPAD_BUTTON_EAST, true));
    require(SDL_SetJoystickVirtualAxis(joystick, SDL_GAMEPAD_AXIS_LEFTX, 32767));
    pad_sdl_poll_main();
    assert(captured.buttons & (1ull << PB_A));
    assert(captured.stick[0] == 32767);
    require(SDL_SetJoystickVirtualButton(joystick, SDL_GAMEPAD_BUTTON_LEFT_STICK, true));
    require(SDL_SetJoystickVirtualButton(joystick, SDL_GAMEPAD_BUTTON_START, true));
    pad_sdl_poll_main();
    assert(captured.buttons == ((1ull << PB_A) | (1ull << PB_LSTICK) | (1ull << PB_PLUS)));
    assert(captured.stick[0] == 32767);
    pad_sdl_focus_main(0);
    assert(!captured.buttons && !captured.stick[0]);
    pad_sdl_focus_main(1);
    pad_sdl_poll_main();
    assert(captured.buttons & (1ull << PB_A));
    SDL_CloseJoystick(joystick);
    require(SDL_DetachVirtualJoystick(id));
    pad_sdl_poll_main();
    assert(!captured.buttons && !captured.stick[0]);
    // Keep another joystick reference: startup-only mode hints must not change.
    require(SDL_InitSubSystem(SDL_INIT_JOYSTICK));
    assert(!pad_sdl_init_main(0));
    assert(pad_sdl_mode_main() == 1);
    SDL_QuitSubSystem(SDL_INIT_JOYSTICK);
    pad_sdl_focus_main(0);
    require(pad_sdl_init_main(0));
    assert(pad_sdl_mode_main() == 0);
    assert(!captured.buttons && !captured.stick[0]);
    pad_sdl_focus_main(1);
    require(pad_sdl_init_main(1));
    assert(pad_sdl_mode_main() == 1);
    pad_sdl_shutdown_main();
    require(pad_sdl_init_main(0));
    single_joycon("BDSP virtual left Joy-Con", "joyconleft");
    single_joycon("BDSP virtual right Joy-Con", "joyconright");
    single_joycon("BDSP virtual left Joy-Con reconnected", "joyconleft");
    for (int cycle = 0; cycle < 8; cycle++) {
        require(pad_sdl_init_main(cycle & 1));
        assert(pad_sdl_mode_main() == (cycle & 1));
        pad_sdl_poll_main();
        assert(!captured.buttons && !captured.stick[0]);
    }
    pad_sdl_shutdown_main();

    SDL_Thread *worker = SDL_CreateThread(audio_worker, "synthetic audio", NULL);
    require(worker != NULL);
    int status = -1;
    SDL_WaitThread(worker, &status);
    assert(status == 0);
    audio_output_shutdown_main();
    SDL_Quit();
    puts("Real SDL: virtual hotplug/buttons/stick/focus and dummy audio passed.");
    puts("Real SDL: virtual single Joy-Con L/R normalized controls and reconnect passed.");
    return 0;
}
