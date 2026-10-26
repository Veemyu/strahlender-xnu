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
