#import "data_manager.h"
#import "data_library.h"
#import "save_archive.h"
#import <UniformTypeIdentifiers/UniformTypeIdentifiers.h>
#include "../../rt-bdsp/save_snapshot.h"
#include <CommonCrypto/CommonDigest.h>
#include <sys/stat.h>

static NSString *T(NSString *en, NSString *de, NSString *es, NSString *pt, NSString *ru) {
    NSString *base = [[NSLocale.preferredLanguages.firstObject componentsSeparatedByCharactersInSet:[NSCharacterSet characterSetWithCharactersInString:@"-_"]] firstObject];
    if ([base isEqual:@"de"]) return de;
    if ([base isEqual:@"es"]) return es;
    if ([base isEqual:@"pt"]) return pt;
    if ([base isEqual:@"ru"] || [base isEqual:@"uk"]) return ru;
    return en;
}
@interface BDSPDataManager : NSObject <UIDocumentPickerDelegate>
@property(nonatomic, weak) UIViewController *presenter;
@property(nonatomic, copy) void (^ready)(void);
@property(nonatomic, copy) void (^dataReady)(void);
@property(nonatomic, copy) NSDictionary *identity;
@property(nonatomic, copy) NSDictionary *saveIdentity;
@property(nonatomic, copy) NSString *saveRoot;
@property(nonatomic, copy) NSString *saveLabel;
@property(nonatomic, copy) NSString *baseSaveRoot;
@property(nonatomic, strong) NSURL *library;
@property(nonatomic, strong) NSData *pendingLibraryBookmark;
@property(nonatomic) BOOL libraryScoped;
@property(nonatomic) BOOL verified;
@property(nonatomic) BOOL running;
@property(nonatomic) BOOL initialDataPhase;
@property(nonatomic) BOOL deviceDataReady;
@property(nonatomic) NSInteger pickerMode;
@property(nonatomic, strong) dispatch_queue_t backupQueue;
@property(nonatomic, strong) UILabel *statusLabel;
@property(nonatomic) NSUInteger statusVersion;
@end
static BDSPDataManager *manager;

static NSString *LibraryKey(void) { return @"bdsp_game_library_bookmark_v1"; }
static NSString *BackupKey(void) { return @"bdsp_save_backup_bookmark_v1"; }
static NSURL *Resolve(NSString *key) {
    NSData *bookmark = [NSUserDefaults.standardUserDefaults dataForKey:key];
    BOOL stale = NO;
    NSURL *url = bookmark ? [NSURL URLByResolvingBookmarkData:bookmark options:0 relativeToURL:nil bookmarkDataIsStale:&stale error:nil] : nil;
    if (!url || stale) return nil;
    return url;
}
static NSString *DocumentsPath(void) { return NSSearchPathForDirectoriesInDomains(NSDocumentDirectory, NSUserDomainMask, YES).firstObject; }
static NSString *StatusKey(NSDictionary *identity) { return [NSString stringWithFormat:@"bdsp_backup_status_%@_%@", identity[@"GameID"], identity[@"ProfileID"]]; }
static NSString *ProfileForMod(NSString *name) {
    NSData *bytes = [name.lowercaseString dataUsingEncoding:NSUTF8StringEncoding];
    unsigned char hash[CC_SHA256_DIGEST_LENGTH]; CC_SHA256(bytes.bytes, (CC_LONG)bytes.length, hash);
    NSMutableString *result = [NSMutableString string];
    for (unsigned i = 0; i < sizeof hash; i++) [result appendFormat:@"%02x", hash[i]];
    return [result substringToIndex:20];
}

@implementation BDSPDataManager
- (void)message:(NSString *)text {
    UIAlertController *alert = [UIAlertController alertControllerWithTitle:T(@"Game data & saves", @"Spieldaten & Saves", @"Datos y partidas", @"Dados e progresso", @"Данные и сохранения") message:text preferredStyle:UIAlertControllerStyleAlert];
    [alert addAction:[UIAlertAction actionWithTitle:@"OK" style:UIAlertActionStyleDefault handler:^(UIAlertAction *action) { (void)action; [self menu]; }]];
    [self.presenter presentViewController:alert animated:YES completion:nil];
}
- (void)pick:(NSInteger)mode {
    self.pickerMode = mode;
    UIDocumentPickerViewController *picker = [[UIDocumentPickerViewController alloc] initForOpeningContentTypes:@[UTTypeFolder] asCopy:NO];
    picker.delegate = self;
    picker.allowsMultipleSelection = NO;
    [self.presenter presentViewController:picker animated:YES completion:nil];
}
- (void)addImportAction:(UIAlertController *)alert {
    if (!self.pendingLibraryBookmark) return;
    [alert addAction:[UIAlertAction actionWithTitle:T(@"Import new game files", @"Neue Spieldaten importieren", @"Importar nuevos datos", @"Importar novos dados", @"Импортировать новые данные") style:UIAlertActionStyleDefault handler:^(UIAlertAction *a) { (void)a; [self pick:4]; }]];
}
- (void)menu {
    if (self.initialDataPhase) {
        UIAlertController *choose = [UIAlertController alertControllerWithTitle:T(@"Choose game library", @"Spieldaten auswählen", @"Elegir biblioteca", @"Escolher biblioteca", @"Выбрать библиотеку") message:T(@"Select the Game Library folder exported by the installer. Keep it locally available on this device.", @"Den vom Installer exportierten Ordner Game Library auswählen und lokal auf diesem Gerät verfügbar halten.", @"Selecciona Game Library, exportada por el instalador. Mantén los archivos disponibles en el dispositivo.", @"Seleciona Game Library, exportada pelo instalador. Mantém os ficheiros disponíveis no dispositivo.", @"Выберите папку Game Library из установщика. Файлы должны быть доступны локально на устройстве.") preferredStyle:UIAlertControllerStyleAlert];
        [choose addAction:[UIAlertAction actionWithTitle:T(@"Choose folder", @"Ordner auswählen", @"Elegir carpeta", @"Escolher pasta", @"Выбрать папку") style:UIAlertActionStyleDefault handler:^(UIAlertAction *a) { (void)a; [self pick:1]; }]];
        [self addImportAction:choose];
        [self.presenter presentViewController:choose animated:YES completion:nil]; return;
    }
    BOOL needsLibrary = [self.identity[@"ExternalLibrary"] boolValue];
    BOOL canPlay = needsLibrary ? self.verified : self.deviceDataReady;
    NSString *profile = [self.saveIdentity[@"ProfileID"] isEqual:@"vanilla"] ? T(@"Unmodified game", @"Unverändertes Spiel", @"Juego sin modificar", @"Jogo sem alterações", @"Игра без модов") : self.saveLabel;
    UIAlertController *alert = [UIAlertController alertControllerWithTitle:canPlay ? T(@"Ready to play", @"Bereit zum Spielen", @"Listo para jugar", @"Pronto para jogar", @"Готово к игре") : T(@"Check game files", @"Spieldaten prüfen", @"Comprobar datos", @"Verificar dados", @"Проверка данных") message:profile preferredStyle:UIAlertControllerStyleAlert];
    UIAlertAction *play = [UIAlertAction actionWithTitle:T(@"Play", @"Spielen", @"Jugar", @"Jogar", @"Играть") style:UIAlertActionStyleDefault handler:^(UIAlertAction *a) {
        (void)a;
        if (![self protectBeforeUpdate]) return;
        self.running = YES;
        [self retryBackups];
        self.ready();
    }];
    play.enabled = canPlay;
    [alert addAction:play];
    [alert addAction:[UIAlertAction actionWithTitle:T(@"Saves & backups…", @"Saves & Backups…", @"Partidas y copias…", @"Progresso e cópias…", @"Сохранения и копии…") style:UIAlertActionStyleDefault handler:^(UIAlertAction *a) { (void)a; [self saveMenu]; }]];
    if (needsLibrary || !canPlay) [alert addAction:[UIAlertAction actionWithTitle:T(@"Game files…", @"Spieldaten…", @"Datos del juego…", @"Dados do jogo…", @"Файлы игры…") style:UIAlertActionStyleDefault handler:^(UIAlertAction *a) { (void)a; [self gameDataMenu]; }]];
    alert.preferredAction = canPlay ? play : nil;
    [self.presenter presentViewController:alert animated:YES completion:nil];
}
- (NSString *)backupStatus {
    return [NSUserDefaults.standardUserDefaults stringForKey:StatusKey(self.saveIdentity)] ?: T(@"No external backup yet.", @"Noch kein externes Backup.", @"Aún no hay copia externa.", @"Ainda sem cópia externa.", @"Внешней копии пока нет.");
}
- (void)saveMenu {
    UIAlertController *alert = [UIAlertController alertControllerWithTitle:T(@"Saves & backups", @"Saves & Backups", @"Partidas y copias", @"Progresso e cópias", @"Сохранения и копии") message:[self backupStatus] preferredStyle:UIAlertControllerStyleAlert];
    [alert addAction:[UIAlertAction actionWithTitle:T(@"Back up…", @"Sichern…", @"Crear copia…", @"Criar cópia…", @"Создать копию…") style:UIAlertActionStyleDefault handler:^(UIAlertAction *a) { (void)a; [self backupMenu]; }]];
    [alert addAction:[UIAlertAction actionWithTitle:T(@"Restore…", @"Wiederherstellen…", @"Restaurar…", @"Restaurar…", @"Восстановить…") style:UIAlertActionStyleDefault handler:^(UIAlertAction *a) { (void)a; [self chooseRestore]; }]];
    [alert addAction:[UIAlertAction actionWithTitle:T(@"Back", @"Zurück", @"Volver", @"Voltar", @"Назад") style:UIAlertActionStyleCancel handler:^(UIAlertAction *a) { (void)a; [self menu]; }]];
    [self.presenter presentViewController:alert animated:YES completion:nil];
}
- (void)backupMenu {
    NSString *hint = T(@"Keep backups outside this app. If you delete the app or its LiveContainer data container, local saves can be lost.", @"Lege deine Backups außerhalb der App ab. Wenn du die App oder den zugehörigen LiveContainer-Datencontainer löschst, können deine lokalen Saves verloren gehen.", @"Guarda copias fuera de esta app. Si borras la app o su contenedor de LiveContainer, puedes perder las partidas locales.", @"Guarda cópias fora desta aplicação. Se apagares a aplicação ou o contentor do LiveContainer, podes perder o progresso local.", @"Храните копии вне приложения. При удалении приложения или контейнера LiveContainer локальные сохранения могут быть потеряны.");
    UIAlertController *alert = [UIAlertController alertControllerWithTitle:T(@"Back up your save", @"Deinen Save sichern", @"Guardar tu partida", @"Guardar o teu progresso", @"Резервная копия сохранения") message:hint preferredStyle:UIAlertControllerStyleAlert];
    [alert addAction:[UIAlertAction actionWithTitle:T(@"Choose backup folder", @"Backup-Ordner auswählen", @"Elegir carpeta de copias", @"Escolher pasta de cópias", @"Выбрать папку копий") style:UIAlertActionStyleDefault handler:^(UIAlertAction *a) { (void)a; [self pick:2]; }]];
    NSString *slot = [self.saveRoot stringByAppendingPathComponent:@"save_1"];
    BOOL hasSave = [NSFileManager.defaultManager fileExistsAtPath:[slot stringByAppendingPathComponent:@"SaveData.bin"]] || [NSFileManager.defaultManager fileExistsAtPath:[slot stringByAppendingPathComponent:@"Backup.bin"]];
    if (hasSave) [alert addAction:[UIAlertAction actionWithTitle:T(@"Back up now", @"Jetzt sichern", @"Crear copia ahora", @"Criar cópia agora", @"Создать копию") style:UIAlertActionStyleDefault handler:^(UIAlertAction *a) { (void)a; [self backupNow]; }]];
    [alert addAction:[UIAlertAction actionWithTitle:T(@"Back", @"Zurück", @"Volver", @"Voltar", @"Назад") style:UIAlertActionStyleCancel handler:^(UIAlertAction *a) { (void)a; [self saveMenu]; }]];
    [self.presenter presentViewController:alert animated:YES completion:nil];
}
- (void)gameDataMenu {
    BOOL needsLibrary = [self.identity[@"ExternalLibrary"] boolValue];
    UIAlertController *alert = [UIAlertController alertControllerWithTitle:T(@"Game files", @"Spieldaten", @"Datos del juego", @"Dados do jogo", @"Файлы игры") message:nil preferredStyle:UIAlertControllerStyleAlert];
    if (needsLibrary) {
        [alert addAction:[UIAlertAction actionWithTitle:T(@"Choose game library", @"Spieldaten auswählen", @"Elegir biblioteca", @"Escolher biblioteca", @"Выбрать библиотеку") style:UIAlertActionStyleDefault handler:^(UIAlertAction *a) { (void)a; [self pick:1]; }]];
        [self addImportAction:alert];
        if (self.library) [alert addAction:[UIAlertAction actionWithTitle:T(@"Check game files again", @"Spieldaten erneut prüfen", @"Volver a comprobar datos", @"Verificar os dados novamente", @"Проверить данные снова") style:UIAlertActionStyleDefault handler:^(UIAlertAction *a) { (void)a; [self verify:self.library]; }]];
    } else {
        [alert addAction:[UIAlertAction actionWithTitle:T(@"Check game files again", @"Spieldaten erneut prüfen", @"Volver a comprobar datos", @"Verificar os dados novamente", @"Проверить данные снова") style:UIAlertActionStyleDefault handler:^(UIAlertAction *a) { (void)a; [self verifyDeviceData:YES]; }]];
    }
    [alert addAction:[UIAlertAction actionWithTitle:T(@"Back", @"Zurück", @"Volver", @"Voltar", @"Назад") style:UIAlertActionStyleCancel handler:^(UIAlertAction *a) { (void)a; [self menu]; }]];
    [self.presenter presentViewController:alert animated:YES completion:nil];
}
- (BOOL)protectBeforeUpdate {
    NSUserDefaults *defaults = NSUserDefaults.standardUserDefaults;
    NSString *key = [StatusKey(self.saveIdentity) stringByAppendingString:@"_protected_build"];
    NSString *build = [NSBundle.mainBundle objectForInfoDictionaryKey:@"BDSPBuildID"] ?: @"legacy";
    if ([[defaults stringForKey:key] isEqual:build]) return YES;
    NSFileManager *fm = NSFileManager.defaultManager;
    NSURL *root = [NSURL fileURLWithPath:self.saveRoot];
    NSURL *slot = [root URLByAppendingPathComponent:@"save_1"];
    if (![fm fileExistsAtPath:[slot URLByAppendingPathComponent:@"SaveData.bin"].path] &&
        ![fm fileExistsAtPath:[slot URLByAppendingPathComponent:@"Backup.bin"].path]) return YES;
    NSURL *parent = [root URLByAppendingPathComponent:@"_upgrade-backups"];
    NSError *error = nil;
    char path[4096];
    struct stat metadata;
    BOOL ok = [fm createDirectoryAtURL:parent withIntermediateDirectories:YES attributes:nil error:&error] &&
        lstat(parent.fileSystemRepresentation, &metadata) == 0 && S_ISDIR(metadata.st_mode) &&
        bdsp_save_snapshot(slot.fileSystemRepresentation, [parent URLByAppendingPathComponent:@"save_1"].fileSystemRepresentation, path, sizeof path) == 0;
    NSURL *snapshot = ok ? [NSURL fileURLWithPath:@(path)] : nil;
    if (ok) ok = BDSPSealSnapshot(snapshot, root, self.saveIdentity, @"save_1", &error);
    if (!ok) {
        [self message:T(@"A backup before this update could not be created. Free space or fix folder access, then retry. The existing save was not changed.", @"Das Backup vor diesem Update konnte nicht erstellt werden. Speicherplatz freigeben oder Ordnerzugriff prüfen und erneut versuchen. Der vorhandene Save wurde nicht verändert.", @"No se pudo crear una copia previa a esta actualización. Libera espacio o comprueba el acceso y vuelve a intentarlo. La partida existente no cambió.", @"Não foi possível criar uma cópia antes desta atualização. Liberta espaço ou verifica o acesso e tenta novamente. O progresso existente não foi alterado.", @"Не удалось создать копию перед обновлением. Освободите место или проверьте доступ и повторите попытку. Прежнее сохранение не изменено.")]; return NO;
    }
    [defaults setObject:build forKey:key];
    NSDictionary *identity = self.saveIdentity;
    dispatch_async(self.backupQueue, ^{ [self exportSnapshot:snapshot identity:identity]; });
    return YES;
}
- (void)backupNow {
    if (self.running) return;
    NSFileManager *fm = NSFileManager.defaultManager;
    NSURL *root = [NSURL fileURLWithPath:self.saveRoot];
    NSURL *parent = [root URLByAppendingPathComponent:@"_snapshots"];
    NSError *error = nil;
    if (![fm createDirectoryAtURL:parent withIntermediateDirectories:YES attributes:nil error:&error]) { [self message:error.localizedDescription]; return; }
    char snapshot[4096];
    NSURL *directory = [parent URLByAppendingPathComponent:@"save_1"];
    if (bdsp_save_snapshot([root URLByAppendingPathComponent:@"save_1"].fileSystemRepresentation, directory.fileSystemRepresentation, snapshot, sizeof snapshot) ||
        !BDSPSealSnapshot([NSURL fileURLWithPath:@(snapshot)], root, self.saveIdentity, @"save_1", &error)) {
        [self message:T(@"The save could not be backed up. Existing files were kept.", @"Der Save konnte nicht gesichert werden. Bestehende Dateien bleiben erhalten.", @"No se pudo crear la copia. Los archivos existentes se conservan.", @"Não foi possível criar a cópia. Os ficheiros existentes foram mantidos.", @"Не удалось создать копию. Существующие файлы сохранены.")]; return;
    }
    [self retryBackups];
    [self message:T(@"Local backup created. External copies are retried when a backup folder is available.", @"Lokales Backup erstellt. Externe Kopien werden mit verfügbarem Backup-Ordner erneut versucht.", @"Copia local creada. Se intentará la copia externa cuando haya una carpeta disponible.", @"Cópia local criada. A cópia externa será tentada quando a pasta estiver disponível.", @"Локальная копия создана. Внешнее копирование повторится, когда папка станет доступна.")];
}
- (void)importDroppedSave {
    UIAlertController *confirm = [UIAlertController alertControllerWithTitle:T(@"Import this save?", @"Diesen Save importieren?", @"¿Importar esta partida?", @"Importar este progresso?", @"Импортировать сохранение?") message:T(@"The current save is kept as a recovery copy. The original imported files are not changed.", @"Der aktuelle Save bleibt als Wiederherstellungskopie erhalten. Die importierten Originaldateien werden nicht verändert.", @"Se conserva la partida actual como copia de recuperación. Los archivos originales no cambian.", @"O progresso atual fica como cópia de recuperação. Os ficheiros originais não são alterados.", @"Текущее сохранение останется в резервной копии. Исходные файлы не изменяются.") preferredStyle:UIAlertControllerStyleAlert];
    [confirm addAction:[UIAlertAction actionWithTitle:T(@"Cancel", @"Abbrechen", @"Cancelar", @"Cancelar", @"Отмена") style:UIAlertActionStyleCancel handler:^(UIAlertAction *a) { (void)a; [self menu]; }]];
    [confirm addAction:[UIAlertAction actionWithTitle:T(@"Import", @"Importieren", @"Importar", @"Importar", @"Импортировать") style:UIAlertActionStyleDefault handler:^(UIAlertAction *a) {
        (void)a; NSFileManager *fm = NSFileManager.defaultManager;
        NSURL *stage = [[NSURL fileURLWithPath:NSTemporaryDirectory()] URLByAppendingPathComponent:NSUUID.UUID.UUIDString];
        NSURL *payload = [stage URLByAppendingPathComponent:@"save"];
        NSError *error = nil;
        BOOL ok = !self.running && [fm createDirectoryAtURL:payload withIntermediateDirectories:YES attributes:nil error:&error];
        for (NSString *name in @[@"SaveData.bin", @"Backup.bin"]) {
            NSURL *source = [NSURL fileURLWithPath:[DocumentsPath() stringByAppendingPathComponent:name]];
            if (ok && ([name isEqual:@"SaveData.bin"] || [fm fileExistsAtPath:source.path])) ok = BDSPFileSHA256(source, &error) && [fm copyItemAtURL:source toURL:[payload URLByAppendingPathComponent:name] error:&error];
        }
        if (ok) ok = BDSPSealSnapshot(stage, [NSURL fileURLWithPath:DocumentsPath()], self.saveIdentity, @"save_1", &error) &&
            BDSPRestoreSnapshot(stage, [NSURL fileURLWithPath:self.saveRoot], self.saveIdentity, &error);
        [fm removeItemAtURL:stage error:nil];
        [self message:ok ? T(@"Save imported.", @"Save importiert.", @"Partida importada.", @"Progresso importado.", @"Сохранение импортировано.") : error.localizedDescription ?: T(@"Import failed. Existing saves were kept.", @"Import fehlgeschlagen. Bestehende Saves bleiben erhalten.", @"Falló la importación. Se conservan las partidas existentes.", @"A importação falhou. O progresso existente foi mantido.", @"Импорт не выполнен. Существующие сохранения оставлены.")];
    }]];
    [self.presenter presentViewController:confirm animated:YES completion:nil];
}
- (void)verify:(NSURL *)url { [self verify:url forceFull:YES]; }
- (void)verify:(NSURL *)url forceFull:(BOOL)forceFull {
    BOOL scoped = [url startAccessingSecurityScopedResource];
    if (!scoped) { [self message:T(@"Folder access failed. Choose the game library again.", @"Ordnerzugriff fehlgeschlagen. Spieldaten erneut auswählen.", @"No se puede acceder. Elige de nuevo la biblioteca.", @"O acesso falhou. Escolhe novamente a biblioteca.", @"Нет доступа. Выберите библиотеку заново.")]; return; }
    NSData *bookmark = [url bookmarkDataWithOptions:NSURLBookmarkCreationMinimalBookmark includingResourceValuesForKeys:nil relativeToURL:nil error:nil];
    self.pendingLibraryBookmark = bookmark;
    UIAlertController *checking = [UIAlertController alertControllerWithTitle:T(@"Checking game files…", @"Spieldaten werden geprüft…", @"Comprobando archivos…", @"A verificar ficheiros…", @"Проверка файлов…") message:T(@"Checking every file before starting. This may take a moment.", @"Alle Dateien werden vor dem Start geprüft. Das kann einen Moment dauern.", @"Se comprueban todos los archivos antes de empezar.", @"Os ficheiros são verificados antes de iniciar.", @"Перед запуском проверяются все файлы.") preferredStyle:UIAlertControllerStyleAlert];
    [self.presenter presentViewController:checking animated:YES completion:^{
        dispatch_async(self.backupQueue, ^{
            NSError *error = nil;
            NSURL *cache = [[NSFileManager.defaultManager URLsForDirectory:NSCachesDirectory inDomains:NSUserDomainMask].firstObject URLByAppendingPathComponent:@"verified-external-game-data.plist"];
            BOOL ok = BDSPCheckLibrary(url, self.identity, cache, forceFull, ^(NSUInteger completed, NSUInteger total) {
                dispatch_async(dispatch_get_main_queue(), ^{ checking.message = [NSString stringWithFormat:@"%lu / %lu", (unsigned long)completed, (unsigned long)total]; });
            }, &error) != nil;
            dispatch_async(dispatch_get_main_queue(), ^{
                if (ok && bookmark) {
                    if (self.libraryScoped) [self.library stopAccessingSecurityScopedResource];
                    self.library = url; self.libraryScoped = YES; self.verified = YES;
                    [NSUserDefaults.standardUserDefaults setObject:bookmark forKey:LibraryKey()];
                } else {
                    [url stopAccessingSecurityScopedResource];
                    if ([url.URLByResolvingSymlinksInPath.path isEqual:self.library.URLByResolvingSymlinksInPath.path]) {
                        self.verified = NO; self.initialDataPhase = YES;
                    }
                }
                [checking dismissViewControllerAnimated:YES completion:^{
                    if (ok && bookmark) { self.initialDataPhase = NO; self.dataReady(); } else [self message:[NSString stringWithFormat:@"%@\n%@", T(@"The game library is incomplete or does not match this app.", @"Die Spieldaten fehlen oder passen nicht zu dieser App.", @"La biblioteca está incompleta o no corresponde a esta app.", @"A biblioteca está incompleta ou não corresponde à aplicação.", @"Библиотека неполная или не подходит приложению."), error.localizedDescription ?: @""]];
                }];
            });
        });
    }];
}
- (void)verifyDeviceData:(BOOL)forceFull {
    NSURL *documents = [NSURL fileURLWithPath:DocumentsPath()];
    NSURL *manifest = [NSBundle.mainBundle.resourceURL URLByAppendingPathComponent:@"res/expected-library.json"];
    BOOL hasManifest = [NSFileManager.defaultManager fileExistsAtPath:manifest.path];
    UIAlertController *checking = [UIAlertController alertControllerWithTitle:T(@"Checking game files…", @"Spieldaten werden geprüft…", @"Comprobando archivos…", @"A verificar ficheiros…", @"Проверка файлов…") message:nil preferredStyle:UIAlertControllerStyleAlert];
    [self.presenter presentViewController:checking animated:YES completion:^{
        dispatch_async(self.backupQueue, ^{
            NSError *failure = nil;
            BOOL ok;
            NSURL *cache = [[NSFileManager.defaultManager URLsForDirectory:NSCachesDirectory inDomains:NSUserDomainMask].firstObject URLByAppendingPathComponent:@"verified-game-data.plist"];
            if (hasManifest) ok = BDSPCheckInstalledData(documents, self.identity, manifest, cache, forceFull, NULL, ^(NSUInteger completed, NSUInteger total) {
                dispatch_async(dispatch_get_main_queue(), ^{ checking.message = [NSString stringWithFormat:@"%lu / %lu", (unsigned long)completed, (unsigned long)total]; });
            }, &failure) != nil;
            else {
                // Compatibility for development bundles predating integrity manifests.
                NSString *relative = self.identity[@"RomFSDirectory"] ?: @"GameData/romfs";
                BOOL directory = NO;
                ok = !relative.isAbsolutePath && ![relative.pathComponents containsObject:@".."] &&
                    [NSFileManager.defaultManager fileExistsAtPath:[[DocumentsPath() stringByAppendingPathComponent:relative] stringByAppendingPathComponent:@"Data"] isDirectory:&directory] && directory;
            }
            dispatch_async(dispatch_get_main_queue(), ^{
                self.deviceDataReady = ok;
                [checking dismissViewControllerAnimated:YES completion:^{
                    if (ok) self.dataReady();
                    else [self message:T(@"Game files are missing or incomplete. Finish copying them with the desktop installer, then check again. Your saves are kept.", @"Spieldaten fehlen oder sind unvollständig. Kopiere sie mit dem Desktop-Installer fertig und prüfe erneut. Deine Saves bleiben erhalten.", @"Faltan datos o están incompletos. Termina la copia con el instalador y comprueba de nuevo. Tus partidas se conservan.", @"Os dados estão em falta ou incompletos. Conclui a cópia com o instalador e verifica novamente. O progresso é mantido.", @"Данные отсутствуют или неполные. Завершите копирование установщиком и повторите проверку. Сохранения остаются.")];
                }];
            });
        });
    }];
}
- (NSArray<NSURL *> *)localSnapshots {
    NSMutableArray<NSURL *> *snapshots = [NSMutableArray array];
    for (NSString *kind in @[@"_snapshots", @"_upgrade-backups"]) {
        NSURL *folder = [NSURL fileURLWithPath:[self.saveRoot stringByAppendingPathComponent:kind]];
        NSDirectoryEnumerator *walk = [NSFileManager.defaultManager enumeratorAtURL:folder includingPropertiesForKeys:nil options:NSDirectoryEnumerationSkipsHiddenFiles errorHandler:nil];
        for (NSURL *file in walk) if ([file.lastPathComponent isEqual:@"backup.json"] && BDSPCheckSnapshot(file.URLByDeletingLastPathComponent, self.saveIdentity, nil)) [snapshots addObject:file.URLByDeletingLastPathComponent];
    }
    return [snapshots sortedArrayUsingComparator:^NSComparisonResult(NSURL *a, NSURL *b) { return [a.lastPathComponent compare:b.lastPathComponent]; }];
}
- (void)chooseRestore {
    UIAlertController *choose = [UIAlertController alertControllerWithTitle:T(@"Restore a backup", @"Backup wiederherstellen", @"Restaurar una copia", @"Restaurar uma cópia", @"Восстановить копию") message:T(@"Choose a verified local backup or open one from Files.", @"Ein geprüftes lokales Backup wählen oder eines aus Dateien öffnen.", @"Elige una copia local verificada o abre una de Archivos.", @"Escolhe uma cópia local verificada ou abre uma de Ficheiros.", @"Выберите проверенную локальную копию или откройте её из Файлов.") preferredStyle:UIAlertControllerStyleAlert];
    NSDateFormatter *format = [NSDateFormatter new]; format.dateStyle = NSDateFormatterMediumStyle; format.timeStyle = NSDateFormatterMediumStyle;
    for (NSURL *snapshot in self.localSnapshots.reverseObjectEnumerator) {
        NSTimeInterval seconds = [[snapshot.lastPathComponent componentsSeparatedByString:@"-"].firstObject doubleValue];
        NSString *name = [format stringFromDate:[NSDate dateWithTimeIntervalSince1970:seconds]];
        if ([snapshot.pathComponents containsObject:@"_upgrade-backups"]) name = [NSString stringWithFormat:@"%@ · %@", name, T(@"Before update", @"Vor Update", @"Antes de actualizar", @"Antes de atualizar", @"До обновления")];
        [choose addAction:[UIAlertAction actionWithTitle:name style:UIAlertActionStyleDefault handler:^(UIAlertAction *a) { (void)a; [self confirmRestore:snapshot scoped:NO]; }]];
    }
    if ([NSFileManager.defaultManager fileExistsAtPath:[DocumentsPath() stringByAppendingPathComponent:@"SaveData.bin"]]) {
        [choose addAction:[UIAlertAction actionWithTitle:T(@"Import SaveData.bin", @"SaveData.bin importieren", @"Importar SaveData.bin", @"Importar SaveData.bin", @"Импорт SaveData.bin") style:UIAlertActionStyleDefault handler:^(UIAlertAction *a) { (void)a; [self importDroppedSave]; }]];
    }
    [choose addAction:[UIAlertAction actionWithTitle:T(@"Open from Files", @"Aus Dateien öffnen", @"Abrir desde Archivos", @"Abrir de Ficheiros", @"Открыть из Файлов") style:UIAlertActionStyleDefault handler:^(UIAlertAction *a) { (void)a; [self pick:3]; }]];
    [choose addAction:[UIAlertAction actionWithTitle:T(@"Cancel", @"Abbrechen", @"Cancelar", @"Cancelar", @"Отмена") style:UIAlertActionStyleCancel handler:^(UIAlertAction *a) { (void)a; [self saveMenu]; }]];
    [self.presenter presentViewController:choose animated:YES completion:nil];
}
- (void)confirmRestore:(NSURL *)url scoped:(BOOL)scoped {
        NSError *coordination = nil;
        __block NSError *error = nil;
        __block NSDictionary *backup = nil;
        NSFileCoordinator *coordinator = [[NSFileCoordinator alloc] initWithFilePresenter:nil];
        [coordinator coordinateReadingItemAtURL:url options:0 error:&coordination byAccessor:^(NSURL *input) { backup = BDSPCheckSnapshot(input, self.saveIdentity, &error); }];
        if (!backup) { if (scoped) [url stopAccessingSecurityScopedResource]; [self message:error.localizedDescription ?: coordination.localizedDescription]; return; }
        UIAlertController *confirm = [UIAlertController alertControllerWithTitle:T(@"Restore this save?", @"Diesen Save wiederherstellen?", @"¿Restaurar esta partida?", @"Restaurar este progresso?", @"Восстановить сохранение?") message:T(@"The current save will be kept as a recovery copy.", @"Der aktuelle Save bleibt als Wiederherstellungskopie erhalten.", @"La partida actual se conservará como copia de recuperación.", @"O progresso atual será mantido como cópia de recuperação.", @"Текущий прогресс останется в резервной копии.") preferredStyle:UIAlertControllerStyleAlert];
        [confirm addAction:[UIAlertAction actionWithTitle:T(@"Cancel", @"Abbrechen", @"Cancelar", @"Cancelar", @"Отмена") style:UIAlertActionStyleCancel handler:^(UIAlertAction *a) { (void)a; if (scoped) [url stopAccessingSecurityScopedResource]; [self menu]; }]];
        [confirm addAction:[UIAlertAction actionWithTitle:T(@"Restore", @"Wiederherstellen", @"Restaurar", @"Restaurar", @"Восстановить") style:UIAlertActionStyleDefault handler:^(UIAlertAction *a) {
            (void)a; __block NSError *failure = nil; __block BOOL ok = NO;
            NSError *coordinationError = nil;
            NSFileCoordinator *read = [[NSFileCoordinator alloc] initWithFilePresenter:nil];
            [read coordinateReadingItemAtURL:url options:0 error:&coordinationError byAccessor:^(NSURL *input) {
                ok = !self.running && BDSPRestoreSnapshot(input, [NSURL fileURLWithPath:self.saveRoot], self.saveIdentity, &failure);
            }];
            if (scoped) [url stopAccessingSecurityScopedResource];
            [self message:ok ? T(@"Save restored.", @"Save wiederhergestellt.", @"Partida restaurada.", @"Progresso restaurado.", @"Сохранение восстановлено.") : failure.localizedDescription ?: T(@"Stop the game before restoring.", @"Vorher das Spiel beenden.", @"Cierra el juego antes de restaurar.", @"Fecha o jogo antes de restaurar.", @"Сначала остановите игру.")];
        }]];
        [self.presenter presentViewController:confirm animated:YES completion:nil];
}
- (void)documentPickerWasCancelled:(UIDocumentPickerViewController *)controller { (void)controller; [self menu]; }
- (void)importData:(NSURL *)source {
    BOOL stale = NO;
    NSURL *target = [NSURL URLByResolvingBookmarkData:self.pendingLibraryBookmark options:0 relativeToURL:nil bookmarkDataIsStale:&stale error:nil];
    BOOL sourceAccess = [source startAccessingSecurityScopedResource];
    BOOL targetAccess = !stale && [target startAccessingSecurityScopedResource];
    if (!sourceAccess || !targetAccess) {
        if (sourceAccess) [source stopAccessingSecurityScopedResource];
        if (targetAccess) [target stopAccessingSecurityScopedResource];
        [self message:T(@"Folder access failed. Choose the game library again.", @"Ordnerzugriff fehlgeschlagen. Spieldaten erneut auswählen.", @"No se puede acceder. Elige de nuevo la biblioteca.", @"O acesso falhou. Escolhe novamente a biblioteca.", @"Нет доступа. Выберите библиотеку заново.")]; return;
    }
    UIAlertController *progress = [UIAlertController alertControllerWithTitle:T(@"Importing game files…", @"Spieldaten werden importiert…", @"Importando datos…", @"A importar dados…", @"Импорт данных…") message:T(@"Existing game versions and saves are kept. New files are checked before activation.", @"Bestehende Spielversionen und Saves bleiben erhalten. Neue Dateien werden vor der Aktivierung geprüft.", @"Se conservan las versiones y partidas existentes. Los archivos nuevos se verifican antes de activarse.", @"As versões e o progresso existentes são mantidos. Os ficheiros novos são verificados antes da ativação.", @"Предыдущие версии и сохранения остаются. Новые файлы проверяются до активации.") preferredStyle:UIAlertControllerStyleAlert];
    [self.presenter presentViewController:progress animated:YES completion:^{
        dispatch_async(self.backupQueue, ^{
            __block BOOL ok = NO;
            __block NSError *failure = nil;
            NSError *coordination = nil;
            NSFileCoordinator *coordinator = [[NSFileCoordinator alloc] initWithFilePresenter:nil];
            [coordinator coordinateReadingItemAtURL:source options:0 writingItemAtURL:target options:0 error:&coordination byAccessor:^(NSURL *input, NSURL *output) {
                if (!BDSPVerifyLibrary(input, self.identity, &failure)) return;
                NSURL *romfs = [input URLByAppendingPathComponent:self.identity[@"RomFSDirectory"]];
                NSURL *mod = self.identity[@"ModDirectory"] ? [input URLByAppendingPathComponent:self.identity[@"ModDirectory"]] : nil;
                ok = BDSPExportLibrary(romfs, mod, self.identity, output, &failure);
            }];
            [source stopAccessingSecurityScopedResource]; [target stopAccessingSecurityScopedResource];
            dispatch_async(dispatch_get_main_queue(), ^{
                [progress dismissViewControllerAnimated:YES completion:^{
                    if (ok) [self verify:target];
                    else [self message:[NSString stringWithFormat:@"%@\n%@", T(@"Import failed. Previous files and saves were kept.", @"Import fehlgeschlagen. Bisherige Dateien und Saves bleiben erhalten.", @"Falló la importación. Se conservan los archivos y partidas anteriores.", @"A importação falhou. Os ficheiros e o progresso anteriores foram mantidos.", @"Импорт не выполнен. Прежние файлы и сохранения оставлены."), failure.localizedDescription ?: coordination.localizedDescription ?: @""]];
                }];
            });
        });
    }];
}
- (void)documentPicker:(UIDocumentPickerViewController *)controller didPickDocumentsAtURLs:(NSArray<NSURL *> *)urls {
    (void)controller;
    NSURL *url = urls.firstObject;
    if (!url) { [self menu]; return; }
    if (self.pickerMode == 4) { [self importData:url]; return; }
    if (self.pickerMode == 3) {
        BOOL scoped = [url startAccessingSecurityScopedResource];
        if (!scoped) { [self message:T(@"Backup access failed.", @"Backup-Zugriff fehlgeschlagen.", @"No se puede acceder a la copia.", @"O acesso à cópia falhou.", @"Нет доступа к копии.")]; return; }
        [self confirmRestore:url scoped:scoped]; return;
    }
    BOOL access = [url startAccessingSecurityScopedResource];
    NSError *error = nil;
    NSData *bookmark = access ? [url bookmarkDataWithOptions:NSURLBookmarkCreationMinimalBookmark includingResourceValuesForKeys:nil relativeToURL:nil error:&error] : nil;
    if (access) [url stopAccessingSecurityScopedResource];
    if (!bookmark) { [self message:T(@"The folder could not be remembered. Choose it again.", @"Der Ordner konnte nicht gespeichert werden. Bitte erneut auswählen.", @"No se pudo recordar la carpeta. Elígela de nuevo.", @"Não foi possível guardar a pasta. Escolhe novamente.", @"Не удалось запомнить папку. Выберите её заново.")]; return; }
    if (self.pickerMode == 1) {
        [self verify:url];
    } else {
        // Local app/container folders cannot provide protection against deletion.
        if (!BDSPBackupFolderIsIndependent(NSHomeDirectory(), url.URLByResolvingSymlinksInPath.path)) { [self message:T(@"Choose a backup folder outside this app and LiveContainer.", @"Einen Backup-Ordner außerhalb dieser App und LiveContainer wählen.", @"Elige una carpeta fuera de esta app y LiveContainer.", @"Escolhe uma pasta fora desta aplicação e do LiveContainer.", @"Выберите папку вне приложения и LiveContainer.")]; return; }
        [NSUserDefaults.standardUserDefaults setObject:bookmark forKey:BackupKey()];
        [self retryBackups]; [self menu];
    }
}
- (void)retryBackups {
    NSString *root = self.saveRoot;
    NSDictionary *identity = self.saveIdentity;
    dispatch_async(self.backupQueue, ^{
        NSMutableArray<NSURL *> *snapshots = [NSMutableArray array];
        for (NSString *kind in @[@"_snapshots", @"_upgrade-backups"]) {
            NSURL *folder = [NSURL fileURLWithPath:[root stringByAppendingPathComponent:kind]];
            NSDirectoryEnumerator *walk = [NSFileManager.defaultManager enumeratorAtURL:folder includingPropertiesForKeys:nil options:NSDirectoryEnumerationSkipsHiddenFiles errorHandler:nil];
            for (NSURL *file in walk) if ([file.lastPathComponent isEqual:@"backup.json"]) [snapshots addObject:file.URLByDeletingLastPathComponent];
        }
        [snapshots sortUsingComparator:^NSComparisonResult(NSURL *a, NSURL *b) { return [a.lastPathComponent compare:b.lastPathComponent]; }];
        for (NSURL *snapshot in snapshots) [self exportSnapshot:snapshot identity:identity];
    });
}
- (void)exportSnapshot:(NSURL *)snapshot identity:(NSDictionary *)identity {
    NSURL *external = Resolve(BackupKey());
    BOOL scoped = [external startAccessingSecurityScopedResource];
    NSError *error = nil;
    __block BOOL ok = NO;
    if (scoped) {
        NSFileCoordinator *coordinator = [[NSFileCoordinator alloc] initWithFilePresenter:nil];
        [coordinator coordinateWritingItemAtURL:external options:0 error:&error byAccessor:^(NSURL *folder) {
            ok = BDSPExportSnapshot(snapshot, folder, identity, nil);
        }];
        [external stopAccessingSecurityScopedResource];
    }
    NSString *status = ok ? T(@"Saved locally and backed up externally", @"Lokal und extern gesichert", @"Guardado localmente y con copia externa", @"Guardado localmente e com cópia externa", @"Сохранено локально и во внешней копии") : T(@"Saved locally · external backup pending", @"Lokal gesichert · externes Backup ausstehend", @"Guardado localmente · copia externa pendiente", @"Guardado localmente · cópia externa pendente", @"Сохранено локально · внешняя копия ожидает");
    [self publishStatus:status identity:identity];
}
- (void)publishStatus:(NSString *)status identity:(NSDictionary *)identity {
    [NSUserDefaults.standardUserDefaults setObject:status forKey:StatusKey(identity)];
    dispatch_async(dispatch_get_main_queue(), ^{
        if (!self.statusLabel) {
            self.statusLabel = [[UILabel alloc] initWithFrame:CGRectMake(12, self.presenter.view.safeAreaInsets.top + 8, MIN(420, self.presenter.view.bounds.size.width - 24), 40)];
            self.statusLabel.font = [UIFont systemFontOfSize:12 weight:UIFontWeightMedium];
            self.statusLabel.numberOfLines = 2;
            self.statusLabel.textColor = UIColor.whiteColor;
            self.statusLabel.backgroundColor = [UIColor.blackColor colorWithAlphaComponent:0.75];
            self.statusLabel.layer.cornerRadius = 8; self.statusLabel.clipsToBounds = YES;
            [self.presenter.view addSubview:self.statusLabel];
        }
        NSUInteger version = ++self.statusVersion;
        self.statusLabel.text = status;
        self.statusLabel.hidden = NO;
        dispatch_after(dispatch_time(DISPATCH_TIME_NOW, 6 * NSEC_PER_SEC), dispatch_get_main_queue(), ^{ if (version == self.statusVersion) self.statusLabel.hidden = YES; });
    });
}
@end

BOOL BDSPConfigureSaveRoot(NSString *path, NSDictionary *identity, NSString *profile, NSError **error) {
    manager.saveRoot = path;
    manager.saveLabel = [identity[@"SaveProfile"] isEqual:profile] && [identity[@"ModName"] isKindOfClass:NSString.class] ? identity[@"ModName"] : path.lastPathComponent;
    manager.saveIdentity = @{@"GameID":identity[@"GameID"] ?: @"0100000011d90000", @"ProfileID":profile ?: @"vanilla"};
    return BDSPRecoverRestore([NSURL fileURLWithPath:path], error);
}
NSString *BDSPCurrentSaveRoot(void) { return manager.saveRoot; }
NSString *BDSPBaseSaveRoot(void) { return manager.baseSaveRoot; }
NSString *BDSPSharedDataPath(NSString *relative) {
    if (!manager.verified || !manager.library || ![relative isKindOfClass:NSString.class] || relative.isAbsolutePath) return nil;
    NSString *base = manager.library.path.stringByStandardizingPath;
    NSString *path = [[base stringByAppendingPathComponent:relative] stringByStandardizingPath];
    return [path hasPrefix:[base stringByAppendingString:@"/"]] ? path : nil;
}
void BDSPPrepareData(UIViewController *presenter, NSDictionary *identity, void (^ready)(void)) {
    manager = [BDSPDataManager new]; manager.presenter = presenter; manager.identity = identity; manager.ready = ready; manager.dataReady = ready;
    manager.backupQueue = dispatch_queue_create("dev.xnubdsp.save-backup", DISPATCH_QUEUE_SERIAL);
    NSString *profile = identity[@"SaveProfile"] ?: ([identity[@"CompiledExeFS"] boolValue] ? ProfileForMod(identity[@"ModName"] ?: @"") : @"vanilla");
    NSString *root = [DocumentsPath() stringByAppendingPathComponent:@"Saves"];
    if ([identity[@"ExternalLibrary"] boolValue]) root = [DocumentsPath() stringByAppendingPathComponent:[NSString stringWithFormat:@"Profiles/%@/%@/Saves", identity[@"GameID"], profile]];
    manager.baseSaveRoot = root;
    if ([identity[@"CompiledExeFS"] boolValue] && [identity[@"ModName"] isKindOfClass:NSString.class]) root = [[root stringByAppendingPathComponent:@"mods"] stringByAppendingPathComponent:[identity[@"SaveStorageVersion"] intValue] >= 2 ? profile : identity[@"ModName"]];
    NSError *error = nil;
    if (!BDSPConfigureSaveRoot(root, identity, profile, &error)) { [manager message:error.localizedDescription]; return; }
    NSURL *library = Resolve(LibraryKey());
    manager.initialDataPhase = [identity[@"ExternalLibrary"] boolValue];
    if (manager.initialDataPhase && library) [manager verify:library forceFull:NO];
    else if (manager.initialDataPhase) [manager menu];
    else [manager verifyDeviceData:NO];
}
void BDSPConfirmStart(void (^ready)(void)) { manager.ready = ready; [manager menu]; }
void BDSPShowDataError(NSString *detail) { manager.running = NO; [manager message:detail]; }

void bdsp_save_committed(const char *root, const char *snapshot, int failure) { @autoreleasepool {
    if (!manager) return;
    NSDictionary *identity = manager.saveIdentity;
    NSError *error = nil;
    NSURL *url = snapshot ? [NSURL fileURLWithPath:@(snapshot)] : nil;
    BOOL sealed = !failure && BDSPSealSnapshot(url, [NSURL fileURLWithPath:@(root)].URLByDeletingLastPathComponent, identity, @(root).lastPathComponent, &error);
    if (!sealed) {
        [manager publishStatus:T(@"Local backup failed · keep the app installed", @"Lokales Backup fehlgeschlagen · App installiert lassen", @"Falló la copia local · conserva la app instalada", @"A cópia local falhou · mantém a aplicação instalada", @"Ошибка локальной копии · не удаляйте приложение") identity:identity];
        fprintf(stderr, "[save] Snapshot could not be sealed (error %d). Existing saves and backups kept.\n", failure);
        return;
    }
    dispatch_async(manager.backupQueue, ^{
        [manager exportSnapshot:url identity:identity];
        // Only verified generated snapshots count toward the ten-generation cap.
        NSFileManager *fm = NSFileManager.defaultManager;
        NSArray<NSURL *> *entries = [[fm contentsOfDirectoryAtURL:url.URLByDeletingLastPathComponent includingPropertiesForKeys:nil options:NSDirectoryEnumerationSkipsHiddenFiles error:nil] sortedArrayUsingComparator:^NSComparisonResult(NSURL *a, NSURL *b) { return [a.lastPathComponent compare:b.lastPathComponent]; }];
        NSMutableArray *valid = [NSMutableArray array];
        for (NSURL *entry in entries) if (BDSPCheckSnapshot(entry, identity, nil)) [valid addObject:entry];
        while (valid.count > 10) { [fm removeItemAtURL:valid.firstObject error:nil]; [valid removeObjectAtIndex:0]; }
    });
} }
