#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Language {
    English,
    German,
}

impl Language {
    pub fn detect() -> Self {
        let locale = std::env::var("BDSP_LANG")
            .ok()
            .or_else(sys_locale::get_locale)
            .unwrap_or_default();
        Self::from_locale(&locale)
    }
    pub fn from_locale(locale: &str) -> Self {
        match locale
            .split(['-', '_', '.'])
            .next()
            .unwrap_or("")
            .to_ascii_lowercase()
            .as_str()
        {
            "de" => Self::German,
            _ => Self::English,
        }
    }
}

macro_rules! messages {
    ($( $key:ident => [$en:literal, $de:literal] ),* $(,)?) => {
        #[derive(Clone, Copy)]
        pub enum Label { $( $key ),* }
        #[cfg(test)]
        impl Label {
            const ALL: &'static [Self] = &[$(Self::$key),*];
        }
        impl Language {
            pub fn t(self, key: Label) -> &'static str {
                let values = match key { $(Label::$key => [$en, $de]),* };
                values[match self { Self::English => 0, Self::German => 1 }]
            }
        }
    }
}

messages! {
    FetchSource => ["Download current source", "Aktuellen Quellcode laden"],
    UpdateShort => ["Update", "Update"],
    UpdateAvailable => ["Installer update available", "Installer-Update verfügbar"],
    UpdateRestartHint => ["Download the verified update and restart the installer? Your files and settings will be kept.", "Geprüftes Update herunterladen und den Installer neu starten? Deine Dateien und Einstellungen bleiben erhalten."],
    UpdateInstaller => ["Update & restart", "Update & Neustart"],
    UpdateDownloading => ["Downloading update…", "Update wird geladen…"],
    DependenciesTitle => ["Prepare your computer", "Computer vorbereiten"],
    DependenciesHint => ["These tools build your app. Installation may ask for your administrator password in a terminal.", "Diese Werkzeuge bauen deine App. Die Installation fragt gegebenenfalls im Terminal nach deinem Administratorpasswort."],
    InstallDependencies => ["Install tools", "Installieren"],
    CheckAgain => ["Check again", "Erneut prüfen"],
    OpenRepository => ["Open project on GitHub", "Projekt auf GitHub öffnen"],
    RepositoryError => ["Couldn't open the browser. Project: github.com/Veemyu/strahlender-xnu", "Browser konnte nicht geöffnet werden. Projekt: github.com/Veemyu/strahlender-xnu"],
    Setup => ["Setup", "Einrichtung"],
    SetupTitle => ["What happens next.", "So geht es weiter."],
    SetupHint => ["We'll guide you through the preparation.", "Wir führen dich durch die Vorbereitung."],
    Target => ["Target", "Ziel"],
    TargetTitle => ["Where do you want to play?", "Wo möchtest du spielen?"],
    TargetHint => ["Choose the device for your finished app.", "Wähle das Gerät für deine fertige App."],
    ComingLater => ["Later · Not available yet", "Später · Noch nicht verfügbar"],
    Simulation => ["Simulation", "Simulation"],
    TargetDesktopHint => ["Build for this computer. We'll check the tools needed for setup.", "Für diesen Computer bauen. Wir prüfen die benötigten Werkzeuge."],
    TargetAppleHostHint => ["Apple targets need a Mac with Xcode. That build connection is still planned.", "Apple-Ziele benötigen einen Mac mit Xcode. Diese Build-Anbindung ist noch geplant."],
    SetupAppleHost => ["Apple builds require macOS and Xcode. Building via a Mac is planned and is not connected in this preview.", "Apple-Builds benötigen macOS und Xcode. Der Build über einen Mac ist geplant und in dieser Vorschau noch nicht angebunden."],
    TargetMacHint => ["Build an app for this Mac. We'll check the tools you need before setup.", "Eine App für diesen Mac bauen. Zuerst prüfen wir die benötigten Werkzeuge."],
    TargetMobileHint => ["Prepare an app for your Apple device. Later we'll guide you through connecting it and signing the app.", "Eine App für dein Apple-Gerät vorbereiten. Später führen wir dich durch Verbindung und Signierung."],
    SetupDesktop => ["We check the tools needed for the build. Before setup, you will see what is missing and needs installing.", "Wir prüfen die Werkzeuge für den Build. Vor der Einrichtung siehst du, was fehlt und installiert werden soll."],
    SetupMac => ["The build needs Apple's developer tools on Mac. Before setup, you'll see what is missing and needs installing.", "Der Build auf dem Mac benötigt Apples Entwicklerwerkzeuge. Vor der Einrichtung siehst du, was fehlt und installiert werden soll."],
    SetupMobile => ["Connect and unlock your iPad or iPhone. Xcode and your configured Apple signing team are used to build and install the app.", "Verbinde und entsperre dein iPad oder iPhone. Xcode und dein eingerichtetes Apple-Signierungsteam werden zum Bauen und Installieren verwendet."],
    BackendHint => ["The installer checks the required tools, prepares your game data and builds the app. You can follow every step in the log.", "Der Installer prüft die nötigen Werkzeuge, bereitet deine Spieldaten vor und baut die App. Im Protokoll kannst du jeden Schritt verfolgen."],
    BackendUnavailable => ["A real build is not connected for this target or game format yet.", "Für dieses Ziel oder Spielformat ist noch kein echter Build angebunden."],
    DemoData => ["Demo · Example file", "Demo · Beispieldatei"],
    DemoGameFile => ["Example.xci", "Beispiel.xci"],
    DemoUpdateFile => ["Example update.nsp", "Beispiel-Update.nsp"],
    DemoNcaFolder => ["My NCA folder", "Mein NCA-Ordner"],
    DemoLongName => ["My very long file name with accents àéï and spaces.xci", "Mein sehr langer Dateiname mit Umlauten äöü und Leerzeichen.xci"],
    DemoMode => ["Demo · Explore without your own files", "Demo · Ohne eigene Dateien ausprobieren"],
    UseExample => ["Use example file", "Beispieldatei verwenden"],
    KeysTitle => ["Add your keys.", "Deine Schlüssel hinzufügen."],
    KeysStepHint => ["First, add prod.keys from your own console.", "Zuerst prod.keys von deiner eigenen Konsole."],
    GameTitle => ["Add your game.", "Dein Basisspiel hinzufügen."],
    GameHint => ["Drop an XCI, NSP or NCA folder here.", "Ziehe eine XCI, NSP oder einen NCA-Ordner hierher."],
    UpdateTitle => ["Add an update?", "Ein Update hinzufügen?"],
    UpdateHint => ["Optional. You can continue without an update.", "Optional. Du kannst auch ohne Update fortfahren."],
    Mods => ["Mods", "Mods"],
    ModsLocation => ["Mod folder", "Mod-Ordner"],
    ModsTitle => ["Add a mod?", "Einen Mod hinzufügen?"],
    ModsChooseTitle => ["Choose what to play.", "Wähle, was du spielen möchtest."],
    ModsChooseHint => ["One mod at a time, or the unmodified game.", "Ein Mod zur Zeit oder das unveränderte Spiel."],
    ModsHint => ["Choose the whole mod folder; RomFS and ExeFS are found automatically.", "Wähle den ganzen Mod-Ordner; RomFS und ExeFS werden automatisch gefunden."],
    RomFSNoBuild => ["RomFS-only mods need no rebuild. Copy them into this folder with your file manager, then refresh.", "Reine RomFS-Mods brauchen keinen Rebuild. Kopiere sie mit dem Dateimanager in diesen Ordner und aktualisiere die Liste."],
    ModsFolder => ["Mods folder", "Mod-Ordner"],
    OpenModsFolder => ["Open folder", "Ordner öffnen"],
    ChooseModFolder => ["Choose mod folder", "Mod-Ordner auswählen"],
    RefreshMods => ["Refresh", "Aktualisieren"],
    NoMods => ["No mods found. The unmodified game stays available.", "Keine Mods gefunden. Das unveränderte Spiel bleibt verfügbar."],
    UnmodifiedGame => ["Unmodified game", "Unverändertes Spiel"],
    RomFSOnly => ["RomFS files work now", "RomFS-Dateien funktionieren bereits"],
    ExeFSBuildNeeded => ["ExeFS build needed", "ExeFS-Build erforderlich"],
    ExeFSWarning => ["This mod contains ExeFS code. Building it is not supported yet; choose an unmodified game or a RomFS-only mod.", "Dieser Mod enthält ExeFS-Code. Sein Build wird noch nicht unterstützt; wähle das unveränderte Spiel oder einen reinen RomFS-Mod."],
    ExeFSBuildReady => ["IPS/IPS32 and subsdk1 are built into a separate mod app with its own icon and save. Your original app stays installed.", "IPS/IPS32 und subsdk1 werden in eine eigene Mod-App mit eigenem Icon und Spielstand eingebaut. Deine Original-App bleibt erhalten."],
    ExeFSBuildReadyTag => ["Separate mod app", "Eigene Mod-App"],
    ModAppResult => ["Separate app", "Eigene App"],
    ExeFSUnsupported => ["This ExeFS folder contains unsupported files. Supported: IPS/IPS32 for main, sdk, subsdk0 and the additional subsdk1 module.", "Dieser ExeFS-Ordner enthält nicht unterstützte Dateien. Unterstützt: IPS/IPS32 für main, sdk, subsdk0 und das zusätzliche subsdk1-Modul."],
    ModsDeviceHint => ["On iPad/iPhone, add RomFS mods without rebuilding via Files → On My Device → BDSP → Mods. This local folder is staging only.", "Auf iPad/iPhone kannst du RomFS-Mods ohne Rebuild über Dateien → Auf meinem Gerät → BDSP → Mods hinzufügen. Dieser lokale Ordner dient nur zur Vorbereitung."],
    ModsFolderUnavailable => ["Could not determine a local mods folder.", "Ein lokaler Mod-Ordner konnte nicht ermittelt werden."],
    ModsPreviewHint => ["RomFS-only mods load at launch without recompiling. On Linux, this choice becomes the launcher default; on Mac, the app asks at launch.", "Reine RomFS-Mods laden beim Start ohne Rebuild. Unter Linux wird diese Wahl die Launcher-Vorgabe; auf dem Mac fragt die App beim Start."],
    UseLight => ["Switch to light mode", "Zum hellen Design wechseln"],
    UseDark => ["Switch to dark mode", "Zum dunklen Design wechseln"],
    Base => ["Game", "Basisspiel"],
    Update => ["Update", "Update"],
    Keys => ["Keys", "Schlüssel"],
    Drop => ["Drop here", "Hier ablegen"],
    Formats => ["XCI, NSP or NCA folder", "XCI, NSP oder NCA-Ordner"],
    File => ["Choose file", "Datei wählen"],
    Folder => ["Choose folder", "Ordner wählen"],
    Remove => ["Remove", "Entfernen"],
    Change => ["Change", "Ändern"],
    SkipUpdate => ["Continue without update", "Ohne Update weiter"],
    SkipMods => ["Skip", "Überspringen"],
    KeysHint => ["Drop prod.keys here or choose a file.", "prod.keys hier ablegen oder auswählen."],
    SearchKeys => ["Search again", "Erneut suchen"],
    NoKeys => ["No keys found automatically. You can add prod.keys yourself.", "Keine Schlüssel automatisch gefunden. Du kannst prod.keys selbst hinzufügen."],
    FoundKeys => ["Keys found in an existing emulator folder.", "Schlüssel in einem vorhandenen Emulator-Ordner gefunden."],
    KeysRestored => ["Using the prod.keys file selected earlier.", "Die zuvor ausgewählte prod.keys-Datei wird verwendet."],
    ErrorTitle => ["Something needs attention", "Etwas braucht deine Aufmerksamkeit"],
    DismissError => ["Got it", "Verstanden"],
    ShowErrorDetails => ["Show details", "Details anzeigen"],
    ErrorDetailsHint => ["The full session log has the exact step and diagnostic.", "Im Sitzungsprotokoll stehen der genaue Schritt und die Diagnose."],
    DiskSpaceError => ["There isn't enough free disk space for this build. Available: {available} GB · Required: {required} GB. Free up space and check again.", "Für diesen Build ist nicht genug Speicherplatz frei. Verfügbar: {available} GB · Benötigt: {required} GB. Gib Speicher frei und prüfe erneut."],
    PythonRuntimeError => ["The installer's private Python environment is missing or incomplete. Reinstall the installer to restore it, then try again.", "Die private Python-Umgebung des Installers fehlt oder ist unvollständig. Installiere den Installer erneut und starte den Build noch einmal."],
    PythonDevelopmentError => ["Python 3.9 or newer is needed by this development build. Install Python, then run the check again.", "Diese Entwicklungsversion benötigt Python 3.9 oder neuer. Installiere Python und starte die Prüfung erneut."],
    SavedInputMissing => ["A previously selected item is no longer available. Please choose it again.", "Eine frühere Auswahl ist nicht mehr verfügbar. Bitte wähle sie erneut aus."],
    SavedModFolderMissing => ["The previously selected mod folder is no longer available.", "Der zuvor ausgewählte Mod-Ordner ist nicht mehr verfügbar."],
    PrivateKeys => ["Key contents stay private", "Schlüsselinhalte bleiben privat"],
    Inspecting => ["Checking…", "Wird geprüft …"],
    Continue => ["Continue", "Weiter"],
    Back => ["Back", "Zurück"],
    ReviewTitle => ["Ready for a preview.", "Bereit für die Vorschau."],
    ReviewHint => ["Your selection, at a glance.", "Deine Auswahl auf einen Blick."],
    OptimizeCpu => ["Optimize for this computer", "Für diesen Computer optimieren"],
    OptimizeCpuHint => ["Recommended. Uses AVX/AVX2 when supported by your CPU.", "Empfohlen. Nutzt AVX/AVX2, wenn deine CPU sie unterstützt."],
    PortableCpuHint => ["Portable build for other computers. Does not require AVX or AVX2.", "Portabler Build für andere Computer. Benötigt kein AVX oder AVX2."],
    NoUpdate => ["No update", "Kein Update"],
    Computer => ["Device", "Gerät"],
    PreviewHint => ["This preview simulates setup. It won't install tools or process your game.", "Diese Vorschau simuliert den Ablauf. Sie installiert keine Werkzeuge und verarbeitet keine Spieldaten."],
    StartPreview => ["Start preview", "Vorschau starten"],
    StartBuild => ["Build app", "App bauen"],
    LogBuildStart => ["Starting the game build.", "Spiel-Build wird gestartet."],
    MissingInput => ["Game file or prod.keys is missing.", "Spieldatei oder prod.keys fehlt."],
    CancelBuild => ["Cancel build", "Build abbrechen"],
    InstalledIn => ["Installed in {folder}", "Installiert in {folder}"],
    ShowInFinder => ["Show in Finder", "Im Finder anzeigen"],
    ShowInFolder => ["Show installation folder", "Installationsordner anzeigen"],
    ShowInstallationFailed => ["The installation folder couldn't be opened. Check that the app is still there.", "Der Installationsordner konnte nicht geöffnet werden. Prüfe, ob die App noch vorhanden ist."],
    BuildPassed => ["Build complete.", "Build abgeschlossen."],
    BuildFailed => ["Build failed. See details for the exact step.", "Build fehlgeschlagen. Details zeigen den genauen Schritt."],
    BuildStepError => ["The build stopped during “{stage}”.\n\n{cause}\n\nOpen the details to see and copy the full build log.", "Der Build wurde bei „{stage}“ abgebrochen.\n\n{cause}\n\nIn den Details kannst du das vollständige Build-Protokoll ansehen und kopieren."],
    BuildStopped => ["Build cancelled.", "Build abgebrochen."],
    ReturnToSetup => ["Back to setup", "Zurück zur Einrichtung"],
    CheckingRequirements => ["Checking build requirements", "Build-Voraussetzungen werden geprüft"],
    CheckFailed => ["Check finished with missing requirements", "Prüfung mit fehlenden Voraussetzungen beendet"],
    PrerequisiteInternalError => ["The installer couldn't finish checking the build requirements because of an internal error. This does not mean a package is missing. Open the details and copy the log to report the problem. Your game files have not been changed.", "Der Installer konnte die Build-Voraussetzungen wegen eines internen Fehlers nicht vollständig prüfen. Das bedeutet nicht, dass ein Paket fehlt. Öffne die Details und kopiere das Protokoll, um den Fehler zu melden. Deine Spieldateien wurden nicht verändert."],
    NeedsAttention => ["Needs attention", "Benötigt Aufmerksamkeit"],
    CheckStopped => ["Check cancelled.", "Prüfung abgebrochen."],
    CancelRequested => ["Cancellation requested.", "Abbruch angefordert."],
    PythonMissing => ["Python 3.9+ is needed for this local development check. The released installer will bundle Python.", "Für diese lokale Entwicklungsprüfung wird Python 3.9+ benötigt. Der veröffentlichte Installer bringt Python selbst mit."],
    RuntimeMissing => ["The verified private Python runtime is missing. Reinstall the installer runtime.", "Die geprüfte private Python-Runtime fehlt. Bitte die Installer-Runtime neu installieren."],
    LogPreflight => ["Starting the read-only prerequisite check.", "Schreibfreie Vorprüfung starten."],
    ProgressTitle => ["One step at a time.", "Schritt für Schritt."],
    Simulated => ["Preview · No files are being processed", "Vorschau · Keine Dateien werden verarbeitet"],
    Tools => ["Check tools", "Werkzeuge prüfen"],
    Prepare => ["Prepare game", "Spieldaten vorbereiten"],
    Generate => ["Generate game code", "Spielcode erzeugen"],
    Compile => ["Compile game code · Clang", "Spielcode kompilieren · Clang"],
    Images => ["Prepare module images", "Modul-Images vorbereiten"],
    ExeFS => ["Apply ExeFS patches", "ExeFS-Patches anwenden"],
    Runtime => ["Build runtime", "Runtime bauen"],
    Install => ["Install app", "App installieren"],
    Package => ["Package app", "App zusammenstellen"],
    FilesCompiled => ["files compiled", "Dateien kompiliert"],
    AnalyzingModule => ["Analyzing module", "Modul analysieren"],
    FunctionsGenerated => ["functions generated", "Funktionen erzeugt"],
    Module => ["Module", "Modul"],
    ModulesGenerated => ["modules generated", "Module erzeugt"],
    CompletedStage => ["Completed", "Abgeschlossen"],
    NextStage => ["Next", "Als Nächstes"],
    Done => ["Done", "Fertig"],
    Running => ["Running", "Läuft"],
    Details => ["Show details", "Details anzeigen"],
    HideDetails => ["Hide details", "Details schließen"],
    CopyLog => ["Copy log", "Protokoll kopieren"],
    CopyLogLine => ["Click to copy this line", "Klicken, um diese Zeile zu kopieren"],
    LogLineCopied => ["Copied", "Kopiert"],
    LogEmpty => ["No activity yet.", "Noch keine Aktivität."],
    LogSearch => ["Searching standard emulator folders for prod.keys.", "Übliche Emulator-Ordner nach prod.keys durchsuchen."],
    LogInspect => ["Checking readability and file type.", "Lesbarkeit und Dateityp prüfen."],
    LogAccepted => ["File check complete. Content validation is still pending.", "Dateiprüfung abgeschlossen. Inhaltsprüfung steht noch aus."],
    LogPreview => ["Starting simulated setup. No commands are executed.", "Simulierten Ablauf starten. Es werden keine Befehle ausgeführt."],
    LogStopped => ["Preview stopped by user.", "Vorschau durch Nutzer beendet."],
    LogComplete => ["Simulation complete. Nothing was installed.", "Simulation abgeschlossen. Es wurde nichts installiert."],
    Step => ["Step", "Schritt"],
    Of => ["of", "von"],
    CheckSelection => ["Review", "Auswahl prüfen"],
    Stop => ["Stop preview", "Vorschau beenden"],
    FinishedTitle => ["Preview complete.", "Vorschau abgeschlossen."],
    FinishedHint => ["Your selection is saved for this session. No game has been installed.", "Deine Auswahl bleibt für diese Sitzung erhalten. Es wurde noch kein Spiel installiert."],
    ToSelection => ["Back to files", "Zur Dateiauswahl"],
    Region => ["Region", "Region"],
    RegionPending => ["Not checked yet", "Noch nicht geprüft"],
    Unreadable => ["This path cannot be read. Please select it again.", "Dieser Pfad ist nicht lesbar. Bitte wähle ihn erneut aus."],
    KeysFileOnly => ["Choose prod.keys, not a folder.", "Bitte wähle prod.keys aus, keinen Ordner."],
    NoNca => ["No NCA files in this folder. Choose the folder containing the .nca files.", "Hier liegen keine NCA-Dateien. Wähle den Ordner direkt mit den .nca-Dateien."],
    WrongFile => ["Choose an XCI, NSP or NCA folder.", "Bitte wähle eine XCI, NSP oder einen NCA-Ordner aus."],
    WrongKeys => ["Choose a .keys file.", "Bitte wähle eine .keys-Datei aus."],
    EmptyFile => ["This file is empty. Please choose another file.", "Diese Datei ist leer. Bitte wähle eine andere Datei aus."],
    OneSource => ["Drop only one file or folder per area.", "Bitte lege pro Bereich nur eine Datei oder einen Ordner ab."],
    DropInArea => ["Drop your file inside its game, update or keys area.", "Lege die Datei im Bereich für Spiel, Update oder Schlüssel ab."],
    PreferenceError => ["Appearance changed, but could not be saved.", "Die Ansicht wurde geändert, konnte aber nicht gespeichert werden."],
    NcaFolder => ["NCA folder", "NCA-Ordner"],
    Files => ["files", "Dateien"],
    SingleFile => ["file", "Datei"],
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn resolves_regional_locales_and_falls_back_to_english() {
        assert_eq!(Language::from_locale("de_DE.UTF-8"), Language::German);
        assert_eq!(Language::from_locale("de-CH"), Language::German);
        assert_eq!(Language::from_locale("de-AT"), Language::German);
        assert_eq!(Language::from_locale("en-GB"), Language::English);
        assert_eq!(Language::from_locale("pt-BR"), Language::English);
        assert_eq!(Language::from_locale("es-ES"), Language::English);
        assert_eq!(Language::from_locale("ja-JP"), Language::English);
    }

    #[test]
    fn every_ui_label_has_both_translations() {
        for &label in Label::ALL {
            for language in [Language::German, Language::English] {
                assert!(!language.t(label).trim().is_empty());
            }
        }
    }
}
