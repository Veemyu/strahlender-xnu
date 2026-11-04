//! Packs the game's save folder into one .zip for a bug report. The user attaches the file to the GitHub issue; nothing is
//! uploaded. Only the `save_<n>` folders (and those of a mod, `mods/<name>/save_<n>`) are read: no keys, firmware or game files.
use std::{
    fs::{self, File},
    io::{self, Write},
    path::{Path, PathBuf},
    time::{SystemTime, UNIX_EPOCH},
};

/// A save is about 1 MiB; this leaves room for backups in the folder and stops a wrong folder from being packed.
pub const SIZE_CAP: u64 = 64 * 1024 * 1024;

#[derive(Debug, Clone)]
pub struct Export {
    pub path: PathBuf,
    pub files: usize,
    pub bytes: u64,
}

struct Entry {
    name: String,
    path: PathBuf,
    size: u64,
}

/// The save folder of the app the installer builds: the same locations the game itself uses (`BDSP_SAVE` wins, as in the game).
pub fn default_save_root() -> Option<PathBuf> {
    if let Some(folder) = std::env::var_os("BDSP_SAVE").filter(|value| !value.is_empty()) {
        return Some(PathBuf::from(folder));
    }
    let data = directories::BaseDirs::new()?.data_dir().to_path_buf();
    Some(if cfg!(target_os = "macos") {
        data.join("dev.local.xnubdsp").join("save")
    } else if cfg!(windows) {
        data.join("StrahlenderXnu").join("save")
    } else {
        data.join("strahlender-xnu").join("saves")
    })
}

/// Downloads, else Desktop, else the home folder.
pub fn default_output_dir() -> Option<PathBuf> {
    let dirs = directories::UserDirs::new()?;
    [dirs.download_dir(), dirs.desktop_dir()]
        .into_iter()
        .flatten()
        .find(|folder| folder.is_dir())
        .map(Path::to_path_buf)
        .or_else(|| Some(dirs.home_dir().to_path_buf()))
}

/// Resolves the default folders (or the given ones) and writes the zip.
pub fn export(save_root: Option<&Path>, out_dir: Option<&Path>) -> Result<Export, String> {
    let root = match save_root {
        Some(root) => root.to_path_buf(),
        None => {
            default_save_root().ok_or("The save folder could not be located on this computer.")?
        }
    };
    let out = match out_dir {
        Some(out) => out.to_path_buf(),
        None => default_output_dir().ok_or("No folder for the export could be found.")?,
    };
    build_zip(&root, &out, &today())
}

fn is_save_folder(name: &str) -> bool {
    name.strip_prefix("save_").is_some_and(|number| {
        !number.is_empty() && number.bytes().all(|byte| byte.is_ascii_digit())
    })
}

fn subfolders(folder: &Path) -> Vec<(String, PathBuf)> {
    let Ok(entries) = fs::read_dir(folder) else {
        return Vec::new();
    };
    let mut found: Vec<(String, PathBuf)> = entries
        .flatten()
        .filter(|entry| entry.file_type().is_ok_and(|kind| kind.is_dir()))
        .filter_map(|entry| Some((entry.file_name().into_string().ok()?, entry.path())))
        .collect();
    found.sort();
    found
}

/// Regular files only; links are not followed.
fn collect(folder: &Path, prefix: &str, into: &mut Vec<Entry>) -> io::Result<()> {
    let mut items: Vec<_> = fs::read_dir(folder)?.flatten().collect();
    items.sort_by_key(|item| item.file_name());
    for item in items {
        let Ok(name) = item.file_name().into_string() else {
            continue;
        };
        let kind = item.file_type()?;
        let name = format!("{prefix}/{name}");
        if kind.is_dir() {
            collect(&item.path(), &name, into)?;
        } else if kind.is_file() {
            into.push(Entry {
                name,
                path: item.path(),
                size: item.metadata()?.len(),
            });
        }
    }
    Ok(())
}

fn gather(root: &Path) -> Result<Vec<Entry>, String> {
    let mut found = Vec::new();
    let mut folders: Vec<(String, PathBuf)> = Vec::new();
    for (name, path) in subfolders(root) {
        if is_save_folder(&name) {
            folders.push((name, path));
        } else if name == "mods" {
            for (mod_name, mod_path) in subfolders(&path) {
                for (save, save_path) in subfolders(&mod_path) {
                    if is_save_folder(&save) {
                        folders.push((format!("mods/{mod_name}/{save}"), save_path));
                    }
                }
            }
        }
    }
    for (name, path) in folders {
        collect(&path, &name, &mut found)
            .map_err(|error| format!("The save folder could not be read: {error}"))?;
    }
    Ok(found)
}

/// Writes `bdsp-save-<date>.zip` (a numbered variant when it exists) into `out_dir` with paths relative to the save folder.
pub fn build_zip(root: &Path, out_dir: &Path, date: &str) -> Result<Export, String> {
    if !root.is_dir() {
        return Err(format!(
            "No save folder was found at {}. Start the game and save once, then try again.",
            root.display()
        ));
    }
    let entries = gather(root)?;
    if entries.is_empty() {
        return Err(
            "The save folder holds no save. Start the game and save once, then try again.".into(),
        );
    }
    let bytes: u64 = entries.iter().map(|entry| entry.size).sum();
    if bytes > SIZE_CAP {
        return Err(format!(
            "The save folder holds {} MiB, more than the {} MiB limit, so nothing was packed. Attach SaveData.bin and Backup.bin by hand instead.",
            bytes.div_ceil(1024 * 1024),
            SIZE_CAP / (1024 * 1024)
        ));
    }
    fs::create_dir_all(out_dir)
        .map_err(|error| format!("The export folder could not be created: {error}"))?;
    let target = free_name(out_dir, date);
    let part = target.with_extension("zip.part");
    let result = write_zip(&part, &entries).and_then(|()| fs::rename(&part, &target));
    if let Err(error) = result {
        let _ = fs::remove_file(&part);
        return Err(format!("The export could not be written: {error}"));
    }
    Ok(Export {
        path: target,
        files: entries.len(),
        bytes,
    })
}

fn free_name(folder: &Path, date: &str) -> PathBuf {
    let first = folder.join(format!("bdsp-save-{date}.zip"));
    if !first.exists() {
        return first;
    }
    (2..)
        .map(|n| folder.join(format!("bdsp-save-{date}-{n}.zip")))
        .find(|path| !path.exists())
        .expect("an unused number exists")
}

fn write_zip(path: &Path, entries: &[Entry]) -> io::Result<()> {
    let mut writer = zip::ZipWriter::new(File::create(path)?);
    let options = zip::write::SimpleFileOptions::default()
        .compression_method(zip::CompressionMethod::Deflated);
    for entry in entries {
        writer
            .start_file(entry.name.as_str(), options)
            .map_err(io::Error::other)?;
        io::copy(&mut File::open(&entry.path)?, &mut writer)?;
    }
    writer.finish().map_err(io::Error::other)?.flush()
}

/// UTC date as `YYYY-MM-DD`.
fn today() -> String {
    let seconds = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|elapsed| elapsed.as_secs())
        .unwrap_or(0);
    date_of((seconds / 86_400) as i64)
}

fn date_of(days_since_epoch: i64) -> String {
    let z = days_since_epoch + 719_468;
    let era = z.div_euclid(146_097);
    let day_of_era = z.rem_euclid(146_097);
    let year_of_era =
        (day_of_era - day_of_era / 1460 + day_of_era / 36_524 - day_of_era / 146_096) / 365;
    let day_of_year = day_of_era - (365 * year_of_era + year_of_era / 4 - year_of_era / 100);
    let month_part = (5 * day_of_year + 2) / 153;
    let day = day_of_year - (153 * month_part + 2) / 5 + 1;
    let month = if month_part < 10 {
        month_part + 3
    } else {
        month_part - 9
    };
    let year = year_of_era + era * 400 + i64::from(month <= 2);
    format!("{year:04}-{month:02}-{day:02}")
}

pub const PRIVACY_NOTE: &str = "The file contains your trainer name and play data. It has no keys and no game files. Nothing is uploaded: attach the file to the GitHub issue yourself.";

/// `strahlender-xnu-installer --cli export-save [--out FOLDER] [--save FOLDER]`
pub fn cli(args: &[String]) -> i32 {
    let (mut out, mut save) = (None, None);
    let mut rest = args.iter();
    while let Some(flag) = rest.next() {
        let slot = match flag.as_str() {
            "--out" => &mut out,
            "--save" => &mut save,
            _ => {
                eprintln!("Usage: --cli export-save [--out FOLDER] [--save FOLDER]");
                return 2;
            }
        };
        match rest.next() {
            Some(value) => *slot = Some(PathBuf::from(value)),
            None => {
                eprintln!("{flag} needs a folder.");
                return 2;
            }
        }
    }
    match export(save.as_deref(), out.as_deref()) {
        Ok(done) => {
            println!(
                "Wrote {} ({} files, {} bytes).\n{PRIVACY_NOTE}",
                done.path.display(),
                done.files,
                done.bytes
            );
            0
        }
        Err(error) => {
            eprintln!("{error}");
            1
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Read;

    fn scratch(name: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!("save-export-{name}-{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        dir
    }

    fn put(path: &Path, bytes: &[u8]) {
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::write(path, bytes).unwrap();
    }

    fn names(zip_path: &Path) -> Vec<String> {
        let mut archive = zip::ZipArchive::new(File::open(zip_path).unwrap()).unwrap();
        let mut names: Vec<String> = (0..archive.len())
            .map(|index| archive.by_index(index).unwrap().name().to_owned())
            .collect();
        names.sort();
        names
    }

    #[test]
    fn only_save_folders_are_packed_with_relative_paths() {
        let base = scratch("paths");
        let root = base.join("save");
        put(&root.join("save_1/SaveData.bin"), b"main");
        put(&root.join("save_1/Backup.bin"), b"backup");
        put(&root.join("mods/Cool Mod/save_1/SaveData.bin"), b"mod");
        put(&root.join("mods/Cool Mod/other/notes.txt"), b"skip");
        put(&root.join("user_id.hex"), b"skip");
        put(&root.join("sdcard/prod.keys"), b"never");
        put(&root.join("save_x/SaveData.bin"), b"skip");
        put(&root.join("_snapshots/save_1/SaveData.bin"), b"skip");
        let out = base.join("out");
        let done = build_zip(&root, &out, "2026-11-04").unwrap();
        assert_eq!(done.path, out.join("bdsp-save-2026-11-04.zip"));
        assert_eq!((done.files, done.bytes), (3, 13));
        let listed = names(&done.path);
        assert_eq!(
            listed,
            [
                "mods/Cool Mod/save_1/SaveData.bin",
                "save_1/Backup.bin",
                "save_1/SaveData.bin"
            ]
        );
        let base_text = base.to_string_lossy().into_owned();
        assert!(
            listed
                .iter()
                .all(|name| !name.contains(&base_text) && !name.contains('\\'))
        );
        let mut archive = zip::ZipArchive::new(File::open(&done.path).unwrap()).unwrap();
        let mut content = String::new();
        archive
            .by_name("save_1/SaveData.bin")
            .unwrap()
            .read_to_string(&mut content)
            .unwrap();
        assert_eq!(content, "main");
        let _ = fs::remove_dir_all(base);
    }

    #[test]
    fn a_missing_or_empty_save_folder_gives_a_plain_message() {
        let base = scratch("missing");
        let missing = build_zip(&base.join("nope"), &base.join("out"), "2026-11-04")
            .err()
            .unwrap();
        assert!(missing.starts_with("No save folder was found"));
        let root = base.join("save");
        put(&root.join("user_id.hex"), b"x");
        let empty = build_zip(&root, &base.join("out"), "2026-11-04")
            .err()
            .unwrap();
        assert!(empty.contains("holds no save"));
        assert!(!base.join("out").exists());
        let _ = fs::remove_dir_all(base);
    }

    #[test]
    fn a_save_folder_over_the_cap_is_refused_and_leaves_nothing_behind() {
        let base = scratch("cap");
        let root = base.join("save");
        let file = root.join("save_1/SaveData.bin");
        fs::create_dir_all(file.parent().unwrap()).unwrap();
        let big = File::create(&file).unwrap();
        big.set_len(SIZE_CAP + 1).unwrap();
        let error = build_zip(&root, &base.join("out"), "2026-11-04")
            .err()
            .unwrap();
        assert!(error.contains("64 MiB"), "{error}");
        assert!(!base.join("out").exists());
        let _ = fs::remove_dir_all(base);
    }

    #[test]
    fn an_existing_export_is_never_overwritten() {
        let base = scratch("again");
        let root = base.join("save");
        put(&root.join("save_1/SaveData.bin"), b"a");
        let out = base.join("out");
        let first = build_zip(&root, &out, "2026-11-04").unwrap();
        let second = build_zip(&root, &out, "2026-11-04").unwrap();
        assert_eq!(first.path.file_name().unwrap(), "bdsp-save-2026-11-04.zip");
        assert_eq!(
            second.path.file_name().unwrap(),
            "bdsp-save-2026-11-04-2.zip"
        );
        assert_eq!(fs::read_dir(&out).unwrap().count(), 2);
        let _ = fs::remove_dir_all(base);
    }

    #[test]
    fn dates_are_civil_utc() {
        assert_eq!(date_of(0), "1970-01-01");
        assert_eq!(date_of(11_016), "2000-02-29");
        assert_eq!(date_of(20_453), "2025-12-31");
    }
}
