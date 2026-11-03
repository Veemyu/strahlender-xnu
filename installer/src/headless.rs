//! `--cli build`: the same Rust steps as the window (request, requirements, source download, driver build) without a
//! window, update check, input restore or preference write. Protocol events go to stdout as JSON lines.
use crate::app::InstallTarget;
use crate::backend::{BuildRequest, Event, IosDelivery};
use crate::flow::{RequestInputs, backend_supported, build_request};
use crate::mod_support::{self, ModEntry};
use crate::platform::Platform;
use std::{
    io::Write,
    path::PathBuf,
    sync::{Arc, atomic::AtomicBool},
};

pub const USAGE: &str = "strahlender-xnu-installer --cli build --target macos|linux|windows|ios --keys FILE --base PATH [--update PATH] [--firmware PATH] [--mod NAME_OR_FOLDER] [--option key=value]... [--data-dir DIR] [--no-updates]\n\nOptions: portable_cpu, clean_build, auto_cleanup, ios_export_no_embed (true|false), ios_delivery (device|ipa), ios_device, ios_team, ios_profile_id.\nEvents are printed as JSON lines on stdout. The exit code is 0 only for a passed build.";

#[derive(Debug, Default, PartialEq, Eq)]
pub struct Config {
    pub target: Option<String>,
    pub keys: Option<PathBuf>,
    pub base: Option<PathBuf>,
    pub update: Option<PathBuf>,
    pub firmware: Option<PathBuf>,
    pub selected_mod: Option<String>,
    pub options: Vec<(String, String)>,
    pub data_dir: Option<PathBuf>,
}

pub fn parse(args: &[String]) -> Result<Config, String> {
    let mut config = Config::default();
    let mut iter = args.iter();
    while let Some(flag) = iter.next() {
        let mut value = |name: &str| {
            iter.next()
                .cloned()
                .ok_or_else(|| format!("{name} needs a value"))
        };
        match flag.as_str() {
            "--target" => config.target = Some(value(flag)?),
            "--keys" => config.keys = Some(value(flag)?.into()),
            "--base" => config.base = Some(value(flag)?.into()),
            "--update" => config.update = Some(value(flag)?.into()),
            "--firmware" => config.firmware = Some(value(flag)?.into()),
            "--mod" => config.selected_mod = Some(value(flag)?),
            "--data-dir" => config.data_dir = Some(value(flag)?.into()),
            // Accepted for scripts; this mode never checks for updates.
            "--no-updates" => {}
            "--option" => {
                let pair = value(flag)?;
                let (key, val) = pair
                    .split_once('=')
                    .ok_or_else(|| format!("--option expects key=value, got {pair}"))?;
                config.options.push((key.into(), val.into()));
            }
            other => return Err(format!("Unknown argument {other}")),
        }
    }
    Ok(config)
}

fn parse_target(value: &str) -> Result<InstallTarget, String> {
    match value {
        "macos" | "mac" => Ok(InstallTarget::Mac),
        "linux" => Ok(InstallTarget::Linux),
        "windows" | "windows-arm64" => Ok(InstallTarget::Windows),
        "ios" => Ok(InstallTarget::Ios),
        other => Err(format!("Unknown target {other}")),
    }
}

fn flag(value: &str, key: &str) -> Result<bool, String> {
    match value {
        "true" | "1" | "yes" => Ok(true),
        "false" | "0" | "no" => Ok(false),
        _ => Err(format!("Option {key} expects true or false")),
    }
}

pub struct Plan {
    pub request: BuildRequest,
    pub mods_folder: Option<PathBuf>,
    pub selected_mod: Option<String>,
    pub target: InstallTarget,
}

pub fn plan(config: &Config, host: Platform, arch: &str) -> Result<Plan, String> {
    let target = parse_target(config.target.as_deref().ok_or("--target is required")?)?;
    let mut mods_folder = mod_support::folder_for(host, target);
    let mut mods: Vec<ModEntry> = Vec::new();
    let mut selected_mod = None;
    if let Some(spec) = &config.selected_mod {
        let path = PathBuf::from(spec);
        if path.is_dir() {
            let library = mod_support::library_for_selection(
                &path.canonicalize().map_err(|error| error.to_string())?,
            )?;
            mods = mod_support::scan_selected(&path)?;
            mods_folder = Some(library);
            selected_mod = mods.first().map(|entry| entry.name.clone());
        } else {
            let folder = mods_folder.as_deref().ok_or("No mods folder available.")?;
            mods = mod_support::scan(folder)?;
            selected_mod = Some(spec.clone());
        }
        if !mods
            .iter()
            .any(|entry| Some(&entry.name) == selected_mod.as_ref())
        {
            return Err(format!("Mod {spec} was not found."));
        }
    }
    let mut ios_delivery = IosDelivery::Device;
    let mut ios_device = None;
    let mut ios_team = String::new();
    let mut ios_new_profile = None;
    let (mut portable_cpu, mut clean_build, mut no_embed, mut auto_cleanup) =
        (false, false, false, false);
    for (key, value) in &config.options {
        match key.as_str() {
            "portable_cpu" => portable_cpu = flag(value, key)?,
            "clean_build" => clean_build = flag(value, key)?,
            "ios_export_no_embed" => no_embed = flag(value, key)?,
            "auto_cleanup" => auto_cleanup = flag(value, key)?,
            "ios_delivery" => {
                ios_delivery = match value.as_str() {
                    "device" => IosDelivery::Device,
                    "ipa" => IosDelivery::Ipa,
                    _ => return Err("Option ios_delivery expects device or ipa".into()),
                }
            }
            "ios_device" => ios_device = Some(value.clone()),
            "ios_team" => ios_team = value.clone(),
            "ios_profile_id" => ios_new_profile = Some(value.clone()),
            _ => return Err(format!("Unknown option {key}")),
        }
    }
    if !backend_supported(
        host,
        target,
        arch,
        config.base.as_deref(),
        selected_mod.as_deref(),
        &mods,
    ) {
        return Err("This target cannot be built here with these inputs.".into());
    }
    let request = build_request(RequestInputs {
        target,
        arch,
        ios_delivery,
        ios_device,
        ios_team: &ios_team,
        ios_profile: None,
        ios_new_profile,
        portable_cpu,
        clean_build,
        ios_export_no_embed: no_embed,
        auto_cleanup,
        base: config.base.clone(),
        keys: config.keys.clone(),
        firmware: config.firmware.clone(),
        update: config.update.clone(),
        selected_mod: selected_mod.clone(),
        mods: &mods,
    })
    .map_err(|_| "--keys and --base are required.".to_string())?;
    Ok(Plan {
        request,
        mods_folder,
        selected_mod,
        target,
    })
}

pub fn event_json(event: &Event) -> serde_json::Value {
    use serde_json::json;
    match event {
        Event::Log { level, message } => {
            json!({"event": "log", "level": level, "message": message})
        }
        Event::Step { id, status } => json!({"event": "step", "id": id, "status": status}),
        Event::Progress {
            id,
            completed,
            total,
        } => json!({"event": "progress", "id": id, "completed": completed, "total": total}),
        Event::Transfer {
            id,
            completed,
            total,
        } => json!({"event": "transfer", "id": id, "completed": completed, "total": total}),
        Event::GeneratorProgress {
            module,
            phase,
            completed,
            total,
            modules_completed,
            modules_total,
        } => json!({
            "event": "generator_progress", "module": module, "phase": phase, "completed": completed,
            "total": total, "modules_completed": modules_completed, "modules_total": modules_total
        }),
        Event::Artifact { kind, path } => json!({"event": "artifact", "kind": kind, "path": path}),
        Event::IosProfile(profile) => json!({"event": "ios_profile", "profile": profile}),
        Event::PythonMissing => json!({"event": "python_missing"}),
        Event::RuntimeMissing => json!({"event": "runtime_missing"}),
        Event::Finished { ok, code } => json!({"event": "finished", "ok": ok, "code": code}),
        Event::Stopped => json!({"event": "stopped"}),
    }
}

/// Process exit code for the last event of a run.
pub fn exit_code(last: Option<&Event>) -> i32 {
    match last {
        Some(Event::Finished { ok: true, .. }) => 0,
        Some(Event::Finished { code, .. }) if (1..256).contains(code) => *code,
        Some(Event::Stopped) => 130,
        _ => 1,
    }
}

/// The driver build alone (source download included), reporting every event to `emit`.
pub fn run_build(
    plan: Plan,
    runtime: &tokio::runtime::Runtime,
    mut emit: impl FnMut(&Event),
) -> i32 {
    let (sender, mut receiver) = tokio::sync::mpsc::channel(32);
    let run = crate::backend::build(
        0,
        Arc::new(AtomicBool::new(false)),
        plan.mods_folder,
        plan.selected_mod,
        plan.request,
        sender,
    );
    let mut last = None;
    runtime.block_on(async {
        let collect = async {
            while let Some((_, event)) = receiver.recv().await {
                emit(&event);
                last = Some(event);
            }
        };
        tokio::join!(run, collect);
    });
    exit_code(last.as_ref())
}

fn requirements(target: InstallTarget, emit: &mut impl FnMut(&Event)) -> Result<(), String> {
    let inspect_target = if target == InstallTarget::Ios {
        "ios"
    } else {
        "native"
    };
    let step = |status: &str| Event::Step {
        id: "requirements".into(),
        status: status.into(),
    };
    emit(&step("started"));
    let mut plan = crate::dependencies::inspect(inspect_target)?;
    if !plan.ready() {
        let unattended = plan.manager == "windows-components"
            || (!plan.fetch.is_empty() && !crate::dependencies::needs_terminal(&plan));
        for line in plan.log_lines() {
            emit(&Event::Log {
                level: "info".into(),
                message: line,
            });
        }
        if unattended {
            crate::dependencies::install(&plan)?;
            plan = crate::dependencies::inspect(inspect_target)?;
        }
    }
    if !plan.ready() {
        for line in plan.log_lines() {
            emit(&Event::Log {
                level: "error".into(),
                message: line,
            });
        }
        return Err("Build requirements are not met.".into());
    }
    emit(&step("complete"));
    Ok(())
}

fn print(event: &Event) {
    let mut out = std::io::stdout().lock();
    let _ = writeln!(out, "{}", event_json(event));
    let _ = out.flush();
}

pub fn run(args: &[String]) -> i32 {
    let config = match parse(args) {
        Ok(config) => config,
        Err(error) => {
            eprintln!("{error}\n\n{USAGE}");
            return 2;
        }
    };
    if let Some(dir) = &config.data_dir {
        // Single threaded start, before any other thread reads the variable.
        unsafe { std::env::set_var("BDSP_INSTALLER_DATA_DIR", dir) };
    }
    let plan = match plan(&config, Platform::native(), std::env::consts::ARCH) {
        Ok(plan) => plan,
        Err(error) => {
            eprintln!("{error}");
            return 2;
        }
    };
    let mut emit = |event: &Event| print(event);
    if let Err(error) = requirements(plan.target, &mut emit) {
        emit(&Event::Log {
            level: "error".into(),
            message: error,
        });
        emit(&Event::Finished { ok: false, code: 3 });
        return 3;
    }
    let runtime = match tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
    {
        Ok(runtime) => runtime,
        Err(error) => {
            eprintln!("{error}");
            return 1;
        }
    };
    run_build(plan, &runtime, emit)
}
