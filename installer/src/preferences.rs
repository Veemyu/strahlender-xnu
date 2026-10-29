use directories::ProjectDirs;
use serde::{Deserialize, Serialize};
use std::{
    fs, io,
    path::{Path, PathBuf},
};

#[derive(Debug, Default, Clone)]
pub struct SavedPaths {
    pub keys: Option<PathBuf>,
    pub base: Option<PathBuf>,
    pub update: Option<PathBuf>,
    pub mod_folder: Option<PathBuf>,
    pub firmware: Option<PathBuf>,
    pub last_directory: Option<PathBuf>,
}

#[derive(Debug, Default, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Appearance {
    #[default]
    Dark,
    Light,
}

#[derive(Default, Serialize, Deserialize)]
struct Preferences {
    #[serde(default)]
    ios_signing_team: Option<String>,
    #[serde(default)]
    appearance: Appearance,
    #[serde(default, with = "stored_path")]
    keys_path: Option<PathBuf>,
    #[serde(default, with = "stored_path")]
    base_path: Option<PathBuf>,
    #[serde(default, with = "stored_path")]
    update_path: Option<PathBuf>,
    #[serde(default, with = "stored_path")]
    mod_folder: Option<PathBuf>,
    #[serde(default, with = "stored_path")]
    firmware_path: Option<PathBuf>,
    #[serde(default, with = "stored_path")]
    last_directory: Option<PathBuf>,
}

mod stored_path {
    use serde::{Deserialize, Deserializer, Serialize, Serializer};
    use std::path::PathBuf;

    pub fn serialize<S>(value: &Option<PathBuf>, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        let encoded = value.as_ref().map(|path| {
            directories::UserDirs::new()
                .and_then(|dirs| {
                    path.strip_prefix(dirs.home_dir()).ok().map(|tail| {
                        if tail.as_os_str().is_empty() {
                            "~".to_owned()
                        } else {
                            format!("~/{}", tail.to_string_lossy().replace('\\', "/"))
                        }
                    })
                })
                .unwrap_or_else(|| path.to_string_lossy().into_owned())
        });
        encoded.serialize(serializer)
    }

    pub fn deserialize<'de, D>(deserializer: D) -> Result<Option<PathBuf>, D::Error>
    where
        D: Deserializer<'de>,
    {
        let encoded = Option::<String>::deserialize(deserializer)?;
        Ok(encoded.map(|value| {
            if value == "~" {
                directories::UserDirs::new()
                    .map(|dirs| dirs.home_dir().to_path_buf())
                    .unwrap_or_else(|| PathBuf::from(value))
            } else if let Some(relative) = value.strip_prefix("~/") {
                directories::UserDirs::new()
                    .map(|dirs| dirs.home_dir().join(relative))
                    .unwrap_or_else(|| PathBuf::from(value))
            } else {
                PathBuf::from(value)
            }
        }))
    }
}

fn path() -> Option<PathBuf> {
    ProjectDirs::from("dev", "Veemyu", "strahlender-xnu-installer")
        .map(|dirs| dirs.config_dir().join("preferences.json"))
}

pub fn load() -> Appearance {
    load_preferences().appearance
}

pub fn save(appearance: Appearance) -> io::Result<()> {
    let mut preferences = load_preferences();
    preferences.appearance = appearance;
    write(preferences)
}

pub fn load_signing_team() -> Option<String> {
    load_preferences()
        .ios_signing_team
        .filter(|id| crate::ios_signing::valid_id(id))
}
pub fn save_signing_team(id: &str) -> io::Result<()> {
    if !crate::ios_signing::valid_id(id) {
        return Err(io::Error::other("Invalid Apple team ID"));
    }
    let mut preferences = load_preferences();
    preferences.ios_signing_team = Some(id.into());
    write(preferences)
}

pub fn load_paths() -> SavedPaths {
    let preferences = load_preferences();
    SavedPaths {
        keys: preferences.keys_path,
        base: preferences.base_path,
        update: preferences.update_path,
        mod_folder: preferences.mod_folder,
        firmware: preferences.firmware_path,
        last_directory: preferences.last_directory,
    }
}

pub fn save_source_path(slot: crate::sources::Slot, value: Option<&Path>) -> io::Result<()> {
    let mut preferences = load_preferences();
    let path = value.map(Path::to_path_buf);
    match slot {
        crate::sources::Slot::Keys => preferences.keys_path = path.clone(),
        crate::sources::Slot::Base => preferences.base_path = path.clone(),
        crate::sources::Slot::Update => preferences.update_path = path.clone(),
    }
    if let Some(path) = path {
        preferences.last_directory = Some(if path.is_dir() {
            path
        } else {
            path.parent()
                .unwrap_or_else(|| Path::new("."))
                .to_path_buf()
        });
    }
    write(preferences)
}

pub fn save_mod_folder(path: &Path) -> io::Result<()> {
    let mut preferences = load_preferences();
    preferences.mod_folder = Some(path.to_path_buf());
    preferences.last_directory = Some(path.to_path_buf());
    write(preferences)
}

fn load_preferences() -> Preferences {
    path()
        .and_then(|path| fs::read(path).ok())
        .and_then(|bytes| serde_json::from_slice::<Preferences>(&bytes).ok())
        .unwrap_or_default()
}

fn write(preferences: Preferences) -> io::Result<()> {
    let path = path().ok_or_else(|| io::Error::other("Configuration directory is unavailable"))?;
    let parent = path.parent().expect("preferences has parent");
    fs::create_dir_all(parent)?;
    let temporary = parent.join("preferences.json.tmp");
    fs::write(&temporary, serde_json::to_vec_pretty(&preferences)?)?;
    #[cfg(windows)]
    if path.exists() {
        fs::remove_file(&path)?;
    }
    fs::rename(temporary, path)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn saved_home_paths_are_tilde_relative() {
        let Some(home) = directories::UserDirs::new() else {
            return;
        };
        let preferences = Preferences {
            keys_path: Some(home.home_dir().join("Ryujinx/system/prod.keys")),
            last_directory: Some(home.home_dir().join("Ryujinx/system")),
            ..Preferences::default()
        };
        let json = serde_json::to_string(&preferences).unwrap();
        assert!(json.contains("~/Ryujinx/system/prod.keys"));
        assert!(!json.contains(&home.home_dir().to_string_lossy().to_string()));
        let restored: Preferences = serde_json::from_str(&json).unwrap();
        assert_eq!(restored.keys_path, preferences.keys_path);
        assert_eq!(restored.last_directory, preferences.last_directory);
    }
}

pub fn save_firmware(path: Option<&Path>) -> io::Result<()> {
    let mut preferences = load_preferences();
    preferences.firmware_path = path.map(Path::to_path_buf);
    if let Some(path) = path {
        preferences.last_directory = path.parent().map(Path::to_path_buf);
    }
    write(preferences)
}
