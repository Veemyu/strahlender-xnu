// Ersatz für runtime/settings.h beim Bau der Vulkan-Fassung: feste Einstellungen ohne FSR, SMAA und Vollbild.
#pragma once
#include <stdbool.h>

enum { UPSCALE_OFF, UPSCALE_METALFX, UPSCALE_FSR1 };
enum { AA_OFF, AA_SMAA };
typedef struct { int upscaler, antialias, res_mode; bool fullscreen; } BdspSettings;
extern BdspSettings g_settings;
void settings_load(void);
