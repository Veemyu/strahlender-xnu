// GameController helpers shared by the macOS and iPadOS shells.
#pragma once
#import <GameController/GameController.h>

// Nintendo pads (Switch Pro, Joy-Con) arrive with the face buttons named like the labels on the pad: buttonA is the right button, as on the
// console. Xbox, PlayStation and generic pads name them by position (buttonA is the bottom one). Telling them apart keeps a Switch pad on
// the console's layout without a setting; the other pads follow the position rule or the "xbox" layout option.
static inline BOOL pad_is_nintendo(GCController *c) {
    NSString *s = [NSString stringWithFormat:@"%@ %@", c.productCategory ?: @"", c.vendorName ?: @""].lowercaseString;
    return [s containsString:@"nintendo"] || [s containsString:@"switch"] || [s containsString:@"joy-con"] || [s containsString:@"joycon"];
}
