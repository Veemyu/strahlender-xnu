//! The newest `main` source as a tarball pinned to one commit. Used by builds (workspace.rs) and by the Windows setup,
//! which runs outside any checkout. Shared with the `installer_setup` binary, so it depends on nothing else here.
use std::{
    path::{Path, PathBuf},
    sync::atomic::{AtomicBool, Ordering},
    time::Duration,
};

pub fn data_dir() -> Result<PathBuf, String> {
    crate::appdir::data_dir()
        .ok_or_else(|| "Your application data folder could not be located.".into())
}

/// Folder of the downloaded sources. On Windows the build below it must stay shallow, so a folder chosen in the build
/// options, or `BDSP_INSTALLER_DATA_DIR` (which wins), for example C:\bdsp, replaces the default below the user profile.
pub fn sources_dir() -> Result<PathBuf, String> {
    sources_dir_in(
        std::env::var_os("BDSP_INSTALLER_DATA_DIR"),
        crate::appdir::chosen_folder(crate::appdir::WORK_FOLDER),
        data_dir,
    )
}

fn sources_dir_in(
    override_dir: Option<std::ffi::OsString>,
    chosen: Option<PathBuf>,
    default: impl FnOnce() -> Result<PathBuf, String>,
) -> Result<PathBuf, String> {
    match override_dir.filter(|value| !value.is_empty()) {
        Some(folder) => Ok(PathBuf::from(folder).join("sources")),
        None => match chosen {
            Some(folder) => Ok(folder.join("sources")),
            None => default().map(|dir| dir.join("sources")),
        },
    }
}

pub fn client() -> Result<reqwest::blocking::Client, String> {
    reqwest::blocking::Client::builder()
        .user_agent(concat!("Strahlender-Installer/", env!("CARGO_PKG_VERSION")))
        .connect_timeout(Duration::from_secs(20))
        .timeout(Duration::from_secs(300))
        .build()
        .map_err(|error| error.to_string())
}

/// Development override: `BDSP_SOURCE_DIR` names a source checkout that is copied below `parent` instead of downloading `main`,
/// so a build can test scripts that are not on `main` yet. Only this function reads it.
const SOURCE_DIR_VARIABLE: &str = "BDSP_SOURCE_DIR";

/// Placeholder revision of a copied checkout; the folder name keeps the shape the pruning expects.
const LOCAL_REVISION: &str = "dec0de000000";

/// Downloads `main` into a fresh folder below `parent` and returns it (or copies the `BDSP_SOURCE_DIR` checkout).
pub fn download_main(parent: &Path, cancelled: &AtomicBool) -> Result<PathBuf, String> {
    if let Some(source) = std::env::var_os(SOURCE_DIR_VARIABLE).filter(|value| !value.is_empty()) {
        return copy_local_source(Path::new(&source), parent, cancelled);
    }
    let client = client()?;
    let sha = main_revision(&client)?;
    let sha = sha.as_str();
    if cancelled.load(Ordering::Acquire) {
        return Err("Source download cancelled.".into());
    }
    std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    // Each run owns its work folder; simultaneous installers cannot share generated files.
    let unique = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_err(|e| e.to_string())?
        .as_millis();
    let staging = parent.join(format!(".download-{}-{unique}", std::process::id()));
    std::fs::create_dir(&staging).map_err(|e| e.to_string())?;
    let result = (|| {
        let response = client
            .get(format!(
                "https://codeload.github.com/Veemyu/strahlender-xnu/tar.gz/{sha}"
            ))
            .send()
            .and_then(|r| r.error_for_status())
            .map_err(|e| format!("Source download failed: {e}"))?;
        let decoder = flate2::read::GzDecoder::new(response);
        let mut archive = tar::Archive::new(decoder);
        for entry in archive.entries().map_err(|e| e.to_string())? {
            if cancelled.load(Ordering::Acquire) {
                return Err("Source download cancelled.".into());
            }
            let mut entry = entry.map_err(|e| e.to_string())?;
            if !entry.unpack_in(&staging).map_err(|e| e.to_string())? {
                return Err("Unsafe path in source archive.".into());
            }
        }
        let root = staging.join(format!("strahlender-xnu-{sha}"));
        if !root.join("scripts/install/driver.py").is_file() {
            return Err("Downloaded source is missing its build driver.".into());
        }
        // 12 hex digits and milliseconds: 26 characters instead of 60, because Windows paths below this folder are
        // limited to 260 characters. Old downloads (40 hex digits, nanoseconds) are still recognized by prune_unused.
        let mut destination = parent.join(folder_name(sha, unique));
        let mut attempt = 0u32;
        while destination.exists() {
            attempt += 1;
            destination = parent.join(folder_name(sha, unique + u128::from(attempt)));
        }
        std::fs::rename(&root, &destination).map_err(|e| e.to_string())?;
        Ok(destination)
    })();
    let _ = std::fs::remove_dir_all(&staging);
    result
}

fn copy_local_source(
    source: &Path,
    parent: &Path,
    cancelled: &AtomicBool,
) -> Result<PathBuf, String> {
    if !source.join("scripts/install/driver.py").is_file() {
        return Err(format!(
            "{SOURCE_DIR_VARIABLE} does not name a source checkout (scripts/install/driver.py is missing)."
        ));
    }
    std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    let unique = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_err(|e| e.to_string())?
        .as_millis();
    let staging = parent.join(format!(".download-{}-{unique}", std::process::id()));
    let result = copy_tree(source, &staging, true, cancelled).and_then(|()| {
        let mut destination = parent.join(folder_name(LOCAL_REVISION, unique));
        let mut attempt = 0u32;
        while destination.exists() {
            attempt += 1;
            destination = parent.join(folder_name(LOCAL_REVISION, unique + u128::from(attempt)));
        }
        std::fs::rename(&staging, &destination).map_err(|e| e.to_string())?;
        Ok(destination)
    });
    if result.is_err() {
        let _ = std::fs::remove_dir_all(&staging);
    }
    result
}

/// Copies a checkout without its history, build outputs and earlier work (`.git`, `work`, and cargo's `target` below `installer`).
fn copy_tree(from: &Path, to: &Path, top: bool, cancelled: &AtomicBool) -> Result<(), String> {
    std::fs::create_dir_all(to).map_err(|e| e.to_string())?;
    for entry in std::fs::read_dir(from).map_err(|e| e.to_string())? {
        if cancelled.load(Ordering::Acquire) {
            return Err("Source copy cancelled.".into());
        }
        let entry = entry.map_err(|e| e.to_string())?;
        let name = entry.file_name();
        let kind = entry.file_type().map_err(|e| e.to_string())?;
        if kind.is_symlink() || (top && (name == ".git" || name == "work")) {
            continue;
        }
        let target = to.join(&name);
        if kind.is_dir() {
            copy_tree(&entry.path(), &target, false, cancelled)?;
        } else {
            std::fs::copy(entry.path(), &target).map_err(|e| e.to_string())?;
        }
    }
    Ok(())
}

/// "<12 hex digits of the revision>-<milliseconds>".
fn folder_name(sha: &str, unique: u128) -> String {
    format!("{}-{unique}", &sha[..12])
}

/// The commit `main` points at. The GitHub API answers first; its anonymous rate limit is shared by everyone behind
/// one address (HTTP 403), so the git transport, which has no such limit, is the fallback.
fn main_revision(client: &reqwest::blocking::Client) -> Result<String, String> {
    let api = client
        .get("https://api.github.com/repos/Veemyu/strahlender-xnu/commits/main")
        .send()
        .and_then(|r| r.error_for_status())
        .and_then(|r| r.json::<serde_json::Value>());
    let from_api = api
        .as_ref()
        .ok()
        .and_then(|value| value["sha"].as_str())
        .filter(|sha| valid_revision(sha))
        .map(str::to_owned);
    if let Some(sha) = from_api {
        return Ok(sha);
    }
    let refs = client
        .get("https://github.com/Veemyu/strahlender-xnu.git/info/refs?service=git-upload-pack")
        .send()
        .and_then(|r| r.error_for_status())
        .and_then(|r| r.text());
    match refs {
        Ok(text) => revision_from_refs(&text)
            .ok_or_else(|| "GitHub returned an invalid source revision.".into()),
        Err(error) => Err(format!(
            "Could not check main. Check your connection and retry: {}",
            api.err().map_or(error.to_string(), |e| e.to_string())
        )),
    }
}

/// Reads the `refs/heads/main` line of a git `info/refs` advertisement: "<4 hex length><40 hex sha> refs/heads/main".
fn revision_from_refs(text: &str) -> Option<String> {
    const SUFFIX: &str = " refs/heads/main";
    let line = text.lines().find(|line| line.ends_with(SUFFIX))?;
    let sha = line.get(line.len().checked_sub(SUFFIX.len() + 40)?..line.len() - SUFFIX.len())?;
    valid_revision(sha).then(|| sha.to_owned())
}

/// Deletes source downloads under `parent` that nothing uses any more: older than `older_than`, without a `work` folder (a build that
/// is still running or kept its work has one) and not `keep`. Every setup and every build downloads its own copy of `main`; a failed
/// or interrupted run leaves it behind. Never fails, never touches anything that is not a plain folder of the form <revision>-<number> (revision: 12 or 40 hex digits).
pub fn prune_unused(parent: &Path, keep: Option<&Path>, older_than: Duration) {
    let Ok(entries) = std::fs::read_dir(parent) else {
        return;
    };
    for entry in entries.flatten() {
        let path = entry.path();
        let name = entry.file_name().to_string_lossy().into_owned();
        let plain = path.is_dir()
            && !entry.file_type().is_ok_and(|t| t.is_symlink())
            && name.split_once('-').is_some_and(|(revision, number)| {
                (valid_revision(revision)
                    || (revision.len() == 12 && revision.bytes().all(|b| b.is_ascii_hexdigit())))
                    && !number.is_empty()
                    && number.bytes().all(|b| b.is_ascii_digit())
            });
        let old = entry
            .metadata()
            .and_then(|m| m.modified())
            .ok()
            .and_then(|time| time.elapsed().ok())
            .is_some_and(|age| age >= older_than);
        if plain && old && Some(path.as_path()) != keep && !path.join("work").exists() {
            let _ = std::fs::remove_dir_all(&path);
        }
    }
}

fn valid_revision(value: &str) -> bool {
    value.len() == 40 && value.bytes().all(|b| b.is_ascii_hexdigit())
}

#[cfg(test)]
mod tests {
    use std::path::PathBuf;
    use std::sync::atomic::AtomicBool;

    #[test]
    fn a_local_checkout_is_copied_without_history_and_work_and_must_be_a_checkout() {
        let base = std::env::temp_dir().join(format!("bdsp-source-dir-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&base);
        let source = base.join("checkout");
        for (path, text) in [
            ("scripts/install/driver.py", "driver"),
            ("installer/src/main.rs", "main"),
            (".git/config", "history"),
            ("work/romfs/file", "game data"),
        ] {
            let file = source.join(path);
            std::fs::create_dir_all(file.parent().unwrap()).unwrap();
            std::fs::write(file, text).unwrap();
        }
        let parent = base.join("sources");
        let never = AtomicBool::new(false);
        let copy = super::copy_local_source(&source, &parent, &never).unwrap();
        assert!(copy.join("scripts/install/driver.py").is_file());
        assert!(copy.join("installer/src/main.rs").is_file());
        assert!(!copy.join(".git").exists());
        assert!(!copy.join("work").exists());
        let name = copy.file_name().unwrap().to_string_lossy().into_owned();
        assert!(name.starts_with(super::LOCAL_REVISION));
        assert_eq!(std::fs::read_dir(&parent).unwrap().count(), 1);
        let empty = base.join("empty");
        std::fs::create_dir_all(&empty).unwrap();
        assert!(super::copy_local_source(&empty, &parent, &never).is_err());
        let _ = std::fs::remove_dir_all(&base);
    }

    #[test]
    fn the_data_folder_variable_replaces_the_default_sources_folder() {
        let default = || Ok(PathBuf::from("profile").join("data"));
        assert_eq!(
            super::sources_dir_in(Some("short".into()), None, default).unwrap(),
            PathBuf::from("short").join("sources")
        );
        for unset in [None, Some("".into())] {
            assert_eq!(
                super::sources_dir_in(unset, None, default).unwrap(),
                PathBuf::from("profile").join("data").join("sources")
            );
        }
    }

    #[test]
    fn a_chosen_folder_beats_the_default_and_the_variable_beats_it() {
        let default = || Ok(PathBuf::from("profile").join("data"));
        let chosen = Some(PathBuf::from("chosen"));
        assert_eq!(
            super::sources_dir_in(None, chosen.clone(), default).unwrap(),
            PathBuf::from("chosen").join("sources")
        );
        assert_eq!(
            super::sources_dir_in(Some("short".into()), chosen, default).unwrap(),
            PathBuf::from("short").join("sources")
        );
    }

    #[test]
    fn main_is_read_from_the_git_advertisement() {
        let sha = "fd7146c4fab98b479e37262efd17fe7284d31dad";
        let text = format!(
            "001e# service=git-upload-pack\n0000015900000000000000000000000000000000000000aa HEAD\0caps\n003d{sha} refs/heads/main\n003c{} refs/heads/win\n",
            "f3c7940de209f543d654e3a6d710a68b88ee1a1b"
        );
        assert_eq!(super::revision_from_refs(&text).as_deref(), Some(sha));
        assert_eq!(super::revision_from_refs("0000 refs/heads/main\n"), None);
        assert_eq!(super::revision_from_refs("no refs here"), None);
    }

    #[test]
    fn unused_source_downloads_are_pruned_but_kept_work_and_other_folders_stay() {
        let parent = std::env::temp_dir().join(format!("bdsp-prune-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&parent);
        let revision = "a".repeat(40);
        let mk = |name: &str, with_work: bool| {
            let dir = parent.join(name);
            std::fs::create_dir_all(dir.join("scripts")).unwrap();
            if with_work {
                std::fs::create_dir_all(dir.join("work")).unwrap();
            }
            dir
        };
        let old = mk(&format!("{revision}-111"), false);
        let with_work = mk(&format!("{revision}-222"), true);
        let current = mk(&format!("{revision}-333"), false);
        let short_old = mk("aaaaaaaaaaaa-1762170000000", false);
        let short_work = mk("aaaaaaaaaaaa-1762170000001", true);
        let foreign = mk("notes", false);
        // nothing is old enough yet
        super::prune_unused(
            &parent,
            Some(&current),
            std::time::Duration::from_secs(3600),
        );
        assert!(
            old.exists()
                && short_old.exists()
                && with_work.exists()
                && current.exists()
                && foreign.exists()
        );
        // with a zero age everything unused goes, except the work folder, the current one and folders that are not ours
        super::prune_unused(&parent, Some(&current), std::time::Duration::ZERO);
        assert!(!old.exists() && !short_old.exists());
        assert!(short_work.exists() && with_work.exists() && current.exists() && foreign.exists());
        let _ = std::fs::remove_dir_all(&parent);
    }

    #[test]
    fn source_folder_names_are_short() {
        let name = super::folder_name(&"a".repeat(40), 1_762_170_000_000);
        assert_eq!(name, "aaaaaaaaaaaa-1762170000000");
        assert_eq!(name.len(), 26);
    }

    #[test]
    fn validates_remote_revision_before_constructing_paths() {
        assert!(super::valid_revision(&"a".repeat(40)));
        assert!(!super::valid_revision("../../main"));
        assert!(!super::valid_revision(&"z".repeat(40)));
    }
}
