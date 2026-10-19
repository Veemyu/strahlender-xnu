// Fenster-Teil des Metal-Renderers für iOS/iPadOS (ersetzt in metal_ios.m alles ab der Marke "UI thread" von metal.m; erzeugt von
// nvn_ios.py). Die App (scripts/recomp/ios/app/app.m) legt die CAMetalLayer im UIView an und setzt g_ios_layer vor dem Start der
// Laufzeit; Eingabe geht über g_ext_buttons/g_ext_stick (nvn_glue.c), die Größe der Zeichenfläche setzt die App.
CAMetalLayer *g_ios_layer;

void ui_window_init(void) {
    if (layer) return;
    settings_load();
    layer = g_ios_layer;
    dev = MTLCreateSystemDefaultDevice();
    layer.device = dev;
    layer.pixelFormat = MTLPixelFormatBGRA8Unorm;
    layer.framebufferOnly = getenv("BDSP_WINDOW_SHOT") ? NO : YES;
    LOG("[ios] Metal-Gerät %s, BC-Texturen %d, maxBufferLength %llu MiB, recommendedMaxWorkingSetSize %llu MiB\n", dev.name.UTF8String,
        (int)dev.supportsBCTextureCompression, (unsigned long long)(dev.maxBufferLength >> 20),
        (unsigned long long)(dev.recommendedMaxWorkingSetSize >> 20));
}

SDL_Window *ui_window(void) { return NULL; }
void *ui_metal_layer(void) { return (__bridge void *)layer; }
void *ui_metal_device(void) { return (__bridge void *)dev; }

int ui_run(void) {
    ui_window_init();
    atomic_store(&ui_ready, true);
    for (;;) {
        if (rt_reboot_requested()) return rt_reboot_requested();
        usleep(16000);
    }
}
