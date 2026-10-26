// A separate UIKit test host. It never loads the game runtime or real saves.
#define main BDSPDataStoreTestMain
#import "../recomp/ios/app/test_data_store.m"
#undef main
#import <UIKit/UIKit.h>

@interface DataTestsDelegate : UIResponder <UIApplicationDelegate>
@property(nonatomic, strong) UIWindow *window;
@end
@implementation DataTestsDelegate
- (BOOL)application:(UIApplication *)application didFinishLaunchingWithOptions:(NSDictionary *)options {
    (void)application; (void)options;
    self.window = [[UIWindow alloc] initWithFrame:UIScreen.mainScreen.bounds];
    self.window.rootViewController = [UIViewController new];
    [self.window makeKeyAndVisible];
    dispatch_async(dispatch_get_main_queue(), ^{
        NSString *documents = NSSearchPathForDirectoriesInDomains(NSDocumentDirectory, NSUserDomainMask, YES).firstObject;
        [NSFileManager.defaultManager removeItemAtPath:[documents stringByAppendingPathComponent:@"result.txt"] error:nil];
        int result = BDSPDataStoreTestMain();
        [@"Native iOS data and save tests passed.\n" writeToFile:[documents stringByAppendingPathComponent:@"result.txt"] atomically:YES encoding:NSUTF8StringEncoding error:nil];
        fflush(stdout); fflush(stderr);
        exit(result);
    });
    return YES;
}
@end
int main(int argc, char **argv) { @autoreleasepool {
    return UIApplicationMain(argc, argv, nil, NSStringFromClass(DataTestsDelegate.class));
} }
