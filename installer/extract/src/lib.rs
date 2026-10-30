//! Stage "extract": ExeFS, RomFS, version and original icons from the user's own XCI/NSP/NCA files.
//! hactool does the cryptography; this crate orchestrates it and never relays its output (it can contain keys).
pub mod icons;
pub mod manifest;
pub mod nca;
pub mod unpack;

use nca::Nca;
use std::{
    ffi::OsString,
    fs,
    path::{Path, PathBuf},
    process::{Command, Stdio},
};

/// Exit codes shared with scripts/build_all.sh: 3 input missing, 5 hactool, 6 keys, 7 NCA not found, 9 check.
#[derive(Debug)]
pub struct Failure {
    pub code: i32,
    pub message: String,
}

fn fail<T>(code: i32, message: impl Into<String>) -> Result<T, Failure> {
    Err(Failure {
        code,
        message: message.into(),
    })
}

pub struct Request {
    pub base: PathBuf,
    pub update: Option<PathBuf>,
    pub keys: PathBuf,
    pub title_keys: Option<PathBuf>,
    pub hactool: PathBuf,
    pub work: PathBuf,
    pub icons: Option<PathBuf>,
    pub force: bool,
    pub keep_nca: bool,
}

#[derive(Debug, PartialEq)]
pub enum Outcome {
    Skipped,
    Extracted,
}

fn base_kind(base: &Path) -> Result<&'static str, Failure> {
    if base.is_dir() {
        return Ok("nca");
    }
    match base
        .extension()
        .map(|e| e.to_string_lossy().to_lowercase())
        .as_deref()
    {
        Some("xci") => Ok("xci"),
        Some("nsp") => Ok("nsp"),
        _ => fail(3, "Choose an XCI, base NSP or NCA directory"),
    }
}

fn folder_size(path: &Path) -> u64 {
    fs::read_dir(path)
        .map(|entries| {
            entries
                .flatten()
                .filter_map(|e| e.metadata().ok())
                .filter(|m| m.is_file())
                .map(|m| m.len())
                .sum()
        })
        .unwrap_or(0)
}

fn sizes(request: &Request, kind: &str) -> (u64, u64) {
    let base = if kind == "nca" {
        folder_size(&request.base)
    } else {
        fs::metadata(&request.base).map_or(0, |m| m.len())
    };
    (
        base,
        request
            .update
            .as_deref()
            .and_then(|u| fs::metadata(u).ok())
            .map_or(0, |m| m.len()),
    )
}

fn inputs<'a>(request: &'a Request, kind: &'a str) -> manifest::Inputs<'a> {
    let (base_size, update_size) = sizes(request, kind);
    manifest::Inputs {
        base_kind: kind,
        base: &request.base,
        update: request.update.as_deref(),
        base_size,
        update_size,
    }
}

/// True if the existing extraction matches these inputs (used by `check` and the cache).
pub fn up_to_date(request: &Request) -> Result<bool, Failure> {
    let kind = base_kind(&request.base)?;
    let icons_present = request
        .icons
        .as_ref()
        .is_none_or(|dir| dir.join("icons.json").is_file());
    Ok(icons_present && manifest::matches(&request.work, &inputs(request, kind)))
}

struct Tool {
    executable: PathBuf,
    keys: PathBuf,
    home: PathBuf,
}

impl Tool {
    fn new(request: &Request, home: PathBuf) -> Result<Self, Failure> {
        fs::create_dir_all(home.join(".switch")).map_err(|e| Failure {
            code: 9,
            message: e.to_string(),
        })?;
        Ok(Self {
            executable: request.hactool.clone(),
            keys: request.keys.clone(),
            home,
        })
    }

    fn command(&self, args: &[OsString]) -> Command {
        let mut command = Command::new(&self.executable);
        command
            .arg("-k")
            .arg(&self.keys)
            .args(["--disablekeywarns", "--suppresskeys"])
            .args(args)
            .env("HOME", &self.home)
            .env("USERPROFILE", &self.home)
            .env("XDG_CONFIG_HOME", &self.home)
            .current_dir(&self.home)
            .stdin(Stdio::null())
            .stderr(Stdio::null());
        command
    }

    /// Runs hactool with all output discarded.
    fn run(&self, args: &[OsString]) -> Result<(), String> {
        let status = self
            .command(args)
            .stdout(Stdio::null())
            .status()
            .map_err(|e| e.to_string())?;
        status
            .success()
            .then_some(())
            .ok_or_else(|| "hactool failed".to_string())
    }

    fn capture(&self, args: &[OsString]) -> Option<String> {
        let output = self.command(args).stdout(Stdio::piped()).output().ok()?;
        output
            .status
            .success()
            .then(|| String::from_utf8_lossy(&output.stdout).into_owned())
    }

    fn unpack(&self, source: &Path, destination: &Path, kind: &str) -> Result<(), String> {
        let (container, flag) = if kind == "xci" {
            ("xci", "--securedir=")
        } else {
            ("pfs0", "--pfs0dir=")
        };
        let mut option = OsString::from(flag);
        option.push(destination);
        self.run(&["-t".into(), container.into(), option, source.into()])
    }

    fn classify(&self, directory: &Path, log: &mut dyn FnMut(&str)) -> Result<Vec<Nca>, Failure> {
        let mut files: Vec<_> = fs::read_dir(directory)
            .map(|entries| entries.flatten().map(|e| e.path()).collect())
            .unwrap_or_default();
        files.retain(|p| {
            p.extension().is_some_and(|e| e.eq_ignore_ascii_case("nca")) && p.is_file()
        });
        files.sort();
        let mut found = Vec::new();
        for file in files {
            match self
                .capture(&["-i".into(), file.clone().into()])
                .map(|text| nca::parse_nca_info(&text, &file))
            {
                Some(Ok(info)) if info.title_id.len() == 16 => found.push(info),
                _ => log(&format!(
                    "  Note: {} not readable (skipped)",
                    file.file_name().unwrap_or_default().to_string_lossy()
                )),
            }
        }
        if found.is_empty() {
            return fail(
                6,
                "No NCA readable: does prod.keys match the firmware/master key revision?",
            );
        }
        Ok(found)
    }
}

fn related<'a>(rows: &'a [Nca], kind: &str, title_id: &str) -> Result<Option<&'a Nca>, Failure> {
    nca::pick_related(rows, kind, title_id).map_err(|message| Failure { code: 9, message })
}

fn io(error: std::io::Error) -> Failure {
    Failure {
        code: 9,
        message: error.to_string(),
    }
}

fn option(name: &str, path: &Path) -> OsString {
    let mut text = OsString::from(name);
    text.push(path);
    text
}

/// Moves exefs, romfs and manifest.json into `work`; the previous result is restored if anything fails.
fn publish(stage: &Path, work: &Path) -> Result<(), Failure> {
    const NAMES: [&str; 3] = ["exefs", "romfs", "manifest.json"];
    let backup = work.join(".previous");
    let _ = fs::remove_dir_all(&backup);
    fs::create_dir_all(&backup).map_err(io)?;
    let mut moved = Vec::new();
    let mut installed = Vec::new();
    let result = (|| {
        for name in NAMES {
            if work.join(name).exists() {
                fs::rename(work.join(name), backup.join(name))?;
                moved.push(name);
            }
        }
        for name in NAMES {
            fs::rename(stage.join(name), work.join(name))?;
            installed.push(name);
        }
        Ok::<(), std::io::Error>(())
    })();
    if let Err(error) = result {
        for name in installed.iter().rev() {
            let _ = fs::rename(work.join(name), stage.join(name));
        }
        for name in moved.iter().rev() {
            let _ = fs::rename(backup.join(name), work.join(name));
        }
        return fail(9, format!("Publishing the extraction failed: {error}"));
    }
    let _ = fs::remove_dir_all(&backup);
    Ok(())
}

pub fn extract(request: &Request, log: &mut dyn FnMut(&str)) -> Result<Outcome, Failure> {
    // hactool runs in a private working directory, so every path must be absolute first.
    let absolute = |path: &Path| {
        path.canonicalize().map_err(|_| Failure {
            code: 3,
            message: format!("Not found: {}", path.display()),
        })
    };
    let request = &Request {
        base: absolute(&request.base)?,
        update: request.update.as_deref().map(absolute).transpose()?,
        keys: absolute(&request.keys)?,
        title_keys: request.title_keys.as_deref().map(absolute).transpose()?,
        hactool: absolute(&request.hactool)?,
        work: {
            fs::create_dir_all(&request.work).map_err(io)?;
            absolute(&request.work)?
        },
        icons: request
            .icons
            .as_deref()
            .map(|p| {
                let _ = fs::create_dir_all(p);
                absolute(p)
            })
            .transpose()?,
        force: request.force,
        keep_nca: request.keep_nca,
    };
    let kind = base_kind(&request.base)?;
    if !request.base.exists() || !request.keys.is_file() {
        return fail(3, "Base game or prod.keys not found");
    }
    if request.update.as_ref().is_some_and(|u| !u.is_file()) {
        return fail(3, "The selected update NSP was not found");
    }
    let title_keys = match &request.title_keys {
        Some(path) => Some(fs::read_to_string(path).map_err(|_| Failure {
            code: 3,
            message: "title.keys not readable".into(),
        })?),
        None => None,
    };
    fs::create_dir_all(&request.work).map_err(io)?;
    let work = request.work.canonicalize().map_err(io)?;
    if ["exefs", "romfs", ".stage"].iter().any(|d| {
        request
            .base
            .canonicalize()
            .is_ok_and(|b| b.starts_with(work.join(d)))
    }) {
        return fail(
            3,
            "Choose your original input outside the replaceable extraction folders",
        );
    }
    if !request.force && up_to_date(request)? {
        log("extract: manifest.json matches, skipped (--force to regenerate)");
        return Ok(Outcome::Skipped);
    }
    let stage = work.join(".stage");
    let _ = fs::remove_dir_all(&stage);
    fs::create_dir_all(&stage).map_err(io)?;
    let result = run_stage(request, kind, title_keys.as_deref(), &work, &stage, log);
    if request.keep_nca {
        for name in ["nca-base", "nca-update"] {
            let _ = fs::remove_dir_all(work.join(name));
            let _ = fs::rename(stage.join(name), work.join(name));
        }
    }
    let _ = fs::remove_dir_all(&stage);
    result.map(|()| Outcome::Extracted)
}

fn run_stage(
    request: &Request,
    kind: &str,
    title_keys: Option<&str>,
    work: &Path,
    stage: &Path,
    log: &mut dyn FnMut(&str),
) -> Result<(), Failure> {
    let tool = Tool::new(request, stage.join("home"))?;
    let update = request.update.is_some();
    let base_dir = stage.join("nca-base");
    let update_dir = stage.join("nca-update");
    log("1/5 unpack the game containers");
    let base_dir = if kind == "nca" {
        request.base.clone()
    } else {
        tool.unpack(&request.base, &base_dir, kind)
            .map_err(|_| Failure {
                code: 5,
                message: "The base game cannot be unpacked (file damaged or keys missing)".into(),
            })?;
        base_dir
    };
    if let Some(update) = &request.update {
        tool.unpack(update, &update_dir, "nsp")
            .map_err(|_| Failure {
                code: 5,
                message: "The update NSP cannot be unpacked".into(),
            })?;
    }

    log("2/5 classify NCAs (content type, title ID)");
    let base_nca = tool.classify(&base_dir, log)?;
    let Some(base_program) = nca::pick(&base_nca, "Program", None) else {
        return fail(7, "No Program NCA found in the base game");
    };
    let title_id = base_program.title_id.clone();
    log(&format!("    base game: title ID {title_id}"));
    let update_nca = if update {
        tool.classify(&update_dir, log)?
    } else {
        Vec::new()
    };
    let (rows, rows_dir) = if update {
        (&update_nca, &update_dir)
    } else {
        (&base_nca, &base_dir)
    };
    let Some(program) = nca::pick(rows, "Program", Some(&title_id)) else {
        return fail(
            7,
            "No update Program NCA for this title ID in the NSP (wrong update?)",
        );
    };
    let control = related(rows, "Control", &title_id)?;
    let meta = related(rows, "Meta", &title_id)?;
    let base_control = if update {
        related(&base_nca, "Control", &title_id)?
    } else {
        control
    };

    log("3/5 title keys (ticket or title.keys)");
    let mut selected = vec![(base_program, &base_dir), (program, rows_dir)];
    selected.extend(control.map(|c| (c, rows_dir)));
    selected.extend(meta.map(|m| (m, rows_dir)));
    if update {
        selected.extend(base_control.map(|c| (c, &base_dir)));
    }
    let mut keys = std::collections::BTreeMap::new();
    for (info, dir) in &selected {
        if let Some(rights) = &info.rights_id {
            let key = nca::find_title_key(rights, dir, title_keys).map_err(|m| Failure {
                code: 6,
                message: m,
            })?;
            keys.insert(rights.clone(), key);
        }
    }
    let text: String = keys
        .iter()
        .map(|(rights, key)| format!("{rights} = {key}\n"))
        .collect();
    fs::write(stage.join("home/.switch/title.keys"), text).map_err(io)?;

    log(&format!(
        "4/5 extract ExeFS and RomFS{}",
        if update {
            " (the update applied to the base NCA)"
        } else {
            ""
        }
    ));
    let mut arguments: Vec<OsString> = Vec::new();
    if update {
        arguments.push(option("--basenca=", &base_program.path));
    }
    arguments.extend([
        option("--exefsdir=", &stage.join("exefs")),
        option("--romfsdir=", &stage.join("romfs")),
        program.path.clone().into(),
    ]);
    tool.run(&arguments).map_err(|_| Failure {
        code: 5,
        message: "The game NCA cannot be extracted (master key revision in prod.keys?)".into(),
    })?;
    if fs::metadata(stage.join("exefs/main")).map_or(0, |m| m.len()) == 0 {
        return fail(9, "exefs/main is missing after the extraction");
    }
    if manifest::romfs_stats(&stage.join("romfs")).map_or(0, |s| s.0) == 0 {
        return fail(9, "romfs is empty after the extraction");
    }

    log("5/5 version, icons and manifest");
    let mut version = 0;
    if let Some(meta) = meta {
        let section = stage.join("cnmt");
        if tool
            .run(&[option("--section0dir=", &section), meta.path.clone().into()])
            .is_ok()
        {
            if let Some(file) = find_first(&section, "cnmt") {
                version = fs::read(file)
                    .ok()
                    .and_then(|d| nca::cnmt_version(&d).ok())
                    .unwrap_or(0);
            }
        }
    }
    let mut display = String::new();
    let extract_control = |info: &Nca, name: &str| -> Option<PathBuf> {
        let target = stage.join(name);
        tool.run(&[option("--romfsdir=", &target), info.path.clone().into()])
            .ok()
            .map(|()| target)
    };
    let update_control = control.and_then(|c| extract_control(c, "control"));
    if let Some(file) = update_control
        .as_deref()
        .and_then(|dir| find_first(dir, "nacp"))
    {
        display = fs::read(file)
            .ok()
            .and_then(|d| nca::nacp_display_version(&d).ok())
            .unwrap_or_default();
    }
    if let Some(destination) = &request.icons {
        // The update's Control wins; the base Control fills languages the update lacks.
        let base_dir_control = if update {
            base_control.and_then(|c| extract_control(c, "control-base"))
        } else {
            None
        };
        let sources: Vec<&Path> = if update {
            base_dir_control
                .iter()
                .chain(update_control.iter())
                .map(PathBuf::as_path)
                .collect()
        } else {
            update_control.iter().map(PathBuf::as_path).collect()
        };
        icons::ingest(&sources, destination, &title_id, log).map_err(|m| Failure {
            code: 9,
            message: m,
        })?;
    }
    let (base_size, update_size) = sizes(request, kind);
    let game = manifest::Game {
        title_id: &title_id,
        title_version: version,
        display_version: &display,
        update_applied: update,
    };
    let record = manifest::build(
        stage,
        &game,
        &manifest::Inputs {
            base_kind: kind,
            base: &request.base,
            update: request.update.as_deref(),
            base_size,
            update_size,
        },
    )
    .map_err(io)?;
    fs::write(
        stage.join("manifest.json"),
        serde_json::to_string_pretty(&record).unwrap() + "\n",
    )
    .map_err(io)?;
    publish(stage, work)
}

/// First file with this extension below `root` (the CNMT or the NACP).
fn find_first(root: &Path, extension: &str) -> Option<PathBuf> {
    let mut entries: Vec<_> = fs::read_dir(root)
        .ok()?
        .flatten()
        .map(|e| e.path())
        .collect();
    entries.sort();
    for path in entries {
        if path.is_dir() {
            if let Some(found) = find_first(&path, extension) {
                return Some(found);
            }
        } else if path
            .extension()
            .is_some_and(|e| e.eq_ignore_ascii_case(extension))
        {
            return Some(path);
        }
    }
    None
}

const USAGE: &str = "Usage: unpack ARCHIVE DESTINATION  (.zip, .tar.gz, .7z)\n       extract|check --base <xci|nsp|nca-folder> [--update <nsp>] --keys <prod.keys> [--title-keys <file>]\n         --hactool <path> --work <folder> [--icons <folder>] [--force] [--keep-nca]\nExit codes: 0 ok (check: up to date), 1 check: not up to date, 2 usage, 3 input missing, 5 hactool, 6 keys, 7 NCA not found, 9 check.";

/// Command line entry shared by the `bdsp-extract` binary and `strahlender-xnu-installer --cli`.
pub fn cli(args: Vec<OsString>) -> i32 {
    let usage = |message: &str| {
        eprintln!("{message}\n{USAGE}");
        2
    };
    let mut args = args.into_iter();
    let Some(command) = args
        .next()
        .and_then(|c| c.into_string().ok())
        .filter(|c| c == "extract" || c == "check" || c == "unpack")
    else {
        return usage("Unknown or missing command");
    };
    if command == "unpack" {
        return unpack::cli(&args.collect::<Vec<_>>());
    }
    let (mut base, mut update, mut keys, mut title_keys, mut hactool, mut work, mut icons) =
        (None, None, None, None, None, None, None);
    let (mut force, mut keep_nca) = (false, false);
    while let Some(flag) = args.next() {
        let slot = match flag.to_str() {
            Some("--force") => {
                force = true;
                continue;
            }
            Some("--keep-nca") => {
                keep_nca = true;
                continue;
            }
            Some("--base") => &mut base,
            Some("--update") => &mut update,
            Some("--keys") => &mut keys,
            Some("--title-keys") => &mut title_keys,
            Some("--hactool") => &mut hactool,
            Some("--work") => &mut work,
            Some("--icons") => &mut icons,
            _ => return usage("Unknown option"),
        };
        match args.next() {
            Some(value) => *slot = Some(PathBuf::from(value)),
            None => return usage("Missing option value"),
        }
    }
    let (Some(base), Some(keys), Some(hactool), Some(work)) = (base, keys, hactool, work) else {
        return usage("--base, --keys, --hactool and --work are required");
    };
    let request = Request {
        base,
        update,
        keys,
        title_keys,
        hactool,
        work,
        icons,
        force,
        keep_nca,
    };
    if command == "check" {
        return match up_to_date(&request) {
            Ok(true) => 0,
            Ok(false) => 1,
            Err(failure) => {
                eprintln!("{}", failure.message);
                failure.code
            }
        };
    }
    let mut log = |line: &str| println!("{line}");
    match extract(&request, &mut log) {
        Ok(Outcome::Skipped | Outcome::Extracted) => 0,
        Err(failure) => {
            eprintln!("ERROR: {}", failure.message);
            failure.code
        }
    }
}
