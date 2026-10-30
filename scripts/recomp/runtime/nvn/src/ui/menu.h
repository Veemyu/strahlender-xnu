// Replacement for runtime/ui/menu.h: no overlay menu.
#pragma once
#include <stdbool.h>
#include <stdint.h>

#ifdef __OBJC__
#import <Metal/Metal.h>
#endif

typedef union SDL_Event SDL_Event;
bool menu_handle_event(const SDL_Event *e);
bool menu_is_open(void);
void menu_apply_window_requests(void *sdl_window);
#ifdef __OBJC__
void menu_render(id<MTLDevice> dev, id<MTLCommandBuffer> cb, id<MTLTexture> target);
#endif
