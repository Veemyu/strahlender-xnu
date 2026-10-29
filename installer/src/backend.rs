use crate::runtime::{backend_python, project_root};
use iced::futures::SinkExt;
use serde::Deserialize;
#[cfg(unix)]
use std::os::unix::process::CommandExt;
use std::{
    path::PathBuf,
    process::Stdio,
    sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
    },
    time::Duration,
};
use tokio::{
    io::{AsyncBufReadExt, BufReader},
    process::Command,
};

const PROTOCOL_VERSION: u32 = 2;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Event {
    Log {
        level: String,
        message: String,
    },
    Step {
        id: String,
        status: String,
    },
    Progress {
        id: String,
        completed: u64,
        total: u64,
    },
    GeneratorProgress {
        module: String,
        phase: String,
        completed: u64,
        total: u64,
        modules_completed: u64,
        modules_total: u64,
    },
    Artifact {
        kind: String,
        path: PathBuf,
    },
    IosProfile(crate::ios_profile::Profile),
    PythonMissing,
    RuntimeMissing,
    Finished {
        ok: bool,
        code: i32,
    },
    Stopped,
}

#[derive(Debug, Deserialize)]
#[serde(tag = "event", rename_all = "snake_case")]
enum ProtocolEvent {
    Hello {
        protocol: u32,
    },
    Step {
        id: String,
        status: String,
    },
    Progress {
        id: String,
        completed: u64,
        total: u64,
        #[serde(default)]
        module: Option<String>,
        #[serde(default)]
        phase: Option<String>,
        #[serde(default)]
        modules_completed: u64,
        #[serde(default)]
        modules_total: u64,
    },
    Log {
        level: String,
        message: String,
    },
    Result {
        ok: bool,
        code: i32,
    },
    Error {
        message: String,
        code: i32,
    },
    Artifact {
        kind: String,
        path: PathBuf,
    },
}

pub fn reveal_installed_application(path: PathBuf) -> Result<(), String> {
    if !path.exists() {
        return Err("The installed app is no longer available.".into());
    }
    #[cfg(target_os = "macos")]
    let mut command = {
        let mut command = std::process::Command::new("open");
        command.arg("-R").arg(&path);
        command
    };
    #[cfg(target_os = "linux")]
    let mut command = {
        let mut command = std::process::Command::new("xdg-open");
        command.arg(
            path.parent()
                .ok_or("The installation folder is unavailable.")?,
        );
        command
    };
    #[cfg(target_os = "windows")]
    let mut command = {
        let mut command = std::process::Command::new("explorer.exe");
        command.arg(
            path.parent()
                .ok_or("The installation folder is unavailable.")?,
        );
        command
    };
    command
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .map_err(|error| error.to_string())?
        .success()
        .then_some(())
        .ok_or("Could not show the installation folder.".into())
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum IosDelivery {
    Device,
    Ipa,
}
impl IosDelivery {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Device => "device",
            Self::Ipa => "ipa",
        }
    }
}

pub struct BuildRequest {
    pub target: &'static str,
    pub ios_delivery: IosDelivery,
    pub ios_device: Option<String>,
    pub ios_team: Option<String>,
    pub ios_profile: Option<crate::ios_profile::Profile>,
    pub ios_new_profile: Option<String>,
    pub portable_cpu: bool,
    pub clean_build: bool,
    pub auto_cleanup: bool,
    pub base: PathBuf,
    pub prod_keys: PathBuf,
    pub firmware: Option<PathBuf>,
    pub update: Option<PathBuf>,
    pub mod_root: Option<PathBuf>,
    pub mod_name: Option<String>,
}

#[cfg(debug_assertions)]
fn set_development_install_root(
    command: &mut Command,
    local_checkout: bool,
    destination: Option<std::ffi::OsString>,
) {
    if local_checkout && let Some(destination) = destination {
        command.arg("--install-root").arg(destination);
    }
}

fn set_cpu_target(command: &mut Command, target: &str, portable: bool) {
    // Inherited shell state must not override the UI, including Apple cross targets.
    if target == "linux" {
        command.env(
            "BDSP_CPU_TARGET",
            if portable { "portable" } else { "native" },
        );
    } else {
        command.env_remove("BDSP_CPU_TARGET");
    }
}

fn ips_helper() -> Option<PathBuf> {
    let executable = std::env::current_exe().ok()?;
    let sibling = executable.with_file_name(if cfg!(windows) {
        "ips_patch.exe"
    } else {
        "ips_patch"
    });
    if sibling.is_file() {
        return Some(sibling);
    }
    if cfg!(debug_assertions) {
        let root = project_root()?;
        let debug = root.join("installer/target/debug/ips_patch");
        if debug.is_file() {
            return Some(debug);
        }
    }
    None
}

enum Action {
    Build(BuildRequest),
}

pub fn build(
    run_id: u64,
    cancelled: Arc<AtomicBool>,
    mods_folder: Option<PathBuf>,
    selected_mod: Option<String>,
    request: BuildRequest,
) -> impl iced::futures::Stream<Item = (u64, Event)> + 'static {
    run_driver(
        run_id,
        cancelled,
        mods_folder,
        selected_mod,
        Action::Build(request),
    )
}

fn run_driver(
    run_id: u64,
    cancelled: Arc<AtomicBool>,
    mods_folder: Option<PathBuf>,
    selected_mod: Option<String>,
    action: Action,
) -> impl iced::futures::Stream<Item = (u64, Event)> + 'static {
    iced::stream::channel(32, async move |mut output| {
        let _ = output
            .send((
                run_id,
                Event::Step {
                    id: "source".into(),
                    status: "started".into(),
                },
            ))
            .await;
        let cleanup_requested = match &action {
            Action::Build(request) => request.auto_cleanup,
        };
        let device_target = match &action {
            Action::Build(request) => request.target == "ios",
        };
        let ipa_export = matches!(&action, Action::Build(request) if request.target == "ios" && request.ios_delivery == IosDelivery::Ipa);
        let remember_profile =
            matches!(&action, Action::Build(request) if ipa_export && request.mod_root.is_some());
        let workspace =
            match crate::workspace::prepare(run_id, &mut output, cancelled.clone()).await {
                Ok(root) => root,
                Err(_) if cancelled.load(Ordering::Acquire) => {
                    let _ = output.send((run_id, Event::Stopped)).await;
                    return;
                }
                Err(message) => {
                    let _ = output
                        .send((
                            run_id,
                            Event::Log {
                                level: "error".into(),
                                message,
                            },
                        ))
                        .await;
                    let _ = output
                        .send((
                            run_id,
                            Event::Finished {
                                ok: false,
                                code: -3,
                            },
                        ))
                        .await;
                    return;
                }
            };
        let root = workspace.root.clone();
        let _ = output
            .send((
                run_id,
                Event::Log {
                    level: "info".into(),
                    message: format!(
                        "Source revision: {}",
                        root.file_name().unwrap_or_default().to_string_lossy()
                    ),
                },
            ))
            .await;
        let driver = root.join("scripts/install/driver.py");
        let _ = output
            .send((
                run_id,
                Event::Step {
                    id: "source".into(),
                    status: "complete".into(),
                },
            ))
            .await;
        let Some((python, private)) = backend_python() else {
            let _ = output.send((run_id, Event::RuntimeMissing)).await;
            let _ = output
                .send((
                    run_id,
                    Event::Finished {
                        ok: false,
                        code: -1,
                    },
                ))
                .await;
            return;
        };
        let mut command = Command::new(&python);
        // The scripts run the extract step through this very executable (`--cli extract`), so no Rust toolchain is needed.
        if let Ok(own) = std::env::current_exe() {
            command
                .env("BDSP_EXTRACT", own)
                .env("BDSP_EXTRACT_PREFIX", "--cli");
        }
        // LLVM still leads PATH; select Git separately so Brew cannot shadow Apple Git.
        if !cfg!(target_os = "windows") {
            command.env("BDSP_GIT", crate::dependencies::git());
        }
        let inherited = std::env::var_os("PATH").unwrap_or_default();
        let mut search_paths: Vec<PathBuf> = if cfg!(target_os = "macos") {
            crate::dependencies::mac_tool_paths()
        } else {
            Vec::new()
        };
        if private && let Some(directory) = python.parent() {
            search_paths.insert(0, directory.to_path_buf());
        }
        search_paths.extend(std::env::split_paths(&inherited));
        if let Ok(path) = std::env::join_paths(search_paths) {
            command.env("PATH", path);
        }
        command.env("BDSP_MOD", selected_mod.unwrap_or_else(|| "none".into()));
        if let Some(folder) = &mods_folder {
            command.env("BDSP_MODS_DIR", folder);
        }
        if private {
            command.arg("-I").env("BDSP_INSTALLER_PRIVATE_RUNTIME", "1");
        } else {
            command.env_remove("BDSP_INSTALLER_PRIVATE_RUNTIME");
        }
        command.arg("-B").arg(&driver);
        match action {
            Action::Build(BuildRequest {
                target,
                ios_delivery,
                ios_device,
                ios_team,
                ios_profile,
                ios_new_profile,
                portable_cpu,
                clean_build,
                auto_cleanup: _,
                base,
                prod_keys,
                firmware,
                update,
                mod_root,
                mod_name,
            }) => {
                set_cpu_target(&mut command, target, portable_cpu);
                command
                    .arg("build")
                    .arg("--root")
                    .arg(&root)
                    .arg("--work")
                    .arg(root.join("work"))
                    .arg("--target")
                    .arg(target)
                    .arg("--base")
                    .arg(base)
                    .arg("--prod-keys")
                    .arg(prod_keys);
                if target.starts_with("windows")
                    && let Some(catalog) = crate::buildenv::root()
                        .ok()
                        .and_then(|root| crate::buildenv::catalog(&root))
                {
                    command.arg("--windows-catalog").arg(catalog);
                }
                if target == "ios" {
                    command.arg("--ios-delivery").arg(ios_delivery.as_str());
                    if ios_delivery == IosDelivery::Device
                        && let Some(device) = ios_device
                    {
                        command.arg("--ios-device").arg(device);
                    }
                    if ios_delivery == IosDelivery::Device
                        && let Some(team) = ios_team
                    {
                        command.arg("--ios-team").arg(team);
                    }
                    if ios_delivery == IosDelivery::Ipa {
                        match crate::workspace::data_dir() {
                            Ok(data) => {
                                command
                                    .arg("--ios-export-dir")
                                    .arg(data.join("exports/ios"));
                            }
                            Err(message) => {
                                let _ = output
                                    .send((
                                        run_id,
                                        Event::Log {
                                            level: "error".into(),
                                            message,
                                        },
                                    ))
                                    .await;
                                let _ = output
                                    .send((
                                        run_id,
                                        Event::Finished {
                                            ok: false,
                                            code: -1,
                                        },
                                    ))
                                    .await;
                                return;
                            }
                        }
                    }
                }
                if clean_build {
                    command.arg("--clean-build");
                }
                if target == "ios"
                    && ios_delivery == IosDelivery::Ipa
                    && let Some(profile) = ios_profile
                {
                    command
                        .arg("--ios-profile-id")
                        .arg(profile.id)
                        .arg("--ios-profile-game")
                        .arg(profile.game)
                        .arg("--ios-bundle-id")
                        .arg(profile.bundle);
                } else if target == "ios"
                    && ios_delivery == IosDelivery::Ipa
                    && let Some(id) = ios_new_profile
                {
                    command.arg("--ios-profile-id").arg(id);
                }
                #[cfg(debug_assertions)]
                set_development_install_root(
                    &mut command,
                    std::env::var_os("BDSP_INSTALLER_DEV_CHECKOUT").as_deref()
                        == Some(std::ffi::OsStr::new("1")),
                    std::env::var_os("BDSP_INSTALLER_DEV_INSTALL_ROOT"),
                );
                if let Some(source) = firmware {
                    let helper = std::env::current_exe().unwrap_or_default().with_file_name(
                        if cfg!(windows) {
                            "firmware_import.exe"
                        } else {
                            "firmware_import"
                        },
                    );
                    command
                        .arg("--firmware")
                        .arg(source)
                        .arg("--firmware-helper")
                        .arg(helper);
                    if let Some(data) =
                        directories::ProjectDirs::from("dev", "Veemyu", "strahlender-xnu-installer")
                    {
                        command
                            .arg("--firmware-cache")
                            .arg(data.data_local_dir().join("firmware"));
                    }
                }
                if let Some(update) = update {
                    command.arg("--update").arg(update);
                }
                if let Some(mod_root) = mod_root {
                    command.arg("--mod-root").arg(mod_root);
                }
                if let Some(mod_name) = mod_name {
                    command.arg("--mod-name").arg(mod_name);
                }
                if let Some(mods_dir) = mods_folder.as_ref() {
                    command.arg("--mods-dir").arg(mods_dir);
                }
                if let Some(helper) = ips_helper() {
                    command.arg("--ips-helper").arg(helper);
                }
            }
        }
        command
            .env("PYTHONDONTWRITEBYTECODE", "1")
            .env("PYTHONUNBUFFERED", "1")
            .env_remove("PYTHONPATH")
            .env_remove("PYTHONHOME")
            .current_dir(&root)
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .kill_on_drop(true);
        #[cfg(unix)]
        command.as_std_mut().process_group(0);
        let mut child = match command.spawn() {
            Ok(child) => child,
            Err(error) => {
                let event = if error.kind() == std::io::ErrorKind::NotFound {
                    Event::PythonMissing
                } else {
                    Event::Log {
                        level: "error".into(),
                        message: format!("Could not start local Python backend: {error}"),
                    }
                };
                let _ = output.send((run_id, event)).await;
                let _ = output
                    .send((
                        run_id,
                        Event::Finished {
                            ok: false,
                            code: -1,
                        },
                    ))
                    .await;
                return;
            }
        };

        let stdout = child.stdout.take().expect("stdout was piped");
        let stderr = child.stderr.take().expect("stderr was piped");
        let mut stdout = BufReader::new(stdout).lines();
        let mut stderr = BufReader::new(stderr).lines();
        let mut stdout_open = true;
        let mut stderr_open = true;
        let mut protocol_seen = false;
        let mut result_seen = false;
        let mut result_ok = false;
        let mut result_code = -1;
        let mut installed_application = None;
        let mut device_package = None;

        while stdout_open || stderr_open {
            if cancelled.load(Ordering::Acquire) {
                #[cfg(unix)]
                if let Some(pid) = child.id() {
                    unsafe { libc::kill(-(pid as i32), libc::SIGTERM) };
                }
                if tokio::time::timeout(Duration::from_secs(5), child.wait())
                    .await
                    .is_err()
                {
                    let _ = child.kill().await;
                }
                let _ = child.wait().await;
                let _ = output.send((run_id, Event::Stopped)).await;
                return;
            }

            tokio::select! {
                _ = tokio::time::sleep(Duration::from_millis(100)) => {},
                line = stdout.next_line(), if stdout_open => match line {
                    Ok(Some(line)) => {
                        match serde_json::from_str::<ProtocolEvent>(&line) {
                            Ok(ProtocolEvent::Hello { protocol }) => {
                                if protocol != PROTOCOL_VERSION {
                                    let _ = output.send((run_id, Event::Log {
                                        level: "error".into(),
                                        message: format!("Backend protocol mismatch: expected {PROTOCOL_VERSION}, received {protocol}."),
                                    })).await;
                                    let _ = child.kill().await;
                                    let _ = child.wait().await;
                                    let _ = output.send((run_id, Event::Finished { ok: false, code: -2 })).await;
                                    return;
                                }
                                protocol_seen = true;
                            }
                            Ok(ProtocolEvent::Step { id, status }) => {
                                let _ = output.send((run_id, Event::Step { id, status })).await;
                            }
                            Ok(ProtocolEvent::Progress { id, completed, total, module, phase, modules_completed, modules_total }) => {
                                let event = match (id.as_str(), module, phase) {
                                    ("eh_gen", Some(module), Some(phase)) => Event::GeneratorProgress {
                                        module, phase, completed, total, modules_completed, modules_total,
                                    },
                                    _ => Event::Progress { id, completed, total },
                                };
                                let _ = output.send((run_id, event)).await;
                            }
                            Ok(ProtocolEvent::Log { level, message }) => {
                                let _ = output.send((run_id, Event::Log { level, message })).await;
                            }
                            Ok(ProtocolEvent::Result { ok, code }) => {
                                result_seen = true;
                                result_ok = ok;
                                result_code = code;
                            }
                            Ok(ProtocolEvent::Error { message, code }) => {
                                let _ = output.send((run_id, Event::Log { level: "error".into(), message })).await;
                                result_seen = true;
                                result_ok = false;
                                result_code = code;
                            }
                            Ok(ProtocolEvent::Artifact { kind, path }) => {
                                if kind == "installed_application" { installed_application = Some(path.clone()); }
                                if kind == "ipa" { device_package = Some(path.clone()); }
                                let _ = output.send((run_id, Event::Artifact { kind, path })).await;
                            }
                            Err(error) => {
                                let _ = output.send((run_id, Event::Log {
                                    level: "error".into(),
                                    message: format!("Invalid backend protocol event: {error}"),
                                })).await;
                                let _ = child.kill().await;
                                let _ = child.wait().await;
                                let _ = output.send((run_id, Event::Finished { ok: false, code: -3 })).await;
                                return;
                            }
                        }
                    }
                    Ok(None) => stdout_open = false,
                    Err(error) => {
                        let _ = output.send((run_id, Event::Log {
                            level: "error".into(),
                            message: format!("Could not read backend output: {error}"),
                        })).await;
                        let _ = child.kill().await;
                        let _ = child.wait().await;
                        let _ = output.send((run_id, Event::Finished { ok: false, code: -4 })).await;
                        return;
                    }
                },
                line = stderr.next_line(), if stderr_open => match line {
                    Ok(Some(line)) if !line.trim().is_empty() => {
                        let line = line.replace(root.to_string_lossy().as_ref(), "<project>");
                        let _ = output.send((run_id, Event::Log { level: "diagnostic".into(), message: line })).await;
                    }
                    Ok(Some(_)) => {},
                    Ok(None) => stderr_open = false,
                    Err(error) => {
                        let _ = output.send((run_id, Event::Log {
                            level: "diagnostic".into(),
                            message: format!("Could not read backend diagnostics: {error}"),
                        })).await;
                        stderr_open = false;
                    }
                },
                _ = tokio::time::sleep(Duration::from_millis(50)) => {}
            }
        }

        let status = child.wait().await;
        let process_ok = status.as_ref().is_ok_and(|status| status.success());
        if !protocol_seen {
            let _ = output
                .send((
                    run_id,
                    Event::Log {
                        level: "error".into(),
                        message: "Backend exited without a protocol handshake.".into(),
                    },
                ))
                .await;
        }
        if !result_seen {
            let code = status.ok().and_then(|status| status.code()).unwrap_or(-1);
            let _ = output
                .send((run_id, Event::Finished { ok: false, code }))
                .await;
        } else {
            let ok = protocol_seen && process_ok && result_ok;
            let profile_package = device_package.clone();
            if ok && cleanup_requested {
                if let Some(owner) = workspace.owner {
                    let _ = output
                        .send((
                            run_id,
                            Event::Step {
                                id: "cleanup".into(),
                                status: "started".into(),
                            },
                        ))
                        .await;
                    let _ = output.send((run_id, Event::Log { level: "info".into(), message:
                        "Removing this run's temporary files. Installed game data, saves and original inputs are kept.".into() })).await;
                    let cleaned = tokio::task::spawn_blocking(move || {
                        let anchor = if ipa_export {
                            device_package
                                .ok_or("The exported IPA is missing; temporary files were kept.")?
                        } else if device_target {
                            owner.export_ipa(&device_package.ok_or(
                                "The device package is missing; temporary files were kept.",
                            )?)?
                        } else {
                            installed_application.ok_or(
                                "The installed application is missing; temporary files were kept.",
                            )?
                        };
                        owner.finish(&anchor)?;
                        Ok::<_, String>(if device_target { Some(anchor) } else { None })
                    })
                    .await
                    .unwrap_or_else(|e| Err(e.to_string()));
                    let status = if cleaned.is_ok() {
                        "complete"
                    } else {
                        "needs attention"
                    };
                    match cleaned {
                        Ok(Some(path)) => {
                            let _ = output
                                .send((
                                    run_id,
                                    Event::Artifact {
                                        kind: "ipa".into(),
                                        path,
                                    },
                                ))
                                .await;
                        }
                        Ok(None) => {}
                        Err(detail) => {
                            let _ = output.send((run_id, Event::Log { level: "warning".into(), message: format!("The build succeeded, but temporary files could not all be removed: {detail}") })).await;
                        }
                    }
                    let _ = output
                        .send((
                            run_id,
                            Event::Step {
                                id: "cleanup".into(),
                                status: status.into(),
                            },
                        ))
                        .await;
                } else {
                    let _ = output.send((run_id, Event::Log { level: "info".into(), message:
                        "Development checkout preserved. Automatic cleanup only removes this installer's downloaded workspaces.".into() })).await;
                }
            }
            if ok
                && remember_profile
                && let Some(path) = profile_package
            {
                let profile = tokio::task::spawn_blocking(move || {
                    let profile = crate::ios_profile::read_ipa(&path)?;
                    crate::ios_profile::remember(&profile)?;
                    Ok::<_, String>(profile)
                })
                .await
                .unwrap_or_else(|e| Err(e.to_string()));
                match profile {
                    Ok(profile) => {
                        let _ = output.send((run_id, Event::IosProfile(profile))).await;
                    }
                    Err(detail) => {
                        let _ = output.send((run_id, Event::Log { level: "warning".into(), message: format!("The IPA was exported, but its update identity could not be remembered. Keep the IPA and select it for future updates: {detail}") })).await;
                    }
                }
            }
            let _ = output
                .send((
                    run_id,
                    Event::Finished {
                        ok,
                        code: result_code,
                    },
                ))
                .await;
        }
    })
}

#[cfg(test)]
mod tests {
    use super::{ProtocolEvent, set_cpu_target};
    use tokio::process::Command;

    fn runtime_marker(runtime: &std::path::Path, executable: &std::path::Path, host: &str) {
        use sha2::{Digest, Sha256};
        let name = executable
            .strip_prefix(runtime)
            .unwrap()
            .to_string_lossy()
            .replace('\\', "/");
        let digest = format!("{:x}", Sha256::digest(std::fs::read(executable).unwrap()));
        std::fs::write(
            runtime.join("runtime.json"),
            serde_json::to_vec(&serde_json::json!({
                "schema": 1, "target": host, "python": "3.13.15", "files": {name: digest}
            }))
            .unwrap(),
        )
        .unwrap();
    }

    #[test]
    fn reveal_does_not_launch_or_create_a_missing_application() {
        let missing = std::env::temp_dir()
            .join(format!("missing-installer-app-{}", std::process::id()))
            .join("BDSP.app");
        assert!(super::reveal_installed_application(missing.clone()).is_err());
        assert!(!missing.exists());
    }

    #[test]
    #[cfg(debug_assertions)]
    fn development_install_destination_requires_an_explicit_local_checkout() {
        let mut command = tokio::process::Command::new("python3");
        super::set_development_install_root(&mut command, false, Some("isolated apps".into()));
        assert_eq!(command.as_std().get_args().count(), 0);
        super::set_development_install_root(&mut command, true, Some("isolated apps".into()));
        assert_eq!(
            command.as_std().get_args().collect::<Vec<_>>(),
            vec![
                std::ffi::OsStr::new("--install-root"),
                std::ffi::OsStr::new("isolated apps")
            ]
        );
    }

    #[test]
    fn progress_protocol_accepts_old_counts_and_native_details() {
        let old: super::ProtocolEvent =
            serde_json::from_str(r#"{"event":"progress","id":"clang","completed":2,"total":3}"#)
                .unwrap();
        assert!(matches!(
            old,
            super::ProtocolEvent::Progress { module: None, .. }
        ));
        let native: super::ProtocolEvent = serde_json::from_str(
            r#"{"event":"progress","id":"eh_gen","module":"main","phase":"analyze","unit":"functions","completed":0,"total":0,"modules_completed":1,"modules_total":5}"#).unwrap();
        assert!(matches!(
            native,
            super::ProtocolEvent::Progress {
                module: Some(_),
                modules_total: 5,
                ..
            }
        ));
    }

    #[test]
    fn cpu_choice_reaches_linux_and_does_not_leak_to_apple_builds() {
        for (target, portable, expected) in [
            ("linux", false, Some("native")),
            ("linux", true, Some("portable")),
            ("macos", true, None),
            ("ios", false, None),
        ] {
            let mut command = Command::new("unused");
            command.env("BDSP_CPU_TARGET", "inherited");
            set_cpu_target(&mut command, target, portable);
            let actual = command
                .as_std()
                .get_envs()
                .find(|(key, _)| *key == "BDSP_CPU_TARGET")
                .unwrap()
                .1
                .and_then(|value| value.to_str());
            assert_eq!(actual, expected);
        }
    }

    #[test]
    fn private_runtime_requires_matching_host_and_python_marker() {
        let Some(host) = crate::runtime::host_target() else {
            return;
        };
        let runtime = std::env::temp_dir().join(format!(
            "strahlender-runtime-marker-test-{}-{:?}",
            std::process::id(),
            std::thread::current().id()
        ));
        let executable = if cfg!(windows) {
            runtime.join("python/python.exe")
        } else {
            runtime.join("python/bin/python3")
        };
        std::fs::create_dir_all(executable.parent().unwrap()).unwrap();
        std::fs::write(&executable, b"test").unwrap();
        runtime_marker(&runtime, &executable, host);
        assert_eq!(
            crate::runtime::verified_runtime_python(&runtime),
            Some(executable.clone())
        );
        let marker = serde_json::from_slice::<serde_json::Value>(
            &std::fs::read(runtime.join("runtime.json")).unwrap(),
        )
        .unwrap();
        assert!(crate::runtime::runtime_inventory_matches(
            &runtime,
            &marker["files"]
        ));
        std::fs::write(&executable, b"tampered").unwrap();
        assert!(!crate::runtime::runtime_inventory_matches(
            &runtime,
            &marker["files"]
        ));
        if cfg!(windows) {
            assert_eq!(crate::runtime::verified_runtime_python(&runtime), None);
        }
        std::fs::write(&executable, b"test").unwrap();
        let extra = runtime.join("injected.pth");
        std::fs::write(&extra, b"unexpected").unwrap();
        assert!(!crate::runtime::runtime_inventory_matches(
            &runtime,
            &marker["files"]
        ));
        std::fs::remove_file(extra).unwrap();
        for name in [
            "../escape",
            "/absolute",
            "C:/drive",
            "python\\python.exe",
            "python//python.exe",
        ] {
            assert!(!crate::runtime::runtime_inventory_matches(
                &runtime,
                &serde_json::json!({
                    name: marker["files"].as_object().unwrap().values().next().unwrap()
                }),
            ));
        }
        std::fs::write(
            runtime.join("runtime.json"),
            r#"{"schema":1,"target":"wrong-host","python":"3.13.15"}"#,
        )
        .unwrap();
        assert_eq!(crate::runtime::verified_runtime_python(&runtime), None);
        std::fs::remove_dir_all(runtime).unwrap();
    }

    #[test]
    fn backend_protocol_accepts_versioned_preflight_events() {
        let hello: ProtocolEvent =
            serde_json::from_str(r#"{"event":"hello","protocol":2}"#).unwrap();
        assert!(matches!(hello, ProtocolEvent::Hello { protocol: 2 }));

        let log: ProtocolEvent =
            serde_json::from_str(r#"{"event":"log","level":"info","message":"clang available"}"#)
                .unwrap();
        assert!(matches!(log, ProtocolEvent::Log { .. }));
    }

    #[test]
    fn universal_bundle_selects_only_the_matching_private_runtime() {
        let resources =
            std::env::temp_dir().join(format!("universal-runtime-test-{}", std::process::id()));
        let host = crate::runtime::host_target().unwrap();
        let native = resources.join("runtime").join(host);
        let executable = native.join(if cfg!(windows) {
            "python/python.exe"
        } else {
            "python/bin/python3"
        });
        std::fs::create_dir_all(executable.parent().unwrap()).unwrap();
        std::fs::write(&executable, b"fixture").unwrap();
        runtime_marker(&native, &executable, host);
        assert_eq!(
            crate::runtime::runtime_in_resources(&resources),
            Some(executable.clone())
        );
        if cfg!(windows) {
            let package = resources.parent().unwrap();
            let fixture = package.join(format!("runtime-layout-{}", std::process::id()));
            std::fs::create_dir(&fixture).unwrap();
            std::fs::rename(&resources, fixture.join("resources")).unwrap();
            let moved_executable = fixture
                .join("resources/runtime")
                .join(host)
                .join("python/python.exe");
            assert_eq!(
                crate::runtime::runtime_beside_executable(&fixture.join("installer.exe")),
                Some(moved_executable)
            );
            std::fs::rename(fixture.join("resources"), &resources).unwrap();
            std::fs::remove_dir(fixture).unwrap();
        }
        std::fs::write(
            native.join("runtime.json"),
            r#"{"schema":1,"target":"other-architecture","python":"3.13.15"}"#,
        )
        .unwrap();
        assert_eq!(crate::runtime::runtime_in_resources(&resources), None);
        std::fs::remove_dir_all(resources).unwrap();
    }

    #[test]
    fn finds_the_source_checkout_from_a_nested_installer_path() {
        let root = std::env::temp_dir().join(format!(
            "strahlender-root-test-{}-{:?}",
            std::process::id(),
            std::thread::current().id()
        ));
        let scripts = root.join("scripts");
        std::fs::create_dir_all(scripts.join("install")).unwrap();
        std::fs::write(scripts.join("install/driver.py"), b"").unwrap();
        std::fs::write(scripts.join("build_stages.py"), b"").unwrap();
        let nested = root.join("installer/target/debug");
        std::fs::create_dir_all(&nested).unwrap();
        assert_eq!(crate::runtime::find_root_from(&nested), Some(root.clone()));
        std::fs::remove_dir_all(root).unwrap();
    }
}
