// Replacement for runtime/nvn/texpatch.h: texpatch (texture changes for a specific game) is not built; the functions
// are no-op stubs in nvn_glue.c.
#pragma once
#include <stdbool.h>
#include <stdint.h>

#include "nvn.h"

#define TEXPATCH_UNKNOWN (-2)
int texpatch_identify(const NvnTexture *t);
int texpatch_bottle_kind(int id);
bool texpatch_is_item_cursor(int id);
uint32_t texpatch_generation(void);
void texpatch_apply(int id, uint32_t lv, uint8_t *blocks, uint32_t w, uint32_t h, uint32_t row);
int texpatch_heart_kind(int id);
void texpatch_heart_tint(int kind, float tint[8]);
