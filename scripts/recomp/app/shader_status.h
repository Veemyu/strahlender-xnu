// Shared native Apple shader status. Renderer callbacks never wait on the UI.
// Include in one application-shell translation unit (UIKit or AppKit).
#pragma once
#import <Foundation/Foundation.h>
#include <pthread.h>

static struct {
    pthread_mutex_t lock;
    NSUInteger jobs, completed;
    uint64_t done, total;
    BOOL gate;
    CFAbsoluteTime first, last;
} bdspShaderStatus = {.lock = PTHREAD_MUTEX_INITIALIZER};

static BOOL BDSPNoticeEnabled(NSString *key) {
    id value = [NSUserDefaults.standardUserDefaults objectForKey:key];
    return value ? [value boolValue] : YES;
}
static NSString *bdspNativeMessage;
static NSString *bdspNativeMessagePreference;
static CFAbsoluteTime bdspNativeMessageUntil;
static double bdspNativeMessageDuration;

// Save/backup completions share the banner and wait until shader work is done.
void bdsp_native_status_message(const char *preference, const char *utf8, double duration) {
    NSString *key = preference ? [NSString stringWithUTF8String:preference] : @"bdsp_notify_save";
    if (!BDSPNoticeEnabled(key)) return;
    NSString *message = utf8 ? [NSString stringWithUTF8String:utf8] : nil;
    pthread_mutex_lock(&bdspShaderStatus.lock);
    bdspNativeMessage = [message copy]; bdspNativeMessagePreference = key; bdspNativeMessageUntil = 0;
    bdspNativeMessageDuration = MAX(1.0, MIN(duration, 15.0));
    pthread_mutex_unlock(&bdspShaderStatus.lock);
}

void bdsp_shader_compile_status(int active) {
    pthread_mutex_lock(&bdspShaderStatus.lock);
    CFAbsoluteTime now = CFAbsoluteTimeGetCurrent();
    if (active) {
        if (!bdspShaderStatus.jobs && now - bdspShaderStatus.last > 0.35) bdspShaderStatus.first = now;
        bdspShaderStatus.jobs++;
    } else {
        if (bdspShaderStatus.jobs) bdspShaderStatus.jobs--;
        bdspShaderStatus.completed++;
    }
    bdspShaderStatus.last = now;
    pthread_mutex_unlock(&bdspShaderStatus.lock);
}

void bdsp_shader_gate_status(uint64_t done, uint64_t total, int active) {
    pthread_mutex_lock(&bdspShaderStatus.lock);
    bdspShaderStatus.gate = active != 0;
    if (!active && !bdspShaderStatus.jobs) bdspShaderStatus.first = 0;
    bdspShaderStatus.done = done; bdspShaderStatus.total = total;
    bdspShaderStatus.last = CFAbsoluteTimeGetCurrent();
    pthread_mutex_unlock(&bdspShaderStatus.lock);
}

static NSString *BDSPShaderLabel(void) {
    NSString *lang = NSLocale.preferredLanguages.firstObject.lowercaseString;
    if ([lang hasPrefix:@"de"]) return @"Shader werden vorbereitet…";
    if ([lang hasPrefix:@"es"]) return @"Preparando sombreadores…";
    if ([lang hasPrefix:@"pt"]) return @"A preparar shaders…";
    if ([lang hasPrefix:@"ru"] || [lang hasPrefix:@"uk"]) return @"Подготовка шейдеров…";
    return @"Preparing shaders…";
}

static void BDSPInstallShaderStatus(void (^display)(NSString *)) {
    static dispatch_once_t once;
    dispatch_once(&once, ^{
        // Coalesce thousands of compiler callbacks into at most ten UI updates
        // per second. Keep a burst visible; avoid flashing for a single cache hit.
        __block NSString *previous;
        [NSTimer scheduledTimerWithTimeInterval:0.1 repeats:YES block:^(NSTimer *timer) {
            (void)timer;
            pthread_mutex_lock(&bdspShaderStatus.lock);
            BOOL gate = bdspShaderStatus.gate;
            NSUInteger jobs = bdspShaderStatus.jobs, completed = bdspShaderStatus.completed;
            uint64_t done = bdspShaderStatus.done, total = bdspShaderStatus.total;
            CFAbsoluteTime first = bdspShaderStatus.first, last = bdspShaderStatus.last;
            pthread_mutex_unlock(&bdspShaderStatus.lock);
            CFAbsoluteTime now = CFAbsoluteTimeGetCurrent();
            NSString *text = nil;
            BOOL shaders = BDSPNoticeEnabled(@"bdsp_notify_shaders");
            if (gate && shaders) text = total ? [NSString stringWithFormat:@"%@ %llu / %llu", BDSPShaderLabel(),
                (unsigned long long)done, (unsigned long long)total] : BDSPShaderLabel();
            else if (shaders && first && now - first >= 0.15 && (jobs || (last - first >= 0.15 && now - last < 0.35)))
                text = [NSString stringWithFormat:@"%@ (%lu)", BDSPShaderLabel(), (unsigned long)completed];
            if (!text) {
                pthread_mutex_lock(&bdspShaderStatus.lock);
                if (bdspNativeMessage && !BDSPNoticeEnabled(bdspNativeMessagePreference)) bdspNativeMessage = nil;
                if (bdspNativeMessage && !bdspNativeMessageUntil)
                    bdspNativeMessageUntil = now + bdspNativeMessageDuration;
                if (bdspNativeMessage && now < bdspNativeMessageUntil) text = bdspNativeMessage;
                else { bdspNativeMessage = nil; bdspNativeMessageUntil = 0; }
                pthread_mutex_unlock(&bdspShaderStatus.lock);
            }
            if (![previous isEqual:text] && (previous || text)) { previous = text; display(text); }
        }];
    });
}
