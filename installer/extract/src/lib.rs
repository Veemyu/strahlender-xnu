//! Stage "extract": ExeFS, RomFS, version and original icons from the user's own XCI/NSP/NCA files.
//! hactool does the cryptography; this crate orchestrates it and never relays its output (it can contain keys).
pub mod icons;
pub mod keys;
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

/// An earlier extraction is verified by hashing the game files again, which is silent and takes minutes: say so.
fn announce_check(request: &Request, log: &mut dyn FnMut(&str)) {
    if request.work.join("manifest.json").is_file() {
        log("    checking the earlier extraction (SHA-256 of the game files)");
    }
}

/// True if the existing extraction matches these inputs (used by `check` and the cache).
pub fn up_to_date(request: &Request) -> Result<bool, Failure> {
    let kind = base_kind(&request.base)?;
    let icons_present = request
        .icons
        .as_ref()
        .is_none_or(|dir| dir.join("icons.json").is_file());
    let inputs = inputs(request, kind);
    let expected = inputs.base_size + inputs.update_size;
    Ok(icons_present
        && hashing(expected, 0, 1000, || {
            manifest::matches(&request.work, &inputs)
        }))
}

struct Tool {
    executable: PathBuf,
    /// The copy of prod.keys that hactool reads (see `keys::for_hactool`).
    keys: PathBuf,
    home: PathBuf,
    /// Entries of the user's prod.keys left out of that copy.
    dropped: usize,
}

impl Tool {
    fn new(request: &Request, home: PathBuf) -> Result<Self, Failure> {
        fs::create_dir_all(home.join(".switch")).map_err(|e| Failure {
            code: 9,
            message: e.to_string(),
        })?;
        let (keys, dropped) = match fs::read(&request.keys) {
            Ok(bytes) => {
                let (text, dropped) = keys::for_hactool(&String::from_utf8_lossy(&bytes));
                let copy = home.join("prod.keys");
                fs::write(&copy, text).map_err(io)?;
                (copy, dropped)
            }
            Err(_) => (request.keys.clone(), 0),
        };
        Ok(Self {
            executable: request.hactool.clone(),
            keys,
            home,
            dropped,
        })
    }

    fn keys(&self) -> Option<keys::Keys> {
        fs::read(&self.keys)
            .ok()
            .map(|bytes| keys::Keys::parse(&String::from_utf8_lossy(&bytes)))
    }

    /// Logs what prod.keys contains (names only) and returns a short explanation for a failure message: the first problem
    /// found, or the note that the keys look complete. `needed` is the master key revision of the game NCA, when known.
    fn explain(&self, needed: Option<u32>, detail: &str, log: &mut dyn FnMut(&str)) -> String {
        if !detail.is_empty() {
            log(&format!("    {detail}"));
        }
        let Some(keys) = self.keys() else {
            return " prod.keys could not be read.".into();
        };
        log(&format!("    prod.keys: {}", keys.summary()));
        let problems = keys.problems(needed);
        for problem in &problems {
            log(&format!("    prod.keys: {problem}"));
        }
        let keys_note = match problems.first() {
            Some(first) => format!(" Keys: {first}."),
            None => " prod.keys has every key this game needs; the game files may be damaged or incomplete.".into(),
        };
        if detail.is_empty() {
            keys_note
        } else {
            format!(" ({detail}).{keys_note}")
        }
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
            .stdin(Stdio::null());
        command
    }

    /// Runs hactool with its output discarded. The error says how it failed: hactool prints key values in its warnings, so only
    /// its masked `Error:` lines are kept.
    fn run(&self, args: &[OsString]) -> Result<(), String> {
        let output = self
            .command(args)
            .stdout(Stdio::null())
            .stderr(Stdio::piped())
            .output()
            .map_err(|e| format!("hactool could not be started: {e}"))?;
        if output.status.success() {
            return Ok(());
        }
        let mut detail = match output.status.code() {
            Some(code) => format!("hactool exit code {code}"),
            None => "hactool was stopped by a signal".to_string(),
        };
        for line in keys::safe_error_lines(&output.stderr) {
            detail.push_str("; ");
            detail.push_str(&line);
        }
        Err(detail)
    }

    fn capture(&self, args: &[OsString]) -> Option<String> {
        let output = self
            .command(args)
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .output()
            .ok()?;
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
            let note = self.explain(None, "", log);
            return fail(
                6,
                format!(
                    "No NCA readable: does prod.keys match the firmware/master key revision?{note}"
                ),
            );
        }
        Ok(found)
    }
}

/// A combined XCI holds base and update; the Patch CNMT says which NCAs are the update (see `nca::split_update`).
fn embedded_update(
    tool: &Tool,
    stage: &Path,
    items: &[Nca],
    log: &mut dyn FnMut(&str),
) -> Result<Option<nca::Split>, Failure> {
    let mut metas = Vec::new();
    for (index, item) in items
        .iter()
        .filter(|n| n.content_type.eq_ignore_ascii_case("Meta"))
        .enumerate()
    {
        let section = stage.join(format!("cnmt-scan-{index}"));
        let parsed = tool
            .run(&[option("--section0dir=", &section), item.path.clone().into()])
            .ok()
            .and_then(|()| find_first(&section, "cnmt"))
            .and_then(|file| fs::read(file).ok())
            .and_then(|data| nca::parse_cnmt(&data).ok());
        metas.extend(parsed.map(|meta| (item, meta)));
    }
    if metas.len() < 2 {
        return Ok(None);
    }
    let split = nca::split_update(items, &metas).map_err(|message| Failure { code: 9, message })?;
    if split.is_some() {
        log("    the container holds the base game and its update; using the newest update");
    }
    Ok(split)
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

/// Size of everything below `dir` (missing folders count as 0).
fn tree_size(dir: &Path) -> u64 {
    let mut total = 0;
    let mut pending = vec![dir.to_path_buf()];
    while let Some(folder) = pending.pop() {
        let Ok(entries) = fs::read_dir(&folder) else {
            continue;
        };
        for entry in entries.flatten() {
            match entry.metadata() {
                Ok(meta) if meta.is_dir() => pending.push(entry.path()),
                Ok(meta) => total += meta.len(),
                Err(_) => {}
            }
        }
    }
    total
}

/// Runs `work` while a helper reports `done()` bytes out of `expected` as `extract progress <permille>` lines between
/// `from` and `to` (of 1000). hactool and the hashing of the inputs give no progress of their own.
fn reported<T>(
    done: impl Fn() -> u64 + Sync,
    expected: u64,
    from: u64,
    to: u64,
    work: impl FnOnce() -> T,
) -> T {
    use std::sync::atomic::{AtomicBool, Ordering::Relaxed};
    let stop = AtomicBool::new(false);
    std::thread::scope(|scope| {
        scope.spawn(|| {
            let mut last = 0;
            'poll: loop {
                let permille = from + (to - from) * done().min(expected.max(1)) / expected.max(1);
                if permille != last {
                    println!("extract progress {permille}");
                    last = permille;
                }
                for _ in 0..10 {
                    if stop.load(Relaxed) {
                        break 'poll;
                    }
                    std::thread::sleep(std::time::Duration::from_millis(50));
                }
            }
        });
        let result = work();
        stop.store(true, Relaxed);
        result
    })
}

/// Progress by the growth of the output folders below `dirs`.
fn watched<T>(dirs: &[&Path], expected: u64, from: u64, to: u64, work: impl FnOnce() -> T) -> T {
    reported(
        || dirs.iter().map(|dir| tree_size(dir)).sum(),
        expected,
        from,
        to,
        work,
    )
}

/// Progress by the bytes hashed while `work` runs (the SHA-256 of the inputs is the slowest silent part).
fn hashing<T>(expected: u64, from: u64, to: u64, work: impl FnOnce() -> T) -> T {
    use std::sync::atomic::Ordering::Relaxed;
    let start = manifest::HASHED.load(Relaxed);
    reported(
        || manifest::HASHED.load(Relaxed).saturating_sub(start),
        expected,
        from,
        to,
        work,
    )
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
    if !request.force {
        announce_check(request, log);
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
    if let Some(keys) = tool.keys() {
        log(&format!("    prod.keys: {}", keys.summary()));
    }
    if tool.dropped > 0 {
        log(&format!(
            "    prod.keys: {} master_kek_source entries with 34 hex digits left out, hactool cannot read them and extraction does not need them",
            tool.dropped
        ));
    }
    let base_dir = if kind == "nca" {
        request.base.clone()
    } else {
        let input = fs::metadata(&request.base).map_or(0, |m| m.len())
            + request
                .update
                .as_ref()
                .map_or(0, |u| fs::metadata(u).map_or(0, |m| m.len()));
        watched(&[&base_dir, &update_dir], input, 0, 250, || {
            tool.unpack(&request.base, &base_dir, kind)
        })
        .map_err(|detail| Failure {
            code: 5,
            message: format!(
                "The base game cannot be unpacked (file damaged or keys missing){}",
                tool.explain(None, &detail, log)
            ),
        })?;
        base_dir
    };
    if let Some(update) = &request.update {
        log("    unpacking the update (NSP)");
        tool.unpack(update, &update_dir, "nsp")
            .map_err(|detail| Failure {
                code: 5,
                message: format!(
                    "The update NSP cannot be unpacked{}",
                    tool.explain(None, &detail, log)
                ),
            })?;
    }

    log("2/5 classify NCAs (content type, title ID)");
    let mut base_nca = tool.classify(&base_dir, log)?;
    let mut update_dir = update_dir;
    let mut embedded = Vec::new();
    if !update {
        if let Some((base, newer)) = embedded_update(&tool, stage, &base_nca, log)? {
            (base_nca, embedded, update_dir) = (base, newer, base_dir.clone());
        }
    }
    let update = update || !embedded.is_empty();
    let Some(base_program) = nca::pick(&base_nca, "Program", None) else {
        return fail(7, "No Program NCA found in the base game");
    };
    let title_id = base_program.title_id.clone();
    log(&format!("    base game: title ID {title_id}"));
    let update_nca = if !embedded.is_empty() {
        embedded
    } else if update {
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
    let expected = program
        .size
        .max(fs::metadata(&program.path).map_or(0, |m| m.len()));
    watched(
        &[&stage.join("exefs"), &stage.join("romfs")],
        expected,
        250,
        700,
        || tool.run(&arguments),
    )
    .map_err(|detail| Failure {
        code: 5,
        message: format!(
            "The game NCA cannot be extracted (master key revision in prod.keys?){}",
            tool.explain(
                base_program.master_revision.max(program.master_revision),
                &detail,
                log
            )
        ),
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
    log("    recording the SHA-256 of the game files");
    let game = manifest::Game {
        title_id: &title_id,
        title_version: version,
        display_version: &display,
        update_applied: update,
    };
    let record = hashing(base_size + update_size, 700, 1000, || {
        manifest::build(
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
    })
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
        if !request.force {
            announce_check(&request, &mut |line| println!("{line}"));
        }
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
