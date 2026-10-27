// Native filesystem tests: only a fresh temporary directory, no device or saves.
#ifdef NDEBUG
#undef NDEBUG
#endif
#import "data_library.h"
#import "save_archive.h"
#include "../../rt-bdsp/save_snapshot.h"
#include <assert.h>
#include <sys/stat.h>
#include <unistd.h>

static NSURL *At(NSURL *root, NSString *name) { return [root URLByAppendingPathComponent:name]; }
static void Put(NSURL *root, NSString *name, NSString *value) {
    NSURL *file = At(root, name);
    assert([NSFileManager.defaultManager createDirectoryAtURL:file.URLByDeletingLastPathComponent withIntermediateDirectories:YES attributes:nil error:nil]);
    assert([value writeToURL:file atomically:YES encoding:NSUTF8StringEncoding error:nil]);
}
int main(void) { @autoreleasepool {
    NSString *guest = @"/private/var/mobile/Containers/Data/Application/host/Documents/Data/Application/guest";
    assert(!BDSPBackupFolderIsIndependent(guest, @"/var/mobile/Containers/Data/Application/host/Documents/Backups"));
    assert(!BDSPBackupFolderIsIndependent(guest, guest));
    assert(BDSPBackupFolderIsIndependent(guest, @"/var/mobile/Library/Mobile Documents/com~apple~CloudDocs/Backups"));
    assert(BDSPBackupFolderIsIndependent(guest, @"/var/mobile/Containers/Shared/AppGroup/file-provider/Backups"));
    NSFileManager *fm = NSFileManager.defaultManager;
    NSURL *root = At([NSURL fileURLWithPath:NSTemporaryDirectory()], NSUUID.UUID.UUIDString);
    NSURL *romfs = At(root, @"source/romfs");
    NSURL *library = At(root, @"Game Library");
    Put(romfs, @"Data/game.bin", @"original");
    NSDictionary *identity = @{@"GameID":@"0100000011d90000", @"GameVersion":@"1.3.0", @"RomFSDirectory":@"GameData/version1/romfs", @"SaveProfile":@"vanilla", @"DataManifest":@"Manifests/version1.json", @"ExternalLibrary":@YES};
    NSError *failure = nil;
    BOOL exported = BDSPExportLibrary(romfs, nil, identity, library, &failure);
    if (!exported) fprintf(stderr, "%s\n", failure.localizedDescription.UTF8String);
    assert(exported);
    assert(BDSPVerifyLibrary(library, identity, nil));
    NSURL *expected = At(root, @"expected-library.json");
    assert(BDSPCreateLibraryManifest(romfs, nil, identity, expected, nil));
    assert(BDSPVerifyInstalledData(library, identity, expected, nil, nil));
    assert(BDSPExportLibrary(romfs, nil, identity, library, nil)); // Reuse without replacement.
    Put(library, @"GameData/version1/romfs/Data/game.bin", @"corruption");
    assert(!BDSPVerifyLibrary(library, identity, nil));
    assert(!BDSPVerifyInstalledData(library, identity, expected, nil, nil));
    assert(!BDSPExportLibrary(romfs, nil, identity, library, nil));
    Put(library, @"GameData/version1/romfs/Data/game.bin", @"original");
    NSMutableDictionary *wrong = identity.mutableCopy;
    wrong[@"GameID"] = @"0000000000000000";
    assert(!BDSPVerifyLibrary(library, wrong, nil));
    wrong = identity.mutableCopy; wrong[@"DataManifest"] = @"../outside.json";
    assert(!BDSPVerifyLibrary(library, wrong, nil));
    NSURL *link = At(romfs, @"unsafe");
    assert(symlink("Data/game.bin", link.fileSystemRepresentation) == 0);
    assert(!BDSPExportLibrary(romfs, nil, identity, At(root, @"unsafe-library"), nil));
    assert([fm removeItemAtURL:link error:nil]);
    Put(library, @"Manifests/version1.json", @"[]");
    assert(!BDSPVerifyLibrary(library, identity, nil));
    assert(BDSPExportLibrary(romfs, nil, identity, library, nil));
    NSDictionary *version2 = @{@"GameID":@"0100000011d90000", @"GameVersion":@"2", @"RomFSDirectory":@"GameData/version2/romfs", @"SaveProfile":@"vanilla", @"DataManifest":@"Manifests/version2.json", @"ExternalLibrary":@YES};
    Put(romfs, @"Data/game.bin", @"new-version");
    assert(BDSPExportLibrary(romfs, nil, version2, library, nil));
    assert(BDSPVerifyLibrary(library, identity, nil)); // Previous version remains usable.
    assert(BDSPVerifyLibrary(library, version2, nil));
    NSURL *mod = At(root, @"mod");
    Put(mod, @"romfs/Data/overlay.bin", @"overlay");
    Put(mod, @"exefs/test.ips", @"PATCH");
    Put(mod, @"prod.keys", @"must not be exported");
    Put(mod, @"Saves/SaveData.bin", @"must not be exported");
    NSMutableDictionary *modIdentity = version2.mutableCopy;
    modIdentity[@"ModDirectory"] = @"Mods/version1/Luminescent Platinum";
    modIdentity[@"DataManifest"] = @"Manifests/mod.json";
    assert(BDSPExportLibrary(romfs, mod, modIdentity, library, nil));
    assert(BDSPVerifyLibrary(library, modIdentity, nil));
    assert(![fm fileExistsAtPath:At(library, @"Mods/version1/Luminescent Platinum/prod.keys").path]);
    assert(![fm fileExistsAtPath:At(library, @"Mods/version1/Luminescent Platinum/Saves").path]);
    // Known build mods are checked; separately added overlays do not alter the base inventory.
    Put(library, @"Mods/version1/Luminescent Platinum/romfs/Data/overlay.bin", @"changed-overlay");
    assert(!BDSPVerifyLibrary(library, modIdentity, nil));
    assert(BDSPVerifyLibrary(library, version2, nil));
    Put(library, @"Mods/version1/Luminescent Platinum/romfs/Data/overlay.bin", @"overlay");
    Put(library, @"Mods/manual/romfs/Data/user-mod.bin", @"new-user-overlay");
    assert(BDSPVerifyLibrary(library, version2, nil));
    assert(BDSPVerifyLibrary(library, modIdentity, nil));
    Put(library, @"GameData/version2/romfs/Data/unlisted.bin", @"changed-base");
    assert(!BDSPVerifyLibrary(library, version2, nil));
    assert([fm removeItemAtURL:At(library, @"GameData/version2/romfs/Data/unlisted.bin") error:nil]);

    Put(root, @"test.ipa", @"package");
    assert(BDSPExportIPA(At(root, @"test.ipa"), At(root, @"export.ipa"), nil));
    assert(BDSPExportIPA(At(root, @"test.ipa"), At(root, @"export.ipa"), nil));
    Put(root, @"test.ipa", @"different-package");
    assert(!BDSPExportIPA(At(root, @"test.ipa"), At(root, @"export.ipa"), nil));

    NSURL *saves = At(root, @"Saves");
    Put(saves, @"save_1/SaveData.bin", @"previous-save");
    Put(saves, @"save_1/Backup.bin", @"previous-backup");
    Put(saves, @"user_id.hex", @"0123456789abcdef");
    NSURL *snapshots = At(root, @"snapshots");
    char snapshotPath[4096];
#ifdef BDSP_SAVE_FAULT_TESTS
    for (NSString *point in @[@"write", @"flush", @"publish"]) {
        setenv("BDSP_SAVE_FAIL_AT", point.UTF8String, 1);
        assert(bdsp_save_snapshot(At(saves, @"save_1").fileSystemRepresentation, snapshots.fileSystemRepresentation, snapshotPath, sizeof snapshotPath) != 0);
        assert(snapshotPath[0] == 0);
        assert([[NSString stringWithContentsOfURL:At(saves, @"save_1/SaveData.bin") encoding:NSUTF8StringEncoding error:nil] isEqual:@"previous-save"]);
    }
    unsetenv("BDSP_SAVE_FAIL_AT");
#endif
    assert(bdsp_save_flush(At(saves, @"save_1").fileSystemRepresentation) == 0);
    assert(bdsp_save_snapshot(At(saves, @"save_1").fileSystemRepresentation, snapshots.fileSystemRepresentation, snapshotPath, sizeof snapshotPath) == 0);
    NSURL *snapshot = [NSURL fileURLWithPath:@(snapshotPath)];
    NSDictionary *profile = @{@"GameID":@"0100000011d90000", @"ProfileID":@"vanilla"};
    assert(BDSPSealSnapshot(snapshot, saves, profile, @"save_1", nil));
    assert(BDSPCheckSnapshot(snapshot, profile, nil));
    assert(!BDSPCheckSnapshot(snapshot, @{@"GameID":@"0100000011d90000", @"ProfileID":@"lumi"}, nil));
    NSURL *external = At(root, @"external");
    assert(BDSPExportSnapshot(snapshot, external, profile, nil));
    assert(BDSPExportSnapshot(snapshot, external, profile, nil));
    Put(snapshot, @"save/SaveData.bin", @"broken");
    assert(!BDSPCheckSnapshot(snapshot, profile, nil));
    assert(!BDSPRestoreSnapshot(snapshot, saves, profile, nil));
    assert([[NSString stringWithContentsOfURL:At(saves, @"save_1/SaveData.bin") encoding:NSUTF8StringEncoding error:nil] isEqual:@"previous-save"]);
    Put(snapshot, @"save/SaveData.bin", @"previous-save");
    Put(saves, @"save_1/SaveData.bin", @"newer-save");
    assert(BDSPRestoreSnapshot(snapshot, saves, profile, nil));
    assert([[NSString stringWithContentsOfURL:At(saves, @"save_1/SaveData.bin") encoding:NSUTF8StringEncoding error:nil] isEqual:@"previous-save"]);
    BOOL foundPrevious = NO;
    for (NSURL *entry in [fm contentsOfDirectoryAtURL:saves includingPropertiesForKeys:nil options:0 error:nil]) {
        if ([entry.lastPathComponent hasPrefix:@"restore-old-"]) foundPrevious = [[NSString stringWithContentsOfURL:At(entry, @"SaveData.bin") encoding:NSUTF8StringEncoding error:nil] isEqual:@"newer-save"];
    }
    assert(foundPrevious);
    Put(saves, @"user_id.hex", @"another-player");
    assert(!BDSPRestoreSnapshot(snapshot, saves, profile, nil));
    // Simulate interruption after the old slot moved, before new slot activation.
    NSURL *old = At(saves, @"restore-old-test");
    assert([fm moveItemAtURL:At(saves, @"save_1") toURL:old error:nil]);
    assert(BDSPWriteJSON(@{@"slot":@"save_1", @"old":@"restore-old-test", @"stage":@"restore-stage-test"}, At(saves, @".restore.json"), nil));
    assert(BDSPRecoverRestore(saves, nil));
    assert([fm fileExistsAtPath:At(saves, @"save_1/SaveData.bin").path]);
    NSURL *empty = At(root, @"fresh-profile");
    assert([fm createDirectoryAtURL:empty withIntermediateDirectories:YES attributes:nil error:nil]);
    assert([fm copyItemAtURL:At(snapshot, @"save") toURL:At(empty, @"restore-stage-test") error:nil]);
    assert(BDSPWriteJSON(@{@"slot":@"save_1", @"old":@"restore-old-test", @"stage":@"restore-stage-test"}, At(empty, @".restore.json"), nil));
    assert(BDSPRecoverRestore(empty, nil));
    assert([fm fileExistsAtPath:At(empty, @"save_1/SaveData.bin").path]);
    assert(BDSPWriteJSON(@{@"slot":@"../save_1", @"old":@"restore-old-test", @"stage":@"restore-stage-test"}, At(empty, @".restore.json"), nil));
    assert(!BDSPRecoverRestore(empty, nil));
    char tooSmall[2];
    assert(bdsp_save_snapshot(At(saves, @"save_1").fileSystemRepresentation, snapshots.fileSystemRepresentation, tooSmall, sizeof tooSmall) != 0);
    assert(symlink("SaveData.bin", At(saves, @"save_1/link").fileSystemRepresentation) == 0);
    assert(bdsp_save_snapshot(At(saves, @"save_1").fileSystemRepresentation, snapshots.fileSystemRepresentation, snapshotPath, sizeof snapshotPath) != 0);
    assert(snapshotPath[0] == 0);
    for (NSURL *entry in [fm contentsOfDirectoryAtURL:snapshots includingPropertiesForKeys:nil options:0 error:nil]) assert(![entry.lastPathComponent hasPrefix:@".pending-"]);
    assert([fm removeItemAtURL:root error:nil]);
    puts("Native iOS data and save tests passed.");
    return 0;
} }
