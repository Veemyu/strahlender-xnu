// Read-only benchmark of an existing canonical RomFS; no game-data copies or saves.
#import "../recomp/ios/app/data_library.h"
#include <time.h>
#include <sys/resource.h>
static double Now(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return t.tv_sec + t.tv_nsec * 1e-9; }
int main(int argc, char **argv) { @autoreleasepool {
    if (argc != 3) { fprintf(stderr, "Usage: benchmark ROMFS EXPECTED_MANIFEST\n"); return 2; }
    NSURL *romfs = [NSURL fileURLWithPath:@(argv[1])].URLByResolvingSymlinksInPath;
    NSDictionary *original = [NSJSONSerialization JSONObjectWithData:[NSData dataWithContentsOfFile:@(argv[2])] options:0 error:nil];
    if (![original[@"trees"] isKindOfClass:NSDictionary.class] || [original[@"trees"] count] != 1) return 2;
    NSArray *entries = [original[@"trees"] allValues][0];
    NSDictionary *identity = @{@"RomFSDirectory":romfs.lastPathComponent};
    NSDictionary *manifest = @{@"schema":@1, @"identity":identity, @"trees":@{romfs.lastPathComponent:entries}};
    NSURL *temporary = [[NSURL fileURLWithPath:NSTemporaryDirectory()] URLByAppendingPathComponent:[@"bdsp-verify-" stringByAppendingString:NSUUID.UUID.UUIDString]];
    NSError *error = nil;
    if (!BDSPWriteJSON(manifest, temporary, &error)) return 2;
    NSURL *receipt = [temporary URLByAppendingPathExtension:@"plist"];
    double start = Now();
    BOOL usedReceipt = NO;
    BOOL ok = BDSPCheckInstalledData(romfs.URLByDeletingLastPathComponent, identity, temporary, receipt, NO, &usedReceipt, nil, &error) != nil;
    double elapsed = Now() - start;
    double fastStart = Now();
    BOOL fast = ok && BDSPCheckInstalledData(romfs.URLByDeletingLastPathComponent, identity, temporary, receipt, NO, &usedReceipt, nil, &error) != nil;
    double fastElapsed = Now() - fastStart;
    struct rusage usage; getrusage(RUSAGE_SELF, &usage);
    [NSFileManager.defaultManager removeItemAtURL:temporary error:nil];
    [NSFileManager.defaultManager removeItemAtURL:receipt error:nil];
    printf("verified=%d files=%lu seconds=%.3f peak_rss_bytes=%ld\n", ok, (unsigned long)entries.count, elapsed, usage.ru_maxrss);
    printf("followup_verified=%d used_receipt=%d seconds=%.3f\n", fast, usedReceipt, fastElapsed);
    if (!ok) fprintf(stderr, "%s\n", error.localizedDescription.UTF8String);
    return ok && fast && usedReceipt ? 0 : 1;
} }
