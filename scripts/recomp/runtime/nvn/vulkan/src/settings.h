// Replacement for runtime/settings.h when building the Vulkan version: fixed settings without FSR, SMAA and fullscreen.
#pragma once
#include <stdbool.h>

enum { UPSCALE_OFF, UPSCALE_METALFX, UPSCALE_FSR1 };
enum { AA_OFF, AA_SMAA };
typedef struct { int upscaler, antialias, res_mode; bool fullscreen; } BdspSettings;
extern BdspSettings g_settings;
void settings_load(void);
