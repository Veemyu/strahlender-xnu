// Shared metadata lookup for native Apple app shells. Images remain generated resources.
#pragma once
#import <Foundation/Foundation.h>
#include <stdio.h>

static inline NSDictionary *BDSPReadIcons(NSString *resources) {
    NSData *data = [NSData dataWithContentsOfFile:[resources stringByAppendingPathComponent:@"AppIcons/icons.json"]];
    NSDictionary *icons = data ? [NSJSONSerialization JSONObjectWithData:data options:0 error:nil] : nil;
    if (![icons isKindOfClass:NSDictionary.class] || ![icons[@"variants"] isKindOfClass:NSArray.class]) return nil;
    return icons;
}

static inline NSDictionary *BDSPFindIcon(NSDictionary *icons, NSString *identifier) {
    if (!identifier.length || [identifier isEqualToString:@"default"]) identifier = icons[@"default"];
    for (NSDictionary *variant in icons[@"variants"])
        if ([variant[@"id"] isEqualToString:identifier]) return variant;
    return nil;
}

static inline NSDictionary *BDSPRecommendedIcon(NSDictionary *icons, NSArray<NSString *> *languages) {
    for (NSString *preferred in languages) {
        NSString *locale = [preferred stringByReplacingOccurrencesOfString:@"_" withString:@"-"];
        for (NSDictionary *variant in icons[@"variants"])
            if ([variant[@"id"] caseInsensitiveCompare:locale] == NSOrderedSame) return variant;
        NSString *language = [[locale componentsSeparatedByString:@"-"] firstObject];
        if ([language isEqualToString:@"zh"]) {
            BOOL traditional = [locale containsString:@"Hant"] || [locale hasSuffix:@"-TW"] || [locale hasSuffix:@"-HK"] || [locale hasSuffix:@"-MO"];
            NSDictionary *match = BDSPFindIcon(icons, traditional ? @"zh-Hant" : @"zh-Hans");
            if (match) return match;
        }
        NSDictionary *standard = BDSPFindIcon(icons, @"default");
        if ([[[standard[@"id"] componentsSeparatedByString:@"-"] firstObject] isEqualToString:language]) return standard;
        for (NSDictionary *variant in icons[@"variants"])
            if ([[[variant[@"id"] componentsSeparatedByString:@"-"] firstObject] isEqualToString:language]) return variant;
    }
    return BDSPFindIcon(icons, @"default");
}

static inline NSString *BDSPIconSelection(NSDictionary *icons) {
    NSUserDefaults *defaults = NSUserDefaults.standardUserDefaults;
    NSString *selected = [defaults stringForKey:@"bdsp_app_icon"] ?: @"default";
    if (!BDSPFindIcon(icons, selected)) {
        if (![selected isEqualToString:@"default"]) {
            [defaults setObject:@"default" forKey:@"bdsp_app_icon"];
            fprintf(stderr, "[icon] Selected variant unavailable; using default\n");
        }
        return @"default";
    }
    return selected;
}
