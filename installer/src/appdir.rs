//! Where the installer keeps its own data. Windows uses one short folder in Roaming AppData (MAX_PATH is tight);
//! macOS and Linux keep the `directories` project folders.
#![allow(dead_code)] // the setup helper binary shares this file and uses only part of it
use std::{
    fs, io,
    path::{Path, PathBuf},
};

/// The single Windows folder name, also checked against scripts/install/pathlimits.py by a test.
pub const WINDOWS_FOLDER: &str = "str-xnu";

/// Root of the installer data: `%APPDATA%\str-xnu` on Windows.
pub fn data_dir() -> Option<PathBuf> {
    if cfg!(windows) {
        directories::BaseDirs::new().map(|dirs| dirs.data_dir().join(WINDOWS_FOLDER))
    } else {
        project().map(|dirs| dirs.data_dir().to_path_buf())
    }
}

/// Machine-local data (the firmware cache); the same root on Windows.
pub fn data_local_dir() -> Option<PathBuf> {
    if cfg!(windows) {
        data_dir()
    } else {
        project().map(|dirs| dirs.data_local_dir().to_path_buf())
    }
}

pub fn config_dir() -> Option<PathBuf> {
    if cfg!(windows) {
        data_dir().map(|root| root.join("config"))
    } else {
        project().map(|dirs| dirs.config_dir().to_path_buf())
    }
}

pub fn logs_dir() -> Option<PathBuf> {
    data_dir().map(|root| root.join("logs"))
}

/// Settings file (in the config folder) with the folder the user chose for the build ...
pub const WORK_FOLDER: &str = "work-folder.txt";
/// ... and for the installed app. A missing file means the default.
pub const INSTALL_FOLDER: &str = "install-folder.txt";

/// The folder the user chose in the build options, or `None` for the default.
pub fn chosen_folder(setting: &str) -> Option<PathBuf> {
    chosen_folder_in(&config_dir()?, setting)
}

/// Remembers the chosen folder; `None` goes back to the default. The folder itself is never created or deleted here.
pub fn choose_folder(setting: &str, folder: Option<&Path>) -> io::Result<()> {
    let config = config_dir().ok_or_else(|| io::Error::other("no configuration folder"))?;
    choose_folder_in(&config, setting, folder)
}

fn chosen_folder_in(config: &Path, setting: &str) -> Option<PathBuf> {
    let text = fs::read_to_string(config.join(setting)).ok()?;
    let folder = PathBuf::from(text.trim());
    folder.is_absolute().then_some(folder)
}

fn choose_folder_in(config: &Path, setting: &str, folder: Option<&Path>) -> io::Result<()> {
    let file = config.join(setting);
    let Some(folder) = folder else {
        return match fs::remove_file(&file) {
            Err(error) if error.kind() != io::ErrorKind::NotFound => Err(error),
            _ => Ok(()),
        };
    };
    let text = folder
        .to_str()
        .filter(|_| folder.is_absolute())
        .ok_or_else(|| io::Error::other("the folder must be a complete path"))?;
    fs::create_dir_all(config)?;
    fs::write(file, text)
}

fn project() -> Option<directories::ProjectDirs> {
    directories::ProjectDirs::from("dev", "Veemyu", "strahlender-xnu-installer")
}

/// The 0.1.4 configuration folder on Windows.
#[cfg(windows)]
fn legacy_config_dir() -> Option<PathBuf> {
    project().map(|dirs| dirs.config_dir().to_path_buf())
}

/// Copies the 0.1.4 preferences once; the old folder is never changed or deleted.
pub fn migrate_legacy_config() {
    #[cfg(windows)]
    if let (Some(old), Some(new)) = (legacy_config_dir(), config_dir()) {
        let _ = copy_config_once(&old, &new);
    }
}

/// When `new` does not exist and `old` does, copies the files of `old` into `new` and verifies the sizes.
/// The copy is built beside `new` and renamed, so `new` never appears half written. `old` is left untouched.
pub fn copy_config_once(old: &Path, new: &Path) -> io::Result<bool> {
    if new.exists() || !old.is_dir() {
        return Ok(false);
    }
    let parent = new
        .parent()
        .ok_or_else(|| io::Error::other("config folder has no parent"))?;
    fs::create_dir_all(parent)?;
    let staging = parent.join("config.migrating");
    if staging.exists() {
        fs::remove_dir_all(&staging)?;
    }
    fs::create_dir(&staging)?;
    for entry in fs::read_dir(old)? {
        let entry = entry?;
        if !entry.file_type()?.is_file() {
            continue;
        }
        let target = staging.join(entry.file_name());
        fs::copy(entry.path(), &target)?;
        if fs::metadata(entry.path())?.len() != fs::metadata(&target)?.len() {
            fs::remove_dir_all(&staging)?;
            return Err(io::Error::other("copied configuration does not match"));
        }
    }
    fs::rename(&staging, new)?;
    Ok(true)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn scratch(name: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!("appdir-{name}-{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        dir
    }

    #[test]
    fn old_preferences_are_copied_once_and_the_old_folder_is_kept() {
        let root = scratch("copy");
        let old = root.join("old");
        let new = root.join("new/config");
        fs::create_dir_all(&old).unwrap();
        fs::write(old.join("preferences.json"), b"{\"language\":\"de\"}").unwrap();
        assert!(copy_config_once(&old, &new).unwrap());
        assert_eq!(
            fs::read(new.join("preferences.json")).unwrap(),
            b"{\"language\":\"de\"}"
        );
        assert!(old.join("preferences.json").exists());
        assert!(!root.join("new/config.migrating").exists());
        fs::write(new.join("preferences.json"), b"changed").unwrap();
        assert!(!copy_config_once(&old, &new).unwrap());
        assert_eq!(fs::read(new.join("preferences.json")).unwrap(), b"changed");
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn nothing_happens_without_an_old_folder_or_when_the_new_one_exists() {
        let root = scratch("skip");
        let new = root.join("config");
        assert!(!copy_config_once(&root.join("missing"), &new).unwrap());
        assert!(!new.exists());
        let old = root.join("old");
        fs::create_dir_all(&old).unwrap();
        fs::write(old.join("preferences.json"), b"x").unwrap();
        fs::create_dir_all(&new).unwrap();
        assert!(!copy_config_once(&old, &new).unwrap());
        assert!(fs::read_dir(&new).unwrap().next().is_none());
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn a_chosen_folder_is_remembered_and_can_be_reset() {
        let config = scratch("chosen").join("config");
        assert_eq!(chosen_folder_in(&config, WORK_FOLDER), None);
        let folder = scratch("chosen-target");
        choose_folder_in(&config, WORK_FOLDER, Some(&folder)).unwrap();
        assert_eq!(chosen_folder_in(&config, WORK_FOLDER), Some(folder.clone()));
        assert_eq!(chosen_folder_in(&config, INSTALL_FOLDER), None);
        choose_folder_in(&config, WORK_FOLDER, None).unwrap();
        choose_folder_in(&config, WORK_FOLDER, None).unwrap();
        assert_eq!(chosen_folder_in(&config, WORK_FOLDER), None);
        assert!(folder.is_dir());
        assert!(choose_folder_in(&config, WORK_FOLDER, Some(Path::new("short"))).is_err());
        fs::write(config.join(WORK_FOLDER), "relative\\folder\n").unwrap();
        assert_eq!(chosen_folder_in(&config, WORK_FOLDER), None);
        let _ = fs::remove_dir_all(folder);
    }

    #[cfg(windows)]
    #[test]
    fn windows_data_lives_in_one_short_roaming_folder() {
        let root = data_dir().unwrap();
        assert_eq!(root.file_name().unwrap(), WINDOWS_FOLDER);
        assert_eq!(config_dir().unwrap(), root.join("config"));
        assert_eq!(logs_dir().unwrap(), root.join("logs"));
    }
}
