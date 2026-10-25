// Neutral controller interface: backends (pad_sdl.c on Linux/Windows, GameController in the Apple shells) fill a PadState, the runtime
// (nvn_glue.c: Npad state for the game, swkbd_ui.c: on-screen keyboard) reads it. Nothing here depends on a UI toolkit.
#pragma once
#include <stdint.h>

// Bit order of PadState.buttons, g_ext_buttons and swkbd_ui_pad
enum { PB_A, PB_B, PB_X, PB_Y, PB_LSTICK, PB_RSTICK, PB_L, PB_R, PB_ZL, PB_ZR, PB_PLUS, PB_MINUS, PB_LEFT, PB_UP, PB_RIGHT, PB_DOWN };

typedef struct {
    uint64_t buttons;   // 1 << PB_*
    int32_t stick[4];   // lx, ly, rx, ry from -32767 to 32767, y positive up
} PadState;

// Called by a backend whenever its state may have changed (any thread). Routes to the game, or to the on-screen keyboard while it is open.
void input_pad_set(const PadState *s);

#if (defined(__linux__) || defined(_WIN32)) && !defined(BDSP_NVN_NONE)
#define PAD_SDL_AVAILABLE 1
// SDL gamepad backend: starts once (idempotent), its own thread, needs no window and no event loop.
void pad_sdl_start(void);
#endif
