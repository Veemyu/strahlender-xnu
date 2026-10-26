#import <Foundation/Foundation.h>
BOOL BDSPSealSnapshot(NSURL *snapshot, NSURL *saveRoot, NSDictionary *identity, NSString *slot, NSError **error);
NSDictionary *BDSPCheckSnapshot(NSURL *snapshot, NSDictionary *identity, NSError **error);
BOOL BDSPExportSnapshot(NSURL *snapshot, NSURL *external, NSDictionary *identity, NSError **error);
BOOL BDSPRestoreSnapshot(NSURL *snapshot, NSURL *saveRoot, NSDictionary *identity, NSError **error);
BOOL BDSPRecoverRestore(NSURL *saveRoot, NSError **error);
BOOL BDSPBackupFolderIsIndependent(NSString *home, NSString *destination);
