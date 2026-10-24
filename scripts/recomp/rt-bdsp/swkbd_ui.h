// On-screen software keyboard in the style of the Switch's own, drawn from the layout files of the user's firmware
// (BDSP_FIRMWARE_DATA, see lyt.h / lyt_scene.h). This file is the platform-independent part: state, key logic, input, scene.
// The renderer (nvn/swkbd_overlay.m) draws swkbd_ui_scene(); the app shells feed swkbd_ui_pad / _touch / _text / _key.
// Own code; nothing from the firmware is stored in the repository.
#ifndef SWKBD_UI_H
#define SWKBD_UI_H

#include <stdint.h>

#include "lyt_scene.h"

#define SWKBD_CANVAS_W 1280
#define SWKBD_CANVAS_H 720

typedef struct {
    uint32_t mode;                   // KeyboardMode: 1 numeric, everything else the letter keyboard
    char header[256], sub[256], guide[512], initial[1024];   // utf-8
    int minlen, maxlen;              // in characters; maxlen <= 0: no limit
    int password;
    int multiline;
} SwkbdParams;

typedef struct {
    // Enter was pressed and the text is long enough. The backend answers with swkbd_ui_resolve (any thread, also from inside the callback).
    void (*submit)(void *user, const char *text);
    // The user cancelled; the keyboard has already closed.
    void (*cancel)(void *user);
} SwkbdCallbacks;

// A renderer calls this once (swkbd_overlay.m does); without one swkbd_ui_available stays 0, because an open keyboard would be
// invisible and block the game.
void swkbd_ui_set_display(int on);
// The renderer's wake-up: called (without the lock held) each time the keyboard opens, so it can start what keeps the picture alive while the game is stopped in the keyboard call.
void swkbd_ui_set_wake(void (*fn)(void));
// True when the keyboard can be shown: with the firmware layouts (BDSP_FIRMWARE_DATA), otherwise as a simple keyboard of our own
// (BDSP_SWKBD_SIMPLE=1 forces the simple one).
int swkbd_ui_available(void);
int swkbd_ui_open(const SwkbdParams *p, SwkbdCallbacks cb, void *user);   // 0 = open; nonzero = not possible (fall back to automatic answer)
// accepted = 1 closes the keyboard; 0 keeps it open and shows `message` (may be NULL) as the explanation line for a few seconds.
void swkbd_ui_resolve(int accepted, const char *message);
int swkbd_ui_active(void);
// True while the keyboard is drawn: open, or playing its closing animation (swkbd_ui_active is 0 then, it takes no input).
int swkbd_ui_visible(void);
// Opacity (0..1) of the blurred backdrop behind the keyboard: 1 while open, fading out with the closing animation.
float swkbd_ui_backdrop(void);

// Input. Buttons as bit numbers: 0 A, 1 B, 2 X, 3 Y, 4 LStick, 5 RStick, 6 L, 7 R, 8 ZL, 9 ZR, 10 Plus, 11 Minus, 12 Left, 13 Up, 14 Right, 15 Down.
void swkbd_ui_pad(uint64_t buttons, int lx, int ly);                 // current state; edges are detected inside
// Touch: down 1 = begins, 0 = the finger is lifted, -1 = cancelled; the key is entered when the finger is lifted over it. Position normalised in the window
// (0..1, y down); the last scene's fit is used.
void swkbd_ui_touch(int down, float nx, float ny);
void swkbd_ui_text(const char *utf8);                                // typed characters (hardware keyboard, native keyboard)
enum { SWKBD_KEY_BACKSPACE = 1, SWKBD_KEY_DELETE, SWKBD_KEY_LEFT, SWKBD_KEY_RIGHT, SWKBD_KEY_HOME, SWKBD_KEY_END, SWKBD_KEY_ENTER, SWKBD_KEY_ESCAPE };
void swkbd_ui_key(int key);
// True when the point (normalised window position) is on the text field of the simple fallback keyboard (no firmware layouts): the shell then brings up the
// system keyboard (iOS). Never true with the console's own keyboard.
int swkbd_ui_field_hit(float nx, float ny);

// Text measurement from the renderer (width in canvas pixels of a utf-8 string at a font size in canvas pixels); optional.
void swkbd_ui_set_measure(float (*fn)(const char *utf8, float font_px));

// Render side: locks the UI, advances animations by dt seconds and returns the scene for a target of w x h pixels (NULL if not active).
// The scene is in canvas pixels (1280x720); *scale and *off give the fit into the target (x_px = off[0] + x * scale). Call swkbd_ui_unlock afterwards.
const LytScene *swkbd_ui_scene(double dt, int target_w, int target_h, float *scale, float off[2]);
void swkbd_ui_unlock(void);

// For tests: the current text, focus name of the focused key.
const char *swkbd_ui_text_value(void);
const char *swkbd_ui_focus_name(void);
// Folder given by BDSP_FIRMWARE_DATA ("" if none): the renderer finds the fonts under fonts/ there.
const char *swkbd_ui_root(void);   // layout name of the focused key

#endif
