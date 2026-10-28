// Exercise the shared status without a game, renderer, personal data or saves.
#import "../recomp/app/shader_status.h"
#include <assert.h>
static void Run(double seconds) { [NSRunLoop.currentRunLoop runUntilDate:[NSDate dateWithTimeIntervalSinceNow:seconds]]; }
int main(void) { @autoreleasepool {
    __block NSString *visible = nil;
    __block NSUInteger updates = 0;
    BDSPInstallShaderStatus(^(NSString *text) {
        assert(NSThread.isMainThread);
        visible = text; updates++;
    });
    bdsp_shader_compile_status(1); bdsp_shader_compile_status(0);
    Run(0.5);
    assert(!visible && updates == 0); // One fast cache hit must never flash.
    for (unsigned i = 0; i < 20; i++) {
        bdsp_shader_compile_status(1); Run(0.01);
        bdsp_shader_compile_status(0); Run(0.01);
    }
    assert(visible); // Many short compiles still show one continuous status.
    Run(0.5); assert(!visible);
    bdsp_shader_gate_status(3, 10, 1); Run(0.2);
    assert([visible containsString:@"3 / 10"]);
    bdsp_native_status_message("bdsp_notify_save", "Saved locally", 1);
    bdsp_shader_gate_status(9, 10, 1); Run(0.2);
    assert([visible containsString:@"9 / 10"]);
    bdsp_shader_gate_status(10, 10, 0); Run(0.2);
    assert([visible isEqualToString:@"Saved locally"]);
    Run(1.2); assert(!visible);
    NSUserDefaults *defaults = NSUserDefaults.standardUserDefaults;
    [defaults setVolatileDomain:@{@"bdsp_notify_shaders":@NO, @"bdsp_notify_save":@NO} forName:NSArgumentDomain];
    bdsp_shader_gate_status(1, 4, 1); Run(0.2); assert(!visible);
    bdsp_native_status_message("bdsp_notify_save", "Hidden save", 1); Run(0.2); assert(!visible);
    [defaults setVolatileDomain:@{@"bdsp_notify_shaders":@YES, @"bdsp_notify_save":@YES} forName:NSArgumentDomain];
    Run(0.2); assert([visible containsString:@"1 / 4"]);
    bdsp_shader_gate_status(4, 4, 0); Run(0.2); assert(!visible); // Disabled save is not replayed.
    for (NSString *key in @[@"bdsp_notify_save", @"bdsp_notify_backup", @"bdsp_notify_warnings", @"bdsp_notify_verification"]) {
        [defaults setVolatileDomain:@{key:@NO} forName:NSArgumentDomain];
        bdsp_native_status_message(key.UTF8String, "Disabled category", 1);
        Run(0.2); assert(!visible);
        // Disabling one category must not hide another category.
        NSString *other = [key isEqual:@"bdsp_notify_save"] ? @"bdsp_notify_backup" : @"bdsp_notify_save";
        bdsp_native_status_message(other.UTF8String, "Independent category", 1);
        Run(0.2); assert([visible isEqualToString:@"Independent category"]);
        Run(1.1); assert(!visible);
    }
    [defaults removeVolatileDomainForName:NSArgumentDomain];
    dispatch_apply(1000, dispatch_get_global_queue(QOS_CLASS_UTILITY, 0), ^(size_t n) {
        (void)n; bdsp_shader_compile_status(1); bdsp_shader_compile_status(0);
    });
    pthread_mutex_lock(&bdspShaderStatus.lock);
    assert(!bdspShaderStatus.jobs && bdspShaderStatus.completed == 1021);
    pthread_mutex_unlock(&bdspShaderStatus.lock);
    puts("Native shader status passed.");
} }
