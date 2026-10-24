// iPadOS shell of the BDSP recompilation (memory model B): UIKit window with CAMetalLayer, touch gamepad, GameController, hardware keyboard,
// paths (Documents), save import, measurement lines. The runtime runs on a thread of its own (bdsp_runtime_main = main.c with -Dmain=...).
// PCM sound through Audio Queue Services and AVAudioSession. Own code.
#import <AVFAudio/AVFAudio.h>
#import <GameController/GameController.h>
#import <QuartzCore/CAMetalLayer.h>
#import <UIKit/UIKit.h>
#import <os/proc.h>
#include <CommonCrypto/CommonDigest.h>
#include <mach/mach.h>
#include <pthread.h>
#include <stdatomic.h>
#include <signal.h>
#include <sys/stat.h>
#include <sys/sysctl.h>
#import <Metal/Metal.h>
#import "../../app/icon_variants.h"
#include <strings.h>
#include "../../rt-bdsp/mods.h"
#include "../../rt-bdsp/swkbd_ui.h"

static BOOL sceneActive;   // state of the scene, set by SceneDelegate

static void ApplyAppIcon(void) {
    static BOOL pending;
    UIApplication *app = UIApplication.sharedApplication;
    if (pending || !app.supportsAlternateIcons || !sceneActive) return;
    NSDictionary *icons = BDSPReadIcons(NSBundle.mainBundle.resourcePath);
    NSDictionary *variant = BDSPFindIcon(icons, BDSPIconSelection(icons));
    if (!variant) return;
    NSString *name = [variant[@"icon"] isEqual:icons[@"primary_icon"]] ? nil : variant[@"icon"];
    if ((!name && !app.alternateIconName) || [name isEqualToString:app.alternateIconName]) return;
    pending = YES;
    [app setAlternateIconName:name completionHandler:^(NSError *error) {
        if (error) fprintf(stderr, "[icon] Icon change failed: %s\n", error.localizedDescription.UTF8String);
        dispatch_async(dispatch_get_main_queue(), ^{ pending = NO; });
    }];
}

extern int bdsp_runtime_main(int argc, char **argv);
#ifndef BDSP_STUB
extern void audio_output_set_active(int active);
#else
static void audio_output_set_active(int active) { (void)active; }
#endif
extern void bdsp_set_fps(int fps);   // services_gfx.c: 30, 60 or 120
extern CAMetalLayer *g_ios_layer;
extern _Atomic uint64_t g_ext_buttons;
extern _Atomic int32_t g_ext_stick[4];

static double FootprintMiB(void);
static BOOL audioInterrupted;

static void SetAudioActive(BOOL active) {
    AVAudioSession *session = AVAudioSession.sharedInstance;
    NSError *error = nil;
    // Quiesce queues before deactivating the session. Guest completion keeps its clock.
    if (!active) audio_output_set_active(0);
    if (![session setActive:active error:&error]) {
        audio_output_set_active(0);
        fprintf(stderr, "[ipad-audio] Session: %s\n", error.localizedDescription.UTF8String);
        return;
    }
    if (active) audio_output_set_active(1);
}

static void ConfigureAudioSession(void) {
    NSError *error = nil;
    if (![AVAudioSession.sharedInstance setCategory:AVAudioSessionCategoryPlayback
                                              mode:AVAudioSessionModeDefault options:0 error:&error]) {
        fprintf(stderr, "[ipad-audio] Kategorie: %s\n", error.localizedDescription.UTF8String);
        audio_output_set_active(0);
        return;
    }
    SetAudioActive(sceneActive && !audioInterrupted);
}
#ifdef BDSP_STUB
// Probe build (deploy_ios.sh build-stub): without runtime and guest code; reports device data and checks the 4 GiB window on the device.
#import <Metal/Metal.h>
#include <sys/mman.h>
CAMetalLayer *g_ios_layer;
_Atomic uint64_t g_ext_buttons;
_Atomic int32_t g_ext_stick[4];
int bdsp_runtime_main(int argc, char **argv) {
    id<MTLDevice> d = MTLCreateSystemDefaultDevice();
    fprintf(stderr, "[probe] Metal %s, BC-Texturen %d, ASTC %d, maxBufferLength %llu MiB, recommendedMaxWorkingSetSize %llu MiB, hasUnifiedMemory %d, Apple9 %d\n",
            d.name.UTF8String, (int)d.supportsBCTextureCompression, (int)[d supportsFamily:MTLGPUFamilyApple4],
            (unsigned long long)(d.maxBufferLength >> 20), (unsigned long long)(d.recommendedMaxWorkingSetSize >> 20), (int)d.hasUnifiedMemory,
            (int)[d supportsFamily:MTLGPUFamilyApple9]);
    fprintf(stderr, "[probe] os_proc_available_memory %zu MiB\n", os_proc_available_memory() >> 20);
    size_t sizes[] = {4096ull << 20, 5200ull << 20, 6000ull << 20, 12800ull << 20};
    for (int i = 0; i < 4; i++) {
        void *p = mmap(NULL, sizes[i], PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANON, -1, 0);
        fprintf(stderr, "[probe] mmap %zu MiB anonymous: %s (%p)\n", sizes[i] >> 20, p == MAP_FAILED ? "ERROR" : "ok", p);
        if (p != MAP_FAILED) {
            void *b = NULL;
            if (sizes[i] <= (4096ull << 20) + (1ull << 30)) {
                id<MTLBuffer> mb = [d newBufferWithBytesNoCopy:p length:sizes[i] options:MTLResourceStorageModeShared deallocator:nil];
                b = (__bridge void *)mb;
                fprintf(stderr, "[probe]   Metal buffer around %zu MiB: %s\n", sizes[i] >> 20, mb ? "ok" : "ERROR");
            }
            (void)b;
            memset(p, 1, 256ull << 20);   // 256 MiB wirklich anfassen
            fprintf(stderr, "[probe]   256 MiB beschrieben, Footprint %.0f MiB, frei %zu MiB\n", FootprintMiB(), os_proc_available_memory() >> 20);
            munmap(p, sizes[i]);
        }
    }
    for (;;) sleep(60);
}
#endif

// Bits as in enum PB_* in nvn_glue.c
enum { PB_A, PB_B, PB_X, PB_Y, PB_LSTICK, PB_RSTICK, PB_L, PB_R, PB_ZL, PB_ZR, PB_PLUS, PB_MINUS, PB_LEFT, PB_UP, PB_RIGHT, PB_DOWN };
#define BIT(b) (1ull << (b))

static _Atomic uint64_t g_touch_mask, g_pad_mask, g_key_mask;
static void publish_buttons(void) {
    if (swkbd_ui_active()) {   // the on-screen keyboard has the input; the game sees no buttons meanwhile
        swkbd_ui_pad(atomic_load(&g_pad_mask), atomic_load(&g_ext_stick[0]), atomic_load(&g_ext_stick[1]));
        atomic_store(&g_ext_buttons, 0);
        return;
    }
    atomic_store(&g_ext_buttons, g_touch_mask | g_pad_mask | g_key_mask);
}
static void SwkbdShowNative(void);   // system keyboard for the text field of the on-screen keyboard (below)

#pragma mark - Paths, save

static NSString *Documents(void) { return NSSearchPathForDirectoriesInDomains(NSDocumentDirectory, NSUserDomainMask, YES).firstObject; }

static NSString *Sha256(NSData *d) {
    unsigned char h[CC_SHA256_DIGEST_LENGTH];
    CC_SHA256(d.bytes, (CC_LONG)d.length, h);
    NSMutableString *s = [NSMutableString string];
    for (int i = 0; i < CC_SHA256_DIGEST_LENGTH; i++) [s appendFormat:@"%02x", h[i]];
    return s;
}

// Take drop files in Documents/ (Files app, devicectl; devicectl creates folders as root, hence files only) over into Documents/Saves/save_1:
// SaveData.bin, Backup.bin, user_id.hex. An unchanged file (hash in Documents/ImportedDropIn.txt) is not imported again.
static void ImportSave(void) {
    NSFileManager *fm = NSFileManager.defaultManager;
    NSString *docs = Documents(), *slot = [docs stringByAppendingPathComponent:@"Saves/save_1"];
    NSData *drop = [NSData dataWithContentsOfFile:[docs stringByAppendingPathComponent:@"SaveData.bin"]];
    [fm createDirectoryAtPath:slot withIntermediateDirectories:YES attributes:nil error:nil];
    NSString *memo = [docs stringByAppendingPathComponent:@"ImportedDropIn.txt"];
    if (drop.length) {
        NSString *h = Sha256(drop), *old = [NSString stringWithContentsOfFile:memo encoding:NSUTF8StringEncoding error:nil];
        if (![h isEqualToString:old]) {
            NSString *cur = [slot stringByAppendingPathComponent:@"SaveData.bin"];
            if ([fm fileExistsAtPath:cur]) {
                NSString *bk = [docs stringByAppendingFormat:@"/Backups/%lld", (long long)NSDate.date.timeIntervalSince1970];
                [fm createDirectoryAtPath:bk withIntermediateDirectories:YES attributes:nil error:nil];
                [fm copyItemAtPath:cur toPath:[bk stringByAppendingPathComponent:@"SaveData.bin"] error:nil];
            }
            [drop writeToFile:cur atomically:YES];
            NSData *b = [NSData dataWithContentsOfFile:[docs stringByAppendingPathComponent:@"Backup.bin"]];
            if (b.length) [b writeToFile:[slot stringByAppendingPathComponent:@"Backup.bin"] atomically:YES];
            [h writeToFile:memo atomically:YES encoding:NSUTF8StringEncoding error:nil];
            fprintf(stderr, "[ipad] Save imported (%lu bytes, sha256 %s)\n", (unsigned long)drop.length, [h substringToIndex:12].UTF8String);
        }
    }
    NSString *uid = [docs stringByAppendingPathComponent:@"user_id.hex"];
    if ([fm fileExistsAtPath:uid]) {
        NSString *dst = [[docs stringByAppendingPathComponent:@"Saves"] stringByAppendingPathComponent:@"user_id.hex"];
        [fm removeItemAtPath:dst error:nil];
        [fm copyItemAtPath:uid toPath:dst error:nil];
    }
}

#pragma mark - Measurement lines

static double FootprintMiB(void) {
    task_vm_info_data_t v;
    mach_msg_type_number_t n = TASK_VM_INFO_COUNT;
    if (task_info(mach_task_self(), TASK_VM_INFO, (task_info_t)&v, &n) != KERN_SUCCESS) return -1;
    return v.phys_footprint / 1048576.0;
}

// BDSP_PROBE_FIXED=1 (diagnostic, off by default): device data (memory, cores, GPU features) and the question whether a fixed window of
// 12.5 GiB can be reserved at a chosen address. Prints one line per candidate and ends the app. The result decides whether guest address
// == host address (memory model A-low) is possible on a device, and whether the GPU can run the game at all (BC textures, buffer size).
static long SysctlLong(const char *name) {
    int64_t v = 0;
    size_t n = sizeof v;
    return sysctlbyname(name, &v, &n, NULL, 0) == 0 ? (long)v : -1;
}

static void ProbeFixedWindows(void) {
    id<MTLDevice> d = MTLCreateSystemDefaultDevice();
    fprintf(stderr, "[probe-fixed] device %s, RAM %ld MiB, CPU cores %ld (performance %ld, efficiency %ld)\n", d.name.UTF8String,
            SysctlLong("hw.memsize") >> 20, SysctlLong("hw.physicalcpu"), SysctlLong("hw.perflevel0.physicalcpu"), SysctlLong("hw.perflevel1.physicalcpu"));
    fprintf(stderr, "[probe-fixed] GPU: BC textures %d, maxBufferLength %llu MiB, recommendedMaxWorkingSetSize %llu MiB, Apple7 %d, Apple8 %d, Apple9 %d\n",
            (int)d.supportsBCTextureCompression, (unsigned long long)(d.maxBufferLength >> 20),
            (unsigned long long)(d.recommendedMaxWorkingSetSize >> 20), (int)[d supportsFamily:MTLGPUFamilyApple7],
            (int)[d supportsFamily:MTLGPUFamilyApple8], (int)[d supportsFamily:MTLGPUFamilyApple9]);
    static const vm_address_t cand[] = {0x100000000ull, 0x200000000ull, 0x300000000ull, 0x400000000ull, 0x500000000ull, 0x600000000ull,
                                        0x700000000ull, 0x800000000ull, 0x900000000ull, 0xA00000000ull, 0xC00000000ull,
                                        0x1000000000ull, 0x2000000000ull, 0x7000000000ull};
    fprintf(stderr, "[probe-fixed] os_proc_available_memory %zu MiB\n", os_proc_available_memory() >> 20);
    for (size_t i = 0; i < 2 * (sizeof cand / sizeof *cand); i++) {   // first the compact window of model A-low (4 GiB), then the Mac-sized one
        const vm_size_t size = (i < sizeof cand / sizeof *cand ? 4096ull : 12800ull) << 20;
        vm_address_t a = cand[i % (sizeof cand / sizeof *cand)];
        kern_return_t kr = vm_allocate(mach_task_self(), &a, size, VM_FLAGS_FIXED);
        fprintf(stderr, "[probe-fixed] %#llx + %llu MiB: %s (kr %d)\n", (unsigned long long)cand[i % (sizeof cand / sizeof *cand)], (unsigned long long)(size >> 20),
                kr == KERN_SUCCESS ? "ok" : "ERROR", kr);
        if (kr == KERN_SUCCESS) {
            memset((void *)a, 1, 64ull << 20);   // really touch some pages
            vm_deallocate(mach_task_self(), a, size);
        }
    }
    fprintf(stderr, "[probe-fixed] done\n");
    exit(0);
}

static void *StatsLoop(void *arg) {
    (void)arg;
    pthread_setname_np("bdsp-stats");
    NSTimeInterval t0 = NSProcessInfo.processInfo.systemUptime;
    for (;;) {
        sleep(5);
        fprintf(stderr, "[ipad] t=%.0f s Footprint %.0f MiB, free per os_proc_available_memory %zu MiB, thermalState %ld, lowPower %d\n",
                NSProcessInfo.processInfo.systemUptime - t0, FootprintMiB(), os_proc_available_memory() >> 20,
                (long)NSProcessInfo.processInfo.thermalState, (int)NSProcessInfo.processInfo.lowPowerModeEnabled);
        if (getenv("BDSP_AUDIO_PROBE")) {
            AVAudioSession *s = AVAudioSession.sharedInstance;
            fprintf(stderr, "[ipad-audio] category %s, other audio playing %d, volume %.2f\n", s.category.UTF8String,
                    (int)s.isOtherAudioPlaying, s.outputVolume);
        }
    }
    return NULL;
}

#pragma mark - Spielansicht

@interface GameView : UIView
@property(nonatomic, strong) NSMutableArray<CALayer *> *pads;
@property(nonatomic) CGPoint dpadC, abxyC;
@property(nonatomic) CGFloat dpadR, btnR, btnOff;
@property(nonatomic) CGRect lRect, rRect, zlRect, zrRect, minusRect, plusRect;
@property(nonatomic) BOOL overlayHidden;
@end

@implementation GameView
+ (Class)layerClass { return CAMetalLayer.class; }

- (instancetype)initWithFrame:(CGRect)f {
    if ((self = [super initWithFrame:f])) {
        self.multipleTouchEnabled = YES;
        self.backgroundColor = UIColor.blackColor;
        CAMetalLayer *l = (CAMetalLayer *)self.layer;
        l.opaque = YES;
        g_ios_layer = l;
    }
    return self;
}

- (void)layoutSubviews {
    [super layoutSubviews];
    CAMetalLayer *l = (CAMetalLayer *)self.layer;
    CGFloat sc = self.traitCollection.displayScale;
    l.contentsScale = sc;
    l.drawableSize = CGSizeMake(self.bounds.size.width * sc, self.bounds.size.height * sc);
    CGRect b = self.bounds;
    UIEdgeInsets sa = self.safeAreaInsets;
    CGFloat m = 28, s = MIN(b.size.width, b.size.height);
    self.dpadR = s * 0.15;
    self.btnR = s * 0.055;
    self.btnOff = s * 0.095;
    self.dpadC = CGPointMake(sa.left + m + self.dpadR * 1.2, b.size.height - sa.bottom - m - self.dpadR * 1.2);
    self.abxyC = CGPointMake(b.size.width - sa.right - m - self.btnOff - self.btnR * 1.2, b.size.height - sa.bottom - m - self.btnOff - self.btnR * 1.2);
    CGFloat pw = s * 0.17, ph = s * 0.06;
    self.lRect = CGRectMake(sa.left + m, sa.top + m, pw, ph);
    self.zlRect = CGRectMake(sa.left + m, sa.top + m + ph + 10, pw, ph);
    self.rRect = CGRectMake(b.size.width - sa.right - m - pw, sa.top + m, pw, ph);
    self.zrRect = CGRectMake(b.size.width - sa.right - m - pw, sa.top + m + ph + 10, pw, ph);
    CGFloat cx = b.size.width / 2, by = b.size.height - sa.bottom - m - ph / 2;
    self.minusRect = CGRectMake(cx - 20 - pw * 0.5, by - ph / 2, pw * 0.5, ph);
    self.plusRect = CGRectMake(cx + 20, by - ph / 2, pw * 0.5, ph);
    [self buildOverlay];
}

- (void)addShape:(UIBezierPath *)p fill:(CGFloat)a {
    CAShapeLayer *s = [CAShapeLayer layer];
    s.path = p.CGPath;
    s.fillColor = [UIColor colorWithWhite:1 alpha:a].CGColor;
    s.strokeColor = [UIColor colorWithWhite:1 alpha:0.5].CGColor;
    s.lineWidth = 2;
    [self.layer addSublayer:s];
    [self.pads addObject:s];
}

- (void)addLabel:(NSString *)t at:(CGPoint)c size:(CGFloat)sz {
    CATextLayer *tl = [CATextLayer layer];
    tl.string = t;
    tl.fontSize = sz;
    tl.alignmentMode = kCAAlignmentCenter;
    tl.foregroundColor = [UIColor colorWithWhite:1 alpha:0.8].CGColor;
    tl.contentsScale = self.traitCollection.displayScale;
    tl.frame = CGRectMake(c.x - 40, c.y - sz * 0.6, 80, sz * 1.3);
    [self.layer addSublayer:tl];
    [self.pads addObject:(CAShapeLayer *)tl];
}

- (void)buildOverlay {
    for (CALayer *l in self.pads) [l removeFromSuperlayer];
    self.pads = [NSMutableArray array];
    if (self.overlayHidden) return;
    CGFloat r = self.dpadR, w = r * 0.62;
    UIBezierPath *cross = [UIBezierPath bezierPath];
    CGPoint c = self.dpadC;
    [cross appendPath:[UIBezierPath bezierPathWithRoundedRect:CGRectMake(c.x - r, c.y - w / 2, 2 * r, w) cornerRadius:w / 4]];
    [cross appendPath:[UIBezierPath bezierPathWithRoundedRect:CGRectMake(c.x - w / 2, c.y - r, w, 2 * r) cornerRadius:w / 4]];
    [self addShape:cross fill:0.12];
    struct { NSString *n; CGFloat dx, dy; } bt[4] = {{@"A", 1, 0}, {@"B", 0, 1}, {@"X", 0, -1}, {@"Y", -1, 0}};
    for (int i = 0; i < 4; i++) {
        CGPoint p = CGPointMake(self.abxyC.x + bt[i].dx * self.btnOff, self.abxyC.y + bt[i].dy * self.btnOff);
        [self addShape:[UIBezierPath bezierPathWithOvalInRect:CGRectMake(p.x - self.btnR, p.y - self.btnR, 2 * self.btnR, 2 * self.btnR)] fill:0.12];
        [self addLabel:bt[i].n at:p size:self.btnR * 0.9];
    }
    struct { CGRect r; NSString *n; } pl[6] = {{self.lRect, @"L"}, {self.rRect, @"R"}, {self.zlRect, @"ZL"}, {self.zrRect, @"ZR"}, {self.minusRect, @"−"}, {self.plusRect, @"+"}};
    for (int i = 0; i < 6; i++) {
        [self addShape:[UIBezierPath bezierPathWithRoundedRect:pl[i].r cornerRadius:pl[i].r.size.height / 2] fill:0.12];
        [self addLabel:pl[i].n at:CGPointMake(CGRectGetMidX(pl[i].r), CGRectGetMidY(pl[i].r)) size:pl[i].r.size.height * 0.5];
    }
}

- (uint64_t)maskForPoint:(CGPoint)p {
    uint64_t m = 0;
    CGFloat dx = p.x - self.dpadC.x, dy = p.y - self.dpadC.y, d = hypot(dx, dy);
    if (d > self.dpadR * 0.25 && d < self.dpadR * 1.6) {
        if (dx < -0.38 * d) m |= BIT(PB_LEFT);
        if (dx > 0.38 * d) m |= BIT(PB_RIGHT);
        if (dy < -0.38 * d) m |= BIT(PB_UP);
        if (dy > 0.38 * d) m |= BIT(PB_DOWN);
    }
    struct { int bit; CGFloat dx, dy; } bt[4] = {{PB_A, 1, 0}, {PB_B, 0, 1}, {PB_X, 0, -1}, {PB_Y, -1, 0}};
    for (int i = 0; i < 4; i++)
        if (hypot(p.x - (self.abxyC.x + bt[i].dx * self.btnOff), p.y - (self.abxyC.y + bt[i].dy * self.btnOff)) < self.btnR * 1.25) m |= BIT(bt[i].bit);
    struct { int bit; CGRect r; } pl[6] = {{PB_L, self.lRect}, {PB_R, self.rRect}, {PB_ZL, self.zlRect}, {PB_ZR, self.zrRect}, {PB_MINUS, self.minusRect}, {PB_PLUS, self.plusRect}};
    for (int i = 0; i < 6; i++)
        if (CGRectContainsPoint(CGRectInset(pl[i].r, -14, -14), p)) m |= BIT(pl[i].bit);
    return m;
}

- (void)updateTouches:(NSSet<UITouch *> *)all ending:(NSSet<UITouch *> *)ending {
    uint64_t m = 0;
    for (UITouch *t in all) {
        if ([ending containsObject:t] || t.phase == UITouchPhaseEnded || t.phase == UITouchPhaseCancelled) continue;
        m |= [self maskForPoint:[t locationInView:self]];
    }
    atomic_store(&g_touch_mask, m);
    publish_buttons();
}
// While the on-screen keyboard is open a touch goes to it (a key, or the text field, which brings up the system keyboard), not to the game
// phase: 1 began, 0 ended, -1 cancelled (a moving finger changes nothing until it is lifted)
- (BOOL)swkbdTouches:(NSSet<UITouch *> *)t phase:(int)phase {
    if (!swkbd_ui_active()) return NO;
    CGPoint p = [t.anyObject locationInView:self];
    float nx = (float)(p.x / self.bounds.size.width), ny = (float)(p.y / self.bounds.size.height);
    if (phase == 1 && swkbd_ui_field_hit(nx, ny)) SwkbdShowNative(); else if (phase != 2) swkbd_ui_touch(phase, nx, ny);
    return YES;
}
- (void)touchesBegan:(NSSet<UITouch *> *)t withEvent:(UIEvent *)e { if ([self swkbdTouches:t phase:1]) return; [self updateTouches:e.allTouches ending:nil]; }
- (void)touchesMoved:(NSSet<UITouch *> *)t withEvent:(UIEvent *)e { if ([self swkbdTouches:t phase:2]) return; [self updateTouches:e.allTouches ending:nil]; }
- (void)touchesEnded:(NSSet<UITouch *> *)t withEvent:(UIEvent *)e { if ([self swkbdTouches:t phase:0]) return; [self updateTouches:e.allTouches ending:t]; }
- (void)touchesCancelled:(NSSet<UITouch *> *)t withEvent:(UIEvent *)e { if ([self swkbdTouches:t phase:-1]) return; [self updateTouches:e.allTouches ending:t]; }
@end

#pragma mark - Controller, Tastatur

static void BindController(GCController *c) {
    GCExtendedGamepad *g = c.extendedGamepad;
    if (!g) return;
    __weak GCExtendedGamepad *wg = g;
    // Button layout of the console (by position): A = right, B = bottom, X = top, Y = left; GameController calls the bottom one "A"
    void (^update)(void) = ^{
        GCExtendedGamepad *p = wg;
        if (!p) return;
        uint64_t m = 0;
        if (p.buttonB.pressed) m |= BIT(PB_A);
        if (p.buttonA.pressed) m |= BIT(PB_B);
        if (p.buttonY.pressed) m |= BIT(PB_X);
        if (p.buttonX.pressed) m |= BIT(PB_Y);
        if (p.leftShoulder.pressed) m |= BIT(PB_L);
        if (p.rightShoulder.pressed) m |= BIT(PB_R);
        if (p.leftTrigger.pressed) m |= BIT(PB_ZL);
        if (p.rightTrigger.pressed) m |= BIT(PB_ZR);
        if (p.buttonMenu.pressed) m |= BIT(PB_PLUS);
        if (p.buttonOptions.pressed) m |= BIT(PB_MINUS);
        if (p.leftThumbstickButton.pressed) m |= BIT(PB_LSTICK);
        if (p.rightThumbstickButton.pressed) m |= BIT(PB_RSTICK);
        if (p.dpad.left.pressed) m |= BIT(PB_LEFT);
        if (p.dpad.right.pressed) m |= BIT(PB_RIGHT);
        if (p.dpad.up.pressed) m |= BIT(PB_UP);
        if (p.dpad.down.pressed) m |= BIT(PB_DOWN);
        atomic_store(&g_pad_mask, m);
        atomic_store(&g_ext_stick[0], (int32_t)(p.leftThumbstick.xAxis.value * 32767));
        atomic_store(&g_ext_stick[1], (int32_t)(p.leftThumbstick.yAxis.value * 32767));
        atomic_store(&g_ext_stick[2], (int32_t)(p.rightThumbstick.xAxis.value * 32767));
        atomic_store(&g_ext_stick[3], (int32_t)(p.rightThumbstick.yAxis.value * 32767));
        publish_buttons();
    };
    g.valueChangedHandler = ^(GCExtendedGamepad *p, GCControllerElement *e) { update(); };
}

static int KeyBit(UIKeyboardHIDUsage k) {
    switch (k) {
    case UIKeyboardHIDUsageKeyboardReturnOrEnter: case UIKeyboardHIDUsageKeyboardSpacebar: case UIKeyboardHIDUsageKeyboardK: return PB_A;
    case UIKeyboardHIDUsageKeyboardDeleteOrBackspace: case UIKeyboardHIDUsageKeyboardJ: return PB_B;
    case UIKeyboardHIDUsageKeyboardX: return PB_X;
    case UIKeyboardHIDUsageKeyboardY: return PB_Y;
    case UIKeyboardHIDUsageKeyboardQ: return PB_L;
    case UIKeyboardHIDUsageKeyboardE: return PB_R;
    case UIKeyboardHIDUsageKeyboardP: return PB_PLUS;
    case UIKeyboardHIDUsageKeyboardO: return PB_MINUS;
    case UIKeyboardHIDUsageKeyboardLeftArrow: case UIKeyboardHIDUsageKeyboardA: return PB_LEFT;
    case UIKeyboardHIDUsageKeyboardRightArrow: case UIKeyboardHIDUsageKeyboardD: return PB_RIGHT;
    case UIKeyboardHIDUsageKeyboardUpArrow: case UIKeyboardHIDUsageKeyboardW: return PB_UP;
    case UIKeyboardHIDUsageKeyboardDownArrow: case UIKeyboardHIDUsageKeyboardS: return PB_DOWN;
    default: return -1;
    }
}

static GameView *gView;   // game view of the scene (controller overlay)

#pragma mark - Screen keyboard (text entry)

// System keyboard: a hidden text field becomes first responder when the text field of the on-screen keyboard is tapped; what is typed goes to
// swkbd_ui (the field itself stays empty). Hardware keyboards type directly (GameVC pressesBegan).
@interface SwkbdNativeField : NSObject <UITextFieldDelegate>
@end
static UITextField *gNativeField;
static SwkbdNativeField *gNativeDelegate;
@implementation SwkbdNativeField
- (BOOL)textField:(UITextField *)f shouldChangeCharactersInRange:(NSRange)r replacementString:(NSString *)s {
    if (s.length == 0) swkbd_ui_key(SWKBD_KEY_BACKSPACE); else swkbd_ui_text(s.UTF8String);
    return NO;
}
- (BOOL)textFieldShouldReturn:(UITextField *)f { swkbd_ui_key(SWKBD_KEY_ENTER); return NO; }
@end

static void SwkbdShowNative(void) {
    if (!gNativeField) {
        gNativeDelegate = [SwkbdNativeField new];
        gNativeField = [[UITextField alloc] initWithFrame:CGRectMake(0, 0, 1, 1)];
        gNativeField.alpha = 0.02;
        gNativeField.delegate = gNativeDelegate;
        gNativeField.autocorrectionType = UITextAutocorrectionTypeNo;
        gNativeField.autocapitalizationType = UITextAutocapitalizationTypeNone;
        gNativeField.returnKeyType = UIReturnKeyDone;
        [gView addSubview:gNativeField];
    }
    [gNativeField becomeFirstResponder];
}

static void SwkbdHideNative(void) {
    if (gNativeField.isFirstResponder) {
        [gNativeField resignFirstResponder];
        [gView.window.rootViewController becomeFirstResponder];   // hardware keys again
    }
}

// Called a few times per second: hides the touch gamepad while the on-screen keyboard is open and puts the system keyboard away when it closes
static void SwkbdPoll(void) {
    static BOOL was;
    BOOL on = swkbd_ui_active() != 0;
    if (on == was) return;
    was = on;
    for (CALayer *l in gView.pads) l.hidden = on;
    if (!on) SwkbdHideNative();
    publish_buttons();
}

static BOOL SwkbdPresses(NSSet<UIPress *> *presses) {
    BOOL handled = NO;
    for (UIPress *p in presses) {
        UIKey *k = p.key;
        if (!k) continue;
        handled = YES;
        switch (k.keyCode) {
        case UIKeyboardHIDUsageKeyboardDeleteOrBackspace: swkbd_ui_key(SWKBD_KEY_BACKSPACE); continue;
        case UIKeyboardHIDUsageKeyboardDeleteForward: swkbd_ui_key(SWKBD_KEY_DELETE); continue;
        case UIKeyboardHIDUsageKeyboardReturnOrEnter: case UIKeyboardHIDUsageKeypadEnter: swkbd_ui_key(SWKBD_KEY_ENTER); continue;
        case UIKeyboardHIDUsageKeyboardEscape: swkbd_ui_key(SWKBD_KEY_ESCAPE); continue;
        case UIKeyboardHIDUsageKeyboardLeftArrow: swkbd_ui_key(SWKBD_KEY_LEFT); continue;
        case UIKeyboardHIDUsageKeyboardRightArrow: swkbd_ui_key(SWKBD_KEY_RIGHT); continue;
        case UIKeyboardHIDUsageKeyboardHome: swkbd_ui_key(SWKBD_KEY_HOME); continue;
        case UIKeyboardHIDUsageKeyboardEnd: swkbd_ui_key(SWKBD_KEY_END); continue;
        default: break;
        }
        if (k.modifierFlags & (UIKeyModifierCommand | UIKeyModifierControl)) continue;
        NSString *c = k.characters;
        unichar first = c.length ? [c characterAtIndex:0] : 0;
        if (first >= 0x20 && !(first >= 0xF700 && first <= 0xF8FF)) swkbd_ui_text(c.UTF8String);   // not the function key codes of UIKit
    }
    return handled;
}

#pragma mark - App


@interface SceneDelegate : UIResponder <UIWindowSceneDelegate>
@property(nonatomic, strong) UIWindow *window;
- (void)startRuntime;
@end

@interface GameVC : UIViewController
@end

@implementation GameVC
- (void)loadView { gView = [[GameView alloc] initWithFrame:CGRectZero]; self.view = gView; }
- (BOOL)prefersStatusBarHidden { return YES; }
- (BOOL)prefersHomeIndicatorAutoHidden { return YES; }
- (UIInterfaceOrientationMask)supportedInterfaceOrientations { return UIInterfaceOrientationMaskLandscape; }
- (BOOL)canBecomeFirstResponder { return YES; }
- (void)viewDidAppear:(BOOL)a {
    [super viewDidAppear:a];
    [self becomeFirstResponder];
    static dispatch_once_t once;
    dispatch_once(&once, ^{
        [(SceneDelegate *)self.view.window.windowScene.delegate startRuntime];
        [NSTimer scheduledTimerWithTimeInterval:0.15 repeats:YES block:^(NSTimer *t) { SwkbdPoll(); }];
    });
}
- (void)pressesBegan:(NSSet<UIPress *> *)presses withEvent:(UIPressesEvent *)e {
    if (swkbd_ui_active() && SwkbdPresses(presses)) return;   // typing into the on-screen keyboard
    BOOL handled = NO;
    for (UIPress *p in presses) {
        int b = p.key ? KeyBit(p.key.keyCode) : -1;
        if (b >= 0) { atomic_fetch_or(&g_key_mask, BIT(b)); handled = YES; }
    }
    publish_buttons();
    if (!handled) [super pressesBegan:presses withEvent:e];
}
- (void)pressesEnded:(NSSet<UIPress *> *)presses withEvent:(UIPressesEvent *)e {
    for (UIPress *p in presses) {
        int b = p.key ? KeyBit(p.key.keyCode) : -1;
        if (b >= 0) atomic_fetch_and(&g_key_mask, ~BIT(b));
    }
    publish_buttons();
}
- (void)pressesCancelled:(NSSet<UIPress *> *)presses withEvent:(UIPressesEvent *)e { [self pressesEnded:presses withEvent:e]; }
@end

@interface AppDelegate : UIResponder <UIApplicationDelegate>
@end

static void *RuntimeThread(void *arg) {
    (void)arg;
    pthread_setname_np("bdsp-runtime");
    char *argv[] = {"bdsp", NULL};
    int rc = bdsp_runtime_main(1, argv);
    fprintf(stderr, "[ipad] Runtime ended (%d)\n", rc);
    exit(rc);
    return NULL;
}

@implementation AppDelegate
- (BOOL)application:(UIApplication *)app didFinishLaunchingWithOptions:(NSDictionary *)opts {
    setvbuf(stdout, NULL, _IOLBF, 0);
    setvbuf(stderr, NULL, _IOLBF, 0);
    // Metal reads MTL_HUD_ENABLED when the device starts; therefore set it before any Metal use (restart required)
    if ([NSUserDefaults.standardUserDefaults boolForKey:@"bdsp_metal_hud"]) setenv("MTL_HUD_ENABLED", "1", 1);
    fprintf(stderr, "[ipad] Metal-HUD %s\n", getenv("MTL_HUD_ENABLED") ? "an" : "aus");
    app.idleTimerDisabled = YES;
    for (GCController *c in GCController.controllers) BindController(c);
    [NSNotificationCenter.defaultCenter addObserverForName:GCControllerDidConnectNotification object:nil queue:NSOperationQueue.mainQueue
                                                usingBlock:^(NSNotification *n) {
        BindController(n.object);
        GameView *v = gView;
        v.overlayHidden = YES;   // with controller: touch gamepad off
        [v buildOverlay];
    }];
    [NSNotificationCenter.defaultCenter addObserverForName:GCControllerDidDisconnectNotification object:nil queue:NSOperationQueue.mainQueue
                                                usingBlock:^(NSNotification *n) {
        atomic_store(&g_pad_mask, 0);
        publish_buttons();
        GameView *v = gView;
        v.overlayHidden = GCController.controllers.count > 0;
        [v buildOverlay];
    }];
    ConfigureAudioSession();
    [NSNotificationCenter.defaultCenter addObserverForName:AVAudioSessionInterruptionNotification object:nil queue:NSOperationQueue.mainQueue
                                                usingBlock:^(NSNotification *n) {
        AVAudioSessionInterruptionType type = [n.userInfo[AVAudioSessionInterruptionTypeKey] unsignedIntegerValue];
        fprintf(stderr, "[ipad-audio] interruption %s, options %lu, reason %lu, scene active %d\n", type == AVAudioSessionInterruptionTypeBegan ? "began" : "ended",
                (unsigned long)[n.userInfo[AVAudioSessionInterruptionOptionKey] unsignedIntegerValue],
                (unsigned long)[n.userInfo[AVAudioSessionInterruptionReasonKey] unsignedIntegerValue], (int)sceneActive);
        audioInterrupted = type == AVAudioSessionInterruptionTypeBegan;
        if (audioInterrupted) SetAudioActive(NO);
        else if (([n.userInfo[AVAudioSessionInterruptionOptionKey] unsignedIntegerValue] & AVAudioSessionInterruptionOptionShouldResume) &&
                 sceneActive) SetAudioActive(YES);
    }];
    [NSNotificationCenter.defaultCenter addObserverForName:AVAudioSessionRouteChangeNotification object:nil queue:NSOperationQueue.mainQueue
                                                usingBlock:^(NSNotification *n) {
        AVAudioSessionRouteDescription *route = AVAudioSession.sharedInstance.currentRoute;
        NSString *outs = route.outputs.firstObject ? route.outputs.firstObject.portType : @"none";
        fprintf(stderr, "[ipad-audio] route change, reason %lu, output %s, volume %.2f\n",
                (unsigned long)[n.userInfo[AVAudioSessionRouteChangeReasonKey] unsignedIntegerValue], outs.UTF8String,
                AVAudioSession.sharedInstance.outputVolume);
    }];
    [NSNotificationCenter.defaultCenter addObserverForName:AVAudioSessionMediaServicesWereResetNotification object:nil queue:NSOperationQueue.mainQueue
                                                usingBlock:^(NSNotification *n) {
        (void)n;
        fprintf(stderr, "[ipad-audio] media services were reset\n");
    }];
    return YES;
}

@end

// Starts the runtime with the game (mod == NULL) or with a mod: the mod's RomFS is merged over the game's and the mod gets a save folder of
// its own (Saves/mods/<name>). The save of the game is not touched while a mod is active, so a dropped-in SaveData.bin waits (ImportSave)
// for the next start of the game.
static void LaunchRuntime(const ModInfo *mod) {
    if (getenv("BDSP_PROBE_FIXED")) ProbeFixedWindows();
    NSString *docs = Documents(), *res = [NSBundle.mainBundle.resourcePath stringByAppendingPathComponent:@"res"];
    NSFileManager *fm = NSFileManager.defaultManager;
    [fm createDirectoryAtPath:[docs stringByAppendingPathComponent:@"Shots"] withIntermediateDirectories:YES attributes:nil error:nil];
    if (mod) {
        if (mods_activate(mod, [docs stringByAppendingPathComponent:@"Saves"].UTF8String) != 0) {
            fprintf(stderr, "[mods] cannot start \"%s\"\n", mod->name);
            return;
        }
        setenv("BDSP_SAVE", mods_active_save(), 1);
    } else {
        ImportSave();
    }
    setenv("BDSP_IMG", [res stringByAppendingPathComponent:@"img32"].UTF8String, 0);
    setenv("BDSP_NPDM", [res stringByAppendingPathComponent:@"main.npdm"].UTF8String, 0);
    setenv("BDSP_ROMFS", [docs stringByAppendingPathComponent:@"GameData/romfs"].UTF8String, 0);
    setenv("BDSP_SAVE", [docs stringByAppendingPathComponent:@"Saves"].UTF8String, 0);
    setenv("BDSP_SHOT_DIR", [docs stringByAppendingPathComponent:@"Shots"].UTF8String, 0);
    setenv("BDSP_TIMEOUT", "86400", 0);
    setenv("BDSP_FPS_INTERVAL", "5", 0);
    setenv("BDSP_XW_DRAIN_DESTROY", "1", 0);   // texture release waits for the renderer worker (suspected cause of the crash in bind_textures); frame rate stays asynchronous
    NSInteger fps = [NSUserDefaults.standardUserDefaults integerForKey:@"bdsp_fps"];
    bdsp_set_fps(fps ? (int)fps : 60);
    fprintf(stderr, "[ipad] Start: %s, device %s, os_proc_available_memory %zu MiB\n", UIDevice.currentDevice.systemVersion.UTF8String,
            UIDevice.currentDevice.model.UTF8String, os_proc_available_memory() >> 20);
    if (![fm fileExistsAtPath:[docs stringByAppendingPathComponent:@"GameData/romfs"]])
        fprintf(stderr, "[ipad] WARNING: Documents/GameData/romfs missing (copy the RomFS via devicectl, docs/recomp-ios.md)\n");
    pthread_t t, st;
    pthread_attr_t at;
    pthread_attr_init(&at);
    pthread_attr_setstacksize(&at, 8 << 20);
    {   // firmware files of the on-screen keyboard (layouts, fonts, name check); without them the keyboard is a simple one of our own
        NSString *fw = [docs stringByAppendingPathComponent:@"Firmware"];
        if ([fm fileExistsAtPath:fw]) setenv("BDSP_FIRMWARE_DATA", fw.UTF8String, 0);
    }
    pthread_create(&t, &at, RuntimeThread, NULL);
    pthread_detach(t);
    pthread_create(&st, NULL, StatsLoop, NULL);
    pthread_detach(st);
}

// Documents/Mods holds mods in the layout of Ryujinx and yuzu (<name>/romfs, <name>/exefs), copied there with the Files app. With at least one
// mod the app asks at launch what to start; the last choice is preselected. BDSP_MOD=<name|none> (devicectl --environment-variables) skips
// the dialog for automated runs.
static ModInfo gMods[MODS_MAX];

// Called from SceneDelegate as soon as the game view appears: then the CAMetalLayer exists with its size
static void StartRuntime(void) {
    NSString *modsDir = [Documents() stringByAppendingPathComponent:@"Mods"];
    [NSFileManager.defaultManager createDirectoryAtPath:modsDir withIntermediateDirectories:YES attributes:nil error:nil];   // visible in the Files app
    int n = mods_scan(modsDir.UTF8String, gMods, MODS_MAX);
    const char *want = getenv("BDSP_MOD");
    if (want && *want) {
        for (int i = 0; i < n; i++) if (!strcasecmp(gMods[i].name, want)) { LaunchRuntime(&gMods[i]); return; }
        if (strcasecmp(want, "none") && strcasecmp(want, "diamond")) {
            fprintf(stderr, "[mods] BDSP_MOD=%s: no such mod in Documents/Mods (%d found)\n", want, n);
            exit(2);
        }
        LaunchRuntime(NULL);
        return;
    }
    if (n == 0) { LaunchRuntime(NULL); return; }
    NSUserDefaults *ud = NSUserDefaults.standardUserDefaults;
    NSString *last = [ud stringForKey:@"bdsp_mod"] ?: @"";
    UIAlertController *a = [UIAlertController alertControllerWithTitle:@"Choose a game"
        message:@"A mod runs with a save of its own. The save of Brilliant Diamond is not touched while a mod is active."
        preferredStyle:UIAlertControllerStyleAlert];
    UIAlertAction *game = [UIAlertAction actionWithTitle:@"Brilliant Diamond" style:UIAlertActionStyleDefault handler:^(UIAlertAction *x) {
        (void)x;
        [ud setObject:@"" forKey:@"bdsp_mod"];
        LaunchRuntime(NULL);
    }];
    [a addAction:game];
    UIAlertAction *preferred = last.length ? nil : game;
    for (int i = 0; i < n; i++) {
        const ModInfo *m = &gMods[i];
        NSString *name = @(m->name);
        UIAlertAction *act = [UIAlertAction actionWithTitle:name style:UIAlertActionStyleDefault handler:^(UIAlertAction *x) {
            (void)x;
            [ud setObject:name forKey:@"bdsp_mod"];
            LaunchRuntime(m);
        }];
        [a addAction:act];
        if ([name isEqualToString:last]) preferred = act;
    }
    if (preferred) a.preferredAction = preferred;
    [gView.window.rootViewController presentViewController:a animated:YES completion:nil];
}

@implementation SceneDelegate
- (void)scene:(UIScene *)scene willConnectToSession:(UISceneSession *)session options:(UISceneConnectionOptions *)options {
    (void)session;
    (void)options;
    self.window = [[UIWindow alloc] initWithWindowScene:(UIWindowScene *)scene];
    self.window.rootViewController = [GameVC new];
    [self.window makeKeyAndVisible];
}
- (void)sceneWillResignActive:(UIScene *)scene {
    (void)scene;
    sceneActive = NO;
    fprintf(stderr, "[ipad-audio] scene resigns active: audio off\n");
    SetAudioActive(NO);
}
- (void)sceneDidBecomeActive:(UIScene *)scene {
    (void)scene;
    sceneActive = YES;
    fprintf(stderr, "[ipad-audio] scene became active: audio %s\n", audioInterrupted ? "stays off (interrupted)" : "on");
    if (!audioInterrupted) SetAudioActive(YES);
    ApplyAppIcon();
}
- (void)startRuntime {
    StartRuntime();
}
@end

int main(int argc, char *argv[]) {
    if (getenv("BDSP_HANG_DUMP")) {   // stall diagnosis: the harness ends hanging runs with SIGTERM, then the thread report appears
        extern void kernel_report(FILE *f);
        signal(SIGTERM, SIG_IGN);
        dispatch_source_t term = dispatch_source_create(DISPATCH_SOURCE_TYPE_SIGNAL, SIGTERM, 0, dispatch_get_global_queue(QOS_CLASS_UTILITY, 0));
        dispatch_source_set_event_handler(term, ^{
            dispatch_after(dispatch_time(DISPATCH_TIME_NOW, 5 * NSEC_PER_SEC), dispatch_get_global_queue(QOS_CLASS_UTILITY, 0), ^{ _exit(143); });  // the report hangs on a held lock
            kernel_report(stderr);
            fflush(stderr);
            _exit(143);
        });
        dispatch_resume(term);
    }
    @autoreleasepool { return UIApplicationMain(argc, argv, nil, NSStringFromClass(AppDelegate.class)); }
}
