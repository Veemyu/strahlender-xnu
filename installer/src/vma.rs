//! The pinned Vulkan Memory Allocator header for Linux systems that have no package for it (Arch, SteamOS).
//! The version, commit and SHA-256 of every file live in `assets/vma.json`; a download that does not match is never used.
//! The copy sits in the installer's data folder and is searched only after the system's own headers (`-idirafter`).
use serde::Deserialize;
use sha2::{Digest, Sha256};
use std::{
    collections::BTreeMap,
    fs,
    io::Read,
    path::{Path, PathBuf},
};

/// Written last: a folder without it is not complete (the build scripts check this name too).
pub const VERIFIED: &str = ".verified";

#[derive(Debug, Deserialize)]
pub struct Pin {
    pub sha256: String,
    pub bytes: u64,
}

#[derive(Debug, Deserialize)]
pub struct Lock {
    pub version: String,
    pub commit: String,
    url: String,
    pub files: BTreeMap<String, Pin>,
}

pub fn lock() -> Lock {
    serde_json::from_str(include_str!("../assets/vma.json")).expect("assets/vma.json is valid")
}

/// `<data>/vma/<version>`: holds `include/vk_mem_alloc.h`, `LICENSE.txt` and the `.verified` marker.
pub fn folder(data: &Path, lock: &Lock) -> PathBuf {
    data.join("vma").join(&lock.version)
}

fn matches(bytes: &[u8], pin: &Pin) -> bool {
    bytes.len() as u64 == pin.bytes
        && format!("{:x}", Sha256::digest(bytes)) == pin.sha256.to_ascii_lowercase()
}

/// True when the folder holds every pinned file unchanged and the marker.
pub fn verified(folder: &Path, lock: &Lock) -> bool {
    folder.join(VERIFIED).is_file()
        && lock
            .files
            .iter()
            .all(|(name, pin)| fs::read(folder.join(name)).is_ok_and(|bytes| matches(&bytes, pin)))
}

/// The folder to hand to the build (`BDSP_VMA_DIR`) when a verified copy exists.
pub fn cached() -> Option<PathBuf> {
    let lock = lock();
    let folder = folder(&crate::source_download::data_dir().ok()?, &lock);
    verified(&folder, &lock).then_some(folder)
}

/// Downloads and verifies the pinned files into the data folder; returns the folder. Safe to repeat.
pub fn fetch() -> Result<PathBuf, String> {
    let client = crate::source_download::client()?;
    fetch_with(
        &crate::source_download::data_dir()?,
        &lock(),
        &mut |url, limit| {
            let response = client
                .get(url)
                .send()
                .and_then(|r| r.error_for_status())
                .map_err(|e| format!("Download failed: {e}"))?;
            let mut bytes = Vec::new();
            response
                .take(limit + 1)
                .read_to_end(&mut bytes)
                .map_err(|e| format!("Download failed: {e}"))?;
            Ok(bytes)
        },
    )
}

/// `get(url, limit)` returns at most `limit + 1` bytes; tests pass a fake.
type Get<'a> = &'a mut dyn FnMut(&str, u64) -> Result<Vec<u8>, String>;

fn fetch_with(data: &Path, lock: &Lock, get: Get) -> Result<PathBuf, String> {
    let target = folder(data, lock);
    if verified(&target, lock) {
        return Ok(target);
    }
    let parent = target.parent().ok_or("Application data unavailable.")?;
    fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    let partial = parent.join(format!("{}.partial-{}", lock.version, std::process::id()));
    let _ = fs::remove_dir_all(&partial);
    let result = (|| {
        for (name, pin) in &lock.files {
            let url = lock
                .url
                .replace("{commit}", &lock.commit)
                .replace("{file}", name);
            let bytes = get(&url, pin.bytes)?;
            if !matches(&bytes, pin) {
                return Err(format!(
                    "The downloaded {name} does not match the pinned version {} (SHA-256 or size differs); it was not used.",
                    lock.version
                ));
            }
            let path = partial.join(name);
            fs::create_dir_all(path.parent().ok_or("Invalid file name.")?)
                .map_err(|e| e.to_string())?;
            fs::write(path, bytes).map_err(|e| e.to_string())?;
        }
        fs::write(partial.join(VERIFIED), b"").map_err(|e| e.to_string())?;
        let _ = fs::remove_dir_all(&target);
        fs::rename(&partial, &target).map_err(|e| e.to_string())
    })();
    let _ = fs::remove_dir_all(&partial);
    result.map(|()| target)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn fake_lock() -> Lock {
        let digest = |bytes: &[u8]| format!("{:x}", Sha256::digest(bytes));
        Lock {
            version: "9.9.9".into(),
            commit: "c".repeat(40),
            url: "https://example.test/{commit}/{file}".into(),
            files: BTreeMap::from([
                (
                    "include/vk_mem_alloc.h".to_string(),
                    Pin {
                        sha256: digest(b"header"),
                        bytes: 6,
                    },
                ),
                (
                    "LICENSE.txt".to_string(),
                    Pin {
                        sha256: digest(b"mit"),
                        bytes: 3,
                    },
                ),
            ]),
        }
    }

    fn scratch(name: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!("bdsp-vma-{name}-{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        dir
    }

    #[test]
    fn the_shipped_lock_pins_a_commit_and_hashes() {
        let lock = lock();
        assert_eq!(lock.commit.len(), 40);
        assert!(lock.url.starts_with("https://") && lock.url.contains("{commit}"));
        for (name, pin) in &lock.files {
            assert_eq!(pin.sha256.len(), 64, "{name}");
            assert!(pin.sha256.bytes().all(|b| b.is_ascii_hexdigit()), "{name}");
            assert!(pin.bytes > 0, "{name}");
        }
    }

    #[test]
    fn a_matching_download_is_stored_complete_and_reused_without_a_second_download() {
        let data = scratch("ok");
        let lock = fake_lock();
        let urls = std::cell::RefCell::new(Vec::new());
        let mut get = |url: &str, _: u64| {
            urls.borrow_mut().push(url.to_string());
            Ok(if url.ends_with("LICENSE.txt") {
                b"mit".to_vec()
            } else {
                b"header".to_vec()
            })
        };
        let folder = fetch_with(&data, &lock, &mut get).unwrap();
        assert!(verified(&folder, &lock));
        let prefix = format!("https://example.test/{}/", "c".repeat(40));
        assert!(urls.borrow().iter().all(|u| u.starts_with(&prefix)));
        let before = urls.borrow().len();
        assert_eq!(fetch_with(&data, &lock, &mut get).unwrap(), folder);
        assert_eq!(
            urls.borrow().len(),
            before,
            "a verified copy is not downloaded again"
        );
        fs::write(folder.join("include/vk_mem_alloc.h"), b"tampered").unwrap();
        assert!(!verified(&folder, &lock));
        fs::remove_dir_all(&data).unwrap();
    }

    #[test]
    fn a_download_that_differs_is_rejected_and_leaves_nothing_behind() {
        let data = scratch("bad");
        let lock = fake_lock();
        let error = fetch_with(&data, &lock, &mut |_, _| Ok(b"other".to_vec())).unwrap_err();
        assert!(
            error.contains("does not match the pinned version 9.9.9"),
            "{error}"
        );
        assert!(!folder(&data, &lock).exists());
        let leftovers = fs::read_dir(data.join("vma")).unwrap().count();
        assert_eq!(leftovers, 0, "no partial folder is left");
        fs::remove_dir_all(&data).unwrap();
    }

    /// Network: `cargo test vma -- --ignored` checks the pins in assets/vma.json against GitHub (run it when changing them).
    #[test]
    #[ignore]
    fn the_pinned_files_are_what_github_serves() {
        let data = scratch("real");
        let client = crate::source_download::client().unwrap();
        let mut get = |url: &str, limit: u64| {
            let mut bytes = Vec::new();
            client
                .get(url)
                .send()
                .and_then(|r| r.error_for_status())
                .map_err(|e| e.to_string())?
                .take(limit + 1)
                .read_to_end(&mut bytes)
                .map_err(|e| e.to_string())?;
            Ok(bytes)
        };
        let lock = lock();
        let folder = fetch_with(&data, &lock, &mut get).unwrap();
        assert!(verified(&folder, &lock));
        fs::remove_dir_all(&data).unwrap();
    }
}
