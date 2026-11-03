//! The Windows components: ONE archive with the compiler, SDL, Vulkan, FFmpeg, hactool and the generator that
//! GitHub Actions builds from the newest upstream releases (.github/workflows/windows-components.yml). The installer
//! ships it inside the installer (resources/), so the user prepares nothing; integrity comes from the SHA-256 in the
//! metadata that travels with it. Builds without the bundle (development) cannot set the Windows environment up.
use crate::process::Hidden;
use serde::Deserialize;

use std::{
    fs, io,
    path::{Component, Path, PathBuf},
};

const ARCHIVE: &str = "windows-components.zip";
const MAX_UNPACKED: u64 = 8 << 30;

#[derive(Debug, Clone, PartialEq, Deserialize)]
pub struct Meta {
    pub schema: u32,
    pub archive: String,
    pub sha256: String,
    pub size_bytes: u64,
    pub created: String,
}

impl Meta {
    fn check(&self) -> Result<(), String> {
        let hex = self.sha256.len() == 64
            && self
                .sha256
                .bytes()
                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b));
        (self.schema == 1
            && self.archive == ARCHIVE
            && hex
            && self.size_bytes > 0
            && self.size_bytes < MAX_UNPACKED)
            .then_some(())
            .ok_or_else(|| "The Windows components metadata is invalid.".to_string())
    }
}

pub fn root() -> Result<PathBuf, String> {
    Ok(crate::appdir::data_dir()
        .ok_or("Application data unavailable.")?
        .join("windows-components"))
}

/// The catalog of the installed environment, if one is installed and complete.
pub fn catalog(root: &Path) -> Option<PathBuf> {
    let current = fs::read_to_string(root.join("current")).ok()?;
    let catalog = root.join(current.trim()).join("catalog.json");
    (current.trim().len() == 16 && catalog.is_file()).then_some(catalog)
}

pub fn installed(root: &Path) -> Option<Meta> {
    let current = fs::read_to_string(root.join("current")).ok()?;
    serde_json::from_slice(
        &fs::read(root.join(current.trim()).join("windows-components.json")).ok()?,
    )
    .ok()
}

fn hash_file(path: &Path) -> Result<(String, u64), String> {
    let hash = bdsp_extract::manifest::file_sha256(path).map_err(|e| e.to_string())?;
    Ok((hash, fs::metadata(path).map_err(|e| e.to_string())?.len()))
}

const LOCK: &str = "install.lock";
const LOCK_MAX_AGE_SECONDS: u64 = 4 * 3600;
pub const BUSY: &str = "The tools are already being installed by another running installer window. Close the other window or wait until it finishes, then try again.";

/// Only one installer process may prepare the tools at a time: they share the folder. The file holds the pid and start time
/// of its owner and is removed on drop; a file of a dead process or an old one is taken over.
#[derive(Debug)]
pub struct InstallLock(PathBuf);

impl InstallLock {
    pub fn acquire(root: &Path) -> Result<Self, String> {
        Self::acquire_with(root, std::process::id(), unix_now(), process_alive)
    }

    fn acquire_with(
        root: &Path,
        pid: u32,
        now: u64,
        alive: impl Fn(u32) -> bool,
    ) -> Result<Self, String> {
        let path = root.join(LOCK);
        for _ in 0..3 {
            match fs::OpenOptions::new()
                .write(true)
                .create_new(true)
                .open(&path)
            {
                Ok(mut file) => {
                    io::Write::write_all(&mut file, format!("{pid}\n{now}\n").as_bytes())
                        .map_err(|e| e.to_string())?;
                    return Ok(Self(path));
                }
                Err(error) if error.kind() == io::ErrorKind::AlreadyExists => {
                    let text = fs::read_to_string(&path).unwrap_or_default();
                    let mut fields = text.lines().map(|v| v.trim().parse::<u64>().ok());
                    let owner = fields.next().flatten();
                    let started = fields.next().flatten();
                    let stale = match (owner, started) {
                        (Some(owner), Some(started)) => {
                            now.saturating_sub(started) > LOCK_MAX_AGE_SECONDS
                                || (owner != u64::from(pid) && !alive(owner as u32))
                        }
                        _ => true,
                    };
                    if !stale {
                        return Err(BUSY.into());
                    }
                    let _ = fs::remove_file(&path);
                }
                Err(error) => return Err(error.to_string()),
            }
        }
        Err(BUSY.into())
    }
}

impl Drop for InstallLock {
    fn drop(&mut self) {
        let _ = fs::remove_file(&self.0);
    }
}

fn unix_now() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_or(0, |d| d.as_secs())
}

#[cfg(unix)]
fn process_alive(pid: u32) -> bool {
    // SAFETY: signal 0 only checks that the process exists.
    let found = unsafe { libc::kill(pid as libc::pid_t, 0) } == 0;
    found || std::io::Error::last_os_error().raw_os_error() == Some(libc::EPERM)
}

#[cfg(windows)]
fn process_alive(pid: u32) -> bool {
    unsafe extern "system" {
        fn OpenProcess(access: u32, inherit: i32, pid: u32) -> *mut core::ffi::c_void;
        fn GetExitCodeProcess(process: *mut core::ffi::c_void, code: *mut u32) -> i32;
        fn CloseHandle(handle: *mut core::ffi::c_void) -> i32;
    }
    // SAFETY: the handle is checked and closed; the exit code is a plain output.
    unsafe {
        let handle = OpenProcess(0x1000, 0, pid);
        if handle.is_null() {
            return false;
        }
        let mut code = 0u32;
        let ok = GetExitCodeProcess(handle, &mut code);
        CloseHandle(handle);
        ok != 0 && code == 259
    }
}

#[cfg(not(any(unix, windows)))]
fn process_alive(_: u32) -> bool {
    true
}

/// The work folders of one unpack: unique per process, so a second installer can never delete them.
fn work_folders(root: &Path, name: &str, pid: u32) -> (PathBuf, PathBuf) {
    (
        root.join(format!("{name}.{pid}.partial")),
        root.join(format!("{name}.{pid}.tools.partial")),
    )
}

/// Verifies the downloaded tools archive against the metadata, unpacks it, lets `assemble(tools, out)` build the full
/// environment next to the others; `current` switches last.
pub fn unpack(
    archive: &Path,
    meta: &Meta,
    root: &Path,
    assemble: impl FnOnce(&Path, &Path) -> Result<(), String>,
) -> Result<PathBuf, String> {
    meta.check()?;
    let (hash, size) = hash_file(archive)?;
    if hash != meta.sha256 || size != meta.size_bytes {
        return Err("The Windows components download is damaged. Retry.".into());
    }
    let name = &meta.sha256[..16];
    let _lock = InstallLock::acquire(root)?;
    let target = root.join(name);
    let (partial, tools) = work_folders(root, name, std::process::id());
    // Under the lock, leftovers of earlier runs (also of crashed processes) belong to nobody.
    for entry in fs::read_dir(root).map_err(|e| e.to_string())?.flatten() {
        let old = entry.file_name().to_string_lossy().into_owned();
        if old.ends_with(".partial") && entry.path().is_dir() {
            let _ = fs::remove_dir_all(entry.path());
        }
    }
    let _ = fs::remove_dir_all(&partial);
    let _ = fs::remove_dir_all(&tools);
    fs::create_dir_all(&tools).map_err(|e| e.to_string())?;
    let result = (|| {
        let mut zip = zip::ZipArchive::new(fs::File::open(archive).map_err(|e| e.to_string())?)
            .map_err(|e| e.to_string())?;
        let mut total = 0u64;
        for index in 0..zip.len() {
            let mut entry = zip.by_index(index).map_err(|e| e.to_string())?;
            let relative = entry
                .enclosed_name()
                .ok_or("The archive contains an unsafe path.")?;
            if relative
                .components()
                .any(|c| !matches!(c, Component::Normal(_)))
                || entry.unix_mode().is_some_and(|m| m & 0o170000 == 0o120000)
            {
                return Err("The archive contains an unsafe entry.".to_string());
            }
            let destination = tools.join(&relative);
            if entry.is_dir() {
                fs::create_dir_all(&destination).map_err(|e| e.to_string())?;
                continue;
            }
            total += entry.size();
            if total > MAX_UNPACKED {
                return Err("The archive is larger than expected.".into());
            }
            fs::create_dir_all(destination.parent().unwrap()).map_err(|e| e.to_string())?;
            let mut file = fs::File::create(&destination).map_err(|e| e.to_string())?;
            io::copy(&mut entry, &mut file).map_err(|e| e.to_string())?;
        }
        assemble(&tools, &partial)?;
        if !partial.join("catalog.json").is_file() {
            return Err("The Windows setup produced no catalog.json.".into());
        }
        fs::write(partial.join("windows-components.json"), serde_json::to_vec(&serde_json::json!({
            "schema": meta.schema, "archive": meta.archive, "sha256": meta.sha256, "size_bytes": meta.size_bytes, "created": meta.created
        })).unwrap()).map_err(|e| e.to_string())?;
        let _ = fs::remove_dir_all(&tools);
        let _ = fs::remove_dir_all(&target);
        fs::rename(&partial, &target).map_err(|e| e.to_string())?;
        let pointer = root.join("current.partial");
        fs::write(&pointer, name)
            .and_then(|_| fs::rename(&pointer, root.join("current")))
            .map_err(|e| e.to_string())
    })();
    if let Err(error) = result {
        let _ = fs::remove_dir_all(&partial);
        let _ = fs::remove_dir_all(&tools);
        return Err(error);
    }
    for entry in fs::read_dir(root).map_err(|e| e.to_string())?.flatten() {
        let old = entry.file_name().to_string_lossy().into_owned();
        if old != name && old != "current" && entry.path().is_dir() {
            let _ = fs::remove_dir_all(entry.path());
        }
    }
    Ok(target.join("catalog.json"))
}

/// The folder whose scripts run the setup: a checkout beside the installer (development), otherwise the newest `main`
/// source, like every build uses. A packaged installer carries no scripts of its own.
fn setup_source(
    beside: Option<PathBuf>,
    download: impl FnOnce() -> Result<PathBuf, String>,
) -> Result<PathBuf, String> {
    match beside {
        Some(root) => Ok(root),
        None => download(),
    }
}

/// The environment the scripts need to run `--cli extract` through the installer executable; every Python step sets it.
pub fn extract_env(tool: &Path) -> [(&'static str, std::ffi::OsString); 2] {
    [
        ("BDSP_EXTRACT", tool.as_os_str().to_os_string()),
        ("BDSP_EXTRACT_PREFIX", "--cli".into()),
    ]
}

/// The executable that answers `--cli unpack`: the installer itself. The helper `installer_setup` does not know `--cli`,
/// so it points at the installer: `BDSP_INSTALLER_EXE`, else the sibling.
fn extract_tool(own: &Path) -> PathBuf {
    if let Some(installer) = std::env::var_os("BDSP_INSTALLER_EXE").map(PathBuf::from)
        && installer.is_file()
    {
        return installer;
    }
    let main = format!("strahlender-xnu-installer{}", std::env::consts::EXE_SUFFIX);
    let sibling = own.with_file_name(&main);
    if own.file_name().is_some_and(|name| name != main.as_str()) && sibling.is_file() {
        sibling
    } else {
        own.to_path_buf()
    }
}

/// What the Windows setup is doing right now, for the installer window: filled from the setup's JSON lines (`--events`, see
/// scripts/install/windows_setup.py) while it runs. One setup runs at a time.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct SetupProgress {
    pub running: bool,
    /// Steps announced by the setup (plus the source download before it) and the number of the current one, 1 based.
    pub total: u32,
    pub index: u32,
    /// "source", "versions", "qt", "toolchain", "sdl", "ffmpeg", "bundle", "tools", "register" and "download", "unpack" or "work".
    pub id: String,
    pub phase: String,
    pub done: u64,
    pub size: u64,
    pub bytes_per_second: f64,
    /// The last lines the setup printed.
    pub log: Vec<String>,
    step_started: Option<std::time::Instant>,
}

#[allow(dead_code)] // the installer_setup binary shares this module but has no window
impl SetupProgress {
    /// 0.0 to 1.0 over all steps; a running download moves its step.
    pub fn fraction(&self) -> f32 {
        if self.total == 0 {
            return 0.0;
        }
        let step = if self.phase == "download" && self.size > 0 {
            self.done as f64 / self.size as f64
        } else {
            0.0
        };
        (((self.index.saturating_sub(1)) as f64 + step) / self.total as f64).min(1.0) as f32
    }

    pub fn seconds_left(&self) -> Option<u64> {
        (self.bytes_per_second > 1.0 && self.size > self.done)
            .then(|| ((self.size - self.done) as f64 / self.bytes_per_second).ceil() as u64)
    }

    /// One line of the setup: a JSON event or plain text.
    pub fn apply(&mut self, line: &str, now: std::time::Instant) {
        let Ok(event) = serde_json::from_str::<serde_json::Value>(line) else {
            let text = line.trim();
            if !text.is_empty() {
                self.log.push(text.to_owned());
                if self.log.len() > 200 {
                    self.log.remove(0);
                }
            }
            return;
        };
        let number = |key: &str| event[key].as_u64().unwrap_or(0);
        match event["event"].as_str() {
            Some("steps") => self.total = number("total") as u32 + 1, // +1: the source download comes first
            Some("step") => {
                self.index = number("index") as u32 + 1;
                self.id = event["id"].as_str().unwrap_or("").to_owned();
                self.phase = event["phase"].as_str().unwrap_or("").to_owned();
                (self.done, self.size, self.bytes_per_second) = (0, 0, 0.0);
                self.step_started = Some(now);
            }
            Some("bytes") => {
                (self.done, self.size) = (number("completed"), number("total"));
                if let Some(started) = self.step_started {
                    let seconds = now.saturating_duration_since(started).as_secs_f64();
                    if seconds >= 1.0 {
                        self.bytes_per_second = self.done as f64 / seconds;
                    }
                }
            }
            _ => {}
        }
    }
}

static SETUP_PROGRESS: std::sync::Mutex<Option<SetupProgress>> = std::sync::Mutex::new(None);

fn with_progress<T>(change: impl FnOnce(&mut SetupProgress) -> T) -> T {
    let mut guard = SETUP_PROGRESS.lock().unwrap_or_else(|e| e.into_inner());
    change(guard.get_or_insert_with(SetupProgress::default))
}

/// The current state of the setup for the window (a copy).
#[allow(dead_code)]
pub fn setup_progress() -> SetupProgress {
    with_progress(|progress| progress.clone())
}

/// Called when the window starts the setup, so an old state is not shown.
#[allow(dead_code)]
pub fn reset_setup_progress() {
    with_progress(|progress| {
        *progress = SetupProgress {
            running: true,
            total: 1,
            index: 1,
            id: "source".into(),
            phase: "download".into(),
            ..Default::default()
        }
    });
}

/// Runs scripts/install/windows_setup.py in the private Python: Qt, FFmpeg and SDL3 come from their publishers.
fn run_setup(tools: &Path, out: &Path) -> Result<(), String> {
    let (python, _) =
        crate::runtime::backend_python().ok_or_else(|| match crate::bundle::last_error() {
            Some(why) => format!("The bundled Python runtime is missing. {why}"),
            None => "The bundled Python runtime is missing.".to_string(),
        })?;
    let sources = crate::source_download::sources_dir();
    if let Ok(parent) = &sources {
        // leftovers of earlier runs; a running setup is younger than two hours
        crate::source_download::prune_unused(
            parent,
            None,
            std::time::Duration::from_secs(2 * 3600),
        );
    }
    let checkout = crate::runtime::project_root();
    let downloaded = checkout.is_none();
    let project = setup_source(checkout, || {
        let parent = sources.clone()?;
        crate::source_download::download_main(&parent, &std::sync::atomic::AtomicBool::new(false))
    })?;
    let mut child = std::process::Command::new(python)
        .hidden()
        .current_dir(&project)
        .envs(extract_env(&extract_tool(
            &std::env::current_exe().map_err(|e| e.to_string())?,
        )))
        .env("PYTHONUNBUFFERED", "1")
        .args([
            "-B",
            "-m",
            "scripts.install.windows_setup",
            "--events",
            "--tools",
        ])
        .arg(tools)
        .arg("--out")
        .arg(out)
        .stdin(std::process::Stdio::null())
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped())
        .spawn()
        .map_err(|e| e.to_string())?;
    let errors = child.stderr.take().map(|mut stream| {
        std::thread::spawn(move || {
            let mut text = String::new();
            let _ = io::Read::read_to_string(&mut stream, &mut text);
            text
        })
    });
    if let Some(stdout) = child.stdout.take() {
        for line in io::BufRead::lines(io::BufReader::new(stdout)).map_while(Result::ok) {
            with_progress(|progress| progress.apply(&line, std::time::Instant::now()));
        }
    }
    let status = child.wait().map_err(|e| e.to_string())?;
    let text = errors
        .and_then(|handle| handle.join().ok())
        .unwrap_or_default();
    if downloaded {
        let _ = fs::remove_dir_all(&project); // this run's copy of main: the next run downloads its own
    }
    if status.success() {
        return Ok(());
    }
    Err(setup_error(&text))
}

/// The error of a failed setup: the end of what its Python printed to stderr, so the cause and the lines before it reach the
/// card and the log, not only the last line.
fn setup_error(stderr: &str) -> String {
    let lines: Vec<&str> = stderr
        .lines()
        .map(str::trim)
        .filter(|line| !line.is_empty())
        .collect();
    if lines.is_empty() {
        return "The Windows setup failed without any error output.".into();
    }
    lines[lines.len().saturating_sub(6)..].join(" | ")
}

/// The tools archive shipped inside the installer (resources/ of the unpacked bundle), with its metadata.
pub fn bundled() -> Option<(PathBuf, Meta)> {
    let resources = crate::bundle::dir()?.join("resources");
    let meta: Meta =
        serde_json::from_slice(&fs::read(resources.join("windows-components.json")).ok()?).ok()?;
    meta.check().ok()?;
    let archive = resources.join(ARCHIVE);
    archive.is_file().then_some((archive, meta))
}

/// Sets up the environment from the tools that ship with the installer, then fetches Qt, FFmpeg and SDL3 from their
/// publishers (windows_setup.py), unless this version is already installed.
pub fn install_latest(root: &Path) -> Result<PathBuf, String> {
    let (archive, meta) =
        bundled().ok_or("This installer build does not include the Windows tools.")?;
    if let (Some(have), Some(catalog)) = (installed(root), catalog(root))
        && have.sha256 == meta.sha256
    {
        return Ok(catalog);
    }
    fs::create_dir_all(root).map_err(|e| e.to_string())?;
    unpack(&archive, &meta, root, run_setup)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn setup_events_drive_the_progress_the_window_shows() {
        use std::time::{Duration, Instant};
        let start = Instant::now();
        let mut progress = SetupProgress::default();
        progress.apply(r#"{"event": "steps", "total": 12}"#, start);
        assert_eq!(progress.total, 13); // plus the source download
        progress.apply(
            r#"{"event": "step", "index": 2, "id": "qt", "phase": "download"}"#,
            start,
        );
        assert_eq!(
            (
                progress.index,
                progress.id.as_str(),
                progress.phase.as_str()
            ),
            (3, "qt", "download")
        );
        progress.apply(
            r#"{"event": "bytes", "completed": 50000000, "total": 200000000}"#,
            start + Duration::from_secs(5),
        );
        assert!((progress.bytes_per_second - 10_000_000.0).abs() < 1.0);
        assert_eq!(progress.seconds_left(), Some(15));
        // two finished steps and a quarter of the third
        assert!((progress.fraction() - (2.25 / 13.0) as f32).abs() < 1e-4);
        // an unpack step has no byte count and a new step starts from nothing
        progress.apply(
            r#"{"event": "step", "index": 3, "id": "qt", "phase": "unpack"}"#,
            start + Duration::from_secs(20),
        );
        assert_eq!(
            (progress.done, progress.size, progress.seconds_left()),
            (0, 0, None)
        );
        assert!((progress.fraction() - (3.0 / 13.0) as f32).abs() < 1e-4);
    }

    #[test]
    fn plain_setup_lines_go_to_the_log_which_stays_short() {
        let mut progress = SetupProgress::default();
        for number in 0..250 {
            progress.apply(
                &format!("Downloading file {number}"),
                std::time::Instant::now(),
            );
        }
        progress.apply("   ", std::time::Instant::now());
        assert_eq!(progress.log.len(), 200);
        assert_eq!(
            progress.log.last().map(String::as_str),
            Some("Downloading file 249")
        );
        assert_eq!(progress.fraction(), 0.0);
    }

    #[test]
    fn the_helper_points_at_the_installer_for_cli_unpack() {
        let dir = scratch("extract-tool");
        let main = dir.join(format!(
            "strahlender-xnu-installer{}",
            std::env::consts::EXE_SUFFIX
        ));
        let helper = dir.join(format!("installer_setup{}", std::env::consts::EXE_SUFFIX));
        assert_eq!(extract_tool(&helper), helper); // no sibling yet
        fs::write(&main, b"x").unwrap();
        assert_eq!(extract_tool(&helper), main);
        assert_eq!(extract_tool(&main), main);
        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn setup_uses_a_checkout_beside_the_installer_else_downloads_main() {
        let beside = Some(PathBuf::from("checkout"));
        let used = setup_source(beside, || Err("must not download".into()));
        assert_eq!(used, Ok(PathBuf::from("checkout")));
        let downloaded = setup_source(None, || Ok(PathBuf::from("main-source")));
        assert_eq!(downloaded, Ok(PathBuf::from("main-source")));
        assert!(setup_source(None, || Err("offline".into())).is_err());
    }
    use std::io::Write;

    fn scratch(name: &str) -> PathBuf {
        let dir =
            std::env::temp_dir().join(format!("bdsp-components-{name}-{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        dir
    }

    fn archive(dir: &Path, entries: &[(&str, &[u8])]) -> (PathBuf, Meta) {
        let path = dir.join("windows-components.zip");
        let mut zip = zip::ZipWriter::new(fs::File::create(&path).unwrap());
        for (name, data) in entries {
            zip.start_file(*name, zip::write::SimpleFileOptions::default())
                .unwrap();
            zip.write_all(data).unwrap();
        }
        zip.finish().unwrap();
        let (sha256, size_bytes) = hash_file(&path).unwrap();
        (
            path,
            Meta {
                schema: 1,
                archive: ARCHIVE.into(),
                sha256,
                size_bytes,
                created: "2026-10-29T00:00:00Z".into(),
            },
        )
    }

    /// Stand-in for windows_setup.py: copies the tools into the environment and registers a catalog.
    fn assemble(tools: &Path, out: &Path) -> Result<(), String> {
        fs::create_dir_all(out.join("hactool")).map_err(|e| e.to_string())?;
        fs::copy(
            tools.join("hactool/hactool.exe"),
            out.join("hactool/hactool.exe"),
        )
        .map_err(|e| e.to_string())?;
        fs::write(out.join("catalog.json"), b"{}").map_err(|e| e.to_string())
    }

    #[test]
    fn a_lock_held_by_a_live_process_refuses_and_deletes_nothing() {
        let dir = scratch("lock-live");
        let root = dir.join("root");
        fs::create_dir_all(root.join("abc.7.tools.partial")).unwrap();
        fs::write(root.join("abc.7.tools.partial/file"), b"x").unwrap();
        let first = InstallLock::acquire_with(&root, 100, 1000, |_| true).unwrap();
        let busy = InstallLock::acquire_with(&root, 200, 1500, |pid| pid == 100).unwrap_err();
        assert_eq!(busy, BUSY);
        assert!(root.join("abc.7.tools.partial/file").is_file());
        drop(first);
        assert!(!root.join(LOCK).exists());
        // the real unpack refuses the same way while another process holds the lock
        let (zip, meta) = archive(&dir, &[("hactool/hactool.exe", b"x")]);
        let held = format!("{}\n{}\n", std::process::id(), unix_now());
        fs::write(root.join(LOCK), &held).unwrap();
        assert_eq!(unpack(&zip, &meta, &root, assemble).unwrap_err(), BUSY);
        assert!(root.join("abc.7.tools.partial/file").is_file());
        assert_eq!(fs::read_to_string(root.join(LOCK)).unwrap(), held);
        fs::remove_dir_all(&dir).unwrap();
    }

    #[test]
    fn a_stale_lock_is_taken_over() {
        let dir = scratch("lock-stale");
        fs::write(dir.join(LOCK), "300\n1000\n").unwrap();
        let dead = InstallLock::acquire_with(&dir, 400, 1100, |_| false).unwrap();
        assert!(
            fs::read_to_string(dir.join(LOCK))
                .unwrap()
                .starts_with("400\n")
        );
        drop(dead);
        fs::write(dir.join(LOCK), "300\n1000\n").unwrap();
        let old = InstallLock::acquire_with(&dir, 400, 1000 + LOCK_MAX_AGE_SECONDS + 1, |_| true);
        assert!(old.is_ok());
        drop(old);
        fs::write(dir.join(LOCK), "garbage").unwrap();
        assert!(InstallLock::acquire_with(&dir, 400, 1100, |_| true).is_ok());
        fs::remove_dir_all(&dir).unwrap();
    }

    #[test]
    fn work_folders_are_unique_per_process_and_only_ours_are_removed() {
        let root = Path::new("root");
        assert_ne!(work_folders(root, "abc", 1), work_folders(root, "abc", 2));
        let (partial, tools) = work_folders(root, "abc", 5);
        assert!(partial.ends_with("abc.5.partial") && tools.ends_with("abc.5.tools.partial"));
    }

    #[test]
    fn the_setup_error_keeps_the_end_of_the_python_output() {
        let text = "Traceback\n  File x\n\nWinError 3 path\n";
        assert_eq!(setup_error(text), "Traceback | File x | WinError 3 path");
        assert!(setup_error("").contains("without any error output"));
        let many: String = (1..=20).map(|n| format!("line {n}\n")).collect();
        assert!(
            setup_error(&many).starts_with("line 15") && setup_error(&many).ends_with("line 20")
        );
    }

    #[test]
    fn unpacks_a_verified_archive_and_switches_the_current_version_last() {
        let dir = scratch("ok");
        let root = dir.join("root");
        fs::create_dir_all(&root).unwrap();
        let (zip, meta) = archive(&dir, &[("hactool/hactool.exe", b"x")]);
        assert!(catalog(&root).is_none());
        let catalog_path = unpack(&zip, &meta, &root, assemble).unwrap();
        assert_eq!(catalog(&root), Some(catalog_path.clone()));
        assert!(
            catalog_path
                .parent()
                .unwrap()
                .join("hactool/hactool.exe")
                .is_file()
        );
        assert_eq!(installed(&root), Some(meta.clone()));
        // A second version replaces the first one completely.
        let (zip2, meta2) = archive(&dir, &[("hactool/hactool.exe", b"2")]);
        unpack(&zip2, &meta2, &root, assemble).unwrap();
        assert_eq!(installed(&root).unwrap().sha256, meta2.sha256);
        assert_eq!(
            fs::read_dir(&root).unwrap().count(),
            2,
            "current plus one version"
        );
        fs::remove_dir_all(&dir).unwrap();
    }

    #[test]
    fn rejects_damaged_unsafe_and_incomplete_archives_without_leaving_files() {
        let dir = scratch("bad");
        let root = dir.join("root");
        fs::create_dir_all(&root).unwrap();
        let (zip, mut meta) = archive(&dir, &[("hactool/hactool.exe", b"x")]);
        meta.sha256 = "0".repeat(64);
        assert!(
            unpack(&zip, &meta, &root, assemble)
                .unwrap_err()
                .contains("damaged")
        );
        let (zip, meta) = archive(&dir, &[("hactool/hactool.exe", b"x"), ("../evil", b"x")]);
        assert!(
            unpack(&zip, &meta, &root, assemble)
                .unwrap_err()
                .contains("unsafe")
        );
        let (zip, meta) = archive(&dir, &[("toolchain/a", b"x")]);
        assert!(
            unpack(&zip, &meta, &root, |_, _| Ok(()))
                .unwrap_err()
                .contains("catalog")
        );
        let (zip, meta) = archive(&dir, &[("hactool/hactool.exe", b"y")]);
        assert!(
            unpack(&zip, &meta, &root, |_, _| Err("setup failed".into()))
                .unwrap_err()
                .contains("setup failed")
        );
        assert_eq!(fs::read_dir(&root).unwrap().count(), 0);
        assert!(!dir.join("evil").exists());
        let bad = Meta {
            archive: "other.zip".into(),
            ..meta
        };
        assert!(bad.check().is_err());
        fs::remove_dir_all(&dir).unwrap();
    }
}
