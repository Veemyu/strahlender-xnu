//! Release builds fetch main once per run; a build never changes revision halfway through.
use crate::backend::Event;
use iced::futures::{SinkExt, channel::mpsc::Sender};
use std::{
    path::{Path, PathBuf},
    sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
    },
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

pub struct Prepared {
    pub root: PathBuf,
    pub owner: Option<crate::workspace_cleanup::OwnedWorkspace>,
}

pub fn source_smoke() -> Result<PathBuf, String> {
    fetch(&data_dir()?.join("sources"), &AtomicBool::new(false)).map(|workspace| workspace.root)
}

pub async fn prepare(
    run: u64,
    output: &mut Sender<(u64, Event)>,
    cancelled: Arc<AtomicBool>,
) -> Result<Prepared, String> {
    if cfg!(debug_assertions)
        && std::env::var_os("BDSP_INSTALLER_DEV_CHECKOUT").as_deref()
            == Some(std::ffi::OsStr::new("1"))
    {
        return crate::backend::project_root()
            .map(|root| Prepared { root, owner: None })
            .ok_or_else(|| "Development checkout not found.".into());
    }
    let _ = output.send((run, Event::Log { level: "info".into(), message: "Downloading the current main source. Your build keeps this revision until completion.".into() })).await;
    let worker_cancelled = cancelled.clone();
    let mut task =
        tokio::task::spawn_blocking(move || fetch(&data_dir()?.join("sources"), &worker_cancelled));
    loop {
        tokio::select! {
            result = &mut task => return result.map_err(|error| error.to_string())?,
            _ = tokio::time::sleep(Duration::from_millis(100)) => {
                if cancelled.load(Ordering::Acquire) { return Err("Source download cancelled.".into()); }
            }
        }
    }
}

fn fetch(parent: &Path, cancelled: &AtomicBool) -> Result<Prepared, String> {
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
        let owner = crate::workspace_cleanup::OwnedWorkspace::register(&destination, parent)?;
        Ok(Prepared {
            root: destination,
            owner: Some(owner),
        })
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
