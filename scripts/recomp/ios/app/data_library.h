#import <Foundation/Foundation.h>

// Shared by the native macOS exporter and the iOS document-picker adapter.
NSDictionary *BDSPVerifyLibrary(NSURL *library, NSDictionary *identity, NSError **error);
NSDictionary *BDSPVerifyLibraryProgress(NSURL *library, NSDictionary *identity, void (^progress)(NSUInteger, NSUInteger), NSError **error);
BOOL BDSPExportLibrary(NSURL *romfs, NSURL *mod, NSDictionary *identity, NSURL *library, NSError **error);
BOOL BDSPCreateLibraryManifest(NSURL *romfs, NSURL *mod, NSDictionary *identity, NSURL *output, NSError **error);
NSDictionary *BDSPVerifyInstalledData(NSURL *library, NSDictionary *identity, NSURL *manifest, void (^progress)(NSUInteger, NSUInteger), NSError **error);
NSString *BDSPFileSHA256(NSURL *file, NSError **error);
BOOL BDSPWriteJSON(id value, NSURL *file, NSError **error);
NSArray *BDSPInventory(NSURL *folder, NSError **error);
BOOL BDSPExportIPA(NSURL *source, NSURL *destination, NSError **error);

// Cheap diagnosis (no hashing) of why game data cannot be used, for a clear message before the slow
// verification. BDSPDataOK only means nothing obvious is wrong; BDSPCheck* still decides.
typedef NS_ENUM(NSInteger, BDSPDataProblem) {
    BDSPDataOK = 0,
    BDSPDataFolderMissing,    // the RomFS folder does not exist
    BDSPDataFolderEmpty,      // it exists but holds no files
    BDSPDataZeroLength,       // files the inventory requires have length 0
    BDSPDataIncomplete,       // files the inventory requires are missing or differ in size
    BDSPDataManifestInvalid,  // the inventory cannot be read or lists no files
};
// manifest == nil (development bundles without an inventory): Data/ must hold a file with content.
// affected receives the number of required files that are missing or empty.
BDSPDataProblem BDSPInspectData(NSURL *library, NSDictionary *identity, NSURL *manifest, NSUInteger *affected);
// Same for a Game Library folder; its inventory is identity[@"DataManifest"] inside the library.
BDSPDataProblem BDSPInspectLibrary(NSURL *library, NSDictionary *identity, NSUInteger *affected);

// Fast metadata check only after a successful full verification. forceFull is
// used for explicit checks/imports. receipt belongs in app-private Library/Caches.
NSDictionary *BDSPCheckInstalledData(NSURL *library, NSDictionary *identity, NSURL *manifest,
    NSURL *receipt, BOOL forceFull, BOOL *usedReceipt,
    void (^progress)(NSUInteger, NSUInteger), NSError **error);
NSDictionary *BDSPCheckLibrary(NSURL *library, NSDictionary *identity, NSURL *receipt,
    BOOL forceFull, void (^progress)(NSUInteger, NSUInteger), NSError **error);
