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

#[derive(Debug, Clone)]
pub enum Message {
    ShowInstalledApp,
    InstallationRevealed(Result<(), String>),
    OpenRepository,
    RepositoryOpened(Result<(), ()>),
    ToggleTheme,
    SelectTarget(InstallTarget),
    OptimizeCpu(bool),
    BuildOptions(bool),
    CleanBuild(bool),
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
    Preview,
    RequirementsChecked(u64, Result<crate::dependencies::Plan, String>),
    InstallRequirements,
    RequirementsOpened(Result<(), String>),
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

#[derive(Debug, Clone, Default)]
pub struct RestoredInputs {
    keys: Option<Source>,
    base: Option<Source>,
    update: Option<Source>,
    mod_folder: Option<PathBuf>,
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
    auto_cleanup: bool,
    build_options_open: bool,
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
    copied_log_line: Option<(usize, Instant)>,
    requirements: Option<crate::dependencies::Plan>,
    requirements_busy: bool,
    available_update: Option<crate::updates::Release>,
    updating: bool,
    update_confirmation: bool,
    setup_log_length: usize,
    requirements_run_id: u64,
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

fn build_error_notice(detail: &str, language: Language) -> String {
    if detail.contains("Prerequisite checker internal error:") {
        return language.t(L::PrerequisiteInternalError).into();
    }
    if let Some(failure) = detail.strip_prefix("Build step failed: ")
        && let Some((stage, cause)) = failure.split_once('\n')
    {
        let label = match crate::progress::Stage::from_id(stage) {
            Some(crate::progress::Stage::Source) => L::FetchSource,
            Some(crate::progress::Stage::Requirements) => L::Tools,
            Some(crate::progress::Stage::Extract) => L::Prepare,
            Some(crate::progress::Stage::Exefs) => L::ExeFS,
            Some(crate::progress::Stage::Generate) => L::Generate,
            Some(crate::progress::Stage::Compile) => L::Compile,
            Some(crate::progress::Stage::Images) => L::Images,
            Some(crate::progress::Stage::Runtime) => L::Runtime,
            Some(crate::progress::Stage::Package) => L::Package,
            Some(crate::progress::Stage::Install) => L::Install,
            None => return detail.into(),
        };
        return language
            .t(L::BuildStepError)
            .replace("{stage}", language.t(label))
            .replace("{cause}", cause);
    }
    disk_space_error(detail, language).unwrap_or_else(|| detail.into())
}

impl Installer {
    #[cfg(test)]
    pub fn new() -> (Self, Task<Message>) {
        Self::with_options(Options::default())
    }

    pub fn with_options(options: Options) -> (Self, Task<Message>) {
        let host = options.platform.unwrap_or_else(Platform::native);
        let demo = options.demo;
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
            language: Language::detect(),
            key_hint: None,
            log: Vec::new(),
            demo,
            target: InstallTarget::native(host),
            portable_cpu: false,
            clean_build: false,
            auto_cleanup: true,
            build_options_open: false,
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
            copied_log_line: None,
            requirements: None,
            requirements_busy: false,
            available_update: None,
            updating: false,
            update_confirmation: false,
            setup_log_length: 0,
            requirements_run_id: 0,
        };
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
            Task::none()
        };
        let task = if !app.demo && app.capture.is_none() {
            Task::batch([
                task,
                Task::perform(
                    async {
                        tokio::task::spawn_blocking(crate::updates::check)
                            .await
                            .unwrap_or_else(|e| Err(e.to_string()))
                    },
                    Message::UpdateChecked,
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
        let task = self.handle(message);
        if self.capture.is_none() && self.preferred_size() != previous {
            Task::batch([task, self.fit_window()])
        } else {
            task
        }
    }

    fn handle(&mut self, message: Message) -> Task<Message> {
        match message {
            Message::UpdateChecked(result) => match result {
                Ok(release) => self.available_update = release,
                Err(error) => self.record("UPDATE", &error),
            },
            Message::ShowUpdateDetails => {
                if let Some(release) = &self.available_update {
                    self.update_confirmation = true;
                    self.notice = Some(format!(
                        "{} {}. {}",
                        self.language.t(L::UpdateAvailable),
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
                        async move {
                            tokio::task::spawn_blocking(move || crate::updates::download(&release))
                                .await
                                .unwrap_or_else(|e| Err(e.to_string()))
                        },
                        Message::UpdateDownloaded,
                    );
                }
            }
            Message::UpdateDownloaded(result) => match result {
                Ok(path) => {
                    return Task::perform(
                        async move {
                            tokio::task::spawn_blocking(move || crate::updates::apply(&path))
                                .await
                                .unwrap_or_else(|e| Err(e.to_string()))
                        },
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
                let log = crate::dependencies::read_setup_log();
                if log.len() != self.setup_log_length {
                    let new = log.get(self.setup_log_length..).unwrap_or(&log);
                    for line in new.lines() {
                        self.record("SETUP", &redact_home_path(line));
                    }
                    self.setup_log_length = log.len();
                }
                match result {
                    Ok(plan) if plan.ready() => {
                        self.requirements = Some(plan);
                        return self.handle(Message::Preview);
                    }
                    Ok(plan) => {
                        self.record("SETUP", &plan.description());
                        self.requirements = Some(plan);
                    }
                    Err(error) => self.notice = Some(error),
                }
            }
            Message::InstallRequirements => {
                self.setup_log_length = 0;
                if let Some(plan) = self.requirements.clone() {
                    return Task::perform(
                        async move {
                            tokio::task::spawn_blocking(move || crate::dependencies::install(&plan))
                                .await
                                .unwrap_or_else(|e| Err(e.to_string()))
                        },
                        Message::RequirementsOpened,
                    );
                }
            }
            Message::RequirementsOpened(result) => match result {
                Ok(()) => {
                    self.record(
                        "SETUP",
                        "Complete the installation in the terminal, then check again here.",
                    );
                    self.requirements = None;
                }
                Err(error) => self.notice = Some(error),
            },
            Message::InputsRestored(restored) => {
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
            }
            Message::ShowNoticeDetails => {
                self.notice = None;
                self.details = true;
            }
            Message::ShowInstalledApp if self.backend_status == BackendStatus::Passed => {
                if let Some(path) = self.installed_app.clone() {
                    return Task::perform(
                        async move {
                            tokio::task::spawn_blocking(move || {
                                crate::backend::reveal_installed_application(path)
                            })
                            .await
                            .unwrap_or_else(|error| Err(error.to_string()))
                        },
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
                self.mods_skipped = false;
                self.mods_folder = mod_support::folder_for(self.host, target);
                self.chosen_mod_folder = None;
                self.select_imported_mod = false;
                self.mods.clear();
                self.selected_mod = None;
                self.mods_scan_id += 1;
                self.mods_scanning = false;
            }
            Message::BuildOptions(open) if self.page == Page::Setup => {
                self.build_options_open = open;
            }
            Message::CleanBuild(enabled) if self.page == Page::Setup => {
                self.clean_build = enabled;
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
                    async move {
                        tokio::task::spawn_blocking(move || match chosen {
                            Some(path) => mod_support::scan_selected(&path),
                            None => mod_support::scan(&folder),
                        })
                        .await
                        .unwrap_or_else(|error| Err(error.to_string()))
                    },
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
                        if self
                            .selected_mod
                            .as_ref()
                            .is_some_and(|name| !self.mods.iter().any(|item| &item.name == name))
                        {
                            self.selected_mod = None;
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
                    async move {
                        tokio::task::spawn_blocking(move || mod_support::open_folder(&folder))
                            .await
                            .unwrap_or_else(|error| Err(error.to_string()))
                    },
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
                return self.handle(Message::RefreshMods);
            }
            Message::SelectMod(selection) if self.page == Page::Mods => {
                if selection
                    .as_ref()
                    .is_none_or(|name| self.mods.iter().any(|item| &item.name == name))
                {
                    self.selected_mod = selection;
                    self.notice = None;
                }
            }
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
                self.details = false;
                self.page = match self.page {
                    Page::Target => Page::Keys,
                    Page::Keys => Page::Game,
                    Page::Game => Page::Update,
                    Page::Update => Page::ModsFolder,
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
                if self.page == Page::Mods && !self.demo && self.capture.is_none() {
                    return self.handle(Message::RefreshMods);
                }
            }
            Message::SkipMods if matches!(self.page, Page::ModsFolder | Page::Mods) => {
                self.mods_skipped = true;
                self.selected_mod = None;
                self.page = Page::Review;
                self.details = false;
                self.notice = None;
                self.hovered = None;
                self.drag_active = false;
            }
            Message::Back if self.page == Page::Progress && self.cleanup_busy => {}
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
                    Page::Review if self.mods_skipped => Page::Update,
                    Page::Review => Page::Mods,
                    Page::Mods => Page::ModsFolder,
                    Page::ModsFolder => Page::Update,
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
                            async move {
                                tokio::task::spawn_blocking(move || {
                                    crate::dependencies::inspect(target)
                                })
                                .await
                                .unwrap_or_else(|e| Err(e.to_string()))
                            },
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
                    self.build_options_open = false;
                    self.cleanup_busy = false;
                    self.motion.snap(0.0);
                    self.last_frame = None;
                    self.backend_run_id += 1;
                    let run_id = self.backend_run_id;
                    let cancelled = Arc::new(AtomicBool::new(false));
                    self.backend_cancel = Some(cancelled.clone());
                    self.record("BACKEND", self.language.t(L::LogBuildStart));
                    let (Some(base), Some(keys)) = (&self.base, &self.keys) else {
                        self.backend_status = BackendStatus::Failed;
                        self.record("BACKEND", self.language.t(L::MissingInput));
                        self.notice = Some(self.language.t(L::MissingInput).into());
                        return Task::none();
                    };
                    let target = match self.target {
                        InstallTarget::Mac => "macos",
                        InstallTarget::Linux => "linux",
                        InstallTarget::Ios => "ios",
                        _ => unreachable!("unsupported target was checked above"),
                    };
                    return Task::run(
                        crate::backend::build(
                            run_id,
                            cancelled,
                            self.mods_folder.clone(),
                            self.selected_mod.clone(),
                            crate::backend::BuildRequest {
                                target,
                                portable_cpu: self.portable_cpu,
                                clean_build: self.clean_build,
                                auto_cleanup: self.auto_cleanup,
                                base: base.path.clone(),
                                prod_keys: keys.path.clone(),
                                update: self.update.as_ref().map(|source| source.path.clone()),
                                mod_root: self
                                    .selected_mod
                                    .as_ref()
                                    .and_then(|name| {
                                        self.mods.iter().find(|item| &item.name == name)
                                    })
                                    .map(|item| item.root.clone()),
                                mod_name: self.selected_mod.clone(),
                            },
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
                crate::backend::Event::Log { level, message } => {
                    let message = redact_home_path(&message);
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
                        self.notice = Some(build_error_notice(&detail, self.language));
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

    // Diagnostic messages intentionally exclude file paths and key contents.
    fn record(&mut self, step: &str, message: &str) {
        self.log
            .push(format!("{:03} [{step}] {message}", self.log.len() + 1));
    }

    fn persist_preferences(&self) -> bool {
        self.capture.is_none() && !self.demo && !cfg!(test)
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
        let mut labels = vec![L::Target, L::Keys, L::Base, L::Update];
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
        let code_mod = !self.mods_skipped
            && self.mods.iter().any(|entry| {
                self.selected_mod.as_deref() == Some(entry.name.as_str()) && entry.has_exefs
            });
        crate::progress::Stage::ALL
            .into_iter()
            .filter(|stage| *stage != crate::progress::Stage::Exefs || code_mod)
            .collect()
    }

    fn build_labels(&self) -> [L; 10] {
        [
            L::FetchSource,
            L::Tools,
            L::Prepare,
            L::ExeFS,
            L::Generate,
            L::Compile,
            L::Images,
            L::Runtime,
            L::Package,
            L::Install,
        ]
    }

    fn active_step(&self) -> usize {
        let offset = 1;
        match self.page {
            Page::Target => 0,
            Page::Keys => offset,
            Page::Game => offset + 1,
            Page::Update => offset + 2,
            Page::ModsFolder => offset + 3,
            Page::Mods => offset + 4,
            Page::Review => offset + if self.mods_skipped { 3 } else { 5 },
            Page::Setup => offset + if self.mods_skipped { 4 } else { 6 },
            Page::Progress => {
                offset
                    + if self.mods_skipped { 5 } else { 7 }
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
    fn ready(&self) -> bool {
        if matches!(self.page, Page::Target | Page::Review | Page::ModsFolder) {
            return true;
        }
        if self.page == Page::Mods {
            return !self.mods_scanning
                && self.selected_mod.as_ref().is_none_or(|name| {
                    self.mods.iter().any(|item| {
                        &item.name == name
                            && (item.has_romfs || item.has_exefs)
                            && (self.demo
                                || !item.has_exefs
                                || (self.apple_ips_target() && item.ips_buildable()))
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

    fn backend_supported(&self) -> bool {
        matches!(
            (self.host, self.target, std::env::consts::ARCH),
            (Platform::Mac, InstallTarget::Mac, "aarch64")
                | (Platform::Mac, InstallTarget::Ios, "aarch64")
                | (Platform::Linux, InstallTarget::Linux, "x86_64")
        ) && self.base.as_ref().is_some_and(|source| {
            source.path.is_dir()
                || source.path.extension().is_some_and(|ext| {
                    ext.eq_ignore_ascii_case("xci") || ext.eq_ignore_ascii_case("nsp")
                })
        }) && self.selected_mod.as_ref().is_none_or(|name| {
            self.mods.iter().any(|item| {
                &item.name == name
                    && (!item.has_exefs || (self.host == Platform::Mac && item.ips_buildable()))
            })
        })
    }

    fn apple_ips_target(&self) -> bool {
        self.host == Platform::Mac && matches!(self.target, InstallTarget::Mac | InstallTarget::Ios)
    }

    fn capture_scenario(&mut self) -> Task<Message> {
        let index = self.capture.as_ref().expect("capture enabled").index;
        self.appearance = Appearance::Dark;
        self.portable_cpu = false;
        self.clean_build = false;
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
        self.backend_cancel = None;
        self.requirements = None;
        self.available_update = None;
        if !matches!(scenario, "empty" | "keys-empty" | "keys-not-found") {
            self.base = Some(Source::fixture(
                self.language.t(L::DemoGameFile),
                "XCI · 4.4 GB",
            ));
            self.update = Some(Source::fixture(
                self.language.t(L::DemoUpdateFile),
                "NSP · 2.8 GB",
            ));
            self.keys = Some(Source::fixture(
                "prod.keys",
                self.language.t(L::PrivateKeys),
            ));
        }
        match scenario {
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
            "mods-folder" => self.page = Page::ModsFolder,
            "mods-folder-ios" => {
                self.page = Page::ModsFolder;
                self.target = InstallTarget::Ios;
                self.mods_folder = mod_support::folder_for(self.host, self.target);
            }
            "mods-empty" => self.page = Page::Mods,
            "mods-ips-ready" | "mods-ips-ios-ready" | "review-mod" => {
                if scenario == "mods-ips-ios-ready" {
                    self.target = InstallTarget::Ios;
                }
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
                self.page = if scenario == "review-mod" {
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
                        self.language.t(L::Files)
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
                self.notice = Some(build_error_notice(error, self.language));
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
            "build-options" => {
                self.page = Page::Setup;
                self.build_options_open = true;
            }
            "setup-dependencies" => {
                self.page = Page::Setup;
                self.requirements = Some(crate::dependencies::Plan {
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
                });
            }
            "update-available" | "update-confirmation" => {
                self.page = Page::Target;
                self.available_update = Some(crate::updates::Release {
                    tag: None,
                    version: "0.2.0".into(),
                    assets: vec![],
                });
                if scenario == "update-confirmation" {
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
            "installed" | "installed-test" => {
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
                    "XCI · 4.4 GB",
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
    fn build_options_are_explicit_and_do_not_change_navigation() {
        let (mut app, _) = Installer::new();
        assert!(!app.clean_build);
        assert!(app.auto_cleanup);
        let _ = app.update(Message::CleanBuild(true));
        assert!(!app.clean_build);
        app.page = Page::Setup;
        let _ = app.update(Message::BuildOptions(true));
        let _ = app.update(Message::CleanBuild(true));
        let _ = app.update(Message::AutoCleanup(false));
        assert!(app.clean_build);
        assert!(!app.auto_cleanup);
        let _ = app.update(Message::Back);
        assert_eq!(app.page, Page::Setup);
        assert!(!app.build_options_open);
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
            assert!(message.contains("~/private/game.xci"));
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
            build_error_notice(error, Language::German),
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
    fn native_generator_error_dialog_keeps_module_phase_and_cause() {
        let cause = "bdsp_codegen [analyze/subsdk1]: error: cross-module entry outside module text";
        let detail = format!("Build step failed: eh_gen\n{cause}");
        for language in Language::ALL {
            let notice = build_error_notice(&detail, language);
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
        ] {
            let notice = build_error_notice(error, language);
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
        assert_eq!(
            app.step_labels().len(),
            8 + crate::progress::Stage::ALL.len() - 1
        );
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
        assert_eq!(app.step_labels().len(), 6 + 9);
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
        assert_eq!(app.active_step(), 8);
        for _ in 0..20 {
            let _ = app.update(Message::Tick);
        }
        assert_eq!(app.active_step(), 10);
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
            8 + crate::progress::Stage::Compile.index() - 1
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
    fn apple_code_mod_can_advance_to_a_separate_build() {
        let root = std::env::temp_dir().join(format!("installer-ips-ready-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&root);
        std::fs::create_dir_all(root.join("Code/ExeFS")).unwrap();
        std::fs::write(root.join("Code/ExeFS/0123.ips"), b"PATCHEOF").unwrap();
        std::fs::write(root.join("Code/ExeFS/subsdk1"), b"NSO0").unwrap();
        std::fs::create_dir_all(root.join("Code/RomFS")).unwrap();
        for target in [InstallTarget::Mac, InstallTarget::Ios] {
            let (mut app, _) = Installer::new();
            app.host = Platform::Mac;
            app.target = target;
            app.page = Page::Mods;
            app.mods = mod_support::scan_selected(&root.join("Code")).unwrap();
            app.selected_mod = Some("Code".into());
            assert!(app.ready());
            let _ = app.update(Message::Review);
            assert_eq!(app.page, Page::Review);
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
}
