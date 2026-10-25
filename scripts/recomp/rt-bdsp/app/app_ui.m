// Menu, keyboard, controller, file drops, pause and restart of the macOS app (see app.h, docs/recomp-macapp.md).
// The window loop (ui_run in metal.m, SDL3) calls menu_handle_event for every event and menu_apply_window_requests
// about every 16 ms on the main thread; both are implemented here (the stubs in nvn/nvn_glue.c are weakly bound).
// Sound: none. Network: none.
// UI texts: the English text is the key (NSLocalizedString, development language en); German is in lproj/de.lproj.
#import <AppKit/AppKit.h>
#import <GameController/GameController.h>
#include "../pad_apple.h"
#include <SDL3/SDL.h>
#include <spawn.h>
#include <stdatomic.h>
#include <unistd.h>

#include "app.h"
#include "../mods.h"
#include "../swkbd_ui.h"
#import "../../app/icon_variants.h"

#define L(s) NSLocalizedString(@s, nil)

static void ApplyDockIcon(void) {
    NSDictionary *icons = BDSPReadIcons([NSString stringWithUTF8String:g_app.resources]);
    NSDictionary *variant = BDSPFindIcon(icons, BDSPIconSelection(icons));
    if ([variant[@"id"] isEqualToString:icons[@"default"]]) {
        // Preserve the system-rendered layered icon for the embedded default.
        NSApp.applicationIconImage = nil;
        return;
    }
    NSString *path = [[NSString stringWithUTF8String:g_app.resources] stringByAppendingPathComponent:@"AppIcons"];
    if (variant) NSApp.applicationIconImage = [[NSImage alloc] initWithContentsOfFile:[path stringByAppendingPathComponent:variant[@"mac_image"] ?: variant[@"image"]]];
}

extern char **environ;
SDL_Window *ui_window(void);
// Input of the runtime (nvn/nvn_glue.c): buttons as a bit mask, sticks from -32767 to 32767 (lx, ly, rx, ry)
extern _Atomic uint64_t g_ext_buttons;
extern _Atomic int32_t g_ext_stick[4];

enum { PB_A, PB_B, PB_X, PB_Y, PB_LSTICK, PB_RSTICK, PB_L, PB_R, PB_ZL, PB_ZR, PB_PLUS, PB_MINUS, PB_LEFT, PB_UP, PB_RIGHT, PB_DOWN };

// ---- Key mapping (Ryujinx default, plus Return/Space = A and Backspace = B)
typedef struct { SDL_Scancode sc; int kind; int a; int b; } KeyMap;   // kind 0: button a; kind 1: stick axis a with direction b (+1/-1)
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
    if (swkbd_ui_active()) {   // the on-screen keyboard has the input; the game sees nothing meanwhile
        atomic_store(&g_ext_buttons, 0);
        for (int i = 0; i < 4; i++) atomic_store(&g_ext_stick[i], 0);
        return;
    }
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

// ---- Controller (GameController.framework: Xbox, PlayStation, Switch Pro, among others)
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
        // Nintendo layout: A is on the right (GameController: buttonB), B at the bottom (buttonA), X at the top (buttonY), Y on the left (buttonX).
        // A Nintendo pad already names its buttons like the console (buttonA is the right one), so it needs no swap.
        BOOL swap = nintendo && !pad_is_nintendo(c);
        if ((swap ? g.buttonB : g.buttonA).pressed) b |= 1ull << PB_A;
        if ((swap ? g.buttonA : g.buttonB).pressed) b |= 1ull << PB_B;
        if ((swap ? g.buttonY : g.buttonX).pressed) b |= 1ull << PB_X;
        if ((swap ? g.buttonX : g.buttonY).pressed) b |= 1ull << PB_Y;
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

// ---- Messages
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

int bdsp_app_pick_game(const char *const *names, int n, int preselect, int *ask_again) {
    @autoreleasepool {
        [NSApplication sharedApplication];
        front();
        NSAlert *a = [NSAlert new];
        a.messageText = @"Choose a game";
        a.informativeText = @"A mod runs with a save of its own. The save of Brilliant Diamond is not touched while a mod is active.";
        NSPopUpButton *pop = [[NSPopUpButton alloc] initWithFrame:NSMakeRect(0, 0, 320, 26) pullsDown:NO];
        [pop addItemWithTitle:@"Brilliant Diamond"];
        for (int i = 0; i < n; i++) [pop addItemWithTitle:@(names[i])];
        [pop selectItemAtIndex:preselect >= 0 && preselect <= n ? preselect : 0];
        a.accessoryView = pop;
        [a addButtonWithTitle:@"Start"];
        [a addButtonWithTitle:@"Quit"];
        a.showsSuppressionButton = YES;
        a.suppressionButton.title = @"Don't ask again (hold Option at launch to choose)";
        NSModalResponse r = [a runModal];
        if (ask_again) *ask_again = a.suppressionButton.state != NSControlStateValueOn;
        return r == NSAlertFirstButtonReturn ? (int)pop.indexOfSelectedItem : -1;
    }
}

// answer 1 = first button
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
    // The environment travels through open/exec to the new instance (BDSP_HOME etc. must stay); test hooks must not come along,
    // otherwise the new instance restarts itself on the same schedule
    static const char *const test_env[] = {"BDSP_UI_SELFTEST", "BDSP_KEY_SCRIPT", "BDSP_PAUSE_SELFTEST", "BDSP_INPUT_SCRIPT", "BDSP_SCREENSHOT_EVERY",
                                           "BDSP_SCREENSHOT_FROM", "BDSP_EXIT_AFTER_SHOT", NULL};
    for (int i = 0; test_env[i]; i++) unsetenv(test_env[i]);
    if (g_app.bundle[0]) {
        // The new instance starts after one second, when this one has exited (same save folder, same window)
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

// ---- Save actions
static void do_import(NSString *path) {
    char msg[3000];
    NSInteger ok = ask(L("Import save?"),
                       [NSString stringWithFormat:L("%@\n\nThe current save is backed up first (backups/). Then the game restarts."), path],
                       @[L("Import"), L("Cancel")]);
    if (ok != 1) return;
    int r = bdsp_save_import(path.fileSystemRepresentation, msg, sizeof msg);
    fprintf(stderr, "[app] Import %s: %s\n", r == 0 ? "ok" : "rejected", msg);
    if (r != 0) { ask(L("Import rejected"), [NSString stringWithUTF8String:msg], @[@"OK"]); return; }
    ask(L("Save imported"), [NSString stringWithUTF8String:msg], @[L("Restart")]);
    bdsp_app_restart();
}

static void open_folder(const char *dir) {
    NSString *p = [NSString stringWithUTF8String:dir];
    [[NSFileManager defaultManager] createDirectoryAtPath:p withIntermediateDirectories:YES attributes:nil error:nil];
    [[NSWorkspace sharedWorkspace] openURL:[NSURL fileURLWithPath:p isDirectory:YES]];
}

static const char *const k_default_config =
    "# BDSP: configuration (key = value). Environment variables BDSP_* take precedence. Changes apply after a restart.\n"
    "# romfs = ~/Library/Application Support/dev.local.xnubdsp/romfs\n"
    "# save = ~/Library/Application Support/dev.local.xnubdsp/save\n"
    "# cache = ~/Library/Caches/dev.local.xnubdsp\n"
    "# logs = ~/Library/Logs/dev.local.xnubdsp\n"
    "# language = en-US          # language the game asks for (en-US, de, fr, es, it, ja, ko, zh-Hans, zh-Hant)\n"
    "# window = 1280x720         # window size in points\n"
    "# fullscreen = 0\n"
    "# pause_on_focus_loss = 0   # 1: the game pauses when the window loses focus\n"
    "# pad_layout = nintendo     # nintendo (button position as on the Switch) or xbox (labels)\n"
    "# backups = 10              # number of backups at start\n"
    "# fps = 60                  # frame rate: 30, 60 or 120 (the menu View > Frame Rate takes precedence)\n";

#define KEYS_HELP_EN \
    "Keyboard (Ryujinx default):\n" \
    "  Z = A    X = B    C = X    V = Y\n" \
    "  Return/Space = A    Backspace = B (additionally)\n" \
    "  E = L    U = R    Q = ZL    O = ZR\n" \
    "  = or Tab = +    Minus = −    F = press left stick    H = press right stick\n" \
    "  Arrow keys = D-pad\n" \
    "  W A S D = left stick    I J K L = right stick\n\n" \
    "Controller (Xbox, PlayStation, Switch Pro): button position as on the Switch (pad_layout = xbox: by label), " \
    "Menu = +, View/Options = −.\n\n" \
    "Window: Cmd+F full screen, Cmd+1 to Cmd+4 window size, Cmd+P pause, Cmd+R restart. No sound."

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
    p.message = L("Choose SaveData.bin or the folder containing it (Ryujinx: bis/user/save/<ID>/0; Switch: exported save)");
    p.prompt = L("Choose");
    if ([p runModal] == NSModalResponseOK && p.URL) do_import(p.URL.path);
}
- (void)resetSave:(id)s {
    if (ask(L("Reset save?"), L("The current save is moved to the backup folder (backups/), then the game starts again without a save."),
            @[L("Reset"), L("Cancel")]) != 1) return;
    char msg[1700];
    int r = bdsp_save_reset(msg, sizeof msg);
    fprintf(stderr, "[app] Reset: %s\n", msg);
    if (r != 0) { ask(L("Reset failed"), [NSString stringWithUTF8String:msg], @[@"OK"]); return; }
    bdsp_app_restart();
}
- (void)restart:(id)s {
    if (ask(L("Restart"), L("The game is closed and restarted. Unsaved progress is lost."), @[L("Restart"), L("Cancel")]) == 1) bdsp_app_restart();
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
    ask(@"Metal HUD", L("Takes effect after restarting BDSP."), @[@"OK"]);
}
- (void)openCache:(id)s { open_folder(g_app.cache); }
- (void)openLogs:(id)s { open_folder(g_app.logs); }
- (void)showConfig:(id)s {
    if (access(g_app.config, R_OK) != 0) { FILE *f = fopen(g_app.config, "w"); if (f) { fputs(k_default_config, f); fclose(f); } }
    [[NSWorkspace sharedWorkspace] activateFileViewerSelectingURLs:@[[NSURL fileURLWithPath:[NSString stringWithUTF8String:g_app.config]]]];
}
- (void)showKeys:(id)s { ask(L("Key Bindings"), NSLocalizedStringWithDefaultValue(@"KEYS_HELP", nil, NSBundle.mainBundle, @KEYS_HELP_EN, nil), @[@"OK"]); }
- (void)selectAppIcon:(NSMenuItem *)sender {
    [NSUserDefaults.standardUserDefaults setObject:sender.representedObject forKey:@"bdsp_app_icon"];
    ApplyDockIcon();
}
- (BOOL)validateMenuItem:(NSMenuItem *)item {
    if (item.action == @selector(togglePause:)) item.state = g_user_paused ? NSControlStateValueOn : NSControlStateValueOff;
    if (item.action == @selector(setFps:)) item.state = item.tag == g_bdsp_fps ? NSControlStateValueOn : NSControlStateValueOff;
    if (item.action == @selector(toggleMetalHud:)) item.state = [[NSUserDefaults standardUserDefaults] boolForKey:@"bdsp_metal_hud"] ? NSControlStateValueOn : NSControlStateValueOff;
    if (item.action == @selector(selectAppIcon:)) {
        NSString *selected = BDSPIconSelection(BDSPReadIcons([NSString stringWithUTF8String:g_app.resources]));
        item.state = [item.representedObject isEqualToString:selected] ? NSControlStateValueOn : NSControlStateValueOff;
    }
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
    // App menu
    NSMenuItem *ai = [bar addItemWithTitle:@"" action:nil keyEquivalent:@""];
    NSMenu *am = [[NSMenu alloc] initWithTitle:name];
    ai.submenu = am;
    item(am, L("About BDSP"), @selector(orderFrontStandardAboutPanel:), @"", 0, NSApp);
    NSMenuItem *iconItem = [am addItemWithTitle:L("App icon") action:nil keyEquivalent:@""];
    NSMenu *iconMenu = [[NSMenu alloc] initWithTitle:iconItem.title];
    iconItem.submenu = iconMenu;
    NSMenuItem *defaultIcon = item(iconMenu, L("Default (English)"), @selector(selectAppIcon:), @"", 0, g_target);
    defaultIcon.representedObject = @"default";
    NSDictionary *icons = BDSPReadIcons([NSString stringWithUTF8String:g_app.resources]);
    NSDictionary *recommended = BDSPRecommendedIcon(icons, NSLocale.preferredLanguages);
    NSDictionary *standardIcon = BDSPFindIcon(icons, @"default");
    if (standardIcon && ![icons[@"default"] hasPrefix:@"en-"])
        defaultIcon.title = [NSString stringWithFormat:@"%@ (%@)", L("Default"), standardIcon[@"label"]];
    for (NSDictionary *variant in icons[@"variants"]) {
        NSString *label = variant[@"label"];
        if ([variant[@"id"] isEqual:recommended[@"id"]]) label = [label stringByAppendingString:L(" (recommended)")];
        NSMenuItem *entry = item(iconMenu, label, @selector(selectAppIcon:), @"", 0, g_target);
        entry.representedObject = variant[@"id"];
        entry.image = [[NSImage alloc] initWithContentsOfFile:[[[NSString stringWithUTF8String:g_app.resources] stringByAppendingPathComponent:@"AppIcons"] stringByAppendingPathComponent:variant[@"mac_image"] ?: variant[@"image"]]];
        entry.image.size = NSMakeSize(24, 24);
    }
    ApplyDockIcon();
    [am addItem:[NSMenuItem separatorItem]];
    item(am, L("Hide BDSP"), @selector(hide:), @"h", NSEventModifierFlagCommand, NSApp);
    item(am, L("Hide Others"), @selector(hideOtherApplications:), @"h", NSEventModifierFlagCommand | NSEventModifierFlagOption, NSApp);
    item(am, L("Show All"), @selector(unhideAllApplications:), @"", 0, NSApp);
    [am addItem:[NSMenuItem separatorItem]];
    item(am, L("Quit BDSP"), @selector(terminate:), @"q", NSEventModifierFlagCommand, NSApp);
    // Game
    NSMenuItem *gi = [bar addItemWithTitle:@"" action:nil keyEquivalent:@""];
    NSMenu *gm = [[NSMenu alloc] initWithTitle:L("Game")];
    gi.submenu = gm;
    item(gm, L("Open Save Folder"), @selector(openSave:), @"o", NSEventModifierFlagCommand, g_target);
    item(gm, L("Import Save …"), @selector(importSave:), @"i", NSEventModifierFlagCommand, g_target);
    [gm addItem:[NSMenuItem separatorItem]];
    item(gm, L("Pause"), @selector(togglePause:), @"p", NSEventModifierFlagCommand, g_target);
    item(gm, L("Restart"), @selector(restart:), @"r", NSEventModifierFlagCommand, g_target);
    item(gm, L("Reset Game …"), @selector(resetSave:), @"r", NSEventModifierFlagCommand | NSEventModifierFlagShift, g_target);
    // View
    NSMenuItem *vi = [bar addItemWithTitle:@"" action:nil keyEquivalent:@""];
    NSMenu *vm = [[NSMenu alloc] initWithTitle:L("View")];
    vi.submenu = vm;
    item(vm, L("Full Screen"), @selector(toggleFullscreen:), @"f", NSEventModifierFlagCommand, g_target);
    NSMenuItem *fi = [vm addItemWithTitle:L("Frame Rate") action:nil keyEquivalent:@""];
    NSMenu *fm = [[NSMenu alloc] initWithTitle:L("Frame Rate")];
    fi.submenu = fm;
    for (NSNumber *f in @[@30, @60, @120]) {
        NSMenuItem *it = item(fm, [NSString stringWithFormat:@"%@ fps", f], @selector(setFps:), @"", 0, g_target);
        it.tag = f.integerValue;
    }
    NSInteger savedFps = [[NSUserDefaults standardUserDefaults] integerForKey:@"bdsp_fps"];
    if (savedFps && !getenv("BDSP_FPS")) bdsp_set_fps((int)savedFps);
    [vm addItem:[NSMenuItem separatorItem]];
    static const int sizes[4][2] = {{960, 540}, {1280, 720}, {1920, 1080}, {2560, 1440}};
    for (int i = 0; i < 4; i++) {
        NSMenuItem *it = item(vm, [NSString stringWithFormat:L("Window Size %d × %d"), sizes[i][0], sizes[i][1]], @selector(windowSize:),
                              [NSString stringWithFormat:@"%d", i + 1], NSEventModifierFlagCommand, g_target);
        it.tag = (NSInteger)sizes[i][0] << 16 | sizes[i][1];
    }
    [vm addItem:[NSMenuItem separatorItem]];
    NSMenuItem *di = [vm addItemWithTitle:L("Debug") action:nil keyEquivalent:@""];
    NSMenu *dm = [[NSMenu alloc] initWithTitle:L("Debug")];
    di.submenu = dm;
    item(dm, L("Show Metal HUD"), @selector(toggleMetalHud:), @"", 0, g_target);
    // Window
    NSMenuItem *wi = [bar addItemWithTitle:@"" action:nil keyEquivalent:@""];
    NSMenu *wm = [[NSMenu alloc] initWithTitle:L("Window")];
    wi.submenu = wm;
    item(wm, L("Minimize"), @selector(performMiniaturize:), @"m", NSEventModifierFlagCommand, nil);
    [NSApp setWindowsMenu:wm];
    // Help
    NSMenuItem *hi = [bar addItemWithTitle:@"" action:nil keyEquivalent:@""];
    NSMenu *hm = [[NSMenu alloc] initWithTitle:L("Help")];
    hi.submenu = hm;
    item(hm, L("Key Bindings …"), @selector(showKeys:), @"", 0, g_target);
    item(hm, L("Show Configuration File"), @selector(showConfig:), @"", 0, g_target);
    item(hm, L("Open Cache Folder (Shaders, Images)"), @selector(openCache:), @"", 0, g_target);
    item(hm, L("Open Log Folder"), @selector(openLogs:), @"", 0, g_target);
    [NSApp setMainMenu:bar];
    [NSApp setHelpMenu:hm];
    if (getenv("BDSP_MENU_DUMP")) {   // check of the menu structure without looking at the screen
        for (NSMenuItem *top in bar.itemArray) {
            fprintf(stderr, "[menu] %s\n", top.submenu.title.UTF8String);
            for (NSMenuItem *it in top.submenu.itemArray)
                if (!it.separatorItem) fprintf(stderr, "[menu]   %s [%s%s%s%s]\n", it.title.UTF8String,
                                               (it.keyEquivalentModifierMask & NSEventModifierFlagCommand) ? "Cmd+" : "",
                                               (it.keyEquivalentModifierMask & NSEventModifierFlagShift) ? "Shift+" : "",
                                               (it.keyEquivalentModifierMask & NSEventModifierFlagOption) ? "Option+" : "", it.keyEquivalent.UTF8String);
        }
    }
}

// ---- Hooks of the window loop (metal.m ui_run)
// Events for the on-screen keyboard (swkbd_ui.c): typed text, editing keys, mouse and touch. Returns true when consumed.
static bool swkbd_event(const SDL_Event *e) {
    switch (e->type) {
    case SDL_EVENT_TEXT_INPUT: swkbd_ui_text(e->text.text); return true;
    case SDL_EVENT_KEY_DOWN:
        if (e->key.mod & SDL_KMOD_GUI) return false;
        switch (e->key.scancode) {
        case SDL_SCANCODE_BACKSPACE: swkbd_ui_key(SWKBD_KEY_BACKSPACE); break;
        case SDL_SCANCODE_DELETE: swkbd_ui_key(SWKBD_KEY_DELETE); break;
        case SDL_SCANCODE_LEFT: swkbd_ui_key(SWKBD_KEY_LEFT); break;
        case SDL_SCANCODE_RIGHT: swkbd_ui_key(SWKBD_KEY_RIGHT); break;
        case SDL_SCANCODE_HOME: swkbd_ui_key(SWKBD_KEY_HOME); break;
        case SDL_SCANCODE_END: swkbd_ui_key(SWKBD_KEY_END); break;
        case SDL_SCANCODE_RETURN: case SDL_SCANCODE_KP_ENTER: swkbd_ui_key(SWKBD_KEY_ENTER); break;
        case SDL_SCANCODE_ESCAPE: swkbd_ui_key(SWKBD_KEY_ESCAPE); break;
        default: break;
        }
        return true;
    case SDL_EVENT_KEY_UP: return !(e->key.mod & SDL_KMOD_GUI);
    case SDL_EVENT_MOUSE_BUTTON_DOWN: {
        SDL_Window *w = ui_window();
        int ww = 0, wh = 0;
        if (w) SDL_GetWindowSize(w, &ww, &wh);
        if (e->button.button == SDL_BUTTON_LEFT && ww > 0 && wh > 0) swkbd_ui_touch(1, e->button.x / ww, e->button.y / wh);
        return true;
    }
    case SDL_EVENT_MOUSE_BUTTON_UP: {
        SDL_Window *w = ui_window();
        int ww = 0, wh = 0;
        if (w) SDL_GetWindowSize(w, &ww, &wh);
        if (e->button.button == SDL_BUTTON_LEFT && ww > 0 && wh > 0) swkbd_ui_touch(0, e->button.x / ww, e->button.y / wh);
        return true;
    }
    case SDL_EVENT_FINGER_DOWN: swkbd_ui_touch(1, e->tfinger.x, e->tfinger.y); return true;
    case SDL_EVENT_FINGER_UP: swkbd_ui_touch(0, e->tfinger.x, e->tfinger.y); return true;
    case SDL_EVENT_FINGER_CANCELED: swkbd_ui_touch(-1, e->tfinger.x, e->tfinger.y); return true;
    default: return false;
    }
}

bool menu_handle_event(const SDL_Event *e) {
    if (swkbd_ui_active() && swkbd_event(e)) return true;
    switch (e->type) {
    case SDL_EVENT_KEY_DOWN: case SDL_EVENT_KEY_UP:
        if (e->key.mod & SDL_KMOD_GUI) return true;   // menu shortcuts (Cmd+…) belong to the menu
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

// ---- Key script for tests (BDSP_KEY_SCRIPT="second:KEY:duration,…" or "@file", counted from process start): feeds real SDL key events
// into the window loop, so through the same mapping as the keyboard (e.g. "62:Z:0.4,70:Up:2"; key names as in SDL_GetScancodeFromName)
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
        if (sc == SDL_SCANCODE_UNKNOWN) { fprintf(stderr, "[app] Key script: unknown key %s\n", name); continue; }
        g_ks[g_nks++] = (KeyStep){at, len, sc, false};
    }
    fprintf(stderr, "[app] Key script with %d steps\n", g_nks);
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

// ---- Self-test of the menu actions (BDSP_UI_SELFTEST="second:action,…", actions: fs, w960, w1280, w1920, w2560, pause, restart): calls the same
// methods as the menu items (without confirmation), because key shortcuts cannot be sent from outside (accessibility access not allowed)
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
            char title[300] = "BDSP";
            if (mods_active()) snprintf(title, sizeof title, "BDSP - %s", mods_active()->name);
            SDL_SetWindowTitle(w, title);
            SDL_SetWindowMinimumSize(w, 640, 360);
            if (g_app.fullscreen && !g_app.headless) SDL_SetWindowFullscreen(w, true);
            if (!g_app.headless) {
                // The window only now appears in the foreground (SDL shows it without activation)
                front();
            }
        }
    }
    @autoreleasepool { pad_poll(); }
    {   // on-screen keyboard: input moves over to it while it is open (and back, with all held keys released)
        static bool kb_was;
        bool kb = swkbd_ui_active();
        if (kb != kb_was) {
            kb_was = kb;
            memset(g_down, 0, sizeof g_down);
            if (kb) SDL_StartTextInput(window); else SDL_StopTextInput(window);
            publish();
        }
        if (kb) swkbd_ui_pad(g_pad_buttons, g_pad_stick[0], g_pad_stick[1]);
    }
    key_script_tick();
    // Self-test of the pause (BDSP_PAUSE_SELFTEST="<from second>:<duration>"): stops the vsync event and releases it again
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
