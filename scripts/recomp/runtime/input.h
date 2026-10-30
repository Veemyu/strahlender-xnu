// Neutral controller interface: backends (pad_sdl.c on Linux/Windows, pad_gc.h for GameController on macOS/iPadOS) and the keyboard/touch of the
// front ends fill one PadState per source, the runtime (nvn_glue.c: Npad state for the game, swkbd_ui.c: on-screen keyboard) reads the merged
// result. Nothing here depends on a UI toolkit.
#pragma once
#include <stdint.h>

// Bit order of PadState.buttons and swkbd_ui_pad
enum { PB_A, PB_B, PB_X, PB_Y, PB_LSTICK, PB_RSTICK, PB_L, PB_R, PB_ZL, PB_ZR, PB_PLUS, PB_MINUS, PB_LEFT, PB_UP, PB_RIGHT, PB_DOWN };

typedef struct {
    uint64_t buttons;   // 1 << PB_*
    int32_t stick[4];   // lx, ly, rx, ry from -32767 to 32767, y positive up
} PadState;

typedef enum { INPUT_SRC_KEYBOARD, INPUT_SRC_TOUCH, INPUT_SRC_PAD, INPUT_SRC_COUNT } InputSource;

// A source reports its whole current state (any thread). Unchanged states are ignored.
void input_source_set(InputSource src, const PadState *s);
static inline void input_pad_set(const PadState *s) { input_source_set(INPUT_SRC_PAD, s); }

// What the game sees: all sources merged (buttons ORed, per stick axis the first source that moves it); empty while the on-screen keyboard
// is open, because it has the input then.
void input_current(PadState *out);

// Call regularly from the front end (every frame or a few times a second): hands the pad to the on-screen keyboard once when it opens.
void input_tick(void);

#if (defined(__linux__) || defined(_WIN32)) && !defined(BDSP_NVN_NONE)
#define PAD_SDL_AVAILABLE 1
// Linux front ends without an SDL event loop use the poller thread.
// Windows initializes and polls on the SDL window/event thread instead.
void pad_sdl_start(void);
#ifdef _WIN32
int pad_sdl_init_main(int combine_joycons);
// Current initialized mode, or -1 if initialization/rollback failed.
int pad_sdl_mode_main(void);
void pad_sdl_poll_main(void);
void pad_sdl_focus_main(int focused);
void pad_sdl_shutdown_main(void);
#endif
#endif
