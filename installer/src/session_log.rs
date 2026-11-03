//! The installer's log lines are also written to a file, so a crash or a closed window does not lose them.
use std::{
    fs::{self, OpenOptions},
    io::Write,
    path::{Path, PathBuf},
    sync::OnceLock,
    time::{SystemTime, UNIX_EPOCH},
};

const KEEP: usize = 10;
static FILE: OnceLock<Option<PathBuf>> = OnceLock::new();

pub fn dir() -> Option<PathBuf> {
    crate::appdir::logs_dir()
}

fn start(dir: &Path) -> Option<PathBuf> {
    fs::create_dir_all(dir).ok()?;
    prune(dir, KEEP - 1);
    let seconds = SystemTime::now().duration_since(UNIX_EPOCH).ok()?.as_secs();
    Some(dir.join(format!("installer-{seconds}.log")))
}

fn prune(dir: &Path, keep: usize) {
    let Ok(entries) = fs::read_dir(dir) else {
        return;
    };
    let mut files: Vec<PathBuf> = entries
        .flatten()
        .map(|entry| entry.path())
        .filter(|path| {
            path.file_name()
                .and_then(|name| name.to_str())
                .is_some_and(|name| name.starts_with("installer-") && name.ends_with(".log"))
        })
        .collect();
    files.sort();
    let excess = files.len().saturating_sub(keep);
    for old in files.into_iter().take(excess) {
        let _ = fs::remove_file(old);
    }
}

/// Name of the file this session writes to (created on first use).
pub fn file_name() -> Option<String> {
    let path = FILE
        .get_or_init(|| dir().and_then(|d| start(&d)))
        .as_ref()?;
    Some(path.file_name()?.to_string_lossy().into_owned())
}

pub fn append(line: &str) {
    let Some(path) = FILE.get_or_init(|| dir().and_then(|d| start(&d))) else {
        return;
    };
    if let Ok(mut file) = OpenOptions::new().create(true).append(true).open(path) {
        let _ = writeln!(file, "{line}");
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn only_the_newest_session_logs_are_kept() {
        let dir = std::env::temp_dir().join(format!("bdsp-session-log-{}", std::process::id()));
        fs::create_dir_all(&dir).unwrap();
        for n in 1..=5 {
            fs::write(dir.join(format!("installer-{n}.log")), "x").unwrap();
        }
        fs::write(dir.join("other.txt"), "keep").unwrap();
        prune(&dir, 2);
        let mut left: Vec<String> = fs::read_dir(&dir)
            .unwrap()
            .flatten()
            .map(|e| e.file_name().to_string_lossy().into_owned())
            .collect();
        left.sort();
        assert_eq!(left, ["installer-4.log", "installer-5.log", "other.txt"]);
        let _ = fs::remove_dir_all(&dir);
    }
}
