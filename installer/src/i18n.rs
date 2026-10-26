#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Language {
    English,
    German,
    Spanish,
    Portuguese,
    Russian,
}

impl Language {
    #[cfg(test)]
    pub const ALL: [Self; 5] = [
        Self::English,
        Self::German,
        Self::Spanish,
        Self::Portuguese,
        Self::Russian,
    ];

    pub fn decimal(self, value: &str) -> String {
        match self {
            Self::English => value.to_owned(),
            Self::German | Self::Spanish | Self::Portuguese | Self::Russian => {
                value.replace('.', ",")
            }
        }
    }

    pub fn dependency_purpose(self, id: &str) -> Option<&'static str> {
        Some(self.t(match id {
            "compiler" | "clang" => Label::Compile,
            "git" => Label::ExtractionTools,
            "cmake" => Label::NativeHelpers,
            "pkg-config" => Label::LocateLibraries,
            "sdl3" | "SDL3" => Label::WindowAudioControllers,
            "ffmpeg" => Label::PlayMovies,
            "qt" => Label::LinuxWindowControls,
            "vulkan" => Label::GpuRendering,
            "shaderc" => Label::CompileShaders,
            "vma" => Label::GpuMemory,
            "time" => Label::BuildTimings,
            "wayland" => Label::WaylandWindow,
            _ => return None,
        }))
    }

    pub fn dependency_note(self, note: &str) -> Option<&'static str> {
        [
            Label::InstallCltNote,
            Label::InstallXcodeNote,
            Label::FinishXcodeNote,
            Label::VmaAurNote,
        ]
        .into_iter()
        .find(|label| Self::English.t(*label) == note)
        .map(|label| self.t(label))
    }

    pub fn files(self, count: u64) -> &'static str {
        let label = if self == Self::Russian {
            match (count % 10, count % 100) {
                (1, n) if n != 11 => Label::SingleFile,
                (2..=4, n) if !(12..=14).contains(&n) => Label::FewFiles,
                _ => Label::Files,
            }
        } else if count == 1 {
            Label::SingleFile
        } else {
            Label::Files
        };
        self.t(label)
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
            "ru" => Self::Russian,
            // Explicit product fallback, not a Ukrainian translation or regional alias.
            "uk" => Self::Russian,
            _ => Self::English,
        }
    }
}

macro_rules! messages {
    ($( $key:ident => [$en:literal, $de:literal, $es:literal, $pt:literal, $ru:literal] ),* $(,)?) => {
        #[derive(Clone, Copy)]
        pub enum Label { $( $key ),* }
        #[cfg(test)]
        impl Label {
            const ALL: &'static [Self] = &[$(Self::$key),*];
        }
        impl Language {
            pub fn t(self, key: Label) -> &'static str {
                let values = match key { $(Label::$key => [$en, $de, $es, $pt, $ru]),* };
                values[match self { Self::English => 0, Self::German => 1, Self::Spanish => 2, Self::Portuguese => 3, Self::Russian => 4 }]
            }
        }
    }
}

messages! {
    ExportIpa => ["Export IPA", "IPA exportieren", "Exportar IPA", "Exportar IPA", "Экспорт IPA"],
    InstallOnDevice => ["Install on device", "Auf Gerät installieren", "Instalar en dispositivo", "Instalar no dispositivo", "Установить на устройство"],
    IpaExportHint => ["Build with Xcode. No connected device or signing team needed. SideStore signs the IPA; LiveContainer compatibility is being tested.", "Mit Xcode bauen. Kein verbundenes Gerät oder Signierungsteam nötig. SideStore signiert die IPA; LiveContainer-Kompatibilität wird getestet.", "Compila con Xcode sin dispositivo conectado ni equipo de firma. SideStore firma la IPA; la compatibilidad con LiveContainer está en pruebas.", "Compila com o Xcode sem dispositivo ligado nem equipa de assinatura. O SideStore assina a IPA; a compatibilidade com o LiveContainer está em teste.", "Сборка через Xcode без подключённого устройства и команды подписи. SideStore подпишет IPA; совместимость с LiveContainer проверяется."],
    IpaExported => ["IPA and game library exported", "IPA und Spieldaten exportiert", "IPA y biblioteca exportadas", "IPA e biblioteca exportadas", "IPA и библиотека экспортированы"],
    IpaInstallSteps => ["Import the IPA into SideStore. Transfer the Game Library folder to Files, then select it in the game. Keep save backups outside the app.", "IPA in SideStore importieren. Den Ordner Game Library nach Dateien übertragen und im Spiel auswählen. Save-Backups außerhalb der App aufbewahren.", "Importa la IPA en SideStore. Transfiere Game Library a Archivos y selecciónala en el juego. Guarda copias de partidas fuera de la app.", "Importa a IPA no SideStore. Transfere Game Library para Ficheiros e seleciona-a no jogo. Guarda cópias do progresso fora da aplicação.", "Импортируйте IPA в SideStore. Перенесите Game Library в Файлы и выберите её в игре. Храните копии сохранений вне приложения."],
    ShowIpa => ["Show IPA", "IPA anzeigen", "Mostrar IPA", "Mostrar IPA", "Показать IPA"],
    ShowGameLibrary => ["Show game files", "Spieldaten anzeigen", "Mostrar datos", "Mostrar dados", "Показать данные"],
    ExportOutput => ["Export app and game data", "App und Spieldaten exportieren", "Exportar app y datos", "Exportar aplicação e dados", "Экспорт приложения и данных"],
    FetchSource => ["Download current source", "Aktuellen Quellcode laden", "Descargar el código actual", "Descarregar o código atual", "Скачать актуальный исходный код"],
    UpdateShort => ["Update", "Update", "Actualización", "Atualização", "Обновление"],
    UpdateAvailable => ["Installer update available", "Installer-Update verfügbar", "Hay una actualización del instalador", "Atualização do instalador disponível", "Доступно обновление установщика"],
    UpdateRestartHint => ["Download the verified update and restart the installer? Your files and settings will be kept.", "Geprüftes Update herunterladen und den Installer neu starten? Deine Dateien und Einstellungen bleiben erhalten.", "¿Descargar la actualización verificada y reiniciar el instalador? Se conservarán tus archivos y ajustes.", "Descarregar a atualização verificada e reiniciar o instalador? Os teus ficheiros e definições serão mantidos.", "Скачать проверенное обновление и перезапустить установщик? Ваши файлы и настройки сохранятся."],
    UpdateInstaller => ["Update & restart", "Update & Neustart", "Actualizar y reiniciar", "Atualizar e reiniciar", "Обновить и перезапустить"],
    UpdateDownloading => ["Downloading update…", "Update wird geladen…", "Descargando actualización…", "A descarregar a atualização…", "Загрузка обновления…"],
    DependenciesTitle => ["Prepare your computer", "Computer vorbereiten", "Prepara tu ordenador", "Prepara o teu computador", "Подготовьте компьютер"],
    DependenciesHint => ["These tools build your app. Installation may ask for your administrator password in a terminal.", "Diese Werkzeuge bauen deine App. Die Installation fragt gegebenenfalls im Terminal nach deinem Administratorpasswort.", "Estas herramientas crean tu aplicación. Su instalación puede pedirte la contraseña de administrador en un terminal.", "Estas ferramentas criam a tua aplicação. A instalação pode pedir a palavra-passe de administrador num terminal.", "Эти инструменты создают приложение. При их установке может потребоваться пароль администратора в терминале."],
    InstallDependencies => ["Install tools", "Installieren", "Instalar herramientas", "Instalar ferramentas", "Установить инструменты"],
    CheckAgain => ["Check again", "Erneut prüfen", "Volver a comprobar", "Verificar novamente", "Проверить снова"],
    OpenRepository => ["Open project on GitHub", "Projekt auf GitHub öffnen", "Abrir el proyecto en GitHub", "Abrir o projeto no GitHub", "Открыть проект на GitHub"],
    RepositoryError => ["Couldn't open the browser. Project: github.com/Veemyu/strahlender-xnu", "Browser konnte nicht geöffnet werden. Projekt: github.com/Veemyu/strahlender-xnu", "No se pudo abrir el navegador. Proyecto: github.com/Veemyu/strahlender-xnu", "Não foi possível abrir o navegador. Projeto: github.com/Veemyu/strahlender-xnu", "Не удалось открыть браузер. Проект: github.com/Veemyu/strahlender-xnu"],
    Setup => ["Setup", "Einrichtung", "Preparación", "Preparação", "Подготовка"],
    SetupTitle => ["What happens next.", "So geht es weiter.", "Qué ocurre después.", "O que acontece a seguir.", "Что будет дальше."],
    SetupHint => ["We'll guide you through the preparation.", "Wir führen dich durch die Vorbereitung.", "Te guiaremos durante la preparación.", "Vamos guiar-te durante a preparação.", "Мы поможем пройти подготовку."],
    Target => ["Target", "Ziel", "Destino", "Destino", "Платформа"],
    TargetTitle => ["Where do you want to play?", "Wo möchtest du spielen?", "¿Dónde quieres jugar?", "Onde queres jogar?", "Где хотите играть?"],
    TargetHint => ["Choose the device for your finished app.", "Wähle das Gerät für deine fertige App.", "Elige el dispositivo para tu aplicación.", "Escolhe o dispositivo para a tua aplicação.", "Выберите устройство для готового приложения."],
    ComingLater => ["Later · Not available yet", "Später · Noch nicht verfügbar", "Más adelante · Aún no disponible", "Mais tarde · Ainda não disponível", "Позже · Пока недоступно"],
    Simulation => ["Simulation", "Simulation", "Simulación", "Simulação", "Симуляция"],
    TargetDesktopHint => ["Build for this computer. We'll check the tools needed for setup.", "Für diesen Computer bauen. Wir prüfen die benötigten Werkzeuge.", "Crea la aplicación para este ordenador. Comprobaremos las herramientas necesarias.", "Cria a aplicação para este computador. Vamos verificar as ferramentas necessárias.", "Создайте приложение для этого компьютера. Мы проверим необходимые инструменты."],
    TargetAppleHostHint => ["Apple targets need a Mac with Xcode. That build connection is still planned.", "Apple-Ziele benötigen einen Mac mit Xcode. Diese Build-Anbindung ist noch geplant.", "Los destinos de Apple necesitan un Mac con Xcode. Esta conexión de compilación está prevista.", "Os destinos Apple precisam de um Mac com Xcode. Esta ligação de compilação está prevista.", "Для платформ Apple нужен Mac с Xcode. Такое подключение для сборки запланировано."],
    SetupAppleHost => ["Apple builds require macOS and Xcode. Building via a Mac is planned and is not connected in this preview.", "Apple-Builds benötigen macOS und Xcode. Der Build über einen Mac ist geplant und in dieser Vorschau noch nicht angebunden.", "Las compilaciones para Apple requieren macOS y Xcode. Está previsto compilar a través de un Mac, pero esta vista previa aún no lo permite.", "As compilações para Apple precisam de macOS e Xcode. Está prevista a compilação através de um Mac, mas esta pré-visualização ainda não a permite.", "Для сборок Apple нужны macOS и Xcode. Сборка через Mac запланирована, но пока недоступна в этом предпросмотре."],
    TargetMacHint => ["Build an app for this Mac. We'll check the tools you need before setup.", "Eine App für diesen Mac bauen. Zuerst prüfen wir die benötigten Werkzeuge.", "Crea una aplicación para este Mac. Primero comprobaremos las herramientas necesarias.", "Cria uma aplicação para este Mac. Primeiro vamos verificar as ferramentas necessárias.", "Создайте приложение для этого Mac. Сначала мы проверим необходимые инструменты."],
    TargetMobileHint => ["Export an IPA or install on a connected device.", "IPA exportieren oder auf verbundenem Gerät installieren.", "Exporta una IPA o instala en un dispositivo conectado.", "Exporta uma IPA ou instala num dispositivo ligado.", "Экспорт IPA или установка на подключённое устройство."],
    SetupDesktop => ["We check the tools needed for the build. Before setup, you will see what is missing and needs installing.", "Wir prüfen die Werkzeuge für den Build. Vor der Einrichtung siehst du, was fehlt und installiert werden soll.", "Comprobamos las herramientas necesarias para compilar. Antes de instalarlas, verás cuáles faltan.", "Verificamos as ferramentas necessárias para compilar. Antes da instalação, vais ver quais estão em falta.", "Мы проверяем инструменты для сборки. До установки вы увидите, какие из них отсутствуют."],
    SetupMac => ["The build needs Apple's developer tools on Mac. Before setup, you'll see what is missing and needs installing.", "Der Build auf dem Mac benötigt Apples Entwicklerwerkzeuge. Vor der Einrichtung siehst du, was fehlt und installiert werden soll.", "La compilación en Mac necesita las herramientas de desarrollo de Apple. Antes de instalarlas, verás cuáles faltan.", "A compilação no Mac precisa das ferramentas de desenvolvimento da Apple. Antes da instalação, vais ver quais estão em falta.", "Для сборки на Mac нужны инструменты разработчика Apple. До установки вы увидите, какие из них отсутствуют."],
    SetupMobile => ["Connect and unlock your iPad or iPhone. Xcode and your configured Apple signing team are used to build and install the app.", "Verbinde und entsperre dein iPad oder iPhone. Xcode und dein eingerichtetes Apple-Signierungsteam werden zum Bauen und Installieren verwendet.", "Conecta y desbloquea tu iPad o iPhone. Se usarán Xcode y tu equipo de firma de Apple configurado para compilar e instalar la aplicación.", "Liga e desbloqueia o teu iPad ou iPhone. O Xcode e a tua equipa de assinatura Apple configurada serão usados para compilar e instalar a aplicação.", "Подключите и разблокируйте iPad или iPhone. Для сборки и установки используются Xcode и настроенная команда подписи Apple."],
    BackendHint => ["The installer checks the required tools, prepares your game data and builds the app. You can follow every step in the log.", "Der Installer prüft die nötigen Werkzeuge, bereitet deine Spieldaten vor und baut die App. Im Protokoll kannst du jeden Schritt verfolgen.", "El instalador comprueba las herramientas, prepara los datos del juego y crea la aplicación. Puedes seguir cada paso en el registro.", "O instalador verifica as ferramentas, prepara os dados do jogo e cria a aplicação. Podes acompanhar cada passo no registo.", "Установщик проверяет инструменты, подготавливает данные игры и создаёт приложение. Каждый шаг можно проследить в журнале."],
    BackendUnavailable => ["A real build is not connected for this target or game format yet.", "Für dieses Ziel oder Spielformat ist noch kein echter Build angebunden.", "La compilación real aún no está disponible para este destino o formato de juego.", "A compilação real ainda não está disponível para este destino ou formato de jogo.", "Настоящая сборка для этой платформы или формата игры пока недоступна."],
    DemoData => ["Demo · Example file", "Demo · Beispieldatei", "Demo · Archivo de ejemplo", "Demo · Ficheiro de exemplo", "Демо · Пример файла"],
    DemoGameFile => ["Example.xci", "Beispiel.xci", "Ejemplo.xci", "Exemplo.xci", "Пример.xci"],
    DemoUpdateFile => ["Example update.nsp", "Beispiel-Update.nsp", "Actualización de ejemplo.nsp", "Atualização de exemplo.nsp", "Пример обновления.nsp"],
    DemoNcaFolder => ["My NCA folder", "Mein NCA-Ordner", "Mi carpeta NCA", "A minha pasta NCA", "Моя папка NCA"],
    DemoLongName => ["My very long file name with accents àéï and spaces.xci", "Mein sehr langer Dateiname mit Umlauten äöü und Leerzeichen.xci", "Mi archivo con un nombre muy largo con acentos áéí y espacios.xci", "O meu ficheiro com um nome muito longo com acentos áéí e espaços.xci", "Мой файл с очень длинным названием и пробелами.xci"],
    DemoMode => ["Demo · Explore without your own files", "Demo · Ohne eigene Dateien ausprobieren", "Demo · Explora sin tus propios archivos", "Demo · Explora sem os teus ficheiros", "Демо · Без собственных файлов"],
    UseExample => ["Use example file", "Beispieldatei verwenden", "Usar archivo de ejemplo", "Usar ficheiro de exemplo", "Использовать пример"],
    KeysTitle => ["Add your keys.", "Deine Schlüssel hinzufügen.", "Añade tus claves.", "Adiciona as tuas chaves.", "Добавьте ключи."],
    KeysStepHint => ["First, add prod.keys from your own console.", "Zuerst prod.keys von deiner eigenen Konsole.", "Primero, añade prod.keys de tu propia consola.", "Primeiro, adiciona prod.keys da tua própria consola.", "Сначала добавьте prod.keys со своей консоли."],
    GameTitle => ["Add your game.", "Dein Basisspiel hinzufügen.", "Añade tu juego.", "Adiciona o teu jogo.", "Добавьте игру."],
    GameHint => ["Drop an XCI, NSP or NCA folder here.", "Ziehe eine XCI, NSP oder einen NCA-Ordner hierher.", "Arrastra aquí un XCI, NSP o una carpeta NCA.", "Arrasta para aqui um XCI, NSP ou uma pasta NCA.", "Перетащите сюда XCI, NSP или папку NCA."],
    UpdateTitle => ["Add an update?", "Ein Update hinzufügen?", "¿Añadir una actualización?", "Adicionar uma atualização?", "Добавить обновление?"],
    UpdateHint => ["Optional. You can continue without an update.", "Optional. Du kannst auch ohne Update fortfahren.", "Opcional. Puedes continuar sin actualizar.", "Opcional. Podes continuar sem uma atualização.", "Необязательно. Можно продолжить без обновления."],
    Mods => ["Mods", "Mods", "Mods", "Mods", "Моды"],
    ModsLocation => ["Mod folder", "Mod-Ordner", "Carpeta del mod", "Pasta do mod", "Папка мода"],
    ModsTitle => ["Add a mod?", "Einen Mod hinzufügen?", "¿Añadir un mod?", "Adicionar um mod?", "Добавить мод?"],
    ModsChooseTitle => ["Choose what to play.", "Wähle, was du spielen möchtest.", "Elige a qué jugar.", "Escolhe o que jogar.", "Выберите, во что играть."],
    ModsChooseHint => ["One mod at a time, or the unmodified game.", "Ein Mod zur Zeit oder das unveränderte Spiel.", "Un mod cada vez, o el juego sin modificar.", "Um mod de cada vez, ou o jogo sem modificações.", "Один мод за раз или игра без изменений."],
    ModsHint => ["Choose the whole mod folder; RomFS and ExeFS are found automatically.", "Wähle den ganzen Mod-Ordner; RomFS und ExeFS werden automatisch gefunden.", "Elige la carpeta completa del mod; RomFS y ExeFS se detectan automáticamente.", "Escolhe a pasta completa do mod; RomFS e ExeFS são detetados automaticamente.", "Выберите всю папку мода; RomFS и ExeFS будут найдены автоматически."],
    RomFSNoBuild => ["RomFS-only mods need no rebuild. Copy them into this folder with your file manager, then refresh.", "Reine RomFS-Mods brauchen keinen Rebuild. Kopiere sie mit dem Dateimanager in diesen Ordner und aktualisiere die Liste.", "Los mods solo de RomFS no necesitan recompilar. Cópialos a esta carpeta con el gestor de archivos y actualiza la lista.", "Os mods só de RomFS não precisam de recompilação. Copia-os para esta pasta com o gestor de ficheiros e atualiza a lista.", "Моды только с RomFS не требуют пересборки. Скопируйте их в эту папку через файловый менеджер и обновите список."],
    ModsFolder => ["Mods folder", "Mod-Ordner", "Carpeta de mods", "Pasta de mods", "Папка модов"],
    OpenModsFolder => ["Open folder", "Ordner öffnen", "Abrir carpeta", "Abrir pasta", "Открыть папку"],
    ChooseModFolder => ["Choose mod folder", "Mod-Ordner auswählen", "Elegir carpeta del mod", "Escolher pasta do mod", "Выбрать папку мода"],
    RefreshMods => ["Refresh", "Aktualisieren", "Actualizar lista", "Atualizar lista", "Обновить"],
    NoMods => ["No mods found. The unmodified game stays available.", "Keine Mods gefunden. Das unveränderte Spiel bleibt verfügbar.", "No se encontraron mods. El juego sin modificar sigue disponible.", "Não foram encontrados mods. O jogo sem modificações continua disponível.", "Моды не найдены. Игра без изменений остаётся доступной."],
    UnmodifiedGame => ["Unmodified game", "Unverändertes Spiel", "Juego sin modificar", "Jogo sem modificações", "Игра без изменений"],
    RomFSOnly => ["RomFS files work now", "RomFS-Dateien funktionieren bereits", "Los archivos RomFS ya funcionan", "Os ficheiros RomFS já funcionam", "Файлы RomFS уже работают"],
    ExeFSBuildNeeded => ["ExeFS build needed", "ExeFS-Build erforderlich", "Requiere compilar ExeFS", "Requer compilação ExeFS", "Нужна сборка ExeFS"],
    ExeFSWarning => ["This mod contains ExeFS code. Building it is not supported yet; choose an unmodified game or a RomFS-only mod.", "Dieser Mod enthält ExeFS-Code. Sein Build wird noch nicht unterstützt; wähle das unveränderte Spiel oder einen reinen RomFS-Mod.", "Este mod contiene código ExeFS. Aún no se puede compilar; elige el juego sin modificar o un mod solo de RomFS.", "Este mod contém código ExeFS. Ainda não é possível compilá-lo; escolhe o jogo sem modificações ou um mod só de RomFS.", "Этот мод содержит код ExeFS. Его сборка пока не поддерживается; выберите игру без изменений или мод только с RomFS."],
    ExeFSBuildReady => ["IPS/IPS32 and subsdk1 are built into a separate mod app with its own icon and save. Your original app stays installed.", "IPS/IPS32 und subsdk1 werden in eine eigene Mod-App mit eigenem Icon und Spielstand eingebaut. Deine Original-App bleibt erhalten.", "IPS/IPS32 y subsdk1 se integran en una aplicación independiente con su propio icono y partida guardada. Tu aplicación original se conserva.", "IPS/IPS32 e subsdk1 são integrados numa aplicação separada, com ícone e progresso guardado próprios. A tua aplicação original é mantida.", "IPS/IPS32 и subsdk1 встраиваются в отдельное приложение мода со своим значком и сохранениями. Исходное приложение останется установленным."],
    ExeFSBuildReadyTag => ["Separate mod app", "Eigene Mod-App", "Aplicación del mod aparte", "Aplicação do mod separada", "Отдельное приложение мода"],
    ModAppResult => ["Separate app", "Eigene App", "App aparte", "App separada", "Отдельно"],
    ExeFSUnsupported => ["This ExeFS folder contains unsupported files. Supported: IPS/IPS32 for main, sdk, subsdk0 and the additional subsdk1 module.", "Dieser ExeFS-Ordner enthält nicht unterstützte Dateien. Unterstützt: IPS/IPS32 für main, sdk, subsdk0 und das zusätzliche subsdk1-Modul.", "Esta carpeta ExeFS contiene archivos no admitidos. Se admiten IPS/IPS32 para main, sdk, subsdk0 y el módulo adicional subsdk1.", "Esta pasta ExeFS contém ficheiros não suportados. São suportados IPS/IPS32 para main, sdk, subsdk0 e o módulo adicional subsdk1.", "В этой папке ExeFS есть неподдерживаемые файлы. Поддерживаются IPS/IPS32 для main, sdk, subsdk0 и дополнительный модуль subsdk1."],
    ModsDeviceHint => ["On iPad/iPhone, add RomFS mods without rebuilding via Files → On My Device → BDSP → Mods. This local folder is staging only.", "Auf iPad/iPhone kannst du RomFS-Mods ohne Rebuild über Dateien → Auf meinem Gerät → BDSP → Mods hinzufügen. Dieser lokale Ordner dient nur zur Vorbereitung.", "En iPad/iPhone, añade mods RomFS sin recompilar desde Archivos → En mi dispositivo → BDSP → Mods. Esta carpeta local solo sirve para prepararlos.", "No iPad/iPhone, adiciona mods RomFS sem recompilar em Ficheiros → No meu dispositivo → BDSP → Mods. Esta pasta local serve apenas para os preparar.", "На iPad/iPhone добавляйте моды RomFS без пересборки через Файлы → На моём устройстве → BDSP → Mods. Локальная папка нужна только для подготовки."],
    ModsFolderUnavailable => ["Could not determine a local mods folder.", "Ein lokaler Mod-Ordner konnte nicht ermittelt werden.", "No se pudo determinar una carpeta local de mods.", "Não foi possível determinar uma pasta local de mods.", "Не удалось определить локальную папку модов."],
    ModsPreviewHint => ["RomFS-only mods load at launch without recompiling. On Linux, this choice becomes the launcher default; on Mac, the app asks at launch.", "Reine RomFS-Mods laden beim Start ohne Rebuild. Unter Linux wird diese Wahl die Launcher-Vorgabe; auf dem Mac fragt die App beim Start.", "Los mods solo de RomFS se cargan al iniciar sin recompilar. En Linux, esta será la opción predeterminada del lanzador; en Mac, la aplicación preguntará al abrirse.", "Os mods só de RomFS são carregados ao iniciar sem recompilar. No Linux, esta será a opção predefinida do lançador; no Mac, a aplicação pergunta ao abrir.", "Моды только с RomFS загружаются при запуске без пересборки. В Linux выбор станет настройкой запуска по умолчанию; на Mac приложение спросит при открытии."],
    UseLight => ["Switch to light mode", "Zum hellen Design wechseln", "Cambiar al modo claro", "Mudar para o modo claro", "Включить светлую тему"],
    UseDark => ["Switch to dark mode", "Zum dunklen Design wechseln", "Cambiar al modo oscuro", "Mudar para o modo escuro", "Включить тёмную тему"],
    Base => ["Game", "Basisspiel", "Juego", "Jogo", "Игра"],
    Update => ["Update", "Update", "Actualización", "Atualização", "Обновление"],
    Keys => ["Keys", "Schlüssel", "Claves", "Chaves", "Ключи"],
    Drop => ["Drop here", "Hier ablegen", "Suelta aquí", "Larga aqui", "Перетащите сюда"],
    Formats => ["XCI, NSP or NCA folder", "XCI, NSP oder NCA-Ordner", "XCI, NSP o carpeta NCA", "XCI, NSP ou pasta NCA", "XCI, NSP или папка NCA"],
    File => ["Choose file", "Datei wählen", "Elegir archivo", "Escolher ficheiro", "Выбрать файл"],
    Folder => ["Choose folder", "Ordner wählen", "Elegir carpeta", "Escolher pasta", "Выбрать папку"],
    Remove => ["Remove", "Entfernen", "Quitar", "Remover", "Убрать"],
    Change => ["Change", "Ändern", "Cambiar", "Alterar", "Изменить"],
    SkipUpdate => ["Continue without update", "Ohne Update weiter", "Continuar sin actualizar", "Continuar sem atualização", "Без обновления"],
    SkipMods => ["Skip", "Überspringen", "Omitir", "Saltar", "Пропустить"],
    KeysHint => ["Drop prod.keys here or choose a file.", "prod.keys hier ablegen oder auswählen.", "Suelta prod.keys aquí o elige un archivo.", "Larga prod.keys aqui ou escolhe um ficheiro.", "Перетащите сюда prod.keys или выберите файл."],
    SearchKeys => ["Search again", "Erneut suchen", "Volver a buscar", "Pesquisar novamente", "Найти снова"],
    NoKeys => ["No keys found automatically. You can add prod.keys yourself.", "Keine Schlüssel automatisch gefunden. Du kannst prod.keys selbst hinzufügen.", "No se encontraron claves automáticamente. Puedes añadir prod.keys manualmente.", "Não foram encontradas chaves automaticamente. Podes adicionar prod.keys manualmente.", "Ключи не найдены автоматически. Вы можете добавить prod.keys вручную."],
    FoundKeys => ["Keys found in an existing emulator folder.", "Schlüssel in einem vorhandenen Emulator-Ordner gefunden.", "Se encontraron claves en la carpeta de un emulador existente.", "Foram encontradas chaves na pasta de um emulador existente.", "Ключи найдены в папке установленного эмулятора."],
    KeysRestored => ["Using the prod.keys file selected earlier.", "Die zuvor ausgewählte prod.keys-Datei wird verwendet.", "Se usa el archivo prod.keys elegido anteriormente.", "Está a ser usado o ficheiro prod.keys escolhido anteriormente.", "Используется ранее выбранный файл prod.keys."],
    ErrorTitle => ["Something needs attention", "Etwas braucht deine Aufmerksamkeit", "Algo necesita tu atención", "Algo precisa da tua atenção", "Требуется внимание"],
    DismissError => ["Got it", "Verstanden", "Entendido", "Entendido", "Понятно"],
    ShowErrorDetails => ["Show details", "Details anzeigen", "Ver detalles", "Mostrar detalhes", "Показать подробности"],
    ErrorDetailsHint => ["The full session log has the exact step and diagnostic.", "Im Sitzungsprotokoll stehen der genaue Schritt und die Diagnose.", "El registro de la sesión muestra el paso exacto y el diagnóstico.", "O registo da sessão mostra o passo exato e o diagnóstico.", "Точный шаг и причина указаны в журнале сеанса."],
    DiskSpaceError => ["There isn't enough free disk space for this build. Available: {available} GB · Required: {required} GB. Free up space and check again.", "Für diesen Build ist nicht genug Speicherplatz frei. Verfügbar: {available} GB · Benötigt: {required} GB. Gib Speicher frei und prüfe erneut.", "No hay suficiente espacio libre para compilar. Disponible: {available} GB · Necesario: {required} GB. Libera espacio y vuelve a comprobar.", "Não há espaço livre suficiente para compilar. Disponível: {available} GB · Necessário: {required} GB. Liberta espaço e verifica novamente.", "Недостаточно свободного места для сборки. Доступно: {available} ГБ · Нужно: {required} ГБ. Освободите место и проверьте снова."],
    PythonRuntimeError => ["The installer's private Python environment is missing or incomplete. Reinstall the installer to restore it, then try again.", "Die private Python-Umgebung des Installers fehlt oder ist unvollständig. Installiere den Installer erneut und starte den Build noch einmal.", "El entorno privado de Python del instalador falta o está incompleto. Reinstala el instalador para restaurarlo e inténtalo de nuevo.", "O ambiente privado de Python do instalador está em falta ou incompleto. Reinstala o instalador para o restaurar e tenta novamente.", "Встроенная среда Python установщика отсутствует или неполна. Переустановите установщик, чтобы восстановить её, и попробуйте снова."],
    PythonDevelopmentError => ["Python 3.9 or newer is needed by this development build. Install Python, then run the check again.", "Diese Entwicklungsversion benötigt Python 3.9 oder neuer. Installiere Python und starte die Prüfung erneut.", "Esta versión de desarrollo necesita Python 3.9 o posterior. Instala Python y vuelve a comprobar.", "Esta versão de desenvolvimento precisa de Python 3.9 ou posterior. Instala o Python e verifica novamente.", "Эта версия для разработки требует Python 3.9 или новее. Установите Python и повторите проверку."],
    SavedInputMissing => ["A previously selected item is no longer available. Please choose it again.", "Eine frühere Auswahl ist nicht mehr verfügbar. Bitte wähle sie erneut aus.", "Un elemento elegido anteriormente ya no está disponible. Elígelo de nuevo.", "Um elemento escolhido anteriormente já não está disponível. Escolhe-o novamente.", "Ранее выбранный элемент больше недоступен. Выберите его снова."],
    SavedModFolderMissing => ["The previously selected mod folder is no longer available.", "Der zuvor ausgewählte Mod-Ordner ist nicht mehr verfügbar.", "La carpeta del mod elegida anteriormente ya no está disponible.", "A pasta do mod escolhida anteriormente já não está disponível.", "Ранее выбранная папка мода больше недоступна."],
    PrivateKeys => ["Key contents stay private", "Schlüsselinhalte bleiben privat", "El contenido de las claves es privado", "O conteúdo das chaves é privado", "Содержимое ключей конфиденциально"],
    Inspecting => ["Checking…", "Wird geprüft …", "Comprobando…", "A verificar…", "Проверка…"],
    Continue => ["Continue", "Weiter", "Continuar", "Continuar", "Продолжить"],
    Back => ["Back", "Zurück", "Atrás", "Voltar", "Назад"],
    ReviewTitle => ["Ready for a preview.", "Bereit für die Vorschau.", "Todo listo para la vista previa.", "Tudo pronto para a pré-visualização.", "Всё готово к предпросмотру."],
    ReviewHint => ["Your selection, at a glance.", "Deine Auswahl auf einen Blick.", "Tu selección, de un vistazo.", "A tua seleção, num relance.", "Ваш выбор перед началом."],
    BuildOptions => ["Build options", "Build-Optionen", "Opciones de compilación", "Opções de compilação", "Параметры сборки"],
    BuildOptionsHint => ["Choose how this build uses temporary files.", "Wähle, wie dieser Build temporäre Dateien nutzt.", "Elige cómo usar los archivos temporales.", "Escolhe como usar os ficheiros temporários.", "Выберите, как использовать временные файлы."],
    CleanBuild => ["Clean build", "Sauberer Neuaufbau", "Compilar desde cero", "Compilar de raiz", "Чистая сборка"],
    CleanBuildHint => ["Regenerate C and rebuild all game code. Extracted game data is reused.", "C neu erzeugen und den gesamten Spielcode neu bauen. Extrahierte Spieldaten werden wiederverwendet.", "Genera de nuevo el C y recompila todo el código del juego. Se reutilizan los datos extraídos.", "Volta a gerar o C e recompila todo o código do jogo. Os dados extraídos são reutilizados.", "Заново создать C и пересобрать весь код игры. Извлечённые данные используются повторно."],
    AutoCleanup => ["Clean up after installation", "Nach der Installation aufräumen", "Limpiar después de instalar", "Limpar após a instalação", "Очистить после установки"],
    AutoCleanupHint => ["Remove downloaded sources and temporary build files after success. Keep the installed game, saves and your original files.", "Heruntergeladene Quellen und temporäre Build-Dateien nach Erfolg entfernen. Installiertes Spiel, Saves und deine Originaldateien bleiben erhalten.", "Elimina el código descargado y los archivos temporales tras la instalación correcta. Conserva el juego instalado, las partidas y tus archivos originales.", "Remove o código descarregado e os ficheiros temporários após uma instalação bem-sucedida. Mantém o jogo instalado, o progresso guardado e os teus ficheiros originais.", "После успешной установки удалить скачанный код и временные файлы. Игра, сохранения и ваши исходные файлы останутся."],
    FailedBuildKept => ["Failed builds are kept for troubleshooting.", "Fehlgeschlagene Builds bleiben zur Fehleranalyse erhalten.", "Las compilaciones fallidas se conservan para investigar el problema.", "As compilações falhadas são mantidas para analisar o problema.", "Неудачные сборки сохраняются для поиска причины ошибки."],
    CleanupFailed => ["Your game is installed. Some temporary files could not be removed; see the log for details.", "Dein Spiel ist installiert. Einige temporäre Dateien konnten nicht entfernt werden; Details stehen im Protokoll.", "Tu juego está instalado. No se pudieron eliminar algunos archivos temporales; consulta el registro.", "O teu jogo está instalado. Não foi possível remover alguns ficheiros temporários; consulta o registo.", "Игра установлена. Не удалось удалить некоторые временные файлы; подробности в журнале."],
    Cleanup => ["Cleaning up temporary files", "Temporäre Dateien aufräumen", "Limpiando archivos temporales", "A limpar ficheiros temporários", "Удаление временных файлов"],
    OptimizeCpu => ["Optimize for this computer", "Für diesen Computer optimieren", "Optimizar para este ordenador", "Otimizar para este computador", "Оптимизировать для этого ПК"],
    OptimizeCpuHint => ["Recommended. Uses AVX/AVX2 when supported by your CPU.", "Empfohlen. Nutzt AVX/AVX2, wenn deine CPU sie unterstützt.", "Recomendado. Usa AVX/AVX2 si tu procesador lo admite.", "Recomendado. Usa AVX/AVX2 se o teu processador suportar.", "Рекомендуется. Использует доступные AVX/AVX2."],
    PortableCpuHint => ["Portable build for other computers. Does not require AVX or AVX2.", "Portabler Build für andere Computer. Benötigt kein AVX oder AVX2.", "Compilación portátil para otros ordenadores. No requiere AVX ni AVX2.", "Compilação portátil para outros computadores. Não requer AVX nem AVX2.", "Переносимая сборка для других компьютеров. AVX и AVX2 не требуются."],
    NoUpdate => ["No update", "Kein Update", "Sin actualización", "Sem atualização", "Без обновления"],
    Computer => ["Device", "Gerät", "Dispositivo", "Dispositivo", "Устройство"],
    PreviewHint => ["This preview simulates setup. It won't install tools or process your game.", "Diese Vorschau simuliert den Ablauf. Sie installiert keine Werkzeuge und verarbeitet keine Spieldaten.", "Esta vista previa simula la preparación. No instala herramientas ni procesa tu juego.", "Esta pré-visualização simula a preparação. Não instala ferramentas nem processa o teu jogo.", "Этот предпросмотр имитирует подготовку. Инструменты не устанавливаются, данные игры не обрабатываются."],
    StartPreview => ["Start preview", "Vorschau starten", "Iniciar vista previa", "Iniciar pré-visualização", "Начать предпросмотр"],
    StartBuild => ["Build app", "App bauen", "Crear aplicación", "Criar aplicação", "Создать приложение"],
    LogBuildStart => ["Starting the game build.", "Spiel-Build wird gestartet.", "Iniciando la compilación del juego.", "A iniciar a compilação do jogo.", "Начинается сборка игры."],
    MissingInput => ["Game file or prod.keys is missing.", "Spieldatei oder prod.keys fehlt.", "Falta el archivo del juego o prod.keys.", "Falta o ficheiro do jogo ou prod.keys.", "Отсутствует файл игры или prod.keys."],
    CancelBuild => ["Cancel build", "Build abbrechen", "Cancelar compilación", "Cancelar compilação", "Отменить сборку"],
    InstalledIn => ["Installed in {folder}", "Installiert in {folder}", "Instalado en {folder}", "Instalado em {folder}", "Установлено в {folder}"],
    ShowInFinder => ["Show in Finder", "Im Finder anzeigen", "Mostrar en Finder", "Mostrar no Finder", "Показать в Finder"],
    ShowInFolder => ["Show installation folder", "Installationsordner anzeigen", "Mostrar carpeta de instalación", "Mostrar pasta de instalação", "Показать папку установки"],
    ShowInstallationFailed => ["The installation folder couldn't be opened. Check that the app is still there.", "Der Installationsordner konnte nicht geöffnet werden. Prüfe, ob die App noch vorhanden ist.", "No se pudo abrir la carpeta de instalación. Comprueba que la aplicación siga allí.", "Não foi possível abrir a pasta de instalação. Verifica se a aplicação ainda lá está.", "Не удалось открыть папку установки. Убедитесь, что приложение всё ещё там."],
    BuildPassed => ["Build complete.", "Build abgeschlossen.", "Compilación completada.", "Compilação concluída.", "Сборка завершена."],
    BuildFailed => ["Build failed. See details for the exact step.", "Build fehlgeschlagen. Details zeigen den genauen Schritt.", "La compilación falló. Consulta los detalles para ver el paso exacto.", "A compilação falhou. Consulta os detalhes para ver o passo exato.", "Сборка не удалась. Точный шаг указан в подробностях."],
    BuildStepError => ["The build stopped during “{stage}”.\n\n{cause}\n\nOpen the details to see and copy the full build log.", "Der Build wurde bei „{stage}“ abgebrochen.\n\n{cause}\n\nIn den Details kannst du das vollständige Build-Protokoll ansehen und kopieren.", "La compilación se detuvo en «{stage}».\n\n{cause}\n\nAbre los detalles para ver y copiar el registro completo.", "A compilação parou em «{stage}».\n\n{cause}\n\nAbre os detalhes para ver e copiar o registo completo.", "Сборка остановлена на шаге «{stage}».\n\n{cause}\n\nОткройте подробности, чтобы просмотреть и скопировать весь журнал сборки."],
    BuildStopped => ["Build cancelled.", "Build abgebrochen.", "Compilación cancelada.", "Compilação cancelada.", "Сборка отменена."],
    ReturnToSetup => ["Back to setup", "Zurück zur Einrichtung", "Volver a la preparación", "Voltar à preparação", "К подготовке"],
    CheckingRequirements => ["Checking build requirements", "Build-Voraussetzungen werden geprüft", "Comprobando requisitos", "A verificar requisitos", "Проверка требований сборки"],
    CheckFailed => ["Check finished with missing requirements", "Prüfung mit fehlenden Voraussetzungen beendet", "Comprobación terminada con requisitos pendientes", "Verificação concluída com requisitos em falta", "Проверка завершена: не все требования выполнены"],
    PrerequisiteInternalError => ["The installer couldn't finish checking the build requirements because of an internal error. This does not mean a package is missing. Open the details and copy the log to report the problem. Your game files have not been changed.", "Der Installer konnte die Build-Voraussetzungen wegen eines internen Fehlers nicht vollständig prüfen. Das bedeutet nicht, dass ein Paket fehlt. Öffne die Details und kopiere das Protokoll, um den Fehler zu melden. Deine Spieldateien wurden nicht verändert.", "Un error interno impidió terminar la comprobación de requisitos. Esto no significa que falte un paquete. Abre los detalles y copia el registro para informar del problema. Los archivos de tu juego no se han modificado.", "Um erro interno impediu a conclusão da verificação de requisitos. Isto não significa que falte um pacote. Abre os detalhes e copia o registo para comunicar o problema. Os ficheiros do teu jogo não foram alterados.", "Внутренняя ошибка помешала завершить проверку требований. Это не означает, что отсутствует пакет. Откройте подробности и скопируйте журнал, чтобы сообщить о проблеме. Файлы игры не изменены."],
    NeedsAttention => ["Needs attention", "Benötigt Aufmerksamkeit", "Necesita atención", "Precisa de atenção", "Требуется внимание"],
    CheckStopped => ["Check cancelled.", "Prüfung abgebrochen.", "Comprobación cancelada.", "Verificação cancelada.", "Проверка отменена."],
    CancelRequested => ["Cancellation requested.", "Abbruch angefordert.", "Cancelación solicitada.", "Cancelamento pedido.", "Запрошена отмена."],
    PythonMissing => ["Python 3.9+ is needed for this local development check. The released installer will bundle Python.", "Für diese lokale Entwicklungsprüfung wird Python 3.9+ benötigt. Der veröffentlichte Installer bringt Python selbst mit.", "Esta comprobación local de desarrollo necesita Python 3.9 o posterior. El instalador publicado incluirá Python.", "Esta verificação local de desenvolvimento precisa de Python 3.9 ou posterior. O instalador publicado incluirá Python.", "Для этой локальной проверки разработки нужен Python 3.9 или новее. Выпускаемый установщик будет включать Python."],
    RuntimeMissing => ["The verified private Python runtime is missing. Reinstall the installer runtime.", "Die geprüfte private Python-Runtime fehlt. Bitte die Installer-Runtime neu installieren.", "Falta el entorno privado de Python verificado. Reinstala el entorno del instalador.", "O ambiente privado de Python verificado está em falta. Reinstala o ambiente do instalador.", "Отсутствует проверенная встроенная среда Python. Переустановите среду установщика."],
    LogPreflight => ["Starting the read-only prerequisite check.", "Schreibfreie Vorprüfung starten.", "Iniciando la comprobación de requisitos sin modificar archivos.", "A iniciar a verificação de requisitos sem alterar ficheiros.", "Начинается проверка требований без изменения файлов."],
    ProgressTitle => ["One step at a time.", "Schritt für Schritt.", "Paso a paso.", "Passo a passo.", "Шаг за шагом."],
    Simulated => ["Preview · No files are being processed", "Vorschau · Keine Dateien werden verarbeitet", "Vista previa · No se procesan archivos", "Pré-visualização · Nenhum ficheiro é processado", "Предпросмотр · Файлы не обрабатываются"],
    Tools => ["Check tools", "Werkzeuge prüfen", "Comprobar herramientas", "Verificar ferramentas", "Проверить инструменты"],
    Prepare => ["Prepare game", "Spieldaten vorbereiten", "Preparar juego", "Preparar jogo", "Подготовить игру"],
    Generate => ["Generate game code", "Spielcode erzeugen", "Generar código del juego", "Gerar código do jogo", "Создать код игры"],
    Compile => ["Compile game code · Clang", "Spielcode kompilieren · Clang", "Compilar código · Clang", "Compilar código · Clang", "Компиляция кода · Clang"],
    Images => ["Prepare module images", "Modul-Images vorbereiten", "Preparar imágenes de módulos", "Preparar imagens dos módulos", "Подготовить образы модулей"],
    ExeFS => ["Apply ExeFS patches", "ExeFS-Patches anwenden", "Aplicar parches ExeFS", "Aplicar patches ExeFS", "Применить патчи ExeFS"],
    Runtime => ["Build runtime", "Runtime bauen", "Compilar entorno de ejecución", "Compilar ambiente de execução", "Собрать среду выполнения"],
    Install => ["Install app", "App installieren", "Instalar aplicación", "Instalar aplicação", "Установить приложение"],
    Package => ["Package app", "App zusammenstellen", "Empaquetar aplicación", "Empacotar aplicação", "Упаковать приложение"],
    FilesCompiled => ["files compiled", "Dateien kompiliert", "archivos compilados", "ficheiros compilados", "файлов скомпилировано"],
    AnalyzingModule => ["Analyzing module", "Modul analysieren", "Analizando módulo", "A analisar módulo", "Анализ модуля"],
    FunctionsGenerated => ["functions generated", "Funktionen erzeugt", "funciones generadas", "funções geradas", "функций создано"],
    Module => ["Module", "Modul", "Módulo", "Módulo", "Модуль"],
    ModulesGenerated => ["modules generated", "Module erzeugt", "módulos generados", "módulos gerados", "модулей создано"],
    CompletedStage => ["Completed", "Abgeschlossen", "Completado", "Concluído", "Готово"],
    NextStage => ["Next", "Als Nächstes", "Siguiente", "Seguinte", "Далее"],
    Done => ["Done", "Fertig", "Listo", "Concluído", "Готово"],
    Running => ["Running", "Läuft", "En curso", "Em curso", "Выполняется"],
    Details => ["Show details", "Details anzeigen", "Ver detalles", "Mostrar detalhes", "Показать подробности"],
    HideDetails => ["Hide details", "Details schließen", "Ocultar detalles", "Ocultar detalhes", "Скрыть подробности"],
    CopyLog => ["Copy log", "Protokoll kopieren", "Copiar registro", "Copiar registo", "Скопировать журнал"],
    LogEmpty => ["No activity yet.", "Noch keine Aktivität.", "Aún no hay actividad.", "Ainda não há atividade.", "Действий пока нет."],
    LogSearch => ["Searching standard emulator folders for prod.keys.", "Übliche Emulator-Ordner nach prod.keys durchsuchen.", "Buscando prod.keys en las carpetas habituales de emuladores.", "A procurar prod.keys nas pastas habituais dos emuladores.", "Поиск prod.keys в стандартных папках эмуляторов."],
    LogInspect => ["Checking readability and file type.", "Lesbarkeit und Dateityp prüfen.", "Comprobando lectura y tipo de archivo.", "A verificar leitura e tipo de ficheiro.", "Проверка доступности и типа файла."],
    LogAccepted => ["File check complete. Content validation is still pending.", "Dateiprüfung abgeschlossen. Inhaltsprüfung steht noch aus.", "Comprobación del archivo completada. La validación del contenido está pendiente.", "Verificação do ficheiro concluída. A validação do conteúdo está pendente.", "Проверка файла завершена. Проверка содержимого ещё не выполнена."],
    LogPreview => ["Starting simulated setup. No commands are executed.", "Simulierten Ablauf starten. Es werden keine Befehle ausgeführt.", "Iniciando la preparación simulada. No se ejecutan comandos.", "A iniciar a preparação simulada. Não são executados comandos.", "Начинается имитация подготовки. Команды не выполняются."],
    LogStopped => ["Preview stopped by user.", "Vorschau durch Nutzer beendet.", "Vista previa detenida por el usuario.", "Pré-visualização interrompida pelo utilizador.", "Предпросмотр остановлен пользователем."],
    LogComplete => ["Simulation complete. Nothing was installed.", "Simulation abgeschlossen. Es wurde nichts installiert.", "Simulación completada. No se ha instalado nada.", "Simulação concluída. Nada foi instalado.", "Симуляция завершена. Ничего не установлено."],
    Step => ["Step", "Schritt", "Paso", "Passo", "Шаг"],
    Of => ["of", "von", "de", "de", "из"],
    CheckSelection => ["Review", "Auswahl prüfen", "Revisar", "Rever seleção", "Проверить выбор"],
    Stop => ["Stop preview", "Vorschau beenden", "Detener vista previa", "Parar pré-visualização", "Остановить предпросмотр"],
    FinishedTitle => ["Preview complete.", "Vorschau abgeschlossen.", "Vista previa completada.", "Pré-visualização concluída.", "Предпросмотр завершён."],
    FinishedHint => ["Your selection is saved for this session. No game has been installed.", "Deine Auswahl bleibt für diese Sitzung erhalten. Es wurde noch kein Spiel installiert.", "Tu selección se conserva durante esta sesión. No se ha instalado ningún juego.", "A tua seleção é mantida durante esta sessão. Nenhum jogo foi instalado.", "Ваш выбор сохранён на время сеанса. Игра не установлена."],
    ToSelection => ["Back to files", "Zur Dateiauswahl", "Volver a los archivos", "Voltar aos ficheiros", "К выбору файлов"],
    Region => ["Region", "Region", "Región", "Região", "Регион"],
    RegionPending => ["Not checked yet", "Noch nicht geprüft", "Aún sin comprobar", "Ainda não verificada", "Ещё не проверен"],
    Unreadable => ["This path cannot be read. Please select it again.", "Dieser Pfad ist nicht lesbar. Bitte wähle ihn erneut aus.", "No se puede leer esta ruta. Vuelve a seleccionarla.", "Não é possível ler este caminho. Volta a selecioná-lo.", "Не удалось прочитать этот путь. Выберите его снова."],
    KeysFileOnly => ["Choose prod.keys, not a folder.", "Bitte wähle prod.keys aus, keinen Ordner.", "Elige prod.keys, no una carpeta.", "Escolhe prod.keys, não uma pasta.", "Выберите prod.keys, а не папку."],
    NoNca => ["No NCA files in this folder. Choose the folder containing the .nca files.", "Hier liegen keine NCA-Dateien. Wähle den Ordner direkt mit den .nca-Dateien.", "No hay archivos NCA en esta carpeta. Elige la carpeta que contenga los archivos .nca.", "Não há ficheiros NCA nesta pasta. Escolhe a pasta que contém os ficheiros .nca.", "В этой папке нет файлов NCA. Выберите папку с файлами .nca."],
    WrongFile => ["Choose an XCI, NSP or NCA folder.", "Bitte wähle eine XCI, NSP oder einen NCA-Ordner aus.", "Elige un XCI, NSP o una carpeta NCA.", "Escolhe um XCI, NSP ou uma pasta NCA.", "Выберите XCI, NSP или папку NCA."],
    WrongKeys => ["Choose a .keys file.", "Bitte wähle eine .keys-Datei aus.", "Elige un archivo .keys.", "Escolhe um ficheiro .keys.", "Выберите файл .keys."],
    EmptyFile => ["This file is empty. Please choose another file.", "Diese Datei ist leer. Bitte wähle eine andere Datei aus.", "Este archivo está vacío. Elige otro.", "Este ficheiro está vazio. Escolhe outro.", "Этот файл пуст. Выберите другой."],
    OneSource => ["Drop only one file or folder per area.", "Bitte lege pro Bereich nur eine Datei oder einen Ordner ab.", "Suelta solo un archivo o carpeta por zona.", "Larga apenas um ficheiro ou pasta por área.", "Перетащите только один файл или папку в каждую область."],
    DropInArea => ["Drop your file inside its game, update or keys area.", "Lege die Datei im Bereich für Spiel, Update oder Schlüssel ab.", "Suelta el archivo en la zona de juego, actualización o claves.", "Larga o ficheiro na área do jogo, atualização ou chaves.", "Перетащите файл в область игры, обновления или ключей."],
    PreferenceError => ["Appearance changed, but could not be saved.", "Die Ansicht wurde geändert, konnte aber nicht gespeichert werden.", "El aspecto cambió, pero no se pudo guardar.", "O aspeto foi alterado, mas não foi possível guardá-lo.", "Оформление изменено, но сохранить настройку не удалось."],
    NcaFolder => ["NCA folder", "NCA-Ordner", "Carpeta NCA", "Pasta NCA", "Папка NCA"],
    Files => ["files", "Dateien", "archivos", "ficheiros", "файлов"],
    SingleFile => ["file", "Datei", "archivo", "ficheiro", "файл"],
    FewFiles => ["files", "Dateien", "archivos", "ficheiros", "файла"],
    ExtractionTools => ["Prepare the extraction tools", "Extraktionswerkzeuge vorbereiten", "Preparar herramientas de extracción", "Preparar ferramentas de extração", "Подготовить инструменты извлечения"],
    NativeHelpers => ["Build native helper libraries", "Native Hilfsbibliotheken bauen", "Compilar bibliotecas auxiliares nativas", "Compilar bibliotecas auxiliares nativas", "Собрать вспомогательные библиотеки"],
    LocateLibraries => ["Locate installed development libraries", "Installierte Entwicklungsbibliotheken finden", "Localizar bibliotecas de desarrollo", "Localizar bibliotecas de desenvolvimento", "Найти библиотеки для разработки"],
    WindowAudioControllers => ["Window, audio and controller support", "Fenster, Audio und Controller unterstützen", "Ventana, audio y mandos", "Janela, áudio e comandos", "Поддержка окна, звука и контроллеров"],
    PlayMovies => ["Play the game's movies", "Videos im Spiel abspielen", "Reproducir vídeos del juego", "Reproduzir vídeos do jogo", "Воспроизводить видеоролики игры"],
    LinuxWindowControls => ["Provide the Linux game window controls", "Bedienelemente des Linux-Spielfensters bereitstellen", "Controles de la ventana del juego en Linux", "Controlos da janela do jogo no Linux", "Элементы управления окном игры в Linux"],
    GpuRendering => ["Render the game on your GPU", "Das Spiel auf der Grafikkarte darstellen", "Renderizar el juego con tu GPU", "Renderizar o jogo com a tua GPU", "Отображать игру с помощью видеокарты"],
    CompileShaders => ["Compile Vulkan shaders", "Vulkan-Shader kompilieren", "Compilar sombreadores Vulkan", "Compilar shaders Vulkan", "Компилировать шейдеры Vulkan"],
    GpuMemory => ["Manage GPU memory", "Grafikspeicher verwalten", "Gestionar la memoria de la GPU", "Gerir a memória da GPU", "Управлять памятью видеокарты"],
    BuildTimings => ["Report build timings", "Build-Zeiten erfassen", "Medir tiempos de compilación", "Medir tempos de compilação", "Измерять время сборки"],
    WaylandWindow => ["Open the game in a Wayland desktop session", "Das Spiel unter Wayland öffnen", "Abrir el juego en una sesión Wayland", "Abrir o jogo numa sessão Wayland", "Открывать игру в сеансе Wayland"],
    InstallCltNote => ["Install Apple's Command Line Tools in the system dialog, then retry.", "Installiere Apples Command Line Tools im Systemdialog und versuche es erneut.", "Instala las Command Line Tools de Apple en el diálogo del sistema y vuelve a intentarlo.", "Instala as Command Line Tools da Apple no diálogo do sistema e tenta novamente.", "Установите Command Line Tools от Apple в системном окне и повторите попытку."],
    InstallXcodeNote => ["Install and open Xcode, accept its license, and install the iOS platform. An Apple signing team is needed only for direct device installation.", "Installiere und öffne Xcode, akzeptiere die Lizenz und installiere die iOS-Plattform. Ein Apple-Signierungsteam ist nur zur direkten Geräteinstallation nötig.", "Instala y abre Xcode, acepta su licencia e instala la plataforma iOS. Solo necesitas un equipo de firma de Apple para instalar directamente en el dispositivo.", "Instala e abre o Xcode, aceita a licença e instala a plataforma iOS. Só precisas de uma equipa de assinatura Apple para instalar diretamente no dispositivo.", "Установите и откройте Xcode, примите лицензию и установите платформу iOS. Команда подписи Apple нужна только для прямой установки на устройство."],
    FinishXcodeNote => ["Open Xcode to finish its first-launch setup and license acceptance, then check again.", "Öffne Xcode, schließe die Ersteinrichtung samt Lizenzannahme ab und prüfe erneut.", "Abre Xcode, completa la configuración inicial y acepta la licencia. Después, vuelve a comprobar.", "Abre o Xcode, conclui a configuração inicial e aceita a licença. Depois, verifica novamente.", "Откройте Xcode, завершите начальную настройку и примите лицензию, затем проверьте снова."],
    VmaAurNote => ["Vulkan Memory Allocator headers are available from the community AUR package vulkan-memory-allocator, not the official Arch repositories. Install that package through your trusted AUR workflow, then check again. The installer does not enable foreign repositories.", "Die Vulkan-Memory-Allocator-Header gibt es im Community-AUR-Paket vulkan-memory-allocator, nicht in den offiziellen Arch-Repositories. Installiere es über deinen gewohnten AUR-Weg und prüfe erneut. Der Installer aktiviert keine fremden Repositories.", "Las cabeceras de Vulkan Memory Allocator están en el paquete comunitario AUR vulkan-memory-allocator, no en los repositorios oficiales de Arch. Instálalo con tu método AUR de confianza y vuelve a comprobar. El instalador no activa repositorios externos.", "Os cabeçalhos Vulkan Memory Allocator estão no pacote comunitário AUR vulkan-memory-allocator, não nos repositórios oficiais do Arch. Instala-o pelo teu método AUR de confiança e verifica novamente. O instalador não ativa repositórios externos.", "Заголовки Vulkan Memory Allocator доступны в пакете сообщества AUR vulkan-memory-allocator, а не в официальных репозиториях Arch. Установите его привычным доверенным способом работы с AUR и проверьте снова. Установщик не подключает сторонние репозитории."],
    Gigabytes => ["GB", "GB", "GB", "GB", "ГБ"],
    Megabytes => ["MB", "MB", "MB", "MB", "МБ"],
    Kilobytes => ["KB", "KB", "KB", "KB", "КБ"],
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
    fn russian_and_explicit_ukrainian_fallback_use_the_russian_catalog() {
        for locale in [
            "ru",
            "ru-RU",
            "ru-KZ",
            "RU_by.UTF-8",
            "ru@variant",
            "uk",
            "uk-UA",
            "UK_ua.UTF-8",
        ] {
            assert_eq!(Language::from_locale(locale), Language::Russian, "{locale}");
        }
        for label in Label::ALL {
            assert_eq!(
                Language::from_locale("uk-UA").t(*label),
                Language::Russian.t(*label)
            );
        }
        assert_eq!(Language::Russian.decimal("21.7"), "21,7");
    }

    #[test]
    fn russian_file_counts_have_singular_few_and_many_forms() {
        for (count, expected) in [
            (0, "файлов"),
            (1, "файл"),
            (2, "файла"),
            (4, "файла"),
            (5, "файлов"),
            (11, "файлов"),
            (12, "файлов"),
            (14, "файлов"),
            (21, "файл"),
            (22, "файла"),
            (101, "файл"),
            (111, "файлов"),
        ] {
            assert_eq!(Language::Russian.files(count), expected);
        }
        assert_eq!(Language::Spanish.files(1), "archivo");
        assert_eq!(Language::Spanish.files(2), "archivos");
        assert_eq!(Language::Portuguese.files(1), "ficheiro");
        assert_eq!(Language::Portuguese.files(2), "ficheiros");
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
    fn package_catalog_has_localized_purposes_and_manual_instructions() {
        assert_eq!(
            Language::Russian.dependency_purpose("clang"),
            Some(Language::Russian.t(Label::Compile))
        );
        assert_eq!(
            Language::Russian.dependency_purpose("SDL3"),
            Some(Language::Russian.t(Label::WindowAudioControllers))
        );
        let catalog: serde_json::Value =
            serde_json::from_str(include_str!("../assets/dependencies.json")).unwrap();
        for component in catalog["components"].as_array().unwrap() {
            for language in Language::ALL {
                assert!(
                    !language
                        .dependency_purpose(component["id"].as_str().unwrap())
                        .unwrap()
                        .is_empty()
                );
                if let Some(note) = component["manual_pacman"].as_str() {
                    assert!(language.dependency_note(note).is_some());
                }
            }
        }
    }

    #[test]
    fn every_ui_label_has_all_five_translations() {
        for &label in Label::ALL {
            for language in Language::ALL {
                assert!(!language.t(label).trim().is_empty());
            }
        }
    }
}
