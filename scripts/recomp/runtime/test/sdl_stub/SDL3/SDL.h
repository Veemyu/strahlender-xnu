// Test-only SDL API surface. No real controllers or SDL implementation.
#pragma once
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>

typedef uint32_t SDL_JoystickID;
typedef unsigned long SDL_ThreadID;
typedef struct SDL_Gamepad { int connected, buttons[16], axes[6]; } SDL_Gamepad;
typedef enum {
    SDL_GAMEPAD_TYPE_STANDARD, SDL_GAMEPAD_TYPE_NINTENDO_SWITCH_JOYCON_LEFT,
    SDL_GAMEPAD_TYPE_NINTENDO_SWITCH_JOYCON_RIGHT, SDL_GAMEPAD_TYPE_NINTENDO_SWITCH_JOYCON_PAIR
} SDL_GamepadType;
SDL_GamepadType SDL_GetGamepadType(SDL_Gamepad *);
typedef enum {
    SDL_GAMEPAD_BUTTON_EAST, SDL_GAMEPAD_BUTTON_SOUTH, SDL_GAMEPAD_BUTTON_NORTH,
    SDL_GAMEPAD_BUTTON_WEST, SDL_GAMEPAD_BUTTON_LEFT_STICK, SDL_GAMEPAD_BUTTON_RIGHT_STICK,
    SDL_GAMEPAD_BUTTON_LEFT_SHOULDER, SDL_GAMEPAD_BUTTON_RIGHT_SHOULDER,
    SDL_GAMEPAD_BUTTON_START, SDL_GAMEPAD_BUTTON_BACK, SDL_GAMEPAD_BUTTON_DPAD_LEFT,
    SDL_GAMEPAD_BUTTON_DPAD_UP, SDL_GAMEPAD_BUTTON_DPAD_RIGHT, SDL_GAMEPAD_BUTTON_DPAD_DOWN
} SDL_GamepadButton;
typedef enum {
    SDL_GAMEPAD_AXIS_LEFTX, SDL_GAMEPAD_AXIS_LEFTY, SDL_GAMEPAD_AXIS_RIGHTX,
    SDL_GAMEPAD_AXIS_RIGHTY, SDL_GAMEPAD_AXIS_LEFT_TRIGGER, SDL_GAMEPAD_AXIS_RIGHT_TRIGGER
} SDL_GamepadAxis;

#define SDL_INIT_GAMEPAD 1
#define SDL_INIT_AUDIO 2
#define SDL_INIT_JOYSTICK 4
#define SDL_AUDIO_S16LE 0x8010
#define SDL_AUDIO_DEVICE_DEFAULT_PLAYBACK 0xffffffffu
typedef struct SDL_AudioStream SDL_AudioStream;
typedef struct { uint32_t format; int channels, freq; } SDL_AudioSpec;
typedef void (*SDL_AudioStreamCallback)(void *, SDL_AudioStream *, int, int);
SDL_AudioStream *SDL_OpenAudioDeviceStream(uint32_t, const SDL_AudioSpec *, SDL_AudioStreamCallback, void *);
bool SDL_ResumeAudioStreamDevice(SDL_AudioStream *);
bool SDL_PauseAudioStreamDevice(SDL_AudioStream *);
bool SDL_ClearAudioStream(SDL_AudioStream *);
bool SDL_SetAudioStreamGain(SDL_AudioStream *, float);
int SDL_GetAudioStreamQueued(SDL_AudioStream *);
bool SDL_PutAudioStreamData(SDL_AudioStream *, const void *, int);
void SDL_DestroyAudioStream(SDL_AudioStream *);
#define SDL_HINT_JOYSTICK_HIDAPI "hidapi"
#define SDL_HINT_JOYSTICK_HIDAPI_SWITCH "switch"
#define SDL_HINT_JOYSTICK_HIDAPI_PS4 "ps4"
#define SDL_HINT_JOYSTICK_HIDAPI_JOY_CONS "joycons"
#define SDL_HINT_JOYSTICK_HIDAPI_COMBINE_JOY_CONS "combine"
#define SDL_HINT_JOYSTICK_ALLOW_BACKGROUND_EVENTS "background"

bool SDL_IsMainThread(void);
SDL_ThreadID SDL_GetCurrentThreadID(void);
bool SDL_SetHint(const char *, const char *);
bool SDL_InitSubSystem(uint32_t);
void SDL_QuitSubSystem(uint32_t);
uint32_t SDL_WasInit(uint32_t);
void SDL_SetGamepadEventsEnabled(bool);
void SDL_SetJoystickEventsEnabled(bool);
void SDL_UpdateGamepads(void);
bool SDL_GetGamepadButton(SDL_Gamepad *, SDL_GamepadButton);
int16_t SDL_GetGamepadAxis(SDL_Gamepad *, SDL_GamepadAxis);
bool SDL_GamepadConnected(SDL_Gamepad *);
const char *SDL_GetGamepadName(SDL_Gamepad *);
const char *SDL_GetError(void);
void SDL_CloseGamepad(SDL_Gamepad *);
SDL_JoystickID *SDL_GetGamepads(int *);
SDL_JoystickID SDL_GetGamepadID(SDL_Gamepad *);
SDL_Gamepad *SDL_OpenGamepad(SDL_JoystickID);
#define SDL_free free
