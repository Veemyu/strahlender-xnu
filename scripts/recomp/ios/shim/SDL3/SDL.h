// iOS replacement for <SDL3/SDL.h>: only the types and constants that nvn_glue.c (key mapping) and the metal_ios.m generated from metal.m
// still mention. Window and input are provided by the app (scripts/recomp/ios/app); keys arrive through g_ext_buttons/g_ext_stick.
#pragma once
#include <stdbool.h>
#include <stdint.h>
#include <time.h>
#include <unistd.h>

typedef struct SDL_Window SDL_Window;
typedef union SDL_Event {
    uint32_t type;
    struct { uint32_t type; uint32_t scancode; } key;
} SDL_Event;

enum { SDL_EVENT_QUIT = 0x100, SDL_EVENT_KEY_DOWN = 0x300, SDL_EVENT_KEY_UP = 0x301 };
enum {
    SDL_SCANCODE_A = 4, SDL_SCANCODE_D = 7, SDL_SCANCODE_E = 8, SDL_SCANCODE_J = 13, SDL_SCANCODE_K = 14, SDL_SCANCODE_O = 18,
    SDL_SCANCODE_P = 19, SDL_SCANCODE_Q = 20, SDL_SCANCODE_S = 22, SDL_SCANCODE_W = 26, SDL_SCANCODE_X = 27, SDL_SCANCODE_Y = 28,
    SDL_SCANCODE_RETURN = 40, SDL_SCANCODE_BACKSPACE = 42, SDL_SCANCODE_SPACE = 44, SDL_SCANCODE_RIGHT = 79, SDL_SCANCODE_LEFT = 80,
    SDL_SCANCODE_DOWN = 81, SDL_SCANCODE_UP = 82,
};

static inline uint64_t SDL_GetTicksNS(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000000000ull + (uint64_t)ts.tv_nsec;
}
static inline uint64_t SDL_GetTicks(void) { return SDL_GetTicksNS() / 1000000ull; }
static inline void SDL_Delay(uint32_t ms) { usleep(ms * 1000u); }
