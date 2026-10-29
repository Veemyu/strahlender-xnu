#include "hle.h"
#include "input.h"
#include "swkbd_ui.h"
#include <SDL3/SDL.h>
#include <assert.h>
#include <string.h>

#ifdef HLE_SECOND_OBJECT
HLE_FUNC("synthetic-second", second) { c->x[0] = 42; }
#else
HLE_FUNC("synthetic-first", first) { c->x[0] = 23; }

#ifndef QT_INPUT_PROBE
static PadState keyboard;
#endif
static int active, text_key, bound, touch_canceled;
static char text[64];
uint64_t g_proc_start_ns;
#ifndef QT_INPUT_PROBE
volatile int g_bdsp_fps = 60;
#endif

void input_handle_event(const void *event);
bool input_update_text(SDL_Window *window, bool enabled);
void nvn_glue_init(void);
#ifndef QT_INPUT_PROBE
void input_source_set(InputSource source, const PadState *state) {
    assert(source == INPUT_SRC_KEYBOARD);
    keyboard = *state;
}
void input_current(PadState *out) { *out = keyboard; }
#endif
void pad_sdl_start(void) {}
int swkbd_ui_active(void) { return active; }
void swkbd_ui_text(const char *value) { snprintf(text, sizeof text, "%s", value); }
void swkbd_ui_key(int key) { text_key = key; }
void swkbd_ui_touch(int down, float x, float y) {
    (void)x; (void)y;
    assert(down == -1);
    touch_canceled++;
}
uint64_t hle_register(const char *name, HostFn fn) { assert(name && fn); return ++bound; }
uint64_t rt_now_ns(void) {
#ifdef QT_INPUT_PROBE
    return 1000000000;
#else
    abort();
#endif
}
void kernel_phys_range(uint64_t *lo, uint64_t *hi) { (void)lo; (void)hi; abort(); }
uint64_t loader_find_symbol(const char *name) { (void)name; abort(); }
void rt_fatal_trace(void) { abort(); }
void bdsp_fatal_report(const char *why, int code) { (void)why; (void)code; abort(); }
void bdsp_gate_hit(const char *what) { (void)what; abort(); }
void *hle_alloc(uint64_t size) { (void)size; abort(); }
uint32_t vi_vsync_handle(void) { abort(); }
void rt_fatal(const char *format, ...) { (void)format; abort(); }
void guest_call(Cpu *cpu, uint64_t address) { (void)cpu; (void)address; abort(); }
uint64_t renderer_present_count(void) { abort(); }

#ifdef QT_INPUT_PROBE
void swkbd_ui_pad(uint64_t buttons, int x, int y) { (void)buttons; (void)x; (void)y; }
void swkbd_ui_pad_held(uint64_t buttons, int x, int y) { (void)buttons; (void)x; (void)y; }
void qt_input_keyboard_active(int value) { active = value; text_key = 0; *text = 0; }
const char *qt_input_text(void) { return text; }
int qt_input_text_key(void) { return text_key; }
uint64_t qt_input_guest_buttons(void) {
    _Alignas(8) uint8_t state[0x28] = {0};
    uint32_t player = 0;
    Cpu cpu = {0};
    cpu.x[0] = (uintptr_t)state;
    cpu.x[1] = (uintptr_t)&player;
    HostFn read = hle_lookup_impl("_ZN2nn3hid12GetNpadStateEPNS0_16NpadFullKeyStateERKj");
    assert(read);
    read(&cpu);
    assert(*(int64_t *)state > 0 && *(uint32_t *)(state + 32) == 1);
    return *(uint64_t *)(state + 8);
}
#else
static int SDLCALL text_worker(void *window) {
    assert(!input_update_text(window, true));
    return 0;
}

static void text_lifecycle(void) {
    assert(!input_update_text(NULL, true));
    assert(SDL_SetHint(SDL_HINT_VIDEO_DRIVER, "dummy"));
    assert(SDL_Init(SDL_INIT_VIDEO));
    SDL_Window *window = SDL_CreateWindow("synthetic text input", 320, 240, 0);
    assert(window && SDL_GetKeyboardFocus() == window);
    assert(!SDL_TextInputActive(window));
    assert(input_update_text(window, true) && SDL_TextInputActive(window));
    assert(input_update_text(window, true) && SDL_TextInputActive(window));
    SDL_Thread *worker = SDL_CreateThread(text_worker, "text-input-wrong-thread", window);
    assert(worker);
    SDL_WaitThread(worker, NULL);
    assert(SDL_TextInputActive(window));
    assert(SDL_HideWindow(window));
    assert(!SDL_GetKeyboardFocus());
    assert(input_update_text(window, true) && !SDL_TextInputActive(window));
    assert(SDL_ShowWindow(window));
    assert(input_update_text(window, true) && SDL_TextInputActive(window));
    SDL_Window *other = SDL_CreateWindow("other focus", 320, 240, 0);
    assert(other && SDL_GetKeyboardFocus() == other);
    assert(SDL_StartTextInput(other));
    assert(input_update_text(window, true) && !SDL_TextInputActive(window));
    assert(SDL_TextInputActive(other));   // never stop text input on the wrong window
    SDL_DestroyWindow(other);
    assert(SDL_HideWindow(window) && SDL_ShowWindow(window));
    assert(input_update_text(window, true) && SDL_TextInputActive(window));
    active = 1;
    SDL_Event event = {0};
    event.type = SDL_EVENT_TEXT_EDITING;
    event.edit.text = "uncommitted";
    input_handle_event(&event);
    assert(input_update_text(window, false) && !SDL_TextInputActive(window));
    assert(input_update_text(window, true) && SDL_TextInputActive(window));
    text_key = 0;
    event.type = SDL_EVENT_KEY_DOWN; event.key.scancode = SDL_SCANCODE_RETURN;
    input_handle_event(&event);
    assert(text_key == SWKBD_KEY_ENTER);   // no stale composition after a stop/restart
    active = 0;
    assert(input_update_text(window, false) && !SDL_TextInputActive(window));
    assert(input_update_text(window, false));
    SDL_DestroyWindow(window);
    SDL_Quit();
}

int main(void) {
    assert(getenv("BDSP_PACE") && !strcmp(getenv("BDSP_PACE"), "0"));
    Cpu cpu = {0};
    HostFn first_fn = hle_lookup_impl("synthetic-first");
    HostFn second_fn = hle_lookup_impl("synthetic-second");
    assert(first_fn && second_fn && !hle_lookup_impl("synthetic-missing"));
    first_fn(&cpu); assert(cpu.x[0] == 23);
    second_fn(&cpu); assert(cpu.x[0] == 42);
    nvn_glue_init();
    assert(bound >= 3);

    SDL_Event event = {0};
    event.type = SDL_EVENT_KEY_DOWN; event.key.scancode = SDL_SCANCODE_K;
    input_handle_event(&event);
    assert(keyboard.buttons == (1ull << PB_A));
    event.type = SDL_EVENT_WINDOW_FOCUS_LOST;
    input_handle_event(&event);
    assert(!keyboard.buttons);
    event.type = SDL_EVENT_KEY_DOWN; event.key.scancode = SDL_SCANCODE_J;
    input_handle_event(&event);
    assert(keyboard.buttons == (1ull << PB_B));
    event.type = SDL_EVENT_KEY_UP;
    input_handle_event(&event);
    assert(!keyboard.buttons);

    event.type = SDL_EVENT_KEY_DOWN; event.key.scancode = SDL_SCANCODE_K;
    input_handle_event(&event);
    assert(keyboard.buttons == (1ull << PB_A));
    active = 1;
    event.type = SDL_EVENT_KEY_UP;
    input_handle_event(&event);
    assert(!keyboard.buttons);   // a key held before the prompt can always release
    event.type = SDL_EVENT_KEY_DOWN; event.key.scancode = SDL_SCANCODE_RETURN;
    input_handle_event(&event);
    assert(text_key == SWKBD_KEY_ENTER && !keyboard.buttons);
    text_key = 0;
    event.type = SDL_EVENT_TEXT_EDITING;
    event.edit.text = "\xe3\x81\xab";
    input_handle_event(&event);
    assert(!*text && !keyboard.buttons);
    const SDL_Scancode ime_keys[] = {
        SDL_SCANCODE_RETURN, SDL_SCANCODE_BACKSPACE, SDL_SCANCODE_DELETE,
        SDL_SCANCODE_LEFT, SDL_SCANCODE_RIGHT, SDL_SCANCODE_HOME, SDL_SCANCODE_END,
        SDL_SCANCODE_ESCAPE,
    };
    for (size_t i = 0; i < sizeof ime_keys / sizeof *ime_keys; i++) {
        event.type = SDL_EVENT_KEY_DOWN; event.key.scancode = ime_keys[i];
        input_handle_event(&event);
        assert(!text_key && !keyboard.buttons);
    }
    event.type = SDL_EVENT_TEXT_INPUT;
    event.text.text = "\xe6\x97\xa5\xe6\x9c\xac";
    input_handle_event(&event);
    assert(!strcmp(text, "\xe6\x97\xa5\xe6\x9c\xac") && !keyboard.buttons);
    event.type = SDL_EVENT_KEY_DOWN; event.key.scancode = SDL_SCANCODE_BACKSPACE;
    input_handle_event(&event);
    assert(text_key == SWKBD_KEY_BACKSPACE && !keyboard.buttons);
    event.type = SDL_EVENT_TEXT_EDITING; event.edit.text = "uncommitted";
    input_handle_event(&event);
    event.edit.text = "";
    input_handle_event(&event);
    event.type = SDL_EVENT_KEY_DOWN; event.key.scancode = SDL_SCANCODE_RETURN;
    input_handle_event(&event);
    assert(text_key == SWKBD_KEY_ENTER);
    event.type = SDL_EVENT_TEXT_EDITING; event.edit.text = "uncommitted";
    input_handle_event(&event);
    event.type = SDL_EVENT_WINDOW_FOCUS_LOST;
    input_handle_event(&event);
    assert(touch_canceled == 1 && !keyboard.buttons);
    event.type = SDL_EVENT_KEY_DOWN; event.key.scancode = SDL_SCANCODE_BACKSPACE;
    input_handle_event(&event);
    assert(text_key == SWKBD_KEY_BACKSPACE);
    active = 0;
    event.type = SDL_EVENT_TEXT_INPUT; event.text.text = "must not enter a closed keyboard";
    input_handle_event(&event);
    assert(!strcmp(text, "\xe6\x97\xa5\xe6\x9c\xac"));
    event.type = SDL_EVENT_KEY_DOWN; event.key.scancode = SDL_SCANCODE_J;
    input_handle_event(&event);
    assert(keyboard.buttons == (1ull << PB_B));
    event.type = SDL_EVENT_KEY_UP;
    input_handle_event(&event);
    assert(!keyboard.buttons);
    text_lifecycle();
    puts("NVN glue: multi-object COFF HLE, keyboard focus reset and UTF-8 text passed.");
    puts("SDL text: native preedit isolation, main-thread lifecycle and focus ownership passed.");
    return 0;
}
#endif
#endif
