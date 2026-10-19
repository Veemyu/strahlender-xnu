// Menü, Tastatur, Controller, Ablegen von Dateien, Pause und Neustart der macOS-App (siehe app.h, docs/recomp-macapp.md).
// Die Fensterschleife (ui_run in metal.m, SDL3) ruft menu_handle_event für jedes Ereignis und menu_apply_window_requests
// etwa alle 16 ms auf dem Hauptthread auf; beides ist hier umgesetzt (die Stummel in nvn/nvn_glue.c sind schwach gebunden).
// Ton: keiner. Netz: keines.
#import <AppKit/AppKit.h>
#import <GameController/GameController.h>
#include <SDL3/SDL.h>
#include <spawn.h>
#include <stdatomic.h>
#include <unistd.h>

#include "app.h"

extern char **environ;
SDL_Window *ui_window(void);
// Eingabe der Laufzeit (nvn/nvn_glue.c): Tasten als Bitmaske, Sticks von -32767 bis 32767 (lx, ly, rx, ry)
extern _Atomic uint64_t g_ext_buttons;
extern _Atomic int32_t g_ext_stick[4];

enum { PB_A, PB_B, PB_X, PB_Y, PB_LSTICK, PB_RSTICK, PB_L, PB_R, PB_ZL, PB_ZR, PB_PLUS, PB_MINUS, PB_LEFT, PB_UP, PB_RIGHT, PB_DOWN };

// ---- Tastenbelegung (Standard von Ryujinx, dazu Return/Leertaste = A und Rücktaste = B)
typedef struct { SDL_Scancode sc; int kind; int a; int b; } KeyMap;   // kind 0: Taste a; kind 1: Stick-Achse a mit Richtung b (+1/-1)
static const KeyMap k_keys[] = {
    {SDL_SCANCODE_Z, 0, PB_A, 0}, {SDL_SCANCODE_RETURN, 0, PB_A, 0}, {SDL_SCANCODE_SPACE, 0, PB_A, 0},
    {SDL_SCANCODE_X, 0, PB_B, 0}, {SDL_SCANCODE_BACKSPACE, 0, PB_B, 0},
    {SDL_SCANCODE_C, 0, PB_X, 0}, {SDL_SCANCODE_V, 0, PB_Y, 0},
    {SDL_SCANCODE_E, 0, PB_L, 0}, {SDL_SCANCODE_U, 0, PB_R, 0}, {SDL_SCANCODE_Q, 0, PB_ZL, 0}, {SDL_SCANCODE_O, 0, PB_ZR, 0},
    {SDL_SCANCODE_EQUALS, 0, PB_PLUS, 0}, {SDL_SCANCODE_KP_PLUS, 0, PB_PLUS, 0}, {SDL_SCANCODE_TAB, 0, PB_PLUS, 0},
    {SDL_SCANCODE_MINUS, 0, PB_MINUS, 0}, {SDL_SCANCODE_KP_MINUS, 0, PB_MINUS, 0},
    {SDL_SCANCODE_F, 0, PB_LSTICK, 0}, {SDL_SCANCODE_H, 0, PB_RSTICK, 0},
    {SDL_SCANCODE_LEFT, 0, PB_LEFT, 0}, {SDL_SCANCODE_RIGHT, 0, PB_RIGHT, 0}, {SDL_SCANCODE_UP, 0, PB_UP, 0}, {SDL_SCANCODE_DOWN, 0, PB_DOWN, 0},
    {SDL_SCANCODE_A, 1, 0, -1}, {SDL_SCANCODE_D, 1, 0, +1}, {SDL_SCANCODE_S, 1, 1, -1}, {SDL_SCANCODE_W, 1, 1, +1},
    {SDL_SCANCODE_J, 1, 2, -1}, {SDL_SCANCODE_L, 1, 2, +1}, {SDL_SCANCODE_K, 1, 3, -1}, {SDL_SCANCODE_I, 1, 3, +1},
};
#define NKEYS (sizeof k_keys / sizeof k_keys[0])
static bool g_down[SDL_SCANCODE_COUNT];
static uint64_t g_pad_buttons;
static int32_t g_pad_stick[4];

static void publish(void) {
    uint64_t b = g_pad_buttons;
    int32_t s[4] = {0, 0, 0, 0};
    for (size_t i = 0; i < NKEYS; i++) {
        if (!g_down[k_keys[i].sc]) continue;
        if (k_keys[i].kind == 0) b |= 1ull << k_keys[i].a;
        else s[k_keys[i].a] += k_keys[i].b * 32767;
    }
    for (int i = 0; i < 4; i++) {
        if (s[i] > 32767) s[i] = 32767;
        if (s[i] < -32767) s[i] = -32767;
        if (!s[i]) s[i] = g_pad_stick[i];
        atomic_store(&g_ext_stick[i], s[i]);
    }
    atomic_store(&g_ext_buttons, b);
}

static void release_all(void) {
    memset(g_down, 0, sizeof g_down);
    publish();
}

// ---- Controller (GameController.framework: Xbox, PlayStation, Switch Pro u. a.)
static int32_t axis32(float v) {
    if (v > -0.12f && v < 0.12f) return 0;
    int32_t r = (int32_t)(v * 32767.0f);
    return r > 32767 ? 32767 : r < -32767 ? -32767 : r;
}

static void pad_poll(void) {
    uint64_t b = 0;
    int32_t s[4] = {0, 0, 0, 0};
    bool nintendo = !strcmp(g_app.pad_layout, "nintendo");
    for (GCController *c in [GCController controllers]) {
        GCExtendedGamepad *g = c.extendedGamepad;
        if (!g) continue;
        // Nintendo-Anordnung: A liegt rechts (GameController: buttonB), B unten (buttonA), X oben (buttonY), Y links (buttonX)
        if ((nintendo ? g.buttonB : g.buttonA).pressed) b |= 1ull << PB_A;
        if ((nintendo ? g.buttonA : g.buttonB).pressed) b |= 1ull << PB_B;
        if ((nintendo ? g.buttonY : g.buttonX).pressed) b |= 1ull << PB_X;
        if ((nintendo ? g.buttonX : g.buttonY).pressed) b |= 1ull << PB_Y;
        if (g.leftShoulder.pressed) b |= 1ull << PB_L;
        if (g.rightShoulder.pressed) b |= 1ull << PB_R;
        if (g.leftTrigger.pressed) b |= 1ull << PB_ZL;
        if (g.rightTrigger.pressed) b |= 1ull << PB_ZR;
        if (g.buttonMenu.pressed) b |= 1ull << PB_PLUS;
        if (g.buttonOptions.pressed) b |= 1ull << PB_MINUS;
        if (g.leftThumbstickButton.pressed) b |= 1ull << PB_LSTICK;
        if (g.rightThumbstickButton.pressed) b |= 1ull << PB_RSTICK;
        if (g.dpad.left.pressed) b |= 1ull << PB_LEFT;
        if (g.dpad.right.pressed) b |= 1ull << PB_RIGHT;
        if (g.dpad.up.pressed) b |= 1ull << PB_UP;
        if (g.dpad.down.pressed) b |= 1ull << PB_DOWN;
        int32_t v[4] = {axis32(g.leftThumbstick.xAxis.value), axis32(g.leftThumbstick.yAxis.value),
                        axis32(g.rightThumbstick.xAxis.value), axis32(g.rightThumbstick.yAxis.value)};
        for (int i = 0; i < 4; i++) if (!s[i]) s[i] = v[i];
    }
    if (b != g_pad_buttons || memcmp(s, g_pad_stick, sizeof s)) {
        g_pad_buttons = b;
        memcpy(g_pad_stick, s, sizeof s);
        publish();
    }
}

// ---- Meldungen
static void front(void) {
    [NSApp setActivationPolicy:NSApplicationActivationPolicyRegular];
    [NSApp activateIgnoringOtherApps:YES];
}

void bdsp_app_alert(const char *title, const char *msg) {
    fprintf(stderr, "[app] %s: %s\n", title, msg);
    if (g_app.headless) return;
    @autoreleasepool {
        [NSApplication sharedApplication];
        front();
        NSAlert *a = [NSAlert new];
        a.messageText = [NSString stringWithUTF8String:title];
        a.informativeText = [NSString stringWithUTF8String:msg];
        [a addButtonWithTitle:@"OK"];
        [a runModal];
    }
}

// Antwort 1 = erste Schaltfläche
static NSInteger ask(NSString *title, NSString *msg, NSArray<NSString *> *buttons) {
    front();
    NSAlert *a = [NSAlert new];
    a.messageText = title;
    a.informativeText = msg;
    for (NSString *b in buttons) [a addButtonWithTitle:b];
    return [a runModal] - NSAlertFirstButtonReturn + 1;
}

void bdsp_app_restart(void) {
    fflush(NULL);
    // Die Umgebung wandert über open/exec zum neuen Exemplar (BDSP_HOME usw. sollen bleiben); Testhaken dürfen nicht mit, sonst
    // startet sich das neue Exemplar nach demselben Zeitplan wieder neu
    static const char *const test_env[] = {"BDSP_UI_SELFTEST", "BDSP_KEY_SCRIPT", "BDSP_PAUSE_SELFTEST", "BDSP_INPUT_SCRIPT", "BDSP_SCREENSHOT_EVERY",
                                           "BDSP_SCREENSHOT_FROM", "BDSP_EXIT_AFTER_SHOT", NULL};
    for (int i = 0; test_env[i]; i++) unsetenv(test_env[i]);
    if (g_app.bundle[0]) {
        // Das neue Exemplar startet nach einer Sekunde, wenn dieses beendet ist (gleicher Spielstand-Ordner, gleiches Fenster)
        char *args[] = {"/bin/sh", "-c", "sleep 1; exec /usr/bin/open -n \"$0\"", g_app.bundle, NULL};
        posix_spawnattr_t at;
        posix_spawnattr_init(&at);
        posix_spawnattr_setflags(&at, POSIX_SPAWN_SETSID);
        pid_t pid;
        posix_spawn(&pid, "/bin/sh", NULL, &at, args, environ);
        _exit(0);
    }
    execv(g_app.exe, g_app.argv);
    _exit(1);
}

// ---- Spielstand-Aktionen
static void do_import(NSString *path) {
    char msg[3000];
    NSInteger ok = ask(@"Spielstand importieren?",
                       [NSString stringWithFormat:@"%@\n\nDer bisherige Spielstand wird vorher gesichert (backups/). Danach startet das Spiel neu.", path],
                       @[@"Importieren", @"Abbrechen"]);
    if (ok != 1) return;
    int r = bdsp_save_import(path.fileSystemRepresentation, msg, sizeof msg);
    fprintf(stderr, "[app] Import %s: %s\n", r == 0 ? "ok" : "abgelehnt", msg);
    if (r != 0) { ask(@"Import abgelehnt", [NSString stringWithUTF8String:msg], @[@"OK"]); return; }
    ask(@"Spielstand importiert", [NSString stringWithUTF8String:msg], @[@"Neustart"]);
    bdsp_app_restart();
}

static void open_folder(const char *dir) {
    NSString *p = [NSString stringWithUTF8String:dir];
    [[NSFileManager defaultManager] createDirectoryAtPath:p withIntermediateDirectories:YES attributes:nil error:nil];
    [[NSWorkspace sharedWorkspace] openURL:[NSURL fileURLWithPath:p isDirectory:YES]];
}

static const char *const k_default_config =
    "# BDSP: Konfiguration (Schlüssel = Wert). Umgebungsvariablen BDSP_* haben Vorrang. Änderungen gelten nach einem Neustart.\n"
    "# romfs = ~/Library/Application Support/dev.local.xnubdsp/romfs\n"
    "# save = ~/Library/Application Support/dev.local.xnubdsp/save\n"
    "# cache = ~/Library/Caches/dev.local.xnubdsp\n"
    "# logs = ~/Library/Logs/dev.local.xnubdsp\n"
    "# language = en-US          # Sprache, die das Spiel erfragt (en-US, de, fr, es, it, ja, ko, zh-Hans, zh-Hant)\n"
    "# window = 1280x720         # Fenstergröße in Punkten\n"
    "# fullscreen = 0\n"
    "# pause_on_focus_loss = 0   # 1: Spiel hält an, wenn das Fenster den Fokus verliert\n"
    "# pad_layout = nintendo     # nintendo (Tastenposition wie bei der Switch) oder xbox (Beschriftung)\n"
    "# backups = 10              # Zahl der Sicherungen beim Start\n"
    "# fps = 60                  # Bildrate: 30, 60 oder 120 (Menü Ansicht > Bildrate hat Vorrang)\n";

static const char *const k_keys_help =
    "Tastatur (Standard von Ryujinx):\n"
    "  Z = A    X = B    C = X    V = Y\n"
    "  Return/Leertaste = A    Rücktaste = B (zusätzlich)\n"
    "  E = L    U = R    Q = ZL    O = ZR\n"
    "  = oder Tab = +    Minus = −    F = L-Stick drücken    H = R-Stick drücken\n"
    "  Pfeiltasten = Steuerkreuz\n"
    "  W A S D = linker Stick    I J K L = rechter Stick\n\n"
    "Controller (Xbox, PlayStation, Switch Pro): Tastenposition wie bei der Switch (pad_layout = xbox: nach Beschriftung), "
    "Menü = +, Ansicht/Optionen = −.\n\n"
    "Fenster: Cmd+F Vollbild, Cmd+1 bis Cmd+4 Fenstergröße, Cmd+P Pause, Cmd+R Neustart. Kein Ton.";

@interface BdspMenu : NSObject <NSMenuItemValidation>
@end
static bool g_user_paused, g_focus_paused;
static void apply_pause(void) { g_bdsp_paused = g_user_paused || g_focus_paused; }

@implementation BdspMenu
- (void)openSave:(id)s { char d[1300]; bdsp_save_dir(d, sizeof d); open_folder(d); }
- (void)importSave:(id)s {
    NSOpenPanel *p = [NSOpenPanel openPanel];
    p.canChooseFiles = YES;
    p.canChooseDirectories = YES;
    p.allowsMultipleSelection = NO;
    p.showsHiddenFiles = YES;
    p.message = @"SaveData.bin oder den Ordner damit wählen (Ryujinx: bis/user/save/<ID>/0; Switch: exportierter Spielstand)";
    p.prompt = @"Wählen";
    if ([p runModal] == NSModalResponseOK && p.URL) do_import(p.URL.path);
}
- (void)resetSave:(id)s {
    if (ask(@"Spielstand zurücksetzen?", @"Der aktuelle Spielstand wird in den Sicherungsordner verschoben (backups/), danach beginnt das Spiel ohne Spielstand neu.",
            @[@"Zurücksetzen", @"Abbrechen"]) != 1) return;
    char msg[1700];
    int r = bdsp_save_reset(msg, sizeof msg);
    fprintf(stderr, "[app] Zurücksetzen: %s\n", msg);
    if (r != 0) { ask(@"Zurücksetzen fehlgeschlagen", [NSString stringWithUTF8String:msg], @[@"OK"]); return; }
    bdsp_app_restart();
}
- (void)restart:(id)s {
    if (ask(@"Neustart", @"Das Spiel wird beendet und neu gestartet. Nicht gespeicherter Fortschritt geht verloren.", @[@"Neustart", @"Abbrechen"]) == 1) bdsp_app_restart();
}
- (void)togglePause:(id)s { g_user_paused = !g_user_paused; apply_pause(); if (g_user_paused) release_all(); }
- (void)toggleFullscreen:(id)s {
    SDL_Window *w = ui_window();
    if (w) SDL_SetWindowFullscreen(w, !(SDL_GetWindowFlags(w) & SDL_WINDOW_FULLSCREEN));
}
- (void)windowSize:(NSMenuItem *)s {
    SDL_Window *w = ui_window();
    if (!w) return;
    if (SDL_GetWindowFlags(w) & SDL_WINDOW_FULLSCREEN) SDL_SetWindowFullscreen(w, false);
    SDL_SetWindowSize(w, (int)(s.tag >> 16), (int)(s.tag & 0xFFFF));
    SDL_SyncWindow(w);
}
- (void)setFps:(NSMenuItem *)s {
    bdsp_set_fps((int)s.tag);
    [[NSUserDefaults standardUserDefaults] setInteger:s.tag forKey:@"bdsp_fps"];
}
- (void)toggleMetalHud:(id)s {
    NSUserDefaults *d = [NSUserDefaults standardUserDefaults];
    [d setBool:![d boolForKey:@"bdsp_metal_hud"] forKey:@"bdsp_metal_hud"];
    ask(@"Metal-HUD", NSLocalizedString(@"Wirkt nach einem Neustart von BDSP.", nil), @[@"OK"]);
}
- (void)openCache:(id)s { open_folder(g_app.cache); }
- (void)openLogs:(id)s { open_folder(g_app.logs); }
- (void)showConfig:(id)s {
    if (access(g_app.config, R_OK) != 0) { FILE *f = fopen(g_app.config, "w"); if (f) { fputs(k_default_config, f); fclose(f); } }
    [[NSWorkspace sharedWorkspace] activateFileViewerSelectingURLs:@[[NSURL fileURLWithPath:[NSString stringWithUTF8String:g_app.config]]]];
}
- (void)showKeys:(id)s { ask(@"Tastenbelegung", [NSString stringWithUTF8String:k_keys_help], @[@"OK"]); }
- (BOOL)validateMenuItem:(NSMenuItem *)item {
    if (item.action == @selector(togglePause:)) item.state = g_user_paused ? NSControlStateValueOn : NSControlStateValueOff;
    if (item.action == @selector(setFps:)) item.state = item.tag == g_bdsp_fps ? NSControlStateValueOn : NSControlStateValueOff;
    if (item.action == @selector(toggleMetalHud:)) item.state = [[NSUserDefaults standardUserDefaults] boolForKey:@"bdsp_metal_hud"] ? NSControlStateValueOn : NSControlStateValueOff;
    if (item.action == @selector(toggleFullscreen:)) {
        SDL_Window *w = ui_window();
        item.state = w && (SDL_GetWindowFlags(w) & SDL_WINDOW_FULLSCREEN) ? NSControlStateValueOn : NSControlStateValueOff;
    }
    return YES;
}
@end

static BdspMenu *g_target;

static NSMenuItem *item(NSMenu *m, NSString *title, SEL sel, NSString *key, NSEventModifierFlags mods, id target) {
    NSMenuItem *i = [m addItemWithTitle:title action:sel keyEquivalent:key];
    i.keyEquivalentModifierMask = mods;
    i.target = target;
    return i;
}

static void install_menu(void) {
    g_target = [BdspMenu new];
    NSMenu *bar = [NSMenu new];
    NSString *name = @"BDSP";
    // App-Menü
    NSMenuItem *ai = [bar addItemWithTitle:@"" action:nil keyEquivalent:@""];
    NSMenu *am = [[NSMenu alloc] initWithTitle:name];
    ai.submenu = am;
    item(am, @"Über BDSP", @selector(orderFrontStandardAboutPanel:), @"", 0, NSApp);
    [am addItem:[NSMenuItem separatorItem]];
    item(am, @"BDSP ausblenden", @selector(hide:), @"h", NSEventModifierFlagCommand, NSApp);
    item(am, @"Andere ausblenden", @selector(hideOtherApplications:), @"h", NSEventModifierFlagCommand | NSEventModifierFlagOption, NSApp);
    item(am, @"Alle einblenden", @selector(unhideAllApplications:), @"", 0, NSApp);
    [am addItem:[NSMenuItem separatorItem]];
    item(am, @"BDSP beenden", @selector(terminate:), @"q", NSEventModifierFlagCommand, NSApp);
    // Spiel
    NSMenuItem *gi = [bar addItemWithTitle:@"" action:nil keyEquivalent:@""];
    NSMenu *gm = [[NSMenu alloc] initWithTitle:@"Spiel"];
    gi.submenu = gm;
    item(gm, @"Spielstand-Ordner öffnen", @selector(openSave:), @"o", NSEventModifierFlagCommand, g_target);
    item(gm, @"Spielstand importieren …", @selector(importSave:), @"i", NSEventModifierFlagCommand, g_target);
    [gm addItem:[NSMenuItem separatorItem]];
    item(gm, @"Pause", @selector(togglePause:), @"p", NSEventModifierFlagCommand, g_target);
    item(gm, @"Neustart", @selector(restart:), @"r", NSEventModifierFlagCommand, g_target);
    item(gm, @"Spiel zurücksetzen …", @selector(resetSave:), @"r", NSEventModifierFlagCommand | NSEventModifierFlagShift, g_target);
    // Ansicht
    NSMenuItem *vi = [bar addItemWithTitle:@"" action:nil keyEquivalent:@""];
    NSMenu *vm = [[NSMenu alloc] initWithTitle:NSLocalizedString(@"Ansicht", nil)];
    vi.submenu = vm;
    item(vm, NSLocalizedString(@"Vollbild", nil), @selector(toggleFullscreen:), @"f", NSEventModifierFlagCommand, g_target);
    NSMenuItem *fi = [vm addItemWithTitle:NSLocalizedString(@"Bildrate", nil) action:nil keyEquivalent:@""];
    NSMenu *fm = [[NSMenu alloc] initWithTitle:NSLocalizedString(@"Bildrate", nil)];
    fi.submenu = fm;
    for (NSNumber *f in @[@30, @60, @120]) {
        NSMenuItem *it = item(fm, [NSString stringWithFormat:@"%@ fps", f], @selector(setFps:), @"", 0, g_target);
        it.tag = f.integerValue;
    }
    NSInteger savedFps = [[NSUserDefaults standardUserDefaults] integerForKey:@"bdsp_fps"];
    if (savedFps) bdsp_set_fps((int)savedFps);
    [vm addItem:[NSMenuItem separatorItem]];
    static const int sizes[4][2] = {{960, 540}, {1280, 720}, {1920, 1080}, {2560, 1440}};
    for (int i = 0; i < 4; i++) {
        NSMenuItem *it = item(vm, [NSString stringWithFormat:NSLocalizedString(@"Fenstergröße %d × %d", nil), sizes[i][0], sizes[i][1]], @selector(windowSize:),
                              [NSString stringWithFormat:@"%d", i + 1], NSEventModifierFlagCommand, g_target);
        it.tag = (NSInteger)sizes[i][0] << 16 | sizes[i][1];
    }
    [vm addItem:[NSMenuItem separatorItem]];
    NSMenuItem *di = [vm addItemWithTitle:NSLocalizedString(@"Debug", nil) action:nil keyEquivalent:@""];
    NSMenu *dm = [[NSMenu alloc] initWithTitle:NSLocalizedString(@"Debug", nil)];
    di.submenu = dm;
    item(dm, NSLocalizedString(@"Metal-HUD anzeigen", nil), @selector(toggleMetalHud:), @"", 0, g_target);
    // Fenster
    NSMenuItem *wi = [bar addItemWithTitle:@"" action:nil keyEquivalent:@""];
    NSMenu *wm = [[NSMenu alloc] initWithTitle:@"Fenster"];
    wi.submenu = wm;
    item(wm, @"Im Dock ablegen", @selector(performMiniaturize:), @"m", NSEventModifierFlagCommand, nil);
    [NSApp setWindowsMenu:wm];
    // Hilfe
    NSMenuItem *hi = [bar addItemWithTitle:@"" action:nil keyEquivalent:@""];
    NSMenu *hm = [[NSMenu alloc] initWithTitle:@"Hilfe"];
    hi.submenu = hm;
    item(hm, @"Tastenbelegung …", @selector(showKeys:), @"", 0, g_target);
    item(hm, @"Konfigurationsdatei zeigen", @selector(showConfig:), @"", 0, g_target);
    item(hm, @"Cache-Ordner öffnen (Shader, Bilder)", @selector(openCache:), @"", 0, g_target);
    item(hm, @"Log-Ordner öffnen", @selector(openLogs:), @"", 0, g_target);
    [NSApp setMainMenu:bar];
    [NSApp setHelpMenu:hm];
    if (getenv("BDSP_MENU_DUMP")) {   // Prüfung der Menüstruktur ohne Sichtkontakt
        for (NSMenuItem *top in bar.itemArray) {
            fprintf(stderr, "[menu] %s\n", top.submenu.title.UTF8String);
            for (NSMenuItem *it in top.submenu.itemArray)
                if (!it.separatorItem) fprintf(stderr, "[menu]   %s [%s%s%s%s]\n", it.title.UTF8String,
                                               (it.keyEquivalentModifierMask & NSEventModifierFlagCommand) ? "Cmd+" : "",
                                               (it.keyEquivalentModifierMask & NSEventModifierFlagShift) ? "Umschalt+" : "",
                                               (it.keyEquivalentModifierMask & NSEventModifierFlagOption) ? "Wahl+" : "", it.keyEquivalent.UTF8String);
        }
    }
}

// ---- Hooks der Fensterschleife (metal.m ui_run)
bool menu_handle_event(const SDL_Event *e) {
    switch (e->type) {
    case SDL_EVENT_KEY_DOWN: case SDL_EVENT_KEY_UP:
        if (e->key.mod & SDL_KMOD_GUI) return true;   // Menükürzel (Cmd+…) gehören dem Menü
        if (e->type == SDL_EVENT_KEY_DOWN && e->key.scancode == SDL_SCANCODE_ESCAPE) {
            SDL_Window *w = ui_window();
            if (w && (SDL_GetWindowFlags(w) & SDL_WINDOW_FULLSCREEN)) SDL_SetWindowFullscreen(w, false);
            return true;
        }
        if (e->key.scancode < SDL_SCANCODE_COUNT) { g_down[e->key.scancode] = e->type == SDL_EVENT_KEY_DOWN; publish(); }
        return true;
    case SDL_EVENT_DROP_FILE:
        if (e->drop.data) do_import([NSString stringWithUTF8String:e->drop.data]);
        return true;
    case SDL_EVENT_WINDOW_FOCUS_LOST:
        release_all();
        if (g_app.pause_on_focus_loss) { g_focus_paused = true; apply_pause(); }
        return false;
    case SDL_EVENT_WINDOW_FOCUS_GAINED:
        if (g_focus_paused) { g_focus_paused = false; apply_pause(); }
        return false;
    default: return false;
    }
}

// ---- Tastenskript für Tests (BDSP_KEY_SCRIPT="Sekunde:TASTE:Dauer,…" oder "@Datei", ab Prozessstart): speist echte SDL-Tastenereignisse
// in die Fensterschleife ein, also durch dieselbe Belegung wie die Tastatur (z. B. "62:Z:0.4,70:Up:2"; Tastennamen wie SDL_GetScancodeFromName)
typedef struct { double at, len; SDL_Scancode sc; bool down; } KeyStep;
static KeyStep g_ks[4096];
static int g_nks = -1;

static void key_script_load(void) {
    g_nks = 0;
    const char *spec = getenv("BDSP_KEY_SCRIPT");
    if (!spec) return;
    static char buf[1 << 17];
    if (spec[0] == '@') {
        FILE *f = fopen(spec + 1, "rb");
        size_t n = f ? fread(buf, 1, sizeof buf - 1, f) : 0;
        if (f) fclose(f);
        buf[n] = 0;
        for (size_t i = 0; i < n; i++) if (buf[i] == '\n') buf[i] = ',';
    } else snprintf(buf, sizeof buf, "%s", spec);
    char *save = NULL;
    for (char *tok = strtok_r(buf, ",", &save); tok && g_nks < 4096; tok = strtok_r(NULL, ",", &save)) {
        double at = 0, len = 0.3;
        char name[32] = "";
        if (sscanf(tok, "%lf:%31[^:]:%lf", &at, name, &len) < 2) continue;
        SDL_Scancode sc = SDL_GetScancodeFromName(name);
        if (sc == SDL_SCANCODE_UNKNOWN) { fprintf(stderr, "[app] Tastenskript: unbekannte Taste %s\n", name); continue; }
        g_ks[g_nks++] = (KeyStep){at, len, sc, false};
    }
    fprintf(stderr, "[app] Tastenskript mit %d Schritten\n", g_nks);
}

static void key_script_tick(void) {
    if (g_nks < 0) key_script_load();
    static double t0;
    if (!t0) t0 = SDL_GetTicks() / 1000.0;
    double t = SDL_GetTicks() / 1000.0 - t0;
    for (int i = 0; i < g_nks; i++) {
        bool want = t >= g_ks[i].at && t < g_ks[i].at + g_ks[i].len;
        if (want == g_ks[i].down) continue;
        g_ks[i].down = want;
        SDL_Event e;
        memset(&e, 0, sizeof e);
        e.type = want ? SDL_EVENT_KEY_DOWN : SDL_EVENT_KEY_UP;
        e.key.scancode = g_ks[i].sc;
        e.key.down = want;
        SDL_PushEvent(&e);
    }
}

// ---- Selbsttest der Menüaktionen (BDSP_UI_SELFTEST="Sekunde:Aktion,…", Aktionen: fs, w960, w1280, w1920, w2560, pause, restart): ruft dieselben
// Methoden wie die Menüeinträge auf (ohne Rückfrage), weil sich Tastenkürzel nicht von außen senden lassen (Bedienungshilfen nicht erlaubt)
static void ui_selftest_tick(void) {
    static char buf[512];
    static struct { double at; char act[16]; bool done; } st[32];
    static int n = -1;
    static double t0;
    if (n < 0) {
        n = 0;
        const char *s = getenv("BDSP_UI_SELFTEST");
        if (s) {
            snprintf(buf, sizeof buf, "%s", s);
            char *save = NULL;
            for (char *tok = strtok_r(buf, ",", &save); tok && n < 32; tok = strtok_r(NULL, ",", &save))
                if (sscanf(tok, "%lf:%15s", &st[n].at, st[n].act) == 2) n++;
        }
        t0 = SDL_GetTicks() / 1000.0;
    }
    double t = SDL_GetTicks() / 1000.0 - t0;
    for (int i = 0; i < n; i++) {
        if (st[i].done || t < st[i].at || !g_target) continue;
        st[i].done = true;
        fprintf(stderr, "[app] Selbsttest %s bei %.1f s\n", st[i].act, t);
        if (!strcmp(st[i].act, "fs")) [g_target toggleFullscreen:nil];
        else if (!strcmp(st[i].act, "pause")) [g_target togglePause:nil];
        else if (!strcmp(st[i].act, "restart")) bdsp_app_restart();
        else if (st[i].act[0] == 'w') {
            NSMenuItem *it = [NSMenuItem new];
            int w = atoi(st[i].act + 1);
            it.tag = (NSInteger)w << 16 | (w * 9 / 16);
            [g_target windowSize:it];
        }
    }
}

void menu_apply_window_requests(void *window) {
    static bool started;
    ui_selftest_tick();
    if (!started) {
        started = true;
        @autoreleasepool {
            install_menu();
            SDL_Window *w = window;
            SDL_SetWindowTitle(w, "BDSP");
            SDL_SetWindowMinimumSize(w, 640, 360);
            if (g_app.fullscreen && !g_app.headless) SDL_SetWindowFullscreen(w, true);
            if (!g_app.headless) {
                // Das Fenster erscheint erst jetzt im Vordergrund (SDL zeigt es ohne Aktivierung)
                front();
            }
        }
    }
    @autoreleasepool { pad_poll(); }
    key_script_tick();
    // Selbsttest der Pause (BDSP_PAUSE_SELFTEST="<ab Sekunde>:<Dauer>"): hält das Vsync-Ereignis an und gibt es wieder frei
    static double t0, p0 = -1, plen;
    if (!t0) {
        t0 = SDL_GetTicks() / 1000.0;
        const char *s = getenv("BDSP_PAUSE_SELFTEST");
        if (s) sscanf(s, "%lf:%lf", &p0, &plen);
    }
    double t = SDL_GetTicks() / 1000.0 - t0;
    if (p0 >= 0 && t >= p0 && t < p0 + plen && !g_user_paused) { g_user_paused = true; apply_pause(); fprintf(stderr, "[app] Pause (Selbsttest) bei %.1f s\n", t); }
    if (p0 >= 0 && t >= p0 + plen && g_user_paused) { g_user_paused = false; apply_pause(); fprintf(stderr, "[app] Pause beendet bei %.1f s\n", t); p0 = -1; }
}
