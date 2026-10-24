//! Read-only mod discovery and the local folder used by the desktop installer.
use crate::{app::InstallTarget, platform::Platform};
use std::{
    fs,
    path::{Path, PathBuf},
    process::{Command, Stdio},
};

pub const MAX_MODS: usize = 32;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ModEntry {
    pub name: String,
    pub root: PathBuf,
    pub has_romfs: bool,
    pub has_exefs: bool,
}

impl ModEntry {
    pub fn ips_buildable(&self) -> bool {
        if !self.has_exefs {
            return false;
        }
        let Ok(children) = fs::read_dir(&self.root) else {
            return false;
        };
        let Some(exefs) = children.filter_map(Result::ok).find(|entry| {
            entry
                .file_name()
                .to_string_lossy()
                .eq_ignore_ascii_case("exefs")
                && entry.file_type().is_ok_and(|kind| kind.is_dir())
        }) else {
            return false;
        };
        let Ok(files) = fs::read_dir(exefs.path()) else {
            return false;
        };
        let mut found = false;
        for file in files.filter_map(Result::ok) {
            let name = file.file_name().to_string_lossy().to_ascii_lowercase();
            if matches!(name.as_str(), "license" | "notice" | ".ds_store") {
                continue;
            }
            if !file.file_type().is_ok_and(|kind| kind.is_file())
                || (name != "subsdk1"
                    && !matches!(
                        file.path().extension().and_then(|ext| ext.to_str()),
                        Some(ext) if ext.eq_ignore_ascii_case("ips") || ext.eq_ignore_ascii_case("ips32")
                    ))
            {
                return false;
            }
            found = true;
        }
        found
    }
}

pub fn folder_for(host: Platform, target: InstallTarget) -> Option<PathBuf> {
    if let Some(override_path) = std::env::var_os("BDSP_MODS_DIR")
        && !override_path.is_empty()
    {
        return Some(PathBuf::from(override_path));
    }
    if host == Platform::Mac && target == InstallTarget::Mac {
        return directories::BaseDirs::new().map(|dirs| {
            dirs.home_dir()
                .join("Library/Application Support/dev.local.xnubdsp/mods")
        });
    }
    directories::ProjectDirs::from("dev", "Veemyu", "strahlender-xnu-installer")
        .map(|dirs| dirs.data_dir().join("mods"))
}

pub fn open_folder(path: &Path) -> Result<(), String> {
    fs::create_dir_all(path).map_err(|error| format!("Could not create mods folder: {error}"))?;
    #[cfg(target_os = "macos")]
    let program = "open";
    #[cfg(target_os = "linux")]
    let program = "xdg-open";
    #[cfg(target_os = "windows")]
    let program = "explorer.exe";
    #[cfg(not(any(target_os = "macos", target_os = "linux", target_os = "windows")))]
    return Err("Opening folders is not supported on this host.".into());
    #[cfg(any(target_os = "macos", target_os = "linux", target_os = "windows"))]
    Command::new(program)
        .arg(path)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .map(|_| ())
        .map_err(|error| format!("Could not open mods folder: {error}"))
}

pub fn scan(path: &Path) -> Result<Vec<ModEntry>, String> {
    if !path.exists() {
        return Ok(Vec::new());
    }
    if !path.is_dir() {
        return Err("The mods location is not a folder.".into());
    }
    fs::read_dir(path).map_err(|error| format!("Cannot read mods folder: {error}"))?;
    #[cfg(unix)]
    {
        scan_native(path)
    }
    #[cfg(not(unix))]
    {
        scan_portable(path)
    }
}

/// Scan a folder chosen by the user, including a wrapper around the actual mod.
/// The runtime scans children of BDSP_MODS_DIR, so use the chosen folder's parent
/// and retain only entries inside the chosen tree.
pub fn scan_selected(path: &Path) -> Result<Vec<ModEntry>, String> {
    let selected = path
        .canonicalize()
        .map_err(|error| format!("Cannot open selected mod folder: {error}"))?;
    if !selected.is_dir() {
        return Err("The selected mod path is not a folder.".into());
    }
    let library = library_for_selection(&selected)?;
    let entries = scan(&library)?
        .into_iter()
        .filter(|entry| entry.root.starts_with(&selected))
        .collect::<Vec<_>>();
    if entries.is_empty() {
        return Err("No romfs or exefs folder was found inside the selected mod folder.".into());
    }
    Ok(entries)
}

pub fn library_for_selection(path: &Path) -> Result<PathBuf, String> {
    let selected = path
        .canonicalize()
        .map_err(|error| format!("Cannot open selected mod folder: {error}"))?;
    let direct = fs::read_dir(&selected)
        .map_err(|error| format!("Cannot read selected mod folder: {error}"))?
        .filter_map(Result::ok)
        .any(|entry| {
            matches!(
                entry
                    .file_name()
                    .to_string_lossy()
                    .to_ascii_lowercase()
                    .as_str(),
                "romfs" | "exefs"
            ) && entry.file_type().is_ok_and(|kind| kind.is_dir())
        });
    if direct {
        selected
            .parent()
            .map(Path::to_path_buf)
            .ok_or("The selected mod folder has no parent".into())
    } else {
        Ok(selected)
    }
}

fn has_exefs_payload(root: &Path) -> bool {
    let Ok(children) = fs::read_dir(root) else {
        return false;
    };
    let Some(exefs) = children.filter_map(Result::ok).find(|entry| {
        entry
            .file_name()
            .to_string_lossy()
            .eq_ignore_ascii_case("exefs")
            && entry.file_type().is_ok_and(|kind| kind.is_dir())
    }) else {
        return false;
    };
    fs::read_dir(exefs.path()).is_ok_and(|entries| {
        entries.filter_map(Result::ok).any(|entry| {
            !matches!(
                entry
                    .file_name()
                    .to_string_lossy()
                    .to_ascii_lowercase()
                    .as_str(),
                "license" | "notice" | ".ds_store"
            )
        })
    })
}

#[cfg(unix)]
#[repr(C)]
struct RawModInfo {
    name: [std::ffi::c_char; 256],
    root: [std::ffi::c_char; 1100],
    romfs: [std::ffi::c_char; 1200],
    exefs: [std::ffi::c_char; 1200],
}

#[cfg(unix)]
impl Default for RawModInfo {
    fn default() -> Self {
        Self {
            name: [0; 256],
            root: [0; 1100],
            romfs: [0; 1200],
            exefs: [0; 1200],
        }
    }
}

#[cfg(unix)]
unsafe extern "C" {
    fn mods_scan(
        mods_dir: *const std::ffi::c_char,
        out: *mut RawModInfo,
        max: std::ffi::c_int,
    ) -> std::ffi::c_int;
}

#[cfg(unix)]
fn scan_native(path: &Path) -> Result<Vec<ModEntry>, String> {
    use std::{
        ffi::{CStr, CString},
        os::unix::ffi::OsStrExt,
    };
    let root = CString::new(path.as_os_str().as_bytes())
        .map_err(|_| "The mods folder path contains an invalid null byte.".to_owned())?;
    let mut raw: Vec<RawModInfo> = (0..MAX_MODS).map(|_| RawModInfo::default()).collect();
    // SAFETY: mods_scan writes at most max entries; the C strings are null-terminated in fixed arrays.
    let count = unsafe { mods_scan(root.as_ptr(), raw.as_mut_ptr(), MAX_MODS as std::ffi::c_int) };
    if count < 0 || count as usize > MAX_MODS {
        return Err("The mod scanner returned an invalid count.".into());
    }
    Ok(raw
        .iter()
        .take(count as usize)
        .map(|item| {
            let string = |bytes: &[std::ffi::c_char]| {
                // SAFETY: mods_scan clears each entry and writes strings with snprintf.
                unsafe { CStr::from_ptr(bytes.as_ptr()) }
                    .to_string_lossy()
                    .into_owned()
            };
            ModEntry {
                name: string(&item.name),
                root: PathBuf::from(string(&item.root)),
                has_romfs: item.romfs[0] != 0,
                has_exefs: item.exefs[0] != 0 && has_exefs_payload(Path::new(&string(&item.root))),
            }
        })
        .collect())
}

#[cfg(any(not(unix), test))]
fn scan_portable(path: &Path) -> Result<Vec<ModEntry>, String> {
    fn visit(
        path: &Path,
        name: &str,
        depth: usize,
        entries: &mut Vec<ModEntry>,
    ) -> Result<(), String> {
        if entries.len() >= MAX_MODS {
            return Ok(());
        }
        let children =
            fs::read_dir(path).map_err(|error| format!("Cannot read mods folder: {error}"))?;
        let mut folders = children
            .filter_map(Result::ok)
            .filter(|item| item.file_type().is_ok_and(|kind| kind.is_dir()))
            .filter(|item| !item.file_name().to_string_lossy().starts_with('.'))
            .map(|item| item.path())
            .collect::<Vec<_>>();
        folders.sort();
        let romfs = folders.iter().any(|item| {
            item.file_name()
                .is_some_and(|name| name.to_string_lossy().eq_ignore_ascii_case("romfs"))
        });
        let exefs = folders.iter().any(|item| {
            item.file_name()
                .is_some_and(|name| name.to_string_lossy().eq_ignore_ascii_case("exefs"))
        });
        if romfs || exefs {
            let mut unique = name.to_owned();
            for index in 2.. {
                if !entries
                    .iter()
                    .any(|item| item.name.eq_ignore_ascii_case(&unique))
                {
                    break;
                }
                unique = format!("{name} ({index})");
            }
            entries.push(ModEntry {
                name: unique,
                root: path.to_path_buf(),
                has_romfs: romfs,
                has_exefs: exefs && has_exefs_payload(path),
            });
        } else if depth > 0 {
            for folder in folders {
                let child_name = folder
                    .file_name()
                    .unwrap_or_default()
                    .to_string_lossy()
                    .into_owned();
                visit(&folder, &child_name, depth - 1, entries)?;
            }
        }
        Ok(())
    }
    let mut entries = Vec::new();
    let mut folders = fs::read_dir(path)
        .map_err(|error| format!("Cannot read mods folder: {error}"))?
        .filter_map(Result::ok)
        .filter(|item| item.file_type().is_ok_and(|kind| kind.is_dir()))
        .map(|item| item.path())
        .collect::<Vec<_>>();
    folders.sort();
    for folder in folders {
        let name = folder
            .file_name()
            .unwrap_or_default()
            .to_string_lossy()
            .into_owned();
        if !name.starts_with('.') {
            visit(&folder, &name, 3, &mut entries)?;
        }
    }
    Ok(entries)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn scanner_uses_runtime_mod_names_without_touching_saves() {
        let root = std::env::temp_dir().join(format!("installer-mods-{}", std::process::id()));
        let _ = fs::remove_dir_all(&root);
        fs::create_dir_all(root.join("Luminescent/wrapper/ROMFS")).unwrap();
        fs::create_dir_all(root.join("Luminescent/wrapper/ExeFS")).unwrap();
        fs::write(root.join("Luminescent/wrapper/ExeFS/code.ips"), b"PATCH\n").unwrap();
        fs::create_dir_all(root.join("Simple/romfs")).unwrap();
        let entries = scan(&root).unwrap();
        assert_eq!(entries.len(), 2);
        assert_eq!(entries[0].name, "wrapper");
        assert!(entries[0].has_romfs && entries[0].has_exefs);
        assert!(entries[0].ips_buildable());
        assert_eq!(entries[1].name, "Simple");
        assert_eq!(entries, scan_portable(&root).unwrap());
        let selected = scan_selected(&root.join("Luminescent")).unwrap();
        assert_eq!(selected.len(), 1);
        assert_eq!(selected[0].name, entries[0].name);
        assert_eq!(
            selected[0].root.canonicalize().unwrap(),
            entries[0].root.canonicalize().unwrap()
        );
        assert!(!root.join("Saves").exists());
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn empty_exefs_does_not_require_code_build() {
        let root = std::env::temp_dir().join(format!("installer-mod-empty-{}", std::process::id()));
        let _ = fs::remove_dir_all(&root);
        fs::create_dir_all(root.join("Mod/romfs")).unwrap();
        fs::create_dir_all(root.join("Mod/exefs")).unwrap();
        let entries = scan_selected(&root.join("Mod")).unwrap();
        assert!(entries[0].has_romfs);
        assert!(!entries[0].has_exefs);
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn subsdk1_is_discovered_as_a_code_build() {
        let root = std::env::temp_dir().join(format!("installer-mod-sub-{}", std::process::id()));
        let _ = fs::remove_dir_all(&root);
        fs::create_dir_all(root.join("Code/ExeFS")).unwrap();
        fs::write(root.join("Code/ExeFS/subsdk1"), b"NSO0").unwrap();
        let entries = scan_selected(&root.join("Code")).unwrap();
        assert!(entries[0].has_exefs);
        assert!(entries[0].ips_buildable());
        fs::write(root.join("Code/ExeFS/subsdk2"), b"NSO0").unwrap();
        assert!(!entries[0].ips_buildable());
        fs::remove_dir_all(root).unwrap();
    }
}
