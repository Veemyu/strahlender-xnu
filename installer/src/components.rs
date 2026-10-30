//! The Windows components: ONE archive with the compiler, SDL, Vulkan, FFmpeg, hactool and the generator that
//! GitHub Actions builds from the newest upstream releases (.github/workflows/windows-components.yml). The installer
//! ships it inside the installer (resources/), so the user prepares nothing; integrity comes from the SHA-256 in the
//! metadata that travels with it. Builds without the bundle (development) cannot set the Windows environment up.
use serde::Deserialize;

use std::{
    fs, io,
    path::{Component, Path, PathBuf},
};

const ARCHIVE: &str = "windows-components.zip";
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
            .ok_or_else(|| "The Windows components metadata is invalid.".to_string())
    }
}

pub fn root() -> Result<PathBuf, String> {
    Ok(
        directories::ProjectDirs::from("dev", "Veemyu", "strahlender-xnu-installer")
            .ok_or("Application data unavailable.")?
            .data_dir()
            .join("windows-components"),
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
    serde_json::from_slice(
        &fs::read(root.join(current.trim()).join("windows-components.json")).ok()?,
    )
    .ok()
}

fn hash_file(path: &Path) -> Result<(String, u64), String> {
    let hash = bdsp_extract::manifest::file_sha256(path).map_err(|e| e.to_string())?;
    Ok((hash, fs::metadata(path).map_err(|e| e.to_string())?.len()))
}

/// Verifies the downloaded tools archive against the metadata, unpacks it, lets `assemble(tools, out)` build the full
/// environment next to the others; `current` switches last.
pub fn unpack(
    archive: &Path,
    meta: &Meta,
    root: &Path,
    assemble: impl FnOnce(&Path, &Path) -> Result<(), String>,
) -> Result<PathBuf, String> {
    meta.check()?;
    let (hash, size) = hash_file(archive)?;
    if hash != meta.sha256 || size != meta.size_bytes {
        return Err("The Windows components download is damaged. Retry.".into());
    }
    let name = &meta.sha256[..16];
    let (partial, target) = (root.join(format!("{name}.partial")), root.join(name));
    let tools = root.join(format!("{name}.tools.partial"));
    let _ = fs::remove_dir_all(&partial);
    let _ = fs::remove_dir_all(&tools);
    fs::create_dir_all(&tools).map_err(|e| e.to_string())?;
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
            let destination = tools.join(&relative);
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
        assemble(&tools, &partial)?;
        if !partial.join("catalog.json").is_file() {
            return Err("The Windows setup produced no catalog.json.".into());
        }
        fs::write(partial.join("windows-components.json"), serde_json::to_vec(&serde_json::json!({
            "schema": meta.schema, "archive": meta.archive, "sha256": meta.sha256, "size_bytes": meta.size_bytes, "created": meta.created
        })).unwrap()).map_err(|e| e.to_string())?;
        let _ = fs::remove_dir_all(&tools);
        let _ = fs::remove_dir_all(&target);
        fs::rename(&partial, &target).map_err(|e| e.to_string())?;
        let pointer = root.join("current.partial");
        fs::write(&pointer, name)
            .and_then(|_| fs::rename(&pointer, root.join("current")))
            .map_err(|e| e.to_string())
    })();
    if let Err(error) = result {
        let _ = fs::remove_dir_all(&partial);
        let _ = fs::remove_dir_all(&tools);
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

/// The folder whose scripts run the setup: a checkout beside the installer (development), otherwise the newest `main`
/// source, like every build uses. A packaged installer carries no scripts of its own.
fn setup_source(
    beside: Option<PathBuf>,
    download: impl FnOnce() -> Result<PathBuf, String>,
) -> Result<PathBuf, String> {
    match beside {
        Some(root) => Ok(root),
        None => download(),
    }
}

/// Runs scripts/install/windows_setup.py in the private Python: Qt, FFmpeg and SDL3 come from their publishers.
fn run_setup(tools: &Path, out: &Path) -> Result<(), String> {
    let (python, _) =
        crate::runtime::backend_python().ok_or("The bundled Python runtime is missing.")?;
    let project = setup_source(crate::runtime::project_root(), || {
        let parent = crate::source_download::data_dir()?.join("sources");
        crate::source_download::download_main(&parent, &std::sync::atomic::AtomicBool::new(false))
    })?;
    let output = std::process::Command::new(python)
        .current_dir(&project)
        .env(
            "BDSP_EXTRACT",
            std::env::current_exe().map_err(|e| e.to_string())?,
        )
        .env("BDSP_EXTRACT_PREFIX", "--cli")
        .args(["-B", "-m", "scripts.install.windows_setup", "--tools"])
        .arg(tools)
        .arg("--out")
        .arg(out)
        .output()
        .map_err(|e| e.to_string())?;
    if output.status.success() {
        return Ok(());
    }
    let text = String::from_utf8_lossy(&output.stderr);
    Err(text
        .lines()
        .last()
        .unwrap_or("The Windows setup failed.")
        .to_string())
}

/// The tools archive shipped inside the installer (resources/ beside the executable), with its metadata.
pub fn bundled() -> Option<(PathBuf, Meta)> {
    let resources = std::env::current_exe().ok()?.parent()?.join("resources");
    let meta: Meta =
        serde_json::from_slice(&fs::read(resources.join("windows-components.json")).ok()?).ok()?;
    meta.check().ok()?;
    let archive = resources.join(ARCHIVE);
    archive.is_file().then_some((archive, meta))
}

/// Sets up the environment from the tools that ship with the installer, then fetches Qt, FFmpeg and SDL3 from their
/// publishers (windows_setup.py), unless this version is already installed.
pub fn install_latest(root: &Path) -> Result<PathBuf, String> {
    let (archive, meta) =
        bundled().ok_or("This installer build does not include the Windows tools.")?;
    if let (Some(have), Some(catalog)) = (installed(root), catalog(root))
        && have.sha256 == meta.sha256
    {
        return Ok(catalog);
    }
    fs::create_dir_all(root).map_err(|e| e.to_string())?;
    unpack(&archive, &meta, root, run_setup)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn setup_uses_a_checkout_beside_the_installer_else_downloads_main() {
        let beside = Some(PathBuf::from("checkout"));
        let used = setup_source(beside, || Err("must not download".into()));
        assert_eq!(used, Ok(PathBuf::from("checkout")));
        let downloaded = setup_source(None, || Ok(PathBuf::from("main-source")));
        assert_eq!(downloaded, Ok(PathBuf::from("main-source")));
        assert!(setup_source(None, || Err("offline".into())).is_err());
    }
    use std::io::Write;

    fn scratch(name: &str) -> PathBuf {
        let dir =
            std::env::temp_dir().join(format!("bdsp-components-{name}-{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        dir
    }

    fn archive(dir: &Path, entries: &[(&str, &[u8])]) -> (PathBuf, Meta) {
        let path = dir.join("windows-components.zip");
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

    /// Stand-in for windows_setup.py: copies the tools into the environment and registers a catalog.
    fn assemble(tools: &Path, out: &Path) -> Result<(), String> {
        fs::create_dir_all(out.join("hactool")).map_err(|e| e.to_string())?;
        fs::copy(
            tools.join("hactool/hactool.exe"),
            out.join("hactool/hactool.exe"),
        )
        .map_err(|e| e.to_string())?;
        fs::write(out.join("catalog.json"), b"{}").map_err(|e| e.to_string())
    }

    #[test]
    fn unpacks_a_verified_archive_and_switches_the_current_version_last() {
        let dir = scratch("ok");
        let root = dir.join("root");
        fs::create_dir_all(&root).unwrap();
        let (zip, meta) = archive(&dir, &[("hactool/hactool.exe", b"x")]);
        assert!(catalog(&root).is_none());
        let catalog_path = unpack(&zip, &meta, &root, assemble).unwrap();
        assert_eq!(catalog(&root), Some(catalog_path.clone()));
        assert!(
            catalog_path
                .parent()
                .unwrap()
                .join("hactool/hactool.exe")
                .is_file()
        );
        assert_eq!(installed(&root), Some(meta.clone()));
        // A second version replaces the first one completely.
        let (zip2, meta2) = archive(&dir, &[("hactool/hactool.exe", b"2")]);
        unpack(&zip2, &meta2, &root, assemble).unwrap();
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
        let (zip, mut meta) = archive(&dir, &[("hactool/hactool.exe", b"x")]);
        meta.sha256 = "0".repeat(64);
        assert!(
            unpack(&zip, &meta, &root, assemble)
                .unwrap_err()
                .contains("damaged")
        );
        let (zip, meta) = archive(&dir, &[("hactool/hactool.exe", b"x"), ("../evil", b"x")]);
        assert!(
            unpack(&zip, &meta, &root, assemble)
                .unwrap_err()
                .contains("unsafe")
        );
        let (zip, meta) = archive(&dir, &[("toolchain/a", b"x")]);
        assert!(
            unpack(&zip, &meta, &root, |_, _| Ok(()))
                .unwrap_err()
                .contains("catalog")
        );
        let (zip, meta) = archive(&dir, &[("hactool/hactool.exe", b"y")]);
        assert!(
            unpack(&zip, &meta, &root, |_, _| Err("setup failed".into()))
                .unwrap_err()
                .contains("setup failed")
        );
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
