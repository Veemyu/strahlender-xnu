//! The Windows build environment: ONE archive with the compiler, SDL, Vulkan, FFmpeg, hactool and the generator that
//! GitHub Actions builds from the newest upstream releases (.github/workflows/windows-buildenv.yml). The installer
//! downloads it instead of asking the user to prepare tools; integrity comes from the SHA-256 in the release metadata.
use serde::Deserialize;
use sha2::{Digest, Sha256};
use std::{
    fs,
    io::{self, Read, Write},
    path::{Component, Path, PathBuf},
};

const RELEASE: &str =
    "https://github.com/Veemyu/strahlender-xnu/releases/download/windows-buildenv";
const ARCHIVE: &str = "windows-buildenv.zip";
const MAX_UNPACKED: u64 = 8 << 30;

#[derive(Debug, Clone, PartialEq, Deserialize)]
pub struct Meta {
    pub schema: u32,
    pub archive: String,
    pub sha256: String,
    pub size_bytes: u64,
    pub created: String,
}

impl Meta {
    fn check(&self) -> Result<(), String> {
        let hex = self.sha256.len() == 64
            && self
                .sha256
                .bytes()
                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b));
        (self.schema == 1
            && self.archive == ARCHIVE
            && hex
            && self.size_bytes > 0
            && self.size_bytes < MAX_UNPACKED)
            .then_some(())
            .ok_or_else(|| "The Windows build environment metadata is invalid.".to_string())
    }
}

pub fn root() -> Result<PathBuf, String> {
    Ok(
        directories::ProjectDirs::from("dev", "Veemyu", "strahlender-xnu-installer")
            .ok_or("Application data unavailable.")?
            .data_dir()
            .join("windows-buildenv"),
    )
}

/// The catalog of the installed environment, if one is installed and complete.
pub fn catalog(root: &Path) -> Option<PathBuf> {
    let current = fs::read_to_string(root.join("current")).ok()?;
    let catalog = root.join(current.trim()).join("catalog.json");
    (current.trim().len() == 16 && catalog.is_file()).then_some(catalog)
}

pub fn installed(root: &Path) -> Option<Meta> {
    let current = fs::read_to_string(root.join("current")).ok()?;
    serde_json::from_slice(&fs::read(root.join(current.trim()).join("windows-buildenv.json")).ok()?)
        .ok()
}

fn hash_file(path: &Path) -> Result<(String, u64), String> {
    let mut file = fs::File::open(path).map_err(|e| e.to_string())?;
    let (mut digest, mut size, mut buffer) = (Sha256::new(), 0, vec![0u8; 1 << 20]);
    loop {
        let n = file.read(&mut buffer).map_err(|e| e.to_string())?;
        if n == 0 {
            return Ok((format!("{:x}", digest.finalize()), size));
        }
        digest.update(&buffer[..n]);
        size += n as u64;
    }
}

/// Verifies the downloaded archive against the metadata and unpacks it next to the others; `current` switches last.
pub fn unpack(archive: &Path, meta: &Meta, root: &Path) -> Result<PathBuf, String> {
    meta.check()?;
    let (hash, size) = hash_file(archive)?;
    if hash != meta.sha256 || size != meta.size_bytes {
        return Err("The Windows build environment download is damaged. Retry.".into());
    }
    let name = &meta.sha256[..16];
    let (partial, target) = (root.join(format!("{name}.partial")), root.join(name));
    let _ = fs::remove_dir_all(&partial);
    fs::create_dir_all(&partial).map_err(|e| e.to_string())?;
    let result = (|| {
        let mut zip = zip::ZipArchive::new(fs::File::open(archive).map_err(|e| e.to_string())?)
            .map_err(|e| e.to_string())?;
        let mut total = 0u64;
        for index in 0..zip.len() {
            let mut entry = zip.by_index(index).map_err(|e| e.to_string())?;
            let relative = entry
                .enclosed_name()
                .ok_or("The archive contains an unsafe path.")?;
            if relative
                .components()
                .any(|c| !matches!(c, Component::Normal(_)))
                || entry.unix_mode().is_some_and(|m| m & 0o170000 == 0o120000)
            {
                return Err("The archive contains an unsafe entry.".to_string());
            }
            let destination = partial.join(&relative);
            if entry.is_dir() {
                fs::create_dir_all(&destination).map_err(|e| e.to_string())?;
                continue;
            }
            total += entry.size();
            if total > MAX_UNPACKED {
                return Err("The archive is larger than expected.".into());
            }
            fs::create_dir_all(destination.parent().unwrap()).map_err(|e| e.to_string())?;
            let mut file = fs::File::create(&destination).map_err(|e| e.to_string())?;
            io::copy(&mut entry, &mut file).map_err(|e| e.to_string())?;
        }
        if !partial.join("catalog.json").is_file() {
            return Err("The archive has no catalog.json.".into());
        }
        fs::write(partial.join("windows-buildenv.json"), serde_json::to_vec(&serde_json::json!({
            "schema": meta.schema, "archive": meta.archive, "sha256": meta.sha256, "size_bytes": meta.size_bytes, "created": meta.created
        })).unwrap()).map_err(|e| e.to_string())?;
        let _ = fs::remove_dir_all(&target);
        fs::rename(&partial, &target).map_err(|e| e.to_string())?;
        let pointer = root.join("current.partial");
        fs::write(&pointer, name)
            .and_then(|_| fs::rename(&pointer, root.join("current")))
            .map_err(|e| e.to_string())
    })();
    if let Err(error) = result {
        let _ = fs::remove_dir_all(&partial);
        return Err(error);
    }
    for entry in fs::read_dir(root).map_err(|e| e.to_string())?.flatten() {
        let old = entry.file_name().to_string_lossy().into_owned();
        if old != name && old != "current" && entry.path().is_dir() {
            let _ = fs::remove_dir_all(entry.path());
        }
    }
    Ok(target.join("catalog.json"))
}

fn client() -> Result<reqwest::blocking::Client, String> {
    reqwest::blocking::Client::builder()
        .user_agent("strahlender-xnu-installer")
        .timeout(std::time::Duration::from_secs(1800))
        .build()
        .map_err(|e| e.to_string())
}

/// Metadata of the newest published environment.
pub fn latest() -> Result<Meta, String> {
    let bytes = client()?
        .get(format!("{RELEASE}/windows-buildenv.json"))
        .send()
        .and_then(|r| r.error_for_status())
        .map_err(|_| "The Windows build environment has not been published yet.".to_string())?
        .bytes()
        .map_err(|e| e.to_string())?;
    let meta: Meta = serde_json::from_slice(&bytes).map_err(|e| e.to_string())?;
    meta.check()?;
    Ok(meta)
}

/// Downloads and installs the newest environment unless it is already installed.
pub fn install_latest(root: &Path) -> Result<PathBuf, String> {
    let meta = latest()?;
    if let (Some(have), Some(catalog)) = (installed(root), catalog(root))
        && have.sha256 == meta.sha256
    {
        return Ok(catalog);
    }
    fs::create_dir_all(root).map_err(|e| e.to_string())?;
    let partial = root.join("download.partial");
    let result = (|| {
        let mut response = client()?
            .get(format!("{RELEASE}/{ARCHIVE}"))
            .send()
            .and_then(|r| r.error_for_status())
            .map_err(|e| e.to_string())?;
        let mut file = fs::File::create(&partial).map_err(|e| e.to_string())?;
        io::copy(&mut response, &mut file).map_err(|e| e.to_string())?;
        file.flush().map_err(|e| e.to_string())?;
        drop(file);
        unpack(&partial, &meta, root)
    })();
    let _ = fs::remove_file(&partial);
    result
}

#[cfg(test)]
mod tests {
    use super::*;

    fn scratch(name: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!("bdsp-buildenv-{name}-{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        dir
    }

    fn archive(dir: &Path, entries: &[(&str, &[u8])]) -> (PathBuf, Meta) {
        let path = dir.join("windows-buildenv.zip");
        let mut zip = zip::ZipWriter::new(fs::File::create(&path).unwrap());
        for (name, data) in entries {
            zip.start_file(*name, zip::write::SimpleFileOptions::default())
                .unwrap();
            zip.write_all(data).unwrap();
        }
        zip.finish().unwrap();
        let (sha256, size_bytes) = hash_file(&path).unwrap();
        (
            path,
            Meta {
                schema: 1,
                archive: ARCHIVE.into(),
                sha256,
                size_bytes,
                created: "2026-10-29T00:00:00Z".into(),
            },
        )
    }

    #[test]
    fn unpacks_a_verified_archive_and_switches_the_current_version_last() {
        let dir = scratch("ok");
        let root = dir.join("root");
        fs::create_dir_all(&root).unwrap();
        let (zip, meta) = archive(
            &dir,
            &[("catalog.json", b"{}"), ("toolchain/bin/clang.exe", b"x")],
        );
        assert!(catalog(&root).is_none());
        let catalog_path = unpack(&zip, &meta, &root).unwrap();
        assert_eq!(catalog(&root), Some(catalog_path.clone()));
        assert!(
            catalog_path
                .parent()
                .unwrap()
                .join("toolchain/bin/clang.exe")
                .is_file()
        );
        assert_eq!(installed(&root), Some(meta.clone()));
        // A second version replaces the first one completely.
        let (zip2, meta2) = archive(&dir, &[("catalog.json", b"{\"v\":2}")]);
        unpack(&zip2, &meta2, &root).unwrap();
        assert_eq!(installed(&root).unwrap().sha256, meta2.sha256);
        assert_eq!(
            fs::read_dir(&root).unwrap().count(),
            2,
            "current plus one version"
        );
        fs::remove_dir_all(&dir).unwrap();
    }

    #[test]
    fn rejects_damaged_unsafe_and_incomplete_archives_without_leaving_files() {
        let dir = scratch("bad");
        let root = dir.join("root");
        fs::create_dir_all(&root).unwrap();
        let (zip, mut meta) = archive(&dir, &[("catalog.json", b"{}")]);
        meta.sha256 = "0".repeat(64);
        assert!(unpack(&zip, &meta, &root).unwrap_err().contains("damaged"));
        let (zip, meta) = archive(&dir, &[("catalog.json", b"{}"), ("../evil", b"x")]);
        assert!(unpack(&zip, &meta, &root).unwrap_err().contains("unsafe"));
        let (zip, meta) = archive(&dir, &[("toolchain/a", b"x")]);
        assert!(unpack(&zip, &meta, &root).unwrap_err().contains("catalog"));
        assert_eq!(fs::read_dir(&root).unwrap().count(), 0);
        assert!(!dir.join("evil").exists());
        let bad = Meta {
            archive: "other.zip".into(),
            ..meta
        };
        assert!(bad.check().is_err());
        fs::remove_dir_all(&dir).unwrap();
    }
}
