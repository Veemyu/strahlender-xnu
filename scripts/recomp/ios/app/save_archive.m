#import "save_archive.h"
#import "data_library.h"
#include "../../runtime/save_snapshot.h"

static BOOL ArchiveError(NSError **error, NSString *message) {
    if (error) *error = [NSError errorWithDomain:@"SaveBackup" code:1 userInfo:@{NSLocalizedDescriptionKey:message}];
    return NO;
}
static BOOL Token(id value) {
    if (![value isKindOfClass:NSString.class] || ![value length] || [value length] > 128) return NO;
    return [value rangeOfCharacterFromSet:[[NSCharacterSet characterSetWithCharactersInString:@"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"] invertedSet]].location == NSNotFound;
}
static BOOL Identity(NSDictionary *identity) { return Token(identity[@"GameID"]) && Token(identity[@"ProfileID"]); }
BOOL BDSPBackupFolderIsIndependent(NSString *home, NSString *destination) {
    home = home.stringByStandardizingPath;
    destination = destination.stringByStandardizingPath;
    if ([home hasPrefix:@"/private/var/"]) home = [home substringFromIndex:8];
    if ([destination hasPrefix:@"/private/var/"]) destination = [destination substringFromIndex:8];
    // LiveContainer may virtualize HOME to a guest directory inside its own
    // system sandbox. A sibling folder there is still lost with the host app.
    NSArray *parts = home.pathComponents;
    NSString *boundary = home;
    for (NSUInteger i = 0; i + 3 < parts.count; i++) {
        BOOL app = [parts[i] isEqual:@"Containers"] && [parts[i+1] isEqual:@"Data"] && [parts[i+2] isEqual:@"Application"];
        BOOL group = [parts[i] isEqual:@"Containers"] && [parts[i+1] isEqual:@"Shared"] && [parts[i+2] isEqual:@"AppGroup"];
        if (app || group) { boundary = [NSString pathWithComponents:[parts subarrayWithRange:NSMakeRange(0, i+4)]]; break; }
    }
    return ![destination isEqual:boundary] && ![destination hasPrefix:[boundary stringByAppendingString:@"/"]];
}
static NSArray *Payload(NSURL *snapshot, NSError **error) {
    NSArray *all = BDSPInventory(snapshot, error);
    if (!all) return nil;
    NSMutableArray *files = [NSMutableArray array];
    for (NSDictionary *entry in all) if (![entry[@"path"] isEqual:@"backup.json"]) [files addObject:entry];
    return files;
}
BOOL BDSPSealSnapshot(NSURL *snapshot, NSURL *saveRoot, NSDictionary *identity, NSString *slot, NSError **error) {
    if (!Identity(identity) || !Token(slot) || ![slot hasPrefix:@"save_"]) return ArchiveError(error, @"Invalid save identity.");
    NSURL *uid = [saveRoot URLByAppendingPathComponent:@"user_id.hex"];
    if ([NSFileManager.defaultManager fileExistsAtPath:uid.path] &&
        ![NSFileManager.defaultManager copyItemAtURL:uid toURL:[snapshot URLByAppendingPathComponent:@"user_id.hex"] error:error]) return NO;
    NSArray *files = Payload(snapshot, error);
    if (!files || !files.count) return ArchiveError(error, @"The local save snapshot is empty or unreadable.");
    return BDSPWriteJSON(@{@"schema":@1, @"identity":identity, @"slot":slot, @"files":files},
        [snapshot URLByAppendingPathComponent:@"backup.json"], error);
}
NSDictionary *BDSPCheckSnapshot(NSURL *snapshot, NSDictionary *identity, NSError **error) {
    NSURL *file = [snapshot URLByAppendingPathComponent:@"backup.json"];
    NSNumber *size = nil;
    [file getResourceValue:&size forKey:NSURLFileSizeKey error:error];
    if (!Identity(identity) || !size || size.unsignedLongLongValue > 1024 * 1024) { ArchiveError(error, @"Missing or invalid backup manifest."); return nil; }
    NSData *bytes = [NSData dataWithContentsOfURL:file options:0 error:error];
    id parsed = bytes ? [NSJSONSerialization JSONObjectWithData:bytes options:0 error:error] : nil;
    if (![parsed isKindOfClass:NSDictionary.class] || ![parsed[@"schema"] isEqual:@1] ||
        ![parsed[@"identity"] isEqual:identity] || !Token(parsed[@"slot"]) || ![parsed[@"slot"] hasPrefix:@"save_"]) {
        ArchiveError(error, @"This backup belongs to another game or save profile."); return nil;
    }
    NSArray *files = Payload(snapshot, error);
    if (!files || !files.count || ![files isEqual:parsed[@"files"]]) {
        ArchiveError(error, @"The backup is incomplete or its checksums do not match."); return nil;
    }
    for (NSDictionary *entry in files) if (![entry[@"path"] hasPrefix:@"save/"] && ![entry[@"path"] isEqual:@"user_id.hex"]) {
        ArchiveError(error, @"Unexpected files in the save backup."); return nil;
    }
    return parsed;
}
BOOL BDSPExportSnapshot(NSURL *snapshot, NSURL *external, NSDictionary *identity, NSError **error) {
    if (!BDSPCheckSnapshot(snapshot, identity, error)) return NO;
    NSFileManager *fm = NSFileManager.defaultManager;
    NSURL *parent = [[external URLByAppendingPathComponent:identity[@"GameID"]] URLByAppendingPathComponent:identity[@"ProfileID"]];
    if (![fm createDirectoryAtURL:parent withIntermediateDirectories:YES attributes:nil error:error]) return NO;
    NSURL *target = [parent URLByAppendingPathComponent:snapshot.lastPathComponent];
    if ([fm fileExistsAtPath:target.path]) {
        NSDictionary *existing = BDSPCheckSnapshot(target, identity, error);
        NSDictionary *source = BDSPCheckSnapshot(snapshot, identity, error);
        return existing && [existing isEqual:source];
    }
    NSURL *stage = [parent URLByAppendingPathComponent:[@".pending-" stringByAppendingString:NSUUID.UUID.UUIDString]];
    if (![fm copyItemAtURL:snapshot toURL:stage error:error]) { [fm removeItemAtURL:stage error:nil]; return NO; }
    if (!BDSPCheckSnapshot(stage, identity, error) || ![fm moveItemAtURL:stage toURL:target error:error]) {
        [fm removeItemAtURL:stage error:nil]; return NO;
    }
    return BDSPCheckSnapshot(target, identity, error) != nil;
}

// A journal is local, uses only generated names and never points outside saveRoot.
BOOL BDSPRecoverRestore(NSURL *saveRoot, NSError **error) {
    NSFileManager *fm = NSFileManager.defaultManager;
    NSURL *journal = [saveRoot URLByAppendingPathComponent:@".restore.json"];
    if (![fm fileExistsAtPath:journal.path]) return YES;
    NSData *bytes = [NSData dataWithContentsOfURL:journal options:0 error:error];
    id state = bytes ? [NSJSONSerialization JSONObjectWithData:bytes options:0 error:error] : nil;
    if (![state isKindOfClass:NSDictionary.class] || !Token(state[@"slot"]) || ![state[@"slot"] hasPrefix:@"save_"] ||
        !Token(state[@"old"]) || ![state[@"old"] hasPrefix:@"restore-old-"] || !Token(state[@"stage"]) || ![state[@"stage"] hasPrefix:@"restore-stage-"]) return ArchiveError(error, @"An interrupted restore needs inspection; saves were kept.");
    NSURL *target = [saveRoot URLByAppendingPathComponent:state[@"slot"]];
    NSURL *old = [saveRoot URLByAppendingPathComponent:state[@"old"]];
    NSURL *stage = [saveRoot URLByAppendingPathComponent:state[@"stage"]];
    if (![fm fileExistsAtPath:target.path]) {
        // Prefer the previous state. For an initially empty profile, complete the
        // verified staged restore instead. Neither branch discards a save.
        NSURL *recover = [fm fileExistsAtPath:old.path] ? old : stage;
        if (![fm moveItemAtURL:recover toURL:target error:error]) return NO;
    }
    return [fm removeItemAtURL:journal error:error];
}

BOOL BDSPRestoreSnapshot(NSURL *snapshot, NSURL *saveRoot, NSDictionary *identity, NSError **error) {
    NSDictionary *manifest = BDSPCheckSnapshot(snapshot, identity, error);
    if (!manifest || !BDSPRecoverRestore(saveRoot, error)) return NO;
    NSFileManager *fm = NSFileManager.defaultManager;
    NSString *slot = manifest[@"slot"];
    NSURL *uid = [saveRoot URLByAppendingPathComponent:@"user_id.hex"];
    NSData *incoming = [NSData dataWithContentsOfURL:[snapshot URLByAppendingPathComponent:@"user_id.hex"]];
    NSData *current = [NSData dataWithContentsOfURL:uid];
    if (current && incoming && ![current isEqual:incoming]) return ArchiveError(error, @"The backup has a different player identity. The existing profile was kept.");
    if (![fm createDirectoryAtURL:saveRoot withIntermediateDirectories:YES attributes:nil error:error]) return NO;
    NSString *suffix = NSUUID.UUID.UUIDString;
    NSString *stageName = [@"restore-stage-" stringByAppendingString:suffix];
    NSString *oldName = [@"restore-old-" stringByAppendingString:suffix];
    NSURL *stage = [saveRoot URLByAppendingPathComponent:stageName];
    NSURL *old = [saveRoot URLByAppendingPathComponent:oldName];
    NSURL *target = [saveRoot URLByAppendingPathComponent:slot];
    if (![fm copyItemAtURL:[snapshot URLByAppendingPathComponent:@"save"] toURL:stage error:error]) return NO;
    if (![BDSPInventory(stage, error) isEqual:BDSPInventory([snapshot URLByAppendingPathComponent:@"save"], error)]) return ArchiveError(error, @"Restore copy verification failed; the original save was kept.");
    if (!current && incoming && ![incoming writeToURL:uid options:NSDataWritingAtomic error:error]) return NO;
    if (bdsp_save_flush(stage.fileSystemRepresentation) || (incoming && bdsp_save_flush(uid.fileSystemRepresentation))) return ArchiveError(error, @"The restored data could not be flushed. Existing saves were kept.");
    NSURL *journal = [saveRoot URLByAppendingPathComponent:@".restore.json"];
    if (!BDSPWriteJSON(@{@"slot":slot, @"old":oldName, @"stage":stageName}, journal, error)) return NO;
    if ([fm fileExistsAtPath:target.path] && ![fm moveItemAtURL:target toURL:old error:error]) return NO;
    if (bdsp_save_flush_directory(saveRoot.fileSystemRepresentation)) return ArchiveError(error, @"The restore was interrupted. Restart to recover the previous save.");
    if (![fm moveItemAtURL:stage toURL:target error:error]) { BDSPRecoverRestore(saveRoot, nil); return NO; }
    if (bdsp_save_flush_directory(saveRoot.fileSystemRepresentation)) return ArchiveError(error, @"The restore needs recovery on next start. Both saves were kept.");
    // The previous complete save deliberately remains available beside the slot.
    return [fm removeItemAtURL:journal error:error];
}
