#[cfg(target_os = "macos")]
use crate::drop_target;
use crate::{
    capture::{self, Capture},
    i18n::{Label as L, Language},
    key_paths,
    mod_support::{self, ModEntry},
    platform::{Options, Platform},
    preferences::{self, Appearance},
    sources::{self, Slot, Source},
    style,
};
mod view;
use iced::{Event, Subscription, Task, Theme, event, keyboard, window};
use std::{
    path::PathBuf,
    sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
    },
    time::{Duration, Instant},
};

fn human_size(bytes: u64) -> String {
    if bytes >= 1_000_000_000 {
        format!("{:.1} GB", bytes as f64 / 1e9)
    } else {
        format!("{} MB", bytes.div_ceil(1_000_000))
    }
}

fn redact_home_path(message: &str) -> String {
    let Some(home) = directories::UserDirs::new() else {
        return message.to_owned();
    };
    let raw = home.home_dir().to_string_lossy();
    let forward = raw.replace('\\', "/");
    let backward = raw.replace('/', "\\");
    message
        .replace(raw.as_ref(), "~")
        .replace(&forward, "~")
        .replace(&backward, "~")
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Page {
    Target,
    Keys,
    Game,
    Update,
    Firmware,
    ModsFolder,
    Mods,
    Review,
    Setup,
    Progress,
    Finished,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum BackendStatus {
    Idle,
    Running,
    Passed,
    Failed,
    Stopped,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum InstallTarget {
    Mac,
    Windows,
    Linux,
    Ios,
    Android,
}

impl InstallTarget {
    fn native(host: Platform) -> Self {
        match host {
            Platform::Mac => Self::Mac,
            Platform::Windows => Self::Windows,
            Platform::Linux => Self::Linux,
        }
    }
    fn label(self) -> &'static str {
        match self {
            Self::Mac => "Mac",
            Self::Windows => "Windows",
            Self::Linux => "Linux",
            Self::Ios => "iPad / iPhone",
            Self::Android => "Android",
        }
    }
}

/// The two Windows folders the user can move: where the build runs and where the finished app is installed.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FolderSetting {
    Work,
    Install,
}

impl FolderSetting {
    fn file(self) -> &'static str {
        match self {
            Self::Work => crate::appdir::WORK_FOLDER,
            Self::Install => crate::appdir::INSTALL_FOLDER,
        }
    }
}

#[derive(Debug, Clone)]
pub enum Message {
    ShowInstalledApp,
    ShowGameLibrary,
    IosDelivery(crate::backend::IosDelivery),
    OpenIosDevices,
    OpenIosSigning,
    RefreshIosSigning,
    IosSigningLoaded(u64, Result<Vec<crate::ios_signing::Team>, String>),
    SelectIosTeam(crate::ios_signing::Team),
    IosTeamChanged(String),
    ManualIosTeam,
    OpenXcode,
    XcodeOpened(Result<(), String>),
    RefreshIosDevices,
    SelectIosDevice(String),
    IosDevicesPage(i8),
    IosDevicesLoaded(u64, Result<Vec<crate::ios_devices::Device>, String>),
    IosProfileView(bool),
    ChooseIosProfile,
    IosProfilePicked(
        Option<String>,
        Result<Option<crate::ios_profile::Profile>, String>,
    ),
    NewIosProfile,
    InstallationRevealed(Result<(), String>),
    OpenRepository,
    RepositoryOpened(Result<(), ()>),
    ToggleTheme,
    OpenSettings(bool),
    SelectLanguage(Language),
    SelectTarget(InstallTarget),
    OptimizeCpu(bool),
    BuildOptions(bool),
    ChooseFolder(FolderSetting),
    FolderPicked(FolderSetting, Option<PathBuf>),
    ResetFolder(FolderSetting),
    CleanBuild(bool),
    ExportWithoutData(bool),
    AutoCleanup(bool),
    AnimationFrame(Instant),
    #[cfg(target_os = "macos")]
    LayoutApplied,
    Browse(Slot, bool),
    Picked(Slot, Option<PathBuf>),
    Inspected(Slot, u64, Result<Source, String>),
    InputsRestored(RestoredInputs),
    Hover(Option<Slot>),
    Event(Event),
    Remove(Slot),
    Review,
    Back,
    SkipMods,
    FindFirmware,
    FirmwareFound(u64, Option<Source>),
    ChooseFirmware(bool),
    FirmwarePicked(Option<PathBuf>),
    FirmwareChecked(u64, PathBuf, Result<(), String>),
    RemoveFirmware,
    SkipFirmware,
    Preview,
    RequirementsChecked(u64, Result<crate::dependencies::Plan, String>),
    InstallRequirements,
    SetupTick,
    AutoBuildTick,
    CancelAutoBuild,
    DefenderChecked(Option<bool>),
    RequirementsOpened(Result<(), String>),
    SystemChecked(Result<Vec<(&'static str, String)>, String>),
    UpdateChecked(Result<Option<crate::updates::Release>, String>),
    UpdateInstaller,
    ShowUpdateDetails,
    UpdateDownloaded(Result<PathBuf, String>),
    UpdateApplied(Result<(), String>),
    BackendEvent(u64, crate::backend::Event),
    Tick,
    ToggleDetails,
    DismissNotice,
    ShowNoticeDetails,
    CopyLog,
    OpenLogFolder,
    ExportSave,
    SaveExported(Result<crate::save_export::Export, String>),
    CopyLogLine(usize),
    ClearCopiedLogLine(usize, Instant),
    DemoInput,
    DemoMod,
    CaptureTick,
    CaptureLayout(Option<iced::Size>),
    Captured(window::Screenshot),
    CaptureSaved(Result<PathBuf, String>),
    DragTick,
    ResolvedDrop(Option<Slot>, PathBuf),
    FindKeys,
    KeysFound(u64, Option<Source>),
    RefreshMods,
    ModsScanned(u64, Result<Vec<ModEntry>, String>),
    OpenModsFolder,
    ModsFolderOpened(Result<(), String>),
    ChooseModFolder,
    ModFolderPicked(Option<PathBuf>),
    SelectMod(Option<String>),
}

const AUTO_BUILD_DELAY: Duration = Duration::from_secs(7);

fn cancels_auto_build(message: &Message) -> bool {
    matches!(
        message,
        Message::CancelAutoBuild
            | Message::Back
            | Message::Preview
            | Message::Review
            | Message::BuildOptions(_)
            | Message::Remove(_)
            | Message::SelectMod(_)
            | Message::ChooseModFolder
            | Message::OpenIosSigning
            | Message::OpenIosDevices
            | Message::InstallRequirements
    )
}

#[derive(Debug, Clone, Default)]
pub struct RestoredInputs {
    keys: Option<Source>,
    base: Option<Source>,
    update: Option<Source>,
    mod_folder: Option<PathBuf>,
    firmware: Option<PathBuf>,
    keys_were_saved: bool,
    keys_missing: bool,
    base_missing: bool,
    update_missing: bool,
    mod_folder_missing: bool,
}

pub struct Installer {
    appearance: Appearance,
    base: Option<Source>,
    update: Option<Source>,
    keys: Option<Source>,
    mods: Vec<ModEntry>,
    selected_mod: Option<String>,
    mods_skipped: bool,
    firmware: Option<PathBuf>,
    firmware_pending: Option<u64>,
    firmware_hint: Option<String>,
    mods_folder: Option<PathBuf>,
    chosen_mod_folder: Option<PathBuf>,
    select_imported_mod: bool,
    mods_scan_id: u64,
    mods_scanning: bool,
    pending: [Option<u64>; 3],
    saved_input_missing: [bool; 3],
    sequence: u64,
    hovered: Option<Slot>,
    drag_active: bool,
    notice: Option<String>,
    page: Page,
    tick: u32,
    details: bool,
    capture: Option<Capture>,
    language: Language,
    key_hint: Option<String>,
    log: Vec<String>,
    demo: bool,
    target: InstallTarget,
    portable_cpu: bool,
    clean_build: bool,
    ios_export_no_embed: bool,
    auto_cleanup: bool,
    build_options_open: bool,
    work_folder: Option<PathBuf>,
    install_folder: Option<PathBuf>,
    settings_open: bool,
    cleanup_busy: bool,
    host: Platform,
    simulated_platform: bool,
    motion: crate::motion::ProgressMotion,
    build_progress: crate::progress::BuildProgress,
    last_frame: Option<Instant>,
    backend_status: BackendStatus,
    backend_cancel: Option<Arc<AtomicBool>>,
    backend_run_id: u64,
    backend_failure_detail: Option<String>,
    installed_app: Option<PathBuf>,
    exported_ipa: Option<PathBuf>,
    exported_ipa_size: Option<u64>,
    game_library: Option<PathBuf>,
    ios_delivery: crate::backend::IosDelivery,
    ios_devices: Vec<crate::ios_devices::Device>,
    ios_device: Option<String>,
    ios_devices_open: bool,
    ios_devices_busy: bool,
    ios_devices_generation: u64,
    ios_devices_failed: bool,
    ios_devices_page: usize,
    ios_signing_open: bool,
    ios_signing_busy: bool,
    ios_signing_generation: u64,
    ios_teams: Vec<crate::ios_signing::Team>,
    ios_team: String,
    ios_team_manual: bool,
    ios_signing_failed: bool,
    ios_profile: Option<crate::ios_profile::Profile>,
    ios_profile_open: bool,
    ios_new_profile: Option<String>,
    copied_log_line: Option<(usize, Instant)>,
    requirements: Option<crate::dependencies::Plan>,
    requirements_busy: bool,
    /// The Windows components are being prepared (downloads); the window shows `setup_progress` meanwhile.
    setup_busy: bool,
    auto_build: Option<Instant>,
    setup_progress: crate::components::SetupProgress,
    /// Windows Defender real-time protection (Windows only): the window explains the wait it causes.
    defender: Option<bool>,
    available_update: Option<crate::updates::Release>,
    updating: bool,
    update_confirmation: bool,
    info_notice: bool,
    setup_log_length: usize,
    requirements_run_id: u64,
    /// The last Install tools failure, shown as a card until the next attempt or check.
    setup_failure: Option<SetupFailure>,
    /// The setup output already copied into the session log, and the step that was last announced there.
    setup_streamed: Vec<String>,
    setup_step_logged: (u32, String, String),
}

#[derive(Debug, Clone, PartialEq)]
struct SetupFailure {
    step: String,
    error: String,
}

/// The lines of `current` that `previous` does not contain: the output is a window of the last lines, so the tail of
/// `previous` can have scrolled out and the longest overlap with the start of `current` is the part seen before.
fn unseen_lines<'a>(previous: &[String], current: &'a [String]) -> &'a [String] {
    let most = previous.len().min(current.len());
    let overlap = (0..=most)
        .rev()
        .find(|&n| previous[previous.len() - n..] == current[..n])
        .unwrap_or(0);
    &current[overlap..]
}

impl Page {
    fn is_input(self) -> bool {
        matches!(self, Self::Keys | Self::Game | Self::Update)
    }
}

fn restore_inputs(saved: preferences::SavedPaths, language: Language) -> RestoredInputs {
    let (base, base_missing) = restore_source(saved.base, Slot::Base, language);
    let (update, update_missing) = restore_source(saved.update, Slot::Update, language);
    let (saved_keys, keys_missing) = restore_source(saved.keys, Slot::Keys, language);
    let keys_were_saved = saved_keys.is_some();
    let keys = saved_keys.or_else(|| key_paths::find(language));
    let mod_folder = saved.mod_folder.clone().filter(|path| path.is_dir());
    let mod_folder_missing = saved.mod_folder.is_some() && mod_folder.is_none();
    RestoredInputs {
        firmware: saved.firmware.filter(|p| p.exists()),
        keys,
        base,
        update,
        mod_folder,
        keys_were_saved,
        keys_missing,
        base_missing,
        update_missing,
        mod_folder_missing,
    }
}

fn restore_source(path: Option<PathBuf>, slot: Slot, language: Language) -> (Option<Source>, bool) {
    let Some(path) = path else {
        return (None, false);
    };
    match sources::inspect(path, slot, language) {
        Ok(source) => (Some(source), false),
        Err(_) => (None, true),
    }
}

fn localized_plan_description(plan: &crate::dependencies::Plan, language: Language) -> String {
    let mut lines: Vec<String> = plan
        .missing
        .iter()
        .map(|item| {
            format!(
                "{}: {}",
                item.id,
                language
                    .dependency_purpose(&item.id)
                    .unwrap_or(&item.purpose)
            )
        })
        .collect();
    lines.extend(
        plan.fetch
            .iter()
            .map(|id| format!("{id}: {}", language.t(L::PinnedDownload))),
    );
    lines.extend(
        plan.manual
            .iter()
            .map(|note| language.dependency_note(note).unwrap_or(note).to_owned()),
    );
    if !plan.packages.is_empty() {
        lines.push(format!("{}: {}", plan.manager, plan.packages.join(", ")));
    }
    lines.join("\n")
}

fn disk_space_error(detail: &str, language: Language) -> Option<String> {
    let line = detail
        .lines()
        .find(|line| line.contains("Disk space >= "))?;
    let required = line
        .split_once("Disk space >= ")?
        .1
        .split_whitespace()
        .next()?;
    let available = line.split_once('(')?.1.split_once(" GB free")?.0;
    let valid_number = |value: &str| {
        !value.is_empty()
            && value
                .chars()
                .all(|character| character.is_ascii_digit() || character == '.')
    };
    if !valid_number(required) || !valid_number(available) {
        return None;
    }
    let available = language.decimal(available);
    Some(
        language
            .t(L::DiskSpaceError)
            .replace("{available}", &available)
            .replace("{required}", &language.decimal(required)),
    )
}

fn build_error_notice(detail: &str, language: Language, exporting: bool) -> String {
    if detail.contains("Build step failed: signing")
        || detail.to_lowercase().contains("signing team")
        || detail.contains("No signing certificate")
        || detail.contains("No profiles for")
    {
        return format!(
            "{}\n\n{}\n\n{}",
            language.t(L::SigningSetup),
            language.t(L::SigningHelp),
            detail
        );
    }
    if detail.contains("Prerequisite checker internal error:") {
        return language.t(L::PrerequisiteInternalError).into();
    }
    if let Some(failure) = detail.strip_prefix("Build step failed: ")
        && let Some((stage, cause)) = failure.split_once('\n')
    {
        let label = match crate::progress::Stage::from_id(stage) {
            Some(crate::progress::Stage::Source) => L::FetchSource,
            Some(crate::progress::Stage::Requirements) => L::Tools,
            Some(crate::progress::Stage::Firmware) => L::Firmware,
            Some(crate::progress::Stage::Extract) => L::Prepare,
            Some(crate::progress::Stage::Exefs) => L::ExeFS,
            Some(crate::progress::Stage::Signing) => L::VerifySigning,
            Some(crate::progress::Stage::Shaders) => L::PrepareShaders,
            Some(crate::progress::Stage::Generate) => L::Generate,
            Some(crate::progress::Stage::Compile) => L::Compile,
            Some(crate::progress::Stage::Images) => L::Images,
            Some(crate::progress::Stage::Runtime) => L::Runtime,
            Some(crate::progress::Stage::Package) => L::Package,
            Some(crate::progress::Stage::Install) => {
                if exporting {
                    L::ExportOutput
                } else {
                    L::Install
                }
            }
            None => return detail.into(),
        };
        return language
            .t(L::BuildStepError)
            .replace("{stage}", language.t(label))
            .replace("{cause}", cause);
    }
    disk_space_error(detail, language).unwrap_or_else(|| detail.into())
}

/// Runs a blocking job off the UI thread; a job that panics becomes an `Err` for the message handler.
async fn blocking<T: Send + 'static>(
    job: impl FnOnce() -> Result<T, String> + Send + 'static,
) -> Result<T, String> {
    tokio::task::spawn_blocking(job)
        .await
        .unwrap_or_else(|e| Err(e.to_string()))
}

impl Installer {
    /// Forgets the selected iOS signing profile and closes its dialog.
    fn clear_ios_profile(&mut self) {
        self.ios_profile = None;
        self.ios_new_profile = None;
        self.ios_profile_open = false;
    }

    fn resolve_ios_profile(&mut self) {
        if self.target != InstallTarget::Ios
            || self.ios_profile.is_some()
            || self.ios_new_profile.is_some()
        {
            return;
        }
        if let Some(name) = &self.selected_mod {
            match crate::ios_profile::load() {
                Ok(profiles) => {
                    self.ios_profile = crate::ios_profile::matching(&profiles, name).cloned();
                    if self.ios_profile.is_none() && self.ios_new_profile.is_none() {
                        self.ios_new_profile = Some(crate::ios_profile::new_id());
                    }
                }
                Err(cause) => {
                    self.notice = Some(
                        self.language
                            .t(L::ProfileReadError)
                            .replace("{cause}", &cause),
                    );
                }
            }
        }
    }

    #[cfg(test)]
    pub fn new() -> (Self, Task<Message>) {
        Self::with_options(Options::default())
    }

    pub fn with_options(options: Options) -> (Self, Task<Message>) {
        let host = options.platform.unwrap_or_else(Platform::native);
        let demo = options.demo;
        let capturing = options.capture.is_some();
        let capture = options
            .capture
            .map(|path| Capture::new(path, options.scenes));
        let mut app = Self {
            appearance: if capture.is_some() {
                Appearance::Dark
            } else {
                preferences::load()
            },
            base: None,
            update: None,
            keys: None,
            mods: Vec::new(),
            selected_mod: std::env::var("BDSP_MOD").ok().filter(|name| {
                !name.is_empty()
                    && !name.eq_ignore_ascii_case("none")
                    && !name.eq_ignore_ascii_case("diamond")
            }),
            mods_skipped: false,
            firmware: None,
            firmware_pending: None,
            firmware_hint: None,
            mods_folder: mod_support::folder_for(host, InstallTarget::native(host)),
            chosen_mod_folder: None,
            select_imported_mod: false,
            mods_scan_id: 0,
            mods_scanning: false,
            pending: [None; 3],
            saved_input_missing: [false; 3],
            sequence: 0,
            hovered: None,
            drag_active: false,
            notice: None,
            page: Page::Target,
            tick: 0,
            details: false,
            capture,
            language: if capturing {
                Language::detect()
            } else {
                Language::startup()
            },
            key_hint: None,
            log: Vec::new(),
            demo,
            target: InstallTarget::native(host),
            portable_cpu: false,
            clean_build: false,
            ios_export_no_embed: false,
            auto_cleanup: true,
            build_options_open: false,
            work_folder: stored_folder(host, FolderSetting::Work),
            install_folder: stored_folder(host, FolderSetting::Install),
            settings_open: false,
            cleanup_busy: false,
            host,
            simulated_platform: options.platform.is_some(),
            motion: crate::motion::ProgressMotion::default(),
            build_progress: crate::progress::BuildProgress::default(),
            last_frame: None,
            backend_status: BackendStatus::Idle,
            backend_cancel: None,
            backend_run_id: 0,
            backend_failure_detail: None,
            installed_app: None,
            exported_ipa: None,
            exported_ipa_size: None,
            game_library: None,
            ios_delivery: crate::backend::IosDelivery::Ipa,
            ios_devices: Vec::new(),
            ios_device: None,
            ios_devices_open: false,
            ios_devices_busy: false,
            ios_devices_generation: 0,
            ios_devices_failed: false,
            ios_devices_page: 0,
            ios_signing_open: false,
            ios_signing_busy: false,
            ios_signing_generation: 0,
            ios_teams: Vec::new(),
            ios_team: preferences::load_signing_team().unwrap_or_default(),
            ios_team_manual: false,
            ios_signing_failed: false,
            ios_profile: None,
            ios_profile_open: false,
            ios_new_profile: None,
            copied_log_line: None,
            requirements: None,
            requirements_busy: false,
            setup_busy: false,
            auto_build: None,
            setup_progress: Default::default(),
            defender: None,
            available_update: None,
            updating: false,
            update_confirmation: false,
            info_notice: false,
            setup_log_length: 0,
            requirements_run_id: 0,
            setup_failure: None,
            setup_streamed: Vec::new(),
            setup_step_logged: Default::default(),
        };
        app.record_system_header();
        if demo {
            app.keys = Some(Source::fixture("prod.keys", app.language.t(L::DemoData)));
            app.base = Some(Source::fixture(
                app.language.t(L::DemoGameFile),
                app.language.t(L::DemoData),
            ));
            app.update = Some(Source::fixture(
                app.language.t(L::DemoUpdateFile),
                app.language.t(L::DemoData),
            ));
        }
        let task = if app.capture.is_some() {
            app.capture_scenario()
        } else if !app.demo {
            let saved = preferences::load_paths();
            let language = app.language;
            Task::perform(
                async move {
                    tokio::task::spawn_blocking(move || restore_inputs(saved, language))
                        .await
                        .unwrap_or_default()
                },
                Message::InputsRestored,
            )
        } else {
            if let Some(mode) = std::env::var_os("BDSP_DEMO_AUTO_START") {
                if mode == "light" {
                    app.appearance = Appearance::Light;
                }
                app.page = Page::Setup;
                app.auto_build = Some(Instant::now());
            }
            Task::none()
        };
        let task = if !app.demo && app.capture.is_none() {
            let data = crate::appdir::data_dir();
            Task::batch([
                task,
                Task::perform(
                    blocking(move || Ok(crate::sysinfo::probe("native", data))),
                    Message::SystemChecked,
                ),
                Task::perform(blocking(crate::updates::check), Message::UpdateChecked),
                Task::perform(
                    blocking(|| Ok::<_, String>(crate::defender::realtime_protection())),
                    |state| Message::DefenderChecked(state.ok().flatten()),
                ),
            ])
        } else {
            task
        };
        (app, task)
    }

    pub fn theme(&self) -> Theme {
        style::theme(self.appearance)
    }

    pub fn subscription(&self) -> Subscription<Message> {
        let events = event::listen().map(Message::Event);
        if self.capture.is_some() {
            Subscription::batch([
                events,
                iced::time::every(Duration::from_millis(900)).map(|_| Message::CaptureTick),
            ])
        } else if self.page == Page::Progress {
            let mut subscriptions = vec![events, window::frames().map(Message::AnimationFrame)];
            if self.demo || self.backend_status == BackendStatus::Idle {
                subscriptions
                    .push(iced::time::every(Duration::from_millis(400)).map(|_| Message::Tick));
            }
            Subscription::batch(subscriptions)
        } else if self.auto_build.is_some() {
            Subscription::batch([events, window::frames().map(|_| Message::AutoBuildTick)])
        } else if self.setup_busy {
            Subscription::batch([
                events,
                iced::time::every(Duration::from_millis(300)).map(|_| Message::SetupTick),
            ])
        } else if self.drag_active {
            Subscription::batch([
                events,
                iced::time::every(Duration::from_millis(40)).map(|_| Message::DragTick),
            ])
        } else {
            events
        }
    }

    pub fn update(&mut self, message: Message) -> Task<Message> {
        let previous = self.preferred_size();
        if self.auto_build.is_some() && cancels_auto_build(&message) {
            self.cancel_auto_build("cancelled by the user");
        }
        let task = self.handle(message);
        if self.capture.is_none() && self.preferred_size() != previous {
            Task::batch([task, self.fit_window()])
        } else {
            task
        }
    }

    fn handle(&mut self, message: Message) -> Task<Message> {
        if let Message::BackendEvent(run_id, _) = &message
            && *run_id == self.backend_run_id
        {
            self.build_progress.touch(Instant::now());
        }
        match message {
            Message::UpdateChecked(result) => match result {
                Ok(release) => {
                    self.available_update = release;
                    // Ask right away, so nobody stays on an old installer by never clicking the header button.
                    if self.available_update.is_some()
                        && self.notice.is_none()
                        && !self.updating
                        && self.backend_status != BackendStatus::Running
                    {
                        return self.handle(Message::ShowUpdateDetails);
                    }
                }
                Err(error) => self.record("UPDATE", &error),
            },
            Message::ShowUpdateDetails => {
                if let Some(release) = &self.available_update {
                    self.update_confirmation = true;
                    self.notice = Some(format!(
                        "{} \u{2192} {}\n{}",
                        env!("CARGO_PKG_VERSION"),
                        release.version,
                        self.language.t(L::UpdateRestartHint)
                    ));
                }
            }
            Message::UpdateInstaller
                if self.backend_status != BackendStatus::Running && !self.updating =>
            {
                if let Some(release) = self.available_update.clone() {
                    self.notice = None;
                    self.update_confirmation = false;
                    self.updating = true;
                    self.record("UPDATE", "Downloading the verified installer update. The app will restart when ready.");
                    return Task::perform(
                        blocking(move || crate::updates::download(&release)),
                        Message::UpdateDownloaded,
                    );
                }
            }
            Message::UpdateDownloaded(result) => match result {
                Ok(path) => {
                    return Task::perform(
                        blocking(move || crate::updates::apply(&path)),
                        Message::UpdateApplied,
                    );
                }
                Err(error) => {
                    self.updating = false;
                    self.notice = Some(error);
                }
            },
            Message::UpdateApplied(result) => {
                self.updating = false;
                match result {
                    Ok(()) => return iced::exit(),
                    Err(error) => self.notice = Some(error),
                }
            }
            Message::RequirementsChecked(run_id, result)
                if run_id == self.requirements_run_id && self.page == Page::Setup =>
            {
                self.requirements_busy = false;
                self.stream_terminal_log();
                self.setup_failure = None;
                match result {
                    Ok(plan) if plan.ready() => {
                        self.requirements = Some(plan);
                        return self.handle(Message::Preview);
                    }
                    Ok(plan) => {
                        for line in plan.log_lines() {
                            self.record("SETUP", &line);
                        }
                        self.requirements = Some(plan);
                    }
                    Err(error) => self.notice = Some(error),
                }
            }
            Message::SetupTick => {
                if self.setup_busy {
                    self.setup_progress = crate::components::setup_progress();
                    self.stream_setup_progress();
                }
            }
            Message::AutoBuildTick => {
                let Some(started) = self.auto_build else {
                    return Task::none();
                };
                if self.page != Page::Setup || self.requirements.is_some() || self.setup_busy {
                    self.cancel_auto_build("the setup page changed");
                } else if started.elapsed() >= AUTO_BUILD_DELAY {
                    self.auto_build = None;
                    self.record("AUTO", "Build started automatically after the countdown.");
                    return self.handle(Message::Preview);
                }
            }
            Message::CancelAutoBuild => {}
            Message::SystemChecked(result) => match result {
                Ok(lines) => {
                    for (step, line) in lines {
                        self.record(step, &redact_home_path(&line));
                    }
                }
                Err(error) => self.record("SYSTEM", &format!("Probe failed: {error}")),
            },
            Message::DefenderChecked(state) => self.defender = state,
            Message::InstallRequirements => {
                if self.setup_busy {
                    return Task::none();
                }
                self.setup_log_length = 0;
                self.setup_failure = None;
                if let Some(plan) = self.requirements.clone() {
                    self.record(
                        "SETUP",
                        &format!("Install tools started ({}).", plan.manager),
                    );
                    if plan.manager == "windows-components" {
                        self.setup_streamed.clear();
                        self.setup_step_logged = Default::default();
                        crate::components::reset_setup_progress();
                        self.setup_progress = crate::components::setup_progress();
                        self.setup_busy = true;
                    }
                    return Task::perform(
                        blocking(move || crate::dependencies::install(&plan)),
                        Message::RequirementsOpened,
                    );
                }
            }
            Message::RequirementsOpened(result) => {
                let components = self
                    .requirements
                    .as_ref()
                    .is_some_and(|plan| plan.manager == "windows-components");
                self.setup_busy = false;
                match result {
                    Ok(()) if components => {
                        self.record("SETUP", "The build environment is ready.");
                        self.requirements = None;
                        self.start_auto_build();
                    }
                    Ok(()) => {
                        let terminal = self
                            .requirements
                            .as_ref()
                            .is_none_or(crate::dependencies::needs_terminal);
                        self.record(
                            "SETUP",
                            if terminal {
                                "Complete the installation in the terminal, then check again here."
                            } else {
                                "The pinned download was verified and stored. Check again here."
                            },
                        );
                        self.requirements = None;
                        if !terminal {
                            self.start_auto_build();
                        }
                    }
                    Err(error) => self.fail_setup(crate::components::setup_progress(), &error),
                }
            }
            Message::InputsRestored(restored) => {
                self.firmware = restored.firmware;
                let keys_restored = restored.keys.is_some();
                self.saved_input_missing = [
                    restored.base_missing,
                    restored.update_missing,
                    restored.keys_missing && !keys_restored,
                ];
                self.keys = restored.keys;
                self.base = restored.base;
                self.update = restored.update;
                self.chosen_mod_folder = restored.mod_folder.clone();
                if let Some(folder) = restored.mod_folder {
                    if let Ok(library) = mod_support::library_for_selection(&folder) {
                        self.mods_folder = Some(library);
                    }
                    self.record("Mods", "Restored the previously selected mod folder.");
                } else if restored.mod_folder_missing {
                    self.record("Mods", self.language.t(L::SavedModFolderMissing));
                }
                if self.keys.is_some() && restored.keys_were_saved {
                    self.key_hint = Some(self.language.t(L::KeysRestored).into());
                    self.record("Keys", self.language.t(L::KeysRestored));
                } else {
                    if restored.keys_missing {
                        self.record("Keys", self.language.t(L::SavedInputMissing));
                    }
                    self.record("Keys", self.language.t(L::LogSearch));
                    if self.keys.is_some() {
                        self.key_hint = Some(self.language.t(L::FoundKeys).into());
                        self.record("Keys", self.language.t(L::FoundKeys));
                        let source = self.keys.clone();
                        self.save_source_preference(Slot::Keys, source.as_ref());
                    } else {
                        self.key_hint = Some(self.language.t(L::NoKeys).into());
                        self.record("Keys", self.language.t(L::NoKeys));
                    }
                }
                if restored.base_missing || restored.update_missing {
                    self.record("Files", self.language.t(L::SavedInputMissing));
                }
            }
            Message::DismissNotice => {
                self.notice = None;
                self.update_confirmation = false;
                self.info_notice = false;
            }
            Message::ShowNoticeDetails => {
                self.notice = None;
                self.details = true;
            }
            Message::ShowInstalledApp | Message::ShowGameLibrary
                if self.backend_status == BackendStatus::Passed =>
            {
                let path = if matches!(message, Message::ShowGameLibrary) {
                    self.game_library.clone()
                } else {
                    self.exported_ipa
                        .clone()
                        .or_else(|| self.installed_app.clone())
                };
                if let Some(path) = path {
                    return Task::perform(
                        blocking(move || crate::backend::reveal_installed_application(path)),
                        Message::InstallationRevealed,
                    );
                }
            }
            Message::InstallationRevealed(Err(error)) => {
                self.record("ERROR", &error);
                self.notice = Some(self.language.t(L::ShowInstallationFailed).into());
            }
            Message::InstallationRevealed(Ok(())) => {}
            Message::OpenRepository => {
                return Task::perform(
                    async {
                        tokio::task::spawn_blocking(crate::project_link::open)
                            .await
                            .unwrap_or(Err(()))
                    },
                    Message::RepositoryOpened,
                );
            }
            Message::RepositoryOpened(Err(())) => {
                self.notice = Some(self.language.t(L::RepositoryError).into());
                self.record("GitHub", self.language.t(L::RepositoryError));
            }
            Message::SelectTarget(target)
                if self.page == Page::Target
                    && self.targets().contains(&target)
                    && target != InstallTarget::Android =>
            {
                self.target = target;
                self.setup_failure = None;
                self.record("SYSTEM", &format!("Selected target: {}", target.label()));
                self.mods_skipped = false;
                self.mods_folder = mod_support::folder_for(self.host, target);
                self.chosen_mod_folder = None;
                self.select_imported_mod = false;
                self.mods.clear();
                self.selected_mod = None;
                self.clear_ios_profile();
                self.mods_scan_id += 1;
                self.mods_scanning = false;
            }
            Message::BuildOptions(open) if self.page == Page::Setup => {
                self.build_options_open = open;
            }
            Message::OpenIosSigning
                if self.host == Platform::Mac
                    && self.target == InstallTarget::Ios
                    && matches!(self.page, Page::Target | Page::Setup) =>
            {
                self.ios_devices_open = false;
                self.ios_signing_open = true;
                return self.handle(Message::RefreshIosSigning);
            }
            Message::RefreshIosSigning if self.ios_signing_open && !self.ios_signing_busy => {
                self.ios_signing_busy = true;
                self.ios_signing_failed = false;
                self.ios_signing_generation += 1;
                let generation = self.ios_signing_generation;
                return Task::perform(crate::ios_signing::scan(), move |result| {
                    Message::IosSigningLoaded(generation, result)
                });
            }
            Message::IosSigningLoaded(generation, result)
                if generation == self.ios_signing_generation =>
            {
                self.ios_signing_busy = false;
                match result {
                    Ok(teams) => {
                        if self.ios_team.is_empty() && teams.len() == 1 {
                            self.ios_team = teams[0].id.clone();
                        }
                        self.ios_teams = teams;
                    }
                    Err(cause) => {
                        self.ios_signing_failed = true;
                        self.record("SIGNING", &cause);
                    }
                }
            }
            Message::SelectIosTeam(team) if self.ios_signing_open => {
                if self.ios_teams.contains(&team) {
                    self.ios_team = team.id;
                }
            }
            Message::IosTeamChanged(id) if self.ios_signing_open => {
                self.ios_team = id.trim().to_ascii_uppercase();
            }
            Message::ManualIosTeam if self.ios_signing_open => {
                let manual = self.ios_team_manual
                    || !self.ios_teams.iter().any(|team| team.id == self.ios_team);
                self.ios_team_manual = !manual;
                if manual && !self.ios_teams.iter().any(|team| team.id == self.ios_team) {
                    self.ios_team = if self.ios_teams.len() == 1 {
                        self.ios_teams[0].id.clone()
                    } else {
                        String::new()
                    };
                }
            }
            Message::OpenXcode if self.ios_signing_open => {
                return Task::perform(
                    async {
                        tokio::process::Command::new("/usr/bin/open")
                            .args(["-a", "Xcode"])
                            .status()
                            .await
                            .map_err(|e| e.to_string())?
                            .success()
                            .then_some(())
                            .ok_or_else(|| "Could not open Xcode.".into())
                    },
                    Message::XcodeOpened,
                );
            }
            Message::XcodeOpened(Err(_)) => {
                self.notice = Some(self.language.t(L::SigningHelp).into());
            }
            Message::OpenIosDevices
                if self.host == Platform::Mac
                    && self.target == InstallTarget::Ios
                    && matches!(self.page, Page::Target | Page::Setup) =>
            {
                self.ios_devices_open = true;
                return self.handle(Message::RefreshIosDevices);
            }
            Message::RefreshIosDevices if self.ios_devices_open && !self.ios_devices_busy => {
                self.ios_devices_busy = true;
                self.ios_devices_failed = false;
                self.ios_devices_generation += 1;
                let generation = self.ios_devices_generation;
                let selected = self.ios_device.clone();
                return Task::perform(crate::ios_devices::scan(selected), move |result| {
                    Message::IosDevicesLoaded(generation, result)
                });
            }
            Message::IosDevicesLoaded(generation, result)
                if generation == self.ios_devices_generation =>
            {
                self.ios_devices_busy = false;
                match result {
                    Ok(devices) => {
                        self.ios_device =
                            crate::ios_devices::choose(&devices, self.ios_device.as_deref());
                        self.ios_devices = devices;
                        self.ios_devices_page = self
                            .ios_devices_page
                            .min(self.ios_devices.len().saturating_sub(1) / 3);
                    }
                    Err(cause) => {
                        self.ios_devices_failed = true;
                        // A failed scan must never leave stale devices marked as connected.
                        for device in &mut self.ios_devices {
                            device.connected = false;
                        }
                        self.record("DEVICE", &cause);
                    }
                }
            }
            Message::IosDevicesPage(delta) if self.ios_devices_open => {
                let last = self.ios_devices.len().saturating_sub(1) / 3;
                self.ios_devices_page = self
                    .ios_devices_page
                    .saturating_add_signed(delta as isize)
                    .min(last);
            }
            Message::SelectIosDevice(id) if self.ios_devices_open && !self.ios_devices_busy => {
                if let Some(device) = self.ios_devices.iter().find(|d| d.id == id) {
                    let connected = device.connected;
                    self.ios_device = Some(id);
                    if !connected {
                        return self.handle(Message::RefreshIosDevices);
                    }
                }
            }
            Message::IosDelivery(delivery)
                if self.page == Page::Target && self.target == InstallTarget::Ios =>
            {
                self.ios_delivery = delivery;
                self.ios_profile = None;
                self.ios_new_profile = None;
            }
            Message::IosProfileView(open) if self.page == Page::Review => {
                self.ios_profile_open = open;
            }
            Message::NewIosProfile if self.page == Page::Review => {
                self.ios_profile = None;
                self.ios_new_profile = Some(crate::ios_profile::new_id());
            }
            Message::ChooseIosProfile
                if self.page == Page::Review
                    && self.target == InstallTarget::Ios
                    && self.host == Platform::Mac =>
            {
                let selection = self.selected_mod.clone();
                return Task::perform(
                    async {
                        let mut dialog =
                            rfd::AsyncFileDialog::new().add_filter("iPhone / iPad", &["ipa"]);
                        if let Ok(data) = crate::workspace::data_dir() {
                            dialog = dialog.set_directory(data.join("exports/ios"));
                        }
                        let Some(file) = dialog.pick_file().await else {
                            return Ok(None);
                        };
                        let path = file.path().to_path_buf();
                        tokio::task::spawn_blocking(move || {
                            crate::ios_profile::read_ipa(&path).map(Some)
                        })
                        .await
                        .map_err(|e| e.to_string())?
                    },
                    move |result| Message::IosProfilePicked(selection.clone(), result),
                );
            }
            Message::IosProfilePicked(selection, result)
                if self.page == Page::Review
                    && self.target == InstallTarget::Ios
                    && selection == self.selected_mod =>
            {
                match result {
                    Ok(Some(profile)) => self.ios_profile = Some(profile),
                    Ok(None) => {}
                    Err(cause) => {
                        self.notice = Some(
                            self.language
                                .t(L::ProfileReadError)
                                .replace("{cause}", &cause),
                        )
                    }
                }
            }
            Message::ChooseFolder(setting)
                if self.host == Platform::Windows
                    && self.page == Page::Setup
                    && self.build_options_open =>
            {
                let current = match setting {
                    FolderSetting::Work => self.work_folder.clone(),
                    FolderSetting::Install => self.install_folder.clone(),
                };
                return Task::perform(
                    async move {
                        let picker = rfd::AsyncFileDialog::new();
                        let picker =
                            current.map_or(picker.clone(), |path| picker.set_directory(path));
                        picker
                            .pick_folder()
                            .await
                            .map(|folder| folder.path().to_path_buf())
                    },
                    move |folder| Message::FolderPicked(setting, folder),
                );
            }
            Message::FolderPicked(setting, Some(path))
                if self.host == Platform::Windows && self.page == Page::Setup =>
            {
                self.set_folder(setting, Some(path));
            }
            Message::ResetFolder(setting)
                if self.host == Platform::Windows && self.page == Page::Setup =>
            {
                self.set_folder(setting, None);
            }
            Message::CleanBuild(enabled) if self.page == Page::Setup => {
                self.clean_build = enabled;
            }
            Message::ExportWithoutData(enabled) if self.page == Page::Review => {
                self.ios_export_no_embed = enabled;
            }
            Message::AutoCleanup(enabled) if self.page == Page::Setup => {
                self.auto_cleanup = enabled;
            }
            Message::OptimizeCpu(enabled)
                if self.page == Page::Review && self.target == InstallTarget::Linux =>
            {
                self.portable_cpu = !enabled;
            }
            Message::AnimationFrame(now) if self.page == Page::Progress => {
                let dt = self
                    .last_frame
                    .map(|last| now.saturating_duration_since(last).as_secs_f32())
                    .unwrap_or(1.0 / 60.0);
                self.last_frame = Some(now);
                let target = if self.demo
                    || (self.capture.is_some() && self.backend_status == BackendStatus::Idle)
                {
                    let stages = self.build_stages();
                    stages[((self.tick / 10) as usize).min(stages.len() - 1)].index() as f32
                        + (self.tick % 10) as f32 / 10.0
                } else {
                    let stage = self.build_progress.active;
                    stage.index() as f32 + self.build_progress.fraction(stage)
                };
                self.motion.advance(target, dt);
            }
            Message::Event(Event::Window(window::Event::Opened { .. })) => {
                return if self.capture.is_some() {
                    self.capture_scenario()
                } else {
                    self.fit_window()
                };
            }
            Message::DemoInput if self.demo && self.page.is_input() => {
                let (slot, name) = match self.page {
                    Page::Keys => (Slot::Keys, "prod.keys"),
                    Page::Game => (Slot::Base, self.language.t(L::DemoGameFile)),
                    _ => (Slot::Update, self.language.t(L::DemoUpdateFile)),
                };
                *self.source_mut(slot) = Some(Source::fixture(name, self.language.t(L::DemoData)));
            }
            Message::DemoMod if self.demo && self.page == Page::Mods => {
                self.mods = vec![ModEntry {
                    name: "Luminescent Platinum".into(),
                    root: PathBuf::from("Example/Luminescent Platinum"),
                    has_romfs: true,
                    has_exefs: true,
                }];
            }
            Message::FindKeys if self.demo => return self.handle(Message::DemoInput),
            Message::RefreshMods
                if matches!(self.page, Page::ModsFolder | Page::Mods) && self.capture.is_none() =>
            {
                let Some(folder) = self.mods_folder.clone() else {
                    self.notice = Some(self.language.t(L::ModsFolderUnavailable).into());
                    return Task::none();
                };
                let chosen = self.chosen_mod_folder.clone();
                self.mods_scan_id += 1;
                let scan_id = self.mods_scan_id;
                self.mods_scanning = true;
                return Task::perform(
                    blocking(move || match chosen {
                        Some(path) => mod_support::scan_selected(&path),
                        None => mod_support::scan(&folder),
                    }),
                    move |result| Message::ModsScanned(scan_id, result),
                );
            }
            Message::ModsScanned(scan_id, result) if scan_id == self.mods_scan_id => {
                self.mods_scanning = false;
                match result {
                    Ok(mods) => {
                        if self.select_imported_mod && mods.len() == 1 {
                            self.selected_mod = Some(mods[0].name.clone());
                        }
                        self.mods = mods;
                        self.resolve_ios_profile();
                        if self
                            .selected_mod
                            .as_ref()
                            .is_some_and(|name| !self.mods.iter().any(|item| &item.name == name))
                        {
                            self.selected_mod = None;
                            self.clear_ios_profile();
                        }
                        self.notice = None;
                    }
                    Err(error) => self.notice = Some(error),
                }
                self.select_imported_mod = false;
            }
            Message::OpenModsFolder if matches!(self.page, Page::ModsFolder | Page::Mods) => {
                let Some(folder) = self
                    .chosen_mod_folder
                    .clone()
                    .or_else(|| self.mods_folder.clone())
                else {
                    self.notice = Some(self.language.t(L::ModsFolderUnavailable).into());
                    return Task::none();
                };
                return Task::perform(
                    blocking(move || mod_support::open_folder(&folder)),
                    Message::ModsFolderOpened,
                );
            }
            Message::ModsFolderOpened(result) => match result {
                Ok(()) => return self.handle(Message::RefreshMods),
                Err(error) => self.notice = Some(error),
            },
            Message::ChooseModFolder if matches!(self.page, Page::ModsFolder | Page::Mods) => {
                let start = preferences::load_paths()
                    .last_directory
                    .filter(|path| path.is_dir());
                return Task::perform(
                    async move {
                        let picker = rfd::AsyncFileDialog::new();
                        let picker =
                            start.map_or(picker.clone(), |path| picker.set_directory(path));
                        picker
                            .pick_folder()
                            .await
                            .map(|folder| folder.path().to_path_buf())
                    },
                    Message::ModFolderPicked,
                );
            }
            Message::ModFolderPicked(Some(path))
                if matches!(self.page, Page::ModsFolder | Page::Mods) =>
            {
                let library = match mod_support::library_for_selection(&path) {
                    Ok(library) => library,
                    Err(error) => {
                        self.notice = Some(error);
                        return Task::none();
                    }
                };
                self.mods_folder = Some(library);
                if self.persist_preferences() && preferences::save_mod_folder(&path).is_err() {
                    self.notice = Some(self.language.t(L::PreferenceError).into());
                }
                self.chosen_mod_folder = Some(path);
                self.select_imported_mod = true;
                self.mods.clear();
                self.selected_mod = None;
                self.clear_ios_profile();
                return self.handle(Message::RefreshMods);
            }
            Message::SelectMod(selection) if self.page == Page::Mods => {
                if selection != self.selected_mod {
                    self.clear_ios_profile();
                }
                if selection
                    .as_ref()
                    .is_none_or(|name| self.mods.iter().any(|item| &item.name == name))
                {
                    self.selected_mod = selection;
                    self.resolve_ios_profile();
                    self.notice = None;
                }
            }
            Message::OpenSettings(open) => self.settings_open = open,
            Message::SelectLanguage(language) => {
                self.language = language;
                if self.capture.is_none() && preferences::save_language(language).is_err() {
                    self.notice = Some(self.language.t(L::PreferenceError).into());
                }
            }
            Message::Back if self.settings_open => self.settings_open = false,
            Message::ToggleTheme => {
                self.appearance = match self.appearance {
                    Appearance::Dark => Appearance::Light,
                    Appearance::Light => Appearance::Dark,
                };
                if self.capture.is_none() && preferences::save(self.appearance).is_err() {
                    self.notice = Some(self.language.t(L::PreferenceError).into());
                }
            }
            Message::Browse(slot, folder) if self.page.is_input() => {
                let language = self.language;
                let start = preferences::load_paths()
                    .last_directory
                    .filter(|path| path.is_dir());
                return Task::perform(
                    async move {
                        let picker = rfd::AsyncFileDialog::new().set_title(match slot {
                            Slot::Base => language.t(L::Base),
                            Slot::Update => language.t(L::Update),
                            Slot::Keys => "prod.keys",
                        });
                        let picker =
                            start.map_or(picker.clone(), |path| picker.set_directory(path));
                        let result = if folder {
                            picker.pick_folder().await
                        } else {
                            let picker = match slot {
                                Slot::Keys => picker.add_filter(language.t(L::Keys), &["keys"]),
                                _ => picker.add_filter(language.t(L::Base), &["xci", "nsp"]),
                            };
                            picker.pick_file().await
                        };
                        (slot, result.map(|file| file.path().to_path_buf()))
                    },
                    |(slot, path)| Message::Picked(slot, path),
                );
            }
            Message::Picked(slot, Some(path)) if self.page.is_input() => {
                self.sequence += 1;
                let sequence = self.sequence;
                self.pending[index(slot)] = Some(sequence);
                self.notice = None;
                self.record(self.slot_label(slot), self.language.t(L::LogInspect));
                let language = self.language;
                if slot == Slot::Keys {
                    self.key_hint = None;
                }
                return Task::perform(
                    async move {
                        tokio::task::spawn_blocking(move || sources::inspect(path, slot, language))
                            .await
                            .unwrap_or_else(|_| Err(language.t(L::Unreadable).into()))
                    },
                    move |result| Message::Inspected(slot, sequence, result),
                );
            }
            Message::Inspected(slot, sequence, result)
                if self.pending[index(slot)] == Some(sequence) =>
            {
                self.pending[index(slot)] = None;
                match result {
                    Ok(source) => {
                        self.record(self.slot_label(slot), self.language.t(L::LogAccepted));
                        self.saved_input_missing[index(slot)] = false;
                        self.save_source_preference(slot, Some(&source));
                        *self.source_mut(slot) = Some(source);
                    }
                    Err(error) => {
                        self.record(self.slot_label(slot), &format!("ERROR: {error}"));
                        self.notice = Some(error);
                    }
                }
            }
            Message::Hover(slot) => self.hovered = slot,
            Message::DragTick => {
                #[cfg(target_os = "macos")]
                return window::latest()
                    .and_then(|id| window::run(id, drop_target::pointer))
                    .then(|point| match point {
                        Some(point) => {
                            iced::advanced::widget::operate(drop_target::HitTest::new(point))
                                .map(Message::Hover)
                        }
                        None => Task::done(Message::Hover(None)),
                    });
            }
            Message::Event(Event::Window(window::Event::FileHovered(_))) => self.drag_active = true,
            Message::Event(Event::Window(window::Event::FilesHoveredLeft)) => {
                self.drag_active = false
            }
            Message::Event(Event::Window(window::Event::FileDropped(path)))
                if self.page.is_input() =>
            {
                self.drag_active = false;
                #[cfg(target_os = "macos")]
                return window::latest()
                    .and_then(|id| window::run(id, drop_target::pointer))
                    .then(move |point| match point {
                        Some(point) => {
                            let path = path.clone();
                            iced::advanced::widget::operate(drop_target::HitTest::new(point))
                                .map(move |slot| Message::ResolvedDrop(slot, path.clone()))
                        }
                        None => Task::done(Message::ResolvedDrop(None, path.clone())),
                    });
                #[cfg(not(target_os = "macos"))]
                return self.update(Message::ResolvedDrop(self.hovered, path));
            }
            Message::ResolvedDrop(slot, path) if self.page.is_input() => {
                let slot = if path
                    .extension()
                    .is_some_and(|ext| ext.eq_ignore_ascii_case("keys"))
                {
                    Some(Slot::Keys)
                } else {
                    slot
                };
                if let Some(slot) = slot {
                    if self.pending[index(slot)].is_none() {
                        return self.update(Message::Picked(slot, Some(path)));
                    }
                    self.notice = Some(self.language.t(L::OneSource).into());
                } else {
                    self.notice = Some(self.language.t(L::DropInArea).into());
                }
            }
            Message::FindKeys if self.page.is_input() || self.page == Page::Target => {
                self.sequence += 1;
                let sequence = self.sequence;
                self.pending[index(Slot::Keys)] = Some(sequence);
                self.key_hint = None;
                self.notice = None;
                self.record(self.language.t(L::Keys), self.language.t(L::LogSearch));
                let language = self.language;
                return Task::perform(
                    async move {
                        tokio::task::spawn_blocking(move || key_paths::find(language))
                            .await
                            .ok()
                            .flatten()
                    },
                    move |source| Message::KeysFound(sequence, source),
                );
            }
            Message::KeysFound(sequence, source)
                if self.pending[index(Slot::Keys)] == Some(sequence) =>
            {
                self.pending[index(Slot::Keys)] = None;
                self.key_hint = Some(
                    self.language
                        .t(if source.is_some() {
                            L::FoundKeys
                        } else {
                            L::NoKeys
                        })
                        .into(),
                );
                self.record(
                    self.language.t(L::Keys),
                    &self.key_hint.clone().unwrap_or_default(),
                );
                if let Some(source) = source {
                    self.saved_input_missing[index(Slot::Keys)] = false;
                    self.save_source_preference(Slot::Keys, Some(&source));
                    self.keys = Some(source);
                }
            }
            Message::Event(Event::Keyboard(keyboard::Event::KeyPressed {
                key: keyboard::Key::Named(keyboard::key::Named::Escape),
                ..
            })) => {
                return self.update(Message::Back);
            }
            Message::Remove(slot) if self.page.is_input() => {
                if slot == Slot::Keys {
                    self.key_hint = None;
                }
                *self.source_mut(slot) = None;
                self.saved_input_missing[index(slot)] = false;
                self.save_source_preference(slot, None);
                self.pending[index(slot)] = None;
                self.notice = None;
            }
            Message::Review if self.ready() => {
                if self.ios_signing_open {
                    if self.persist_preferences()
                        && preferences::save_signing_team(&self.ios_team).is_err()
                    {
                        self.notice = Some(self.language.t(L::PreferenceError).into());
                        return Task::none();
                    }
                    self.ios_signing_open = false;
                    if self.page == Page::Target {
                        self.page = Page::Keys;
                    }
                    return Task::none();
                }
                if self.ios_devices_open {
                    self.ios_devices_open = false;
                    if self.page == Page::Target {
                        return self.handle(Message::OpenIosSigning);
                    }
                    return Task::none();
                }
                if self.page == Page::Target
                    && self.target == InstallTarget::Ios
                    && self.host == Platform::Mac
                    && self.ios_delivery == crate::backend::IosDelivery::Device
                    && !self.demo
                {
                    return self.handle(Message::OpenIosDevices);
                }
                if self.page == Page::Review && self.ios_profile_open {
                    self.ios_profile_open = false;
                    return Task::none();
                }
                self.details = false;
                self.page = match self.page {
                    Page::Target => Page::Keys,
                    Page::Keys => Page::Game,
                    Page::Game => Page::Update,
                    Page::Update => Page::Firmware,
                    Page::Firmware => Page::ModsFolder,
                    Page::ModsFolder => Page::Mods,
                    Page::Mods => Page::Review,
                    Page::Review => Page::Setup,
                    page => page,
                };
                if self.page == Page::ModsFolder {
                    self.mods_skipped = false;
                }
                self.notice = None;
                self.hovered = None;
                self.drag_active = false;
                if self.page == Page::Firmware
                    && self.firmware.is_none()
                    && !self.demo
                    && self.capture.is_none()
                {
                    return self.handle(Message::FindFirmware);
                }
                if self.page == Page::Mods && !self.demo && self.capture.is_none() {
                    return self.handle(Message::RefreshMods);
                }
            }
            Message::FindFirmware
                if self.page == Page::Firmware && self.firmware_pending.is_none() =>
            {
                self.sequence += 1;
                let id = self.sequence;
                self.firmware_pending = Some(id);
                self.firmware_hint = None;
                let keys = self.keys.as_ref().map(|s| s.path.clone());
                let language = self.language;
                self.record("Firmware", language.t(L::FirmwareSearching));
                return Task::perform(
                    async move {
                        tokio::task::spawn_blocking(move || {
                            key_paths::find_firmware(keys, language)
                        })
                        .await
                        .ok()
                        .flatten()
                    },
                    move |source| Message::FirmwareFound(id, source),
                );
            }
            Message::FirmwareFound(id, source) if self.firmware_pending == Some(id) => {
                self.firmware_pending = None;
                let hint = if let Some(source) = source {
                    let hint = self
                        .language
                        .t(L::FirmwareDetected)
                        .replace("{emulator}", &source.description);
                    self.firmware = Some(source.path);
                    hint
                } else {
                    self.language.t(L::FirmwareNotFound).to_owned()
                };
                self.record("Firmware", &hint);
                self.firmware_hint = Some(hint);
            }
            Message::ChooseFirmware(folder)
                if self.page == Page::Firmware && self.firmware_pending.is_none() =>
            {
                let language = self.language;
                let start = preferences::load_paths().last_directory;
                return Task::perform(
                    async move {
                        let picker = rfd::AsyncFileDialog::new().set_title(language.t(L::Firmware));
                        let picker =
                            start.map_or(picker.clone(), |path| picker.set_directory(path));
                        let file = if folder {
                            picker.pick_folder().await
                        } else {
                            picker.add_filter("ZIP", &["zip"]).pick_file().await
                        };
                        file.map(|f| f.path().to_owned())
                    },
                    Message::FirmwarePicked,
                );
            }
            Message::FirmwarePicked(Some(path))
                if self.page == Page::Firmware && self.firmware_pending.is_none() =>
            {
                self.sequence += 1;
                let id = self.sequence;
                self.firmware_pending = Some(id);
                self.notice = None;
                return Task::perform(
                    async move {
                        let p = path.clone();
                        let result = tokio::task::spawn_blocking(move || {
                            crate::firmware::inspect_source(&p)
                        })
                        .await
                        .unwrap_or_else(|_| Err("Firmware inspection failed.".into()));
                        (id, path, result)
                    },
                    |(id, path, result)| Message::FirmwareChecked(id, path, result),
                );
            }
            Message::FirmwareChecked(id, path, result) if self.firmware_pending == Some(id) => {
                self.firmware_pending = None;
                match result {
                    Ok(()) => {
                        self.firmware_hint = None;
                        self.firmware = Some(path.clone());
                        if !self.demo && self.capture.is_none() {
                            let _ = preferences::save_firmware(Some(&path));
                        }
                    }
                    Err(detail) => {
                        self.notice = Some(format!(
                            "{}\n\n{}",
                            self.language.t(L::FirmwareInvalid),
                            redact_home_path(&detail)
                        ))
                    }
                }
            }
            Message::RemoveFirmware => {
                self.firmware = None;
                self.firmware_hint = None;
                self.firmware_pending = None;
                if !self.demo && self.capture.is_none() {
                    let _ = preferences::save_firmware(None);
                }
            }
            Message::SkipFirmware
                if self.page == Page::Firmware && self.firmware_pending.is_none() =>
            {
                self.firmware = None;
                self.page = Page::ModsFolder;
                self.mods_skipped = false;
                self.notice = None;
                self.drag_active = false;
            }
            Message::Event(Event::Window(window::Event::FileDropped(path)))
                if self.page == Page::Firmware =>
            {
                self.drag_active = false;
                return self.handle(Message::FirmwarePicked(Some(path)));
            }
            Message::SkipMods if matches!(self.page, Page::ModsFolder | Page::Mods) => {
                self.mods_skipped = true;
                self.selected_mod = None;
                self.clear_ios_profile();
                self.page = Page::Review;
                self.details = false;
                self.notice = None;
                self.hovered = None;
                self.drag_active = false;
            }
            Message::Back if self.ios_signing_open => {
                self.ios_signing_open = false;
                if self.page == Page::Target {
                    self.ios_devices_open = true;
                }
            }
            Message::Back if self.ios_devices_open => {
                self.ios_devices_open = false;
            }
            Message::Back if self.page == Page::Progress && self.cleanup_busy => {}
            Message::Back if self.page == Page::Review && self.ios_profile_open => {
                self.ios_profile_open = false;
            }
            Message::Back if self.page == Page::Setup && self.build_options_open => {
                self.build_options_open = false;
            }
            Message::Back => {
                self.requirements_run_id += 1;
                self.requirements_busy = false;
                self.requirements = None;
                if self.page == Page::Progress && !self.demo && self.capture.is_none() {
                    if self.backend_status == BackendStatus::Running {
                        if let Some(cancel) = &self.backend_cancel {
                            cancel.store(true, Ordering::Release);
                        }
                        self.record("BACKEND", self.language.t(L::CancelRequested));
                    } else {
                        self.page = Page::Setup;
                        self.details = false;
                        self.notice = None;
                    }
                    return Task::none();
                }
                self.details = false;
                if self.page == Page::Progress {
                    self.record("PREVIEW", self.language.t(L::LogStopped));
                }
                self.page = match self.page {
                    Page::Target => Page::Target,
                    Page::Keys => Page::Target,
                    Page::Game => Page::Keys,
                    Page::Update => Page::Game,
                    Page::Review if self.mods_skipped => Page::Firmware,
                    Page::Review => Page::Mods,
                    Page::Mods => Page::ModsFolder,
                    Page::ModsFolder => Page::Firmware,
                    Page::Firmware => Page::Update,
                    Page::Setup => Page::Review,
                    Page::Progress => Page::Setup,
                    Page::Finished => Page::Keys,
                };
                self.notice = None;
                self.tick = 0;
                self.hovered = None;
                self.drag_active = false;
                if self.page == Page::Keys
                    && self.keys.is_none()
                    && self.pending[index(Slot::Keys)].is_none()
                    && self.capture.is_none()
                    && !self.demo
                {
                    return self.handle(Message::FindKeys);
                }
            }
            Message::Preview if self.page == Page::Setup => {
                if self.updating {
                    return Task::none();
                }
                if !self.demo {
                    if self.target == InstallTarget::Ios
                        && self.ios_delivery == crate::backend::IosDelivery::Device
                        && !self.ios_device_ready()
                    {
                        return self.handle(Message::OpenIosDevices);
                    }
                    if self.target == InstallTarget::Ios
                        && self.ios_delivery == crate::backend::IosDelivery::Device
                        && !crate::ios_signing::valid_id(&self.ios_team)
                    {
                        return self.handle(Message::OpenIosSigning);
                    }
                    if self.target == InstallTarget::Ios
                        && self.ios_delivery == crate::backend::IosDelivery::Ipa
                        && self.selected_mod.is_some()
                        && self.ios_profile.is_none()
                        && self.ios_new_profile.is_none()
                    {
                        if let Err(cause) = crate::ios_profile::load() {
                            self.notice = Some(
                                self.language
                                    .t(L::ProfileReadError)
                                    .replace("{cause}", &cause),
                            );
                            return Task::none();
                        }
                        self.resolve_ios_profile();
                    }
                    if !self.backend_supported() {
                        self.record("BACKEND", self.language.t(L::BackendUnavailable));
                        self.notice = Some(self.language.t(L::BackendUnavailable).into());
                        return Task::none();
                    }
                    if self.requirements_busy {
                        return Task::none();
                    }
                    if !self.requirements.as_ref().is_some_and(|p| p.ready()) {
                        self.requirements_busy = true;
                        self.requirements_run_id += 1;
                        let requirements_run_id = self.requirements_run_id;
                        let target = if self.target == InstallTarget::Ios {
                            "ios"
                        } else {
                            "native"
                        };
                        return Task::perform(
                            blocking(move || crate::dependencies::inspect(target)),
                            move |result| Message::RequirementsChecked(requirements_run_id, result),
                        );
                    }
                    self.requirements = None;
                    self.details = false;
                    self.page = Page::Progress;
                    self.backend_status = BackendStatus::Running;
                    self.backend_failure_detail = None;
                    self.notice = None;
                    self.build_progress = crate::progress::BuildProgress::default();
                    self.installed_app = None;
                    self.exported_ipa = None;
                    self.exported_ipa_size = None;
                    self.game_library = None;
                    self.build_options_open = false;
                    self.cleanup_busy = false;
                    self.motion.snap(0.0);
                    self.last_frame = None;
                    self.backend_run_id += 1;
                    let run_id = self.backend_run_id;
                    let cancelled = Arc::new(AtomicBool::new(false));
                    self.backend_cancel = Some(cancelled.clone());
                    self.record("BACKEND", self.language.t(L::LogBuildStart));
                    let request = match crate::flow::build_request(self.request_inputs()) {
                        Ok(request) => request,
                        Err(_) => {
                            self.backend_status = BackendStatus::Failed;
                            self.record("BACKEND", self.language.t(L::MissingInput));
                            self.notice = Some(self.language.t(L::MissingInput).into());
                            return Task::none();
                        }
                    };
                    return Task::run(
                        backend_stream(
                            run_id,
                            cancelled,
                            self.mods_folder.clone(),
                            self.selected_mod.clone(),
                            request,
                        ),
                        |(id, event)| Message::BackendEvent(id, event),
                    );
                }
                self.details = false;
                self.page = Page::Progress;
                self.tick = 0;
                self.motion.snap(0.0);
                self.last_frame = None;
                self.record("PREVIEW", self.language.t(L::LogPreview));
                self.record("PREVIEW", self.language.t(L::Tools));
            }
            Message::BackendEvent(run_id, event) if run_id == self.backend_run_id => match event {
                crate::backend::Event::Step { id, status } => {
                    if id == "cleanup" {
                        self.cleanup_busy = status == "started";
                        if status == "needs attention" {
                            self.notice = Some(self.language.t(L::CleanupFailed).into());
                        }
                    }
                    self.build_progress.step(&id, &status);
                    self.record("BACKEND", &format!("{id}: {status}"));
                }
                crate::backend::Event::GeneratorProgress {
                    module,
                    phase,
                    completed,
                    total,
                    modules_completed,
                    modules_total,
                } => {
                    self.build_progress.active = crate::progress::Stage::Generate;
                    self.build_progress.generator = crate::progress::GeneratorProgress {
                        module,
                        phase,
                        completed: completed.min(total),
                        total,
                        modules_completed,
                        modules_total,
                    };
                }
                crate::backend::Event::Progress {
                    id,
                    completed,
                    total,
                } => {
                    self.build_progress.count(&id, completed, total);
                }
                crate::backend::Event::Transfer {
                    id,
                    completed,
                    total,
                } => {
                    self.build_progress
                        .transfer(&id, completed, total, Instant::now());
                }
                crate::backend::Event::Log { level, message } => {
                    let message = redact_home_path(&message);
                    self.build_progress.note_log(&level, &message);
                    if level == "error" {
                        self.backend_failure_detail = Some(message.clone());
                    } else if level == "warning" || level == "hint" {
                        let detail = self.backend_failure_detail.get_or_insert_with(String::new);
                        if !detail.is_empty() {
                            detail.push('\n');
                        }
                        detail.push_str(&message);
                    }
                    let prefix = if level == "error" || level == "warning" {
                        "ERROR"
                    } else {
                        "BACKEND"
                    };
                    self.record(prefix, &message);
                }
                crate::backend::Event::Artifact { kind, path } => {
                    let name = path.file_name().unwrap_or_default().to_string_lossy();
                    self.record("BACKEND", &format!("{kind}: {name}"));
                    if kind == "ipa" {
                        self.exported_ipa_size = std::fs::metadata(&path).ok().map(|m| m.len());
                        self.exported_ipa = Some(path.clone());
                    }
                    if kind == "game_library" {
                        self.game_library = Some(path.clone());
                    }
                    if kind == "installed_application" && self.target != InstallTarget::Ios {
                        let folder = path
                            .parent()
                            .and_then(|p| p.file_name())
                            .unwrap_or_default()
                            .to_string_lossy();
                        self.record(
                            "BACKEND",
                            &self.language.t(L::InstalledIn).replace("{folder}", &folder),
                        );
                        self.installed_app = Some(path);
                    }
                }
                crate::backend::Event::IosProfile(profile) => {
                    self.ios_profile = Some(profile);
                }
                crate::backend::Event::PythonMissing => {
                    self.record("BACKEND", self.language.t(L::PythonMissing));
                    self.backend_failure_detail =
                        Some(self.language.t(L::PythonDevelopmentError).into());
                }
                crate::backend::Event::RuntimeMissing => {
                    self.record("BACKEND", self.language.t(L::RuntimeMissing));
                    self.backend_failure_detail =
                        Some(self.language.t(L::PythonRuntimeError).into());
                }
                crate::backend::Event::Finished { ok, code } => {
                    self.build_progress.finish(Instant::now());
                    self.backend_status = if ok {
                        BackendStatus::Passed
                    } else {
                        BackendStatus::Failed
                    };
                    self.backend_cancel = None;
                    if !ok {
                        let detail = self
                            .backend_failure_detail
                            .take()
                            .unwrap_or_else(|| self.language.t(L::CheckFailed).into());
                        self.notice = Some(build_error_notice(
                            &detail,
                            self.language,
                            self.target == InstallTarget::Ios
                                && self.ios_delivery == crate::backend::IosDelivery::Ipa,
                        ));
                    } else {
                        self.backend_failure_detail = None;
                    }
                    self.record(
                        "BACKEND",
                        &format!(
                            "{} (exit code {code})",
                            self.language
                                .t(if ok { L::BuildPassed } else { L::BuildFailed })
                        ),
                    );
                }
                crate::backend::Event::Stopped => {
                    self.build_progress.finish(Instant::now());
                    self.backend_status = BackendStatus::Stopped;
                    self.backend_cancel = None;
                    self.record("BACKEND", self.language.t(L::CheckStopped));
                }
            },
            Message::Tick
                if self.page == Page::Progress
                    && (self.demo
                        || self.capture.is_some()
                        || self.backend_status == BackendStatus::Idle) =>
            {
                self.tick += 1;
                if self.tick >= self.build_stages().len() as u32 * 10 {
                    self.record("PREVIEW", self.language.t(L::LogComplete));
                    self.page = Page::Finished;
                } else if self.tick.is_multiple_of(10) {
                    let stage = self.build_stages()[(self.tick / 10) as usize];
                    let label = self.build_labels()[stage.index()];
                    self.record("PREVIEW", self.language.t(label));
                }
            }
            Message::ToggleDetails => self.details = !self.details,
            Message::CopyLogLine(index) => {
                if let Some(line) = self.log.get(index) {
                    let copied_at = Instant::now();
                    self.copied_log_line = Some((index, copied_at));
                    return Task::batch([
                        iced::clipboard::write(line.clone()),
                        Task::perform(tokio::time::sleep(Duration::from_millis(1800)), move |_| {
                            Message::ClearCopiedLogLine(index, copied_at)
                        }),
                    ]);
                }
            }
            Message::ClearCopiedLogLine(index, copied_at) => {
                if self.copied_log_line == Some((index, copied_at)) {
                    self.copied_log_line = None;
                }
            }
            Message::OpenLogFolder => {
                if let Some(folder) = crate::session_log::dir() {
                    let _ = std::fs::create_dir_all(&folder);
                    if let Err(error) = crate::open::folder(&folder) {
                        self.notice = Some(error);
                    }
                }
            }
            Message::ExportSave => {
                return Task::perform(
                    blocking(|| crate::save_export::export(None, None)),
                    Message::SaveExported,
                );
            }
            Message::SaveExported(Ok(done)) => {
                let file = done
                    .path
                    .file_name()
                    .map(|name| name.to_string_lossy().into_owned())
                    .unwrap_or_default();
                self.record(
                    "SAVE",
                    &format!(
                        "Exported {} files ({} bytes) as {file}.",
                        done.files, done.bytes
                    ),
                );
                let folder = done.path.parent().unwrap_or(&done.path);
                self.info_notice = false;
                if let Err(error) = crate::open::folder(folder) {
                    self.notice = Some(error);
                } else {
                    self.notice = Some(
                        self.language
                            .t(L::SaveExportedHint)
                            .replace("{file}", &file),
                    );
                    self.info_notice = true;
                }
            }
            Message::SaveExported(Err(error)) => {
                self.info_notice = false;
                self.notice = Some(error);
            }
            Message::CopyLog => return iced::clipboard::write(self.log.join("\n")),
            Message::CaptureTick => {
                if let Some(capture) = &mut self.capture
                    && !capture.waiting
                {
                    capture.waiting = true;
                    return iced::advanced::widget::operate(capture::LayoutCheck::default())
                        .map(Message::CaptureLayout);
                }
            }
            Message::CaptureLayout(overflow) => {
                if let Some(capture) = &mut self.capture {
                    let error = match overflow {
                        Some(size) if size.width > 0.5 || size.height > 0.5 => Some(format!(
                            "{}: main content overflows by {:.2} × {:.2} logical pixels",
                            capture.filename().display(),
                            size.width,
                            size.height
                        )),
                        None => Some("Main content not found for layout validation".into()),
                        _ => None,
                    };
                    if let Some(error) = error {
                        eprintln!("Layout error: {error}");
                        capture.layout_errors.push(error);
                    }
                    return window::latest()
                        .and_then(window::screenshot)
                        .map(Message::Captured);
                }
            }
            Message::Captured(screenshot) => {
                if let Some(capture) = &self.capture {
                    return Task::perform(
                        capture::save(screenshot, capture.filename()),
                        Message::CaptureSaved,
                    );
                }
            }
            Message::CaptureSaved(result) => {
                match result {
                    Ok(path) => println!("Screenshot: {}", path.display()),
                    Err(error) => {
                        eprintln!("Screenshot failed: {error}");
                        std::process::exit(1);
                    }
                }
                if let Some(capture) = &mut self.capture {
                    capture.index += 1;
                    if capture.index >= capture.scenes.len() {
                        if !capture.layout_errors.is_empty() {
                            eprintln!(
                                "{} layout overflow(s) detected.",
                                capture.layout_errors.len()
                            );
                            std::process::exit(1);
                        }
                        return iced::exit();
                    }
                    capture.waiting = false;
                }
                return self.capture_scenario();
            }
            _ => {}
        }
        Task::none()
    }

    /// The facts that need no probe, before any step. The slow ones follow with `Message::SystemChecked`.
    fn record_system_header(&mut self) {
        if self.capture.is_some() || self.demo {
            return;
        }
        let log_file = self
            .persist_preferences()
            .then(crate::session_log::file_name)
            .flatten();
        let data = crate::appdir::data_dir();
        let host = if self.simulated_platform {
            format!("{} (simulated)", self.host.label())
        } else {
            self.host.label().to_owned()
        };
        let lines = crate::sysinfo::header(
            &host,
            self.target.label(),
            self.language.code(),
            data.as_deref(),
            log_file.as_deref(),
        );
        for line in lines {
            self.record("SYSTEM", &redact_home_path(&line));
        }
    }

    /// Copies what the terminal install wrote since the last look into the session log.
    fn stream_terminal_log(&mut self) {
        let log = crate::dependencies::read_setup_log();
        if log.len() != self.setup_log_length {
            let new = log.get(self.setup_log_length..).unwrap_or(&log);
            for line in new.lines() {
                self.record("SETUP", &redact_home_path(line));
            }
            self.setup_log_length = log.len();
        }
    }

    /// Step changes and new output lines of the running Windows setup go into the session log as they happen.
    fn stream_setup_progress(&mut self) {
        let progress = self.setup_progress.clone();
        let step = (progress.index, progress.id.clone(), progress.phase.clone());
        if progress.index > 0 && step != self.setup_step_logged {
            self.record(
                "SETUP",
                &format!(
                    "Step {} of {}: {} ({})",
                    progress.index, progress.total, progress.id, progress.phase
                ),
            );
            self.setup_step_logged = step;
        }
        for line in unseen_lines(&self.setup_streamed, &progress.log) {
            self.record("SETUP", &redact_home_path(line));
        }
        self.setup_streamed = progress.log;
    }

    /// An install of the requirements failed: the log gets the exact error with the step and the last output, and a card
    /// stays on screen (the error is not only a dialog that disappears).
    fn fail_setup(&mut self, progress: crate::components::SetupProgress, error: &str) {
        let error = redact_home_path(error);
        let manager = self.requirements.as_ref().map(|plan| plan.manager.clone());
        let step = if manager.as_deref() == Some("windows-components") {
            self.setup_progress = progress;
            self.stream_setup_progress();
            let p = &self.setup_progress;
            let step = format!(
                "step {} of {}, {} ({})",
                p.index.max(1),
                p.total.max(1),
                if p.id.is_empty() { "unknown" } else { &p.id },
                if p.phase.is_empty() {
                    "unknown"
                } else {
                    &p.phase
                }
            );
            self.record("SETUP", &format!("Install tools failed in {step}: {error}"));
            step
        } else {
            self.stream_terminal_log();
            let manager = manager.unwrap_or_else(|| "unknown".into());
            self.record(
                "SETUP",
                &format!("Install tools failed ({manager}): {error}"),
            );
            manager
        };
        self.setup_failure = Some(SetupFailure { step, error });
    }

    // Diagnostic messages intentionally exclude file paths and key contents.
    fn record(&mut self, step: &str, message: &str) {
        let line = format!("{:03} [{step}] {message}", self.log.len() + 1);
        if self.persist_preferences() {
            crate::session_log::append(&line);
        }
        self.log.push(line);
    }

    fn persist_preferences(&self) -> bool {
        self.capture.is_none() && !self.demo && !cfg!(test)
    }

    /// Remembers a chosen build or install folder; `None` returns to the default.
    fn set_folder(&mut self, setting: FolderSetting, folder: Option<PathBuf>) {
        if self.persist_preferences()
            && crate::appdir::choose_folder(setting.file(), folder.as_deref()).is_err()
        {
            self.notice = Some(self.language.t(L::PreferenceError).into());
            return;
        }
        match setting {
            FolderSetting::Work => self.work_folder = folder,
            FolderSetting::Install => self.install_folder = folder,
        }
    }

    fn save_source_preference(&mut self, slot: Slot, source: Option<&Source>) {
        if self.persist_preferences()
            && preferences::save_source_path(slot, source.map(|source| source.path.as_path()))
                .is_err()
        {
            self.notice = Some(self.language.t(L::PreferenceError).into());
        }
    }

    fn slot_label(&self, slot: Slot) -> &'static str {
        self.language.t(match slot {
            Slot::Keys => L::Keys,
            Slot::Base => L::Base,
            Slot::Update => L::Update,
        })
    }

    fn targets(&self) -> Vec<InstallTarget> {
        let mut targets = vec![InstallTarget::native(self.host)];
        if self.host != Platform::Mac {
            targets.push(InstallTarget::Mac);
        }
        targets.extend([InstallTarget::Ios, InstallTarget::Android]);
        targets
    }

    fn step_labels(&self) -> Vec<L> {
        let mut labels = vec![L::Target, L::Keys, L::Base, L::Update, L::Firmware];
        if !self.mods_skipped {
            labels.extend([L::ModsLocation, L::Mods]);
        }
        labels.extend([L::CheckSelection, L::Setup]);
        labels.extend(
            self.build_stages()
                .iter()
                .map(|stage| self.build_labels()[stage.index()]),
        );
        labels
    }

    fn build_stages(&self) -> Vec<crate::progress::Stage> {
        crate::flow::build_stages(
            self.target,
            self.ios_delivery,
            self.firmware.is_some(),
            crate::flow::code_mod_selected(
                self.mods_skipped,
                self.selected_mod.as_deref(),
                &self.mods,
            ),
        )
    }

    fn build_labels(&self) -> [L; 13] {
        [
            L::FetchSource,
            L::Tools,
            L::Firmware,
            L::Prepare,
            L::ExeFS,
            L::VerifySigning,
            L::PrepareShaders,
            L::Generate,
            L::Compile,
            L::Images,
            L::Runtime,
            L::Package,
            if self.target == InstallTarget::Ios
                && self.ios_delivery == crate::backend::IosDelivery::Ipa
            {
                L::ExportOutput
            } else {
                L::Install
            },
        ]
    }

    fn active_step(&self) -> usize {
        let offset = 1;
        match self.page {
            Page::Target => 0,
            Page::Keys => offset,
            Page::Game => offset + 1,
            Page::Update => offset + 2,
            Page::Firmware => offset + 3,
            Page::ModsFolder => offset + 4,
            Page::Mods => offset + 5,
            Page::Review => offset + if self.mods_skipped { 4 } else { 6 },
            Page::Setup => offset + if self.mods_skipped { 5 } else { 7 },
            Page::Progress => {
                offset
                    + if self.mods_skipped { 6 } else { 8 }
                    + if self.demo
                        || (self.capture.is_some() && self.backend_status == BackendStatus::Idle)
                    {
                        ((self.tick / 10) as usize).min(self.build_stages().len() - 1)
                    } else {
                        self.build_stages()
                            .iter()
                            .position(|stage| *stage == self.build_progress.active)
                            .unwrap_or(0)
                    }
            }
            Page::Finished => self.step_labels().len() - 1,
        }
    }

    fn source(&self, slot: Slot) -> Option<&Source> {
        match slot {
            Slot::Base => self.base.as_ref(),
            Slot::Update => self.update.as_ref(),
            Slot::Keys => self.keys.as_ref(),
        }
    }
    fn source_mut(&mut self, slot: Slot) -> &mut Option<Source> {
        match slot {
            Slot::Base => &mut self.base,
            Slot::Update => &mut self.update,
            Slot::Keys => &mut self.keys,
        }
    }
    fn ios_device_ready(&self) -> bool {
        !self.ios_devices_busy
            && self
                .ios_devices
                .iter()
                .any(|d| Some(&d.id) == self.ios_device.as_ref() && d.connected)
    }

    fn start_auto_build(&mut self) {
        let device_delivery = self.target == InstallTarget::Ios
            && self.ios_delivery == crate::backend::IosDelivery::Device;
        if self.demo || self.page != Page::Setup || device_delivery || !self.backend_supported() {
            return;
        }
        self.auto_build = Some(Instant::now());
        self.record(
            "AUTO",
            &format!(
                "The build starts in {} seconds. Press Cancel to stop it.",
                AUTO_BUILD_DELAY.as_secs()
            ),
        );
    }

    fn cancel_auto_build(&mut self, reason: &str) {
        if self.auto_build.take().is_some() {
            self.record("AUTO", &format!("Automatic build start stopped: {reason}."));
        }
    }

    fn auto_build_progress(&self) -> Option<f32> {
        self.auto_build.map(|started| {
            (started.elapsed().as_secs_f32() / AUTO_BUILD_DELAY.as_secs_f32()).min(1.0)
        })
    }

    fn ready(&self) -> bool {
        if self.ios_signing_open {
            return !self.ios_signing_busy && crate::ios_signing::valid_id(&self.ios_team);
        }
        if self.ios_devices_open {
            return self.ios_device_ready();
        }
        if matches!(self.page, Page::Target | Page::Review | Page::ModsFolder) {
            return true;
        }
        if self.page == Page::Firmware {
            return self.firmware_pending.is_none() && (self.demo || self.firmware.is_some());
        }
        if self.page == Page::Mods {
            return !self.mods_scanning
                && self.selected_mod.as_ref().is_none_or(|name| {
                    self.mods.iter().any(|item| {
                        &item.name == name
                            && (item.has_romfs || item.has_exefs)
                            && (self.demo
                                || !item.has_exefs
                                || (self.ips_target() && item.ips_buildable()))
                    })
                });
        }
        if self.pending.iter().any(Option::is_some) {
            return false;
        }
        if self.demo {
            return self.page.is_input();
        }
        match self.page {
            Page::Keys => self.keys.is_some(),
            Page::Game | Page::Update => self.keys.is_some() && self.base.is_some(),
            _ => false,
        }
    }

    fn request_inputs(&self) -> crate::flow::RequestInputs<'_> {
        crate::flow::RequestInputs {
            target: self.target,
            arch: std::env::consts::ARCH,
            ios_delivery: self.ios_delivery,
            ios_device: self.ios_device.clone(),
            ios_team: &self.ios_team,
            ios_profile: self.ios_profile.clone(),
            ios_new_profile: self.ios_new_profile.clone(),
            portable_cpu: self.portable_cpu,
            clean_build: self.clean_build,
            ios_export_no_embed: self.ios_export_no_embed,
            auto_cleanup: self.auto_cleanup,
            base: self.base.as_ref().map(|source| source.path.clone()),
            keys: self.keys.as_ref().map(|source| source.path.clone()),
            firmware: self.firmware.clone(),
            update: self.update.as_ref().map(|source| source.path.clone()),
            selected_mod: self.selected_mod.clone(),
            mods: &self.mods,
        }
    }

    fn backend_supported(&self) -> bool {
        crate::flow::backend_supported(
            self.host,
            self.target,
            std::env::consts::ARCH,
            self.base.as_ref().map(|source| source.path.as_path()),
            self.selected_mod.as_deref(),
            &self.mods,
        )
    }

    fn experimental_target(&self) -> bool {
        experimental_target(self.host, self.target, std::env::consts::ARCH)
    }

    /// Targets whose build stages IPS/IPS32 and subsdk1 into a separate mod app.
    fn ips_target(&self) -> bool {
        crate::flow::ips_target(self.host, self.target)
    }

    fn capture_scenario(&mut self) -> Task<Message> {
        let index = self.capture.as_ref().expect("capture enabled").index;
        self.appearance = Appearance::Dark;
        self.portable_cpu = false;
        self.clean_build = false;
        self.ios_export_no_embed = false;
        self.settings_open = false;
        self.auto_cleanup = true;
        self.build_options_open = false;
        self.cleanup_busy = false;
        let scenario = self.capture.as_ref().expect("capture enabled").scenes[index];
        self.base = None;
        self.update = None;
        self.keys = None;
        self.saved_input_missing = [false; 3];
        self.mods.clear();
        self.selected_mod = None;
        self.clear_ios_profile();
        self.ios_devices_open = false;
        self.ios_signing_open = false;
        self.ios_teams.clear();
        self.ios_team.clear();
        self.ios_devices.clear();
        self.ios_device = None;
        self.ios_devices_busy = false;
        self.ios_devices_failed = false;
        self.ios_devices_page = 0;
        self.mods_skipped = false;
        self.mods_scanning = false;
        self.notice = None;
        self.page = Page::Keys;
        self.demo = matches!(scenario, "demo" | "demo-review" | "demo-target-ios");
        self.target = InstallTarget::native(self.host);
        self.motion.snap(0.0);
        self.details = false;
        self.key_hint = None;
        self.tick = 0;
        self.log.clear();
        self.copied_log_line = None;
        self.backend_status = BackendStatus::Idle;
        self.installed_app = None;
        self.exported_ipa = None;
        self.exported_ipa_size = None;
        self.game_library = None;
        self.backend_cancel = None;
        self.requirements = None;
        self.available_update = None;
        if !matches!(scenario, "empty" | "keys-empty" | "keys-not-found") {
            self.base = Some(Source::fixture(
                self.language.t(L::DemoGameFile),
                &format!(
                    "XCI · {}",
                    sources::size_label(44 * (1 << 30) / 10, self.language)
                ),
            ));
            self.update = Some(Source::fixture(
                self.language.t(L::DemoUpdateFile),
                &format!(
                    "NSP · {}",
                    sources::size_label(28 * (1 << 30) / 10, self.language)
                ),
            ));
            self.keys = Some(Source::fixture(
                "prod.keys",
                self.language.t(L::PrivateKeys),
            ));
        }
        match scenario {
            "signing-check" => {
                self.page = Page::Progress;
                self.target = InstallTarget::Ios;
                self.ios_delivery = crate::backend::IosDelivery::Device;
                self.backend_status = BackendStatus::Running;
                self.build_progress.step("signing", "started");
                self.motion
                    .snap(crate::progress::Stage::Signing.index() as f32);
            }

            "signing" | "signing-empty" | "signing-manual" => {
                self.page = Page::Target;
                self.target = InstallTarget::Ios;
                self.ios_delivery = crate::backend::IosDelivery::Device;
                self.ios_signing_open = true;
                if scenario != "signing-empty" {
                    self.ios_teams = vec![crate::ios_signing::Team {
                        id: "TESTTEAM01".into(),
                        name: "Personal Team".into(),
                    }];
                    self.ios_team = "TESTTEAM01".into();
                }
                self.ios_team_manual = scenario == "signing-manual";
            }
            "setup-ios-device" => {
                self.page = Page::Setup;
                self.target = InstallTarget::Ios;
                self.ios_delivery = crate::backend::IosDelivery::Device;
                self.ios_team = "TESTTEAM01".into();
            }
            "log-copy" => {
                self.page = Page::Progress;
                self.details = true;
                for _ in 0..40 {
                    self.record("BACKEND","Checking Apple signing configuration and device prerequisites. Existing game saves are kept.");
                }
                self.copied_log_line = Some((39, Instant::now()));
            }

            "devices" | "devices-many" | "devices-empty" | "devices-offline" | "devices-error" => {
                self.page = Page::Target;
                self.target = InstallTarget::Ios;
                self.ios_delivery = crate::backend::IosDelivery::Device;
                self.ios_devices_open = true;
                if scenario != "devices-empty" {
                    self.ios_devices = [
                        ("one", "iPad Pro", false),
                        ("two", "iPhone", true),
                        ("three", "iPad Air", true),
                    ]
                    .into_iter()
                    .map(|(id, name, wifi)| crate::ios_devices::Device {
                        id: id.into(),
                        name: name.into(),
                        model: name.into(),
                        wifi,
                        connected: matches!(scenario, "devices" | "devices-many"),
                    })
                    .collect();
                    self.ios_device = Some("two".into());
                }
                if scenario == "devices-many" {
                    self.ios_devices.push(crate::ios_devices::Device {
                        id: "four".into(),
                        name: "iPad Pro".into(),
                        model: "iPad Pro".into(),
                        connected: true,
                        wifi: true,
                    });
                }
                self.ios_devices_failed = scenario == "devices-error";
            }

            "target" | "demo" => self.page = Page::Target,
            "target-ios" | "demo-target-ios" => {
                self.page = Page::Target;
                self.target = InstallTarget::Ios;
            }
            "target-mac" => {
                self.page = Page::Target;
                self.target = InstallTarget::Mac;
            }
            "keys-not-found" => self.key_hint = Some(self.language.t(L::NoKeys).into()),
            "game-empty" => {
                self.page = Page::Game;
                self.base = None;
            }
            "game-selected" => self.page = Page::Game,
            "update-empty" => {
                self.page = Page::Update;
                self.update = None;
            }
            "firmware-empty" => {
                self.page = Page::Firmware;
                self.firmware = None;
            }
            "firmware-selected" => {
                self.page = Page::Firmware;
                self.firmware = Some(PathBuf::from("Firmware.zip"));
            }
            "firmware-import-progress" => {
                self.firmware = Some(PathBuf::from("Firmware.zip"));
                self.page = Page::Progress;
                self.backend_status = BackendStatus::Running;
                self.build_progress.step("firmware", "started");
                self.motion
                    .snap(crate::progress::Stage::Firmware.index() as f32);
            }
            "firmware-auto" => {
                self.page = Page::Firmware;
                self.firmware = Some(PathBuf::from("registered"));
                self.firmware_hint = Some(
                    self.language
                        .t(L::FirmwareDetected)
                        .replace("{emulator}", "Ryujinx / Ryubing"),
                );
            }
            "firmware-not-found" => {
                self.page = Page::Firmware;
                self.firmware = None;
                self.firmware_hint = Some(self.language.t(L::FirmwareNotFound).into());
            }
            "review-firmware" => {
                self.page = Page::Review;
                self.firmware = Some(PathBuf::from("Firmware.zip"));
            }
            "mods-folder" => self.page = Page::ModsFolder,
            "mods-folder-ios" => {
                self.page = Page::ModsFolder;
                self.target = InstallTarget::Ios;
                self.mods_folder = mod_support::folder_for(self.host, self.target);
            }
            "mods-folder-windows" => {
                self.page = Page::ModsFolder;
                self.target = InstallTarget::Windows;
                self.mods_folder = mod_support::folder_for(self.host, self.target);
            }
            "mods-empty" => self.page = Page::Mods,
            "mods-ips-ready"
            | "mods-ips-ios-ready"
            | "review-mod"
            | "review-ios-mod"
            | "review-ios-mod-nodata"
            | "ios-profile" => {
                if matches!(
                    scenario,
                    "mods-ips-ios-ready"
                        | "review-ios-mod"
                        | "review-ios-mod-nodata"
                        | "ios-profile"
                ) {
                    self.target = InstallTarget::Ios;
                }
                // The longest review page: mod, profile link and the longer text of the switch that is on.
                self.ios_export_no_embed = scenario == "review-ios-mod-nodata";
                let root = self
                    .capture
                    .as_ref()
                    .unwrap()
                    .directory
                    .join("fixture-mod/Luminescent Platinum");
                let exefs = root.join("ExeFS");
                std::fs::create_dir_all(&exefs).expect("create screenshot fixture");
                std::fs::write(exefs.join("0123.ips"), b"PATCHEOF")
                    .expect("write screenshot fixture");
                self.ios_profile_open = scenario == "ios-profile";
                self.page = if matches!(
                    scenario,
                    "review-mod" | "review-ios-mod" | "review-ios-mod-nodata" | "ios-profile"
                ) {
                    Page::Review
                } else {
                    Page::Mods
                };
                self.mods = vec![ModEntry {
                    name: "Luminescent Platinum".into(),
                    root,
                    has_romfs: true,
                    has_exefs: true,
                }];
                self.selected_mod = Some("Luminescent Platinum".into());
            }
            "mods-selected" | "mods-exefs-only" => {
                self.page = Page::Mods;
                self.mods = vec![ModEntry {
                    name: "Luminescent Platinum".into(),
                    root: PathBuf::from("Example/Luminescent Platinum"),
                    has_romfs: scenario != "mods-exefs-only",
                    has_exefs: true,
                }];
                self.selected_mod = Some("Luminescent Platinum".into());
            }
            "update-selected" => self.page = Page::Update,
            "nca" => {
                self.page = Page::Game;
                self.base = Some(Source::fixture(
                    self.language.t(L::DemoNcaFolder),
                    &format!(
                        "{} · 12 {}",
                        self.language.t(L::NcaFolder),
                        self.language.files(12)
                    ),
                ));
                self.update = None;
            }
            "error" | "error-details" => {
                self.page = Page::Game;
                self.base = None;
                self.notice = Some(self.language.t(L::NoNca).into());
                self.record(
                    self.language.t(L::Base),
                    &format!("ERROR: {}", self.language.t(L::NoNca)),
                );
                self.details = scenario == "error-details";
            }
            "error-prerequisite" => {
                self.page = Page::Progress;
                self.backend_status = BackendStatus::Failed;
                self.build_progress.step("prerequisites", "started");
                self.tick = (crate::progress::Stage::Requirements.index() * 10) as u32;
                let error = "Prerequisite checker internal error: KeyError: 'detail'";
                self.notice = Some(build_error_notice(error, self.language, false));
                self.record("ERROR", error);
            }
            "error-disk" => {
                self.page = Page::Progress;
                self.notice = disk_space_error(
                    "MISSING  Disk space >= 40 GB free (21.7 GB free)\nNext step: Free up disk space before continuing.",
                    self.language,
                );
                self.log
                    .push("001 [ERROR] MISSING  Disk space >= 40 GB free (21.7 GB free)".into());
                self.log
                    .push("002 [BACKEND] Next step: Free up disk space before continuing.".into());
            }
            "review" | "demo-review" => self.page = Page::Review,
            "review-portable" => {
                self.page = Page::Review;
                self.portable_cpu = true;
            }
            "review-skip-mods" => {
                self.page = Page::Review;
                self.mods_skipped = true;
            }
            "setup" => self.page = Page::Setup,
            "setup-auto-start" | "setup-auto-start-late" => {
                self.page = Page::Setup;
                let percent = if scenario == "setup-auto-start" {
                    33
                } else {
                    80
                };
                let elapsed = AUTO_BUILD_DELAY * percent.min(100) / 100;
                self.auto_build = Instant::now().checked_sub(elapsed);
            }
            "build-options" => {
                self.page = Page::Setup;
                self.build_options_open = true;
            }
            "setup-dependencies" | "setup-dependencies-details" => {
                self.page = Page::Setup;
                self.details = scenario == "setup-dependencies-details";
                self.requirements = Some(if self.host == Platform::Windows {
                    crate::dependencies::windows_plan("x86_64", false)
                } else {
                    crate::dependencies::Plan {
                        manager: "dnf".into(),
                        packages: vec!["clang".into(), "SDL3-devel".into()],
                        missing: vec![
                            crate::dependencies::Missing {
                                id: "clang".into(),
                                purpose: "Compile the game code".into(),
                            },
                            crate::dependencies::Missing {
                                id: "SDL3".into(),
                                purpose: "Window, audio and controller support".into(),
                            },
                        ],
                        ..Default::default()
                    }
                });
                if let Some(plan) = &self.requirements {
                    let description = localized_plan_description(plan, self.language);
                    self.record("SETUP", &description);
                }
            }
            "settings" => self.settings_open = true,
            "update-available" | "update-confirmation" | "update-prompt" => {
                self.page = Page::Target;
                self.available_update = Some(crate::updates::Release {
                    tag: None,
                    version: "0.2.0".into(),
                    assets: vec![],
                });
                if matches!(scenario, "update-confirmation" | "update-prompt") {
                    let _ = self.handle(Message::ShowUpdateDetails);
                }
            }
            "review-ios" => {
                self.page = Page::Review;
                self.target = InstallTarget::Ios;
            }
            "setup-ios" => {
                self.page = Page::Setup;
                self.target = InstallTarget::Ios;
            }
            "installed" | "installed-test" | "ipa-exported" => {
                self.page = Page::Progress;
                self.backend_status = BackendStatus::Passed;
                self.build_progress = crate::progress::BuildProgress::default();
                for stage in crate::progress::Stage::ALL {
                    self.build_progress.stages[stage.index()].done = true;
                }
                self.build_progress.active = crate::progress::Stage::Install;
                self.installed_app = Some(if scenario == "installed-test" {
                    PathBuf::from("test-build/gui-installed-apps/BDSP.app")
                } else {
                    PathBuf::from("/Applications/BDSP.app")
                });
                self.motion
                    .snap(crate::progress::Stage::Install.index() as f32 + 1.0);
                if scenario == "ipa-exported" {
                    self.target = InstallTarget::Ios;
                    self.ios_delivery = crate::backend::IosDelivery::Ipa;
                    self.installed_app = None;
                    self.exported_ipa = Some(PathBuf::from("exports/game.ipa"));
                    self.game_library = Some(PathBuf::from("exports/Game Library"));
                }
            }
            "generator-analyze" | "generator-emit" => {
                self.page = Page::Progress;
                self.backend_status = BackendStatus::Running;
                self.build_progress = crate::progress::BuildProgress::default();
                self.build_progress.step("eh_gen", "started");
                self.build_progress.count("eh_gen", 1, 5);
                self.build_progress.generator = crate::progress::GeneratorProgress {
                    module: "main".into(),
                    phase: if scenario == "generator-analyze" {
                        "analyze"
                    } else {
                        "emit"
                    }
                    .into(),
                    completed: if scenario == "generator-analyze" {
                        0
                    } else {
                        218097
                    },
                    total: if scenario == "generator-analyze" {
                        0
                    } else {
                        218098
                    },
                    modules_completed: 1,
                    modules_total: 5,
                };
                self.motion.snap(
                    crate::progress::Stage::Generate.index() as f32
                        + self
                            .build_progress
                            .fraction(crate::progress::Stage::Generate),
                );
            }
            "progress" | "progress-details" => {
                self.page = Page::Progress;
                self.tick = 38;
                self.motion
                    .snap(self.build_stages()[3].index() as f32 + 0.8);
                self.details = scenario == "progress-details";
                self.record("PREVIEW", self.language.t(L::LogPreview));
                self.record("PREVIEW", self.language.t(L::Tools));
                self.record("PREVIEW", self.language.t(L::Prepare));
                if self.details {
                    self.copied_log_line = Some((1, Instant::now()));
                }
            }
            "progress-security-note" => {
                self.page = Page::Progress;
                self.backend_status = BackendStatus::Running;
                self.defender = Some(true);
                self.build_progress = crate::progress::BuildProgress::default();
                self.build_progress.step("package", "started");
                let stage = crate::progress::Stage::Package;
                self.motion.snap(stage.index() as f32 + 0.5);
            }
            "device-copy" => {
                self.page = Page::Progress;
                self.backend_status = BackendStatus::Running;
                self.build_progress = crate::progress::BuildProgress::default();
                self.build_progress.step("install", "started");
                self.build_progress.count("install", 11520, 18025);
                let now = Instant::now();
                let (gb, total) = (1u64 << 30, 47 * (1u64 << 30) / 10);
                self.build_progress.transfer(
                    "install",
                    gb,
                    total,
                    now.checked_sub(Duration::from_secs(60)).unwrap_or(now),
                );
                self.build_progress.transfer("install", 3 * gb, total, now);
                let stage = crate::progress::Stage::Install;
                self.motion
                    .snap(stage.index() as f32 + self.build_progress.fraction(stage));
                self.record("BACKEND", "Copying 18025 files (4.7 GB) to the device.");
                self.record("BACKEND", "Copying game data to the device.");
            }
            "shaders" => {
                self.page = Page::Progress;
                self.backend_status = BackendStatus::Running;
                self.build_progress = crate::progress::BuildProgress::default();
                self.build_progress.step("shaders", "started");
                self.build_progress.note_log(
                    "diagnostic",
                    "shaders: compiling the Metal libraries for macosx",
                );
                self.build_progress.count("shaders", 1710, 2739);
                let stage = crate::progress::Stage::Shaders;
                self.motion
                    .snap(stage.index() as f32 + self.build_progress.fraction(stage));
                self.record("BACKEND", "shaders: 2739 distinct shaders from 4336 programs (180 use global memory and compile at run time)");
            }
            "shaders-translate" => {
                self.page = Page::Progress;
                self.backend_status = BackendStatus::Running;
                self.build_progress = crate::progress::BuildProgress::default();
                self.build_progress.step("shaders", "started");
                self.build_progress
                    .note_log("diagnostic", "shaders: translating");
                self.build_progress.count("shaders", 491, 0);
                self.motion
                    .snap(crate::progress::Stage::Shaders.index() as f32);
                self.record("BACKEND", "shaders: translating");
            }
            "extract-step" | "extract-silent" => {
                self.page = Page::Progress;
                self.backend_status = BackendStatus::Running;
                self.build_progress = crate::progress::BuildProgress::default();
                self.build_progress.step("extract", "started");
                for line in [
                    "4/5 extract ExeFS and RomFS (the update applied to the base NCA)",
                    "5/5 version, icons and manifest",
                    "Original icons: 9 language variants",
                    "    recording the SHA-256 of the game files",
                ] {
                    self.build_progress.note_log("diagnostic", line);
                    self.record("BACKEND", line);
                }
                self.build_progress.count("extract", 962, 1000);
                if scenario == "extract-silent" {
                    self.build_progress
                        .shift_clock(crate::progress::SILENCE * 3 + Duration::from_secs(7));
                    self.build_progress.touch(
                        Instant::now()
                            .checked_sub(crate::progress::SILENCE * 3)
                            .unwrap_or_else(Instant::now),
                    );
                }
                let stage = crate::progress::Stage::Extract;
                self.motion
                    .snap(stage.index() as f32 + self.build_progress.fraction(stage));
            }
            "preflight-running" | "preflight-details" => {
                self.page = Page::Progress;
                self.build_progress = crate::progress::BuildProgress::default();
                self.build_progress.step("prerequisites", "started");
                self.tick = (crate::progress::Stage::Requirements.index() * 10) as u32;
                self.backend_status = if scenario == "preflight-running" {
                    BackendStatus::Running
                } else {
                    BackendStatus::Failed
                };
                self.details = scenario == "preflight-details";
                self.record("BACKEND", self.language.t(L::LogPreflight));
                self.record("BACKEND", "OK  python3 >= 3.9 (3.14.3)");
                if scenario == "preflight-running" {
                    self.record("BACKEND", "OK  git (for hactool)");
                } else {
                    self.record("BACKEND", "MISSING  Disk space >= 40 GB free (34 GB free)");
                    self.record("BACKEND", "Next step: Free up space on this disk.");
                    self.record("BACKEND", self.language.t(L::CheckFailed));
                }
            }
            "finished" => self.page = Page::Finished,
            "long-name" => {
                self.page = Page::Game;
                self.base = Some(Source::fixture(
                    self.language.t(L::DemoLongName),
                    &format!(
                        "XCI · {}",
                        sources::size_label(44 * (1 << 30) / 10, self.language)
                    ),
                ));
            }
            _ => {}
        }
        let size = self.preferred_size();
        #[cfg(not(target_os = "macos"))]
        return window::latest().and_then(move |id| crate::window_layout::resize(id, size));
        #[cfg(target_os = "macos")]
        window::latest().and_then(move |id| window::resize(id, size))
    }
}

/// The folder chosen earlier in the build options; only Windows has the choice, and tests never read the real settings.
fn stored_folder(host: Platform, setting: FolderSetting) -> Option<PathBuf> {
    if host == Platform::Windows && !cfg!(test) {
        crate::appdir::chosen_folder(setting.file())
    } else {
        None
    }
}

/// The window side of a run: the backend writes into a plain channel, this forwards it into the iced stream.
fn backend_stream(
    run_id: u64,
    cancelled: Arc<AtomicBool>,
    mods_folder: Option<std::path::PathBuf>,
    selected_mod: Option<String>,
    request: crate::backend::BuildRequest,
) -> impl iced::futures::Stream<Item = (u64, crate::backend::Event)> + 'static {
    iced::stream::channel(32, async move |mut output| {
        use iced::futures::SinkExt;
        let (sender, mut receiver) = tokio::sync::mpsc::channel(32);
        let run = crate::backend::build(
            run_id,
            cancelled,
            mods_folder,
            selected_mod,
            request,
            sender,
        );
        let forward = async {
            while let Some(item) = receiver.recv().await {
                if output.send(item).await.is_err() {
                    break;
                }
            }
        };
        tokio::join!(run, forward);
    })
}

fn experimental_target(host: Platform, target: InstallTarget, arch: &str) -> bool {
    host == Platform::Linux && target == InstallTarget::Linux && arch == "aarch64"
}

fn index(slot: Slot) -> usize {
    match slot {
        Slot::Base => 0,
        Slot::Update => 1,
        Slot::Keys => 2,
    }
}

fn compact_name(name: &str) -> String {
    let chars: Vec<_> = name.chars().collect();
    if chars.len() <= 42 {
        return name.into();
    }
    format!(
        "{}…{}",
        chars[..26].iter().collect::<String>(),
        chars[chars.len() - 13..].iter().collect::<String>()
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn backend_support_matrix_unlocks_linux_aarch64_and_keeps_the_rest() {
        use InstallTarget::{Ios, Linux, Mac, Windows};
        let supported =
            |host, target, arch| crate::flow::platform_backend_supported(host, target, arch);
        assert!(supported(Platform::Linux, Linux, "x86_64"));
        assert!(supported(Platform::Linux, Linux, "aarch64"));
        assert!(!supported(Platform::Linux, Linux, "riscv64"));
        assert!(!supported(Platform::Linux, Windows, "x86_64"));
        assert!(supported(Platform::Mac, Mac, "aarch64"));
        assert!(supported(Platform::Mac, Ios, "aarch64"));
        assert!(!supported(Platform::Mac, Mac, "x86_64"));
        assert!(!supported(Platform::Mac, Linux, "aarch64"));
        assert!(supported(Platform::Windows, Windows, "x86_64"));
        assert!(supported(Platform::Windows, Windows, "aarch64"));
        assert!(!supported(Platform::Windows, Linux, "x86_64"));
        assert!(experimental_target(Platform::Linux, Linux, "aarch64"));
        assert!(!experimental_target(Platform::Linux, Linux, "x86_64"));
        assert!(!experimental_target(Platform::Mac, Mac, "aarch64"));
        assert!(!experimental_target(Platform::Windows, Windows, "aarch64"));
    }

    #[test]
    fn real_progress_renders_every_stage_with_and_without_firmware() {
        let (mut app, _) = Installer::new();
        app.demo = false;
        app.capture = None;
        app.page = Page::Progress;
        app.backend_status = BackendStatus::Running;
        for firmware in [None, Some(PathBuf::from("firmware.zip"))] {
            app.firmware = firmware;
            for stage in crate::progress::Stage::ALL {
                app.build_progress.active = stage;
                let _ = app.view();
            }
        }
    }

    #[test]
    fn firmware_is_optional_explicit_and_rejects_stale_inspection() {
        let (mut app, _) = Installer::new();
        app.demo = true;
        app.page = Page::Firmware;
        app.firmware_pending = Some(5);
        let path = PathBuf::from("Firmware.zip");
        let _ = app.update(Message::FirmwareChecked(4, path.clone(), Ok(())));
        assert!(app.firmware.is_none());
        let _ = app.update(Message::SkipFirmware);
        assert_eq!(app.page, Page::Firmware);
        let _ = app.update(Message::FirmwareChecked(5, path.clone(), Ok(())));
        assert_eq!(app.firmware.as_ref(), Some(&path));
        assert!(
            app.build_stages()
                .contains(&crate::progress::Stage::Firmware)
        );
        let _ = app.update(Message::SkipFirmware);
        assert_eq!(app.page, Page::ModsFolder);
        assert!(app.firmware.is_none());
        assert!(
            !app.build_stages()
                .contains(&crate::progress::Stage::Firmware)
        );
        let _ = app.update(Message::Back);
        assert_eq!(app.page, Page::Firmware);
        app.demo = false;
        assert!(!app.ready()); // Without a selection, use the explicit Skip action.
    }

    #[test]
    fn a_second_install_tools_press_is_ignored_while_the_tools_are_downloading() {
        let (mut app, _) = Installer::with_options(Options {
            platform: Some(Platform::Windows),
            capture: Some(std::env::temp_dir().join("windows-double-install-capture")),
            scenes: vec!["setup-dependencies"],
            ..Options::default()
        });
        app.setup_busy = true;
        app.setup_log_length = 7;
        let _ = app.handle(Message::InstallRequirements);
        assert_eq!(app.setup_log_length, 7);
        assert!(app.setup_busy);
    }

    fn auto_build_app() -> Installer {
        let (mut app, _) = Installer::with_options(Options {
            platform: Some(Platform::Windows),
            capture: Some(std::env::temp_dir().join("auto-build-capture")),
            scenes: vec!["setup-dependencies"],
            ..Options::default()
        });
        app.requirements = None;
        app
    }

    #[test]
    fn the_auto_build_countdown_stops_on_cancel_and_on_leaving_the_page() {
        let mut app = auto_build_app();
        app.auto_build = Some(Instant::now());
        let _ = app.update(Message::CancelAutoBuild);
        assert!(app.auto_build.is_none());
        assert!(app.log.iter().any(|line| line.contains("stopped")));

        app.auto_build = Some(Instant::now());
        app.page = Page::Target;
        let _ = app.handle(Message::AutoBuildTick);
        assert!(app.auto_build.is_none());
    }

    #[test]
    fn the_auto_build_countdown_starts_the_build_only_after_the_delay() {
        let mut app = auto_build_app();
        app.auto_build = Some(Instant::now());
        let _ = app.handle(Message::AutoBuildTick);
        assert!(app.auto_build.is_some());
        app.auto_build = Instant::now().checked_sub(AUTO_BUILD_DELAY);
        let _ = app.handle(Message::AutoBuildTick);
        assert!(app.auto_build.is_none());
        assert!(
            app.log
                .iter()
                .any(|line| line.contains("started automatically"))
        );
    }

    #[test]
    fn windows_dependency_capture_offers_the_build_environment_download() {
        let (app, _) = Installer::with_options(Options {
            platform: Some(Platform::Windows),
            capture: Some(std::env::temp_dir().join("windows-dependency-capture")),
            scenes: vec!["setup-dependencies"],
            ..Options::default()
        });
        assert_eq!(app.page, Page::Setup);
        assert_eq!(app.target, InstallTarget::Windows);
        let plan = app.requirements.expect("Windows requirements");
        assert_eq!(plan.manager, "windows-components");
        assert!(!plan.ready());
        assert!(plan.packages.is_empty());
        assert!(
            plan.missing
                .iter()
                .any(|item| item.id == "windows-components")
        );
        assert!(
            app.log
                .iter()
                .any(|line| line.contains("windows-components"))
        );
    }

    #[test]
    fn ios_delivery_is_explicit_and_cannot_change_during_a_build() {
        let (mut app, _) = Installer::new();
        app.target = InstallTarget::Ios;
        app.page = Page::Target;
        assert_eq!(app.ios_delivery, crate::backend::IosDelivery::Ipa);
        let _ = app.update(Message::IosDelivery(crate::backend::IosDelivery::Device));
        assert_eq!(app.ios_delivery, crate::backend::IosDelivery::Device);
        app.page = Page::Progress;
        let _ = app.update(Message::IosDelivery(crate::backend::IosDelivery::Ipa));
        assert_eq!(app.ios_delivery, crate::backend::IosDelivery::Device);
    }

    #[test]
    fn ipa_export_errors_name_the_export_stage() {
        for language in [
            Language::English,
            Language::German,
            Language::Spanish,
            Language::Portuguese,
            Language::Russian,
        ] {
            let notice = build_error_notice(
                "Build step failed: install\nExisting output differs",
                language,
                true,
            );
            assert!(notice.contains(language.t(L::ExportOutput)));
            assert!(notice.contains("Existing output differs"));
        }
    }

    #[test]
    fn settings_page_opens_closes_and_language_choice_is_saved() {
        let dir = std::env::temp_dir().join(format!("xnu-settings-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        preferences::use_test_dir(dir.clone());
        let (mut app, _) = Installer::new();
        assert!(!app.settings_open);
        let _ = app.update(Message::OpenSettings(true));
        assert!(app.settings_open);
        let _ = app.update(Message::SelectLanguage(Language::Portuguese));
        assert_eq!(app.language, Language::Portuguese);
        assert_eq!(preferences::load_language(), Some(Language::Portuguese));
        let _ = app.update(Message::Back);
        assert!(!app.settings_open);
        assert_eq!(app.page, Page::Target);
        let _ = std::fs::remove_dir_all(dir);
    }

    #[test]
    fn build_options_are_explicit_and_do_not_change_navigation() {
        let (mut app, _) = Installer::new();
        assert!(!app.clean_build);
        assert!(app.auto_cleanup);
        let _ = app.update(Message::CleanBuild(true));
        assert!(!app.clean_build);
        let _ = app.update(Message::ExportWithoutData(true));
        assert!(!app.ios_export_no_embed);
        app.page = Page::Setup;
        let _ = app.update(Message::BuildOptions(true));
        let _ = app.update(Message::CleanBuild(true));
        let _ = app.update(Message::ExportWithoutData(true));
        assert!(!app.ios_export_no_embed);
        let _ = app.update(Message::AutoCleanup(false));
        assert!(app.clean_build);
        assert!(!app.auto_cleanup);
        let _ = app.update(Message::Back);
        assert_eq!(app.page, Page::Setup);
        assert!(!app.build_options_open);
    }

    #[test]
    fn windows_folders_are_chosen_in_the_build_options_and_can_be_reset() {
        let (mut app, _) = Installer::new();
        app.host = Platform::Windows;
        app.page = Page::Setup;
        let work = PathBuf::from("C:\\bdsp");
        let _ = app.update(Message::FolderPicked(
            FolderSetting::Work,
            Some(work.clone()),
        ));
        let _ = app.update(Message::FolderPicked(
            FolderSetting::Install,
            Some(PathBuf::from("D:\\games")),
        ));
        assert_eq!(app.work_folder, Some(work));
        assert_eq!(app.install_folder, Some(PathBuf::from("D:\\games")));
        let _ = app.update(Message::ResetFolder(FolderSetting::Work));
        assert_eq!(app.work_folder, None);
        assert!(app.install_folder.is_some());
        let _ = app.update(Message::FolderPicked(FolderSetting::Work, None));
        assert_eq!(app.work_folder, None);
    }

    #[test]
    fn other_systems_ignore_the_windows_folder_messages() {
        let (mut app, _) = Installer::new();
        app.host = Platform::Mac;
        app.page = Page::Setup;
        let _ = app.update(Message::FolderPicked(
            FolderSetting::Work,
            Some(PathBuf::from("/data")),
        ));
        assert_eq!(app.work_folder, None);
    }

    #[test]
    fn export_without_game_data_is_chosen_on_the_review_page_and_never_set_automatically() {
        let (mut app, _) = Installer::new();
        assert!(!app.ios_export_no_embed);
        app.page = Page::Review;
        let _ = app.update(Message::ExportWithoutData(true));
        assert!(app.ios_export_no_embed);
        let _ = app.update(Message::ExportWithoutData(false));
        assert!(!app.ios_export_no_embed);
        assert_eq!(human_size(5_298_146_927), "5.3 GB");
        assert_eq!(human_size(229_768_040), "230 MB");
    }

    #[test]
    fn the_ipa_result_names_the_size_only_when_it_is_known() {
        use crate::i18n::Language;
        let (mut app, _) = Installer::new();
        app.exported_ipa = Some(PathBuf::from("exports/game.ipa"));
        app.game_library = Some(PathBuf::from("exports/Game Library"));
        for language in [
            Language::English,
            Language::German,
            Language::Spanish,
            Language::Portuguese,
            Language::Russian,
        ] {
            app.language = language;
            for with_library in [true, false] {
                app.game_library = with_library.then(|| PathBuf::from("exports/Game Library"));
                app.ios_export_no_embed = true;
                app.exported_ipa_size = None;
                let without = app.ipa_result_text();
                assert!(
                    !without.contains("()") && !without.contains("{size}"),
                    "{without}"
                );
                assert!(without.contains("game.ipa"), "{without}");
                app.exported_ipa_size = Some(229_768_040);
                assert!(app.ipa_result_text().contains("(230 MB)"));
            }
        }
    }

    #[test]
    fn copy_feedback_timer_cannot_clear_a_newer_copy() {
        let (mut app, _) = Installer::new();
        let older = Instant::now();
        let newer = older + Duration::from_millis(1);
        app.copied_log_line = Some((0, newer));
        let _ = app.update(Message::ClearCopiedLogLine(0, older));
        assert_eq!(app.copied_log_line, Some((0, newer)));
        let _ = app.update(Message::ClearCopiedLogLine(0, newer));
        assert!(app.copied_log_line.is_none());
    }

    #[test]
    fn cpu_choice_is_editable_only_in_linux_review() {
        let (mut app, _) = Installer::new();
        assert!(
            !app.portable_cpu,
            "Every launch defaults to CPU optimization"
        );
        app.demo = true;
        app.target = InstallTarget::Linux;
        app.page = Page::Review;
        app.portable_cpu = false;
        let _ = app.update(Message::OptimizeCpu(false));
        assert!(app.portable_cpu);
        app.page = Page::Progress;
        let _ = app.update(Message::OptimizeCpu(true));
        assert!(app.portable_cpu);
        app.page = Page::Review;
        app.target = InstallTarget::Mac;
        let _ = app.update(Message::OptimizeCpu(true));
        assert!(app.portable_cpu);
        app.target = InstallTarget::Linux;
        let _ = app.update(Message::OptimizeCpu(true));
        assert!(!app.portable_cpu);
    }

    #[test]
    fn backend_log_paths_hide_the_home_directory() {
        if let Some(home) = directories::UserDirs::new() {
            let full = home.home_dir().join("private/game.xci");
            let message = redact_home_path(&format!("Cannot read {}", full.display()));
            assert!(!message.contains(&home.home_dir().to_string_lossy().to_string()));
            assert!(message.replace('\\', "/").contains("~/private/game.xci"));
        }
    }

    #[test]
    fn disk_space_failure_is_specific_and_localized() {
        let detail =
            "MISSING  Disk space >= 40 GB free (21.7 GB free)\nNext step: Free up disk space.";
        for language in [Language::Spanish, Language::Portuguese] {
            let notice = disk_space_error(detail, language).unwrap();
            assert!(notice.contains("21,7 GB"));
            assert!(notice.contains("40 GB"));
            assert!(!notice.contains("{available}"));
        }
        let russian = disk_space_error(detail, Language::Russian).unwrap();
        assert!(russian.contains("Доступно: 21,7 ГБ"));
        assert!(russian.contains("Нужно: 40 ГБ"));
        assert_eq!(
            disk_space_error(detail, Language::English).as_deref(),
            Some(
                "There isn't enough free disk space for this build. Available: 21.7 GB · Required: 40 GB. Free up space and check again."
            )
        );
        assert_eq!(
            disk_space_error(detail, Language::German).as_deref(),
            Some(
                "Für diesen Build ist nicht genug Speicherplatz frei. Verfügbar: 21,7 GB · Benötigt: 40 GB. Gib Speicher frei und prüfe erneut."
            )
        );
    }

    #[test]
    fn internal_prerequisite_error_explains_failure_and_keeps_technical_log() {
        let (mut app, _) = Installer::new();
        app.language = Language::English;
        let error = "Prerequisite checker internal error: KeyError: 'detail'";
        let _ = app.update(Message::BackendEvent(
            app.backend_run_id,
            crate::backend::Event::Log {
                level: "error".into(),
                message: error.into(),
            },
        ));
        let _ = app.update(Message::BackendEvent(
            app.backend_run_id,
            crate::backend::Event::Finished { ok: false, code: 1 },
        ));
        assert_eq!(
            app.notice.as_deref(),
            Some(Language::English.t(L::PrerequisiteInternalError))
        );
        assert!(app.log.iter().any(|line| line.contains(error)));
        assert_eq!(
            build_error_notice(error, Language::German, false),
            Language::German.t(L::PrerequisiteInternalError)
        );
    }

    #[test]
    fn installation_result_keeps_the_real_destination_and_progress_does_not_spam_logs() {
        let (mut app, _) = Installer::new();
        app.target = InstallTarget::Mac;
        let initial = app.log.len();
        for completed in [0, 100, 200, 300] {
            let _ = app.update(Message::BackendEvent(
                app.backend_run_id,
                crate::backend::Event::Progress {
                    id: "clang".into(),
                    completed,
                    total: 300,
                },
            ));
        }
        assert_eq!(app.log.len(), initial);
        let destination = PathBuf::from("isolated/gui-installed-apps/BDSP.app");
        let _ = app.update(Message::BackendEvent(
            app.backend_run_id,
            crate::backend::Event::Artifact {
                kind: "installed_application".into(),
                path: destination.clone(),
            },
        ));
        assert_eq!(app.installed_app, Some(destination));
        assert!(app.log.last().unwrap().contains("gui-installed-apps"));
    }

    #[test]
    fn dependency_view_translates_explanations_without_changing_package_names() {
        let plan = crate::dependencies::Plan {
            manager: "dnf".into(),
            packages: vec!["clang".into(), "SDL3-devel".into()],
            missing: vec![crate::dependencies::Missing {
                id: "sdl3".into(),
                purpose: "Window, audio and controller support".into(),
            }],
            manual: vec![Language::English.t(L::FinishXcodeNote).into()],
            ..Default::default()
        };
        for language in Language::ALL {
            let description = localized_plan_description(&plan, language);
            assert!(description.contains(language.t(L::WindowAudioControllers)));
            assert!(description.contains(language.t(L::FinishXcodeNote)));
            assert!(description.contains("dnf: clang, SDL3-devel"));
        }
    }

    #[test]
    fn native_generator_error_dialog_keeps_module_phase_and_cause() {
        let cause = "bdsp_codegen [analyze/subsdk1]: error: cross-module entry outside module text";
        let detail = format!("Build step failed: eh_gen\n{cause}");
        for language in Language::ALL {
            let notice = build_error_notice(&detail, language, false);
            assert!(notice.contains(language.t(L::Generate)));
            assert!(notice.contains(cause));
        }
    }

    #[test]
    fn compiler_failure_names_the_stage_and_actual_cause() {
        let error = "Build step failed: runtime\nkernel.c:12:10: fatal error: 'sys/sysctl.h' file not found";
        for (language, stage) in [
            (Language::English, "Build runtime"),
            (Language::German, "Runtime bauen"),
            (Language::Spanish, "Compilar entorno de ejecución"),
            (Language::Portuguese, "Compilar ambiente de execução"),
            (Language::Russian, "Собрать среду выполнения"),
        ] {
            let notice = build_error_notice(error, language, false);
            assert!(notice.contains(stage));
            assert!(notice.contains("sys/sysctl.h"));
            assert!(!notice.contains("missing requirements"));
        }
    }

    #[test]
    fn simulated_hosts_offer_the_exact_targets_and_never_select_android() {
        for host in [Platform::Mac, Platform::Windows, Platform::Linux] {
            let (mut app, _) = Installer::with_options(Options {
                demo: true,
                platform: Some(host),
                ..Options::default()
            });
            let expected = match host {
                Platform::Mac => vec![
                    InstallTarget::Mac,
                    InstallTarget::Ios,
                    InstallTarget::Android,
                ],
                Platform::Windows => vec![
                    InstallTarget::Windows,
                    InstallTarget::Mac,
                    InstallTarget::Ios,
                    InstallTarget::Android,
                ],
                Platform::Linux => vec![
                    InstallTarget::Linux,
                    InstallTarget::Mac,
                    InstallTarget::Ios,
                    InstallTarget::Android,
                ],
            };
            assert_eq!(app.targets(), expected);
            assert_eq!(app.page, Page::Target);
            assert_eq!(app.target, InstallTarget::native(host));
            let _ = app.update(Message::SelectTarget(InstallTarget::Android));
            assert_eq!(app.target, InstallTarget::native(host));
            for target in expected
                .into_iter()
                .filter(|target| *target != InstallTarget::Android)
            {
                let _ = app.update(Message::SelectTarget(target));
                assert_eq!(app.target, target);
                let _ = app.update(Message::Review);
                assert_eq!(app.page, Page::Keys);
                let _ = app.update(Message::Back);
                assert_eq!(app.page, Page::Target);
                assert_eq!(app.target, target);
            }
            let unsupported = if host == Platform::Windows {
                InstallTarget::Linux
            } else {
                InstallTarget::Windows
            };
            let previous = app.target;
            let _ = app.update(Message::SelectTarget(unsupported));
            assert_eq!(app.target, previous);
        }
    }

    #[test]
    fn target_is_selected_before_inputs_and_survives_back_navigation() {
        let (mut app, _) = Installer::new();
        app.page = Page::Target;
        let _ = app.update(Message::SelectTarget(InstallTarget::Ios));
        let _ = app.update(Message::Review);
        assert_eq!(app.page, Page::Keys);
        assert_eq!(app.target, InstallTarget::Ios);
        let _ = app.update(Message::Back);
        assert_eq!(app.page, Page::Target);
        assert_eq!(app.target, InstallTarget::Ios);
        let _ = app.update(Message::SelectTarget(InstallTarget::Mac));
        assert_eq!(app.target, InstallTarget::Mac);
        assert_eq!(app.step_labels().len(), 9 + app.build_stages().len());
    }

    #[test]
    fn patch_step_is_only_visible_for_the_selected_code_mod() {
        use crate::progress::Stage;
        let (mut app, _) = Installer::new();
        assert!(!app.build_stages().contains(&Stage::Exefs));
        app.mods = vec![
            ModEntry {
                name: "Artwork only".into(),
                root: PathBuf::from("example"),
                has_romfs: true,
                has_exefs: false,
            },
            ModEntry {
                name: "Code mod".into(),
                root: PathBuf::from("example-code"),
                has_romfs: true,
                has_exefs: true,
            },
        ];
        app.selected_mod = Some("Artwork only".into());
        assert!(!app.build_stages().contains(&Stage::Exefs));
        app.selected_mod = Some("Code mod".into());
        assert!(app.build_stages().contains(&Stage::Exefs));
        app.mods_skipped = true;
        assert!(!app.build_stages().contains(&Stage::Exefs));
        app.page = Page::Progress;
        app.backend_status = BackendStatus::Running;
        app.build_progress.step("exefs", "skipped");
        app.build_progress.step("eh_gen", "started");
        let active = app.active_step();
        assert!(matches!(app.step_labels()[active], L::Generate));
        // 7 pages and the build steps of the host's default target; only the Apple targets have the shader step
        let shaders = usize::from(matches!(
            app.target,
            InstallTarget::Mac | InstallTarget::Ios
        ));
        assert_eq!(app.step_labels().len(), 7 + 9 + shaders);
        app.page = Page::Finished;
        assert_eq!(app.active_step(), app.step_labels().len() - 1);
    }

    #[test]
    fn demo_can_walk_through_all_views_without_real_inputs() {
        let (mut app, _) = Installer::new();
        app.page = Page::Keys;
        app.demo = true;
        app.pending = [None; 3];
        app.keys = None;
        app.base = None;
        app.update = None;
        for page in [
            Page::Game,
            Page::Update,
            Page::Firmware,
            Page::ModsFolder,
            Page::Mods,
            Page::Review,
        ] {
            let _ = app.update(Message::Review);
            assert_eq!(app.page, page);
        }
        let _ = app.update(Message::Review);
        assert_eq!(app.page, Page::Setup);
        let _ = app.update(Message::Back);
        assert_eq!(app.page, Page::Review);
        let _ = app.update(Message::Back);
        assert_eq!(app.page, Page::Mods);
        let _ = app.update(Message::Back);
        assert_eq!(app.page, Page::ModsFolder);
        let _ = app.update(Message::Back);
        assert_eq!(app.page, Page::Firmware);
        let _ = app.update(Message::Back);
        assert_eq!(app.page, Page::Update);
        let _ = app.update(Message::DemoInput);
        assert_eq!(
            app.update.as_ref().unwrap().name(),
            app.language.t(L::DemoUpdateFile)
        );
    }

    #[test]
    fn progress_and_diagnostics_survive_failure_stop_and_completion() {
        let (mut app, _) = Installer::new();
        app.page = Page::Keys;
        app.pending = [None; 3];
        app.page = Page::Game;
        app.pending[index(Slot::Base)] = Some(42);
        let _ = app.update(Message::Inspected(
            Slot::Base,
            42,
            Err("No NCA files".into()),
        ));
        assert!(app.log.last().unwrap().contains("ERROR: No NCA files"));
        assert_eq!(app.active_step(), 2);
        app.page = Page::Setup;
        app.demo = true;
        let _ = app.update(Message::Preview);
        assert_eq!(app.active_step(), 9);
        for _ in 0..20 {
            let _ = app.update(Message::Tick);
        }
        assert_eq!(app.active_step(), 11);
        let _ = app.update(Message::Back);
        assert!(
            app.log
                .last()
                .unwrap()
                .contains(app.language.t(L::LogStopped))
        );
        app.page = Page::Setup;
        app.demo = true;
        let _ = app.update(Message::Preview);
        for _ in 0..crate::progress::Stage::ALL.len() * 10 {
            let _ = app.update(Message::Tick);
        }
        assert_eq!(app.page, Page::Finished);
        assert!(
            app.log
                .last()
                .unwrap()
                .contains(app.language.t(L::LogComplete))
        );
        assert!(
            app.log
                .iter()
                .any(|line| line.contains("ERROR: No NCA files"))
        );
    }

    #[test]
    fn backend_file_count_updates_only_the_active_compile_stage() {
        let (mut app, _) = Installer::new();
        app.page = Page::Progress;
        app.backend_status = BackendStatus::Running;
        app.backend_run_id = 7;
        let _ = app.update(Message::BackendEvent(
            7,
            crate::backend::Event::Step {
                id: "eh_gen".into(),
                status: "complete".into(),
            },
        ));
        let _ = app.update(Message::BackendEvent(
            7,
            crate::backend::Event::Step {
                id: "clang".into(),
                status: "started".into(),
            },
        ));
        let _ = app.update(Message::BackendEvent(
            7,
            crate::backend::Event::Progress {
                id: "clang".into(),
                completed: 2368,
                total: 2369,
            },
        ));
        assert_eq!(
            app.active_step(),
            9 + app
                .build_stages()
                .iter()
                .position(|stage| *stage == crate::progress::Stage::Compile)
                .unwrap()
        );
        let clang = app.build_progress.stages[crate::progress::Stage::Compile.index()];
        assert_eq!((clang.completed, clang.total), (2368, 2369));
        assert!(clang.fraction() < 1.0);
        assert!(app.build_progress.stages[crate::progress::Stage::Generate.index()].done);
        let _ = app.update(Message::BackendEvent(
            6,
            crate::backend::Event::Progress {
                id: "clang".into(),
                completed: 2369,
                total: 2369,
            },
        ));
        assert_eq!(
            app.build_progress.stages[crate::progress::Stage::Compile.index()].completed,
            2368
        );
    }

    #[test]
    fn backend_log_lines_tell_the_extraction_step_and_a_silent_backend_is_still_working() {
        use crate::progress::{SILENCE, Stage};
        let (mut app, _) = Installer::new();
        app.page = Page::Progress;
        app.backend_status = BackendStatus::Running;
        app.backend_run_id = 3;
        let send = |app: &mut Installer, event| {
            let _ = app.update(Message::BackendEvent(3, event));
        };
        send(
            &mut app,
            crate::backend::Event::Step {
                id: "extract".into(),
                status: "started".into(),
            },
        );
        for message in [
            "1/5 unpack the game containers",
            "4/5 extract ExeFS and RomFS (the update applied to the base NCA)",
            "extract progress 420",
            "    recording the SHA-256 of the game files",
            "Original icons: 9 language variants",
        ] {
            send(
                &mut app,
                crate::backend::Event::Log {
                    level: "diagnostic".into(),
                    message: message.into(),
                },
            );
        }
        assert_eq!(app.build_progress.active, Stage::Extract);
        assert_eq!(app.build_progress.step, Some((4, 5)));
        let now = Instant::now();
        let text = app.build_progress.activity_text(app.language, now).unwrap();
        assert_eq!(text.headline, app.language.t(L::ActHashing));
        assert_eq!(
            text.detail.as_deref(),
            Some("Original icons: 9 language variants")
        );
        let later = app
            .build_progress
            .activity_text(app.language, now + SILENCE + Duration::from_secs(1))
            .unwrap();
        assert!(later.headline.contains(app.language.t(L::ActHashing)));
        assert_ne!(later.headline, text.headline);
        // Events of another run do not count as a sign of life.
        let _ = app.update(Message::BackendEvent(
            2,
            crate::backend::Event::Log {
                level: "diagnostic".into(),
                message: "2/5 classify NCAs".into(),
            },
        ));
        assert_eq!(app.build_progress.step, Some((4, 5)));
    }

    fn newer_release() -> crate::updates::Release {
        crate::updates::Release {
            tag: None,
            version: "9.9.9".into(),
            assets: vec![],
        }
    }

    #[test]
    fn a_newer_installer_is_offered_right_after_the_start() {
        let (mut app, _) = Installer::new();
        app.notice = None;
        let _ = app.update(Message::UpdateChecked(Ok(Some(newer_release()))));
        assert!(app.update_confirmation);
        let notice = app.notice.clone().unwrap();
        assert!(notice.contains("9.9.9") && notice.contains(env!("CARGO_PKG_VERSION")));
        let _ = app.update(Message::DismissNotice); // "Later": the header button stays
        assert!(app.notice.is_none() && app.available_update.is_some());
    }

    #[test]
    fn the_update_prompt_never_hides_another_message_or_interrupts_a_build() {
        let (mut app, _) = Installer::new();
        app.notice = Some("A build error".into());
        let _ = app.update(Message::UpdateChecked(Ok(Some(newer_release()))));
        assert!(!app.update_confirmation);
        assert_eq!(app.notice.as_deref(), Some("A build error"));
        assert!(app.available_update.is_some());

        let (mut app, _) = Installer::new();
        app.notice = None;
        app.backend_status = BackendStatus::Running;
        let _ = app.update(Message::UpdateChecked(Ok(Some(newer_release()))));
        assert!(!app.update_confirmation && app.notice.is_none());

        let (mut app, _) = Installer::new();
        app.notice = None;
        let _ = app.update(Message::UpdateChecked(Ok(None)));
        let _ = app.update(Message::UpdateChecked(Err("offline".into())));
        assert!(!app.update_confirmation && app.notice.is_none());
    }

    #[test]
    fn views_are_sequential_and_skipping_update_preserves_inputs() {
        let (mut app, _) = Installer::new();
        app.page = Page::Keys;
        app.pending = [None; 3];
        let _ = app.update(Message::Review);
        assert_eq!(app.page, Page::Keys);
        app.keys = Some(Source::fixture("prod.keys", "Keys"));
        let _ = app.update(Message::Review);
        assert_eq!(app.page, Page::Game);
        let _ = app.update(Message::Review);
        assert_eq!(app.page, Page::Game);
        app.base = Some(Source::fixture("game.nsp", "NSP"));
        let _ = app.update(Message::Review);
        assert_eq!(app.page, Page::Update);
        let _ = app.update(Message::Review);
        assert_eq!(app.page, Page::Firmware);
        if let Some(id) = app.firmware_pending {
            let _ = app.update(Message::FirmwareFound(id, None));
        }
        let _ = app.update(Message::SkipFirmware);
        assert_eq!(app.page, Page::ModsFolder);
        let _ = app.update(Message::Review);
        assert_eq!(app.page, Page::Mods);
        let _ = app.update(Message::ModsScanned(app.mods_scan_id, Ok(vec![])));
        let _ = app.update(Message::Review);
        assert_eq!(app.page, Page::Review);
        assert!(app.update.is_none());
        let _ = app.update(Message::Back);
        assert_eq!(app.page, Page::Mods);
        let _ = app.update(Message::Back);
        assert_eq!(app.page, Page::ModsFolder);
        let _ = app.update(Message::Back);
        assert_eq!(app.page, Page::Firmware);
        let _ = app.update(Message::Back);
        assert_eq!(app.page, Page::Update);
        let _ = app.update(Message::Back);
        assert_eq!(app.page, Page::Game);
        assert_eq!(app.base.as_ref().unwrap().name(), "game.nsp");
        assert!(app.keys.is_some());
    }

    #[test]
    fn exefs_only_mod_cannot_advance_as_romfs() {
        let (mut app, _) = Installer::new();
        app.page = Page::Mods;
        app.mods = vec![ModEntry {
            name: "Code mod".into(),
            root: PathBuf::from("/synthetic/Code mod"),
            has_romfs: false,
            has_exefs: true,
        }];
        app.selected_mod = Some("Code mod".into());
        assert!(!app.ready());
        let _ = app.update(Message::Review);
        assert_eq!(app.page, Page::Mods);
        app.selected_mod = None;
        assert!(app.ready());
    }

    #[test]
    fn code_mod_can_advance_to_a_separate_build_on_mac_ios_windows_and_linux() {
        let root = std::env::temp_dir().join(format!("installer-ips-ready-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&root);
        std::fs::create_dir_all(root.join("Code/ExeFS")).unwrap();
        std::fs::write(root.join("Code/ExeFS/0123.ips"), b"PATCHEOF").unwrap();
        std::fs::write(root.join("Code/ExeFS/subsdk1"), b"NSO0").unwrap();
        std::fs::create_dir_all(root.join("Code/RomFS")).unwrap();
        for (host, target, buildable) in [
            (Platform::Mac, InstallTarget::Mac, true),
            (Platform::Mac, InstallTarget::Ios, true),
            (Platform::Windows, InstallTarget::Windows, true),
            (Platform::Linux, InstallTarget::Linux, true),
        ] {
            let (mut app, _) = Installer::new();
            app.host = host;
            app.target = target;
            app.page = Page::Mods;
            app.mods = mod_support::scan_selected(&root.join("Code")).unwrap();
            app.selected_mod = Some("Code".into());
            assert_eq!(app.ready(), buildable, "{target:?}");
            let _ = app.update(Message::Review);
            assert_eq!(
                app.page,
                if buildable { Page::Review } else { Page::Mods },
                "{target:?}"
            );
        }
        std::fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn single_import_is_selected_once_and_refresh_preserves_vanilla_choice() {
        let (mut app, _) = Installer::new();
        app.page = Page::Mods;
        app.select_imported_mod = true;
        let entries = vec![ModEntry {
            name: "Example".into(),
            root: "/synthetic/Example".into(),
            has_romfs: true,
            has_exefs: false,
        }];
        let _ = app.update(Message::ModsScanned(app.mods_scan_id, Ok(entries.clone())));
        assert_eq!(app.selected_mod.as_deref(), Some("Example"));
        let _ = app.update(Message::SelectMod(None));
        let _ = app.update(Message::ModsScanned(app.mods_scan_id, Ok(entries)));
        assert_eq!(app.selected_mod, None);
    }

    #[test]
    fn no_automatic_keys_is_informational_and_manual_input_wins_races() {
        let (mut app, _) = Installer::new();
        app.page = Page::Keys;
        app.pending[index(Slot::Keys)] = Some(1);
        let _ = app.update(Message::KeysFound(1, None));
        assert!(app.notice.is_none());
        assert!(app.key_hint.is_some());
        app.pending[index(Slot::Keys)] = Some(3);
        let _ = app.update(Message::KeysFound(
            2,
            Some(Source::fixture("auto.keys", "Keys")),
        ));
        assert!(app.keys.is_none());
        let _ = app.update(Message::Inspected(
            Slot::Keys,
            3,
            Ok(Source::fixture("manual.keys", "Keys")),
        ));
        let _ = app.update(Message::KeysFound(2, None));
        assert_eq!(app.keys.as_ref().unwrap().name(), "manual.keys");
    }

    #[test]
    fn removed_input_cannot_be_restored_by_late_inspection() {
        let (mut app, _) = Installer::new();
        app.page = Page::Keys;
        app.pending = [None; 3];
        app.pending[index(Slot::Base)] = Some(1);
        let _ = app.update(Message::Remove(Slot::Base));
        let _ = app.update(Message::Inspected(
            Slot::Base,
            1,
            Ok(Source::fixture("old.xci", "XCI")),
        ));
        assert!(app.base.is_none());
        assert!(!app.ready());
    }

    #[test]
    fn replacing_input_discards_old_result_and_blocks_review_until_complete() {
        let (mut app, _) = Installer::new();
        app.page = Page::Keys;
        app.pending = [None; 3];
        app.page = Page::Game;
        app.base = Some(Source::fixture("previous.xci", "XCI"));
        app.keys = Some(Source::fixture("prod.keys", "Keys"));
        app.pending[index(Slot::Base)] = Some(2);
        let _ = app.update(Message::Review);
        assert_eq!(app.page, Page::Game);
        let _ = app.update(Message::Inspected(
            Slot::Base,
            1,
            Ok(Source::fixture("old.xci", "XCI")),
        ));
        assert_eq!(app.base.as_ref().unwrap().name(), "previous.xci");
        let _ = app.update(Message::Inspected(
            Slot::Base,
            2,
            Ok(Source::fixture("new.xci", "XCI")),
        ));
        let _ = app.update(Message::Review);
        assert_eq!(app.page, Page::Update);
        assert_eq!(app.base.as_ref().unwrap().name(), "new.xci");
    }
    #[test]
    fn device_selection_stays_explicit_and_stale_refreshes_cannot_replace_it() {
        let (mut app, _) = Installer::new();
        app.ios_team.clear();
        app.host = Platform::Mac;
        app.target = InstallTarget::Ios;
        app.page = Page::Target;
        app.ios_devices_open = true;
        app.ios_devices_busy = true;
        app.ios_devices_generation = 2;
        let devices = vec![
            crate::ios_devices::Device {
                id: "one".into(),
                name: "iPad".into(),
                model: "Test".into(),
                connected: true,
                wifi: false,
            },
            crate::ios_devices::Device {
                id: "two".into(),
                name: "iPhone".into(),
                model: "Test".into(),
                connected: true,
                wifi: true,
            },
        ];
        let _ = app.update(Message::IosDevicesLoaded(1, Ok(devices.clone())));
        assert!(app.ios_devices_busy);
        let _ = app.update(Message::IosDevicesLoaded(2, Ok(devices.clone())));
        assert!(!app.ready());
        let _ = app.update(Message::SelectIosDevice("two".into()));
        assert!(app.ready());
        for id in ["three", "four"] {
            let mut device = devices[0].clone();
            device.id = id.into();
            app.ios_devices.push(device);
        }
        let _ = app.update(Message::IosDevicesPage(1));
        assert_eq!(app.ios_devices_page, 1);
        assert_eq!(app.ios_device.as_deref(), Some("two"));
        let _ = app.update(Message::IosDevicesPage(127));
        assert_eq!(app.ios_devices_page, 1);
        let _ = app.update(Message::IosDevicesPage(-1));
        assert_eq!(app.ios_devices_page, 0);
        let _ = app.update(Message::IosDevicesLoaded(2, Err("test failure".into())));
        assert!(!app.ready());
        assert_eq!(app.ios_device.as_deref(), Some("two"));
        let _ = app.update(Message::IosDevicesLoaded(2, Ok(devices)));
        assert!(app.ready());
        let _ = app.update(Message::Review);
        assert_eq!(app.page, Page::Target);
        assert!(app.ios_signing_open);
        app.ios_signing_busy = false;
        assert!(!app.ready());
        let _ = app.update(Message::IosTeamChanged("testteam01".into()));
        assert!(app.ready());
        let _ = app.update(Message::Review);
        assert_eq!(app.page, Page::Keys);
        assert!(!app.ios_devices_open);
        app.page = Page::Setup;
        app.ios_devices_open = true;
        let _ = app.update(Message::Review);
        assert_eq!(app.page, Page::Setup);
        assert!(!app.ios_devices_open);
    }
    #[test]
    fn signing_requires_explicit_valid_team_and_preserves_a_manual_choice_on_refresh() {
        let (mut app, _) = Installer::new();
        app.page = Page::Target;
        app.host = Platform::Mac;
        app.target = InstallTarget::Ios;
        app.ios_signing_open = true;
        app.ios_signing_busy = true;
        app.ios_signing_generation = 2;
        let teams = vec![
            crate::ios_signing::Team {
                id: "TESTTEAM01".into(),
                name: "First team".into(),
            },
            crate::ios_signing::Team {
                id: "TESTTEAM02".into(),
                name: "Second team".into(),
            },
        ];
        app.ios_team.clear();
        let _ = app.update(Message::IosSigningLoaded(1, Ok(teams.clone())));
        assert!(app.ios_signing_busy);
        let _ = app.update(Message::IosSigningLoaded(2, Ok(teams.clone())));
        assert!(!app.ready());
        let _ = app.update(Message::SelectIosTeam(teams[1].clone()));
        assert!(app.ready());
        let _ = app.update(Message::IosTeamChanged("bad".into()));
        assert!(!app.ready());
        let _ = app.update(Message::IosTeamChanged("manual0001".into()));
        assert!(app.ready());
        let _ = app.update(Message::IosSigningLoaded(2, Ok(teams)));
        assert_eq!(app.ios_team, "MANUAL0001");
        let _ = app.update(Message::ManualIosTeam);
        assert!(app.ios_team.is_empty());
        assert!(!app.ready());
    }
    #[test]
    fn signing_preflight_is_only_a_direct_device_build_step_before_generation() {
        let (mut app, _) = Installer::new();
        app.target = InstallTarget::Ios;
        app.ios_delivery = crate::backend::IosDelivery::Ipa;
        assert!(
            !app.build_stages()
                .contains(&crate::progress::Stage::Signing)
        );
        app.ios_delivery = crate::backend::IosDelivery::Device;
        let stages = app.build_stages();
        assert!(
            stages
                .iter()
                .position(|s| *s == crate::progress::Stage::Signing)
                .unwrap()
                < stages
                    .iter()
                    .position(|s| *s == crate::progress::Stage::Generate)
                    .unwrap()
        );
        app.target = InstallTarget::Mac;
        assert!(
            !app.build_stages()
                .contains(&crate::progress::Stage::Signing)
        );
    }
    fn lines(values: &[&str]) -> Vec<String> {
        values.iter().map(|v| v.to_string()).collect()
    }

    #[test]
    fn setup_output_is_streamed_without_repeating_lines() {
        let seen = lines(&["a", "b", "c"]);
        assert_eq!(unseen_lines(&[], &seen), &seen[..]);
        assert_eq!(unseen_lines(&seen, &lines(&["a", "b", "c", "d"])), ["d"]);
        // the window of last lines scrolled: the first line fell out
        assert_eq!(unseen_lines(&seen, &lines(&["b", "c", "d"])), ["d"]);
        assert!(unseen_lines(&seen, &seen).is_empty());
    }

    #[test]
    fn a_failed_components_install_is_in_the_log_with_step_and_error_and_stays_visible() {
        let (mut app, _) = Installer::with_options(Options {
            platform: Some(Platform::Windows),
            capture: Some(std::env::temp_dir().join("setup-failure-capture")),
            scenes: vec!["setup-dependencies"],
            ..Options::default()
        });
        assert_eq!(
            app.requirements.as_ref().map(|p| p.manager.as_str()),
            Some("windows-components")
        );
        let mut progress = crate::components::SetupProgress::default();
        let now = std::time::Instant::now();
        progress.apply(r#"{"event": "steps", "total": 12}"#, now);
        progress.apply(
            r#"{"event": "step", "index": 2, "id": "qt", "phase": "unpack"}"#,
            now,
        );
        progress.apply("Unpacking qtbase", now);
        progress.apply("Cannot create output file", now);
        app.fail_setup(progress.clone(), "Qt archive is corrupt");
        // the same output arriving again (a late tick) adds nothing
        app.fail_setup(progress, "Qt archive is corrupt");
        let text = app.log.join("\n");
        assert!(text.contains("[SETUP] Step 3 of 13: qt (unpack)"), "{text}");
        assert!(
            text.contains(
                "Install tools failed in step 3 of 13, qt (unpack): Qt archive is corrupt"
            )
        );
        assert_eq!(text.matches("Cannot create output file").count(), 1);
        assert_eq!(text.matches("Unpacking qtbase").count(), 1);
        let failure = app.setup_failure.clone().expect("a card stays on screen");
        assert!(failure.step.contains("qt") && failure.error == "Qt archive is corrupt");
        assert!(app.requirements.is_some(), "Retry needs the plan");
        let _ = app.handle(Message::InstallRequirements);
        assert!(app.setup_failure.is_none() && app.setup_busy);
        assert!(app.log.last().unwrap().contains("Install tools started"));
    }

    #[test]
    fn the_system_block_is_written_once_at_start_without_the_home_directory() {
        let (app, _) = Installer::with_options(Options::default());
        let system: Vec<&String> = app.log.iter().filter(|l| l.contains("[SYSTEM]")).collect();
        assert_eq!(
            system
                .iter()
                .filter(|l| l.contains(concat!("Installer ", env!("CARGO_PKG_VERSION"))))
                .count(),
            1
        );
        let text = system
            .iter()
            .map(|l| l.as_str())
            .collect::<Vec<_>>()
            .join("\n");
        assert!(text.contains(std::env::consts::ARCH));
        assert!(text.contains("selected target:") && text.contains("language:"));
        assert!(text.contains("log file:") && text.contains("Data folder:"));
        assert!(app.log[0].starts_with("001 [SYSTEM]"));
        if let Some(home) = directories::UserDirs::new() {
            let home = home.home_dir().to_string_lossy().into_owned();
            assert!(!text.contains(&home), "{text}");
            let line =
                crate::sysinfo::header("Windows", "Windows", "en", Some(&home_child(&home)), None)
                    .join("\n");
            assert!(!redact_home_path(&line).contains(&home));
        }
    }

    fn home_child(home: &str) -> PathBuf {
        PathBuf::from(home).join("AppData").join("strahlender")
    }

    static ENV: std::sync::Mutex<()> = std::sync::Mutex::new(());

    const STUB_DRIVER: &str = r#"import json, sys
def emit(**event):
    print(json.dumps(event), flush=True)
emit(event="hello", protocol=2)
emit(event="step", id="prepare", status="started")
emit(event="progress", id="prepare", completed=1, total=2)
emit(event="log", level="info", message=" ".join(sys.argv[1:]))
emit(event="artifact", kind="installed_application", path="stub-app")
emit(event="result", ok=True, code=0)
"#;

    #[test]
    #[cfg(debug_assertions)]
    fn window_and_cli_build_the_same_request_and_event_stream() {
        use iced::futures::StreamExt;
        let _guard = ENV.lock().unwrap_or_else(|poisoned| poisoned.into_inner());
        let native = Platform::native();
        if !crate::flow::platform_backend_supported(
            native,
            InstallTarget::native(native),
            std::env::consts::ARCH,
        ) {
            return; // this host has no build path (for example an Intel Mac), so there is nothing to run
        }
        let dir = std::env::temp_dir().join(format!("headless-parity-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        let driver = dir.join("root/scripts/install");
        std::fs::create_dir_all(&driver).unwrap();
        std::fs::write(driver.join("driver.py"), STUB_DRIVER).unwrap();
        let base = dir.join("base");
        std::fs::create_dir_all(&base).unwrap();
        let keys = dir.join("prod.keys");
        std::fs::write(&keys, b"").unwrap();
        unsafe {
            std::env::set_var("BDSP_INSTALLER_DEV_CHECKOUT", "1");
            std::env::set_var("BDSP_INSTALLER_DEV_ROOT", dir.join("root"));
            std::env::set_var("BDSP_MODS_DIR", dir.join("mods"));
            std::env::remove_var("BDSP_INSTALLER_RUNTIME");
        }
        let host = Platform::native();
        let arch = std::env::consts::ARCH;
        let target = InstallTarget::native(host);
        let flag = crate::flow::target_name(target, arch).unwrap();

        let (mut app, _) = Installer::new();
        app.target = target;
        app.base = Some(sources::Source {
            path: base.clone(),
            description: String::new(),
        });
        app.keys = Some(sources::Source {
            path: keys.clone(),
            description: String::new(),
        });
        app.ios_delivery = crate::backend::IosDelivery::Device;
        app.ios_team = String::new();
        app.ios_device = None;
        app.ios_profile = None;
        app.ios_new_profile = None;
        app.auto_cleanup = false;
        app.portable_cpu = false;
        app.clean_build = false;
        app.ios_export_no_embed = false;
        app.selected_mod = None;
        app.firmware = None;
        app.update = None;
        let gui_request = crate::flow::build_request(app.request_inputs()).unwrap();

        let args: Vec<String> = [
            "--target",
            flag,
            "--keys",
            keys.to_str().unwrap(),
            "--base",
            base.to_str().unwrap(),
            "--no-updates",
        ]
        .map(String::from)
        .to_vec();
        let config = crate::headless::parse(&args).unwrap();
        let cli_plan = crate::headless::plan(&config, host, arch).unwrap();
        assert_eq!(cli_plan.request, gui_request);

        let runtime = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .unwrap();
        let gui_events: Vec<_> = runtime
            .block_on(
                backend_stream(
                    1,
                    Arc::new(AtomicBool::new(false)),
                    app.mods_folder.clone(),
                    None,
                    gui_request,
                )
                .collect::<Vec<_>>(),
            )
            .into_iter()
            .map(|(_, event)| event)
            .collect();
        let mut cli_events = Vec::new();
        let code =
            crate::headless::run_build(cli_plan, &runtime, |event| cli_events.push(event.clone()));
        unsafe {
            std::env::remove_var("BDSP_INSTALLER_DEV_CHECKOUT");
            std::env::remove_var("BDSP_INSTALLER_DEV_ROOT");
            std::env::remove_var("BDSP_MODS_DIR");
        }
        let _ = std::fs::remove_dir_all(&dir);

        assert_eq!(code, 0, "{cli_events:?}");
        assert_eq!(gui_events, cli_events);
        assert!(matches!(
            cli_events.last(),
            Some(crate::backend::Event::Finished { ok: true, .. })
        ));
        assert!(
            cli_events
                .iter()
                .any(|event| matches!(event, crate::backend::Event::Artifact { kind, .. } if kind == "installed_application"))
        );
    }

    #[test]
    fn window_and_cli_start_the_driver_with_the_same_arguments_and_environment() {
        use crate::driver_plan::{DriverPlan, Python, tests::facts};
        let _guard = ENV.lock().unwrap_or_else(|poisoned| poisoned.into_inner());
        let dir = std::env::temp_dir().join(format!("driver-parity-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        let base = dir.join("base");
        std::fs::create_dir_all(&base).unwrap();
        let keys = dir.join("prod.keys");
        std::fs::write(&keys, b"").unwrap();
        let mod_folder = dir.join("library/alpha");
        std::fs::create_dir_all(mod_folder.join("romfs")).unwrap();
        std::fs::write(mod_folder.join("romfs/file.bin"), b"x").unwrap();
        let library = dir.join("library");
        unsafe { std::env::set_var("BDSP_MODS_DIR", dir.join("default-mods")) };

        let arch = std::env::consts::ARCH;
        let ipa = [("ios_delivery", "ipa")];
        let ipa_new_profile = [
            ("ios_delivery", "ipa"),
            ("ios_profile_id", "PROFILE1"),
            ("ios_export_no_embed", "true"),
            ("clean_build", "true"),
        ];
        let device = [
            ("ios_delivery", "device"),
            ("ios_device", "UDID-1"),
            ("ios_team", "ABCDE12345"),
        ];
        type Case<'a> = (Platform, InstallTarget, &'a [(&'a str, &'a str)], bool);
        let cases: [Case; 13] = [
            (Platform::Mac, InstallTarget::Mac, &[], false),
            (Platform::Mac, InstallTarget::Mac, &[], true),
            (Platform::Mac, InstallTarget::Ios, &device, false),
            (Platform::Mac, InstallTarget::Ios, &device, true),
            (Platform::Mac, InstallTarget::Ios, &ipa, false),
            (Platform::Mac, InstallTarget::Ios, &ipa, true),
            (Platform::Mac, InstallTarget::Ios, &ipa_new_profile, true),
            (Platform::Linux, InstallTarget::Linux, &[], false),
            (
                Platform::Linux,
                InstallTarget::Linux,
                &[("portable_cpu", "true")],
                true,
            ),
            (Platform::Windows, InstallTarget::Windows, &[], false),
            (Platform::Windows, InstallTarget::Windows, &[], true),
            (
                Platform::Windows,
                InstallTarget::Windows,
                &[("clean_build", "true"), ("auto_cleanup", "true")],
                false,
            ),
            (
                Platform::Linux,
                InstallTarget::Linux,
                &[("auto_cleanup", "yes")],
                false,
            ),
        ];
        let mut compared = 0;
        for (host, target, options, with_mod) in cases {
            if !crate::flow::platform_backend_supported(host, target, arch) {
                continue;
            }
            let flag = crate::flow::target_name(target, arch).unwrap();
            let (mut app, _) = Installer::with_options(crate::platform::Options {
                platform: Some(host),
                ..Default::default()
            });
            app.target = target;
            app.base = Some(sources::Source {
                path: base.clone(),
                description: String::new(),
            });
            app.keys = Some(sources::Source {
                path: keys.clone(),
                description: String::new(),
            });
            app.mods_folder = mod_support::folder_for(host, target);
            // Saved preferences of the machine running the test must not leak in.
            app.ios_delivery = crate::backend::IosDelivery::Device;
            app.ios_team = String::new();
            app.ios_device = None;
            app.ios_profile = None;
            app.ios_new_profile = None;
            app.auto_cleanup = false;
            app.portable_cpu = false;
            app.clean_build = false;
            app.ios_export_no_embed = false;
            app.firmware = None;
            app.update = None;
            app.selected_mod = None;
            app.mods.clear();
            if with_mod {
                app.mods = mod_support::scan_selected(&mod_folder).unwrap();
                app.mods_folder = Some(mod_support::library_for_selection(&mod_folder).unwrap());
                app.selected_mod = app.mods.first().map(|entry| entry.name.clone());
            }
            for (key, value) in options {
                match *key {
                    "ios_delivery" => {
                        app.ios_delivery = if *value == "ipa" {
                            crate::backend::IosDelivery::Ipa
                        } else {
                            crate::backend::IosDelivery::Device
                        }
                    }
                    "ios_device" => app.ios_device = Some((*value).into()),
                    "ios_team" => app.ios_team = (*value).into(),
                    "ios_profile_id" => app.ios_new_profile = Some((*value).into()),
                    "portable_cpu" => app.portable_cpu = *value == "true",
                    "clean_build" => app.clean_build = *value == "true",
                    "ios_export_no_embed" => app.ios_export_no_embed = *value == "true",
                    "auto_cleanup" => app.auto_cleanup = matches!(*value, "true" | "yes"),
                    other => panic!("{other}"),
                }
            }
            let gui_request = crate::flow::build_request(app.request_inputs()).unwrap();

            let mut args: Vec<String> = [
                "--target",
                flag,
                "--keys",
                keys.to_str().unwrap(),
                "--base",
                base.to_str().unwrap(),
            ]
            .map(String::from)
            .to_vec();
            if with_mod {
                args.extend(["--mod".into(), mod_folder.to_str().unwrap().into()]);
            }
            for (key, value) in options {
                args.extend(["--option".into(), format!("{key}={value}")]);
            }
            let config = crate::headless::parse(&args).unwrap();
            let cli = crate::headless::plan(&config, host, arch).unwrap();
            assert_eq!(cli.request, gui_request, "{host:?} {flag} {options:?}");
            assert_eq!(cli.mods_folder, app.mods_folder);
            assert_eq!(cli.selected_mod, app.selected_mod);
            if with_mod {
                assert_eq!(
                    app.mods_folder.as_deref(),
                    library.canonicalize().ok().as_deref()
                );
            }

            let host_facts = facts(host);
            let python = Python {
                program: "python".into(),
                private: true,
            };
            let root = std::path::Path::new("root");
            let gui_plan = DriverPlan::new(
                &host_facts,
                &python,
                root,
                &gui_request,
                app.mods_folder.as_deref(),
                app.selected_mod.as_deref(),
            )
            .unwrap();
            let cli_plan = DriverPlan::new(
                &host_facts,
                &python,
                root,
                &cli.request,
                cli.mods_folder.as_deref(),
                cli.selected_mod.as_deref(),
            )
            .unwrap();
            assert_eq!(gui_plan, cli_plan, "{host:?} {flag} {options:?}");

            let args: Vec<_> = gui_plan.args.iter().map(|a| a.to_string_lossy()).collect();
            let has = |flag: &str| args.iter().any(|arg| arg == flag);
            assert!(has(flag));
            assert_eq!(has("--mod-name"), with_mod);
            assert_eq!(
                has("--ios-export-dir"),
                options.contains(&("ios_delivery", "ipa"))
            );
            assert_eq!(has("--windows-catalog"), flag.starts_with("windows"));
            compared += 1;
        }
        unsafe { std::env::remove_var("BDSP_MODS_DIR") };
        let _ = std::fs::remove_dir_all(&dir);
        assert!(
            compared >= 4,
            "only {compared} combinations were supported here"
        );
    }
}
