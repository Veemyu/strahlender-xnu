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

pub use crate::source_download::{client, data_dir};

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
        return crate::runtime::project_root()
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
    let root = crate::source_download::download_main(parent, cancelled)?;
    let owner = crate::workspace_cleanup::OwnedWorkspace::register(&root, parent)?;
    Ok(Prepared {
        root,
        owner: Some(owner),
    })
}
