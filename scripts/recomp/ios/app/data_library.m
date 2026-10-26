#import "data_library.h"
#include <CommonCrypto/CommonDigest.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>
#include <stdlib.h>

static BOOL Fail(NSError **error, NSString *message) {
    if (error) *error = [NSError errorWithDomain:@"GameData" code:1
        userInfo:@{NSLocalizedDescriptionKey:message}];
    return NO;
}

NSString *BDSPFileSHA256(NSURL *file, NSError **error) {
    int fd = open(file.fileSystemRepresentation, O_RDONLY | O_NOFOLLOW);
    struct stat before, after;
    if (fd < 0) { Fail(error, @"A data file could not be opened."); return nil; }
    if (fstat(fd, &before) || !S_ISREG(before.st_mode)) {
        close(fd); Fail(error, @"Only regular data files are supported."); return nil;
    }
    CC_SHA256_CTX context; CC_SHA256_Init(&context);
    unsigned char buffer[65536], hash[CC_SHA256_DIGEST_LENGTH];
    ssize_t count;
    while ((count = read(fd, buffer, sizeof buffer)) > 0) CC_SHA256_Update(&context, buffer, (CC_LONG)count);
    BOOL valid = count == 0 && fstat(fd, &after) == 0 && before.st_size == after.st_size &&
        before.st_mtimespec.tv_sec == after.st_mtimespec.tv_sec && before.st_mtimespec.tv_nsec == after.st_mtimespec.tv_nsec;
    close(fd);
    if (!valid) { Fail(error, @"A data file changed or could not be read completely."); return nil; }
    CC_SHA256_Final(hash, &context);
    NSMutableString *hex = [NSMutableString string];
    for (unsigned i = 0; i < sizeof hash; i++) [hex appendFormat:@"%02x", hash[i]];
    return hex;
}

BOOL BDSPWriteJSON(id value, NSURL *file, NSError **error) {
    NSData *data = [NSJSONSerialization dataWithJSONObject:value options:NSJSONWritingSortedKeys error:error];
    if (!data) return NO;
    NSString *pattern = [file.URLByDeletingLastPathComponent.path stringByAppendingPathComponent:@".json-XXXXXX"];
    char *temporary = strdup(pattern.fileSystemRepresentation);
    if (!temporary) return Fail(error, @"Not enough memory to write metadata.");
    int fd = mkstemp(temporary);
    BOOL ok = fd >= 0;
    NSUInteger written = 0;
    while (ok && written < data.length) {
        ssize_t count = write(fd, (const char *)data.bytes + written, data.length - written);
        if (count < 0 && errno == EINTR) continue;
        if (count <= 0) { ok = NO; break; }
        written += (NSUInteger)count;
    }
    if (ok) ok = fsync(fd) == 0;
    if (fd >= 0 && close(fd) != 0) ok = NO;
    if (ok) ok = rename(temporary, file.fileSystemRepresentation) == 0;
    if (ok) {
        int directory = open(file.URLByDeletingLastPathComponent.fileSystemRepresentation, O_RDONLY | O_DIRECTORY);
        ok = directory >= 0 && fsync(directory) == 0;
        if (directory >= 0) close(directory);
    }
    if (!ok) unlink(temporary);
    free(temporary);
    return ok || Fail(error, @"Metadata could not be saved completely. Existing data was kept.");
}

static BOOL Relative(NSString *path) {
    if (![path isKindOfClass:NSString.class] || !path.length || path.isAbsolutePath || [path containsString:@"\\"]) return NO;
    for (NSString *part in path.pathComponents) if ([part isEqual:@".."] || [part isEqual:@"."]) return NO;
    return [path isEqual:path.stringByStandardizingPath];
}

static NSURL *SafeURL(NSURL *root, NSString *relative, NSError **error) {
    if (!Relative(relative)) { Fail(error, @"The data manifest contains an invalid path."); return nil; }
    NSURL *current = root;
    struct stat st;
    for (NSString *part in relative.pathComponents) {
        current = [current URLByAppendingPathComponent:part];
        if (lstat(current.fileSystemRepresentation, &st) || S_ISLNK(st.st_mode)) {
            Fail(error, @"A game data path is missing or is a symbolic link."); return nil;
        }
    }
    return current;
}

static BOOL MakeParents(NSURL *root, NSString *relative, NSError **error) {
    if (!Relative(relative)) return Fail(error, @"Invalid data folder.");
    int fd = open(root.fileSystemRepresentation, O_RDONLY | O_DIRECTORY | O_NOFOLLOW);
    if (fd < 0) return Fail(error, @"The export folder is not accessible.");
    for (NSString *part in relative.pathComponents) {
        const char *name = part.fileSystemRepresentation;
        if (mkdirat(fd, name, 0700) && errno != EEXIST) { close(fd); return Fail(error, @"The data folder could not be created."); }
        int child = openat(fd, name, O_RDONLY | O_DIRECTORY | O_NOFOLLOW);
        close(fd); fd = child;
        if (fd < 0) return Fail(error, @"A data folder is a symbolic link or is inaccessible.");
    }
    close(fd); return YES;
}

static NSArray *InventoryProgress(NSURL *folder, void (^progress)(void), NSError **error) {
    struct stat rootStat;
    if (lstat(folder.fileSystemRepresentation, &rootStat) || !S_ISDIR(rootStat.st_mode)) {
        Fail(error, @"The data folder is missing or is a symbolic link."); return nil;
    }
    folder = folder.URLByResolvingSymlinksInPath;
    NSMutableArray *files = [NSMutableArray array];
    __block BOOL failed = NO;
    __block NSError *walkError = nil;
    NSDirectoryEnumerator *walk = [NSFileManager.defaultManager enumeratorAtURL:folder
        includingPropertiesForKeys:nil options:0 errorHandler:^BOOL(NSURL *url, NSError *failure) {
            (void)url; failed = YES; walkError = failure; return NO;
        }];
    char *canonical = realpath(folder.fileSystemRepresentation, NULL);
    if (!canonical) { Fail(error, @"The data folder could not be resolved."); return nil; }
    NSString *prefix = [[NSString stringWithUTF8String:canonical] stringByAppendingString:@"/"];
    free(canonical);
    for (NSURL *file in walk) {
        struct stat st;
        if (lstat(file.fileSystemRepresentation, &st) || (!S_ISREG(st.st_mode) && !S_ISDIR(st.st_mode))) {
            Fail(error, @"Game data may contain only files and directories."); return nil;
        }
        if (S_ISDIR(st.st_mode)) continue;
        if ([file.lastPathComponent isEqual:@".DS_Store"]) continue;
        char *resolvedFile = realpath(file.fileSystemRepresentation, NULL);
        NSString *actualPath = resolvedFile ? [NSString stringWithUTF8String:resolvedFile] : nil;
        free(resolvedFile);
        if (![actualPath hasPrefix:prefix]) { Fail(error, @"A data path escaped its folder."); return nil; }
        NSString *hash = BDSPFileSHA256(file, error);
        if (!hash) return nil;
        [files addObject:@{@"path":[actualPath substringFromIndex:prefix.length], @"size":@(st.st_size), @"sha256":hash}];
        if (progress) progress();
    }
    if (failed) { if (error) *error = walkError; return nil; }
    return [files sortedArrayUsingComparator:^NSComparisonResult(NSDictionary *a, NSDictionary *b) {
        return [a[@"path"] compare:b[@"path"] options:NSLiteralSearch];
    }];
}
NSArray *BDSPInventory(NSURL *folder, NSError **error) { return InventoryProgress(folder, nil, error); }

NSDictionary *BDSPVerifyInstalledData(NSURL *library, NSDictionary *identity, NSURL *manifestURL, void (^progress)(NSUInteger, NSUInteger), NSError **error) {
    NSNumber *length = nil;
    [manifestURL getResourceValue:&length forKey:NSURLFileSizeKey error:error];
    if (!length || length.unsignedLongLongValue > 32 * 1024 * 1024) { Fail(error, @"Invalid data manifest size."); return nil; }
    NSData *bytes = [NSData dataWithContentsOfURL:manifestURL options:0 error:error];
    id parsed = bytes ? [NSJSONSerialization JSONObjectWithData:bytes options:0 error:error] : nil;
    if (![parsed isKindOfClass:NSDictionary.class]) { Fail(error, @"Invalid data manifest."); return nil; }
    NSDictionary *manifest = parsed;
    if (![manifest[@"schema"] isEqual:@1] || ![manifest[@"identity"] isEqual:identity] ||
        ![manifest[@"trees"] isKindOfClass:NSDictionary.class]) {
        Fail(error, @"These game files do not match this app build."); return nil;
    }
    NSArray *roots = identity[@"ModDirectory"] ? @[identity[@"RomFSDirectory"], identity[@"ModDirectory"]] : @[identity[@"RomFSDirectory"]];
    if (manifest[@"trees"] && [manifest[@"trees"] count] != roots.count) { Fail(error, @"Unexpected data folders."); return nil; }
    __block NSUInteger checked = 0;
    NSUInteger total = 0;
    for (NSString *root in roots) {
        if (![manifest[@"trees"][root] isKindOfClass:NSArray.class]) { Fail(error, @"Invalid file inventory."); return nil; }
        total += [manifest[@"trees"][root] count];
    }
    if (progress) progress(0, total);
    for (NSString *relative in roots) {
        NSURL *folder = SafeURL(library, relative, error);
        NSArray *actual = folder ? InventoryProgress(folder, ^{
            checked++;
            if (progress && (checked % 128 == 0 || checked == total)) progress(MIN(checked, total), total);
        }, error) : nil;
        if (!actual || ![actual isEqual:manifest[@"trees"][relative]]) {
            if (actual) Fail(error, @"Game data is incomplete or its checksums do not match.");
            return nil;
        }
    }
    return manifest;
}
NSDictionary *BDSPVerifyLibraryProgress(NSURL *library, NSDictionary *identity, void (^progress)(NSUInteger, NSUInteger), NSError **error) {
    NSURL *manifest = SafeURL(library, identity[@"DataManifest"], error);
    return manifest ? BDSPVerifyInstalledData(library, identity, manifest, progress, error) : nil;
}
NSDictionary *BDSPVerifyLibrary(NSURL *library, NSDictionary *identity, NSError **error) { return BDSPVerifyLibraryProgress(library, identity, nil, error); }

static NSArray<NSURL *> *ModFolders(NSURL *root, NSError **error) {
    NSArray *entries = [NSFileManager.defaultManager contentsOfDirectoryAtURL:root includingPropertiesForKeys:nil options:0 error:error];
    if (!entries) return nil;
    NSMutableArray *folders = [NSMutableArray array];
    NSMutableSet *seen = [NSMutableSet set];
    for (NSURL *entry in entries) {
        NSString *name = entry.lastPathComponent.lowercaseString;
        if (![name isEqual:@"romfs"] && ![name isEqual:@"exefs"]) continue;
        struct stat st;
        if ([seen containsObject:name] || lstat(entry.fileSystemRepresentation, &st) || !S_ISDIR(st.st_mode)) {
            Fail(error, @"The mod has duplicate or invalid RomFS/ExeFS folders."); return nil;
        }
        [seen addObject:name]; [folders addObject:entry];
    }
    return folders;
}
static NSArray *ModInventory(NSURL *root, NSError **error) {
    NSArray *folders = ModFolders(root, error);
    if (!folders) return nil;
    NSMutableArray *files = [NSMutableArray array];
    for (NSURL *folder in folders) {
        NSArray *entries = BDSPInventory(folder, error);
        if (!entries) return nil;
        for (NSDictionary *entry in entries) {
            NSMutableDictionary *copy = entry.mutableCopy;
            copy[@"path"] = [folder.lastPathComponent stringByAppendingPathComponent:entry[@"path"]];
            [files addObject:copy];
        }
    }
    return [files sortedArrayUsingComparator:^NSComparisonResult(NSDictionary *a, NSDictionary *b) { return [a[@"path"] compare:b[@"path"] options:NSLiteralSearch]; }];
}

BOOL BDSPCreateLibraryManifest(NSURL *romfs, NSURL *mod, NSDictionary *identity, NSURL *output, NSError **error) {
    NSArray *base = BDSPInventory(romfs, error);
    if (!base) return NO;
    NSMutableDictionary *trees = [NSMutableDictionary dictionaryWithObject:base forKey:identity[@"RomFSDirectory"]];
    if (mod) {
        NSArray *overlay = [identity[@"ExternalLibrary"] boolValue] ? ModInventory(mod, error) : BDSPInventory(mod, error);
        if (!overlay) return NO;
        trees[identity[@"ModDirectory"]] = overlay;
    }
    return BDSPWriteJSON(@{@"schema":@1, @"identity":identity, @"trees":trees}, output, error);
}

BOOL BDSPExportLibrary(NSURL *romfs, NSURL *mod, NSDictionary *identity, NSURL *library, NSError **error) {
    NSFileManager *fm = NSFileManager.defaultManager;
    if (!Relative(identity[@"DataManifest"]) || !Relative(identity[@"RomFSDirectory"]) ||
        (mod && !Relative(identity[@"ModDirectory"]))) return Fail(error, @"Invalid export identity.");
    if (![fm createDirectoryAtURL:library withIntermediateDirectories:YES attributes:nil error:error]) return NO;
    struct stat libraryStat;
    if (lstat(library.fileSystemRepresentation, &libraryStat) || !S_ISDIR(libraryStat.st_mode)) return Fail(error, @"The export destination is not a regular directory.");
    library = library.URLByResolvingSymlinksInPath;
    NSMutableDictionary *trees = [NSMutableDictionary dictionary];
    NSArray *sources = mod ? @[romfs, mod] : @[romfs];
    NSArray *destinations = mod ? @[identity[@"RomFSDirectory"], identity[@"ModDirectory"]] : @[identity[@"RomFSDirectory"]];
    for (NSUInteger i = 0; i < sources.count; i++) {
        NSArray *inventory = i == 0 ? BDSPInventory(sources[i], error) : ModInventory(sources[i], error);
        if (!inventory) return NO;
        if (!inventory.count) return Fail(error, @"The selected game data is empty.");
        NSString *relative = destinations[i];
        NSURL *target = [library URLByAppendingPathComponent:relative];
        if (!MakeParents(library, relative.stringByDeletingLastPathComponent, error)) return NO;
        if ([fm fileExistsAtPath:target.path]) {
            NSURL *safe = SafeURL(library, relative, error);
            if (!safe || ![BDSPInventory(safe, error) isEqual:inventory]) return Fail(error, @"Existing exported data differs; it was not overwritten.");
        } else {
            // Only this unique staging directory may be removed after failure.
            NSURL *stage = [library URLByAppendingPathComponent:[@".pending-" stringByAppendingString:NSUUID.UUID.UUIDString]];
            BOOL copied = YES;
            if (i == 0) copied = [fm copyItemAtURL:sources[i] toURL:stage error:error];
            else {
                copied = [fm createDirectoryAtURL:stage withIntermediateDirectories:NO attributes:nil error:error];
                NSArray *folders = copied ? ModFolders(sources[i], error) : nil;
                if (!folders) copied = NO;
                for (NSURL *folder in folders) if (![fm copyItemAtURL:folder toURL:[stage URLByAppendingPathComponent:folder.lastPathComponent] error:error]) { copied = NO; break; }
            }
            if (!copied) { [fm removeItemAtURL:stage error:nil]; return NO; }
            if (![BDSPInventory(stage, error) isEqual:inventory]) { [fm removeItemAtURL:stage error:nil]; return Fail(error, @"Export verification failed; existing data was kept."); }
            if (![fm createDirectoryAtURL:target.URLByDeletingLastPathComponent withIntermediateDirectories:YES attributes:nil error:error] ||
                ![fm moveItemAtURL:stage toURL:target error:error]) { [fm removeItemAtURL:stage error:nil]; return NO; }
        }
        trees[relative] = inventory;
    }
    NSURL *manifest = [library URLByAppendingPathComponent:identity[@"DataManifest"]];
    if (!MakeParents(library, [identity[@"DataManifest"] stringByDeletingLastPathComponent], error)) return NO;
    struct stat manifestStat;
    if (lstat(manifest.fileSystemRepresentation, &manifestStat) == 0 && !S_ISREG(manifestStat.st_mode)) return Fail(error, @"The manifest destination is not a regular file.");
    if (!BDSPWriteJSON(@{@"schema":@1, @"identity":identity, @"trees":trees}, manifest, error)) return NO;
    return BDSPVerifyLibrary(library, identity, error) != nil;
}

BOOL BDSPExportIPA(NSURL *source, NSURL *destination, NSError **error) {
    NSFileManager *fm = NSFileManager.defaultManager;
    NSString *hash = BDSPFileSHA256(source, error);
    if (!hash) return NO;
    if ([fm fileExistsAtPath:destination.path]) {
        NSString *existing = BDSPFileSHA256(destination, error);
        return [existing isEqual:hash] || Fail(error, @"An existing IPA differs; it was not overwritten.");
    }
    NSURL *temporary = [destination.URLByDeletingLastPathComponent URLByAppendingPathComponent:[@".ipa-" stringByAppendingString:NSUUID.UUID.UUIDString]];
    BOOL ok = [fm copyItemAtURL:source toURL:temporary error:error];
    if (ok) ok = [BDSPFileSHA256(temporary, error) isEqual:hash];
    if (ok) {
        int fd = open(temporary.fileSystemRepresentation, O_RDONLY | O_NOFOLLOW);
        ok = fd >= 0 && fsync(fd) == 0;
        if (fd >= 0) close(fd);
    }
    // Cocoa's move refuses an existing target and also works on filesystems
    // without hard-link support, unlike link-based publication.
    if (ok) ok = [fm moveItemAtURL:temporary toURL:destination error:error];
    if (!ok) { [fm removeItemAtURL:temporary error:nil]; if (error && !*error) Fail(error, @"IPA export failed verification; previous output was kept."); }
    return ok;
}

#ifdef BDSP_DATA_TOOL
int main(int argc, const char **argv) { @autoreleasepool {
    if (argc != 4 && argc != 6) { fprintf(stderr, "Usage: ios-data verify LIBRARY IDENTITY.plist | export ROMFS MOD-or-- IDENTITY.plist LIBRARY\n"); return 2; }
    NSError *error = nil;
    if (argc == 4 && !strcmp(argv[1], "publish-ipa")) {
        BOOL ok = BDSPExportIPA([NSURL fileURLWithPath:@(argv[2])], [NSURL fileURLWithPath:@(argv[3])], &error);
        if (!ok) fprintf(stderr, "error: %s\n", error.localizedDescription.UTF8String ?: "IPA export failed");
        return ok ? 0 : 1;
    }
    BOOL exporting = !strcmp(argv[1], "export");
    BOOL manifestOnly = !strcmp(argv[1], "manifest");
    if ((!exporting && !manifestOnly && strcmp(argv[1], "verify")) || argc != (exporting || manifestOnly ? 6 : 4)) return 2;
    NSString *identityPath = @(argv[exporting || manifestOnly ? 4 : 3]);
    NSDictionary *identity = [NSDictionary dictionaryWithContentsOfFile:identityPath];
    if (!identity || ![identity[@"RomFSDirectory"] isKindOfClass:NSString.class]) return 2;
    if (manifestOnly) {
        BOOL ok = BDSPCreateLibraryManifest([NSURL fileURLWithPath:@(argv[2])].URLByResolvingSymlinksInPath,
            strcmp(argv[3], "-") ? [NSURL fileURLWithPath:@(argv[3])].URLByResolvingSymlinksInPath : nil,
            identity, [NSURL fileURLWithPath:@(argv[5])], &error);
        if (!ok) fprintf(stderr, "error: %s\n", error.localizedDescription.UTF8String ?: "Manifest generation failed");
        return ok ? 0 : 1;
    }
    BOOL ok = exporting ? BDSPExportLibrary([NSURL fileURLWithPath:@(argv[2])].URLByResolvingSymlinksInPath,
        strcmp(argv[3], "-") ? [NSURL fileURLWithPath:@(argv[3])].URLByResolvingSymlinksInPath : nil,
        identity, [NSURL fileURLWithPath:@(argv[5])], &error) :
        BDSPVerifyLibrary([NSURL fileURLWithPath:@(argv[2])], identity, &error) != nil;
    if (!ok) fprintf(stderr, "error: %s\n", error.localizedDescription.UTF8String ?: "Invalid data package");
    return ok ? 0 : 1;
} }
#endif
