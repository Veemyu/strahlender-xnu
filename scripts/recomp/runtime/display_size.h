// Display size shared by every shell and platform (display_size.c): the aspect ratio and render height choices, their storage, and the size of this run.
#pragma once
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct { const char *value, *label; double aspect; } DisplayChoice;   // value as stored/accepted, label = English menu text, aspect 0 = not a fixed ratio
const DisplayChoice *display_aspect_choices(int *count);
const DisplayChoice *display_height_choices(int *count);
// Preference "aspect" or "render_height": environment variable, else the file named by BDSP_DISPLAY_CONFIG; NULL when unset.
const char *display_pref_get(const char *key);
bool display_pref_store(const char *aspect, const char *render_height);
double display_aspect(void);   // aspect of the render size of this run (16:9 when stock)
void display_size_init(void);  // chooses the size and writes the slots of the main module before the guest starts
bool display_size_set(int w, int h);

#ifdef __cplusplus
}
#endif
