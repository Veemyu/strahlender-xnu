#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Language {
    English,
    German,
    Spanish,
    Portuguese,
}

impl Language {
    #[cfg(test)]
    pub const ALL: [Self; 4] = [Self::English, Self::German, Self::Spanish, Self::Portuguese];

    pub fn decimal(self, value: &str) -> String {
        match self {
            Self::English => value.to_owned(),
            Self::German | Self::Spanish | Self::Portuguese => value.replace('.', ","),
        }
    }

    pub fn detect() -> Self {
        let locale = std::env::var("BDSP_LANG")
            .ok()
            .or_else(sys_locale::get_locale)
            .unwrap_or_default();
        Self::from_locale(&locale)
    }
    pub fn from_locale(locale: &str) -> Self {
        match locale
            .trim()
            .split(['-', '_', '.', '@'])
            .next()
            .unwrap_or("")
            .to_ascii_lowercase()
            .as_str()
        {
            "de" => Self::German,
            "es" => Self::Spanish,
            "pt" => Self::Portuguese,
            _ => Self::English,
        }
    }
}

macro_rules! messages {
    ($( $key:ident => [$en:literal, $de:literal, $es:literal, $pt:literal] ),* $(,)?) => {
        #[derive(Clone, Copy)]
        pub enum Label { $( $key ),* }
        #[cfg(test)]
        impl Label {
            const ALL: &'static [Self] = &[$(Self::$key),*];
        }
        impl Language {
            pub fn t(self, key: Label) -> &'static str {
                let values = match key { $(Label::$key => [$en, $de, $es, $pt]),* };
                values[match self { Self::English => 0, Self::German => 1, Self::Spanish => 2, Self::Portuguese => 3 }]
            }
        }
    }
}

messages! {
    FetchSource => ["Download current source", "Aktuellen Quellcode laden", "Descargar el código actual", "Descarregar o código atual"],
    UpdateShort => ["Update", "Update", "Actualización", "Atualização"],
    UpdateAvailable => ["Installer update available", "Installer-Update verfügbar", "Hay una actualización del instalador", "Atualização do instalador disponível"],
    UpdateRestartHint => ["Download the verified update and restart the installer? Your files and settings will be kept.", "Geprüftes Update herunterladen und den Installer neu starten? Deine Dateien und Einstellungen bleiben erhalten.", "¿Descargar la actualización verificada y reiniciar el instalador? Se conservarán tus archivos y ajustes.", "Descarregar a atualização verificada e reiniciar o instalador? Os teus ficheiros e definições serão mantidos."],
    UpdateInstaller => ["Update & restart", "Update & Neustart", "Actualizar y reiniciar", "Atualizar e reiniciar"],
    UpdateDownloading => ["Downloading update…", "Update wird geladen…", "Descargando actualización…", "A descarregar a atualização…"],
    DependenciesTitle => ["Prepare your computer", "Computer vorbereiten", "Prepara tu ordenador", "Prepara o teu computador"],
    DependenciesHint => ["These tools build your app. Installation may ask for your administrator password in a terminal.", "Diese Werkzeuge bauen deine App. Die Installation fragt gegebenenfalls im Terminal nach deinem Administratorpasswort.", "Estas herramientas crean tu aplicación. Su instalación puede pedirte la contraseña de administrador en un terminal.", "Estas ferramentas criam a tua aplicação. A instalação pode pedir a palavra-passe de administrador num terminal."],
    InstallDependencies => ["Install tools", "Installieren", "Instalar herramientas", "Instalar ferramentas"],
    CheckAgain => ["Check again", "Erneut prüfen", "Volver a comprobar", "Verificar novamente"],
    OpenRepository => ["Open project on GitHub", "Projekt auf GitHub öffnen", "Abrir el proyecto en GitHub", "Abrir o projeto no GitHub"],
    RepositoryError => ["Couldn't open the browser. Project: github.com/Veemyu/strahlender-xnu", "Browser konnte nicht geöffnet werden. Projekt: github.com/Veemyu/strahlender-xnu", "No se pudo abrir el navegador. Proyecto: github.com/Veemyu/strahlender-xnu", "Não foi possível abrir o navegador. Projeto: github.com/Veemyu/strahlender-xnu"],
    Setup => ["Setup", "Einrichtung", "Preparación", "Preparação"],
    SetupTitle => ["What happens next.", "So geht es weiter.", "Qué ocurre después.", "O que acontece a seguir."],
    SetupHint => ["We'll guide you through the preparation.", "Wir führen dich durch die Vorbereitung.", "Te guiaremos durante la preparación.", "Vamos guiar-te durante a preparação."],
    Target => ["Target", "Ziel", "Destino", "Destino"],
    TargetTitle => ["Where do you want to play?", "Wo möchtest du spielen?", "¿Dónde quieres jugar?", "Onde queres jogar?"],
    TargetHint => ["Choose the device for your finished app.", "Wähle das Gerät für deine fertige App.", "Elige el dispositivo para tu aplicación.", "Escolhe o dispositivo para a tua aplicação."],
    ComingLater => ["Later · Not available yet", "Später · Noch nicht verfügbar", "Más adelante · Aún no disponible", "Mais tarde · Ainda não disponível"],
    Simulation => ["Simulation", "Simulation", "Simulación", "Simulação"],
    TargetDesktopHint => ["Build for this computer. We'll check the tools needed for setup.", "Für diesen Computer bauen. Wir prüfen die benötigten Werkzeuge.", "Crea la aplicación para este ordenador. Comprobaremos las herramientas necesarias.", "Cria a aplicação para este computador. Vamos verificar as ferramentas necessárias."],
    TargetAppleHostHint => ["Apple targets need a Mac with Xcode. That build connection is still planned.", "Apple-Ziele benötigen einen Mac mit Xcode. Diese Build-Anbindung ist noch geplant.", "Los destinos de Apple necesitan un Mac con Xcode. Esta conexión de compilación está prevista.", "Os destinos Apple precisam de um Mac com Xcode. Esta ligação de compilação está prevista."],
    SetupAppleHost => ["Apple builds require macOS and Xcode. Building via a Mac is planned and is not connected in this preview.", "Apple-Builds benötigen macOS und Xcode. Der Build über einen Mac ist geplant und in dieser Vorschau noch nicht angebunden.", "Las compilaciones para Apple requieren macOS y Xcode. Está previsto compilar a través de un Mac, pero esta vista previa aún no lo permite.", "As compilações para Apple precisam de macOS e Xcode. Está prevista a compilação através de um Mac, mas esta pré-visualização ainda não a permite."],
    TargetMacHint => ["Build an app for this Mac. We'll check the tools you need before setup.", "Eine App für diesen Mac bauen. Zuerst prüfen wir die benötigten Werkzeuge.", "Crea una aplicación para este Mac. Primero comprobaremos las herramientas necesarias.", "Cria uma aplicação para este Mac. Primeiro vamos verificar as ferramentas necessárias."],
    TargetMobileHint => ["Prepare an app for your Apple device. Later we'll guide you through connecting it and signing the app.", "Eine App für dein Apple-Gerät vorbereiten. Später führen wir dich durch Verbindung und Signierung.", "Prepara una aplicación para tu dispositivo Apple. Más adelante te guiaremos para conectarlo y firmar la aplicación.", "Prepara uma aplicação para o teu dispositivo Apple. Mais tarde vamos guiar-te na ligação e assinatura da aplicação."],
    SetupDesktop => ["We check the tools needed for the build. Before setup, you will see what is missing and needs installing.", "Wir prüfen die Werkzeuge für den Build. Vor der Einrichtung siehst du, was fehlt und installiert werden soll.", "Comprobamos las herramientas necesarias para compilar. Antes de instalarlas, verás cuáles faltan.", "Verificamos as ferramentas necessárias para compilar. Antes da instalação, vais ver quais estão em falta."],
    SetupMac => ["The build needs Apple's developer tools on Mac. Before setup, you'll see what is missing and needs installing.", "Der Build auf dem Mac benötigt Apples Entwicklerwerkzeuge. Vor der Einrichtung siehst du, was fehlt und installiert werden soll.", "La compilación en Mac necesita las herramientas de desarrollo de Apple. Antes de instalarlas, verás cuáles faltan.", "A compilação no Mac precisa das ferramentas de desenvolvimento da Apple. Antes da instalação, vais ver quais estão em falta."],
    SetupMobile => ["Connect and unlock your iPad or iPhone. Xcode and your configured Apple signing team are used to build and install the app.", "Verbinde und entsperre dein iPad oder iPhone. Xcode und dein eingerichtetes Apple-Signierungsteam werden zum Bauen und Installieren verwendet.", "Conecta y desbloquea tu iPad o iPhone. Se usarán Xcode y tu equipo de firma de Apple configurado para compilar e instalar la aplicación.", "Liga e desbloqueia o teu iPad ou iPhone. O Xcode e a tua equipa de assinatura Apple configurada serão usados para compilar e instalar a aplicação."],
    BackendHint => ["The installer checks the required tools, prepares your game data and builds the app. You can follow every step in the log.", "Der Installer prüft die nötigen Werkzeuge, bereitet deine Spieldaten vor und baut die App. Im Protokoll kannst du jeden Schritt verfolgen.", "El instalador comprueba las herramientas, prepara los datos del juego y crea la aplicación. Puedes seguir cada paso en el registro.", "O instalador verifica as ferramentas, prepara os dados do jogo e cria a aplicação. Podes acompanhar cada passo no registo."],
    BackendUnavailable => ["A real build is not connected for this target or game format yet.", "Für dieses Ziel oder Spielformat ist noch kein echter Build angebunden.", "La compilación real aún no está disponible para este destino o formato de juego.", "A compilação real ainda não está disponível para este destino ou formato de jogo."],
    DemoData => ["Demo · Example file", "Demo · Beispieldatei", "Demo · Archivo de ejemplo", "Demo · Ficheiro de exemplo"],
    DemoGameFile => ["Example.xci", "Beispiel.xci", "Ejemplo.xci", "Exemplo.xci"],
    DemoUpdateFile => ["Example update.nsp", "Beispiel-Update.nsp", "Actualización de ejemplo.nsp", "Atualização de exemplo.nsp"],
    DemoNcaFolder => ["My NCA folder", "Mein NCA-Ordner", "Mi carpeta NCA", "A minha pasta NCA"],
    DemoLongName => ["My very long file name with accents àéï and spaces.xci", "Mein sehr langer Dateiname mit Umlauten äöü und Leerzeichen.xci", "Mi archivo con un nombre muy largo con acentos áéí y espacios.xci", "O meu ficheiro com um nome muito longo com acentos áéí e espaços.xci"],
    DemoMode => ["Demo · Explore without your own files", "Demo · Ohne eigene Dateien ausprobieren", "Demo · Explora sin tus propios archivos", "Demo · Explora sem os teus ficheiros"],
    UseExample => ["Use example file", "Beispieldatei verwenden", "Usar archivo de ejemplo", "Usar ficheiro de exemplo"],
    KeysTitle => ["Add your keys.", "Deine Schlüssel hinzufügen.", "Añade tus claves.", "Adiciona as tuas chaves."],
    KeysStepHint => ["First, add prod.keys from your own console.", "Zuerst prod.keys von deiner eigenen Konsole.", "Primero, añade prod.keys de tu propia consola.", "Primeiro, adiciona prod.keys da tua própria consola."],
    GameTitle => ["Add your game.", "Dein Basisspiel hinzufügen.", "Añade tu juego.", "Adiciona o teu jogo."],
    GameHint => ["Drop an XCI, NSP or NCA folder here.", "Ziehe eine XCI, NSP oder einen NCA-Ordner hierher.", "Arrastra aquí un XCI, NSP o una carpeta NCA.", "Arrasta para aqui um XCI, NSP ou uma pasta NCA."],
    UpdateTitle => ["Add an update?", "Ein Update hinzufügen?", "¿Añadir una actualización?", "Adicionar uma atualização?"],
    UpdateHint => ["Optional. You can continue without an update.", "Optional. Du kannst auch ohne Update fortfahren.", "Opcional. Puedes continuar sin actualizar.", "Opcional. Podes continuar sem uma atualização."],
    Mods => ["Mods", "Mods", "Mods", "Mods"],
    ModsLocation => ["Mod folder", "Mod-Ordner", "Carpeta del mod", "Pasta do mod"],
    ModsTitle => ["Add a mod?", "Einen Mod hinzufügen?", "¿Añadir un mod?", "Adicionar um mod?"],
    ModsChooseTitle => ["Choose what to play.", "Wähle, was du spielen möchtest.", "Elige a qué jugar.", "Escolhe o que jogar."],
    ModsChooseHint => ["One mod at a time, or the unmodified game.", "Ein Mod zur Zeit oder das unveränderte Spiel.", "Un mod cada vez, o el juego sin modificar.", "Um mod de cada vez, ou o jogo sem modificações."],
    ModsHint => ["Choose the whole mod folder; RomFS and ExeFS are found automatically.", "Wähle den ganzen Mod-Ordner; RomFS und ExeFS werden automatisch gefunden.", "Elige la carpeta completa del mod; RomFS y ExeFS se detectan automáticamente.", "Escolhe a pasta completa do mod; RomFS e ExeFS são detetados automaticamente."],
    RomFSNoBuild => ["RomFS-only mods need no rebuild. Copy them into this folder with your file manager, then refresh.", "Reine RomFS-Mods brauchen keinen Rebuild. Kopiere sie mit dem Dateimanager in diesen Ordner und aktualisiere die Liste.", "Los mods solo de RomFS no necesitan recompilar. Cópialos a esta carpeta con el gestor de archivos y actualiza la lista.", "Os mods só de RomFS não precisam de recompilação. Copia-os para esta pasta com o gestor de ficheiros e atualiza a lista."],
    ModsFolder => ["Mods folder", "Mod-Ordner", "Carpeta de mods", "Pasta de mods"],
    OpenModsFolder => ["Open folder", "Ordner öffnen", "Abrir carpeta", "Abrir pasta"],
    ChooseModFolder => ["Choose mod folder", "Mod-Ordner auswählen", "Elegir carpeta del mod", "Escolher pasta do mod"],
    RefreshMods => ["Refresh", "Aktualisieren", "Actualizar lista", "Atualizar lista"],
    NoMods => ["No mods found. The unmodified game stays available.", "Keine Mods gefunden. Das unveränderte Spiel bleibt verfügbar.", "No se encontraron mods. El juego sin modificar sigue disponible.", "Não foram encontrados mods. O jogo sem modificações continua disponível."],
    UnmodifiedGame => ["Unmodified game", "Unverändertes Spiel", "Juego sin modificar", "Jogo sem modificações"],
    RomFSOnly => ["RomFS files work now", "RomFS-Dateien funktionieren bereits", "Los archivos RomFS ya funcionan", "Os ficheiros RomFS já funcionam"],
    ExeFSBuildNeeded => ["ExeFS build needed", "ExeFS-Build erforderlich", "Requiere compilar ExeFS", "Requer compilação ExeFS"],
    ExeFSWarning => ["This mod contains ExeFS code. Building it is not supported yet; choose an unmodified game or a RomFS-only mod.", "Dieser Mod enthält ExeFS-Code. Sein Build wird noch nicht unterstützt; wähle das unveränderte Spiel oder einen reinen RomFS-Mod.", "Este mod contiene código ExeFS. Aún no se puede compilar; elige el juego sin modificar o un mod solo de RomFS.", "Este mod contém código ExeFS. Ainda não é possível compilá-lo; escolhe o jogo sem modificações ou um mod só de RomFS."],
    ExeFSBuildReady => ["IPS/IPS32 and subsdk1 are built into a separate mod app with its own icon and save. Your original app stays installed.", "IPS/IPS32 und subsdk1 werden in eine eigene Mod-App mit eigenem Icon und Spielstand eingebaut. Deine Original-App bleibt erhalten.", "IPS/IPS32 y subsdk1 se integran en una aplicación independiente con su propio icono y partida guardada. Tu aplicación original se conserva.", "IPS/IPS32 e subsdk1 são integrados numa aplicação separada, com ícone e progresso guardado próprios. A tua aplicação original é mantida."],
    ExeFSBuildReadyTag => ["Separate mod app", "Eigene Mod-App", "Aplicación del mod aparte", "Aplicação do mod separada"],
    ModAppResult => ["Separate app", "Eigene App", "App aparte", "App separada"],
    ExeFSUnsupported => ["This ExeFS folder contains unsupported files. Supported: IPS/IPS32 for main, sdk, subsdk0 and the additional subsdk1 module.", "Dieser ExeFS-Ordner enthält nicht unterstützte Dateien. Unterstützt: IPS/IPS32 für main, sdk, subsdk0 und das zusätzliche subsdk1-Modul.", "Esta carpeta ExeFS contiene archivos no admitidos. Se admiten IPS/IPS32 para main, sdk, subsdk0 y el módulo adicional subsdk1.", "Esta pasta ExeFS contém ficheiros não suportados. São suportados IPS/IPS32 para main, sdk, subsdk0 e o módulo adicional subsdk1."],
    ModsDeviceHint => ["On iPad/iPhone, add RomFS mods without rebuilding via Files → On My Device → BDSP → Mods. This local folder is staging only.", "Auf iPad/iPhone kannst du RomFS-Mods ohne Rebuild über Dateien → Auf meinem Gerät → BDSP → Mods hinzufügen. Dieser lokale Ordner dient nur zur Vorbereitung.", "En iPad/iPhone, añade mods RomFS sin recompilar desde Archivos → En mi dispositivo → BDSP → Mods. Esta carpeta local solo sirve para prepararlos.", "No iPad/iPhone, adiciona mods RomFS sem recompilar em Ficheiros → No meu dispositivo → BDSP → Mods. Esta pasta local serve apenas para os preparar."],
    ModsFolderUnavailable => ["Could not determine a local mods folder.", "Ein lokaler Mod-Ordner konnte nicht ermittelt werden.", "No se pudo determinar una carpeta local de mods.", "Não foi possível determinar uma pasta local de mods."],
    ModsPreviewHint => ["RomFS-only mods load at launch without recompiling. On Linux, this choice becomes the launcher default; on Mac, the app asks at launch.", "Reine RomFS-Mods laden beim Start ohne Rebuild. Unter Linux wird diese Wahl die Launcher-Vorgabe; auf dem Mac fragt die App beim Start.", "Los mods solo de RomFS se cargan al iniciar sin recompilar. En Linux, esta será la opción predeterminada del lanzador; en Mac, la aplicación preguntará al abrirse.", "Os mods só de RomFS são carregados ao iniciar sem recompilar. No Linux, esta será a opção predefinida do lançador; no Mac, a aplicação pergunta ao abrir."],
    UseLight => ["Switch to light mode", "Zum hellen Design wechseln", "Cambiar al modo claro", "Mudar para o modo claro"],
    UseDark => ["Switch to dark mode", "Zum dunklen Design wechseln", "Cambiar al modo oscuro", "Mudar para o modo escuro"],
    Base => ["Game", "Basisspiel", "Juego", "Jogo"],
    Update => ["Update", "Update", "Actualización", "Atualização"],
    Keys => ["Keys", "Schlüssel", "Claves", "Chaves"],
    Drop => ["Drop here", "Hier ablegen", "Suelta aquí", "Larga aqui"],
    Formats => ["XCI, NSP or NCA folder", "XCI, NSP oder NCA-Ordner", "XCI, NSP o carpeta NCA", "XCI, NSP ou pasta NCA"],
    File => ["Choose file", "Datei wählen", "Elegir archivo", "Escolher ficheiro"],
    Folder => ["Choose folder", "Ordner wählen", "Elegir carpeta", "Escolher pasta"],
    Remove => ["Remove", "Entfernen", "Quitar", "Remover"],
    Change => ["Change", "Ändern", "Cambiar", "Alterar"],
    SkipUpdate => ["Continue without update", "Ohne Update weiter", "Continuar sin actualizar", "Continuar sem atualização"],
    SkipMods => ["Skip", "Überspringen", "Omitir", "Saltar"],
    KeysHint => ["Drop prod.keys here or choose a file.", "prod.keys hier ablegen oder auswählen.", "Suelta prod.keys aquí o elige un archivo.", "Larga prod.keys aqui ou escolhe um ficheiro."],
    SearchKeys => ["Search again", "Erneut suchen", "Volver a buscar", "Pesquisar novamente"],
    NoKeys => ["No keys found automatically. You can add prod.keys yourself.", "Keine Schlüssel automatisch gefunden. Du kannst prod.keys selbst hinzufügen.", "No se encontraron claves automáticamente. Puedes añadir prod.keys manualmente.", "Não foram encontradas chaves automaticamente. Podes adicionar prod.keys manualmente."],
    FoundKeys => ["Keys found in an existing emulator folder.", "Schlüssel in einem vorhandenen Emulator-Ordner gefunden.", "Se encontraron claves en la carpeta de un emulador existente.", "Foram encontradas chaves na pasta de um emulador existente."],
    KeysRestored => ["Using the prod.keys file selected earlier.", "Die zuvor ausgewählte prod.keys-Datei wird verwendet.", "Se usa el archivo prod.keys elegido anteriormente.", "Está a ser usado o ficheiro prod.keys escolhido anteriormente."],
    ErrorTitle => ["Something needs attention", "Etwas braucht deine Aufmerksamkeit", "Algo necesita tu atención", "Algo precisa da tua atenção"],
    DismissError => ["Got it", "Verstanden", "Entendido", "Entendido"],
    ShowErrorDetails => ["Show details", "Details anzeigen", "Ver detalles", "Mostrar detalhes"],
    ErrorDetailsHint => ["The full session log has the exact step and diagnostic.", "Im Sitzungsprotokoll stehen der genaue Schritt und die Diagnose.", "El registro de la sesión muestra el paso exacto y el diagnóstico.", "O registo da sessão mostra o passo exato e o diagnóstico."],
    DiskSpaceError => ["There isn't enough free disk space for this build. Available: {available} GB · Required: {required} GB. Free up space and check again.", "Für diesen Build ist nicht genug Speicherplatz frei. Verfügbar: {available} GB · Benötigt: {required} GB. Gib Speicher frei und prüfe erneut.", "No hay suficiente espacio libre para compilar. Disponible: {available} GB · Necesario: {required} GB. Libera espacio y vuelve a comprobar.", "Não há espaço livre suficiente para compilar. Disponível: {available} GB · Necessário: {required} GB. Liberta espaço e verifica novamente."],
    PythonRuntimeError => ["The installer's private Python environment is missing or incomplete. Reinstall the installer to restore it, then try again.", "Die private Python-Umgebung des Installers fehlt oder ist unvollständig. Installiere den Installer erneut und starte den Build noch einmal.", "El entorno privado de Python del instalador falta o está incompleto. Reinstala el instalador para restaurarlo e inténtalo de nuevo.", "O ambiente privado de Python do instalador está em falta ou incompleto. Reinstala o instalador para o restaurar e tenta novamente."],
    PythonDevelopmentError => ["Python 3.9 or newer is needed by this development build. Install Python, then run the check again.", "Diese Entwicklungsversion benötigt Python 3.9 oder neuer. Installiere Python und starte die Prüfung erneut.", "Esta versión de desarrollo necesita Python 3.9 o posterior. Instala Python y vuelve a comprobar.", "Esta versão de desenvolvimento precisa de Python 3.9 ou posterior. Instala o Python e verifica novamente."],
    SavedInputMissing => ["A previously selected item is no longer available. Please choose it again.", "Eine frühere Auswahl ist nicht mehr verfügbar. Bitte wähle sie erneut aus.", "Un elemento elegido anteriormente ya no está disponible. Elígelo de nuevo.", "Um elemento escolhido anteriormente já não está disponível. Escolhe-o novamente."],
    SavedModFolderMissing => ["The previously selected mod folder is no longer available.", "Der zuvor ausgewählte Mod-Ordner ist nicht mehr verfügbar.", "La carpeta del mod elegida anteriormente ya no está disponible.", "A pasta do mod escolhida anteriormente já não está disponível."],
    PrivateKeys => ["Key contents stay private", "Schlüsselinhalte bleiben privat", "El contenido de las claves es privado", "O conteúdo das chaves é privado"],
    Inspecting => ["Checking…", "Wird geprüft …", "Comprobando…", "A verificar…"],
    Continue => ["Continue", "Weiter", "Continuar", "Continuar"],
    Back => ["Back", "Zurück", "Atrás", "Voltar"],
    ReviewTitle => ["Ready for a preview.", "Bereit für die Vorschau.", "Todo listo para la vista previa.", "Tudo pronto para a pré-visualização."],
    ReviewHint => ["Your selection, at a glance.", "Deine Auswahl auf einen Blick.", "Tu selección, de un vistazo.", "A tua seleção, num relance."],
    BuildOptions => ["Build options", "Build-Optionen", "Opciones de compilación", "Opções de compilação"],
    BuildOptionsHint => ["Choose how this build uses temporary files.", "Wähle, wie dieser Build temporäre Dateien nutzt.", "Elige cómo usar los archivos temporales.", "Escolhe como usar os ficheiros temporários."],
    CleanBuild => ["Clean build", "Sauberer Neuaufbau", "Compilar desde cero", "Compilar de raiz"],
    CleanBuildHint => ["Regenerate C and rebuild all game code. Extracted game data is reused.", "C neu erzeugen und den gesamten Spielcode neu bauen. Extrahierte Spieldaten werden wiederverwendet.", "Genera de nuevo el C y recompila todo el código del juego. Se reutilizan los datos extraídos.", "Volta a gerar o C e recompila todo o código do jogo. Os dados extraídos são reutilizados."],
    AutoCleanup => ["Clean up after installation", "Nach der Installation aufräumen", "Limpiar después de instalar", "Limpar após a instalação"],
    AutoCleanupHint => ["Remove downloaded sources and temporary build files after success. Keep the installed game, saves and your original files.", "Heruntergeladene Quellen und temporäre Build-Dateien nach Erfolg entfernen. Installiertes Spiel, Saves und deine Originaldateien bleiben erhalten.", "Elimina el código descargado y los archivos temporales tras la instalación correcta. Conserva el juego instalado, las partidas y tus archivos originales.", "Remove o código descarregado e os ficheiros temporários após uma instalação bem-sucedida. Mantém o jogo instalado, o progresso guardado e os teus ficheiros originais."],
    FailedBuildKept => ["Failed builds are kept for troubleshooting.", "Fehlgeschlagene Builds bleiben zur Fehleranalyse erhalten.", "Las compilaciones fallidas se conservan para investigar el problema.", "As compilações falhadas são mantidas para analisar o problema."],
    CleanupFailed => ["Your game is installed. Some temporary files could not be removed; see the log for details.", "Dein Spiel ist installiert. Einige temporäre Dateien konnten nicht entfernt werden; Details stehen im Protokoll.", "Tu juego está instalado. No se pudieron eliminar algunos archivos temporales; consulta el registro.", "O teu jogo está instalado. Não foi possível remover alguns ficheiros temporários; consulta o registo."],
    Cleanup => ["Cleaning up temporary files", "Temporäre Dateien aufräumen", "Limpiando archivos temporales", "A limpar ficheiros temporários"],
    OptimizeCpu => ["Optimize for this computer", "Für diesen Computer optimieren", "Optimizar para este ordenador", "Otimizar para este computador"],
    OptimizeCpuHint => ["Recommended. Uses AVX/AVX2 when supported by your CPU.", "Empfohlen. Nutzt AVX/AVX2, wenn deine CPU sie unterstützt.", "Recomendado. Usa AVX/AVX2 si tu procesador lo admite.", "Recomendado. Usa AVX/AVX2 se o teu processador suportar."],
    PortableCpuHint => ["Portable build for other computers. Does not require AVX or AVX2.", "Portabler Build für andere Computer. Benötigt kein AVX oder AVX2.", "Compilación portátil para otros ordenadores. No requiere AVX ni AVX2.", "Compilação portátil para outros computadores. Não requer AVX nem AVX2."],
    NoUpdate => ["No update", "Kein Update", "Sin actualización", "Sem atualização"],
    Computer => ["Device", "Gerät", "Dispositivo", "Dispositivo"],
    PreviewHint => ["This preview simulates setup. It won't install tools or process your game.", "Diese Vorschau simuliert den Ablauf. Sie installiert keine Werkzeuge und verarbeitet keine Spieldaten.", "Esta vista previa simula la preparación. No instala herramientas ni procesa tu juego.", "Esta pré-visualização simula a preparação. Não instala ferramentas nem processa o teu jogo."],
    StartPreview => ["Start preview", "Vorschau starten", "Iniciar vista previa", "Iniciar pré-visualização"],
    StartBuild => ["Build app", "App bauen", "Crear aplicación", "Criar aplicação"],
    LogBuildStart => ["Starting the game build.", "Spiel-Build wird gestartet.", "Iniciando la compilación del juego.", "A iniciar a compilação do jogo."],
    MissingInput => ["Game file or prod.keys is missing.", "Spieldatei oder prod.keys fehlt.", "Falta el archivo del juego o prod.keys.", "Falta o ficheiro do jogo ou prod.keys."],
    CancelBuild => ["Cancel build", "Build abbrechen", "Cancelar compilación", "Cancelar compilação"],
    InstalledIn => ["Installed in {folder}", "Installiert in {folder}", "Instalado en {folder}", "Instalado em {folder}"],
    ShowInFinder => ["Show in Finder", "Im Finder anzeigen", "Mostrar en Finder", "Mostrar no Finder"],
    ShowInFolder => ["Show installation folder", "Installationsordner anzeigen", "Mostrar carpeta de instalación", "Mostrar pasta de instalação"],
    ShowInstallationFailed => ["The installation folder couldn't be opened. Check that the app is still there.", "Der Installationsordner konnte nicht geöffnet werden. Prüfe, ob die App noch vorhanden ist.", "No se pudo abrir la carpeta de instalación. Comprueba que la aplicación siga allí.", "Não foi possível abrir a pasta de instalação. Verifica se a aplicação ainda lá está."],
    BuildPassed => ["Build complete.", "Build abgeschlossen.", "Compilación completada.", "Compilação concluída."],
    BuildFailed => ["Build failed. See details for the exact step.", "Build fehlgeschlagen. Details zeigen den genauen Schritt.", "La compilación falló. Consulta los detalles para ver el paso exacto.", "A compilação falhou. Consulta os detalhes para ver o passo exato."],
    BuildStepError => ["The build stopped during “{stage}”.\n\n{cause}\n\nOpen the details to see and copy the full build log.", "Der Build wurde bei „{stage}“ abgebrochen.\n\n{cause}\n\nIn den Details kannst du das vollständige Build-Protokoll ansehen und kopieren.", "La compilación se detuvo en «{stage}».\n\n{cause}\n\nAbre los detalles para ver y copiar el registro completo.", "A compilação parou em «{stage}».\n\n{cause}\n\nAbre os detalhes para ver e copiar o registo completo."],
    BuildStopped => ["Build cancelled.", "Build abgebrochen.", "Compilación cancelada.", "Compilação cancelada."],
    ReturnToSetup => ["Back to setup", "Zurück zur Einrichtung", "Volver a la preparación", "Voltar à preparação"],
    CheckingRequirements => ["Checking build requirements", "Build-Voraussetzungen werden geprüft", "Comprobando requisitos", "A verificar requisitos"],
    CheckFailed => ["Check finished with missing requirements", "Prüfung mit fehlenden Voraussetzungen beendet", "Comprobación terminada con requisitos pendientes", "Verificação concluída com requisitos em falta"],
    PrerequisiteInternalError => ["The installer couldn't finish checking the build requirements because of an internal error. This does not mean a package is missing. Open the details and copy the log to report the problem. Your game files have not been changed.", "Der Installer konnte die Build-Voraussetzungen wegen eines internen Fehlers nicht vollständig prüfen. Das bedeutet nicht, dass ein Paket fehlt. Öffne die Details und kopiere das Protokoll, um den Fehler zu melden. Deine Spieldateien wurden nicht verändert.", "Un error interno impidió terminar la comprobación de requisitos. Esto no significa que falte un paquete. Abre los detalles y copia el registro para informar del problema. Los archivos de tu juego no se han modificado.", "Um erro interno impediu a conclusão da verificação de requisitos. Isto não significa que falte um pacote. Abre os detalhes e copia o registo para comunicar o problema. Os ficheiros do teu jogo não foram alterados."],
    NeedsAttention => ["Needs attention", "Benötigt Aufmerksamkeit", "Necesita atención", "Precisa de atenção"],
    CheckStopped => ["Check cancelled.", "Prüfung abgebrochen.", "Comprobación cancelada.", "Verificação cancelada."],
    CancelRequested => ["Cancellation requested.", "Abbruch angefordert.", "Cancelación solicitada.", "Cancelamento pedido."],
    PythonMissing => ["Python 3.9+ is needed for this local development check. The released installer will bundle Python.", "Für diese lokale Entwicklungsprüfung wird Python 3.9+ benötigt. Der veröffentlichte Installer bringt Python selbst mit.", "Esta comprobación local de desarrollo necesita Python 3.9 o posterior. El instalador publicado incluirá Python.", "Esta verificação local de desenvolvimento precisa de Python 3.9 ou posterior. O instalador publicado incluirá Python."],
    RuntimeMissing => ["The verified private Python runtime is missing. Reinstall the installer runtime.", "Die geprüfte private Python-Runtime fehlt. Bitte die Installer-Runtime neu installieren.", "Falta el entorno privado de Python verificado. Reinstala el entorno del instalador.", "O ambiente privado de Python verificado está em falta. Reinstala o ambiente do instalador."],
    LogPreflight => ["Starting the read-only prerequisite check.", "Schreibfreie Vorprüfung starten.", "Iniciando la comprobación de requisitos sin modificar archivos.", "A iniciar a verificação de requisitos sem alterar ficheiros."],
    ProgressTitle => ["One step at a time.", "Schritt für Schritt.", "Paso a paso.", "Passo a passo."],
    Simulated => ["Preview · No files are being processed", "Vorschau · Keine Dateien werden verarbeitet", "Vista previa · No se procesan archivos", "Pré-visualização · Nenhum ficheiro é processado"],
    Tools => ["Check tools", "Werkzeuge prüfen", "Comprobar herramientas", "Verificar ferramentas"],
    Prepare => ["Prepare game", "Spieldaten vorbereiten", "Preparar juego", "Preparar jogo"],
    Generate => ["Generate game code", "Spielcode erzeugen", "Generar código del juego", "Gerar código do jogo"],
    Compile => ["Compile game code · Clang", "Spielcode kompilieren · Clang", "Compilar código · Clang", "Compilar código · Clang"],
    Images => ["Prepare module images", "Modul-Images vorbereiten", "Preparar imágenes de módulos", "Preparar imagens dos módulos"],
    ExeFS => ["Apply ExeFS patches", "ExeFS-Patches anwenden", "Aplicar parches ExeFS", "Aplicar patches ExeFS"],
    Runtime => ["Build runtime", "Runtime bauen", "Compilar entorno de ejecución", "Compilar ambiente de execução"],
    Install => ["Install app", "App installieren", "Instalar aplicación", "Instalar aplicação"],
    Package => ["Package app", "App zusammenstellen", "Empaquetar aplicación", "Empacotar aplicação"],
    FilesCompiled => ["files compiled", "Dateien kompiliert", "archivos compilados", "ficheiros compilados"],
    AnalyzingModule => ["Analyzing module", "Modul analysieren", "Analizando módulo", "A analisar módulo"],
    FunctionsGenerated => ["functions generated", "Funktionen erzeugt", "funciones generadas", "funções geradas"],
    Module => ["Module", "Modul", "Módulo", "Módulo"],
    ModulesGenerated => ["modules generated", "Module erzeugt", "módulos generados", "módulos gerados"],
    CompletedStage => ["Completed", "Abgeschlossen", "Completado", "Concluído"],
    NextStage => ["Next", "Als Nächstes", "Siguiente", "Seguinte"],
    Done => ["Done", "Fertig", "Listo", "Concluído"],
    Running => ["Running", "Läuft", "En curso", "Em curso"],
    Details => ["Show details", "Details anzeigen", "Ver detalles", "Mostrar detalhes"],
    HideDetails => ["Hide details", "Details schließen", "Ocultar detalles", "Ocultar detalhes"],
    CopyLog => ["Copy log", "Protokoll kopieren", "Copiar registro", "Copiar registo"],
    LogEmpty => ["No activity yet.", "Noch keine Aktivität.", "Aún no hay actividad.", "Ainda não há atividade."],
    LogSearch => ["Searching standard emulator folders for prod.keys.", "Übliche Emulator-Ordner nach prod.keys durchsuchen.", "Buscando prod.keys en las carpetas habituales de emuladores.", "A procurar prod.keys nas pastas habituais dos emuladores."],
    LogInspect => ["Checking readability and file type.", "Lesbarkeit und Dateityp prüfen.", "Comprobando lectura y tipo de archivo.", "A verificar leitura e tipo de ficheiro."],
    LogAccepted => ["File check complete. Content validation is still pending.", "Dateiprüfung abgeschlossen. Inhaltsprüfung steht noch aus.", "Comprobación del archivo completada. La validación del contenido está pendiente.", "Verificação do ficheiro concluída. A validação do conteúdo está pendente."],
    LogPreview => ["Starting simulated setup. No commands are executed.", "Simulierten Ablauf starten. Es werden keine Befehle ausgeführt.", "Iniciando la preparación simulada. No se ejecutan comandos.", "A iniciar a preparação simulada. Não são executados comandos."],
    LogStopped => ["Preview stopped by user.", "Vorschau durch Nutzer beendet.", "Vista previa detenida por el usuario.", "Pré-visualização interrompida pelo utilizador."],
    LogComplete => ["Simulation complete. Nothing was installed.", "Simulation abgeschlossen. Es wurde nichts installiert.", "Simulación completada. No se ha instalado nada.", "Simulação concluída. Nada foi instalado."],
    Step => ["Step", "Schritt", "Paso", "Passo"],
    Of => ["of", "von", "de", "de"],
    CheckSelection => ["Review", "Auswahl prüfen", "Revisar", "Rever seleção"],
    Stop => ["Stop preview", "Vorschau beenden", "Detener vista previa", "Parar pré-visualização"],
    FinishedTitle => ["Preview complete.", "Vorschau abgeschlossen.", "Vista previa completada.", "Pré-visualização concluída."],
    FinishedHint => ["Your selection is saved for this session. No game has been installed.", "Deine Auswahl bleibt für diese Sitzung erhalten. Es wurde noch kein Spiel installiert.", "Tu selección se conserva durante esta sesión. No se ha instalado ningún juego.", "A tua seleção é mantida durante esta sessão. Nenhum jogo foi instalado."],
    ToSelection => ["Back to files", "Zur Dateiauswahl", "Volver a los archivos", "Voltar aos ficheiros"],
    Region => ["Region", "Region", "Región", "Região"],
    RegionPending => ["Not checked yet", "Noch nicht geprüft", "Aún sin comprobar", "Ainda não verificada"],
    Unreadable => ["This path cannot be read. Please select it again.", "Dieser Pfad ist nicht lesbar. Bitte wähle ihn erneut aus.", "No se puede leer esta ruta. Vuelve a seleccionarla.", "Não é possível ler este caminho. Volta a selecioná-lo."],
    KeysFileOnly => ["Choose prod.keys, not a folder.", "Bitte wähle prod.keys aus, keinen Ordner.", "Elige prod.keys, no una carpeta.", "Escolhe prod.keys, não uma pasta."],
    NoNca => ["No NCA files in this folder. Choose the folder containing the .nca files.", "Hier liegen keine NCA-Dateien. Wähle den Ordner direkt mit den .nca-Dateien.", "No hay archivos NCA en esta carpeta. Elige la carpeta que contenga los archivos .nca.", "Não há ficheiros NCA nesta pasta. Escolhe a pasta que contém os ficheiros .nca."],
    WrongFile => ["Choose an XCI, NSP or NCA folder.", "Bitte wähle eine XCI, NSP oder einen NCA-Ordner aus.", "Elige un XCI, NSP o una carpeta NCA.", "Escolhe um XCI, NSP ou uma pasta NCA."],
    WrongKeys => ["Choose a .keys file.", "Bitte wähle eine .keys-Datei aus.", "Elige un archivo .keys.", "Escolhe um ficheiro .keys."],
    EmptyFile => ["This file is empty. Please choose another file.", "Diese Datei ist leer. Bitte wähle eine andere Datei aus.", "Este archivo está vacío. Elige otro.", "Este ficheiro está vazio. Escolhe outro."],
    OneSource => ["Drop only one file or folder per area.", "Bitte lege pro Bereich nur eine Datei oder einen Ordner ab.", "Suelta solo un archivo o carpeta por zona.", "Larga apenas um ficheiro ou pasta por área."],
    DropInArea => ["Drop your file inside its game, update or keys area.", "Lege die Datei im Bereich für Spiel, Update oder Schlüssel ab.", "Suelta el archivo en la zona de juego, actualización o claves.", "Larga o ficheiro na área do jogo, atualização ou chaves."],
    PreferenceError => ["Appearance changed, but could not be saved.", "Die Ansicht wurde geändert, konnte aber nicht gespeichert werden.", "El aspecto cambió, pero no se pudo guardar.", "O aspeto foi alterado, mas não foi possível guardá-lo."],
    NcaFolder => ["NCA folder", "NCA-Ordner", "Carpeta NCA", "Pasta NCA"],
    Files => ["files", "Dateien", "archivos", "ficheiros"],
    SingleFile => ["file", "Datei", "archivo", "ficheiro"],
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
        assert_eq!(Language::from_locale("pt-BR"), Language::Portuguese);
        assert_eq!(Language::from_locale("es-ES"), Language::Spanish);
        assert_eq!(Language::from_locale("ja-JP"), Language::English);
    }

    #[test]
    fn regional_spanish_and_portuguese_share_their_base_catalogs() {
        for locale in [
            "es",
            "es-ES",
            "es-419",
            "es-MX",
            "es-AR",
            "es-CL",
            "ES_co.UTF-8",
            "es@euro",
        ] {
            assert_eq!(Language::from_locale(locale), Language::Spanish, "{locale}");
        }
        for locale in [
            "pt",
            "pt-PT",
            "pt-BR",
            "pt_BR.UTF-8",
            "pt-AO",
            "PT_mz",
            "pt@euro",
        ] {
            assert_eq!(
                Language::from_locale(locale),
                Language::Portuguese,
                "{locale}"
            );
        }
        for label in Label::ALL {
            assert_eq!(
                Language::from_locale("es-MX").t(*label),
                Language::from_locale("es-ES").t(*label)
            );
            assert_eq!(
                Language::from_locale("pt-BR").t(*label),
                Language::from_locale("pt-PT").t(*label)
            );
        }
    }

    #[test]
    fn translated_parameters_match_the_english_catalog() {
        fn parameters(value: &str) -> Vec<&str> {
            let mut parameters: Vec<_> = value
                .split('{')
                .skip(1)
                .map(|part| {
                    part.split_once('}')
                        .expect("Unclosed translation parameter")
                        .0
                })
                .collect();
            parameters.sort_unstable();
            parameters
        }
        for label in Label::ALL {
            let expected = parameters(Language::English.t(*label));
            for language in Language::ALL {
                assert_eq!(parameters(language.t(*label)), expected);
            }
        }
    }

    #[test]
    fn every_ui_label_has_all_four_translations() {
        for &label in Label::ALL {
            for language in Language::ALL {
                assert!(!language.t(label).trim().is_empty());
            }
        }
    }
}
