//! The newest `main` source as a tarball pinned to one commit. Used by builds (workspace.rs) and by the Windows setup,
//! which runs outside any checkout. Shared with the `installer_setup` binary, so it depends on nothing else here.
use std::{
    path::{Path, PathBuf},
    sync::atomic::{AtomicBool, Ordering},
    time::Duration,
};

pub fn data_dir() -> Result<PathBuf, String> {
    directories::ProjectDirs::from("dev", "Veemyu", "strahlender-xnu-installer")
        .map(|dirs| dirs.data_dir().to_path_buf())
        .ok_or_else(|| "Your application data folder could not be located.".into())
}

pub fn client() -> Result<reqwest::blocking::Client, String> {
    reqwest::blocking::Client::builder()
        .user_agent(concat!("Strahlender-Installer/", env!("CARGO_PKG_VERSION")))
        .connect_timeout(Duration::from_secs(20))
        .timeout(Duration::from_secs(300))
        .build()
        .map_err(|error| error.to_string())
}

/// Downloads `main` into a fresh folder below `parent` and returns it.
pub fn download_main(parent: &Path, cancelled: &AtomicBool) -> Result<PathBuf, String> {
    let client = client()?;
    let revision: serde_json::Value = client
        .get("https://api.github.com/repos/Veemyu/strahlender-xnu/commits/main")
        .send()
        .and_then(|r| r.error_for_status())
        .and_then(|r| r.json())
        .map_err(|e| format!("Could not check main. Check your connection and retry: {e}"))?;
    let sha = revision["sha"]
        .as_str()
        .filter(|s| valid_revision(s))
        .ok_or("GitHub returned an invalid source revision.")?;
    if cancelled.load(Ordering::Acquire) {
        return Err("Source download cancelled.".into());
    }
    std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    // Each run owns its work folder; simultaneous installers cannot share generated files.
    let unique = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_err(|e| e.to_string())?
        .as_nanos();
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
        let destination = parent.join(format!("{sha}-{unique}"));
        std::fs::rename(&root, &destination).map_err(|e| e.to_string())?;
        Ok(destination)
    })();
    let _ = std::fs::remove_dir_all(&staging);
    result
}

fn valid_revision(value: &str) -> bool {
    value.len() == 40 && value.bytes().all(|b| b.is_ascii_hexdigit())
}

#[cfg(test)]
mod tests {
    #[test]
    fn validates_remote_revision_before_constructing_paths() {
        assert!(super::valid_revision(&"a".repeat(40)));
        assert!(!super::valid_revision("../../main"));
        assert!(!super::valid_revision(&"z".repeat(40)));
    }
}
