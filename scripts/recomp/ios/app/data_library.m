#import "data_library.h"
#include <CommonCrypto/CommonDigest.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>
#include <stdlib.h>
#include <errno.h>
#include <dirent.h>
#import <dispatch/dispatch.h>

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
    do {
        count = read(fd, buffer, sizeof buffer);
        if (count < 0 && errno == EINTR) continue;
        if (count <= 0) break;
        CC_SHA256_Update(&context, buffer, (CC_LONG)count);
    } while (YES);
    BOOL valid = count == 0 && fstat(fd, &after) == 0 && before.st_size == after.st_size &&
        before.st_mtimespec.tv_sec == after.st_mtimespec.tv_sec && before.st_mtimespec.tv_nsec == after.st_mtimespec.tv_nsec &&
        before.st_ctimespec.tv_sec == after.st_ctimespec.tv_sec && before.st_ctimespec.tv_nsec == after.st_ctimespec.tv_nsec;
    close(fd);
    if (!valid) { Fail(error, @"A data file changed or could not be read completely."); return nil; }
    CC_SHA256_Final(hash, &context);
    static const char digits[] = "0123456789abcdef";
    char hex[CC_SHA256_DIGEST_LENGTH * 2];
    for (unsigned i = 0; i < sizeof hash; i++) {
        hex[2 * i] = digits[hash[i] >> 4];
        hex[2 * i + 1] = digits[hash[i] & 15];
    }
    return [[NSString alloc] initWithBytes:hex length:sizeof hex encoding:NSASCIIStringEncoding];
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

// One bounded autorelease pool per file, including Foundation traversal/path temporaries.
// Export builds an inventory; verification consumes entries directly instead of building
// and sorting a second full inventory of hashes and dictionaries.
static BOOL WalkFiles(NSURL *folder, BOOL (^visit)(NSURL *, NSString *, off_t, NSError **), NSError **error) {
    struct stat rootStat;
    if (lstat(folder.fileSystemRepresentation, &rootStat) || !S_ISDIR(rootStat.st_mode))
        return Fail(error, @"The data folder is missing or is a symbolic link.");
    folder = folder.URLByResolvingSymlinksInPath;
    __block BOOL failed = NO;
    __block NSError *walkError = nil;
    NSDirectoryEnumerator *walk = [NSFileManager.defaultManager enumeratorAtURL:folder
        includingPropertiesForKeys:nil options:0 errorHandler:^BOOL(NSURL *url, NSError *failure) {
            (void)url; failed = YES; walkError = failure; return NO;
        }];
    char *canonical = realpath(folder.fileSystemRepresentation, NULL);
    if (!canonical) return Fail(error, @"The data folder could not be resolved.");
    NSString *prefix = [[NSString stringWithUTF8String:canonical] stringByAppendingString:@"/"];
    free(canonical);
    NSError *failure = nil;
    for (;;) { @autoreleasepool {
        NSURL *file = [walk nextObject];
        if (!file) break;
        struct stat st;
        if (lstat(file.fileSystemRepresentation, &st) || (!S_ISREG(st.st_mode) && !S_ISDIR(st.st_mode))) {
            Fail(&failure, @"Game data may contain only files and directories."); break;
        }
        if (S_ISDIR(st.st_mode)) continue;
        if ([file.lastPathComponent isEqual:@".DS_Store"]) continue;
        char *resolvedFile = realpath(file.fileSystemRepresentation, NULL);
        NSString *actualPath = resolvedFile ? [NSString stringWithUTF8String:resolvedFile] : nil;
        free(resolvedFile);
        if (![actualPath hasPrefix:prefix]) { Fail(&failure, @"A data path escaped its folder."); break; }
        if (!visit(file, [actualPath substringFromIndex:prefix.length], st.st_size, &failure)) {
            if (!failure) Fail(&failure, @"Game data could not be checked.");
            break;
        }
    } }
    if (failure) { if (error) *error = failure; return NO; }
    if (failed) { if (error) *error = walkError; return NO; }
    return YES;
}
NSArray *BDSPInventory(NSURL *folder, NSError **error) {
    NSMutableArray *files = [NSMutableArray array];
    BOOL ok = WalkFiles(folder, ^BOOL(NSURL *file, NSString *path, off_t size, NSError **visitError) {
        NSString *hash = BDSPFileSHA256(file, visitError);
        if (!hash) return NO;
        [files addObject:@{@"path":path, @"size":@(size), @"sha256":hash}];
        return YES;
    }, error);
    return ok ? [files sortedArrayUsingComparator:^NSComparisonResult(NSDictionary *a, NSDictionary *b) {
        return [a[@"path"] compare:b[@"path"] options:NSLiteralSearch];
    }] : nil;
}

static BOOL VerifyTree(NSURL *folder, NSArray *expected, void (^progress)(void), NSError **error) {
    NSMutableDictionary<NSString *, NSDictionary *> *remaining = [NSMutableDictionary dictionaryWithCapacity:expected.count];
    NSCharacterSet *invalidHashCharacters = [[NSCharacterSet characterSetWithCharactersInString:@"0123456789abcdef"] invertedSet];
    for (id item in expected) {
        if (![item isKindOfClass:NSDictionary.class]) return Fail(error, @"Invalid file inventory.");
        NSDictionary *entry = item;
        NSString *path = entry[@"path"], *hash = entry[@"sha256"];
        NSNumber *size = entry[@"size"];
        if (entry.count != 3 || !Relative(path) || remaining[path] ||
            ![size isKindOfClass:NSNumber.class] || size.longLongValue < 0 ||
            ![size isEqual:@(size.longLongValue)] ||
            ![hash isKindOfClass:NSString.class] || hash.length != 64 ||
            [hash rangeOfCharacterFromSet:invalidHashCharacters].location != NSNotFound)
            return Fail(error, @"Invalid or duplicate file inventory entry.");
        remaining[path] = entry;
    }
    // A fixed pool overlaps small-file metadata/I/O with native SHA work. Never
    // queue one outstanding task per file or retain the complete actual inventory.
#ifndef BDSP_VERIFY_WORKERS
#define BDSP_VERIFY_WORKERS 2
#endif
    NSUInteger workers = MIN((NSUInteger)4, MAX((NSUInteger)1,
        MIN((NSUInteger)BDSP_VERIFY_WORKERS, NSProcessInfo.processInfo.activeProcessorCount)));
    dispatch_semaphore_t slots = dispatch_semaphore_create((long)workers);
    dispatch_group_t group = dispatch_group_create();
    dispatch_queue_t queue = dispatch_get_global_queue(QOS_CLASS_UTILITY, 0);
    NSLock *lock = [NSLock new];
    __block NSError *hashFailure = nil;
    NSError *walkFailure = nil;
    BOOL ok = WalkFiles(folder, ^BOOL(NSURL *file, NSString *path, off_t size, NSError **visitError) {
        dispatch_semaphore_wait(slots, DISPATCH_TIME_FOREVER);
        [lock lock];
        NSError *previousFailure = hashFailure;
        NSDictionary *entry = remaining[path];
        [lock unlock];
        if (previousFailure || !entry || ![entry[@"size"] isEqual:@(size)]) {
            dispatch_semaphore_signal(slots);
            if (previousFailure) { if (visitError) *visitError = previousFailure; return NO; }
            return Fail(visitError, @"Game data is incomplete or its checksums do not match.");
        }
        dispatch_group_async(group, queue, ^{ @autoreleasepool {
            [lock lock];
            BOOL cancelled = hashFailure != nil;
            [lock unlock];
            if (!cancelled) {
                NSError *failure = nil;
                NSString *hash = BDSPFileSHA256(file, &failure);
                if (hash && ![hash isEqual:entry[@"sha256"]])
                    Fail(&failure, @"Game data is incomplete or its checksums do not match.");
                [lock lock];
                if (!hashFailure && (!hash || failure)) {
                    hashFailure = failure;
                    if (!hashFailure) Fail(&hashFailure, @"A data file could not be checked.");
                }
                if (!hashFailure) {
                    [remaining removeObjectForKey:path];
                    if (progress) progress(); // Serialized; file progress never goes backwards.
                }
                [lock unlock];
            }
            dispatch_semaphore_signal(slots);
        } });
        return YES;
    }, &walkFailure);
    dispatch_group_wait(group, DISPATCH_TIME_FOREVER);
    // All descriptors/tasks have finished before returning either success or error.
    if (!ok || hashFailure) { if (error) *error = walkFailure ?: hashFailure; return NO; }
    return remaining.count == 0 || Fail(error, @"Game data is incomplete or its checksums do not match.");
}

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
        if (!folder || !VerifyTree(folder, manifest[@"trees"][relative], ^{
            checked++;
            if (progress && (checked % 128 == 0 || checked == total)) progress(MIN(checked, total), total);
        }, error)) return nil;
    }
    return manifest;
}
// A receipt is an optimisation, not a replacement for SHA-256 authentication.
// It lives outside Documents and records every file's inode, size and nanosecond
// timestamps. Imports, edits, replaced trees and manifest changes require SHA again.
// Descriptor-relative metadata traversal avoids resolving an absolute NSURL and
// realpath for every file. O_NOFOLLOW / fstatat keep the same symlink boundary.
// Each recursive call owns its descriptor, including failure paths.
static BOOL SnapshotDirectory(int fd, NSString *relative, NSMutableDictionary *files,
    NSUInteger depth, NSError **error) {
    if (depth > 256) { close(fd); return Fail(error, @"The data folder is nested too deeply."); }
    DIR *directory = fdopendir(fd);
    if (!directory) { close(fd); return Fail(error, @"The data folder could not be read."); }
    BOOL ok = YES;
    NSError *failure = nil;
    for (;;) { @autoreleasepool {
        errno = 0;
        struct dirent *entry = readdir(directory);
        if (!entry) {
            if (errno) ok = Fail(&failure, @"The data folder could not be read completely.");
            break;
        }
        if (!strcmp(entry->d_name, ".") || !strcmp(entry->d_name, "..")) continue;
        struct stat st;
        if (fstatat(dirfd(directory), entry->d_name, &st, AT_SYMLINK_NOFOLLOW) ||
            (!S_ISREG(st.st_mode) && !S_ISDIR(st.st_mode))) {
            ok = Fail(&failure, @"Game data may contain only files and directories."); break;
        }
        NSString *name = [NSFileManager.defaultManager stringWithFileSystemRepresentation:entry->d_name length:strlen(entry->d_name)];
        if (!name) { ok = Fail(&failure, @"A data filename could not be read."); break; }
        NSString *path = relative.length ? [relative stringByAppendingPathComponent:name] : name;
        if (S_ISDIR(st.st_mode)) {
            int child = openat(dirfd(directory), entry->d_name, O_RDONLY | O_DIRECTORY | O_NOFOLLOW);
            if (child < 0) { ok = Fail(&failure, @"A data directory changed or could not be opened."); break; }
            ok = SnapshotDirectory(child, path, files, depth + 1, &failure);
            if (!ok) break;
        } else if (![name isEqual:@".DS_Store"]) {
            files[path] = @[@(st.st_dev), @(st.st_ino), @(st.st_size),
                @(st.st_mtimespec.tv_sec), @(st.st_mtimespec.tv_nsec),
                @(st.st_ctimespec.tv_sec), @(st.st_ctimespec.tv_nsec)];
        }
    } }
    closedir(directory);
    if (!ok && error) *error = failure;
    return ok;
}

static NSDictionary *DataSnapshot(NSURL *library, NSDictionary *identity, NSError **error) {
    NSMutableDictionary *snapshot = [NSMutableDictionary new];
    NSArray *roots = identity[@"ModDirectory"] ? @[identity[@"RomFSDirectory"], identity[@"ModDirectory"]] : @[identity[@"RomFSDirectory"]];
    for (NSString *relative in roots) {
        NSURL *folder = SafeURL(library, relative, error);
        if (!folder) return nil;
        NSMutableDictionary *files = [NSMutableDictionary new];
        int fd = open(folder.fileSystemRepresentation, O_RDONLY | O_DIRECTORY | O_NOFOLLOW);
        if (fd < 0) { Fail(error, @"The data folder could not be opened."); return nil; }
        if (!SnapshotDirectory(fd, @"", files, 0, error)) return nil;
        snapshot[relative] = files;
    }
    return snapshot;
}

NSDictionary *BDSPCheckInstalledData(NSURL *library, NSDictionary *identity, NSURL *manifestURL,
    NSURL *receiptURL, BOOL forceFull, BOOL *usedReceipt,
    void (^progress)(NSUInteger, NSUInteger), NSError **error) {
    CFAbsoluteTime started = CFAbsoluteTimeGetCurrent();
    if (usedReceipt) *usedReceipt = NO;
    NSNumber *manifestSize = nil;
    [manifestURL getResourceValue:&manifestSize forKey:NSURLFileSizeKey error:error];
    if (!manifestSize || manifestSize.unsignedLongLongValue > 32 * 1024 * 1024) {
        Fail(error, @"Invalid data manifest size."); return nil;
    }
    NSString *manifestHash = BDSPFileSHA256(manifestURL, error);
    if (!manifestHash) return nil;
    NSDictionary *before = DataSnapshot(library, identity, error);
    if (!before) return nil;
    NSDictionary *receipt = receiptURL ? [NSDictionary dictionaryWithContentsOfURL:receiptURL] : nil;
    if (!forceFull && [receipt[@"schema"] isEqual:@1] &&
        [receipt[@"manifestSHA256"] isEqual:manifestHash] &&
        [receipt[@"identity"] isEqual:identity] &&
        [receipt[@"files"] isEqual:before]) {
        NSData *bytes = [NSData dataWithContentsOfURL:manifestURL options:0 error:error];
        NSDictionary *manifest = bytes ? [NSJSONSerialization JSONObjectWithData:bytes options:0 error:error] : nil;
        if ([manifest isKindOfClass:NSDictionary.class] && [manifest[@"schema"] isEqual:@1] && [manifest[@"identity"] isEqual:identity]) {
            if (usedReceipt) *usedReceipt = YES;
            fprintf(stderr, "[data] unchanged inventory: metadata check %.3f s\n", CFAbsoluteTimeGetCurrent() - started);
            return manifest;
        }
    }
    // Invalidate before starting; an interrupted or failed check never leaves a hit.
    if (receiptURL) [NSFileManager.defaultManager removeItemAtURL:receiptURL error:nil];
    NSDictionary *manifest = BDSPVerifyInstalledData(library, identity, manifestURL, progress, error);
    if (!manifest) return nil;
    NSDictionary *after = DataSnapshot(library, identity, error);
    if (!after || ![before isEqual:after] || ![manifestHash isEqual:BDSPFileSHA256(manifestURL, error)]) {
        Fail(error, @"Game data changed during verification. Check again."); return nil;
    }
    if (receiptURL) {
        NSDictionary *value = @{@"schema":@1, @"manifestSHA256":manifestHash,
            @"identity":identity, @"files":after};
        NSData *bytes = [NSPropertyListSerialization dataWithPropertyList:value format:NSPropertyListBinaryFormat_v1_0 options:0 error:nil];
        // Cache failure is harmless: the next launch simply hashes again.
        [NSFileManager.defaultManager createDirectoryAtURL:receiptURL.URLByDeletingLastPathComponent
            withIntermediateDirectories:YES attributes:nil error:nil];
        [bytes writeToURL:receiptURL options:NSDataWritingAtomic error:nil];
    }
    fprintf(stderr, "[data] full SHA-256 verification %.3f s\n", CFAbsoluteTimeGetCurrent() - started);
    return manifest;
}

NSDictionary *BDSPCheckLibrary(NSURL *library, NSDictionary *identity, NSURL *receipt,
    BOOL forceFull, void (^progress)(NSUInteger, NSUInteger), NSError **error) {
    NSURL *manifest = SafeURL(library, identity[@"DataManifest"], error);
    return manifest ? BDSPCheckInstalledData(library, identity, manifest, receipt, forceFull, NULL, progress, error) : nil;
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
