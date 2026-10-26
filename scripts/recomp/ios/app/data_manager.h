#import <UIKit/UIKit.h>
void BDSPPrepareData(UIViewController *presenter, NSDictionary *identity, void (^ready)(void));
void BDSPConfirmStart(void (^ready)(void));
// Pre-start failures only: no running game thread may be marked stopped here.
void BDSPShowDataError(NSString *detail);
NSString *BDSPSharedDataPath(NSString *relative);
BOOL BDSPConfigureSaveRoot(NSString *path, NSDictionary *identity, NSString *profile, NSError **error);
NSString *BDSPCurrentSaveRoot(void);
NSString *BDSPBaseSaveRoot(void);
