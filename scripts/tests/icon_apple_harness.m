// Synthetic tests of the same preference/locale resolver used by macOS and iPadOS.
#import "../recomp/app/icon_variants.h"
#include <assert.h>

int main(void) {
    @autoreleasepool {
        NSDictionary *icons = @{@"default": @"en-US", @"variants": @[
            @{@"id": @"de"}, @{@"id": @"en-GB"}, @{@"id": @"en-US"}, @{@"id": @"ja"},
            @{@"id": @"zh-Hans"}, @{@"id": @"zh-Hant"}]};
        assert([BDSPRecommendedIcon(icons, @[@"de-DE"])[@"id"] isEqual:@"de"]);
        assert([BDSPRecommendedIcon(icons, @[@"en-AU"])[@"id"] isEqual:@"en-US"]);
        assert([BDSPRecommendedIcon(icons, @[@"en-GB"])[@"id"] isEqual:@"en-GB"]);
        assert([BDSPRecommendedIcon(icons, @[@"ja-JP"])[@"id"] isEqual:@"ja"]);
        assert([BDSPRecommendedIcon(icons, @[@"zh-TW"])[@"id"] isEqual:@"zh-Hant"]);
        assert([BDSPRecommendedIcon(icons, @[@"zh-CN"])[@"id"] isEqual:@"zh-Hans"]);
        assert([BDSPRecommendedIcon(icons, @[@"xx"])[@"id"] isEqual:@"en-US"]);
        assert(BDSPFindIcon(icons, @"missing") == nil);
        assert([BDSPFindIcon(icons, @"default")[@"id"] isEqual:@"en-US"]);
    }
    return 0;
}
