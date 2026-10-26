use iced::futures::SinkExt;
use serde::Deserialize;
#[cfg(unix)]
use std::os::unix::process::CommandExt;
use std::{
    path::{Path, PathBuf},
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

pub struct BuildRequest {
    pub target: &'static str,
    pub portable_cpu: bool,
    pub base: PathBuf,
    pub prod_keys: PathBuf,
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

pub fn project_root() -> Option<PathBuf> {
    let starts = vec![std::env::current_dir().ok()?, std::env::current_exe().ok()?];
    #[cfg(debug_assertions)]
    let mut starts = starts;
    #[cfg(debug_assertions)]
    if let Some(manifest) = option_env!("CARGO_MANIFEST_DIR") {
        starts.push(PathBuf::from(manifest));
    }
    starts.into_iter().find_map(|start| find_root_from(&start))
}

fn host_target() -> Option<&'static str> {
    match (std::env::consts::OS, std::env::consts::ARCH) {
        ("macos", "aarch64") => Some("macos-aarch64"),
        ("macos", "x86_64") => Some("macos-x86_64"),
        ("linux", "aarch64") => Some("linux-aarch64"),
        ("linux", "x86_64") => Some("linux-x86_64"),
        ("windows", "aarch64") => Some("windows-aarch64"),
        ("windows", "x86_64") => Some("windows-x86_64"),
        _ => None,
    }
}

fn verified_runtime_python(runtime: &Path) -> Option<PathBuf> {
    let marker: serde_json::Value =
        serde_json::from_slice(&std::fs::read(runtime.join("runtime.json")).ok()?).ok()?;
    if marker.get("schema")?.as_u64()? != 1
        || marker.get("target")?.as_str()? != host_target()?
        || marker.get("python")?.as_str()? != "3.13.15"
    {
        return None;
    }
    let executable = if cfg!(windows) {
        runtime.join("python/python.exe")
    } else {
        runtime.join("python/bin/python3")
    };
    executable.is_file().then_some(executable)
}

fn bundled_runtime() -> Option<PathBuf> {
    let executable = std::env::current_exe().ok()?;
    let contents = executable.parent()?.parent()?;
    runtime_in_resources(&contents.join("Resources"))
}

fn runtime_in_resources(resources: &Path) -> Option<PathBuf> {
    let runtime = resources.join("runtime");
    if let Some(host) = host_target()
        && let Some(python) = verified_runtime_python(&runtime.join(host))
    {
        return Some(python);
    }
    // Existing single-architecture Mac bundles and Linux AppImages.
    verified_runtime_python(&runtime)
}

fn backend_python() -> Option<(PathBuf, bool)> {
    if let Some(runtime) = std::env::var_os("BDSP_INSTALLER_RUNTIME") {
        return verified_runtime_python(Path::new(&runtime)).map(|python| (python, true));
    }
    if let Some(python) = bundled_runtime() {
        return Some((python, true));
    }
    if let Some(dirs) = directories::ProjectDirs::from("dev", "Veemyu", "strahlender-xnu-installer")
        && let Some(target) = host_target()
        && let Some(python) =
            verified_runtime_python(&dirs.data_dir().join("runtimes/3.13.15").join(target))
    {
        return Some((python, true));
    }
    cfg!(debug_assertions).then(|| (PathBuf::from("python3"), false))
}

pub fn runtime_smoke() -> Result<(), String> {
    let (python, private) = backend_python().ok_or("The bundled Python runtime is missing.")?;
    if !private {
        return Err("Runtime smoke checks require private Python.".into());
    }
    let status = std::process::Command::new(python)
        .args([
            "-I",
            "-B",
            "-c",
            concat!(
                include_str!("../runtime/native_smoke.py"),
                "\nimport UnityPy, UnityPy.UnityPyBoost\n"
            ),
        ])
        .status()
        .map_err(|e| e.to_string())?;
    if status.success() {
        Ok(())
    } else {
        Err("Private runtime smoke check failed.".into())
    }
}

fn find_root_from(start: &Path) -> Option<PathBuf> {
    let mut current = if start.is_file() {
        start.parent()?.to_path_buf()
    } else {
        start.to_path_buf()
    };
    loop {
        if current.join("scripts/install/driver.py").is_file()
            && current.join("scripts/build_stages.py").is_file()
        {
            return Some(current);
        }
        if !current.pop() {
            return None;
        }
    }
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
        let root = match crate::workspace::prepare(run_id, &mut output, cancelled.clone()).await {
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
        // LLVM still leads PATH; select Git separately so Brew cannot shadow Apple Git.
        command.env("BDSP_GIT", crate::dependencies::git());
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
                portable_cpu,
                base,
                prod_keys,
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
                #[cfg(debug_assertions)]
                set_development_install_root(
                    &mut command,
                    std::env::var_os("BDSP_INSTALLER_DEV_CHECKOUT").as_deref()
                        == Some(std::ffi::OsStr::new("1")),
                    std::env::var_os("BDSP_INSTALLER_DEV_INSTALL_ROOT"),
                );
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
        let Some(host) = super::host_target() else {
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
        std::fs::write(
            runtime.join("runtime.json"),
            format!(r#"{{"schema":1,"target":"{host}","python":"3.13.15"}}"#),
        )
        .unwrap();
        assert_eq!(super::verified_runtime_python(&runtime), Some(executable));
        std::fs::write(
            runtime.join("runtime.json"),
            r#"{"schema":1,"target":"wrong-host","python":"3.13.15"}"#,
        )
        .unwrap();
        assert_eq!(super::verified_runtime_python(&runtime), None);
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
        let host = super::host_target().unwrap();
        let native = resources.join("runtime").join(host);
        let executable = native.join(if cfg!(windows) {
            "python/python.exe"
        } else {
            "python/bin/python3"
        });
        std::fs::create_dir_all(executable.parent().unwrap()).unwrap();
        std::fs::write(&executable, b"fixture").unwrap();
        std::fs::write(
            native.join("runtime.json"),
            format!(r#"{{"schema":1,"target":"{host}","python":"3.13.15"}}"#),
        )
        .unwrap();
        assert_eq!(super::runtime_in_resources(&resources), Some(executable));
        std::fs::write(
            native.join("runtime.json"),
            r#"{"schema":1,"target":"other-architecture","python":"3.13.15"}"#,
        )
        .unwrap();
        assert_eq!(super::runtime_in_resources(&resources), None);
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
        assert_eq!(super::find_root_from(&nested), Some(root.clone()));
        std::fs::remove_dir_all(root).unwrap();
    }
}
