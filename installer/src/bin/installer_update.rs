//! Runs outside the bundle being replaced. Never requests administrator privileges.
use std::{
    path::{Path, PathBuf},
    process::Command,
};
fn replace(source: &Path, destination: &Path) -> Result<(), String> {
    let parent = destination.parent().ok_or("Install folder missing.")?;
    let staged = parent.join(format!(".strahlender-update-staged-{}", std::process::id()));
    let backup = parent.join(format!(".strahlender-update-backup-{}", std::process::id()));
    if staged.exists() || backup.exists() {
        return Err("An earlier update needs review before replacement.".into());
    }
    if source.is_dir() {
        if !Command::new("ditto")
            .arg(source)
            .arg(&staged)
            .status()
            .map_err(|e| e.to_string())?
            .success()
        {
            return Err("Could not stage update. The installation may be read-only.".into());
        }
    } else {
        std::fs::copy(source, &staged).map_err(|e| e.to_string())?;
    }
    std::fs::rename(destination, &backup).map_err(|e| e.to_string())?;
    if let Err(error) = std::fs::rename(&staged, destination) {
        let rollback = std::fs::rename(&backup, destination);
        return Err(format!("Update failed: {error}. Rollback: {rollback:?}"));
    }
    let launched = if destination.extension().is_some_and(|s| s == "app") {
        Command::new("open")
            .arg(destination)
            .status()
            .is_ok_and(|s| s.success())
    } else {
        Command::new(destination).spawn().is_ok()
    };
    if !launched {
        let _ = std::fs::rename(destination, &staged);
        std::fs::rename(&backup, destination).map_err(|e| e.to_string())?;
        return Err("Updated installer could not start; previous version restored.".into());
    }
    Ok(())
}
fn main() {
    let args: Vec<_> = std::env::args_os().skip(1).collect();
    if args.len() != 3 {
        eprintln!("Usage: installer_update PID SOURCE DESTINATION");
        std::process::exit(2);
    }
    let Ok(pid) = args[0].to_string_lossy().parse::<i32>() else {
        std::process::exit(2);
    };
    if pid <= 1 {
        std::process::exit(2);
    }
    #[cfg(unix)]
    {
        for _ in 0..600 {
            if unsafe { libc::kill(pid, 0) } != 0 {
                break;
            }
            std::thread::sleep(std::time::Duration::from_millis(100));
        }
        if unsafe { libc::kill(pid, 0) } == 0 {
            eprintln!("Installer is still running; update deferred.");
            std::process::exit(1);
        }
    }
    if let Err(error) = replace(&PathBuf::from(&args[1]), &PathBuf::from(&args[2])) {
        eprintln!("{error}");
        std::process::exit(1);
    }
}

#[cfg(all(test, unix))]
mod tests {
    use super::*;
    use std::os::unix::fs::PermissionsExt;

    fn fixture(name: &str) -> PathBuf {
        let root =
            std::env::temp_dir().join(format!("installer-update-{name}-{}", std::process::id()));
        std::fs::create_dir(&root).unwrap();
        root
    }
    #[test]
    fn failed_launch_restores_the_original() {
        let root = fixture("rollback");
        let old = root.join("installer");
        let new = root.join("download");
        std::fs::write(&old, b"original installer").unwrap();
        std::fs::write(&new, b"not executable").unwrap();
        std::fs::set_permissions(&new, std::fs::Permissions::from_mode(0o600)).unwrap();
        assert!(replace(&new, &old).is_err());
        assert_eq!(std::fs::read(old).unwrap(), b"original installer");
        std::fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn staged_conflict_preserves_current_installation() {
        let root = fixture("conflict");
        let old = root.join("installer");
        let new = root.join("download");
        std::fs::write(&old, b"original installer").unwrap();
        std::fs::write(&new, b"new installer").unwrap();
        std::fs::write(
            root.join(format!(".strahlender-update-backup-{}", std::process::id())),
            b"earlier backup",
        )
        .unwrap();
        assert!(replace(&new, &old).is_err());
        assert_eq!(std::fs::read(old).unwrap(), b"original installer");
        std::fs::remove_dir_all(root).unwrap();
    }
}
