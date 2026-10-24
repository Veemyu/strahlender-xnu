//! Bounded discovery using a registry that the shared CLI can also consume.
//! Only metadata/readability is checked here; decryption validation is backend work.
use crate::{
    i18n::Language,
    sources::{self, Slot, Source},
};
use serde::Deserialize;
use std::{
    collections::HashSet,
    path::{Path, PathBuf},
};

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Registry {
    schema: u32,
    profiles: Vec<Profile>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Profile {
    id: String,
    name: String,
    windows: Vec<Location>,
    macos: Vec<Location>,
    linux: Vec<Location>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Location {
    base: Base,
    path: PathBuf,
}

#[derive(Deserialize)]
#[serde(rename_all = "lowercase")]
enum Base {
    Home,
    Roaming,
    Config,
    Data,
}

struct Candidate {
    emulator: String,
    path: PathBuf,
}

fn registry() -> Registry {
    let registry: Registry = serde_json::from_str(include_str!("../assets/emulator-paths.json"))
        .expect("embedded emulator path registry must be valid");
    assert_eq!(registry.schema, 1, "unsupported emulator registry schema");
    registry
}

fn candidates(
    os: &str,
    home: &Path,
    roaming: Option<&Path>,
    config: Option<&Path>,
    data: Option<&Path>,
) -> Vec<Candidate> {
    let config = config
        .map(Path::to_path_buf)
        .unwrap_or_else(|| home.join(".config"));
    let data = data
        .map(Path::to_path_buf)
        .unwrap_or_else(|| home.join(".local/share"));
    let mut seen = HashSet::new();
    let mut paths = Vec::new();
    for profile in registry().profiles {
        debug_assert!(!profile.id.is_empty());
        let locations = match os {
            "windows" => profile.windows,
            "macos" => profile.macos,
            "linux" => profile.linux,
            _ => Vec::new(),
        };
        for location in locations {
            let base = match location.base {
                Base::Home => Some(home),
                Base::Roaming => roaming,
                Base::Config => Some(config.as_path()),
                Base::Data => Some(data.as_path()),
            };
            if let Some(base) = base {
                let path = base.join(location.path).join("prod.keys");
                if seen.insert(path.clone()) {
                    paths.push(Candidate {
                        emulator: profile.name.clone(),
                        path,
                    });
                }
            }
        }
    }
    paths
}

pub fn find(language: Language) -> Option<Source> {
    let home = directories::UserDirs::new()?.home_dir().to_path_buf();
    let roaming = std::env::var_os("APPDATA")
        .map(PathBuf::from)
        .filter(|p| p.is_absolute() && p.is_dir())
        .or_else(|| {
            if cfg!(target_os = "windows") {
                directories::BaseDirs::new().map(|dirs| dirs.config_dir().to_path_buf())
            } else {
                Some(home.join("AppData/Roaming"))
            }
        });
    let config = std::env::var_os("XDG_CONFIG_HOME")
        .map(PathBuf::from)
        .filter(|p| p.is_absolute());
    let data = std::env::var_os("XDG_DATA_HOME")
        .map(PathBuf::from)
        .filter(|p| p.is_absolute());
    let paths = candidates(
        std::env::consts::OS,
        &home,
        roaming.as_deref(),
        config.as_deref(),
        data.as_deref(),
    );
    find_candidate(paths, language)
}

fn find_candidate(paths: Vec<Candidate>, language: Language) -> Option<Source> {
    paths.into_iter().find_map(|candidate| {
        sources::inspect(candidate.path, Slot::Keys, language)
            .ok()
            .map(|mut source| {
                source.description = candidate.emulator;
                source
            })
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn lookup_skips_missing_and_empty_files_and_never_changes_a_found_file() {
        let root = std::env::temp_dir().join(format!(
            "strahlender-lookup-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        std::fs::create_dir(&root).unwrap();
        let empty = root.join("empty.keys");
        let valid = root.join("prod.keys");
        std::fs::write(&empty, b"").unwrap();
        std::fs::write(&valid, b"synthetic test fixture, no key material").unwrap();
        let candidate = |name: &str, path| Candidate {
            emulator: name.into(),
            path,
        };
        let found = find_candidate(
            vec![
                candidate("missing", root.join("missing.keys")),
                candidate("empty", empty),
                candidate("Eden", valid.clone()),
            ],
            Language::English,
        )
        .unwrap();
        assert_eq!(found.path, valid);
        assert_eq!(found.description, "Eden");
        assert_eq!(
            std::fs::read(&valid).unwrap(),
            b"synthetic test fixture, no key material"
        );
        assert!(find_candidate(Vec::new(), Language::English).is_none());
        std::fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn every_researched_emulator_has_windows_macos_and_linux_paths() {
        let registry = registry();
        let mut ids = HashSet::new();
        for profile in registry.profiles {
            assert!(ids.insert(profile.id.clone()), "duplicate profile");
            if profile.id != "legacy" && !profile.id.ends_with("-flatpak") {
                assert!(
                    !profile.windows.is_empty()
                        && !profile.macos.is_empty()
                        && !profile.linux.is_empty(),
                    "{} misses a desktop platform",
                    profile.id
                );
            }
            for location in profile
                .windows
                .iter()
                .chain(&profile.macos)
                .chain(&profile.linux)
            {
                assert!(!location.path.is_absolute());
                assert!(
                    !location
                        .path
                        .components()
                        .any(|part| matches!(part, std::path::Component::ParentDir))
                );
            }
        }
        for id in [
            "ryujinx-ryubing",
            "yuzu",
            "suyu",
            "sudachi",
            "eden",
            "citron",
        ] {
            assert!(ids.contains(id));
        }
    }

    #[test]
    fn resolves_the_correct_platform_roots_and_respects_xdg() {
        let home = Path::new("/synthetic/home");
        for os in ["windows", "macos", "linux"] {
            let paths = candidates(
                os,
                home,
                Some(Path::new("/roaming")),
                Some(Path::new("/custom-config")),
                Some(Path::new("/custom-data")),
            );
            let has = |path: &str| {
                paths
                    .iter()
                    .any(|candidate| candidate.path == Path::new(path))
            };
            match os {
                "windows" => {
                    assert!(has("/roaming/Ryujinx/system/prod.keys"));
                    for name in ["yuzu", "suyu", "sudachi", "eden", "citron"] {
                        assert!(has(&format!("/roaming/{name}/keys/prod.keys")));
                    }
                }
                "macos" => assert!(has(
                    "/synthetic/home/Library/Application Support/Ryujinx/system/prod.keys"
                )),
                _ => {
                    assert!(has("/custom-config/Ryujinx/system/prod.keys"));
                    assert!(has(
                        "/synthetic/home/.var/app/org.yuzu_emu.yuzu/data/yuzu/keys/prod.keys"
                    ));
                    assert!(has(
                        "/synthetic/home/.var/app/org.ryujinx.Ryujinx/config/Ryujinx/system/prod.keys"
                    ));
                }
            }
            if os != "windows" {
                for name in ["yuzu", "suyu", "sudachi", "eden", "citron"] {
                    assert!(has(&format!("/custom-data/{name}/keys/prod.keys")));
                }
                assert!(!has("/custom-config/sudachi/keys/prod.keys"));
            }
            assert!(paths.len() < 20);
        }
    }
}
