// Ersatz für runtime/platform.h: nur die Zeitfunktionen.
#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

uint64_t plat_now_ns(void);
void plat_sleep_until_ns(uint64_t t);
