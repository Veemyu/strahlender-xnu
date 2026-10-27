// Simulator-only preview of the real pre-game UIKit dialogs. No game runtime or real saves.
#import <UIKit/UIKit.h>

@interface PreviewDelegate : UIResponder <UIApplicationDelegate>
@property(nonatomic, strong) UIWindow *window;
@property(nonatomic, strong) id manager;
@end
@implementation PreviewDelegate
- (BOOL)application:(UIApplication *)application didFinishLaunchingWithOptions:(NSDictionary *)options {
    (void)application; (void)options;
    self.window = [[UIWindow alloc] initWithFrame:UIScreen.mainScreen.bounds];
    self.window.rootViewController = [UIViewController new];
    self.window.overrideUserInterfaceStyle = UIUserInterfaceStyleDark;
    [self.window makeKeyAndVisible];
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, NSEC_PER_SEC / 2), dispatch_get_main_queue(), ^{
        NSArray *args = NSProcessInfo.processInfo.arguments;
        NSUInteger index = [args indexOfObject:@"--screen"];
        NSString *screen = index != NSNotFound && index + 1 < args.count ? args[index+1] : @"menu";
        NSAssert(([@[@"menu", @"saveMenu", @"backupMenu", @"gameDataMenu"] containsObject:screen]), @"Unknown preview screen");
        NSString *root = [NSTemporaryDirectory() stringByAppendingPathComponent:@"ui-preview-only"];
        [NSFileManager.defaultManager removeItemAtPath:root error:nil];
        [NSFileManager.defaultManager createDirectoryAtPath:root withIntermediateDirectories:YES attributes:nil error:nil];
        if ([args containsObject:@"--has-save"]) {
            NSString *slot = [root stringByAppendingPathComponent:@"save_1"];
            [NSFileManager.defaultManager createDirectoryAtPath:slot withIntermediateDirectories:YES attributes:nil error:nil];
            [@"Synthetic UI fixture, not a game save" writeToFile:[slot stringByAppendingPathComponent:@"SaveData.bin"] atomically:YES encoding:NSUTF8StringEncoding error:nil];
        }
        self.manager = [NSClassFromString(@"BDSPDataManager") new];
        [self.manager setValue:self.window.rootViewController forKey:@"presenter"];
        [self.manager setValue:@{@"GameID":@"0000000000000000", @"ProfileID":@"vanilla"} forKey:@"identity"];
        [self.manager setValue:@{@"GameID":@"0000000000000000", @"ProfileID":@"vanilla"} forKey:@"saveIdentity"];
        [self.manager setValue:root forKey:@"saveRoot"];
        [self.manager setValue:@YES forKey:@"deviceDataReady"];
        [self.manager setValue:^{ NSLog(@"Preview only: no game is started."); } forKey:@"ready"];
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Warc-performSelector-leaks"
        [self.manager performSelector:NSSelectorFromString(screen)];
#pragma clang diagnostic pop
        dispatch_after(dispatch_time(DISPATCH_TIME_NOW, NSEC_PER_SEC), dispatch_get_main_queue(), ^{
            UIAlertController *alert = (UIAlertController *)self.window.rootViewController.presentedViewController;
            NSAssert([alert isKindOfClass:UIAlertController.class], @"Expected the real pre-game dialog");
            NSAssert(alert.actions.count <= 3, @"Dialog has too many choices");
            for (UIAlertAction *action in alert.actions) NSAssert(action.enabled, @"Preview has an unexpected disabled action");
            NSLog(@"Native %@ preview: %lu actions; window %@; alert %@", screen, (unsigned long)alert.actions.count, NSStringFromCGRect(self.window.bounds), NSStringFromCGRect(alert.view.frame));
        });
    });
    return YES;
}
@end
int main(int argc, char **argv) { @autoreleasepool { return UIApplicationMain(argc, argv, nil, NSStringFromClass(PreviewDelegate.class)); } }
